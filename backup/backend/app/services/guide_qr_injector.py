"""Deterministischer Guide-Quick-Reply-Injektor.

Das LLM bekommt im Prompt zwar erklärt, dass es bei passenden User-Fragen
einen Guide-QR der Form ``__guide__|<label>|<url>`` einbauen darf — aber
in der Praxis ist die Hit-Rate < 20%. Damit der Webseiten-Lotse trotzdem
zuverlässig erscheint, läuft dieses Modul **nach** dem QR-LLM und
injiziert deterministisch einen Guide-QR, wenn:

1. Die User-Frage zu einem konfigurierten Pattern passt (Regex), UND
2. Die LLM-generierten Quick-Replies noch keinen ``__guide__|...`` haben.

Das Mapping ist hier inline gehalten (statt YAML), weil es klein und
selten geändert wird. Bei Wachstum auf >20 Einträge auf YAML umstellen.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)


# Der Magic-Prefix, den das Frontend erkennt (siehe chat.component.ts:
# ChatComponent.GUIDE_QR_PREFIX). MUSS exakt 1:1 dort übereinstimmen.
GUIDE_QR_PREFIX = "__guide__|"


# Reihenfolge: spezifischere Patterns ZUERST, generische zuletzt.
# Jedes Tupel: (regex, label, url, priority).
# - regex: re.IGNORECASE wird automatisch angewendet
# - label: Text auf dem Button (max ~40 chars)
# - url: vollständiges https-URL (Cross-Domain-Handoff übernimmt das
#   Widget; das Ziel muss aber zur guide-mode allow-list passen)
# - priority: bei Mehrfach-Match gewinnt der höchste Wert
_RULES: list[tuple[str, str, str, int]] = [
    # Themenseiten — explizite Anfragen mit Thema-Slug
    (r"\bthemenseite[ns]?\s+(?:zu(?:m|r)?|f(?:ü|ue)r|über)\s+klimawandel\b",
     "Themenseite Klimawandel", "https://wirlernenonline.de/themenseite/klimawandel", 90),
    (r"\bthemenseite[ns]?\s+(?:zu(?:m|r)?|f(?:ü|ue)r|über)\s+photosynthese\b",
     "Themenseite Photosynthese", "https://wirlernenonline.de/themenseite/photosynthese", 90),
    (r"\bthemenseite[ns]?\s+(?:zu(?:m|r)?|f(?:ü|ue)r|über)\s+nachhaltigkeit\b",
     "Themenseite Nachhaltigkeit", "https://wirlernenonline.de/themenseite/nachhaltigkeit", 90),

    # Was IST eine Themenseite (Konzept-Frage)
    (r"\bwas\s+(?:ist|sind|bedeutet)\s+(?:eine|die)?\s*themenseite",
     "Themenseiten-Beispiel", "https://wirlernenonline.de/themenseite/klimawandel", 80),

    # Mitmachen / Beitragen / Inhalte einreichen
    (r"\b(?:mitmachen|mit\s*machen|beitragen|inhalte\s+(?:einreichen|hochladen|teilen)|wie\s+kann\s+ich\s+(?:bei\s+wlo\s+)?(?:helfen|mitwirken))\b",
     "Mitmachen-Seite", "https://wirlernenonline.de/mitmachen", 75),

    # Über WLO / Hintergrund / wer steht dahinter
    (r"\b(?:wer\s+(?:steht|steckt)\s+(?:hinter|dahinter)|(?:über|ueber)\s+wlo|wer\s+macht\s+wlo|über\s+(?:die\s+)?plattform)\b",
     "Über WLO", "https://wirlernenonline.de/ueber-uns", 70),

    # Geschichte / Entstehung / Projekt-Hintergrund
    (r"\b(?:wie\s+ist\s+wlo\s+entstanden|entstehung|geschichte\s+(?:von\s+)?wlo|projekt(?:hintergrund)?|hintergrund\s+(?:von\s+)?wlo)\b",
     "Hintergrund WLO", "https://wirlernenonline.de/projekt", 65),

    # Fachportale-Übersicht — akzeptiert alle drei Schreibweisen pro
    # Umlaut (ä / ae / a), damit Anfragen ohne Umlaute genauso matchen.
    (r"\b(?:welche\s+f(?:ä|ae|a)cher|alle\s+f(?:ä|ae|a)cher|f(?:ä|ae|a)chportal\w*|alle\s+(?:disziplinen|portale)|f(?:ä|ae|a)cher(?:ü|ue|u)bersicht)\b",
     "Fachportal-Übersicht", "https://wirlernenonline.de/fachportale", 70),

    # OER allgemein
    (r"\bwas\s+(?:ist|sind|bedeutet|bedeuten)\s+oer\b",
     "OER-Erklärung", "https://wirlernenonline.de/oer", 60),

    # Edu-Sharing — nur die ECHT eindeutigen Spezialfälle hier matchen,
    # damit allgemeine „edu-sharing"-Anfragen vom Stage-3b-RAG-Chunk-
    # Lookup beantwortet werden (der zwischen Verein, Plattform,
    # Metaventis-Software, ITSjointly etc. anhand des tatsächlich
    # getroffenen RAG-Chunks unterscheidet).
    #
    # Verein (e.V., e.v., Vereinsstruktur explizit gefragt):
    (r"\bedu[\s-]*sharing(?:[\s.-]*net)?\s*e\.?\s*v\.?\b",
     "Edu-Sharing-Verein", "https://edu-sharing.net/", 60),
    # ITSjointly Spezialfrage (eigenes BMBF-Förderprojekt):
    (r"\b(?:its[\s-]*)?jointly[\s-]*(projekt|förderprojekt|info)?\b",
     "ITSjointly-Projekt", "https://its.jointly.info/", 60),
    # Bewusste Nicht-Spezialregel für „was ist edu-sharing" usw. —
    # das überlassen wir Stage 3b (RAG-Chunk-URL aus Frontmatter), weil
    # je nach Frage entweder edu-sharing.com (Metaventis-Plattform),
    # openeduhub.net (gemeinsames Repo), edu-sharing-network.org
    # (Verein) oder its.jointly.info (Förderprojekt) das RICHTIGE Ziel
    # ist — eine pauschale Default-URL trifft hier zu oft daneben.

    # WissenLebtOnline — eigene Schwester-Webseite mit eigener URL.
    # Triggert auf "wissenlebtonline" (mit oder ohne Leerzeichen)
    # und auf "wlo-projekt"/"wlo-infrastruktur" — beides Indikatoren
    # für Fragen zur Hintergrund-Plattform statt zum Suchportal.
    (r"\bwissen\s*lebt\s*online\b",
     "WissenLebtOnline-Webseite", "https://wissenlebtonline.de/", 78),

    # Metaventis — separate Firma, eigene Domain.
    (r"\bmetaventis\b",
     "Metaventis", "https://metaventis.com/", 65),

    # Startseite WLO als Fallback wenn der User nach „WLO allgemein" fragt
    (r"\bwas\s+(?:ist|kann)\s+(?:wir\s*lernen\s*online|wirlernenonline|wlo)\b",
     "WLO-Startseite", "https://wirlernenonline.de/", 50),
]


  # RAG-Area → (Anzeigetext, Ziel-URL, Brand-Regex). Fallback wenn weder
# Message-Regex noch LLM einen Guide-QR liefert.
#
# Die Areas werden in ``session_state["_rag_areas_used"]`` getrackt —
# sowohl bei expliziten ``query_knowledge``-Calls als auch beim Mode-
# Always-Prefetch (jeder Turn). Damit nicht JEDER Turn einen Guide-QR
# bekommt (Prefetch ist breit), prüft ``find_rag_area_match`` per
# Brand-Regex, ob der Bot die Area in seiner Antwort TATSÄCHLICH
# verwendet hat — nur dann wird die URL angeboten.
#
# Keys = Area-Namen aus 05-knowledge/rag-config.yaml. Tuple-Position 3
# ist eine Regex (re.IGNORECASE) auf den Bot-Response-Text. Areas ohne
# eigene Webseite (FAQ, Plattformwissen) sind nicht gelistet und lösen
# nie einen Guide-QR aus.
_RAG_AREA_URLS: dict[str, tuple[str, str, str]] = {
    "WissenLebtOnline":         ("WissenLebtOnline-Webseite", "https://wissenlebtonline.de/",
                                 r"\bwissen\s*lebt\s*online\b|\bwissenlebtonline\b"),
    "WirLernenOnline":          ("WirLernenOnline-Webseite", "https://wirlernenonline.de/",
                                 r"\b(?:wir\s*lernen\s*online|wirlernenonline|wlo)\b"),
    "OER-Wissen":               ("OER-Erklärung", "https://wirlernenonline.de/oer",
                                 r"\boer\b|\bopen\s+educational\s+resources\b"),
    # Edu-Sharing-Verein: edu-sharing-network.org ist die Vereins-Webseite
    # (gemeinnütziger e.V.). edu-sharing.net ist die historisch ältere
    # Marken-Domain — Frontmatter zeigt aber auf edu-sharing-network.org.
    "Edu-Sharing-Network":      ("Edu-Sharing-Verein", "https://edu-sharing-network.org/",
                                 r"edu[\s-]*sharing(?:[\s.-]*net)?\s*e\.?\s*v\.?|edu[\s-]*sharing[\s-]*verein|edu[\s-]*sharing\.net|edu[\s-]*sharing[\s-]*network"),
    # Edu-Sharing-Metaventis: edu-sharing.com ist die Metaventis-Produkt-
    # Webseite (kommerzielle Open-Source-Software). openeduhub.net ist
    # das gemeinsame Repository — passt nur als Notlösung, deshalb
    # ist .com hier vorne.
    "Edu-Sharing-Metaventis":   ("Edu-Sharing-Software", "https://edu-sharing.com/",
                                 r"\bmetaventis\b|edu[\s-]*sharing\.com|edu[\s-]*sharing[\s-]*(plattform|software|cloud|produkt)"),
    "ITSJOINTLY-Schlussbericht": ("ITSjointly-Projekt", "https://its.jointly.info/",
                                  r"\bitsjointly\b|\bjointly[\s-]*(projekt|info|förderprojekt)?\b"),
}


# Cache der kompilierten Regexen — ohne Re-Compile pro Call.
_COMPILED: list[tuple[re.Pattern, str, str, int]] | None = None


def _compiled() -> list[tuple[re.Pattern, str, str, int]]:
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = [
            (re.compile(pat, re.IGNORECASE), label, url, prio)
            for (pat, label, url, prio) in _RULES
        ]
    return _COMPILED


def _has_guide_qr(qrs: Iterable[str]) -> bool:
    """True if at least one entry already uses the magic prefix."""
    return any(isinstance(q, str) and q.startswith(GUIDE_QR_PREFIX) for q in qrs)


def _normalize_to_https(url: str) -> str:
    """Bring-mich-hin-URLs werden im selben Browser-Tab geöffnet — wir
    erlauben nur HTTPS, damit der User nicht versehentlich von einer
    HTTPS-Seite auf eine unverschlüsselte HTTP-Seite umgeleitet wird.

    Das LLM rendert manchmal aus seinem Trainingswissen ``http://`` ohne
    ``s`` (Beispiel-Eval: ``http://wissenlebtonline.de/`` obwohl der
    RAG-Inhalt durchgehend ``https://`` enthält). Wir upgraden hier
    transparent.
    """
    if not url or not isinstance(url, str):
        return url or ""
    s = url.strip()
    if s.lower().startswith("http://"):
        return "https://" + s[len("http://"):]
    return s


def _format_qr(label: str, url: str) -> str:
    return f"{GUIDE_QR_PREFIX}{label}|{_normalize_to_https(url)}"


def find_guide_match(message: str) -> tuple[str, str] | None:
    """Return ``(label, url)`` for the highest-priority pattern that
    matches ``message``, or ``None`` when no pattern matches.

    Pure function — no side effects, no I/O. Call sites can use it for
    direct lookups (e.g. when composing tool-arg replies).
    """
    if not message or not isinstance(message, str):
        return None
    best: tuple[str, str, int] | None = None  # (label, url, prio)
    for pat, label, url, prio in _compiled():
        if pat.search(message):
            if best is None or prio > best[2]:
                best = (label, url, prio)
    if best is None:
        return None
    return best[0], best[1]


def _allow_listed_host(url: str) -> bool:
    """True if ``url``'s host matches the guide-mode allow-list. Used to
    keep response-text URLs from leaking to non-WLO domains."""
    try:
        from urllib.parse import urlparse
        from app.services.guide_mode_service import host_is_allowed
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        return host_is_allowed(parsed.hostname)
    except Exception:
        return False


def _is_domain_root(url: str) -> bool:
    """True wenn die URL nur die Domain-Hauptseite ist (kein Pfad oder
    nur ``/``). Beispiele:
      - https://wirlernenonline.de         → True
      - https://wirlernenonline.de/        → True
      - https://wirlernenonline.de/oer/    → False
    Wird für die LLM-eigene-QR-Wahl verwendet: Domain-Roots sind
    schwache Treffer und werden von präziseren Stages (Markdown-Link,
    RAG-Chunk-URL) überstimmt.
    """
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url or "")
        path = (parsed.path or "").strip()
        return path in ("", "/") and not parsed.query and not parsed.fragment
    except Exception:
        return False


def _parse_existing_guide(qr: str) -> tuple[str, str] | None:
    """Parse a magic-prefix QR string ``__guide__|<label>|<url>``.
    Returns ``(label, url)`` or ``None`` on malformed input.
    """
    if not isinstance(qr, str) or not qr.startswith(GUIDE_QR_PREFIX):
        return None
    rest = qr[len(GUIDE_QR_PREFIX):]
    sep = rest.find("|")
    if sep == -1:
        return None
    label = rest[:sep].strip()
    url = rest[sep + 1:].strip()
    if not url:
        return None
    return label, url


# Match Markdown-Links: ``[label](url)`` plus angle-bracket URLs ``<url>``.
# Used to harvest URLs the bot explicitly mentioned in its response text —
# those are far more precise than the hardcoded RAG-Area URLs (which always
# point at domain root, regardless of topic).
_MD_LINK_RE = re.compile(
    r"\[([^\]]{1,80})\]\((https?://[^\s)]+)\)"
    r"|<(https?://[^\s>]+)>",
    re.IGNORECASE,
)


def find_response_urls(response_text: str | None) -> list[tuple[str, str]]:
    """Extract ALL allow-listed URLs from the bot's Markdown response in
    document order. Returns a list of ``(label, url)`` tuples — empty
    if no usable URL was found.

    Priorities (within a single response):
    - Markdown-Links ``[label](url)`` first — that's the canonical form
      the bot uses when summarising RAG content; the label is then a
      meaningful Topic-Name.
    - Angle-bracket auto-links ``<url>`` second — fallback when the bot
      pastes a URL without anchor text.

    Filters:
    - Only ``http(s)``-URLs (output is always normalised to HTTPS by
      the caller via ``_format_qr``).
    - Only allow-listed hosts (guide-mode.yaml ``allowed_hosts``).
    - Skips trailing punctuation (``,``, ``.``, ``;``) on URLs.
    - **Skips URLs pointing at the bare domain root** — those add no
      value over the deterministic Stage-3b/3c fallbacks.
    - Deduplicates by URL within the same response.

    Returning a list (not just the first match) lets the caller offer
    multiple Bring-mich-hin-buttons when the bot referenced multiple
    pages — e.g. ``[WLO](https://wlo.de/) and [Angebote](https://wlo.de/angebote/)``
    yields two distinct Guide-QRs.
    """
    if not response_text:
        return []

    specific: list[tuple[str, str]] = []
    domain_roots: list[tuple[str, str]] = []
    seen: set[str] = set()

    for m in _MD_LINK_RE.finditer(response_text):
        label = (m.group(1) or "").strip() or None
        url = (m.group(2) or m.group(3) or "").strip()
        url = url.rstrip(",.;:!?")
        if not url or url in seen:
            continue
        seen.add(url)
        if not _allow_listed_host(url):
            continue
        eff_label = label
        if not eff_label:
            try:
                from urllib.parse import urlparse
                last_seg = urlparse(url).path.rstrip("/").split("/")[-1] or "Quell-Seite"
                eff_label = last_seg.replace("-", " ").title()
            except Exception:
                eff_label = "Mehr erfahren"
        if len(eff_label) > 50:
            eff_label = eff_label[:47] + "…"
        if _is_domain_root(url):
            domain_roots.append((eff_label, url))
        else:
            specific.append((eff_label, url))

    # Spezifische URLs zuerst (mit Sub-Pfad = präziser Treffer);
    # Domain-Roots danach. So wird ``[WLO](https://wlo.de/) und
    # [Angebote](https://wlo.de/angebote/)`` als
    # ``[Angebote, WLO]`` zurückgegeben — die spezifische URL ist
    # primärer Bring-mich-hin-Kandidat, der Domain-Root sekundär.
    return specific + domain_roots


def find_response_url(response_text: str | None) -> tuple[str, str] | None:
    """Backward-compatible single-result variant of
    :func:`find_response_urls`. Returns the first hit or ``None``."""
    hits = find_response_urls(response_text)
    return hits[0] if hits else None


def find_rag_area_match(
    rag_areas: Iterable[str] | None,
    response_text: str | None = None,
) -> tuple[str, str] | None:
    """Return ``(label, url)`` for the first RAG-area that is BOTH
    mapped in ``_RAG_AREA_URLS`` AND verifiably used in the bot's
    response (Brand-Regex match on ``response_text``).

    Why the Brand-Match check: Since mode:always RAG-areas are
    prefetched on EVERY turn, simply tracking "what was loaded" would
    fire a Guide-QR on every chat turn — even when the bot's answer
    doesn't actually rely on that source. The Brand-Regex (third
    tuple position in ``_RAG_AREA_URLS``) is a cheap proxy for
    "did the bot mention this source by name". When the regex matches,
    we're confident the user benefits from a link to the source page.

    When ``response_text`` is None or empty, the Brand-check is
    skipped — useful for explicit ``query_knowledge``-only turns
    where the user clearly asked about a specific area.

    Pure function. Used as last-resort fallback after Stage 1
    (message-regex) and Stage 2 (LLM eigene ``__guide__|...``).
    """
    if not rag_areas:
        return None
    text = (response_text or "").lower()
    for area in rag_areas:
        if not isinstance(area, str):
            continue
        triple = _RAG_AREA_URLS.get(area)
        if not triple:
            continue
        label, url, brand_re = triple
        # If we have response_text, require the brand to appear in it.
        # Without response_text (e.g. legacy callers), trust the area
        # was queried explicitly enough to warrant the link.
        if text:
            try:
                if not re.search(brand_re, text, re.IGNORECASE):
                    continue
            except re.error:
                # Bad regex in config — skip this entry, don't crash.
                logger.warning("invalid brand regex for area '%s'", area)
                continue
        return label, url
    return None


def inject_guide_qr(
    message: str,
    quick_replies: list[str],
    *,
    enabled: bool = True,
    max_qrs: int = 4,
    rag_areas_used: Iterable[str] | None = None,
    response_text: str | None = None,
    rag_top_sources: Iterable[str] | None = None,
    max_guide_qrs: int = 2,
) -> list[str]:
    """Return a copy of ``quick_replies`` with a Guide-QR added (or
    upgraded) when appropriate.

    Trigger-Reihenfolge (deterministisch vor heuristisch):
    1. **Message-Regex** matcht eine Regel aus ``_RULES`` →
       SETZT/ERSETZT den Guide-QR. Übersteuert auch eine bereits vom
       LLM gesetzte ``__guide__|...``-Wahl, weil Regex deterministisch
       und domain-konsistent ist.
    2. **LLM-Eigenproduktion**: hat das LLM selbst schon einen
       ``__guide__|...``-Eintrag erzeugt und Stage 1 hatte keinen
       Treffer → diesen unverändert lassen.
    3. **RAG-Area-Fallback**: hat der Bot ``query_knowledge(area=…)``
       mit einer in ``_RAG_AREA_URLS`` gemappten Area aufgerufen →
       die zugehörige Quell-URL anbieten.

    Behavior:
    - ``enabled=False`` → identity. Call sites pass the user's
      ``guide_mode`` toggle here so the injector is a no-op when
      Lotsen-Modus deaktiviert ist.
    - Match gefunden → der Guide-QR wird an Position 0 eingefügt;
      bei Überschreitung von ``max_qrs`` (default 4) wird der letzte
      normale Eintrag entfernt (statistisch der schwächste).
    - Nichts matcht und Liste hat keinen Guide-QR → unverändert.
    """
    if not enabled:
        return list(quick_replies)
    qrs = list(quick_replies or [])

    # Sammle Kandidaten in Prioritäts-Reihenfolge. Mehrere Stages können
    # Treffer haben — bei ``max_guide_qrs >= 2`` nehmen wir die top-N
    # nach Stage-Priorität, dedupliziert nach URL.
    candidates: list[tuple[str, str, str]] = []  # (label, url, source-tag)
    seen_urls: set[str] = set()

    def _add(label: str, url: str, source: str) -> None:
        norm = _normalize_to_https(url).rstrip("/")
        # Empty path "/" still allowed once — but dedupe based on the
        # full normalized form (without trailing slash).
        if not norm or norm in seen_urls:
            return
        if not _allow_listed_host(url):
            return
        seen_urls.add(norm)
        candidates.append((label, _normalize_to_https(url), source))

    # Stage 1 (specific): Message-Regex mit Sub-Pfad-URL.
    msg_match = find_guide_match(message)
    msg_specific = msg_match is not None and not _is_domain_root(msg_match[1])
    if msg_specific:
        _add(msg_match[0], msg_match[1], "message-regex")
    weak_msg_match = msg_match if msg_match and not msg_specific else None

    # Stage 2 (specific): LLM-eigener __guide__ mit Sub-Pfad.
    existing_qr = next(
        (q for q in qrs if isinstance(q, str) and q.startswith(GUIDE_QR_PREFIX)),
        None,
    )
    existing_parsed = _parse_existing_guide(existing_qr) if existing_qr else None
    llm_specific = existing_parsed is not None and not _is_domain_root(existing_parsed[1])
    if llm_specific:
        _add(existing_parsed[0], existing_parsed[1], "llm-pick")
    weak_llm_pick = existing_qr if existing_qr and not llm_specific else None

    # Bestehende LLM-QRs aus der Liste entfernen — wir setzen unsere
    # normalisierten Versionen am Ende neu ein, damit http→https und
    # Reihenfolge konsistent sind.
    qrs = [q for q in qrs if not (isinstance(q, str) and q.startswith(GUIDE_QR_PREFIX))]

    # Stage 3a: ALLE Bot-Markdown-Links aus response_text — wenn der
    # Bot zwei distinkte URLs verlinkt (z.B. ``[WLO](…) und [Angebote](…)``),
    # werden beide als Guide-QR-Kandidaten registriert und tauchen
    # bei ``max_guide_qrs >= 2`` als getrennte Buttons auf.
    for r_label, r_url in find_response_urls(response_text):
        _add(r_label, r_url, "response-url")

    # Stage 3b: RAG-Chunk-Frontmatter-URL.
    if rag_top_sources:
        try:
            from app.services.rag_url_index import url_for_chunk_sources
            # Versuche bis zu 3 Top-Sources; bei max_guide_qrs=2 reicht
            # idealerweise der erste eindeutige Frontmatter-Treffer,
            # aber wir nehmen mehrere damit dedupe-nach-URL nicht zu
            # früh ausgeht.
            sources_list = [s for s in rag_top_sources if isinstance(s, str)]
            for src in sources_list[:3]:
                chunk_url = url_for_chunk_sources([src])
                if chunk_url and _allow_listed_host(chunk_url) and not _is_domain_root(chunk_url):
                    from urllib.parse import urlparse
                    last_seg = urlparse(chunk_url).path.rstrip("/").split("/")[-1] or ""
                    label = (last_seg.replace("-", " ").title() if last_seg else "Quell-Seite")
                    if len(label) > 50:
                        label = label[:47] + "…"
                    _add(label, chunk_url, "rag-chunk-url")
        except Exception as e:
            logger.warning("rag_top_sources lookup failed: %s", e)

    # Stage 3c: RAG-Area-Brand-Match (Domain-Hauptseite, gefiltert).
    rag_match = find_rag_area_match(rag_areas_used, response_text=response_text)
    if rag_match is not None:
        _add(rag_match[0], rag_match[1], "rag-area")

    # Stage 4 (weak): Message-Regex mit Domain-Root.
    if weak_msg_match:
        _add(weak_msg_match[0], weak_msg_match[1], "message-weak")

    # Stage 5 (weak): LLM-Pick mit Domain-Root.
    if weak_llm_pick:
        weak_parsed = _parse_existing_guide(weak_llm_pick)
        if weak_parsed:
            _add(weak_parsed[0], weak_parsed[1], "llm-weak")

    if not candidates:
        return qrs

    # Top-N Guide-QRs nehmen — Reihenfolge ist die Stage-Priorität,
    # Duplikate nach URL bereits gefiltert.
    picks = candidates[:max(0, max_guide_qrs)]
    if not picks:
        return qrs

    # An den Anfang der QR-Liste einfügen (umgekehrt iterieren, damit
    # die erste Stage am weitesten vorn landet).
    for label, url, _src in reversed(picks):
        qrs.insert(0, _format_qr(label, url))

    if max_qrs and len(qrs) > max_qrs:
        qrs = qrs[:max_qrs]

    if logger.isEnabledFor(logging.DEBUG):
        for label, url, src in picks:
            logger.debug("guide-qr injected (%s): '%s' → %s", src, label, url)

    return qrs
