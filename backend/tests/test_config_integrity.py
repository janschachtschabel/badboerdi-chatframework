"""Config-Integrität — referenzielle Konsistenz der ausgelieferten Config.

Das ist das wichtigste Regressionsnetz: es fängt genau die Fehlerklasse,
die uns real getroffen hat — ein Pattern, das auf eine RAG-Area zeigt, die
nicht existiert; ein Typ-Alias, der auf einen unbekannten Material-Typ
mappt; ein Safety-Pattern, das es nicht (mehr) gibt.

Liest die ECHTEN YAML/MD-Dateien über die produktiven Loader (keine Mocks),
damit eine kaputt-editierte Config im CI sofort rot wird statt erst im
Live-Chat aufzufallen.
"""

from __future__ import annotations

from app.services import config_loader as cl


# ── Loader-Smoke: kein Loader wirft, Pflicht-Dimensionen sind nicht leer ──

def test_core_loaders_return_nonempty():
    assert cl.load_intents(), "intents.yaml leer/nicht geladen"
    assert cl.load_persona_definitions(), "keine Personas geladen"
    assert cl.load_pattern_definitions(), "keine Patterns geladen"
    assert cl.load_states(), "keine States geladen"
    assert cl.load_rag_config(), "rag-config leer/nicht geladen"
    assert cl.load_canvas_material_types(), "keine Material-Typen geladen"


# ── Referenzielle Integrität (die Bug-Klassen) ──

def test_pattern_rag_areas_reference_real_areas():
    """Jede in einem Pattern referenzierte RAG-Area muss in rag-config existieren."""
    known = set(cl.get_all_rag_areas())
    offenders = [
        (p.get("id"), area)
        for p in cl.load_pattern_definitions()
        for area in (p.get("rag_areas") or [])
        if area not in known
    ]
    assert not offenders, (
        f"Pattern verweist auf unbekannte RAG-Area: {offenders}. "
        f"Bekannte Areas: {sorted(known)}"
    )


def test_type_aliases_resolve_to_real_material_types():
    """Alias- und LRT-Mappings dürfen nur auf existierende Material-Typ-IDs zeigen."""
    type_ids = {m["id"] for m in cl.load_canvas_material_types() if m.get("id")}
    al = cl.load_canvas_type_aliases()
    bad_alias = {k: v for k, v in al["aliases"].items() if v not in type_ids}
    bad_lrt = {k: v for k, v in al["lrt_to_type"].items() if v not in type_ids}
    assert not bad_alias, f"Alias zeigt auf unbekannten Material-Typ: {bad_alias}"
    assert not bad_lrt, f"LRT-Mapping zeigt auf unbekannten Material-Typ: {bad_lrt}"


def test_safety_enforced_patterns_exist():
    """crisis_pattern/threat_pattern in safety-config müssen reale Patterns sein."""
    cfg = cl.load_safety_config()
    pat_ids = {p["id"] for p in cl.load_pattern_definitions() if p.get("id")}
    for key in ("crisis_pattern", "threat_pattern"):
        pid = cfg.get(key)
        if pid:
            assert pid in pat_ids, (
                f"safety-config.{key}={pid!r} ist kein existierendes Pattern "
                f"(vorhanden: {sorted(pat_ids)})"
            )


# ── Eindeutigkeit der IDs ──

def test_dimension_ids_are_unique():
    for loader in (
        cl.load_pattern_definitions,
        cl.load_intents,
        cl.load_persona_definitions,
        cl.load_states,
    ):
        ids = [x.get("id") for x in loader() if x.get("id")]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        assert not dupes, f"Doppelte IDs in {loader.__name__}: {dupes}"


# ── Policy- und Gold-Flow-Regeln referenzieren bekannte Dimensionen ──

def test_policy_rules_reference_known_dimensions():
    persona_ids = {p.get("id") for p in cl.load_persona_definitions()}
    intent_ids = {i.get("id") for i in cl.load_intents()}
    cfg = cl.load_policy_config()
    for rule in (cfg.get("rules") or []):
        match = rule.get("match", {}) or {}
        rid = rule.get("id", "?")
        if match.get("persona"):
            assert match["persona"] in persona_ids, (
                f"policy rule {rid} → unbekannte persona {match['persona']!r}"
            )
        if match.get("intent"):
            assert match["intent"] in intent_ids, (
                f"policy rule {rid} → unbekannter intent {match['intent']!r}"
            )


def test_gold_flows_reference_known_dimensions():
    persona_ids = {p.get("id") for p in cl.load_persona_definitions()} | {"*"}
    intent_ids = {i.get("id") for i in cl.load_intents()} | {"*"}
    flows = cl.load_gold_flows()
    assert flows, "keine Gold-Flows geladen"
    for flow in flows:
        fid = flow.get("id", "?")
        assert flow.get("persona") in persona_ids, (
            f"Gold-Flow {fid} → unbekannte persona {flow.get('persona')!r}"
        )
        for turn in flow.get("turns", []):
            exp = turn.get("expect", {}) or {}
            if exp.get("intent"):
                assert exp["intent"] in intent_ids, (
                    f"Gold-Flow {fid} → unbekannter expect.intent {exp['intent']!r}"
                )
            if exp.get("persona"):
                assert exp["persona"] in persona_ids, (
                    f"Gold-Flow {fid} → unbekannte expect.persona {exp['persona']!r}"
                )
