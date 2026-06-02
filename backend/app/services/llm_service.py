"""LLM service using OpenAI API for classification and response generation."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from pydantic import ValidationError

from app.models.schemas import ClassificationResult
from app.services.mcp_client import TOOL_DEFINITIONS, call_mcp_tool, parse_wlo_cards, resolve_discipline_labels
from app.services.pattern_engine import select_pattern
from app.services.config_loader import (
    load_persona_prompt, load_domain_rules, load_base_persona, load_guardrails,
    load_intents, load_states, load_entities, load_signal_modulations,
    load_device_config, load_persona_definitions, load_pattern_definitions,
    get_state_directive,
)
from app.services.llm_provider import get_client, get_chat_model, build_chat_kwargs

import logging as _log
_logger = _log.getLogger(__name__)

client = get_client()
MODEL = get_chat_model()


def _strip_trailing_option_lines(text: str, quick_replies: list[str]) -> str:
    """Sicherheitsnetz: Entfernt Quick-Reply-/„Bring mich hin"-Optionszeilen,
    die das Modell gelegentlich ZUSÄTZLICH ans Ende des Antworttexts schreibt.

    Diese Optionen gehören ausschließlich ins strukturierte ``quick_replies``-
    Feld (das Frontend rendert sie als Pillen/Buttons UNTER der Antwort) — nicht
    als fetter Text in die Chat-Blase. Es werden nur Zeilen am ENDE entfernt,
    die (nach Abzug von Markdown-Deko) exakt einem Quick-Reply entsprechen oder
    eine „Bring mich hin"-Guide-Zeile sind. Inhaltliche Sätze bleiben unberührt.
    """
    if not text:
        return text

    def _norm(s: str) -> str:
        s = s.strip().lstrip("-–—•*_ \t").rstrip("*_ \t")
        return s.rstrip(":：").strip().lower()

    qr_norm = {_norm(q) for q in (quick_replies or []) if q and q.strip()}
    lines = text.split("\n")
    while lines:
        raw = lines[-1].strip()
        if not raw:
            lines.pop()
            continue
        n = _norm(raw)
        if n and (n in qr_norm or n.startswith("bring mich hin")):
            lines.pop()
            continue
        break
    return "\n".join(lines).rstrip()


# ── Reasoning / "Thinking"-Filter ─────────────────────────────────────
# Manche Modelle schreiben ihren Denk-/Reasoning-Block INLINE in den
# sichtbaren Antworttext. Empirisch (Scan 2026-06-01 gegen b-api.staging)
# macht das im AcademicCloud-Katalog NUR ``deepseek-r1-distill-llama-70b``
# (kompletter ``<think>…</think>``-Block in ``message.content``). ALLE
# anderen Modelle — inkl. des Defaults ``mistral-large-3``, gemma-3,
# glm-4.7, gpt-oss-120b und die qwen3.5/3.6-Familie — legen Reasoning in
# ein SEPARATES Feld (``reasoning``/``reasoning_content``), das der
# Antwort-Pfad nie liest. Für diese ist der Filter ein No-op. Er ist die
# Versicherung, damit ein Wechsel von ``LLM_CHAT_MODEL`` auf ein
# Thinking-Modell die Gedankenkette NICHT zum Nutzer durchlässt.
_THINK_BLOCK_RE = re.compile(
    r"<(think|thinking|reasoning)\b[^>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE
)
# Offener Think-Tag ohne Schließen (Modell lief mid-reasoning ins Token-Limit
# → finish_reason=length): alles ab dem Tag verwerfen.
_THINK_OPEN_TAIL_RE = re.compile(
    r"<(think|thinking|reasoning)\b[^>]*>.*\Z", re.DOTALL | re.IGNORECASE
)
# Unicode-Variante (manche R1-Distills): ◁think▷ … ◁/think▷
_THINK_UNI_BLOCK_RE = re.compile(r"◁think▷.*?◁/think▷", re.DOTALL)
_THINK_UNI_TAIL_RE = re.compile(r"◁think▷.*\Z", re.DOTALL)
# gpt-oss-„harmony"-Kanalmarker — auf unserer Strecke nie geleakt, aber
# billig zu neutralisieren, falls ein künftiges Modell sie doch durchreicht.
_HARMONY_MARKERS = (
    "<|channel|>", "<|message|>", "<|start|>", "<|end|>",
    "<|im_start|>", "<|im_end|>", "assistantfinal",
)


def strip_reasoning_markers(text: str) -> str:
    """Entfernt Chain-of-Thought, die ins SICHTBARE ``content`` geleakt ist.

    Reihenfolge:
      1. geschlossene ``<think>…</think>`` / ``<thinking>`` / ``<reasoning>``
         Blöcke (deepseek-r1-distill u.a.),
      2. ein UNGESCHLOSSENER ``<think>…``-Rest (Token-Limit mitten im Denken),
      3. die Unicode-Variante ``◁think▷…◁/think▷``,
      4. gpt-oss-„harmony"-Kanalmarker (defensiv).

    Reasoning im SEPARATEN ``reasoning``/``reasoning_content``-Feld wird NICHT
    angefasst — der Antwort-Pfad liest nur ``message.content``, die Felder
    erreichen den Nutzer also ohnehin nie. Für Modelle, die nichts davon
    emittieren (mistral-large-3, gemma-3, glm-4.7, gpt-oss-120b, qwen3.5/3.6 …),
    liefert die Fast-Path-Prüfung den Text unverändert zurück.
    """
    if not text:
        return text
    # Fast path: nichts „thinking"-artiges vorhanden → unverändert.
    if "<" not in text and "◁" not in text and "assistantfinal" not in text:
        return text
    out = _THINK_BLOCK_RE.sub("", text)
    out = _THINK_OPEN_TAIL_RE.sub("", out)
    out = _THINK_UNI_BLOCK_RE.sub("", out)
    out = _THINK_UNI_TAIL_RE.sub("", out)
    for marker in _HARMONY_MARKERS:
        out = out.replace(marker, "")
    return out.strip()


class _ThinkSafeStreamer:
    """Live-Streaming-Schutz: hält ``<think>…</think>`` aus dem Token-Stream —
    nicht erst aus dem finalen Text.

    Pro Chunk wird der sichtbare Text aus der GESAMTEN Akkumulation via
    ``strip_reasoning_markers`` neu abgeleitet (Single Source of Truth, robust
    gegen über Chunk-Grenzen zerschnittene Tags). Weitergereicht wird nur der
    STABILE Präfix — alles bis auf einen Sicherheits-Tail von ``_HOLDBACK``
    Zeichen, der noch der ANFANG eines Markers sein könnte (z.B. ``<thi`` bevor
    ``<think>`` komplett ist). ``flush()`` gibt am Stream-Ende den Rest frei.

    Saubere Modelle (mistral-large-3, gpt-5.4-mini …) streamen praktisch 1:1 —
    nur die letzten ~16 Zeichen erscheinen gebündelt am Schluss. Ein
    Thinking-Modell (z.B. deepseek-r1) leakt seinen Denk-Block NIE: weder ein
    Teil-Tag noch der Inhalt wird je gesendet.
    """
    _HOLDBACK = 16  # ≥ längster Marker ("assistantfinal"=14, "<reasoning"=10)

    def __init__(self, on_token: Any):
        self._on = on_token
        self._acc = ""
        self._emitted = 0  # bereits gesendete Zeichen des sichtbaren Texts

    def _emit(self, visible: str, target_len: int) -> None:
        end = min(target_len, len(visible))
        if self._on is None or end <= self._emitted:
            return
        # Stabiler Präfix: strip betrifft nur den Suffix, wo neue Tags entstehen,
        # daher ist visible[:self._emitted] über Aufrufe hinweg konstant.
        piece = visible[self._emitted:end]
        if not piece:
            return
        try:
            self._on(piece)
        except Exception:
            pass
        self._emitted = end

    def __call__(self, chunk: str) -> None:
        if chunk:
            self._acc += chunk
        if self._on is None:
            return
        visible = strip_reasoning_markers(self._acc)
        self._emit(visible, len(visible) - self._HOLDBACK)

    def flush(self) -> None:
        if self._on is None:
            return
        visible = strip_reasoning_markers(self._acc)
        self._emit(visible, len(visible))


def _make_think_safe_on_token(on_token: Any) -> "_ThinkSafeStreamer":
    """Factory für den Live-Streaming-Thinking-Filter (siehe _ThinkSafeStreamer)."""
    return _ThinkSafeStreamer(on_token)


# ── State-Conversation-Flow helpers (Welle C Sprint 6) ────────────────
# Pattern wählt WAS antworten + welche Tools — State sagt in welcher
# Verlaufs-Phase die Antwort einzahlt. Diese Helper laden die
# Phase-Direktive aus 04-states/states.yaml und fallen leise zurück,
# wenn ein State-id unbekannt ist (z.B. veraltete Session-Daten nach
# S3-Löschung).
def _get_state_meta_safe(state_id: str) -> dict[str, Any]:
    try:
        return get_state_directive(state_id) or {}
    except Exception as exc:  # noqa: BLE001
        _logger.warning("state-directive lookup failed for %s: %s", state_id, exc)
        return {}


# ── Dynamic classification tool (built from config files) ────

def _build_classify_tool() -> dict[str, Any]:
    """Build the classify_input tool definition from config files."""
    # Load persona IDs from persona files
    persona_defs = load_persona_definitions()
    if persona_defs:
        persona_ids = [p["id"] for p in persona_defs]
    else:
        device_cfg = load_device_config()
        persona_ids = list(device_cfg.get("persona_formality", {}).keys()) or [
            "P-LEH", "P-LER", "P-ENT", "P-RED", "P-RED",
            "P-ENT", "P-ENT", "P-ELT", "P-AND",
        ]

    # Load intents
    intents = load_intents()
    intent_ids = [i["id"] for i in intents] or [
        "I01", "I01", "I03",
        "I07", "I08", "I02", "I02",
        "I02", "I04",
    ]

    # Load states. Fallback list mirrors the live states.yaml after Welle C
    # Sprint 6 — S3 (Redaktions-Recherche) was removed (redundant to
    # persona P-RED, not a distinct conversation phase).
    states = load_states()
    state_ids = [s["id"] for s in states] or [
        "S1", "S2", "S3", "S3", "S3",
        "S3", "S3", "S3", "S3", "S3", "S3",
    ]

    # Load entities
    entities = load_entities()
    entity_props = {}
    for e in entities:
        entity_props[e["id"]] = {"type": "string"}
    if not entity_props:
        entity_props = {
            "fach": {"type": "string"}, "stufe": {"type": "string"},
            "thema": {"type": "string"}, "medientyp": {"type": "string"},
            "lizenz": {"type": "string"},
        }

    # Load patterns — for the optional pattern_id_hint field. Phase-1 Shadow-
    # Mode: LLM proposes a pattern but the deterministic Pattern-Engine still
    # decides. We log how often the two agree so we can later promote the
    # hint to a Tie-Breaker.
    patterns = load_pattern_definitions()
    pattern_ids = [p.get("id") for p in patterns if p.get("id")] or ["M04"]

    # Welle E (2026-05-23): Distinct MCP-Tools aus allen Pattern-Frontmattern
    # sammeln. Dient als Enum für den optionalen ``tool_id_hint``-Slot, mit
    # dem der Klassifikator dem Spec-Prefetch sagt "ruf bevorzugt dieses Tool".
    tool_hint_ids: list[str] = []
    for p in patterns:
        for tool in (p.get("tools") or []):
            if tool and tool not in tool_hint_ids:
                tool_hint_ids.append(tool)
    if not tool_hint_ids:
        tool_hint_ids = [
            "search_wlo_topic_pages",
            "search_wlo_collections",
            "search_wlo_content",
        ]

    return {
        "type": "function",
        "function": {
            "name": "classify_input",
            "description": "Classify the user message into the 7 input dimensions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "persona_id": {
                        "type": "string",
                        "enum": persona_ids,
                        "description": "Detected user persona",
                    },
                    "persona_confidence": {
                        "type": "number",
                        "description": (
                            "Confidence of persona classification (0.0-1.0). "
                            "Use <0.6 when the message COULD plausibly come from "
                            "multiple personas (e.g. 'Materialien zu X' fits "
                            "Lehrkraft, Schüler, Eltern). Use ≥0.8 only with "
                            "explicit self-identification or unambiguous signals."
                        ),
                    },
                    "intent_id": {
                        "type": "string",
                        "enum": intent_ids,
                        "description": "Classified intent",
                    },
                    "intent_confidence": {
                        "type": "number",
                        "description": "Confidence of intent classification (0.0-1.0)",
                    },
                    "signals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Detected behavioral signals",
                    },
                    "entities": {
                        "type": "object",
                        "properties": entity_props,
                    },
                    "turn_type": {
                        "type": "string",
                        "enum": ["initial", "follow_up", "clarification", "correction", "topic_switch"],
                    },
                    "next_state": {
                        "type": "string",
                        "enum": state_ids,
                    },
                    # NEW (Phase 1, Shadow-Mode): optional Pattern-Hint.
                    # Pattern-Engine entscheidet weiterhin authoritativ — wir
                    # loggen nur, wie oft LLM und Engine übereinstimmen.
                    "pattern_id_hint": {
                        "type": "string",
                        "enum": pattern_ids,
                        "description": (
                            "Optional: Welches Pattern passt holistisch zur User-"
                            "Anfrage? Wähle aus der Pattern-Liste das, das du "
                            "intuitiv als beste Reaktion siehst — UNABHÄNGIG von "
                            "deiner persona/intent-Wahl. Reine Mess-Telemetrie; "
                            "die Pattern-Engine entscheidet final via Gates+Score. "
                            "Lass leer wenn unsicher."
                        ),
                    },
                    "pattern_reasoning": {
                        "type": "string",
                        "description": (
                            "1-2 Sätze: Warum dieses Pattern? Welche 1 Alternative "
                            "kam noch in Frage und warum verworfen?"
                        ),
                    },
                    # Welle E (2026-05-23) — MCP-Tool-Hint für Speculative
                    # Prefetch. Erlaubt sind nur Tools die in irgendeinem
                    # Pattern als ``tools:`` deklariert sind (siehe
                    # ``tool_hint_ids`` oben). Backend prüft zusätzlich,
                    # dass der Tool-Hint mit den ``tools`` des final gewählten
                    # Pattern kompatibel ist — sonst fällt es auf Heuristik
                    # zurück.
                    "tool_id_hint": {
                        "type": "string",
                        "enum": tool_hint_ids,
                        "description": (
                            "Optional: Welches MCP-Tool soll als erstes "
                            "spekulativ aufgerufen werden um den Treffer-"
                            "Cache zu wärmen? Wähle z.B. search_wlo_topic_pages "
                            "wenn der User nach einer Themenseite fragt, "
                            "search_wlo_content bei Medientyp-Filter "
                            "(\"nur Videos\"), search_wlo_collections bei "
                            "Sammlungs-Anfragen. Lass leer wenn keine Suche "
                            "(z.B. reines Q&A) oder unklar."
                        ),
                    },
                    "tool_reasoning": {
                        "type": "string",
                        "description": (
                            "1 Satz: Warum dieses Tool als Primary? Wird im "
                            "Quality-Log gespeichert zur Auswertung."
                        ),
                    },
                },
                "required": ["persona_id", "persona_confidence", "intent_id",
                              "intent_confidence", "signals",
                              "entities", "turn_type", "next_state"],
            },
        },
    }


# ──────────────────────────────────────────────────────────────────────
# Klassifikator-Prompt — YAML-driven Renderer (Welle E, 2026-05-25)
#
# Vorher: ~3500 Tokens hardcoded Persona-/Intent-/Entity-Regeln im
# Python-String (Zeilen 422–727 alt). Studio konnte davon nichts
# editieren — Redaktion sah nur ID+Label+Description.
#
# Jetzt: Alle Regeln stehen in den YAML/MD-Dateien (intents.yaml,
# 04-personas/*.md, entities.yaml, states.yaml). Die Renderer hier
# bauen daraus die Prompt-Blöcke. Was im Code bleibt:
#   - Generische Scaffold-Sätze ("Erkenne sowohl explizit als auch
#     implizit", "Prüfe Trigger gegen Negativ-Trigger", …) — die
#     gelten unabhängig von konkreten Intent-/Persona-IDs.
#   - Format-Hinweise (Reihenfolge der Sektionen, Tool-Aufruf).
#   - Dynamic-Block (state, entities, persona, turn, page, canvas).
# ──────────────────────────────────────────────────────────────────────

# Max-Limits pro Renderer — verhindern, dass eine versehentlich groß
# editierte YAML-Datei den Prompt explodieren lässt. Werte sind weit
# genug für realistische Konfigurationen, aber begrenzen Worst-Case-
# Token-Costs sichtbar.
_MAX_HINTS_PER_PERSONA = 40
_MAX_ANTI_HINTS_PER_PERSONA = 20
_MAX_DISCRIMINATORS_PER_DIM = 8
_MAX_TRIGGER_VERBS = 20
_MAX_NEGATIVE_TRIGGERS = 8
_MAX_POSITIVE_EXAMPLES = 8
_MAX_NEGATIVE_EXAMPLES = 12
_MAX_EXAMPLES_PER_INTENT = 6


def _render_personas_block(persona_defs: list[dict]) -> str:
    """Render the Personas section of the classifier prompt from
    persona MD definitions.

    Output structure per persona:
        ### P-XXX — Label
        Beschreibung (Ziele).
        Positiv-Marker: "phrase 1", "phrase 2", ...
        Anti-Marker (NICHT diese Persona): "phrase A", ...
        Diskriminatoren:
          - Bullet 1
          - Bullet 2

    The generic instruction block (how to use these markers, when
    self-ID trumps everything, etc.) is emitted ONCE at the top of the
    section — not duplicated per persona.
    """
    if not persona_defs:
        return "\n(keine Personas konfiguriert — defaulte zu P-AND.)\n"

    head = (
        "PERSONA-REGELN (gelten für alle Personas, Daten unten):\n"
        "- Erkenne Personas SOWOHL durch EXPLIZITE Selbst-Aussagen "
        "(\"Ich bin Lehrer:in / Politikerin / Journalist\") als auch durch "
        "IMPLIZITE Sprach-Marker (Positiv-Marker-Liste pro Persona).\n"
        "\n"
        "**HARTE OVERRIDE-Regel: Explizite Selbst-ID dominiert IMMER.**\n"
        "Sobald der User sagt \"Ich bin X\" / \"als X\" / \"ich bin "
        "X:in\" / \"als X:in\" (z.B. \"ich bin Schüler:in\", \"als Lehrkraft\", "
        "\"ich bin Mutter\"), ist die Persona = X. Diese Self-ID übersteuert\n"
        "JEDE konkurrierende Topic-Wahl im gleichen Satz, auch wenn der Rest\n"
        "nach einer anderen Persona klingt.\n"
        "Beispiel: \"Ich bin Schüler:in und lerne für meine Klausur. Hilf mir\n"
        "einen Lernpfad für meine Unterrichtseinheit zu bauen.\" → "
        "**P-LER** (NICHT P-LEH, obwohl \"Unterrichtseinheit\" P-LEH-Marker ist).\n"
        "Bei Self-ID: turn_type=\"correction\" UND persona_confidence>=0.9.\n"
        "\n"
        "- Anti-Marker (False-Positive-Schutz) NIE als Positiv-Treffer "
        "verwenden — sie sagen, was eine Persona NICHT eindeutig macht.\n"
        "- Intent ≠ Persona: ein Anfrage-Thema (z.B. \"Statistiken\", "
        "\"Bildungspolitik\") bestimmt nicht die Persona — Persona kommt "
        "aus Sprachstil + Selbst-ID + Kontext.\n"
        "- Mehrere starke Positiv-Marker EINER Persona schlagen einzelne "
        "konkurrierende Marker einer anderen — Beispiel: 2× P-LER-Marker "
        "(\"kapiere nicht\" + \"Schritt für Schritt\") überstimmt eine vage "
        "Frage zu \"Feedback geben\" → bleib bei P-LER.\n"
        "- Im Zweifel P-AND, nicht eine spezifische Persona raten — aber "
        "MIND. 2 Positiv-Marker derselben Persona = nicht mehr Zweifelsfall.\n"
    )

    parts: list[str] = [head, ""]
    for p in persona_defs:
        pid = p.get("id", "")
        if not pid:
            continue
        block: list[str] = [f"### {pid} — {p.get('label', '')}"]
        if p.get("description"):
            block.append(p["description"])

        # Welle E v2 (2026-05-25): bevorzugt ``positive_markers`` (neuer Name),
        # fallback ``hints`` (alter Alias).
        pos = (p.get("positive_markers") or p.get("hints") or [])[
            :_MAX_HINTS_PER_PERSONA
        ]
        if pos:
            block.append(
                "Positiv-Marker: " + ", ".join(f'"{h}"' for h in pos)
            )

        # ``anti_markers`` ist list[{phrase, redirect_to?, rationale?}];
        # ``anti_hints`` (legacy list[str]) als Fallback.
        anti_raw = p.get("anti_markers") or p.get("anti_hints") or []
        anti_lines: list[str] = []
        for item in anti_raw[:_MAX_ANTI_HINTS_PER_PERSONA]:
            if isinstance(item, dict):
                phrase = str(item.get("phrase") or "").strip()
                if not phrase:
                    continue
                rt = str(item.get("redirect_to") or "").strip()
                anti_lines.append(f'"{phrase}"' + (f" → {rt}" if rt else ""))
            elif isinstance(item, str) and item.strip():
                anti_lines.append(f'"{item.strip()}"')
        if anti_lines:
            block.append(
                "Anti-Marker (NICHT diese Persona): "
                + ", ".join(anti_lines)
            )

        # Discriminators: jetzt list[{vs, rule, example_a?, example_b?}]
        # statt list[str]. Render kompakt als "vs. P-XYZ: rule".
        disc_raw = p.get("discriminators") or []
        disc_lines: list[str] = []
        for d in disc_raw[:_MAX_DISCRIMINATORS_PER_DIM]:
            if isinstance(d, dict) and d.get("vs"):
                vs = str(d["vs"]).strip()
                rule = str(d.get("rule") or "").strip()
                disc_lines.append(f"vs. {vs}: {rule}" if rule else f"vs. {vs}")
            elif isinstance(d, str) and d.strip():
                disc_lines.append(d.strip())
        if disc_lines:
            block.append("Diskriminatoren:")
            block.extend(f"  - {line}" for line in disc_lines)

        parts.append("\n".join(block))
    return "\n\n".join(parts) + "\n"


def _render_intents_block(intent_defs: list[dict]) -> str:
    """Render the Intents section from intents.yaml.

    Output structure per intent:
        ### I05 — Inhalt-Generieren
        Beschreibung.
        Trigger-Verben: "erstelle", "generiere", ...
        Negativ-Trigger:
          - "phrase" → I03 (rationale)
          - "phrase" → I06 (wenn canvas_state.mode == "material")
        Diskriminatoren:
          - vs. I04: rule
            "Beispiel A" → I05; "Beispiel B" → I04
        Beispiele: ...

    Generic instruction block (Negativ-Trigger schlagen Positiv-Trigger,
    create-Verb hat Vorrang vor such-Verb, etc.) wird ONCE oben emittiert.
    """
    if not intent_defs:
        return "\n(keine Intents konfiguriert)\n"

    intent_summary = ", ".join(
        f"{i.get('id', '?')} ({i.get('label', '')})" for i in intent_defs
    )

    head = (
        f"Intent-Übersicht: {intent_summary}\n\n"
        "INTENT-REGELN (gelten für alle Intents, Daten unten):\n"
        "- Trigger-Verben sind starke Pro-Signale, ABER Negativ-Trigger "
        "schlagen Positiv-Trigger. Prüfe zuerst die Negativ-Trigger.\n"
        "- Wenn ein Negativ-Trigger matcht, route zu `redirect_to` und "
        "wähle DEN Intent statt diesem.\n"
        "- Diskriminatoren beantworten Cross-Intent-Verwechslungen — "
        "konsultiere sie immer bei mehreren plausiblen Intents.\n"
        "- Bei Edit-Verben (kürzer/ausführlicher/ergänze/…) und aktivem "
        "Canvas-Inhalt: IMMER der Edit-Intent (I06), egal welche Material-"
        "Typ-Wörter im Satz stehen.\n"
        "- Im Zweifel: konservativ klassifizieren, lieber turn_type "
        "\"clarification\" als ein falscher Intent.\n"
    )

    parts: list[str] = [head, ""]
    for i in intent_defs:
        iid = i.get("id", "")
        if not iid:
            continue
        block: list[str] = [f"### {iid} — {i.get('label', '')}"]
        if i.get("description"):
            block.append(str(i["description"]).strip())

        triggers = (i.get("trigger_verbs") or [])[:_MAX_TRIGGER_VERBS]
        if triggers:
            block.append(
                "Trigger-Verben: " + ", ".join(f'"{t}"' for t in triggers)
            )

        neg = (i.get("negative_triggers") or [])[:_MAX_NEGATIVE_TRIGGERS]
        if neg:
            block.append("Negativ-Trigger:")
            for n in neg:
                if not isinstance(n, dict):
                    continue
                phrase = n.get("phrase", "").strip()
                target = n.get("redirect_to", "").strip()
                rationale = n.get("rationale", "").strip()
                when = n.get("when", "").strip()
                line = f'  - "{phrase}" → {target}' if target else f'  - "{phrase}"'
                if when:
                    line += f" (wenn {when})"
                if rationale:
                    line += f" — {rationale}"
                block.append(line)

        disc = (i.get("discriminators") or [])[:_MAX_DISCRIMINATORS_PER_DIM]
        if disc:
            block.append("Diskriminatoren:")
            for d in disc:
                if not isinstance(d, dict):
                    continue
                vs = d.get("vs", "").strip()
                rule = d.get("rule", "").strip()
                ex_a = d.get("example_a", "").strip()
                ex_b = d.get("example_b", "").strip()
                if vs and rule:
                    block.append(f"  - vs. {vs}: {rule}")
                if ex_a:
                    block.append(f"      Bsp: {ex_a}")
                if ex_b:
                    block.append(f"      Bsp: {ex_b}")

        examples = (i.get("examples") or [])[:_MAX_EXAMPLES_PER_INTENT]
        if examples:
            block.append("Beispiele:")
            block.extend(f'  - "{e}"' for e in examples)

        parts.append("\n".join(block))
    return "\n\n".join(parts) + "\n"


def _render_states_block(state_defs: list[dict]) -> str:
    """Render the States section from states.yaml.

    Output per state:
        - S1 (Orientierung): description
          Wahl-Kriterien:
            - bullet 1
            - bullet 2
    """
    if not state_defs:
        return "\n(keine States konfiguriert)\n"

    head = (
        "STATE-REGELN (Conversation-Phase wählen):\n"
        "- Wähle den State, der den AKTUELLEN Turn beschreibt — nicht "
        "den letzten oder erwarteten.\n"
        "- Wahl-Kriterien pro State unten beachten.\n"
        "- Default-Übergang: Slot komplett → S3, Slot fehlt → S2, "
        "kein konkretes Anliegen → S1.\n"
    )

    parts: list[str] = [head, ""]
    for s in state_defs:
        sid = s.get("id", "")
        if not sid:
            continue
        block: list[str] = [f"- {sid} ({s.get('label', '')})"]
        desc = (s.get("description") or "").strip()
        if desc:
            block.append(f"  {desc}")
        criteria = s.get("selection_criteria") or []
        if criteria:
            block.append("  Wahl-Kriterien:")
            block.extend(f"    - {c}" for c in criteria)
        parts.append("\n".join(block))
    return "\n".join(parts) + "\n"


def _render_entities_block(entity_defs: list[dict]) -> str:
    """Render the Entities section from entities.yaml.

    Output per entity:
        - id: description
          Positiv-Beispiele:
            - "Satz" → value
          Negativ-Beispiele (Slot bleibt leer):
            - "Satz" — rationale
          Diskriminator vs. other: rule
    """
    if not entity_defs:
        return "\n(keine Entities konfiguriert)\n"

    head = (
        "ENTITY-REGELN (Slot-Extraction):\n"
        "- Slots IMMER LEER lassen, wenn der erwartete Wert nicht "
        "eigenständig im Satz steht. Lieber leer als Substring-Klau.\n"
        "- Diskriminatoren unten zeigen Cross-Slot-Fallstricke "
        "(z.B. fach vs thema).\n"
        "- Positiv-Beispiele zeigen erwartete Werte; "
        "Negativ-Beispiele zeigen, wann der Slot LEER bleiben muss.\n"
    )

    parts: list[str] = [head, ""]
    for e in entity_defs:
        eid = e.get("id", "")
        if not eid:
            continue
        desc = (e.get("description") or e.get("label") or "").strip().replace("\n", " ")
        block: list[str] = [f"- {eid}: {desc}"]

        pos = (e.get("positive_examples") or [])[:_MAX_POSITIVE_EXAMPLES]
        if pos:
            block.append("  Positiv-Beispiele:")
            for ex in pos:
                if not isinstance(ex, dict):
                    continue
                t = ex.get("text", "").strip()
                v = ex.get("value", "").strip()
                if t and v:
                    block.append(f'    - "{t}" → {v}')

        neg = (e.get("negative_examples") or [])[:_MAX_NEGATIVE_EXAMPLES]
        if neg:
            block.append("  Negativ-Beispiele (Slot bleibt leer):")
            for ex in neg:
                if not isinstance(ex, dict):
                    continue
                t = ex.get("text", "").strip()
                r = ex.get("rationale", "").strip()
                if t:
                    block.append(f'    - "{t}" — {r}' if r else f'    - "{t}"')

        disc = (e.get("discriminators") or [])[:_MAX_DISCRIMINATORS_PER_DIM]
        if disc:
            for d in disc:
                if not isinstance(d, dict):
                    continue
                vs = d.get("vs", "").strip()
                rule = d.get("rule", "").strip()
                if vs and rule:
                    block.append(f"  Diskriminator vs. {vs}: {rule}")

        parts.append("\n".join(block))
    return "\n".join(parts) + "\n"


def _render_patterns_hint_block(pattern_defs: list[dict]) -> str:
    """Render the Patterns hint section.

    Welle E v4 (2026-05-25): Der ``pattern_id_hint`` ist primärer
    Pattern-Selektor (nicht mehr Tie-Breaker). Wir listen Patterns
    kompakt mit ID + Label + 1-Liner-Purpose — Gate-Spalten sind
    raus, weil der Hint-Pfad keine Gates mehr kennt.
    """
    if not pattern_defs:
        return (
            "\nPattern-Hint: (keine Patterns geladen — Hint-Feld leer "
            "lassen)\n"
        )

    head = (
        "PATTERN-HINT (PRIMÄR — wählt das Antwort-Muster):\n"
        "- Wähle das Pattern, das die beste Reaktion für die Anfrage "
        "darstellt. Dein Hint ist die Pattern-Wahl, nicht nur Telemetrie.\n"
        "- Routing-Rules können in eindeutigen Edge-Cases übersteuern "
        "(z. B. I05 ohne Thema → M03 Slot-Klärung).\n"
        "- Lass das Feld nur leer, wenn keine Pattern-Beschreibung "
        "wirklich passt — dann greift M15 (Orientierung) als Fallback.\n"
        "- `pattern_reasoning`: 1–2 Sätze, warum dieses Pattern und "
        "welche 1 Alternative noch in Frage kam.\n"
    )

    # Welle E v4+7 (2026-05-26): Pattern-Hint-Block jetzt RICHTIG strukturiert
    # — pro Pattern rendern wir:
    #   - id + label + short_purpose (1 Zeile)
    #   - when_to_use (positive Trigger, 3-5 Items)
    #   - when_not_to_use (negative Trigger, 3-5 Items)
    #   - trigger_phrases (konkrete User-Beispiele, 3-5 Items)
    #   - discriminators (vs M-Other: Regel + Beispiel)
    # Diese 4 strukturierten Felder ersetzen die zentrale pattern_disambig-
    # uators-Sektion aus classify-overrides.yaml (Single-Source-of-Truth in
    # den Pattern-MDs selbst).
    lines: list[str] = []
    for p in pattern_defs:
        pid = p.get("id")
        if not pid:
            continue
        label = p.get("label", "")
        purpose = (p.get("short_purpose") or "").strip().replace("\n", " ")
        if not purpose:
            purpose = (p.get("core_rule") or "").strip().replace("\n", " ")
            if len(purpose) > 100:
                purpose = purpose[:97] + "…"
        lines.append(f"\n### {pid} — {label}")
        if purpose:
            lines.append(f"_Zweck:_ {purpose}")

        wtu = p.get("when_to_use") or []
        if wtu:
            lines.append("**Einsetzen wenn:**")
            for it in wtu[:5]:
                lines.append(f"  - {it}")

        wntu = p.get("when_not_to_use") or []
        if wntu:
            lines.append("**NICHT einsetzen wenn:**")
            for it in wntu[:5]:
                lines.append(f"  - {it}")

        trigs = p.get("trigger_phrases") or []
        if trigs:
            lines.append(
                "**Typische User-Phrasen:** "
                + " · ".join(f"„{t}"+'"' for t in trigs[:5])
            )

        discs = p.get("discriminators") or []
        if discs:
            lines.append("**Tie-Breaks:**")
            for d in discs[:5]:
                vs = d.get("vs", "")
                rule = d.get("rule", "")
                ex = d.get("example", "")
                line = f"  - vs **{vs}**: {rule}"
                if ex:
                    line += f" _Beispiel:_ {ex}"
                lines.append(line)

    return head + "\n" + "\n".join(lines) + "\n"


def _render_signals_block() -> str:
    """Render the Signals section grouped by dimension (Tonalität,
    Verhalten, …). Reads 04-signals/signal-modulations.yaml directly
    because the public load function only returns modulations, not
    the dimension grouping.
    """
    from app.services.config_loader import _load_yaml
    sig_data = _load_yaml("04-signals/signal-modulations.yaml")
    sig_defs = sig_data.get("signals", {})
    if not sig_defs:
        return "\n(keine Signale konfiguriert)\n"
    by_dim: dict[str, list[str]] = {}
    for sig_id, cfg in sig_defs.items():
        dim = cfg.get("dimension", "Unbekannt") if isinstance(cfg, dict) else "Unbekannt"
        by_dim.setdefault(dim, []).append(sig_id)
    return "\n".join(
        f"{dim}: {', '.join(sigs)}" for dim, sigs in by_dim.items()
    ) + "\n"


def _render_canvas_block(canvas_state: dict | None) -> str:
    """Render the Canvas-context block (only when canvas mode != empty).

    Welle E (2026-05): Canvas pane wurde aus dem Frontend entfernt, aber
    der Klassifikator nutzt den Canvas-Kontext weiter, um Edit-Anfragen
    (I06) sicher zu erkennen, wenn der vorherige Bot-Turn ein InlineDoc
    rendered hat. Daher bleibt der Renderer.
    """
    if not (canvas_state and canvas_state.get("mode")
            and canvas_state.get("mode") != "empty"):
        return ""
    c_title = (canvas_state.get("title") or "").strip()
    c_type = (canvas_state.get("material_type") or "").strip()
    c_mode = canvas_state.get("mode", "")
    c_md = (canvas_state.get("markdown") or "")[:800]
    c_cards = canvas_state.get("cards_count") or 0
    out = ["\n\n## Canvas-Kontext (was der Nutzer gerade sieht)",
           f"Modus: {c_mode}"]
    if c_title:
        out.append(f"Titel: {c_title}")
    if c_type:
        out.append(f"Material-Typ: {c_type}")
    if c_mode == "cards":
        out.append(f"Kachel-Anzahl: {c_cards}")
    if c_md:
        out.append(f"Auszug aus dem Canvas-Dokument:\n{c_md}")
    out.append(
        "\nKRITISCH — Intent-Auswahl bei aktivem Canvas:\n"
        "- Wenn die Nutzernachricht sich auf den Canvas-Inhalt bezieht "
        "(\"hier\", \"das\", \"der Text\", \"die Aufgabe\", \"der Titel\") "
        "ODER Edit-Verben nutzt — IMMER intent_id=\"I06\", "
        "turn_type=\"follow_up\".\n"
        "- I05 (NEU erstellen) ist NUR richtig bei explizitem neuem "
        "Material zu einem ANDEREN Thema (\"Mach mir stattdessen ein "
        "Quiz zu X\").\n"
        "- Meta-Fragen zum Canvas-Inhalt (\"Was bedeutet hier X?\") sind "
        "turn_type=\"clarification\"."
    )
    return "\n".join(out)


def _build_classify_system_prompt(
    session_state: dict,
    environment: dict,
    canvas_state: dict | None = None,
) -> str:
    """Build the classification system prompt from config files.

    Welle E (2026-05-25): Alle Persona-/Intent-/Entity-/State-Regeln
    leben in den YAML/MD-Konfigurationsdateien. Diese Funktion
    assembliert sie zu einem System-Prompt — das ist alles, was hier
    noch hardcoded ist:

      1. Fester Header (Aufgabe + Eingangsdimensionen).
      2. Generische Scaffold-Sätze pro Sektion (Renderer liefern sie).
      3. Daten-Blöcke pro Dimension (Renderer aus YAML-Werten gebaut).
      4. Dynamic-Block (state, entities, persona, turn, page, canvas).

    Das LEGACY-Layout (DYNAMIC zuerst) bleibt hinter ``CLASSIFY_PROMPT_
    LEGACY_ORDER=1`` erhalten als Rollback-Switch.
    """
    intents = load_intents()
    states = load_states()
    entities = load_entities()
    persona_defs = load_persona_definitions()
    patterns_for_prompt = load_pattern_definitions()

    # Static blocks — alle aus YAML/MD geladen, durch Renderer formatiert.
    personas_block = _render_personas_block(persona_defs)
    intents_block = _render_intents_block(intents)
    signals_block = _render_signals_block()
    states_block = _render_states_block(states)
    entities_block = _render_entities_block(entities)
    patterns_block = _render_patterns_hint_block(patterns_for_prompt)

    # Persona-/Canvas-Snippets im Dynamic-Block
    persona_prompt = ""
    if session_state.get("persona_id"):
        persona_prompt = f"\nAktuelle Persona: {session_state['persona_id']}"

    canvas_prompt = _render_canvas_block(canvas_state)

    # Semantic page-context block (populated if the widget is embedded on a
    # theme page and page_context_service resolved its metadata).
    try:
        from app.services import page_context_service
        _page_meta = page_context_service.get_cached(session_state)
        _page_block = page_context_service.render_for_prompt(
            _page_meta, environment.get("page_context"),
        )
        # Fallback: when MCP resolution found nothing (off-platform host
        # page) but the widget's DOM-detector extracted visible text,
        # render that as a heuristic context block.
        if not _page_block:
            _page_block = page_context_service.render_raw_for_prompt(
                environment.get("page_context"),
            )
    except Exception:
        _page_block = ""

    # Also keep the raw page_context as a compact one-liner for debug /
    # fallback (the semantic block is the primary signal).
    _raw_pc = {
        k: v for k, v in (environment.get("page_context") or {}).items()
        if k in ("node_id", "collection_id", "search_query",
                 "topic_page_slug", "subject_slug", "page_kind",
                 "page_type", "widget", "detection_source")
    }

    # Cache-Maximierung: dynamische Felder (state, entities, persona,
    # turn count, page, canvas, page_block) stehen am ENDE des System-
    # Prompts. So bleibt der lange statische Prefix (Personas, Intents,
    # States, Entities, Patterns) zwischen Turns identisch → OpenAI
    # Prompt-Cache greift auf 5000+ Tokens.
    _dynamic_block = (
        f"\n## Aktueller Turn-Kontext\n"
        f"State: {session_state.get('state_id', 'S1')}\n"
        f"Bekannte Entities: {json.dumps(session_state.get('entities', {}))}"
        f"{persona_prompt}\n"
        f"Turn: {session_state.get('turn_count', 0) + 1}\n"
        f"Seite: {environment.get('page', '/')}\n"
        f"Seitenkontext (Rohdaten): {json.dumps(_raw_pc)}\n"
        f"Device: {environment.get('device', 'desktop')}"
        f"{canvas_prompt}\n"
        f"{_page_block}"
    ).rstrip()

    # Statischer Prefix — alle Daten kommen aus YAML/MD, die Renderer
    # liefern Generisches + Daten. Tool-Aufruf-Hinweis am Ende.
    _static_block = (
        "\n## Personas (WICHTIG: Genau zuordnen!)\n"
        + personas_block
        + "\n## Intents\n"
        + intents_block
        + "\n## Signale\n"
        + signals_block
        + "\n## States\n"
        + states_block
        + "\n## Entities\n"
        + entities_block
        + "\n## Patterns (Hint-Feld, optional)\n"
        + patterns_block
        + "\nRufe classify_input auf mit den erkannten Werten."
    )

    header = (
        "Du bist der Klassifikations-Modul des WLO-Chatbots.\n"
        "Analysiere die Nutzernachricht und klassifiziere sie in die "
        "Input-Dimensionen Persona, Intent, Signale, State, Entities. "
        "Optional: Pattern-Hint + Tool-Hint.\n"
    )

    # Welle E v4+6 (2026-05-26): Hard-Overrides + Pattern-Disambiguatoren
    # + Few-Shot-Examples werden aus YAML (01-base/classify-overrides.yaml)
    # geladen. Vorher inline hartkodiert — jetzt Studio-bearbeitbar via den
    # YAML-Editor im RoutingRulesView/Display-Rules-Tab.
    from app.services.config_loader import load_classify_overrides_config
    co = load_classify_overrides_config()
    override_block = _render_classify_overrides_block(co)
    pattern_disambig_block = _render_pattern_disambiguators_block(
        co.get("pattern_disambiguators") or []
    )
    fewshot_block = _render_fewshot_block(
        co.get("few_shot_examples") or []
    )

    return (
        header
        + _static_block
        + override_block
        + pattern_disambig_block
        + fewshot_block
        + _dynamic_block
    )


def _render_classify_overrides_block(co: dict) -> str:
    """Render Persona-/Intent-/Topic-Hard-Overrides aus classify-
    overrides.yaml.

    Welle E v4+6: ersetzt den hartkodierten override_block. Wenn die YAML
    fehlt/leer ist, kommt ein leerer String raus — Klassifizier fällt
    dann auf Persona-Markdown + Intent-YAML zurück.
    """
    if not co:
        return ""
    out = ["\n## HARD-OVERRIDE-REGELN (überschreiben Persona/Intent-Defaults im Zweifel)\n"]

    pers = co.get("persona_overrides") or []
    if pers:
        out.append("\n### Persona-Override\n")
        for rule in pers:
            persona = rule.get("persona", "")
            trig = rule.get("triggers") or []
            ex_role = rule.get("except_explicit_role") or []
            req_all = rule.get("requires_all") or []
            req_any = rule.get("requires_any") or []
            label_parts = []
            if trig:
                label_parts.append(
                    "Tokens {"
                    + ", ".join(f'"{t}"' for t in trig[:12])
                    + "}"
                )
            if req_all:
                label_parts.append(
                    "+ alle von ["
                    + ", ".join(req_all)
                    + "]"
                )
            if req_any:
                label_parts.append(
                    "+ eines von ["
                    + ", ".join(req_any)
                    + "]"
                )
            head = " ".join(label_parts) or "(keine Trigger)"
            line = f"- {head} → Persona = {persona}"
            if ex_role:
                line += (
                    ", AUSSER explizite Selbst-ID: "
                    + ", ".join(f'„{r}"' for r in ex_role)
                )
            out.append(line + ".\n")

    ints = co.get("intent_overrides") or []
    if isinstance(ints, list) and ints:
        out.append("\n### Intent-Override (Verb-Disambiguation)\n")
        for rule in ints:
            intent = rule.get("intent", "")
            desc = rule.get("description", "")
            trig = rule.get("triggers") or []
            if trig:
                out.append(
                    f"- {desc} → Intent = {intent}. Trigger: "
                    + ", ".join(f"`{t}`" for t in trig[:14])
                    + ".\n"
                )

    # Konflikt-Regel auf Top-Level (aus classify-overrides.yaml)
    conf_rule = (co.get("intent_conflict_rule") or "").strip()
    if conf_rule:
        out.append("\n**Konflikt-Regel:** " + conf_rule + "\n")

    topic = co.get("topic_overrides") or {}
    if topic:
        out.append("\n### Topic-Slot-Override\n")
        phantom = topic.get("phantom_topic_phrases") or {}
        if phantom.get("phrases"):
            out.append(
                "- Phantom-Topic-Phrasen "
                + ", ".join(f'„{p}"' for p in phantom["phrases"][:8])
                + " → extrahiere `topic` als LEERES Feld (führt zu M03-Slot-Klärung).\n"
            )
        fach_fb = topic.get("fach_as_topic_fallback") or {}
        if fach_fb.get("triggers"):
            out.append(
                "- Wenn der User NUR ein Fach nennt ("
                + ", ".join(fach_fb["triggers"][:8])
                + ", ...) ohne konkreteres Thema → extrahiere `fach`=Fach UND `topic`=Fach.\n"
            )

    return "".join(out)


def _render_pattern_disambiguators_block(disambs: list) -> str:
    """Render Pattern-Konflikt-Regeln aus classify-overrides.yaml."""
    if not disambs:
        return ""
    out = ["\n## PATTERN-KONFLIKTE (deterministische Tie-Breaks)\n"]
    for d in disambs:
        label = d.get("label") or d.get("id", "")
        out.append(f"\n**{label}**\n")
        for r in (d.get("rules") or []):
            out.append(f"- {r}\n")
        for ex in (d.get("examples") or []):
            inp = ex.get("input", "")
            expected = ex.get("expected", "")
            rationale = ex.get("rationale", "")
            line = f"- Beispiel: „{inp}" + "\" → " + expected
            if rationale:
                line += f" ({rationale})"
            out.append(line + "\n")
    return "".join(out)


def _render_fewshot_block(examples: list) -> str:
    """Render Few-Shot-Examples aus classify-overrides.yaml."""
    if not examples:
        return ""
    out = [
        "\n## FEW-SHOT-BEISPIELE (User → erwartetes Pattern)\n",
        "Diese Beispiele sind verbindlich — bei ähnlichen Inputs nimm dasselbe Pattern.\n\n",
    ]
    for i, ex in enumerate(examples, 1):
        inp = ex.get("input", "")
        intent = ex.get("intent", "")
        pat = ex.get("pattern", "")
        note = ex.get("note", "")
        line = f"{i}. „{inp}" + f"\" → {intent}, {pat}"
        if note:
            line += f" ({note})"
        out.append(line + "\n")
    return "".join(out)


def _formality_guidance(formality: str, persona_id: str) -> str:
    """Concrete, persona-aware writing guidance for the LLM.

    The LLM historically treats ``Formality: Sie`` as a soft hint and slips
    into casual "hey, schön dass du da bist" even for journalists and civil
    servants. This helper expands the terse token into explicit examples
    and NEVER-lists, which the LLM follows much more reliably.

    2026-05-25 (eval-c4c0): Vocabulary erweitert — die Pattern-Engine
    liefert das Token aus drei Quellen mit unterschiedlichen Schreibweisen:
      - Persona-MD-Frontmatter:  "siezen" / "duzen" / "neutral" / "wie_user"
      - device-config.yaml:      "Sie" / "du" / "neutral" (Großschreibung!)
      - Tone-Modifier override:  "siezen" / "duzen"
    Vorher matched der Helper nur ``sie/formal/foermlich`` und ``du/informal/duzen``
    → "siezen" und "Sie" fielen durch zum Neutral-Block → Bot bekam keine
    explizite Anrede-Anweisung → duzte trotz P-ENT/P-RED/P-LEH/P-ELT.
    """
    f = (formality or "").strip().lower()
    # Formal personas: strict Sie + professional register
    # Akzeptiert: "sie" (device-config), "siezen" (Persona-MD), formal/foermlich (Alt-Synonyme)
    if f in ("sie", "siezen", "formal", "foermlich"):
        # Extra strictness for personas whose scores were worst in the eval.
        # 2026-05-25 (eval-c4c0): Liste war doppelt + P-ELT fehlte — aufgeräumt.
        strict = persona_id in ("P-ENT", "P-RED", "P-LEH", "P-ELT")
        # Welle E v4++++ (2026-05-26, eval-bce3): Anrede-Priorität verschärft.
        # eval-bce3 zeigte M13/M11/M03 mit P-ENT/P-LEH duzten trotz siezen-
        # Modifier, weil die Pattern-Body-Beispiele oft "du" enthalten und
        # der LLM diese mimt. Wir ergänzen einen expliziten Override-Hinweis:
        # die Anrede aus dem Modifier hat IMMER Priorität gegenüber
        # Pattern-Body-Beispielen.
        base = (
            "Schreibe ausschließlich in der Sie-Form (\"Ich kann Ihnen ...\", "
            "\"Haben Sie ...\", \"Möchten Sie ...\"). KEINE Du-Formen.\n"
            "\n"
            "**WICHTIG -- diese Sie-Anrede überschreibt alle Pattern-Body-\n"
            "Beispiele.** Falls das Pattern-Schema (z.B. M03/M13/M14) "
            "Du-Form-Beispiele enthält (\"Danke, du möchtest ...\", "
            "\"Du kannst ...\"), übersetze sie automatisch in die Sie-Form "
            "(\"Vielen Dank -- Sie möchten ...\", \"Sie können ...\"). "
            "Die Modifier-Anrede ist verbindlich."
        )
        if strict:
            extra_leh = ""
            if persona_id == "P-LEH":
                # Welle E v4+11 (2026-05-26, eval-f6f56): P-LEH driftete in
                # M15/M11/M13 trotz formality=siezen — Pattern-Body-Beispiele
                # mit „dir/du" wurden vom LLM mimt. Extra-strikte Anweisung
                # für die schwächste Persona aus den letzten 4 Eval-Runs.
                extra_leh = (
                    "\n"
                    "P-LEH SPEZIAL — Lehrkräfte-Register zwingend:\n"
                    "- Begrüßung IMMER: \"Schön, dass Sie da sind\" (NIE \"Schön, dass du da bist\")\n"
                    "- Begleitung IMMER: \"ich begleite Sie\" / \"ich unterstütze Sie\"\n"
                    "  (NIE \"ich begleite dich\" / \"ich helfe dir\")\n"
                    "- Material-Anbieten IMMER: \"ich kann Ihnen ... raussuchen\" /\n"
                    "  \"ich erstelle Ihnen\" (NIE \"ich kann dir\" / \"ich erstell dir\")\n"
                    "- Übergabe IMMER: \"Hier ist Ihr Material\" / \"Ich habe Ihnen ein\n"
                    "  Quiz erstellt\" (NIE \"Hier ist dein Material\")\n"
                    "- Edit-Bestätigung IMMER: \"Ich habe den Text gekürzt\" / \"für Ihre\n"
                    "  Unterrichtseinheit gekürzt\" (NIE \"habe ich für dich gekürzt\")\n"
                    "- Anwendungs-Hinweis IMMER: \"Sie können das Material direkt in\n"
                    "  Ihrer Unterrichtseinheit verwenden\" (NIE \"du kannst es nutzen\")\n"
                )
            return (
                f"{base}\n"
                "\n"
                "KRITISCH — Register professionell halten:\n"
                "- KEINE Grußfloskeln wie \"Hey\", \"Oh\", \"Ah\", \"Hi\", \"Klar doch\"\n"
                "- KEINE Füllwörter wie \"echt\", \"voll\", \"cool\", \"ok\", \"einfach mal\",\n"
                "  \"so'n bisschen\", \"ne\", \"mal schauen\", \"check ich\"\n"
                "- KEINE Ich-du-Komplizenschaft (\"wir zwei\", \"du weißt ja\")\n"
                "- KEINE Laden-/Regal-Metaphern: NICHT \"im Regal\", \"aus dem Regal\",\n"
                "  \"Regal schauen\", \"geholt\", \"gezogen\", \"gegriffen\", \"gestöbert\",\n"
                "  \"hier ist was\" — bei Fach-Personas sachlich benennen:\n"
                "  \"Ich habe folgende Materialien gefunden\", \"Zu Ihrem Thema liegen\n"
                "  vor:\", \"Die Suche ergibt:\"\n"
                "- Sachlich-präzise Formulierungen, keine Umgangssprache\n"
                "- Fachbegriffe (OER, Lizenz, Bildungsstufe) unkommentiert verwenden — "
                "die Persona kennt sie\n"
                "- Satz-Enden mit konkreter Info oder Frage, keine Emoji/Smileys"
                + extra_leh
            )
        return base
    # Informal personas: du but still respectful
    # ``lower()`` oben fängt schon "Du" → "du" ab; Liste deckt die drei
    # konfig-Vokabulare ab (device-config, Persona-MD, Alt-Synonym).
    if f in ("du", "duzen", "informal"):
        # P-LER wants explicitly jugendlich-friendly tone; eval showed it was
        # getting over-formal responses.
        if persona_id == "P-LER":
            return (
                "Schreibe in der Du-Form, einfach und freundlich. Kurze Sätze, "
                "keine Fachchinesisch-Häufung.\n"
                "- Beispiele: \"Ich kann dir helfen …\", \"Hast du schon probiert …\", "
                "\"Willst du, dass ich …\"\n"
                "- Locker, aber nicht albern. Keine gespielte Jugendsprache ('cringe', "
                "'lit'). Einfach natürlich.\n"
                "- KEINE Siezen-Formulierungen — der Nutzer ist Schüler:in."
            )
        return (
            "Schreibe in der Du-Form (\"Ich kann dir …\", \"Hast du …\", "
            "\"Willst du …\"). KEINE Sie-Formen.\n"
            "Freundlich-persönlich, aber keine übertriebene Umgangssprache."
        )
    # Neutral (P-AND etc.)
    return (
        "Persona nicht klar — bleibe neutral. Vermeide explizite Anrede ("
        "\"Ich kann helfen …\" statt \"Ich kann Ihnen/dir helfen …\") bis die "
        "Persona klar ist. Freundlich und offen, aber nicht übermäßig casual."
    )


_SYSTEM_PROMPT_TOKEN_HISTOGRAM: dict[str, int] = {}  # phase → max prompt tokens seen


def _approx_token_count(text: str) -> int:
    """Cheap token estimate via tiktoken (cl100k_base for the gpt-5/gpt-4
    family). Falls back to a 4-char heuristic if tiktoken is unavailable.

    A2.4 — Used to log system-prompt size at INFO level so we can verify
    the OpenAI prompt cache (which kicks in at ≥1024 prompt tokens) is
    actually addressable. If our system prompt is <1024 tokens we'd never
    benefit from prompt caching no matter how stable it is.
    """
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # 4 chars/token is the OpenAI rule of thumb for English/German.
        return max(1, len(text) // 4)


def _log_system_prompt_size(phase: str, system_prompt: str) -> None:
    """Log the system prompt token count once per significant change.

    Tracks per-phase max so we don't spam logs for every turn. If a phase's
    system prompt suddenly grew/shrunk by >5%, log a new entry — that's
    usually the moment a config change altered prompt-cache behavior.
    """
    tokens = _approx_token_count(system_prompt)
    prev = _SYSTEM_PROMPT_TOKEN_HISTOGRAM.get(phase, 0)
    if prev == 0 or abs(tokens - prev) > max(20, prev * 0.05):
        _logger.info(
            "system_prompt[%s] tokens=%d (was=%d, cache-eligible=%s)",
            phase, tokens, prev, tokens >= 1024,
        )
        _SYSTEM_PROMPT_TOKEN_HISTOGRAM[phase] = tokens


def _extract_usage(resp: Any) -> dict[str, Any]:
    """Extract token-usage details from an OpenAI ChatCompletion response.

    Returns a flat dict {prompt, completion, cached, model} where ``cached``
    is taken from ``prompt_tokens_details.cached_tokens`` (OpenAI prompt
    cache, requires identical prefix >1024 tokens). Defaults to 0 on miss.
    """
    try:
        u = getattr(resp, "usage", None)
        if not u:
            return {"prompt": 0, "completion": 0, "cached": 0, "model": getattr(resp, "model", "")}
        cached = 0
        details = getattr(u, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        return {
            "prompt": getattr(u, "prompt_tokens", 0) or 0,
            "completion": getattr(u, "completion_tokens", 0) or 0,
            "cached": cached,
            "model": getattr(resp, "model", "") or "",
        }
    except Exception:
        return {"prompt": 0, "completion": 0, "cached": 0, "model": ""}


def usage_accumulator_new() -> dict[str, Any]:
    """Empty accumulator: one per chat turn, threaded through LLM-calling
    helpers so callers can pass it in and we sum up Token-Costs centrally.

    ``per_phase`` (A2.1) splits the same totals by call-site label so we can
    diagnose where the OpenAI prompt cache breaks. Phases used today:
      classify, tool_loop, response, reflection, quick_replies, learning_path,
      canvas_create, canvas_edit, canvas_remix
    """
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "calls": 0,
        "models": {},
        "per_phase": {},
    }


def usage_accumulator_add(
    acc: dict[str, Any],
    usage: dict[str, Any],
    phase: str | None = None,
) -> None:
    """Add one extracted usage-record into the per-turn accumulator.

    ``phase`` is the call-site label (e.g. ``"classify"`` / ``"response"`` /
    ``"quick_replies"``). When provided, the same numbers are also folded
    into ``acc["per_phase"][phase]`` so we can break down where the cache
    is actually hitting and where prompts are too small / too variable.
    """
    if not acc or not usage:
        return
    p = int(usage.get("prompt", 0) or 0)
    c = int(usage.get("completion", 0) or 0)
    cached = int(usage.get("cached", 0) or 0)
    acc["prompt_tokens"] += p
    acc["completion_tokens"] += c
    acc["cached_tokens"] += cached
    acc["calls"] += 1
    model = usage.get("model") or "unknown"
    m = acc["models"].setdefault(model, {"prompt": 0, "completion": 0, "cached": 0, "calls": 0})
    m["prompt"] += p
    m["completion"] += c
    m["cached"] += cached
    m["calls"] += 1
    if phase:
        ph = acc.setdefault("per_phase", {}).setdefault(
            phase, {"prompt": 0, "completion": 0, "cached": 0, "calls": 0},
        )
        ph["prompt"] += p
        ph["completion"] += c
        ph["cached"] += cached
        ph["calls"] += 1


class _StreamedMessage:
    """Lightweight stand-in for ``ChatCompletionMessage`` produced by
    streaming. Has the attributes ``content``, ``tool_calls`` (each with
    ``id``, ``function.name``, ``function.arguments``), and ``role``.

    The non-streaming code path consumes ``resp.choices[0].message`` via
    these attributes; this class provides them so the existing tool-loop
    body can run unchanged regardless of streaming on/off.
    """
    def __init__(self) -> None:
        self.role: str = "assistant"
        self.content: str | None = None
        self.tool_calls: list[Any] | None = None


class _StreamedToolCall:
    """Stand-in for an OpenAI ``ChoiceDeltaToolCall``-rolled-up object."""
    def __init__(self, tc_id: str = "", name: str = "", arguments: str = "") -> None:
        self.id = tc_id
        self.type = "function"
        self.function = type("Fn", (), {"name": name, "arguments": arguments})()


class _StreamedChoice:
    def __init__(self) -> None:
        self.message = _StreamedMessage()
        self.finish_reason: str | None = None


class _StreamedResponse:
    """Stand-in for ``ChatCompletion`` reconstructed from a streamed call."""
    def __init__(self) -> None:
        self.choices: list[_StreamedChoice] = [_StreamedChoice()]
        self.usage: Any = None
        self.model: str = ""


class _RespondToUserExtractor:
    """Progressive parser for the ``respond_to_user`` tool's JSON args.

    The tool schema is ``{text: str, quick_replies: list[str]}``, and the
    LLM emits the ``text`` field FIRST (we declared it first). As argument
    chunks stream in, we incrementally extract characters of the ``text``
    string and forward them to ``on_token`` — so the user sees the answer
    fill in token-by-token, exactly as if the model had emitted plain
    content.

    We do NOT try to parse the closing ``quick_replies`` array
    incrementally — those land in one shot at the end (and the caller can
    json.loads the full args string post-stream).

    State machine: scan for ``"text":`` then ``"`` (skipping whitespace);
    forward characters until an unescaped ``"``; ignore everything after.
    """
    def __init__(self, on_token: Any) -> None:
        self._buf = ""
        self._on_token = on_token
        self._scan_pos = 0       # next char index to inspect
        self._mode = "search"    # search | text | done
        self._escape_next = False

    def feed(self, chunk: str) -> None:
        if not chunk or self._mode == "done":
            self._buf += chunk or ""
            return
        self._buf += chunk
        # ── Phase 1: search for "text" key opening quote ──
        if self._mode == "search":
            # Find ``"text"`` followed by optional whitespace + ``:`` + ws + ``"``
            idx = self._buf.find('"text"', self._scan_pos)
            if idx < 0:
                # not yet present — wait for more chunks
                self._scan_pos = max(0, len(self._buf) - 8)  # keep last few chars in case "text" straddles boundary
                return
            cur = idx + len('"text"')
            # Skip whitespace + ``:`` + whitespace
            while cur < len(self._buf) and self._buf[cur] in " \t\n":
                cur += 1
            if cur >= len(self._buf):
                return  # need more
            if self._buf[cur] != ":":
                # Malformed — ``"text"`` not as a key. Skip past and keep searching.
                self._scan_pos = cur
                return
            cur += 1
            while cur < len(self._buf) and self._buf[cur] in " \t\n":
                cur += 1
            if cur >= len(self._buf):
                return  # need more
            if self._buf[cur] != '"':
                # The text value isn't a string (could be null) — give up streaming.
                self._mode = "done"
                return
            # Found opening quote of the text value
            self._scan_pos = cur + 1
            self._mode = "text"

        # ── Phase 2: stream characters until unescaped ``"`` ──
        if self._mode == "text":
            buf_len = len(self._buf)
            out: list[str] = []
            i = self._scan_pos
            while i < buf_len:
                ch = self._buf[i]
                if self._escape_next:
                    # Translate JSON escape to actual char
                    out.append({
                        '"': '"', '\\': '\\', '/': '/',
                        'n': '\n', 't': '\t', 'r': '\r',
                        'b': '\b', 'f': '\f',
                    }.get(ch, ch))
                    self._escape_next = False
                    i += 1
                    continue
                if ch == '\\':
                    self._escape_next = True
                    i += 1
                    continue
                if ch == '"':
                    # Closing quote — text field complete
                    self._scan_pos = i + 1
                    self._mode = "done"
                    break
                out.append(ch)
                i += 1
            else:
                # Loop exhausted without break — partial text, more coming
                self._scan_pos = i
            if out:
                try:
                    self._on_token("".join(out))
                except Exception:
                    pass

    @property
    def buffer(self) -> str:
        return self._buf


async def _stream_completion(
    on_token: Any,
    **kwargs: Any,
) -> _StreamedResponse:
    """OpenAI streaming wrapper that mirrors ``client.chat.completions.create``.

    Returns a ``_StreamedResponse`` that the existing non-streaming code
    path consumes via the same attributes (``choices[0].message.content``,
    ``choices[0].message.tool_calls``, ``choices[0].finish_reason``).

    Tokens are forwarded via ``on_token(text_chunk)``:
      * For plain content responses → each ``delta.content`` chunk goes
        straight through.
      * For ``respond_to_user`` tool calls → the JSON args buffer is fed
        through ``_RespondToUserExtractor``, which extracts the ``text``
        field characters and emits them. Other tool calls (search_*,
        get_*) accumulate silently — they are not user-visible text.
    """
    # Force stream + ask for usage in the final chunk (OpenAI 2024+).
    kwargs["stream"] = True
    kwargs["stream_options"] = {"include_usage": True}

    aggregate = _StreamedResponse()
    msg = aggregate.choices[0].message
    content_parts: list[str] = []
    # Live-Streaming-Schutz: <think>…</think> wird schon WÄHREND des Streamens
    # unterdrückt (nicht erst im finalen Text). Saubere Modelle streamen 1:1.
    _safe_on_token = _make_think_safe_on_token(on_token)
    # tc_index → {"id": str, "name": str, "args_buf": str, "extractor": _RespondToUserExtractor | None}
    tool_calls_accum: dict[int, dict[str, Any]] = {}

    stream = await client.chat.completions.create(**kwargs)
    async for chunk in stream:
        # Final chunk in OpenAI's stream often carries the cumulative usage
        # (only when stream_options.include_usage is set). Capture it so
        # _extract_usage works below just like for non-streaming responses.
        if getattr(chunk, "usage", None) is not None:
            aggregate.usage = chunk.usage
        if getattr(chunk, "model", None):
            aggregate.model = chunk.model
        if not chunk.choices:
            continue
        ch0 = chunk.choices[0]
        delta = getattr(ch0, "delta", None)
        if ch0.finish_reason:
            aggregate.choices[0].finish_reason = ch0.finish_reason
        if delta is None:
            continue
        if getattr(delta, "role", None):
            msg.role = delta.role
        if getattr(delta, "content", None):
            content_parts.append(delta.content)
            _safe_on_token(delta.content)
        if getattr(delta, "tool_calls", None):
            for tc_delta in delta.tool_calls:
                idx = getattr(tc_delta, "index", 0) or 0
                slot = tool_calls_accum.setdefault(idx, {
                    "id": "", "name": "", "args_buf": "", "extractor": None,
                })
                if getattr(tc_delta, "id", None):
                    slot["id"] = tc_delta.id
                fn = getattr(tc_delta, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                        # Lazily attach the JSON-stream extractor for respond_to_user
                        if slot["name"] == "respond_to_user" and slot["extractor"] is None:
                            slot["extractor"] = _RespondToUserExtractor(on_token)
                            # Replay any args we received before the name arrived
                            if slot["args_buf"]:
                                slot["extractor"].feed(slot["args_buf"])
                    if getattr(fn, "arguments", None):
                        slot["args_buf"] += fn.arguments
                        if slot["extractor"] is not None:
                            slot["extractor"].feed(fn.arguments)

    # Live-Stream-Filter leeren — letzten Sicherheits-Tail (Hold-back) freigeben.
    _safe_on_token.flush()
    # Reconstitute the message
    if content_parts:
        msg.content = "".join(content_parts)
    if tool_calls_accum:
        ordered = [tool_calls_accum[k] for k in sorted(tool_calls_accum.keys())]
        msg.tool_calls = [
            _StreamedToolCall(slot["id"], slot["name"], slot["args_buf"])
            for slot in ordered
        ]
    return aggregate


async def classify_input(
    message: str,
    history: list[dict],
    session_state: dict,
    environment: dict,
    canvas_state: dict | None = None,
    usage_acc: dict[str, Any] | None = None,
) -> ClassificationResult:
    """Phase 1: Classify user input into the 7 input dimensions.

    Returns a validated ClassificationResult. Falls back to defaults on
    validation errors so the pipeline never breaks.
    """
    system = _build_classify_system_prompt(session_state, environment, canvas_state)
    _log_system_prompt_size("classify", system)
    classify_tool = _build_classify_tool()

    messages = [{"role": "system", "content": system}]
    for h in history[-10:]:
        messages.append(h)
    messages.append({"role": "user", "content": message})

    resp = await client.chat.completions.create(
        **build_chat_kwargs(
            model=MODEL,
            messages=messages,
            tools=[classify_tool],
            tool_choice={"type": "function", "function": {"name": "classify_input"}},
            temperature=0.1,
        )
    )
    if usage_acc is not None:
        usage_accumulator_add(usage_acc, _extract_usage(resp), phase="classify")

    tool_call = resp.choices[0].message.tool_calls[0]
    raw = json.loads(tool_call.function.arguments)

    # ── Deterministic post-classifier overrides ────────────────
    # The LLM-classifier systematically over-selects I05 when a
    # material-type word like "Arbeitsblatt" or "Pressemitteilung"
    # appears in the message, even when the actual intent is clearly
    # routing, download or evaluation. These regex-based overrides
    # catch the unambiguous cases and force the correct intent.

    # ── Persona + Intent overrides ────────────────────────────────
    # Welle E v4+12 (Sprint K, 2026-05-27): Die Rule-Engine wurde
    # komplett entfernt. Deterministische Hard-Overrides leben jetzt
    # ausschließlich in ``chatbots/wlo/v1/01-base/classify-overrides.yaml``
    # und werden vom Classifier-System-Prompt als Hint-Anker geladen
    # (siehe ``_render_classify_overrides_block``). Kein Runtime-Pfad
    # mehr — das LLM bekommt die Trigger als Prompt-Beispiele.
    try:
        return ClassificationResult.model_validate(raw)
    except ValidationError as e:
        import logging
        logging.getLogger(__name__).warning("Classification validation error: %s", e)
        # Fall back with whatever fields are valid
        return ClassificationResult.model_construct(**{
            k: v for k, v in raw.items()
            if k in ClassificationResult.model_fields
        })


def _render_pattern_brief(pattern_output: dict[str, Any]) -> str:
    """Welle E v3 (2026-05-25): structured Pattern-Brief block.

    Renders the active pattern as four explicit sections — Kernregel,
    Verbotene Formulierungen, Anti-Patterns, Pattern-Brief (body_md) —
    so the response-LLM gets each piece labelled instead of one flat
    Markdown block. Sections without content are omitted.
    """
    label = pattern_output.get("label") or pattern_output.get("id") or "?"
    core_rule = (pattern_output.get("core_rule") or "").strip()
    forbidden = pattern_output.get("forbidden_phrases") or []
    anti = pattern_output.get("anti_patterns") or []
    body_md = (pattern_output.get("body_md") or "").strip()
    resp_type = pattern_output.get("response_type", "answer")
    tone = pattern_output.get("tone", "sachlich")
    # Welle E v4+7 (2026-05-26): when_to_use als Kontext-Briefing —
    # erklärt dem Response-LLM WARUM dieses Pattern gewählt wurde.
    # Hilft das Verhalten konsistent zum Klassifizier-Trigger zu halten.
    when_to_use = pattern_output.get("when_to_use") or []

    parts: list[str] = [
        f"## Aktives Pattern: {label}",
        f"Response-Typ: {resp_type}  ·  Ton: {tone}",
    ]
    if when_to_use:
        parts.append(
            "### Warum dieses Pattern (Kontext-Briefing)\n"
            + "Du wurdest gewählt, weil eine dieser Bedingungen zutrifft:\n"
            + "\n".join(f"- {w}" for w in when_to_use[:5])
        )
    if core_rule:
        parts.append("### Kernregel (HART)\n" + core_rule)
    if forbidden:
        parts.append(
            "### Verbotene Formulierungen — NICHT verwenden\n"
            + "\n".join(f'- "{p}"' for p in forbidden)
        )
    if anti:
        parts.append(
            "### Anti-Patterns — diese Handlungen vermeiden\n"
            + "\n".join(f"- {p}" for p in anti)
        )
    if body_md:
        parts.append("### Pattern-Brief (verbindlich)\n" + body_md)
    elif not (core_rule or forbidden or anti):
        parts.append("_(kein Pattern-Brief — folge der Kernregel)_")
    return "\n\n".join(parts)


async def generate_response(
    message: str,
    history: list[dict],
    classification: dict[str, Any],
    pattern_output: dict[str, Any],
    pattern_label: str,
    session_state: dict,
    environment: dict,
    rag_context: str = "",
    available_rag_areas: list[str] | None = None,
    rag_config: dict[str, Any] | None = None,
    blocked_tools: list[str] | None = None,
    prefetched_tool: dict[str, Any] | None = None,
    prefetched_extras: list[dict[str, Any]] | None = None,
    canvas_state: dict | None = None,
    usage_acc: dict[str, Any] | None = None,
    on_token: Any = None,
) -> tuple[str, list[dict], list[str], list]:
    """Generate the final response using the selected pattern and MCP tools.

    Returns (response_text, wlo_cards, tools_called, outcomes).
    Outcomes is a list of ToolOutcome objects (Triple-Schema T-23).

    ``on_token`` is the Phase-2 streaming hook (POST /api/chat/stream). When
    provided, the LLM call inside the tool-loop runs with ``stream=True``
    and forwards each text-delta to the callback — both for plain content
    responses AND for ``respond_to_user`` tool args (where the ``text``
    field is extracted progressively from the JSON arg-stream). Default
    ``None`` keeps the regular non-streaming POST /api/chat unchanged.
    """
    blocked_tools = blocked_tools or []
    persona_id = classification.get("persona_id", "P-AND")
    base_persona = load_base_persona()
    guardrails = load_guardrails()
    persona_prompt = load_persona_prompt(persona_id)
    domain_rules = load_domain_rules()

    # Welle C Sprint 6 — State als Verlaufs-Phase. Pattern wählt WAS antworten
    # + welche Tools, State sagt WIE in der aktuellen Verlaufs-Phase
    # einzuzahlen ist (z.B. "stelle EINE Frage" in S2 Slot-Erfassung,
    # "frage nach Pass" in S3 Ergebnis-Kuratierung).
    _resp_state_id = classification.get('next_state', 'S1')
    _resp_state_meta = _get_state_meta_safe(_resp_state_id)
    _resp_state_directive = (
        _resp_state_meta.get('bot_directive')
        or '— keine spezifische Direktive für diese Phase, folge dem Pattern.'
    )

    # Build system prompt following 5-Layer LPA architecture
    system_parts = [
        # Layer 1: Identity (base persona from config)
        base_persona,
        # Layer 2: Domain rules
        domain_rules,
        # Layer 3: Persona-specific prompt
        persona_prompt,
        # Layer 4: Active pattern + intent
        # Welle E v3 (2026-05-25): Pattern-Brief wird strukturiert gerendert.
        # core_rule + forbidden_phrases + anti_patterns kommen aus den
        # Frontmatter-Feldern; body_md enthält nur noch das Pflicht-Antwort-
        # Schema + pattern-spezifische Tabellen (die zu unique sind, um sie
        # zu schematisieren).
        _render_pattern_brief(pattern_output)
        + f"""

### Anrede-Form (STRIKT einhalten — Persona-abhängig)
Formality: {pattern_output.get('formality', 'neutral')}
{_formality_guidance(pattern_output.get('formality', 'neutral'), persona_id)}

**WICHTIG — Quick-Replies (Pillen-Buttons) IMMER in Du-Form:**
Die Formality-Regel oben gilt NUR für den **Bot-Antwort-Text** (was BOERDi
dem Nutzer schreibt). Die Quick-Replies dagegen sind **nutzerseitige
Folge-Eingaben** — der Nutzer spricht BOERDi an, und der Nutzer duzt
BOERDi IMMER (BOERDi ist eine freundliche Eule, kein formaler Beamter).
- Quick-Replies in **Du-Form** schreiben, egal welche Persona-Formality
  oben gesetzt ist: „Kannst du das genauer erklären?", „Zeig mir mehr",
  „Erklär mir den Unterschied".
- **NIE Sie-Form** in Quick-Replies: NICHT „Können Sie mir helfen?",
  NICHT „Zeigen Sie mir mehr.", NICHT „Bitte erklären Sie das."
- Auch nicht „Ja, bitte sagen Sie mir …" — sondern „Ja, gerne." oder
  „Ja, sag's mir."
Länge: {pattern_output.get('length', 'mittel')} (kurz=kompakte 2-4 Saetze, ein Absatz; mittel=strukturierte Erklaerung mit 2-4 Absaetzen, gerne mit H3-Unterpunkten wenn das Thema mehrere Aspekte hat; lang=ausfuehrliche Darstellung mit mehreren Absaetzen, Beispielen und Aufzaehlungen)
Wenn internes Wissen (RAG-Kontext, query_knowledge-Ergebnisse) verfuegbar ist, nutze es inhaltlich REICH aus — der Nutzer hat explizit gefragt und erwartet eine substantielle Antwort, keine Ein-Satz-Zusammenfassung.

**ZWINGEND zu Quell-URLs (NICHT optional)**: jeder RAG-Kontext-Block beginnt mit einer Frontmatter-Zeile der Form ``**URL**: <https://…>`` oder ``source: "https://…"``. Sobald du eine **inhaltliche Aussage** aus dem RAG-Kontext entnimmst (Plattform-Erklärung, Projekt-Hintergrund, OER-Lizenz-Detail, Verein-Info, Statistik, Akteur-Beschreibung, Förder-/Projekt-Info), MUSST du im Antwort-Text mindestens **einen Markdown-Link** auf die jeweils zugehoerige Original-URL einbauen. KEINE blossen Plain-Text-Erwähnungen wie „auf der WLO-Seite findest du …" — das wird vom Frontend nicht als Link erkannt. Korrekt:

  - „Mehr dazu auf [WLO-Über-uns](https://wirlernenonline.de/ueber-wirlernenonline/)"
  - „Siehe den [OER-Bereich](https://wirlernenonline.de/oer/) und die [Themenseiten](https://wirlernenonline.de/fachportale)"
  - „Die Angebote sind auf [WissenLebtOnline](https://wp-test.wirlernenonline.de/) gebündelt, siehe insbesondere [Angebote](https://wp-test.wirlernenonline.de/angebote/)."

REGELN:
1. Mindestens **EIN** Markdown-Link pro RAG-gestützter Antwort. Bei mehreren erwähnten Konzepten gerne 2-3 Links — das erlaubt dem Frontend, mehrere Bring-mich-hin-Buttons zu rendern.
2. Nimm die KONKRETE Unter-Seite mit Pfad (``/oer/`` statt ``/``). Domain-Roots ohne Pfad sind erlaubt, aber spezifische Pfade gewinnen.
3. Schreibe die URL EXAKT wie im Frontmatter (mit ``https://``-Schema, mit allen Pfad-Segmenten). Erfinde keine Pfade, die nicht im Kontext stehen — wenn der RAG-Block ``https://x/y/`` zeigt, schreibe ``[Label](https://x/y/)``, nicht ``[Label](https://x/y/z)``.
4. Wenn du KEINEN passenden Link aus dem RAG-Kontext kennst, lass den Markdown-Link weg — erfinde nichts.
Detail: {pattern_output.get('detail_level', 'standard')}
Max. Ergebnisse: {pattern_output.get('max_items', 5)}""",
        # Layer 5: Conversation context + State-Verlaufs-Phase (Welle C Sprint 6)
        f"""## Kontext
Seite: {environment.get('page', '/')}
Entities: {json.dumps({k: v for k, v in (classification.get('entities') or {}).items() if not k.startswith('_')})}
Signale: {', '.join(classification.get('signals', []))}
Gesprächs-Phase: {_resp_state_id} ({_resp_state_meta.get('label', '?')})
Rolle in dieser Phase: {_resp_state_meta.get('role', '—')}

## Phase-Direktive (befolge, ergänzend zum Pattern-Verhalten)
{_resp_state_directive}""",
    ]

    # Semantic page-context block (resolved theme-page metadata). Cached on
    # session_state["entities"]["_page_metadata"] by page_context_service at
    # request entry time. Goes after the generic context so the LLM treats
    # it as prime information.
    try:
        from app.services import page_context_service
        _pm = page_context_service.get_cached(session_state)
        _pb = page_context_service.render_for_prompt(
            _pm, environment.get("page_context"),
        )
        if _pb:
            system_parts.append(_pb)
        else:
            # Fallback: widget extracted visible page text but MCP could
            # not resolve to platform metadata — use the heuristic block.
            _raw_pb = page_context_service.render_raw_for_prompt(
                environment.get("page_context"),
            )
            if _raw_pb:
                system_parts.append(_raw_pb)
    except Exception:
        pass

    # Welle E v4++++ (2026-05-26, eval-bce3): M11 Edit braucht den Vor-Inhalt
    # explizit, nicht nur in der Conversation-History. eval-bce3 zeigte: bei
    # 4 von 6 Personas hat der LLM trotz vorhandenem ~3000-Zeichen Vor-Turn
    # in der History den M11-Fallback "Ich habe gerade nichts zum Anpassen"
    # gewählt — der Pattern-Body-Fallback war zu prominent formuliert.
    # Lösung: wenn pattern_id == M11, packe ``_canvas_last_markdown`` direkt
    # als System-Block in den Prompt. Dann hat der LLM keine Ausrede mehr.
    _pattern_id_for_m11 = (pattern_output.get("pattern_id")
                            or pattern_output.get("short_purpose", "").split()[0]
                            or "")
    # Heuristisch: der Caller setzt ``pattern_output["_pattern_id"]`` oder
    # ähnlich nicht zuverlässig — wir prüfen daher ``output_mode == "rerender"``,
    # was nur M11 hat.
    if pattern_output.get("output_mode") == "rerender":
        _prev_md = (
            (session_state.get("entities") or {}).get("_canvas_last_markdown")
            or ""
        ).strip()
        if _prev_md:
            system_parts.append(
                "## Aktueller Inhalt zum Editieren\n\n"
                "Der User möchte den folgenden Inhalt anpassen (Vor-Turn-"
                "Material aus dieser Session). **Lies ihn vollständig**, "
                "wende die Edit-Anweisung der aktuellen User-Nachricht an "
                "und gib den kompletten überarbeiteten Markdown-Block zurück "
                "— NICHT 'Ich habe gerade nichts zum Anpassen'. Der Inhalt "
                "IST hier:\n\n"
                "```markdown\n"
                + _prev_md[:8000]  # Hard-Cap auf 8k chars für Token-Budget
                + ("\n```\n" if len(_prev_md) <= 8000
                   else "\n…\n```\n(Inhalt gekürzt, vollständig in der "
                        "Conversation-History sichtbar.)\n")
            )

    # Card-text-mode: how to handle overlap between text and material cards
    _card_mode = pattern_output.get("card_text_mode", "minimal")
    # Host-Flag cards-enabled=false signalisiert: das Frontend rendert
    # *keine* Kacheln, sondern hängt nur 3 dezente Inline-Markdown-Links
    # ans Antwort-Ende. Der User sieht also weniger visuelles Feedback —
    # eine refinement-Rückfrage ("Was brauchst du gerade am meisten?")
    # wirkt dann wie eine Sackgasse, nicht wie ein Angebot. Wenn der
    # Embed-Host diesen Modus aktiv anfordert, sollen wir die Treffer
    # direkt liefern statt zurückzufragen.
    _cards_inline_mode = environment.get("cards_enabled") is False
    # Welle C.5 (2026-05): Im inline-result-grouping-Modus rendert das Frontend
    # die Treffer NICHT als 5er-Liste mit Einzelmaterial-Icons, sondern in drei
    # separaten Boxen (Themenseiten / Sammlungen / Webseiten-Inhalte) mit je
    # **max. 3 sichtbaren Items**, dazu eine Such-CTA-Box ("Alle Treffer
    # zur Suche „<term>"" → springt auf die WLO-Suche, in der Einzelinhalte
    # auftauchen). Einzelinhalte (node_type != collection / keine topic_pages)
    # haben in diesem Modus also KEIN sichtbares UI-Pendant — Erwähnungen im
    # Text wirken für den User wie "wo sind die zwei Materialien hin?" (vgl.
    # User-Feedback 2026-05-21: „zwei konkrete Materialien" → nicht sichtbar).
    # Default ist seit Welle C.5 ``True`` (None → True), wir branchen also auf
    # ``not False`` — Legacy-Inline (cards_enabled=False + grouping=False
    # explizit) kriegt weiter das alte 5er-Listen-Prompt.
    _inline_grouping_mode = (
        _cards_inline_mode
        and environment.get("inline_result_grouping") is not False
    )

    # Pattern-ID aus dem Label extrahieren ("M05 (Material-Suche...)") → "M05"
    # Nur Such-Pattern (M05/M06/M07/M08) kriegen den ausführlichen
    # "Material-Typ-Anfragen / Such-CTA"-Block angehängt. Für M04 (Wissens-
    # Antwort), M09 (Lernpfad), M10 (KI-Inhalt), M11 (Nachbearbeitung),
    # M13 (Einreichen), M14 (Feedback), M15 (Orientierung) ist dieser
    # Block irreführend — sie sollen NIE "Für Videos zum Thema schau in
    # die Suche unten" antworten. Bug-Fix aus Eval eval-b2cd4e274be9.
    _pattern_id = ((pattern_label or "").strip().split(" ")[0] or "").upper()
    _is_search_pattern = _pattern_id in {"M05", "M06", "M07", "M08"}
    if _card_mode == "minimal":
        system_parts.append("""
## Darstellungsregel: Materialien als Kacheln (Modus: minimal)
Gefundene Materialien werden dem Nutzer automatisch als interaktive Kacheln angezeigt
(Titel, Beschreibung, Vorschau, Metadaten, Links). Du musst diese Informationen
NICHT im Text wiederholen.
- Schreibe eine kurze kontextuelle Einleitung (1-2 Saetze): Was wurde gefunden, warum passt es.
- Nenne KEINE einzelnen Titel, Beschreibungen oder Metadaten im Text.
- RICHTIG: "Hier sind 4 Materialien zur Bruchrechnung, darunter Videos und interaktive Uebungen."
- FALSCH: "1. **Bruchrechnung leicht gemacht** — Ein Video das erklaert..."
- Die Kacheln liefern alle Details — dein Text liefert den Kontext.""")
    elif _card_mode == "reference":
        system_parts.append("""
## Darstellungsregel: Materialien im Text referenzieren (Modus: reference)
Gefundene Materialien werden dem Nutzer auch als Kacheln angezeigt, aber du DARFST
und SOLLST sie im Text namentlich nennen und didaktisch einordnen.
- Nutze die Materialtitel im Text fuer Struktur (Reihenfolge, Lernziele, Zeitangaben).
- Verlinke genannte Materialien als Markdown-Link: [Titel](URL)
  Nutze die URL aus den Tool-Ergebnissen (wlo_url oder url).
- Wiederhole NICHT die vollstaendige Beschreibung oder Metadaten — die stehen in den Kacheln.
- RICHTIG: "Schritt 2 (15 Min.): Mit [Brueche addieren](https://wirlernenonline.de/...) ueben die SuS..."
- FALSCH: "Schritt 2: **Brueche addieren** — Ein Arbeitsblatt fuer Klasse 6 mit CC BY-SA..."
- Dein Text liefert die didaktische Struktur, die Kacheln liefern die Material-Details.""")
    elif _card_mode == "highlight":
        system_parts.append("""
## Darstellungsregel: Ausgewaehlte Materialien hervorheben (Modus: highlight)
Gefundene Materialien werden dem Nutzer als Kacheln angezeigt. Du darfst 1-2 Materialien
im Text kurz hervorheben und begruenden, warum sie besonders passen.
- Hebe maximal 1-2 Materialien namentlich hervor — nicht alle einzeln auflisten.
- Verlinke hervorgehobene Materialien als Markdown-Link: [Titel](URL)
  Nutze die URL aus den Tool-Ergebnissen (wlo_url oder url).
- Begruende kurz WARUM (z.B. "besonders gut fuer den Einstieg", "interaktiv und motivierend").
- Die restlichen Materialien stehen in den Kacheln — nicht im Text beschreiben.
- RICHTIG: "Besonders empfehlenswert ist [Fotosynthese verstehen](https://wirlernenonline.de/...), weil es anschaulich erklaert."
- FALSCH: "1. *Fotosynthese verstehen* — Video, CC BY... 2. *Arbeitsblatt Fotosynthese* — PDF..."
- Dein Text liefert die Empfehlung, die Kacheln liefern den Ueberblick.""")

    # Re-Rank-Hinweis im Kachel-Mode (Card-Pipeline v2):
    # Das ``select_top_cards``-Tool ist auch im Kachel-Modus verfügbar und
    # dient als Re-Rank-Hint für die deterministische Backend-Auswahl. Wenn
    # das LLM eine sinnvolle Reihenfolge angibt, übernimmt sie das Backend.
    # Sonst greift Relevance-Score-Sortierung. Dieser Hinweis kommt
    # **zusätzlich** zu den minimal/reference/highlight-Anweisungen.
    if not _cards_inline_mode:
        system_parts.append("""
## Optionaler Re-Rank über select_top_cards
Wenn die Search-Tools mehrere Treffer geliefert haben und du eine klare
Reihenfolge bevorzugst (z.B. weil eine bestimmte Sammlung perfekt zum
User-Thema passt und vorne stehen soll), rufe ``select_top_cards`` mit
den 1-5 node_ids in deiner Wunsch-Reihenfolge auf. Das Backend ordnet
die Kacheln dann genau so an.

Wenn du keine starke Präferenz hast, kannst du den Call weglassen — das
Backend wählt dann deterministisch nach Relevance-Match (Title/Keywords/
Disciplines). Bei Klärungs-Turn / leeren Tool-Results: NICHT aufrufen.""")

    # Inline-Link-Mode (Host hat cards-enabled="false" gesetzt) — Override:
    # Die Treffer werden NICHT als Kacheln angezeigt, sondern vom Backend
    # nach deiner Antwort als 3 dezente Inline-Markdown-Links angehaengt.
    # Der User sieht also nur deinen Text + die 3 Links. Eine Refinement-
    # Rueckfrage am Ende fuehlt sich dann wie eine Sackgasse an
    # ("der Bot fragt schon wieder?") statt wie ein hilfreicher Folge-Schritt.
    # In diesem Modus sollst du direkt liefern, nicht zurueckfragen.
    if _inline_grouping_mode and _is_search_pattern:
        system_parts.append("""
## Inline-Result-Grouping-Mode (Host-Setting inline-result-grouping=true, Default seit Welle C.5)
Die Treffer werden in DREI nach Typ getrennten Boxen angezeigt:
  - **Themenseiten** (max. 3 sichtbar) — kuratierte Übersichts-Seiten
  - **Sammlungen** (max. 3 sichtbar) — thematisch gebündelte Materialien
  - **Webseiten-Inhalte** (max. 3 sichtbar) — RAG-Quellen aus deinem Text
Darunter eine **Such-CTA-Box** ("Alle Treffer zur Suche „<term>"")
die auf die externe WLO-Suche springt, in der Einzelinhalte (Videos,
Arbeitsblätter, Übungen …) zu finden sind.

**WICHTIG — Was der User SIEHT vs. was du im Tool-Loop kennst:**
Du darfst weiterhin ``search_wlo_content`` aufrufen und kennst dann die
Einzelinhalte aus dem Tool-Result. Aber: Diese **Einzelinhalte werden NICHT
als sichtbare Items angezeigt** — sie tauchen für den User nur indirekt über
die "Alle Treffer zur Suche"-CTA auf. Wenn du im Text sagst "ich habe dir
zwei Videos rausgesucht" oder "konkrete Materialien zusammengestellt",
sieht der User KEINE zwei Videos in der UI — nur Sammlungen/Themenseiten.
Das verwirrt.

**WAHRHEITSPFLICHT — bezieh dich auf den UI-BOX-STATUS:**

Nach jedem Such-Tool-Call kommt im Tool-Result eine Zeile
``[UI-BOX-STATUS …]`` mit den Counts pro sichtbarer Box. Diese Zahlen
sind die EINZIGE Wahrheit darüber, was der User sieht. Wenn dort steht
"0 Sammlungen sichtbar", dann sprich im Text NICHT von Sammlungen —
auch wenn das verlockend wäre. Erfundene Treffer sind eine
Halluzination und beschädigen die Antwortqualität.

**TEXT-REGEL (ABSOLUT STRIKT — KEINE AUSNAHMEN):**

Es gibt nur ZWEI sichtbare Anker für den User: Themenseiten und Sammlungen.
NUR diese beiden Begriffe darfst du im Antwort-Text verwenden, wenn du
Treffer anpreist — UND nur dann, wenn die UI tatsächlich mindestens eine
Themenseite/Sammlung zeigt (siehe UI-BOX-STATUS).

VERBOTENE WÖRTER im Antwort-Text (auch wenn du sie im Tool-Result siehst):
  ❌ "Video"      ❌ "Arbeitsblatt"  ❌ "Übung"      ❌ "Quiz"
  ❌ "Audio"      ❌ "Präsentation"  ❌ "Lehrbuch"   ❌ "Interaktiv"
  ❌ "Material"   ❌ "Materialien"   ❌ "Inhalt"     ❌ "Inhalte"
  ❌ "Aufgabe"    ❌ "Beispiel"      ❌ "Erklärung"  ❌ "Anwendung"
Auch keine Anwendungs-Themen ("für Fläche, Umfang und Konstruktion") als
ob du konkrete Materialien dazu liefern würdest — du lieferst nur
Sammlungen/Themenseiten, die diese Aspekte abdecken könnten.

ERLAUBTE Begriffe für Treffer: "Themenseite(n)", "Sammlung(en)",
"Überblick", "Einstieg", "kuratierte Auswahl". Punkt.

KEINE Mengenangaben für unsichtbare Treffer:
  ❌ "ein Arbeitsblatt und ein Video"
  ❌ "zwei konkrete Materialien"
  ❌ "drei Übungen zum Vertiefen"
  ❌ "ergänzende Inhalte"
  ✅ "eine Sammlung und zwei Themenseiten"
  ✅ "passende Sammlungen zum Thema"

KEIN "dazu kommt …" / "ergänzend …" / "zusätzlich noch …" für
Material-Typen — wenn da was kommt, dann nur weitere Sammlungen/
Themenseiten oder die Such-CTA.

**FORMEL FÜR DEINE EINLEITUNG (1-2 Sätze, mehr nicht):**
  "Hier ist/sind [Anzahl] [Themenseite(n)/Sammlung(en)] zu <Thema>.
   [optional: 1 Satz Einordnung, warum es passt.]"
  → Optional am Ende: "Für Einzelinhalte (Videos, Arbeitsblätter …) klick
    auf die Such-CTA darunter."

**MATERIAL-TYP-ANFRAGEN (User fragt nach Video / Arbeitsblatt / Übung / …):**

Dieser Fall ist speziell — die Search-Pipeline durchsucht dann fokussiert
``search_wlo_content`` mit dem gewünschten ``learningResourceType``, und
in der Regel kommen NUR Einzelinhalte zurück (keine Sammlungen, keine
Themenseiten). Im UI-BOX-STATUS steht dann typisch:
``0 Themenseite(n), 0 Sammlung(en), N Einzelinhalt(e) NICHT sichtbar``.

Das heißt: die UI zeigt nur die Such-CTA + ggf. Webseiten-Inhalte —
keine Themenseiten-Box, keine Sammlungs-Box. Korrekte Antwort:

  ✅ "Für Videos zur Prozentrechnung schau in die Suche unten — dort
      findest du die gefilterten Treffer."
  ✅ "Hier sind passende Arbeitsblätter zur Photosynthese — klick auf
      die Suche unten, dort sind sie gefiltert aufgelistet."
  ✅ "Direkt im Chat zeige ich für Material-Typ-Anfragen nichts in
      Boxen, weil Einzelinhalte besser über die Suche ausgewählt werden.
      Über die Such-CTA findest du die Treffer."

NICHT antworten:
  ❌ "Ja — ich hab dir passende Sammlungen rausgezogen." (wenn keine
      Sammlung im UI-STATUS steht — pure Halluzination)
  ❌ "Hier sind zwei Sammlungen…" (wenn der User VIDEOS wollte und der
      Status 0 Sammlungen zeigt)
  ❌ Ein konkretes Video/Arbeitsblatt namentlich nennen (selbst wenn du
      es im redacted Summary siehst — sichtbar wird es erst beim Klick
      auf die Such-CTA).

Auch im Type-Focus-Fall gilt: KEINE konkreten Material-Titel zählen
oder typisieren („zwei Videos", „drei Arbeitsblätter") — nur generisch
auf die Such-CTA verweisen.

**TURN-FLOW (STRIKT):**
1. **search_wlo_***-Tools aufrufen — typischerweise ``search_wlo_topic_pages``
   und/oder ``search_wlo_collections``. ``search_wlo_content`` ist OPTIONAL
   (hilfreich für Lernpfad-Vorbereitung, aber nicht nötig für die Box-
   Anzeige) — wenn du es rufst, beziehe dich im Text trotzdem nicht auf
   die einzelnen Inhalte.
2. **select_top_cards** ist OPTIONAL in diesem Modus — das Backend filtert
   die Cards automatisch in die drei Boxen. Wenn du eine bestimmte Reihen-
   folge bevorzugst, rufe es trotzdem (Re-Rank-Hint).
3. **Plain-Text-Antwort** — 1-2-Satz-Einleitung, GENERISCH formuliert,
   NUR Themenseiten/Sammlungen erwähnen.

**KONKRETE BEISPIELE — bezogen auf reale Fehler:**

User: "Dreiecke in Mathematik"
  ✅ RICHTIG: "Hier sind passende Treffer zu Dreiecken in Mathematik. Die
              Sammlung gibt dir einen kuratierten Überblick über das Thema."
  ❌ FALSCH:  "Hier sind passende Treffer zu Dreiecken in Mathematik. Die
              Sammlung gibt dir den Überblick, dazu kommen ein Arbeitsblatt
              und ein Video für Fläche, Umfang und Konstruktion."
      ↑ "Arbeitsblatt", "Video", "dazu kommen" → verspricht unsichtbare Items.

User: "Mathe Grundschule"
  ✅ RICHTIG: "Für Mathe in der Grundschule habe ich dir zwei Sammlungen
              und eine Themenseite herausgesucht."
  ❌ FALSCH:  "Ich habe dir einen Überblick und zwei konkrete Materialien
              zusammengestellt."
      ↑ "Materialien" verboten.

User: "Hast du was zu Klimawandel?"
  ✅ RICHTIG: "Ja, hier sind passende Sammlungen zum Klimawandel — eine
              Themenseite fasst die zentralen Aspekte zusammen."
  ❌ FALSCH:  "Ja, ich habe dir eine Themenseite und ein Video zum Treibhaus-
              effekt herausgesucht."
      ↑ "Video" verboten.

## URL-EINBETTUNG — NIE im Bot-Text

NIEMALS Markdown-Links zu URLs in deinem Antwort-Text schreiben. Das gilt
absolut, auch wenn du URLs aus Wissensquellen oder Training-Daten siehst.
URLs werden vom System automatisch über Kacheln/Boxen/CTAs gerendert.
""")
    elif _inline_grouping_mode and not _is_search_pattern:
        # Pattern ist KEIN Such-Pattern (also M04 Wissens-Antwort, M09
        # Lernpfad, M10 KI-Inhalt, M11 Nachbearbeitung, M13 Einreichen,
        # M14 Feedback, M15 Orientierung). Diese Pattern liefern eigene
        # Antwort-Templates aus dem Pattern-Markdown — der globale
        # Material-Suche-Block würde nur Halluzinationen erzeugen
        # ("Für Videos schau in die Suche unten"). Statt dessen knapper
        # Anti-Halluzinations-Hinweis:
        system_parts.append("""
## Pattern-Modus: KEIN Suche-Antworten

Das aktive Pattern liefert eine eigene Antwort-Struktur (siehe Kernregel
oben). **NIEMALS** folgende Formulierungen verwenden:

  ❌ "Für Videos zum Thema schau in die Suche unten"
  ❌ "Hier sind passende Sammlungen / Themenseiten"
  ❌ "Klick auf die Such-CTA darunter"
  ❌ "Such-Treffer in der gefilterten Auflistung"

Diese gehören zu Material-Such-Patterns (M05/M06/M07/M08), nicht zu
diesem Pattern. Halte dich strikt an die im Pattern-Markdown
beschriebene Antwort-Form (Wissens-Antwort / Lernpfad-Plan / KI-Inhalt /
Submit-Link / Feedback-Echo / Orientierungs-Optionen).

Such-Tools (`search_wlo_*`) NICHT aufrufen — das aktive Pattern braucht
sie nicht.
""")
    elif _cards_inline_mode:
        system_parts.append("""
## Inline-Link-Mode (Host-Setting cards-enabled="false")
Die Treffer werden NICHT als Kacheln gerendert. Stattdessen hängt das
Backend nach deiner Antwort eine strukturierte Liste mit den von DIR
ausgewählten Treffern an (mit kleinem Material-Symbol-Icon pro Treffer:
Themenseite / Sammlung / Einzelmaterial). Der User sieht deinen Text +
darunter diese Link-Liste.

**TURN-FLOW (STRIKT):**
1. **search_wlo_***-Tools aufrufen, um Treffer zu beschaffen. Wenn nur
   Sammlungen/Themenseiten gefunden werden, kannst du zusätzlich
   ``search_wlo_content`` rufen, um die Auswahl mit Einzelinhalten zu
   ergänzen.
2. **select_top_cards(card_ids=[...], reasoning="...")** aufrufen —
   wähle aus den Treffern bis zu 5 node_ids in Anzeige-Reihenfolge aus.
   Auswahl-Regeln siehe Tool-Beschreibung. **Dieser Schritt ist
   verpflichtend, sobald du etwas zeigen willst** — sonst weiß das Backend
   nicht, welche Treffer es anzeigen soll, und die User sieht nur deinen
   Text ohne Links. Wenn du gar nichts gefunden hast: kein select_top_cards
   und keine Liefer-Behauptung („rausgesucht", „gefunden") — stattdessen
   eine Klärungsfrage.
3. Plain-Text-Antwort — kurze 1-2-Satz-Prosa als Einleitung der Liste.

**AUSWAHL-PRIORITÄT** für select_top_cards:
- **ZIEL: bis zu 5 Treffer** — wenn die Search-Tools genug geliefert haben.
- DEFAULT-Reihenfolge: Themenseiten zuerst (geben breiten Überblick),
  dann Sammlungen, dann Einzelinhalte.
- **MIX**: 1 Sammlung + 3-4 Einzelinhalte ist meist besser als 1 Sammlung
  alleine. Fülle freie Slots mit passenden Einzelinhalten auf.
- AUSNAHME (Typ-Fokus): Wenn der User explizit nach Material-Typ fragt
  (Video, Arbeitsblatt, Übung, Quiz, Audio, Präsentation, Interaktiv,
  Kurs) → bis zu 5 Einzelinhalte dieses Typs. Keine Themenseiten/
  Sammlungen dazwischen.
- Auch 1-2 Treffer sind OK, wenn wirklich nicht mehr passend ist — dann
  trotzdem select_top_cards mit diesen IDs aufrufen, NIE leer lassen.

**WICHTIG zur Intro-Formulierung — Backend-Auto-Augmentation:**
Wenn du nur Sammlungen oder Themenseiten gewählt hast (keine Einzelinhalte
dabei), ergänzt das Backend automatisch passende Einzelinhalte (Video,
Arbeitsblatt, Lehrbuch …) auf insgesamt bis zu 5 Treffer. Deshalb:
- **Schreibe deine Einleitung GENERISCH genug**, dass sie sowohl 1 Treffer
  als auch 5 gemischte Treffer abdeckt. NICHT "eine passende Sammlung"
  (Singular festgenagelt) — BESSER "Hier ist eine passende Sammlung und
  ergänzende Materialien" / "Hier ist das, was zum Thema passt" / "Hier
  sind passende Treffer".
- Bei Typ-Fokus-Anfragen ("Hast du Videos?") gibt es KEINE Augmentation —
  da kannst du Plural konkret nennen ("Hier sind 5 Videos zum Thema").
- Zähle keine Materialtypen aus deinem select_top_cards-Call im Text auf
  ("eine Sammlung und ein Video") — du weißt vorher nicht, was das Backend
  zusätzlich anhängt. Generisch bleiben.

**WEITERE REGELN (STRIKT):**
1. **NIE Markdown-Links in deinem Text** — auch nicht zu Fachportalen,
   FAQ-Seiten, Suchseiten, WLO-Unterseiten, Wikipedia o.ä. Das Backend
   hängt strukturierte Links separat an. WENN KEINE Treffer da sind
   (Klärungs-/Frage-Turn ohne select_top_cards), antwortest du PLAIN
   TEXT — keine Links. Auch keine "siehe XY"-Verweise.
2. **Keine Aufzählung von Material-Titeln** im Text — die Liste darunter
   zeigt sie eh. Schreibe stattdessen eine kurze kontextuelle Einleitung
   (1-2 Sätze): Was wurde gefunden, warum passt es.
3. **LIEFERN, NICHT VERSPRECHEN.** Wenn du Tools aufgerufen und Treffer
   per select_top_cards ausgewählt hast → schreibe im **Präsens/Perfekt**,
   niemals im Futur:
     * RICHTIG: "Hier sind passende Sammlungen zu Bruchrechnung..."
     * RICHTIG: "Ich habe dir vier kuratierte Sammlungen rausgefischt..."
     * FALSCH:  "Ich schau dir die besten Treffer raus..." ← FUTUR-PROMISE
     * FALSCH:  "Gleich folgen die Treffer..."             ← FUTUR-PROMISE
     * FALSCH:  "Lass mich kurz suchen..."                 ← FUTUR-PROMISE
   Die Backend-Link-Liste wird **DIREKT nach deinem Text** angezeigt — es
   gibt kein "danach", kein "gleich", kein zweistufiges Reveal.
   **WICHTIG**: Behaupte NIEMALS, etwas geliefert zu haben („rausgefischt",
   „gefunden", „hier sind die Treffer"…), ohne tatsächlich vorher
   search_wlo_*-Tools UND select_top_cards aufgerufen zu haben. Wenn du
   keine Treffer hast → Klärungsfrage statt Liefer-Behauptung.
4. **Keine Refinement-Rückfrage** wenn Treffer geliefert wurden.
   Bei Klärungs-Turn (kein Material gefunden, kein select_top_cards)
   darfst du EINE Rückfrage stellen (z.B. "Was ist dein Thema?"). Sonst
   beende mit Aussage oder bestätigtem nächsten Schritt.
5. **Tools tatsächlich aufrufen.** Wenn der User Material will, rufe
   die Search-Tools UND select_top_cards auf — schreibe nicht "ich finde
   X" ohne den ganzen Flow durchzuziehen.
6. **Quick-Replies** (Pillen-Buttons unterm Text) liefern Folge-
   Optionen — du musst nicht im Text um Details bitten.
7. **Tonalität**: liefernd, nicht fragend, nicht Wissen-Predigen.

RICHTIG (Klärung, keine Treffer):
   "Gerne — sag mir kurz dein Thema, dann schau ich passende Sammlungen
   für deinen Unterricht raus."
RICHTIG (Treffer gefunden, select_top_cards aufgerufen):
   "Hier sind passende Sammlungen zu Klimawandel — die Themenseite
   darunter fasst die zentralen Aspekte zusammen, die anderen vertiefen
   einzelne Schwerpunkte wie Nachhaltigkeit oder Naturschutz."
FALSCH:
   "Mehr dazu finden Sie auf [den Fachportalen](https://...)."
   "Hier sind: [Umwelt](https://...), [Nachhaltigkeit](https://...)."
   "Ich schau dir die besten Treffer raus — gleich folgen sie." ← FUTUR
   "Lass mich kurz nach Bruchrechnung suchen..."                ← FUTUR

## URL-EINBETTUNG — NIE im Bot-Text

NIEMALS Markdown-Links zu URLs in deinem Antwort-Text schreiben. Das gilt
absolut, auch wenn du URLs aus Wissensquellen oder Training-Daten siehst:

VERBOTEN:
   "[WirLernenOnline FAQ](https://wirlernenonline.de/faq/)"
   "[Über WLO](https://wirlernenonline.de/ueber-wlo)"
   "Schau auf [die Themenseite Klimawandel](https://...) für mehr."
   "- [Bildungsbereiche](https://wirlernenonline.de/bildungsbereiche)"

ERLAUBT (Plain-Text-Referenz auf den Namen):
   "Mehr dazu findest du in den WLO-FAQs und im WLO-Überblick."
   "Die Themenseite Klimawandel fasst die Kernaspekte zusammen."
   "Du findest dort u.a. Bildungsbereiche, Materialtypen und Personas."

WARUM:
- URLs werden vom System automatisch und semantisch korrekt aus den
  echten Card-Metadaten + RAG-Source-Frontmatter ausgespielt — über
  Kacheln, die "Webseiten-Inhalte"-Box und Such-CTAs der UI. Du musst
  und sollst keine URLs in den Text schreiben.
- URLs die du aus dem Training kennst oder erraten würdest, können
  veraltet, falsch oder halluziniert sein → kaputte Klicks für den User.
- Doppelte Anzeige (URL im Text + Box) ist Lärm.

Falls dir ein Tool eine konkrete URL als ``card.link``/``card.url``
liefert, übergib sie NICHT als Text — das System verlinkt die Kachel.
""")

    # Signal-driven modulation rules
    if pattern_output.get("skip_intro"):
        system_parts.append("\n## Regel: Keine Einleitung. Direkt zur Sache.")
    if pattern_output.get("one_option"):
        system_parts.append("\n## Regel: Nur 1 Option anbieten. Nicht überfordern.")
    if pattern_output.get("add_sources"):
        system_parts.append("\n## Regel: Quellen und Herkunft explizit nennen.")
    if pattern_output.get("degradation"):
        missing = pattern_output.get("missing_slots", [])
        blocked = pattern_output.get("blocked_patterns", [])
        blocked_info = ""
        if blocked:
            blocked_info = " Blockierte Patterns: " + ", ".join(
                f"{b['id']} ({b['label']}, braucht: {', '.join(b['missing'])})"
                for b in blocked
            ) + "."
        system_parts.append(
            f"\n## Degradation aktiv: Fehlende Slots: {missing}.{blocked_info}\n"
            "PFLICHT-RUECKFRAGE: Dir fehlen Informationen fuer die gewuenschte Aufgabe.\n"
            "Deine Antwort MUSS eine DIREKTE FRAGE nach den fehlenden Infos enthalten.\n"
            "- Wenn 'thema' fehlt: Frage EXPLIZIT nach dem konkreten Thema.\n"
            "  Beispiel: 'Mathe, super! Welches Thema steht an — Bruchrechnung, Geometrie, Gleichungen?'\n"
            "- Wenn 'stufe' fehlt: Frage nach der Bildungsstufe — NICHT nach der Klassenstufe. "
            "(WLO-Inhalte sind nur auf Bildungsstufen-Ebene getaggt: Grundschule, Sek I, Sek II, "
            "Berufliche Bildung, Hochschule, Erwachsenenbildung.) Wenn der Nutzer trotzdem eine "
            "Klassenstufe nennt, uebernimm das Mapping still im Hintergrund.\n"
            "- Baue KEINEN Lernpfad oder Unterrichtsentwurf ohne konkretes Thema.\n"
            "- Die Frage soll am ANFANG deiner Antwort stehen, nicht versteckt am Ende.\n"
            "- Rufe KEINE Tools auf und zeige KEINE Materialien/Sammlungen an — die Rueckfrage\n"
            "  ist ein reiner Text-Dialog. Erst NACH der Antwort des Nutzers wird gesucht."
        )

    # RAG as tools: knowledge areas are presented as callable functions
    has_rag_tools = bool(available_rag_areas)
    if rag_context:
        # Memory context only (no blind RAG injection)
        system_parts.append(f"\n{rag_context}")

    # Guardrails (from config file, always last — not overridable)
    system_parts.append(guardrails)

    # Check if pattern explicitly has NO tools — or degradation blocks tool use
    _degradation_no_tools = bool(
        pattern_output.get("degradation")
        and pattern_output.get("missing_slots")
        and "thema" in pattern_output.get("missing_slots", [])
    )
    has_explicit_empty_tools = ("tools" in pattern_output and not pattern_output["tools"])
    pattern_wants_no_tools = _degradation_no_tools or (
        has_explicit_empty_tools and not (
            pattern_output.get("sources") and "mcp" in pattern_output["sources"]
        )
    )

    if pattern_wants_no_tools:
        if _degradation_no_tools:
            # Degradation: ask for missing info, no tool calls
            system_parts.append("""
## Antwort-Regeln
- Antworte NUR mit Text — rufe KEINE Tools auf.
- Stelle die Rueckfrage nach den fehlenden Informationen.
- Erfinde KEINE Sammlungen oder Materialien.

Antworte auf Deutsch. Formatiere mit Markdown.""")
        else:
            # Pattern like M15 Orientierungs-Guide: pure text, no tool calls
            system_parts.append("""
## Antwort-Regeln
- Antworte NUR mit flieszendem Text.
- Rufe KEINE Tools auf.
- Stelle die Faehigkeiten des Chatbots vor und biete konkrete Einstiegspunkte an.
- Erfinde KEINE Sammlungen oder Materialien.
- Schliesse mit einer offenen Frage die hilft, die Persona des Nutzers zu klaeren.
- WICHTIG: Antwortvorschlaege / Quick Replies werden automatisch als Buttons
  unter dem Text gerendert. Schreibe sie NIEMALS in den Antworttext
  (keine Liste wie "**Quick Replies:**", keine Aufzaehlung von Vorschlaegen).

Antworte auf Deutsch. Formatiere mit Markdown.""")
    else:
        # Inject collection context from session for chat-based browsing
        last_collections_json = session_state.get("entities", {}).get("_last_collections", "")
        collection_context = ""
        if last_collections_json:
            try:
                cols = json.loads(last_collections_json)
                col_lines = [f'  - "{c["title"]}" (nodeId: {c["node_id"]})' for c in cols]
                collection_context = f"""
## Verfuegbare Sammlungen aus vorherigen Ergebnissen
Der Nutzer hat diese Sammlungen bereits gesehen:
{chr(10).join(col_lines)}

Wenn der Nutzer "zeig mir die Inhalte von [Sammlung]" oder aehnlich sagt,
nutze get_collection_contents mit der passenden nodeId."""

            except (json.JSONDecodeError, KeyError):
                pass

        # Inject previously shown content items for learning path / lesson prep
        last_contents_json = session_state.get("entities", {}).get("_last_contents", "")
        if last_contents_json:
            try:
                contents = json.loads(last_contents_json)
                if contents:
                    content_lines = []
                    for i, c in enumerate(contents, 1):
                        types = ", ".join(c.get("learning_resource_types", [])) or "Material"
                        content_lines.append(
                            f'  {i}. "{c["title"]}" ({types})'
                            + (f' — {c["description"][:100]}' if c.get("description") else "")
                        )
                    collection_context += f"""

## Zuvor gezeigte Materialien
Der Nutzer hat diese Einzelinhalte in vorherigen Suchergebnissen gesehen:
{chr(10).join(content_lines)}

Wenn der Nutzer einen Lernpfad, eine Unterrichtsvorbereitung oder eine Strukturierung
dieser Materialien wuenscht, nutze diese Liste als Grundlage. Du kannst:
- Die Materialien in eine sinnvolle didaktische Reihenfolge bringen
- Lernziele fuer jeden Schritt formulieren
- Zeitvorschlaege machen
- Ergaenzende Materialien per search_wlo_content nachsuchen wenn noetig
Du musst dafuer KEINE neuen Such-Tools aufrufen — die Materialien sind bereits bekannt."""
            except (json.JSONDecodeError, KeyError):
                pass

        # Build knowledge area descriptions for the prompt
        knowledge_tool_desc = ""
        if available_rag_areas and rag_config:
            area_lines = []
            for area in available_rag_areas:
                desc = rag_config.get(area, {}).get("description", area)
                mode = rag_config.get(area, {}).get("mode", "on-demand")
                area_lines.append(f'  - query_knowledge(area="{area}"): {desc}')
            knowledge_tool_desc = "\n".join(area_lines)

        system_parts.append(f"""
## Verfuegbare Werkzeuge

Du hast zwei Arten von Werkzeugen:

### A) Wissensdatenbank (query_knowledge)
Internes Wissen aus hochgeladenen Dokumenten. Nutze diese Tools wenn die Frage
durch internes Wissen beantwortet werden kann (z.B. Prozesse, Konzepte, Richtlinien).
{knowledge_tool_desc if knowledge_tool_desc else '  (Keine Wissensbereiche verfuegbar)'}

### B) MCP-Tools (externe Suche & Datenquellen — WLO-MCP v2)
- search_wlo_collections: Kuratierte WLO-Sammlungen nach Thema suchen
- search_wlo_content: Einzelne Lernmaterialien suchen (Arbeitsblaetter, Videos, etc.)
- search_wlo_topic_pages: Themenseiten suchen oder pruefen ob eine Sammlung eine hat
  (per query ODER per collectionId; filtert nach targetGroup: teacher/learner/general;
   Varianten werden serverseitig gemerged)
- get_collection_contents: Inhalte einer Sammlung per nodeId abrufen
- get_node_details: Metadaten eines WLO-Knotens abrufen
- lookup_wlo_vocabulary: Filter-Werte nachschlagen (Faecher, Bildungsstufen, Lizenzen, Zielgruppen)
- get_subject_portals: Liste aller WLO-Fachportale (alphabetisch, mit nodeId)
- browse_collection_tree: Strukturierter Drilldown unter eine Sammlung (depth 1 oder 2)
- get_nodes_details: Bulk-Metadaten fuer mehrere nodeIds parallel
- wlo_health_check: Verfuegbarkeit/Latenz der WLO-API pruefen
{collection_context}

## Tool-Routing-Regeln

SCHRITT 1 — RICHTIGES WERKZEUG WAEHLEN (IN DIESER REIHENFOLGE PRUEFEN!):

1. ZUERST pruefen: Passt die Frage zu einem Wissensbereich in query_knowledge?
   Wenn ja → query_knowledge aufrufen! Beispiele:
   - "Was ist WirLernenOnline?" → query_knowledge(area="wirlernenonline.de-webseite", ...)
   - "Was macht edu-sharing?" → query_knowledge(area="edu-sharing-com-webseite", ...)
   - Jede Frage zu internen Prozessen, Konzepten, Dokumenten → query_knowledge
   WICHTIG: Die "always"-Bereiche werden beim Start AUTOMATISCH vorab durchsucht.
   Wenn du ein query_knowledge-Ergebnis mit "[Bereits durchsuchte Bereiche: ...]"
   siehst, sind diese Bereiche SCHON abgefragt — rufe query_knowledge fuer diese
   Bereiche NICHT nochmal auf! Nur fuer andere Bereiche oder bei einer ganz
   anderen Suchanfrage darfst du query_knowledge erneut aufrufen.

2. DANN: Frage nach Lernmaterialien, Sammlungen, OER-Inhalten?
   → search_wlo_collections oder search_wlo_content

3. DANN: Frage ueber WLO, edu-sharing, metaVentis als Plattform/Projekt?
   → query_knowledge mit dem passenden RAG-Bereich (wirlernenonline.de-webseite,
     edu-sharing-com-webseite, edu-sharing-net-webseite, wissenlebtonline-webseite).
     Es gibt KEINE MCP-Web-Crawler-Tools mehr.

4. NAVIGATION/UEBERBLICK statt Suche?
   → "Welche Faecher gibt es?" / "alle Fachportale" / "Uebersicht WLO":
     get_subject_portals (KEINE Suche, KEIN search_wlo_collections — die
     Top-Level-Portale stehen separat unter dem WLO-Wurzelknoten).
   → "Welche Themen unter X?" / "Bereiche unter Y" / "Wie ist Z gegliedert?":
     browse_collection_tree(nodeId=<X.id>, depth=1, includeContentCounts=true)
     — liefert die Sub-Sammlungen, NICHT die Files.
   → Bei "ist die WLO-API erreichbar?" / Diagnose: wlo_health_check.
   → Wenn du fuer >3 nodeIds Metadaten brauchst: get_nodes_details (Bulk
     statt N x get_node_details).

Du DARFST query_knowledge und MCP-Tools in derselben Antwort kombinieren!

SCHRITT 2 — REGELN:
1. Erfinde KEINE Materialien — nur was die Tools zurueckgeben.
2. SOFORT handeln: Wenn der User ein Thema nennt, rufe sofort das passende
   Tool auf. Keine Rueckfragen wenn du genug Kontext hast.
3. lookup_wlo_vocabulary nur fuer Filter-Werte, NIE als Ersatz fuer Suche.
4. Bei Sammlungs-Suche: ZUERST search_wlo_collections (kuratiert).
   search_wlo_content nur bei explizitem Wunsch nach Einzelmaterialien.
   NACH search_wlo_collections: Pruefe mit search_wlo_topic_pages(collectionId=...)
   ob die Top-Sammlungen Themenseiten haben. Liefere die URL wenn vorhanden.
5. DIREKTE Themenseiten-Suche: Wenn der User explizit nach "Themenseite",
   "Themenseiten" oder "Topic Page" fragt, rufe DIREKT search_wlo_topic_pages(query=...)
   auf — NICHT erst search_wlo_collections. Zeige die gefundenen Themenseiten mit URL.
   Wenn keine Themenseiten gefunden werden, sage das ehrlich und biete stattdessen
   eine Sammlungs-Suche an.
6. Frage NIE "Fuer welches Fach suchst du?" -- hoechstens nach dem Thema.
7. Wenn query_knowledge Ergebnisse liefert, nutze diese als Hauptquelle.
   Du kannst zusaetzlich MCP-Tools aufrufen um ergaenzende Materialien zu finden.
8. FILTER-PFLICHT bei medientyp (STRIKT): Wenn in den Entities ein `medientyp`
   gesetzt ist (z.B. "Video", "Arbeitsblatt", "Bild", "interaktiv",
   "Simulation", "Quiz", "Kurs"), gilt OHNE AUSNAHME:
   a) Ziel-Tool ist search_wlo_content (Sammlungen lassen sich nicht nach
      Inhaltstyp filtern — search_wlo_collections taugt NICHT als
      Fallback fuer medientyp-Anfragen).
   b) Uebergib den Wert als `learningResourceType`-Parameter an
      search_wlo_content. Der MCP-Server akzeptiert sowohl Labels als
      auch URIs — beides funktioniert:
        "Video", "Arbeitsblatt", "Bild", "Audio", "Interaktives medium",
        "Unterrichtsplan", "Quiz", "Kurs", "Praesentation", "Lernspiel",
        "Simulation", "Webseite", ...
      Wenn du dir bei der genauen Form unsicher bist, hilft
      lookup_wlo_vocabulary(vocabulary="lrt") — aber oft ist der Label
      ausreichend.
   c) WICHTIG: Der Parameter heisst `learningResourceType` (NICHT
      `resourceType`!). Der MCP-Server ignoriert den alten Namen.
   d) Rufe search_wlo_content NIE OHNE learningResourceType auf, wenn
      entities.medientyp gesetzt ist — auch nicht als Fallback nach
      leerem search_wlo_collections-Ergebnis.
   e) Wenn kein passender Eintrag gefunden wird, weise kurz im
      Antworttext darauf hin ("Ich konnte nicht exakt nach '<medientyp>'
      filtern") und suche ungefiltert.
9. Fach & Bildungsstufe als Filter: Wenn entities `fach` bzw. `stufe` enthalten,
   setze sie als `discipline` bzw. `educationalContext` (NICHT
   `educationalLevel`!) in search_wlo_content / search_wlo_collections.
   Der MCP-Server akzeptiert sowohl Klartext-Labels ("Mathematik",
   "Sekundarstufe I") als auch URIs aus lookup_wlo_vocabulary. Eine
   Filter-Ebene "Klassenstufe" gibt es NICHT — mappe Klassenangaben
   immer auf die Bildungsstufe (Kl. 1-4=Grundschule, 5-10=Sek I,
   11-13=Sek II).

Antworte auf Deutsch. Formatiere mit Markdown.""")

    # ── Recency-Anker (2026-05-23) — Pattern-Brief noch einmal ans Ende ──
    # Bei 22k+ Token Prompt sinkt die Befolgung der Layer-4-Direktive. Das
    # LLM liest die letzten Anweisungen am genauesten (recency bias). Wir
    # spiegeln deshalb den Kern des Pattern-Briefs hier als „LETZTE
    # ERINNERUNG" — Anti-Patterns und Antwort-Schema bleiben dominant.
    _body_recap = (pattern_output.get("body_md") or "").strip()
    if _body_recap:
        system_parts.append(f"""
## ⚡ LETZTE ERINNERUNG — verbindlich vor jeder Antwort

Aktives Pattern: **{pattern_label}**.

Du musst dich strikt an folgenden Pattern-Brief halten. Andere
Direktiven in diesem Prompt (z.B. „nutze RAG reich aus", „füge
URL-Links ein") gelten NUR im Rahmen dessen, was der Pattern-Brief
zulässt. Wenn der Pattern-Brief sagt „max. 2 Sätze" oder „keine
Material-Aufzählung", dann **gilt das**, auch wenn das Wissen für eine
lange Antwort vorhanden wäre.

{_body_recap}
""")

    system = "\n".join(system_parts)
    _log_system_prompt_size("response", system)

    # Determine which tools to offer
    # (module-level _logger is already imported at top of file — keep this
    # local re-import for backwards compat with existing _logger.* calls
    # below in this function.)
    import logging as _log
    _logger = _log.getLogger(__name__)

    # In MCP-v2 there are no more Web-Crawler "info tools" — Plattform-/
    # Projekt-Themen werden ausschliesslich vom RAG-Kontext (query_knowledge)
    # abgedeckt. Daher leeres Set, das wir aber als Variable behalten,
    # damit die Set-Vereinigungen unten weiterhin funktionieren ohne
    # Sonderfaelle.
    INFO_TOOLS: set[str] = set()
    active_tools = []
    has_explicit_tools = "tools" in pattern_output
    has_mcp_source = pattern_output.get("sources") and "mcp" in pattern_output["sources"]

    if pattern_output.get("tools"):
        # Pattern defines specific tools → use those
        tool_names = set(pattern_output["tools"]) | INFO_TOOLS
        active_tools = [t for t in TOOL_DEFINITIONS if t["function"]["name"] in tool_names]
    elif has_explicit_tools and not pattern_output["tools"]:
        # Pattern explicitly set tools=[] → NO tools (e.g. M15 Orientierungs-Guide)
        active_tools = []
    elif has_mcp_source:
        active_tools = TOOL_DEFINITIONS
    else:
        # Fallback: search + topic pages
        fallback_tools = {"search_wlo_collections", "search_wlo_topic_pages"} | INFO_TOOLS
        active_tools = [t for t in TOOL_DEFINITIONS if t["function"]["name"] in fallback_tools]

    # ── Route medientyp queries away from search_wlo_collections ──────
    # Sammlungen (collections) cannot be filtered by resourceType, so if the
    # classifier extracted a medientyp the only correct path is
    # search_wlo_content. Removing the collection tool here prevents the
    # LLM from "falling back" to collections when content search could
    # satisfy the filter — a pattern we saw it enter after empty
    # collection results.
    _classif_entities_top = classification.get("entities", {}) or {}
    if _classif_entities_top.get("medientyp"):
        before = {t["function"]["name"] for t in active_tools}
        # Welle C.5+ (2026-05-22): zusätzlich ``search_wlo_topic_pages``
        # entfernen. Bei medientyp-Fokus will der User Einzelinhalte mit
        # konkretem Filter — Themenseiten-Vorschläge sind ähnlich
        # irreführend wie Sammlungs-Vorschläge (siehe User-Feedback:
        # „auf 'nur videos bitte' sollte der Bot KEINE Sammlungen oder
        # Themenseiten anzeigen oder im Prompt berücksichtigen").
        _strip_in_type_focus = {
            "search_wlo_collections",
            "search_wlo_topic_pages",
        }
        active_tools = [
            t for t in active_tools
            if t["function"]["name"] not in _strip_in_type_focus
        ]
        removed = before - {t["function"]["name"] for t in active_tools}
        if removed:
            _logger.info(
                "medientyp=%r → removed %s from active_tools to force content search",
                _classif_entities_top.get("medientyp"), sorted(removed),
            )
        # Ensure search_wlo_content is available even if pattern didn't list it.
        if not any(t["function"]["name"] == "search_wlo_content" for t in active_tools):
            for td in TOOL_DEFINITIONS:
                if td["function"]["name"] == "search_wlo_content":
                    active_tools.append(td)
                    _logger.info("medientyp set — added search_wlo_content to active_tools")
                    break

    # ── Pattern-Sources-Gate (Welle C.5+, 2026-05-22) ─────────────
    # Wenn das aktive Pattern ``sources`` deklariert hat UND "rag" NICHT
    # darin steht, schalten wir die RAG-Pipeline komplett aus — weder
    # Prefetch noch ``query_knowledge``-Tool werden bereitgestellt.
    # Patterns ohne ``sources``-Deklaration (Default) bekommen alles.
    _pattern_sources_decl = pattern_output.get("sources")
    _rag_allowed_for_pattern = (
        _pattern_sources_decl is None
        or "rag" in _pattern_sources_decl
    )
    # ── Add RAG knowledge areas as virtual tools ──────────────────
    if available_rag_areas and rag_config and _rag_allowed_for_pattern:
        area_descriptions = []
        for area in available_rag_areas:
            desc = rag_config.get(area, {}).get("description", f"Wissensbereich: {area}")
            area_descriptions.append(f"{area}: {desc}")

        knowledge_tool = {
            "type": "function",
            "function": {
                "name": "query_knowledge",
                "description": (
                    "PRIMAERE WISSENSQUELLE: Durchsuche die interne Wissensdatenbank. "
                    "Rufe dieses Tool ZUERST auf bevor du externe Such-Tools nutzt! "
                    "Nutze es bei Fragen zu: internem Wissen, Prozessen, Richtlinien, "
                    "Konzepten, Dokumenten, rechtlichen Themen, Qualitaetssicherung. "
                    "Verfuegbare Bereiche: "
                    + "; ".join(area_descriptions)
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "area": {
                            "type": "string",
                            "description": "Wissensbereich. Verfuegbar: " + ", ".join(available_rag_areas),
                            "enum": available_rag_areas,
                        },
                        "query": {
                            "type": "string",
                            "description": "Suchanfrage an die Wissensdatenbank",
                        },
                    },
                    "required": ["area", "query"],
                },
            },
        }
        active_tools = [knowledge_tool] + active_tools  # Knowledge first!

    # ── Curation-Tool: select_top_cards (immer verfügbar) ─────────────
    # Im Inline-Mode ist der Tool-Call obligatorisch — sonst weiß das
    # Backend nicht, welche IDs als Inline-Links gerendert werden sollen.
    # Im Kachel-Mode ist der Call optional, dient aber als Re-Rank-Hint
    # für Card-Pipeline v2: wenn das LLM eine thematisch sinnvolle
    # Reihenfolge der 5 besten Treffer angibt, übernimmt v2 die.
    # Wird das Tool nicht aufgerufen, wählt v2 deterministisch nach
    # Relevance-Score (Title/Keywords/Disciplines/Description-Match).
    if _cards_inline_mode:
        _select_description_lead = (
            "FINAL-SELECTION für Inline-Modus. RUFE DIESES TOOL NACH "
            "DEN SEARCH-TOOLS AUF. Wähle aus den eben gefundenen "
            "Treffern 1-5 IDs aus, in der Reihenfolge in der sie dem "
            "User gezeigt werden sollen. Wenn du gar nichts gefunden "
            "hast, RUFE DIESES TOOL NICHT — antworte stattdessen mit "
            "einer Klärungsfrage.\n\n"
            "**Wenn etwas gefunden wurde, ist dieser Tool-Call "
            "obligatorisch.** Ohne diesen Call sieht der User keinen "
            "Link — nur deinen Text."
        )
    else:
        _select_description_lead = (
            "RE-RANK-HINT für Kachel-Modus. Optional aufrufbar, NACHDEM "
            "die Search-Tools Treffer geliefert haben. Wenn du eine "
            "thematisch sinnvolle Reihenfolge der 5 passendsten Treffer "
            "hast (z.B. Sammlung zum Thema zuerst, dann passende Einzel-"
            "inhalte), übergib sie hier — das Backend ordnet die Kacheln "
            "dann genau in dieser Reihenfolge an. Wenn du keine Präferenz "
            "hast oder die Treffer ohnehin schon thematisch matchen, "
            "kannst du den Call weglassen — das Backend wählt dann "
            "deterministisch nach Relevance-Score (Title/Keywords/"
            "Disciplines-Match).\n\n"
            "**Nur sinnvoll, wenn echte Treffer da sind.** Bei "
            "Klärungs-Turn / leeren Tool-Results: nicht aufrufen."
        )
    select_cards_tool = {
        "type": "function",
        "function": {
            "name": "select_top_cards",
            "description": (
                _select_description_lead + "\n\n"
                "AUSWAHL-REGELN:\n"
                "1. **ZIEL: bis zu 5 IDs** — wenn die Tools genug geliefert "
                "haben. Aber auch 1, 2 oder 3 sind OK, wenn wirklich nicht "
                "mehr Passendes da ist. Lieber wenige gute als gar keine.\n"
                "2. **Typ-Priorität (DEFAULT)**: Themenseiten zuerst "
                "(geben Überblick), dann Sammlungen, dann Einzelinhalte. "
                "Themenseiten erkennst du an Tool-Result-Einträgen mit "
                "node_type='collection' UND nicht-leerem topic_pages-Array.\n"
                "3. **MIX**: Wenn nur 1 Themenseite oder 1 Sammlung "
                "perfekt passt, fülle die freien Slots mit passenden "
                "Einzelinhalten auf (z.B. 1 Sammlung + 3 Einzelinhalte). "
                "1 Sammlung + Mix von Einzelinhalten ist meist besser als "
                "nur 1 Sammlung alleine.\n"
                "4. AUSNAHME (Typ-Fokus): Wenn der User explizit nach "
                "Material-Typ fragt (Video, Arbeitsblatt, Übung, Quiz, "
                "Audio, Präsentation, Interaktiv, Kurs) → bis zu 5 "
                "Einzelinhalte dieses Typs, KEINE Themenseiten/Sammlungen "
                "dazwischen.\n"
                "5. Klar Unpassendes (falsches Fach, falsche Klassenstufe) "
                "weglassen. Thematisch verwandte Treffer sind erlaubt.\n\n"
                "Die IDs sind die ``node_id``-Werte aus den search-Tool-"
                "Ergebnissen — exakt im UUID-Format wie geliefert."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "card_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "1-5 node_ids in Anzeige-Reihenfolge. Erste ID "
                            "wird oben angezeigt."
                        ),
                        "minItems": 1,
                        "maxItems": 5,
                    },
                    "reasoning": {
                        "type": "string",
                        "description": (
                            "1 Satz: warum diese Auswahl in dieser "
                            "Reihenfolge — landet im Debug-Log."
                        ),
                    },
                },
                "required": ["card_ids"],
            },
        },
    }
    # Perf-Schalter: select_top_cards ist im Kachel-Modus nur ein OPTIONALER
    # Re-Rank-Hint (sonst wählt das Backend deterministisch nach MCP-Ranking).
    # Mit CHAT_DISABLE_SELECT_TOP_CARDS=1 lässt sich dieser zusätzliche
    # LLM-Tool-Turn abschalten → ~1 Round-Trip/Such-Turn schneller (zum
    # Messen/Tunen). Default: an (Verhalten unverändert).
    if (os.getenv("CHAT_DISABLE_SELECT_TOP_CARDS") or "").strip() not in ("1", "true", "True"):
        active_tools.append(select_cards_tool)
    else:
        _logger.info(
            "select_top_cards via CHAT_DISABLE_SELECT_TOP_CARDS deaktiviert — "
            "Backend nutzt deterministische Karten-Auswahl (MCP-Ranking)."
        )

    # Combined-output tool (opt-in) — see env CHAT_INLINE_QUICK_REPLIES.
    # When enabled, the model is instructed to call ``respond_to_user`` for
    # the FINAL answer instead of plain content, with both ``text`` and
    # ``quick_replies`` in one shot. This saves the separate quick_replies
    # LLM round-trip (~1-2s) for ~70% of turns. Default OFF until measured.
    _inline_qr_enabled = (
        (os.getenv("CHAT_INLINE_QUICK_REPLIES") or "").strip() in ("1", "true", "yes")
    )
    if _inline_qr_enabled:
        respond_tool = {
            "type": "function",
            "function": {
                "name": "respond_to_user",
                "description": (
                    "FINALE Antwort an den Nutzer. Nutze dieses Tool NUR wenn du "
                    "alle nötigen Such-/Vokabular-/Knowledge-Tools bereits gerufen "
                    "hast und die finale Antwort fertig ist. Liefere die Markdown-"
                    "formatierte Antwort als ``text`` und 2-4 kurze nutzerseitige "
                    "Folgevorschläge als ``quick_replies`` (max 6-8 Wörter pro "
                    "Vorschlag, vom NUTZER formuliert — der Text MUSS so klingen, "
                    "als würde der Nutzer ihn selbst tippen, z.B. 'Mehr davon "
                    "zeigen', 'Anderes Thema wählen', 'Ja, gerne', 'Nein danke'). "
                    "ANREDE-REGEL (kritisch): Der Nutzer spricht BOERDi mit DU an, "
                    "nicht mit Sie — auch wenn die Persona-Modulation 'siezen' "
                    "auf den BOT-Text gesetzt ist (das gilt nur für die Antwort "
                    "des Bots an den Nutzer, NICHT für die Pillen-Vorschläge). "
                    "Quick-Replies dürfen daher NICHT 'Können Sie mir helfen?' "
                    "enthalten, sondern 'Kannst du mir helfen?' / 'Zeig mir mehr' / "
                    "'Erklär mir den Unterschied'. Du-Form ist Pflicht. "
                    "Wenn keine Folgevorschläge passen (z.B. CRISIS), gib leere Liste. "
                    "BRING-MICH-HIN-VORSCHLAG: Wenn deine Antwort eine konkrete "
                    "WLO-Webseiten-URL adressiert (z.B. /themenseite/<slug>, "
                    "/fachportale, /mitmachen, /ueber-uns), darfst du EINEN Eintrag "
                    "in folgendem Spezialformat einfügen: "
                    "``__guide__|<kurzer Anzeigetext>|<vollständige URL>`` — "
                    "Frontend rendert das als hervorgehobenen Same-Tab-Navigations-"
                    "Button. Beispiel: "
                    "``__guide__|Themenseite Klimawandel|https://wirlernenonline.de/themenseite/klimawandel``. "
                    "Nutze NUR vollständige URLs (Schema + Host), keine relativen "
                    "Pfade. Maximal EIN solcher Eintrag pro Antwort."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": (
                                "Die Markdown-formatierte Antwort an den Nutzer. "
                                "WICHTIG: Schreibe die Folgevorschläge (quick_replies) "
                                "und den ``__guide__``-Link NICHT zusätzlich in den "
                                "text — die erscheinen separat als Pillen/Buttons UNTER "
                                "der Antwort. Der text endet mit dem letzten "
                                "inhaltlichen Satz; KEINE aufgelisteten Klick-Optionen "
                                "am Ende (kein 'Zeig mir mehr' / 'Anderes Thema wählen' "
                                "und keine 'Bring mich hin:'-Zeile)."
                            ),
                        },
                        "quick_replies": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "2-4 kurze Folgevorschläge. Jeder Vorschlag ist ein "
                                "Satz, den der Nutzer als nächste Eingabe sagen würde "
                                "(NICHT was der Bot vorschlägt zu tun). "
                                "ANREDE: Du-Form, weil der Nutzer den Bot duzt — "
                                "auch dann, wenn die Bot-Antwort selbst siezt. "
                                "Beispiele: 'Zeig mir mehr', 'Anderes Thema wählen', "
                                "'Kannst du das genauer erklären?'. KEINE Sie-Form "
                                "wie 'Können Sie mir ...?' / 'Zeigen Sie mir ...'. "
                                "EIN Eintrag darf optional ein Bring-mich-hin-"
                                "Spezialformat sein: ``__guide__|<Label>|<URL>`` — "
                                "siehe Tool-Description."
                            ),
                            "minItems": 0,
                            "maxItems": 4,
                        },
                    },
                    "required": ["text"],
                },
            },
        }
        active_tools = active_tools + [respond_tool]

    messages = [{"role": "system", "content": system}]

    # Inject the current canvas state as an additional system context.
    # This lets the LLM reference or modify what the user currently sees
    # in the canvas pane (material text, card grid), not just the chat history.
    if canvas_state and canvas_state.get("mode") and canvas_state.get("mode") != "empty":
        c_mode = canvas_state.get("mode")
        c_title = (canvas_state.get("title") or "").strip()
        c_type = (canvas_state.get("material_type") or "").strip()
        c_md = (canvas_state.get("markdown") or "").strip()
        c_cards = canvas_state.get("cards_count") or 0
        parts = [
            f"Canvas-Modus: {c_mode}",
        ]
        if c_title: parts.append(f"Titel: {c_title}")
        if c_type:  parts.append(f"Material-Typ: {c_type}")
        if c_mode == "cards":
            parts.append(f"Angezeigte Kacheln: {c_cards}")
        if c_md and c_mode != "cards":
            parts.append("Aktueller Canvas-Inhalt (Markdown):\n" + c_md[:4000])
        canvas_ctx = (
            "[Kontext: Canvas-Pane rechts im Widget]\n" + "\n".join(parts) +
            "\n\nDer Nutzer sieht diesen Canvas-Inhalt parallel zum Chat. "
            "Wenn er sich mit 'hier', 'das', 'die Aufgabe', 'der Text' o.ae. "
            "auf Canvas-Inhalte bezieht, antworte direkt darauf. Verweise auf "
            "einzelne Abschnitte/Aufgaben/Kacheln, wenn hilfreich."
        )
        messages.append({"role": "system", "content": canvas_ctx})

    for h in history[-10:]:
        messages.append(h)

    # ── Pre-fetch only "always" areas, on-demand areas via LLM tool call ──
    # "always" areas: pre-fetched and injected (guaranteed to be available)
    # "on-demand" areas: only queried when LLM explicitly calls query_knowledge
    knowledge_prefetched = False
    always_areas: list[str] = []  # tracked for redundant-call guard in tool loop
    # Retrieval-Defaults — ueberschreibbar via ENV oder rag-config.yaml
    # (siehe app.services.rag_service.get_retrieval_settings). Aktuelle
    # Werte bleiben 15 / 0.30, damit bestehende Installationen unveraendert laufen.
    from app.services.rag_service import get_retrieval_settings as _get_rag_settings
    _rag_settings = _get_rag_settings()
    _RAG_TOP_K = _rag_settings["top_k"]
    _RAG_MIN_SCORE = _rag_settings["min_score"]
    _RAG_MAX_CHARS_PER_AREA = _rag_settings["max_chars_per_area"]
    # Pattern-Gate-Log + Prefetch-Trigger (siehe Berechnung oben).
    _logger.info(
        "rag-prefetch-gate: pattern=%s sources=%r → allowed=%s",
        pattern_output.get("pattern_id") or pattern_label,
        _pattern_sources_decl,
        _rag_allowed_for_pattern,
    )
    if available_rag_areas and rag_config and _rag_allowed_for_pattern:
        always_areas = [a for a in available_rag_areas if rag_config.get(a, {}).get("mode") == "always"]

        if always_areas:
            from app.services.rag_service import get_rag_context as _get_rag_ctx
            # Side-channel out_sources: collect the filenames of the top
            # chunks the prefetch picked. Used downstream by
            # ``_attach_guide_qr`` (chat.py) to surface the EXACT source
            # URL via ``rag_url_index``, instead of the generic
            # Domain-Hauptseite.
            _prefetch_sources: list[str] = []
            prefetch_ctx = await _get_rag_ctx(
                message, areas=always_areas, top_k=_RAG_TOP_K,
                min_score=_RAG_MIN_SCORE,
                max_chars_per_area=_RAG_MAX_CHARS_PER_AREA,
                out_sources=_prefetch_sources,
            )
            if _prefetch_sources:
                used_src = session_state.setdefault("_rag_top_sources", [])
                for s in _prefetch_sources:
                    if s not in used_src:
                        used_src.append(s)
            _logger.info("RAG pre-fetch for areas %s: %d chars", always_areas, len(prefetch_ctx) if prefetch_ctx else 0)
            if prefetch_ctx:
                knowledge_prefetched = True
                # Track prefetched areas in session_state so the Guide-QR
                # injector (chat.py:_attach_guide_qr) sieht sie als
                # *Kandidaten*. Es ist nicht garantiert, dass der Bot die
                # Quelle wirklich nutzt — der Injektor prüft anschließend
                # via Brand-Regex am Bot-Response-Text, ob die Area
                # tatsächlich verwendet wurde.
                used = session_state.setdefault("_rag_areas_used", [])
                for _a in always_areas:
                    if _a and _a not in used:
                        used.append(_a)
                # Inject as a completed tool call — tell the LLM ALL always-areas were searched
                areas_label = ", ".join(always_areas)
                messages.append({"role": "user", "content": message})
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "prefetch_knowledge",
                        "type": "function",
                        "function": {
                            "name": "query_knowledge",
                            "arguments": json.dumps({
                                "area": always_areas[0],
                                "query": message,
                            }),
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": "prefetch_knowledge",
                    "content": (
                        f"[Bereits durchsuchte Bereiche: {areas_label}]\n\n"
                        + prefetch_ctx[:12000]
                    ),
                })

    if not knowledge_prefetched:
        messages.append({"role": "user", "content": message})

    # Tools deren Ergebnis im inline_result_grouping-Modus Einzelinhalt-
    # Details enthalten könnte und damit Quellen für "Arbeitsblatt"-/
    # "Video"-/"Inhalt"-Leakage in den Bot-Text sind. Nicht enthalten:
    # search_wlo_collections / _topic_pages / browse_collection_tree /
    # get_subject_portals — deren Treffer SIND als Boxen sichtbar, der
    # User sieht also was beschrieben wird.
    _EINZELINHALT_LEAK_TOOLS = {
        "search_wlo_content",      # primärer Treffer-Pool für Einzelmaterialien
        "get_collection_contents",  # Sammlung-Inhalte = i.d.R. Einzelmaterialien
        "get_node_details",        # Detail-View eines konkreten (oft Einzel-)Knotens
    }

    def _is_einzelinhalt_card(c: dict) -> bool:
        """True wenn die Card im Frontend als Einzelinhalt rendert (also NICHT
        in den sichtbaren Boxen erscheint, nur über die Such-CTA erreichbar
        ist). Spiegelt die Frontend-Klassifikation ``isInhalt`` aus
        ``chat.component.ts``: node_type != 'collection'."""
        nt = (c.get("node_type") or "").strip().lower()
        if nt == "collection":
            return False
        # Topic-pages werden im Frontend als Themenseiten gerendert (sichtbar).
        if c.get("topic_pages"):
            return False
        return True

    def _is_themenseite_card(c: dict) -> bool:
        """Frontend-Spiegel: collection + topic_pages-Variants vorhanden."""
        return (c.get("node_type") == "collection"
                and bool(c.get("topic_pages")))

    def _is_pure_sammlung_card(c: dict) -> bool:
        """Frontend-Spiegel: collection ohne topic_pages."""
        return (c.get("node_type") == "collection"
                and not c.get("topic_pages"))

    def _ui_box_state_footer(cards: list[dict]) -> str:
        """Strukturierte Beschreibung dessen, was der User NACH diesem Tool-
        Call in den Result-Group-Boxen tatsächlich sieht. Wird im
        inline_grouping_mode an JEDE Tool-Result-Message angehängt, damit
        die LLM bei der Text-Generation **nur über tatsächlich Sichtbares**
        spricht (Anti-Hallucination, vgl. User-Feedback 2026-05-21:
        Bot kündigte „zwei Sammlungen" an, UI zeigte keine).

        Nicht für Card-Aufzählung — nur Counts pro Box-Typ. Reihenfolge
        entspricht der Render-Reihenfolge im Chat (Themenseiten >
        Sammlungen > Webseiten-Inhalte > Such-CTA)."""
        if not _inline_grouping_mode:
            return ""
        n_topic = sum(1 for c in cards if _is_themenseite_card(c))
        n_coll = sum(1 for c in cards if _is_pure_sammlung_card(c))
        n_content = sum(1 for c in cards if _is_einzelinhalt_card(c))
        return (
            "\n\n[UI-BOX-STATUS nach diesem Tool-Call — gilt fuer deinen "
            "Antwort-Text]: "
            f"{n_topic} Themenseite(n) sichtbar, "
            f"{n_coll} Sammlung(en) sichtbar, "
            f"{n_content} Einzelinhalt(e) NICHT sichtbar (nur via Such-CTA "
            "zur externen Suche erreichbar). "
            "WAHRHEITSPFLICHT: Sprich im Text nur ueber die sichtbaren "
            "Boxen UND verweise auf die Such-CTA, wenn der User nach "
            "Einzelinhalten / Material-Typen gefragt hat. NIEMALS "
            "Sammlungen/Themenseiten erfinden, die der UI-Status nicht "
            "zeigt — das ist eine Halluzination."
        )

    def _redact_search_content_for_llm(
        name: str, raw_text: str, parsed_cards: list[dict],
    ) -> str:
        """Im inline_result_grouping-Modus die Einzelinhalte aus dem
        LLM-sichtbaren Tool-Result-Text rausziehen — die Cards selbst
        bleiben in ``all_cards`` / Prefetch-Akkumulatoren erhalten, sodass
        Such-CTA-Count und Lernpfad-Generator (separater Flow) weiter
        Zugriff haben.

        Greift wenn:
          - inline_result_grouping-Modus aktiv UND
          - Tool gehört zu den Einzelinhalt-Quellen UND
          - die geparsten Cards enthalten mindestens 1 Einzelinhalt.

        Tools mit ausschließlich Sammlungen/Themenseiten (search_wlo_collections,
        search_wlo_topic_pages, browse_collection_tree, get_subject_portals)
        werden NICHT redacted — der User SIEHT diese Treffer.
        """
        if not (_inline_grouping_mode and parsed_cards):
            return raw_text[:4000]
        if name not in _EINZELINHALT_LEAK_TOOLS:
            return raw_text[:4000]
        einzel = [c for c in parsed_cards if _is_einzelinhalt_card(c)]
        if not einzel:
            # Tool steht zwar auf der Leak-Liste, aber konkret nur Sammlungen
            # zurückgekommen → keine Redaction nötig (z.B. get_collection_contents
            # einer Meta-Sammlung).
            return raw_text[:4000]
        n = len(einzel)
        types: dict[str, int] = {}
        for c in einzel:
            lrt = (c.get("lrt_label")
                   or c.get("learning_resource_type")
                   or "Inhalt")
            types[lrt] = types.get(lrt, 0) + 1
        type_summary = ", ".join(
            f"{k}x {t}" for t, k in sorted(
                types.items(), key=lambda x: -x[1],
            )[:5]
        ) or "verschiedene Typen"
        _logger.info(
            "inline_grouping: redacted %s (n=%d einzelinhalte, types=%s)",
            name, n, type_summary,
        )
        return (
            f"OK - {name} lieferte {n} Einzelinhalte "
            f"({type_summary}). Diese sind im Backend gespeichert "
            "und werden NICHT als sichtbare Items angezeigt - der "
            "User erreicht sie nur ueber die Such-CTA. WICHTIG: "
            "Du darfst diese Einzelinhalte NICHT im Antwort-Text "
            "erwaehnen, zaehlen oder typisieren (kein 'ein Video', "
            "'ein Arbeitsblatt', 'zwei Materialien', 'eine Aufgabe'). "
            "Sprich im Text NUR ueber Themenseiten und Sammlungen."
        )

    # ── Speculative MCP prefetch injection ─────────────────────────
    # If chat.py spawned a speculative MCP search in parallel with safety
    # and pattern selection, the result lands here as `prefetched_tool`.
    # We inject it as a completed assistant tool-call so the LLM sees the
    # data already available and (in most cases) skips its own tool round.
    mcp_prefetched = False
    mcp_prefetch_cards: list[dict] = []
    if (
        prefetched_tool
        and prefetched_tool.get("name")
        and prefetched_tool.get("result_text")
        and prefetched_tool["name"] not in (blocked_tools or [])
    ):
        _name = prefetched_tool["name"]
        _args = prefetched_tool.get("arguments") or {}
        _txt = prefetched_tool["result_text"]
        try:
            # Welle E v4+12 (Sprint K rev2, 2026-05-27): Topic-Pages-
            # Primary-Prefetch braucht ``parse_wlo_topic_page_cards``,
            # damit das ``topic_pages``-Variant-Array gefüllt wird — sonst
            # rendert das Frontend die Cards als „Sammlung" statt
            # „Themenseite". Bug-Befund: bei „Klimawandel"-Suche feuerte
            # der Primary-Tool ``search_wlo_topic_pages`` korrekt, aber
            # ``parse_wlo_cards`` verlor die Variant-Annotation → keine
            # Themenseiten-Box im Chat-Widget.
            if _name == "search_wlo_topic_pages":
                from app.services.mcp_client import parse_wlo_topic_page_cards as _ptp
                mcp_prefetch_cards = _ptp(_txt) or []
            else:
                mcp_prefetch_cards = parse_wlo_cards(_txt) or []
            await resolve_discipline_labels(mcp_prefetch_cards)
            if _name == "search_wlo_collections":
                for c in mcp_prefetch_cards:
                    c.setdefault("node_type", "collection")
        except Exception:
            mcp_prefetch_cards = []
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "prefetch_mcp",
                "type": "function",
                "function": {
                    "name": _name,
                    "arguments": json.dumps(_args),
                },
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": "prefetch_mcp",
            "content": _redact_search_content_for_llm(_name, _txt, mcp_prefetch_cards),
        })
        mcp_prefetched = True

    # Extra-prefetches — Themenseiten + Einzelinhalte (oder die jeweils
    # andere Kombination) laufen in chat.py parallel zum primary spec_task.
    # Wir injizieren JEDEN als simulated tool call, damit der LLM den
    # GESAMTEN Treffer-Pool (Themenseite + Sammlung + Einzelinhalt) im
    # current turn sieht. Effekt: er kann fundiert 5 IDs auswählen, kennt
    # die Titel/Beschreibungen für seine Intro-Prosa, UND kann in folge-
    # turns auf jeden einzelnen Treffer per node_id Bezug nehmen (z.B.
    # für Remix-Anfragen).
    prefetched_extras_cards: list[dict] = []
    if prefetched_extras:
        from app.services.mcp_client import parse_wlo_topic_page_cards as _ptp
        for _i, _ex in enumerate(prefetched_extras):
            _ex_name = _ex.get("name") or ""
            _ex_args = _ex.get("arguments") or {}
            _ex_text = _ex.get("result_text") or ""
            if not _ex_name or not _ex_text:
                continue
            if _ex_name in (blocked_tools or []):
                continue
            # Cards parsen mit dem richtigen Parser. topic_pages liefert
            # variant-Arrays, normale Such-Tools nicht.
            try:
                if _ex_name == "search_wlo_topic_pages":
                    _ex_cards = _ptp(_ex_text) or []
                else:
                    _ex_cards = parse_wlo_cards(_ex_text) or []
                await resolve_discipline_labels(_ex_cards)
                if _ex_name == "search_wlo_collections":
                    for _c in _ex_cards:
                        _c.setdefault("node_type", "collection")
            except Exception:
                _ex_cards = []
            prefetched_extras_cards.extend(_ex_cards)
            # In messages als simulated tool call einbinden — eindeutige
            # tool_call_id pro extra, damit OpenAI's tool-result-pairing
            # nicht durcheinanderkommt.
            _tc_id = f"prefetch_extra_{_i}"
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": _tc_id,
                    "type": "function",
                    "function": {
                        "name": _ex_name,
                        "arguments": json.dumps(_ex_args),
                    },
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": _tc_id,
                "content": _redact_search_content_for_llm(_ex_name, _ex_text, _ex_cards),
            })

    # Tool calling loop
    # mcp_prefetch_cards = primary; prefetched_extras_cards = extras.
    # Beide dedupen per node_id, damit Mehrfach-Listing nicht passiert
    # (gleicher Treffer kann z.B. in collections- UND content-Suche
    # auftauchen).
    all_cards: list[dict] = []
    _seen_ids: dict[str, dict] = {}
    for _c in list(mcp_prefetch_cards) + list(prefetched_extras_cards):
        _nid = _c.get("node_id") if isinstance(_c, dict) else None
        if _nid and _nid in _seen_ids:
            _existing = _seen_ids[_nid]
            if not _existing.get("topic_pages") and _c.get("topic_pages"):
                _existing["topic_pages"] = _c["topic_pages"]
            if not _existing.get("topic_page_url") and _c.get("topic_page_url"):
                _existing["topic_page_url"] = _c["topic_page_url"]
            continue
        if _nid:
            _seen_ids[_nid] = _c
        all_cards.append(_c)
    # UI-Box-Status nach Prefetch-Phase: separate ``role: system``-Message,
    # damit die LLM gleich beim ersten Tool-Loop-Schritt weiß, was nach
    # Prefetch sichtbar wäre. Greift nur im inline_grouping_mode — sonst
    # wäre die Info redundant (Tile-Cards werden flach gerendert).
    _initial_footer = _ui_box_state_footer(all_cards)
    if _initial_footer.strip():
        messages.append({
            "role": "system",
            "content": (
                "Status der UI-Boxen aus den Prefetch-Tool-Calls:"
                + _initial_footer
            ),
        })
    tools_called: list[str] = []
    outcomes: list = []  # ToolOutcome list (Triple-Schema T-23)
    if knowledge_prefetched:
        tools_called.append("query_knowledge (prefetch)")
    if mcp_prefetched:
        tools_called.append(f"{prefetched_tool['name']} (prefetch)")
        from app.models.schemas import ToolOutcome
        outcomes.append(ToolOutcome(
            tool=prefetched_tool["name"],
            status="success" if mcp_prefetch_cards else "empty",
            item_count=len(mcp_prefetch_cards),
        ))
    if prefetched_extras:
        from app.models.schemas import ToolOutcome
        for _ex in prefetched_extras:
            _ex_name = _ex.get("name") or "?"
            tools_called.append(f"{_ex_name} (prefetch-extra)")
            outcomes.append(ToolOutcome(
                tool=_ex_name,
                status="success",
                item_count=0,  # zähle hier nicht detailliert — primary deckt's ab
            ))
    max_iterations = 5
    first_iteration = True
    # Phase A1 — Reflection-Loop-Flag: nur EINMAL retryen, sonst Endlosschleife
    _reflection_done = False

    for iteration in range(max_iterations):
        tool_choice: Any = None
        if active_tools:
            # Force tool call on first iteration — but NOT if context is already available
            # (pre-fetched knowledge or prior content cards already provide context)
            has_prior_content = bool(session_state.get("entities", {}).get("_last_contents"))
            # Pattern-Override: Discovery/Listing-Patterns brauchen IMMER den
            # echten Tool-Output (Karten), auch wenn RAG-Kontext da ist —
            # sonst antwortet der LLM mit einer Aufzählung in Text statt mit
            # klickbaren Karten. WLO-MCP-Calls sind günstig, also kann der
            # Extra-Round-Trip sein.
            pattern_forces_tool = bool(pattern_output.get("force_tool_use"))
            # `tools_called` enthält ggf. bereits "query_knowledge (prefetch)"
            # vom RAG-Vorabfetch — das soll force_tool_use NICHT blockieren.
            # Nur ECHTE MCP-Tool-Calls (kein "(prefetch)"-Suffix) zählen als
            # "Tool wurde schon aufgerufen, Force erfüllt".
            real_tools_called = [
                t for t in tools_called
                if not (isinstance(t, str) and "(prefetch)" in t)
            ]
            if pattern_forces_tool and first_iteration and not real_tools_called:
                tool_choice = "required"
                _logger.info(
                    "force_tool_use=true → tool_choice=required (active_tools=%d)",
                    len(active_tools),
                )
            elif (
                first_iteration
                and not tools_called
                and not knowledge_prefetched
                and not mcp_prefetched
                and not has_prior_content
            ):
                tool_choice = "required"
            first_iteration = False

        # Map pattern.length → GPT-5 verbosity. RAG/knowledge-heavy turns get
        # an extra bump so the model actually USES the prefetched context
        # rather than condensing it into a one-liner.
        _length = (pattern_output.get("length") or "mittel").lower()
        _verbosity_map = {"kurz": "low", "mittel": "medium", "lang": "high"}
        _verbosity = _verbosity_map.get(_length, "medium")
        if knowledge_prefetched or (rag_context and len(rag_context) > 500):
            # RAG context present → lift at least one notch (medium → high).
            if _verbosity == "low":
                _verbosity = "medium"
            elif _verbosity == "medium":
                _verbosity = "high"

        kwargs = build_chat_kwargs(
            model=MODEL,
            messages=messages,
            tools=active_tools or None,
            tool_choice=tool_choice,
            temperature=0.4,
            verbosity=_verbosity,
        )

        try:
            if on_token is not None:
                # Phase-2 Streaming — same kwargs but tokens arrive progressively
                # via on_token. The reconstructed _StreamedResponse exposes the
                # same attributes so the tool-loop body below is unchanged.
                resp = await _stream_completion(on_token, **kwargs)
            else:
                resp = await client.chat.completions.create(**kwargs)
        except Exception as e:
            _logger.error("LLM API error: %s", e)
            return f"Fehler bei der Verarbeitung: {e}", all_cards, tools_called, outcomes

        choice = resp.choices[0]
        if usage_acc is not None:
            # A2.1 — Phase-Label je Iteration: tool-Iteration vs final response.
            # Hilft bei der Cache-Hit-Rate-Diagnose: "response"-Calls haben oft
            # keinen Cache-Hit, weil Tool-Output-Messages den Prompt variieren.
            _phase = (
                "tool_loop"
                if (choice.finish_reason == "tool_calls" and choice.message.tool_calls)
                else "response"
            )
            usage_accumulator_add(usage_acc, _extract_usage(resp), phase=_phase)

        # Track whether the model used the optional respond_to_user tool —
        # if so, the for-loop's tool-handling falls through and we treat it
        # as the final response instead of a continued tool round-trip.
        _inline_response_text: str | None = None
        _inline_quick_replies: list[str] = []

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            # Convert message to a dict shape OpenAI accepts on the next call.
            # Non-streaming responses ship a Pydantic ChatCompletionMessage that
            # the SDK can re-serialize; the streaming path produces our own
            # ``_StreamedMessage`` shim, which has the same attributes but
            # isn't auto-serialized — hand it through as a plain dict so both
            # paths work uniformly.
            messages.append({
                "role": getattr(choice.message, "role", "assistant"),
                "content": getattr(choice.message, "content", None),
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    } for tc in choice.message.tool_calls
                ],
            })
            for tc in choice.message.tool_calls:
                tool_name = tc.function.name
                tool_args = json.loads(tc.function.arguments)
                tools_called.append(tool_name)

                # ── Inline-Mode-Curation: select_top_cards ────────────
                # LLM-Auswahl der finalen Treffer-Anzeige (siehe Tool-
                # Definition oben). IDs in session_state stashen — wird im
                # Postprocess (_apply_widget_modes_postprocess) genutzt, um
                # die Cards auf genau diese IDs zu filtern in dieser
                # Reihenfolge.
                if tool_name == "select_top_cards":
                    ids = tool_args.get("card_ids") or []
                    reasoning = (tool_args.get("reasoning") or "").strip()
                    # Sanitize: nur Strings, dedupe, max 5
                    clean_ids: list[str] = []
                    seen: set[str] = set()
                    for x in ids:
                        if isinstance(x, str) and x.strip() and x not in seen:
                            clean_ids.append(x.strip())
                            seen.add(x.strip())
                        if len(clean_ids) >= 5:
                            break
                    session_state["_selected_card_ids"] = clean_ids
                    session_state["_selected_card_reasoning"] = reasoning
                    _logger.info(
                        "select_top_cards: %d IDs picked — %s",
                        len(clean_ids), reasoning[:120],
                    )
                    # Welle E (2026-05-23) — Konsistenz Prompt ↔ Anzeige:
                    # nach der Auswahl bekommt der LLM einen verschärften
                    # Reminder, dass er NUR über diese IDs sprechen darf.
                    # Backend-seitiges Trunken der älteren Tool-Results
                    # wäre noch sauberer (siehe TODO), würde aber den
                    # OpenAI-Tool-Call-Chain brechen.
                    _consistency_tail = ""
                    try:
                        from app.services.config_loader import (
                            load_display_rules_config as _ldrc,
                        )
                        _dr_pak = (_ldrc().get("prompt_anzeige_konsistenz") or {})
                        _pak_excl = set(_dr_pak.get("exclude_patterns") or [])
                        if (
                            _dr_pak.get("enabled", True)
                            and (pattern_output.get("id") or "") not in _pak_excl
                            and clean_ids
                        ):
                            _consistency_tail = (
                                "\n\nWICHTIG: Im nächsten ``respond_to_user``-"
                                "Aufruf darfst du NUR über genau diese "
                                f"{len(clean_ids)} ausgewählten IDs sprechen. "
                                "Material, Sammlungen oder Themenseiten, die "
                                "in vorigen Tool-Results stehen aber NICHT in "
                                "dieser Auswahl, NICHT erwähnen — der User "
                                "sieht im Frontend nur diese gewählten Treffer. "
                                "Wenn du im Text auf Treffer Bezug nimmst: "
                                "ausschließlich auf die gewählten."
                            )
                    except Exception:  # pragma: no cover — defensive
                        _consistency_tail = ""

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": (
                            (
                                f"OK — Auswahl gespeichert ({len(clean_ids)} IDs). "
                                "Rufe jetzt respond_to_user mit der Prosa-Antwort auf."
                                if _inline_qr_enabled
                                else f"OK — Auswahl gespeichert ({len(clean_ids)} IDs)."
                            ) + _consistency_tail
                        ),
                    })
                    continue

                # ── Combined-output: model emitted FINAL answer + quick_replies ─
                # See env CHAT_INLINE_QUICK_REPLIES + the respond_to_user tool
                # definition above. Treat this as the equivalent of a
                # finish_reason == "stop" with the extracted text.
                if tool_name == "respond_to_user":
                    _inline_response_text = strip_reasoning_markers((tool_args.get("text") or "").strip())
                    qr = tool_args.get("quick_replies") or []
                    _inline_quick_replies = [
                        str(r).strip() for r in qr if isinstance(r, str) and str(r).strip()
                    ][:4]
                    # Safety net: the model occasionally ALSO writes the quick-
                    # replies / "Bring mich hin"-link as bold lines at the END of
                    # the answer text. They belong only in quick_replies (rendered
                    # as pills/buttons), not as text in the bubble — strip them.
                    _inline_response_text = _strip_trailing_option_lines(
                        _inline_response_text, _inline_quick_replies
                    )
                    # OpenAI requires every tool call to be followed by a
                    # role=tool message in the chain. Acknowledge briefly.
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "OK",
                    })
                    # Don't process more tool calls — respond_to_user means
                    # we're done.
                    break

                # ── Handle virtual knowledge tool ──────────────
                if tool_name == "query_knowledge":
                    from app.services.rag_service import get_rag_context
                    area = tool_args.get("area", "general")
                    query = tool_args.get("query", message)

                    # Track explicitly-queried RAG areas in session_state so the
                    # downstream Guide-QR-injector (chat.py:_attach_guide_qr) can
                    # offer a "Bring mich hin"-link to the area's source URL
                    # (z.B. WissenLebtOnline → https://wissenlebtonline.de/).
                    # Bewusst NUR explizite Calls — die mode:always-Prefetch
                    # läuft immer, das wäre als Guide-Trigger zu breit.
                    used = session_state.setdefault("_rag_areas_used", [])
                    if area and area not in used:
                        used.append(area)

                    # Guard: if this area was already covered by the pre-fetch
                    # and the query is the same, return a short hint instead of
                    # re-querying the database (saves an embedding API call).
                    if knowledge_prefetched and area in always_areas and query == message:
                        _logger.info("query_knowledge(%s): skipped — already pre-fetched", area)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": (
                                f"Bereich '{area}' wurde bereits vorab durchsucht. "
                                "Die Ergebnisse findest du in der vorherigen query_knowledge-Antwort."
                            ),
                        })
                        continue

                    _explicit_sources: list[str] = []
                    result_text = await get_rag_context(
                        query, areas=[area], top_k=_RAG_TOP_K,
                        min_score=_RAG_MIN_SCORE,
                        max_chars_per_area=_RAG_MAX_CHARS_PER_AREA,
                        out_sources=_explicit_sources,
                    )
                    if _explicit_sources:
                        used_src = session_state.setdefault("_rag_top_sources", [])
                        for s in _explicit_sources:
                            if s not in used_src:
                                used_src.append(s)
                    if not result_text:
                        result_text = f"Keine relevanten Informationen im Bereich '{area}' gefunden."
                    _logger.info("query_knowledge(%s): %d chars", area, len(result_text))

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text[:6000],
                    })
                    continue

                # ── Handle MCP tools ──────────────────────────
                # Safety: refuse blocked tools (Triple-Schema T-19)
                if tool_name in blocked_tools:
                    from app.models.schemas import ToolOutcome
                    outcomes.append(ToolOutcome(
                        tool=tool_name, status="error",
                        error="blocked by safety layer",
                    ))
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": "Tool wurde aus Sicherheitsgruenden blockiert.",
                    })
                    continue

                # Enforce maxResults limit on search/collection tools.
                # (maxItems is a legacy alias accepted by our Pydantic validator.)
                MAX_RESULTS = 5
                if tool_name in ("search_wlo_collections", "search_wlo_content", "get_collection_contents"):
                    # Migrate legacy key if the LLM passed the old name.
                    if "maxItems" in tool_args and "maxResults" not in tool_args:
                        tool_args["maxResults"] = tool_args.pop("maxItems")
                    tool_args.setdefault("maxResults", MAX_RESULTS)
                    if tool_args["maxResults"] > MAX_RESULTS:
                        tool_args["maxResults"] = MAX_RESULTS

                # ── Safety net: forward entity-level filters the LLM forgot ──
                # The classifier extracts medientyp / fach / stufe up-front; the
                # LLM is instructed to pass them as learningResourceType /
                # discipline / educationalContext on content searches, but it's
                # not 100% reliable (especially when it chains
                # search_wlo_collections first and then does a "fallback"
                # search_wlo_content). We inject missing filters here so user
                # intent isn't lost. mcp_client's fuzzy label→URI resolver
                # tolerates paraphrased entity values.
                if tool_name == "search_wlo_content":
                    _classif_entities = classification.get("entities", {}) or {}
                    # Migrate any legacy keys the LLM might still send
                    if "resourceType" in tool_args and "learningResourceType" not in tool_args:
                        tool_args["learningResourceType"] = tool_args.pop("resourceType")
                    if "educationalLevel" in tool_args and "educationalContext" not in tool_args:
                        tool_args["educationalContext"] = tool_args.pop("educationalLevel")
                    _medientyp = _classif_entities.get("medientyp")
                    if _medientyp and "learningResourceType" not in tool_args:
                        _logger.info(
                            "injecting learningResourceType=%r from entities.medientyp (LLM omitted it)",
                            _medientyp,
                        )
                        tool_args["learningResourceType"] = _medientyp
                    _fach = _classif_entities.get("fach")
                    if _fach and "discipline" not in tool_args:
                        tool_args["discipline"] = _fach
                    _stufe = _classif_entities.get("stufe")
                    if _stufe and "educationalContext" not in tool_args:
                        tool_args["educationalContext"] = _stufe
                # Same for search_wlo_collections — collections can't be
                # filtered by learningResourceType, but fach/stufe are valid
                # and worth propagating.
                elif tool_name == "search_wlo_collections":
                    _classif_entities = classification.get("entities", {}) or {}
                    if "educationalLevel" in tool_args and "educationalContext" not in tool_args:
                        tool_args["educationalContext"] = tool_args.pop("educationalLevel")
                    _fach = _classif_entities.get("fach")
                    if _fach and "discipline" not in tool_args:
                        tool_args["discipline"] = _fach
                    _stufe = _classif_entities.get("stufe")
                    if _stufe and "educationalContext" not in tool_args:
                        tool_args["educationalContext"] = _stufe

                # Triple-Schema T-23: call with structured outcome
                from app.services.outcome_service import call_with_outcome
                result_text, outcome = await call_with_outcome(tool_name, tool_args)
                outcomes.append(outcome)
                # Only search/content tools produce card-shaped output. Vocabulary
                # and *_info tools return markdown documentation that would pollute
                # the card list (e.g. "## Vokabular: Bildungsstufe" becoming a card).
                CARD_YIELDING_TOOLS = {
                    "search_wlo_collections", "search_wlo_content",
                    "search_wlo_topic_pages", "get_collection_contents",
                    "get_node_details",
                    # MCP v2 — Discovery/Listing-Tools liefern auch Karten
                    # (Fachportale + Sub-Sammlungen sind klickbare Cards).
                    "get_subject_portals",
                    "browse_collection_tree",
                }
                if tool_name in CARD_YIELDING_TOOLS:
                    # search_wlo_topic_pages has its OWN parser — the standard
                    # parse_wlo_cards reads ``nodeId`` and ignores ``variants``,
                    # producing cards without the ``topic_pages`` array. Without
                    # that array isTopicPage() returns false → cards render as
                    # plain Inhalt-cards instead of topic-page-cards with the
                    # 🌐 Themenseite button. The dedicated parser fixes this.
                    if tool_name == "search_wlo_topic_pages":
                        from app.services.mcp_client import parse_wlo_topic_page_cards
                        cards = parse_wlo_topic_page_cards(result_text)
                    else:
                        cards = parse_wlo_cards(result_text)
                    await resolve_discipline_labels(cards)
                else:
                    cards = []
                # Mark cards from search_wlo_collections as collections
                if tool_name == "search_wlo_collections":
                    for c in cards:
                        c.setdefault("node_type", "collection")
                # Merge topic_pages from search_wlo_topic_pages into existing cards
                if tool_name == "search_wlo_topic_pages":
                    existing_by_id = {c["node_id"]: c for c in all_cards if c.get("node_id")}
                    for c in cards:
                        nid = c.get("node_id", "")
                        tp_list = c.get("topic_pages", [])
                        if nid and nid in existing_by_id and tp_list:
                            existing = existing_by_id[nid]
                            existing_vids = {
                                v.get("variant_id") for v in existing.get("topic_pages", [])
                            }
                            for v in tp_list:
                                if v.get("variant_id") not in existing_vids:
                                    existing.setdefault("topic_pages", []).append(v)
                            # If the existing card came from a non-topic-page tool
                            # (e.g. get_subject_portals → node_type='content'),
                            # promote it to 'collection' now that it has topic
                            # pages — otherwise the frontend's isTopicPage()
                            # check fails and the card renders as a flat
                            # Inhalt-card without the 🌐 Themenseite button.
                            existing["node_type"] = "collection"
                # Deduplicate by node_id — enrich topic_pages on collision
                existing_by_id = {c.get("node_id"): c for c in all_cards if c.get("node_id")}
                for c in cards:
                    _nid = c.get("node_id")
                    if _nid and _nid in existing_by_id:
                        _ex = existing_by_id[_nid]
                        if not _ex.get("topic_pages") and c.get("topic_pages"):
                            _ex["topic_pages"] = c["topic_pages"]
                        if not _ex.get("topic_page_url") and c.get("topic_page_url"):
                            _ex["topic_page_url"] = c["topic_page_url"]
                    elif _nid:
                        all_cards.append(c)
                        existing_by_id[_nid] = c
                    else:
                        all_cards.append(c)

                # ── Inline-Result-Grouping: search_wlo_content-Redaction ──
                # Im Box-Anzeige-Modus zeigt die UI Einzelinhalte NICHT direkt
                # an — sie tauchen nur indirekt über die "Alle Treffer zur
                # Suche"-CTA auf. Wenn die LLM den vollen Tool-Result-Text mit
                # Titeln/Beschreibungen sieht, paraphrasiert sie diese unter-
                # mauernd ("ein Arbeitsblatt und ein Video für Fläche, Umfang
                # und Konstruktion") — der User sieht aber gar keine
                # Materialien in der UI und ist verwirrt (User-Feedback
                # 2026-05-21). Helper-Funktion ``_redact_search_content_for_llm``
                # ersetzt den Text durch eine kompakte Summary (Anzahl + grobe
                # Typ-Verteilung). Cards selbst bleiben in ``all_cards``, sodass
                # Lernpfad-Generator (separater Flow) und Such-CTA-Count weiter
                # arbeiten.
                # Tool-Result + UI-Box-Status-Footer (Anti-Hallucination):
                # die Footer-Zeile sagt der LLM, was nach diesem Call WIRKLICH
                # in den sichtbaren Boxen landet — sodass sie im Antwort-Text
                # keine Sammlungen/Themenseiten erfinden kann.
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": (
                        _redact_search_content_for_llm(tool_name, result_text, cards)
                        + _ui_box_state_footer(all_cards)
                    ),
                })

            # If respond_to_user was called among the tool calls, treat THIS
            # iteration as the finish point. Otherwise continue the outer
            # for-loop into the next LLM round-trip.
            if _inline_response_text is None:
                continue
            # Inline final response — set response_text + stash quick_replies
            # and fall through to the Reflection/return path below (which
            # used to be the ``else`` branch only).
            response_text = _inline_response_text
            session_state["_inline_quick_replies"] = _inline_quick_replies
        else:
            response_text = strip_reasoning_markers(choice.message.content or "")

        # ── Final-answer path — runs for BOTH content-only and inline
        #    respond_to_user tool calls. Phase A1 Reflection check gates the
        #    return so a missing-tool retry can still trigger.
        if True:
            # Phase A1 — Reflection-Loop für Tool-Compliance:
            # Wenn das Pattern Tools verlangt (force_tool_use=true) UND keines
            # davon im Tool-Loop tatsächlich gerufen wurde, einmal mit harter
            # Korrektur-Anweisung neu versuchen. Schützt vor LLMs, die einen
            # netten Text-Antwort-Shortcut nehmen, obwohl ihre Pattern-Definition
            # eindeutig MCP-/Service-Calls verlangt.
            #
            # Sicherheits-Conditions (vermeidet Endlos-Loops):
            #   - läuft nur 1× pro Turn (Flag _reflection_done)
            #   - greift nur wenn pattern_output.force_tool_use == True
            #   - greift nur wenn pattern_output.tools eine echte Liste ist
            #   - greift nur wenn keines der erwarteten Tools im tools_called auftaucht
            requires_tools = bool(pattern_output.get("force_tool_use"))
            required_tools = list(pattern_output.get("tools") or [])
            requires_all = bool(pattern_output.get("requires_all_tools"))
            actual_bare = {(t or "").split(" ", 1)[0].strip() for t in tools_called}
            # B1: requires_all_tools=true → vollständige Coverage; sonst Schnittmenge
            if requires_all:
                missing_tools = [t for t in required_tools if t not in actual_bare]
                tool_satisfied = not missing_tools
            else:
                missing_tools = list(required_tools) if not (set(required_tools) & actual_bare) else []
                tool_satisfied = bool(set(required_tools) & actual_bare)

            if (not _reflection_done) and requires_tools and required_tools and not tool_satisfied:
                _logger.info(
                    "Reflection-Loop: Pattern %s verlangt Tools %s (mode=%s), aufgerufen %s, fehlend %s — Retry",
                    pattern_label, required_tools,
                    "ALL" if requires_all else "ANY",
                    sorted(actual_bare), missing_tools,
                )
                _reflection_done = True
                # Korrektur-Nachricht in den Loop-Messages-Stack einfügen
                if requires_all:
                    msg = (
                        f"⚠ KORREKTUR: Du hast PAT-{pattern_label} gewählt; dieses Pattern "
                        f"verlangt ALLE diese Tools nacheinander: {', '.join(required_tools)}. "
                        f"Du hast {sorted(actual_bare) or 'keinen davon'} bisher gerufen. "
                        f"Rufe JETZT die fehlenden Tools ({', '.join(missing_tools)}) auf, "
                        f"BEVOR du final antwortest."
                    )
                else:
                    msg = (
                        f"⚠ KORREKTUR: Du hast PAT-{pattern_label} gewählt, aber KEINEN der "
                        f"verlangten Tools genutzt: {', '.join(required_tools)}. "
                        f"Rufe JETZT mindestens EINEN dieser Tools auf, BEVOR du final "
                        f"antwortest. Ohne Tool-Aufruf hast du keine echten Daten zur Verfügung — "
                        f"deine Antwort wäre erfunden."
                    )
                messages.append({"role": "user", "content": msg})
                # Continue zur nächsten Iteration: Loop wird Tools forcieren
                # weil active_tools immer noch gesetzt ist und der LLM jetzt
                # den expliziten Hinweis hat.
                continue

            return response_text, all_cards, tools_called, outcomes

    # Fallback: if max_iterations reached without final text, generate a
    # short closing summary based on whatever we found.
    if all_cards:
        try:
            summary_resp = await client.chat.completions.create(
                **build_chat_kwargs(
                    model=MODEL,
                    messages=messages + [{
                        "role": "user",
                        "content": (
                            "Bitte fasse jetzt KURZ (1–2 Sätze) zusammen, was du gefunden "
                            "hast — ohne weitere Tool-Aufrufe. Sprich den Nutzer direkt an."
                        ),
                    }],
                    temperature=0.4,
                )
            )
            text = strip_reasoning_markers((summary_resp.choices[0].message.content or "").strip())
            if text:
                return text, all_cards, tools_called, outcomes
        except Exception as e:
            _logger.warning("Fallback summary failed: %s", e)
        return (
            f"Ich habe {len(all_cards)} passende Materialien für dich gefunden — "
            "schau sie dir gerne an:",
            all_cards, tools_called, outcomes,
        )
    return "Ich konnte leider keine Antwort generieren.", all_cards, tools_called, outcomes


# ── Persona-abhaengige Quick-Reply-Menues (Capability-Hints) ──────────
# Diese Listen geben dem LLM einen konkreten Vorrat an plausiblen
# Vorschlaegen, ausgerichtet an dem, was der Bot TATSAECHLICH kann.
# Der LLM darf daraus ableiten oder abwandeln — NICHT woertlich kopieren.
_CAPABILITY_HINTS_DIDACTIC = [
    # Suche
    "Zeig mir mehr Material zu {thema}",
    "Hast du auch Videos/Audios dazu?",
    "Gibt es interaktive Uebungen dazu?",
    "Welche Sammlungen gibt es zu {thema}?",
    "Welche Themenseite passt dazu?",
    # Canvas-Create didaktisch
    "Erstelle mir ein Arbeitsblatt dazu",
    "Mach mir ein Quiz dazu",
    "Erstell mir eine Praesentation zu {thema}",
    "Bau mir einen Lernpfad daraus",
    # Canvas-Edit (wenn S3)
    "Mach es einfacher",
    "Fuege Loesungen hinzu",
    "Kuerzer fassen",
    "Mehr Beispiele bitte",
    # Vertiefung / Richtung
    "Was gibt es noch zu {fach}?",
    "Anderes Thema: ",
    "Fuer welche Klassenstufe ist das?",
]

_CAPABILITY_HINTS_ANALYTICAL = [
    # Projekt-/OER-Statistik / Plattforminfos
    "Welche Statistiken gibt es zu WLO?",
    "Wie viele Materialien hat WLO?",
    "Welche Faecher sind am besten abgedeckt?",
    "Wer steht hinter WLO?",
    "Welche Projekte laufen gerade?",
    # Canvas-Create analytisch
    "Erstell mir einen Bericht dazu",
    "Bau mir ein Factsheet zu {thema}",
    "Ich brauche einen Projektsteckbrief",
    "Entwirf eine Pressemitteilung dazu",
    "Erstell mir einen Vergleich zu {thema}",
    # Canvas-Edit
    "Formeller formulieren",
    "Kuerzer fassen",
    "Kennzahlen ergaenzen",
    "Foerderlogik hervorheben",
    # Suche / Kontext
    "Zeig mir Datengrundlagen dazu",
    "Welche Zielgruppen sind primaer?",
]


def _capability_hints_for_persona(
    persona_id: str, in_canvas: bool, has_topic: bool,
) -> list[str]:
    """Return a focused subset of capability hints for the quick-reply LLM."""
    from app.services.canvas_service import get_analytical_personas
    analytical = get_analytical_personas()
    base = (
        _CAPABILITY_HINTS_ANALYTICAL if persona_id in analytical
        else _CAPABILITY_HINTS_DIDACTIC
    )
    hints = [h for h in base if not (("{thema}" in h or "{fach}" in h) and not has_topic)]
    if not in_canvas:
        # Drop pure-edit hints — no canvas yet.
        hints = [h for h in hints if not any(
            w in h.lower() for w in (
                "einfacher", "loesungen", "kuerzer", "mehr beispiele",
                "formeller", "kennzahlen ergaenzen", "foerderlogik",
            )
        )]
    return hints[:14]


async def generate_quick_replies(
    message: str,
    response_text: str,
    classification: dict[str, Any],
    session_state: dict,
    usage_acc: dict[str, Any] | None = None,
) -> list[str]:
    """Generate 4 context-aware quick reply suggestions using LLM.

    ``usage_acc`` is optional — when threaded through, the LLM call's
    tokens are accounted under phase ``"quick_replies"`` (A2.1) so the
    eval aggregator can break out QR cost separately from classify /
    response.
    """
    persona_id = classification.get("persona_id", "P-AND")
    intent_id = classification.get("intent_id", "")
    state_id = classification.get("next_state", session_state.get("state_id", "S1"))
    entities = classification.get("entities", {}) or {}
    # Drop internal keys (prefix _) — they would confuse the LLM.
    public_entities = {k: v for k, v in entities.items() if not str(k).startswith("_")}

    in_canvas = state_id == "S3"
    thema = public_entities.get("thema") or public_entities.get("topic") or ""
    fach = public_entities.get("fach") or ""
    has_topic = bool(thema or fach)
    capability_hints = _capability_hints_for_persona(persona_id, in_canvas, has_topic)
    # Fill the {thema}/{fach} placeholders in the hints with the concrete
    # session values so the LLM sees realistic example sentences.
    filled_hints = []
    for h in capability_hints:
        try:
            filled_hints.append(h.format(thema=thema or "dem Thema", fach=fach or "deinem Fach"))
        except Exception:
            filled_hints.append(h)

    # Semantic page-context block (resolved theme-page metadata, if any)
    try:
        from app.services import page_context_service
        _pm = page_context_service.get_cached(session_state)
        _page_line = ""
        if _pm and _pm.get("title"):
            _page_line = (
                f"\nAktuelle Themenseite: {_pm['title']}"
                + (f" ({', '.join((_pm.get('disciplines') or [])[:2])})"
                   if _pm.get("disciplines") else "")
                + (f" | Stufen: {', '.join((_pm.get('educational_contexts') or [])[:2])}"
                   if _pm.get("educational_contexts") else "")
            )
    except Exception:
        _page_line = ""

    persona_salute = "Sie" if persona_id in {
        "P-LEH", "P-ELT", "P-ENT", "P-ENT", "P-ENT", "P-RED", "P-RED",
    } else "du"

    # Welle C Sprint 6: State-spezifische QR-Direktive ergänzen.
    # bot_directive aus 04-states/states.yaml — der LLM-QR-Generator
    # liest sie als "Was als nächster Verlaufs-Schritt anzubieten ist".
    _qr_state_meta = _get_state_meta_safe(state_id)
    _qr_state_label = _qr_state_meta.get("label", "")
    _qr_state_directive = _qr_state_meta.get("bot_directive", "")

    system = f"""Du generierst genau 4 kurze Antwortvorschlaege fuer einen Chatbot-Nutzer.
Der Nutzer interagiert gerade mit BOERDi, dem Chatbot der Bildungsplattform
WirLernenOnline (WLO).

## Kontext
- Persona: {persona_id} (Anrede: {persona_salute})
- Intent: {intent_id}
- Gesprächs-Phase: {state_id} ({_qr_state_label}){" — Canvas-Arbeit aktiv" if in_canvas else ""}
- Erkannte Entities: {json.dumps(public_entities, ensure_ascii=False)}{_page_line}

## Phase-Direktive für die Quick-Reply-Auswahl
{_qr_state_directive or '— keine spezifische Direktive für diese Phase, biete generische Folgeschritte an.'}
Die 4 Vorschläge müssen zu dieser Phase passen — z.B. in der Ergebnis-Kuratierung Refinement-Optionen,
in der Bewertung & Feedback eine Probing-Frage, in der Slot-Erfassung wahrscheinliche Slot-Werte.

## Was BOERDi kann (die Vorschlaege MUESSEN sich daraus bedienen)
1. **Inhalte suchen** — einzelne Materialien (Video, Arbeitsblatt, Audio, interaktive
   Uebung, Bild, Text) mit Filtern auf Fach, Stufe, Medientyp, Lizenz.
2. **Sammlungen suchen** — kuratierte Material-Sammlungen.
3. **Themenseiten suchen** — didaktisch aufbereitete Einstiegsseiten zu einem Thema.
4. **Plattforminfos und OER-Projektinfos** — Fragen zu WLO, edu-sharing, Metaventis,
   Projekten, Zahlen/Statistiken zur Plattform.
5. **Canvas-Ausgaben (neue Inhalte erstellen)** — didaktisch: Arbeitsblatt, Infoblatt,
   Praesentation, Quiz, Checkliste, Glossar, Strukturuebersicht, Uebungen,
   Lerngeschichte, Versuchsanleitung, Diskussionskarten, Rollenspiel, **Lernpfad**.
   Analytisch: Bericht, Factsheet, Projektsteckbrief, Pressemitteilung, Vergleich.
6. **Canvas-Edits** — bestehenden Canvas-Inhalt verfeinern (einfacher, kuerzer,
   ausfuehrlicher, Loesungen ergaenzen, formeller, etc.) — NUR wenn State=S3.

## Realistische Vorschlag-Beispiele fuer diese Persona
(Inspiration — nicht woertlich uebernehmen, auf den konkreten Kontext anpassen.)
{chr(10).join(f"- {h}" for h in filled_hints)}

## Perspektive (STRIKT — wichtigste Regel)
Die 4 Vorschlaege sind **Saetze, die der NUTZER dem Bot sagt**, nicht der Bot
zum Nutzer. Schreib aus Ich-/Du-Perspektive des Users. Bot-imperative
("Mach", "Zeige", "Filtere"...) sind nur dann ok, wenn der NUTZER damit etwas
vom Bot verlangt ("Zeig mir nur Videos") — nicht als Bot-Selbstbefehl
("Material zeigen"). Faustregel: Jeder Vorschlag muss vor dem Wort
"Boerdi/Bot" stehen koennen wie ein User-Satz.
FALSCH (Bot-Perspektive / handlungslos):
  - "Weitere Materialien zeigen"
  - "Suche eingrenzen"
  - "Nur Arbeitsblaetter zeigen"   ← wirkt wie Bot-Selbstbefehl
RICHTIG (Nutzer-Perspektive):
  - "Zeig mir mehr davon"
  - "Ich will das auf Klasse 8 eingrenzen"
  - "Zeig mir nur Arbeitsblaetter"   ← Nutzer fordert vom Bot
  - "Hast du auch Videos dazu?"

## Standalone-Regel (KRITISCH — kein Kontext-Anhang moeglich)
Jeder Vorschlag wird als **alleinstehender Button** dargestellt. Der Nutzer
kann ihn NICHT bearbeiten oder ergaenzen — er klickt 1:1 wie er da steht.
Deshalb:
  - Jeder Vorschlag muss **fuer sich alleine sinnvoll** sein, ohne den
    vorherigen Bot-Satz mitzulesen.
  - KEINE Demonstrativa ohne Bezug: "Mehr davon", "Das genauer", "Mach es
    einfacher" sind nur OK wenn aus dem Thema-Kontext eindeutig ist, worauf
    sich "davon"/"das"/"es" bezieht. Im Zweifel das Thema konkret nennen:
      SCHLECHT: "Mehr davon zeigen"
      BESSER:   "Mehr zu Photosynthese zeigen"
  - KEINE Vorschlaege die ein ungesagtes Subjekt voraussetzen.

## Struktur (4 verschiedene Typen — KEIN Duplikat)
Waehle 4 aus den folgenden Kategorien (mindestens 3 unterschiedliche Kategorien):
  (a) **Vertiefung / Material-Typ-Filter** — mehr zum aktuellen Thema/Treffer,
      gerne mit konkretem Material-Typ-Filter (Video, Arbeitsblatt, Uebung,
      Audio, Praesentation, Interaktiv, Quiz, Bild, Text). Diese Filter sind
      ausdruecklich erwuenscht — sie propagieren in die Suche und werden
      als Such-Filter weitergereicht.
      z.B. "Hast du auch Videos dazu?", "Zeig mir nur Arbeitsblaetter",
           "Gibt es das fuer Klasse 8?", "Ich brauche interaktive Uebungen"
  (b) **Canvas-Ausgabe** — neues Material erstellen lassen (zieht den aktuellen
      Kontext als Thema heran)
      z.B. "Mach mir ein Quiz daraus", "Erstell mir einen Lernpfad"
  (c) **Canvas-Edit** — NUR wenn S3 aktiv: bestehenden Inhalt aendern
      z.B. "Mach es einfacher", "Fuege Loesungen hinzu"
  (d) **Richtungswechsel** — anderes Thema / andere Fachrichtung
      z.B. "Anderes Thema: Klimawandel", "Was gibt's zu Physik?"
  (e) **Plattforminfo** — KONKRETE, existierende Aspekte von WLO.
      ZULAESSIG (existieren wirklich):
        - "Welche Faecher deckt WLO ab?"
        - "Wie viele Materialien gibt es?"
        - "Wer steht hinter WLO?" / "Wer betreibt WLO?"
        - "Was ist OER?" / "Was bedeuten die Lizenzen?"
        - "Was ist eine Themenseite?" / "Was sind Fachportale?"
        - "Welche Bildungsstufen werden abgedeckt?"
        - "Kann ich eigene Materialien einreichen?"
      VERBOTEN (existieren NICHT als WLO-Konzept):
        - "Plattforminfrastruktur", "Architektur", "Backend", "API"
        - "Roadmap", "Strategie", "Datenmodell"
        - irgendein erfundener Tech-Begriff
      Wenn du dir unsicher bist ob ein Begriff existiert: lass die
      Plattforminfo-Kategorie weg und nimm eine andere.
  (f) **Konkrete Antwort auf Rueckfrage des Bots** — wenn der Bot eine Frage
      stellt (Thema? Fach? Stufe?), liefere KONKRETE Antworten als Vorschlaege,
      z.B. bei Mathe-Frage: "Bruchrechnung Klasse 6", "Geometrie Sek I".

## Regeln
1. Genau 4 Vorschlaege, einer pro Zeile, KEINE Nummerierung, KEINE Bullets.
2. Jeder Vorschlag max 6-8 Woerter.
3. Anrede strikt {persona_salute}.
4. Wenn Canvas aktiv (S3) ist: mindestens EIN Edit-Vorschlag (Kategorie c).
5. Wenn Themenseite bekannt: mindestens EIN Vorschlag der den Seiten-Kontext nutzt.
6. Wenn Persona analytisch ist (P-ENT/P-ENT/P-RED/P-ENT/P-RED):
   bevorzuge Bericht/Factsheet/Steckbrief/Pressemitteilung/Vergleich und
   Plattform-/Projekt-/Statistik-Fragen. Weniger klassische Lehrmaterialien.
7. Wenn Persona didaktisch (P-LEH/P-LER/P-ELT/P-AND): klassische Lehrmaterialien
   + Lernpfad + Medienvielfalt. Keine Berichte/Factsheets.
8. Wenn der Bot eine Rueckfrage stellt, liefere KONKRETE Antworten (Kategorie f) —
   KEINE generischen Phrasen wie "Was kannst du noch?".
9. NIEMALS erfundene oder vage Begriffe. Wenn du nicht 100% sicher bist
   dass etwas auf WLO existiert: nimm einen anderen Vorschlag. Lieber
   ein konkretes Fach-Beispiel ("Mathe Klasse 8") als ein abstraktes,
   nicht-existierendes Konzept.
10. Vorschlaege sollen **selbst-erklaerend** sein. Wenn man den Vorschlag
    aus dem Kontext reisst, muss klar bleiben was angefragt wird.
    SCHLECHT: "Mehr davon zeigen" (ohne Bezug)
    GUT: "Mehr Mathe-Videos zeigen" / "Anderes Thema waehlen"
11. **Bring-mich-hin-Vorschlag (Webseiten-Lotse — sehr oft nutzbar)**:
    Wenn die NUTZER-NACHRICHT zu einer dieser konkreten WLO-Seiten passt,
    MUSST du EINEN der 4 Vorschlaege als Spezialformat schreiben:

       ``__guide__|<kurzer Anzeigetext>|<vollstaendige URL>``

    Frontend rendert das als dunkelblauen Same-Tab-Navigations-Button.
    Die anderen 3 Vorschlaege bleiben normale Folgesaetze.

    NUTZER-FRAGE → ANZUBIETENDE WLO-URL (verlaesslich; erfinde KEINE
    weiteren Pfade ausserhalb dieser Liste):

    Frage zu Themenseiten / Konzept-Erklaerung „was ist eine Themenseite":
      __guide__|Themenseiten-Beispiel|https://wirlernenonline.de/themenseite/klimawandel
    Frage zu Fachportalen / „welche Faecher / fachportale" / Uebersicht:
      __guide__|Fachportal-Uebersicht|https://wirlernenonline.de/fachportale
    Frage zu Mitmachen / „wie kann ich beitragen / einreichen":
      __guide__|Mitmachen-Seite|https://wirlernenonline.de/mitmachen
    Frage zu „wer steht hinter / wer macht / ueber WLO":
      __guide__|Ueber WLO|https://wirlernenonline.de/ueber-uns
    Frage zu „WLO-Projekt / Hintergrund / Geschichte":
      __guide__|Hintergrund-Info|https://wirlernenonline.de/projekt
    Frage zu OER / Lizenzen (allgemein):
      __guide__|OER-Erklaerung|https://wirlernenonline.de/oer
    Frage zu konkretem Thema X (Themenseite gewuenscht):
      __guide__|Themenseite <X>|https://wirlernenonline.de/themenseite/<x-kleinbuchstaben>
    Frage zu Edu-Sharing / „edu-sharing.net":
      __guide__|Edu-Sharing|https://openeduhub.net/

    REGELN:
    - URL muss vollstaendig sein (https://...), kein relativer Pfad.
    - Maximal 1 Guide-QR pro Antwort. Insgesamt also 4 Zeilen davon 1 Guide.
    - Wenn KEINE der oben gelisteten Frage-Kategorien passt, KEINEN Guide-QR
      einbauen — dann 4 normale Vorschlaege.
    - Themenseiten-Slugs nur fuer Themen die der User EXPLIZIT genannt hat
      (z.B. „klimawandel", „photosynthese") — keine Slugs erfinden.
    - Anzeigetext kurz, konkret, deutsch. KEINE generische „Bring mich hin"
      ohne Kontext.

Gib NUR die 4 Zeilen zurueck, sonst nichts."""

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Nutzernachricht: {message}\n\nBot-Antwort: {response_text[:500]}"},
    ]

    try:
        resp = await client.chat.completions.create(
            **build_chat_kwargs(
                model=MODEL,
                messages=messages,
                temperature=0.6,
                max_tokens=150,
            )
        )
        if usage_acc is not None:
            usage_accumulator_add(usage_acc, _extract_usage(resp), phase="quick_replies")
        text = strip_reasoning_markers(resp.choices[0].message.content or "")
        replies = [line.strip().lstrip("-•*0123456789. ") for line in text.strip().split("\n") if line.strip()]
        # Drop duplicates while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for r in replies:
            k = r.lower()
            if k and k not in seen:
                seen.add(k)
                unique.append(r)
        return unique[:4]
    except Exception:
        return []


async def generate_learning_path_text(
    collection_title: str,
    contents_text: str,
    session_state: dict,
) -> str:
    """Generate a pedagogically structured learning path from collection contents."""
    persona_id = session_state.get("persona_id", "P-AND")
    entities = session_state.get("entities", {})

    learner_info = []
    if entities.get("fach"):
        learner_info.append(f"Fach: {entities['fach']}")
    if entities.get("stufe"):
        learner_info.append(f"Bildungsstufe: {entities['stufe']}")
    learner_ctx = " | ".join(learner_info) if learner_info else "allgemeine Lernende"

    # If fach/stufe are missing, the LLM should infer plausible defaults
    # from the topic (e.g. "Photosynthese" → Biologie, Sek I) AND state
    # this assumption transparently in the response. Eval-Befund Run 10:
    # ohne dieses Hinzunehmen liefert M09 leere Schritt 1/2/3-Templates.
    has_fach = bool(entities.get("fach"))
    has_stufe = bool(entities.get("stufe"))
    default_hint = ""
    if not has_fach or not has_stufe:
        default_hint = (
            "\n\n**WICHTIG — Fach/Stufe ableiten und transparent nennen:**\n"
            f"- Fach{'' if has_fach else ' (NICHT genannt — leite plausible Annahme aus dem Thema ab)'}: "
            f"{entities.get('fach') or '— leite ab'}\n"
            f"- Stufe{'' if has_stufe else ' (NICHT genannt — leite plausible Annahme aus dem Thema ab)'}: "
            f"{entities.get('stufe') or '— leite ab'}\n"
            "Beispiele: 'Photosynthese' → Biologie / Sek I; 'Bruchrechnung' → "
            "Mathematik / Sek I; 'Mittelalter' → Geschichte / Sek I.\n"
            "Im ersten Satz des Lernpfad-Titels die Annahme transparent benennen, "
            "z.B. 'Lernpfad zu *X* (Annahme: Biologie / Sek I — bei Bedarf "
            "anpassen).'"
        )

    system = f"""Du bist BOERDi, ein paedagogischer Assistent fuer WirLernenOnline.de.
Erstelle einen strukturierten Lernpfad aus den gegebenen Inhalten.
Persona: {persona_id}
Kontext: {learner_ctx}{default_hint}

FORMATIERUNGS-REGELN — WICHTIG:
- KEINE LaTeX-Syntax verwenden. Kein \\frac{{}}{{}}, kein \\sqrt{{}}, keine $...$-Delimiter.
- Brueche als Unicode darstellen wo moeglich: 1/2, 1/3, 3/4 — oder ausgeschrieben
  ("ein Drittel", "drei Viertel"). NIEMALS \\frac12 oder ( \\frac12 ).
- Mathematische Ausdruecke als einfacher Text: x^2 statt x^{{2}}, sqrt(2) statt
  \\sqrt{{2}}.
- Markdown wird zu HTML gerendert (marked.js + DOMPurify) — alles, was nicht
  Standard-Markdown ist, kommt beim User als Rohtext an."""

    prompt = f"""Erstelle einen paedagogisch strukturierten **Lernpfad** zum Thema \"{collection_title}\".

Verfuegbare Inhalte:

{contents_text}

**Aufgabe:** Waehle die geeignetsten Inhalte aus und ordne sie in einem sinnvollen Lernpfad an.
Bringe die Materialien in eine didaktisch sinnvolle Reihenfolge (vom Einfachen zum Komplexen).

**HARTE REGELN — nicht verhandelbar:**
1. **Jeder Inhalt darf maximal EINMAL verwendet werden.** Verlinke nie dasselbe
   Material in zwei verschiedenen Schritten. Wiederholungen sind ein Fehler.
2. **Die Anzahl der Schritte richtet sich nach den verfuegbaren Materialien:**
   - Bei 1 Material → 1 Schritt (plus Hinweis, dass der Pfad so kurz ist, weil nur
     ein passendes Material gefunden wurde). Schreibe keinen mehrstufigen Pfad mit
     einem einzigen wiederholten Material.
   - Bei 2-3 Materialien → 2-3 Schritte.
   - Bei 4+ Materialien → 3-5 Schritte, klassisch Einstieg / Erarbeitung / Sicherung.
3. **Das Thema des Lernpfads ist \"{collection_title}\" — nicht der Titel einer
   Sammlung oder eines einzelnen Inhalts.** Wenn die Materialien thematisch nur
   am Rand passen, weise darauf explizit hin (z.B. \"Ein direkt zu '{collection_title}'
   passendes Material war nicht verfuegbar — die folgenden Inhalte streifen das
   Thema.\"). Kapere das Thema nicht.

**Format (Markdown, auf Deutsch):**

Beginne mit einem kurzen Ueberblick:
> **Lernpfad: {collection_title}**
> Kurze Beschreibung des Lernziels (1-2 Saetze).
> Geschaetzte Gesamtdauer: X Minuten

Dann die einzelnen Schritte als nummerierte Abschnitte:
### Schritt 1: Einstieg (ca. X Min.)
- *Lernziel: ...*
- Verlinkter Inhalt: [Titel](URL)
- Aktivitaet: Was sollen die Lernenden konkret tun?
- Begruendung warum dieser Inhalt hier passt

### Schritt 2: Erarbeitung (ca. X Min.)
...usw.

### Schritt N: Sicherung / Vertiefung
...

Schliesse mit:
- **Differenzierung:** Tipps fuer schnellere / langsamere Lernende
- **Tipp fuer Lehrende:** Praktische Hinweise zur Durchfuehrung

Nutze ausschliesslich Inhalte aus der obigen Liste. Verlinke alle verwendeten Inhalte.
Wenn wenige Materialien vorhanden sind, schlage konkret vor, welche Materialtypen
zur Ergaenzung gesucht werden koennten (z.B. \"ein kurzes Erklaervideo\",
\"ein Arbeitsblatt mit Aufgaben\") — aber verwende niemals dasselbe Material mehrfach,
um Luecken zu fuellen."""

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    try:
        resp = await client.chat.completions.create(
            **build_chat_kwargs(
                model=MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
            )
        )
        return strip_reasoning_markers(resp.choices[0].message.content or "") or "Lernpfad konnte nicht erstellt werden."
    except Exception as e:
        return f"Fehler beim Erstellen des Lernpfads: {e}"
