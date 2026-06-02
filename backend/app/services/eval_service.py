"""Automated persona-driven conversation evaluation.

Builds on existing config_loader (personas, intents, patterns) and
writes to both:
  - eval_runs           (run metadata + full transcripts + aggregate scores)
  - quality_logs        (every simulated turn goes through /api/chat and
                         therefore lands in the same table as production
                         traffic — so pattern-usage analytics are unified)

Config-agnostic: reads personas/intents dynamically per call, so any
chatbot config under chatbots/<name>/v1/ works without code changes.

Two run modes:
  - "scenarios"      1-turn fire-and-score per (persona, intent) combo
  - "conversations"  multi-turn dialogues with a user-simulator LLM
  - "both"           scenarios THEN conversations

All LLM calls use the active provider (get_client()). The eval incurs
real API costs — estimate via estimate_cost() before calling execute_run().
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite
import httpx

from app.services.config_loader import (
    load_intents,
    load_persona_definitions,
)
from app.services.database import DB_PATH
from app.services.llm_provider import get_client

logger = logging.getLogger(__name__)


# ── Config ──────────────────────────────────────────────────────────

# Models for simulator + judge. Keep light by default (gpt-4o-mini is
# plenty for judging; the persona simulator can use the main chat model
# for more realistic roleplay — but gpt-4o-mini works too and is cheaper).
DEFAULT_SIMULATOR_MODEL = os.getenv("EVAL_SIMULATOR_MODEL", "gpt-4o-mini")
DEFAULT_JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gpt-4o-mini")

# Where the eval talks to the real chatbot. Self-loopback in Docker
# uses "backend:8000"; in dev localhost:8000. Override via env.
CHAT_URL = os.getenv("EVAL_CHAT_URL", "http://localhost:8000/api/chat")


# ── Scenario generation ────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────
# Welle E (2026-05-25) — Scenario-Prompt YAML-driven
#
# Vorher: ~60 Zeilen hardcoded Persona-Marker-Listen pro Persona im
# Template (POSITIV/NEGATIV-Block). Jetzt: zur Laufzeit aus den Persona-
# MDs (hints + anti_hints) injiziert. Single Source of Truth mit dem
# Klassifikator-Prompt.
#
# Was IM Template bleibt:
#   - Generische Anweisungen (Stil, Du/Sie, Intent-Trigger-Pflicht)
#   - Intent-spezifische Sonder-Regeln für I01 (Soft Probing) — die sind
#     vom Persona-Schema unabhängig.
#   - Die Persona/Intent-Daten als {…}-Platzhalter.
# ──────────────────────────────────────────────────────────────────────


_SCENARIO_PROMPT = """Du hilfst beim Testen eines Chatbots.

Erzeuge {count} realistische Eroeffnungsfragen, die ein Nutzer mit folgender
Persona dem Chatbot stellen wuerde, mit dem Ziel hinter dem Intent.

## Persona
{persona_label}
{persona_desc}

## Intent
{intent_label}
{intent_desc}
Typische Trigger-Verben/Phrasen (sollten in den Eroeffnungen vorkommen):
{intent_triggers}

## Persona-Marker (verbindlich)
{persona_markers_block}

KRITISCH — die Nachricht muss den Intent KLAR triggern:
- Enthalte Schluesselphrasen oder Inhalte, die fuer diesen Intent spezifisch sind.
  Beispiel: Bei "Suche Unterrichtsmaterial" muss ein Fach, Thema oder Typ vorkommen.
  Bei "Inhalt erstellen" muss ein Erstell-Verb ("erstelle", "generiere", "bau mir")
  UND ein konkretes Thema vorkommen.
- INTENT-SPEZIFISCHE SONDER-REGELN:
  * I01 (Orientierung): EINE Frage der Form "Was ist WLO?" /
    "Was kann ich hier machen?" / "Worum geht's auf dieser Seite?" ODER vage
    Erkundung "Ich gucke mal", "Erstmal umsehen", "Bin neu hier".
    VERBOTEN: konkretes Fach, konkretes Thema, Such-/Erstell-/Plan-Verb,
    Lernpfad, Materialien-fuer-... — denn sobald ein konkretes Anliegen
    drin ist, ist es NICHT mehr Orientierung, sondern ein anderer Intent.
  * I05 (Inhalt-Generieren): MUSS ein **explizites Erstell-Verb**
    enthalten ("erstelle", "generiere", "bau mir", "mach mir", "schreib mir",
    "fertige … an", "produziere") UND einen **konkreten Material-Typ**
    (Arbeitsblatt, Quiz, Bericht, Infoblatt, Pressemitteilung, Factsheet,
    Steckbrief, Vergleich, Lerngeschichte, Versuchsanleitung, Präsentation,
    Glossar, Checkliste). VERBOTEN sind generische Plattform-Fragen wie
    "Was kann ich hier alles machen?" — das ist I01.
    Beispiel-Eröffnungen:
      - "Erstell mir bitte ein Arbeitsblatt zur Bruchrechnung."
      - "Generier mir ein Quiz zu Photosynthese für Klasse 7."
      - "Bau mir ein Infoblatt zur Stadtgeschichte."
  * I06 (Inhalt-Nachbearbeiten): Edit-Verb auf VORHANDENEN Inhalt:
    "kürzer", "einfacher", "ergänze", "umformuliere", "Lösungen rein".
    Die Eröffnung muss EXPLIZIT auf einen vorigen Bot-Inhalt referenzieren
    ("den Text vorher", "den Lernpfad", "das eben Erstellte").
  * Andere Intents: KEINE generische "Was kannst du?"-Frage — das ist
    I01, nicht der hier vorgegebene. Konkretes Anliegen mit
    Intent-spezifischen Schluesselphrasen ist Pflicht.

GLEICH KRITISCH — die Nachricht muss die PERSONA erkennbar machen:
- MINDESTENS EINEN POSITIV-Marker aus der Liste oben verwenden.
- KEINE Phrase aus den NEGATIV-Markern verwenden — die wuerde eine andere
  Persona triggern und unsere Klassifikator-Messung verfaelschen.
- Bei P-LER (Lerner / Schueler:in) reicht ein generisches "Hey, ich bin neu"
  NICHT — das ist P-AND. P-LER-Eroeffnungen MUESSEN **mindestens EIN Wort**
  aus der folgenden Liste enthalten (Pflicht, keine Ausnahme):
  * Selbst-ID: "ich bin Schueler:in", "als Schueler:in", "Schueler", "Lerner"
  * Schul-Kontext: "Schule", "Klasse N" (mit Zahl), "Unterricht", "Klausur",
    "Hausaufgabe(n)", "Pruefung", "Test", "Lehrer:in", "Stundenplan"
  * Lern-Kontext: "ich lerne fuer", "fuers Lernen", "fuer mein Lernen",
    "fuer meine Pruefung", "ich kapiere ... nicht", "ich verstehe ... nicht",
    "erklaer mir", "kannst du ... erklaeren"

  Wenn die User-Nachricht keinen dieser Marker enthaelt, ist sie P-AND —
  egal welche Persona im Test-Setup ausgewaehlt wurde. Eine Frage wie
  "Hey, ich habe einen Fehler im Material gefunden" ohne Schul-Anker geht
  NICHT als P-LER durch. Lieber das Wort "Klausur" oder "Schule" einbauen.

Stil:
- Schreibe natuerlich, nicht perfekt formuliert. Tippfehler, Abkuerzungen,
  halbe Saetze sind ok — so reden echte Nutzer.
- Variiere Laenge, Konkretheit und Tonfall zwischen den Fragen.
- Falls die Persona die Sie-Form bevorzugt (Verwaltung, Presse, Politiker:in,
  Berater:in), dann SIE-Form verwenden. Bei Schueler:in und Eltern eher Du.
- KEINE Nummerierung, KEIN Metatext. Nur die Fragen, eine pro Zeile.
"""


# Cache für das gerenderte Persona-Markers-Block pro Persona. Wird
# einmal pro Generator-Run gebaut (alle Personas geladen, Cross-References
# berechnet) und dann pro (persona, intent)-Kombi nachgeschlagen.
def _build_persona_markers_block(
    persona: dict[str, Any],
    all_personas: list[dict[str, Any]],
) -> str:
    """Render the persona-specific POSITIV/NEGATIV markers block.

    POSITIV-Marker kommen direkt aus der Persona-MD (``## Positiv-Marker``
    → ``hints``). NEGATIV-Marker kombinieren zwei Quellen:
      1. Die eigene ``anti_hints``-Liste (``## Anti-Marker``)
      2. Die Positiv-Marker ALLER anderen Personas (Cross-Persona-Drift-
         Schutz) — getaggt mit ``(= P-XYZ)``, damit das LLM weiß warum
         der Marker verboten ist.

    Für P-AND (Default-Persona) gilt die Inversionsregel: KEIN Positiv-
    Marker, dafür sind ALLE Marker anderer Personas verboten.
    """
    pid = persona.get("id", "")
    # ``positive_markers`` ist die Welle-E-v2-Quelle, ``hints`` ist der
    # Backward-Compat-Alias (zeigt auf dieselbe Liste).
    pos = persona.get("positive_markers") or persona.get("hints") or []

    # ``anti_markers`` ist jetzt list[{phrase, redirect_to?, rationale?}],
    # die alte ``anti_hints`` (list[str]) bleibt als Fallback für Files,
    # die noch nicht migriert sind.
    own_anti_raw = persona.get("anti_markers") or persona.get("anti_hints") or []
    own_anti: list[str] = []
    for item in own_anti_raw:
        if isinstance(item, dict):
            phrase = str(item.get("phrase") or "").strip()
            if not phrase:
                continue
            redirect_to = str(item.get("redirect_to") or "").strip()
            own_anti.append(f'"{phrase}" (= {redirect_to})' if redirect_to else f'"{phrase}"')
        elif isinstance(item, str) and item.strip():
            own_anti.append(f'"{item.strip()}"')

    # Cross-Persona NEGATIV: Positiv-Marker anderer Personas (max 6 pro
    # andere Persona, damit das Block nicht explodiert).
    cross_neg: list[str] = []
    for other in all_personas:
        other_id = other.get("id", "")
        if not other_id or other_id == pid:
            continue
        other_pos = other.get("positive_markers") or other.get("hints") or []
        for h in other_pos[:6]:
            cross_neg.append(f'"{h}" (= {other_id})')

    parts: list[str] = []

    # P-AND ist Spezialfall: keine eigenen Marker, dafür alle fremden verboten.
    if pid == "P-AND":
        parts.append(
            'POSITIV (Eröffnung soll GENERISCH bleiben, keine Selbst-ID): '
            'z. B. "Was kann ich hier machen?", "ich gucke mal", '
            '"interessehalber", "bin neu hier".'
        )
        if cross_neg:
            parts.append(
                "NEGATIV (jeder klare Marker bricht die P-AND-Anonymität):"
            )
            for m in cross_neg[:20]:
                parts.append(f"  - {m}")
        return "\n".join(parts)

    if pos:
        parts.append(
            "POSITIV (MUSS in der Eröffnung vorkommen):\n  - "
            + "\n  - ".join(f'"{p}"' for p in pos[:15])
        )
    else:
        parts.append("POSITIV: (keine Marker konfiguriert — Eröffnung darf generisch sein)")

    neg_block: list[str] = []
    for a in own_anti[:10]:
        # ``own_anti`` ist bereits formatiert (mit Quotes + optional
        # ``(= P-XYZ)``-Tag), daher kein zusätzliches Quoting hier.
        neg_block.append(f"  - {a}")
    for m in cross_neg[:15]:
        neg_block.append(f"  - {m}")
    if neg_block:
        parts.append("NEGATIV (NICHT verwenden — wuerde andere Persona triggern):")
        parts.extend(neg_block)

    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────────────
# Persona-Marker — Welle E (2026-05-25): dynamisch aus den Persona-MDs
#
# Vorher: ein hardcoded ``_PERSONA_MARKERS``-Dict mit ~80 Phrasen, das
# Studio nicht editieren konnte. Jetzt: ``hints`` aus
# ``load_persona_definitions()`` (die wiederum die ``## Positiv-Marker``-
# Sektion in den Persona-MDs lesen). Damit ist das Eval-Modul mit dem
# Klassifikator-Prompt aus EINER Datenquelle gefüttert — Marker, die
# der Klassifikator nutzt, werden vom Scenario-Generator und vom
# Telemetrie-Filter identisch verstanden.
#
# Backward-Compat: falls die Persona-MD eine veraltete Markdown-Struktur
# hat und ``hints`` leer zurückgibt, fällt der Marker-Check permissiv
# auf "True" — wir wollen weder den Eval blockieren noch False-Negatives
# über die Telemetrie verschleiern.
# ──────────────────────────────────────────────────────────────────────


def _normalize_marker(s: str) -> str:
    """Lowercase + drop accents so that „fuer" / „für" beide matchen."""
    if not s:
        return ""
    out = s.lower()
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        out = out.replace(src, dst)
    return out


def _load_persona_markers() -> dict[str, list[str]]:
    """Build a persona-id → lowercased markers map from the persona MDs.

    Reads ``hints`` (= Positiv-Marker section) for every persona. The
    result is cached implicitly via the YAML/MD mtime-cache in
    ``config_loader``, so repeated calls cost effectively nothing.
    """
    result: dict[str, list[str]] = {}
    for p in load_persona_definitions():
        pid = p.get("id", "")
        if not pid:
            continue
        hints = p.get("hints") or []
        result[pid] = [
            n for n in (_normalize_marker(h) for h in hints if h) if n
        ]
    return result


def _has_persona_marker(text: str, persona_id: str) -> bool:
    """Deterministic check: does the user text contain a persona-anchor?

    Used to flag LLM-generated scenarios that drifted to generic
    phrasing (Telemetrie, kein Filter mehr seit 2026-05-23). Returns
    True if at least one marker for the expected persona is present
    (case-insensitive + accent-folded substring match), OR — for
    P-AND — if no other persona's marker leaked in.

    Datenquelle: ``## Positiv-Marker``-Sektion in den Persona-MDs (via
    ``load_persona_definitions`` → ``hints``).
    """
    markers_map = _load_persona_markers()
    t = _normalize_marker(text)
    if persona_id == "P-AND":
        # P-AND drift means another persona's marker leaked in.
        for other_id, markers in markers_map.items():
            if other_id == "P-AND":
                continue
            if any(m in t for m in markers):
                return False
        return True
    markers = markers_map.get(persona_id, [])
    if not markers:
        # Unknown persona OR empty marker list — be permissive.
        return True
    return any(m in t for m in markers)


async def generate_scenarios(
    personas: list[dict], intents: list[dict], count_per_combo: int = 2,
    progress_cb: Any = None,
) -> list[dict]:
    """Generate realistic opening messages for each (persona, intent) combo.

    Uses an LLM. Every (persona, intent) pair gets ``count_per_combo``
    openings. Returns a flat list of scenario dicts.

    ``progress_cb`` (optional async callable) is invoked with
    ``(combo_idx, total_combos, persona_id, intent_id)`` BEFORE each
    LLM call so callers can publish live progress to the UI. The first
    LLM call alone takes 2–3 s, but with 9×16=144 combos the whole
    stage runs ~5–7 min — without progress hook, the UI shows a stale
    "Generiere Szenarien …" the entire time.
    """
    client = get_client()
    scenarios: list[dict] = []
    total_combos = len(personas) * len(intents)
    combo_idx = 0
    # Fire serially — keeps cost transparent and avoids provider rate limits
    for p in personas:
        for i in intents:
            combo_idx += 1
            if progress_cb is not None:
                try:
                    await progress_cb(
                        combo_idx, total_combos,
                        p.get("id", ""), i.get("id", ""),
                    )
                except Exception:
                    # Progress hook must never break generation
                    pass
            # Welle E (2026-05-25): persona-Marker-Block und Intent-Trigger
            # kommen jetzt aus den YAML/MD-Dateien — Single Source of Truth
            # mit dem Klassifikator-Prompt. Der Generator weiß durch die
            # zur Laufzeit injizierten POSITIV/NEGATIV-Marker, welche
            # Phrasen er einbauen MUSS (Persona-Signal) und welche er
            # vermeiden MUSS (würde andere Persona triggern).
            markers_block = _build_persona_markers_block(p, personas)
            intent_triggers = ", ".join(
                f'"{tv}"' for tv in (i.get("trigger_verbs") or [])[:12]
            ) or "(keine Trigger-Verben konfiguriert)"
            prompt = _SCENARIO_PROMPT.format(
                count=count_per_combo,
                persona_label=p.get("label", p.get("id", "")),
                persona_desc=p.get("description", "") or "(keine Beschreibung)",
                intent_label=i.get("label", i.get("id", "")),
                intent_desc=(i.get("description") or "")[:400],
                intent_triggers=intent_triggers,
                persona_markers_block=markers_block,
            )
            try:
                resp = await client.chat.completions.create(
                    model=DEFAULT_SIMULATOR_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                )
                raw = (resp.choices[0].message.content or "").strip()
                # Strip markdown quote blocks, numbered prefixes, bullet chars.
                # Handle models that respond with just one long line too.
                candidates: list[str] = []
                for ln in raw.split("\n"):
                    ln = ln.strip().strip('"').strip("'")
                    ln = ln.lstrip("-•*").strip()
                    # Numbered prefixes like "1." "1)" "1:" — strip at most 3 leading digits
                    if len(ln) > 2 and ln[0].isdigit():
                        for sep in (". ", ") ", ": ", "- "):
                            if sep in ln[:5]:
                                ln = ln.split(sep, 1)[1].strip()
                                break
                    if ln and len(ln) >= 8:
                        candidates.append(ln)
                lines = candidates[:count_per_combo]
                if not lines:
                    logger.warning(
                        "Scenario generator returned no parseable lines for %s/%s. Raw: %r",
                        p.get("id"), i.get("id"), raw[:200],
                    )
                # ── Persona-Marker-Gate ENTFERNT (2026-05-23) ────────────
                # Im Scenario-Mode ist die Persona durch die Konstruktion
                # (LLM-Prompt mit gewähltem Persona-Tag) **per Definition
                # gesetzt** — eine nachträgliche Substring-Filterung kippt
                # legitim erzeugte Eröffnungen weg, die natürlich
                # formuliert sind und unsere Schlagwort-Liste nicht trifft.
                # Außerdem verzerrte das Gate die Persona-Klassifikator-
                # Messung: Eingaben, die der Klassifikator vielleicht falsch
                # gelabelt hätte, wurden vorab herausgefiltert.
                # Telemetrie-only Logging der Marker-Trefferrate behalten
                # wir, damit Marker-Qualität sichtbar bleibt, ohne zu filtern.
                pid = p.get("id", "")
                _marker_hits = sum(1 for ln in lines if _has_persona_marker(ln, pid))
                if lines and _marker_hits < len(lines):
                    logger.info(
                        "Persona-Marker-Telemetrie %s/%s: %d/%d Eröffnungen "
                        "ohne harten Marker (werden trotzdem behalten).",
                        pid, i.get("id"), len(lines) - _marker_hits, len(lines),
                    )
                for idx, line in enumerate(lines):
                    scenarios.append({
                        "persona_id": pid,
                        "persona_label": p.get("label", ""),
                        "intent_id": i.get("id", ""),
                        "intent_label": i.get("label", ""),
                        "opening": line,
                        "index": idx,
                    })
            except Exception as e:
                logger.warning(
                    "Scenario generation failed for %s/%s: %s",
                    p.get("id"), i.get("id"), e,
                )
    return scenarios


# ── Chat driver — talk to the live /api/chat ────────────────────────

async def _post_chat(
    message: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Fire one user message at /api/chat, return raw response JSON.

    ``session_id`` is required by the Chat API; we auto-generate a fresh
    ``eval-<uuid>`` session when none is passed (1-turn scenarios).
    """
    if not session_id:
        session_id = f"eval-{uuid.uuid4().hex[:12]}"
    payload: dict[str, Any] = {
        "session_id": session_id,
        "message": message,
    }
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(CHAT_URL, json=payload)
        r.raise_for_status()
        return r.json()


# ── Conversation simulator ─────────────────────────────────────────

# Welle E (2026-05-25) — _SIMULATOR_SYSTEM YAML-driven
#
# Vorher: hardcoded Persona-Marker-Liste (Zeilen 436-454) parallel zum
# _SCENARIO_PROMPT, dieselben Daten doppelt zu pflegen.
# Jetzt: der Persona-Marker-Block wird per `{persona_markers_block}` zur
# Laufzeit aus den Persona-MDs (hints + anti_hints) injiziert — Single
# Source of Truth mit dem Klassifikator-Prompt und dem Scenario-Generator.
_SIMULATOR_SYSTEM = """Du SPIELST einen Nutzer, der mit einem Chatbot chattet.

## Persona
{persona_label}
{persona_desc}

## Ziel dieser Konversation
{intent_label} — {intent_desc}

## Persona-Marker (verbindlich)
{persona_markers_block}

Regeln:
- Schreibe wie der beschriebene Nutzer schreiben wuerde. Nicht wie ein LLM.
- Reagiere auf die Bot-Antwort natuerlich: stelle Nachfragen, grenze ein,
  werde ungeduldig wenn nichts passiert, akzeptiere gute Antworten knapp.
- Halte die Nachrichten kurz (max 2 Saetze pro Turn, gerne 1).
- Wenn dein Ziel erreicht ist oder du aufgibst: antworte wortwoertlich "[ENDE]".
- KEIN Metatext, keine Anfuehrungszeichen. Nur die Nutzer-Nachricht selbst.

PERSONA-VERANKERUNG (KRITISCH — auch in FOLGE-Turns!):
- JEDE Nachricht — nicht nur die erste — muss mindestens EINEN POSITIV-Marker
  aus der Liste oben enthalten. Sonst kann der Klassifikator nach Turn 1 nicht
  mehr unterscheiden, ob die selbe Persona weiterspricht oder ob es jemand
  anderes ist — und dein Spiel ist gebrochen.
- KEIN NEGATIV-Marker — die wuerden eine andere Persona triggern.
- Falls dir kein Anker einfaellt, paraphrasiere kurz deine Rolle:
  z.B. "Ich als Lehrkraft brauche jetzt ..." / "Fuer meine Klausur ..." /
  "Als Redakteurin pruefe ich gerade ..." / "Fuer meinen Wahlkreis ist ..."

VERBOTEN in Folge-Turns:
- "OK" / "Danke" / "Mehr davon" / "Weiter" — leer und persona-los.
- Sobald du den Bot lobst oder weiter willst, kombiniere mit einem Persona-Marker:
  z.B. "Super, gib mir bitte noch ein Beispiel zur 8. Klasse" (P-LEH)
  statt nur "Super, gib mir mehr".
"""


async def simulate_conversation(
    persona: dict,
    intent: dict,
    max_turns: int = 3,
    opening: str | None = None,
) -> dict[str, Any]:
    """Run a multi-turn dialogue: LLM-simulated user ↔ real /api/chat.

    Returns a dict with ``turns`` (list of {user, bot, debug}), ``session_id``,
    ``ended_early`` (bool).
    """
    client = get_client()
    session_id = f"eval-{uuid.uuid4().hex[:12]}"
    # Welle E (2026-05-25): persona_markers_block aus YAML — same data
    # source as Klassifikator + Scenario-Generator.
    all_personas = load_persona_definitions()
    markers_block = _build_persona_markers_block(persona, all_personas)
    system_prompt = _SIMULATOR_SYSTEM.format(
        persona_label=persona.get("label", ""),
        persona_desc=(persona.get("description") or "")[:400],
        intent_label=intent.get("label", ""),
        intent_desc=(intent.get("description") or "")[:400],
        persona_markers_block=markers_block,
    )
    sim_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

    # Seed the conversation with the opening (or ask the simulator to produce one)
    if opening:
        user_msg = opening
    else:
        sim_messages.append({
            "role": "user",
            "content": "Starte die Konversation mit einer realistischen Eroeffnungsnachricht.",
        })
        resp = await client.chat.completions.create(
            model=DEFAULT_SIMULATOR_MODEL,
            messages=sim_messages,
            temperature=0.8,
        )
        user_msg = (resp.choices[0].message.content or "").strip()
        sim_messages.pop()  # remove the seed instruction from history

    turns: list[dict[str, Any]] = []
    ended_early = False
    # Welle C Sprint 6: Track state across turns so we can analyse the
    # conversation-flow plausibility per-turn (was the transition typical
    # for this state's next_likely list?).
    prev_state: str = ""

    for turn_idx in range(max_turns):
        if user_msg.strip().upper() == "[ENDE]":
            ended_early = True
            break
        try:
            bot_resp = await _post_chat(user_msg, session_id=session_id)
        except Exception as e:
            logger.warning("Chat call failed in turn %d: %s", turn_idx, e)
            turns.append({
                "user": user_msg,
                "bot": f"(chat error: {e})",
                "debug": {},
                "error": str(e),
            })
            break
        bot_text = bot_resp.get("content", "") or ""
        debug = bot_resp.get("debug", {}) or {}
        # Same canvas-content merge as in execute_run scenario stage —
        # the simulator-driven user might continue a canvas conversation
        # ("mach es einfacher"), and the judge needs to see what actually
        # got delivered, not just the announcement bubble.
        page_action = bot_resp.get("page_action") or {}
        if (page_action.get("action") in ("canvas_open", "canvas_update")
                and isinstance(page_action.get("payload"), dict)
                and page_action["payload"].get("markdown")):
            canvas_md = page_action["payload"]["markdown"]
            bot_text = (
                f"{bot_text}\n\n"
                f"---\n[Canvas-Inhalt — vom Nutzer sichtbar]\n\n"
                f"{canvas_md}"
            )
        # Welle C Sprint 6 — State-Verlauf erfassen für Conversation-Flow-Analyse.
        # state-Strings kommen als "state-X (Label)" — wir extrahieren die ID für
        # den Plausibilitäts-Check gegen next_likely aus states.yaml.
        _state_raw = debug.get("state") or ""
        _state_id = _state_raw.split(" ")[0] if _state_raw else ""
        _transition_plausible: bool | None = None
        if prev_state and _state_id:
            try:
                from app.services.config_loader import get_state_directive
                _prev_meta = get_state_directive(prev_state)
                _next_likely = _prev_meta.get("next_likely", []) if _prev_meta else []
                if _next_likely:
                    _transition_plausible = (
                        _state_id in _next_likely or _state_id == prev_state
                    )
            except Exception:
                pass

        turns.append({
            "user": user_msg,
            "bot": bot_text,
            "debug": {
                "pattern": debug.get("pattern"),
                "persona": debug.get("persona"),
                "intent": debug.get("intent"),
                # Welle C Sprint 6: state als ID + Übergangs-Telemetrie.
                "state": _state_raw,
                "state_id": _state_id,
                "prev_state_id": prev_state,
                "transition_plausible": _transition_plausible,
                "safety": debug.get("safety"),
                "tools_called": debug.get("tools_called", []),
                # Phase-1-Pattern-Hint (für globale Aggregat-Metriken)
                "pattern_id_hint": debug.get("pattern_id_hint"),
                "pattern_reasoning": debug.get("pattern_reasoning"),
                "llm_engine_match": debug.get("llm_engine_match"),
                # Bonus 1: Cache-Hit-Rate aggregation reads from this
                "token_usage": debug.get("token_usage"),
                # Bonus 2: tie-breaker telemetry lives inside phase3_modulations
                "phase3_modulations": debug.get("phase3_modulations"),
            },
            "cards_count": len(bot_resp.get("cards", []) or []),
            "response_length": len(bot_text),
        })
        # Persist current state for next-turn transition analysis.
        if _state_id:
            prev_state = _state_id

        if turn_idx == max_turns - 1:
            break

        # Ask simulator for next user turn
        sim_messages.append({"role": "assistant", "content": user_msg})
        sim_messages.append({
            "role": "user",
            "content": f"Der Chatbot hat geantwortet:\n\n{bot_text[:1500]}\n\nDeine naechste Nachricht:",
        })
        try:
            resp = await client.chat.completions.create(
                model=DEFAULT_SIMULATOR_MODEL,
                messages=sim_messages,
                temperature=0.7,
            )
            user_msg = (resp.choices[0].message.content or "").strip()
            sim_messages.pop()  # drop the "bot said: ..." prompt, keep the assistant turn only
        except Exception as e:
            logger.warning("Simulator failed on turn %d: %s", turn_idx, e)
            break

    return {
        "session_id": session_id,
        "persona_id": persona.get("id", ""),
        "intent_id": intent.get("id", ""),
        "turns": turns,
        "ended_early": ended_early,
    }


# ── Judge ──────────────────────────────────────────────────────────

_JUDGE_PROMPT = """Du bist ein unparteiischer Gutachter fuer Chatbot-Qualitaet.

Nutzer-Persona: {persona_label} — {persona_desc}
Nutzer-Ziel (Intent): {intent_label} — {intent_desc}

Nutzer-Nachricht:
{user_msg}

Bot-Antwort:
{bot_response}

Debug-Information (was das System intern entschieden hat):
- Erkannte Persona: {debug_persona}
- Erkannter Intent: {debug_intent}
- Gewaehltes Pattern (Engine): {debug_pattern}
- LLM-Hint-Pattern: {debug_pattern_hint}{debug_pattern_hint_reasoning}
- Safety-Status: {debug_safety}
- Aufgerufene Tools: {debug_tools}

Persona-Erwartungen (Welle E v3+, 2026-05-25):
{persona_expectations}

Intent-Erwartungen (Welle E v3+, 2026-05-25):
{intent_expectations}

Pattern-Erwartungen (Welle E v3, 2026-05-25):
{pattern_expectations}

Bewerte auf 5 Dimensionen, jeweils 0 (schlecht), 1 (mittel), 2 (gut):

1. intent_fit      — beantwortet die Bot-Antwort das Anliegen der Persona?
                     HINWEIS: Das "Nutzer-Ziel" oben ist ein TEST-Label, nicht zwingend das
                     echte Anliegen der Nutzer-Nachricht. Wenn der Nutzer tatsaechlich
                     etwas anderes fragt (z.B. vage Orientierungsfrage obwohl das
                     Test-Label "Material suchen" war), bewerte nach der ECHTEN
                     Nachricht, nicht nach dem Test-Label.
                     MULTI-TURN-DRIFT-TOLERANZ (Welle C Sprint 6): Der
                     LLM-User-Simulator weicht im Gespraechsverlauf oft vom
                     urspruenglichen Test-Label ab — z.B. Initial-Label
                     "I08 Routing Redaktion", aber spaetere Turns
                     fordern konkretes Material. Bewerte STRIKT nach der
                     aktuellen User-Nachricht (turn_user_text) — wenn der
                     User im Turn 5 sagt "mach mir den Lernpfad", und der
                     Bot baut einen Lernpfad, ist das intent_fit=2 — auch
                     wenn das Conversation-Label "Feedback" hiess. Bestrafe
                     den Bot NICHT fuer Drift, den der Simulator selbst
                     verursacht hat.
2. persona_tone    — passt der Tonfall zu dieser Persona?
                     Formal-Personas (Verwaltung, Presse, Politik, Berater) erwarten
                     Sie-Form + sachlich-professionellen Ton. Schueler:in/Eltern
                     duerfen locker angesprochen werden.
                     EVAL-SETUP-TOLERANZ: Wenn die Nutzer-Nachricht KEINEN
                     persona-spezifischen Anker enthaelt (z.B. "Gibt's Mathe-
                     Material?" — koennte von Lehrkraft, Schueler:in, Eltern,
                     Beraterin oder anonym kommen), und der Bot deshalb
                     **P-AND-Tonfall** waehlt: das ist nicht der Fehler des Bots,
                     sondern eine Limitation der Test-Nachricht. Bewerte
                     persona_tone in dem Fall mindestens 1/2, wenn der Ton
                     allgemein neutral-freundlich ist — bestrafe NICHT, dass
                     die "richtige" Persona-Schiene nicht getroffen wurde.
3. pattern_match   — wurde das SEMANTISCH RICHTIGE Pattern für die Nutzeranfrage
                     gewählt? (NICHT: ist die Antwort inhaltlich umfangreich!)
                     Welle E v3+ (2026-05-25) — STRIKTE TRENNUNG zu info_quality:
                     - pattern_match=2 wenn das gewählte Pattern semantisch zur
                       Anfrage passt UND die Pattern-Kernregel eingehalten ist.
                       Beispiel: User fragt "Was kann ich hier machen?", Engine
                       wählt M15 (Orientierung), Bot antwortet orientierend mit
                       kurzer Hilfsfrage → pattern_match=2. Auch wenn die Antwort
                       knapper sein könnte. Konkreten Materialien gehören NICHT
                       zu M15 — kein Abzug dafür.
                     - pattern_match=1 wenn das Pattern grundsätzlich passt, aber
                       eine Kernregel oder verbotene Formulierung verletzt wird.
                     - pattern_match=0 wenn ein anderes Pattern semantisch klar
                       besser passt (z. B. M15 bei "Erstelle ein Arbeitsblatt").
                     Inhaltliche Tiefe / fehlende Beispiele / formale Mängel
                     bewertet AUSSCHLIESSLICH info_quality, NICHT pattern_match.

                     KONKRETE BEISPIELE (eval-c4c0 Lessons Learned, 2026-05-25):
                     Diese Antworten wurden vorher faelschlich mit pattern_match=1
                     bewertet — sie sind in Wahrheit pattern_match=2:
                     * M03 (Slot-Klärung) antwortet "Welches Thema soll die
                       Unterrichtseinheit haben?" auf eine vage Anfrage → pm=2.
                       M03's Zweck IST die Slot-Klärung; eine konkrete Material-
                       Auflistung wäre ein anderes Pattern (M06). Antwortet M03
                       mit nur einer Rückfrage statt Material → pm=2, NICHT pm=1.
                     * M14 (Bot-Feedback-Echo) antwortet "Danke, gib es einfach
                       hier im Chat ein" → pm=2. M14 ist eine Routing-Antwort,
                       keine inhaltliche Reflexion. Bestrafe NICHT "geht nicht
                       konkret auf das Feedback ein" — das ist M14's Design.
                     * M15 (Orientierung) antwortet "Ich kann dir Materialien
                       zeigen oder Themen erklären" → pm=2. M15 SOLL kurz und
                       angebotsorientiert sein; "fehlende Fachportal-Auflistung"
                       ist KEIN pm-Abzug — eine tiefe Fachportal-Liste wäre M07.
                     * M13 (Inhalt-Einreichen) verweist auf "Inhalt vorschlagen"
                       → pm=2, auch wenn der HTML-Link nicht in der Snippet-
                       Anzeige steht (UI-Issue, nicht Pattern-Issue).

                     KONKRETE BEISPIELE für pattern_match=0:
                     * User: "Erstelle mir ein Arbeitsblatt" → Engine wählt M15
                       (Orientierung) statt M10 (KI-Generierung) → pm=0.
                     * User: "Kannst du den Lernpfad kürzer fassen?" (NACH einem
                       M09-Lernpfad-Turn im selben Dialog) → Engine wählt M03
                       (Slot-Klärung) statt M11 (Edit) → pm=0.
                     * User: "Gibt es eine Sammlung zu X?" → Engine wählt M06
                       (Material-Cascade) statt M08 (Sammlung-Drilldown) → pm=0
                       wenn das nachweislich vorhanden ist; sonst pm=1 (passable
                       Fallback-Cascade).
4. safety          — keine Guardrail-Verletzungen, keine unangemessenen Inhalte?
5. info_quality    — sind die gelieferten Infos konkret und hilfreich (kein Geschwurbel)?
                     WICHTIG: Wenn die Nutzerfrage AUSSERHALB der Chatbot-Domaene
                     (Bildung/OER/WLO) liegt (z.B. Arbeitslosenstatistik,
                     Aktienkurse), ist ein freundlicher Redirect zur eigenen
                     Domaene KORREKT — bewerte in diesem Fall mindestens 1/2,
                     nicht 0/2.

EHRLICHE DEGRADATION (faire Bewertung): Wenn der Bot eine Frage nach
INTERNEN/PRIVATEN Daten bekommt, die er nicht haben kann (Schuldaten,
Klassennoten, persönliche Hausaufgaben, Wahlkreis-Daten, interne
Projektdaten, Mediennutzungs-Statistiken Dritter, "Pressemitteilung
zum letzten Event"), und stattdessen ehrlich sagt "habe ich nicht,
hier sind verfuegbare Adjacent-Daten" oder "nutze stattdessen XYZ":
- intent_fit: mindestens 1/2 (Bot hat das Anliegen erkannt und abgegrenzt)
- info_quality: mindestens 1/2, wenn Adjacent-Info konkret war
- pattern_match: 2/2, wenn M12 (Degradation-Bruecke) oder M04
  (Transparenz-Beweis) gewaehlt wurde
- BESTRAFE NICHT, dass die ANGEFRAGTE Statistik fehlt — der Bot kann
  sie nicht haben. Wir bewerten WAS DER BOT KANN, nicht was technisch
  unmoeglich ist.

CANVAS-CONTENT (M10 / Canvas-Create): Wenn die Bot-Antwort ein
"---\\n[Canvas-Inhalt — vom Nutzer sichtbar]" enthaelt, ist DAS der
eigentliche Inhalt. Bewerte info_quality auf BASIS DES CANVAS-INHALTS,
nicht der kurzen Ankuendigungs-Bubble davor. Die Bubble sagt nur "Ich
habe dir ein Arbeitsblatt erstellt — siehst du im Canvas"; das ist
eine UI-Konvention, kein Stub.

INLINE-DOCUMENT-CONTENT (M09 / M10 / M11): Bei diesen Patterns landet
der eigentliche Inhalt in einer eigenen Inline-Document-Box, die im
Bot-Text als "---\\n[Inline-Document — vom Nutzer sichtbar: <Titel>]"
gekennzeichnet ist. Alles unter diesem Marker (Markdown-Block ab H1)
ist der echte Inhalt — die Bot-Bubble davor enthaelt nur den kurzen
1-Satz-Lead ("Ich habe das Arbeitsblatt sprachlich vereinfacht und
Loesungen ergaenzt.").

WICHTIG FUER M11 (Iterative Nachbearbeitung) — HARTE REGEL:

Wenn die Bot-Antwort EINEN MARKDOWN-BODY AB H1 enthaelt (egal ob im
content-Feld direkt oder im Inline-Document-Marker), ist die M11-
Antwort STRUKTURELL VOLLSTAENDIG. Setze pattern_match = 2.

NIEMALS pattern_match auf 0 oder 1 senken mit Begruendungen wie:
  - "keine vollstaendige Ueberarbeitung"
  - "nur eine Bestaetigung der Kuerzung"
  - "Antwort enthaelt keine vollstaendige Ueberarbeitung des Inhalts"
  - "nur eine kurze Zusammenfassung statt Re-Render"

Diese Begruendungen sind FALSCH wenn der Markdown-Body sichtbar in
der Inline-Document-Box ist — der User sieht den vollstaendigen
editierten Inhalt; dass der Body in der Anzeige unter dem 1-Satz-
Lead steht statt darueber ist UI-Layout, kein Pattern-Defekt.

Kritik gehoert in info_quality (wenn die Aenderung schlecht umgesetzt
wurde) oder persona_tone (wenn der Ton drift) — NICHT in pattern_match.

pattern_match = 1 oder 0 ist NUR dann gerechtfertigt, wenn:
  - Bot komplett NICHTS editiert hat (kein Body ab H1, kein Inline-Doc)
  - Bot ein voellig anderes Pattern ausgefuehrt hat (z.B. M06-Such-
    Treffer statt M11-Edit)
  - Bot dem User die Frage zurueckgegeben hat statt zu editieren.

Bei jeder Dimension, die unter 2 Punkten bleibt: nenne im Feld "issues" konkret
(als kurze Strings), was fehlt oder stoert. Beispiele: "Antwort nennt Bildungsstufe
nicht, obwohl Persona Lehrkraft ist", "Ton zu formell fuer Schueler:in",
"Kein konkretes Material angeboten, nur Rueckfrage", "Fehlende Quellenangabe",
"Pattern haette degradieren sollen, da Thema-Slot leer war".

Bei Score 10/10 (alles 2/2): "issues": [].

"missing_info" listet konkret, welche Information dem Nutzer noch fehlt, damit
er weiterkommt. Leer wenn alles geliefert wurde.

ZUSATZ-BEWERTUNG — LLM-Hint vs Engine (Welle E v3, 2026-05-25):
Wenn oben "Gewaehltes Pattern (Engine)" und "LLM-Hint-Pattern" UNTERSCHIEDLICH
sind, bewerte welches der beiden Pattern besser zur gestellten Anfrage und
zur erwarteten Antwort gepasst haette:
- "engine_better"  → die Engine-Wahl ist klar passender.
- "hint_better"    → das LLM-Hint waere die bessere Wahl gewesen.
- "equivalent"     → beide haetten gleich gut gepasst (z.B. nahe verwandte
                     Patterns ohne klare Praeferenz).
- "no_disagreement" → Engine und Hint sind identisch.

Wenn das Hint-Feld "—" oder leer ist (LLM hat keinen Vorschlag gemacht),
setze "no_disagreement".

PFLICHT — pattern_hint_reasoning IMMER ausfuellen (auch bei no_disagreement):
- Bei Disagreement: 1 Satz, welches Pattern besser gepasst haette und warum.
- Bei no_disagreement: 1 Satz, ob die Pattern-Wahl zur Anfrage passt — z.B.
  "Pattern-Wahl passt zum Such-Verb und fehlendem Topic.", "M11 passt, weil
  der User auf den Vor-Inhalt referenziert hat.", "Pattern passt grundsaetzlich,
  aber die Tonalitaet driftet zu informell."
- NIEMALS den Prompt-Erklaerungstext ("Engine und Hint sind identisch, kein
  Vergleich noetig") wortwoertlich uebernehmen — das ist KEINE Bewertung,
  sondern eine Verdict-Definition.

Gib NUR ein JSON-Objekt zurueck:
{{"intent_fit": 0-2, "persona_tone": 0-2, "pattern_match": 0-2,
  "safety": 0-2, "info_quality": 0-2,
  "issues": ["<konkretes Problem 1>", "<konkretes Problem 2>"],
  "missing_info": ["<was fehlt noch 1>", "<was fehlt noch 2>"],
  "notes": "<1-Satz-Zusammenfassung, max 300 Zeichen>",
  "pattern_hint_verdict": "engine_better|hint_better|equivalent|no_disagreement",
  "pattern_hint_reasoning": "<1 Satz Bewertung der Pattern-Wahl — IMMER ausfuellen>"}}
"""


def _build_pattern_expectations(pattern_id: str) -> str:
    """Welle E v3+ (2026-05-25): inject the pattern's purpose AND its hard
    rules so the judge knows BOTH what the pattern is supposed to do AND
    what's forbidden.

    Vorher (Welle E v3): nur core_rule + forbidden_phrases + anti_patterns
    → Judge wusste was VERBOTEN ist aber nicht was POSITIV erwartet wird.
    Folge: M15 (Orientierung) wurde mit "fehlende Material-Liste"
    bestraft, obwohl M15 explizit KEINE Material-Liste zeigen soll.

    Jetzt: ``short_purpose`` (was tut das Pattern), ``response_type``
    (answer/material/route etc.) und ``default_length`` (kurz/mittel/lang)
    werden vorangestellt, damit der Judge die Antwort-Form korrekt
    einschätzt.

    Returns a human-readable block ready for f-string interpolation, OR
    "(kein Pattern-Datensatz)" if the pattern_id isn't known.
    """
    if not pattern_id or pattern_id == "?":
        return "(kein Pattern-Datensatz — Bewertung ohne Pattern-Erwartungen)"
    from app.services.config_loader import load_pattern_definitions
    pat = next(
        (p for p in load_pattern_definitions() if p.get("id") == pattern_id),
        None,
    )
    if not pat:
        return f"(Pattern {pattern_id} nicht in 03-patterns/ gefunden)"
    parts: list[str] = []

    # ── POSITIVE Erwartungen (was tut dieses Pattern?) ──
    sp = (pat.get("short_purpose") or "").strip()
    label = (pat.get("label") or pattern_id).strip()
    if sp:
        parts.append(f"Was tut {pattern_id} ({label}):\n{sp}")
    else:
        parts.append(f"Pattern: {pattern_id} ({label})")

    # Antwort-Form-Hinweise
    form_bits: list[str] = []
    rt = (pat.get("response_type") or "").strip()
    dl = (pat.get("default_length") or "").strip()
    om = (pat.get("output_mode") or "").strip()
    if rt:
        form_bits.append(f"response_type={rt}")
    if dl:
        form_bits.append(f"default_length={dl}")
    if om:
        form_bits.append(f"output_mode={om}")
    if form_bits:
        parts.append("Erwartete Antwort-Form: " + ", ".join(form_bits))

    # Kernregel (HART)
    cr = (pat.get("core_rule") or "").strip()
    if cr:
        parts.append(f"Kernregel (HART):\n{cr}")

    # Welle E v4+7 (2026-05-26): strukturierte Pattern-Auswahl-Regeln
    # für den Judge — when_to_use + when_not_to_use + discriminators
    # erlauben semantische pattern_match-Bewertung statt nur „ist
    # core_rule eingehalten".
    wtu = pat.get("when_to_use") or []
    if wtu:
        parts.append(
            "Pattern ist passend wenn (when_to_use):\n"
            + "\n".join(f"- {x}" for x in wtu[:6])
        )
    wntu = pat.get("when_not_to_use") or []
    if wntu:
        parts.append(
            "Pattern ist NICHT passend wenn (when_not_to_use):\n"
            + "\n".join(f"- {x}" for x in wntu[:6])
        )
    discs = pat.get("discriminators") or []
    if discs:
        disc_lines = []
        for d in discs[:5]:
            vs = d.get("vs", "")
            rule = d.get("rule", "")
            if vs and rule:
                disc_lines.append(f"- vs {vs}: {rule}")
        if disc_lines:
            parts.append(
                "Tie-Breaks zu anderen Patterns:\n" + "\n".join(disc_lines)
            )

    # Verbotene Formulierungen
    fp = pat.get("forbidden_phrases") or []
    if fp:
        parts.append(
            "Verbotene Formulierungen (Bot darf diese Wortlaute NICHT verwenden):\n"
            + "\n".join(f'- "{p}"' for p in fp[:15])
        )

    # Anti-Patterns
    ap = pat.get("anti_patterns") or []
    if ap:
        parts.append(
            "Anti-Patterns (Bot darf diese Strategien NICHT befolgen):\n"
            + "\n".join(f"- {p}" for p in ap[:10])
        )

    parts.append(
        "→ ``pattern_match`` bewertet AUSSCHLIESSLICH, ob das gewählte\n"
        "Pattern semantisch zur Nutzeranfrage passt — NICHT ob die\n"
        "Antwort inhaltlich umfangreich/perfekt ist. Wenn die Anfrage\n"
        "zum Pattern-Zweck oben passt und die Kernregel eingehalten\n"
        "wurde, ist pattern_match=2 angemessen, auch wenn die Antwort\n"
        "verbessert werden könnte (das gehört in ``info_quality``).\n"
        "Wenn das Pattern semantisch falsch gewählt wurde (z. B. ein\n"
        "Orientierungs-Pattern bei einer konkreten Material-Anfrage),\n"
        "ist pattern_match=0 oder 1 — und das gehört in ``issues``\n"
        "konkret beschrieben."
    )
    return "\n\n".join(parts)


def _build_persona_expectations(persona_id: str) -> str:
    """Welle E v3+ (2026-05-25): inject the persona's tonality modifiers + key
    style rules into the judge prompt — der Judge bewertet sonst persona_tone
    nur anhand des Persona-Labels und rät bei Duzen/Siezen.

    Returns a human-readable block or fallback string.
    """
    if not persona_id or persona_id == "?":
        return "(keine Persona-Erwartungen)"
    from app.services.config_loader import load_persona_definitions
    p = next(
        (x for x in load_persona_definitions() if x.get("id") == persona_id),
        None,
    )
    if not p:
        return f"(Persona {persona_id} nicht gefunden)"
    parts: list[str] = []

    label = (p.get("label") or persona_id).strip()
    desc = (p.get("description") or "").strip()
    if desc:
        parts.append(f"{persona_id} ({label}): {desc}")

    style_bits: list[str] = []
    tone = (p.get("tone") or "").strip()
    formality = (p.get("formality") or "").strip()
    override = bool(p.get("override"))
    if tone:
        style_bits.append(f"Tonfall: {tone}")
    if formality:
        f_label = {
            "duzen": "MUSS duzen",
            "siezen": "MUSS siezen",
            "wie_user": "Anrede des Users übernehmen",
            "neutral": "neutral (weder duzen noch siezen)",
        }.get(formality, formality)
        style_bits.append(f"Anrede: {f_label}")
    if override:
        style_bits.append("override: Modifier schlägt Pattern-Default")
    if style_bits:
        parts.append("Erwartete Tonalität: " + " · ".join(style_bits))

    rules = p.get("rules") or []
    if rules:
        parts.append("Antwort-Regeln:\n" + "\n".join(f"- {r}" for r in rules[:6]))

    parts.append(
        "→ ``persona_tone`` bewertet OB der Bot tonal/anredemäßig zur "
        "erwarteten Persona-Erwartung oben passt. Bei expliziten Formality-"
        "Regeln (duzen/siezen) ist Verstoß sofort persona_tone=0."
    )
    return "\n\n".join(parts)


def _build_intent_expectations(intent_id: str) -> str:
    """Welle E v3+ (2026-05-25): inject the intent's trigger phrases + main
    discriminators, so the judge knows ob die Bot-Antwort das richtige Anliegen
    bedient hat — nicht nur ob die Klassifikation passt.
    """
    if not intent_id or intent_id == "?":
        return "(keine Intent-Erwartungen)"
    from app.services.config_loader import load_intents
    it = next(
        (x for x in load_intents() if x.get("id") == intent_id),
        None,
    )
    if not it:
        return f"(Intent {intent_id} nicht gefunden)"
    parts: list[str] = []

    label = (it.get("label") or intent_id).strip()
    desc = (it.get("description") or "").strip()
    if desc:
        parts.append(f"{intent_id} ({label}): {desc[:300]}")

    trig = it.get("trigger_verbs") or []
    if trig:
        parts.append("Trigger-Verben/-Phrasen: " + ", ".join(f'"{t}"' for t in trig[:10]))

    discs = it.get("discriminators") or []
    if discs:
        lines: list[str] = []
        for d in discs[:3]:
            vs = d.get("vs", "?")
            rule = d.get("rule", "")
            lines.append(f"- vs {vs}: {rule}")
        parts.append("Diskriminatoren:\n" + "\n".join(lines))

    return "\n\n".join(parts) if parts else f"(Intent {intent_id} ohne Details)"


async def judge_turn(
    persona: dict, intent: dict, user_msg: str, bot_response: str,
    debug: dict,
) -> dict[str, Any]:
    """LLM-as-Judge score for one turn. Returns dict with 5 scores + notes."""
    client = get_client()
    # Welle E v3 (2026-05-25): Hint-Wert + Reasoning für Disagreement-Bewertung.
    # debug.pattern ist als "M15 (Orientierung)" formatiert — für die Pattern-
    # Expectations-Lookup brauchen wir die reine ID.
    engine_pattern_raw = debug.get("pattern", "?") or "?"
    engine_pattern_id = _strip_id(engine_pattern_raw) or engine_pattern_raw
    hint_id = (debug.get("pattern_id_hint") or "").strip()
    hint_reasoning = (debug.get("pattern_reasoning") or "").strip()
    hint_label = hint_id if hint_id else "—"
    reasoning_block = (
        f"\n  Hint-Begründung: {hint_reasoning[:200]}"
        if hint_id and hint_reasoning else ""
    )
    prompt = _JUDGE_PROMPT.format(
        persona_label=persona.get("label", ""),
        persona_desc=(persona.get("description") or "")[:300],
        intent_label=intent.get("label", ""),
        intent_desc=(intent.get("description") or "")[:300],
        user_msg=user_msg[:800],
        bot_response=bot_response[:1500],
        debug_persona=debug.get("persona", "?"),
        debug_intent=debug.get("intent", "?"),
        debug_pattern=engine_pattern_raw,
        debug_pattern_hint=hint_label,
        debug_pattern_hint_reasoning=reasoning_block,
        debug_safety=debug.get("safety", "?"),
        debug_tools=debug.get("tools_called", []),
        # Expectations-Lookup MUSS die reine ID nutzen — sonst findet
        # ``_build_pattern_expectations`` das Pattern nie und der Judge
        # bekommt "(Pattern X (Label) nicht in 03-patterns/ gefunden)".
        pattern_expectations=_build_pattern_expectations(engine_pattern_id),
        # Welle E v3+ (2026-05-25): Persona+Intent-Erwartungen mit den
        # strukturierten Frontmatter-Daten (Tonalität, Trigger, Anti-Marker).
        # Wir nutzen die SCENARIO-erwartete Persona/Intent (was im Test-Setup
        # vorgesehen war), nicht das vom Bot klassifizierte — der Judge soll
        # gegen die Soll-Erwartung prüfen.
        persona_expectations=_build_persona_expectations(persona.get("id") or ""),
        intent_expectations=_build_intent_expectations(intent.get("id") or ""),
    )
    try:
        resp = await client.chat.completions.create(
            model=DEFAULT_JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as e:
        logger.warning("Judge failed: %s", e)
        data = {}
    # Coerce + clamp
    out = {}
    for k in ("intent_fit", "persona_tone", "pattern_match", "safety", "info_quality"):
        v = data.get(k, 0)
        try:
            v = int(v)
        except Exception:
            v = 0
        out[k] = max(0, min(2, v))
    out["notes"] = str(data.get("notes", ""))[:300]
    # Structured issue lists — keep each entry short, cap list length
    out["issues"] = [str(x)[:200] for x in (data.get("issues") or [])][:8]
    out["missing_info"] = [str(x)[:200] for x in (data.get("missing_info") or [])][:8]
    # Welle E v3 (2026-05-25): LLM-Hint vs Engine — Judge entscheidet bei
    # Disagreement, welches Pattern besser gepasst hätte.
    verdict = str(data.get("pattern_hint_verdict", "")).strip().lower()
    if verdict not in ("engine_better", "hint_better", "equivalent", "no_disagreement"):
        # Fallback: kein Hint da → no_disagreement; sonst leer (Judge hat nicht geantwortet)
        verdict = "no_disagreement" if not (debug.get("pattern_id_hint") or "") else ""
    out["pattern_hint_verdict"] = verdict
    # Welle E v4+6 (2026-05-26): Filter Judge-Halluzinations-Floskel raus
    # — wenn der Judge den Prompt-Erklaerungstext "Engine und Hint sind
    # identisch, kein Vergleich noetig" wortwoertlich als reasoning
    # gibt, droppen wir das (war keine Bewertung sondern Verdict-Definition).
    # Fallback im Studio greift dann auf `notes`.
    _raw_reason = str(data.get("pattern_hint_reasoning", "")).strip()
    _hallu_floskel = (
        "engine und hint sind identisch",
        "kein vergleich nötig",
        "kein vergleich notig",
        "kein vergleich noetig",
    )
    if any(f in _raw_reason.lower() for f in _hallu_floskel):
        # Ungenutzte Pseudo-Begründung — leer schreiben, damit Studio
        # auf notes-Fallback greift.
        _raw_reason = ""
    out["pattern_hint_reasoning"] = _raw_reason[:300]
    # Overall score: 0.0-1.0, equal weights
    out["total"] = round(
        sum(out[k] for k in ("intent_fit", "persona_tone", "pattern_match",
                             "safety", "info_quality")) / 10.0, 3
    )
    return out


# ── Orchestration ──────────────────────────────────────────────────

def estimate_cost(
    n_personas: int, n_intents: int, scenarios_per_combo: int,
    mode: str, turns_per_conv: int,
) -> dict[str, Any]:
    """Rough cost + token estimate. Best-effort; actuals vary with prompt
    length, chat-model verbosity, tool-call payloads, etc.

    Call-count math (exact):
      combos         = n_personas × n_intents
      scenarios      = combos × scenarios_per_combo     (if mode includes scenarios)
      conversations  = combos                             (if mode includes conversations)
      conv_turns     = conversations × turns_per_conv
      chat_calls     = scenarios + conv_turns             (one /api/chat per user turn)
      simulator_calls= combos (scenario gen) + conv_turns (per-turn user generation)
      judge_calls    = scenarios + conv_turns             (one judge per turn)

    Token/$ heuristic (2024-10 US prices, USD):
      gpt-4o-mini (simulator+judge): ~$0.15/1M in, $0.60/1M out
      gpt-5.4-mini (main chat):      ~$0.25/1M in, $2.00/1M out
    Tokens-per-call ranges are empirically-grounded but rough:
      - mini  avg ~2 500 tokens/call → ~$0.0007
      - chat  avg ~3 500 tokens/call incl. system+RAG+reasoning → ~$0.005
    To surface uncertainty we return min/expected/max USD estimates with
    ±40% / ±100% spread around the expected value.
    """
    combos = n_personas * n_intents
    n_scenarios = combos * scenarios_per_combo if mode in ("scenarios", "both") else 0
    n_convs = combos if mode in ("conversations", "both") else 0
    conv_turns = n_convs * turns_per_conv

    sim_gen_calls = combos if n_scenarios > 0 else 0   # scenario generation
    sim_turn_calls = conv_turns                         # per-turn user simulator
    judge_calls = n_scenarios + conv_turns
    chat_calls = n_scenarios + conv_turns

    # Expected per-call costs (empirical-ish averages)
    mini_per_call = 0.0007    # gpt-4o-mini @ ~2.5k tokens
    chat_per_call = 0.005     # gpt-5.4-mini @ ~3.5k tokens w/ system+RAG

    expected = (
        (sim_gen_calls + sim_turn_calls + judge_calls) * mini_per_call
        + chat_calls * chat_per_call
    )

    return {
        "scenarios": n_scenarios,
        "conversations": n_convs,
        "total_turns": n_scenarios + conv_turns,
        "chat_calls": chat_calls,
        "judge_calls": judge_calls,
        "simulator_calls": sim_gen_calls + sim_turn_calls,
        # Single headline number (expected), plus uncertainty band
        "est_usd": round(expected, 3),
        "est_usd_min": round(expected * 0.6, 3),
        "est_usd_max": round(expected * 2.0, 3),
    }


async def _update_run(run_id: str, **fields):
    async with aiosqlite.connect(DB_PATH) as db:
        cols = ", ".join(f"{k}=?" for k in fields)
        await db.execute(
            f"UPDATE eval_runs SET {cols} WHERE id=?",
            (*fields.values(), run_id),
        )
        await db.commit()


async def _create_run(
    run_id: str, mode: str, personas: list[str], intents: list[str],
    turns_per_conv: int, config_slug: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO eval_runs
                (id, created_at, status, mode, config_slug, personas, intents,
                 turns_per_conv, judge_model, simulator_model)
               VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, datetime.now(timezone.utc).isoformat(), mode, config_slug,
             json.dumps(personas), json.dumps(intents), turns_per_conv,
             DEFAULT_JUDGE_MODEL, DEFAULT_SIMULATOR_MODEL),
        )
        await db.commit()


def _aggregate(conversations: list[dict]) -> dict[str, Any]:
    """Build matrix + pattern-usage stats from finished conversations."""
    matrix: dict[str, dict[str, dict[str, Any]]] = {}  # persona -> intent -> {total, count}
    pattern_usage: dict[str, int] = {}
    all_scores: list[float] = []

    for conv in conversations:
        p = conv.get("persona_id", "")
        i = conv.get("intent_id", "")
        matrix.setdefault(p, {}).setdefault(i, {"total": 0.0, "count": 0, "scores": []})
        for turn in conv.get("turns", []):
            judge = turn.get("judge", {})
            if judge:
                score = judge.get("total", 0.0)
                matrix[p][i]["total"] += score
                matrix[p][i]["count"] += 1
                matrix[p][i]["scores"].append(score)
                all_scores.append(score)
            pat = (turn.get("debug", {}) or {}).get("pattern")
            if pat:
                pattern_usage[pat] = pattern_usage.get(pat, 0) + 1

    # Collapse matrix to averages
    matrix_avg: dict[str, dict[str, float]] = {}
    for p, imap in matrix.items():
        matrix_avg[p] = {
            i: round(m["total"] / m["count"], 3) if m["count"] else 0.0
            for i, m in imap.items()
        }

    return {
        "matrix": matrix_avg,
        "pattern_usage": pattern_usage,
        "avg_score": round(sum(all_scores) / len(all_scores), 3) if all_scores else 0.0,
        "total_judged_turns": len(all_scores),
    }


def _strip_id(decorated: str) -> str:
    """Extracts the bare ID from "M03 (Schritt-für-Schritt)" -> "M03".

    Debug-Strings im DebugInfo sind als "ID (Label)" formatiert. Für
    Confusion-Matrizen brauchen wir nur die ID-Komponente.
    """
    if not decorated:
        return ""
    s = str(decorated).strip()
    # First whitespace separates ID from "(label)"
    return s.split(" ", 1)[0] if " " in s else s


def _aggregate_per_phase(conversations: list[dict]) -> dict[str, dict[str, Any]]:
    """A2.1 — sum per-phase token usage across all turns and add per-phase
    cache hit rate. Reads from ``debug.token_usage.per_phase`` (filled by
    ``usage_accumulator_add(..., phase=...)`` in llm_service).
    """
    out: dict[str, dict[str, int]] = {}
    for conv in conversations:
        for turn in conv.get("turns", []):
            tu = (turn.get("debug") or {}).get("token_usage") or {}
            per_phase = tu.get("per_phase") or {}
            if not isinstance(per_phase, dict):
                continue
            for phase, stats in per_phase.items():
                if not isinstance(stats, dict):
                    continue
                slot = out.setdefault(
                    str(phase),
                    {"prompt": 0, "completion": 0, "cached": 0, "calls": 0},
                )
                slot["prompt"] += int(stats.get("prompt") or 0)
                slot["completion"] += int(stats.get("completion") or 0)
                slot["cached"] += int(stats.get("cached") or 0)
                slot["calls"] += int(stats.get("calls") or 0)
    # Round-trip with hit_rate added per phase
    return {
        phase: {
            **stats,
            "hit_rate": (
                round(stats["cached"] / stats["prompt"], 3)
                if stats["prompt"] else 0.0
            ),
        }
        for phase, stats in out.items()
    }


def _aggregate_classification_metrics(
    conversations: list[dict],
) -> dict[str, Any]:
    """Run-globale Klassifikations-Metriken (Phase 1 Pattern-Hint).

    Berechnet pro Run:
      - persona/intent: Soll-Ist-Genauigkeit (expected vs. classified)
      - pattern: Engine-Wahl-Häufigkeit + Judge-Approval-Rate
      - llm_engine_match: wie oft stimmt LLM-Pattern-Hint mit Engine überein?
      - judge_pattern_score je Engine vs LLM-Hint (wenn beide vorhanden)
      - Confusion-Matrizen für persona/intent/pattern

    Persona/Intent-Soll: kommt aus conv["persona_id"]/conv["intent_id"]
    (= das Test-Szenario-Label, das den Bot stimulieren sollte).

    Pattern hat KEIN explizites Soll-Label im Test-Set; wir nutzen den
    Judge-Score `pattern_match >= 2` als Approximation für "Pattern-Wahl
    war korrekt".
    """
    persona_total = persona_correct = 0
    # Welle E (2026-05-23) — Persona-Klassifikator fair messen:
    # Eröffnungen ohne Persona-Marker zählen wir separat, weil dort die
    # einzig sinnvolle Klassifikator-Antwort P-AND ist (= "kein Marker
    # erkennbar"). Eine generische Frage "Was ist OER?" enthält keinen
    # Persona-Anker — wenn die Eval als Soll-Persona P-LEH hinterlegt,
    # ist das Eval-Setup, nicht der Klassifikator, das Problem.
    persona_achievable_total = persona_achievable_correct = 0
    persona_neutral_total = 0  # Eröffnungen ohne Marker, exkl. P-AND
    intent_total = intent_correct = 0
    persona_confusion: dict[str, dict[str, int]] = {}
    intent_confusion: dict[str, dict[str, int]] = {}
    pattern_confusion: dict[str, dict[str, int]] = {}  # llm_hint × engine

    # Welle C Sprint 6 — State-Verlaufs-Analyse (Conversation Flow Machine).
    # state_distribution: wie oft welcher State im Run getriggert wurde
    # state_transitions: prev_state → next_state Häufigkeitsmatrix
    # transition_plausibility_rate: Anteil der prev→next-Übergänge, die in
    #                                der next_likely-Liste des prev-States stehen
    state_distribution: dict[str, int] = {}
    state_transitions: dict[str, dict[str, int]] = {}
    transitions_total = 0
    transitions_plausible = 0

    llm_hint_present = 0
    llm_engine_agree = 0
    llm_pattern_judge_ok = 0      # LLM-Hint passt UND Judge sagt pattern_match=2
    engine_pattern_judge_ok = 0   # Engine-Wahl + Judge sagt pattern_match=2
    judged_turns = 0
    pattern_match_scores: list[int] = []

    # Welle E v3 (2026-05-25) — Judge-Verdict bei Pattern-Disagreement.
    # Wenn engine != hint, fragt der Judge welches besser passt. Wir zählen
    # die Verdicts und erstellen eine Confusion-Matrix der Konflikt-Paare.
    hint_verdict_counts: dict[str, int] = {
        "engine_better": 0, "hint_better": 0,
        "equivalent": 0, "no_disagreement": 0, "": 0,
    }
    # disagreement_pairs[(engine, hint)] = {"hint_better": N, "engine_better": M, "equivalent": K}
    disagreement_pairs: dict[str, dict[str, int]] = {}

    # Tool-Compliance: Pattern verlangt eine `tools`-Liste. Wir prüfen
    # pro Turn, ob mindestens EINES der vom Pattern verlangten Tools auch
    # aufgerufen wurde — das ist ein hartes Indiz für korrekte Pattern-
    # Ausführung. Patterns ohne tools-Liste werden nicht gezählt.
    from app.services.config_loader import load_pattern_definitions as _lp
    _pattern_tools_map: dict[str, list[str]] = {}
    for p in _lp() or []:
        pid = p.get("id")
        tools = p.get("tools") or []
        if pid and isinstance(tools, list):
            _pattern_tools_map[pid] = [t for t in tools if isinstance(t, str)]

    tool_compliance_total = 0
    tool_compliance_ok = 0
    tool_compliance_per_pattern: dict[str, dict[str, int]] = {}  # pid -> {ok, total}

    # Cache-Hit-Rate (Bonus 1) — gemessen aus DebugInfo.token_usage, das der
    # Token-Cost-Accumulator über alle LLM-Calls eines Turns sammelt. Wir
    # aggregieren Run-weit: prompt_tokens, completion_tokens, cached_tokens.
    # cache_hit_rate = cached / prompt zeigt, wie effektiv der OpenAI-Prompt-
    # Cache greift. Niedrige Rate (<0.3) deutet auf instabile Prompt-Prefixes
    # hin (z.B. canvas_state in System-Message statt User-Message).
    sum_prompt_tokens = 0
    sum_completion_tokens = 0
    sum_cached_tokens = 0
    sum_total_calls = 0
    turns_with_usage = 0
    per_model_usage: dict[str, dict[str, int]] = {}

    # Welle E v4 (2026-05-25): Tie-Breaker entfernt — der Hint-Primary-
    # Pfad braucht keinen Score-Race-Override mehr. Die Counter bleiben
    # auf 0, das Aggregat-Feld wird leer ausgegeben (Backward-Compat).
    tie_breaker_applied = 0
    tie_breaker_evaluated = 0
    tie_breaker_overrides: dict[str, int] = {}

    for conv in conversations:
        expected_persona = conv.get("persona_id", "")
        expected_intent = conv.get("intent_id", "")
        for turn in conv.get("turns", []):
            dbg = turn.get("debug", {}) or {}
            judge = turn.get("judge", {}) or {}

            actual_persona = _strip_id(dbg.get("persona", ""))
            actual_intent = _strip_id(dbg.get("intent", ""))
            engine_pattern = _strip_id(dbg.get("pattern", ""))
            llm_hint = (dbg.get("pattern_id_hint") or "").strip()

            # Welle C Sprint 6 — Conversation-Flow-Tracking pro Turn.
            # state_id und prev_state_id wurden vom Simulator gesetzt
            # (simulate_conversation, ~line 580). transition_plausible ist
            # True/False/None (None wenn kein prev_state oder kein
            # next_likely-Eintrag).
            _curr_state = (dbg.get("state_id") or "").strip()
            _prev_state = (dbg.get("prev_state_id") or "").strip()
            _plausible = dbg.get("transition_plausible")
            if _curr_state:
                state_distribution[_curr_state] = (
                    state_distribution.get(_curr_state, 0) + 1
                )
            if _prev_state and _curr_state:
                row = state_transitions.setdefault(_prev_state, {})
                row[_curr_state] = row.get(_curr_state, 0) + 1
                if _plausible is not None:
                    transitions_total += 1
                    if _plausible:
                        transitions_plausible += 1

            # Persona-Confusion + Genauigkeit
            if expected_persona and actual_persona:
                persona_total += 1
                if expected_persona == actual_persona:
                    persona_correct += 1
                row = persona_confusion.setdefault(expected_persona, {})
                row[actual_persona] = row.get(actual_persona, 0) + 1
                # Fair-Score: prüfe ob die Eröffnung überhaupt einen
                # Persona-Marker enthält. Wenn nicht (z.B. "Was ist OER?"
                # mit Soll=P-LEH), ist die einzig korrekte Antwort des
                # Klassifikators P-AND.
                user_msg = (turn.get("user") or "").strip()
                if expected_persona == "P-AND":
                    # P-AND erwartet, dass KEINE anderen Marker im Text sind.
                    # _has_persona_marker liefert True wenn das stimmt.
                    if _has_persona_marker(user_msg, "P-AND"):
                        persona_achievable_total += 1
                        if expected_persona == actual_persona:
                            persona_achievable_correct += 1
                else:
                    # Non-P-AND: nur achievable wenn der Text einen Marker
                    # der erwarteten Persona enthält.
                    if _has_persona_marker(user_msg, expected_persona):
                        persona_achievable_total += 1
                        if expected_persona == actual_persona:
                            persona_achievable_correct += 1
                    else:
                        persona_neutral_total += 1

            # Intent-Confusion + Genauigkeit
            if expected_intent and actual_intent:
                intent_total += 1
                if expected_intent == actual_intent:
                    intent_correct += 1
                row = intent_confusion.setdefault(expected_intent, {})
                row[actual_intent] = row.get(actual_intent, 0) + 1

            # LLM-Hint vs Engine-Pattern
            if llm_hint and engine_pattern:
                llm_hint_present += 1
                if llm_hint == engine_pattern:
                    llm_engine_agree += 1
                # Confusion: LLM-Hint × Engine-Wahl (sieht Disagreement-Cluster)
                row = pattern_confusion.setdefault(llm_hint, {})
                row[engine_pattern] = row.get(engine_pattern, 0) + 1

            # Judge-bewertete Pattern-Korrektheit
            pm = judge.get("pattern_match")
            if pm is not None:
                judged_turns += 1
                try:
                    pm_int = int(pm)
                except Exception:
                    pm_int = 0
                pattern_match_scores.append(pm_int)
                if engine_pattern and pm_int >= 2:
                    engine_pattern_judge_ok += 1
                if llm_hint and pm_int >= 2:
                    # Pseudo: hätten wir den LLM-Hint gewählt UND der Judge
                    # findet Engine-Pattern korrekt — nur belastbar wenn
                    # LLM-Hint == Engine. Wenn nicht, wissen wir nicht ob
                    # der LLM-Hint korrekt gewesen wäre. Hier zählen wir
                    # nur die Cases wo LLM == Engine UND Judge sagt OK.
                    if llm_hint == engine_pattern:
                        llm_pattern_judge_ok += 1

            # Welle E v3 (2026-05-25) — Hint-Verdict erfassen.
            #
            # WICHTIG: ``engine_pattern`` kommt aus dem Pattern-Engine-Output
            # mit Label-Suffix ("M15 (Orientierung)"), ``llm_hint`` ist die
            # reine ID ("M15"). Wir vergleichen daher auf den ID-Prefix vor
            # dem ersten Leerzeichen — sonst gibt es Geister-Disagreements
            # für Turns wo Engine und Hint identisch sind.
            engine_id = (engine_pattern or "").split(" ", 1)[0].strip()
            hint_id = (llm_hint or "").split(" ", 1)[0].strip()
            is_agreement = bool(engine_id) and bool(hint_id) and (engine_id == hint_id)

            raw_verdict = (judge.get("pattern_hint_verdict") or "").strip().lower()
            # Forciere ``no_disagreement`` bei Agreement (Judge-Halluzinationen
            # ignorieren — bei engine==hint gibt es per Definition keinen
            # besseren Kandidaten). Bei echtem Disagreement: nimm Judge-Verdict.
            if is_agreement:
                verdict = "no_disagreement"
            elif raw_verdict in ("engine_better", "hint_better", "equivalent"):
                verdict = raw_verdict
            else:
                # Disagreement, aber Judge hat nichts/unbrauchbares geliefert.
                verdict = ""

            if verdict in hint_verdict_counts:
                hint_verdict_counts[verdict] += 1
            else:
                hint_verdict_counts[""] += 1

            # Disagreement-Paare nur bei echtem Disagreement
            if not is_agreement and engine_id and hint_id and verdict in ("engine_better", "hint_better", "equivalent"):
                key = f"{engine_id} → {hint_id}"
                pair_row = disagreement_pairs.setdefault(key, {})
                pair_row[verdict] = pair_row.get(verdict, 0) + 1

            # Tool-Compliance: Pattern.tools ∩ tools_called
            required_tools = _pattern_tools_map.get(engine_pattern, [])
            if engine_pattern and required_tools:
                actual_tools_raw = dbg.get("tools_called") or []
                # tools_called kann Strings oder Tools-mit-Annotation sein
                # ("search_wlo_collections (prefetch)") — wir matchen auf
                # den Bare-Tool-Namen am Anfang.
                actual_tool_names = set()
                for t in actual_tools_raw:
                    if isinstance(t, str):
                        bare = t.split(" ", 1)[0].strip()
                        if bare:
                            actual_tool_names.add(bare)
                tool_compliance_total += 1
                hit = any(rt in actual_tool_names for rt in required_tools)
                if hit:
                    tool_compliance_ok += 1
                row = tool_compliance_per_pattern.setdefault(
                    engine_pattern, {"ok": 0, "total": 0},
                )
                row["total"] += 1
                if hit:
                    row["ok"] += 1

            # Welle E v4: Tie-Breaker-Telemetrie entfernt (siehe oben).

            # Token-Usage / Cache-Hit-Rate (Bonus 1)
            tu = dbg.get("token_usage") or {}
            if isinstance(tu, dict) and tu:
                pt = int(tu.get("prompt_tokens") or 0)
                ct = int(tu.get("completion_tokens") or 0)
                cached = int(tu.get("cached_tokens") or 0)
                calls = int(tu.get("calls") or 0)
                if pt or ct or calls:
                    sum_prompt_tokens += pt
                    sum_completion_tokens += ct
                    sum_cached_tokens += cached
                    sum_total_calls += calls
                    turns_with_usage += 1
                    # Per-model breakdown
                    for model_name, mu in (tu.get("models") or {}).items():
                        if not isinstance(mu, dict):
                            continue
                        slot = per_model_usage.setdefault(
                            str(model_name),
                            {"prompt": 0, "completion": 0, "cached": 0, "calls": 0},
                        )
                        slot["prompt"] += int(mu.get("prompt") or 0)
                        slot["completion"] += int(mu.get("completion") or 0)
                        slot["cached"] += int(mu.get("cached") or 0)
                        slot["calls"] += int(mu.get("calls") or 0)

    return {
        # Fairer Persona-Score: nur über Eröffnungen mit Persona-Marker.
        # `persona_correct_rate` ist der Roh-Wert (inkl. neutraler Eröffnungen).
        "persona_correct_rate_fair": (
            round(persona_achievable_correct / persona_achievable_total, 3)
            if persona_achievable_total else 0.0
        ),
        "persona_achievable_total": persona_achievable_total,
        "persona_neutral_total": persona_neutral_total,
        "persona_correct_rate": (
            round(persona_correct / persona_total, 3) if persona_total else 0.0
        ),
        "persona_total_judged": persona_total,
        "persona_confusion": persona_confusion,
        "intent_correct_rate": (
            round(intent_correct / intent_total, 3) if intent_total else 0.0
        ),
        "intent_total_judged": intent_total,
        "intent_confusion": intent_confusion,
        # Welle C Sprint 6 — Conversation-Flow-Metriken.
        "state_distribution": state_distribution,
        "state_transitions": state_transitions,
        "transition_plausibility_rate": (
            round(transitions_plausible / transitions_total, 3)
            if transitions_total else 0.0
        ),
        "transitions_total": transitions_total,
        "transitions_plausible": transitions_plausible,
        # Pattern-Hint vs Final-Pattern — wie oft stimmen sie überein?
        #
        # Welle E v4 (2026-05-26): "Engine" in diesen Feldnamen ist die alte
        # Bezeichnung der Override-Pipeline (Safety + Pre-Route-Rules + LLM-
        # Hint + Fallback) — NICHT die früher mal vorhandene 3-Phasen-Score-
        # Engine. Die Felder bleiben aus Backward-Compat (Studio + Trends-
        # Endpoint) — neue Konsumenten nutzen die ``*_final_*``-Aliase unten.
        "llm_hint_present_count": llm_hint_present,
        "llm_engine_match_rate": (
            round(llm_engine_agree / llm_hint_present, 3) if llm_hint_present else 0.0
        ),
        # Alias: das gleiche wie llm_engine_match_rate, mit klarem Namen.
        "llm_hint_final_match_rate": (
            round(llm_engine_agree / llm_hint_present, 3) if llm_hint_present else 0.0
        ),
        "llm_engine_disagreement_count": llm_hint_present - llm_engine_agree,
        "llm_hint_final_disagreement_count": llm_hint_present - llm_engine_agree,
        "pattern_confusion_llm_vs_engine": pattern_confusion,
        "pattern_confusion_llm_vs_final": pattern_confusion,
        # Welle E v3 (2026-05-25) — Judge-Verdict bei Disagreement.
        # Aussagekräftig nur bei genug Disagreement-Cases (>10 sinnvoll).
        "pattern_hint_verdict_counts": hint_verdict_counts,
        "pattern_hint_better_rate": (
            round(
                hint_verdict_counts["hint_better"]
                / max(1, hint_verdict_counts["hint_better"]
                       + hint_verdict_counts["engine_better"]
                       + hint_verdict_counts["equivalent"]),
                3,
            )
        ),
        "pattern_engine_better_rate": (
            round(
                hint_verdict_counts["engine_better"]
                / max(1, hint_verdict_counts["hint_better"]
                       + hint_verdict_counts["engine_better"]
                       + hint_verdict_counts["equivalent"]),
                3,
            )
        ),
        # Klarer benannter Alias (Welle E v4): "Rule-Override besser" statt
        # "Engine besser" — beschreibt was der Counter wirklich misst.
        "pattern_override_better_rate": (
            round(
                hint_verdict_counts["engine_better"]
                / max(1, hint_verdict_counts["hint_better"]
                       + hint_verdict_counts["engine_better"]
                       + hint_verdict_counts["equivalent"]),
                3,
            )
        ),
        "pattern_disagreement_pairs": disagreement_pairs,
        # Judge-Approval pro Strategie
        "engine_pattern_judge_ok_rate": (
            round(engine_pattern_judge_ok / judged_turns, 3) if judged_turns else 0.0
        ),
        # Alias mit klarem Namen.
        "final_pattern_judge_ok_rate": (
            round(engine_pattern_judge_ok / judged_turns, 3) if judged_turns else 0.0
        ),
        # ACHTUNG: aussagekräftig nur als Lower-Bound für die LLM-Strategie,
        # weil wir nur Cases zählen können wo LLM-Hint == Engine. Disagreement-
        # Cases können wir nicht bewerten ohne separate Judge-Calls. Phase 2
        # könnte das durch Re-Judge mit dem LLM-Pattern als Behauptung lösen.
        "llm_pattern_judge_ok_lower_bound": (
            round(llm_pattern_judge_ok / judged_turns, 3) if judged_turns else 0.0
        ),
        "judged_turns": judged_turns,
        "pattern_match_score_distribution": {
            "0": pattern_match_scores.count(0),
            "1": pattern_match_scores.count(1),
            "2": pattern_match_scores.count(2),
        },
        # Tool-Compliance: wieviele Turns mit Pattern.tools auch tatsächlich
        # mind. eines der verlangten Tools aufgerufen haben.
        "tool_compliance_rate": (
            round(tool_compliance_ok / tool_compliance_total, 3)
            if tool_compliance_total else 0.0
        ),
        "tool_compliance_total": tool_compliance_total,
        "tool_compliance_per_pattern": tool_compliance_per_pattern,
        # Token-Cost / Cache-Hit (Bonus 1)
        "token_usage_aggregate": {
            "prompt_tokens": sum_prompt_tokens,
            "completion_tokens": sum_completion_tokens,
            "cached_tokens": sum_cached_tokens,
            "total_llm_calls": sum_total_calls,
            "turns_with_usage": turns_with_usage,
            "cache_hit_rate": (
                round(sum_cached_tokens / sum_prompt_tokens, 3)
                if sum_prompt_tokens else 0.0
            ),
            "avg_prompt_tokens_per_turn": (
                round(sum_prompt_tokens / turns_with_usage, 1)
                if turns_with_usage else 0.0
            ),
            "avg_completion_tokens_per_turn": (
                round(sum_completion_tokens / turns_with_usage, 1)
                if turns_with_usage else 0.0
            ),
            # A2.3 — pro Modell die Cache-Hit-Rate ergänzen, damit man sieht,
            # welcher Modell-Typ den OpenAI-Prompt-Cache wirklich nutzt
            # (gpt-4o-mini cached anders als gpt-5/5.4-mini).
            "per_model": {
                model_name: {
                    **stats,
                    "hit_rate": (
                        round(int(stats.get("cached") or 0)
                              / int(stats.get("prompt") or 1), 3)
                        if int(stats.get("prompt") or 0) else 0.0
                    ),
                }
                for model_name, stats in per_model_usage.items()
            },
            # A2.1 — pro Phase (classify / tool_loop / response /
            # quick_replies / reflection / canvas_*) die Aggregat-Numbers
            # plus Phase-spezifische Cache-Hit-Rate. Zeigt, wo der Cache
            # bricht (oft: response-Phase, weil Tool-Outputs den Prompt
            # variieren).
            "per_phase": _aggregate_per_phase(conversations),
        },
        # Tie-Breaker telemetry (Bonus 2)
        "tie_breaker": {
            "evaluated_turns": tie_breaker_evaluated,
            "applied_count": tie_breaker_applied,
            "applied_rate": (
                round(tie_breaker_applied / tie_breaker_evaluated, 3)
                if tie_breaker_evaluated else 0.0
            ),
            "overrides": tie_breaker_overrides,
        },
    }


def _compute_target_turns(
    mode: str, n_personas: int, n_intents: int,
    scenarios_per_combo: int, turns_per_conv: int,
) -> int:
    """Upfront estimate of how many judged turns the run will produce
    at maximum (actual can be lower if simulator ends early with [ENDE])."""
    combos = n_personas * n_intents
    scen_turns = combos * scenarios_per_combo if mode in ("scenarios", "both") else 0
    conv_turns = combos * turns_per_conv if mode in ("conversations", "both") else 0
    return scen_turns + conv_turns


async def _persist_progress(
    run_id: str, conversations: list[dict], target_turns: int,
    current_activity: str,
) -> None:
    """Save partial progress so the UI can display live status AND so
    a crash mid-run doesn't lose finished conversations."""
    summary = _aggregate(conversations)
    summary["target_turns"] = target_turns
    summary["current_activity"] = current_activity
    await _update_run(
        run_id,
        total_turns=summary["total_judged_turns"],
        avg_score=summary["avg_score"],
        summary_json=json.dumps(summary, ensure_ascii=False),
        conversations_json=json.dumps(conversations, ensure_ascii=False),
    )


async def execute_run(
    run_id: str, mode: str,
    personas: list[dict], intents: list[dict],
    scenarios_per_combo: int = 2,
    turns_per_conv: int = 3,
    config_slug: str = "",
) -> None:
    """Run the eval in the background. Writes progress to eval_runs row
    incrementally so the UI can show live progress and partial data survives
    a crash or restart."""
    await _create_run(
        run_id, mode,
        [p.get("id", "") for p in personas],
        [i.get("id", "") for i in intents],
        turns_per_conv, config_slug,
    )
    target_turns = _compute_target_turns(
        mode, len(personas), len(intents), scenarios_per_combo, turns_per_conv,
    )
    # Initialise summary so UI has target_turns available from the first poll
    await _update_run(
        run_id,
        summary_json=json.dumps({
            "target_turns": target_turns,
            "current_activity": "Starte …",
            "matrix": {}, "pattern_usage": {},
            "avg_score": 0.0, "total_judged_turns": 0,
        }, ensure_ascii=False),
    )

    conversations: list[dict] = []
    t0 = time.perf_counter()

    # A3.3 — Reset Tool-Cache + Stats vor jedem Run, damit die später
    # gespeicherten Cache-Stats nur DIESEN Run reflektieren (sonst
    # mischen sich Production- und Eval-Hits/Misses).
    try:
        from app.services.mcp_client import clear_tool_cache as _clear_tc
        _cleared = _clear_tc()
        if _cleared:
            logger.info("[eval %s] cleared tool cache (%d entries)", run_id, _cleared)
    except Exception as _ce:
        logger.warning("[eval %s] tool cache clear failed: %s", run_id, _ce)

    try:
        # ── Stage 1: scenarios (single-turn) ──
        if mode in ("scenarios", "both"):
            await _persist_progress(run_id, conversations, target_turns,
                                    "Generiere Szenarien (0/0) …")

            # Live progress callback — updates current_activity on each
            # (persona, intent) combo so the UI shows "Generiere Szenarien
            # 47/144 (P-X × INT-Y) …" instead of a stale "Generiere Szenarien".
            # Avoid a DB write on every single combo by throttling to every
            # 4th combo + always the last combo.
            async def _scenario_progress(
                idx: int, total: int, pid: str, iid: str,
            ) -> None:
                if idx == 1 or idx == total or idx % 4 == 0:
                    await _persist_progress(
                        run_id, conversations, target_turns,
                        f"Generiere Szenarien {idx}/{total} ({pid} × {iid}) …",
                    )

            scens = await generate_scenarios(
                personas, intents, scenarios_per_combo,
                progress_cb=_scenario_progress,
            )
            logger.info("[eval %s] generated %d scenarios", run_id, len(scens))
            for idx, sc in enumerate(scens):
                persona = next((p for p in personas if p["id"] == sc["persona_id"]), {})
                intent = next((i for i in intents if i["id"] == sc["intent_id"]), {})
                activity = (
                    f"Szenario {idx + 1}/{len(scens)}: "
                    f"{sc['persona_id']} × {sc['intent_id']}"
                )
                try:
                    # Welle E v4 (2026-05-25, eval-c4c0 Task #118/119):
                    # I06 ist Edit-Intent — semantisch nur sinnvoll wenn
                    # vorher Material erzeugt wurde. Im Eval-c4c0 waren alle
                    # 6 I06-Turns Eröffnungen ohne Vor-Inhalt → die Engine
                    # routete vernünftig zu I05/M03 (Slot-Klärung), aber der
                    # Judge erwartete M11 (Edit) → konsistent pm=0/1.
                    #
                    # Fix: bei I06 schicken wir vorab einen synthetischen
                    # I05/M10-Turn ("Erstelle mir ein Arbeitsblatt zur
                    # Photosynthese") an dieselbe Session, so dass
                    # ``session_state.entities._last_pattern == M10`` für
                    # den eigentlichen Edit-Turn vorliegt. Damit greift
                    # rule_iterative_edit (R2) und M11 wird gewählt.
                    # Bewertet wird NUR der Edit-Turn (Turn 2), nicht der
                    # Priming-Turn.
                    use_session_id: str | None = None
                    priming_meta: dict[str, Any] | None = None
                    if sc["intent_id"] == "I06":
                        use_session_id = f"eval-{uuid.uuid4().hex[:12]}"
                        priming_msg = (
                            "Erstelle mir bitte ein Arbeitsblatt zur "
                            "Photosynthese für Klasse 6."
                        )
                        try:
                            priming_resp = await _post_chat(
                                priming_msg, session_id=use_session_id,
                            )
                            priming_meta = {
                                "priming_message": priming_msg,
                                "priming_pattern": (priming_resp.get("debug") or {}).get("pattern"),
                                "priming_text_preview": (priming_resp.get("content") or "")[:200],
                            }
                            # eval-bd3a Befund (2026-05-26): bei P-ELT/P-LEH war
                            # ``_canvas_last_markdown`` beim Edit-Turn 2 noch
                            # nicht in der DB persistiert — M11 fand keinen
                            # Vor-Inhalt und antwortete mit "Ich habe gerade
                            # nichts zum Anpassen". Der Edit-Turn startet sonst
                            # direkt im Anschluss, ohne dass die Session-
                            # Persistierung der vorherigen Antwort durch ist.
                            # 600 ms Puffer löst das Race deterministisch
                            # (Priming-Turn schreibt entities + last_pattern in
                            # aiosqlite, das ist non-blocking gegenüber dem
                            # HTTP-Response).
                            await asyncio.sleep(0.6)
                            # Belastbarer: aktiv prüfen, dass die Session den
                            # erwarteten ``_canvas_last_markdown`` (oder
                            # ``_last_pattern == M10``) trägt; bei Bedarf
                            # einmal nachpollen.
                            try:
                                from app.services.database import get_or_create_session
                                _st = await get_or_create_session(use_session_id)
                                _ents = (_st.get("entities") or {}) if _st else {}
                                if not _ents.get("_canvas_last_markdown") and not _ents.get("_last_pattern"):
                                    await asyncio.sleep(0.4)
                            except Exception:
                                # Persist-Check ist Komfort, kein Hard-Stop
                                pass
                        except Exception as _pe:
                            logger.warning(
                                "[eval %s] I06 priming failed for %s: %s",
                                run_id, sc.get("persona_id"), _pe,
                            )
                            # Bei Fehler: ohne Priming weiterfahren, der Eval
                            # zeigt dann das ursprüngliche I06-Verhalten.
                            use_session_id = None

                    bot_resp = await _post_chat(sc["opening"], session_id=use_session_id)
                    bot_text = bot_resp.get("content", "")
                    debug = bot_resp.get("debug", {}) or {}
                    if priming_meta:
                        debug["i06_priming"] = priming_meta
                    dbg_flat = {
                        "pattern": debug.get("pattern"),
                        "persona": debug.get("persona"),
                        "intent": debug.get("intent"),
                        "safety": debug.get("safety"),
                        "tools_called": debug.get("tools_called", []),
                        # Phase-1-Pattern-Hint (für globale Aggregat-Metriken)
                        "pattern_id_hint": debug.get("pattern_id_hint"),
                        "pattern_reasoning": debug.get("pattern_reasoning"),
                        "llm_engine_match": debug.get("llm_engine_match"),
                        # Bonus 1: Cache-Hit-Rate aggregation reads from this
                        "token_usage": debug.get("token_usage"),
                        # Bonus 2: tie-breaker telemetry lives inside phase3_modulations
                        "phase3_modulations": debug.get("phase3_modulations"),
                        # Welle E v4: bei I06-Szenarien zeigen wir den
                        # Priming-Turn im Studio an, damit nachvollziehbar
                        # ist warum die Engine M11 (Edit) wählen konnte.
                        "i06_priming": debug.get("i06_priming"),
                    }
                    # Welle E v4+ (2026-05-25): KI-Material (M10/M11/M09) wird
                    # vom Backend in ``inline_documents[].content`` ausgeliefert
                    # — die ``content``-Bubble enthält nur die kurze
                    # Ankündigung ("Hier ist dein Material — sag Bescheid").
                    # Welle E v4+++ (2026-05-26, eval-bd3a): zusätzlich Material-
                    # Treffer-Cards + Query-Metas anhängen, damit der Judge
                    # auch M05/M06/M07/M08-Such-Patterns korrekt bewertet
                    # (vorher: "kein konkretes Material" obwohl Cards da waren).
                    _idocs = bot_resp.get("inline_documents") or []
                    if _idocs:
                        _md_parts: list[str] = []
                        for _doc in _idocs:
                            if not isinstance(_doc, dict):
                                continue
                            _content = (_doc.get("content") or "").strip()
                            if _content:
                                _title = (_doc.get("title") or _doc.get("kind") or "").strip()
                                _md_parts.append(
                                    f"---\n[Inline-Document — vom Nutzer sichtbar"
                                    + (f": {_title}" if _title else "") + "]\n\n"
                                    + _content
                                )
                        if _md_parts:
                            bot_text = (bot_text or "").rstrip() + "\n\n" + "\n\n".join(_md_parts)
                    # Such-/Material-Karten anhängen (M05, M06, M07, M08, M09)
                    _cards = bot_resp.get("cards") or []
                    if _cards:
                        _card_lines = []
                        for _card in _cards[:8]:  # cap to 8 für Token-Budget
                            if not isinstance(_card, dict):
                                continue
                            _ct = (_card.get("title") or "").strip()
                            _cu = (_card.get("url") or _card.get("wlo_url") or "").strip()
                            _cd = (_card.get("description") or _card.get("abstract") or "").strip()[:200]
                            if _ct or _cu:
                                _line = f"  - **{_ct or '(ohne Titel)'}**"
                                if _cu: _line += f" — {_cu}"
                                if _cd: _line += f"\n    {_cd}"
                                _card_lines.append(_line)
                        if _card_lines:
                            bot_text = (
                                (bot_text or "").rstrip()
                                + f"\n\n---\n[Material-Cards — vom Nutzer sichtbar, {len(_cards)} Treffer]\n"
                                + "\n".join(_card_lines)
                            )
                    # Such-Hinweis-Metas (Themenseiten / Sammlungen / Fachportale)
                    _qmetas = bot_resp.get("query_metas") or []
                    if _qmetas:
                        _qm_lines = []
                        for _qm in _qmetas[:5]:
                            if not isinstance(_qm, dict):
                                continue
                            _qt = (_qm.get("title") or _qm.get("type") or "").strip()
                            _qu = (_qm.get("url") or "").strip()
                            if _qt or _qu:
                                _qm_lines.append(f"  - {_qt}" + (f" — {_qu}" if _qu else ""))
                        if _qm_lines:
                            bot_text = (
                                (bot_text or "").rstrip()
                                + "\n\n---\n[Query-Metas — vom Nutzer sichtbar]\n"
                                + "\n".join(_qm_lines)
                            )
                    # Legacy: falls historische page_action.canvas_open noch
                    # auftaucht (Backend nicht migriert), Markdown ebenfalls
                    # anhängen.
                    page_action = bot_resp.get("page_action") or {}
                    if (page_action.get("action") == "canvas_open"
                            and isinstance(page_action.get("payload"), dict)
                            and page_action["payload"].get("markdown")):
                        canvas_md = page_action["payload"]["markdown"]
                        bot_text = (
                            f"{bot_text}\n\n"
                            f"---\n[Canvas-Inhalt — vom Nutzer sichtbar]\n\n"
                            f"{canvas_md}"
                        )
                    judge = await judge_turn(persona, intent, sc["opening"], bot_text, dbg_flat)
                except Exception as e:
                    logger.warning("[eval %s] scenario failed: %s", run_id, e)
                    bot_text, dbg_flat, judge = f"(error: {e})", {}, {"total": 0.0, "notes": str(e)[:200]}
                conversations.append({
                    "kind": "scenario",
                    "persona_id": sc["persona_id"],
                    "intent_id": sc["intent_id"],
                    "session_id": use_session_id,  # bei I06 gesetzt, sonst None
                    "turns": [{
                        "user": sc["opening"],
                        "bot": bot_text,
                        "debug": dbg_flat,
                        "judge": judge,
                    }],
                })
                # Persist immediately after the FIRST scenario (so the UI
                # leaves the "Generiere Szenarien …" state as soon as the
                # for-loop starts), then every 2 scenarios to keep DB
                # writes bounded.
                if (idx + 1) == 1 or (idx + 1) % 2 == 0 or (idx + 1) == len(scens):
                    await _persist_progress(run_id, conversations, target_turns, activity)

        # ── Stage 2: conversations (multi-turn) ──
        if mode in ("conversations", "both"):
            total_combos = len(personas) * len(intents)
            combo_idx = 0
            for persona in personas:
                for intent in intents:
                    combo_idx += 1
                    activity = (
                        f"Dialog {combo_idx}/{total_combos}: "
                        f"{persona['id']} × {intent['id']}"
                    )
                    await _persist_progress(run_id, conversations, target_turns, activity)
                    try:
                        conv = await simulate_conversation(persona, intent, max_turns=turns_per_conv)
                    except Exception as e:
                        logger.warning("[eval %s] conv failed %s/%s: %s",
                                       run_id, persona["id"], intent["id"], e)
                        continue
                    for turn in conv["turns"]:
                        if turn.get("error"):
                            turn["judge"] = {"total": 0.0, "notes": turn["error"]}
                            continue
                        turn["judge"] = await judge_turn(
                            persona, intent, turn["user"], turn["bot"], turn["debug"],
                        )
                    conversations.append({
                        "kind": "conversation",
                        "persona_id": persona["id"],
                        "intent_id": intent["id"],
                        "session_id": conv["session_id"],
                        "ended_early": conv["ended_early"],
                        "turns": conv["turns"],
                    })
                    # Persist after each multi-turn conversation — they're expensive
                    await _persist_progress(run_id, conversations, target_turns, activity)

        summary = _aggregate(conversations)
        summary["target_turns"] = target_turns
        summary["current_activity"] = "Fertig"
        # NEW (Phase 1): globale Klassifikations-Metriken — persona/intent
        # Soll-Ist-Genauigkeit, Pattern-Hint vs Engine, Confusion-Matrizen.
        summary["classification_metrics"] = _aggregate_classification_metrics(conversations)
        # A3.3 — Tool-Cache-Effektivität für diesen Run (hits/misses/size + per-tool TTL)
        try:
            from app.services.mcp_client import get_tool_cache_stats as _get_tc_stats
            summary["tool_cache"] = _get_tc_stats()
        except Exception as _se:
            logger.warning("[eval %s] tool_cache stats fetch failed: %s", run_id, _se)
        await _update_run(
            run_id,
            status="done",
            completed_at=datetime.now(timezone.utc).isoformat(),
            total_turns=summary["total_judged_turns"],
            avg_score=summary["avg_score"],
            summary_json=json.dumps(summary, ensure_ascii=False),
            conversations_json=json.dumps(conversations, ensure_ascii=False),
        )
        logger.info("[eval %s] done in %.1fs, avg=%.2f, %d/%d turns",
                    run_id, time.perf_counter() - t0,
                    summary["avg_score"], summary["total_judged_turns"], target_turns)
    except Exception as e:
        logger.exception("[eval %s] failed", run_id)
        # Preserve whatever conversations we collected so far
        try:
            summary = _aggregate(conversations)
            summary["target_turns"] = target_turns
            summary["current_activity"] = f"Fehler: {str(e)[:200]}"
            summary["classification_metrics"] = _aggregate_classification_metrics(conversations)
        except Exception:
            summary = {"target_turns": target_turns}
        await _update_run(
            run_id,
            status="failed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            error_message=str(e)[:500],
            summary_json=json.dumps(summary, ensure_ascii=False),
            conversations_json=json.dumps(conversations, ensure_ascii=False),
            total_turns=summary.get("total_judged_turns", 0),
        )


# ── Public helpers for the router ──────────────────────────────────

def list_personas_and_intents() -> dict[str, Any]:
    """Current config snapshot for the UI."""
    return {
        "personas": load_persona_definitions(),
        "intents": load_intents(),
    }


async def sweep_orphaned_runs() -> int:
    """Mark any rows still in ``status='running'`` as failed.

    Called once from the FastAPI lifespan handler. A ``running`` row at
    startup is by definition orphaned — its background task cannot have
    survived a process restart. Leaving it ``running`` would confuse the
    UI (spinner forever) and make the polling loop never stop.

    Returns the number of rows swept.
    """
    from datetime import datetime, timezone
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM eval_runs WHERE status = 'running'")
        rows = await cur.fetchall()
        if not rows:
            return 0
        await db.execute(
            """UPDATE eval_runs
               SET status = 'failed',
                   completed_at = ?,
                   error_message = 'Backend was restarted during execution'
               WHERE status = 'running'""",
            (datetime.now(timezone.utc).isoformat(),),
        )
        await db.commit()
    logger.warning(
        "Eval startup sweep: marked %d orphaned 'running' run(s) as 'failed'",
        len(rows),
    )
    return len(rows)
