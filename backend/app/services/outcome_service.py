"""Outcome layer (T-23/24/25/27 from Triple-Schema v2).

Separates raw tool results from final content. Tool calls produce
Outcomes (success/empty/error/timeout + metadata) which then drive:
- Confidence adjustments (T-25)
- State transitions (T-27)
- Content generation (T-24)
"""

from __future__ import annotations

import time
from typing import Any

from app.models.schemas import ToolOutcome
from app.services.mcp_client import call_mcp_tool


async def call_with_outcome(
    tool_name: str,
    tool_args: dict[str, Any],
) -> tuple[str, ToolOutcome]:
    """Call an MCP tool and return both raw result and structured Outcome.

    Wraps `call_mcp_tool` to produce a ToolOutcome with status metadata.
    """
    outcome = ToolOutcome(tool=tool_name)
    start = time.monotonic()

    try:
        result = await call_mcp_tool(tool_name, tool_args)
        outcome.latency_ms = int((time.monotonic() - start) * 1000)

        if not result or not result.strip():
            outcome.status = "empty"
            outcome.item_count = 0
        else:
            outcome.status = "success"
            # Heuristic item count for search tools
            if tool_name in ("search_wlo_collections", "search_wlo_content",
                              "get_collection_contents"):
                # Count by node references in the response
                outcome.item_count = result.count("nodeId") or result.count("- ")
            else:
                outcome.item_count = 1
        return result, outcome

    except Exception as e:
        outcome.status = "error"
        outcome.error = str(e)[:200]
        outcome.latency_ms = int((time.monotonic() - start) * 1000)
        return "", outcome


def adjust_confidence(base: float, outcomes: list[ToolOutcome]) -> float:
    """Recalculate confidence based on tool outcomes (T-25).

    Errors and empty results lower confidence; successful tool calls
    with results raise it slightly.
    """
    conf = base
    for o in outcomes:
        if o.status == "error":
            conf -= 0.20
        elif o.status == "empty":
            conf -= 0.10
        elif o.status == "success" and o.item_count > 0:
            conf += 0.05
        elif o.status == "timeout":
            conf -= 0.15
    return max(0.0, min(1.0, conf))


def derive_state_hint(outcomes: list[ToolOutcome]) -> str:
    """Suggest state transition based on outcomes (T-27).

    Returns a state hint or empty string if no transition needed.
    """
    if not outcomes:
        return ""
    # All errors/empty → user needs clarification
    failed = [o for o in outcomes if o.status in ("error", "empty", "timeout")]
    if failed and len(failed) == len(outcomes):
        return "state-clarification"
    # Successful results → move to result curation
    successful = [o for o in outcomes if o.status == "success" and o.item_count > 0]
    if successful:
        return "state-6"  # result curation
    return ""
