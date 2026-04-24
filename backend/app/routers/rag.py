"""RAG router — manage knowledge areas, ingest documents/URLs, query."""

from __future__ import annotations

import os
import tempfile
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.schemas import RagDocument, RagQuery, RagResult
from app.services.rag_service import (
    convert_to_markdown, convert_url_to_markdown, ingest_document, query_rag,
)
from app.services.database import get_rag_chunks

router = APIRouter()


@router.post("/ingest/file")
async def ingest_file(
    file: UploadFile = File(...),
    area: str = Form("general"),
    title: str = Form(""),
):
    """Upload and ingest a document (PDF, DOCX, PPTX, etc.) via markitdown."""
    if not title:
        title = file.filename or "Unbenannt"

    # Save to temp file
    suffix = os.path.splitext(file.filename or "")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        markdown = await convert_to_markdown(tmp_path)
        if markdown.startswith("Fehler"):
            raise HTTPException(status_code=400, detail=markdown)

        chunks = await ingest_document(area, title, file.filename or "", markdown)
        return {"status": "ok", "title": title, "area": area, "chunks": chunks,
                "preview": markdown[:500]}
    finally:
        os.unlink(tmp_path)


@router.post("/ingest/url")
async def ingest_url(
    url: str = Form(...),
    area: str = Form("general"),
    title: str = Form(""),
):
    """Ingest a web page into a knowledge area via markitdown."""
    if not title:
        title = url

    markdown = await convert_url_to_markdown(url)
    if markdown.startswith("Fehler"):
        raise HTTPException(status_code=400, detail=markdown)

    chunks = await ingest_document(area, title, url, markdown)
    return {"status": "ok", "title": title, "area": area, "chunks": chunks,
            "preview": markdown[:500]}


@router.post("/ingest/text")
async def ingest_text(
    content: str = Form(...),
    area: str = Form("general"),
    title: str = Form(""),
    source: str = Form("manual"),
):
    """Ingest raw markdown/text into a knowledge area."""
    chunks = await ingest_document(area, title or "Manueller Eintrag", source, content)
    return {"status": "ok", "title": title, "area": area, "chunks": chunks}


@router.post("/query", response_model=list[RagResult])
async def rag_query(req: RagQuery):
    """Query the RAG knowledge base."""
    results = await query_rag(req.query, req.area, req.top_k)
    return [RagResult(**r) for r in results]


@router.get("/areas")
async def list_areas():
    """List all knowledge areas with chunk counts."""
    import aiosqlite
    from app.services.database import DB_PATH

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT area, COUNT(*) as count, COUNT(DISTINCT title) as docs "
            "FROM rag_chunks GROUP BY area ORDER BY area"
        )
        rows = await cursor.fetchall()
        return [{"area": r["area"], "chunks": r["count"], "documents": r["docs"]}
                for r in rows]


@router.get("/area/{area}")
async def get_area_documents(area: str):
    """List documents in a knowledge area.

    Documents are grouped by the compound key ``(title, source)`` so that
    e.g. two uploads with the same filename from different folders, or two
    manual entries with the same title, remain distinguishable.
    """
    chunks = await get_rag_chunks(area)
    docs: dict[tuple[str, str], Any] = {}
    for c in chunks:
        key = (c.get("title") or "", c.get("source") or "")
        if key not in docs:
            docs[key] = {
                "title": key[0],
                "source": key[1],
                "chunks": 0,
                "preview": "",
            }
        docs[key]["chunks"] += 1
        if not docs[key]["preview"]:
            docs[key]["preview"] = (c.get("content") or "")[:200]
    return list(docs.values())


@router.delete("/area/{area}")
async def delete_area(area: str):
    """Delete all chunks in a knowledge area."""
    import aiosqlite
    from app.services.database import DB_PATH

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM rag_chunks WHERE area = ?", (area,))
        await db.commit()
    return {"status": "deleted", "area": area}


@router.get("/area/{area}/doc")
async def get_area_document(area: str, title: str = "", source: str = ""):
    """Return all chunks of a single document, ordered by chunk_index.

    Identified by ``(area, title, source)`` exactly like the delete
    endpoint. Use when the Studio wants to preview the full content
    of a RAG document instead of just the 200-char preview.

    Returns ``{title, source, area, chunks: [{index, content, created_at}]}``.
    """
    import aiosqlite
    from app.services.database import DB_PATH

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT chunk_index, content, created_at "
            "FROM rag_chunks "
            "WHERE area = ? AND title = ? AND source = ? "
            "ORDER BY chunk_index ASC, id ASC",
            (area, title, source),
        )
        rows = [dict(r) for r in await cursor.fetchall()]

    return {
        "area": area,
        "title": title,
        "source": source,
        "chunk_count": len(rows),
        "total_chars": sum(len(r.get("content") or "") for r in rows),
        "chunks": [
            {
                "index": r.get("chunk_index", 0),
                "content": r.get("content") or "",
                "created_at": r.get("created_at") or "",
            }
            for r in rows
        ],
    }


@router.delete("/area/{area}/doc")
async def delete_area_document(area: str, title: str = "", source: str = ""):
    """Delete a single document (all its chunks) from a knowledge area.

    Query params ``title`` and ``source`` together identify the document
    — they must match the values returned by ``GET /area/{area}``. Empty
    strings are valid (the match is exact). Also cleans up the vector
    index rows so semantic search doesn't return orphan matches.
    """
    import aiosqlite
    from app.services.database import DB_PATH, _connect_vec

    # Grab the ids first so we can also purge the vec-index rows.
    chunk_ids: list[int] = []
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM rag_chunks WHERE area = ? AND title = ? AND source = ?",
            (area, title, source),
        )
        chunk_ids = [row[0] for row in await cur.fetchall()]

    if not chunk_ids:
        return {
            "status": "noop",
            "area": area,
            "title": title,
            "source": source,
            "deleted": 0,
        }

    # Delete chunks + vec-index rows in lockstep. sqlite-vec has its own
    # handle so we can't do a single JOIN delete.
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM rag_chunks WHERE area = ? AND title = ? AND source = ?",
            (area, title, source),
        )
        await db.commit()

    try:
        async with _connect_vec() as vdb:
            placeholders = ",".join("?" for _ in chunk_ids)
            await vdb.execute(
                f"DELETE FROM rag_vec WHERE chunk_id IN ({placeholders})",
                chunk_ids,
            )
            await vdb.commit()
    except Exception as e:
        # Not fatal — the orphaned vec rows won't match anything without
        # their chunk content, but log so we notice accumulating cruft.
        import logging
        logging.getLogger(__name__).warning(
            "rag_vec cleanup after doc delete failed: %s", e,
        )

    return {
        "status": "deleted",
        "area": area,
        "title": title,
        "source": source,
        "deleted": len(chunk_ids),
    }


@router.post("/embed")
async def embed_missing():
    """Generate embeddings for all chunks that don't have one yet.

    Called automatically after seed import, or manually via API.
    Returns the number of chunks that were embedded.
    """
    import struct
    import aiosqlite
    from app.services.database import DB_PATH, EMBED_DIM, _connect_vec
    from app.services.rag_service import get_embedding, embedding_to_bytes

    # Find chunks without embeddings
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, content FROM rag_chunks WHERE embedding IS NULL"
        )
        rows = [dict(r) for r in await cursor.fetchall()]

    if not rows:
        return {"status": "ok", "embedded": 0, "message": "All chunks already have embeddings"}

    # Generate embeddings and store
    count = 0
    async with _connect_vec() as db:
        for row in rows:
            try:
                emb = await get_embedding(row["content"])
                emb_bytes = embedding_to_bytes(emb)
                await db.execute(
                    "UPDATE rag_chunks SET embedding = ? WHERE id = ?",
                    (emb_bytes, row["id"]),
                )
                if len(emb_bytes) == EMBED_DIM * 4:
                    await db.execute(
                        "INSERT OR REPLACE INTO rag_vec (chunk_id, embedding) VALUES (?, ?)",
                        (row["id"], emb_bytes),
                    )
                count += 1
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Embedding failed for chunk %d: %s", row["id"], e)
        await db.commit()

    return {"status": "ok", "embedded": count, "total": len(rows)}
