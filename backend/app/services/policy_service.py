"""Policy layer (T-13/14 from Triple-Schema v2).

Org/regulatory rules — distinct from Safety (which handles user risk).
Policy decides what's *allowed* by configuration: tool whitelists per
persona, mandatory disclaimers, license restrictions, etc.

Rules are loaded from `01-base/policy.yaml` so they can be edited
in the Studio (tab "Identität & Schutz", alongside Guardrails + Safety)
without code changes.
"""

from __future__ import annotations

import re
from typing import Any

from app.models.schemas import PolicyDecision
from app.services.config_loader import load_policy_config


def assess_policy(
    message: str,
    persona_id: str,
    intent_id: str,
) -> PolicyDecision:
    """Apply policy rules and return a PolicyDecision.

    Each rule in policy.yaml may define:
      match: { persona?, intent?, message_regex? }
      effect: { block_tools?, disclaimer? }

    Hinweis: Policy erzwingt KEINE harte Blockade (Guardrail R-01 „nie
    blockieren") — sie sperrt nur einzelne Tools und hängt Pflicht-
    Disclaimer an.
    """
    decision = PolicyDecision()
    cfg = load_policy_config()
    rules = cfg.get("rules", []) or []
    msg = (message or "").lower()

    for rule in rules:
        match = rule.get("match", {}) or {}
        if "persona" in match and match["persona"] != persona_id:
            continue
        if "intent" in match and match["intent"] != intent_id:
            continue
        regex = match.get("message_regex")
        if regex:
            try:
                if not re.search(regex, msg):
                    continue
            except re.error:
                continue

        effect = rule.get("effect", {}) or {}
        rid = rule.get("id", "policy-rule")
        decision.matched_rules.append(rid)

        for t in effect.get("block_tools", []) or []:
            if t not in decision.blocked_tools:
                decision.blocked_tools.append(t)
        disc = effect.get("disclaimer")
        if disc and disc not in decision.required_disclaimers:
            decision.required_disclaimers.append(disc)

    return decision
