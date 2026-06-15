"""Policy-Layer — bedingte Org-/Regulierungsregeln (block_tools + disclaimer).

Wichtige Invariante: Policy erzwingt KEINE harte Blockade (Guardrail R-01
„nie blockieren"). Sie kann nur Tools sperren und Pflicht-Disclaimer anhängen.
Die Regeln werden hier gemockt, damit der Test unabhängig vom ausgelieferten
policy.yaml-Inhalt bleibt (dessen Referenzen prüft test_config_integrity).
"""

from __future__ import annotations

from app.services import policy_service as ps


def _patch_rules(monkeypatch, rules):
    monkeypatch.setattr(ps, "load_policy_config", lambda: {"rules": rules})


def test_no_rules_means_clean_decision(monkeypatch):
    _patch_rules(monkeypatch, [])
    d = ps.assess_policy("egal", "P-LEH", "I02")
    assert d.matched_rules == []
    assert d.blocked_tools == []
    assert d.required_disclaimers == []


def test_persona_match_applies_effect(monkeypatch):
    _patch_rules(monkeypatch, [{
        "id": "r-persona",
        "match": {"persona": "P-ENT"},
        "effect": {"block_tools": ["search_wlo_content"], "disclaimer": "Hinweis X"},
    }])
    hit = ps.assess_policy("frage", "P-ENT", "I02")
    assert "r-persona" in hit.matched_rules
    assert "search_wlo_content" in hit.blocked_tools
    assert "Hinweis X" in hit.required_disclaimers
    # andere Persona → kein Match
    miss = ps.assess_policy("frage", "P-LEH", "I02")
    assert miss.matched_rules == []


def test_intent_and_regex_match(monkeypatch):
    _patch_rules(monkeypatch, [{
        "id": "r-regex",
        "match": {"intent": "I02", "message_regex": r"\bdatenschutz\b"},
        "effect": {"disclaimer": "DSGVO-Hinweis"},
    }])
    hit = ps.assess_policy("Frage zum Datenschutz hier", "P-LEH", "I02")
    assert "r-regex" in hit.matched_rules
    # Regex passt nicht → kein Match
    miss = ps.assess_policy("ganz andere frage", "P-LEH", "I02")
    assert miss.matched_rules == []
    # Intent passt nicht → kein Match (trotz passender Regex)
    miss2 = ps.assess_policy("Frage zum Datenschutz", "P-LEH", "I05")
    assert miss2.matched_rules == []


def test_broken_regex_is_skipped_not_crashing(monkeypatch):
    _patch_rules(monkeypatch, [{
        "id": "r-bad",
        "match": {"message_regex": "([unclosed"},
        "effect": {"disclaimer": "nope"},
    }])
    d = ps.assess_policy("irgendwas", "P-LEH", "I02")  # darf nicht werfen
    assert d.matched_rules == []


def test_block_tools_deduped_across_rules(monkeypatch):
    _patch_rules(monkeypatch, [
        {"id": "r1", "match": {}, "effect": {"block_tools": ["t_a", "t_b"]}},
        {"id": "r2", "match": {}, "effect": {"block_tools": ["t_b", "t_c"],
                                             "disclaimer": "D"}},
    ])
    d = ps.assess_policy("x", "P-LEH", "I02")
    assert d.matched_rules == ["r1", "r2"]
    assert d.blocked_tools == ["t_a", "t_b", "t_c"]  # dedupe, Reihenfolge stabil
    assert d.required_disclaimers == ["D"]


def test_policy_decision_has_no_hard_block_field():
    # R-01-Invariante: PolicyDecision kennt kein allowed=False mehr.
    d = ps.assess_policy("x", "P-LEH", "I02")
    assert not hasattr(d, "allowed") or getattr(d, "allowed") is not False
