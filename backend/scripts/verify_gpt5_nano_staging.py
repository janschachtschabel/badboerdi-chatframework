"""Verifiziert gpt-5.4-nano auf der B-API STAGING (/openai-Passthrough),
genau so wie die App ein GPT-5-Modell ruft:
  * tool-loser Call: verbosity + reasoning_effort, KEIN max_tokens
  * Tool-Call: tools + forced tool_choice, verbosity, KEIN reasoning_effort
  * Embeddings: text-embedding-3-small (der Standard-DB-Pfad) über die B-API

Key aus B_API_KEY_STAGING. Aufruf (aus backend/): python scripts/verify_gpt5_nano_staging.py
"""
from __future__ import annotations
import asyncio, json, os, sys
import httpx
from openai import AsyncOpenAI

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OAI = "https://b-api.staging.openeduhub.net/api/v1/llm/openai"
MODEL = "gpt-5.4-nano"
EMBED = "text-embedding-3-small"
KEY = (os.getenv("B_API_KEY_STAGING") or "").strip()

RESPOND_TOOL = {
    "type": "function",
    "function": {
        "name": "respond_to_user",
        "description": "Antworte dem Nutzer, optional mit Quick-Replies.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
            "quick_replies": {"type": "array", "items": {"type": "string"}}},
            "required": ["text"]},
    },
}


async def main():
    if not KEY:
        print("ERROR: B_API_KEY_STAGING nicht gesetzt."); sys.exit(1)
    c = AsyncOpenAI(api_key=KEY, base_url=OAI,
                    default_headers={"X-API-KEY": KEY}, timeout=90, max_retries=1)
    print("=" * 72)
    print(f"  Verify gpt-5.4-nano @ {OAI}")
    print("=" * 72)

    # 1) Katalog
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.get(f"{OAI}/models", headers={"X-API-KEY": KEY})
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", [])
        names = [m["id"] if isinstance(m, dict) else str(m) for m in items]
        print(f"  [models] gpt-5.4-nano im Katalog: {MODEL in names}")
        print(f"           gpt-5.4*: {sorted(n for n in names if n.startswith('gpt-5.4'))}")
    except Exception as e:
        print(f"  [models] FEHLER {type(e).__name__}: {str(e)[:120]}")

    # 2) tool-loser GPT-5-Call (verbosity + reasoning_effort, kein max_tokens)
    try:
        r1 = await c.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Antworte in genau einem Satz: Was ist Photosynthese?"}],
            verbosity="medium", reasoning_effort="low")
        txt = (r1.choices[0].message.content or "").strip()
        u = r1.usage
        print(f"  [chat ] {'OK' if txt else 'LEER'}  '{txt[:90]}'  "
              f"(prompt={getattr(u,'prompt_tokens','?')}, completion={getattr(u,'completion_tokens','?')})")
    except Exception as e:
        print(f"  [chat ] FEHLER {type(e).__name__}: {str(e)[:160]}")

    # 3) Tool-Call (respond_to_user, forced) — kein reasoning_effort bei Tools
    try:
        r2 = await c.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": "Nutze respond_to_user."},
                      {"role": "user", "content": "Erkläre kurz Photosynthese und gib 2 Quick-Replies."}],
            tools=[RESPOND_TOOL],
            tool_choice={"type": "function", "function": {"name": "respond_to_user"}},
            verbosity="medium")
        tcs = r2.choices[0].message.tool_calls or []
        if tcs:
            args = json.loads(tcs[0].function.arguments)
            print(f"  [tool ] OK  {tcs[0].function.name}  text='{str(args.get('text'))[:60]}'  "
                  f"qr={args.get('quick_replies')}")
        else:
            print(f"  [tool ] KEINE tool_calls; content='{(r2.choices[0].message.content or '')[:90]}'")
    except Exception as e:
        print(f"  [tool ] FEHLER {type(e).__name__}: {str(e)[:160]}")

    # 4) Embeddings text-embedding-3-small über die B-API (DB-Pfad)
    try:
        re_ = await c.embeddings.create(model=EMBED, input="Photosynthese ist ein biologischer Prozess.")
        dim = len(re_.data[0].embedding)
        print(f"  [embed] {EMBED}: OK, dim={dim} {'(DB-kompatibel)' if dim == 1536 else '(!=1536!)'}")
    except Exception as e:
        print(f"  [embed] FEHLER {type(e).__name__}: {str(e)[:160]}")

    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
