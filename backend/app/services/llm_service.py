"""LLM service using OpenAI API for classification and response generation."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from pydantic import ValidationError

from app.models.schemas import ClassificationResult
from app.services.mcp_client import TOOL_DEFINITIONS, call_mcp_tool, parse_wlo_cards, resolve_discipline_labels
from app.services.pattern_engine import select_pattern
from app.services.config_loader import (
    load_persona_prompt, load_domain_rules, load_base_persona, load_guardrails,
    load_intents, load_states, load_entities, load_signal_modulations,
    load_device_config, load_persona_definitions, load_pattern_definitions,
)
from app.services.llm_provider import get_client, get_chat_model, build_chat_kwargs

import logging as _log
_logger = _log.getLogger(__name__)

client = get_client()
MODEL = get_chat_model()


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
            "P-W-LK", "P-W-SL", "P-W-POL", "P-W-PRESSE", "P-W-RED",
            "P-BER", "P-VER", "P-ELT", "P-AND",
        ]

    # Load intents
    intents = load_intents()
    intent_ids = [i["id"] for i in intents] or [
        "INT-W-01", "INT-W-02", "INT-W-03a", "INT-W-03b", "INT-W-03c",
        "INT-W-04", "INT-W-05", "INT-W-06", "INT-W-07", "INT-W-08",
        "INT-W-09", "INT-W-10",
    ]

    # Load states
    states = load_states()
    state_ids = [s["id"] for s in states] or [
        "state-1", "state-2", "state-3", "state-4", "state-5",
        "state-6", "state-7", "state-8", "state-9", "state-10", "state-11",
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
    pattern_ids = [p.get("id") for p in patterns if p.get("id")] or ["PAT-01"]

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
                },
                "required": ["persona_id", "persona_confidence", "intent_id",
                              "intent_confidence", "signals",
                              "entities", "turn_type", "next_state"],
            },
        },
    }


def _build_classify_system_prompt(
    session_state: dict,
    environment: dict,
    canvas_state: dict | None = None,
) -> str:
    """Build the classification system prompt from config files."""
    # Load config-driven element lists
    device_cfg = load_device_config()
    persona_formality = device_cfg.get("persona_formality", {})
    intents = load_intents()
    states = load_states()
    modulations, _ = load_signal_modulations()
    entities = load_entities()

    # Format persona list (with labels + descriptions + detection hints from persona files)
    persona_defs = load_persona_definitions()
    if persona_defs:
        persona_parts = []
        for p in persona_defs:
            desc = p.get("description", "")
            hints = p.get("hints", [])
            line = f"- {p['id']} ({p['label']})"
            if desc:
                line += f": {desc}"
            if hints:
                line += f"\n  Erkennungshinweise: {', '.join(hints[:20])}"
            persona_parts.append(line)
        persona_lines = "\n".join(persona_parts)
    elif persona_formality:
        persona_lines = "\n".join(f"- {pid}" for pid in persona_formality.keys())
    else:
        persona_lines = "- P-AND (Andere)"

    # Format intent list
    intent_lines = ", ".join(
        f"{i['id']} ({i['label']})" for i in intents
    ) if intents else ""

    # Format signal list by dimension
    signals_by_dim: dict[str, list[str]] = {}
    for sig_id, cfg in modulations.items():
        dim = cfg.get("dimension", "Unbekannt") if isinstance(cfg, dict) else "Unbekannt"
        signals_by_dim.setdefault(dim, []).append(sig_id)
    # Reload from YAML for dimension info
    from app.services.config_loader import _load_yaml
    sig_data = _load_yaml("04-signals/signal-modulations.yaml")
    sig_defs = sig_data.get("signals", {})
    signals_by_dim = {}
    for sig_id, cfg in sig_defs.items():
        dim = cfg.get("dimension", "Unbekannt")
        signals_by_dim.setdefault(dim, []).append(sig_id)
    signal_lines = "\n".join(
        f"{dim}: {', '.join(sigs)}" for dim, sigs in signals_by_dim.items()
    )

    # Format state list
    state_lines = ", ".join(
        f"{s['id']} ({s['label']})" for s in states
    ) if states else ""

    # Format pattern list — kompakt: ID + Label + Gates + 1-Liner-Hint.
    # Vollbeschreibungen würden den Prompt aufblähen; das LLM wählt den
    # Hint überwiegend nach Persona/Intent-Gates plus Patterntyp-Stimmung.
    # Bevorzuge `short_purpose` (1-2 Sätze WANN+WOFÜR) wenn im Pattern-File
    # gesetzt, sonst Fallback auf `core_rule`-Auszug.
    patterns_for_prompt = load_pattern_definitions()
    pattern_parts = []
    for p in patterns_for_prompt:
        pid = p.get("id")
        if not pid:
            continue
        label = p.get("label", "")
        gp = p.get("gate_personas", ["*"])
        gi = p.get("gate_intents", ["*"])
        gs = p.get("gate_states", ["*"])
        # Compact gate-summary: persona|intent|state separated by /
        def _g(lst):
            if not lst or "*" in lst:
                return "*"
            if len(lst) <= 4:
                return ",".join(lst)
            return f"{','.join(lst[:3])},+{len(lst)-3}"
        gates = f"{_g(gp)} / {_g(gi)} / {_g(gs)}"
        # Bevorzugt short_purpose, sonst core_rule-Auszug
        purpose = (p.get("short_purpose") or "").strip().replace("\n", " ")
        if not purpose:
            purpose = (p.get("core_rule") or "").strip().replace("\n", " ")
            if len(purpose) > 100:
                purpose = purpose[:97] + "…"
        line = f"- {pid} ({label}) [Gates {gates}]"
        if purpose:
            line += f": {purpose}"
        pattern_parts.append(line)
    pattern_lines = "\n".join(pattern_parts) if pattern_parts else (
        "(keine Patterns geladen — Hint-Feld leer lassen)"
    )

    # Format entity list with descriptions so the LLM distinguishes fach vs thema
    if entities:
        entity_lines = "\n".join(
            f"- {e['id']}: {e.get('description', e.get('label', ''))}"
            for e in entities
        )
    else:
        entity_lines = (
            "- fach: Schulfach oder Fachgebiet (z.B. Mathematik, Deutsch, Biologie)\n"
            "- stufe: Bildungsstufe aus dem WLO-Vokabular (Grundschule, Sekundarstufe I, "
            "Sekundarstufe II, Berufliche Bildung, Hochschule, Erwachsenenbildung). "
            "Nennt der Nutzer eine Klassenstufe, MAPPE sie: Klasse 1-4=Grundschule, "
            "Klasse 5-10=Sekundarstufe I, Klasse 11-13=Sekundarstufe II. "
            "Eine Filter-Ebene 'Klassenstufe' gibt es auf WLO nicht.\n"
            "- thema: Konkretes Thema oder Lerngegenstand (z.B. Bruchrechnung, Fotosynthese)\n"
            "- medientyp: Art des Materials (z.B. Video, Arbeitsblatt)\n"
            "- lizenz: Gewünschte Lizenz (z.B. CC BY, CC0)"
        )

    persona_prompt = ""
    if session_state.get("persona_id"):
        persona_prompt = f"\nAktuelle Persona: {session_state['persona_id']}"

    canvas_prompt = ""
    if canvas_state and canvas_state.get("mode") and canvas_state.get("mode") != "empty":
        c_title = (canvas_state.get("title") or "").strip()
        c_type = (canvas_state.get("material_type") or "").strip()
        c_mode = canvas_state.get("mode")
        c_md = (canvas_state.get("markdown") or "")[:800]
        c_cards = canvas_state.get("cards_count") or 0
        canvas_prompt = (
            f"\n\n## Canvas-Kontext (was der Nutzer gerade sieht)"
            f"\nModus: {c_mode}"
            + (f"\nTitel: {c_title}" if c_title else "")
            + (f"\nMaterial-Typ: {c_type}" if c_type else "")
            + (f"\nKachel-Anzahl: {c_cards}" if c_mode == "cards" else "")
            + (f"\nAuszug aus dem Canvas-Dokument:\n{c_md}" if c_md else "")
            + "\n\nKRITISCH — Intent-Auswahl bei aktivem Canvas:"
              "\n- Wenn die Nutzernachricht sich auf den Canvas-Inhalt bezieht"
              " (\"hier\", \"das\", \"der Text\", \"die Aufgabe\", \"der Titel\")"
              " ODER Edit-Verben nutzt (\"mach es\", \"kürzer\", \"ausführlicher\","
              " \"ändere\", \"ergänze\", \"entferne\", \"fasse präziser\",  \"einfacher\","
              " \"anpassen\", \"umformulieren\", \"schreib um\"):"
              " → intent_id = \"INT-W-12\" (Canvas-Edit), turn_type=\"follow_up\"."
              "\n- INT-W-11 (NEU erstellen) ist NUR richtig, wenn der Nutzer"
              " explizit ein NEUES Material zu einem ANDEREN Thema will"
              " (\"Mach mir stattdessen ein Quiz zu X\")."
              "\n- Zurückfragen oder Meta-Fragen zum Canvas-Inhalt (\"Was bedeutet"
              " hier X?\") sind turn_type=\"clarification\", Intent wie aus der"
              " Sachfrage ableitbar (meist INT-W-06 Faktenfragen)."
        )

    # Semantic page-context block (populated if the widget is embedded on a
    # theme page and page_context_service resolved its metadata).
    try:
        from app.services import page_context_service
        _page_meta = page_context_service.get_cached(session_state)
        _page_block = page_context_service.render_for_prompt(_page_meta)
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

    # A2.2 — Cache-Maximierung: dynamische Felder (state, entities, persona,
    # turn count, page, canvas, page_block) werden ans ENDE des System-Prompts
    # verschoben. So bleibt der lange statische Prefix (Personas-Liste,
    # Intent-Regeln, State-Beschreibungen, Tool-Schema) zwischen Turns
    # identisch → OpenAI Prompt-Cache greift auf 5000+ Tokens.
    #
    # Achtung: Inhalt unverändert. Nur Reihenfolge im Prompt geändert:
    # STATIC → DYNAMIC statt DYNAMIC → STATIC. Falls je ein Klassifikator-
    # Regression beobachtet wird, mit env CLASSIFY_PROMPT_LEGACY_ORDER=1
    # auf die alte Reihenfolge zurückrollen.
    _legacy_order = (os.getenv("CLASSIFY_PROMPT_LEGACY_ORDER") or "").strip() == "1"

    _dynamic_block = (
        f"\n## Aktueller Turn-Kontext\n"
        f"State: {session_state.get('state_id', 'state-1')}\n"
        f"Bekannte Entities: {json.dumps(session_state.get('entities', {}))}"
        f"{persona_prompt}\n"
        f"Turn: {session_state.get('turn_count', 0) + 1}\n"
        f"Seite: {environment.get('page', '/')}\n"
        f"Seitenkontext (Rohdaten): {json.dumps(_raw_pc)}\n"
        f"Device: {environment.get('device', 'desktop')}"
        f"{canvas_prompt}\n"
        f"{_page_block}"
    ).rstrip()

    _static_block = f"""
{persona_lines}

PERSONA-REGELN:
- Erkenne Personas SOWOHL durch EXPLIZITE Aussagen als auch durch IMPLIZITE Hinweise.
- EXPLIZIT: "Ich bin Lehrer/Politiker/Journalist/..." → direkte Zuordnung.
- IMPLIZIT: Nutze die Erkennungshinweise oben! Wenn der Nutzer Woerter/Phrasen verwendet
  die zu einer Persona passen, waehle diese Persona auch ohne explizite Selbstidentifikation.

  P-W-SL (Schueler:in/Lerner) — WICHTIGE Signale:
  - "fuer meine Pruefung", "fuer den Test", "fuer meinen Jahrgang", "fuer mich"
  - "fuer meine Klasse" (gemeint "die Klasse in die ICH gehe", nicht "die ich unterrichte")
  - "ich lerne", "ich verstehe nicht", "erklaer mir", "hab ich", "ich hab"
  - "Hausaufgaben", "Schulaufgabe", "Klausur"
  - Typisch: Du-Form, informeller Ton, kurze Saetze, "hey"/"hi"/"ne"/"ok"/"hab"
  - Altersgerechte Vagheit: "wie geht das?", "was ist X?"
  - Bei P-W-SL NIEMALS annehmen, dass eine ganze Klasse unterrichtet wird!

  P-W-LK (Lehrkraft) — SPEZIFISCHE Signale (nicht Default!):
  - "Unterricht planen", "Unterrichtseinheit", "Unterrichtsstunde", "Stundenentwurf"
  - "meine SchueleR:innen" (Plural, BESITZ-Relation), "meine Klasse unterrichten"
  - "Lehrplan", "Curriculum", "didaktisch", "Lernziele"
  - Typisch: Siezen, sachlich-professionell, Fachvokabular
  - "Arbeitsblatt" ALLEIN reicht NICHT — auch Eltern/Schueler suchen Arbeitsblaetter

  P-ELT (Eltern):
  - "mein Kind", "meine Tochter", "mein Sohn", "fuer meinen [Alter]-Jaehrigen"
  - "Nachhilfe", "Hausaufgaben meines Kindes"
  - Siezen, Sorge-Unterton

  P-W-RED (Redaktion/Autor:in):
  - "Ich bin Redakteur:in", "Artikel schreiben", "kuratieren"
  - "Inhalte einstellen", "Materialien hochladen"
  - "Quellen recherchieren"

  P-W-POL (Politik):
  - "Bildungspolitik", "Ministerium", "Gesetzgebung", "Positionspapier"
  - "aus Sicht der Politik", "fuer unsere Partei", "Multiplikator:in"

  P-W-PRESSE (Presse):
  - "Artikel schreiben", "Journalist", "Pressemitteilung", "zitierfähig"
  - "fuer meine Leser:innen", "Presseanfrage"

  P-BER (Berater:in):
  - "fuer unsere Schule evaluieren", "Vergleich verschiedener Angebote"
  - "Beratungsprozess", "Empfehlung"

  P-VER (Verwaltung):
  - "fuer unsere Verwaltung", "amtliche Daten", "in der Behoerdenarbeit"
  - "Kennzahlen fuer das Ministerium", "Bezirksauswertung"
  - WICHTIG: das blosse Wort "Statistiken"/"Zahlen"/"KPIs" macht NICHT
    automatisch P-VER — auch Lehrkraefte fragen nach Klassen-Statistiken,
    Eltern nach Hausaufgaben-Zahlen, Schueler:innen nach ihren Noten.
    P-VER ONLY wenn explizit Verwaltungs-/Behoerden-Kontext erkennbar ist.

- **KRITISCH — Intent != Persona**: Eine Frage nach **Statistiken**,
  **Reporting** oder **Zahlen** (Intent: INT-W-09) bedeutet NICHT
  automatisch P-VER. Persona kommt aus **Sprachstil + Selbst-ID +
  Kontext**, nicht aus dem Anfrage-Thema. Beispiele:
  - "Kannst du mir die Statistiken zu Hausaufgaben meiner Tochter zeigen"
    → P-ELT (mein/meine Tochter ist die Persona-Signal, NICHT "Statistiken")
  - "Statistiken zu meinen Pruefungen" → P-W-SL (mein/Pruefungen)
  - "Reichweitenstatistiken meiner Artikel" → P-W-RED (meine Artikel)
  - "Statistiken zur Bezirksauswertung" → P-VER (Bezirksauswertung)

- **KRITISCH — Bildungspolitik-THEMA != P-W-POL-PERSONA**: Das Wort
  "Bildungspolitik" alleine macht jemanden NICHT zu P-W-POL. Auch
  Lehrkraefte, Beratende, Verwaltung und Redaktion fragen nach
  bildungspolitischen Themen. P-W-POL nur waehlen wenn EXPLIZITE
  Selbst-ID ("ich bin Politikerin", "als Abgeordneter") ODER
  unmissverstaendliche Politik-Kontext-Woerter (Wahlkreis, Fraktion,
  Plenum, Anhoerung, Antrag, Positionspapier) auftauchen. Bei "Wie
  funktioniert WLO fuer Bildungspolitik" ist die Persona NICHT
  ableitbar — defaulte zu P-AND statt P-W-POL.

- **KRITISCH — "Statistik" ist eine Frage, kein Persona-Signal**:
  "Welche Statistiken zu X" / "Aktuelle Zahlen" / "Reichweite" sind
  Intent-W-09-Signale. Sie machen NIEMALS automatisch P-VER. Auch
  Lehrkraefte, Eltern, Schueler:innen und Pressevertreter:innen fragen
  nach Statistiken. Persona separat aus Sprache und Self-ID ableiten.

- **KRITISCH — P-W-LK ist KEIN Default!** Wenn keine eindeutigen Lehrkraft-Signale
  vorliegen (siehe Liste oben), waehle P-AND statt P-W-LK. Besser unklar als falsch
  zugewiesen. Viele "Lehrer-klingende" Nachrichten ("fuer die Klasse", "Lernpfad",
  "Material zu X") kommen auch von Eltern, SchuelerInnen oder Beratenden.

- **Szenario-Hinweis**: Nach "Ich bin Journalist und..." → IMMER P-W-PRESSE
  (auch wenn der Rest nach Redaktion klingt). Explicit self-id trumps topic.

- Bei expliziter Selbstidentifikation: turn_type = "correction" setzen.
- Wenn die aktuelle Persona P-AND ist und der Nutzer klare spezifische Signale
  sendet → umklassifizieren. Aber im Zweifel P-AND bleiben.
- WICHTIG: "Lernpfad erstellen" ALLEIN macht noch keine Lehrkraft — auch Eltern,
  SchuelerInnen und Beratende koennen Lernpfade wollen. Nur mit zusaetzlichem
  Lehrkraft-Signal ("meine SchuelerInnen", "Unterricht planen") wird es P-W-LK.

## Intents
{intent_lines}

INTENT-REGELN:
- "Ich will mich erst mal umschauen", "ich schau erst mal", "was gibt es hier",
  "was kannst du", "ich orientiere mich", "erstmal schauen" → INT-W-02 (Soft Probing)
  Signal: orientierungssuchend. State: state-1.
- "Was ist WLO", "Was ist WirLernenOnline" → INT-W-01 (WLO kennenlernen)
- Wenn der Nutzer auf die Begruessung mit Orientierungswunsch antwortet → INT-W-02.

- INT-W-05 (Routing Redaktion) — Nutzer:in meldet einen Fehler, Inhaltsluecke,
  Wunsch oder bittet um Weiterleitung an das Redaktionsteam.
  TYPISCHE TRIGGER:
  - "an die Redaktion weiterleiten", "an Redaktion schicken", "an die Redaktion melden"
  - "Ich habe einen Fehler gefunden" (in Materialien / Texten / Übungen)
  - "Hier ist was falsch", "Da stimmt etwas nicht", "Ungereimtheiten entdeckt"
  - "Es fehlen Materialien zu X", "Koennt ihr das ergaenzen?"
  - "Wo kann ich einen Inhaltswunsch einreichen?"
  - "Wie kann ich eigene Materialien hochladen?" (Redakteur:in-Upload-Flow)
  TYPISCHE BEISPIELE:
  - "Ich habe einen Fehler in dem Artikel über nachhaltige Energie gefunden,
     könnten Sie das bitte an die Redaktion weiterleiten?" → INT-W-05
  - "Hey, ich habe hier ein paar Fehler in den Übungen gefunden, könntet ihr
     das mal checken?" → INT-W-05 (nicht INT-W-04 Feedback, nicht INT-W-11!)
  - "Kann ich einen Hinweis an die Redaktion schicken, weil ich einen Fehler
     in den Matheaufgaben gefunden habe?" → INT-W-05
  - "Wie kann ich meine eigenen Unterrichtsmaterialien hochladen?" → INT-W-05

  ABGRENZUNG INT-W-05 vs. INT-W-04 (Feedback):
  - INT-W-04 = allgemeine Meinung/Einschätzung zum Chatbot/Ergebnis, kein
    Weiterleitungs-Wunsch: "Das war hilfreich", "Die Ergebnisse sind nicht gut"
  - INT-W-05 = konkrete Meldung/Wunsch MIT impliziertem Weiterleitungs-Wunsch
    an die Redaktion: "Fehler gefunden + weiterleiten", "Inhalt fehlt"

- INT-W-11 (Inhalt erstellen) — Nutzer:in will ein NEUES Material KI-generieren lassen.

  ⚠️ ACHTUNG: INT-W-11 ist SELTENER als auf den ersten Blick. Der häufigste
  Classifier-Fehler ist: jeder Satz mit "Arbeitsblatt", "Quiz", "Pressemitteilung"
  etc. wird zu INT-W-11 gestempelt. Das ist FALSCH. Nur mit echtem
  CREATE-VERB am Satz-Anfang ist es INT-W-11. Bei folgenden Signalen
  ist ein anderer Intent richtig:

    * "runterladen", "herunterladen", "zur Verfügung stellen",
      "bereitstellen", "liefern", "geben", "bekommen" → INT-W-07 (Download)
    * "bewerten", "überprüfen", "prüfen", "wie gut ist", "ist X geeignet"
      → INT-W-08 (Inhalte evaluieren)
    * "Statistiken", "Zahlen", "Übersicht zu ... Daten", "wie viele",
      "aktuelle Nutzungsdaten", "Reporting" → INT-W-09 (Analyse & Reporting)
    * "kürzer", "ausführlicher", "mach es einfacher", "ergänze",
      "ändere den Titel", "umformulieren" (wenn Canvas aktiv) → INT-W-12 (Canvas-Edit)
    * "Fehler gefunden", "falsch", "weiterleiten an Redaktion" → INT-W-04/05
    * "Was ist X", "Wer ist", "Was macht" (Fakten/Info) → INT-W-06 (Faktenfragen)

  TRIGGER-VERBEN für INT-W-11: "erstelle", "erstell mir", "generiere", "mach mir ein(e)",
  "schreib ein(e)", "bau mir", "entwirf", "fasse zusammen als", "produziere".
  Typische Beispiele:
  - "Erstelle ein Arbeitsblatt zu ..."
  - "Mach mir ein Quiz zu ..."
  - "Generiere ein Infoblatt ueber ..."
  - "Schreib eine Lerngeschichte zum Thema ..."
  - "Bau mir ein Rollenspiel zu ..."
  next_state: state-12 (Canvas-Arbeit).
  Zusaetzliches Entity: wenn Material-Typ erkennbar (Arbeitsblatt/Quiz/Glossar/etc.),
  speichere ihn unter entities.material_typ.

- ABGRENZUNG INT-W-11 vs. INT-W-10 (Unterrichtsplanung):
  - INT-W-10 = Lehrkraft plant eine komplette Unterrichtseinheit / Stunde / Lernpfad,
    erwartet STRUKTURIERTE MATERIALZUSAMMENSTELLUNG aus bestehenden Quellen.
    Trigger: "Lernpfad", "Stundenentwurf", "Unterrichtsplanung", "Unterrichtseinheit",
    "Unterrichtsstunde", "plane eine Stunde".
    **AUCH INT-W-10**: "Materialzusammenstellung", "Material zusammenstellen",
    "strukturierte Sammlung", "Sammlung zusammenstellen", "Materialpaket",
    "Übersicht von/aus Materialien", "mehrere Materialien zu ..." —
    der Plural + "Zusammenstellung/Sammlung" signalisiert kuratierte Mehrfach-
    Quellen, NICHT ein einzelnes neues Dokument.
  - INT-W-11 = einzelnes, neu generiertes Material wird gewuenscht.
    Trigger: siehe oben (Verb + konkreter Material-Typ, SINGULAR).
  - Faustregel: "Lernpfad"/"Stunde"/"Einheit"/"Zusammenstellung"/"Sammlung" → INT-W-10;
    konkreter SINGULÄRER Typ wie "Arbeitsblatt"/"Quiz"/"Glossar" ohne Stunden- oder
    Zusammenstellungs-Kontext → INT-W-11.
  - Beispiel: "Erstelle eine Materialzusammenstellung zu X" → INT-W-10 (mehrere
    Materialien aus dem Bestand). "Erstelle ein Arbeitsblatt zu X" → INT-W-11
    (ein neues Dokument).

- ABGRENZUNG INT-W-11 vs. INT-W-03b (Unterrichtsmaterial suchen):
  - INT-W-03b = Nutzer:in SUCHT bestehende Materialien im WLO-Bestand.
    Trigger: "Zeig mir", "Suche", "Finde", "Gibt es", "Hast du", "Welche ... gibt es".
  - INT-W-11 = Nutzer:in will ein NEUES Material ERSTELLEN lassen.
    Trigger: siehe oben (aktive Verben).
  - Faustregel: "Zeig mir Arbeitsblaetter zu X" → INT-W-03b;
    "Erstelle ein Arbeitsblatt zu X" → INT-W-11.

- KRITISCHE NEGATIV-ABGRENZUNG für INT-W-11 (setze NICHT INT-W-11 wenn):
  Auch wenn ein Material-Typ-Wort ("Arbeitsblatt", "Quiz", "Übung", "Material",
  "Lernpfad", "Übersicht", "Pressemitteilung", "Vergleich") im Text auftaucht,
  ist INT-W-11 oft FALSCH. Prüfe zuerst diese Ausschlüsse:

  * Wenn Downloaden / Herunterladen / Bereitstellen:
    "Kann ich X runterladen?", "Stellen Sie mir X zum Download bereit",
    "Wo finde ich X zum Download?", "Können Sie mir X liefern?"
    → INT-W-07 (Material herunterladen), NICHT INT-W-11.

  * Wenn Bewertung / Qualitätsprüfung / Review:
    "Wie gut ist dieses X?", "Kannst du die Qualität von X bewerten?",
    "Überprüfe mal bitte X", "Ist X geeignet für Y?"
    → INT-W-08 (Inhalte evaluieren), NICHT INT-W-11.

  * Wenn Statistik / Daten / Zahlen / Reporting:
    "Wie viele X gibt es?", "Statistiken zu X", "Übersicht über Nutzung",
    "Leistungsdaten", "Wochendaten", "aktuelle Zahlen"
    → INT-W-09 (Analyse & Reporting), NICHT INT-W-11.
    Auch wenn Wort "Übersicht" vorkommt — "Übersicht über aktuelle Zahlen"
    ist KEIN Canvas-Create-Request für eine Strukturübersicht-Material!

  * Wenn Canvas-Edit (User arbeitet bereits mit einem Canvas-Inhalt):
    "Mach X kürzer", "fasse X präziser", "ergänze X um Y",
    "Kannst du X ausführlicher gestalten?", "Ändere den Titel im Canvas"
    → INT-W-12 (Canvas-Edit), NICHT INT-W-11.
    Siehe Canvas-Kontext oben — wenn Canvas aktiv ist und der User
    Änderungs-Verben nutzt: IMMER INT-W-12.

  * Wenn Feedback / Fehlermeldung / Routing:
    "Ich hab einen Fehler gefunden", "Könnten Sie das an Redaktion
    weiterleiten", "Hier ist was falsch", "Meine Frage zum Test von gestern"
    → INT-W-04 (Feedback) oder INT-W-05 (Routing Redaktion), NICHT INT-W-11.

  FAUSTREGEL: INT-W-11 nur wenn ein klares CREATE-Verb ("erstelle", "mach mir",
  "generiere", "bau mir", "schreib mir", "entwirf", "produziere") mit einem
  konkreten Thema (NICHT Substring, siehe Thema-Regeln) vorliegt.
  Wenn der Satz auf Frage-/Review-/Meta-Verb endet ("bewerten", "überprüfen",
  "runterladen", "bereitstellen", "liefern", "bekommen", "zur Verfügung"):
  NICHT INT-W-11.

- SAMMLUNGEN vs. THEMENSEITEN vs. EINZELINHALTE — richtiges INT-W-03?:
  - Wenn der User explizit "Sammlung(en)", "Kollektion" oder "Themenseite(n)",
    "Fachportal", "Portal" erwaehnt → INT-W-03a (Themenseite/Sammlung
    entdecken), NICHT INT-W-03b.
  - Wenn der User einen Material-Typ erwaehnt ("Arbeitsblatt", "Video",
    "Quiz", "Uebung", "Unterrichtsbaustein") → INT-W-03b (Material suchen).
  - Wenn der User offen formuliert ("zeig mir was zu X", "etwas ueber X",
    "Material zu X" ohne spezifischen Typ) und Schueler:in/Eltern
    ist → INT-W-03c (Lerninhalt suchen).
  - Wenn offen formuliert und Lehrkraft ist → INT-W-03a, weil Lehrkraefte
    zuerst von kuratierten Sammlungen/Themenseiten profitieren.
  - Faustregel: "Zeig mir Sammlungen zu Optik" → INT-W-03a mit thema=Optik.

## Signale
{signal_lines}

## States
{state_lines}

## Entities
{entity_lines}

ENTITY-REGELN:
- fach und thema sind VERSCHIEDENE Slots! Ein Fach (Mathematik, Deutsch, Biologie) ist KEIN Thema.
- thema ist ein konkreter Lerngegenstand INNERHALB eines Fachs (z.B. Bruchrechnung, Fotosynthese, Lyrik der Romantik).
- "Mathe", "Biologie", "Geschichte" → fach setzen, thema LEER lassen.
- "Bruchrechnung", "Dreisatz", "Zellteilung" → thema setzen (und ggf. fach ableiten).
- "Mathe Bruchrechnung" → fach="Mathematik", thema="Bruchrechnung".

KRITISCHE REGEL FÜR `thema` (Lerninhalt):
Niemals einen Substring der Nachricht als thema verwenden, nur weil dort ein
Material-Typ auftaucht. `thema` ist ein eigenständiger Lerngegenstand, NICHT
ein Satzfragment. Wenn kein klarer Lerngegenstand erkennbar ist, LASSE `thema`
komplett LEER. Dann fragt das System degradierend nach.

POSITIV (thema korrekt füllen):
- "Erstelle ein Arbeitsblatt zur **Photosynthese**" → thema="Photosynthese"
- "Quiz zu **Bruchrechnung** für Klasse 6" → thema="Bruchrechnung"
- "Material zum **Klimawandel**" → thema="Klimawandel"
- "Lerngeschichte über die **Römer**" → thema="die Römer"

NEGATIV (thema MUSS leer bleiben — sonst landet Müll im Canvas-Titel):
- "Kannst du mir das Arbeitsblatt runterladen?" → thema="" (kein Lerninhalt genannt!)
- "Ich brauche Ideen für ein neues Arbeitsblatt" → thema="" (nur Absicht, kein Thema)
- "Hey, ich hab ne Frage zu den Übungen für mein Kind" → thema="" (vages Feedback)
- "Gibt's ne Übersicht zu den aktuellen Statistiken?" → thema="" (Meta-Frage)
- "Hilf mir die Qualität des Arbeitsblatts zu bewerten" → thema="" (Review, kein Lerninhalt)
- "Erstelle mir ein neues Material" → thema="" (kein Thema genannt → degradieren)
- "Mach mir ein Quiz" (ohne Thema) → thema="" (Material-Typ klar, Thema fehlt)
- "Ich brauche Hilfe bei Mathe" → fach="Mathematik", thema="" (nur Fach!)
- "Ich lerne Biologie" → fach="Biologie", thema="" (kein Thema darin)
- "Kannst du mir bei Deutsch helfen?" → fach="Deutsch", thema="" (Fach, kein Thema)
- "Ich suche Materialien" → thema="" (keine Lerngegenstand-Nennung)
- "Ich will Infos" → thema="" (kein Inhalt, kein Fach)

WICHTIG — Unterschied Fach vs. Thema nochmal explizit:
  Schulfächer (Mathe/Mathematik, Deutsch, Biologie, Chemie, Physik, Englisch,
  Geschichte, Erdkunde, Geographie, Sport, Kunst, Musik, Informatik, Religion,
  Ethik, Politik, Wirtschaft, Sozialkunde) → IMMER fach, NIE thema.
  Nur eigenständige Lerngegenstände wie "Bruchrechnung", "Photosynthese",
  "Mittelalter", "Satz des Pythagoras", "Gedichtanalyse" sind thema.

FAUSTREGEL: Wenn du die Frage "Worum geht das thematisch?" nicht mit einem
EIGENSTÄNDIGEN Lerngegenstand beantworten kannst (der ohne Umgebungstext für
sich steht und ein Inhaltsthema bezeichnet), lasse `thema` LEER. Ein Thema
wird durch Substantive wie "Photosynthese", "Mittelalter", "Bruchrechnung"
markiert — nicht durch Füllwörter, Verben oder Pronomen wie "das", "diese(s)",
"Ideen für ...", "eine Frage zu ...".

## Patterns (Hinweis-Feld, optional)

Schau dir nach Persona/Intent-Bestimmung NOCHMAL die Anfrage an und wähle
zusätzlich das Pattern, das für dich holistisch am besten passt. Das ist
ein optionales Hinweis-Feld (Telemetrie/Mess-Modus) — die deterministische
Pattern-Engine entscheidet weiterhin authoritativ. Wir loggen nur, wie oft
deine Wahl mit der Engine-Wahl übereinstimmt.

Wann hilft dein Hint? Bei Tight-Races, wenn Engine-Score zwei Patterns
fast gleich rankt (z.B. PAT-08 vs PAT-01, PAT-13 vs PAT-14). Du siehst
die volle Anfrage holistisch — die Engine sieht nur abgeleitete Signale.

{pattern_lines}

Wähl ein Pattern dessen Gates passen (`gate_personas`/`gate_intents`/
`gate_states`-Liste oder `*` für Wildcard). Wenn du unsicher bist, lass
das Feld leer.

Begründe dein Pattern-Hint kurz im `pattern_reasoning`-Feld (1-2 Sätze):
warum dieses Pattern, welche 1 Alternative kam noch in Frage und warum
verworfen.

Rufe classify_input auf mit den erkannten Werten."""

    if _legacy_order:
        # Original layout (DYNAMIC at the very top, before personas) — kept
        # behind an env flag so we can rollback instantly if the new order
        # ever degrades classifier accuracy.
        return f"""Du bist der Klassifikations-Modul des WLO-Chatbots.
Analysiere die Nutzernachricht und klassifiziere sie in die 7 Input-Dimensionen.

Aktueller State: {session_state.get('state_id', 'state-1')}
Bekannte Entities: {json.dumps(session_state.get('entities', {}))}{persona_prompt}
Turn: {session_state.get('turn_count', 0) + 1}
Seite: {environment.get('page', '/')}
Seitenkontext (Rohdaten): {json.dumps(_raw_pc)}
Device: {environment.get('device', 'desktop')}{canvas_prompt}
{_page_block}

## Personas (WICHTIG: Genau zuordnen!){_static_block}"""

    # New cache-friendly order: long static prefix first, dynamic context last.
    # Same content; only the placement of the dynamic block moves to the end
    # so the OpenAI prompt cache can match the unchanging prefix between turns.
    return (
        "Du bist der Klassifikations-Modul des WLO-Chatbots.\n"
        "Analysiere die Nutzernachricht und klassifiziere sie in die 7 Input-Dimensionen.\n\n"
        "## Personas (WICHTIG: Genau zuordnen!)"
        + _static_block
        + _dynamic_block
    )


def _formality_guidance(formality: str, persona_id: str) -> str:
    """Concrete, persona-aware writing guidance for the LLM.

    The LLM historically treats ``Formality: Sie`` as a soft hint and slips
    into casual "hey, schön dass du da bist" even for journalists and civil
    servants. This helper expands the terse token into explicit examples
    and NEVER-lists, which the LLM follows much more reliably.
    """
    f = (formality or "").strip().lower()
    # Formal personas: strict Sie + professional register
    if f in ("sie", "formal", "foermlich"):
        # Extra strictness for personas whose scores were worst in the eval
        strict = persona_id in (
            "P-W-POL", "P-W-PRESSE", "P-VER",  # Politik, Presse, Verwaltung
            "P-BER", "P-W-LK",                   # Berater, Lehrkraft
        )
        base = (
            "Schreibe ausschließlich in der Sie-Form (\"Ich kann Ihnen …\", "
            "\"Haben Sie …\", \"Möchten Sie …\"). KEINE Du-Formen."
        )
        if strict:
            return (
                f"{base}\n"
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
            )
        return base
    # Informal personas: du but still respectful
    if f in ("du", "informal", "duzen"):
        # P-W-SL wants explicitly jugendlich-friendly tone; eval showed it was
        # getting over-formal responses.
        if persona_id == "P-W-SL":
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
            try:
                on_token(delta.content)
            except Exception:
                pass
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
    # The LLM-classifier systematically over-selects INT-W-11 when a
    # material-type word like "Arbeitsblatt" or "Pressemitteilung"
    # appears in the message, even when the actual intent is clearly
    # routing, download or evaluation. These regex-based overrides
    # catch the unambiguous cases and force the correct intent.

    # ── Persona + Intent overrides — MIGRATED to YAML rule engine ──
    # All deterministic post-classifier overrides now live in
    # ``chatbots/wlo/v1/06-rules/routing-rules.yaml`` and apply via the
    # pre-route engine pass in chat.py:
    #
    #   * R-PSI-1..R-PSI-8 — persona self-id ("ich bin Lehrer", "als
    #     Redakteur", "für unsere Verwaltung", …)
    #   * R-6b — persona_confidence < 0.40 → P-AND fallback
    #   * R-3                — INT-W-11 + Materialzusammenstellung → INT-W-10
    #   * rule_intent_w11_to_w05 — INT-W-11 + Redaktion-Trigger → INT-W-05
    #   * rule_intent_w11_to_w07 — INT-W-11 + Download-Trigger    → INT-W-07
    #   * rule_intent_w11_to_w08 — INT-W-11 + Eval-Trigger        → INT-W-08
    #   * rule_intent_w11_to_w09 — INT-W-11 + Statistik-Trigger   → INT-W-09
    #   * rule_intent_w11_to_w06 — INT-W-11 + Faktenfrage-Trigger → INT-W-06
    #   * rule_intent_w11_to_w02 — INT-W-11 + Orientierungs-Trigger → INT-W-02
    #
    # The chat router applies the resulting ``intent_override`` /
    # ``persona_override`` values via the pre-route hook before pattern
    # selection. To debug a specific override, see the Studio Routing
    # Rules tab → Test-Bench (no LLM call needed).
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

    # Build system prompt following 5-Layer LPA architecture
    system_parts = [
        # Layer 1: Identity (base persona from config)
        base_persona,
        # Layer 2: Domain rules
        domain_rules,
        # Layer 3: Persona-specific prompt
        persona_prompt,
        # Layer 4: Active pattern + intent
        f"""## Aktives Pattern: {pattern_label}
Kernregel: {pattern_output.get('core_rule', '')}
Response-Typ: {pattern_output.get('response_type', 'answer')}
Ton: {pattern_output.get('tone', 'sachlich')}

### Anrede-Form (STRIKT einhalten — Persona-abhängig)
Formality: {pattern_output.get('formality', 'neutral')}
{_formality_guidance(pattern_output.get('formality', 'neutral'), persona_id)}
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
        # Layer 5: Conversation context
        f"""## Kontext
Seite: {environment.get('page', '/')}
Entities: {json.dumps({k: v for k, v in (classification.get('entities') or {}).items() if not k.startswith('_')})}
Signale: {', '.join(classification.get('signals', []))}
State: {classification.get('next_state', 'state-1')}""",
    ]

    # Semantic page-context block (resolved theme-page metadata). Cached on
    # session_state["entities"]["_page_metadata"] by page_context_service at
    # request entry time. Goes after the generic context so the LLM treats
    # it as prime information.
    try:
        from app.services import page_context_service
        _pm = page_context_service.get_cached(session_state)
        _pb = page_context_service.render_for_prompt(_pm)
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

    # Card-text-mode: how to handle overlap between text and material cards
    _card_mode = pattern_output.get("card_text_mode", "minimal")
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
            # Pattern like PAT-20 Orientierungs-Guide: pure text, no tool calls
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
        # Pattern explicitly set tools=[] → NO tools (e.g. PAT-20 Orientierungs-Guide)
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
        active_tools = [
            t for t in active_tools
            if t["function"]["name"] != "search_wlo_collections"
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

    # ── Add RAG knowledge areas as virtual tools ──────────────────
    if available_rag_areas and rag_config:
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
                    "Vorschlag, in Persona-passender Anrede, vom Nutzer formuliert "
                    "z.B. 'Mehr davon zeigen', 'Anderes Thema wählen'). "
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
                            "description": "Die Markdown-formatierte Antwort an den Nutzer.",
                        },
                        "quick_replies": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "2-4 kurze Folgevorschläge. Jeder Vorschlag ist ein "
                                "Satz, den der Nutzer als nächste Eingabe sagen würde "
                                "(NICHT was der Bot vorschlägt zu tun). EIN Eintrag "
                                "darf optional ein Bring-mich-hin-Spezialformat sein: "
                                "``__guide__|<Label>|<URL>`` — siehe Tool-Description."
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
    if available_rag_areas and rag_config:
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
            "content": _txt[:4000],
        })
        mcp_prefetched = True

    # Tool calling loop
    all_cards: list[dict] = list(mcp_prefetch_cards)
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

                # ── Combined-output: model emitted FINAL answer + quick_replies ─
                # See env CHAT_INLINE_QUICK_REPLIES + the respond_to_user tool
                # definition above. Treat this as the equivalent of a
                # finish_reason == "stop" with the extracted text.
                if tool_name == "respond_to_user":
                    _inline_response_text = (tool_args.get("text") or "").strip()
                    qr = tool_args.get("quick_replies") or []
                    _inline_quick_replies = [
                        str(r).strip() for r in qr if isinstance(r, str) and str(r).strip()
                    ][:4]
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
                # Deduplicate by node_id
                existing_ids = {c.get("node_id") for c in all_cards if c.get("node_id")}
                for c in cards:
                    if c.get("node_id") not in existing_ids:
                        all_cards.append(c)
                        existing_ids.add(c.get("node_id"))

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text[:4000],
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
            response_text = choice.message.content or ""

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
            text = (summary_resp.choices[0].message.content or "").strip()
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
    # Canvas-Edit (wenn state-12)
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
    state_id = classification.get("next_state", session_state.get("state_id", "state-1"))
    entities = classification.get("entities", {}) or {}
    # Drop internal keys (prefix _) — they would confuse the LLM.
    public_entities = {k: v for k, v in entities.items() if not str(k).startswith("_")}

    in_canvas = state_id == "state-12"
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
        "P-W-LK", "P-ELT", "P-VER", "P-W-POL", "P-BER", "P-W-PRESSE", "P-W-RED",
    } else "du"

    system = f"""Du generierst genau 4 kurze Antwortvorschlaege fuer einen Chatbot-Nutzer.
Der Nutzer interagiert gerade mit BOERDi, dem Chatbot der Bildungsplattform
WirLernenOnline (WLO).

## Kontext
- Persona: {persona_id} (Anrede: {persona_salute})
- Intent: {intent_id}
- State: {state_id}{" (Canvas-Arbeit aktiv)" if in_canvas else ""}
- Erkannte Entities: {json.dumps(public_entities, ensure_ascii=False)}{_page_line}

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
   ausfuehrlicher, Loesungen ergaenzen, formeller, etc.) — NUR wenn State=state-12.

## Realistische Vorschlag-Beispiele fuer diese Persona
(Inspiration — nicht woertlich uebernehmen, auf den konkreten Kontext anpassen.)
{chr(10).join(f"- {h}" for h in filled_hints)}

## Perspektive
Die 4 Vorschlaege sind saetze, die der NUTZER dem Bot sagt — NICHT der Bot zum Nutzer.
FALSCH: "Weitere Materialien zeigen", "Suche eingrenzen"
RICHTIG: "Zeig mir mehr davon", "Ich will das eingrenzen"

## Struktur (4 verschiedene Typen — KEIN Duplikat)
Waehle 4 aus den folgenden Kategorien (mindestens 3 unterschiedliche Kategorien):
  (a) **Vertiefung** — mehr zum aktuellen Thema/Treffer
      z.B. "Hast du auch Videos dazu?", "Gibt es das fuer Klasse 8?"
  (b) **Canvas-Ausgabe** — neues Material erstellen lassen (zieht den aktuellen
      Kontext als Thema heran)
      z.B. "Mach mir ein Quiz daraus", "Erstell mir einen Lernpfad"
  (c) **Canvas-Edit** — NUR wenn state-12 aktiv: bestehenden Inhalt aendern
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
4. Wenn Canvas aktiv (state-12) ist: mindestens EIN Edit-Vorschlag (Kategorie c).
5. Wenn Themenseite bekannt: mindestens EIN Vorschlag der den Seiten-Kontext nutzt.
6. Wenn Persona analytisch ist (P-VER/P-W-POL/P-W-PRESSE/P-BER/P-W-RED):
   bevorzuge Bericht/Factsheet/Steckbrief/Pressemitteilung/Vergleich und
   Plattform-/Projekt-/Statistik-Fragen. Weniger klassische Lehrmaterialien.
7. Wenn Persona didaktisch (P-W-LK/P-W-SL/P-ELT/P-AND): klassische Lehrmaterialien
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
        text = resp.choices[0].message.content or ""
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
    # ohne dieses Hinzunehmen liefert PAT-19 leere Schritt 1/2/3-Templates.
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
Kontext: {learner_ctx}{default_hint}"""

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
        return resp.choices[0].message.content or "Lernpfad konnte nicht erstellt werden."
    except Exception as e:
        return f"Fehler beim Erstellen des Lernpfads: {e}"
