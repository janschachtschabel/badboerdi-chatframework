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
    """List documents in a knowledge area."""
    chunks = await get_rag_chunks(area)
    # Group by title
    docs: dict[str, Any] = {}
    for c in chunks:
        t = c["title"]
        if t not in docs:
            docs[t] = {"title": t, "source": c["source"], "chunks": 0, "preview": ""}
        docs[t]["chunks"] += 1
        if not docs[t]["preview"]:
            docs[t]["preview"] = c["content"][:200]
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
