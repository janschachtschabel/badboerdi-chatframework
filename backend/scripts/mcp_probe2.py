"""Verify that the REAL parameter names actually filter."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

MCP_URL = os.getenv("MCP_SERVER_URL", "https://wlo-mcp-server.vercel.app/mcp")

_id = 0
_session: str | None = None


def _next_id() -> int:
    global _id
    _id += 1
    return _id


def _parse(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    last = None
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                try:
                    last = json.loads(data)
                except json.JSONDecodeError:
                    pass
    return last or {}


async def _rpc(method: str, params: dict | None = None, notif: bool = False) -> dict:
    global _session
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if not notif:
        body["id"] = _next_id()
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if _session and method != "initialize":
        headers["Mcp-Session-Id"] = _session
    async with httpx.AsyncClient(timeout=30.0) as cli:
        r = await cli.post(MCP_URL, json=body, headers=headers)
    sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id")
    if sid:
        _session = sid
    if r.status_code not in (200, 202):
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
    if notif or not r.text.strip():
        return {}
    return _parse(r.text)


async def _handshake():
    await _rpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "clientInfo": {"name": "mcp-probe2", "version": "1.0"},
    })
    await _rpc("notifications/initialized", notif=True)


def _result_text(rpc_result: dict) -> str:
    r = rpc_result.get("result") or {}
    parts = r.get("content") or []
    out = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            out.append(p.get("text", ""))
        elif isinstance(p, str):
            out.append(p)
    return "\n".join(out)


def _summarize(text: str) -> tuple[int, list[str]]:
    """Extract total count + list of resource types seen in cards."""
    import re
    m = re.search(r"Gefundene Treffer gesamt:\s*(\d+)", text)
    total = int(m.group(1)) if m else -1
    types = re.findall(r"Ressourcentyp:\s*([^\n]+)", text)
    return total, types


async def main():
    await _handshake()

    tests = [
        ("UNFILTERED baseline",
         {"query": "Bruchrechnung", "maxResults": 5}),

        ("WRONG param resourceType='Arbeitsblatt' (our current bug)",
         {"query": "Bruchrechnung", "resourceType": "Arbeitsblatt", "maxResults": 5}),

        ("CORRECT param learningResourceType='Arbeitsblatt' (label)",
         {"query": "Bruchrechnung", "learningResourceType": "Arbeitsblatt", "maxResults": 5}),

        ("CORRECT learningResourceType=URI of Arbeitsblatt",
         {"query": "Bruchrechnung", "learningResourceType":
          "http://w3id.org/openeduhub/vocabs/new_lrt_aggregated/c8e52242-361b-4a2a-b95d-25e516b28b45",
          "maxResults": 5}),

        ("CORRECT learningResourceType='Video' (label)",
         {"query": "Bruchrechnung", "learningResourceType": "Video", "maxResults": 5}),

        ("CORRECT both filters: learningResourceType=Arbeitsblatt, discipline=Mathematik",
         {"query": "Bruchrechnung", "learningResourceType": "Arbeitsblatt",
          "discipline": "Mathematik", "maxResults": 5}),

        ("CORRECT educationalContext='Sekundarstufe I'",
         {"query": "Bruchrechnung", "educationalContext": "Sekundarstufe I",
          "learningResourceType": "Arbeitsblatt", "maxResults": 5}),

        ("WRONG educationalLevel='Sekundarstufe I' (our current bug)",
         {"query": "Bruchrechnung", "educationalLevel": "Sekundarstufe I",
          "learningResourceType": "Arbeitsblatt", "maxResults": 5}),
    ]

    for name, args in tests:
        r = await _rpc("tools/call", {"name": "search_wlo_content", "arguments": args})
        txt = _result_text(r)
        total, types = _summarize(txt)
        # Count LRT occurrences
        from collections import Counter
        ctr = Counter(t.split(",")[0].strip() for t in types)
        print(f"\n=== {name} ===")
        print(f"  args: {args}")
        print(f"  total={total}  lrt_distribution={dict(ctr)}")


if __name__ == "__main__":
    asyncio.run(main())
