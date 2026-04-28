"""MCP client for WLO search tools (HTTP JSON-RPC 2.0 with SSE support).

Implements the full MCP protocol handshake:
1. initialize → get session ID
2. notifications/initialized → confirm
3. tools/call → actual tool calls (with session ID header)
"""

from __future__ import annotations

import json
import os
import logging
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.models.schemas import (
    SearchWloArgs, SearchTopicPagesArgs, CollectionContentsArgs, NodeDetailsArgs,
    LookupVocabularyArgs, SubjectPortalsArgs, CollectionTreeArgs,
    HealthCheckArgs, NodesDetailsArgs,
)

logger = logging.getLogger(__name__)

# Map tool names to their Pydantic argument models. Reflects the MCP
# server v2 toolkit (10 tools) — the four web-content scrapers from v1
# have been removed because RAG handles those topics in Boerdi.
_TOOL_ARG_MODELS: dict[str, type] = {
    "search_wlo_collections": SearchWloArgs,
    "search_wlo_content":     SearchWloArgs,
    "search_wlo_topic_pages": SearchTopicPagesArgs,
    "get_collection_contents":CollectionContentsArgs,
    "get_node_details":       NodeDetailsArgs,
    "lookup_wlo_vocabulary":  LookupVocabularyArgs,
    "get_subject_portals":    SubjectPortalsArgs,
    "browse_collection_tree": CollectionTreeArgs,
    "wlo_health_check":       HealthCheckArgs,
    "get_nodes_details":      NodesDetailsArgs,
}

# MCP-Server-URL. Robust gegen die Docker-Compose-Falle, in der
# ``${MCP_SERVER_URL:-}`` einen leeren String an den Container reicht
# (statt ``unset`` zu lassen) — wir behandeln Leer-String wie Unset und
# tolerieren Trailing-Slash.
_DEFAULT_MCP_URL = "https://wlo-mcp-server.vercel.app/mcp"
MCP_URL = ((os.getenv("MCP_SERVER_URL") or "").strip().rstrip("/") or _DEFAULT_MCP_URL)

# Session state per server URL (initialized on first tool call)
_sessions: dict[str, dict[str, Any]] = {}  # url -> {session_id, initialized}
_request_id: int = 0

# Legacy single-server compat
_session_id: str | None = None
_initialized: bool = False


def _next_id() -> int:
    global _request_id
    _request_id += 1
    return _request_id


def _build_headers(include_session: bool = True) -> dict[str, str]:
    """Build HTTP headers matching boerdi's MCP client."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if include_session and _session_id:
        headers["Mcp-Session-Id"] = _session_id
    return headers


def _parse_sse(text: str) -> Any:
    """Parse SSE (Server-Sent Events) response, extracting the last JSON data line."""
    last_json = None
    for line in text.split("\n"):
        trimmed = line.strip()
        if trimmed.startswith("data:"):
            data = trimmed[5:].strip()
            if data and data != "[DONE]":
                try:
                    last_json = json.loads(data)
                except json.JSONDecodeError:
                    pass
    return last_json


def _parse_response(text: str) -> dict:
    """Parse response — try JSON first, then SSE fallback."""
    # Try plain JSON first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try SSE parsing
    result = _parse_sse(text)
    if result:
        return result

    logger.warning("Could not parse MCP response: %s", text[:200])
    return {}


async def _json_rpc(method: str, params: dict | None = None, is_notification: bool = False) -> dict:
    """Send a JSON-RPC 2.0 request to the MCP server."""
    body: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params:
        body["params"] = params
    if not is_notification:
        body["id"] = _next_id()

    headers = _build_headers(include_session=(method != "initialize"))

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            MCP_URL,
            json=body,
            headers=headers,
        )

    # Capture session ID from any response
    global _session_id
    sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
    if sid:
        _session_id = sid

    if resp.status_code not in (200, 202):
        logger.error("MCP HTTP %d for %s: %s", resp.status_code, method, resp.text[:300])
        return {"error": {"message": f"HTTP {resp.status_code}"}}

    if is_notification or not resp.text.strip():
        return {}

    return _parse_response(resp.text)


async def _ensure_initialized():
    """Perform MCP handshake if not yet done."""
    global _session_id, _initialized

    if _initialized:
        return

    # Step 1: Initialize
    result = await _json_rpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "clientInfo": {"name": "badboerdi", "version": "1.0.0"},
    })

    if "error" in result:
        logger.error("MCP initialize failed: %s", result["error"])
        return

    # Extract session ID from response (may be in headers or result)
    # The session ID is typically returned in the response
    if "result" in result:
        logger.info("MCP initialized: %s", json.dumps(result["result"])[:200])

    # Step 2: Send initialized notification
    await _json_rpc("notifications/initialized", is_notification=True)

    _initialized = True
    logger.info("MCP handshake complete (session_id=%s)", _session_id)


async def _ensure_initialized_with_session():
    """Perform MCP handshake, capturing session ID from HTTP response headers."""
    global _session_id, _initialized

    if _initialized:
        return

    body = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "badboerdi", "version": "1.0.0"},
        },
        "id": _next_id(),
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(MCP_URL, json=body, headers=headers)

    if resp.status_code not in (200, 202):
        logger.error("MCP initialize HTTP %d: %s", resp.status_code, resp.text[:300])
        return

    # Capture session ID from response header
    sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
    if sid:
        _session_id = sid
        logger.info("MCP session ID: %s", sid)

    result = _parse_response(resp.text)
    if "result" in result:
        logger.info("MCP server: %s", json.dumps(result["result"])[:200])

    # Send initialized notification
    notif_body = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }
    notif_headers = dict(headers)
    if _session_id:
        notif_headers["Mcp-Session-Id"] = _session_id

    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(MCP_URL, json=notif_body, headers=notif_headers)

    _initialized = True
    logger.info("MCP handshake complete")


# All 10 WLO MCP tools v2 (for OpenAI function calling)
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_wlo_collections",
            "description": "Search WirLernenOnline (WLO) for Sammlungen (= Themenseiten) — kuratierte thematische Seiten, die Lerninhalte buendeln. Sammlungen koennen NICHT nach Inhaltstyp (Video/Arbeitsblatt/...) gefiltert werden — dafuer search_wlo_content verwenden.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Suchanfrage auf Deutsch, z.B. 'Klimawandel' oder 'Algebra'. Leer lassen fuer Top-Level-Sammlungen."},
                    "parentNodeId": {"type": "string", "description": "NodeId einer Eltern-Sammlung, um darin zu suchen. Leer fuer Suche ab WLO-Root."},
                    "educationalContext": {"type": "string", "description": "Bildungsstufe als Label ODER URI — z.B. 'Primarstufe', 'Sekundarstufe I', 'Sekundarstufe II', 'Hochschule'. Mappe Klassenangaben IMMER auf eine Bildungsstufe (Kl. 1-4=Grundschule, 5-10=Sek I, 11-13=Sek II). Eine Filterebene 'Klassenstufe' existiert NICHT."},
                    "discipline": {"type": "string", "description": "Fach/Schulfach als Label ODER URI — z.B. 'Mathematik', 'Biologie', 'Informatik', 'Deutsch'."},
                    "userRole": {"type": "string", "description": "Zielgruppe als Label ODER URI — z.B. 'Lehrer/in', 'Lerner/in', 'Eltern'."},
                    "maxResults": {"type": "integer", "description": "Anzahl Treffer (1-20, Default 5)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_wlo_content",
            "description": "Search WirLernenOnline (WLO) for einzelne Lerninhalte (Arbeitsblaetter, Videos, interaktive Medien, Unterrichtsplaene, Quizze, Bilder, Kurse, ...). Nutze diese Funktion wenn der Nutzer nach einem konkreten Inhaltstyp fragt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Suchanfrage auf Deutsch, z.B. 'Bruchrechnung Grundschule' oder 'Klimawandel interaktiv'."},
                    "educationalContext": {"type": "string", "description": "Bildungsstufe als Label ODER URI — z.B. 'Primarstufe', 'Sekundarstufe I', 'Sekundarstufe II', 'Hochschule', 'Berufliche Bildung'. Mappe Klassenangaben IMMER auf eine Bildungsstufe (Kl. 1-4=Grundschule, 5-10=Sek I, 11-13=Sek II). Eine Filterebene 'Klassenstufe' existiert NICHT."},
                    "discipline": {"type": "string", "description": "Fach/Schulfach als Label ODER URI — z.B. 'Mathematik', 'Biologie', 'Deutsch', 'Informatik'."},
                    "userRole": {"type": "string", "description": "Zielgruppe als Label ODER URI — z.B. 'Lehrer/in', 'Lerner/in'."},
                    "learningResourceType": {"type": "string", "description": "Inhaltstyp / Lernressourcentyp (lrt) als Label ODER URI — z.B. 'Video', 'Arbeitsblatt', 'Bild', 'Interaktives medium', 'Unterrichtsplan', 'Quiz', 'Audio', 'Kurs'. PFLICHT wenn der Nutzer einen Inhaltstyp nennt. Labels aus lookup_wlo_vocabulary(vocabulary='lrt'). Ohne diesen Filter kommen gemischte Treffer zurueck."},
                    "publisher": {"type": "string", "description": "Anbieter-Filter, z.B. 'Klexikon', 'ZUM', 'Serlo', 'Khan Academy'."},
                    "maxResults": {"type": "integer", "description": "Anzahl Treffer (1-20, Default 8)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_wlo_topic_pages",
            "description": "Themenseiten suchen oder pruefen ob eine Sammlung eine Themenseite hat. Themenseiten sind kuratierte Seiten-Layouts mit Swimlanes, zugeschnitten auf Zielgruppen (Lehrkraefte, Lernende, Allgemein). Nutze per query fuer Themen-Suche oder per collectionId um eine konkrete Sammlung zu pruefen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Thematische Suchanfrage, z.B. 'Physik' oder 'Farben'. Leer lassen um alle aufzulisten."},
                    "collectionId": {"type": "string", "description": "NodeId einer Sammlung, um direkt zu pruefen ob sie eine Themenseite hat."},
                    "targetGroup": {"type": "string", "enum": ["teacher", "learner", "general"], "description": "Zielgruppe: teacher (Lehrkraefte), learner (Lernende), general (Allgemein)"},
                    "educationalContext": {"type": "string", "description": "Bildungsstufe, z.B. 'Grundschule', 'Sekundarstufe I'"},
                    "maxResults": {"type": "integer", "description": "Max. Ergebnisse (1-20, Standard 5)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_collection_contents",
            "description": "Inhalte und/oder Sub-Sammlungen einer WLO-Sammlung (Themenseite) per nodeId abrufen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nodeId": {"type": "string", "description": "NodeId der Sammlung (aus search_wlo_collections)"},
                    "query": {"type": "string", "description": "Optionale Such-/Filter-Anfrage, um Ergebnisse innerhalb der Sammlung zu re-ranken."},
                    "contentFilter": {"type": "string", "enum": ["files", "folders", "both"], "description": "files = Lernmaterialien (Default), folders = Sub-Sammlungen, both = alles"},
                    "includeSubcollections": {"type": "boolean", "description": "Wenn true: Sub-Sammlungen rekursiv durchsuchen (nur fuer contentFilter=files)"},
                    "maxResults": {"type": "integer", "description": "Max. Treffer (1-100, Default 20)"},
                    "skipCount": {"type": "integer", "description": "Pagination-Offset (Default 0)"},
                },
                "required": ["nodeId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_details",
            "description": "Get detailed metadata for a specific WLO content node.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nodeId": {"type": "string", "description": "Node ID"},
                },
                "required": ["nodeId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_wlo_vocabulary",
            "description": "Look up valid filter values for WLO search. Use 'discipline' for subjects, 'educationalContext' for education levels, 'lrt' for resource types, 'userRole' for target groups. Returns entries with URIs — use the URI as the filter value on search_wlo_content / search_wlo_collections (resourceType / educationalLevel / discipline).",
            "parameters": {
                "type": "object",
                "properties": {
                    "vocabulary": {
                        "type": "string",
                        "enum": ["educationalContext", "discipline", "userRole", "lrt", "license", "targetGroup"],
                        "description": "Which vocabulary to look up. educationalContext=Bildungsstufen, discipline=Fächer, lrt=Lernressourcentypen, userRole=Zielgruppen, license=CC-Lizenzen, targetGroup=Themenseiten-Zielgruppen.",
                    },
                },
                "required": ["vocabulary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_subject_portals",
            "description": (
                "Listet die WLO-Fachportale — die Top-Level-Sammlungen direkt unter dem WLO-Wurzelknoten "
                "(Mathematik, Informatik, Deutsch, Biologie, …). Nutze dies, um dem Nutzer einen Überblick "
                "über alle abgedeckten Fächer zu geben oder als Einstiegspunkt für einen geführten Drilldown. "
                "Liefert pro Portal nodeId, Name, Beschreibung, optional Themenseiten-URL und Anzahl der "
                "Sub-Sammlungen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "educationalContext": {
                        "type": "string",
                        "description": "Optionaler Filter, z.B. 'Sekundarstufe I'.",
                    },
                    "includeContentCounts": {
                        "type": "boolean",
                        "description": "Wenn true, fügt pro Portal die Anzahl der direkten Sub-Sammlungen hinzu.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_collection_tree",
            "description": (
                "Strukturierter Drilldown unter eine Sammlung. Liefert die direkten Sub-Sammlungen "
                "(depth=1) oder zwei Ebenen (depth=2), optional mit der Anzahl Files je Sub-Sammlung. "
                "Nutze für 'Zeig mir Themenbereiche unter Mathematik', NICHT für die Files selbst — "
                "dafür ist get_collection_contents zuständig."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nodeId": {
                        "type": "string",
                        "description": "UUID der Eltern-Sammlung im Format 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' (z.B. '742d8c87-e5a3-4658-86f9-419c2cea6574' für Informatik). NIEMALS einen Fach-Namen wie 'Informatik' oder 'Mathe' übergeben — das funktioniert nicht. Wenn nur ein Fach-Name vorliegt, ZUERST get_subject_portals oder search_wlo_collections aufrufen, um die UUID zu beschaffen.",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "1=direkte Kinder (schnell, Default), 2=auch Enkel (mehr API-Calls)",
                    },
                    "includeContentCounts": {
                        "type": "boolean",
                        "description": "Wenn true, holt die Anzahl Files pro Sub-Sammlung (Extra-Round-Trip).",
                    },
                    "maxResults": {
                        "type": "integer",
                        "description": "Max. Sub-Sammlungen auf Top-Level (1-100, Default 50)",
                    },
                },
                "required": ["nodeId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wlo_health_check",
            "description": (
                "Probt die WLO-Repository-API auf Erreichbarkeit. Liefert ok-Status, Latenz und den "
                "Wurzel-Knoten zurück. Nützlich um 'WLO ist down' von 'keine Treffer für deine Anfrage' "
                "zu unterscheiden."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_nodes_details",
            "description": (
                "Bulk-Abfrage von Metadaten für mehrere nodeIds parallel (max. 50). Spart Round-Trips, "
                "wenn man Details für viele bereits gefundene Karten braucht. Liefert dieselbe Feldmenge "
                "wie get_node_details mit outputFormat='json' — disciplines/educationalContexts als Labels."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nodeIds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Liste von Node-IDs (max. 50)",
                    },
                },
                "required": ["nodeIds"],
            },
        },
    },
]


def validate_tool_args(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate and clean tool arguments using Pydantic models.

    Returns the validated arguments as a dict (with defaults applied,
    empty strings stripped). Passes through unchanged if no model is registered.
    """
    model = _TOOL_ARG_MODELS.get(tool_name)
    if not model:
        return arguments
    try:
        validated = model.model_validate(arguments)
        # Export only non-empty values (strip empty optional strings)
        return {
            k: v for k, v in validated.model_dump().items()
            if v != "" and v != 0 or k in model.model_fields and model.model_fields[k].is_required()
        }
    except ValidationError as e:
        logger.warning("Tool arg validation for %s: %s — using raw args", tool_name, e)
        return arguments


# Tools that support `outputFormat="json"` on MCP server v2+. We auto-set
# JSON for them so callers can rely on a structured response without each
# call site repeating the parameter. Tools NOT in this set keep their
# native format (e.g. `lookup_wlo_vocabulary` only emits Markdown that
# `_ensure_label_cache` parses).
_JSON_CAPABLE_TOOLS: frozenset[str] = frozenset({
    "search_wlo_collections",
    "search_wlo_content",
    "get_collection_contents",
    "get_node_details",
    "search_wlo_topic_pages",
    "get_subject_portals",
    "browse_collection_tree",
})


async def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    """Call a WLO MCP tool via JSON-RPC 2.0 with MCP protocol handshake."""
    global _initialized, _session_id

    # Debug: log raw LLM-supplied arguments BEFORE validation/resolution so we
    # can see exactly what the model wanted to send. Keeps this at INFO — the
    # cost is ~100 bytes per tool call and it's indispensable for diagnosing
    # filter bugs.
    logger.info("MCP tool %s args: %s", tool_name, arguments)

    # Validate arguments before sending to MCP server
    arguments = validate_tool_args(tool_name, arguments)

    # Auto-resolve label→URI for filter values. The WLO MCP server expects
    # the URI form (e.g. 'http://w3id.org/openeduhub/vocabs/new_lrt_aggregated/...')
    # for resourceType / discipline / educationalLevel. If the LLM passed a
    # plain label or alias ('Video', 'interaktiv', 'Mathematik', 'Sek I'),
    # we look it up in the corresponding vocabulary cache and substitute
    # the URI transparently. Unknown labels are passed through unchanged.
    if tool_name in ("search_wlo_content", "search_wlo_collections"):
        arguments = await _resolve_filter_uris(arguments)

    # Default to JSON output for tools that support it. Cleaner parsing in
    # parse_wlo_cards / parse_wlo_topic_page_cards, label-resolved values,
    # no regex mosaic. v1 servers ignore the unknown param and return
    # Markdown — our parsers accept both, so this is safe to roll out.
    if (
        tool_name in _JSON_CAPABLE_TOOLS
        and "outputFormat" not in arguments
    ):
        arguments = {**arguments, "outputFormat": "json"}

    # Ensure we have a valid session
    await _ensure_initialized_with_session()

    # Make the actual tool call
    result = await _json_rpc("tools/call", {
        "name": tool_name,
        "arguments": arguments,
    })

    if "error" in result:
        error_msg = result["error"].get("message", "Unknown error")
        logger.error("MCP tool %s error: %s", tool_name, error_msg)
        # Reset session state so next call re-initializes
        _initialized = False
        _session_id = None
        # Retry once with fresh session
        logger.info("Retrying MCP tool %s with fresh session...", tool_name)
        await _ensure_initialized_with_session()
        result = await _json_rpc("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if "error" in result:
            error_msg = result["error"].get("message", "Unknown error")
            logger.error("MCP tool %s retry failed: %s", tool_name, error_msg)
            return f"MCP error: {error_msg}"

    # Extract text content from result
    result_data = result.get("result", {})
    content_parts = result_data.get("content", [])

    texts = []
    for part in content_parts:
        if isinstance(part, dict) and part.get("type") == "text":
            texts.append(part.get("text", ""))
        elif isinstance(part, str):
            texts.append(part)

    response = "\n".join(texts) if texts else json.dumps(result_data)
    logger.info("MCP tool %s returned %d chars", tool_name, len(response))
    return response


def parse_total_count(mcp_text: str) -> int:
    """Extract total result count from MCP response text.

    Looks for patterns like:
    - "Gesamt: 42"
    - "Total: 42"
    - "42 Ergebnisse"
    - "Found 42 results"
    """
    import re
    # "Gesamt: 17" or "Total: 17"
    m = re.search(r"(?:Gesamt|Total|Treffer|Ergebnisse gesamt)[:\s]+(\d+)", mcp_text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # "17 Ergebnisse" or "17 results"
    m = re.search(r"(\d+)\s+(?:Ergebnisse|results|Treffer|Eintr)", mcp_text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # "Found 17"
    m = re.search(r"(?:Found|Gefunden)[:\s]+(\d+)", mcp_text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 0


def parse_wlo_topic_page_cards(mcp_text: str) -> list[dict]:
    """Parse `search_wlo_topic_pages` v2 JSON output into Boerdi cards.

    The MCP server (v2) merges variants by collection server-side and
    delivers each card pre-labelled. We just need to map field names to
    Boerdi's internal card schema.

    Server output shape::

        {
          "total": N,
          "results": [
            {
              "title": "Mathematik",
              "collectionId": "<uuid>",
              "topicPageUrl": "https://...",
              "educationalContexts": ["Sek I", ...],
              "variants": [
                {"variantId": "...", "targetGroup": "teacher",
                 "targetGroupLabel": "Lehrkräfte", "topicPageUrl": "..."},
                ...
              ]
            }
          ]
        }

    The legacy Markdown parser (with `_pending_variant`-state and
    target-group label inference) was removed in v2. v1 servers — which
    only emit Markdown — are no longer supported.
    """
    if not mcp_text:
        return []
    try:
        obj = json.loads(mcp_text)
    except (ValueError, json.JSONDecodeError):
        logger.warning(
            "parse_wlo_topic_page_cards: not a JSON envelope (first 80 chars: %r)",
            mcp_text[:80],
        )
        return []
    if not isinstance(obj, dict) or not isinstance(obj.get("results"), list):
        return []

    cards: list[dict] = []
    for r in obj["results"]:
        if not isinstance(r, dict):
            continue
        cid = r.get("collectionId") or ""
        if not cid:
            continue
        topic_pages: list[dict] = []
        # Magic strings the WLO-MCP returns when no real value is set —
        # treat as empty so the frontend's variantLabel disambiguator
        # (target_group → URL params → variant_id → "Variante N") kicks
        # in and the dropdown shows distinguishable entries instead of
        # all variants showing the same generic placeholder.
        UNINFORMATIVE = {
            "", "nicht gesetzt", "nicht gesezt", "unbekannt",
            "topic page", "topic pages", "themenseite", "themenseiten",
            "-", "—",
        }

        def _clean(val: str | None) -> str:
            s = (val or "").strip()
            return "" if s.lower() in UNINFORMATIVE else s

        for v in r.get("variants") or []:
            if not isinstance(v, dict):
                continue
            topic_pages.append({
                "variant_id":   _clean(v.get("variantId")),
                "target_group": _clean(v.get("targetGroup")),
                "label":        _clean(v.get("targetGroupLabel")) or "Themenseite",
                "url":          v.get("topicPageUrl") or r.get("topicPageUrl") or "",
            })

        # ── Dedup: collapse functionally-identical variants ─────────
        # Real-world WLO data often has multiple variants with the SAME
        # url + target_group + label — only the variantId UUID differs.
        # Klicking any of them opens the same page → showing them all in
        # the dropdown is misleading. Keep only one entry per unique
        # (url, target_group, label) tuple. The variant_id of the FIRST
        # entry wins (preserves the canonical-ID semantics).
        if len(topic_pages) > 1:
            _seen: dict[tuple, dict] = {}
            for tp in topic_pages:
                _key = (
                    tp.get("url", ""),
                    tp.get("target_group", "").lower(),
                    tp.get("label", "").lower(),
                )
                if _key not in _seen:
                    _seen[_key] = tp
            _before = len(topic_pages)
            topic_pages = list(_seen.values())
            if len(topic_pages) < _before:
                logger.info(
                    "topic_page variants collapsed: %d → %d für '%s' "
                    "(funktional identisch — gleiche URL/Target/Label)",
                    _before, len(topic_pages), r.get("title", "?"),
                )
        cards.append({
            "node_id":              cid,
            "title":                r.get("title") or cid,
            "node_type":            "collection",
            "topic_pages":          topic_pages,
            "educational_contexts": r.get("educationalContexts") or [],
            "wlo_url": (
                f"https://redaktion.openeduhub.net/edu-sharing/"
                f"components/render/{cid}"
            ),
            "topic_page_url": r.get("topicPageUrl") or "",
        })
    return cards


def _cards_from_json_envelope(data: dict) -> list[dict] | None:
    """Map an MCP v2 JSON envelope ({total, count, results: FormattedNode[]})
    to the internal Boerdi card schema.

    Returns the parsed cards on a v2 envelope, ``None`` if the input doesn't
    look like one (so the caller can fall back to the regex parser).

    The MCP v2 ``FormattedNode`` shape (from ``formatNodes`` in the MCP
    server) is the canonical input — every field is already label-resolved
    server-side (disciplines, educationalContexts, license, …).
    """
    if not isinstance(data, dict):
        return None
    results = data.get("results")
    if not isinstance(results, list):
        return None
    # Heuristic: v2 envelope always has a `total` int and at least one
    # entry shaped like a FormattedNode (with `nodeId`).
    if not (
        ("total" in data or "count" in data)
        and (
            len(results) == 0
            or (isinstance(results[0], dict) and "nodeId" in results[0])
        )
    ):
        return None

    cards: list[dict] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        nid = r.get("nodeId") or ""
        if not nid:
            continue
        node_type = r.get("nodeType") or "content"
        cards.append({
            "node_id": nid,
            "title": r.get("title") or "",
            "description": r.get("description") or "",
            "keywords": r.get("keywords") or [],
            "disciplines": r.get("disciplines") or [],
            "educational_contexts": r.get("educationalContexts") or [],
            "user_roles": r.get("userRoles") or [],
            "learning_resource_types": r.get("learningResourceTypes") or [],
            # Primary "open"-link (external preferred, in-repo viewer as fallback).
            "url": r.get("url") or "",
            # Direct binary download (no auth) — only set on file nodes.
            # Frontend can offer a download button without an extra round-trip.
            "download_url": r.get("downloadUrl") or "",
            # In-repo viewer URL (PDF/video preview component).
            "content_url": r.get("contentUrl") or "",
            "preview_url": r.get("previewUrl") or "",
            # Distinguish generic mediatype-icon from real generated thumbnail —
            # frontend can decide whether to feature the preview prominently.
            "preview_is_icon": bool(r.get("previewIsIcon")),
            "mime_type": r.get("mimeType") or "",
            "file_size": r.get("fileSize") or 0,
            "license": r.get("license") or "",
            "publisher": r.get("publisher") or "",
            "node_type": node_type,
            "wlo_url": (
                f"https://redaktion.openeduhub.net/edu-sharing/components/"
                f"render/{nid}"
            ),
            "topic_page_url": r.get("topicPageUrl") or "",
        })
    return cards


def parse_wlo_cards(mcp_text: str) -> list[dict]:
    """Parse an MCP v2 JSON envelope into Boerdi card objects.

    The MCP server is called with ``outputFormat="json"`` (set centrally in
    :func:`call_mcp_tool` for all v2-aware tools) and returns:

    .. code-block:: json

        {"total": N, "count": M, "results": [FormattedNode, ...]}

    All vocab fields (`disciplines`, `educationalContexts`, `userRoles`,
    `learningResourceTypes`, `license`) arrive **label-resolved** —
    Hochschulfächersystematik via server-side `_DISPLAYNAME`, school
    vocab via the local map, license via the license vocab. No client-
    side URI-→-label resolution remains.

    The legacy Markdown / key-value parser was removed in v2 (see git
    history if you need it back). v1 servers — which only emit Markdown —
    are no longer supported.
    """
    if not mcp_text:
        return []
    try:
        obj = json.loads(mcp_text)
    except (ValueError, json.JSONDecodeError):
        logger.warning("parse_wlo_cards: not a JSON envelope (first 80 chars: %r)", mcp_text[:80])
        return []
    cards = _cards_from_json_envelope(obj)
    if cards is None:
        logger.warning("parse_wlo_cards: JSON did not match v2 envelope shape")
        return []
    return cards


# ── Label→URI caches for filter auto-resolution ─────────────────
#
# Maps lowercased label OR alias → canonical URI. Populated lazily
# via lookup_wlo_vocabulary. Used by _resolve_filter_uris to translate
# LLM-produced filter values (which may arrive as labels like 'Video'
# or aliases like 'interaktiv') into the URI form the MCP server
# requires for filtering.
_label_to_uri_cache: dict[str, dict[str, str]] = {
    # vocabulary → {normalized_label_or_alias: uri}
    "lrt": {},
    "discipline": {},
    "educationalContext": {},
    "userRole": {},
}
_label_cache_loaded: dict[str, bool] = {
    "lrt": False,
    "discipline": False,
    "educationalContext": False,
    "userRole": False,
}


def _norm_label(s: str) -> str:
    """Lowercase and strip for case-insensitive lookup."""
    return (s or "").strip().lower()


async def _ensure_label_cache(vocab: str) -> None:
    """Lazily populate the label→URI cache for a vocabulary."""
    if _label_cache_loaded.get(vocab):
        return
    if vocab not in _label_to_uri_cache:
        return  # unknown vocab, do nothing
    try:
        raw = await call_mcp_tool("lookup_wlo_vocabulary", {"vocabulary": vocab})
    except Exception as e:  # pragma: no cover — network failure
        logger.warning("%s vocabulary preload failed: %s", vocab, e)
        _label_cache_loaded[vocab] = True
        return

    # Output format (from real MCP response):
    #   - **Video**
    #     URI: http://w3id.org/openeduhub/vocabs/new_lrt_aggregated/...
    #   - **Interaktives medium** | Aliases: interactive media, interaktiv, simulation
    #     URI: http://w3id.org/openeduhub/vocabs/new_lrt_aggregated/...
    import re as _re
    current_label: str | None = None
    current_aliases: list[str] = []
    cache = _label_to_uri_cache[vocab]

    for line in (raw or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        # Entry header: "- **Label** | Aliases: a, b, c" or "- **Label**"
        m_label = _re.match(r"-\s*\*\*(.+?)\*\*(?:\s*\|\s*Aliases:\s*(.+))?\s*$", line)
        if m_label:
            current_label = m_label.group(1).strip()
            aliases_str = m_label.group(2) or ""
            current_aliases = [a.strip() for a in aliases_str.split(",") if a.strip()]
            continue
        # URI line: "URI: http://..."
        m_uri = _re.match(r"URI:\s*(https?://\S+)", line)
        if m_uri and current_label:
            uri = m_uri.group(1).strip()
            cache.setdefault(_norm_label(current_label), uri)
            for alias in current_aliases:
                cache.setdefault(_norm_label(alias), uri)
            current_label = None
            current_aliases = []

    logger.info("%s label→URI cache loaded: %d entries", vocab, len(cache))
    _label_cache_loaded[vocab] = True


def _fuzzy_lookup(cache: dict[str, str], needle: str) -> tuple[str, str] | None:
    """Best-effort label→URI lookup that tolerates LLM paraphrasing.

    Strategy:
    1. Exact match on normalized form ("Video" → cache["video"]).
    2. Substring containment either way — cache key contains needle OR
       needle contains cache key. This catches "Interaktives Material"
       vs. cache entry "interaktiv" (alias of "Interaktives medium"):
       needle contains the alias, so it matches.
    3. Longest-substring wins when multiple keys match, to prefer
       specific over generic (e.g. "interaktives medium" over "medium").

    Returns (matched_key, uri) on hit, None otherwise.
    """
    if not needle:
        return None
    nn = _norm_label(needle)
    # 1. exact
    if nn in cache:
        return nn, cache[nn]
    # 2. substring
    best_key: str | None = None
    best_len = 0
    for key in cache:
        if not key:
            continue
        # key appears in needle (e.g. "interaktiv" in "interaktives material")
        if key in nn or nn in key:
            if len(key) > best_len:
                best_key = key
                best_len = len(key)
    if best_key is not None:
        return best_key, cache[best_key]
    return None


# ── LLM-gestütztes Vocab-Mapping (Fallback wenn fuzzy_lookup leer ausgeht) ──
#
# User-Eingaben sind nicht immer in unserer Vokabular-Form ("biology" statt
# "Biologie", "Mathe Klasse 11 Gym", "Naturwiss"). _fuzzy_lookup deckt
# Substring-Paraphrasen ab; für komplexere Mappings (Sprache, paraphrasierte
# Konzepte) holen wir den LLM dazu — pro (vocab, value)-Kombination einmal,
# dann gecacht.
_llm_vocab_cache: dict[tuple[str, str], str | None] = {}

# Eingaben, die offensichtlich keine Vokabular-Werte sind, sollten gar nicht
# erst beim LLM landen (verschwendet Tokens und Latenz). Sehr lange Strings,
# offensichtliche Sätze oder Whitespace-only werden hier abgewiesen.
_LLM_VOCAB_MIN_LEN = 2
_LLM_VOCAB_MAX_LEN = 80


async def _llm_vocab_match(vocab: str, value: str) -> str | None:
    """Use the chat LLM to map a free-form value to a vocabulary URI.

    Returns the URI on a confident match, ``None`` when the LLM declines.
    Cached per (vocab, normalized_value) — repeats only consume one LLM call
    across the whole process lifetime.
    """
    nv = _norm_label(value)
    if not nv:
        return None
    if len(nv) < _LLM_VOCAB_MIN_LEN or len(nv) > _LLM_VOCAB_MAX_LEN:
        return None
    cache_key = (vocab, nv)
    if cache_key in _llm_vocab_cache:
        return _llm_vocab_cache[cache_key]

    cache = _label_to_uri_cache.get(vocab) or {}
    if not cache:
        return None

    # Build a compact list of "<label or alias>: <uri>" — the LLM picks one.
    # We dedupe URIs since multiple aliases share the same URI.
    by_uri: dict[str, list[str]] = {}
    for key, uri in cache.items():
        by_uri.setdefault(uri, []).append(key)
    options_lines: list[str] = []
    for uri, aliases in by_uri.items():
        prim = aliases[0]
        rest = aliases[1:6]  # cap aliases to keep prompt small
        suffix = f" (also: {', '.join(rest)})" if rest else ""
        options_lines.append(f"- {prim}{suffix} → {uri}")
    options_text = "\n".join(options_lines)

    vocab_label = {
        "lrt": "learning resource type",
        "discipline": "school subject / discipline",
        "educationalContext": "educational level / Bildungsstufe",
        "userRole": "target user role",
    }.get(vocab, vocab)

    system = (
        "You are a strict vocabulary mapper for the WirLernenOnline (WLO) "
        f"taxonomy. Map a free-form user term to ONE entry from the list of "
        f"valid {vocab_label}s, or reply 'NONE' if no entry matches with "
        "reasonable confidence. Reply ONLY with the URI of the chosen entry "
        "(verbatim from the list) or the literal string 'NONE'. No prose, no "
        "punctuation."
    )
    user = (
        f"User term: {value!r}\n\n"
        f"Valid {vocab_label}s:\n{options_text}\n\n"
        "Pick the URI of the best matching entry, or reply 'NONE'."
    )

    try:
        # Lazy import to avoid a circular import at module load time.
        from app.services.llm_provider import get_client, get_chat_model
        client = get_client()
        model = get_chat_model()
        # Minimal token budget — the answer is one URI line.
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=80,
            temperature=0,
        )
        content = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("LLM vocab-match for %s=%r failed: %s", vocab, value, e)
        _llm_vocab_cache[cache_key] = None
        return None

    if not content or content.upper() == "NONE":
        _llm_vocab_cache[cache_key] = None
        logger.info("LLM declined vocab match: %s=%r", vocab, value)
        return None

    # Validate: must be one of the URIs we offered.
    valid_uris = set(by_uri.keys())
    # The model sometimes wraps the URI in quotes/backticks — strip light
    # decoration before comparing.
    candidate = content.strip().strip("`'\"<>")
    if candidate not in valid_uris:
        # Last resort: see if the response *contains* one of the URIs.
        for uri in valid_uris:
            if uri in candidate:
                candidate = uri
                break
        else:
            logger.warning(
                "LLM vocab-match returned non-URI for %s=%r: %r",
                vocab, value, content[:200],
            )
            _llm_vocab_cache[cache_key] = None
            return None

    _llm_vocab_cache[cache_key] = candidate
    logger.info("LLM resolved vocab %s=%r → %s", vocab, value, candidate)
    return candidate


async def _resolve_filter_uris(arguments: dict[str, Any]) -> dict[str, Any]:
    """Rewrite label-style filter values into URIs using vocabulary caches.

    The WLO MCP server accepts BOTH plain labels and full URIs for its
    filter params (learningResourceType, discipline, educationalContext,
    userRole). We still run a label→URI translation because:
      * it normalises paraphrased values ("Interaktives Material" → the
        canonical alias "interaktiv" → URI for Interaktives medium), and
      * URIs are unambiguous and less brittle to server-side label parsing.

    Leaves URIs untouched. Unresolvable labels are passed through — the
    server may still accept them (exact label match) or at worst return
    unfiltered results.
    """
    # Map the server's actual parameter names → vocabulary name used with
    # lookup_wlo_vocabulary. These are the REAL MCP param names (matched
    # against the server's tools/list schema), NOT our historical aliases.
    key_to_vocab = {
        "learningResourceType": "lrt",
        "discipline": "discipline",
        "educationalContext": "educationalContext",
        "userRole": "userRole",
    }
    out = dict(arguments)
    for key, vocab in key_to_vocab.items():
        val = out.get(key)
        if not isinstance(val, str) or not val:
            continue
        if val.startswith(("http://", "https://")):
            continue  # already a URI
        await _ensure_label_cache(vocab)
        cache = _label_to_uri_cache.get(vocab) or {}
        match = _fuzzy_lookup(cache, val)
        if match:
            matched_key, uri = match
            if matched_key == _norm_label(val):
                logger.info("resolved %s=%r → %s", key, val, uri)
            else:
                logger.info("resolved %s=%r via fuzzy %r → %s", key, val, matched_key, uri)
            out[key] = uri
            continue
        # Heuristik leer → LLM-Fallback. Greift bei paraphrasierten /
        # fremdsprachigen / nicht-canonical Eingaben ("sciences",
        # "Mathe Klasse 11 Gym", "Naturwiss"). Pro (vocab, value) genau
        # ein LLM-Call dank _llm_vocab_cache.
        llm_uri = await _llm_vocab_match(vocab, val)
        if llm_uri:
            out[key] = llm_uri
            continue
        logger.info("no URI for %s=%r (vocab=%s); passing label through", key, val, vocab)
    return out


async def resolve_discipline_labels(cards: list[dict]) -> list[dict]:
    """No-op kept for source-compat with older call sites.

    With MCP server v2, the server-side ``ccm:taxonid_DISPLAYNAME``
    already produces clean labels for both the school discipline vocab
    AND the Hochschulfächersystematik. The previous URI-→-label fallback
    chain (``_pretty_uri_label`` / ``_ensure_discipline_cache`` /
    ``_discipline_uri_to_label``) is therefore dead code and was
    removed. This stub stays so callers don't have to be patched all
    at once — feel free to delete the call sites in a follow-up.
    """
    return cards


# ── Multi-server support ─────────────────────────────────────────

async def discover_server_tools(url: str) -> list[dict[str, Any]]:
    """Connect to an MCP server, perform handshake, and list available tools.

    Returns list of tool definitions [{name, description, parameters}, ...].
    Used by the Studio to discover tools when registering a new MCP server.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    # Step 1: Initialize
    init_body = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "badboerdi-discovery", "version": "1.0.0"},
        },
        "id": 1,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=init_body, headers=headers)

    if resp.status_code not in (200, 202):
        raise ConnectionError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    session_id = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")

    # Step 2: Send initialized notification
    notif_headers = dict(headers)
    if session_id:
        notif_headers["Mcp-Session-Id"] = session_id

    notif_body = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(url, json=notif_body, headers=notif_headers)

    # Step 3: List tools
    list_body = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 2,
    }
    list_headers = dict(headers)
    if session_id:
        list_headers["Mcp-Session-Id"] = session_id

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=list_body, headers=list_headers)

    if resp.status_code not in (200, 202):
        raise ConnectionError(f"tools/list failed: HTTP {resp.status_code}")

    result = _parse_response(resp.text)
    tools_data = result.get("result", {}).get("tools", [])

    return [
        {
            "name": t.get("name", ""),
            "description": t.get("description", ""),
        }
        for t in tools_data
        if isinstance(t, dict) and t.get("name")
    ]


def _get_server_url_for_tool(tool_name: str) -> str:
    """Look up which MCP server provides a given tool.

    Falls back to default MCP_URL if no registry match is found.
    """
    from app.services.config_loader import get_enabled_mcp_servers

    for server in get_enabled_mcp_servers():
        server_tools = server.get("tools", [])
        if tool_name in server_tools:
            return server.get("url", MCP_URL)

    return MCP_URL
