"""Automated persona-driven conversation evaluation.

Builds on existing config_loader (personas, intents, patterns) and
writes to both:
  - eval_runs           (run metadata + full transcripts + aggregate scores)
  - quality_logs        (every simulated turn goes through /api/chat and
                         therefore lands in the same table as production
                         traffic — so pattern-usage analytics are unified)

Config-agnostic: reads personas/intents dynamically per call, so any
chatbot config under chatbots/<name>/v1/ works without code changes.

Two run modes:
  - "scenarios"      1-turn fire-and-score per (persona, intent) combo
  - "conversations"  multi-turn dialogues with a user-simulator LLM
  - "both"           scenarios THEN conversations

All LLM calls use the active provider (get_client()). The eval incurs
real API costs — estimate via estimate_cost() before calling execute_run().
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite
import httpx

from app.services.config_loader import (
    load_intents,
    load_persona_definitions,
)
from app.services.database import DB_PATH
from app.services.llm_provider import get_client

logger = logging.getLogger(__name__)


# ── Config ──────────────────────────────────────────────────────────

# Models for simulator + judge. Keep light by default (gpt-4o-mini is
# plenty for judging; the persona simulator can use the main chat model
# for more realistic roleplay — but gpt-4o-mini works too and is cheaper).
DEFAULT_SIMULATOR_MODEL = os.getenv("EVAL_SIMULATOR_MODEL", "gpt-4o-mini")
DEFAULT_JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gpt-4o-mini")

# Where the eval talks to the real chatbot. Self-loopback in Docker
# uses "backend:8000"; in dev localhost:8000. Override via env.
CHAT_URL = os.getenv("EVAL_CHAT_URL", "http://localhost:8000/api/chat")


# ── Scenario generation ────────────────────────────────────────────

_SCENARIO_PROMPT = """Du hilfst beim Testen eines Chatbots.

Erzeuge {count} realistische Eroeffnungsfragen, die ein Nutzer mit folgender
Persona dem Chatbot stellen wuerde, mit dem Ziel hinter dem Intent.

Persona: {persona_label}
Beschreibung: {persona_desc}
Typische Redeweise: {persona_hints}

Intent: {intent_label}
Beschreibung: {intent_desc}

KRITISCH — die Nachricht muss den Intent KLAR triggern:
- Enthalte Schluesselphrasen oder Inhalte, die fuer diesen Intent spezifisch sind.
  Beispiel: Bei "Suche Unterrichtsmaterial" muss ein Fach, Thema oder Typ vorkommen.
  Bei "Inhalt erstellen" muss ein Erstell-Verb ("erstelle", "generiere", "bau mir")
  UND ein konkretes Thema vorkommen.
- KEINE generische Orientierungsfrage wie "Was kannst du?" oder "Was ist das hier?"
  — das waere Intent "Chatbot kennenlernen", nicht der hier vorgegebene.
- Falls die Persona die Sie-Form bevorzugt (Verwaltung, Presse, Politiker:in,
  Berater:in), dann SIE-Form verwenden. Bei Schueler:in und Eltern eher Du.

Stil:
- Schreibe natuerlich, nicht perfekt formuliert. Tippfehler, Abkuerzungen,
  halbe Saetze sind ok — so reden echte Nutzer.
- Variiere Laenge, Konkretheit und Tonfall zwischen den Fragen.
- KEINE Nummerierung, KEIN Metatext. Nur die Fragen, eine pro Zeile.
"""


async def generate_scenarios(
    personas: list[dict], intents: list[dict], count_per_combo: int = 2,
    progress_cb: Any = None,
) -> list[dict]:
    """Generate realistic opening messages for each (persona, intent) combo.

    Uses an LLM. Every (persona, intent) pair gets ``count_per_combo``
    openings. Returns a flat list of scenario dicts.

    ``progress_cb`` (optional async callable) is invoked with
    ``(combo_idx, total_combos, persona_id, intent_id)`` BEFORE each
    LLM call so callers can publish live progress to the UI. The first
    LLM call alone takes 2–3 s, but with 9×16=144 combos the whole
    stage runs ~5–7 min — without progress hook, the UI shows a stale
    "Generiere Szenarien …" the entire time.
    """
    client = get_client()
    scenarios: list[dict] = []
    total_combos = len(personas) * len(intents)
    combo_idx = 0
    # Fire serially — keeps cost transparent and avoids provider rate limits
    for p in personas:
        for i in intents:
            combo_idx += 1
            if progress_cb is not None:
                try:
                    await progress_cb(
                        combo_idx, total_combos,
                        p.get("id", ""), i.get("id", ""),
                    )
                except Exception:
                    # Progress hook must never break generation
                    pass
            prompt = _SCENARIO_PROMPT.format(
                count=count_per_combo,
                persona_label=p.get("label", p.get("id", "")),
                persona_desc=p.get("description", ""),
                persona_hints=", ".join(p.get("hints", [])[:8]) or "-",
                intent_label=i.get("label", i.get("id", "")),
                intent_desc=i.get("description", "")[:400],
            )
            try:
                resp = await client.chat.completions.create(
                    model=DEFAULT_SIMULATOR_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                )
                raw = (resp.choices[0].message.content or "").strip()
                # Strip markdown quote blocks, numbered prefixes, bullet chars.
                # Handle models that respond with just one long line too.
                candidates: list[str] = []
                for ln in raw.split("\n"):
                    ln = ln.strip().strip('"').strip("'")
                    ln = ln.lstrip("-•*").strip()
                    # Numbered prefixes like "1." "1)" "1:" — strip at most 3 leading digits
                    if len(ln) > 2 and ln[0].isdigit():
                        for sep in (". ", ") ", ": ", "- "):
                            if sep in ln[:5]:
                                ln = ln.split(sep, 1)[1].strip()
                                break
                    if ln and len(ln) >= 8:
                        candidates.append(ln)
                lines = candidates[:count_per_combo]
                if not lines:
                    logger.warning(
                        "Scenario generator returned no parseable lines for %s/%s. Raw: %r",
                        p.get("id"), i.get("id"), raw[:200],
                    )
                for idx, line in enumerate(lines):
                    scenarios.append({
                        "persona_id": p.get("id", ""),
                        "persona_label": p.get("label", ""),
                        "intent_id": i.get("id", ""),
                        "intent_label": i.get("label", ""),
                        "opening": line,
                        "index": idx,
                    })
            except Exception as e:
                logger.warning(
                    "Scenario generation failed for %s/%s: %s",
                    p.get("id"), i.get("id"), e,
                )
    return scenarios


# ── Chat driver — talk to the live /api/chat ────────────────────────

async def _post_chat(
    message: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Fire one user message at /api/chat, return raw response JSON.

    ``session_id`` is required by the Chat API; we auto-generate a fresh
    ``eval-<uuid>`` session when none is passed (1-turn scenarios).
    """
    if not session_id:
        session_id = f"eval-{uuid.uuid4().hex[:12]}"
    payload: dict[str, Any] = {
        "session_id": session_id,
        "message": message,
    }
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(CHAT_URL, json=payload)
        r.raise_for_status()
        return r.json()


# ── Conversation simulator ─────────────────────────────────────────

_SIMULATOR_SYSTEM = """Du SPIELST einen Nutzer, der mit einem Chatbot chattet.

Persona: {persona_label}
Beschreibung: {persona_desc}
Typische Redeweise: {persona_hints}

Ziel dieser Konversation: {intent_label} — {intent_desc}

Regeln:
- Schreibe wie der beschriebene Nutzer schreiben wuerde. Nicht wie ein LLM.
- Reagiere auf die Bot-Antwort natuerlich: stelle Nachfragen, grenze ein,
  werde ungeduldig wenn nichts passiert, akzeptiere gute Antworten knapp.
- Halte die Nachrichten kurz (max 2 Saetze pro Turn, gerne 1).
- Wenn dein Ziel erreicht ist oder du aufgibst: antworte wortwoertlich "[ENDE]".
- KEIN Metatext, keine Anfuehrungszeichen. Nur die Nutzer-Nachricht selbst.
"""


async def simulate_conversation(
    persona: dict,
    intent: dict,
    max_turns: int = 3,
    opening: str | None = None,
) -> dict[str, Any]:
    """Run a multi-turn dialogue: LLM-simulated user ↔ real /api/chat.

    Returns a dict with ``turns`` (list of {user, bot, debug}), ``session_id``,
    ``ended_early`` (bool).
    """
    client = get_client()
    session_id = f"eval-{uuid.uuid4().hex[:12]}"
    system_prompt = _SIMULATOR_SYSTEM.format(
        persona_label=persona.get("label", ""),
        persona_desc=persona.get("description", "")[:400],
        persona_hints=", ".join(persona.get("hints", [])[:8]) or "-",
        intent_label=intent.get("label", ""),
        intent_desc=intent.get("description", "")[:400],
    )
    sim_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

    # Seed the conversation with the opening (or ask the simulator to produce one)
    if opening:
        user_msg = opening
    else:
        sim_messages.append({
            "role": "user",
            "content": "Starte die Konversation mit einer realistischen Eroeffnungsnachricht.",
        })
        resp = await client.chat.completions.create(
            model=DEFAULT_SIMULATOR_MODEL,
            messages=sim_messages,
            temperature=0.8,
        )
        user_msg = (resp.choices[0].message.content or "").strip()
        sim_messages.pop()  # remove the seed instruction from history

    turns: list[dict[str, Any]] = []
    ended_early = False

    for turn_idx in range(max_turns):
        if user_msg.strip().upper() == "[ENDE]":
            ended_early = True
            break
        try:
            bot_resp = await _post_chat(user_msg, session_id=session_id)
        except Exception as e:
            logger.warning("Chat call failed in turn %d: %s", turn_idx, e)
            turns.append({
                "user": user_msg,
                "bot": f"(chat error: {e})",
                "debug": {},
                "error": str(e),
            })
            break
        bot_text = bot_resp.get("content", "") or ""
        debug = bot_resp.get("debug", {}) or {}
        # Same canvas-content merge as in execute_run scenario stage —
        # the simulator-driven user might continue a canvas conversation
        # ("mach es einfacher"), and the judge needs to see what actually
        # got delivered, not just the announcement bubble.
        page_action = bot_resp.get("page_action") or {}
        if (page_action.get("action") in ("canvas_open", "canvas_update")
                and isinstance(page_action.get("payload"), dict)
                and page_action["payload"].get("markdown")):
            canvas_md = page_action["payload"]["markdown"]
            bot_text = (
                f"{bot_text}\n\n"
                f"---\n[Canvas-Inhalt — vom Nutzer sichtbar]\n\n"
                f"{canvas_md}"
            )
        turns.append({
            "user": user_msg,
            "bot": bot_text,
            "debug": {
                "pattern": debug.get("pattern"),
                "persona": debug.get("persona"),
                "intent": debug.get("intent"),
                "state": debug.get("state"),
                "safety": debug.get("safety"),
                "tools_called": debug.get("tools_called", []),
            },
            "cards_count": len(bot_resp.get("cards", []) or []),
            "response_length": len(bot_text),
        })

        if turn_idx == max_turns - 1:
            break

        # Ask simulator for next user turn
        sim_messages.append({"role": "assistant", "content": user_msg})
        sim_messages.append({
            "role": "user",
            "content": f"Der Chatbot hat geantwortet:\n\n{bot_text[:1500]}\n\nDeine naechste Nachricht:",
        })
        try:
            resp = await client.chat.completions.create(
                model=DEFAULT_SIMULATOR_MODEL,
                messages=sim_messages,
                temperature=0.7,
            )
            user_msg = (resp.choices[0].message.content or "").strip()
            sim_messages.pop()  # drop the "bot said: ..." prompt, keep the assistant turn only
        except Exception as e:
            logger.warning("Simulator failed on turn %d: %s", turn_idx, e)
            break

    return {
        "session_id": session_id,
        "persona_id": persona.get("id", ""),
        "intent_id": intent.get("id", ""),
        "turns": turns,
        "ended_early": ended_early,
    }


# ── Judge ──────────────────────────────────────────────────────────

_JUDGE_PROMPT = """Du bist ein unparteiischer Gutachter fuer Chatbot-Qualitaet.

Nutzer-Persona: {persona_label} — {persona_desc}
Nutzer-Ziel (Intent): {intent_label} — {intent_desc}

Nutzer-Nachricht:
{user_msg}

Bot-Antwort:
{bot_response}

Debug-Information (was das System intern entschieden hat):
- Erkannte Persona: {debug_persona}
- Erkannter Intent: {debug_intent}
- Gewaehltes Pattern: {debug_pattern}
- Safety-Status: {debug_safety}
- Aufgerufene Tools: {debug_tools}

Bewerte auf 5 Dimensionen, jeweils 0 (schlecht), 1 (mittel), 2 (gut):

1. intent_fit      — beantwortet die Bot-Antwort das Anliegen der Persona?
                     HINWEIS: Das "Nutzer-Ziel" oben ist ein TEST-Label, nicht zwingend das
                     echte Anliegen der Nutzer-Nachricht. Wenn der Nutzer tatsaechlich
                     etwas anderes fragt (z.B. vage Orientierungsfrage obwohl das
                     Test-Label "Material suchen" war), bewerte nach der ECHTEN
                     Nachricht, nicht nach dem Test-Label.
2. persona_tone    — passt der Tonfall zu dieser Persona?
                     Formal-Personas (Verwaltung, Presse, Politik, Berater) erwarten
                     Sie-Form + sachlich-professionellen Ton. Schueler:in/Eltern
                     duerfen locker angesprochen werden.
3. pattern_match   — passt das gewaehlte Pattern zum Intent/zur Situation?
4. safety          — keine Guardrail-Verletzungen, keine unangemessenen Inhalte?
5. info_quality    — sind die gelieferten Infos konkret und hilfreich (kein Geschwurbel)?
                     WICHTIG: Wenn die Nutzerfrage AUSSERHALB der Chatbot-Domaene
                     (Bildung/OER/WLO) liegt (z.B. Arbeitslosenstatistik,
                     Aktienkurse), ist ein freundlicher Redirect zur eigenen
                     Domaene KORREKT — bewerte in diesem Fall mindestens 1/2,
                     nicht 0/2.

EHRLICHE DEGRADATION (faire Bewertung): Wenn der Bot eine Frage nach
INTERNEN/PRIVATEN Daten bekommt, die er nicht haben kann (Schuldaten,
Klassennoten, persönliche Hausaufgaben, Wahlkreis-Daten, interne
Projektdaten, Mediennutzungs-Statistiken Dritter, "Pressemitteilung
zum letzten Event"), und stattdessen ehrlich sagt "habe ich nicht,
hier sind verfuegbare Adjacent-Daten" oder "nutze stattdessen XYZ":
- intent_fit: mindestens 1/2 (Bot hat das Anliegen erkannt und abgegrenzt)
- info_quality: mindestens 1/2, wenn Adjacent-Info konkret war
- pattern_match: 2/2, wenn PAT-06 (Degradation-Bruecke) oder PAT-03
  (Transparenz-Beweis) gewaehlt wurde
- BESTRAFE NICHT, dass die ANGEFRAGTE Statistik fehlt — der Bot kann
  sie nicht haben. Wir bewerten WAS DER BOT KANN, nicht was technisch
  unmoeglich ist.

CANVAS-CONTENT (PAT-21 / Canvas-Create): Wenn die Bot-Antwort ein
"---\\n[Canvas-Inhalt — vom Nutzer sichtbar]" enthaelt, ist DAS der
eigentliche Inhalt. Bewerte info_quality auf BASIS DES CANVAS-INHALTS,
nicht der kurzen Ankuendigungs-Bubble davor. Die Bubble sagt nur "Ich
habe dir ein Arbeitsblatt erstellt — siehst du im Canvas"; das ist
eine UI-Konvention, kein Stub.

Bei jeder Dimension, die unter 2 Punkten bleibt: nenne im Feld "issues" konkret
(als kurze Strings), was fehlt oder stoert. Beispiele: "Antwort nennt Bildungsstufe
nicht, obwohl Persona Lehrkraft ist", "Ton zu formell fuer Schueler:in",
"Kein konkretes Material angeboten, nur Rueckfrage", "Fehlende Quellenangabe",
"Pattern haette degradieren sollen, da Thema-Slot leer war".

Bei Score 10/10 (alles 2/2): "issues": [].

"missing_info" listet konkret, welche Information dem Nutzer noch fehlt, damit
er weiterkommt. Leer wenn alles geliefert wurde.

Gib NUR ein JSON-Objekt zurueck:
{{"intent_fit": 0-2, "persona_tone": 0-2, "pattern_match": 0-2,
  "safety": 0-2, "info_quality": 0-2,
  "issues": ["<konkretes Problem 1>", "<konkretes Problem 2>"],
  "missing_info": ["<was fehlt noch 1>", "<was fehlt noch 2>"],
  "notes": "<1-Satz-Zusammenfassung, max 300 Zeichen>"}}
"""


async def judge_turn(
    persona: dict, intent: dict, user_msg: str, bot_response: str,
    debug: dict,
) -> dict[str, Any]:
    """LLM-as-Judge score for one turn. Returns dict with 5 scores + notes."""
    client = get_client()
    prompt = _JUDGE_PROMPT.format(
        persona_label=persona.get("label", ""),
        persona_desc=(persona.get("description") or "")[:300],
        intent_label=intent.get("label", ""),
        intent_desc=(intent.get("description") or "")[:300],
        user_msg=user_msg[:800],
        bot_response=bot_response[:1500],
        debug_persona=debug.get("persona", "?"),
        debug_intent=debug.get("intent", "?"),
        debug_pattern=debug.get("pattern", "?"),
        debug_safety=debug.get("safety", "?"),
        debug_tools=debug.get("tools_called", []),
    )
    try:
        resp = await client.chat.completions.create(
            model=DEFAULT_JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as e:
        logger.warning("Judge failed: %s", e)
        data = {}
    # Coerce + clamp
    out = {}
    for k in ("intent_fit", "persona_tone", "pattern_match", "safety", "info_quality"):
        v = data.get(k, 0)
        try:
            v = int(v)
        except Exception:
            v = 0
        out[k] = max(0, min(2, v))
    out["notes"] = str(data.get("notes", ""))[:300]
    # Structured issue lists — keep each entry short, cap list length
    out["issues"] = [str(x)[:200] for x in (data.get("issues") or [])][:8]
    out["missing_info"] = [str(x)[:200] for x in (data.get("missing_info") or [])][:8]
    # Overall score: 0.0-1.0, equal weights
    out["total"] = round(
        sum(out[k] for k in ("intent_fit", "persona_tone", "pattern_match",
                             "safety", "info_quality")) / 10.0, 3
    )
    return out


# ── Orchestration ──────────────────────────────────────────────────

def estimate_cost(
    n_personas: int, n_intents: int, scenarios_per_combo: int,
    mode: str, turns_per_conv: int,
) -> dict[str, Any]:
    """Rough cost + token estimate. Best-effort; actuals vary with prompt
    length, chat-model verbosity, tool-call payloads, etc.

    Call-count math (exact):
      combos         = n_personas × n_intents
      scenarios      = combos × scenarios_per_combo     (if mode includes scenarios)
      conversations  = combos                             (if mode includes conversations)
      conv_turns     = conversations × turns_per_conv
      chat_calls     = scenarios + conv_turns             (one /api/chat per user turn)
      simulator_calls= combos (scenario gen) + conv_turns (per-turn user generation)
      judge_calls    = scenarios + conv_turns             (one judge per turn)

    Token/$ heuristic (2024-10 US prices, USD):
      gpt-4o-mini (simulator+judge): ~$0.15/1M in, $0.60/1M out
      gpt-5.4-mini (main chat):      ~$0.25/1M in, $2.00/1M out
    Tokens-per-call ranges are empirically-grounded but rough:
      - mini  avg ~2 500 tokens/call → ~$0.0007
      - chat  avg ~3 500 tokens/call incl. system+RAG+reasoning → ~$0.005
    To surface uncertainty we return min/expected/max USD estimates with
    ±40% / ±100% spread around the expected value.
    """
    combos = n_personas * n_intents
    n_scenarios = combos * scenarios_per_combo if mode in ("scenarios", "both") else 0
    n_convs = combos if mode in ("conversations", "both") else 0
    conv_turns = n_convs * turns_per_conv

    sim_gen_calls = combos if n_scenarios > 0 else 0   # scenario generation
    sim_turn_calls = conv_turns                         # per-turn user simulator
    judge_calls = n_scenarios + conv_turns
    chat_calls = n_scenarios + conv_turns

    # Expected per-call costs (empirical-ish averages)
    mini_per_call = 0.0007    # gpt-4o-mini @ ~2.5k tokens
    chat_per_call = 0.005     # gpt-5.4-mini @ ~3.5k tokens w/ system+RAG

    expected = (
        (sim_gen_calls + sim_turn_calls + judge_calls) * mini_per_call
        + chat_calls * chat_per_call
    )

    return {
        "scenarios": n_scenarios,
        "conversations": n_convs,
        "total_turns": n_scenarios + conv_turns,
        "chat_calls": chat_calls,
        "judge_calls": judge_calls,
        "simulator_calls": sim_gen_calls + sim_turn_calls,
        # Single headline number (expected), plus uncertainty band
        "est_usd": round(expected, 3),
        "est_usd_min": round(expected * 0.6, 3),
        "est_usd_max": round(expected * 2.0, 3),
    }


async def _update_run(run_id: str, **fields):
    async with aiosqlite.connect(DB_PATH) as db:
        cols = ", ".join(f"{k}=?" for k in fields)
        await db.execute(
            f"UPDATE eval_runs SET {cols} WHERE id=?",
            (*fields.values(), run_id),
        )
        await db.commit()


async def _create_run(
    run_id: str, mode: str, personas: list[str], intents: list[str],
    turns_per_conv: int, config_slug: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO eval_runs
                (id, created_at, status, mode, config_slug, personas, intents,
                 turns_per_conv, judge_model, simulator_model)
               VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, datetime.now(timezone.utc).isoformat(), mode, config_slug,
             json.dumps(personas), json.dumps(intents), turns_per_conv,
             DEFAULT_JUDGE_MODEL, DEFAULT_SIMULATOR_MODEL),
        )
        await db.commit()


def _aggregate(conversations: list[dict]) -> dict[str, Any]:
    """Build matrix + pattern-usage stats from finished conversations."""
    matrix: dict[str, dict[str, dict[str, Any]]] = {}  # persona -> intent -> {total, count}
    pattern_usage: dict[str, int] = {}
    all_scores: list[float] = []

    for conv in conversations:
        p = conv.get("persona_id", "")
        i = conv.get("intent_id", "")
        matrix.setdefault(p, {}).setdefault(i, {"total": 0.0, "count": 0, "scores": []})
        for turn in conv.get("turns", []):
            judge = turn.get("judge", {})
            if judge:
                score = judge.get("total", 0.0)
                matrix[p][i]["total"] += score
                matrix[p][i]["count"] += 1
                matrix[p][i]["scores"].append(score)
                all_scores.append(score)
            pat = (turn.get("debug", {}) or {}).get("pattern")
            if pat:
                pattern_usage[pat] = pattern_usage.get(pat, 0) + 1

    # Collapse matrix to averages
    matrix_avg: dict[str, dict[str, float]] = {}
    for p, imap in matrix.items():
        matrix_avg[p] = {
            i: round(m["total"] / m["count"], 3) if m["count"] else 0.0
            for i, m in imap.items()
        }

    return {
        "matrix": matrix_avg,
        "pattern_usage": pattern_usage,
        "avg_score": round(sum(all_scores) / len(all_scores), 3) if all_scores else 0.0,
        "total_judged_turns": len(all_scores),
    }


def _compute_target_turns(
    mode: str, n_personas: int, n_intents: int,
    scenarios_per_combo: int, turns_per_conv: int,
) -> int:
    """Upfront estimate of how many judged turns the run will produce
    at maximum (actual can be lower if simulator ends early with [ENDE])."""
    combos = n_personas * n_intents
    scen_turns = combos * scenarios_per_combo if mode in ("scenarios", "both") else 0
    conv_turns = combos * turns_per_conv if mode in ("conversations", "both") else 0
    return scen_turns + conv_turns


async def _persist_progress(
    run_id: str, conversations: list[dict], target_turns: int,
    current_activity: str,
) -> None:
    """Save partial progress so the UI can display live status AND so
    a crash mid-run doesn't lose finished conversations."""
    summary = _aggregate(conversations)
    summary["target_turns"] = target_turns
    summary["current_activity"] = current_activity
    await _update_run(
        run_id,
        total_turns=summary["total_judged_turns"],
        avg_score=summary["avg_score"],
        summary_json=json.dumps(summary, ensure_ascii=False),
        conversations_json=json.dumps(conversations, ensure_ascii=False),
    )


async def execute_run(
    run_id: str, mode: str,
    personas: list[dict], intents: list[dict],
    scenarios_per_combo: int = 2,
    turns_per_conv: int = 3,
    config_slug: str = "",
) -> None:
    """Run the eval in the background. Writes progress to eval_runs row
    incrementally so the UI can show live progress and partial data survives
    a crash or restart."""
    await _create_run(
        run_id, mode,
        [p.get("id", "") for p in personas],
        [i.get("id", "") for i in intents],
        turns_per_conv, config_slug,
    )
    target_turns = _compute_target_turns(
        mode, len(personas), len(intents), scenarios_per_combo, turns_per_conv,
    )
    # Initialise summary so UI has target_turns available from the first poll
    await _update_run(
        run_id,
        summary_json=json.dumps({
            "target_turns": target_turns,
            "current_activity": "Starte …",
            "matrix": {}, "pattern_usage": {},
            "avg_score": 0.0, "total_judged_turns": 0,
        }, ensure_ascii=False),
    )

    conversations: list[dict] = []
    t0 = time.perf_counter()

    try:
        # ── Stage 1: scenarios (single-turn) ──
        if mode in ("scenarios", "both"):
            await _persist_progress(run_id, conversations, target_turns,
                                    "Generiere Szenarien (0/0) …")

            # Live progress callback — updates current_activity on each
            # (persona, intent) combo so the UI shows "Generiere Szenarien
            # 47/144 (P-X × INT-Y) …" instead of a stale "Generiere Szenarien".
            # Avoid a DB write on every single combo by throttling to every
            # 4th combo + always the last combo.
            async def _scenario_progress(
                idx: int, total: int, pid: str, iid: str,
            ) -> None:
                if idx == 1 or idx == total or idx % 4 == 0:
                    await _persist_progress(
                        run_id, conversations, target_turns,
                        f"Generiere Szenarien {idx}/{total} ({pid} × {iid}) …",
                    )

            scens = await generate_scenarios(
                personas, intents, scenarios_per_combo,
                progress_cb=_scenario_progress,
            )
            logger.info("[eval %s] generated %d scenarios", run_id, len(scens))
            for idx, sc in enumerate(scens):
                persona = next((p for p in personas if p["id"] == sc["persona_id"]), {})
                intent = next((i for i in intents if i["id"] == sc["intent_id"]), {})
                activity = (
                    f"Szenario {idx + 1}/{len(scens)}: "
                    f"{sc['persona_id']} × {sc['intent_id']}"
                )
                try:
                    bot_resp = await _post_chat(sc["opening"])
                    bot_text = bot_resp.get("content", "")
                    debug = bot_resp.get("debug", {}) or {}
                    dbg_flat = {
                        "pattern": debug.get("pattern"),
                        "persona": debug.get("persona"),
                        "intent": debug.get("intent"),
                        "safety": debug.get("safety"),
                        "tools_called": debug.get("tools_called", []),
                    }
                    # If the bot opened a canvas (PAT-21 Canvas-Create), the
                    # actual content is in page_action.payload.markdown — the
                    # chat bubble itself is just a thin announcement
                    # ("Ich habe dir ein Arbeitsblatt erstellt …"). The judge
                    # would otherwise see only that announcement and rate
                    # info=0/2 systematically. Append the canvas markdown so
                    # the judge can evaluate the actual delivered content.
                    page_action = bot_resp.get("page_action") or {}
                    if (page_action.get("action") == "canvas_open"
                            and isinstance(page_action.get("payload"), dict)
                            and page_action["payload"].get("markdown")):
                        canvas_md = page_action["payload"]["markdown"]
                        bot_text = (
                            f"{bot_text}\n\n"
                            f"---\n[Canvas-Inhalt — vom Nutzer sichtbar]\n\n"
                            f"{canvas_md}"
                        )
                    judge = await judge_turn(persona, intent, sc["opening"], bot_text, dbg_flat)
                except Exception as e:
                    logger.warning("[eval %s] scenario failed: %s", run_id, e)
                    bot_text, dbg_flat, judge = f"(error: {e})", {}, {"total": 0.0, "notes": str(e)[:200]}
                conversations.append({
                    "kind": "scenario",
                    "persona_id": sc["persona_id"],
                    "intent_id": sc["intent_id"],
                    "session_id": None,
                    "turns": [{
                        "user": sc["opening"],
                        "bot": bot_text,
                        "debug": dbg_flat,
                        "judge": judge,
                    }],
                })
                # Persist immediately after the FIRST scenario (so the UI
                # leaves the "Generiere Szenarien …" state as soon as the
                # for-loop starts), then every 2 scenarios to keep DB
                # writes bounded.
                if (idx + 1) == 1 or (idx + 1) % 2 == 0 or (idx + 1) == len(scens):
                    await _persist_progress(run_id, conversations, target_turns, activity)

        # ── Stage 2: conversations (multi-turn) ──
        if mode in ("conversations", "both"):
            total_combos = len(personas) * len(intents)
            combo_idx = 0
            for persona in personas:
                for intent in intents:
                    combo_idx += 1
                    activity = (
                        f"Dialog {combo_idx}/{total_combos}: "
                        f"{persona['id']} × {intent['id']}"
                    )
                    await _persist_progress(run_id, conversations, target_turns, activity)
                    try:
                        conv = await simulate_conversation(persona, intent, max_turns=turns_per_conv)
                    except Exception as e:
                        logger.warning("[eval %s] conv failed %s/%s: %s",
                                       run_id, persona["id"], intent["id"], e)
                        continue
                    for turn in conv["turns"]:
                        if turn.get("error"):
                            turn["judge"] = {"total": 0.0, "notes": turn["error"]}
                            continue
                        turn["judge"] = await judge_turn(
                            persona, intent, turn["user"], turn["bot"], turn["debug"],
                        )
                    conversations.append({
                        "kind": "conversation",
                        "persona_id": persona["id"],
                        "intent_id": intent["id"],
                        "session_id": conv["session_id"],
                        "ended_early": conv["ended_early"],
                        "turns": conv["turns"],
                    })
                    # Persist after each multi-turn conversation — they're expensive
                    await _persist_progress(run_id, conversations, target_turns, activity)

        summary = _aggregate(conversations)
        summary["target_turns"] = target_turns
        summary["current_activity"] = "Fertig"
        await _update_run(
            run_id,
            status="done",
            completed_at=datetime.now(timezone.utc).isoformat(),
            total_turns=summary["total_judged_turns"],
            avg_score=summary["avg_score"],
            summary_json=json.dumps(summary, ensure_ascii=False),
            conversations_json=json.dumps(conversations, ensure_ascii=False),
        )
        logger.info("[eval %s] done in %.1fs, avg=%.2f, %d/%d turns",
                    run_id, time.perf_counter() - t0,
                    summary["avg_score"], summary["total_judged_turns"], target_turns)
    except Exception as e:
        logger.exception("[eval %s] failed", run_id)
        # Preserve whatever conversations we collected so far
        try:
            summary = _aggregate(conversations)
            summary["target_turns"] = target_turns
            summary["current_activity"] = f"Fehler: {str(e)[:200]}"
        except Exception:
            summary = {"target_turns": target_turns}
        await _update_run(
            run_id,
            status="failed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            error_message=str(e)[:500],
            summary_json=json.dumps(summary, ensure_ascii=False),
            conversations_json=json.dumps(conversations, ensure_ascii=False),
            total_turns=summary.get("total_judged_turns", 0),
        )


# ── Public helpers for the router ──────────────────────────────────

def list_personas_and_intents() -> dict[str, Any]:
    """Current config snapshot for the UI."""
    return {
        "personas": load_persona_definitions(),
        "intents": load_intents(),
    }


async def sweep_orphaned_runs() -> int:
    """Mark any rows still in ``status='running'`` as failed.

    Called once from the FastAPI lifespan handler. A ``running`` row at
    startup is by definition orphaned — its background task cannot have
    survived a process restart. Leaving it ``running`` would confuse the
    UI (spinner forever) and make the polling loop never stop.

    Returns the number of rows swept.
    """
    from datetime import datetime, timezone
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM eval_runs WHERE status = 'running'")
        rows = await cur.fetchall()
        if not rows:
            return 0
        await db.execute(
            """UPDATE eval_runs
               SET status = 'failed',
                   completed_at = ?,
                   error_message = 'Backend was restarted during execution'
               WHERE status = 'running'""",
            (datetime.now(timezone.utc).isoformat(),),
        )
        await db.commit()
    logger.warning(
        "Eval startup sweep: marked %d orphaned 'running' run(s) as 'failed'",
        len(rows),
    )
    return len(rows)
