"""Export RAG chunks from the local database to a JSON seed file.

Usage:
    python -m scripts.rag_export                         # export all areas
    python -m scripts.rag_export --areas recht general   # export specific areas
    python -m scripts.rag_export --output my-seed.json   # custom output path

The seed file contains chunks WITHOUT embeddings (they are regenerated on import
using the configured embedding model). This keeps the file small and git-friendly.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import date

DB_PATH = os.getenv("DATABASE_PATH", "badboerdi.db")
DEFAULT_OUTPUT = os.path.join("knowledge", "rag-seed.json")


def export_rag(db_path: str, areas: list[str] | None, output: str, version: str | None = None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if areas:
        placeholders = ",".join("?" for _ in areas)
        query = f"SELECT area, title, source, chunk_index, content FROM rag_chunks WHERE area IN ({placeholders}) ORDER BY area, id"
        rows = conn.execute(query, areas).fetchall()
    else:
        rows = conn.execute(
            "SELECT area, title, source, chunk_index, content FROM rag_chunks ORDER BY area, id"
        ).fetchall()

    chunks = []
    for r in rows:
        chunks.append({
            "area": r["area"],
            "title": r["title"],
            "source": r["source"],
            "chunk_index": r["chunk_index"],
            "content": r["content"],
        })

    # Group stats
    area_counts: dict[str, int] = {}
    for c in chunks:
        area_counts[c["area"]] = area_counts.get(c["area"], 0) + 1

    seed_version = version or date.today().isoformat()

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump({
            "version": seed_version,
            "description": "RAG knowledge seed for BadBOERDi chatbot",
            "areas": area_counts,
            "chunks": chunks,
        }, f, ensure_ascii=False, indent=2)

    print(f"Exported {len(chunks)} chunks to {output}")
    for area, count in sorted(area_counts.items()):
        print(f"  {area}: {count} chunks")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export RAG chunks to seed JSON")
    parser.add_argument("--db", default=DB_PATH, help="Database path")
    parser.add_argument("--areas", nargs="*", help="Only export these areas")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT, help="Output file path")
    parser.add_argument("--version", "-v", default=None, help="Seed version (default: today's date, e.g. 2026-04-11)")
    args = parser.parse_args()
    export_rag(args.db, args.areas, args.output, args.version)
