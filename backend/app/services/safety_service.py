"""Safety layer (T-12 / T-19 from Triple-Schema v2).

Multi-stage risk assessment that runs BEFORE pattern selection and tool
execution. Independent of persona/pattern logic so it cannot be bypassed.

Stages:
  1. Regex gate           — fast (~1 ms), always on
  2. OpenAI Moderation    — eskaliert nur bei Verdacht (~50–150 ms),
                            deckt Strafrecht / Jugendschutz / Hate / Violence
  3. LLM Legal Classifier — GPT-mini mit deutschem Rechts-Prompt (~150 ms),
                            deckt Persönlichkeitsrechte und Datenschutz

Konfigurierbar in 01-base/safety-config.yaml unter `escalation`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

from app.models.schemas import SafetyDecision
from app.services.config_loader import load_safety_config

logger = logging.getLogger(__name__)

# ── Stage 1: Regex patterns ─────────────────────────────────────────
# Crisis = Nutzer richtet Gewalt/Suizid gegen SICH SELBST.  Ein reines
# "ich" weiter vorn im Satz reicht NICHT — "ich werde dich umbringen"
# wäre sonst eine Crisis statt einer Drohung gegen Dritte.  Darum muss
# das self-referentielle Pronomen (mich/mir/selbst) DIREKT am Gewaltverb
# hängen (max. 10 Zeichen Abstand).
_CRISIS_PATTERNS = [
    # Suizid-Keywords sind klar self-referential
    r"\b(suizid|suicid|selbstmord|selbstt[öo]tung)\b",
    # Selbstverletzung
    r"\b(selbstverletz|ritz mich|ritze mich|ritzen seit|tu mir weh)\b",
    # "umbringen / töten" mit engem Selbstbezug. 0-10 Zeichen Abstand —
    # "ich will mich umbringen" ✓, "ich werde dich finden und umbringen" ✗.
    # WICHTIG: `umbring\w*` statt `\bumbring\b` — sonst matcht "umbringen"
    # nicht, weil \b mitten im Wort steht.
    r"\b(mich|mir)\b[^.?!]{0,10}\bumbring\w*\b",
    r"\b(mich|mir)\b[^.?!]{0,10}\bt[öo]te\w*\b",
    r"\bumbring\w*\b[^.?!]{0,10}\b(mich|mir)\b",
    r"\bt[öo]te\w*\b[^.?!]{0,10}\b(mich|mir)\b",
    r"\bmich\s+selbst\b[^.?!]{0,10}\b(umbring\w*|t[öo]te\w*)\b",
    # "nicht mehr leben wollen" — klar Suizid
    r"\bnicht mehr leben\b",
    # Tabletten-/Überdosis-Euphemismen (fängt "wie viele tabletten muss
    # ich nehmen damit es reicht", "genug tabletten für immer", "überdosis")
    r"\b(tabletten|pillen)\b[^.?!]{0,40}\b(reich(en|t)|genug|f[üu]r immer|damit (es|ich))\b",
    r"\b(überdosis|ueberdosis|overdose)\b",
]

# Threat = Nutzer droht Gewalt/Tötung gegen Dritte.  Eigener enforced
# Pattern (PAT-REFUSE-THREAT) und HIGH-Risk, aber KEINE Suizid-Empathie.
# Vorsicht: `\bumbring\b` matcht NICHT in "umbringen"! Deshalb `umbring\w*`.
_THREAT_PATTERNS = [
    # "Ich werde dich/euch/ihn/sie umbringen/töten …"
    r"\b(werde|will|gonna)\b[^.?!]{0,30}\b(dich|euch|ihn|sie|ihr|you|him|her|them)\b[^.?!]{0,40}\b(umbring\w*|t[öo]te\w*|abstech\w*|erschieß\w*|erschiess\w*|kill\w*|murder\w*)\b",
    # "… umbringen, dich", umgekehrte Reihenfolge
    r"\b(umbring\w*|t[öo]te\w*|abstech\w*|erschieß\w*|erschiess\w*|kill\w*|murder\w*)\b[^.?!]{0,40}\b(dich|euch|ihn|sie|ihr|you|him|her|them)\b",
    # "Ich finde dich und …"
    r"\bich\s+finde\s+dich\b[^.?!]{0,40}\b(umbring\w*|t[öo]te\w*|fertig)\b",
]

_PII_PATTERNS = [
    r"\b(passwort|password|kreditkart|sozialvers|geburtsdatum)\b.*\b(meine?|ist|lautet)\b",
]
# Heuristik-Trigger: wenn eines dieser Wörter auftaucht, soll der Legal-Classifier
# auch im "smart"-Mode laufen, selbst wenn das Risiko sonst noch low wäre.
_LEGAL_TRIGGER_PATTERNS = [
    r"\b(hasse|hass|hassen|scheiß|verflucht|verfluche|drohe|drohung|drohst)\b",
    r"\b(umbring|umbringen|töten|toeten|abstech|erschieß|vergewaltig)\b",
    r"\b(schlag dich|schlage dich|hau dich|hau ihn|fertig mach)\b",
    r"\b(idiot|arschloch|hurensohn|wichser|missgeburt)\b",
    r"\b(nazi|jude|kanake|neger)\b",
    r"\b(hate|kill you|hurt you|threat|murder)\b",
]

# All patterns are matched against `message.lower()`, so the patterns
# themselves must be lowercase. Don't put uppercase tokens here.
_INJECTION_PATTERNS = [
    # DE: allow 1-3 intermediate words between "ignoriere" and the noun so
    # phrases like "ignoriere alle vorherigen anweisungen" match.
    r"ignorier[et]?\s+(?:\w+\s+){1,3}(anweisungen|regeln|instruktionen|prompts?)",
    # EN: same — "ignore all previous instructions", "ignore your prior rules".
    r"ignore\s+(?:\w+\s+){1,3}(instructions|rules|prompts?)",
    r"system\s*prompt",
    # Persona-override — handles both "verhalte dich als/wie …" and
    # free-form "du bist jetzt <rolle/modus>". The old pattern required
    # "(as|wie|ein)" after "du bist jetzt …" which missed "du bist jetzt
    # dan mode" (no connector word).
    r"\b(verhalte dich|act as|you are now)\s+(as|wie|ein)\s+",
    r"\bdu bist jetzt\s+\w+",
    r"(reveal|zeig(e)?|gib aus)\s+(your|den|deinen)\s+(prompt|system|instructions)",
    # Known jailbreak modes — keep lowercase!
    r"\b(jailbreak|dan\s*mode|developer\s*mode|do\s*anything\s*now)\b",
    r"\bantworte\s+ohne\s+filter\b",
    r"<\|.*?\|>",
    r"```\s*system",
]


def _resolve_preset(cfg: dict) -> dict:
    """Resolve active preset from security_level. Falls back to legacy escalation."""
    level = (cfg.get("security_level") or "standard").lower()
    # Backwards-compat: "basic" was renamed/merged into "standard"
    if level == "basic":
        level = "standard"
    presets = cfg.get("presets") or {}
    preset = presets.get(level)
    if preset:
        return {
            "level": level,
            "moderation": preset.get("moderation", "smart"),
            "legal_classifier": preset.get("legal_classifier", "smart"),
            "prompt_injection": bool(preset.get("prompt_injection", False)),
            "legal_trigger_override": bool(preset.get("legal_trigger_override", False)),
            "threshold_multiplier": float(preset.get("threshold_multiplier", 1.0)),
            "double_check": bool(preset.get("double_check", False)),
        }
    # Legacy fallback
    esc = cfg.get("escalation", {}) or {}
    mode = esc.get("mode", "off")
    return {
        "level": "legacy",
        "moderation": "always" if mode == "always" else ("smart" if mode == "smart" else "never"),
        "legal_classifier": "smart" if esc.get("legal_classifier", True) else "never",
        "prompt_injection": False,
        "legal_trigger_override": True,
        "threshold_multiplier": 1.0,
        "double_check": False,
    }


def _stage_should_run(stage_mode: str, current_risk: str) -> bool:
    if stage_mode == "always":
        return True
    if stage_mode == "smart":
        return current_risk in ("medium", "high")
    return False


def _regex_gate(message: str, signals: list[str]) -> SafetyDecision:
    """Stage 1: fast regex assessment.

    Three mutually exclusive hard-block paths:
      * Crisis — user endangers themselves → PAT-CRISIS (empathic)
      * Threat — user threatens others   → PAT-REFUSE-THREAT (firm refusal)
      * PII   — user volunteers sensitive data → soft medium block

    Crisis takes priority over Threat when both would match (conservative
    side of the fence — never respond with hostility if there's any
    self-harm signal).
    """
    msg = (message or "").lower()
    decision = SafetyDecision()
    decision.stages_run.append("regex")

    for pat in _CRISIS_PATTERNS:
        if re.search(pat, msg):
            decision.risk_level = "high"
            decision.enforced_pattern = "PAT-CRISIS"
            decision.blocked_tools = [
                "search_wlo_collections", "search_wlo_content",
                "get_collection_contents",
            ]
            decision.reasons.append("crisis_signal_detected")
            decision.legal_flags.append("jugendschutz")
            return decision

    for pat in _THREAT_PATTERNS:
        if re.search(pat, msg):
            decision.risk_level = "high"
            decision.enforced_pattern = "PAT-REFUSE-THREAT"
            decision.blocked_tools = [
                "search_wlo_collections", "search_wlo_content",
                "get_collection_contents",
            ]
            decision.reasons.append("threat_signal_detected")
            decision.legal_flags.append("strafrecht")
            return decision

    for pat in _PII_PATTERNS:
        if re.search(pat, msg):
            decision.risk_level = "medium"
            decision.blocked_tools.append("search_wlo_content")
            decision.reasons.append("pii_in_message")
            decision.legal_flags.append("datenschutz")
            break

    if "bedroht" in signals or "in_gefahr" in signals:
        decision.risk_level = "high"
        decision.reasons.append("danger_signal")

    return decision


# ── Stage 2: OpenAI Moderation API ──────────────────────────────────
async def _openai_moderate(message: str) -> dict[str, Any]:
    """Call OpenAI omni-moderation-latest. Returns dict with categories+scores.

    Free of charge. Returns {} on any error so we never fail-closed
    (the regex stage is the safety floor).
    """
    try:
        from app.services.llm_provider import get_client, is_openai_native
        if not is_openai_native():
            # Moderation endpoint only exists on api.openai.com
            return {}
        client = get_client()
        result = await client.moderations.create(
            model="omni-moderation-latest",
            input=message[:4000],
        )
        r = result.results[0]
        return {
            "flagged": bool(r.flagged),
            "categories": {k: bool(v) for k, v in r.categories.model_dump().items()},
            "scores": {k: float(v) for k, v in r.category_scores.model_dump().items()},
        }
    except Exception as e:
        logger.warning("OpenAI moderation failed: %s", e)
        return {}


# ── Stage 3: LLM Legal Classifier (Persönlichkeitsrechte / Datenschutz) ──
_LEGAL_SYSTEM = """Du bist ein juristischer Sicherheits-Klassifikator für einen Bildungs-Chatbot.
Prüfe die Nutzeranfrage auf Verstöße gegen deutsches Recht.
Antworte AUSSCHLIESSLICH mit gültigem JSON nach diesem Schema:
{
  "strafrecht": {"risk": 0.0..1.0, "reason": "kurz"},
  "jugendschutz": {"risk": 0.0..1.0, "reason": "kurz"},
  "persoenlichkeitsrechte": {"risk": 0.0..1.0, "reason": "kurz"},
  "datenschutz": {"risk": 0.0..1.0, "reason": "kurz"}
}

Bewerte realistisch — auch mittelstarke Verstöße sollen ein risk > 0.5 bekommen.
Risk 0 = unauffällig, 0.3 = grenzwertig, 0.6 = klar problematisch, 1 = schwerer Verstoß.

- Strafrecht: Volksverhetzung (§130), Beleidigung (§185), Bedrohung (§241),
  Anleitungen zu Straftaten, Gewaltverherrlichung
- Jugendschutz: Inhalte ungeeignet für Minderjährige, Suizidthemen, exzessive Gewalt
- Persönlichkeitsrechte: Beleidigung, Hassäußerungen (auch gegen Organisationen,
  Marken, Produkte oder Plattformen wie z.B. "ich hasse X"), Rufschädigung,
  Verleumdung, Outing, unerlaubte Personendaten, Doxing
- Datenschutz: PII (Passwörter, Adressen, IDs), Aufforderung zur Preisgabe

WICHTIG: Aussagen wie "ich hasse [Organisation/Plattform/Person]" sind
Persönlichkeitsrechte mit risk >= 0.6 — auch ohne explizite Beleidigung."""


async def _llm_legal_classify(message: str) -> dict[str, dict]:
    """Stage 3: GPT-mini classifier for German legal categories.

    Returns dict like {"strafrecht": {"risk": 0.1, "reason": "..."}, ...}
    """
    try:
        from app.services.llm_provider import get_client, get_chat_model, build_chat_kwargs
        client = get_client()
        resp = await client.chat.completions.create(
            **build_chat_kwargs(
                model=get_chat_model(),
                messages=[
                    {"role": "system", "content": _LEGAL_SYSTEM},
                    {"role": "user", "content": message[:2000]},
                ],
                temperature=0.0,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        out = {}
        for cat in ("strafrecht", "jugendschutz", "persoenlichkeitsrechte", "datenschutz"):
            entry = data.get(cat, {})
            if isinstance(entry, dict):
                out[cat] = {
                    "risk": float(entry.get("risk", 0.0) or 0.0),
                    "reason": str(entry.get("reason", ""))[:200],
                }
        return out
    except Exception as e:
        logger.warning("LLM legal classifier failed: %s", e)
        return {}


# ── Main entry point ────────────────────────────────────────────────
async def assess_safety(message: str, signals: list[str] | None = None) -> SafetyDecision:
    """Multi-stage safety assessment.

    Always runs the regex gate. Eskaliert je nach `escalation.mode` an
    die LLM-Stufen. Failure-mode: jede LLM-Stufe darf scheitern; das
    Regex-Gate bleibt das harte Backstop.
    """
    signals = signals or []
    decision = _regex_gate(message, signals)

    # Bereits hartes High aus Regex → nicht weiter eskalieren, sofort blocken
    if decision.risk_level == "high":
        return decision

    cfg = load_safety_config()
    preset = _resolve_preset(cfg)
    esc = cfg.get("escalation", {}) or {}
    decision.reasons.append(f"level:{preset['level']}")

    # ── Stage: Prompt-Injection (regex, optional per preset) ──────
    if preset["prompt_injection"]:
        decision.stages_run.append("prompt_injection")
        for pat in _INJECTION_PATTERNS:
            if re.search(pat, (message or "").lower()):
                if decision.risk_level == "low":
                    decision.risk_level = "medium"
                decision.reasons.append("possible_prompt_injection")
                if "persoenlichkeitsrechte" not in decision.legal_flags:
                    pass  # injection isn't a legal flag
                break

    # ── Decide which LLM stages to run ────────────────────────────
    run_moderation = _stage_should_run(preset["moderation"], decision.risk_level)
    run_legal = _stage_should_run(preset["legal_classifier"], decision.risk_level)

    # Heuristik-Override: smart-Mode + Triggerwort → Legal trotzdem laufen lassen
    # Nur aktiv wenn das Preset es explizit erlaubt (legal_trigger_override).
    if preset.get("legal_trigger_override") and preset["legal_classifier"] == "smart" and not run_legal:
        msg_lower = (message or "").lower()
        if any(re.search(p, msg_lower) for p in _LEGAL_TRIGGER_PATTERNS):
            run_legal = True
            decision.reasons.append("legal_trigger_match")

    tasks = []
    if run_moderation:
        tasks.append(("openai", _openai_moderate(message)))
        decision.stages_run.append("openai_moderation")
    if run_legal:
        tasks.append(("legal", _llm_legal_classify(message)))
        decision.stages_run.append("llm_legal")

    if not tasks:
        return decision

    decision.escalated = True
    _t0 = time.perf_counter()
    results = await asyncio.gather(*(t[1] for t in tasks), return_exceptions=True)
    _elapsed_ms = (time.perf_counter() - _t0) * 1000
    logger.info(
        "safety stages=%s level=%s took %.0fms",
        ",".join(n for n, _ in tasks), preset["level"], _elapsed_ms,
    )

    openai_data: dict[str, Any] = {}
    legal_data: dict[str, dict] = {}
    for (name, _), res in zip(tasks, results):
        if isinstance(res, Exception):
            continue
        if name == "openai":
            openai_data = res or {}
        elif name == "legal":
            legal_data = res or {}

    # ── Merge OpenAI moderation ───────────────────────────────────
    thresholds = esc.get("thresholds", {}) or {}
    hard_blocks = set(esc.get("hard_block_categories", []) or [])
    tmul = preset.get("threshold_multiplier", 1.0)
    flagged_now: list[str] = []
    if openai_data:
        scores = openai_data.get("scores", {})
        for cat, score in scores.items():
            decision.categories[cat] = score
            thr = float(thresholds.get(cat, 0.95)) * tmul
            if score >= thr:
                flagged_now.append(cat)

    decision.flagged_categories = flagged_now

    # OpenAI-Kategorie → deutsche Rechtsfelder mappen
    cat_to_legal = {
        "self_harm": "jugendschutz",
        "self_harm/intent": "jugendschutz",
        "sexual/minors": "jugendschutz",
        "violence": "strafrecht",
        "violence/graphic": "strafrecht",
        "hate": "strafrecht",
        "hate/threatening": "strafrecht",
        "harassment": "persoenlichkeitsrechte",
        "harassment/threatening": "persoenlichkeitsrechte",
        "illicit": "strafrecht",
        "illicit/violent": "strafrecht",
    }
    for cat in flagged_now:
        legal = cat_to_legal.get(cat)
        if legal and legal not in decision.legal_flags:
            decision.legal_flags.append(legal)

    # Hard-Block-Kategorien sofort high. Wählt Pattern je nach Kategorie:
    #   - self_harm / sexual/minors       → PAT-CRISIS (empathisch)
    #   - hate/threatening / harassment/threatening → PAT-REFUSE-THREAT (sachlich ablehnend)
    #   - illicit/violent                 → PAT-CRISIS (default refusal, siehe config)
    hard_hit = [c for c in flagged_now if c in hard_blocks]
    if hard_hit:
        decision.risk_level = "high"
        # Pattern wählen: wenn ein Threat-Kategorie dabei ist UND keine
        # Selbstgefährdung, nimm das Threat-Pattern. Selbstgefährdung
        # hat immer Vorrang (Schutz hat Vorrang).
        threat_cats = {"hate/threatening", "harassment/threatening"}
        crisis_cats = {"self_harm", "self_harm/intent", "sexual/minors"}
        if set(hard_hit) & crisis_cats:
            decision.enforced_pattern = cfg.get("crisis_pattern", "PAT-CRISIS")
        elif set(hard_hit) & threat_cats:
            decision.enforced_pattern = cfg.get("threat_pattern", "PAT-REFUSE-THREAT")
        else:
            # illicit/violent etc. — generische Zurückweisung über Crisis-Pattern
            decision.enforced_pattern = cfg.get("crisis_pattern", "PAT-CRISIS")
        for t in cfg.get("crisis_blocked_tools", []):
            if t not in decision.blocked_tools:
                decision.blocked_tools.append(t)
        decision.reasons.append(f"hard_block:{','.join(hard_hit)}")

    # ── Merge LLM legal classifier ────────────────────────────────
    legal_thr = esc.get("legal_thresholds", {}) or {}
    flag_thr = float(legal_thr.get("flag", 0.4)) * tmul
    high_thr = float(legal_thr.get("high", 0.7)) * tmul
    if legal_data:
        for cat, entry in legal_data.items():
            risk = entry.get("risk", 0.0)
            reason = entry.get("reason", "")[:80]
            decision.categories[f"legal:{cat}"] = risk
            if risk >= flag_thr:
                if cat not in decision.legal_flags:
                    decision.legal_flags.append(cat)
                if risk >= high_thr and cat in ("strafrecht", "jugendschutz") and decision.risk_level != "high":
                    decision.risk_level = "high"
                    decision.reasons.append(f"legal:{cat} {risk:.2f} ({reason})")
                elif decision.risk_level == "low":
                    decision.risk_level = "medium"
                    decision.reasons.append(f"legal:{cat} {risk:.2f}")

    # ── Downgrade false positives ─────────────────────────────────
    # Prompt-injection hits are kept at medium even when moderation/legal come
    # back clean — the user still deserves the "looks like an instruction,
    # ignoring it" notice.
    if (
        esc.get("downgrade_false_positives", True)
        and decision.risk_level == "medium"
        and not flagged_now
        and not any(e.get("risk", 0) >= 0.5 for e in legal_data.values())
        and "crisis_signal_detected" not in decision.reasons
        and "possible_prompt_injection" not in decision.reasons
    ):
        decision.risk_level = "low"
        decision.reasons.append("downgraded_by_llm_check")

    return decision
