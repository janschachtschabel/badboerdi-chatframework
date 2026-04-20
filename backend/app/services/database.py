"""SQLite database for sessions, memory (short+long term), and RAG chunks."""

from __future__ import annotations

import json
import os
import struct
import time
from datetime import datetime
from typing import Any

import aiosqlite
import sqlite_vec

DB_PATH = os.getenv("DATABASE_PATH", "badboerdi.db")

EMBED_DIM = 1536  # text-embedding-3-small


def _make_vec_connector(db_path: str = DB_PATH):
    """Return a connector callable that creates sqlite3 connections with sqlite-vec loaded."""
    import sqlite3

    def connector() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn

    return connector


def _connect_vec(db_path: str = DB_PATH) -> aiosqlite.Connection:
    """Create an aiosqlite connection with sqlite-vec pre-loaded."""
    return aiosqlite.Connection(_make_vec_connector(db_path), iter_chunk_size=64)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    persona_id   TEXT DEFAULT '',
    state_id     TEXT DEFAULT 'state-1',
    entities     TEXT DEFAULT '{}',
    signal_history TEXT DEFAULT '[]',
    turn_count   INTEGER DEFAULT 0,
    created_at   TEXT,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    cards_json   TEXT DEFAULT '[]',
    debug_json   TEXT DEFAULT '{}',
    created_at   TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS memory (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    key          TEXT NOT NULL,
    value        TEXT NOT NULL,
    memory_type  TEXT DEFAULT 'short',
    created_at   TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    area         TEXT NOT NULL,
    title        TEXT DEFAULT '',
    source       TEXT DEFAULT '',
    chunk_index  INTEGER DEFAULT 0,
    content      TEXT NOT NULL,
    embedding    BLOB,
    created_at   TEXT
);

CREATE TABLE IF NOT EXISTS safety_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    ip           TEXT DEFAULT '',
    risk_level   TEXT DEFAULT 'low',
    stages_run   TEXT DEFAULT '[]',
    reasons      TEXT DEFAULT '[]',
    legal_flags  TEXT DEFAULT '[]',
    flagged_categories TEXT DEFAULT '[]',
    blocked_tools TEXT DEFAULT '[]',
    enforced_pattern TEXT DEFAULT '',
    escalated    INTEGER DEFAULT 0,
    rate_limited INTEGER DEFAULT 0,
    message      TEXT DEFAULT '',
    categories_json TEXT DEFAULT '{}',
    created_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_session ON memory(session_id);
CREATE INDEX IF NOT EXISTS idx_rag_area ON rag_chunks(area);
CREATE TABLE IF NOT EXISTS meta (
    key          TEXT PRIMARY KEY,
    value        TEXT NOT NULL,
    updated_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_safety_logs_session ON safety_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_safety_logs_created ON safety_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_safety_logs_risk ON safety_logs(risk_level);

CREATE TABLE IF NOT EXISTS quality_logs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT NOT NULL,
    turn_count        INTEGER DEFAULT 0,
    -- Classification
    persona_id        TEXT DEFAULT '',
    intent_id         TEXT DEFAULT '',
    intent_confidence REAL DEFAULT 0.0,
    final_confidence  REAL DEFAULT 0.0,
    turn_type         TEXT DEFAULT '',
    state_id          TEXT DEFAULT '',
    signals           TEXT DEFAULT '[]',
    entities          TEXT DEFAULT '{}',
    -- Pattern selection
    pattern_id        TEXT DEFAULT '',
    pattern_label     TEXT DEFAULT '',
    phase2_winner_score REAL DEFAULT 0.0,
    phase2_runner_up    TEXT DEFAULT '',
    phase2_score_gap    REAL DEFAULT 0.0,
    eliminated_count  INTEGER DEFAULT 0,
    candidate_count   INTEGER DEFAULT 0,
    -- Response quality
    response_length   INTEGER DEFAULT 0,
    cards_count       INTEGER DEFAULT 0,
    tools_called      TEXT DEFAULT '[]',
    tool_outcomes     TEXT DEFAULT '[]',
    -- Modulations applied
    length_setting    TEXT DEFAULT '',
    degradation       INTEGER DEFAULT 0,
    missing_slots     TEXT DEFAULT '[]',
    -- Context
    page              TEXT DEFAULT '',
    device            TEXT DEFAULT '',
    message           TEXT DEFAULT '',
    -- Full debug for deep analysis
    debug_json        TEXT DEFAULT '{}',
    created_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_quality_logs_session ON quality_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_quality_logs_created ON quality_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_quality_logs_pattern ON quality_logs(pattern_id);
CREATE INDEX IF NOT EXISTS idx_quality_logs_intent ON quality_logs(intent_id);
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    # First: create regular tables (no vec extension needed)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()

    # Second: create vec0 virtual table (needs sqlite-vec extension)
    async with _connect_vec() as db:
        try:
            await db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS rag_vec USING vec0("
                f"  chunk_id INTEGER PRIMARY KEY, "
                f"  embedding float[{EMBED_DIM}]"
                f")"
            )
        except Exception:
            pass  # Already exists

        await db.commit()

        # Migrate existing embeddings from rag_chunks.embedding BLOB → rag_vec
        await _migrate_embeddings_to_vec(db)

    # Import RAG seed if database is empty
    await _import_rag_seed_if_empty()


import logging as _logging

_db_logger = _logging.getLogger(__name__)

# Seed file paths (checked in order)
_SEED_PATHS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "knowledge", "rag-seed.json"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "chatbots", "wlo", "v1", "05-knowledge", "rag-seed.json"),
]


async def _get_meta(db: aiosqlite.Connection, key: str) -> str | None:
    """Read a value from the meta table."""
    cursor = await db.execute("SELECT value FROM meta WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row[0] if row else None


async def _set_meta(db: aiosqlite.Connection, key: str, value: str):
    """Write a value to the meta table."""
    await db.execute(
        "INSERT OR REPLACE INTO meta (key, value, updated_at) VALUES (?, ?, ?)",
        (key, value, datetime.utcnow().isoformat()),
    )


async def _import_rag_seed_if_empty():
    """Import RAG seed data — version-aware with area-level diffing.

    Behaviour:
    - Empty DB → full import of all seed chunks.
    - DB has data but seed version is newer → import only NEW areas
      (areas that exist in the seed but not yet in the DB). Existing areas
      that the user may have edited via Studio are never overwritten.
    - DB seed version matches → skip (nothing to do).

    Chunks are imported without embeddings; embeddings are generated in a
    background task after startup (requires LLM API key).
    """
    # Find seed file
    seed_path = None
    for p in _SEED_PATHS:
        if os.path.isfile(p):
            seed_path = p
            break

    if not seed_path:
        _db_logger.info("No RAG seed file found, starting with empty knowledge base")
        return

    # Load seed data
    with open(seed_path, "r", encoding="utf-8") as f:
        seed = json.load(f)

    seed_version = seed.get("version", "0")
    chunks = seed.get("chunks", [])
    if not chunks:
        return

    # Compare versions
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        stored_version = await _get_meta(db, "seed_version")

        if stored_version == seed_version:
            _db_logger.info("Seed version %s already imported, skipping", seed_version)
            return

        # Find which areas already exist in DB
        cursor = await db.execute("SELECT DISTINCT area FROM rag_chunks")
        existing_areas = {row[0] for row in await cursor.fetchall()}

        # Determine which seed areas are new
        seed_areas = {c["area"] for c in chunks}
        new_areas = seed_areas - existing_areas

        if not new_areas and existing_areas:
            _db_logger.info(
                "Seed version %s → %s: all %d areas already exist, updating version marker only",
                stored_version or "(none)", seed_version, len(seed_areas),
            )
            await _set_meta(db, "seed_version", seed_version)
            await db.commit()
            return

        # Filter chunks to only new areas
        chunks_to_import = [c for c in chunks if c["area"] in new_areas] if existing_areas else chunks

        _db_logger.info(
            "Seed version %s → %s: importing %d chunks in %d new area(s): %s",
            stored_version or "(none)", seed_version,
            len(chunks_to_import), len(new_areas) if existing_areas else len(seed_areas),
            ", ".join(sorted(new_areas) if existing_areas else sorted(seed_areas)),
        )

        for c in chunks_to_import:
            await db.execute(
                "INSERT INTO rag_chunks (area, title, source, chunk_index, content, embedding, created_at) "
                "VALUES (?, ?, ?, ?, ?, NULL, ?)",
                (c["area"], c.get("title", ""), c.get("source", ""),
                 c.get("chunk_index", 0), c["content"], datetime.utcnow().isoformat()),
            )

        await _set_meta(db, "seed_version", seed_version)
        await db.commit()

    _db_logger.info(
        "Seed import complete: %d chunks (embeddings will be generated in background)",
        len(chunks_to_import),
    )


async def _migrate_embeddings_to_vec(db: aiosqlite.Connection):
    """One-time migration: copy embeddings from rag_chunks BLOB to rag_vec virtual table."""
    # Check if there are rag_chunks with embeddings not yet in rag_vec
    cursor = await db.execute(
        "SELECT r.id, r.embedding FROM rag_chunks r "
        "WHERE r.embedding IS NOT NULL "
        "AND r.id NOT IN (SELECT chunk_id FROM rag_vec)"
    )
    rows = await cursor.fetchall()
    if not rows:
        return

    for row in rows:
        chunk_id = row[0]
        emb_blob = row[1]
        if emb_blob and len(emb_blob) == EMBED_DIM * 4:  # float32 = 4 bytes
            await db.execute(
                "INSERT INTO rag_vec (chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, emb_blob),
            )
    await db.commit()


# ── Session helpers ─────────────────────────────────────────────

async def get_or_create_session(session_id: str) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = await cursor.fetchone()
        if row:
            return dict(row)
        now = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT INTO sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            (session_id, now, now),
        )
        await db.commit()
        return {
            "session_id": session_id,
            "persona_id": "",
            "state_id": "state-1",
            "entities": "{}",
            "signal_history": "[]",
            "turn_count": 0,
            "created_at": now,
            "updated_at": now,
        }


async def update_session(session_id: str, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values())
    vals.append(datetime.utcnow().isoformat())
    vals.append(session_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE sessions SET {sets}, updated_at = ? WHERE session_id = ?",
            vals,
        )
        await db.commit()


# ── Safety log helpers ─────────────────────────────────────────

async def log_safety_event(
    session_id: str,
    message: str,
    decision: Any,
    ip: str = "",
    rate_limited: bool = False,
) -> None:
    """Persist a safety decision row. Truncates message to 500 chars."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO safety_logs ("
            "  session_id, ip, risk_level, stages_run, reasons, legal_flags,"
            "  flagged_categories, blocked_tools, enforced_pattern, escalated,"
            "  rate_limited, message, categories_json, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, ip,
                getattr(decision, "risk_level", "low") if decision else "low",
                json.dumps(getattr(decision, "stages_run", []) if decision else []),
                json.dumps(getattr(decision, "reasons", []) if decision else []),
                json.dumps(getattr(decision, "legal_flags", []) if decision else []),
                json.dumps(getattr(decision, "flagged_categories", []) if decision else []),
                json.dumps(getattr(decision, "blocked_tools", []) if decision else []),
                getattr(decision, "enforced_pattern", "") if decision else "",
                1 if (decision and getattr(decision, "escalated", False)) else 0,
                1 if rate_limited else 0,
                (message or "")[:500],
                json.dumps(getattr(decision, "categories", {}) if decision else {}),
                datetime.utcnow().isoformat(),
            ),
        )
        await db.commit()


async def get_safety_logs(
    limit: int = 100,
    risk_min: str = "",
    session_id: str = "",
) -> list[dict]:
    """Return recent safety log rows. risk_min: '' | 'medium' | 'high'."""
    where = []
    args: list[Any] = []
    if session_id:
        where.append("session_id = ?")
        args.append(session_id)
    if risk_min == "medium":
        where.append("risk_level IN ('medium','high')")
    elif risk_min == "high":
        where.append("risk_level = 'high'")
    sql = "SELECT * FROM safety_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(sql, args)
        rows = await cursor.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("stages_run", "reasons", "legal_flags", "flagged_categories",
                      "blocked_tools", "categories_json"):
                try:
                    d[k] = json.loads(d.get(k) or ("{}" if k == "categories_json" else "[]"))
                except Exception:
                    pass
            out.append(d)
        return out


# ── Quality log helpers ────────────────────────────────────────

async def log_quality_event(
    session_id: str,
    message: str,
    turn_count: int,
    debug_info: dict,
    response_length: int = 0,
    cards_count: int = 0,
    page: str = "",
    device: str = "",
) -> None:
    """Persist a quality/analytics row for offline analysis.

    Extracts key metrics from the DebugInfo dict and stores them as
    indexed columns for fast querying while keeping the full debug JSON
    for deep-dive analysis.
    """
    p3 = debug_info.get("phase3_modulations", {})
    scores = debug_info.get("phase2_scores", {})

    # Compute winner score and score gap to runner-up
    winner_score = 0.0
    runner_up_id = ""
    score_gap = 0.0
    if scores:
        sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
        winner_score = sorted_scores[0][1] if sorted_scores else 0.0
        if len(sorted_scores) >= 2:
            runner_up_id = sorted_scores[1][0]
            score_gap = round(sorted_scores[0][1] - sorted_scores[1][1], 4)

    # Extract pattern ID from "PAT-10 (Fakten-Bulletin)" format
    pattern_str = debug_info.get("pattern", "")
    pattern_id = pattern_str.split(" ")[0] if pattern_str else ""
    pattern_label = pattern_str

    # Extract outcomes
    outcomes = debug_info.get("outcomes", [])
    outcome_dicts = [o if isinstance(o, dict) else (o.model_dump() if hasattr(o, "model_dump") else {})
                     for o in outcomes]

    eliminated = debug_info.get("phase1_eliminated", [])
    candidates_count = len(scores)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO quality_logs ("
            "  session_id, turn_count, persona_id, intent_id, intent_confidence,"
            "  final_confidence, turn_type, state_id, signals, entities,"
            "  pattern_id, pattern_label, phase2_winner_score, phase2_runner_up,"
            "  phase2_score_gap, eliminated_count, candidate_count,"
            "  response_length, cards_count, tools_called, tool_outcomes,"
            "  length_setting, degradation, missing_slots,"
            "  page, device, message, debug_json, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, turn_count,
                debug_info.get("persona", ""),
                debug_info.get("intent", ""),
                debug_info.get("confidence", 0.0),  # intent_confidence ≈ final after adjustments
                debug_info.get("confidence", 0.0),
                debug_info.get("turn_type", ""),
                debug_info.get("state", ""),
                json.dumps(debug_info.get("signals", [])),
                json.dumps(debug_info.get("entities", {})),
                pattern_id, pattern_label,
                winner_score, runner_up_id, score_gap,
                len(eliminated), candidates_count,
                response_length, cards_count,
                json.dumps(debug_info.get("tools_called", [])),
                json.dumps(outcome_dicts),
                p3.get("length", ""),
                1 if p3.get("degradation") else 0,
                json.dumps(p3.get("missing_slots", [])),
                page, device,
                (message or "")[:500],
                json.dumps(debug_info),
                datetime.utcnow().isoformat(),
            ),
        )
        await db.commit()


async def get_quality_logs(
    limit: int = 100,
    session_id: str = "",
    pattern_id: str = "",
    intent_id: str = "",
) -> list[dict]:
    """Return recent quality log rows with optional filters."""
    where = []
    args: list[Any] = []
    if session_id:
        where.append("session_id = ?")
        args.append(session_id)
    if pattern_id:
        where.append("pattern_id LIKE ?")
        args.append(f"{pattern_id}%")
    if intent_id:
        where.append("intent_id LIKE ?")
        args.append(f"{intent_id}%")
    sql = "SELECT * FROM quality_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(sql, args)
        rows = await cursor.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("signals", "entities", "tools_called", "tool_outcomes",
                      "missing_slots", "debug_json"):
                try:
                    d[k] = json.loads(d.get(k) or ("[]" if k != "entities" and k != "debug_json" else "{}"))
                except Exception:
                    pass
            out.append(d)
        return out


async def delete_quality_log(log_id: int) -> int:
    """Delete a single quality log row by primary key. Returns row count."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM quality_logs WHERE id = ?", (log_id,),
        )
        await db.commit()
        return cur.rowcount or 0


async def clear_quality_logs(
    session_id: str = "",
    pattern_id: str = "",
    intent_id: str = "",
) -> int:
    """Bulk-delete quality logs by the same filter shape as get_quality_logs.

    With NO filter given, deletes ALL quality logs — callers must confirm.
    Returns number of deleted rows.
    """
    where: list[str] = []
    args: list[Any] = []
    if session_id:
        where.append("session_id = ?"); args.append(session_id)
    if pattern_id:
        where.append("pattern_id LIKE ?"); args.append(f"{pattern_id}%")
    if intent_id:
        where.append("intent_id LIKE ?"); args.append(f"{intent_id}%")
    sql = "DELETE FROM quality_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, args)
        await db.commit()
        return cur.rowcount or 0


async def get_quality_stats() -> dict:
    """Aggregate quality metrics for dashboard / offline analysis."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        stats: dict = {}

        # Total turns logged
        c = await db.execute("SELECT COUNT(*) as cnt FROM quality_logs")
        stats["total_turns"] = (await c.fetchone())["cnt"]

        # Pattern distribution
        c = await db.execute(
            "SELECT pattern_id, COUNT(*) as cnt FROM quality_logs "
            "GROUP BY pattern_id ORDER BY cnt DESC LIMIT 20"
        )
        stats["pattern_distribution"] = {r["pattern_id"]: r["cnt"] for r in await c.fetchall()}

        # Intent distribution
        c = await db.execute(
            "SELECT intent_id, COUNT(*) as cnt FROM quality_logs "
            "GROUP BY intent_id ORDER BY cnt DESC LIMIT 20"
        )
        stats["intent_distribution"] = {r["intent_id"]: r["cnt"] for r in await c.fetchall()}

        # Average confidence
        c = await db.execute("SELECT AVG(final_confidence) as avg_conf FROM quality_logs")
        stats["avg_confidence"] = round((await c.fetchone())["avg_conf"] or 0, 3)

        # Average score gap (low gap = pattern selection is ambiguous)
        c = await db.execute("SELECT AVG(phase2_score_gap) as avg_gap FROM quality_logs")
        stats["avg_score_gap"] = round((await c.fetchone())["avg_gap"] or 0, 4)

        # Degradation rate
        c = await db.execute(
            "SELECT COUNT(*) as cnt FROM quality_logs WHERE degradation = 1"
        )
        deg_count = (await c.fetchone())["cnt"]
        stats["degradation_rate"] = round(deg_count / max(stats["total_turns"], 1), 3)

        # Tight races (score_gap < 0.02 — patterns almost tied)
        c = await db.execute(
            "SELECT COUNT(*) as cnt FROM quality_logs WHERE phase2_score_gap < 0.02"
        )
        stats["tight_races"] = (await c.fetchone())["cnt"]

        # Empty entity rate
        c = await db.execute(
            "SELECT COUNT(*) as cnt FROM quality_logs WHERE entities = '{}'"
        )
        empty_ent = (await c.fetchone())["cnt"]
        stats["empty_entity_rate"] = round(empty_ent / max(stats["total_turns"], 1), 3)

        # Average response length
        c = await db.execute("SELECT AVG(response_length) as avg_len FROM quality_logs")
        stats["avg_response_length"] = round((await c.fetchone())["avg_len"] or 0, 0)

        return stats


# ── Message helpers ────────────────────────────────────────────

async def save_message(session_id: str, role: str, content: str,
                       cards: list | None = None, debug: dict | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (session_id, role, content, cards_json, debug_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, role, content, json.dumps(cards or []),
             json.dumps(debug or {}), datetime.utcnow().isoformat()),
        )
        await db.commit()


async def get_messages(session_id: str, limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        rows = await cursor.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def delete_messages_for_session(session_id: str) -> int:
    """Delete only the chat messages for a session (keeps the session row
    + its memory + quality/safety logs intact). Returns number of rows."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM messages WHERE session_id = ?", (session_id,),
        )
        await db.commit()
        return cur.rowcount or 0


async def delete_session(session_id: str) -> dict[str, int]:
    """Fully delete a session and every dependent row.

    Returns row counts per table so the API can give useful feedback.
    Safe no-op if the session does not exist (all counts 0).
    """
    counts: dict[str, int] = {}
    async with aiosqlite.connect(DB_PATH) as db:
        for table in ("messages", "memory", "quality_logs", "safety_logs"):
            cur = await db.execute(
                f"DELETE FROM {table} WHERE session_id = ?", (session_id,),
            )
            counts[table] = cur.rowcount or 0
        cur = await db.execute(
            "DELETE FROM sessions WHERE session_id = ?", (session_id,),
        )
        counts["sessions"] = cur.rowcount or 0
        await db.commit()
    return counts


# ── Memory helpers ─────────────────────────────────────────────

async def save_memory(session_id: str, key: str, value: str, memory_type: str = "short"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO memory (session_id, key, value, memory_type, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, key, value, memory_type, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def get_memory(session_id: str, memory_type: str | None = None) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if memory_type:
            cursor = await db.execute(
                "SELECT key, value, memory_type FROM memory WHERE session_id = ? AND memory_type = ?",
                (session_id, memory_type),
            )
        else:
            cursor = await db.execute(
                "SELECT key, value, memory_type FROM memory WHERE session_id = ?",
                (session_id,),
            )
        return [dict(r) for r in await cursor.fetchall()]


# ── RAG chunk helpers ─────────────────────────────────────────

async def store_rag_chunk(area: str, title: str, source: str,
                          chunk_index: int, content: str, embedding: bytes | None = None):
    async with _connect_vec() as db:
        cursor = await db.execute(
            "INSERT INTO rag_chunks (area, title, source, chunk_index, content, embedding, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (area, title, source, chunk_index, content, embedding, datetime.utcnow().isoformat()),
        )
        chunk_id = cursor.lastrowid

        # Also insert into vec0 virtual table for fast vector search
        if embedding and len(embedding) == EMBED_DIM * 4:
            await db.execute(
                "INSERT INTO rag_vec (chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, embedding),
            )

        await db.commit()


async def get_rag_chunks(area: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, area, title, source, chunk_index, content FROM rag_chunks WHERE area = ? ORDER BY id",
            (area,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def search_rag_chunks(area: str, query_embedding: list[float], top_k: int = 3) -> list[dict]:
    """Vector similarity search using sqlite-vec (vec0 virtual table)."""
    query_blob = struct.pack(f"{len(query_embedding)}f", *query_embedding)

    async with _connect_vec() as db:
        db.row_factory = aiosqlite.Row

        # sqlite-vec KNN query: vec0 WHERE only supports MATCH + k,
        # so we filter by area in a wrapping query after the KNN search.
        cursor = await db.execute(
            "SELECT sub.content, sub.source, sub.area, sub.title, sub.distance "
            "FROM ("
            "  SELECT r.content, r.source, r.area, r.title, v.distance "
            "  FROM rag_vec v "
            "  JOIN rag_chunks r ON r.id = v.chunk_id "
            "  WHERE v.embedding MATCH ? AND k = ?"
            ") sub "
            "WHERE sub.area = ? "
            "ORDER BY sub.distance",
            (query_blob, top_k * 5, area),  # over-fetch to account for area filter
        )
        rows = await cursor.fetchall()

    results = []
    for row in rows:
        # sqlite-vec returns L2 distance; convert to a 0-1 similarity score
        distance = row["distance"]
        score = 1.0 / (1.0 + distance)
        results.append({
            "chunk": row["content"],
            "score": score,
            "source": row["source"],
            "area": row["area"],
            "title": row["title"],
        })

    return results[:top_k]
