"""Load chatbot configuration from markdown/YAML files."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

CHATBOT_DIR = Path(__file__).parent.parent.parent / "chatbots" / "wlo" / "v1"


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown file. Returns (meta, body)."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, match.group(2)


def load_persona_prompt(persona_id: str) -> str:
    """Load persona markdown prompt file."""
    persona_map = {
        "P-W-LK": "lk", "P-W-SL": "sl", "P-W-POL": "pol", "P-W-PRESSE": "presse",
        "P-W-RED": "red", "P-BER": "ber", "P-VER": "ver", "P-ELT": "elt", "P-AND": "and",
    }
    slug = persona_map.get(persona_id, "and")
    path = CHATBOT_DIR / "04-personas" / f"{slug}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"Persona: {persona_id} (Standard-Persona)"


def load_domain_rules() -> str:
    """Load all domain files (rules + knowledge)."""
    domain_dir = CHATBOT_DIR / "02-domain"
    if not domain_dir.exists():
        return ""
    parts = []
    for path in sorted(domain_dir.glob("*.md")):
        parts.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(parts) if parts else ""


def load_base_persona() -> str:
    """Load the base persona (Layer 1)."""
    path = CHATBOT_DIR / "01-base" / "base-persona.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def load_guardrails() -> str:
    """Load guardrails."""
    path = CHATBOT_DIR / "01-base" / "guardrails.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def list_config_files() -> list[dict]:
    """List all config files in the chatbot directory for the Studio."""
    files = []
    if not CHATBOT_DIR.exists():
        return files
    for path in sorted(CHATBOT_DIR.rglob("*")):
        if path.is_file() and path.suffix in (".md", ".json", ".yml", ".yaml"):
            rel = path.relative_to(CHATBOT_DIR)
            files.append({
                "path": str(rel).replace("\\", "/"),
                "full_path": str(path),
                "name": path.name,
                "type": path.suffix.lstrip("."),
            })
    return files


def _validate_config_path(rel_path: str) -> Path:
    """Validate and resolve a relative config path, preventing path traversal.

    Raises ValueError if the resolved path escapes CHATBOT_DIR.
    """
    path = (CHATBOT_DIR / rel_path).resolve()
    try:
        path.relative_to(CHATBOT_DIR.resolve())
    except ValueError:
        raise ValueError(f"Path traversal blocked: {rel_path}")
    return path


def read_config_file(rel_path: str) -> str:
    """Read a config file by relative path."""
    path = _validate_config_path(rel_path)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def write_config_file(rel_path: str, content: str):
    """Write a config file by relative path."""
    path = _validate_config_path(rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    # Invalidate YAML cache so Studio edits are visible immediately,
    # regardless of filesystem mtime resolution.
    _YAML_CACHE.pop(rel_path, None)


_YAML_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _load_yaml(rel_path: str) -> dict[str, Any]:
    """Load a YAML config file with mtime-based caching.

    Re-parses only when the file's modification time has changed,
    so studio edits are picked up immediately but every chat turn
    avoids the (~5–20 ms) parse overhead.
    """
    path = CHATBOT_DIR / rel_path
    if not path.exists():
        return {}
    try:
        mtime = path.stat().st_mtime
        cached = _YAML_CACHE.get(rel_path)
        if cached and cached[0] == mtime:
            return cached[1]
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        _YAML_CACHE[rel_path] = (mtime, data)
        return data
    except yaml.YAMLError:
        return {}


def invalidate_yaml_cache(rel_path: str | None = None) -> None:
    """Drop cached YAML — use after a write_config_file() call."""
    if rel_path is None:
        _YAML_CACHE.clear()
    else:
        _YAML_CACHE.pop(rel_path, None)


def load_signal_modulations() -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Load signal modulation table from config.

    Returns (modulations_dict, reduce_items_signals).
    """
    data = _load_yaml("04-signals/signal-modulations.yaml")
    signals = data.get("signals", {})

    modulations: dict[str, dict[str, Any]] = {}
    for signal_id, cfg in signals.items():
        mods: dict[str, Any] = {}
        for key in ("tone", "length", "skip_intro", "one_option", "add_sources",
                     "show_more", "show_overview"):
            if key in cfg:
                mods[key] = cfg[key]
        modulations[signal_id] = mods

    reduce_items = data.get("reduce_items_signals", [])
    return modulations, reduce_items


def load_intents() -> list[dict[str, Any]]:
    """Load intent definitions from config."""
    data = _load_yaml("04-intents/intents.yaml")
    return data.get("intents", [])


def load_states() -> list[dict[str, Any]]:
    """Load state definitions from config."""
    data = _load_yaml("04-states/states.yaml")
    return data.get("states", [])


def load_entities() -> list[dict[str, Any]]:
    """Load entity/slot definitions from config."""
    data = _load_yaml("04-entities/entities.yaml")
    return data.get("entities", [])


# ──────────────────────────────────────────────────────────────────────────
# Canvas config (05-canvas/)
# ──────────────────────────────────────────────────────────────────────────

def load_canvas_material_types() -> list[dict[str, Any]]:
    """Load canvas material-type definitions (emoji, label, category, structure).

    Returns a list of dicts with keys: id, label, emoji, category, structure.
    Empty list if file missing — canvas_service then falls back to its
    in-code defaults.
    """
    data = _load_yaml("05-canvas/material-types.yaml")
    return data.get("material_types", [])


def load_canvas_type_aliases() -> dict[str, Any]:
    """Load canvas type-alias + LRT-mapping + short-whitelist from one YAML.

    Returns a dict with keys:
      - aliases:         dict[str, str]   keyword → canonical type id
      - short_whitelist: list[str]        short aliases allowed mid-text
      - lrt_to_type:     dict[str, str]   edu-sharing LRT → canvas type id

    Missing sections return empty containers.
    """
    data = _load_yaml("05-canvas/type-aliases.yaml") or {}
    return {
        "aliases": data.get("aliases", {}) or {},
        "short_whitelist": data.get("short_whitelist", []) or [],
        "lrt_to_type": data.get("lrt_to_type", {}) or {},
    }


def load_canvas_create_triggers() -> dict[str, list[str]]:
    """Load create-trigger verbs + search-verbs for canvas intent override.

    Returns dict with 'create_triggers' and 'search_verbs' (both list[str]).
    """
    data = _load_yaml("05-canvas/create-triggers.yaml") or {}
    return {
        "create_triggers": data.get("create_triggers", []) or [],
        "search_verbs": data.get("search_verbs", []) or [],
    }


def load_canvas_edit_triggers() -> dict[str, list[str]]:
    """Load edit-trigger verbs + explicit-create-overrides for Canvas-Edit.

    Returns dict with 'edit_triggers' and 'explicit_create_overrides'
    (both list[str]).
    """
    data = _load_yaml("05-canvas/edit-triggers.yaml") or {}
    return {
        "edit_triggers": data.get("edit_triggers", []) or [],
        "explicit_create_overrides": data.get("explicit_create_overrides", []) or [],
    }


def load_canvas_persona_priorities() -> dict[str, list[str]]:
    """Load persona-priority groups for canvas quick-reply ordering.

    Returns dict with key 'analytical_personas' (list of persona ids).
    """
    data = _load_yaml("05-canvas/persona-priorities.yaml") or {}
    return {
        "analytical_personas": data.get("analytical_personas", []) or [],
    }


def load_device_config() -> dict[str, Any]:
    """Load device config (max_items, persona_formality)."""
    return _load_yaml("01-base/device-config.yaml")


def load_persona_definitions() -> list[dict[str, str]]:
    """Load persona ID→label→description mapping from persona markdown files."""
    personas_dir = CHATBOT_DIR / "04-personas"
    if not personas_dir.exists():
        return []
    results = []
    for path in sorted(personas_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        pid = meta.get("id", "")
        if not pid:
            continue
        # Extract label from first heading: "# Lehrkraft [P-W-LK]"
        label = pid
        heading = re.search(r"^#\s+(.+?)(?:\s*\[.*\])?\s*$", body, re.MULTILINE)
        if heading:
            label = heading.group(1).strip()
        # Extract short description from "Primäre Ziele" section
        desc = ""
        goals_match = re.search(
            r"##\s*Prim.re Ziele\s*\n((?:[-*]\s+.*\n?)+)", body
        )
        if goals_match:
            goals = [
                line.lstrip("-* ").strip()
                for line in goals_match.group(1).strip().split("\n")
                if line.strip()
            ]
            desc = "; ".join(goals)

        # Extract detection hints from "Erkennungshinweise" section
        hints: list[str] = []
        hints_match = re.search(
            r"##\s*Erkennungshinweise\s*\n((?:[-*]\s+.*\n?)+)", body
        )
        if hints_match:
            for line in hints_match.group(1).strip().split("\n"):
                line = line.lstrip("-* ").strip()
                if line:
                    # Each line may contain multiple quoted phrases separated by commas
                    for phrase in re.findall(r'"([^"]+)"', line):
                        hints.append(phrase)
        results.append({"id": pid, "label": label, "description": desc, "hints": hints})
    return results


def load_rag_config() -> dict[str, dict[str, Any]]:
    """Load RAG area configuration (mode: always/on-demand per area).

    Returns dict like {"wlo-hilfe": {"mode": "always"}, "faq": {"mode": "on-demand"}}.
    """
    data = _load_yaml("05-knowledge/rag-config.yaml")
    # Top-level keys are area names, each with 'mode' and optional 'description'
    config: dict[str, dict[str, Any]] = {}
    for key, val in data.items():
        if isinstance(val, dict) and "mode" in val:
            config[key] = val
    return config


def get_always_on_rag_areas() -> list[str]:
    """Return list of RAG area names configured as 'always' available."""
    config = load_rag_config()
    return [area for area, cfg in config.items() if cfg.get("mode") == "always"]


def get_on_demand_rag_areas() -> list[str]:
    """Return list of RAG area names configured as 'on-demand'."""
    config = load_rag_config()
    return [area for area, cfg in config.items() if cfg.get("mode") == "on-demand"]


def get_all_rag_areas() -> list[str]:
    """Return all configured RAG area names."""
    config = load_rag_config()
    return list(config.keys())


def load_mcp_servers() -> list[dict[str, Any]]:
    """Load registered MCP servers from 05-knowledge/mcp-servers.yaml.

    Returns list of server dicts with id, name, url, description, enabled, tools.
    """
    data = _load_yaml("05-knowledge/mcp-servers.yaml")
    servers = data.get("servers", [])
    return [s for s in servers if isinstance(s, dict) and s.get("id")]


def save_mcp_servers(servers: list[dict[str, Any]]) -> None:
    """Save MCP server registry to 05-knowledge/mcp-servers.yaml."""
    import yaml as _yaml
    content = (
        "# MCP-Server-Registry\n"
        "# Registrierte MCP-Server fuer den Chatbot.\n\n"
    )
    content += _yaml.dump(
        {"servers": servers},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    write_config_file("05-knowledge/mcp-servers.yaml", content)


def get_enabled_mcp_servers() -> list[dict[str, Any]]:
    """Return only enabled MCP servers."""
    return [s for s in load_mcp_servers() if s.get("enabled", True)]


def load_policy_config() -> dict[str, Any]:
    """Load policy rules (Triple-Schema v2 — T-13/14) from 02-domain/policy.yaml."""
    return _load_yaml("02-domain/policy.yaml")


def load_safety_config() -> dict[str, Any]:
    """Load safety configuration (Triple-Schema v2 — T-12/19) from 01-base/safety-config.yaml."""
    return _load_yaml("01-base/safety-config.yaml")


def load_quality_log_config() -> dict[str, Any]:
    """Load quality logging configuration from 01-base/quality-log-config.yaml."""
    return _load_yaml("01-base/quality-log-config.yaml")


def load_privacy_config() -> dict[str, bool]:
    """Load privacy/logging toggles from 01-base/privacy-config.yaml.

    Returns a flat dict with the four toggles (messages, memory, quality,
    safety). Missing file or keys default to True (log-all).
    Safety is hardcoded to True — the YAML value is ignored on read so
    an accidental `safety: false` in the config file can't silence the
    audit trail.
    """
    data = _load_yaml("01-base/privacy-config.yaml") or {}
    section = (data.get("logging") if isinstance(data, dict) else None) or {}
    return {
        "messages": bool(section.get("messages", True)),
        "memory": bool(section.get("memory", True)),
        "quality": bool(section.get("quality", True)),
        "safety": True,  # not user-togglable
    }


def load_contexts() -> list[dict[str, Any]]:
    """Load named context definitions (T-04/05) from 04-contexts/contexts.yaml."""
    data = _load_yaml("04-contexts/contexts.yaml")
    return data.get("contexts", [])


def load_pattern_definitions() -> list[dict[str, Any]]:
    """Load all pattern definitions from 03-patterns/*.md files.

    Each file has YAML frontmatter with pattern fields. Returns a list of
    dicts that can be used to construct PatternDef objects.
    """
    patterns_dir = CHATBOT_DIR / "03-patterns"
    if not patterns_dir.exists():
        return []

    results = []
    for path in sorted(patterns_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        if not meta.get("id"):
            continue

        # Extract core_rule from body if not in frontmatter
        if "core_rule" not in meta:
            # Look for ## Kernregel section
            cr_match = re.search(r"## Kernregel\s*\n(.+?)(?:\n##|\Z)", body, re.DOTALL)
            if cr_match:
                meta["core_rule"] = cr_match.group(1).strip()

        meta["_source_file"] = str(path.relative_to(CHATBOT_DIR)).replace("\\", "/")
        results.append(meta)

    return results
