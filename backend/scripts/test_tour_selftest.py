"""Standalone self-test for the Webseiten-Tour state machine.

Pure logic — loads 01-base/website-tour.yaml via config_loader and runs the
tour_service render/advance functions through a full walkthrough. No server,
no API key, no network. Run:

    python -m pytest scripts/test_tour_selftest.py      # or
    python scripts/test_tour_selftest.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.config_loader import load_website_tour_config  # noqa: E402
from app.services import tour_service as t  # noqa: E402


def main() -> int:
    cfg = load_website_tour_config()
    assert cfg.get("enabled") is True, f"tour not enabled / not loaded: {list(cfg)}"
    groups = cfg.get("groups", [])
    assert len(groups) == 7, f"expected 7 groups, got {len(groups)}"
    print(f"[ok] config loaded — enabled={cfg.get('enabled')} groups={len(groups)} "
          f"base_host={cfg.get('base_host')}")

    def show(step, group, kind="normal"):
        r = t.render(step, cfg, group, kind=kind)
        print(f"\n=== step={step} kind={kind} qrs={len(r['quick_replies'])} final={r['final']}")
        print("    " + (r["text"][:160].replace("\n", "\n    ")))
        for q in r["quick_replies"]:
            print("    QR:", q[:90])
        return r

    # Path normalisation
    assert t._norm_path("https://wp-test.wirlernenonline.de/home/redaktionen/?x=1") == "/home/redaktionen"
    assert t._norm_path("/home/") == "/home"
    print("[ok] path normalisation")

    # intro → group
    r = show("intro", "")
    assert any(q.startswith(t.GUIDE_QR_PREFIX) and "/home/" in q for q in r["quick_replies"])
    adv, expl, nxt = t.expected("intro", "", cfg)
    assert adv == "/home" and nxt == "group", (adv, nxt)
    print("[ok] intro nav→/home, advances to group on arrival")

    # group: 7 group QRs + unsure
    r = show("group", "")
    assert len(r["quick_replies"]) == 8, r["quick_replies"]
    assert not any(q.startswith(t.GUIDE_QR_PREFIX) for q in r["quick_replies"]), "group QRs must be plain"
    print("[ok] group shows 8 plain quick-replies (7 groups + unsure)")

    # group matching
    assert (t.match_group("Redaktionen", cfg) or {}).get("id") == "redaktionen"
    assert (t.match_group("ich entwickle software", cfg) or {}).get("id") == "software-hersteller"
    assert (t.match_group("politik", cfg) or {}).get("id") == "politik"
    assert t.match_group("völliger unsinn xyz", cfg) is None
    print("[ok] group matching (label, synonym, miss)")

    # group_page → content
    r = show("group_page", "redaktionen")
    assert any("redaktionen" in q for q in r["quick_replies"])
    adv, _, nxt = t.expected("group_page", "redaktionen", cfg)
    assert adv == "/home/redaktionen" and nxt == "content", (adv, nxt)

    # content → solutions
    r = show("content", "redaktionen")
    assert any("/bildungsinhalte/" in q for q in r["quick_replies"])
    adv, _, nxt = t.expected("content", "redaktionen", cfg)
    assert adv == "/bildungsinhalte" and nxt == "solutions", (adv, nxt)

    # solutions → contact (+ explore targets)
    r = show("solutions", "redaktionen")
    assert any("/mitmachen/" in q for q in r["quick_replies"])
    assert "wlo-redaktionssoftware" in r["text"], "group angebote must appear as links"
    assert "fachportale" in r["text"].lower(), "content sublinks must appear"
    adv, expl, nxt = t.expected("solutions", "redaktionen", cfg)
    assert adv == "/mitmachen" and nxt == "contact"
    assert "/angebote/wlo-redaktionssoftware" in expl
    assert "/fachportale" in expl
    print(f"[ok] solutions: explore targets = {len(expl)} (angebote + sublinks)")

    # contact (final)
    r = show("contact", "redaktionen")
    assert r["final"] is True and r["quick_replies"] == []
    assert "/mitmachen/faq/" in r["text"]
    print("[ok] contact is final, contact links inline")

    # nudge / explore
    rn = t.render("content", cfg, "redaktionen", kind="nudge")
    assert rn["text"] and any("/bildungsinhalte/" in q for q in rn["quick_replies"])
    re_ = t.render("solutions", cfg, "redaktionen", kind="explore")
    assert re_["text"] and any("/mitmachen/" in q for q in re_["quick_replies"])
    print("[ok] nudge + explore re-offer current step nav")

    print("\nALL TOUR SELFTESTS PASSED ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
