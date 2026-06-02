"""Live end-to-end walkthrough of the Webseiten-Tour against a running backend.

Hits http://127.0.0.1:8000/api/chat with the tour signals and asserts the
state machine advances correctly. The tour bypasses the LLM, so this needs
no API key and is fully deterministic. stdlib only.

    python scripts/test_tour_live.py
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"


def post(session_id, message, tour_action=None, page="/"):
    env = {"page": page, "host": "wp-test.wirlernenonline.de"}
    if tour_action:
        env["tour_action"] = tour_action
    body = {"session_id": session_id, "message": message, "environment": env}
    req = urllib.request.Request(
        f"{BASE}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def navs(resp):
    return [q for q in resp.get("quick_replies", []) if q.startswith("__guide__|")]


def plains(resp):
    return [q for q in resp.get("quick_replies", []) if not q.startswith("__guide__|")]


def step(resp):
    return (resp.get("tour") or {}).get("step")


def active(resp):
    return (resp.get("tour") or {}).get("active")


def main():
    sid = "tour-curl-001"
    ok = 0

    # 1. Start (on "/", not /home → intro)
    r = post(sid, "Web-Tour starten", tour_action="start", page="/")
    assert step(r) == "intro" and active(r) is True, r.get("tour")
    assert any("/home/" in q for q in navs(r)), navs(r)
    assert "Rundtour" in r["content"] or "Tour" in r["content"]
    print(f"1. start          → step={step(r)} active={active(r)} navs={len(navs(r))}  OK"); ok += 1

    # 2. Arrival /home/ → group (8 plain QRs, no nav)
    r = post(sid, "[tick]", tour_action="tick", page="/home/")
    assert step(r) == "group", r.get("tour")
    assert len(plains(r)) == 8 and len(navs(r)) == 0, (plains(r), navs(r))
    print(f"2. tick /home/    → step={step(r)} plainQRs={len(plains(r))}  OK"); ok += 1

    # 3. Group reply "Redaktionen" → group_page (nav to /home/redaktionen/)
    r = post(sid, "Redaktionen", page="/home/")
    assert step(r) == "group_page", r.get("tour")
    assert any("/home/redaktionen/" in q for q in navs(r)), navs(r)
    print(f"3. reply Redaktionen → step={step(r)} nav={navs(r)[0][-45:]}  OK"); ok += 1

    # 4. Arrival group page → content (nav to /bildungsinhalte/)
    r = post(sid, "[tick]", tour_action="tick", page="/home/redaktionen/")
    assert step(r) == "content", r.get("tour")
    assert any("/bildungsinhalte/" in q for q in navs(r)), navs(r)
    print(f"4. tick group pg  → step={step(r)} nav→bildungsinhalte  OK"); ok += 1

    # 5. Arrival /bildungsinhalte/ → solutions (angebote links + nav /mitmachen/)
    r = post(sid, "[tick]", tour_action="tick", page="/bildungsinhalte/")
    assert step(r) == "solutions", r.get("tour")
    assert any("/mitmachen/" in q for q in navs(r)), navs(r)
    assert "wlo-redaktionssoftware" in r["content"], "group angebote links missing"
    assert "fachportale" in r["content"].lower(), "content sublinks missing"
    print(f"5. tick bildungs. → step={step(r)} angebote+sublinks inline  OK"); ok += 1

    # 6. Arrival /mitmachen/ → contact (final, tour inactive)
    r = post(sid, "[tick]", tour_action="tick", page="/mitmachen/")
    assert step(r) == "contact" and active(r) is False, r.get("tour")
    assert r.get("quick_replies", []) == [] or len(navs(r)) == 0
    assert "/mitmachen/faq/" in r["content"]
    print(f"6. tick /mitmachen/ → step={step(r)} active={active(r)} FINAL  OK"); ok += 1

    # 7. Negative: fresh tour, tick to a wrong page → nudge, no advance
    sid2 = "tour-curl-neg-002"
    post(sid2, "Web-Tour starten", tour_action="start", page="/")
    r = post(sid2, "[tick]", tour_action="tick", page="/voellig/woanders/")
    assert step(r) == "intro" and active(r) is True, r.get("tour")
    assert any("/home/" in q for q in navs(r)), "nudge should re-offer current nav"
    print(f"7. tick wrong page → step={step(r)} (no advance) nudge+nav  OK"); ok += 1

    # 8. Stale tick (no active tour) → empty content, tour.active=false
    r = post("tour-never-started-003", "[tick]", tour_action="tick", page="/home/")
    assert active(r) is False and (r.get("content") or "") == "", r.get("tour")
    print(f"8. stale tick     → empty content, active={active(r)}  OK"); ok += 1

    print(f"\nALL {ok} LIVE TOUR CHECKS PASSED ✅")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\n❌ ASSERTION FAILED: {e}")
        sys.exit(1)
