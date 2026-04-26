"""Pydantic models for the BadBoerdi API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ── Classification result (validated LLM output) ──────────────────
class ClassificationResult(BaseModel):
    """Validated output from LLM classification (the 7 input dimensions)."""
    persona_id: str = "P-AND"
    persona_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    intent_id: str = "INT-W-03a"
    intent_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    signals: list[str] = Field(default_factory=list)
    entities: dict[str, Any] = Field(default_factory=dict)
    turn_type: str = "initial"
    next_state: str = "state-1"


# ── Environment (sent by frontend every turn) ──────────────────────
class Environment(BaseModel):
    page: str = "/"
    page_context: dict[str, Any] = Field(default_factory=dict)
    device: str = "desktop"
    locale: str = "de-DE"
    session_duration: int = 0
    referrer: str = "direkt"


# ── Chat request / response ────────────────────────────────────────
class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(..., max_length=10000)
    environment: Environment = Field(default_factory=Environment)
    action: str | None = None  # browse_collection | generate_learning_path | canvas_create | canvas_edit | None
    action_params: dict[str, Any] = Field(default_factory=dict)  # e.g. {collection_id, title} or {current_markdown, edit_instruction, material_type}
    # Snapshot of what the user currently sees in the canvas pane. The
    # frontend sends this with every turn so the classifier / LLM knows
    # the user's visible context (e.g. when asking "was bedeutet hier
    # der Zaehler?" about an on-screen worksheet).
    canvas_state: dict[str, Any] | None = None  # {title, material_type, markdown, mode: 'material'|'cards'|'empty', cards_count?}


class WloCard(BaseModel):
    node_id: str = ""
    title: str = ""
    description: str = ""
    disciplines: list[str] = Field(default_factory=list)
    educational_contexts: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    learning_resource_types: list[str] = Field(default_factory=list)
    url: str = ""
    wlo_url: str = ""
    preview_url: str = ""
    license: str = ""
    publisher: str = ""
    node_type: str = "content"
    topic_pages: list[dict[str, str]] = Field(default_factory=list)
    # Each entry: {url, target_group, label}
    # e.g. [{url: "https://...", target_group: "teacher", label: "Lehrkräfte"}]


class ToolOutcome(BaseModel):
    """Outcome of a tool call — separate from final content (T-23/24).

    Tracks what happened with a tool call beyond the raw result text:
    success/error/empty status, error messages, item counts, latency.
    Used to feedback into Confidence (T-25) and State (T-27).
    """
    tool: str = ""
    status: str = "success"  # success | empty | error | timeout
    item_count: int = 0
    error: str = ""
    latency_ms: int = 0


class PolicyDecision(BaseModel):
    """Policy layer decision (T-13/14).

    Org/regulatory policy gating that runs alongside Safety. Distinguishes
    between hard blocks (required by policy) and soft warnings.
    """
    allowed: bool = True
    blocked_tools: list[str] = Field(default_factory=list)
    required_disclaimers: list[str] = Field(default_factory=list)
    matched_rules: list[str] = Field(default_factory=list)


class ContextSnapshot(BaseModel):
    """Context layer snapshot (T-04/05).

    Formalised conversation/session context: aggregated entities, relevant
    history slice, environment, memory keys. Drives pattern fit + LLM prompts.
    """
    page: str = ""
    device: str = ""
    locale: str = ""
    session_duration: int = 0
    turn_count: int = 0
    entities: dict[str, Any] = Field(default_factory=dict)
    recent_signals: list[str] = Field(default_factory=list)
    memory_keys: list[str] = Field(default_factory=list)
    last_intent: str = ""
    last_state: str = ""


class TraceEntry(BaseModel):
    """Single trace step (T-29/30/31).

    Observability records for each layer transition: when, what, outcome.
    Built up over the request lifecycle and shipped in DebugInfo.
    """
    step: str = ""              # safety | policy | classify | context | pattern | tools | response | feedback
    label: str = ""             # human-readable description
    duration_ms: int = 0
    data: dict[str, Any] = Field(default_factory=dict)


class SafetyDecision(BaseModel):
    """Safety layer decision (T-12/19).

    Risk-based gating that can block tools or enforce specific patterns
    independently of pattern selection.
    """
    risk_level: str = "low"  # low | medium | high
    blocked_tools: list[str] = Field(default_factory=list)
    enforced_pattern: str = ""
    reasons: list[str] = Field(default_factory=list)
    # Multi-stage details
    stages_run: list[str] = Field(default_factory=list)  # regex | openai_moderation | llm_legal
    categories: dict[str, float] = Field(default_factory=dict)  # cat → score
    flagged_categories: list[str] = Field(default_factory=list)
    legal_flags: list[str] = Field(default_factory=list)  # strafrecht|jugendschutz|persoenlichkeit|datenschutz
    escalated: bool = False  # True if any LLM stage was invoked


class DebugInfo(BaseModel):
    persona: str = ""
    intent: str = ""
    state: str = ""
    turn_type: str = ""  # initial | follow_up | topic_switch | correction | clarification
    signals: list[str] = Field(default_factory=list)
    pattern: str = ""
    entities: dict[str, Any] = Field(default_factory=dict)
    tools_called: list[str] = Field(default_factory=list)
    phase1_eliminated: list[str] = Field(default_factory=list)
    phase2_scores: dict[str, float] = Field(default_factory=dict)
    phase3_modulations: dict[str, Any] = Field(default_factory=dict)
    # NEW (Triple-Schema v2)
    outcomes: list[ToolOutcome] = Field(default_factory=list)
    safety: SafetyDecision | None = None
    confidence: float = 1.0  # final confidence after all adjustments
    policy: PolicyDecision | None = None
    context: ContextSnapshot | None = None
    trace: list[TraceEntry] = Field(default_factory=list)


class PaginationInfo(BaseModel):
    """Pagination metadata for card results."""
    total_count: int = 0         # Total items available (0 = unknown)
    skip_count: int = 0          # Current offset
    page_size: int = 5           # Items per page
    has_more: bool = False       # More items available?
    collection_id: str = ""      # For "load more" on collection contents
    collection_title: str = ""   # Title for display


class ChatResponse(BaseModel):
    session_id: str
    content: str
    cards: list[WloCard] = Field(default_factory=list)
    follow_up: str = "none"
    quick_replies: list[str] = Field(default_factory=list)
    debug: DebugInfo = Field(default_factory=DebugInfo)
    page_action: dict[str, Any] | None = None
    pagination: PaginationInfo | None = None


# ── Session / Memory ──────────────────────────────────────────────
class SessionState(BaseModel):
    session_id: str
    persona_id: str = ""
    state_id: str = "state-1"
    entities: dict[str, Any] = Field(default_factory=dict)
    signal_history: list[str] = Field(default_factory=list)
    turn_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryEntry(BaseModel):
    session_id: str
    key: str
    value: str
    memory_type: str = "short"  # short | long
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── RAG ───────────────────────────────────────────────────────────
class RagDocument(BaseModel):
    id: str = ""
    area: str = "general"
    title: str = ""
    source: str = ""
    content: str = ""
    chunks: int = 0


class RagQuery(BaseModel):
    query: str
    area: str = "general"
    top_k: int = 3


class RagResult(BaseModel):
    chunk: str
    score: float
    source: str
    area: str


# ── MCP tool arguments (validated before calling MCP server) ─────
class SearchWloArgs(BaseModel):
    """Arguments for search_wlo_collections and search_wlo_content.

    NOTE: These parameter names match the WLO MCP server schema EXACTLY.
    Historical mismatches (resourceType, educationalLevel, maxItems) caused
    the server to silently ignore our filters; those legacy names are now
    accepted via pre-validator aliases but always exported as the server's
    canonical names (learningResourceType, educationalContext, maxResults).
    """
    query: str = ""
    discipline: str = ""
    educationalContext: str = ""  # educationalLevel is a legacy alias
    learningResourceType: str = ""  # resourceType is a legacy alias
    userRole: str = ""
    publisher: str = ""
    parentNodeId: str = ""  # only valid for search_wlo_collections
    maxResults: int = Field(default=5, ge=1, le=20)  # maxItems is a legacy alias

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_names(cls, data):
        """Accept old param names we used in prompts and UI history."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # educationalLevel → educationalContext
        if "educationalContext" not in data and "educationalLevel" in data:
            data["educationalContext"] = data.pop("educationalLevel")
        # resourceType → learningResourceType
        if "learningResourceType" not in data and "resourceType" in data:
            data["learningResourceType"] = data.pop("resourceType")
        # maxItems → maxResults
        if "maxResults" not in data and "maxItems" in data:
            data["maxResults"] = data.pop("maxItems")
        # Drop fields the real MCP schema doesn't know
        data.pop("license", None)
        data.pop("skipCount", None)
        return data


class CollectionContentsArgs(BaseModel):
    """Arguments for get_collection_contents.

    Matches MCP schema: nodeId, query, contentFilter, includeSubcollections,
    maxResults, skipCount. Legacy name maxItems accepted via pre-validator.
    """
    nodeId: str
    query: str = ""
    contentFilter: str = ""  # "files" | "folders" | "both"
    includeSubcollections: bool = False
    maxResults: int = Field(default=5, ge=1, le=100)
    skipCount: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_names(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "maxResults" not in data and "maxItems" in data:
            data["maxResults"] = data.pop("maxItems")
        return data


class NodeDetailsArgs(BaseModel):
    """Arguments for get_node_details."""
    nodeId: str


class InfoQueryArgs(BaseModel):
    """Arguments for info tools (get_wirlernenonline_info, get_edu_sharing_*, get_metaventis_info)."""
    query: str


class SearchTopicPagesArgs(BaseModel):
    """Arguments for search_wlo_topic_pages."""
    query: str = ""
    collectionId: str = ""
    targetGroup: str = ""  # teacher | learner | general
    educationalContext: str = ""
    maxResults: int = Field(default=5, ge=1, le=20)


class LookupVocabularyArgs(BaseModel):
    """Arguments for lookup_wlo_vocabulary.

    NOTE: The upstream MCP server expects the parameter name ``vocabulary``
    (not ``field``). Historically this project used ``field``; we accept
    either via the pre-validator for backwards compatibility, but the
    exported argument is always ``vocabulary``.
    """
    vocabulary: str

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_field(cls, data):
        if isinstance(data, dict) and "vocabulary" not in data and "field" in data:
            data = {**data, "vocabulary": data["field"]}
        return data


# ── Config / Studio ──────────────────────────────────────────────
class ConfigFile(BaseModel):
    path: str
    content: str
    file_type: str = "markdown"


class PageAction(BaseModel):
    """Action to send back to host page or widget canvas (search results, navigate, etc.).

    Values:
      Host-Page:
        navigate, show_collection, show_results, share_content
      Widget-Canvas (Phase 1):
        canvas_open          payload: {title, material_type, markdown}
        canvas_update        payload: {markdown}
        canvas_show_cards    payload: {cards, query}
        canvas_close         payload: {}
    """
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
