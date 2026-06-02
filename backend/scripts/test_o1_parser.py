"""O1 Stage 1: search_wlo_all über call_mcp_tool + parse_search_all_cards.
Verifiziert auto-outputFormat=json + typisierte Karten-Töpfe gegen den
deployten MCP. Aufruf (backend/): python scripts/test_o1_parser.py
"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()
from app.services.mcp_client import call_mcp_tool, parse_search_all_cards  # noqa: E402
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


async def main():
    for q in ("Photosynthese", "Bruchrechnung Klasse 7"):
        raw = await call_mcp_tool("search_wlo_all", {"query": q})  # outputFormat=json auto
        pots = parse_search_all_cards(raw)
        print(f"\n=== '{q}' ===")
        for pot, cards in pots.items():
            print(f"  {pot:12s}: {len(cards)}")
            for c in cards[:2]:
                tp = "Themenseite" if c.get("topic_page_url") else "-"
                print(f"     - [{c.get('node_type')}/{tp}] {str(c.get('title'))[:44]}  url={'ja' if c.get('wlo_url') else 'nein'}")
    print("\nfertig.")


if __name__ == "__main__":
    asyncio.run(main())
