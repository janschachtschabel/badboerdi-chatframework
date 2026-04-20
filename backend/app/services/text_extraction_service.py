"""Text-Extraction-Service (Phase 2).

Wrapper um den OEH-Text-Extraction-Dienst
`https://text-extraction.prod.openeduhub.net/from-url` mit einem Noise-Filter.
Der Dienst liefert typischerweise sehr viel Boilerplate (Cookie-Banner,
Navigation, Footer, Social-Media-Links, Sidebar-Widget) — fuer einen
Remix-Flow muss das reduziert werden, sonst sprengt der Volltext den
LLM-Kontext und dominiert das generierte Material mit Noise.

Design:
- Kurzer Timeout (12s) — UI-Flow darf nicht blockieren.
- `method="browser"` (Headless-Chromium beim Dienst), damit auch JS-Seiten
  vernuenftig gerendert werden.
- Post-Processing: Blacklist haeufiger Boilerplate-Zeilen + Fokus auf den
  zentralen Content-Block (groesster zusammenhaengender Textabschnitt ohne
  Bulletpoint-Nav).
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ENDPOINT = "https://text-extraction.prod.openeduhub.net/from-url"
_UA = "BadBoerdi-Widget/1.0 (+https://wirlernenonline.de)"

# Zeilen die typischerweise Navigation/Cookie/Footer sind — werden entfernt.
_NOISE_LINE_RE = re.compile(
    r"(?i)^("
    r"zustimmung verwalten|cookie|datenschutz|impressum|agb|nutzungsbedingungen|"
    r"newsletter|social|folge uns|teilen|drucken|nach oben|zur\u00fcck|"
    r"menue?|navigation|home|startseite|kontakt|anmelden|registrieren|"
    r"skip to content|zum inhalt springen|zur hauptnavigation|"
    r"\u00bb|optionen verwalten|einstellungen|manage (consent|options)|"
    r"akzeptieren|ablehnen|speichern|funktional|vorlieben|statistiken|marketing|"
    r"alle akzeptieren|nur notwendige"
    r")\b.*$"
)
# Markdown-Bullets mit nur Links / einzelnem Wort (Nav-Klone).
# Erfasst auch Wikipedia-Links mit Title-Attribut: [Text](URL "Title")
_NAV_BULLET_RE = re.compile(
    r"^\s*[-*+]\s+"
    r"(?:"
    # (a) Nur ein Markdown-Link (mit optionalem Title in Quotes)
    r"\[[^\]]+\]\(\S+(?:\s+\"[^\"]*\")?\)"
    # (b) oder ein sehr kurzer Bare-Text (<=40 chars, typischer Nav-Label)
    r"|[A-Za-z\u00c0-\u017f\d .\u2013\u2014&/()-]{1,40}"
    r")\s*$"
)
# Mehrere Links auf einer Zeile (typische Inline-Nav) — wenn >=2 Links und
# wenig anderer Text, ist es fast immer Navigation.
_MULTI_LINK_RE = re.compile(r"\[[^\]]+\]\(\S+[^)]*\)")
# Bildverweise (fuer unsere Zwecke irrelevant)
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
# Duplicate collapse
_WHITE_RE = re.compile(r"[ \t]+")
_BLANK_BLOCK_RE = re.compile(r"\n{3,}")


def _clean_markdown(md: str) -> str:
    """Heuristic boilerplate filter for OEH-text-extraction markdown output."""
    if not md:
        return ""
    # Bilder raus (ohne Caption sind sie im Remix unbrauchbar)
    md = _MD_IMAGE_RE.sub("", md)
    out_lines: list[str] = []
    for raw in md.splitlines():
        line = _WHITE_RE.sub(" ", raw.rstrip())
        stripped = line.strip()
        if not stripped:
            out_lines.append("")
            continue
        if _NOISE_LINE_RE.match(stripped):
            continue
        if _NAV_BULLET_RE.match(line):
            continue
        # Zeile mit >=2 Markdown-Links und wenig Rest-Text -> Nav
        links = _MULTI_LINK_RE.findall(line)
        if len(links) >= 2:
            text_outside = _MULTI_LINK_RE.sub("", line).strip(" -*|[]()")
            if len(text_outside) < 30:
                continue
        out_lines.append(line)
    cleaned = "\n".join(out_lines)
    # Leer-Zeilen-Bloecke zusammenfassen
    cleaned = _BLANK_BLOCK_RE.sub("\n\n", cleaned).strip()
    return cleaned


def _extract_main_block(cleaned: str, min_chars: int = 400) -> str:
    """Return the largest coherent prose block (heuristic).

    Splits on blank-line separated blocks, drops very short ones and picks
    the longest contiguous run of useful content.
    """
    if not cleaned:
        return ""
    blocks = [b.strip() for b in re.split(r"\n{2,}", cleaned) if b.strip()]
    if not blocks:
        return ""
    # Keep blocks with enough words/chars; drop single-line nav dregs
    keep = [b for b in blocks if len(b) >= 60 or b.startswith(("#", "##", "###"))]
    if not keep:
        return cleaned
    # Prefer the longest contiguous range
    return "\n\n".join(keep)


async def extract_text_from_url(
    url: str,
    *,
    lang: str = "auto",
    method: str = "browser",
    timeout_s: float = 12.0,
    max_chars: int = 6000,
) -> dict[str, Any] | None:
    """Extract textual content from a URL with the OEH service.

    Returns a dict {text, lang, status, version, original_length, cleaned_length}
    or None on failure. `text` is already noise-filtered and capped at
    `max_chars`. Callers can further truncate for LLM context.
    """
    u = (url or "").strip()
    if not u or not u.startswith(("http://", "https://")):
        return None
    payload = {
        "url": u,
        "method": method,
        "browser_location": None,
        "lang": lang,
        "output_format": "markdown",
        "preference": "none",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s, headers={"User-Agent": _UA}) as c:
            r = await c.post(_ENDPOINT, json=payload)
            if r.status_code != 200:
                logger.info("text-extraction status %s for %r", r.status_code, u)
                return None
            data = r.json() or {}
            raw = data.get("text") or ""
            if not raw:
                return None
            cleaned = _clean_markdown(raw)
            focused = _extract_main_block(cleaned) or cleaned
            if len(focused) > max_chars:
                focused = focused[:max_chars].rsplit("\n", 1)[0] + "\n\n[…Text gekuerzt]"
            return {
                "text": focused,
                "lang": data.get("lang") or "",
                "status": data.get("status") or r.status_code,
                "version": data.get("version") or "",
                "original_length": len(raw),
                "cleaned_length": len(focused),
            }
    except (httpx.HTTPError, ValueError) as e:
        logger.info("text-extraction failed for %r: %s", u, e)
        return None
