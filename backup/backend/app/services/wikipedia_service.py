"""Schlanker Wikipedia-DE-Helper (Phase-2-MVP).

Nutzt die offizielle MediaWiki-REST-Summary-API (de.wikipedia.org) — keine
zusaetzliche Abhaengigkeit, keine Crawler-Logik. Liefert fuer ein Thema
Titel, Beschreibung und Lead-Paragraph. Wird von canvas_service genutzt,
um KI-generierte Materialien mit gepruefter Kurzinfo anzureichern.

Design-Entscheidungen:
- Summary-Endpoint liefert schon einen 3-5 Satz Extract (ideale Groesse).
- Search-Endpoint vorgeschaltet, damit wir Weiterleitungen / uneindeutige
  Titel sauber abfangen.
- Time-out bewusst kurz (6s) — wir wollen den Canvas-Flow nicht blockieren.
- Ab v2: Relevance-Check vor dem Einsatz — nur wenn der gefundene Artikel
  wirklich zum Topic passt (Title/Extract enthaelt normalisiertes Topic
  oder umgekehrt), geben wir den Summary zurueck. Sonst None, damit der
  LLM auf sein eigenes Wissen zurueckfaellt.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://de.wikipedia.org/w/rest.php/v1"
_SUMMARY_BASE = "https://de.wikipedia.org/api/rest_v1/page/summary"
_UA = "BadBoerdi-Widget/1.0 (+https://wirlernenonline.de; contact: redaktion@wirlernenonline.de)"


def _normalize(s: str) -> str:
    """Lowercase, strip diacritics + non-alnum, collapse whitespace."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9äöüß ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_STOP = {
    "und", "oder", "der", "die", "das", "den", "dem", "des",
    "ein", "eine", "einer", "einem", "eines", "für", "fuer",
    "klasse", "schule", "stufe", "sek", "kl",
    "stadt", "land", "ort",  # generic location words — don't let them alone match
}


def _word_match(word: str, normalized_text: str) -> bool:
    """Whole-word match in a whitespace-normalized text.

    Uses padded substring check ('\\s+word\\s+' in '\\s+text\\s+') instead
    of raw `word in text`, because plain substring would accept
    'berlin' in 'ueberlingen' (b-e-r-l-i-n is a substring of ueb-erlin-gen).
    """
    if not word or not normalized_text:
        return False
    return f" {word} " in f" {normalized_text} "


def _is_relevant(topic: str, title: str, extract: str) -> bool:
    """True if the article looks genuinely about `topic`.

    Strategie (von stark nach schwach):
      1. Direkte Enthaltenheit: Topic == Title, Topic ⊂ Title, Title ⊂ Topic
      2. Multi-Word-Topic (≥2 Original-Tokens): das laengste Content-Word
         muss als GANZES Wort im Titel auftreten. Verhindert:
           - "Stadt Berlin" → "Stadtbergen"     ('berlin' ∉ 'stadtbergen')
           - "Stadt Berlin" → "Stadt Ueberlingen" ('berlin' ∉ Wortgrenze)
      3. Single-Word-Topic: Word-Match in Title oder Extract ODER
         bidirektionaler Prefix ≥ 5 Zeichen (fängt "Bruchrechnung" ↔
         "Bruch (Mathematik)", "Feinoptik" ↔ "Feinoptiker").
    """
    t = _normalize(topic)
    nt = _normalize(title)
    ne = _normalize(extract[:300])
    if not t:
        return False

    # 1. Direct containment (rare but strong)
    if t == nt or t in nt or nt in t:
        return True

    original_tokens = t.split()
    content_words = [w for w in original_tokens if len(w) >= 4 and w not in _STOP]
    if not content_words:
        return False

    # 2. Multi-word topic: longest content word must appear as a whole word
    #    in the title.
    if len(original_tokens) >= 2:
        longest = max(content_words, key=len)
        return _word_match(longest, nt)

    # 3. Single-word topic.
    word = content_words[0]
    if _word_match(word, nt) or _word_match(word, ne):
        return True
    # Morphological relatives: "Bruchrechnung" ↔ "Bruch", "Feinoptik" ↔
    # "Feinoptiker". Word must share a common prefix of at least 5 chars
    # with a full word in the title.
    for tw in nt.split():
        if len(tw) >= 5 and (word.startswith(tw) or tw.startswith(word)):
            return True

    return False


async def fetch_wikipedia_summary(topic: str, timeout_s: float = 6.0) -> dict[str, Any] | None:
    """Resolve a topic to a Wikipedia article summary, if relevant.

    Returns a dict with keys {title, description, extract, url} or None on
    miss / irrelevant match / disambiguation. Never raises — failures return
    None so the caller can fall back to LLM-only.
    """
    q = (topic or "").strip()
    if not q:
        return None

    try:
        async with httpx.AsyncClient(timeout=timeout_s, headers={"User-Agent": _UA}) as c:
            # Step 1: search — ask for top-3 so we can pick the best relevant hit.
            sr = await c.get(f"{_BASE}/search/title", params={"q": q, "limit": 3})
            if sr.status_code != 200:
                logger.info("wiki search status %s for %r", sr.status_code, q)
                return None
            data = sr.json() or {}
            pages = data.get("pages") or []
            if not pages:
                return None

            # Step 2: fetch summaries in order, return the first relevant one.
            for page in pages:
                key = page.get("key") or page.get("title")
                if not key:
                    continue
                try:
                    su = await c.get(f"{_SUMMARY_BASE}/{key}")
                except httpx.HTTPError:
                    continue
                if su.status_code != 200:
                    continue
                sdata = su.json() or {}
                if sdata.get("type") == "disambiguation":
                    continue
                extract = (sdata.get("extract") or "").strip()
                if not extract:
                    continue
                title = sdata.get("title") or page.get("title") or q

                if not _is_relevant(q, title, extract):
                    logger.info("wiki reject irrelevant hit for %r: %r", q, title)
                    continue

                return {
                    "title": title,
                    "description": (sdata.get("description") or "").strip(),
                    "extract": extract,
                    "url": ((sdata.get("content_urls") or {}).get("desktop") or {}).get("page") or "",
                }
            logger.info("wiki: no relevant hit for %r (checked %d)", q, len(pages))
            return None
    except (httpx.HTTPError, ValueError) as e:
        logger.info("wiki lookup failed for %r: %s", q, e)
        return None
