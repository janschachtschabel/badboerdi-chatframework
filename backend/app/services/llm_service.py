"""LLM service using OpenAI API for classification and response generation."""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import ValidationError

from app.models.schemas import ClassificationResult
from app.services.mcp_client import TOOL_DEFINITIONS, call_mcp_tool, parse_wlo_cards
from app.services.pattern_engine import select_pattern
from app.services.config_loader import (
    load_persona_prompt, load_domain_rules, load_base_persona, load_guardrails,
    load_intents, load_states, load_entities, load_signal_modulations,
    load_device_config, load_persona_definitions,
)
from app.services.llm_provider import get_client, get_chat_model

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


def _build_classify_system_prompt(session_state: dict, environment: dict) -> str:
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
                line += f"\n  Erkennungshinweise: {', '.join(hints[:12])}"
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

    # Format entity list
    entity_lines = ", ".join(e["id"] for e in entities) if entities else "fach, stufe, thema, medientyp, lizenz"

    persona_prompt = ""
    if session_state.get("persona_id"):
        persona_prompt = f"\nAktuelle Persona: {session_state['persona_id']}"

    return f"""Du bist der Klassifikations-Modul des WLO-Chatbots.
Analysiere die Nutzernachricht und klassifiziere sie in die 7 Input-Dimensionen.

Aktueller State: {session_state.get('state_id', 'state-1')}
Bekannte Entities: {json.dumps(session_state.get('entities', {}))}{persona_prompt}
Turn: {session_state.get('turn_count', 0) + 1}
Seite: {environment.get('page', '/')}
Seitenkontext: {json.dumps(environment.get('page_context', {}))}
Device: {environment.get('device', 'desktop')}

## Personas (WICHTIG: Genau zuordnen!)
{persona_lines}

PERSONA-REGELN:
- Erkenne Personas SOWOHL durch EXPLIZITE Aussagen als auch durch IMPLIZITE Hinweise.
- EXPLIZIT: "Ich bin Lehrer/Politiker/Journalist/..." → direkte Zuordnung.
- IMPLIZIT: Nutze die Erkennungshinweise oben! Wenn der Nutzer Woerter/Phrasen verwendet
  die zu einer Persona passen, waehle diese Persona auch ohne explizite Selbstidentifikation.
  Beispiele:
  - "Unterricht planen", "fuer meine Klasse", "Arbeitsblatt" → P-W-LK (Lehrkraft)
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

## Intents
{intent_lines}

INTENT-REGELN:
- "Ich will mich erst mal umschauen", "ich schau erst mal", "was gibt es hier",
  "was kannst du", "ich orientiere mich", "erstmal schauen" → INT-W-02 (Soft Probing)
  Signal: orientierungssuchend. State: state-1.
- "Was ist WLO", "Was ist WirLernenOnline" → INT-W-01 (WLO kennenlernen)
- Wenn der Nutzer auf die Begruessung mit Orientierungswunsch antwortet → INT-W-02.

## Signale
{signal_lines}

## States
{state_lines}

## Entities
{entity_lines}

Rufe classify_input auf mit den erkannten Werten."""


async def classify_input(
    message: str,
    history: list[dict],
    session_state: dict,
    environment: dict,
) -> ClassificationResult:
    """Phase 1: Classify user input into the 7 input dimensions.

    Returns a validated ClassificationResult. Falls back to defaults on
    validation errors so the pipeline never breaks.
    """
    system = _build_classify_system_prompt(session_state, environment)
    classify_tool = _build_classify_tool()

    messages = [{"role": "system", "content": system}]
    for h in history[-10:]:
        messages.append(h)
    messages.append({"role": "user", "content": message})

    resp = await client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=[classify_tool],
        tool_choice={"type": "function", "function": {"name": "classify_input"}},
        temperature=0.1,
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
Länge: {pattern_output.get('length', 'mittel')}
Max. Ergebnisse: {pattern_output.get('max_items', 5)}""",
        # Layer 5: Conversation context
        f"""## Kontext
Seite: {environment.get('page', '/')}
Seitenkontext: {json.dumps(environment.get('page_context', {}))}
Entities: {json.dumps(classification.get('entities', {}))}
Signale: {', '.join(classification.get('signals', []))}
State: {classification.get('next_state', 'state-1')}""",
    ]

    # Signal-driven modulation rules
    if pattern_output.get("skip_intro"):
        system_parts.append("\n## Regel: Keine Einleitung. Direkt zur Sache.")
    if pattern_output.get("one_option"):
        system_parts.append("\n## Regel: Nur 1 Option anbieten. Nicht überfordern.")
    if pattern_output.get("add_sources"):
        system_parts.append("\n## Regel: Quellen und Herkunft explizit nennen.")
    if pattern_output.get("degradation"):
        missing = pattern_output.get("missing_slots", [])
        system_parts.append(
            f"\n## Degradation aktiv: Fehlende Slots: {missing}. "
            "Starte breite Suche UND frage gleichzeitig nach fehlenden Infos. Nie blockieren!"
        )

    # RAG as tools: knowledge areas are presented as callable functions
    has_rag_tools = bool(available_rag_areas)
    if rag_context:
        # Memory context only (no blind RAG injection)
        system_parts.append(f"\n{rag_context}")

    # Guardrails (from config file, always last — not overridable)
    system_parts.append(guardrails)

    # Check if pattern explicitly has NO tools
    has_explicit_empty_tools = ("tools" in pattern_output and not pattern_output["tools"])
    pattern_wants_no_tools = has_explicit_empty_tools and not (
        pattern_output.get("sources") and "mcp" in pattern_output["sources"]
    )

    if pattern_wants_no_tools:
        # Pattern like PAT-20 Orientierungs-Guide: pure text, no tool calls
        system_parts.append("""
## Antwort-Regeln
- Antworte NUR mit Text und Quick Replies.
- Rufe KEINE Tools auf.
- Stelle die Faehigkeiten des Chatbots vor und biete konkrete Einstiegspunkte an.
- Erfinde KEINE Sammlungen oder Materialien.
- Schliesse mit einer offenen Frage die hilft, die Persona des Nutzers zu klaeren.

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
    for h in history[-10:]:
        messages.append(h)

    # ── Pre-fetch only "always" areas, on-demand areas via LLM tool call ──
    # "always" areas: pre-fetched and injected (guaranteed to be available)
    # "on-demand" areas: only queried when LLM explicitly calls query_knowledge
    knowledge_prefetched = False
    always_areas: list[str] = []  # tracked for redundant-call guard in tool loop
    _RAG_TOP_K = 8  # global budget for pre-fetched RAG chunks
    _RAG_MIN_SCORE = 0.25  # drop chunks below this relevance threshold
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
                        + prefetch_ctx[:6000]
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
        kwargs: dict[str, Any] = {
            "model": MODEL,
            "messages": messages,
            "temperature": 0.4,
        }
        if active_tools:
            kwargs["tools"] = active_tools
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
                kwargs["tool_choice"] = "required"
            first_iteration = False

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

                # Enforce maxItems limit on search/collection tools
                MAX_ITEMS = 5
                if tool_name in ("search_wlo_collections", "search_wlo_content", "get_collection_contents"):
                    tool_args.setdefault("maxItems", MAX_ITEMS)
                    if tool_args["maxItems"] > MAX_ITEMS:
                        tool_args["maxItems"] = MAX_ITEMS

                # Triple-Schema T-23: call with structured outcome
                from app.services.outcome_service import call_with_outcome
                result_text, outcome = await call_with_outcome(tool_name, tool_args)
                outcomes.append(outcome)
                cards = parse_wlo_cards(result_text)
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
    entities = classification.get("entities", {})

    system = f"""Du generierst genau 4 kurze Antwortvorschlaege fuer einen Chatbot-Nutzer.
Der Nutzer hat gerade mit einem Bildungsportal-Chatbot (WirLernenOnline) interagiert.

Kontext:
- Persona: {persona_id}
- Intent: {intent_id}
- State: {state_id}
- Erkannte Entities: {json.dumps(entities)}

WICHTIG — Perspektive:
Die Vorschlaege sind Saetze, die der NUTZER sagen wuerde — NICHT der Bot!
Schreibe aus ICH-Perspektive des Nutzers. Der Nutzer spricht den Bot an.
FALSCH (Bot-Perspektive): "Weitere Materialien zeigen", "Suche eingrenzen"
RICHTIG (User-Perspektive): "Zeig mir mehr davon", "Ich will das eingrenzen"

Regeln:
1. Genau 4 Vorschlaege, einer pro Zeile
2. Jeder Vorschlag max 6-8 Woerter
3. Vorschlaege muessen zur Persona und zum aktuellen Gespraechskontext passen
4. Mix aus diesen Typen:
   a) 1x Vertiefung (mehr zum aktuellen Thema, z.B. "Gibt es Videos dazu?")
   b) 1x Richtungswechsel (neues Thema/anderer Blickwinkel, z.B. "Was gibt es zu Physik?")
   c) 1x Weiterverarbeitung (Lernpfad, Unterrichtspaket, z.B. "Mach mir einen Lernpfad daraus")
   d) 1x offene Frage oder Orientierung (z.B. "Was kannst du noch?")
5. Natuerlich klingen, wie echte Nutzer-Eingaben — keine Bot-Kommandos
6. KEINE Nummerierung, KEINE Aufzaehlungszeichen, nur der reine Text
7. Sprache: Deutsch, passend zur Persona (du/Sie)

Beispiele fuer Lehrkraefte (Sie):
Haben Sie auch Videos dazu?
Erstellen Sie mir einen Lernpfad
Was gibt es zur Oberstufe?
Anderes Thema: Klimawandel

Beispiele fuer Schueler (du):
Hast du noch mehr davon?
Erklaer mir das genauer
Ich suche was zu Mathe
Mach mir einen Lernpfad daraus

Beispiele fuer Eltern (Sie):
Gibt es das auch als Video?
Was empfehlen Sie fuer Klasse 5?
Ich suche etwas anderes
Wie kann mein Kind damit lernen?"""

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Nutzernachricht: {message}\n\nBot-Antwort: {response_text[:500]}"},
    ]

    try:
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=150,
        )
        text = resp.choices[0].message.content or ""
        replies = [line.strip() for line in text.strip().split("\n") if line.strip()]
        return replies[:4]
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
Wenn wenige Materialien vorhanden sind, schlage vor wo ergaenzende Materialien hilfreich waeren."""

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    try:
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=2000,
        )
        return resp.choices[0].message.content or "Lernpfad konnte nicht erstellt werden."
    except Exception as e:
        return f"Fehler beim Erstellen des Lernpfads: {e}"
