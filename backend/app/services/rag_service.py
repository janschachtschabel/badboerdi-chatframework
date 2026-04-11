"""RAG service: ingest documents via markitdown, chunk, embed, and search."""

from __future__ import annotations

import os
import re
import struct
from typing import Any

import httpx

from app.services.database import store_rag_chunk, get_rag_chunks, search_rag_chunks
from app.services.llm_provider import get_client, get_embed_model

client = get_client()
EMBED_MODEL = get_embed_model()


async def get_embedding(text: str) -> list[float]:
    """Get embedding vector from the configured LLM provider."""
    resp = await client.embeddings.create(model=EMBED_MODEL, input=text[:8000])
    return resp.data[0].embedding


def embedding_to_bytes(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


def chunk_markdown(text: str, max_chunk: int = 1000, overlap: int = 150) -> list[str]:
    """Split text into chunks using a multi-strategy approach.

    Strategy priority:
    1. Split at markdown headings (H1-H3)
    2. If that produces too few chunks, split at paragraph boundaries (double newline)
    3. Final fallback: split at sentence boundaries with overlap
    """
    # ── Strategy 1: heading-based split ─────────────────────
    sections = re.split(r"(?=^#{1,3}\s)", text, flags=re.MULTILINE)
    heading_sections = [s.strip() for s in sections if s.strip()]

    # If headings produce good granularity, use them
    if len(heading_sections) > 1:
        return _merge_sections(heading_sections, max_chunk)

    # ── Strategy 2: paragraph-based split ───────────────────
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if len(paragraphs) > 1:
        return _merge_sections(paragraphs, max_chunk)

    # ── Strategy 3: sentence-based split with overlap ───────
    # For texts without headings or paragraph breaks (e.g. raw PDF text)
    return _split_by_sentences(text, max_chunk, overlap)


def _merge_sections(sections: list[str], max_chunk: int) -> list[str]:
    """Merge small sections into chunks up to max_chunk size."""
    chunks: list[str] = []
    current = ""

    for section in sections:
        if not section:
            continue
        if len(current) + len(section) + 2 > max_chunk and current:
            chunks.append(current.strip())
            current = section
        else:
            current = (current + "\n\n" + section) if current else section

    if current.strip():
        chunks.append(current.strip())

    # Post-process: split any oversized chunks
    final: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chunk:
            final.append(chunk)
        else:
            final.extend(_split_by_sentences(chunk, max_chunk, 100))

    return final if final else [sections[0][:max_chunk]]


def _split_by_sentences(text: str, max_chunk: int, overlap: int) -> list[str]:
    """Split text at sentence boundaries with overlap for context continuity."""
    # Split on sentence-ending punctuation followed by space or newline
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        # Absolute fallback: hard split at max_chunk
        return [text[i:i + max_chunk] for i in range(0, len(text), max_chunk - overlap)]

    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 > max_chunk and current:
            chunks.append(current.strip())
            # Overlap: keep last ~overlap chars for context continuity
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:].lstrip() + " " + sentence
            else:
                current = sentence
        else:
            current = (current + " " + sentence) if current else sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text[:max_chunk]]


async def convert_to_markdown(file_path: str) -> str:
    """Convert any document to markdown using markitdown."""
    try:
        from markitdown import MarkItDown
        mid = MarkItDown()
        result = mid.convert(file_path)
        return result.text_content
    except Exception as e:
        return f"Fehler beim Konvertieren: {e}"


async def convert_url_to_markdown(url: str) -> str:
    """Fetch a URL and convert to markdown using markitdown."""
    try:
        from markitdown import MarkItDown
        mid = MarkItDown()
        result = mid.convert_url(url)
        return result.text_content
    except Exception as e:
        return f"Fehler beim Konvertieren: {e}"


async def ingest_document(
    area: str,
    title: str,
    source: str,
    markdown_content: str,
) -> int:
    """Chunk, embed, and store a markdown document. Returns chunk count."""
    chunks = chunk_markdown(markdown_content)

    for i, chunk in enumerate(chunks):
        embedding = await get_embedding(chunk)
        emb_bytes = embedding_to_bytes(embedding)
        await store_rag_chunk(area, title, source, i, chunk, emb_bytes)

    return len(chunks)


async def query_rag(query: str, area: str = "general", top_k: int = 3) -> list[dict]:
    """Search RAG knowledge base by semantic similarity."""
    query_emb = await get_embedding(query)
    results = await search_rag_chunks(area, query_emb, top_k)
    return results


async def get_rag_context(query: str, areas: list[str] | None = None, top_k: int = 3,
                          min_score: float = 0.25) -> str:
    """Get RAG context string for injection into LLM prompt.

    Queries all given areas, merges results, filters by relevance threshold,
    and returns the top-k chunks sorted by score.  Because all areas share the
    same embedding model and distance metric, scores are directly comparable
    across areas — no per-area guarantees needed.

    Args:
        query: Search query.
        areas: List of knowledge areas to search.
        top_k: Maximum total chunks to return.
        min_score: Minimum similarity score (0-1). Chunks below this threshold
                   are dropped even if top_k is not yet reached. This prevents
                   irrelevant chunks from diluting the context.
    """
    if not areas:
        areas = ["general"]

    all_results = []
    for area in areas:
        results = await query_rag(query, area, top_k)
        all_results.extend(results)

    if not all_results:
        return ""

    # Sort by score globally across all areas, then filter by relevance threshold
    all_results.sort(key=lambda x: x["score"], reverse=True)
    top = [r for r in all_results[:top_k] if r["score"] >= min_score]

    if not top:
        return ""

    parts = []
    for r in top:
        parts.append(f"[Quelle: {r.get('title', r.get('source', 'unbekannt'))} | "
                     f"Bereich: {r['area']} | Relevanz: {r['score']:.2f}]\n{r['chunk']}")

    return "\n\n---\n\n".join(parts)


async def get_always_on_rag_context(query: str, top_k: int = 3) -> str:
    """Get RAG context from areas configured as 'always' available.

    These areas are included in every request regardless of pattern config.
    """
    from app.services.config_loader import get_always_on_rag_areas

    always_areas = get_always_on_rag_areas()
    if not always_areas:
        return ""

    return await get_rag_context(query, areas=always_areas, top_k=top_k)
