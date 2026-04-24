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
    InfoQueryArgs, LookupVocabularyArgs,
)

logger = logging.getLogger(__name__)

# Map tool names to their Pydantic argument models
_TOOL_ARG_MODELS: dict[str, type] = {
    "search_wlo_collections": SearchWloArgs,
    "search_wlo_content": SearchWloArgs,
    "search_wlo_topic_pages": SearchTopicPagesArgs,
    "get_collection_contents": CollectionContentsArgs,
    "get_node_details": NodeDetailsArgs,
    "get_wirlernenonline_info": InfoQueryArgs,
    "get_edu_sharing_network_info": InfoQueryArgs,
    "get_edu_sharing_product_info": InfoQueryArgs,
    "get_metaventis_info": InfoQueryArgs,
    "lookup_wlo_vocabulary": LookupVocabularyArgs,
}

MCP_URL = os.getenv("MCP_SERVER_URL", "https://wlo-mcp-server.vercel.app/mcp")

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


# All 9 WLO MCP tools (for OpenAI function calling)
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
            "name": "get_wirlernenonline_info",
            "description": "Infos von WirLernenOnline (WLO) – OER-Portal. Nutze bei Fragen zu: WLO, WirLernenOnline, OER, Fachportale, Qualitaetssicherung, Mitmachen, Fachredaktion, was ist WLO, wie funktioniert WLO, wer steckt dahinter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic or question about WLO"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_edu_sharing_network_info",
            "description": "Infos von edu-sharing-network.org – Community & Vernetzung. Nutze bei Fragen zu: edu-sharing Vernetzung, JOINTLY, ITsJOINTLY, BIRD, Bildungsraum Digital, Hackathon, OER-Sommercamp, Netzwerk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query about edu-sharing network"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_edu_sharing_product_info",
            "description": "Infos zum edu-sharing Software-Produkt. Nutze bei Fragen zu: edu-sharing Software, Repository, Content-Management, LMS-Integration, Schnittstellen, API, Technik.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query about edu-sharing product"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metaventis_info",
            "description": "Infos von metaventis.com – Unternehmen hinter edu-sharing. Nutze bei Fragen zu: metaVentis, Schulcloud, IDM, Autoren-Loesung, F&E, Firmenwissen, E-Learning, wer entwickelt edu-sharing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query about metaVentis"},
                },
                "required": ["query"],
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
                        "enum": ["educationalContext", "discipline", "userRole", "lrt"],
                        "description": "Which vocabulary to look up: educationalContext (Bildungsstufen), discipline (Fächer), lrt (Lernressourcentypen), userRole (Zielgruppen)",
                    },
                },
                "required": ["vocabulary"],
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


_UUID_RE = re.compile(
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
    re.IGNORECASE,
)


def _extract_collection_id_from_url(url: str) -> str:
    """Pull the collection UUID out of a WLO topic-page URL.

    Topic-page URLs look like:
      .../components/topic-pages?collectionId=324f24e3-6687-...
      .../components/topic-pages?collectionId=<uuid>&var=teacher
      .../components/render/<uuid>
      .../components/collections?id=<uuid>&scope=...
    Any of those are acceptable — we just return the first UUID we find.
    """
    if not url:
        return ""
    m = _UUID_RE.search(url)
    return m.group(0) if m else ""


def parse_wlo_topic_page_cards(mcp_text: str) -> list[dict]:
    """Parse the special `search_wlo_topic_pages` output.

    The response uses `Sammlung-nodeId:` / `Variante-ID:` / `Themenseite:`
    instead of the plain `nodeId:` / `URL:` that `parse_wlo_cards` expects.
    Multiple variants of the same topic page (different target groups) are
    merged into one card, with all variants collected in `topic_pages[]`.
    """
    if not mcp_text:
        return []

    cards_by_nid: dict[str, dict] = {}
    order: list[str] = []
    current_title: str | None = None
    current: dict | None = None

    for raw in mcp_text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("## "):
            # New variant block — the title is the collection title
            current_title = line.lstrip("#").strip()
            current = None
            continue
        if not current_title:
            continue

        ll = line.lower()
        if ll.startswith("sammlung-nodeid:") or ll.startswith("nodeid:"):
            nid = line.split(":", 1)[-1].strip()
            if not nid:
                continue
            if nid not in cards_by_nid:
                cards_by_nid[nid] = {
                    "node_id": nid,
                    "title": current_title,
                    "node_type": "collection",
                    "topic_pages": [],
                    "wlo_url": f"https://redaktion.openeduhub.net/edu-sharing/components/render/{nid}",
                }
                order.append(nid)
            current = cards_by_nid[nid]
            # Keep the longest/earliest title we saw
            if not current.get("title"):
                current["title"] = current_title
        elif ll.startswith("variante-id:") and current is not None:
            current.setdefault("_pending_variant", {})["variant_id"] = line.split(":", 1)[-1].strip()
        elif ll.startswith("zielgruppe:") and current is not None:
            tg = line.split(":", 1)[-1].strip()
            if tg.lower() in ("nicht gesetzt", "unknown", "-", ""):
                tg = ""
            current.setdefault("_pending_variant", {})["target_group"] = tg
        elif ll.startswith("label:") and current is not None:
            current.setdefault("_pending_variant", {})["label"] = line.split(":", 1)[-1].strip()
        elif ll.startswith("themenseite:") and current is not None:
            url = line.split(":", 1)[-1].strip()
            variant = current.pop("_pending_variant", {}) or {}
            variant["url"] = url
            variant.setdefault("target_group", "")
            variant.setdefault("variant_id", "")
            # Prefer a human-readable label derived from the Zielgruppe
            # ('Lehrkräfte' / 'Lernende' / 'Allgemein') — only keep a
            # generic MCP-supplied label if it's actually informative
            # (i.e. not the useless default "Themenseite"). Variants
            # without a target group fall back to "Themenseite".
            mcp_label = (variant.get("label") or "").strip()
            tg_label = _tp_label(variant.get("target_group", ""))
            if mcp_label and mcp_label.lower() != "themenseite":
                variant["label"] = mcp_label
            else:
                variant["label"] = tg_label
            current["topic_pages"].append(variant)

    return [cards_by_nid[nid] for nid in order]


def parse_wlo_cards(mcp_text: str) -> list[dict]:
    """Parse MCP response text into structured WLO card objects.

    Supports both formats:
    - Markdown bullet format: "- **Titel:** value"
    - Plain key-value format: "Titel: value"  (current MCP server format)
    """
    cards = []
    current: dict = {}

    def _val(line: str) -> str:
        """Extract value from 'Key: value' or '- **Key:** value' line."""
        if ":**" in line:
            return line.split(":**", 1)[-1].strip().strip("*")
        if ": " in line:
            return line.split(": ", 1)[-1].strip()
        return ""

    for line in mcp_text.split("\n"):
        line = line.strip()
        if not line:
            continue  # Skip empty lines — only ## headings start new cards

        ll = line.lower()

        # Skip separator lines
        if line.startswith("---") or line.startswith("===") or all(c == '-' for c in line):
            continue

        # Headings → new card
        if line.startswith("# ") or line.startswith("## "):
            if current.get("title"):
                cards.append(current)
            current = {"title": line.lstrip("#").strip()}

        # URL (content link)
        elif ll.startswith("url:") or ll.startswith("- **url"):
            current["url"] = _val(line)

        # WLO URL
        elif ll.startswith("wlo") or ll.startswith("- **wlo"):
            current["wlo_url"] = _val(line)

        # Vorschaubild / Preview
        elif ll.startswith("vorschaubild:") or ll.startswith("preview:") or ll.startswith("- **preview"):
            current["preview_url"] = _val(line)

        # Beschreibung
        elif ll.startswith("beschreibung:") or ll.startswith("- **beschreibung"):
            current["description"] = _val(line)

        # nodeId
        elif ll.startswith("nodeid:") or ll.startswith("- **node"):
            node_id = _val(line)
            current["node_id"] = node_id
            # Generate WLO URL from nodeId if not already set
            if node_id and not current.get("wlo_url"):
                current["wlo_url"] = f"https://redaktion.openeduhub.net/edu-sharing/components/render/{node_id}"

        # Fach / Discipline
        elif ll.startswith("fach:") or ll.startswith("discipline:") or ll.startswith("- **fach") or ll.startswith("- **discipline"):
            current["disciplines"] = [d.strip() for d in _val(line).split(",")]

        # Bildungsstufe / Educational level
        elif ll.startswith("bildungsstufe:") or ll.startswith("educational") or ll.startswith("- **bildungsstufe") or ll.startswith("- **educational"):
            current["educational_contexts"] = [e.strip() for e in _val(line).split(",")]

        # Ressourcentyp / Type
        elif ll.startswith("ressourcentyp:") or ll.startswith("typ:") or ll.startswith("- **typ") or ll.startswith("- **lernressourcentyp") or ll.startswith("- **ressourcentyp"):
            val = _val(line)
            if val and val.lower() != "inhalt":
                types = [t.strip() for t in val.split(",")]
                current["learning_resource_types"] = types
                # Auto-detect collection from resource type
                if any(t.lower() in ("sammlung", "collection") for t in types):
                    current["node_type"] = "collection"

        # Lizenz / License
        elif ll.startswith("lizenz:") or ll.startswith("license:") or ll.startswith("- **lizenz") or ll.startswith("- **license"):
            current["license"] = _val(line)

        # Schlagworte / Keywords
        elif ll.startswith("schlagwort") or ll.startswith("keywords:") or ll.startswith("- **keywords") or ll.startswith("- **schlagw"):
            current["keywords"] = [k.strip() for k in _val(line).split(",")]

        # Anbieter / Publisher
        elif ll.startswith("anbieter:") or ll.startswith("herausgeber:") or ll.startswith("publisher:") or ll.startswith("- **herausgeber") or ll.startswith("- **publisher"):
            current["publisher"] = _val(line)

        # Themenseite URL (from search_wlo_topic_pages)
        elif ll.startswith("themenseite:") or ll.startswith("themenseiten-url:") or ll.startswith("topic page:") or ll.startswith("topicpageurl:") or ll.startswith("- **themenseite"):
            current["_tp_url"] = _val(line)

        # Sammlung-nodeId (from search_wlo_topic_pages — links variant to collection)
        elif ll.startswith("sammlung-nodeid:") or ll.startswith("sammlung nodeid:"):
            current["_tp_collection_id"] = _val(line)

        # Variante-ID (from search_wlo_topic_pages)
        elif ll.startswith("variante-id:") or ll.startswith("variante id:"):
            current["_tp_variant_id"] = _val(line)

        # Zielgruppe (from search_wlo_topic_pages)
        elif ll.startswith("zielgruppe:"):
            val = _val(line)
            if val and val != "nicht gesetzt":
                current["_tp_target_group"] = val

        # Sammlung / Collection markers
        elif ll.startswith("- **sammlung") or ll.startswith("- **collection") or ll.startswith("sammlung:"):
            current["node_type"] = "collection"

    if current.get("title"):
        cards.append(current)

    # ── Post-process: convert topic-page fields into topic_pages list ──
    # Topic-page results have _tp_* fields. Group variants by collection.
    tp_by_collection: dict[str, list[dict[str, str]]] = {}
    regular_cards = []
    for c in cards:
        if c.get("_tp_url"):
            # This is a topic-page variant, not a regular card.
            # Priority for the collection ID (used as `node_id` so browse /
            # learning_path / remix work exactly like for Sammlungen):
            #   1. explicit `Sammlung-nodeId:` from MCP
            #   2. the regular `nodeId:` on the card (if any)
            #   3. extracted from the URL's `collectionId=<uuid>` or `<uuid>`
            #      path segment — the WLO topic-page URL always carries it.
            coll_id = (
                c.get("_tp_collection_id")
                or c.get("node_id")
                or _extract_collection_id_from_url(c.get("_tp_url", ""))
                or ""
            )
            tg_raw = c.get("_tp_target_group", "")
            label = _tp_label(tg_raw)
            variant = {
                "url": c["_tp_url"],
                "target_group": tg_raw,
                "label": label,
                "variant_id": c.get("_tp_variant_id", ""),
            }
            if coll_id:
                tp_by_collection.setdefault(coll_id, []).append(variant)
            # Also emit as a card so the LLM can reference it.
            # Carry over any additional metadata the parser picked up —
            # search_wlo_topic_pages sometimes ships preview_url / disciplines /
            # educational_contexts / license alongside the variant data.
            card = {
                "node_id": coll_id,
                "title": c.get("title", ""),
                "description": c.get("description", ""),
                "node_type": "collection",
                "topic_pages": [variant],
                "wlo_url": c.get("wlo_url", ""),
                "url": c.get("url", ""),
                "preview_url": c.get("preview_url", ""),
                "disciplines": c.get("disciplines", []),
                "educational_contexts": c.get("educational_contexts", []),
                "keywords": c.get("keywords", []),
                "learning_resource_types": c.get("learning_resource_types", []),
                "license": c.get("license", ""),
                "publisher": c.get("publisher", ""),
            }
            # Deduplicate: only add if not already in regular_cards with same node_id
            if not any(rc.get("node_id") == coll_id and rc.get("node_id") for rc in regular_cards):
                regular_cards.append(card)
            else:
                # Merge variant into existing card
                for rc in regular_cards:
                    if rc.get("node_id") == coll_id:
                        existing_vids = {v.get("variant_id") for v in rc.get("topic_pages", [])}
                        if variant["variant_id"] not in existing_vids:
                            rc.setdefault("topic_pages", []).append(variant)
                        break
        else:
            # Clean up any stray _tp_ keys from regular cards
            for k in list(c.keys()):
                if k.startswith("_tp_"):
                    del c[k]
            regular_cards.append(c)

    return regular_cards


# Target-group label mapping for topic-page variants
_TARGET_GROUP_LABELS = {
    "teacher": "Lehrkräfte",
    "learner": "Lernende",
    "general": "Allgemein",
}


# ── Discipline label cache ──────────────────────────────────────────
#
# The WLO MCP server resolves school-discipline taxon URIs to labels
# (e.g. "Mathematik"), but for Hochschulfaecher (vocab:
# hochschulfaechersystematik) it returns raw URIs. We lazily fetch the
# full discipline vocabulary once via lookup_wlo_vocabulary and build
# a URI→label map that post_process_discipline_labels() applies to
# card.disciplines lists in place.
_discipline_uri_to_label: dict[str, str] = {}
_discipline_cache_loaded: bool = False


# Fallback slug labels for well-known WLO vocabulary paths, used when
# the vocabulary lookup hasn't populated the cache yet (first request)
# or when a specific URI isn't covered.
_VOCAB_PATH_LABELS = {
    "hochschulfaechersystematik": "Hochschulfach",
    "discipline": "Fach",
    "educationalContext": "Bildungsstufe",
    "learningResourceType": "Ressourcentyp",
}


def _pretty_uri_label(uri: str) -> str:
    """Turn a taxon URI into a readable fallback label.

    ``http://w3id.org/openeduhub/vocabs/hochschulfaechersystematik/n4``
    → ``"Hochschulfach (n4)"``.  Leaves plain labels unchanged.
    """
    if not uri or not uri.startswith(("http://", "https://")):
        return uri
    # Strip query/fragment and trailing slashes
    raw = uri.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    parts = [p for p in raw.split("/") if p]
    if len(parts) < 2:
        return uri
    slug = parts[-1]
    vocab = parts[-2]
    pretty_vocab = _VOCAB_PATH_LABELS.get(vocab, vocab.replace("-", " ").title())
    return f"{pretty_vocab} ({slug})"


async def _ensure_discipline_cache() -> None:
    """Populate the URI→label cache for card display (discipline vocab).

    Piggybacks on ``_ensure_label_cache('discipline')`` and inverts its
    label→URI mapping to produce a URI→label map that card post-processing
    uses to replace raw discipline URIs with human-readable labels.
    """
    global _discipline_cache_loaded
    if _discipline_cache_loaded:
        return
    await _ensure_label_cache("discipline")
    # Invert label→URI map. When multiple labels/aliases point to the same
    # URI, prefer the one that looks like a proper noun (first word capital).
    seen: dict[str, str] = {}
    for label_or_alias, uri in _label_to_uri_cache.get("discipline", {}).items():
        existing = seen.get(uri)
        candidate = label_or_alias
        if not existing:
            seen[uri] = candidate
        else:
            # Prefer shorter / capitalized labels (typically the primary prefLabel)
            if (len(candidate) < len(existing)) or (candidate and candidate[0].isupper() and not existing[0].isupper()):
                seen[uri] = candidate
    for uri, label in seen.items():
        _discipline_uri_to_label.setdefault(uri, label.capitalize() if label else label)
    logger.info(
        "discipline URI→label cache loaded: %d entries",
        len(_discipline_uri_to_label),
    )
    _discipline_cache_loaded = True


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
        else:
            logger.info("no URI for %s=%r (vocab=%s); passing label through", key, val, vocab)
    return out


async def resolve_discipline_labels(cards: list[dict]) -> list[dict]:
    """Replace URI entries in each card's ``disciplines`` list with human labels.

    Uses the lazy vocabulary cache when populated; falls back to the
    slug-pretty-printer so raw URIs never reach the UI.
    """
    if not cards:
        return cards

    # Check if any card actually contains URI disciplines; only then load cache.
    any_uri = any(
        isinstance(c.get("disciplines"), list)
        and any(d.startswith(("http://", "https://")) for d in c["disciplines"])
        for c in cards
    )
    if any_uri:
        await _ensure_discipline_cache()

    for card in cards:
        raw = card.get("disciplines") or []
        if not raw:
            continue
        resolved: list[str] = []
        for d in raw:
            if not isinstance(d, str):
                continue
            if d.startswith(("http://", "https://")):
                label = _discipline_uri_to_label.get(d) or _pretty_uri_label(d)
                resolved.append(label)
            else:
                resolved.append(d)
        card["disciplines"] = resolved
    return cards


def _tp_label(target_group: str) -> str:
    """Human-readable label for a topic-page target group."""
    if not target_group:
        return "Themenseite"
    return _TARGET_GROUP_LABELS.get(target_group.lower(), target_group.title())


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
