"""Config router — serves and updates chatbot configuration files for the Studio."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.schemas import ConfigFile
from app.services.auth import require_studio_key
from app.services.config_loader import (
    CHATBOT_DIR,
    list_config_files,
    read_config_file,
    write_config_file,
)

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
    from app.services.config_loader import CHATBOT_DIR
    full_path = CHATBOT_DIR / path
    if full_path.exists():
        os.remove(full_path)
        return {"status": "deleted", "path": path}
    raise HTTPException(status_code=404, detail="File not found")


@router.get("/export")
async def export_config():
    """Export full configuration as JSON for frontend/studio use."""
    files = list_config_files()
    export = {}
    for f in files:
        content = read_config_file(f["path"])
        export[f["path"]] = {
            "name": f["name"],
            "type": f["type"],
            "content": content,
        }
    return export


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

    from app.services.mcp_client import discover_server_tools
    try:
        tools = await discover_server_tools(url)
        return {"url": url, "tools": tools}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Verbindung fehlgeschlagen: {e}")


class ConfigImport(BaseModel):
    """Batch import: dict of {path: {name, type, content}}."""
    files: dict[str, dict[str, str]]


@router.post("/import")
async def import_config(data: ConfigImport):
    """Batch import: write multiple config files at once from an export JSON."""
    written = []
    for path, entry in data.files.items():
        content = entry.get("content", "")
        if not content:
            continue
        write_config_file(path, content)
        written.append(path)
    return {"status": "imported", "files": written, "count": len(written)}


# ── Full backup / restore as ZIP ─────────────────────────────────
#
# These two endpoints zip up / restore the *entire* chatbots/wlo/v1 tree so
# you can snapshot a configuration, swap variants for A/B testing, or share
# a setup with another instance.

@router.get("/backup")
async def backup_config():
    """Download the full configuration as a ZIP archive."""
    if not CHATBOT_DIR.exists():
        raise HTTPException(status_code=404, detail="No chatbot config found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(CHATBOT_DIR.rglob("*")):
            if path.is_file():
                arc = path.relative_to(CHATBOT_DIR).as_posix()
                zf.write(path, arcname=arc)
    buf.seek(0)

    fname = f"boerdi-config-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/restore")
async def restore_config(
    file: UploadFile = File(...),
    wipe: bool = False,
):
    """Restore a configuration from a ZIP backup.

    Parameters
    ----------
    file : UploadFile
        The .zip produced by ``GET /api/config/backup``.
    wipe : bool
        If true, every file in the current chatbots/wlo/v1 tree is deleted
        BEFORE the archive is extracted. Use this when restoring a foreign
        snapshot to avoid leftover orphans. Default is false (merge).
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="ZIP file required")

    raw = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP archive")

    # Path safety: refuse archives with absolute paths or '..' segments
    for name in zf.namelist():
        if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
            raise HTTPException(status_code=400, detail=f"Unsafe path in ZIP: {name}")

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
    extracted = []
    for member in zf.infolist():
        if member.is_dir():
            continue
        target = CHATBOT_DIR / member.filename
        # Defense in depth: ensure target stays inside CHATBOT_DIR
        try:
            target.resolve().relative_to(CHATBOT_DIR.resolve())
        except ValueError:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as dst:
            dst.write(src.read())
        extracted.append(member.filename)

    return {
        "status": "restored",
        "wiped": wipe,
        "files_extracted": len(extracted),
        "files": extracted[:50],  # cap response size
    }
