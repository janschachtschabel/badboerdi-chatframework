"""Multi-Session-Simulation: Filter-Verfeinerungs-Bug & Topic-Switch-Verhalten.

Welle C Sprint 6 Hotfix-Verifikation. Spielt 3 Sessions mit jeweils
4 Turns durch:

    Turn 1: "Ich suche etwas zu einem Thema."          (Slot-Erfassung erwartet)
    Turn 2: "<Thema>"                                  (Mix Cards erwartet)
    Turn 3: "nur videos"                               (nur Video-Cards erwartet)
    Turn 4: "<anderes Thema>"                          (Topic-Switch)

Themen: Bruchrechnung, Photosynthese, Klimawandel.

Loggt pro Turn:
  - intent (Engine)
  - llm_pattern_hint
  - pattern (Engine-Winner)
  - state
  - tools_called
  - turn_type
  - signals
  - entities (medientyp / thema / fach)
  - cards_kind_distribution (collection / content / topic_page)
  - response_preview (erste 200 Zeichen)

Druckt am Ende eine kompakte Tabelle + Bug-Diagnose.

Run:  python scripts/multi_session_filter_test.py
"""
from __future__ import annotations

import asyncio
import json
import uuid
import sys

import httpx

CHAT_URL = "http://localhost:8000/api/chat"

# 3 Sessions mit denselben Turn-Patterns, anderen Themen.
SESSIONS = [
    {
        "name": "Bruchrechnung",
        "turns": [
            "Ich suche etwas zu einem Thema.",
            "Bruchrechnung",
            "nur videos",
            "Photosynthese",  # Topic-Switch
        ],
    },
    {
        "name": "Klimawandel",
        "turns": [
            "Ich suche etwas zu einem Thema.",
            "Klimawandel",
            "nur videos",
            "Goethe Faust",  # Topic-Switch
        ],
    },
    {
        "name": "Photosynthese",
        "turns": [
            "Ich suche etwas zu einem Thema.",
            "Photosynthese",
            "nur videos",
            "Französische Revolution",  # Topic-Switch
        ],
    },
]


def _split_label(s: str) -> tuple[str, str]:
    """`"INT-W-03 (Inhalte abrufen)"` → `("INT-W-03", "Inhalte abrufen")`."""
    if not s:
        return "", ""
    if " (" in s and s.endswith(")"):
        i = s.index(" (")
        return s[:i], s[i + 2:-1]
    return s, ""


def _cards_kind_distribution(cards: list[dict]) -> dict[str, int]:
    dist = {"collection": 0, "content": 0, "topic_page": 0, "other": 0}
    for c in cards or []:
        nt = (c.get("node_type") or "").lower() if isinstance(c, dict) else ""
        if nt in dist:
            dist[nt] += 1
        else:
            dist["other"] += 1
    return dist


def _content_types_in_cards(cards: list[dict]) -> set[str]:
    """Welche `learning_resource_types` kommen in den Content-Cards vor?"""
    types: set[str] = set()
    for c in cards or []:
        if not isinstance(c, dict):
            continue
        if c.get("node_type") != "content":
            continue
        lrt = c.get("learning_resource_types") or []
        for t in lrt:
            if isinstance(t, str):
                types.add(t.lower())
    return types


async def run_session(session: dict, idx: int) -> list[dict]:
    sid = f"multitest-{uuid.uuid4().hex[:10]}"
    results: list[dict] = []
    print(f"\n{'═' * 90}")
    print(f"SESSION {idx + 1}: {session['name']}  (session_id={sid})")
    print(f"{'═' * 90}")

    async with httpx.AsyncClient(timeout=90.0) as client:
        for turn_idx, user_msg in enumerate(session["turns"], 1):
            print(f"\n--- Turn {turn_idx}: ⌨️ \"{user_msg}\" ---")
            try:
                r = await client.post(CHAT_URL, json={
                    "session_id": sid,
                    "message": user_msg,
                })
                r.raise_for_status()
                resp = r.json()
            except Exception as e:
                print(f"  ERROR: {e}")
                results.append({"turn": turn_idx, "error": str(e)})
                continue

            dbg = resp.get("debug", {}) or {}
            cards = resp.get("cards", []) or []
            qrs = resp.get("quick_replies", []) or []
            content = (resp.get("content") or "").strip()

            intent_id, intent_label = _split_label(dbg.get("intent", ""))
            pattern_id, _ = _split_label(dbg.get("pattern", ""))
            state_id, _ = _split_label(dbg.get("state", ""))
            persona_id, _ = _split_label(dbg.get("persona", ""))

            llm_hint = dbg.get("pattern_id_hint") or ""
            llm_match = dbg.get("llm_engine_match")
            tools = dbg.get("tools_called", []) or []
            signals = dbg.get("signals", []) or []
            entities = dbg.get("entities", {}) or {}
            entities_pub = {k: v for k, v in entities.items() if not str(k).startswith("_")}

            cards_dist = _cards_kind_distribution(cards)
            content_types = _content_types_in_cards(cards)

            # Print formatted
            print(f"  persona={persona_id:8s}  intent={intent_id:10s}  pattern={pattern_id:8s}  state={state_id}")
            print(f"  llm_hint={llm_hint or '—':8s}  match={llm_match}  turn_type={dbg.get('turn_type', '—')}")
            print(f"  signals={signals[:4]}")
            print(f"  entities={entities_pub}")
            print(f"  tools={tools[:4]}")
            print(f"  cards={len(cards)}: collection={cards_dist['collection']} "
                  f"content={cards_dist['content']} topic_page={cards_dist['topic_page']} other={cards_dist['other']}")
            if content_types:
                print(f"  content_types={sorted(content_types)[:5]}")
            print(f"  qrs={qrs[:4]}")
            print(f"  content_preview=\"{content[:180].replace(chr(10), ' ')}{'…' if len(content) > 180 else ''}\"")

            results.append({
                "turn": turn_idx,
                "user_msg": user_msg,
                "persona": persona_id,
                "intent": intent_id,
                "pattern": pattern_id,
                "state": state_id,
                "llm_hint": llm_hint,
                "llm_match": llm_match,
                "turn_type": dbg.get("turn_type"),
                "signals": signals,
                "entities": entities_pub,
                "tools": tools,
                "cards_total": len(cards),
                "cards_dist": cards_dist,
                "content_types": sorted(content_types),
                "qrs": qrs,
                "content_preview": content[:200],
            })

    return results


def diagnose(all_results: list[list[dict]]) -> None:
    print("\n" + "═" * 90)
    print("DIAGNOSE — Bug-Check pro Session")
    print("═" * 90)

    for idx, session_results in enumerate(all_results):
        if not session_results:
            continue
        topic = SESSIONS[idx]["name"]
        print(f"\n● Session {idx + 1} ({topic}):")

        # Turn 1: kein Thema → Slot-Erfassung erwartet (PAT-02 oder PAT-20)
        t1 = session_results[0] if len(session_results) > 0 else {}
        t1_pat = t1.get("pattern", "")
        t1_cards = t1.get("cards_total", 0)
        if t1_pat in {"PAT-02", "PAT-20"}:
            print(f"  ✓ T1 Slot-Erfassung: pattern={t1_pat} (gut)")
        else:
            print(f"  ⚠ T1 erwartete PAT-02/20, bekommen: {t1_pat}")
        if t1_cards > 0:
            print(f"  ⚠ T1 hat {t1_cards} Cards, sollte 0 sein (noch kein Thema!)")
        else:
            print(f"  ✓ T1 keine Cards (richtig, da Thema fehlt)")

        # Turn 2: Thema genannt → Mix erwartet
        t2 = session_results[1] if len(session_results) > 1 else {}
        t2_dist = t2.get("cards_dist", {})
        t2_total = t2.get("cards_total", 0)
        if t2_total >= 3:
            print(f"  ✓ T2 Mix-Antwort: {t2_total} Cards "
                  f"(col={t2_dist.get('collection', 0)} content={t2_dist.get('content', 0)} topic={t2_dist.get('topic_page', 0)})")
        else:
            print(f"  ⚠ T2 zu wenige Cards: {t2_total}")

        # Turn 3: "nur videos" → NUR content-cards mit medientyp=video
        t3 = session_results[2] if len(session_results) > 2 else {}
        t3_dist = t3.get("cards_dist", {})
        t3_types = set(t3.get("content_types", []))
        t3_collections = t3_dist.get("collection", 0)
        t3_topics = t3_dist.get("topic_page", 0)
        if t3_collections == 0 and t3_topics == 0:
            print(f"  ✓ T3 Filter sauber: keine Sammlungen, keine Themenseiten")
        else:
            print(f"  ⚠ T3 FILTER-LECK: {t3_collections} Sammlungen + {t3_topics} Themenseiten trotz 'nur videos' "
                  f"(pattern={t3.get('pattern')}, entities={t3.get('entities')})")
        if "video" in {t.lower() for t in t3_types}:
            print(f"  ✓ T3 content-types enthalten 'video': {t3_types}")
        else:
            print(f"  ⚠ T3 content-types ohne 'video': {t3_types}")
        print(f"     T3 pattern={t3.get('pattern')}, state={t3.get('state')}, intent={t3.get('intent')}, "
              f"llm_hint={t3.get('llm_hint') or '—'}")

        # Turn 4: Topic-Switch
        t4 = session_results[3] if len(session_results) > 3 else {}
        t4_turn_type = (t4.get("turn_type") or "").lower()
        t4_entities = t4.get("entities", {})
        t4_thema = (t4_entities.get("thema") or "").lower()
        t4_pat = t4.get("pattern", "")
        new_topic = SESSIONS[idx]["turns"][3].split()[0].lower()
        if t4_turn_type == "topic_switch":
            print(f"  ✓ T4 turn_type=topic_switch erkannt")
        else:
            print(f"  ⚠ T4 turn_type={t4_turn_type or '—'} (erwartet topic_switch)")
        if new_topic in t4_thema or new_topic in (t4_entities.get("fach") or "").lower():
            print(f"  ✓ T4 neues Thema in entities: {t4_entities}")
        else:
            print(f"  ⚠ T4 entities haben das neue Thema NICHT übernommen: {t4_entities}")


async def main():
    all_results: list[list[dict]] = []
    for i, session in enumerate(SESSIONS):
        res = await run_session(session, i)
        all_results.append(res)

    diagnose(all_results)

    # JSON dump
    out_path = "multi_session_filter_test_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            [{"name": SESSIONS[i]["name"], "turns": all_results[i]} for i in range(len(SESSIONS))],
            f, ensure_ascii=False, indent=2,
        )
    print(f"\n📄 Volle Daten in: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
