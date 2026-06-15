"""Config router — serves and updates chatbot configuration files for the Studio."""

from __future__ import annotations

import io
import logging
import os
import re
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.models.schemas import ConfigFile
from app.services.auth import require_studio_key
from app.services.config_loader import (
    CHATBOT_DIR,
    list_config_files,
    read_config_file,
    write_config_file,
)

logger = logging.getLogger(__name__)

# Where server-side snapshots live (persist across restarts, relative to
# the backend root so Docker-volumes can mount it).
_BACKEND_DIR = Path(__file__).resolve().parents[2]
SNAPSHOTS_DIR = _BACKEND_DIR / "snapshots"

router = APIRouter()

# Public sub-router for endpoints the embedded widget consumes WITHOUT
# Studio auth — e.g. ``/api/config/guide-mode`` is fetched by every
# Web-Component instance at boot to learn the allow-list. Studio-auth on
# the main router would block that with 401 in production. Mounted
# separately in main.py with NO ``_studio_deps``.
public_router = APIRouter()


@router.get("/files")
async def get_config_files():
    """List all configuration files (markdown, JSON, YAML)."""
    return list_config_files()


@router.get("/file")
async def get_config_file(path: str):
    """Read a specific config file by relative path."""
    content = read_config_file(path)
    if not content and not path:
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": path, "content": content}


@router.put("/file")
async def update_config_file(file: ConfigFile):
    """Update or create a config file."""
    write_config_file(file.path, file.content)
    return {"status": "saved", "path": file.path}


@router.delete("/file")
async def delete_config_file(path: str):
    """Delete a config file."""
    import os
    from app.services.config_loader import _validate_config_path
    try:
        full_path = _validate_config_path(path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if full_path.exists():
        os.remove(full_path)
        return {"status": "deleted", "path": path}
    raise HTTPException(status_code=404, detail="File not found")


# ── Privacy / Logging switches ─────────────────────────────────────
#
# Thin typed wrapper around 01-base/privacy-config.yaml so the Studio
# doesn't have to know the YAML schema. Safety logging is hard-coded to
# True — the YAML value is ignored on read AND reset to true on every
# write so a leaked write can't silence the audit trail.

class PrivacyConfig(BaseModel):
    messages: bool = True
    memory: bool = True
    quality: bool = True
    # read-only; shown so the Studio can display it, but PUT ignores it
    safety: bool = True
    # Welle E v4+12 (Sprint K, 2026-05-27): rules-Toggle entfernt —
    # Rule-Engine wurde komplett ausgebaut.


@router.get("/privacy", response_model=PrivacyConfig)
async def get_privacy_config():
    """Return the current chat/memory/quality logging toggles."""
    from app.services.config_loader import load_privacy_config
    return PrivacyConfig(**load_privacy_config())


# ── Tone-Modifier (Welle B.3 / C.5) ──────────────────────────────
#
# Persona-Tonalitäts-Modifier werden im Persona-Editor unter dem
# Markdown-Bereich als Form-UI angezeigt (siehe ElementEditor.tsx).
# Diese Endpoints liefern + speichern die strukturierten Modifier-
# Werte separat von der Persona-MD-Datei, damit der Studio nicht
# auf YAML-Round-Trip-Logik im Frontend angewiesen ist.

class ToneModifier(BaseModel):
    tone: str = "locker"
    length_bias: float = 0.0  # [-0.3 .. +0.3]
    formality: str = "wie_user"  # duzen | siezen | wie_user
    card_text_mode: str = "minimal"  # minimal | kurz | explanation | ausfuehrlich
    override: bool = False


class ToneModifiersPayload(BaseModel):
    modifiers: dict[str, ToneModifier]
    default_modifier: ToneModifier


_TONE_MODIFIERS_PATH = "01-base/tone-modifiers.yaml"
_TONE_MODIFIERS_HEADER = (
    "# Tonalitäts-Modifier pro Persona — verwaltet im Studio (Persona-Editor)\n"
    "# ----------------------------------------------------------------------\n"
    "# Persona ist KEIN Pattern-Selektor — sie modifiziert nur tone/length/\n"
    "# formality/card_text_mode der Bot-Antwort. Pattern bleibt unabhängig.\n"
    "#\n"
    "# Schema pro Persona:\n"
    "#   tone           : sachlich | warm | locker | professionell | formell\n"
    "#                    | kollegial | ermutigend | sachorientiert | …\n"
    "#   length_bias    : float in [-0.3 .. +0.3]. -0.2 = ca. 20% kürzer.\n"
    "#                    Wird auf Pattern.default_length angerechnet.\n"
    "#   formality      : duzen | siezen | wie_user\n"
    "#                    'wie_user' = Bot spiegelt User-Anrede.\n"
    "#   card_text_mode : minimal | kurz | explanation | ausfuehrlich\n"
    "#   override       : true  = Modifier überschreibt Pattern-Defaults\n"
    "#                    false = Modifier ist nur Hinweis (Pattern wins)\n"
    "#\n"
    "# Editing: Persona-Studio (Element-Browser → Personas → Persona auswählen).\n"
    "# Änderungen wirken live (mtime-Cache-Invalidation).\n"
)


def _serialize_tone_modifier(m: ToneModifier) -> str:
    return (
        f"    tone: {m.tone}\n"
        f"    length_bias: {m.length_bias}\n"
        f"    formality: {m.formality}\n"
        f"    card_text_mode: {m.card_text_mode}\n"
        f"    override: {str(m.override).lower()}\n"
    )


@router.get("/tone-modifiers", response_model=ToneModifiersPayload)
async def get_tone_modifiers_route():
    """Return all persona tone-modifiers + default fallback.

    Schema mirror of ``01-base/tone-modifiers.yaml`` — used by the
    Persona-Editor's tonality form. Reads via the live mtime-cache, so
    edits to the YAML on disk show up here without restart.
    """
    from app.services.config_loader import load_tone_modifiers_config
    cfg = load_tone_modifiers_config()
    return ToneModifiersPayload(
        modifiers={k: ToneModifier(**v) for k, v in cfg["modifiers"].items()},
        default_modifier=ToneModifier(**cfg["default"]),
    )


@router.put("/tone-modifiers", response_model=ToneModifiersPayload)
async def put_tone_modifiers_route(payload: ToneModifiersPayload):
    """Persist tone-modifiers — Single-Source aus Persona-MD-Frontmatter.

    Welle C.5 (2026-05): Schreibt die Modifier pro Persona DIREKT in das
    Frontmatter der jeweiligen ``04-personas/<persona>.md``-Datei. Das
    ersetzt die historische ``01-base/tone-modifiers.yaml`` und vermeidet
    Doppelung mit dem ``## Tonalität``-Markdown-Block der Persona-Datei.

    Der ``default_modifier`` bleibt in ``01-base/tone-modifiers.yaml`` —
    das ist nicht Persona-spezifisch, sondern der Fallback für unbekannte
    Personas (z.B. ein Custom-Persona-ID, das aus der LLM-Klassifikation
    kommt aber kein Eintrag in 04-personas/ hat).

    Die Studio-API bleibt identisch: PUT mit Bulk-Map. Der Helper im
    Loader (``update_persona_modifier_in_frontmatter``) erledigt den
    Round-Trip pro Persona.
    """
    from app.services.config_loader import (
        load_tone_modifiers_config,
        update_persona_modifier_in_frontmatter,
    )

    # Update persona modifiers in their respective MD files.
    failed: list[str] = []
    for pid, mod in payload.modifiers.items():
        ok = update_persona_modifier_in_frontmatter(pid, mod.model_dump())
        if not ok:
            failed.append(pid)
    if failed:
        # C (2026-06-10): vorher wurde hier still 200 geliefert — der
        # Studio-Nutzer sah "gespeichert", obwohl Personas fehlschlugen.
        # Erfolgreiche Writes bleiben bestehen (kein Rollback nötig, jede
        # Persona-Datei ist unabhängig); der Fehler macht die Teilmenge
        # sichtbar, das Studio zeigt seinen Fehler-Status.
        raise HTTPException(
            500,
            "Tone-Modifier teilweise gespeichert — fehlgeschlagen für: "
            + ", ".join(sorted(failed)),
        )

    # Default-Modifier bleibt in der historischen YAML (nicht Persona-
    # spezifisch). Wir schreiben sie minimal — nur default_modifier.
    default_yaml = (
        "# Default-Modifier für unbekannte Personas — wird genutzt, wenn der\n"
        "# Classifier eine Persona liefert, für die keine 04-personas/*.md\n"
        "# existiert. Persona-spezifische Modifier leben im Frontmatter der\n"
        "# jeweiligen Persona-Datei (siehe ``04-personas/<id>.md``).\n"
        "\n"
        "default_modifier:\n"
        f"    tone: {payload.default_modifier.tone}\n"
        f"    length_bias: {payload.default_modifier.length_bias}\n"
        f"    formality: {payload.default_modifier.formality}\n"
        f"    card_text_mode: {payload.default_modifier.card_text_mode}\n"
        f"    override: {str(payload.default_modifier.override).lower()}\n"
    )
    write_config_file(_TONE_MODIFIERS_PATH, default_yaml)

    # Re-read so the response reflects what is now on disk.
    cfg = load_tone_modifiers_config()
    return ToneModifiersPayload(
        modifiers={k: ToneModifier(**v) for k, v in cfg["modifiers"].items()},
        default_modifier=ToneModifier(**cfg["default"]),
    )


@public_router.get("/guide-mode")
async def get_guide_mode_config_route():
    """Public Webseiten-Guide-Modus configuration consumed by the widget.

    The widget calls this once at boot to learn (a) the default toggle
    state and (b) the allow-list of hosts on which the toggle should
    even appear. The toggle is hidden + Mode forcibly off on any other
    domain.

    Mounted on ``public_router`` (no Studio auth) — the widget runs in
    every embedder's browser and doesn't have the Studio API key.
    """
    from app.services.config_loader import (
        load_guide_mode_config, load_header_nav_config,
    )
    cfg = load_guide_mode_config()
    # Optionale Kopfzeilen-Nav-Buttons (Studio-pflegbar) gleich mitliefern,
    # damit das Widget sie ohne zweiten Boot-Request rendern kann.
    cfg["header_nav"] = load_header_nav_config().get("buttons", [])
    return cfg


@router.put("/privacy", response_model=PrivacyConfig)
async def update_privacy_config(cfg: PrivacyConfig):
    """Update logging toggles. Writes 01-base/privacy-config.yaml atomically.

    `safety` is always forced true — the UI may show the value, but it
    cannot be disabled from here.
    """
    yaml_body = (
        "# Privacy-Konfiguration (Datenschutz)\n"
        "# Verwaltet ueber das Studio — Aenderungen wirken live\n"
        "# (mtime-Cache-Invalidation auf Write).\n"
        "\n"
        "logging:\n"
        f"  messages: {str(bool(cfg.messages)).lower()}\n"
        f"  memory: {str(bool(cfg.memory)).lower()}\n"
        f"  quality: {str(bool(cfg.quality)).lower()}\n"
        "  # safety is hardcoded ON in code — this value is informative only.\n"
        "  safety: true\n"
    )
    write_config_file("01-base/privacy-config.yaml", yaml_body)
    from app.services.config_loader import load_privacy_config
    return PrivacyConfig(**load_privacy_config())


# ── Canvas material types (typed CRUD for Studio GUI editor) ─────
#
# Reads / writes 05-canvas/material-types.yaml as JSON, so the Studio
# does not need a YAML parser. The endpoint preserves the file's leading
# comment block (lines 1–15 in the canonical file) so authors don't lose
# the schema-doc when round-tripping through the GUI.

class CanvasMaterialType(BaseModel):
    id: str
    label: str
    emoji: str = ""
    category: str  # 'didaktisch' | 'analytisch'
    structure: str = ""


class CanvasMaterialTypesPayload(BaseModel):
    material_types: list[CanvasMaterialType]


_CANVAS_TYPES_PATH = "05-canvas/material-types.yaml"
_CANVAS_TYPES_HEADER = (
    "# Canvas-Material-Typen\n"
    "# ============================================================================\n"
    "# Jede Definition wird im Canvas als möglicher Output-Typ angeboten.\n"
    "# - id:        interner Key (nur a-z, ziffern, _). Wird vom Code referenziert.\n"
    "# - label:     Anzeigename im UI\n"
    "# - emoji:     Vorangestelltes Symbol in Quick-Replies + Canvas-Badge\n"
    "# - category:  'didaktisch' (Lehrer/Schüler/Eltern) oder 'analytisch'\n"
    "#              (Verwaltung/Politik/Presse/Beratung). Steuert die\n"
    "#              Badge-Farbe im Canvas und die Quick-Reply-Reihenfolge pro\n"
    "#              Persona (siehe persona-priorities.yaml).\n"
    "# - structure: Markdown-Struktur-Vorgabe, die dem LLM im Create-Prompt als\n"
    "#              konkrete Gliederungs-Anweisung mitgegeben wird.\n"
    "#\n"
    "# Änderungen an dieser Datei wirken live — Backend-Cache invalidiert sich\n"
    "# über mtime. Kein Restart nötig.\n"
)


@router.get("/canvas/material-types", response_model=CanvasMaterialTypesPayload)
async def get_canvas_material_types():
    """Return parsed material-types as typed JSON for the Studio GUI editor."""
    from app.services.config_loader import load_canvas_material_types
    items = load_canvas_material_types() or []
    return CanvasMaterialTypesPayload(
        material_types=[CanvasMaterialType(**item) for item in items],
    )


@router.put("/canvas/material-types", response_model=CanvasMaterialTypesPayload)
async def update_canvas_material_types(payload: CanvasMaterialTypesPayload):
    """Persist material-types back to YAML.

    Uses ``yaml.safe_dump`` with a custom string representer so that the
    multi-line ``structure`` field round-trips as a literal block scalar
    (``|``) instead of inline-quoted text. This keeps diffs readable for
    humans editing the file directly in Git.
    """
    import yaml as _yaml

    # Validate ids are unique and category is one of the known values.
    seen: set[str] = set()
    valid_categories = {"didaktisch", "analytisch"}
    for mt in payload.material_types:
        if mt.id in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate id: {mt.id}")
        seen.add(mt.id)
        if mt.category not in valid_categories:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category '{mt.category}' for id '{mt.id}' "
                       f"(must be one of {sorted(valid_categories)})",
            )

    # Custom string representer: multi-line strings use literal block scalar.
    def _str_repr(dumper, data):
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    class _MaterialDumper(_yaml.SafeDumper):
        pass

    _MaterialDumper.add_representer(str, _str_repr)

    body = _yaml.dump(
        {"material_types": [mt.model_dump() for mt in payload.material_types]},
        Dumper=_MaterialDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    )
    write_config_file(_CANVAS_TYPES_PATH, _CANVAS_TYPES_HEADER + "\n" + body)

    # Re-read so the response reflects what's now on disk.
    from app.services.config_loader import load_canvas_material_types
    items = load_canvas_material_types() or []
    return CanvasMaterialTypesPayload(
        material_types=[CanvasMaterialType(**item) for item in items],
    )


@router.get("/elements")
async def get_elements():
    """Return all editable elements (patterns, personas, intents, states, signals, entities)
    with their source file paths for the Studio element browser."""
    from app.services.config_loader import (
        load_pattern_definitions, load_persona_definitions,
        load_intents, load_states, load_entities,
        load_signal_modulations, load_device_config,
    )

    # Patterns — Welle E v4 (2026-05-25): gate_* + signal_*_fit + page_bonus
    # sind aus dem aktiven Schema raus. Wir liefern weiterhin die alten
    # Listen-Felder (personas/intents/states/signals_boost) für Studio-UI-
    # Komponenten, die sie noch anzeigen — aber immer leer, weil die
    # Pattern-MDs sie nicht mehr setzen.
    patterns = []
    for p in load_pattern_definitions():
        patterns.append({
            "id": p.get("id"),
            "label": p.get("label", p.get("id")),
            "personas": [],
            "intents": [],
            "states": [],
            "signals_boost": [],
            "file": p.get("_source_file", ""),
        })

    # Personas — Welle E v2 (2026-05-25): alle strukturierten Felder
    # durchreichen, damit das Studio die Form-Editoren mit Daten füllen
    # kann. Frühere Variante hat nur id/label/file geliefert und so die
    # neuen Marker/Diskriminatoren/Ziele/Regeln im UI verschluckt.
    from app.services.config_loader import _persona_slug
    personas = []
    for p in load_persona_definitions():
        slug = _persona_slug(p["id"])
        entry = dict(p)  # alles durchreichen (positive_markers, anti_markers, ...)
        entry["file"] = f"04-personas/{slug}.md"
        # Internes Loader-Feld nicht ans Frontend leaken.
        entry.pop("_source_file", None)
        personas.append(entry)

    # Intents
    intents = load_intents()
    for i in intents:
        i["file"] = "04-intents/intents.yaml"

    # States
    states = load_states()
    for s in states:
        s["file"] = "04-states/states.yaml"

    # Signals
    mods, reduce = load_signal_modulations()
    signals = []
    for sig_id, mod in mods.items():
        signals.append({"id": sig_id, "modulations": mod, "file": "04-signals/signal-modulations.yaml"})

    # Entities
    entities = load_entities()
    for e in entities:
        e["file"] = "04-entities/entities.yaml"

    # Device config
    device = load_device_config()

    return {
        "patterns": patterns,
        "personas": personas,
        "intents": intents,
        "states": states,
        "signals": signals,
        "entities": entities,
        "device": device,
        "base_files": [
            {"label": "Base-Persona (Identität)", "file": "01-base/base-persona.md"},
            {"label": "Guardrails (R-01 bis R-10)", "file": "01-base/guardrails.md"},
            {"label": "Device & Formality", "file": "01-base/device-config.yaml"},
            {"label": "Domain-Rules", "file": "02-domain/domain-rules.md"},
        ],
    }


# ──────────────────────────────────────────────────────────────────────
# Welle E (2026-05-25) — Strukturierte PUT-Endpoints für die 4 Dimensionen
#
# Studio braucht für die neuen Form-Editoren atomic Saves, die alle
# Felder durchreichen ohne Datenverlust. Der ``/file`` PUT-Endpoint
# ersetzt die Datei komplett — der ist gut für freie Markdown/YAML-
# Bearbeitung, aber nicht für GUI-Formulare (Studio müsste YAML im
# Frontend serialisieren, was fehleranfällig ist).
#
# Stattdessen: pro Dimension ein PUT, das eine validierte Liste von
# Pydantic-Models nimmt und via ruamel.yaml round-trip schreibt —
# Header-Kommentare bleiben erhalten, Schema-Doku ist sicher.
# ──────────────────────────────────────────────────────────────────────


class IntentNegativeTrigger(BaseModel):
    phrase: str
    redirect_to: str | None = None
    rationale: str | None = None
    when: str | None = None


class IntentDiscriminator(BaseModel):
    vs: str
    rule: str
    example_a: str | None = None
    example_b: str | None = None


class IntentEntry(BaseModel):
    id: str
    label: str
    description: str | None = None
    examples: list[str] = []
    trigger_verbs: list[str] = []
    negative_triggers: list[IntentNegativeTrigger] = []
    discriminators: list[IntentDiscriminator] = []


class StateEntry(BaseModel):
    id: str
    label: str
    description: str | None = None
    role: str | None = None
    bot_directive: str | None = None
    next_likely: list[str] = []
    selection_criteria: list[str] = []


class EntityPositiveExample(BaseModel):
    text: str
    value: str | None = None


class EntityNegativeExample(BaseModel):
    text: str
    rationale: str | None = None


class EntityDiscriminator(BaseModel):
    vs: str
    rule: str
    example_a: str | None = None
    example_b: str | None = None


class EntityEntry(BaseModel):
    id: str
    label: str | None = None
    type: str = "string"
    description: str | None = None
    examples: list[str] = []
    positive_examples: list[EntityPositiveExample] = []
    negative_examples: list[EntityNegativeExample] = []
    discriminators: list[EntityDiscriminator] = []


def _strip_empty(obj: Any) -> Any:
    """Recursively drop ``None``, ``""``, ``[]``, ``{}`` from a structure.

    Keeps the YAML clean — empty lists and null fields pollute the file
    and confuse the Studio readers (e.g. `negative_triggers: []` would
    render an empty section).
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            cleaned = _strip_empty(v)
            if cleaned not in (None, "", [], {}):
                out[k] = cleaned
        return out
    if isinstance(obj, list):
        return [_strip_empty(x) for x in obj if _strip_empty(x) not in (None, "", [], {})]
    return obj


def _dump_intents(entries: list[IntentEntry]) -> list[dict]:
    """Convert validated Pydantic entries → clean YAML-ready dicts."""
    cleaned: list[dict] = []
    for e in entries:
        d = e.model_dump()
        d = _strip_empty(d)
        cleaned.append(d)
    return cleaned


@router.get("/intents")
async def get_intents_route():
    """Return all intents with full nested fields (for the Studio form UI)."""
    from app.services.config_loader import load_intents
    return {"intents": load_intents()}


@router.put("/intents")
async def put_intents_route(payload: dict):
    """Replace intents.yaml with a validated list of intents.

    Payload shape: ``{"intents": [<IntentEntry>, ...]}``.

    The header comment block of intents.yaml is preserved via ruamel.yaml
    round-trip. We rewrite only the ``intents:`` key; if the file is new
    or empty, we re-create the standard SCHEMA header.
    """
    from app.services.config_loader import (
        load_yaml_roundtrip, save_yaml_roundtrip,
    )
    raw = payload.get("intents")
    if not isinstance(raw, list):
        raise HTTPException(400, "Payload must be {'intents': [...]}.")
    # Validate every entry
    entries = [IntentEntry.model_validate(item) for item in raw]
    # IDs must be unique
    if len({e.id for e in entries}) != len(entries):
        raise HTTPException(400, "Intent IDs must be unique.")

    data = load_yaml_roundtrip("04-intents/intents.yaml")
    if data is None:
        # New file — re-instantiate a minimal map; header comments are gone.
        data = {}
    data["intents"] = _dump_intents(entries)
    save_yaml_roundtrip("04-intents/intents.yaml", data)
    return {"status": "saved", "count": len(entries)}


@router.get("/states")
async def get_states_route():
    """Return all states with full nested fields."""
    from app.services.config_loader import load_states
    return {"states": load_states()}


@router.put("/states")
async def put_states_route(payload: dict):
    """Replace states.yaml with a validated list of states."""
    from app.services.config_loader import (
        load_yaml_roundtrip, save_yaml_roundtrip, _multiline_str,
    )
    raw = payload.get("states")
    if not isinstance(raw, list):
        raise HTTPException(400, "Payload must be {'states': [...]}.")
    entries = [StateEntry.model_validate(item) for item in raw]
    if len({e.id for e in entries}) != len(entries):
        raise HTTPException(400, "State IDs must be unique.")

    cleaned: list[dict] = []
    for e in entries:
        d = _strip_empty(e.model_dump())
        # bot_directive is multi-line — render as YAML literal block.
        if "bot_directive" in d:
            d["bot_directive"] = _multiline_str(d["bot_directive"])
        cleaned.append(d)

    data = load_yaml_roundtrip("04-states/states.yaml") or {}
    data["states"] = cleaned
    save_yaml_roundtrip("04-states/states.yaml", data)
    return {"status": "saved", "count": len(entries)}


# ── Personas (Welle E v2, 2026-05-25) ──────────────────────────────
#
# Personas leben als 04-personas/<slug>.md mit YAML-Frontmatter — Body
# ist nur noch Persönlichkeits-Prosa. Das PUT-Endpoint schreibt das
# Frontmatter via ruamel-Roundtrip + den Body als Plain-Markdown am Ende.

class PersonaAntiMarker(BaseModel):
    phrase: str
    redirect_to: str | None = None
    rationale: str | None = None


class PersonaDiscriminator(BaseModel):
    vs: str
    rule: str
    example_a: str | None = None
    example_b: str | None = None


class PersonaEntry(BaseModel):
    id: str
    label: str
    description: str | None = None
    tone: str | None = None
    length_bias: float | None = None
    formality: str | None = None
    card_text_mode: str | None = None
    override: bool | None = None
    positive_markers: list[str] = []
    anti_markers: list[PersonaAntiMarker] = []
    discriminators: list[PersonaDiscriminator] = []
    goals: list[str] = []
    rules: list[str] = []
    typical_intents: list[str] = []
    personality_text: str | None = None


@router.get("/personas")
async def get_personas_route():
    """Return all personas with full structured fields."""
    from app.services.config_loader import load_persona_definitions
    return {"personas": load_persona_definitions()}


@router.put("/personas")
async def put_personas_route(payload: dict):
    """Persist all personas. Each one is written as a separate
    ``04-personas/<slug>.md`` file with YAML-Frontmatter + Markdown body
    (personality_text).
    """
    from app.services.config_loader import (
        _persona_slug, _validate_config_path, invalidate_yaml_cache, CHATBOT_DIR,
    )
    from ruamel.yaml import YAML
    raw = payload.get("personas")
    if not isinstance(raw, list):
        raise HTTPException(400, "Payload must be {'personas': [...]}.")
    entries = [PersonaEntry.model_validate(item) for item in raw]
    if len({e.id for e in entries}) != len(entries):
        raise HTTPException(400, "Persona IDs must be unique.")

    yml = YAML(typ="rt")
    yml.preserve_quotes = True
    yml.indent(mapping=2, sequence=4, offset=2)
    yml.width = 200

    for e in entries:
        slug = _persona_slug(e.id)
        rel_path = f"04-personas/{slug}.md"

        # Build frontmatter dict — only set keys that are actually populated
        # so the YAML stays clean and human-readable.
        fm: dict[str, Any] = {
            "element": "persona",
            "id": e.id,
            "label": e.label,
        }
        if e.description:
            fm["description"] = e.description
        # Tonalitäts-Modifier (nur wenn nicht None)
        for k in ("tone", "length_bias", "formality", "card_text_mode", "override"):
            v = getattr(e, k)
            if v is not None:
                fm[k] = v
        # Strukturierte Klassifikations-Felder
        if e.positive_markers:
            fm["positive_markers"] = list(e.positive_markers)
        if e.anti_markers:
            fm["anti_markers"] = [_strip_empty(am.model_dump()) for am in e.anti_markers]
        if e.discriminators:
            fm["discriminators"] = [_strip_empty(d.model_dump()) for d in e.discriminators]
        if e.goals:
            fm["goals"] = list(e.goals)
        if e.rules:
            fm["rules"] = list(e.rules)
        if e.typical_intents:
            fm["typical_intents"] = list(e.typical_intents)

        # Render frontmatter as YAML
        import io
        buf = io.StringIO()
        yml.dump(fm, buf)
        fm_yaml = buf.getvalue().rstrip()

        body = (e.personality_text or "").strip()
        # Standard-H1 voranstellen, wenn der Body kein eigenes Heading hat
        if body and not re.match(r"^\s*#\s", body):
            body = f"# {e.id} — {e.label}\n\n{body}"

        full = f"---\n{fm_yaml}\n---\n\n{body}\n" if body else f"---\n{fm_yaml}\n---\n"

        # Validate path inside CHATBOT_DIR
        path = _validate_config_path(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(full, encoding="utf-8")
        invalidate_yaml_cache(rel_path)

    return {"status": "saved", "count": len(entries)}


# ── Patterns (Welle E v3, 2026-05-25) ──────────────────────────────
#
# Patterns leben als 03-patterns/<id>.md mit YAML-Frontmatter + Body.
# Frontmatter enthält Gates, Tonality-Defaults UND die strukturierten
# Felder core_rule/forbidden_phrases/anti_patterns. Body trägt nur noch
# die Pattern-spezifischen Sektionen (Pflicht-Antwort-Schema, Tabellen,
# Beispiele) — die generischen Regel-Sektionen sind ins Frontmatter
# gehoben (Welle-E-v3-Migration).

class PatternEntry(BaseModel):
    """Pattern-Schema für PUT /api/config/patterns.

    Welle E v4 (2026-05-25): gate_personas/gate_intents/gate_states sind
    entfernt — Pattern wird vom LLM-Hint gewählt, deterministische Gates
    sind aus der Engine raus. Falls das Studio noch alte Werte in den
    Payload schickt, werden sie still verworfen (extra='ignore' Pydantic-
    Default).
    """
    id: str
    label: str
    short_purpose: str | None = None
    priority: int | None = None
    default_tone: str | None = None
    default_length: str | None = None
    response_type: str | None = None
    sources: list[str] = []
    rag_areas: list[str] = []
    tools: list[str] = []
    output_mode: str | None = None
    precondition_slots: list[str] = []
    # Welle B.5-Flag (M09): Cards-Box auf im Text verlinkte Materialien
    # filtern. Muss durch den GET→PUT-Roundtrip erhalten bleiben — der
    # Serializer unten baut das Frontmatter aus diesem Schema neu auf.
    card_text_link_required: bool | None = None
    # QR-Policy (2026-06-10): exact | speculative | none + Anzahl-Override.
    quick_replies_mode: str | None = None
    quick_replies_max: int | None = None
    core_rule: str | None = None
    forbidden_phrases: list[str] = []
    anti_patterns: list[str] = []
    # Welle E v4+7 (2026-05-26): strukturierte Pattern-Auswahl-Regeln
    # — when_to_use/when_not_to_use/trigger_phrases als String-Listen,
    # discriminators als Liste {vs, rule, example}.
    when_to_use: list[str] = []
    when_not_to_use: list[str] = []
    trigger_phrases: list[str] = []
    discriminators: list[dict[str, str]] = []
    body_md: str | None = None


@router.get("/patterns")
async def get_patterns_route():
    """Return all patterns with full structured fields."""
    from app.services.config_loader import load_pattern_definitions
    patterns = load_pattern_definitions()
    # Strip internal _source_file from the response (UI doesn't need it).
    return {"patterns": [
        {k: v for k, v in p.items() if k != "_source_file"}
        for p in patterns
    ]}


@router.put("/patterns")
async def put_patterns_route(payload: dict):
    """Persist all patterns. Each one is written as a separate
    ``03-patterns/<slug>.md`` with YAML-Frontmatter + Markdown body.

    File slug is derived from the existing source file (preserves the
    ``m13-einreichen-melden.md`` naming) or, for new patterns, generated
    from id + label.
    """
    from app.services.config_loader import (
        load_pattern_definitions, _validate_config_path, invalidate_yaml_cache,
        CHATBOT_DIR,
    )
    from ruamel.yaml import YAML
    from ruamel.yaml.scalarstring import LiteralScalarString
    raw = payload.get("patterns")
    if not isinstance(raw, list):
        raise HTTPException(400, "Payload must be {'patterns': [...]}.")
    entries = [PatternEntry.model_validate(item) for item in raw]
    if len({e.id for e in entries}) != len(entries):
        raise HTTPException(400, "Pattern IDs must be unique.")

    # Build {id → existing source path} so we keep the original filename.
    existing_by_id = {
        p["id"]: p.get("_source_file", "")
        for p in load_pattern_definitions()
    }

    yml = YAML(typ="rt")
    yml.preserve_quotes = True
    yml.indent(mapping=2, sequence=4, offset=2)
    yml.width = 200

    for e in entries:
        rel_path = existing_by_id.get(e.id, "")
        if not rel_path:
            # New pattern → derive a filename slug.
            slug_label = re.sub(r"[^a-z0-9-]+", "-",
                                 (e.label or e.id).lower()).strip("-")
            rel_path = f"03-patterns/{e.id.lower()}-{slug_label}.md"

        # Frontmatter dict — only set keys that are actually populated.
        fm: dict[str, Any] = {"id": e.id, "label": e.label}
        if e.short_purpose:
            fm["short_purpose"] = e.short_purpose
        if e.priority is not None:
            fm["priority"] = e.priority
        # Welle E v4: gate_* nicht mehr serialisieren — Hint-Primary
        # Pattern-Selektion kennt keine Gates mehr.
        for k in ("default_tone", "default_length", "response_type",
                  "output_mode"):
            v = getattr(e, k)
            if v:
                fm[k] = v
        for k in ("sources", "rag_areas", "tools", "precondition_slots"):
            v = getattr(e, k)
            if v:
                fm[k] = list(v)
        if e.card_text_link_required:
            fm["card_text_link_required"] = True
        # QR-Policy: nur serialisieren wenn vom Default abweichend, damit
        # unkonfigurierte Patterns schlank bleiben (Default = exact/global).
        if e.quick_replies_mode and e.quick_replies_mode != "exact":
            if e.quick_replies_mode not in ("speculative", "none"):
                raise HTTPException(
                    400, f"quick_replies_mode ungültig: {e.quick_replies_mode!r}",
                )
            fm["quick_replies_mode"] = e.quick_replies_mode
        if e.quick_replies_max is not None:
            fm["quick_replies_max"] = max(1, min(6, int(e.quick_replies_max)))
        if e.core_rule:
            cr = e.core_rule.strip()
            fm["core_rule"] = LiteralScalarString(cr + "\n") if "\n" in cr else cr
        if e.forbidden_phrases:
            fm["forbidden_phrases"] = list(e.forbidden_phrases)
        if e.anti_patterns:
            fm["anti_patterns"] = list(e.anti_patterns)
        # Welle E v4+7 (2026-05-26): strukturierte Pattern-Auswahl-Regeln
        # serialisieren (when_to_use, when_not_to_use, trigger_phrases,
        # discriminators). Studio kann die jetzt direkt editieren.
        if e.when_to_use:
            fm["when_to_use"] = list(e.when_to_use)
        if e.when_not_to_use:
            fm["when_not_to_use"] = list(e.when_not_to_use)
        if e.trigger_phrases:
            fm["trigger_phrases"] = list(e.trigger_phrases)
        if e.discriminators:
            fm["discriminators"] = [
                {"vs": str(d.get("vs", "")).strip(),
                 "rule": str(d.get("rule", "")).strip(),
                 "example": str(d.get("example", "")).strip()}
                for d in e.discriminators
                if d.get("vs") and d.get("rule")
            ]

        import io
        buf = io.StringIO()
        yml.dump(fm, buf)
        fm_yaml = buf.getvalue().rstrip()

        body = (e.body_md or "").strip()
        # H1 if body doesn't start with one
        if body and not re.match(r"^\s*#\s", body):
            body = f"# {e.id} — {e.label}\n\n{body}"

        full = f"---\n{fm_yaml}\n---\n\n{body}\n" if body else f"---\n{fm_yaml}\n---\n"

        path = _validate_config_path(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(full, encoding="utf-8")
        invalidate_yaml_cache(rel_path)

    return {"status": "saved", "count": len(entries)}


@router.get("/entities")
async def get_entities_route():
    """Return all entities + accumulation_rules block."""
    from app.services.config_loader import load_entities, _load_yaml
    raw = _load_yaml("04-entities/entities.yaml")
    return {
        "entities": load_entities(),
        "accumulation_rules": raw.get("accumulation_rules", {}),
    }


@router.put("/entities")
async def put_entities_route(payload: dict):
    """Replace entities.yaml with a validated entity list.

    accumulation_rules block is preserved as-is from the existing file
    (Studio does not edit those).
    """
    from app.services.config_loader import (
        load_yaml_roundtrip, save_yaml_roundtrip, _multiline_str,
    )
    raw = payload.get("entities")
    if not isinstance(raw, list):
        raise HTTPException(400, "Payload must be {'entities': [...]}.")
    entries = [EntityEntry.model_validate(item) for item in raw]
    if len({e.id for e in entries}) != len(entries):
        raise HTTPException(400, "Entity IDs must be unique.")

    cleaned: list[dict] = []
    for e in entries:
        d = _strip_empty(e.model_dump())
        # description can be multi-line → use block scalar for readability.
        if "description" in d:
            d["description"] = _multiline_str(d["description"])
        cleaned.append(d)

    data = load_yaml_roundtrip("04-entities/entities.yaml") or {}
    data["entities"] = cleaned
    # accumulation_rules block stays untouched (preserved by round-trip).
    save_yaml_roundtrip("04-entities/entities.yaml", data)
    return {"status": "saved", "count": len(entries)}


# ── MCP Server Registry ──────────────────────────────────────────

# Cache MCP-Tool-Descriptions for ~5 min so the studio's GET /mcp-servers
# doesn't pay the discover round-trip on every render. The descriptions
# change rarely (only on MCP-server deploys); a short TTL is fine.
_TOOL_DESC_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
_TOOL_DESC_TTL_S = 300.0


async def _fetch_tool_descriptions(url: str) -> dict[str, str]:
    """Get {tool_name: description} for an MCP server, cached.

    Returns an empty dict on any failure so the caller can render the
    server tile without descriptions instead of erroring out.
    """
    import time
    now = time.time()
    cached = _TOOL_DESC_CACHE.get(url)
    if cached and (now - cached[0]) < _TOOL_DESC_TTL_S:
        return cached[1]
    from app.services.mcp_client import discover_server_tools
    try:
        tools = await discover_server_tools(url)
        descs = {
            t["name"]: (t.get("description") or "").strip()
            for t in tools
            if isinstance(t, dict) and t.get("name")
        }
    except Exception:
        descs = {}
    _TOOL_DESC_CACHE[url] = (now, descs)
    return descs


@router.get("/mcp-servers")
async def get_mcp_servers():
    """List all registered MCP servers, with tool descriptions inline.

    The studio shows the tool list as small tags. Without descriptions,
    near-identical tool names like ``get_node_details`` (single) and
    ``get_nodes_details`` (bulk) are visually indistinguishable. We
    therefore enrich the response with a ``tool_descriptions`` map so
    the frontend can render hover-tooltips.
    """
    from app.services.config_loader import load_mcp_servers
    servers = load_mcp_servers()
    # Best-effort: enrich enabled servers with tool descriptions.
    # Failures are silent — the frontend will just show tags without tooltips.
    for srv in servers:
        if srv.get("enabled") and srv.get("url") and srv.get("tools"):
            srv["tool_descriptions"] = await _fetch_tool_descriptions(srv["url"])
    return servers


class McpServerUpdate(BaseModel):
    servers: list[dict]


@router.put("/mcp-servers")
async def update_mcp_servers(data: McpServerUpdate):
    """Update the full MCP server registry.

    Schutzregel: Wenn das Studio die URL des Primary-Servers
    (id=wlo-mcp) zu ändern versucht, ignorieren wir das stillschweigend.
    Die Primary-URL wird ausschließlich per ``MCP_SERVER_URL`` Env-Var
    gesteuert; ein YAML-Override würde nur Verwirrung schaffen.
    Der Save-Layer (``save_mcp_servers``) filtert das URL-Feld für den
    Primary automatisch raus, sodass auch eingeschmuggelte Werte
    nicht persistiert werden.
    """
    from app.services.config_loader import save_mcp_servers
    save_mcp_servers(data.servers)
    return {"status": "saved", "count": len(data.servers)}


@router.post("/mcp-servers/discover")
async def discover_mcp_tools(url: str = ""):
    """Connect to an MCP server and discover its available tools.

    This performs a temporary MCP handshake to list tools without
    permanently registering the server.
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    # SSRF protection: block private/internal network ranges
    from urllib.parse import urlparse
    import ipaddress
    import socket
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid URL")
    # Block common internal hostnames
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or hostname.endswith(".local"):
        raise HTTPException(status_code=400, detail="Internal URLs not allowed")
    try:
        resolved = socket.getaddrinfo(hostname, None)
        for _, _, _, _, addr in resolved:
            ip = ipaddress.ip_address(addr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise HTTPException(status_code=400, detail="Internal network URLs not allowed")
    except socket.gaierror:
        raise HTTPException(status_code=400, detail=f"Cannot resolve hostname: {hostname}")

    from app.services.mcp_client import discover_server_tools
    try:
        tools = await discover_server_tools(url)
        return {"url": url, "tools": tools}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Verbindung fehlgeschlagen: {e}")


# ── Full backup / restore + server-side snapshots ──────────────────
#
# The ZIP archive packs two trees:
#   config/<files...>   → the whole chatbots/wlo/v1 content tree
#   db/badboerdi.db     → (optional) SQLite DB snapshot via sqlite3.backup()
#
# Restore is backward-compatible: archives WITHOUT a "config/" prefix are
# treated as config-only (old format from before 2026-04-19).


def _slugify(text: str) -> str:
    """Lower-case slug safe for a filename (no path separators)."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip())
    s = s.strip("-.")
    return s.lower()[:40] or "snapshot"


def _sqlite_backup_to_file(src_db: Path, dest_file: Path) -> None:
    """Online-backup of a SQLite DB using the backup API.

    Produces a consistent snapshot even if the app is actively writing.
    Works on Windows even when the source file is locked.
    """
    src = sqlite3.connect(str(src_db))
    dst = sqlite3.connect(str(dest_file))
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()


def _sqlite_restore_from_file(src_file: Path, dst_db: Path) -> None:
    """Overwrite the live SQLite DB with the contents of src_file.

    Uses the backup API in reverse so we don't have to replace a possibly
    locked file on Windows. This ATOMICALLY replaces all tables.
    """
    src = sqlite3.connect(str(src_file))
    dst = sqlite3.connect(str(dst_db))
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()


def _build_backup_zip(include_db: bool) -> bytes:
    """Serialize the config tree (+ optional DB) into a ZIP byte blob."""
    if not CHATBOT_DIR.exists():
        raise HTTPException(status_code=404, detail="No chatbot config found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Config under "config/" prefix
        for path in sorted(CHATBOT_DIR.rglob("*")):
            if path.is_file():
                arc = "config/" + path.relative_to(CHATBOT_DIR).as_posix()
                zf.write(path, arcname=arc)
        # Database
        if include_db:
            try:
                from app.services.database import DB_PATH
                db_path = Path(DB_PATH)
                if db_path.exists():
                    with tempfile.NamedTemporaryFile(
                        suffix=".db", delete=False,
                    ) as tmp:
                        tmp_path = Path(tmp.name)
                    try:
                        _sqlite_backup_to_file(db_path, tmp_path)
                        zf.write(tmp_path, arcname="db/badboerdi.db")
                    finally:
                        try:
                            tmp_path.unlink()
                        except OSError:
                            pass
            except Exception as e:
                logger.warning("DB backup skipped: %s", e)

    buf.seek(0)
    return buf.getvalue()


def _restore_from_zip_bytes(raw: bytes, wipe: bool, include_db: bool) -> dict:
    """Apply a backup ZIP to the running instance. Returns counts."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP archive")

    # Path safety: refuse archives with absolute paths or '..' segments
    for name in zf.namelist():
        if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
            raise HTTPException(status_code=400, detail=f"Unsafe path in ZIP: {name}")

    # Split members: new-format (config/ + db/) or legacy (everything → config)
    config_members: list[zipfile.ZipInfo] = []
    db_members: list[zipfile.ZipInfo] = []
    has_new_prefix = any(
        n.startswith("config/") or n.startswith("db/")
        for n in zf.namelist()
    )
    for m in zf.infolist():
        if m.is_dir():
            continue
        if has_new_prefix:
            if m.filename.startswith("db/"):
                db_members.append(m)
            elif m.filename.startswith("config/"):
                config_members.append(m)
            # else: ignore unknown top-level
        else:
            # Legacy: no prefix → treat everything as config
            config_members.append(m)

    # ── Restore config ──
    if wipe:
        for path in sorted(CHATBOT_DIR.rglob("*"), reverse=True):
            try:
                if path.is_file():
                    path.unlink()
                elif path.is_dir() and path != CHATBOT_DIR:
                    path.rmdir()
            except OSError:
                pass

    CHATBOT_DIR.mkdir(parents=True, exist_ok=True)
    extracted_config = 0
    for m in config_members:
        name = m.filename
        if name.startswith("config/"):
            name = name[len("config/"):]
        if not name:
            continue
        target = CHATBOT_DIR / name
        try:
            target.resolve().relative_to(CHATBOT_DIR.resolve())
        except ValueError:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(m) as src, open(target, "wb") as dst:
            dst.write(src.read())
        extracted_config += 1

    # ── Restore DB ──
    db_restored = False
    if include_db and db_members:
        try:
            from app.services.database import DB_PATH
            db_path = Path(DB_PATH)
            db_member = db_members[0]
            with tempfile.NamedTemporaryFile(
                suffix=".db", delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)
            try:
                with zf.open(db_member) as src:
                    tmp_path.write_bytes(src.read())
                # Use backup-API in reverse so no file-replace is needed.
                _sqlite_restore_from_file(tmp_path, db_path)
                # Drop YAML mtime cache — config files changed on disk.
                try:
                    from app.services.config_loader import invalidate_yaml_cache
                    invalidate_yaml_cache()
                except Exception:
                    pass
                db_restored = True
            finally:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        except Exception as e:
            logger.error("DB restore failed: %s", e)

    return {
        "status": "restored",
        "wiped": wipe,
        "config_files": extracted_config,
        "db_restored": db_restored,
        "db_in_archive": bool(db_members),
    }


@router.get("/backup")
async def backup_config(include_db: bool = True):
    """Download the full configuration (+ optional DB) as a ZIP archive.

    Query params:
      include_db: also bundle the SQLite DB (sessions, messages, memory,
                  quality/safety logs, RAG chunks). Default: true.
    """
    data = _build_backup_zip(include_db=include_db)
    tag = "full" if include_db else "config"
    fname = f"boerdi-{tag}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.zip"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/restore")
async def restore_config(
    file: UploadFile = File(...),
    wipe: bool = False,
    include_db: bool = True,
):
    """Restore a configuration (+ optional DB) from a ZIP backup.

    Parameters
    ----------
    file : UploadFile
        The .zip produced by ``GET /api/config/backup``.
    wipe : bool
        Delete every file under chatbots/wlo/v1 BEFORE extracting. Use this
        when restoring a foreign snapshot to avoid leftover orphans.
    include_db : bool
        Also restore the SQLite DB if present in the ZIP. Default: true.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="ZIP file required")
    raw = await file.read()
    return _restore_from_zip_bytes(raw, wipe=wipe, include_db=include_db)


# ── Server-side snapshots ────────────────────────────────────────
#
# Snapshots are full backups stored on the server under backend/snapshots/.
# They let users create/restore quickly without download+upload roundtrips.

_SNAP_NAME_RE = re.compile(r"^snap-(\d{8}-\d{6})(?:-(.+))?\.zip$")


def _resolve_snapshot_path(snap_id: str) -> Path:
    """Return the ZIP path for a snapshot id, or 404."""
    if "/" in snap_id or "\\" in snap_id or ".." in snap_id:
        raise HTTPException(status_code=400, detail="Invalid snapshot id")
    fname = snap_id if snap_id.endswith(".zip") else f"{snap_id}.zip"
    path = SNAPSHOTS_DIR / fname
    try:
        path.resolve().relative_to(SNAPSHOTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid snapshot id")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return path


def _snapshot_meta(path: Path) -> dict:
    m = _SNAP_NAME_RE.match(path.name)
    ts = m.group(1) if m else ""
    label = m.group(2) if (m and m.group(2)) else ""
    # Peek into the ZIP to see if it contains a DB
    has_db = False
    try:
        with zipfile.ZipFile(path) as zf:
            has_db = any(n.startswith("db/") for n in zf.namelist())
    except Exception:
        pass
    return {
        "id": path.stem,
        "file": path.name,
        "size": path.stat().st_size,
        "label": label,
        "created_at": ts,
        "mtime": path.stat().st_mtime,
        "include_db": has_db,
    }


@router.post("/snapshots")
async def create_snapshot(label: str = "", include_db: bool = True):
    """Create a server-side snapshot (ZIP stays on the backend).

    Query params:
      label:       optional human-readable tag (slugified into the filename)
      include_db:  also snapshot the SQLite DB (default true)
    """
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(label) if label else "snapshot"
    fname = f"snap-{ts}-{slug}.zip"
    target = SNAPSHOTS_DIR / fname
    # Protect against same-second collisions on fast repeated clicks.
    i = 1
    while target.exists():
        target = SNAPSHOTS_DIR / f"snap-{ts}-{slug}-{i}.zip"
        i += 1

    data = _build_backup_zip(include_db=include_db)
    target.write_bytes(data)
    return _snapshot_meta(target)


@router.get("/snapshots")
async def list_snapshots():
    """List all server-side snapshots, newest first."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    items = [
        _snapshot_meta(p)
        for p in SNAPSHOTS_DIR.glob("snap-*.zip")
        if p.is_file()
    ]
    items.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    return items


@router.delete("/snapshots/{snap_id}")
async def delete_snapshot(snap_id: str):
    """Delete a server-side snapshot."""
    path = _resolve_snapshot_path(snap_id)
    path.unlink()
    return {"status": "deleted", "id": snap_id}


@router.post("/snapshots/{snap_id}/restore")
async def restore_snapshot(
    snap_id: str,
    wipe: bool = False,
    include_db: bool = True,
):
    """Restore a server-side snapshot in-place (no upload needed)."""
    path = _resolve_snapshot_path(snap_id)
    raw = path.read_bytes()
    out = _restore_from_zip_bytes(raw, wipe=wipe, include_db=include_db)
    out["snapshot_id"] = snap_id
    return out


@router.get("/snapshots/{snap_id}/download")
async def download_snapshot(snap_id: str):
    """Download a server-side snapshot as ZIP."""
    path = _resolve_snapshot_path(snap_id)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


# ── Factory snapshot ─────────────────────────────────────────────
#
# The factory snapshot is the "as-shipped" default state:
# a single ZIP at backend/knowledge/factory-snapshot.zip that contains the
# full config tree + a populated SQLite DB (with embeddings). On a brand-new
# installation (empty DB), `database._restore_factory_snapshot_if_empty()`
# unpacks it before the server accepts the first request.
#
# The factory snapshot is SEPARATE from user-side snapshots under
# backend/snapshots/:
#   - User snapshots come and go, can be bulk-deleted.
#   - The factory is versioned with the repo / the deployment, stays put,
#     and is what "Werkseinstellungen zurücksetzen" falls back to.

FACTORY_PATH = _BACKEND_DIR / "knowledge" / "factory-snapshot.zip"


def _factory_meta() -> dict:
    """Inspect the factory snapshot on disk and return a compact summary."""
    if not FACTORY_PATH.exists() or not FACTORY_PATH.is_file():
        return {"exists": False}
    size = FACTORY_PATH.stat().st_size
    mtime = FACTORY_PATH.stat().st_mtime
    has_db = False
    has_config = False
    config_files = 0
    try:
        with zipfile.ZipFile(FACTORY_PATH) as zf:
            names = zf.namelist()
            has_db = any(n.startswith("db/") for n in names)
            has_config = any(n.startswith("config/") for n in names)
            config_files = sum(1 for n in names if n.startswith("config/") and not n.endswith("/"))
    except Exception:
        pass
    return {
        "exists": True,
        "size": size,
        "mtime": mtime,
        "has_db": has_db,
        "has_config": has_config,
        "config_files": config_files,
        "path": str(FACTORY_PATH),
    }


@router.get("/factory")
async def get_factory_info():
    """Metadata of the factory snapshot (or exists=False)."""
    return _factory_meta()


@router.get("/factory/download")
async def download_factory():
    """Download the current factory snapshot as ZIP."""
    if not FACTORY_PATH.exists():
        raise HTTPException(status_code=404, detail="No factory snapshot present.")
    return FileResponse(
        FACTORY_PATH,
        media_type="application/zip",
        filename="factory-snapshot.zip",
        headers={"Content-Disposition": 'attachment; filename="factory-snapshot.zip"'},
    )


@router.post("/factory/restore")
async def restore_factory(wipe: bool = True, include_db: bool = True):
    """Restore the factory snapshot in-place.

    Defaults are aggressive on purpose: ``wipe=true`` cleans up orphan config
    files, ``include_db=true`` replaces the DB so embeddings and Studio
    settings are restored too. Callers that want to keep the DB can pass
    ``?include_db=false``.

    Returns the same shape as ``/restore`` so the Studio can show the
    per-table counts.
    """
    if not FACTORY_PATH.exists():
        raise HTTPException(status_code=404, detail="No factory snapshot present.")
    raw = FACTORY_PATH.read_bytes()
    out = _restore_from_zip_bytes(raw, wipe=wipe, include_db=include_db)
    out["source"] = "factory"
    return out


@router.post("/factory/save")
async def save_factory(from_snapshot: str | None = None):
    """Promote a user-snapshot to the factory snapshot (or take a live one).

    - ``from_snapshot=<id>`` copies an existing snapshot from
      ``snapshots/`` to ``knowledge/factory-snapshot.zip``.
    - omitted → builds a fresh snapshot from the current running state
      (config + DB including embeddings) and writes it to the factory
      path. Useful in Ops to "seal" the current state as the new default.

    Both modes overwrite any existing factory snapshot.
    """
    FACTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if from_snapshot:
        src = _resolve_snapshot_path(from_snapshot)
        FACTORY_PATH.write_bytes(src.read_bytes())
        logger.info("factory-snapshot replaced from user snapshot %s", from_snapshot)
    else:
        data = _build_backup_zip(include_db=True)
        FACTORY_PATH.write_bytes(data)
        logger.info("factory-snapshot rebuilt from live state (%d bytes)", len(data))
    return _factory_meta()


@router.post("/factory/upload")
async def upload_factory(file: UploadFile = File(...)):
    """Upload a new factory snapshot ZIP directly (ops pathway)."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="ZIP file required")
    raw = await file.read()
    # Cheap validity check: is this a readable ZIP with a config/ tree?
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
            if not any(n.startswith("config/") for n in names):
                raise HTTPException(
                    status_code=400,
                    detail="ZIP does not contain a 'config/' tree — not a factory snapshot.",
                )
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP archive")
    FACTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    FACTORY_PATH.write_bytes(raw)
    logger.info("factory-snapshot uploaded (%d bytes, %s)", len(raw), file.filename)
    return _factory_meta()
