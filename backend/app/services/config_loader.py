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
    """Render the Layer-3 persona block for the response prompt.

    Welle E v2 (2026-05-25): Statt der rohen MD-Datei (die Klassifikations-
    Marker enthält, die NICHT in den Antwort-Prompt gehören) bauen wir
    hier eine kompakte Persönlichkeits-Beschreibung aus den Frontmatter-
    Feldern, die für die Antwort relevant sind:

      * description     — wer ist diese Persona
      * tone/formality  — wie soll der Bot klingen
      * goals           — was will diese Persona vom Bot
      * rules           — Antwort-Stil-Regeln
      * personality_text — freier Body-Text

    Klassifikations-Felder (positive_markers, anti_markers, discriminators,
    typical_intents) bleiben AUSSEN VOR — sie würden den Antwort-LLM mit
    irrelevantem Kontext fluten (~500 Token pro Persona) und ihn dazu
    verleiten, Marker-Phrasen wörtlich zu rezitieren.
    """
    slug = _persona_slug(persona_id)
    path = CHATBOT_DIR / "04-personas" / f"{slug}.md"
    if not path.exists():
        return f"Persona: {persona_id} (Standard-Persona)"

    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    if not meta:
        # Old-style file without frontmatter → return raw (best-effort).
        return text

    label = str(meta.get("label") or persona_id)
    desc = str(meta.get("description") or "").strip()
    tone = str(meta.get("tone") or "").strip()
    formality = str(meta.get("formality") or "").strip()
    length_bias = meta.get("length_bias")

    parts: list[str] = [f"## Persona: {persona_id} — {label}"]
    if desc:
        parts.append(desc)

    # Tone/formality als kompakte Anweisung
    style_bits: list[str] = []
    if tone:
        style_bits.append(f"Tonfall {tone}")
    if formality:
        f_label = {
            "duzen": "duze die Person",
            "siezen": "sieze die Person",
            "wie_user": "übernimm die Anrede des Users",
            "neutral": "halte die Anrede neutral, bis sie klar ist",
        }.get(formality, formality)
        style_bits.append(f_label)
    try:
        lb = float(length_bias) if length_bias is not None else 0.0
        if lb > 0.15:
            style_bits.append("antworte etwas ausführlicher als sonst")
        elif lb < -0.15:
            style_bits.append("antworte etwas knapper als sonst")
    except (TypeError, ValueError):
        pass
    if style_bits:
        parts.append("**Stil**: " + "; ".join(style_bits) + ".")

    goals = [str(x).strip() for x in (meta.get("goals") or []) if str(x).strip()]
    if goals:
        parts.append("**Ziele dieser Persona**:")
        parts.extend(f"- {g}" for g in goals)

    rules = [str(x).strip() for x in (meta.get("rules") or []) if str(x).strip()]
    if rules:
        parts.append("**Antwort-Regeln**:")
        parts.extend(f"- {r}" for r in rules)

    # Persönlichkeits-Prosa aus Body (H1 entfernen, alles andere lassen)
    body_clean = re.sub(r"^\s*#\s+.*\n", "", body, count=1).strip()
    if body_clean:
        parts.append(body_clean)

    return "\n\n".join(parts)


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


# ──────────────────────────────────────────────────────────────────────
# Round-Trip YAML — Welle E (2026-05-25)
#
# ruamel.yaml im round-trip-Modus erhält:
#   - Header-Kommentare (z. B. das SCHEMA-Doku-Block in intents.yaml)
#   - Inline-Kommentare zwischen Items
#   - Quote-Stil (single vs double)
#   - Indentation
#
# Nutzen: Studio-PUT-Endpoints (PATCH /api/config/intents etc.) können
# die GANZE Liste neu setzen, ohne dass die ausführliche YAML-Doku am
# Anfang der Datei weggeputzt wird. Wir bauen genau einmal pro Save-
# Request ein neues YAML-Dokument, behalten aber die Top-Level-Struktur.
# ──────────────────────────────────────────────────────────────────────

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.scalarstring import LiteralScalarString
except ImportError:  # pragma: no cover — ruamel ist in requirements.txt
    YAML = None  # type: ignore
    LiteralScalarString = None  # type: ignore


def _build_roundtrip_yaml() -> Any:
    """Build a configured ruamel.yaml instance for our round-trip needs.

    - ``typ='rt'`` enables round-trip mode (comment/quote preservation).
    - ``indent`` matches the existing 2/4/2 layout of our YAML files.
    - ``width`` set high so simple scalars stay on one line (no surprise
      line-wraps mid-bullet that confuse human editors).
    """
    if YAML is None:
        return None
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 200
    return y


_ROUNDTRIP_YAML = _build_roundtrip_yaml()


def load_yaml_roundtrip(rel_path: str) -> Any:
    """Load a YAML file in round-trip mode (preserves comments)."""
    if _ROUNDTRIP_YAML is None:
        # Fallback: plain pyyaml — comments are lost, but at least
        # the structural data round-trips.
        return _load_yaml(rel_path)
    path = CHATBOT_DIR / rel_path
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return _ROUNDTRIP_YAML.load(f)


def save_yaml_roundtrip(rel_path: str, data: Any) -> None:
    """Persist a YAML structure with round-trip formatting.

    Validates the path is inside CHATBOT_DIR and invalidates both the
    plain-YAML mtime-cache (so subsequent ``_load_yaml`` calls re-parse)
    and the round-trip cache (none — we don't cache rt YAMLs, they're
    written ad-hoc for save events).
    """
    path = _validate_config_path(rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _ROUNDTRIP_YAML is None:
        # Last-resort fallback: pyyaml dump (loses comments).
        import yaml as _yaml
        with path.open("w", encoding="utf-8") as f:
            _yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    else:
        with path.open("w", encoding="utf-8") as f:
            _ROUNDTRIP_YAML.dump(data, f)
    invalidate_yaml_cache(rel_path)


def _multiline_str(s: str) -> Any:
    """Coerce a string into a YAML literal block scalar (``|``) so multi-
    line directives (e.g. ``states.yaml:bot_directive``) render readably
    after a round-trip save.

    Returns a plain string if the input is single-line — block style is
    only useful for actual multi-line content.
    """
    if not isinstance(s, str):
        return s
    if "\n" not in s:
        return s
    if LiteralScalarString is None:
        return s
    return LiteralScalarString(s)


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


# ──────────────────────────────────────────────────────────────────────────
# Persona-Markdown — strukturierte Sektionen lesen
#
# Welle E (2026-05-25): Persona-Dateien haben jetzt strukturierte Sektionen
# (## Positiv-Marker, ## Anti-Marker, ## Diskriminatoren, ## Ziele, …) die
# der Klassifizier-Prompt-Builder genau wie YAML-Felder rendern kann.
#
# Quote-Tolerance: Phrasen in Bullets dürfen mit "...", '...', „..." oder
# »...« umrahmt sein — alle Varianten werden extrahiert. Ohne Quotes wird
# der Bullet-Text selbst als Phrase genommen (für Markdown-Listen ohne
# typografische Quotes).
# ──────────────────────────────────────────────────────────────────────────

_PHRASE_QUOTE_RE = re.compile(
    r'"([^"]+)"|'           # ASCII double
    r"'([^']+)'|"           # ASCII single
    r"„([^“]+)“|"  # German „..."
    r"«([^»]+)»"    # «...»
)


def _extract_md_section(body: str, *names: str) -> str:
    """Return the body of the first ``## <name>`` section found.

    Tries each ``name`` in order, returns the section body verbatim
    (without the heading). Section ends at the next ``## `` heading or
    end-of-file. Sub-headings ``###`` stay inside the returned block.
    Returns ``""`` if no matching section exists.
    """
    for name in names:
        # Heading match is permissive — allows trailing parentheses,
        # markers, emoji etc. after the section name.
        rx = re.compile(
            rf"^##\s+{re.escape(name)}[^\n]*\n([\s\S]*?)(?=^##\s|\Z)",
            re.MULTILINE,
        )
        m = rx.search(body)
        if m:
            return m.group(1)
    return ""


def _extract_bullet_phrases(section_body: str) -> list[str]:
    """Pull bulleted phrases from a markdown section body.

    Each ``- ...`` bullet is read. Quote-rules:
      * If the bullet contains one or more quoted spans, every quoted
        phrase is added (independently — so ``- "a / b"`` adds ``a / b``,
        ``- "a", "b"`` adds both).
      * If the bullet has no quotes, its full text (after the dash) is
        added as a single phrase (with trailing ``— erklärung`` stripped).

    Sub-headings (``### `` lines) and blank lines are ignored.
    """
    phrases: list[str] = []
    for raw_line in (section_body or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Skip sub-headings and arbitrary bold lines used as group titles.
        if line.startswith("#") or (line.startswith("**") and line.endswith("**")):
            continue
        # Only proper bullets — skip prose paragraphs between bullets.
        if not (line.startswith("- ") or line.startswith("* ")):
            continue
        bullet = line[2:].strip()
        if not bullet:
            continue
        found_any = False
        for match in _PHRASE_QUOTE_RE.finditer(bullet):
            for grp in match.groups():
                if grp:
                    phrases.append(grp.strip())
                    found_any = True
        if not found_any:
            # No quotes — take the bullet text itself (drop trailing
            # ``— note`` / ``-- note`` so the phrase stays tight).
            clean = re.split(r"\s+[—–-]{1,2}\s+", bullet, maxsplit=1)[0].strip()
            if clean:
                phrases.append(clean)
    return phrases


def _extract_section_lines(section_body: str) -> list[str]:
    """Return non-empty bullet lines from a section (used for ``ziele``,
    ``regeln``, ``diskriminatoren`` where we keep the full sentence).

    Each line is stripped of its leading dash/asterisk, indent, and
    trailing whitespace. Sub-headings are dropped. Useful when we want
    to show whole bullet sentences in the prompt, not just quoted
    phrases.
    """
    out: list[str] = []
    for raw_line in (section_body or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("**") and line.endswith("**"):
            # Group sub-headings inside the section — drop.
            continue
        if line.startswith("- ") or line.startswith("* "):
            out.append(line[2:].strip())
    return out


def load_persona_definitions() -> list[dict[str, Any]]:
    """Load persona definitions from 04-personas/*.md files.

    Welle E v2 (2026-05-25): Alle strukturierten Daten leben jetzt im
    YAML-Frontmatter — einheitlich mit intents.yaml / states.yaml /
    entities.yaml. Body ist nur noch optionale Persönlichkeits-Prosa.

    Frontmatter-Felder (alle optional außer id/label):
      id, label, description
      tone, length_bias, formality, card_text_mode, override (Modifier)
      positive_markers      — list[str]
      anti_markers          — list[{phrase, redirect_to?, rationale?}]
      discriminators        — list[{vs, rule, example_a?, example_b?}]
      goals                 — list[str]
      rules                 — list[str]
      typical_intents       — list[str]

    Backward-Compat: Wenn ein File noch das v1-Schema (MD-Sektionen) hat,
    parsen wir die Sektionen als Fallback — damit alte Files bis zur
    nächsten Bearbeitung weiterleben.
    """
    personas_dir = CHATBOT_DIR / "04-personas"
    if not personas_dir.exists():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(personas_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        pid = meta.get("id", "")
        if not pid:
            continue

        # Label: Frontmatter > erstes Heading > Fallback ID
        label = str(meta.get("label") or "").strip()
        if not label:
            heading = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
            if heading:
                raw = heading.group(1).strip()
                # "P-LER — Lerner:in / Schüler:in" → "Lerner:in / Schüler:in"
                label = re.sub(r"^P-[A-Z]+\s*[—–-]\s*", "", raw).strip() or raw
            else:
                label = pid

        desc = str(meta.get("description") or "").strip()

        # ── Strukturierte Klassifikations-Felder ──
        positive_markers = _normalize_str_list(meta.get("positive_markers"))
        anti_markers = _normalize_anti_markers(meta.get("anti_markers"))
        discriminators = _normalize_persona_discriminators(meta.get("discriminators"))
        goals = _normalize_str_list(meta.get("goals"))
        rules = _normalize_str_list(meta.get("rules"))
        typical_intents = _normalize_str_list(meta.get("typical_intents"))

        # ── Backward-Compat: MD-Sektionen lesen wenn Frontmatter leer ──
        if not positive_markers:
            pos_body = _extract_md_section(
                body, "Positiv-Marker", "Erkennungshinweise", "Marker",
            )
            positive_markers = _extract_bullet_phrases(pos_body)
        if not anti_markers:
            anti_body = _extract_md_section(body, "Anti-Marker")
            anti_markers = [{"phrase": p} for p in _extract_bullet_phrases(anti_body)]
        if not discriminators:
            disc_body = _extract_md_section(body, "Diskriminatoren", "Abgrenzung")
            discriminators = [
                {"vs": "", "rule": line}
                for line in _extract_section_lines(disc_body)
                if line
            ]
        if not goals:
            goals_body = _extract_md_section(
                body, "Ziele", "Primäre Ziele", "Primaere Ziele",
            )
            goals = _extract_section_lines(goals_body)
            if not desc and goals_body:
                desc = "; ".join(goals) if goals else goals_body.strip().split("\n")[0]
        if not rules:
            rules_body = _extract_md_section(body, "Regeln")
            rules = _extract_section_lines(rules_body)

        # Body als Persönlichkeits-Prosa (ohne H1-Heading)
        personality = re.sub(r"^\s*#\s+.*\n", "", body, count=1).strip()

        entry: dict[str, Any] = {
            "id": pid,
            "label": label,
            "description": desc,
            "positive_markers": positive_markers,
            # Backward-Compat-Alias — viele Konsumenten lesen ``hints``.
            "hints": positive_markers,
            "anti_markers": anti_markers,
            "discriminators": discriminators,
            "goals": goals,
            "rules": rules,
            "typical_intents": typical_intents,
            "personality_text": personality,
        }
        # Tonality-Modifier (optional)
        for k in ("tone", "length_bias", "formality", "card_text_mode", "override"):
            if k in meta:
                entry[k] = meta[k]
        entry["_source_file"] = str(path.relative_to(CHATBOT_DIR)).replace("\\", "/")
        results.append(entry)
    return results


def _normalize_str_list(raw: Any) -> list[str]:
    """Coerce a Frontmatter list-of-strings into a clean ``list[str]``."""
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x or "").strip()]
    return []


def _normalize_anti_markers(raw: Any) -> list[dict[str, str]]:
    """Coerce ``anti_markers`` into a uniform list of dicts.

    Accepts:
      - list[str] (legacy plain phrases) → dicts with only ``phrase``.
      - list[dict] with ``phrase`` (req), ``redirect_to``, ``rationale``.
    """
    if not raw or not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append({"phrase": item.strip()})
        elif isinstance(item, dict) and item.get("phrase"):
            entry = {"phrase": str(item["phrase"]).strip()}
            if item.get("redirect_to"):
                entry["redirect_to"] = str(item["redirect_to"]).strip()
            if item.get("rationale"):
                entry["rationale"] = str(item["rationale"]).strip()
            out.append(entry)
    return out


def _normalize_persona_discriminators(raw: Any) -> list[dict[str, str]]:
    """Coerce ``discriminators`` (vs/rule/example_a/example_b) into dicts."""
    if not raw or not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("vs"):
            continue
        entry = {
            "vs": str(item["vs"]).strip(),
            "rule": str(item.get("rule") or "").strip(),
        }
        for k in ("example_a", "example_b"):
            if item.get(k):
                entry[k] = str(item[k]).strip()
        out.append(entry)
    return out


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
        "repo_base_url": get_repo_base_url(),
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


def load_website_tour_config() -> dict[str, Any]:
    """Webseiten-Tour-Skript aus 01-base/website-tour.yaml (Domänwissen).

    Gibt den ``website_tour``-Block zurück (Texte, Ziel-URLs, Gruppen,
    Gruppe→Angebot-Mapping, Kontakt-Links). Studio-pflegbar — das VERHALTEN
    (State Machine, Ankunfts-Erkennung) liegt deterministisch im Backend
    (``tour_service.py`` + ``chat.py``). ``enabled`` default True; mtime-Cache
    via ``_load_yaml`` wie bei den übrigen Loadern.
    """
    data = _load_yaml("01-base/website-tour.yaml") or {}
    cfg = data.get("website_tour")
    if not isinstance(cfg, dict):
        return {"enabled": False, "groups": [], "steps": {}}
    cfg["enabled"] = bool(cfg.get("enabled", True))
    return cfg


def load_display_rules_config() -> dict[str, Any]:
    """Studio-pflegbare Display-Regeln aus 01-base/display-rules.yaml.

    Welle E (2026-05-23) — zentralisiert das WAS-und-WIE der Anzeige:
      * inline_documents     — Lernpfad/KI-Material in gerahmter Box
      * single_content_box   — Einzelinhalte als Box (default an, max 3)
      * groups               — Maximal-Anzahl pro Gruppen-Box
      * inline_card_links    — Inline-Markdown-Limit (wenn Host-Schalter
                                cards-enabled=false greift)
      * quick_replies        — max_count + inline_fallback
      * prompt_anzeige_konsistenz — RAG-Curation an/aus, Pattern-Excludes

    Werte werden auf sane Bounds gewrapt damit eine kaputt editierte YAML
    nicht die Response brechen kann. Frontend bekommt das Ergebnis als
    Echo-Feld ``ChatResponse.display_rules`` jeden Turn (kein extra
    Endpoint nötig), darf aber zusätzlich /api/config/display-rules
    abfragen wenn es die Settings beim Bootstrap haben will.
    """
    data = _load_yaml("01-base/display-rules.yaml") or {}
    cfg = data.get("display_rules") or {}

    # ── inline_documents ──
    ind = cfg.get("inline_documents") or {}
    raw_font = ind.get("font_size_percent")
    try:
        font_pct = int(raw_font) if raw_font is not None else 85
    except (TypeError, ValueError):
        font_pct = 85
    font_pct = max(70, min(100, font_pct))

    per_pat_raw = ind.get("per_pattern") or {}
    per_pattern: dict[str, bool] = {}
    for k, v in per_pat_raw.items():
        try:
            per_pattern[str(k).strip().upper()] = bool(v)
        except Exception:
            continue
    # Defaults für M09/M10/M11 falls fehlend.
    for _pid in ("M09", "M10", "M11"):
        per_pattern.setdefault(_pid, True)

    intro_raw = ind.get("intro_text") or {}
    intro_text: dict[str, str] = {}
    for k, v in intro_raw.items():
        s = str(v or "").strip()
        if s:
            intro_text[str(k).strip().upper()] = s

    inline_documents = {
        "enabled": bool(ind.get("enabled", True)),
        "font_size_percent": font_pct,
        "per_pattern": per_pattern,
        "intro_text": intro_text,
    }

    # ── groups (4 Box-Typen — Welle E konsolidiert) ──
    # Backward-Compat: ``single_content_box.max_count`` aus alten YAMLs
    # wird als Fallback für ``groups.materialien_max`` akzeptiert. Wenn
    # beide Werte gesetzt sind, gewinnt der explizite ``groups``-Eintrag.
    grp = cfg.get("groups") or {}
    scb_raw = cfg.get("single_content_box") or {}
    _legacy_max = scb_raw.get("max_count")

    def _grp_int(key: str, default: int, lo: int, hi: int) -> int:
        raw = grp.get(key)
        if raw is None and key == "materialien_max" and _legacy_max is not None:
            raw = _legacy_max  # Backward-Compat
        try:
            v = int(raw) if raw is not None else default
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    groups = {
        "themenseiten_max": _grp_int("themenseiten_max", 3, 1, 20),
        "sammlungen_max":   _grp_int("sammlungen_max",   3, 1, 20),
        "materialien_max":  _grp_int("materialien_max",  3, 1, 8),
        "webseiten_max":    _grp_int("webseiten_max",    3, 1, 30),
    }

    # ── single_content_box (nur noch enabled + layout) ──
    # ``max_count`` lebt jetzt in ``groups.materialien_max``. Wir halten
    # die Property aber zwecks Echo-Stabilität für ältere Frontend-
    # Versionen weiter im Output — gemappt aus groups.
    scb_layout = str(scb_raw.get("layout") or "card").strip().lower()
    if scb_layout not in ("card", "list"):
        scb_layout = "card"
    single_content_box = {
        "enabled": bool(scb_raw.get("enabled", True)),
        "max_count": groups["materialien_max"],
        "layout": scb_layout,
    }

    # ── inline_card_links ──
    icl = cfg.get("inline_card_links") or {}
    raw_lim = icl.get("limit")
    try:
        icl_lim = int(raw_lim) if raw_lim is not None else 3
    except (TypeError, ValueError):
        icl_lim = 3
    icl_lim = max(1, min(6, icl_lim))
    raw_tt = icl.get("title_max_chars")
    try:
        icl_tt = int(raw_tt) if raw_tt is not None else 70
    except (TypeError, ValueError):
        icl_tt = 70
    icl_tt = max(30, min(200, icl_tt))
    inline_card_links = {"limit": icl_lim, "title_max_chars": icl_tt}

    # ── quick_replies ──
    qr = cfg.get("quick_replies") or {}
    raw_qrm = qr.get("max_count")
    try:
        qr_max = int(raw_qrm) if raw_qrm is not None else 4
    except (TypeError, ValueError):
        qr_max = 4
    qr_max = max(0, min(6, qr_max))
    quick_replies = {
        "max_count": qr_max,
        "inline_fallback_enabled": bool(qr.get("inline_fallback_enabled", True)),
    }

    # ── prompt_anzeige_konsistenz ──
    pak = cfg.get("prompt_anzeige_konsistenz") or {}
    excl_raw = pak.get("exclude_patterns") or []
    excl: list[str] = []
    for e in excl_raw:
        s = str(e or "").strip().upper()
        if s and s not in excl:
            excl.append(s)
    prompt_anzeige_konsistenz = {
        "enabled": bool(pak.get("enabled", True)),
        "exclude_patterns": excl,
    }

    return {
        "inline_documents": inline_documents,
        "single_content_box": single_content_box,
        "groups": groups,
        "inline_card_links": inline_card_links,
        "quick_replies": quick_replies,
        "prompt_anzeige_konsistenz": prompt_anzeige_konsistenz,
    }


def load_guide_rules_config() -> dict[str, Any]:
    """Lotsen-Regeln aus 02-domain/guide-rules.yaml (Welle E, 2026-05-23).

    Liefert ``message_rules`` (Liste von Dicts mit ``pattern``, ``label``,
    ``url``, ``priority``) und ``rag_area_rules`` (Dict area→{label, url,
    brand_pattern}). Wird vom ``guide_qr_injector`` als Datenquelle
    genutzt — alte Hardcoded-Regeln im Python-Modul bleiben als Fallback,
    werden aber nicht mehr aktiv verwendet sobald die YAML lädt.

    Defensive Defaults: bei kaputter YAML kommt eine leere Struktur
    zurück, das Modul fällt dann auf seinen eigenen Hardcoded-Fallback
    zurück (keine Crash, keine fehlenden Buttons).
    """
    data = _load_yaml("02-domain/guide-rules.yaml") or {}

    raw_msgs = data.get("message_rules") or []
    msg_rules: list[dict[str, Any]] = []
    for item in raw_msgs:
        if not isinstance(item, dict):
            continue
        pat = str(item.get("pattern") or "").strip()
        lbl = str(item.get("label") or "").strip()
        url = str(item.get("url") or "").strip()
        if not (pat and lbl and url):
            continue
        try:
            prio = int(item.get("priority") or 50)
        except (TypeError, ValueError):
            prio = 50
        msg_rules.append({
            "pattern": pat,
            "label": lbl,
            "url": url,
            "priority": prio,
        })

    raw_rag = data.get("rag_area_rules") or {}
    rag_rules: dict[str, dict[str, str]] = {}
    if isinstance(raw_rag, dict):
        for area, cfg in raw_rag.items():
            if not isinstance(cfg, dict):
                continue
            lbl = str(cfg.get("label") or "").strip()
            url = str(cfg.get("url") or "").strip()
            bp = str(cfg.get("brand_pattern") or "").strip()
            if not (lbl and url and bp):
                continue
            rag_rules[str(area).strip()] = {
                "label": lbl,
                "url": url,
                "brand_pattern": bp,
            }

    return {
        "message_rules": msg_rules,
        "rag_area_rules": rag_rules,
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


# Welle E v2 (2026-05-25): 1:1-Mapping persona-id → filename slug.
# Frühere Slug-Variabilität (lk/sl/pol/presse/ber/ver) wurde aufgeräumt.
_PERSONA_SLUG_MAP: dict[str, str] = {
    "P-AND": "and",
    "P-ELT": "elt",
    "P-ENT": "ent",
    "P-LEH": "leh",
    "P-LER": "ler",
    "P-RED": "red",
}


def _persona_slug(persona_id: str) -> str:
    """Map persona-id (``P-LEH``) to filename slug (``leh``)."""
    if persona_id in _PERSONA_SLUG_MAP:
        return _PERSONA_SLUG_MAP[persona_id]
    # Default-Fallback: P-XYZ → xyz
    return persona_id.lower().replace("p-", "", 1)


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


def load_tie_breaker_config() -> dict[str, Any]:
    """Welle E v4 (2026-05-25): Tie-Breaker entfernt — der Hint-Primary-
    Pfad in ``pattern_engine.select_pattern`` braucht keine Score-Race-
    Override-Mechanik mehr. Funktion bleibt als no-op Shim, damit
    Aufrufer (z.B. ältere Eval-Snapshots) keinen ImportError werfen.
    """
    return {
        "enabled": False,
        "max_score_gap": 0.05,
        "top_n_window": 2,
        "allow_patterns_winner": [],
    }


def load_classify_overrides_config() -> dict[str, Any]:
    """Klassifikations-Overrides aus 01-base/classify-overrides.yaml.

    Welle E v4+6 (2026-05-26): Persona-/Intent-/Topic-Hard-Overrides +
    Pattern-Disambiguatoren + Few-Shot-Examples für den classify-Prompt.
    Vorher hartkodiert in llm_service.py; jetzt YAML-bearbeitbar.

    Returns:
        Dict mit Schlüsseln: persona_overrides, intent_overrides,
        topic_overrides, pattern_disambiguators, few_shot_examples.
        Bei kaputter/fehlender YAML alle Listen leer.
    """
    data = _load_yaml("01-base/classify-overrides.yaml") or {}
    return {
        "persona_overrides": data.get("persona_overrides") or [],
        "intent_overrides": data.get("intent_overrides") or [],
        "intent_conflict_rule": data.get("intent_conflict_rule") or "",
        "topic_overrides": data.get("topic_overrides") or {},
        "pattern_disambiguators": data.get("pattern_disambiguators") or [],
        "few_shot_examples": data.get("few_shot_examples") or [],
    }


def load_privacy_config() -> dict[str, bool]:
    """Load privacy/logging toggles from 01-base/privacy-config.yaml.

    Returns a flat dict with four toggles (messages, memory, quality,
    safety). Missing file or keys default to True (log-all). Safety is
    hardcoded to True — the YAML value is ignored on read so an
    accidental `safety: false` in the config file can't silence the
    audit trail.

    Welle E v4+12 (Sprint K, 2026-05-27): ``rules``-Toggle entfernt —
    Rule-Engine und shadow_router wurden komplett ausgebaut.
    """
    data = _load_yaml("01-base/privacy-config.yaml") or {}
    section = (data.get("logging") if isinstance(data, dict) else None) or {}
    return {
        "messages": bool(section.get("messages", True)),
        "memory": bool(section.get("memory", True)),
        "quality": bool(section.get("quality", True)),
        "safety": True,  # not user-togglable
    }


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

        # Welle E v3 (2026-05-25): structured sections live in frontmatter.
        # If a pattern hasn't been migrated yet, fall back to MD-section parsing.

        # core_rule
        if "core_rule" not in meta:
            cr_match = re.search(
                r"##\s+Kernregel[^\n]*\n(.+?)(?:\n##|\Z)", body, re.DOTALL,
            )
            if cr_match:
                meta["core_rule"] = cr_match.group(1).strip()

        # forbidden_phrases (Bullet-Liste mit ❌-Markern)
        if "forbidden_phrases" not in meta:
            phrases: list[str] = []
            for sect in ("Verbotene Formulierungen", "Verbotene Anti-Patterns"):
                rx = re.compile(
                    rf"##\s+{re.escape(sect)}[^\n]*\n([\s\S]*?)(?=^##\s|\Z)",
                    re.MULTILINE,
                )
                m = rx.search(body)
                if not m:
                    continue
                for line in m.group(1).splitlines():
                    s = line.strip()
                    bm = re.match(r"^[-*]\s+(.*)$", s)
                    if not bm:
                        continue
                    item = re.sub(r"^[❌✕✗]\s*", "", bm.group(1).strip()).strip()
                    item = re.sub(r'^[„"](.*?)["“]$', r"\1", item).strip()
                    if item and item not in phrases:
                        phrases.append(item)
            if phrases:
                meta["forbidden_phrases"] = phrases

        # anti_patterns (Bullet-Liste, semantisch verschieden von forbidden_phrases —
        # anti_patterns sind FALSCHE Handlungen/Strategien, forbidden_phrases sind
        # konkrete Wortlaute).
        if "anti_patterns" not in meta:
            patterns: list[str] = []
            for sect in ("Anti-Patterns", "Nicht tun"):
                rx = re.compile(
                    rf"##\s+{re.escape(sect)}[^\n]*\n([\s\S]*?)(?=^##\s|\Z)",
                    re.MULTILINE,
                )
                m = rx.search(body)
                if not m:
                    continue
                for line in m.group(1).splitlines():
                    s = line.strip()
                    bm = re.match(r"^[-*]\s+(.*)$", s)
                    if not bm:
                        continue
                    item = bm.group(1).strip()
                    if item and item not in patterns:
                        patterns.append(item)
            if patterns:
                meta["anti_patterns"] = patterns

        # Normalize list fields — ensure str-list regardless of YAML quirks
        for key in ("forbidden_phrases", "anti_patterns"):
            if key in meta:
                meta[key] = [str(x).strip() for x in (meta[key] or []) if str(x).strip()]

        # Welle E v4+7 (2026-05-26): strukturierte Pattern-Auswahl-Regeln
        # (when_to_use, when_not_to_use, trigger_phrases) als Listen,
        # discriminators als Liste von Dicts {vs, rule, example}. Normalize
        # damit kaputt-editierte YAML nicht den Loader bricht.
        for key in ("when_to_use", "when_not_to_use", "trigger_phrases"):
            if key in meta:
                meta[key] = [
                    str(x).strip() for x in (meta[key] or []) if str(x).strip()
                ]
        if "discriminators" in meta:
            cleaned: list[dict] = []
            for d in (meta["discriminators"] or []):
                if not isinstance(d, dict):
                    continue
                vs = str(d.get("vs") or "").strip()
                rule = str(d.get("rule") or "").strip()
                example = str(d.get("example") or "").strip()
                if vs and rule:
                    cleaned.append({"vs": vs, "rule": rule, "example": example})
            meta["discriminators"] = cleaned

        # Body for the Pattern-Brief: strip H1 (= title, already in `label`)
        # AND strip the sections we've migrated above (so they don't appear
        # twice in the response prompt — once as structured field, once as raw
        # markdown). Sections that aren't migrated stay in body_md so things
        # like ``## Pflicht-Antwort-Schema`` reach the LLM verbatim.
        body_stripped = re.sub(r"^\s*#\s+.*\n", "", body, count=1)
        for sect in ("Kernregel \\(HART\\)", "Kernregel",
                     "Verbotene Formulierungen \\(würden Bug 1 reproduzieren\\)",
                     "Verbotene Formulierungen", "Verbotene Anti-Patterns",
                     "Anti-Patterns", "Nicht tun"):
            body_stripped = re.sub(
                rf"^##\s+{sect}[^\n]*\n[\s\S]*?(?=^##\s|\Z)",
                "", body_stripped, flags=re.MULTILINE,
            )
        body_stripped = re.sub(r"\n{3,}", "\n\n", body_stripped).strip()
        meta["body_md"] = body_stripped

        meta["_source_file"] = str(path.relative_to(CHATBOT_DIR)).replace("\\", "/")
        results.append(meta)

    return results
