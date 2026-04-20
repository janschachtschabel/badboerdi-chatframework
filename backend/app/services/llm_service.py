"""LLM service using OpenAI API for classification and response generation."""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import ValidationError

from app.models.schemas import ClassificationResult
from app.services.mcp_client import TOOL_DEFINITIONS, call_mcp_tool, parse_wlo_cards, resolve_discipline_labels
from app.services.pattern_engine import select_pattern
from app.services.config_loader import (
    load_persona_prompt, load_domain_rules, load_base_persona, load_guardrails,
    load_intents, load_states, load_entities, load_signal_modulations,
    load_device_config, load_persona_definitions,
)
from app.services.llm_provider import get_client, get_chat_model, build_chat_kwargs

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
                },
                "required": ["persona_id", "intent_id", "intent_confidence", "signals",
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
            + "\n\nWICHTIG: Wenn die Nutzernachricht sich auf etwas im Canvas bezieht "
              "(\"hier\", \"das\", \"die Aufgabe\", \"der Text\", \"mach es ...\"), "
              "ist turn_type = \"follow_up\" oder \"clarification\" und Intent richtet "
              "sich nach dem Canvas-Inhalt (INT-W-11 bei Material-Edits; INT-W-10 bei "
              "Lernpfad-Edits; sonst wie aus der Nachricht ableitbar)."
        )

    # Semantic page-context block (populated if the widget is embedded on a
    # theme page and page_context_service resolved its metadata).
    try:
        from app.services import page_context_service
        _page_meta = page_context_service.get_cached(session_state)
        _page_block = page_context_service.render_for_prompt(_page_meta)
    except Exception:
        _page_block = ""

    # Also keep the raw page_context as a compact one-liner for debug /
    # fallback (the semantic block is the primary signal).
    _raw_pc = {
        k: v for k, v in (environment.get("page_context") or {}).items()
        if k in ("node_id", "collection_id", "search_query",
                 "topic_page_slug", "subject_slug", "page_type", "widget")
    }

    return f"""Du bist der Klassifikations-Modul des WLO-Chatbots.
Analysiere die Nutzernachricht und klassifiziere sie in die 7 Input-Dimensionen.

Aktueller State: {session_state.get('state_id', 'state-1')}
Bekannte Entities: {json.dumps(session_state.get('entities', {}))}{persona_prompt}
Turn: {session_state.get('turn_count', 0) + 1}
Seite: {environment.get('page', '/')}
Seitenkontext (Rohdaten): {json.dumps(_raw_pc)}
Device: {environment.get('device', 'desktop')}{canvas_prompt}
{_page_block}

## Personas (WICHTIG: Genau zuordnen!)
{persona_lines}

PERSONA-REGELN:
- Erkenne Personas SOWOHL durch EXPLIZITE Aussagen als auch durch IMPLIZITE Hinweise.
- EXPLIZIT: "Ich bin Lehrer/Politiker/Journalist/..." → direkte Zuordnung.
- IMPLIZIT: Nutze die Erkennungshinweise oben! Wenn der Nutzer Woerter/Phrasen verwendet
  die zu einer Persona passen, waehle diese Persona auch ohne explizite Selbstidentifikation.
  Beispiele:
  - "Unterricht planen", "fuer meine Klasse", "Arbeitsblatt" → P-W-LK (Lehrkraft)
  - "Lernpfad erstellen", "Lernplan", "Unterrichtsentwurf", "Stundenentwurf" → P-W-LK (Lehrkraft)
  - "ich verstehe nicht", "erklaer mir", "Hausaufgaben" → P-W-SL (Lerner)
  - "mein Kind", "fuer zu Hause", "Nachhilfe" → P-ELT (Eltern)
  - "Bildungspolitik", "Ministerium" → P-W-POL (Politik)
  - "Presseanfrage", "Artikel schreiben" → P-W-PRESSE (Presse)
  - "kuratieren", "Inhalte einstellen" → P-W-RED (Redaktion)
  - "evaluieren", "Vergleich", "fuer unsere Schule" → P-BER (Berater)
  - "Statistiken", "Statistik", "KPIs", "Reporting", "Zahlen", "wie viele" → P-VER (Verwaltung)
  - "Fakten", "Daten", "Nutzungszahlen", "Reichweite", "OER Statistik" → P-VER (Verwaltung)
- WICHTIG: Wer nach Statistiken, Zahlen, Fakten oder Daten fragt ist FAST IMMER P-VER oder P-W-POL, NIEMALS P-AND!
- P-AND NUR wenn KEINE der Erkennungshinweise zutreffen und KEINE Zuordnung moeglich ist.
  Typische P-AND Nachrichten: "hallo", "hi", reine Begruessung ohne inhaltlichen Hinweis.
- Bei expliziter Selbstidentifikation: turn_type = "correction" setzen.
- Im Zweifel: Lieber eine spezifische Persona als P-AND waehlen!
- Wenn die aktuelle Persona P-AND ist und der Nutzer thematische Signale sendet → SOFORT umklassifizieren!
- WICHTIG: Wer einen Lernpfad, Lernplan, Unterrichtsentwurf oder Stundenentwurf erstellen will,
  ist mit hoher Wahrscheinlichkeit P-W-LK (Lehrkraft) — NICHT P-AND oder P-W-SL!
  Auch Schueler koennen Lernpfade wollen, aber nur wenn sie explizit "ich lerne", "fuer mich" o.ae. sagen.

## Intents
{intent_lines}

INTENT-REGELN:
- "Ich will mich erst mal umschauen", "ich schau erst mal", "was gibt es hier",
  "was kannst du", "ich orientiere mich", "erstmal schauen" → INT-W-02 (Soft Probing)
  Signal: orientierungssuchend. State: state-1.
- "Was ist WLO", "Was ist WirLernenOnline" → INT-W-01 (WLO kennenlernen)
- Wenn der Nutzer auf die Begruessung mit Orientierungswunsch antwortet → INT-W-02.

- INT-W-11 (Inhalt erstellen) — Nutzer:in will ein NEUES Material KI-generieren lassen.
  TRIGGER-VERBEN: "erstelle", "erstell mir", "generiere", "mach mir ein(e)",
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
  - INT-W-11 = einzelnes, neu generiertes Material wird gewuenscht.
    Trigger: siehe oben (Verb + konkreter Material-Typ).
  - Faustregel: "Lernpfad"/"Stunde"/"Einheit" → INT-W-10; konkreter Typ wie
    "Arbeitsblatt"/"Quiz"/"Glossar" ohne Stunden-Kontext → INT-W-11.

- ABGRENZUNG INT-W-11 vs. INT-W-03b (Unterrichtsmaterial suchen):
  - INT-W-03b = Nutzer:in SUCHT bestehende Materialien im WLO-Bestand.
    Trigger: "Zeig mir", "Suche", "Finde", "Gibt es", "Hast du", "Welche ... gibt es".
  - INT-W-11 = Nutzer:in will ein NEUES Material ERSTELLEN lassen.
    Trigger: siehe oben (aktive Verben).
  - Faustregel: "Zeig mir Arbeitsblaetter zu X" → INT-W-03b;
    "Erstelle ein Arbeitsblatt zu X" → INT-W-11.

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

Rufe classify_input auf mit den erkannten Werten."""


async def classify_input(
    message: str,
    history: list[dict],
    session_state: dict,
    environment: dict,
    canvas_state: dict | None = None,
) -> ClassificationResult:
    """Phase 1: Classify user input into the 7 input dimensions.

    Returns a validated ClassificationResult. Falls back to defaults on
    validation errors so the pipeline never breaks.
    """
    system = _build_classify_system_prompt(session_state, environment, canvas_state)
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

    tool_call = resp.choices[0].message.tool_calls[0]
    raw = json.loads(tool_call.function.arguments)

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
) -> tuple[str, list[dict], list[str], list]:
    """Generate the final response using the selected pattern and MCP tools.

    Returns (response_text, wlo_cards, tools_called, outcomes).
    Outcomes is a list of ToolOutcome objects (Triple-Schema T-23).
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
Formality: {pattern_output.get('formality', 'neutral')}
Länge: {pattern_output.get('length', 'mittel')} (kurz=kompakte 2-4 Saetze, ein Absatz; mittel=strukturierte Erklaerung mit 2-4 Absaetzen, gerne mit H3-Unterpunkten wenn das Thema mehrere Aspekte hat; lang=ausfuehrliche Darstellung mit mehreren Absaetzen, Beispielen und Aufzaehlungen)
Wenn internes Wissen (RAG-Kontext, query_knowledge-Ergebnisse) verfuegbar ist, nutze es inhaltlich REICH aus — der Nutzer hat explizit gefragt und erwartet eine substantielle Antwort, keine Ein-Satz-Zusammenfassung.
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

### B) MCP-Tools (externe Suche & Datenquellen)
- search_wlo_collections: Kuratierte WLO-Sammlungen nach Thema suchen
- search_wlo_content: Einzelne Lernmaterialien suchen (Arbeitsblaetter, Videos, etc.)
- search_wlo_topic_pages: Themenseiten suchen oder pruefen ob eine Sammlung eine hat
  (per query ODER per collectionId; filtert nach targetGroup: teacher/learner/general)
- get_collection_contents: Inhalte einer Sammlung per nodeId abrufen
- get_node_details: Metadaten eines WLO-Knotens abrufen
- lookup_wlo_vocabulary: Filter-Werte nachschlagen (Faecher, Bildungsstufen)
- get_wirlernenonline_info: Infos ueber WLO/OER-Portal
- get_edu_sharing_network_info: Infos zum edu-sharing Netzwerk
- get_edu_sharing_product_info: Infos zur edu-sharing Software
- get_metaventis_info: Infos zu metaVentis
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
   → get_wirlernenonline_info / get_edu_sharing_* / get_metaventis_info

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

    # Determine which tools to offer
    import logging as _log
    _logger = _log.getLogger(__name__)
    # Info tools should ALWAYS be available regardless of pattern
    INFO_TOOLS = {
        "get_wirlernenonline_info", "get_edu_sharing_network_info",
        "get_edu_sharing_product_info", "get_metaventis_info",
    }
    active_tools = []
    has_explicit_tools = "tools" in pattern_output
    has_mcp_source = pattern_output.get("sources") and "mcp" in pattern_output["sources"]

    if pattern_output.get("tools"):
        # Pattern defines specific tools → use those + info tools
        tool_names = set(pattern_output["tools"]) | INFO_TOOLS
        active_tools = [t for t in TOOL_DEFINITIONS if t["function"]["name"] in tool_names]
    elif has_explicit_tools and not pattern_output["tools"]:
        # Pattern explicitly set tools=[] → NO tools (e.g. PAT-20 Orientierungs-Guide)
        active_tools = []
    elif has_mcp_source:
        active_tools = TOOL_DEFINITIONS
    else:
        # Fallback: always offer search + topic pages + all info tools
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
    _RAG_TOP_K = 15  # global budget for pre-fetched RAG chunks
    _RAG_MIN_SCORE = 0.30  # drop chunks below this relevance threshold
    if available_rag_areas and rag_config:
        always_areas = [a for a in available_rag_areas if rag_config.get(a, {}).get("mode") == "always"]

        if always_areas:
            from app.services.rag_service import get_rag_context as _get_rag_ctx
            prefetch_ctx = await _get_rag_ctx(
                message, areas=always_areas, top_k=_RAG_TOP_K,
                min_score=_RAG_MIN_SCORE,
            )
            _logger.info("RAG pre-fetch for areas %s: %d chars", always_areas, len(prefetch_ctx) if prefetch_ctx else 0)
            if prefetch_ctx:
                knowledge_prefetched = True
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

    for iteration in range(max_iterations):
        tool_choice: Any = None
        if active_tools:
            # Force tool call on first iteration — but NOT if context is already available
            # (pre-fetched knowledge or prior content cards already provide context)
            has_prior_content = bool(session_state.get("entities", {}).get("_last_contents"))
            if (
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
            resp = await client.chat.completions.create(**kwargs)
        except Exception as e:
            _logger.error("LLM API error: %s", e)
            return f"Fehler bei der Verarbeitung: {e}", all_cards, tools_called, outcomes

        choice = resp.choices[0]

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            messages.append(choice.message)
            for tc in choice.message.tool_calls:
                tool_name = tc.function.name
                tool_args = json.loads(tc.function.arguments)
                tools_called.append(tool_name)

                # ── Handle virtual knowledge tool ──────────────
                if tool_name == "query_knowledge":
                    from app.services.rag_service import get_rag_context
                    area = tool_args.get("area", "general")
                    query = tool_args.get("query", message)

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

                    result_text = await get_rag_context(query, areas=[area], top_k=_RAG_TOP_K)
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
                }
                if tool_name in CARD_YIELDING_TOOLS:
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
        else:
            response_text = choice.message.content or ""
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
) -> list[str]:
    """Generate 4 context-aware quick reply suggestions using LLM."""
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
  (e) **Plattforminfo** — Fragen ueber WLO, Projekte, Zahlen
      z.B. "Welche Faecher deckt WLO ab?", "Wer steht hinter der Plattform?"
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

    system = f"""Du bist BOERDi, ein paedagogischer Assistent fuer WirLernenOnline.de.
Erstelle einen strukturierten Lernpfad aus den gegebenen Inhalten.
Persona: {persona_id}
Kontext: {learner_ctx}"""

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
