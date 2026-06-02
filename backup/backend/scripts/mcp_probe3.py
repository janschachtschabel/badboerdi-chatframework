"""Investigate where school- vs. university-discipline mappings live.

Goal: verify whether lookup_wlo_vocabulary(vocabulary='discipline') on the
upstream WLO MCP server returns Hochschulfächer alongside Schulfächer, or
whether Hochschulfächer need a separate vocabulary lookup.

Also checks the RAW URIs that search results emit for each.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter
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
        "clientInfo": {"name": "mcp-probe3", "version": "1.0"},
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


async def main():
    await _handshake()

    print("=" * 72)
    print("1) Which vocabularies does lookup_wlo_vocabulary accept?")
    print("=" * 72)
    # tools/list first — check the enum on 'vocabulary'
    r = await _rpc("tools/list")
    tools = (r.get("result") or {}).get("tools", [])
    for t in tools:
        if t.get("name") == "lookup_wlo_vocabulary":
            schema = t.get("inputSchema") or {}
            print(json.dumps(schema, indent=2, ensure_ascii=False)[:2000])
            break

    print("\n" + "=" * 72)
    print("2) discipline vocab — does it include Hochschulfaecher?")
    print("=" * 72)
    r = await _rpc("tools/call", {"name": "lookup_wlo_vocabulary",
                                   "arguments": {"vocabulary": "discipline"}})
    txt = _result_text(r)
    print(f"  chars: {len(txt)}")
    # Count URI path prefixes
    uris = re.findall(r"URI:\s*(https?://\S+)", txt)
    path_counter = Counter()
    for u in uris:
        # path segment right before the slug
        parts = [p for p in u.rstrip("/").split("/") if p]
        if len(parts) >= 2:
            vocab_path = parts[-2]
            path_counter[vocab_path] += 1
    print(f"  total URIs: {len(uris)}")
    print(f"  vocab paths seen: {dict(path_counter)}")
    # Show sample entries from each vocab path
    for vocab_path in path_counter:
        print(f"\n  --- sample entries from .../{vocab_path}/... ---")
        count = 0
        for line in txt.split("\n"):
            if f"/{vocab_path}/" in line:
                # grab surrounding label
                count += 1
                if count <= 3:
                    print(f"    {line.strip()}")
        print(f"    (total: {count} URIs)")

    print("\n" + "=" * 72)
    print("3) Try lookup_wlo_vocabulary(vocabulary='hochschulfaechersystematik')")
    print("=" * 72)
    r = await _rpc("tools/call", {"name": "lookup_wlo_vocabulary",
                                   "arguments": {"vocabulary": "hochschulfaechersystematik"}})
    txt = _result_text(r)
    print(f"  chars: {len(txt)}")
    print(f"  first 500 chars:\n{txt[:500]}")

    print("\n" + "=" * 72)
    print("4) Try some other likely names")
    print("=" * 72)
    for alt in ["hochschulfach", "hochschulfaecher", "higher_education_subject",
                "university_discipline"]:
        r = await _rpc("tools/call", {"name": "lookup_wlo_vocabulary",
                                       "arguments": {"vocabulary": alt}})
        txt = _result_text(r)
        print(f"  {alt!r} → {len(txt)} chars; head: {txt[:150].replace(chr(10), ' | ')}")

    print("\n" + "=" * 72)
    print("5) Does a search_wlo_content hit return Hochschulfach URIs?")
    print("=" * 72)
    r = await _rpc("tools/call", {"name": "search_wlo_content",
                                   "arguments": {
                                       "query": "Quantenmechanik",
                                       "educationalContext": "Hochschule",
                                       "maxResults": 3,
                                   }})
    txt = _result_text(r)
    # Look for discipline lines
    faecher = re.findall(r"Fach(?:er)?:\s*([^\n]+)", txt)
    for f in faecher[:6]:
        print(f"    Fach: {f}")


if __name__ == "__main__":
    asyncio.run(main())
