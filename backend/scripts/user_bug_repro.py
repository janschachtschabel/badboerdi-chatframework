"""Reproduziere die User-Tests aus dem Live-Widget — beide Modi durchspielen.

Test A — Widget-Demo (Lotsen aus, Kacheln+Canvas an, cards-enabled=true)
Test B — Inline-Widget (Lotsen an, Kacheln+Canvas aus, cards-enabled=false)

Pro Turn loggen:
  - pattern, intent, state, persona, llm_hint, llm_match
  - cards_total + node_type-Verteilung + content_types
  - entities + signals + turn_type
  - response_text (full, NICHT abgeschnitten — wir wollen die Inline-Links sehen)
  - quick_replies

Diagnose-Print: speziell für die User-Bugs:
  - T3 nur-Videos: Sammlungen drin? Content-Types?
  - T4 Topic-Switch: entities reset? alter Slot weg?
  - Inline-Modus: Links im Text?
"""
import asyncio
import json
import re
import uuid

import httpx

CHAT_URL = "http://localhost:8000/api/chat"

TURNS = [
    "Ich suche etwas zu einem Thema.",
    "Bruchrechnung",
    "nur Videos anzeigen",
    "anderes Thema",
]


def _split(s: str) -> str:
    """`"INT-W-03 (Inhalte abrufen)"` → `"INT-W-03"`."""
    if not s: return ""
    return s.split(" ")[0]


def _count_nodes(cards):
    nt = {"collection": 0, "content": 0, "topic_page": 0, "other": 0}
    for c in cards or []:
        t = (c.get("node_type") or "").lower() if isinstance(c, dict) else ""
        nt[t if t in nt else "other"] += 1
    return nt


def _content_types(cards):
    out = set()
    for c in cards or []:
        if not isinstance(c, dict): continue
        if c.get("node_type") != "content": continue
        for t in (c.get("learning_resource_types") or []):
            if isinstance(t, str):
                out.add(t.lower())
    return sorted(out)


def _count_markdown_links(text: str) -> int:
    """Zähle [Label](URL)-Markdown-Links im Bot-Text."""
    if not text: return 0
    return len(re.findall(r"\[[^\]]+\]\(https?://[^\)]+\)", text))


async def run_test(name: str, environment: dict, cards_enabled: bool) -> list[dict]:
    sid = f"bugrepro-{uuid.uuid4().hex[:8]}"
    print(f"\n{'═' * 100}")
    print(f"TEST {name}  (session_id={sid})")
    print(f"  environment={environment}, cards_enabled={cards_enabled}")
    print(f"{'═' * 100}")

    results = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i, msg in enumerate(TURNS, 1):
            print(f"\n── Turn {i}: ⌨️ \"{msg}\" ──")
            payload = {
                "session_id": sid,
                "message": msg,
                "environment": environment,
            }
            r = await client.post(CHAT_URL, json=payload)
            resp = r.json()

            dbg = resp.get("debug", {}) or {}
            cards = resp.get("cards", []) or []
            qrs = resp.get("quick_replies", []) or []
            content = (resp.get("content") or "").strip()

            persona = _split(dbg.get("persona", ""))
            intent = _split(dbg.get("intent", ""))
            pattern = _split(dbg.get("pattern", ""))
            state = _split(dbg.get("state", ""))
            tt = dbg.get("turn_type", "")
            llm_hint = dbg.get("pattern_id_hint") or "—"
            llm_match = dbg.get("llm_engine_match")
            tools = [t for t in (dbg.get("tools_called") or [])]
            signals = dbg.get("signals", []) or []
            entities = dbg.get("entities", {}) or {}
            ent_pub = {k: v for k, v in entities.items() if not str(k).startswith("_")}
            nt_dist = _count_nodes(cards)
            ctypes = _content_types(cards)
            md_links = _count_markdown_links(content)

            print(f"  persona={persona:8s}  intent={intent:10s}  pattern={pattern:8s}  state={state}")
            print(f"  llm_hint={llm_hint:8s}  match={llm_match}  turn_type={tt}")
            print(f"  signals={signals[:4]}")
            print(f"  entities={ent_pub}")
            print(f"  tools={tools[:5]}")
            print(f"  cards={len(cards)}: col={nt_dist['collection']} content={nt_dist['content']} topic={nt_dist['topic_page']} other={nt_dist['other']}")
            if ctypes:
                print(f"  content_types={ctypes[:6]}")
            print(f"  md_links_in_text={md_links}")
            print(f"  qrs={qrs[:4]}")
            print(f"  content[0:240]=\"{content[:240].replace(chr(10), ' / ')}\"")

            results.append({
                "turn": i, "user": msg,
                "pattern": pattern, "intent": intent, "state": state, "persona": persona,
                "llm_hint": llm_hint, "llm_match": llm_match, "turn_type": tt,
                "signals": signals, "entities": ent_pub, "tools": tools,
                "cards_total": len(cards), "node_dist": nt_dist, "content_types": ctypes,
                "md_links": md_links,
                "qrs": qrs, "content": content,
            })
    return results


def diagnose(label: str, res: list[dict], cards_enabled: bool):
    print(f"\n► Diagnose {label}:")
    if len(res) < 4: return
    t1, t2, t3, t4 = res

    # T1: Slot-Erfassung
    print(f"  T1 \"Ich suche etwas\":  pattern={t1['pattern']:6s} cards={t1['cards_total']:2d}  "
          f"→ {'✓' if t1['cards_total'] == 0 else '⚠'} keine Cards bei vagem Anliegen")

    # T2: Thema genannt
    print(f"  T2 \"Bruchrechnung\":     pattern={t2['pattern']:6s} cards={t2['cards_total']:2d} "
          f"(col={t2['node_dist']['collection']}/cont={t2['node_dist']['content']}/topic={t2['node_dist']['topic_page']})  "
          f"llm_hint={t2['llm_hint']} → ent={t2['entities']}")

    # T3: nur Videos
    leaks = t3['node_dist']['collection'] + t3['node_dist']['topic_page']
    nonvideo_types = [t for t in t3['content_types'] if 'video' not in t]
    print(f"  T3 \"nur Videos\":        pattern={t3['pattern']:6s} cards={t3['cards_total']:2d} "
          f"(col={t3['node_dist']['collection']}/cont={t3['node_dist']['content']}/topic={t3['node_dist']['topic_page']})  "
          f"llm_hint={t3['llm_hint']} medientyp={t3['entities'].get('medientyp')}")
    if leaks > 0:
        print(f"     ⚠ FILTER-LECK: {t3['node_dist']['collection']} Sammlungen + {t3['node_dist']['topic_page']} Themenseiten im Output")
    else:
        print(f"     ✓ Sammlungen+Themenseiten weg")
    if nonvideo_types:
        print(f"     ⚠ Nicht-Video-Typen in content_types: {nonvideo_types}")
    else:
        print(f"     ✓ content_types nur Video oder leer: {t3['content_types']}")

    # Inline-Mode: erwarte Inline-Links im Text
    if not cards_enabled:
        if t2['md_links'] == 0 and t2['cards_total'] > 0:
            print(f"     ⚠ T2 Inline-Mode: {t2['cards_total']} Cards aber 0 Markdown-Links im Text!")
        elif t2['md_links'] > 0:
            print(f"     ✓ T2 Inline-Mode: {t2['md_links']} Markdown-Links im Text")
        if t3['md_links'] == 0 and t3['cards_total'] > 0:
            print(f"     ⚠ T3 Inline-Mode: {t3['cards_total']} Cards aber 0 Markdown-Links im Text!")
        elif t3['md_links'] > 0:
            print(f"     ✓ T3 Inline-Mode: {t3['md_links']} Markdown-Links im Text")

    # T4: anderes Thema ohne neues Thema
    t4_text_lower = t4['content'].lower()
    has_old_topic = "bruchrechnung" in t4_text_lower or "bruchrechnung" in str(t4['entities']).lower()
    print(f"  T4 \"anderes Thema\":     pattern={t4['pattern']:6s} cards={t4['cards_total']:2d} "
          f"turn_type={t4['turn_type']} llm_hint={t4['llm_hint']} → ent={t4['entities']}")
    print(f"     {'⚠' if has_old_topic else '✓'} Altes Thema 'Bruchrechnung' im Folge-Output: {has_old_topic}")
    if t4['pattern'] in ("PAT-02",):
        print(f"     ✓ PAT-02 (Klärung) — perfekt für 'anderes Thema' ohne neues Thema")
    elif t4['cards_total'] > 0:
        print(f"     ⚠ T4 hat {t4['cards_total']} Cards — bei 'anderes Thema' OHNE neues Thema sollten 0 Cards kommen")


async def main():
    # Test A: Widget-Demo Modus
    env_a = {
        "guide_mode": False, "host": "",
        "cards_enabled": True, "canvas_enabled": True,
        "quick_replies_enabled": True, }
    res_a = await run_test("A — Widget-Demo (Lotsen AUS, Kacheln+Canvas AN)", env_a, cards_enabled=True)

    # Test B: Inline-Widget Modus
    env_b = {
        "guide_mode": True, "host": "wirlernenonline.de",
        "cards_enabled": False, "canvas_enabled": False,
        "quick_replies_enabled": True, }
    res_b = await run_test("B — Inline-Widget (Lotsen AN, Kacheln+Canvas AUS)", env_b, cards_enabled=False)

    print("\n" + "═" * 100)
    print("DIAGNOSE")
    print("═" * 100)
    diagnose("A (Widget-Demo)", res_a, cards_enabled=True)
    diagnose("B (Inline-Widget)", res_b, cards_enabled=False)

    with open("user_bug_repro_results.json", "w", encoding="utf-8") as f:
        json.dump({"test_a": res_a, "test_b": res_b}, f, ensure_ascii=False, indent=2)
    print(f"\n📄 Volle Daten in: user_bug_repro_results.json")


if __name__ == "__main__":
    asyncio.run(main())
