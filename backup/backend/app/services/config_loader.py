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


def get_state_directive(state_id: str) -> dict[str, Any]:
    """Return Conversation-Flow metadata for a given state.

    Welle C Sprint 6: States carry a ``role`` (Bot-Rolle in dieser Phase),
    ``bot_directive`` (Handlungs-Anweisung für den Response-Prompt) und
    ``next_likely`` (plausible Übergangs-States für den Plausibilitäts-
    Validator). Callers use this in three places:

    1. Response-Prompt (llm_service.generate_response) — directive an LLM.
    2. Quick-Reply-Generator — phase-spezifische QR-Vorschläge.
    3. Plausibilitäts-Validator (validate_transition) — next_likely-Check.

    Empty dict if state-id unknown — callers should treat this as
    "no directive" (Bot fällt auf Pattern-Default zurück).
    """
    for s in load_states():
        if s.get("id") == state_id:
            return {
                "id": s.get("id", ""),
                "label": s.get("label", ""),
                "role": s.get("role", ""),
                "bot_directive": s.get("bot_directive", "").strip(),
                "next_likely": s.get("next_likely", []),
            }
    return {}


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
        entry = {"id": pid, "label": label, "description": desc, "hints": hints}
        # Welle C.5 (2026-05): Tonalitäts-Modifier aus Frontmatter
        # durchreichen, damit ``load_tone_modifiers_config()`` sie
        # ohne separate YAML-Datei lesen kann. Felder sind optional —
        # wenn nicht im Frontmatter, fallen Defaults im Coerce.
        for k in ("tone", "length_bias", "formality",
                  "card_text_mode", "override"):
            if k in meta:
                entry[k] = meta[k]
        # Auch _source_file durchreichen, damit der PUT-Endpoint
        # weiß, welche Datei er beim Modifier-Update editieren muss.
        entry["_source_file"] = str(path.relative_to(CHATBOT_DIR)).replace("\\", "/")
        results.append(entry)
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


# Base-URL des edu-sharing-Repos. Muss zum MCP-Server (oben) passen, weil
# Node-IDs aus dem MCP-Repo stammen und die abgeleiteten ``wlo_url``-/
# ``preview_url``-Links genau auf dieses Repo zeigen müssen — sonst zeigen
# Produktion-Links auf Staging-Nodes (oder umgekehrt) und führen ins Leere.
#
# Production:  REPO_BASE_URL=https://redaktion.openeduhub.net
# Staging:     REPO_BASE_URL=https://repository.staging.openeduhub.net
#
# Default bleibt Production, damit Bestandsinstallationen unverändert
# funktionieren. Wer den Staging-MCP nutzt (MCP_SERVER_URL=...staging...),
# sollte REPO_BASE_URL gleichzeitig auf den Staging-Host umstellen.
_REPO_BASE_URL_ENV = "REPO_BASE_URL"
_REPO_BASE_URL_DEFAULT = "https://redaktion.openeduhub.net"


def get_repo_base_url() -> str:
    """Base-URL des edu-sharing-Repos für ``wlo_url``/``preview_url``-Bau.

    Env-Var ``REPO_BASE_URL`` hat Vorrang, sonst Production-Default.
    Trailing-Slash wird entfernt, damit aufrufender Code unbesorgt
    ``{base}/edu-sharing/...`` konkatenieren kann.
    """
    import os as _os
    raw = (_os.getenv(_REPO_BASE_URL_ENV) or "").strip().rstrip("/")
    return raw or _REPO_BASE_URL_DEFAULT


def rewrite_repo_host(url: str) -> str:
    """Schreibt URLs, die auf den Production-Repo-Default-Host zeigen, auf
    den konfigurierten ``REPO_BASE_URL`` um — nötig wenn der MCP-Server
    auf Staging zeigt, aber die ``previewUrl``/``contentUrl``-Felder
    serverseitig immer mit dem Production-Host gebaut werden. Ohne Rewrite
    landen Staging-Node-IDs auf Production-Hostnamen und liefern 404.

    Greift NUR, wenn:
      * Die URL nicht-leer ist und
      * Ein abweichender ``REPO_BASE_URL`` konfiguriert ist (sonst No-Op) und
      * Die URL exakt mit dem Production-Default-Host beginnt.

    Externe URLs (Wikipedia, YouTube, Verlage, andere Hosts im
    ``*.openeduhub.net``-Allow-List) bleiben unberührt.
    """
    if not isinstance(url, str) or not url:
        return url
    base = get_repo_base_url()
    if base == _REPO_BASE_URL_DEFAULT:
        return url  # Kein Rewrite nötig — Production-Konfiguration.
    if url.startswith(_REPO_BASE_URL_DEFAULT + "/") or url == _REPO_BASE_URL_DEFAULT:
        return base + url[len(_REPO_BASE_URL_DEFAULT):]
    return url


def rewrite_repo_host_v2(url: str, target_repo_base: str | None = None) -> str:
    """Card-Pipeline v2 Variante des Host-Rewrites: bidirektional und
    konfigurierbar über ``known_repo_hosts`` in card-pipeline.yaml.

    Im Gegensatz zu :func:`rewrite_repo_host` (das nur den hartcodierten
    Production-Default umschreibt) schreibt diese Funktion jeden bekannten
    Repo-Host auf den Target-Base um — egal ob die MCP-Antwort Production-
    auf-Staging oder Staging-auf-Production gemappt werden muss.

    Args:
        url: Eine URL aus einer Card (kann auch leer / extern sein).
        target_repo_base: Ziel-Repo-URL (Default: ``get_repo_base_url()``).

    Returns:
        Umgeschriebene URL, wenn der Host in ``known_repo_hosts`` steht
        und nicht bereits dem Target entspricht. Sonst die Original-URL.
    """
    if not isinstance(url, str) or not url:
        return url
    target = (target_repo_base or get_repo_base_url()).rstrip("/")
    if not target:
        return url
    # Wenn die URL bereits auf den Target-Host zeigt, nichts zu tun.
    if url == target or url.startswith(target + "/"):
        return url
    # Bekannte Repo-Hosts aus YAML (mit Production-Fallback, falls die
    # YAML noch nicht existiert oder leer ist).
    known = _load_card_pipeline_raw().get("known_repo_hosts") or [
        _REPO_BASE_URL_DEFAULT,
        "https://repository.staging.openeduhub.net",
        "https://repository.openeduhub.net",
    ]
    for host in known:
        h = str(host or "").rstrip("/")
        if not h or h == target:
            continue
        if url == h:
            return target
        if url.startswith(h + "/"):
            return target + url[len(h):]
    return url


def _load_card_pipeline_raw() -> dict[str, Any]:
    """Roh-Lesefunktion für card-pipeline.yaml — wird intern auch von
    :func:`rewrite_repo_host_v2` genutzt, damit dort der gleiche YAML-Cache
    greift wie für die anderen Card-Pipeline-Settings.
    """
    data = _load_yaml("01-base/card-pipeline.yaml") or {}
    return data.get("card_pipeline") or {}


def load_card_pipeline_config() -> dict[str, Any]:
    """Lädt die Card-Pipeline v2 Konfiguration aus 01-base/card-pipeline.yaml.

    Returns ein Dict mit clamped/typisierten Werten:
      - ``pool_size`` (5..50, default 20)
      - ``llm_curation_pool`` (1..pool_size, default min(15, pool_size))
      - ``final_selection_size`` (1..10, default 5)
      - ``enable_llm_curation`` (bool, default True)
      - ``min_displayed_cards`` (0..final_selection_size, default 5)
      - ``known_repo_hosts`` (list[str], default Production + Staging)

    Wenn die Datei fehlt oder die Werte fehlerhaft sind, fallen wir auf
    sichere Defaults zurück — die Pipeline läuft auch dann.
    """
    cfg = _load_card_pipeline_raw()

    def _int_clamp(key: str, default: int, lo: int, hi: int) -> int:
        raw = cfg.get(key)
        if raw is None:
            return default
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, v))

    pool_size = _int_clamp("pool_size", 20, 5, 50)
    llm_pool = _int_clamp("llm_curation_pool", min(15, pool_size), 1, pool_size)
    final_size = _int_clamp("final_selection_size", 5, 1, 10)
    min_displayed = _int_clamp("min_displayed_cards", 5, 0, final_size)

    raw_enable = cfg.get("enable_llm_curation")
    enable_llm = True if raw_enable is None else bool(raw_enable)

    raw_hosts = cfg.get("known_repo_hosts") or []
    known_hosts: list[str] = []
    for h in raw_hosts:
        s = str(h or "").strip().rstrip("/")
        if s and s not in known_hosts:
            known_hosts.append(s)
    if not known_hosts:
        known_hosts = [
            _REPO_BASE_URL_DEFAULT,
            "https://repository.staging.openeduhub.net",
            "https://repository.openeduhub.net",
        ]

    return {
        "pool_size": pool_size,
        "llm_curation_pool": llm_pool,
        "final_selection_size": final_size,
        "enable_llm_curation": enable_llm,
        "min_displayed_cards": min_displayed,
        "known_repo_hosts": known_hosts,
    }


def card_pipeline_v2_enabled() -> bool:
    """True, wenn der Env-Flag ``CARD_PIPELINE_V2`` auf einen truthy Wert
    gesetzt ist (1/true/yes/on, case-insensitive).

    Solange False, läuft die alte Logik. Wir nutzen das, um die neue
    Pipeline schrittweise einzuführen und A/B-Vergleiche zu fahren.
    """
    import os as _os
    val = (_os.getenv("CARD_PIPELINE_V2") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


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

    # cards_inline_link_limit: 1..6, default 5
    raw_limit = cfg.get("cards_inline_link_limit")
    try:
        limit = int(raw_limit) if raw_limit is not None else 5
    except (TypeError, ValueError):
        limit = 5
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


# Default-Wortliste für den Placeholder-Filter. Wird nur als Fallback
# verwendet, wenn 01-base/placeholder-topics.yaml fehlt oder keine
# Liste enthält. Synchron halten mit der YAML-Datei.
_PLACEHOLDER_TOPICS_DEFAULT: tuple[str, ...] = (
    "thema", "themen", "ein thema", "einem thema", "irgendwas",
    "etwas", "was", "irgendetwas", "irgendein thema", "sonstiges",
    "material", "materialien", "ein material", "ein paar materialien",
    "sachen", "dinge", "stuff", "topic", "etwas thema",
    "inhalt", "inhalte", "content",
)


def load_placeholder_topics_config() -> dict[str, Any]:
    """Lade die Placeholder-Topics-Konfiguration aus
    01-base/placeholder-topics.yaml.

    Gibt zurück:
      - ``topics`` : set[str]  -- Begriffe (lowercase, getrimmt), die als
        Platzhalter behandelt werden. Der Backend-Filter setzt
        ``classification.entities['thema']`` auf "" wenn der Wert in
        dieser Menge enthalten ist.
      - ``min_length`` : int  -- Werte mit weniger Zeichen (nach strip)
        gelten ebenfalls als Platzhalter. Default 3 (lässt "OER",
        "DSGVO" als gültige Topics durch, fängt aber Tippfehler ab).

    Fehlt die Datei oder enthält sie keine Liste, fallen wir auf die
    historische Default-Liste (``_PLACEHOLDER_TOPICS_DEFAULT``) zurück,
    damit Bestandsinstallationen wie heute funktionieren.
    """
    data = _load_yaml("01-base/placeholder-topics.yaml") or {}
    raw_list = data.get("placeholder_topics")

    topics: set[str] = set()
    if isinstance(raw_list, list) and raw_list:
        for item in raw_list:
            s = str(item or "").strip().lower()
            if s:
                topics.add(s)
    if not topics:
        topics = {t for t in _PLACEHOLDER_TOPICS_DEFAULT}

    raw_min = data.get("min_topic_length")
    try:
        min_length = int(raw_min) if raw_min is not None else 3
    except (TypeError, ValueError):
        min_length = 3
    # Defensive Clamp: 0..10. 0 deaktiviert den Length-Check effektiv,
    # >10 wäre absurd kurz/lang für ein Topic.
    min_length = max(0, min(10, min_length))

    return {"topics": topics, "min_length": min_length}


_VALID_FORMALITIES = {"duzen", "siezen", "wie_user"}
_VALID_CARD_TEXT_MODES = {"minimal", "kurz", "explanation", "ausfuehrlich"}


def _coerce_tone_modifier(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a raw tone-modifier dict (Frontmatter or YAML) to the
    canonical schema. Used by ``load_tone_modifiers_config``.
    """
    if not isinstance(raw, dict):
        raw = {}
    tone = str(raw.get("tone") or "locker").strip() or "locker"
    try:
        length_bias = float(raw.get("length_bias", 0.0))
    except (TypeError, ValueError):
        length_bias = 0.0
    length_bias = max(-0.3, min(0.3, length_bias))
    formality = str(raw.get("formality") or "wie_user").strip()
    if formality not in _VALID_FORMALITIES:
        formality = "wie_user"
    card_text_mode = str(raw.get("card_text_mode") or "minimal").strip()
    if card_text_mode not in _VALID_CARD_TEXT_MODES:
        card_text_mode = "minimal"
    return {
        "tone": tone,
        "length_bias": length_bias,
        "formality": formality,
        "card_text_mode": card_text_mode,
        "override": bool(raw.get("override", False)),
    }


def load_tone_modifiers_config() -> dict[str, Any]:
    """Load Persona-Tonalitäts-Modifier — Single-Source aus Persona-MD-Frontmatter.

    Welle C.5 (2026-05): Modifier-Daten leben jetzt direkt im Frontmatter
    der jeweiligen Persona-Datei (``04-personas/<persona>.md``). Das
    ersetzt die separate ``01-base/tone-modifiers.yaml`` und vermeidet
    Doppelung zwischen Persona-Tonalitäts-Beschreibung (Markdown) und
    strukturierten Modifier-Werten (vorher YAML, jetzt Frontmatter).

    Returns:
        dict mit zwei Top-Level-Keys:
          - ``modifiers`` : dict[persona_id, dict] mit Pro-Persona-Modifiern.
          - ``default``   : dict mit Fallback-Modifier für unbekannte Personas.

    Fallback-Kaskade:
      1. Frontmatter pro Persona-MD (Single-Source).
      2. Falls Persona-Datei keine Modifier-Felder hat: Default
         (BOERDi-Locker-Duzen).
      3. Falls die historische ``01-base/tone-modifiers.yaml`` noch
         existiert (Migrations-Backup), wird sie als ZWEITE Fallback-
         Ebene gelesen, damit Rollback möglich bleibt.
    """
    # Primary source: Persona-Frontmatter
    modifiers: dict[str, dict[str, Any]] = {}
    try:
        for p in load_persona_definitions():
            pid = p.get("id")
            if not pid:
                continue
            # Check if any modifier field is set in frontmatter
            if any(k in p for k in ("tone", "length_bias", "formality",
                                     "card_text_mode", "override")):
                modifiers[str(pid)] = _coerce_tone_modifier(p)
    except Exception:
        modifiers = {}

    # Secondary source: historisches YAML (nur wenn Frontmatter leer)
    if not modifiers:
        data = _load_yaml("01-base/tone-modifiers.yaml") or {}
        raw_modifiers = data.get("modifiers") or {}
        for pid, raw in raw_modifiers.items():
            if not pid:
                continue
            modifiers[str(pid)] = _coerce_tone_modifier(raw)

    # Default-Modifier — stets aus tone-modifiers.yaml (falls existent),
    # sonst aus statischem Code-Default. Das default_modifier ist nicht
    # Persona-spezifisch, gehört also nicht ins Persona-Frontmatter.
    default_data = _load_yaml("01-base/tone-modifiers.yaml") or {}
    default = _coerce_tone_modifier(default_data.get("default_modifier") or {})

    return {"modifiers": modifiers, "default": default}


_PERSONA_SLUG_MAP: dict[str, str] = {
    "P-W-LK": "lk", "P-W-SL": "sl", "P-W-POL": "pol", "P-W-PRESSE": "presse",
    "P-W-RED": "red", "P-BER": "ber", "P-VER": "ver", "P-ELT": "elt", "P-AND": "and",
}


def _persona_slug(persona_id: str) -> str:
    """Map persona-id (``P-W-LK``) to filename slug (``lk``)."""
    return _PERSONA_SLUG_MAP.get(persona_id, persona_id.lower().replace("p-", ""))


# Header-Block für das Modifier-Frontmatter — wird beim Persona-Update
# eingefügt, falls eine Persona-Datei noch keine Modifier-Felder hat.
_PERSONA_MODIFIER_HEADER = (
    "# ── Tonalitäts-Modifier (Welle B.3 / C.5, 2026-05) ──────────────\n"
)

_MODIFIER_KEYS = ("tone", "length_bias", "formality", "card_text_mode", "override")


def update_persona_modifier_in_frontmatter(
    persona_id: str,
    modifier: dict[str, Any],
) -> bool:
    """Update the 5 modifier fields in a persona's MD frontmatter.

    Welle C.5 (2026-05): Schreibt die normalisierten Modifier-Felder
    direkt in das YAML-Frontmatter der jeweiligen Persona-MD-Datei. Das
    ist die Single-Source — kein separater YAML-Round-Trip mehr.

    Implementation: Liest die existierende Datei, ersetzt nur die
    Modifier-Zeilen (oder fügt sie am Ende des Frontmatters ein), schreibt
    zurück. Lässt allen anderen Frontmatter-Content + den gesamten
    Markdown-Body unverändert.

    Returns True bei Erfolg, False wenn die Persona-Datei nicht gefunden
    wurde oder keine Frontmatter hat.
    """
    slug = _persona_slug(persona_id)
    rel_path = f"04-personas/{slug}.md"
    full = CHATBOT_DIR / rel_path
    if not full.exists():
        return False

    text = full.read_text(encoding="utf-8")
    m = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", text, re.DOTALL)
    if not m:
        return False
    prefix, fm_body, sep, body = m.groups()

    # Normalize the modifier (clamp / defaults) so we don't write garbage.
    canonical = _coerce_tone_modifier(modifier)

    # Strip existing modifier lines (preserve comment-line above them so
    # repeated updates don't re-duplicate the header).
    fm_lines = fm_body.split("\n")
    new_lines: list[str] = []
    skip_next_blank_after_header = False
    for ln in fm_lines:
        stripped = ln.strip()
        # Match keys at top-level: "key: value" with up to 2 leading spaces
        is_modifier_line = False
        for k in _MODIFIER_KEYS:
            if re.match(rf"^\s*{re.escape(k)}\s*:", ln):
                is_modifier_line = True
                break
        # Drop our header-comment too (we'll re-add it below)
        is_header_comment = "Tonalitäts-Modifier" in ln and ln.lstrip().startswith("#")
        if is_modifier_line or is_header_comment:
            continue
        new_lines.append(ln)

    # Trim trailing blank lines so we get a clean append point.
    while new_lines and new_lines[-1].strip() == "":
        new_lines.pop()

    # Append the canonical modifier block (with header comment).
    new_lines.append(_PERSONA_MODIFIER_HEADER.rstrip("\n"))
    new_lines.append(f"tone: {canonical['tone']}")
    new_lines.append(f"length_bias: {canonical['length_bias']}")
    new_lines.append(f"formality: {canonical['formality']}")
    new_lines.append(f"card_text_mode: {canonical['card_text_mode']}")
    new_lines.append(f"override: {str(canonical['override']).lower()}")

    new_fm = "\n".join(new_lines)
    new_text = f"{prefix}{new_fm}{sep}{body}"
    full.write_text(new_text, encoding="utf-8")
    return True


def get_tone_modifier_for_persona(persona_id: str | None) -> dict[str, Any]:
    """Lookup-Helper: Modifier für eine konkrete Persona-ID liefern.

    Falls die Persona nicht in der YAML steht oder die ID leer ist,
    wird der ``default_modifier`` zurückgegeben.
    """
    cfg = load_tone_modifiers_config()
    if not persona_id:
        return cfg["default"]
    return cfg["modifiers"].get(str(persona_id)) or cfg["default"]


# Welle E (2026-05): tie_breaker / persona_loosening / pattern_selection
# Configs entfernt — LLM-Hint ist die Pattern-Auswahl, kein Override-Mechanismus
# mehr nötig.  Funktionen sind als no-op-Stubs für Backwards-Kompat
# erhalten (z.B. wenn Tests sie noch importieren), liefern aber konstante
# Disabled-Defaults zurück.

def load_tie_breaker_config() -> dict[str, Any]:
    """Welle E stub — Tie-Breaker ist obsolet.  Liefert immer disabled."""
    return {
        "enabled": False,
        "live": False,
        "max_score_gap": 0.05,
        "top_n_window": 2,
        "allow_patterns_winner": [],
    }


def load_pattern_selection_mode() -> str:
    """Welle E stub — Pattern-Selection-Mode ist obsolet.

    Pattern-Wahl läuft jetzt immer per LLM-Hint (mit Safety- und
    Klärungs-Fallback). Diese Funktion bleibt nur erhalten, damit alter
    Code, der sie noch importiert, nicht crashed.
    """
    return "llm_hint"


def load_eval_setup_config() -> dict[str, Any]:
    """Load eval setup parameters (Welle D, 2026-05).

    Returned shape::

        {
            "persona_marker_gate": "strict" | "warn" | "off",
        }

    Defaults: ``warn`` (telemetry only, no drops) — chosen because the
    aggressive strict mode lost >80% of generated scenarios in real runs.
    """
    data = _load_yaml("01-base/eval-config.yaml") or {}
    cfg = data.get("eval_setup") or {}
    mode = str(cfg.get("persona_marker_gate", "warn")).strip().lower()
    if mode not in ("strict", "warn", "off"):
        mode = "warn"
    return {"persona_marker_gate": mode}


def load_cross_persona_scenarios() -> dict[str, Any]:
    """Load curated atypical persona×intent combos for stress-testing
    (Welle D Shadow-A/B addon).

    Returns::

        {
            "enabled": bool,    # Default from YAML; the eval-run flag overrides this.
            "combos": [
                {"persona_id": "P-W-SL", "intent_id": "INT-W-10",
                 "description": "...", "expected_behavior": "..."},
                ...
            ],
        }

    Missing file → empty combo list, enabled=False (safe default).
    """
    data = _load_yaml("01-base/cross-persona-scenarios.yaml") or {}
    cfg = data.get("cross_persona_scenarios") or {}
    combos_raw = cfg.get("combos") or []
    combos: list[dict[str, str]] = []
    for c in combos_raw:
        if not isinstance(c, dict):
            continue
        pid = str(c.get("persona_id") or "").strip()
        iid = str(c.get("intent_id") or "").strip()
        if not pid or not iid:
            continue
        combos.append({
            "persona_id": pid,
            "intent_id": iid,
            "description": str(c.get("description") or "").strip(),
            "expected_behavior": str(c.get("expected_behavior") or "").strip(),
        })
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "combos": combos,
    }


def load_persona_loosening_config() -> dict[str, Any]:
    """Welle E stub — Persona-Loosening ist obsolet (Persona entkoppelt)."""
    return {
        "enabled": False,
        "live": False,
        "persona_trait_signals": set(),
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

    Welle E (2026-05-17) — Naming convention switch:
        * Neue Patterns folgen dem Muster ``p<N>-<slug>.md`` mit lower-case
          ``p`` (z.B. ``p01-krisen-empathie.md``, ``p13-slot-klaerung.md``).
        * Alte Patterns mit Prefix ``pat-`` (z.B. ``pat-06-degradation-...``)
          werden **nicht mehr geladen**.  Sie bleiben als Backup-Referenz
          im Repo, sind aber für die Routing-Engine unsichtbar.

    Each new file has YAML frontmatter with pattern fields. Returns a list
    of dicts that can be used to construct PatternDef objects.
    """
    patterns_dir = CHATBOT_DIR / "03-patterns"
    if not patterns_dir.exists():
        return []

    results = []
    for path in sorted(patterns_dir.glob("*.md")):
        name = path.name
        # Welle E filter: only load new-scheme files (p01-..., p13-..., ...).
        # Old pat-* files are ignored — see migration note above.
        if not re.match(r"^p\d+-", name):
            continue

        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        if not meta.get("id"):
            continue

        # Extract core_rule from body if not in frontmatter
        if "core_rule" not in meta:
            cr_match = re.search(r"## Kernregel\s*\n(.+?)(?:\n##|\Z)", body, re.DOTALL)
            if cr_match:
                meta["core_rule"] = cr_match.group(1).strip()

        meta["_source_file"] = str(path.relative_to(CHATBOT_DIR)).replace("\\", "/")
        results.append(meta)

    return results
