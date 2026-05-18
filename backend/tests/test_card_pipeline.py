"""Smoke-Tests für die Card-Pipeline v2 (Phase 1-3a/3b).

Deckt die Pure-Functions ab — :func:`fetch_card_pool` ist nicht enthalten,
weil sie MCP-Calls erfordert (kommt in einer separaten Integration-Suite
mit ``aioresponses``/``respx`` Mocks).

Die Tests sind so geschrieben, dass sie auch ohne aktive
``CARD_PIPELINE_V2=1``-Env-Variable laufen — sie importieren die Module
direkt und testen die Funktionen isoliert.
"""
from __future__ import annotations

import pytest

from app.services.card_pipeline import (
    annotate_cards_with_link,
    build_card_link,
    infer_intent_kind,
    normalize_cards,
    select_final_cards,
    summarize_pipeline_result,
    validate_card_link,
    _relevance_score,
    _sort_by_relevance,
    _tokenize_query,
)
from app.services.config_loader import (
    card_pipeline_v2_enabled,
    load_card_pipeline_config,
    rewrite_repo_host_v2,
)


PROD = "https://redaktion.openeduhub.net"
STAG = "https://repository.staging.openeduhub.net"


# ══════════════════════════════════════════════════════════════════════════
# infer_intent_kind
# ══════════════════════════════════════════════════════════════════════════

class TestInferIntentKind:
    def test_general_default(self):
        assert infer_intent_kind(user_message="Material zu Photosynthese") == "general"

    def test_type_focus_when_wanted_types(self):
        out = infer_intent_kind(
            user_message="Videos zu Photosynthese",
            wanted_content_types={"video"},
        )
        assert out == "type-focus"

    def test_collection_contents_wins_over_types(self):
        out = infer_intent_kind(
            user_message="Was steht in der Sammlung?",
            wanted_content_types={"video"},
            collection_id="abc-uuid",
        )
        assert out == "collection-contents"

    def test_empty_message_returns_general(self):
        assert infer_intent_kind(user_message="") == "general"


# ══════════════════════════════════════════════════════════════════════════
# rewrite_repo_host_v2  (Phase 7 — bidirektionaler Host-Rewrite)
# ══════════════════════════════════════════════════════════════════════════

class TestRewriteRepoHostV2:
    def test_production_to_staging(self):
        url = f"{PROD}/edu-sharing/components/render/abc"
        out = rewrite_repo_host_v2(url, target_repo_base=STAG)
        assert out == f"{STAG}/edu-sharing/components/render/abc"

    def test_staging_to_production(self):
        url = f"{STAG}/edu-sharing/components/render/abc"
        out = rewrite_repo_host_v2(url, target_repo_base=PROD)
        assert out == f"{PROD}/edu-sharing/components/render/abc"

    def test_external_url_untouched(self):
        url = "https://www.youtube.com/watch?v=xyz"
        assert rewrite_repo_host_v2(url, target_repo_base=STAG) == url

    def test_same_host_no_op(self):
        url = f"{STAG}/foo"
        assert rewrite_repo_host_v2(url, target_repo_base=STAG) == url

    def test_empty_url_safe(self):
        assert rewrite_repo_host_v2("", target_repo_base=PROD) == ""

    def test_none_url_safe(self):
        assert rewrite_repo_host_v2(None, target_repo_base=PROD) is None  # type: ignore[arg-type]


# ══════════════════════════════════════════════════════════════════════════
# load_card_pipeline_config — clamps + defaults
# ══════════════════════════════════════════════════════════════════════════

class TestLoadCardPipelineConfig:
    def test_keys_present(self):
        cfg = load_card_pipeline_config()
        for key in (
            "pool_size", "llm_curation_pool", "final_selection_size",
            "enable_llm_curation", "min_displayed_cards", "known_repo_hosts",
        ):
            assert key in cfg, f"missing config key: {key}"

    def test_clamped_to_safe_ranges(self):
        cfg = load_card_pipeline_config()
        assert 5 <= cfg["pool_size"] <= 50
        assert 1 <= cfg["final_selection_size"] <= 10
        assert cfg["llm_curation_pool"] <= cfg["pool_size"]
        assert cfg["min_displayed_cards"] <= cfg["final_selection_size"]

    def test_known_repo_hosts_includes_known(self):
        cfg = load_card_pipeline_config()
        hosts = cfg["known_repo_hosts"]
        # Mindestens prod + staging müssen rein, sonst läuft der Rewrite
        # nicht in der Standard-Konfiguration.
        assert PROD in hosts
        assert STAG in hosts


# ══════════════════════════════════════════════════════════════════════════
# normalize_cards — Host-Rewrite + node_type + Dedup + Sort
# ══════════════════════════════════════════════════════════════════════════

class TestNormalizeCardsNodeType:
    def test_topic_page_with_pages(self):
        cards = [{
            "node_id": "tp1", "node_type": "collection",
            "topic_pages": [{"url": "https://wirlernenonline.de/x"}],
        }]
        out = normalize_cards(cards)
        assert out[0]["node_type"] == "topic_page"

    def test_pure_collection(self):
        cards = [{"node_id": "c1", "node_type": "collection", "topic_pages": []}]
        out = normalize_cards(cards)
        assert out[0]["node_type"] == "collection"

    def test_content_default(self):
        cards = [{"node_id": "v1", "node_type": "content"}]
        out = normalize_cards(cards)
        assert out[0]["node_type"] == "content"

    def test_empty_card_defaults_to_content(self):
        out = normalize_cards([{"node_id": "x"}])
        assert out[0]["node_type"] == "content"


class TestNormalizeCardsDedupAndSort:
    def test_dedup_by_node_id(self):
        cards = [
            {"node_id": "A", "node_type": "content", "title": "First"},
            {"node_id": "A", "node_type": "content", "title": "Duplicate"},
            {"node_id": "B", "node_type": "content", "title": "Other"},
        ]
        out = normalize_cards(cards)
        assert len(out) == 2
        assert out[0]["title"] == "First"  # Erstes Vorkommen gewinnt

    def test_idless_cards_all_kept(self):
        cards = [
            {"node_id": "", "title": "X1", "node_type": "content"},
            {"node_id": "", "title": "X2", "node_type": "content"},
        ]
        out = normalize_cards(cards)
        assert len(out) == 2

    def test_general_sorts_topic_collection_content(self):
        cards = [
            {"node_id": "v1", "node_type": "content"},
            {"node_id": "c1", "node_type": "collection"},
            {"node_id": "tp1", "node_type": "collection",
             "topic_pages": [{"url": "x"}]},
        ]
        out = normalize_cards(cards, intent_kind="general")
        assert [c["node_type"] for c in out] == ["topic_page", "collection", "content"]

    def test_type_focus_keeps_pool_order(self):
        cards = [
            {"node_id": "v1", "node_type": "content"},
            {"node_id": "c1", "node_type": "collection"},
            {"node_id": "tp1", "node_type": "collection",
             "topic_pages": [{"url": "x"}]},
        ]
        out = normalize_cards(cards, intent_kind="type-focus")
        # Keine Resortierung — Original-Order beibehalten
        assert [c["node_id"] for c in out] == ["v1", "c1", "tp1"]


class TestNormalizeCardsHostRewrite:
    def test_production_url_rewritten_to_staging(self):
        cards = [{
            "node_id": "x", "node_type": "content",
            "wlo_url": f"{PROD}/edu-sharing/components/render/x",
            "url": f"{PROD}/foo",
        }]
        out = normalize_cards(cards, target_repo_base=STAG)
        assert out[0]["wlo_url"].startswith(STAG)
        assert out[0]["url"].startswith(STAG)

    def test_external_urls_untouched(self):
        cards = [{
            "node_id": "x", "node_type": "content",
            "url": "https://www.youtube.com/watch?v=foo",
        }]
        out = normalize_cards(cards, target_repo_base=STAG)
        assert out[0]["url"] == "https://www.youtube.com/watch?v=foo"

    def test_topic_page_variant_urls_processed(self):
        cards = [{
            "node_id": "tp", "node_type": "collection",
            "topic_pages": [
                {"url": f"{PROD}/edu-sharing/render/x", "label": "X"},
            ],
        }]
        out = normalize_cards(cards, target_repo_base=STAG)
        assert out[0]["topic_pages"][0]["url"].startswith(STAG)


# ══════════════════════════════════════════════════════════════════════════
# build_card_link — Lookup-Tabelle
# ══════════════════════════════════════════════════════════════════════════

class TestBuildCardLinkTopicPage:
    def test_returns_topic_page_url(self):
        card = {
            "node_id": "tp1", "node_type": "topic_page",
            "topic_page_url": "https://wirlernenonline.de/themenseite/x",
        }
        out = build_card_link(card, repo_base=PROD)
        assert out == "https://wirlernenonline.de/themenseite/x"

    def test_same_in_guide_mode(self):
        card = {
            "node_id": "tp1", "node_type": "topic_page",
            "topic_page_url": "https://wirlernenonline.de/themenseite/x",
        }
        assert (
            build_card_link(card, guide_mode=True, repo_base=PROD)
            == build_card_link(card, guide_mode=False, repo_base=PROD)
        )

    def test_fallback_to_variant_url(self):
        card = {
            "node_id": "tp1", "node_type": "topic_page",
            "topic_pages": [{"url": "https://wirlernenonline.de/variant"}],
        }
        out = build_card_link(card, repo_base=PROD)
        assert out == "https://wirlernenonline.de/variant"

    def test_fallback_to_collection_browse(self):
        card = {"node_id": "tp1", "node_type": "topic_page"}
        out = build_card_link(card, repo_base=PROD)
        assert out == f"{PROD}/edu-sharing/components/collections?id=tp1"


class TestBuildCardLinkCollection:
    def test_returns_browse_url(self):
        card = {"node_id": "c1", "node_type": "collection"}
        out = build_card_link(card, repo_base=PROD)
        assert out == f"{PROD}/edu-sharing/components/collections?id=c1"

    def test_with_search_query(self):
        card = {"node_id": "c1", "node_type": "collection"}
        out = build_card_link(card, repo_base=PROD, search_query="Eiszeit")
        assert out == f"{PROD}/edu-sharing/components/collections?id=c1&q=Eiszeit"

    def test_search_query_url_encoded(self):
        card = {"node_id": "c1", "node_type": "collection"}
        out = build_card_link(card, repo_base=PROD, search_query="Erste Welt")
        # Leerzeichen muss URL-encoded sein
        assert "Erste%20Welt" in out or "Erste+Welt" in out

    def test_same_in_guide_and_normal_mode(self):
        card = {"node_id": "c1", "node_type": "collection"}
        assert (
            build_card_link(card, guide_mode=True, repo_base=PROD)
            == build_card_link(card, guide_mode=False, repo_base=PROD)
        )

    def test_uses_target_repo_base(self):
        card = {"node_id": "c1", "node_type": "collection"}
        out = build_card_link(card, repo_base=STAG)
        assert out.startswith(STAG)


class TestBuildCardLinkContent:
    def test_normal_mode_uses_external_url(self):
        card = {
            "node_id": "v1", "node_type": "content",
            "url": "https://www.youtube.com/watch?v=x",
        }
        out = build_card_link(card, guide_mode=False, repo_base=PROD)
        assert out == "https://www.youtube.com/watch?v=x"

    def test_guide_mode_uses_repo_render(self):
        card = {
            "node_id": "v1", "node_type": "content",
            "url": "https://www.youtube.com/watch?v=x",
        }
        out = build_card_link(card, guide_mode=True, repo_base=PROD)
        assert out == f"{PROD}/edu-sharing/components/render/v1"

    def test_no_external_falls_back_to_render(self):
        card = {"node_id": "v1", "node_type": "content"}
        out = build_card_link(card, guide_mode=False, repo_base=PROD)
        assert out == f"{PROD}/edu-sharing/components/render/v1"

    def test_no_id_uses_external_url(self):
        card = {"node_type": "content", "url": "https://example.com/foo"}
        out = build_card_link(card, repo_base=PROD)
        assert out == "https://example.com/foo"


class TestBuildCardLinkDefensive:
    def test_empty_dict(self):
        assert build_card_link({}, repo_base=PROD) == ""

    def test_none(self):
        assert build_card_link(None, repo_base=PROD) == ""  # type: ignore[arg-type]

    def test_unknown_node_type_falls_back_to_content(self):
        # Wenn node_type nicht in den 3 kanonischen Werten ist, wird per
        # _infer_node_type re-bestimmt → content (Default).
        card = {"node_id": "x", "node_type": "weird", "url": "https://example.com"}
        out = build_card_link(card, repo_base=PROD)
        assert out == "https://example.com"


# ══════════════════════════════════════════════════════════════════════════
# validate_card_link — Allow-List
# ══════════════════════════════════════════════════════════════════════════

class TestValidateCardLink:
    def test_wlo_de_allowed(self):
        assert validate_card_link("https://wirlernenonline.de/themenseite/x")

    def test_repo_prod_allowed(self):
        assert validate_card_link(f"{PROD}/edu-sharing/components/render/x")

    def test_repo_staging_allowed(self):
        assert validate_card_link(f"{STAG}/edu-sharing/components/render/x")

    def test_youtube_not_allowed(self):
        assert not validate_card_link("https://www.youtube.com/watch?v=x")

    def test_empty_rejected(self):
        assert not validate_card_link("")

    def test_none_rejected(self):
        assert not validate_card_link(None)  # type: ignore[arg-type]

    def test_invalid_scheme_rejected(self):
        assert not validate_card_link("ftp://example.com/x")

    def test_custom_allow_list(self):
        # Wenn allowed_hosts übergeben wird, ignoriert die Funktion die
        # guide-mode.yaml-Default-Liste.
        out = validate_card_link(
            "https://example.com/x",
            allowed_hosts=["example.com"],
        )
        assert out


# ══════════════════════════════════════════════════════════════════════════
# select_final_cards — Mix + LLM-Re-Rank + Filter
# ══════════════════════════════════════════════════════════════════════════

def _make_pool() -> list[dict]:
    """Standard-Test-Pool: 1 Themenseite, 3 Sammlungen, 12 Videos."""
    pool = [
        {"node_id": "TP1", "title": "TP-Math", "node_type": "topic_page",
         "topic_pages": [{"url": "x"}]},
        {"node_id": "C1", "title": "Col-1", "node_type": "collection"},
        {"node_id": "C2", "title": "Col-2", "node_type": "collection"},
        {"node_id": "C3", "title": "Col-3", "node_type": "collection"},
    ]
    for i in range(1, 13):
        pool.append({
            "node_id": f"V{i}", "title": f"Video-{i}", "node_type": "content",
            "learning_resource_types": ["Video"],
        })
    return pool


class TestSelectFinalCards:
    def test_general_default_mix(self):
        out = select_final_cards(
            _make_pool(), intent_kind="general", final_size=5,
        )
        types = [c["node_type"] for c in out]
        # 1 Themenseite + 1 Sammlung + 3 Einzel
        assert types == ["topic_page", "collection", "content", "content", "content"]

    def test_general_llm_selection_used(self):
        out = select_final_cards(
            _make_pool(), intent_kind="general", final_size=5,
            selected_node_ids=["C2", "V8", "V5"],
        )
        ids = [c["node_id"] for c in out]
        # LLM-picks zuerst, dann deterministischer Fill
        assert ids[:3] == ["C2", "V8", "V5"]

    def test_general_hallucinated_ids_ignored(self):
        out = select_final_cards(
            _make_pool(), intent_kind="general", final_size=5,
            selected_node_ids=["DOES-NOT-EXIST", "V1", "ALSO-FAKE"],
        )
        ids = [c["node_id"] for c in out]
        # V1 wird gefunden, der Rest deterministisch
        assert "V1" in ids
        assert "DOES-NOT-EXIST" not in ids
        assert "ALSO-FAKE" not in ids

    def test_type_focus_strict_filter(self):
        out = select_final_cards(
            _make_pool(), intent_kind="type-focus", final_size=5,
            wanted_content_types={"video"},
        )
        # Alle Treffer müssen content-Typ sein (Sammlungen + Themenseiten raus)
        assert all(c["node_type"] == "content" for c in out)
        assert len(out) == 5

    def test_type_focus_no_match_returns_empty(self):
        out = select_final_cards(
            _make_pool(), intent_kind="type-focus", final_size=5,
            wanted_content_types={"arbeitsblatt"},  # nichts im Pool
        )
        assert out == []

    def test_small_pool_returns_all(self):
        small = [
            {"node_id": "X1", "node_type": "content"},
            {"node_id": "X2", "node_type": "content"},
        ]
        out = select_final_cards(small, intent_kind="general", final_size=5)
        assert len(out) == 2

    def test_collection_contents_no_resort(self):
        # Bei collection-contents bleibt die Pool-Reihenfolge erhalten
        contents = [
            {"node_id": f"CC{i}", "node_type": "content"} for i in range(1, 8)
        ]
        out = select_final_cards(contents, intent_kind="collection-contents",
                                  final_size=5)
        assert [c["node_id"] for c in out] == ["CC1", "CC2", "CC3", "CC4", "CC5"]

    def test_empty_pool_returns_empty(self):
        out = select_final_cards([], intent_kind="general", final_size=5)
        assert out == []


# ══════════════════════════════════════════════════════════════════════════
# annotate_cards_with_link
# ══════════════════════════════════════════════════════════════════════════

class TestAnnotateCardsWithLink:
    def test_link_field_set_on_each_card(self):
        cards = [
            {"node_id": "c1", "node_type": "collection"},
            {"node_id": "v1", "node_type": "content", "url": "https://x.de/y"},
        ]
        out = annotate_cards_with_link(cards, repo_base=PROD)
        assert all("link" in c for c in out)
        assert out[0]["link"].startswith(PROD)
        assert out[1]["link"] == "https://x.de/y"

    def test_require_allowed_fallback_to_render(self):
        # YouTube-URL ist nicht in der Allow-Liste → Fallback auf Repo-Render
        cards = [{
            "node_id": "v1", "node_type": "content",
            "url": "https://www.youtube.com/watch?v=x",
        }]
        out = annotate_cards_with_link(
            cards, repo_base=PROD, require_allowed=True,
        )
        assert out[0]["link"] == f"{PROD}/edu-sharing/components/render/v1"

    def test_guide_mode_propagated(self):
        # Im Guide-Modus muss der Link für Einzelinhalte auf Repo-Render zeigen
        cards = [{
            "node_id": "v1", "node_type": "content",
            "url": "https://www.youtube.com/watch?v=x",
        }]
        out = annotate_cards_with_link(
            cards, guide_mode=True, repo_base=PROD,
        )
        assert out[0]["link"].endswith("/render/v1")


# ══════════════════════════════════════════════════════════════════════════
# summarize_pipeline_result — Logger-Format
# ══════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════
# Relevance-Sortierung — Phase 3a Erweiterung
# ══════════════════════════════════════════════════════════════════════════

class TestTokenizeQuery:
    def test_simple(self):
        assert _tokenize_query("Bruchrechnung") == {"bruchrechnung"}

    def test_strips_stopwords(self):
        out = _tokenize_query("Material zu Bruchrechnung")
        assert out == {"bruchrechnung"}, f"got {out}"

    def test_multi_token(self):
        out = _tokenize_query("Eiszeit (Geographie)")
        assert out == {"eiszeit", "geographie"}

    def test_german_umlauts(self):
        out = _tokenize_query("Brücke über die Donau")
        assert "brücke" in out
        assert "donau" in out

    def test_drops_short_tokens(self):
        # 1-Zeichen-Tokens raus
        out = _tokenize_query("a b ab")
        assert out == {"ab"}

    def test_empty_returns_empty_set(self):
        assert _tokenize_query("") == set()
        assert _tokenize_query(None) == set()  # type: ignore[arg-type]


class TestRelevanceScore:
    def test_no_tokens_returns_zero(self):
        assert _relevance_score({"title": "X"}, set()) == 0.0

    def test_title_match_strongest(self):
        s = _relevance_score(
            {"title": "Bruchrechnung Einführung"},
            {"bruchrechnung"},
        )
        assert s == 2.0

    def test_keywords_match(self):
        s = _relevance_score(
            {"title": "X", "keywords": ["Bruchrechnung", "Mathe"]},
            {"bruchrechnung"},
        )
        assert s == 1.0

    def test_combined_signals_add_up(self):
        s = _relevance_score(
            {
                "title": "Bruchrechnung",
                "keywords": ["Bruchrechnung"],
                "disciplines": ["Mathematik"],
                "description": "Eine Einführung in die Bruchrechnung.",
            },
            {"bruchrechnung", "mathematik"},
        )
        # Token "bruchrechnung": title 2.0 + keywords 1.0 + description 0.3 = 3.3
        # Token "mathematik":    disciplines 0.5
        # Summe: 3.8
        assert s == pytest.approx(3.8, abs=0.01)

    def test_no_match_returns_zero(self):
        assert _relevance_score(
            {"title": "Politische Bildung"},
            {"bruchrechnung"},
        ) == 0.0


class TestSortByRelevance:
    def test_relevant_first(self):
        cards = [
            {"node_id": "A", "title": "Politische Bildung"},
            {"node_id": "B", "title": "Bruchrechnung Übungen"},
            {"node_id": "C", "title": "Geometrie"},
        ]
        out = _sort_by_relevance(cards, {"bruchrechnung"})
        assert out[0]["node_id"] == "B"

    def test_stable_for_ties(self):
        cards = [
            {"node_id": "A", "title": "Zero-1"},
            {"node_id": "B", "title": "Zero-2"},
        ]
        out = _sort_by_relevance(cards, {"unrelated"})
        # Beide Score 0 → MCP-Reihenfolge erhalten
        assert [c["node_id"] for c in out] == ["A", "B"]

    def test_empty_tokens_passthrough(self):
        cards = [{"node_id": "X"}, {"node_id": "Y"}]
        out = _sort_by_relevance(cards, set())
        assert [c["node_id"] for c in out] == ["X", "Y"]


class TestSelectFinalCardsRelevance:
    """Live-Bug Reproduktion: bei query="Bruchrechnung" liefert die alte v2
    "Politische Bildung" als erste Sammlung. Mit Relevance-Sort muss eine
    Bruchrechnung-Sammlung gewinnen.
    """

    def test_relevant_collection_wins(self):
        pool = [
            {"node_id": "C-pol", "node_type": "collection",
             "title": "Politische Bildung"},
            {"node_id": "C-mat", "node_type": "collection",
             "title": "Sammlung Bruchrechnung Übungen"},
            {"node_id": "V1", "node_type": "content",
             "title": "Andere Mathematik-Inhalte"},
        ]
        out = select_final_cards(
            pool, intent_kind="general", final_size=3,
            query="Material zu Bruchrechnung",
        )
        # Erste Card muss die Bruchrechnung-Sammlung sein
        assert out[0]["node_id"] == "C-mat"

    def test_type_focus_relevance_sort(self):
        pool = [
            {"node_id": "V-off", "node_type": "content",
             "title": "Andere Sache",
             "learning_resource_types": ["Video"]},
            {"node_id": "V-on", "node_type": "content",
             "title": "Photosynthese-Video",
             "learning_resource_types": ["Video"]},
        ]
        out = select_final_cards(
            pool, intent_kind="type-focus", final_size=2,
            wanted_content_types={"video"},
            query="Videos zur Photosynthese",
        )
        assert out[0]["node_id"] == "V-on"

    def test_no_query_keeps_pool_order(self):
        pool = [
            {"node_id": "C1", "node_type": "collection", "title": "Erste"},
            {"node_id": "C2", "node_type": "collection", "title": "Zweite"},
            {"node_id": "V1", "node_type": "content", "title": "Drei"},
        ]
        out = select_final_cards(pool, intent_kind="general", final_size=3)
        # Ohne Query: Mix bleibt deterministisch (1 Coll dann content)
        assert out[0]["node_id"] == "C1"

    def test_irrelevant_group_dropped_when_other_matches(self):
        """Live-Bug: bei Bruchrechnung-Query waren ALLE 7 Sammlungen
        irrelevant; aber Inhalte enthielten 4 Bruchrechnung-Matches. Die
        irrelevante Sammlung "Politische Bildung" wurde trotzdem als erste
        Card angezeigt. Fix: Score-0-Gruppen werden ganz weggelassen.
        """
        pool = [
            # 3 Sammlungen, KEINE mit "Bruchrechnung"-Match
            {"node_id": "C-pol", "node_type": "collection", "title": "Politische Bildung"},
            {"node_id": "C-bio", "node_type": "collection", "title": "Biologie-Sammlung"},
            {"node_id": "C-his", "node_type": "collection", "title": "Geschichte"},
            # 3 Inhalte, ALLE mit Match
            {"node_id": "V1", "node_type": "content", "title": "Bruchrechnung Übung 1"},
            {"node_id": "V2", "node_type": "content", "title": "Bruchrechnung Video"},
            {"node_id": "V3", "node_type": "content", "title": "Bruchrechnung Aufgabenblatt"},
        ]
        out = select_final_cards(
            pool, intent_kind="general", final_size=5,
            query="Material zu Bruchrechnung",
        )
        # Keine der irrelevanten Sammlungen darf in der Auswahl sein.
        ids = [c["node_id"] for c in out]
        assert "C-pol" not in ids
        assert "C-bio" not in ids
        assert "C-his" not in ids
        assert ids == ["V1", "V2", "V3"]

    def test_all_irrelevant_fallback_to_pool_order(self):
        """Wenn keine Card im Pool zur Query passt (vage Query, leerer
        Pool-Match), behalten wir alle Cards in MCP-Reihenfolge — sonst
        bekäme der User leere Hände."""
        pool = [
            {"node_id": "A", "node_type": "collection", "title": "Etwas"},
            {"node_id": "B", "node_type": "content", "title": "Anderes"},
            {"node_id": "C", "node_type": "content", "title": "Drittes"},
        ]
        out = select_final_cards(
            pool, intent_kind="general", final_size=5,
            query="völlig unmatching Quantenchromodynamik",
        )
        # Mix-Logik nimmt 1 Sammlung + 2 Inhalte (Reihenfolge stable)
        assert len(out) == 3
        ids = [c["node_id"] for c in out]
        assert "A" in ids and "B" in ids and "C" in ids

    def test_collection_contents_no_relevance_resort(self):
        # Bei collection-contents bleibt die kuratierte Reihenfolge — auch
        # wenn die Query nicht zu allen Titeln matcht.
        pool = [
            {"node_id": "Off1", "node_type": "content", "title": "Anderes A"},
            {"node_id": "On1", "node_type": "content", "title": "Photosynthese B"},
        ]
        out = select_final_cards(
            pool, intent_kind="collection-contents", final_size=2,
            query="Photosynthese",
        )
        # Original-Reihenfolge muss bleiben (kuratierte Sammlung)
        assert [c["node_id"] for c in out] == ["Off1", "On1"]


class TestSummarizePipelineResult:
    def test_format_contains_counts(self):
        result = {
            "intent_kind": "general",
            "pool_size": 20,
            "normalized_size": 18,
            "final_size": 5,
            "cards": [
                {"node_type": "content", "node_id": "v1", "title": "X"},
            ],
        }
        s = summarize_pipeline_result(result)
        assert "[v2]" in s
        assert "intent=general" in s
        assert "pool=20>18>5" in s

    def test_ascii_only_no_unicode_arrows(self):
        result = {
            "intent_kind": "general",
            "pool_size": 1, "normalized_size": 1, "final_size": 1,
            "cards": [{"node_type": "content", "node_id": "x", "title": "y"}],
        }
        s = summarize_pipeline_result(result)
        # Kein Unicode-Pfeil — sonst crasht Windows-cp1252 stdout im Logger
        assert "→" not in s


# ══════════════════════════════════════════════════════════════════════════
# Env-Flag — card_pipeline_v2_enabled
# ══════════════════════════════════════════════════════════════════════════

class TestCardPipelineV2Enabled:
    def test_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv("CARD_PIPELINE_V2", raising=False)
        assert card_pipeline_v2_enabled() is False

    def test_zero_returns_false(self, monkeypatch):
        monkeypatch.setenv("CARD_PIPELINE_V2", "0")
        assert card_pipeline_v2_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "True", "yes", "on", "ON"])
    def test_truthy_values(self, monkeypatch, val):
        monkeypatch.setenv("CARD_PIPELINE_V2", val)
        assert card_pipeline_v2_enabled() is True
