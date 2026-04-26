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


@router.get("/privacy", response_model=PrivacyConfig)
async def get_privacy_config():
    """Return the current chat/memory/quality logging toggles."""
    from app.services.config_loader import load_privacy_config
    return PrivacyConfig(**load_privacy_config())


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

    # Patterns — fields from frontmatter use gate_* and signal_*_fit naming
    patterns = []
    for p in load_pattern_definitions():
        # Merge all signal fit levels for display
        all_signals = []
        for key in ("signal_high_fit", "signal_medium_fit", "signal_low_fit"):
            val = p.get(key, [])
            if isinstance(val, list):
                all_signals.extend(val)
        patterns.append({
            "id": p.get("id"),
            "label": p.get("label", p.get("id")),
            "personas": p.get("gate_personas", []),
            "intents": p.get("gate_intents", []),
            "states": p.get("gate_states", []),
            "signals_boost": all_signals,
            "file": p.get("_source_file", ""),
        })

    # Personas
    personas = []
    persona_map = {
        "P-W-LK": "lk", "P-W-SL": "sl", "P-W-POL": "pol", "P-W-PRESSE": "presse",
        "P-W-RED": "red", "P-BER": "ber", "P-VER": "ver", "P-ELT": "elt", "P-AND": "and",
    }
    for p in load_persona_definitions():
        slug = persona_map.get(p["id"], p["id"].lower())
        personas.append({
            "id": p["id"],
            "label": p["label"],
            "file": f"04-personas/{slug}.md",
        })

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


# ── MCP Server Registry ──────────────────────────────────────────

@router.get("/mcp-servers")
async def get_mcp_servers():
    """List all registered MCP servers."""
    from app.services.config_loader import load_mcp_servers
    return load_mcp_servers()


class McpServerUpdate(BaseModel):
    servers: list[dict]


@router.put("/mcp-servers")
async def update_mcp_servers(data: McpServerUpdate):
    """Update the full MCP server registry."""
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
