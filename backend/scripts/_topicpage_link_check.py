import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.card_pipeline import build_card_link, normalize_cards
from app.services.mcp_client import parse_wlo_topic_page_cards

REPO = "https://repository.staging.openeduhub.net"
UID = "0b637d52-9747-40b2-a37d-52974720b2b6"

# ── A) build_card_link direkt ────────────────────────────────────────
c1 = {"node_id": UID, "node_type": "topic_page"}
l1 = build_card_link(c1, repo_base=REPO)
print("A1 topic_page (kein tp_url):", l1)
assert l1 == f"{REPO}/edu-sharing/components/topic-pages?collectionId={UID}", l1

tp = f"{REPO}/edu-sharing/components/topic-pages?collectionId=abc-123"
c2 = {"node_id": "ref-999", "node_type": "topic_page", "topic_page_url": tp}
assert build_card_link(c2, repo_base=REPO) == tp

c3 = {"node_id": "col-123", "node_type": "collection"}
l3 = build_card_link(c3, repo_base=REPO)
print("A3 collection:", l3)
assert l3 == f"{REPO}/edu-sharing/components/collections?id=col-123", l3

# ── B) Volle Pipeline: search_wlo_topic_pages-JSON → parse → normalize → link
#      Worst case: MCP liefert KEINE topicPageUrl und KEINE Varianten.
raw = json.dumps({
    "total": 1,
    "results": [{
        "title": "Klimawandel",
        "collectionId": UID,
        "topicPageUrl": "",
        "educationalContexts": ["Sekundarstufe I"],
        "variants": [],
    }],
})
cards = parse_wlo_topic_page_cards(raw)
assert cards and cards[0]["node_type"] == "topic_page", cards
norm = normalize_cards(cards, target_repo_base=REPO)
link = build_card_link(norm[0], repo_base=REPO, search_query="zeige mir alle themenseiten")
wlo = norm[0].get("wlo_url", "")
print("B  pipeline link :", link)
print("B  pipeline wlo  :", wlo)
assert "/components/topic-pages?collectionId=" in link, link
assert "/components/collections" not in link, link
assert "/components/collections" not in wlo, wlo  # auch das Sekundär-Feld

print("\nALLE THEMENSEITEN-LINK-CHECKS OK ✅  (auch Worst-Case → topic-pages, kein collections-Leak)")
