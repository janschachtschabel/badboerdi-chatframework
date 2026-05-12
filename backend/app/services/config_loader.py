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

        # Extract detection hints from "Erkennungshinweise" section.
        # Accepts blank lines + bold sub-headings between bullets (e.g. presse.md
        # / elt.md group hints under "**Self-ID-Phrasen:**" / "**Vokabeln:**").
        # Section ends at the NEXT heading (## or ### — both must terminate so
        # that "### Abgrenzung zu …" doesn't pollute hints with cross-persona
        # markers from the discriminator text).
        hints: list[str] = []
        hints_section = re.search(
            r"##\s*Erkennungshinweise\s*\n([\s\S]*?)(?=\n#{2,}\s|\Z)", body
        )
        if hints_section:
            for line in hints_section.group(1).split("\n"):
                stripped = line.strip()
                if not stripped or stripped.startswith("##"):
                    continue
                # Pull every quoted phrase from EVERY line — bullets, bold
                # sub-headings ("**Vokabeln:**"), and prose all welcome.
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


# ID des Primary-Servers (WLO). Seine URL ist *ausschließlich* per Env
# steuerbar (``MCP_SERVER_URL``); Studio / YAML können sie nicht ändern.
# Alle anderen Server in der Registry sind über das Studio frei
# editier-, hinzufüg- und entfernbar.
_PRIMARY_MCP_SERVER_ID = "wlo-mcp"
_PRIMARY_MCP_URL_ENV = "MCP_SERVER_URL"
_PRIMARY_MCP_URL_DEFAULT = "https://wlo-mcp-server.vercel.app/mcp"


def _resolve_primary_mcp_url() -> str:
    """URL des Primary-MCP-Servers — Env hat Vorrang, sonst Hardcoded-Default.

    Toleriert die docker-compose-Falle eines leeren Env-Strings und
    entfernt Trailing-Slashes.
    """
    import os as _os
    raw = (_os.getenv(_PRIMARY_MCP_URL_ENV) or "").strip().rstrip("/")
    return raw or _PRIMARY_MCP_URL_DEFAULT


# Default-Skeleton für den Primary-Eintrag — wird genutzt, wenn der Save-
# Schutz den Primary wiederherstellen muss und die YAML keinen brauchbaren
# Stand mehr liefert (z.B. weil sie überhaupt nicht existiert).
_PRIMARY_MCP_DEFAULT_ENTRY: dict[str, Any] = {
    "id": _PRIMARY_MCP_SERVER_ID,
    "name": "WLO edu-sharing",
    "description": "WirLernenOnline MCP-Server mit Such- und Metadaten-Tools",
    "enabled": True,
    "tools": [
        "search_wlo_collections",
        "search_wlo_content",
        "get_collection_contents",
        "get_node_details",
        "lookup_wlo_vocabulary",
        "search_wlo_topic_pages",
        "get_subject_portals",
        "browse_collection_tree",
        "wlo_health_check",
        "get_nodes_details",
    ],
}


def _load_primary_from_yaml() -> dict[str, Any]:
    """Liefert den aktuellen Primary-Eintrag direkt aus der YAML — ohne
    Env-Override oder UI-Hint-Felder. Wird beim Save genutzt, falls der
    Primary aus dem eingehenden Payload fehlt; wir greifen dann auf den
    zuletzt persistierten Stand zurück. Wenn die YAML keinen Primary
    hat, kommt der Hardcoded-Skeleton (mit allen 10 Default-Tools).
    """
    try:
        data = _load_yaml("05-knowledge/mcp-servers.yaml")
        for s in data.get("servers", []):
            if isinstance(s, dict) and s.get("id") == _PRIMARY_MCP_SERVER_ID:
                # Defensiv-kopieren, damit Anrufer den Cache nicht mutieren.
                # ``url`` (falls historisch in der YAML) raus — der Primary
                # bekommt seine URL beim Read aus der Env-Var.
                clone = {k: v for k, v in s.items() if k != "url"}
                return clone
    except Exception:
        pass
    # Defensivkopie der Default-Tool-Liste — damit ein späterer Aufrufer
    # die Modul-Konstante nicht versehentlich mutiert.
    return {**_PRIMARY_MCP_DEFAULT_ENTRY, "tools": list(_PRIMARY_MCP_DEFAULT_ENTRY["tools"])}


def load_mcp_servers() -> list[dict[str, Any]]:
    """Load registered MCP servers from 05-knowledge/mcp-servers.yaml.

    Returns list of server dicts with id, name, url, description, enabled, tools.

    URL-Auflösung pro Server:
      * **Primary (id=wlo-mcp)**: URL kommt *immer* aus
        ``MCP_SERVER_URL`` (Env), Default ``_PRIMARY_MCP_URL_DEFAULT``.
        Ein eventueller ``url``-Wert in der YAML wird ignoriert. Zusätzlich
        bekommt der Eintrag ``url_source: "env"`` + ``url_env_var`` und
        ``url_readonly: True``, damit das Studio-UI die URL als read-only
        markieren kann.
      * **Sonstige Server** (vom Studio hinzugefügt): YAML-``url`` gilt,
        ``url_source: "yaml"``, ``url_readonly: False``.
    """
    data = _load_yaml("05-knowledge/mcp-servers.yaml")
    servers = [s for s in data.get("servers", []) if isinstance(s, dict) and s.get("id")]

    primary_url = _resolve_primary_mcp_url()
    for s in servers:
        if s.get("id") == _PRIMARY_MCP_SERVER_ID:
            s["url"] = primary_url
            s["url_source"] = "env"
            s["url_env_var"] = _PRIMARY_MCP_URL_ENV
            s["url_readonly"] = True
        else:
            s.setdefault("url_source", "yaml")
            s.setdefault("url_readonly", False)
    return servers


def save_mcp_servers(servers: list[dict[str, Any]]) -> None:
    """Save MCP server registry to 05-knowledge/mcp-servers.yaml.

    Schutzlogik:
      * **Primary (id=wlo-mcp)**: ``url`` wird vor dem Schreiben aus dem
        Eintrag entfernt (kommt zur Laufzeit immer aus der Env-Var).
        Schickt das Studio versehentlich eine geänderte URL für den
        Primary mit, wird sie silent verworfen.
      * **Primary-Pflicht**: Fehlt der Primary-Eintrag in der eingehenden
        Liste komplett (z.B. weil ihn jemand im Studio gelöscht hat oder
        weil ein versehentliches ``PUT []`` kam), legen wir ihn aus dem
        zuvor-persistierten YAML-Stand wieder an. Notfallminimum: ein
        leerer Skeleton mit Default-Tools. Damit kann der Primary nicht
        weggeschossen werden — die Bot-Funktionalität bleibt erhalten.
      * **Meta-Felder** (``url_source``, ``url_env_var``, ``url_readonly``)
        sind reine Anzeigehilfen für die UI und werden nicht persistiert.
      * **Sonstige Server**: bleiben wie übergeben.
    """
    import yaml as _yaml

    cleaned: list[dict[str, Any]] = []
    has_primary = False
    for s in servers:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        # Strip UI-only meta fields
        out = {k: v for k, v in s.items()
               if k not in ("url_source", "url_env_var", "url_readonly", "tool_descriptions")}
        # Primary: niemals eine url persistieren — sie kommt aus Env.
        if s.get("id") == _PRIMARY_MCP_SERVER_ID:
            out.pop("url", None)
            has_primary = True
        cleaned.append(out)

    # Primary-Pflicht: wenn er gelöscht wurde, wiederherstellen.
    if not has_primary:
        primary_entry = _load_primary_from_yaml()
        # An Position 0 einsetzen, damit der Primary in der Studio-UI
        # weiterhin oben auftaucht (gleiche Lese-Reihenfolge wie load).
        cleaned.insert(0, primary_entry)
        import logging
        logging.getLogger(__name__).warning(
            "save_mcp_servers: Primary-Eintrag (id=%s) fehlte im Payload — "
            "automatisch wiederhergestellt. Die UI sollte den Primary nicht "
            "löschbar machen.",
            _PRIMARY_MCP_SERVER_ID,
        )

    content = (
        "# MCP-Server-Registry\n"
        "# Registrierte MCP-Server fuer den Chatbot.\n"
        f"#\n# Primary-Server (id={_PRIMARY_MCP_SERVER_ID}): URL kommt aus der\n"
        f"# Env-Variable ``{_PRIMARY_MCP_URL_ENV}`` (Default:\n"
        f"# {_PRIMARY_MCP_URL_DEFAULT}). Nicht in dieser YAML eintragen — sie\n"
        "# wird vom Backend automatisch gefiltert.\n#\n"
        "# Weitere Server können über das Studio (System → MCP-Server →\n"
        "# Hinzufuegen) frei verwaltet werden — sie bekommen ihre url\n"
        "# regulaer aus dieser YAML.\n\n"
    )
    content += _yaml.dump(
        {"servers": cleaned},
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


def load_guide_mode_config() -> dict[str, Any]:
    """Load Webseiten-Guide-Modus configuration.

    Returns the parsed ``guide_mode`` block from 01-base/guide-mode.yaml
    with safe defaults if the file is missing. The frontend reads this
    once at widget-init via /api/config/guide-mode and uses it for the
    allow-list check; the backend uses the same data to decide whether
    to attach ``guide_url`` to outgoing cards.
    """
    data = _load_yaml("01-base/guide-mode.yaml") or {}
    cfg = data.get("guide_mode") or {}
    # NB: ``max_guide_targets_per_turn`` honours 0 as "unlimited". The
    # earlier `or 5` coerced 0 → 5, silently capping every response at
    # 5 cards even when the YAML asked for unlimited. Now: only fall
    # back to 5 when the key is missing or non-int, never on 0.
    raw_max = cfg.get("max_guide_targets_per_turn")
    if raw_max is None:
        max_targets = 5
    else:
        try:
            max_targets = int(raw_max)
        except (TypeError, ValueError):
            max_targets = 5

    # max_guide_quick_replies: Anzahl Bring-mich-hin-Buttons in der
    # Quick-Reply-Reihe. Auf [1, 3] geclamped — 0 würde das Feature
    # abschalten, 4 würde keinen Platz für Folge-Fragen lassen
    # (UX-Anti-Pattern). Default 2 wenn fehlend / non-int.
    raw_qr = cfg.get("max_guide_quick_replies")
    if raw_qr is None:
        max_guide_qrs = 2
    else:
        try:
            max_guide_qrs = int(raw_qr)
        except (TypeError, ValueError):
            max_guide_qrs = 2
    max_guide_qrs = max(1, min(3, max_guide_qrs))

    # Cross-TLD-Session-Brücke: Liste vertrauenswürdiger Domains für
    # ``?bsid=…&bgm=…``-Handoff. Env-Override per ``GUIDE_TRUSTED_DOMAINS``
    # (Komma- oder Whitespace-getrennt) — überschreibt YAML komplett,
    # damit pro Deployment unterschiedliche Allow-Listen gefahren werden
    # können (Staging vs. Prod).
    import os as _os
    import re as _re_td
    env_td = (_os.getenv("GUIDE_TRUSTED_DOMAINS") or "").strip()
    if env_td:
        td_raw = _re_td.split(r"[,\s]+", env_td)
    else:
        td_raw = list(cfg.get("trusted_domains") or [])
    trusted_domains: list[str] = []
    for d in td_raw:
        s = str(d or "").strip()
        if not s:
            continue
        # Toleriere ``https://``/``http://``-Präfix und trailing-slashes —
        # gleiche Normalisierung wie im Frontend.
        s = _re_td.sub(r"^https?://", "", s, flags=_re_td.IGNORECASE)
        s = s.strip("/").lower()
        if s and s not in trusted_domains:
            trusted_domains.append(s)

    return {
        "default_enabled": bool(cfg.get("default_enabled", True)),
        "allowed_hosts": [str(h).strip().lower()
                          for h in (cfg.get("allowed_hosts") or [])
                          if str(h).strip()],
        "url_fields_priority": list(cfg.get("url_fields_priority") or [
            "topic_page_url", "wlo_url", "url", "content_url", "preview_url",
        ]),
        "max_guide_targets_per_turn": max_targets,
        "max_guide_quick_replies": max_guide_qrs,
        "trusted_domains": trusted_domains,
    }


def load_widget_modes_config() -> dict[str, Any]:
    """Load Widget-Embed-Modi configuration.

    Returns the parsed ``widget_modes`` block from 01-base/widget-modes.yaml
    with safe defaults. The four host-side flags (cards-enabled, canvas-
    enabled, ai-content-enabled, quick-replies-enabled) come from the
    embedded widget via the Environment block — this file just specifies
    the *consequences* (link limits, fallback texts).

    Limits are clamped to sane bounds so a misconfigured YAML can't break
    the response shape.
    """
    data = _load_yaml("01-base/widget-modes.yaml") or {}
    cfg = data.get("widget_modes") or {}

    # cards_inline_link_limit: 1..6, default 3
    raw_limit = cfg.get("cards_inline_link_limit")
    try:
        limit = int(raw_limit) if raw_limit is not None else 3
    except (TypeError, ValueError):
        limit = 3
    limit = max(1, min(6, limit))

    # cards_inline_link_title_max: 30..200 chars, default 70
    raw_title = cfg.get("cards_inline_link_title_max")
    try:
        title_max = int(raw_title) if raw_title is not None else 70
    except (TypeError, ValueError):
        title_max = 70
    title_max = max(30, min(200, title_max))

    alt = cfg.get("ai_disabled_alt_response") or {}
    alt_text = str(alt.get("text") or
                   "Auf dieser Seite kann ich gerade kein neues Material "
                   "für dich erstellen. Magst du dir stattdessen bestehende "
                   "Inhalte zeigen lassen?").strip()
    alt_qrs = [str(q).strip() for q in (alt.get("quick_replies") or [])
               if str(q).strip()]

    return {
        "cards_inline_link_limit": limit,
        "cards_inline_link_title_max": title_max,
        "ai_disabled_alt_response": {
            "text": alt_text,
            "quick_replies": alt_qrs,
        },
    }


def load_tie_breaker_config() -> dict[str, Any]:
    """Load Pattern-Engine tie-breaker configuration (Bonus 2).

    Returns the parsed ``tie_breaker`` block from 01-base/tie-breaker.yaml.
    Missing file or empty block → safe defaults (disabled, empty allow list).
    """
    data = _load_yaml("01-base/tie-breaker.yaml") or {}
    cfg = data.get("tie_breaker") or {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "max_score_gap": float(cfg.get("max_score_gap", 0.05) or 0.05),
        "top_n_window": int(cfg.get("top_n_window", 2) or 2),
        "allow_patterns_winner": list(cfg.get("allow_patterns_winner") or []),
    }


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
