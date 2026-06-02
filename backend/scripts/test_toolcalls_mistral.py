"""Tool-Calling-Test für mistral-large-3 (AcademicCloud) — der Make-or-Break-
Check, bevor die App real auf AcademicCloud umgestellt wird.

Der Chatbot lebt von OpenAI-Function-Calling:
  * classify_input        (forced tool_choice = bestimmte Funktion)
  * respond_to_user       (Hauptantwort + Quick-Replies, forced)
  * search_content u.a.   (MCP-Tools, tool_choice="auto")
  * 2-Schritt-Loop        (Tool-Call → tool-result → finale Antwort)

Mistral nutzt auf vLLM einen Spezial-Tokenizer — offen ist, ob Tool-Calls
STRUKTURIERT (message.tool_calls) geparst werden oder als TEXT
([TOOL_CALLS]…) zurückkommen. Genau das prüfen wir, mit gpt-5.4-mini als
Baseline.

Alles STRIKT SERIELL (AcademicCloud: keine parallelen Calls). Key aus
B_API_KEY_STAGING. App-B_API_KEY unangetastet.

Aufruf (aus backend/):  python scripts/test_toolcalls_mistral.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from openai import AsyncOpenAI

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

B_API_BASE = "https://b-api.staging.openeduhub.net/api/v1/llm"
AC_BASE = f"{B_API_BASE}/academiccloud"
OAI_BASE = f"{B_API_BASE}/openai"
KEY_VAR = "B_API_KEY_STAGING"

MISTRAL = "mistral-large-3-675b-instruct-2512"
GPT5 = "gpt-5.4-mini"

SYSTEM = "Du bist Boerdi, ein Lerncoach für WirLernenOnline. Nutze die bereitgestellten Tools."

# ── Tool-Definitionen (nah an den echten App-Tools) ──────────────────
RESPOND_TOOL = {
    "type": "function",
    "function": {
        "name": "respond_to_user",
        "description": "Antworte dem Nutzer und schlage optional kurze Quick-Replies vor.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Die Antwort an den Nutzer."},
                "quick_replies": {
                    "type": "array", "items": {"type": "string"},
                    "description": "0-4 kurze Folgevorschläge.",
                },
            },
            "required": ["text"],
        },
    },
}
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_content",
        "description": "Suche Lernmaterial in der WLO-Datenbank.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Suchbegriff / Thema"},
                "discipline": {"type": "string", "description": "Fach, z.B. Biologie"},
                "educational_context": {"type": "string", "description": "z.B. Sekundarstufe I"},
            },
            "required": ["query"],
        },
    },
}
CLASSIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_input",
        "description": "Klassifiziere die Nutzereingabe in Intent + Persona.",
        "parameters": {
            "type": "object",
            "properties": {
                "intent_id": {"type": "string", "enum": ["I01", "I03", "I05", "I06", "I07"]},
                "persona_id": {"type": "string", "enum": ["P-LEH", "P-LER", "P-ENT", "P-AND"]},
                "intent_confidence": {"type": "number"},
            },
            "required": ["intent_id", "persona_id", "intent_confidence"],
        },
    },
}


def _client(base: str, key: str) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=key or "unused", base_url=base,
                       default_headers={"X-API-KEY": key} if key else None,
                       timeout=90.0, max_retries=1)


def _parse_tool_calls(msg) -> tuple[list[dict], str]:
    """Returns (parsed_calls, problem). parsed_calls = [{name, args, args_ok}].
    problem != '' wenn der Tool-Call als TEXT statt strukturiert kam."""
    calls = []
    tcs = getattr(msg, "tool_calls", None) or []
    for tc in tcs:
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", None) if fn else None
        raw = getattr(fn, "arguments", "") if fn else ""
        try:
            args = json.loads(raw) if raw else {}
            args_ok = True
        except Exception:
            args = {"_raw": raw[:200]}
            args_ok = False
        calls.append({"name": name, "args": args, "args_ok": args_ok, "id": getattr(tc, "id", None)})
    problem = ""
    if not calls:
        content = (getattr(msg, "content", None) or "")
        if "[TOOL_CALLS]" in content or '"name"' in content and '"arguments"' in content:
            problem = f"Tool-Call kam als TEXT statt strukturiert: {content[:160]!r}"
    return calls, problem


async def _chat(client, model, messages, tools, tool_choice):
    kwargs = {"model": model, "messages": messages, "tools": tools}
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    # GPT-5-Familie verbietet ``max_tokens`` (verlangt ``max_completion_tokens``);
    # die App sendet dort bewusst KEIN Token-Limit (Länge via verbosity). Für die
    # AcademicCloud-Direktmodelle (mistral u.a.) setzen wir einen Floor wie im App-Pfad.
    name_l = model.lower()
    if not name_l.startswith(("gpt-5", "o1", "o3", "o4")):
        kwargs["max_tokens"] = 1000
    return await client.chat.completions.create(**kwargs)


def _res(label, ok, detail):
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}  —  {detail}", flush=True)
    return ok


async def run_model(name: str, base: str, key: str) -> dict:
    print(f"\n{'='*78}\n  {name}   ({base})\n{'='*78}")
    c = _client(base, key)
    results = {}

    # 1) AUTO single tool — entscheidet das Modell, das Suchtool zu rufen?
    try:
        r = await _chat(c, name,
                        [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": "Finde mir Material zur Photosynthese für Klasse 8."}],
                        [SEARCH_TOOL], "auto")
        msg = r.choices[0].message
        calls, problem = _parse_tool_calls(msg)
        ok = bool(calls) and calls[0]["name"] == "search_content" and calls[0]["args_ok"] and "query" in calls[0]["args"]
        detail = (problem or f"name={calls[0]['name'] if calls else None}, args={calls[0]['args'] if calls else None}, "
                  f"finish={r.choices[0].finish_reason}")
        results["auto_single"] = _res("1) tool_choice=auto → search_content", ok, detail)
    except Exception as e:
        results["auto_single"] = _res("1) tool_choice=auto → search_content", False, f"{type(e).__name__}: {str(e)[:140]}")

    # 2) FORCED specific tool — classify_input erzwingen
    try:
        r = await _chat(c, name,
                        [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": "Was ist Photosynthese?"}],
                        [CLASSIFY_TOOL],
                        {"type": "function", "function": {"name": "classify_input"}})
        msg = r.choices[0].message
        calls, problem = _parse_tool_calls(msg)
        a = calls[0]["args"] if calls else {}
        ok = (bool(calls) and calls[0]["name"] == "classify_input" and calls[0]["args_ok"]
              and "intent_id" in a and "persona_id" in a)
        detail = problem or f"args={a}"
        results["forced_classify"] = _res("2) forced tool_choice → classify_input", ok, detail)
    except Exception as e:
        results["forced_classify"] = _res("2) forced tool_choice → classify_input", False, f"{type(e).__name__}: {str(e)[:140]}")

    # 3) respond_to_user (forced) — Text + quick_replies
    try:
        r = await _chat(c, name,
                        [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": "Erkläre kurz Photosynthese und gib 2 Quick-Replies."}],
                        [RESPOND_TOOL],
                        {"type": "function", "function": {"name": "respond_to_user"}})
        msg = r.choices[0].message
        calls, problem = _parse_tool_calls(msg)
        a = calls[0]["args"] if calls else {}
        ok = bool(calls) and calls[0]["name"] == "respond_to_user" and calls[0]["args_ok"] and bool(a.get("text"))
        qr = a.get("quick_replies")
        detail = problem or f"text={str(a.get('text'))[:60]!r}, quick_replies={qr}"
        results["respond_tool"] = _res("3) forced → respond_to_user (text+QRs)", ok, detail)
    except Exception as e:
        results["respond_tool"] = _res("3) forced → respond_to_user", False, f"{type(e).__name__}: {str(e)[:140]}")

    # 4) 2-Schritt-Loop: search_content → tool-result → finale Antwort
    try:
        msgs = [{"role": "system", "content": SYSTEM + " Suche zuerst, antworte dann mit respond_to_user."},
                {"role": "user", "content": "Finde Material zur Bruchrechnung und fasse es kurz zusammen."}]
        r1 = await _chat(c, name, msgs, [SEARCH_TOOL, RESPOND_TOOL], "auto")
        m1 = r1.choices[0].message
        calls1, problem1 = _parse_tool_calls(m1)
        step1_ok = bool(calls1) and calls1[0]["name"] == "search_content"
        if not step1_ok:
            results["roundtrip"] = _res("4) 2-Schritt-Loop", False,
                                        problem1 or f"Schritt1 rief nicht search_content: {[c2['name'] for c2 in calls1]}")
        else:
            # Assistant-Tool-Call + tool-result an die History anhängen
            msgs.append({"role": "assistant", "content": m1.content or "",
                         "tool_calls": [{"id": calls1[0]["id"] or "call_1", "type": "function",
                                         "function": {"name": "search_content",
                                                      "arguments": json.dumps(calls1[0]["args"])}}]})
            fake_results = json.dumps({"results": [
                {"title": "Bruchrechnung Grundlagen", "url": "https://x/1"},
                {"title": "Übungsblatt Brüche Klasse 6", "url": "https://x/2"},
            ]}, ensure_ascii=False)
            msgs.append({"role": "tool", "tool_call_id": calls1[0]["id"] or "call_1", "content": fake_results})
            r2 = await _chat(c, name, msgs, [SEARCH_TOOL, RESPOND_TOOL], "auto")
            m2 = r2.choices[0].message
            calls2, problem2 = _parse_tool_calls(m2)
            # Erfolg: entweder respond_to_user ODER sinnvoller finaler Text
            final_text = (m2.content or "").strip()
            used_respond = bool(calls2) and calls2[0]["name"] == "respond_to_user"
            mentions = any(k in (final_text + json.dumps(calls2)).lower() for k in ("bruch", "übung", "material"))
            ok = (used_respond or bool(final_text)) and (mentions or used_respond)
            detail = (problem2 or
                      (f"Schritt2=respond_to_user, text={str((calls2[0]['args'] if calls2 else {}).get('text'))[:60]!r}"
                       if used_respond else f"Schritt2=Text: {final_text[:80]!r}"))
            results["roundtrip"] = _res("4) 2-Schritt-Loop (search→result→Antwort)", ok, detail)
    except Exception as e:
        results["roundtrip"] = _res("4) 2-Schritt-Loop", False, f"{type(e).__name__}: {str(e)[:140]}")

    await c.close()
    return results


async def main() -> None:
    key = (os.getenv(KEY_VAR) or "").strip()
    if not key:
        print(f"ERROR: {KEY_VAR} nicht gesetzt."); sys.exit(1)
    print("#" * 78)
    print("#  TOOL-CALLING-TEST — mistral-large-3 (AcademicCloud) vs. gpt-5.4-mini")
    print(f"#  key: {key[:6]}***")
    print("#" * 78)

    mistral_res = await run_model(MISTRAL, AC_BASE, key)
    gpt_res = await run_model(GPT5, OAI_BASE, key)

    print(f"\n{'='*78}\n  ZUSAMMENFASSUNG\n{'='*78}")
    tests = ["auto_single", "forced_classify", "respond_tool", "roundtrip"]
    labels = {"auto_single": "auto→search", "forced_classify": "forced→classify",
              "respond_tool": "respond_to_user", "roundtrip": "2-Schritt-Loop"}
    hdr = f"  {'Test':18s} | {'mistral-large-3':>16s} | {'gpt-5.4-mini':>14s}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for t in tests:
        m = "OK" if mistral_res.get(t) else "FAIL"
        g = "OK" if gpt_res.get(t) else "FAIL"
        print(f"  {labels[t]:18s} | {m:>16s} | {g:>14s}")
    mok = sum(1 for t in tests if mistral_res.get(t))
    gok = sum(1 for t in tests if gpt_res.get(t))
    print(f"\n  mistral-large-3: {mok}/4   ·   gpt-5.4-mini: {gok}/4")
    if mok == 4:
        print("  → mistral-large-3 ist tool-calling-tauglich für den Chatbot.")
    elif mok == 0:
        print("  → mistral-large-3 liefert KEINE strukturierten Tool-Calls auf dieser")
        print("    Strecke → Chatbot-Umstieg auf AcademicCloud/mistral NICHT möglich,")
        print("    solange der vLLM-Tool-Parser fehlt.")
    else:
        print("  → mistral-large-3 nur TEILWEISE tool-calling-tauglich — Details oben.")


if __name__ == "__main__":
    asyncio.run(main())
