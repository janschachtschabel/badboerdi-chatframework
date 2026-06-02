"""Card-Pipeline v2 — Beschaffung + Normalisierung (Phase 1+2).

Dieses Modul ersetzt schrittweise die heute über chat.py, mcp_client.py und
guide_mode_service.py verteilte Card-Logik. Es liefert zwei Funktionen, die
eine klare Trennung schaffen:

  * :func:`fetch_card_pool` — ein einziger Aufruf, der je nach Intent-Kind
    parallel die richtigen MCP-Tools ruft und einen großen, vereinheitlichten
    Card-Pool zurückgibt.
  * :func:`normalize_cards` — bringt jede Card durch eine deterministische
    Bereinigung: Host-Rewrite, node_type-Normalisierung, Dedup, Sortierung.

Die Funktionen sind **side-effect-frei** und parallel zur bestehenden Logik
einsetzbar. Solange der Env-Flag ``CARD_PIPELINE_V2`` nicht aktiv ist, ruft
chat.py sie nicht produktiv auf — wir nutzen den Pfad bisher nur für A/B-
Logging und Test-Suite-Aufbau (Phase 9).

Spätere Phasen (3+) bauen darauf auf:
  * Phase 3: :func:`build_card_link` als zentrale URL-Resolution
  * Phase 4: Display-Vereinheitlichung über ``card['link']``
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal
from urllib.parse import quote, urlparse

from app.services.config_loader import (
    get_repo_base_url,
    load_card_pipeline_config,
    rewrite_repo_host_v2,
)

logger = logging.getLogger(__name__)

# Drei kanonische Intent-Kinder für die Beschaffungs-Strategie.
#
#   "general"            — User fragt nach Material zu einem Thema. Pool
#                          wird auf drei Tools verteilt (Themenseite +
#                          Sammlung + Einzelinhalt), Reihenfolge der Final-
#                          Auswahl bevorzugt Themenseite > Sammlung > Einzel.
#   "type-focus"         — User fragt nach einem konkreten Material-Typ
#                          (Videos, Arbeitsblätter, …). Pool kommt nur von
#                          search_wlo_content mit LRT-Filter.
#   "collection-contents"— User klickte/erwähnte eine bestimmte Sammlung.
#                          Pool ist exakt der get_collection_contents-Output.
IntentKind = Literal["general", "type-focus", "collection-contents"]

# Drei kanonische node_types für die Display-Logik:
#   "topic_page" — Sammlung MIT befülltem topic_pages-Feld (Themenseiten-Card)
#   "collection" — Sammlung OHNE topic_pages (reine Sammlung)
#   "content"    — Einzelinhalt (jeder andere Node)
#
# Vorher: 2 Werte ("collection"/"content") + topic_pages-Subfield-Check.
# Die Drei-Wege-Unterscheidung macht alle Folge-Entscheidungen (URL-Resolution
# in Phase 3, Display in Phase 4) zu einem trivialen Lookup statt einer
# zusammengesetzten Bedingung.
NodeType = Literal["topic_page", "collection", "content"]

# Sortier-Prio nach node_type bei "general"-Intent (kleiner = weiter vorn).
_NODE_TYPE_PRIORITY: dict[str, int] = {
    "topic_page": 0,
    "collection": 1,
    "content": 2,
}


def infer_intent_kind(
    *,
    user_message: str,
    wanted_content_types: set[str] | None = None,
    collection_id: str | None = None,
) -> IntentKind:
    """Heuristik für den Intent-Kind aus User-Message + Kontext.

    Wird in Phase 3 (chat-flow Integration) zentral aufgerufen. Aktuell
    bewusst simpel — komplexere Routing-Entscheidungen (z.B. NLU-basiert)
    können später hinzugefügt werden, ohne :func:`fetch_card_pool` zu ändern.

    Reihenfolge der Checks:
      1. ``collection_id`` gesetzt → ``"collection-contents"`` (höchste Prio,
         User hat explizit eine Sammlung im Fokus).
      2. ``wanted_content_types`` nicht-leer → ``"type-focus"`` (User fragt
         nach einem konkreten Material-Typ).
      3. Sonst → ``"general"``.
    """
    if collection_id:
        return "collection-contents"
    if wanted_content_types:
        return "type-focus"
    return "general"


async def fetch_card_pool(
    *,
    query: str,
    intent_kind: IntentKind,
    pool_size: int | None = None,
    collection_id: str | None = None,
    learning_resource_type_uri: str | None = None,
    discipline_uri: str | None = None,
    educational_context_uri: str | None = None,
) -> list[dict[str, Any]]:
    """Beschaffungs-Phase: ein einziger Aufruf liefert den Card-Pool.

    Je nach ``intent_kind`` werden ein oder drei MCP-Tools parallel gerufen,
    die Ergebnisse parsed und in eine einheitliche Card-Liste gegossen. Der
    Caller bekommt einen großen Pool (Default 20 Cards) zurück — die Final-
    Auswahl auf 5 Cards passiert in Phase 3.

    Args:
        query: User-Suchstring (für search_wlo_*-Tools).
        intent_kind: Bestimmt, welche Tools wir rufen.
        pool_size: Override für die Pool-Größe. Default: aus
            ``card-pipeline.yaml``.
        collection_id: Pflicht für ``intent_kind="collection-contents"``.
        learning_resource_type_uri: Optional bei ``"type-focus"``. URI des
            LRT-Filters (z.B. der WLO-LRT-URI für "Video").
        discipline_uri: Optional bei ``"general"``/``"type-focus"``.
        educational_context_uri: Optional, gleicher Anwendungsfall.

    Returns:
        Liste von Card-Dicts im internen Boerdi-Schema (Felder wie
        ``node_id``, ``title``, ``wlo_url``, …). NICHT-normalisiert —
        Host-Rewrite und node_type-Mapping macht :func:`normalize_cards`.

    Raises:
        Nichts. Tool-Fehler werden geloggt und liefern leere Teilmengen.
    """
    # Lazy-Import, damit das Modul auch in Test-Suiten ohne MCP-Server-Setup
    # importierbar bleibt (z.B. für Phase 9 Smoke-Tests).
    from app.services.mcp_client import (
        call_mcp_tool,
        parse_wlo_cards,
        parse_wlo_topic_page_cards,
    )

    cfg = load_card_pipeline_config()
    effective_pool = pool_size if pool_size is not None else cfg["pool_size"]
    # Defensiv-Clamp — sollte schon aus der YAML clamped sein, aber Caller
    # könnten einen Override mit None > YAML-Cap übergeben.
    effective_pool = max(1, min(50, int(effective_pool)))

    logger.info(
        "fetch_card_pool: kind=%s query=%r pool=%d coll=%s lrt=%s",
        intent_kind, query[:60] if query else "", effective_pool,
        collection_id or "-", learning_resource_type_uri or "-",
    )

    # ── intent_kind == "collection-contents" ──────────────────────────
    if intent_kind == "collection-contents":
        if not collection_id:
            logger.warning(
                "fetch_card_pool: collection-contents ohne collection_id — leer."
            )
            return []
        try:
            raw = await call_mcp_tool(
                "get_collection_contents",
                {"collectionId": collection_id, "maxResults": effective_pool},
            )
        except Exception as e:  # pragma: no cover — network failure
            logger.warning("get_collection_contents failed: %s", e)
            return []
        cards = parse_wlo_cards(raw) or []
        logger.info(
            "fetch_card_pool kind=collection-contents → %d cards", len(cards),
        )
        return cards

    # ── intent_kind == "type-focus" ────────────────────────────────────
    if intent_kind == "type-focus":
        args: dict[str, Any] = {
            "query": query or "",
            "maxResults": effective_pool,
        }
        if learning_resource_type_uri:
            args["learningResourceType"] = learning_resource_type_uri
        if discipline_uri:
            args["discipline"] = discipline_uri
        if educational_context_uri:
            args["educationalContext"] = educational_context_uri
        try:
            raw = await call_mcp_tool("search_wlo_content", args)
        except Exception as e:  # pragma: no cover
            logger.warning("search_wlo_content (type-focus) failed: %s", e)
            return []
        cards = parse_wlo_cards(raw) or []
        logger.info("fetch_card_pool kind=type-focus → %d cards", len(cards))
        return cards

    # ── intent_kind == "general" (Default) ────────────────────────────
    # Pool wird auf 3 Tools verteilt. Wir nehmen je ein Drittel + 1 Sicher-
    # heits-Spielraum (ungerade Aufteilungen runden hoch).
    per_tool = max(3, (effective_pool + 2) // 3)
    base_args: dict[str, Any] = {"query": query or "", "maxResults": per_tool}
    if discipline_uri:
        base_args["discipline"] = discipline_uri
    if educational_context_uri:
        base_args["educationalContext"] = educational_context_uri

    async def _call(tool_name: str, args: dict[str, Any]) -> str:
        try:
            return await call_mcp_tool(tool_name, args)
        except Exception as e:  # pragma: no cover
            logger.warning("%s failed: %s", tool_name, e)
            return ""

    raw_tp, raw_col, raw_con = await asyncio.gather(
        _call("search_wlo_topic_pages", dict(base_args)),
        _call("search_wlo_collections", dict(base_args)),
        _call("search_wlo_content", dict(base_args)),
    )

    cards_tp = parse_wlo_topic_page_cards(raw_tp) or []
    cards_col = parse_wlo_cards(raw_col) or []
    cards_con = parse_wlo_cards(raw_con) or []

    logger.info(
        "fetch_card_pool kind=general → tp=%d col=%d con=%d",
        len(cards_tp), len(cards_col), len(cards_con),
    )

    # Themenseiten zuerst, dann Sammlungen, dann Einzelinhalte. Normalisierung
    # (inkl. node_type-Inferenz + Dedup) macht der Caller.
    return [*cards_tp, *cards_col, *cards_con]


def _infer_node_type(card: dict[str, Any]) -> NodeType:
    """Drei-Wege-Mapping aus den vorhandenen Card-Feldern.

    * ``topic_pages``-Liste nicht-leer → ``"topic_page"``
    * ``node_type == "collection"`` → ``"collection"``
    * Sonst → ``"content"``

    Die Eingabe-Cards aus dem MCP haben heute nur 2 Werte ("collection" /
    "content") plus ein topic_pages-Subfield. Wir kollabieren das hier in
    einen einzigen Drei-Wege-Wert, damit Phase 3 und Phase 4 nicht beide
    den topic_pages-Check duplizieren müssen.
    """
    if isinstance(card.get("topic_pages"), list) and card.get("topic_pages"):
        return "topic_page"
    if card.get("node_type") == "collection":
        return "collection"
    return "content"


def _rewrite_card_urls(card: dict[str, Any], target_repo: str) -> None:
    """In-place: alle URL-Felder einer Card durch den bidirektionalen
    Host-Rewrite schicken.

    Die Felder sind sowohl die externen Links (``url``, ``content_url``,
    ``download_url``, ``preview_url``) als auch der in-repo Permalink
    ``wlo_url``. Topic-Page-URLs (``topic_page_url``, sowie pro Variante in
    ``topic_pages``) zeigen meist auf wirlernenonline.de — sie würden vom
    Rewrite ohnehin nicht angefasst (Host nicht in ``known_repo_hosts``).
    """
    for f in ("url", "content_url", "preview_url", "download_url", "wlo_url"):
        v = card.get(f)
        if v:
            card[f] = rewrite_repo_host_v2(v, target_repo)

    # Variante-URLs in topic_pages: rewrite falls jemand sie auf einen
    # Repo-Host geknüpft hat (unüblich, aber defensiv).
    tps = card.get("topic_pages")
    if isinstance(tps, list):
        for tp in tps:
            if isinstance(tp, dict) and tp.get("url"):
                tp["url"] = rewrite_repo_host_v2(tp["url"], target_repo)


def normalize_cards(
    cards: list[dict[str, Any]],
    *,
    target_repo_base: str | None = None,
    intent_kind: IntentKind = "general",
) -> list[dict[str, Any]]:
    """Normalisierungs-Phase: bringt jede Card durch eine deterministische
    Bereinigung.

    Schritte (Reihenfolge wichtig):
      1. Host-Rewrite (bidirektional, über ``known_repo_hosts``).
      2. ``node_type``-Normalisierung auf drei kanonische Werte
         (``topic_page`` / ``collection`` / ``content``).
      3. Dedup per ``node_id`` (erstes Vorkommen gewinnt).
      4. Sortierung nach Standard-Priorität (nur für ``"general"``-Intent;
         bei ``"type-focus"`` / ``"collection-contents"`` bleibt die
         MCP-Reihenfolge erhalten).

    Args:
        cards: Roh-Cards aus :func:`fetch_card_pool` (oder einer anderen
            Quelle, solange das Card-Dict-Schema passt).
        target_repo_base: Override für den Repo-Base-URL. Default:
            ``get_repo_base_url()``.
        intent_kind: Steuert nur die Sortierung in Schritt 4.

    Returns:
        Neue Card-Liste (in-place mutiert die Dicts, aber NICHT die
        Original-Liste — vorhersehbarer für Caller).
    """
    if not cards:
        return []

    target_repo = (target_repo_base or get_repo_base_url()).rstrip("/")

    # Schritt 1 + 2: Rewrite + node_type-Inferenz. In-place auf den Dicts,
    # weil die Eingabe-Cards eh frisch geparsed sind und nicht weiterleben.
    for c in cards:
        if not isinstance(c, dict):
            continue
        _rewrite_card_urls(c, target_repo)
        c["node_type"] = _infer_node_type(c)

    # Schritt 3: Dedup per node_id. Cards ohne node_id (defensiv) bleiben
    # alle erhalten — ohne ID können wir nicht entscheiden, ob's Duplikate
    # sind.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        nid = str(c.get("node_id") or "").strip()
        if nid:
            if nid in seen:
                continue
            seen.add(nid)
        deduped.append(c)

    # Schritt 4: Sortierung. Stabil (Python sort), damit innerhalb einer
    # node_type-Gruppe die MCP-Trefferreihenfolge erhalten bleibt.
    if intent_kind == "general":
        deduped.sort(
            key=lambda c: _NODE_TYPE_PRIORITY.get(c.get("node_type", "content"), 99)
        )

    logger.info(
        "normalize_cards: in=%d out=%d intent=%s repo=%s",
        len(cards), len(deduped), intent_kind, target_repo,
    )
    return deduped


# ══════════════════════════════════════════════════════════════════════════
# Phase 3b — URL-Resolution
# ══════════════════════════════════════════════════════════════════════════
#
# Eine einzige Funktion (:func:`build_card_link`) baut für jede Card den
# definitiven Link. Ihre Lookup-Tabelle:
#
#   card.node_type   Normal-Modus                       Lotsen-Modus
#   ──────────────   ────────────────────────────────   ──────────────────
#   topic_page       card['topic_page_url']             card['topic_page_url']
#                    (extern, kuratiert)                 (extern, kuratiert)
#   collection       {repo}/components/collections      {repo}/components/collections
#                    ?id={uuid}&q={query}               ?id={uuid}&q={query}
#   content          card['url'] (extern bevorzugt)     {repo}/components/render/{uuid}
#                    oder Repo-render als Fallback      (immer im Repo)
#
# Damit:
#   * Themenseiten + Sammlungen: identische Ziele in beiden Modi (kuratiert
#     bzw. Browse-Ansicht der Sammlung — der User sieht direkt den Inhalt).
#   * Einzelinhalte: Normal-Modus folgt dem externen Link wenn vorhanden,
#     Lotsen-Modus zwingt ins Repo (wo der User im WLO-Ökosystem bleibt).
#   * Der ``&q=``-Query-Param auf Sammlungs-Links sorgt für besseren Browse-
#     Kontext (User landet direkt im gefilterten Inhalt der Sammlung).
#
# Ersetzt komplett (sobald die Integration in Phase 4 fertig ist):
#   guide_mode_service.pick_guide_url
#   guide_mode_service._rewrite_collection_render_to_browse
#   chat._inline_card_url (lokale Helper)


def _is_render_uuid(value: str) -> bool:
    """True, wenn ``value`` ein 8-4-4-4-12 UUID-Hex-String ist (das Format
    von edu-sharing-Node-IDs)."""
    if not isinstance(value, str) or len(value) != 36:
        return False
    parts = value.split("-")
    if len(parts) != 5 or [len(p) for p in parts] != [8, 4, 4, 4, 12]:
        return False
    return all(c in "0123456789abcdefABCDEF" for p in parts for c in p)


def _repo_render_url(node_id: str, repo_base: str) -> str:
    """``{repo}/edu-sharing/components/render/{uuid}`` — Permalink eines
    Nodes innerhalb der edu-sharing-Instanz."""
    return f"{repo_base.rstrip('/')}/edu-sharing/components/render/{node_id}"


def _repo_collection_browse_url(
    node_id: str, repo_base: str, search_query: str = "",
) -> str:
    """``{repo}/edu-sharing/components/collections?id={uuid}[&q=…]`` —
    Browse-Ansicht einer Sammlung (zeigt direkt die enthaltenen Materialien
    statt der Metadaten-Detailseite).

    ``search_query`` wird als ``&q=``-Parameter angehängt, wenn nicht leer.
    Damit landet der User in der gefilterten Browse-Ansicht — passend, weil
    der Bot ja gerade nach genau diesem Begriff gesucht hat.
    """
    base = f"{repo_base.rstrip('/')}/edu-sharing/components/collections?id={node_id}"
    if search_query:
        # ``quote`` mit ``safe=""`` codiert auch Leerzeichen → ``%20`` (nicht
        # ``+``, das ist nur in application/x-www-form-urlencoded gültig).
        # edu-sharing's collections-View versteht beides, aber %20 ist sauberer.
        base += f"&q={quote(search_query, safe='')}"
    return base


def _card_as_dict(card: Any) -> dict[str, Any] | None:
    """Zieht ein Card-Dict aus dict | Pydantic-Model | beliebigem Objekt.

    Returns None wenn nichts greifbares dabei ist — Caller können dann
    defensiv aufhören.
    """
    if isinstance(card, dict):
        return card
    if card is None:
        return None
    # Pydantic V2: model_dump()
    md = getattr(card, "model_dump", None)
    if callable(md):
        try:
            return md()
        except Exception:
            pass
    # Pydantic V1: dict()-Methode oder __dict__-Attribut
    d = getattr(card, "dict", None)
    if callable(d):
        try:
            return d()
        except Exception:
            pass
    # Letzter Versuch: __dict__ (für normale Klassen)
    raw = getattr(card, "__dict__", None)
    if isinstance(raw, dict):
        return dict(raw)
    return None


def build_card_link(
    card: Any,
    *,
    guide_mode: bool = False,
    repo_base: str | None = None,
    search_query: str = "",
) -> str:
    """Single Source of Truth für die Card-URL.

    Liest aus der Card den ``node_type`` (vorher von :func:`normalize_cards`
    gesetzt) und liefert nach Lookup-Tabelle den Link. Es gibt kein Fallback
    auf "irgendein URL-Feld" mehr — wenn ein Feld fehlt, das die Tabelle
    erwartet, fallen wir auf den Repo-Link zurück (immer noch besser als
    eine leere Card).

    Args:
        card: Card-Dict ODER Pydantic-Model (z.B. ``WloCard``), idealerweise
            schon durch :func:`normalize_cards` gegangen.
        guide_mode: True wenn der User im Lotsen-Modus ist (Repo-Links für
            Einzelinhalte; Themenseiten + Sammlungen verhalten sich gleich).
        repo_base: Override für die Repo-Base-URL. Default:
            ``get_repo_base_url()``.
        search_query: Optional. Wird an Sammlungs-Browse-URLs als ``&q=``
            angehängt für besseren Browse-Kontext.

    Returns:
        Vollständige URL (https://…). Leerer String nur, wenn die Card
        weder ``node_id`` noch ``url`` hat (sollte praktisch nie passieren —
        ein normalisierter Pool enthält keine solche Cards).
    """
    card = _card_as_dict(card)
    if not isinstance(card, dict):
        return ""
    repo = (repo_base or get_repo_base_url()).rstrip("/")
    node_id = str(card.get("node_id") or "").strip()
    # node_type-Inferenz: vertraue dem von normalize_cards gesetzten Wert,
    # fall back auf Inferenz wenn die Card aus einem alten Pfad kommt.
    nt = card.get("node_type")
    if nt not in ("topic_page", "collection", "content"):
        nt = _infer_node_type(card)

    # ── Themenseiten ───────────────────────────────────────────────────
    if nt == "topic_page":
        tp_url = str(card.get("topic_page_url") or "").strip()
        if tp_url:
            return tp_url
        # Fallback: die Card hat zwar node_type=topic_page (also topic_pages
        # befüllt), aber kein topic_page_url-Feld. Nimm die erste Variante.
        for tp in card.get("topic_pages") or []:
            if isinstance(tp, dict):
                u = str(tp.get("url") or "").strip()
                if u:
                    return u
        # Letzter Fallback: Browse-Ansicht der Sammlung (= Themenseite ohne
        # kuratierten Link ist semantisch eine Sammlung).
        if node_id:
            return _repo_collection_browse_url(node_id, repo, search_query)
        return ""

    # ── Sammlungen ─────────────────────────────────────────────────────
    if nt == "collection":
        if node_id:
            return _repo_collection_browse_url(node_id, repo, search_query)
        # Keine node_id → defensiv: nimm ein vorhandenes URL-Feld.
        for f in ("wlo_url", "url", "content_url", "preview_url"):
            v = str(card.get(f) or "").strip()
            if v:
                return v
        return ""

    # ── Einzelinhalte ──────────────────────────────────────────────────
    # Normal-Modus: bevorzugt den externen Link (card.url, falls extern).
    # Lotsen-Modus: zwingt zum Repo-Render-Link (User bleibt im WLO-Tab).
    if guide_mode:
        if node_id:
            return _repo_render_url(node_id, repo)
        # Fallback: irgendein Repo-URL-Feld
        for f in ("wlo_url", "content_url", "preview_url"):
            v = str(card.get(f) or "").strip()
            if v:
                return v
        return ""

    # Normal-Modus content: externes URL bevorzugt
    ext = str(card.get("url") or "").strip()
    if ext:
        # Ist es bereits ein Repo-Render-Link? Dann ist das technisch in
        # Ordnung, aber wenn ein externer Provider-Link existiert, hätten
        # wir den genommen. card['url'] kommt vom MCP normalerweise als
        # externer Link (ccm:wwwurl) für Content-Nodes, also nehmen wir
        # ihn direkt.
        return ext
    # Kein externer Link → Repo-Render als sinnvoller Default
    if node_id:
        return _repo_render_url(node_id, repo)
    return ""


def _host_of(url: str) -> str:
    """Lowercased hostname ohne Port + ohne ``www.``-Präfix, oder Empty
    bei Parse-Fehler."""
    if not isinstance(url, str) or not url:
        return ""
    try:
        h = (urlparse(url.strip()).hostname or "").strip().lower()
    except Exception:
        return ""
    if ":" in h:
        h = h.split(":", 1)[0]
    if h.startswith("www."):
        h = h[4:]
    return h


def _host_matches_pattern(host: str, pattern: str) -> bool:
    """True wenn ``host`` exakt oder als Subdomain-Wildcard auf
    ``pattern`` passt (gleiche Semantik wie guide_mode_service)."""
    if not host or not pattern:
        return False
    p = pattern.strip().lower()
    if p.startswith("*."):
        suffix = p[1:]  # ".example.com"
        return host.endswith(suffix) and host != p[2:]
    return host == p


def validate_card_link(
    link: str,
    *,
    allowed_hosts: list[str] | None = None,
) -> bool:
    """True, wenn ``link`` eine wohlgeformte http(s)-URL ist und ihr Host
    in der Allow-Liste steht.

    Wenn ``allowed_hosts`` nicht übergeben wird, ziehen wir die Liste aus
    der bestehenden ``guide-mode.yaml`` (über
    :func:`guide_mode_service.host_is_allowed`) — so bleibt Phase 3b
    rückwärts-kompatibel mit der heutigen Allow-Liste, ohne sie zu
    duplizieren. Eine eigene Allow-Liste in ``card-pipeline.yaml`` können
    wir später ergänzen, sobald wir sie wirklich brauchen.
    """
    if not isinstance(link, str) or not link:
        return False
    try:
        parsed = urlparse(link.strip())
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = _host_of(link)
    if not host:
        return False
    if allowed_hosts is None:
        # Fallback auf die guide-mode.yaml-Allow-Liste — wird auch im
        # Lotsen-Modus für die Frontend-Auswahl genutzt.
        from app.services.guide_mode_service import host_is_allowed
        return host_is_allowed(host)
    for pattern in allowed_hosts:
        if _host_matches_pattern(host, pattern):
            return True
    return False


def _set_link_field(card: Any, link: str) -> None:
    """Setzt ``link`` auf einer Card — egal ob Dict oder Pydantic-Model.

    Bei Pydantic-Models nutzen wir ``setattr``; das funktioniert nur, wenn
    ``link`` im Schema definiert ist (für ``WloCard`` ist das der Fall seit
    Phase 4a). Wenn nicht, fangen wir die Exception und loggen — dann ist
    ``card.link`` weiterhin der Default-Wert aus dem Schema.
    """
    if isinstance(card, dict):
        card["link"] = link
        return
    try:
        setattr(card, "link", link)
    except (AttributeError, ValueError) as e:
        logger.debug(
            "annotate_cards_with_link: setattr(link) failed for %s: %s",
            type(card).__name__, e,
        )


def _get_node_id(card: Any) -> str:
    """Hole ``node_id`` aus dict oder Pydantic-Model."""
    if isinstance(card, dict):
        return str(card.get("node_id") or "").strip()
    return str(getattr(card, "node_id", "") or "").strip()


def annotate_cards_with_link(
    cards: list[Any],
    *,
    guide_mode: bool = False,
    repo_base: str | None = None,
    search_query: str = "",
    require_allowed: bool = False,
    allowed_hosts: list[str] | None = None,
) -> list[Any]:
    """Schreibt für jede Card das ``link``-Feld via :func:`build_card_link`.

    Robust gegen beide Card-Typen — Dict und Pydantic-Model. Der Caller
    bekommt die gleiche Liste zurück, jede Card hat jetzt das ``link``-Feld.

    Wenn ``require_allowed=True`` und der gebaute Link nicht durch
    :func:`validate_card_link` kommt, wird auf den Repo-Render-Link
    zurückgefallen (immer noch ein gültiges Ziel, weil unser eigener Host).

    Args:
        cards: Liste von Card-Dicts oder Pydantic-Models (Mischbar).
        guide_mode: An build_card_link weitergereicht.
        repo_base: Override für Repo-URL.
        search_query: Wird an Sammlungs-Browse-Links angehängt.
        require_allowed: Wenn True, wird Validation gegen die Allow-Liste
            gemacht; Cards mit nicht-allow-listed Link bekommen den
            Repo-Render-Fallback.
        allowed_hosts: Optional. Wenn None und require_allowed=True,
            wird die Liste aus guide-mode.yaml gezogen.

    Returns:
        Die gleiche Liste, jede Card hat jetzt das ``link``-Feld gesetzt.
    """
    repo = (repo_base or get_repo_base_url()).rstrip("/")
    for c in cards or []:
        link = build_card_link(
            c, guide_mode=guide_mode, repo_base=repo, search_query=search_query,
        )
        if require_allowed and link and not validate_card_link(
            link, allowed_hosts=allowed_hosts,
        ):
            nid = _get_node_id(c)
            if nid:
                fallback = _repo_render_url(nid, repo)
                logger.debug(
                    "annotate_cards_with_link: link %r not allow-listed -> "
                    "fallback to repo-render %r",
                    link, fallback,
                )
                link = fallback
            else:
                logger.debug(
                    "annotate_cards_with_link: link %r not allow-listed and "
                    "card has no node_id - leaving link empty.",
                    link,
                )
                link = ""
        _set_link_field(c, link)
        # Welle C Sprint 6 Hotfix — Lotsen-URL-Konsistenz auf card.url.
        #
        # User-Bug-Report: Im Event-Inspector und in einigen Frontend-Pfaden
        # (z.B. canvas.component.html: ``c.url || c.wlo_url``,
        # card-utils.getCardPrimaryUrl-Fallback) wird ``card.url`` ausgelesen
        # — und das ist im Lotsen-Modus die externe Provider-URL (youtube.com
        # etc.). Das untergräbt die "in derselben Tab bleiben"-Garantie des
        # Lotsen-Modus.
        #
        # Fix: Im Lotsen-Modus auch ``card.url`` mit dem (gerade berechneten)
        # Repo-Link überschreiben, sobald wir einen Repo-Link haben. So zeigen
        # ALLE Frontend-URL-Pfade (link / url / wlo_url / guide_url) im
        # Lotsen-Modus aufs Repo. Im Normal-Modus bleibt ``card.url``
        # unverändert — dort soll der User absichtlich extern springen.
        if guide_mode and link:
            try:
                if isinstance(c, dict):
                    if c.get("url") and c["url"] != link:
                        c["url"] = link
                else:
                    if getattr(c, "url", "") and getattr(c, "url", "") != link:
                        setattr(c, "url", link)
            except (AttributeError, ValueError):
                pass  # Defensiv — niemals den Annotations-Lauf wegen url-Override brechen
    return cards


# ══════════════════════════════════════════════════════════════════════════
# Phase 3a — Final-Auswahl (deterministisch + optionaler LLM-Re-Rank)
# ══════════════════════════════════════════════════════════════════════════
#
# Strategie:
#
#   1. Pool kommt schon sortiert aus :func:`normalize_cards` (bei
#      ``intent_kind="general"``: topic_page > collection > content).
#   2. Bei ``intent_kind="type-focus"``: vorab strikt auf Cards filtern, die
#      sowohl ``node_type == "content"`` als auch matching
#      ``learning_resource_types`` haben. Sammlungen + Themenseiten raus,
#      weil der User explizit Einzelinhalte will.
#   3. Bei ``intent_kind="general"`` mit deterministischer Auswahl:
#      Mix-Strategie 1+1+3 (1 Themenseite, falls vorhanden + 1 Sammlung,
#      falls vorhanden + 3 Einzelinhalte). Wenn ein Slot leer bleibt, wird
#      er mit Cards der nächsten Prio aufgefüllt.
#   4. Optional: ``selected_node_ids`` aus LLM-Re-Rank überschreiben die
#      Reihenfolge.
#   5. Auffüllen bis ``min_displayed`` aus deterministischer Mix-Reihe.
#   6. Schneiden auf ``final_size``.
#
# Das LLM kann **nur re-ordnen und filtern**, nicht hinzufügen — der Pool
# ist die ground truth. Damit ist die "LLM hat zu wenig gewählt → Backend
# füllt auf"-Logik nicht mehr nötig: wir füllen einfach aus dem Pool, der
# eh schon Sek vorhanden ist.


# ── Relevance-Sortierung (Phase 3a Erweiterung) ────────────────────────
#
# Beobachtung aus Live-Test: bei query="Material zu Bruchrechnung" liefert
# search_wlo_collections als ersten Treffer manchmal "Politische Bildung"
# (irgendeine generische Sammlung). v1 löste das durch LLM-Text-Auswahl;
# v2 nimmt deterministisch die erste — daher Off-Topic.
#
# Mitigation: ein leichter Relevance-Score, der Cards mit Query-Match im
# Titel/Description/Keywords nach oben sortiert (innerhalb ihrer
# node_type-Gruppe). Cards ohne Match bleiben in MCP-Reihenfolge dahinter.

# Deutsche Stopwörter — Cards für "Material zu Photosynthese" sollen nicht
# auf "Material"/"zu" matchen.
_RELEVANCE_STOPWORDS = frozenset({
    "der", "die", "das", "den", "dem", "des",
    "ein", "eine", "einen", "einer", "einem", "eines",
    "zu", "zur", "zum", "im", "in", "an", "am", "auf", "mit", "und",
    "oder", "aber", "wie", "was", "wer", "wo", "wann", "wieso", "warum",
    "ist", "sind", "war", "waren", "sein", "haben", "hat", "wird", "werden",
    "kann", "können", "soll", "sollen", "muss", "müssen", "will", "wollen",
    "material", "materialien", "inhalt", "inhalte", "thema", "themen",
    "zeig", "zeige", "such", "suche", "find", "finde", "gib", "ich", "mir",
    "du", "wir", "ihr", "sie", "es",
})


def _tokenize_query(query: str) -> set[str]:
    """Liefert lowercase-Token aus ``query``, minus Stopwörter.

    Splittet an Whitespace + Satzzeichen, hält nur Tokens mit 2+ Zeichen.
    Wird im Hot-Path aufgerufen, deshalb bewusst simpel statt NLP-Library.
    """
    if not query:
        return set()
    import re as _re
    tokens = _re.findall(r"[\wäöüÄÖÜß]+", query.lower(), _re.UNICODE)
    return {
        t for t in tokens
        if len(t) >= 2 and t not in _RELEVANCE_STOPWORDS
    }


def _relevance_score(card: dict[str, Any], query_tokens: set[str]) -> float:
    """Heuristischer Relevance-Score: Match-Häufigkeit in Title/Description/
    Keywords/Disciplines.

    Score ist 0.0 wenn keiner der Query-Token irgendwo vorkommt — solche
    Cards bleiben am Ende ihrer Gruppe.

    Gewichtung:
      * Titel-Match:        2.0 pro Token (stärkstes Signal)
      * Keywords-Match:     1.0 pro Token
      * Disciplines-Match:  0.5 pro Token
      * Description-Match:  0.3 pro Token

    Multi-Token-Queries summieren sich auf — "Eiszeit Geographie" matcht
    auf "Eiszeit (Geographie)" → 4.0 (zwei Titel-Matches).
    """
    if not query_tokens or not isinstance(card, dict):
        return 0.0
    score = 0.0
    title = (card.get("title") or "").lower()
    desc = (card.get("description") or "").lower()
    keywords = " ".join(str(k) for k in (card.get("keywords") or [])).lower()
    disciplines = " ".join(str(d) for d in (card.get("disciplines") or [])).lower()
    for tok in query_tokens:
        if tok in title:
            score += 2.0
        if tok in keywords:
            score += 1.0
        if tok in disciplines:
            score += 0.5
        if tok in desc:
            score += 0.3
    return score


def _sort_by_relevance(
    cards: list[dict[str, Any]],
    query_tokens: set[str],
) -> list[dict[str, Any]]:
    """Stabile Sortierung absteigend nach :func:`_relevance_score`.

    Innerhalb gleichen Scores bleibt die Original-Reihenfolge erhalten
    (Python sort ist stable) — d.h. wenn der Score 0 ist (keine Query-
    Tokens oder kein Match), kommt die MCP-Original-Reihenfolge raus.
    """
    if not query_tokens or not cards:
        return list(cards)
    return sorted(
        cards,
        key=lambda c: _relevance_score(c, query_tokens),
        reverse=True,
    )


def _filter_to_wanted_content_types(
    cards: list[dict[str, Any]],
    wanted: set[str],
) -> list[dict[str, Any]]:
    """Behält nur Cards mit ``node_type == "content"`` UND mindestens einem
    matching Eintrag in ``learning_resource_types`` (Substring-Match
    case-insensitive auf der konkatenierten LRT-Liste).

    Sammlungen + Themenseiten werden bei aktivem Type-Fokus rausgefiltert,
    weil der User-Intent eindeutig auf Einzelinhalte zielt.
    """
    if not wanted:
        return list(cards)
    out: list[dict[str, Any]] = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        if c.get("node_type") != "content":
            continue
        lrt = c.get("learning_resource_types") or []
        blob = " ".join(str(t).lower() for t in lrt if t)
        if any(w in blob for w in wanted):
            out.append(c)
    return out


def _deterministic_mix(
    cards: list[dict[str, Any]],
    target_size: int,
    query_tokens: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Mix-Strategie für ``intent_kind="general"``:

      * 1 Themenseite (falls verfügbar)
      * 1 Sammlung (falls verfügbar)
      * Rest mit Einzelinhalten auffüllen
      * Wenn ein Slot leer bleibt, mit Cards aus den anderen Pools
        weitergefüllt (Prio: content > collection > topic_page für die
        Resterampe).

    Wenn ``query_tokens`` übergeben wird, werden Cards **innerhalb** jeder
    Type-Gruppe nach Relevance-Score absteigend sortiert (Title/Keywords/
    Disciplines/Description-Match). Bei Score 0 oder fehlenden Tokens
    bleibt die MCP-Original-Reihenfolge erhalten (stable sort).
    """
    if not cards or target_size <= 0:
        return []

    by_type: dict[str, list[dict[str, Any]]] = {
        "topic_page": [], "collection": [], "content": [],
    }
    for c in cards:
        nt = c.get("node_type")
        if nt in by_type:
            by_type[nt].append(c)

    # Wenn Query-Tokens gegeben: erst nach Relevance sortieren, dann
    # Score-0-Cards aus jeder Gruppe entfernen — ABER nur, wenn mindestens
    # EINE Gruppe relevante Cards hat. Wenn alle Pools komplett irrelevant
    # sind (vage Query oder Stopwort-only), behalten wir alle Cards in
    # MCP-Reihenfolge — sonst bekommt der User leere Hände.
    #
    # Beispiel: Query "Material zu Bruchrechnung" → query_tokens={"bruchrechnung"}.
    # Pool hat 7 Sammlungen, davon 0 mit "Bruchrechnung" im Titel.
    # Pool hat 7 Inhalte, davon 4 mit "Bruchrechnung"-Match.
    # → Sammlungs-Gruppe wird auf [] gefiltert (keine relevante Sammlung)
    # → Inhalts-Gruppe wird auf 4 gefiltert
    # → Mix nimmt 0 Sammlungen, 5 Inhalte (aus 4 + 1 Auffüller? Nein —
    #    Auffüllung passiert nur OHNE Filter, also bleiben 4 relevante).
    if query_tokens:
        for key in by_type:
            by_type[key] = _sort_by_relevance(by_type[key], query_tokens)
        any_relevant = any(
            _relevance_score(c, query_tokens) > 0
            for cards_in_group in by_type.values()
            for c in cards_in_group
        )
        if any_relevant:
            for key in by_type:
                by_type[key] = [
                    c for c in by_type[key]
                    if _relevance_score(c, query_tokens) > 0
                ]
            logger.info(
                "_deterministic_mix: relevance-filtered pools tp=%d col=%d con=%d "
                "(query_tokens=%s)",
                len(by_type["topic_page"]), len(by_type["collection"]),
                len(by_type["content"]), sorted(query_tokens),
            )

    out: list[dict[str, Any]] = []

    # Slot 1: 1× Themenseite
    if by_type["topic_page"]:
        out.append(by_type["topic_page"].pop(0))

    # Slot 2: 1× Sammlung
    if len(out) < target_size and by_type["collection"]:
        out.append(by_type["collection"].pop(0))

    # Restplätze: erstmal mit Einzelinhalten auffüllen
    while len(out) < target_size and by_type["content"]:
        out.append(by_type["content"].pop(0))

    # Wenn noch Plätze offen: rest aus Sammlungen, dann Themenseiten.
    # Sammlungen-Prio höher, weil sie ein zusammenhängendes Materialset
    # darstellen — bei knappem Pool sinnvoller als "noch eine Themenseite".
    while len(out) < target_size and by_type["collection"]:
        out.append(by_type["collection"].pop(0))
    while len(out) < target_size and by_type["topic_page"]:
        out.append(by_type["topic_page"].pop(0))

    return out


def _select_by_ids(
    cards: list[dict[str, Any]],
    selected_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Splittet ``cards`` in zwei Listen:
      * ``picked``: Cards, deren ``node_id`` in ``selected_ids`` steht, in
        der vom LLM angegebenen Reihenfolge.
      * ``rest``: alle anderen Pool-Cards, in der Pool-Reihenfolge.

    IDs aus ``selected_ids``, zu denen keine Card im Pool passt, werden
    ignoriert (LLM kann halluzinieren).
    """
    if not selected_ids:
        return [], list(cards)
    by_id: dict[str, dict[str, Any]] = {}
    for c in cards:
        nid = str(c.get("node_id") or "").strip()
        if nid:
            by_id[nid] = c
    picked: list[dict[str, Any]] = []
    seen_picked: set[str] = set()
    for sid in selected_ids:
        s = str(sid or "").strip()
        if not s or s in seen_picked:
            continue
        if s in by_id:
            picked.append(by_id[s])
            seen_picked.add(s)
    rest = [c for c in cards
            if str(c.get("node_id") or "").strip() not in seen_picked]
    return picked, rest


def select_final_cards(
    pool: list[dict[str, Any]],
    *,
    intent_kind: IntentKind,
    final_size: int | None = None,
    min_displayed: int | None = None,
    wanted_content_types: set[str] | None = None,
    selected_node_ids: list[str] | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Final-Auswahl-Pipeline (Phase 3a).

    Args:
        pool: Normalisierter Card-Pool (idealerweise aus :func:`fetch_card_pool`
            + :func:`normalize_cards`).
        intent_kind: ``"general"`` / ``"type-focus"`` / ``"collection-contents"``.
        final_size: Wie viele Cards zurückgeben. Default: aus
            ``card-pipeline.yaml``.
        min_displayed: Mindest-Anzahl. Wenn die LLM-Auswahl weniger liefert,
            wird mit deterministischer Auswahl aufgefüllt. Default aus YAML.
        wanted_content_types: Bei ``intent_kind="type-focus"`` Pflicht —
            die Pool-Cards werden vor der Auswahl strikt darauf gefiltert.
        selected_node_ids: Optionale LLM-Output. Cards mit diesen IDs werden
            in genau dieser Reihenfolge vorgereiht. IDs ohne matching Pool-
            Card werden ignoriert.
        query: Optional. Die User-Anfrage, aus der Relevance-Tokens gebildet
            werden. Cards mit Query-Match im Title/Keywords/Description
            werden nach oben sortiert (innerhalb ihrer Type-Gruppe bei
            general, gesamt bei type-focus). Bei ``None`` oder leerer Query
            bleibt die MCP-Reihenfolge erhalten.

    Returns:
        Liste von genau ``min(final_size, len(verfügbar))`` Cards.
    """
    cfg = load_card_pipeline_config()
    eff_final = final_size if final_size is not None else cfg["final_selection_size"]
    eff_min = min_displayed if min_displayed is not None else cfg["min_displayed_cards"]
    eff_min = min(eff_min, eff_final)

    if not pool:
        return []

    # Relevance-Tokens nur einmal pro Anruf berechnen.
    q_tokens = _tokenize_query(query or "")

    # Schritt 1: Bei type-focus strikt filtern.
    working: list[dict[str, Any]] = list(pool)
    if intent_kind == "type-focus" and wanted_content_types:
        before = len(working)
        working = _filter_to_wanted_content_types(working, wanted_content_types)
        logger.info(
            "select_final_cards type-focus filter: %d → %d (wanted=%s)",
            before, len(working), sorted(wanted_content_types),
        )

    # Schritt 2: Deterministische Reihenfolge — bei "general" Mix mit
    # innerhalb-der-Gruppe-Relevance-Sort, sonst gesamt-Relevance.
    # Bei "collection-contents" KEINE Relevance-Sortierung — die Sammlung
    # ist eine kuratierte Reihenfolge, die wollen wir nicht umstellen.
    if intent_kind == "general":
        det_order = _deterministic_mix(working, eff_final * 2, query_tokens=q_tokens)
    elif intent_kind == "type-focus":
        det_order = _sort_by_relevance(working, q_tokens)
    else:
        det_order = list(working)

    # Schritt 3: LLM-Re-Rank (wenn angegeben) — picked cards vorne, rest
    # aus der deterministischen Ordnung dahinter.
    if selected_node_ids:
        picked, _rest = _select_by_ids(working, selected_node_ids)
        # Auffüllen aus der deterministischen Ordnung (det_order), ohne
        # Duplikate.
        seen_ids = {str(c.get("node_id") or "").strip() for c in picked}
        seen_ids.discard("")
        ordered: list[dict[str, Any]] = list(picked)
        for c in det_order:
            nid = str(c.get("node_id") or "").strip()
            if nid and nid in seen_ids:
                continue
            ordered.append(c)
            if nid:
                seen_ids.add(nid)
    else:
        ordered = det_order

    # Schritt 4: Auf final_size schneiden, aber sicherstellen dass min_displayed
    # erreicht wird (falls Pool reicht).
    target = max(eff_min, 1) if len(ordered) >= eff_min else len(ordered)
    target = min(eff_final, max(target, len(ordered[:eff_final])))
    out = ordered[:target]

    logger.info(
        "select_final_cards: intent=%s pool=%d → %d (final=%d, min=%d, "
        "llm_pick=%s)",
        intent_kind, len(pool), len(out), eff_final, eff_min,
        bool(selected_node_ids),
    )
    return out


# ══════════════════════════════════════════════════════════════════════════
# End-to-End-Wrapper für chat.py-Integration
# ══════════════════════════════════════════════════════════════════════════
#
# :func:`run_pipeline_v2` ist die "alles auf einmal"-Funktion, die der
# Caller (chat.py oder Test-Suite) ansprechen kann, wenn er nicht jeden
# Schritt einzeln steuern will. Sie tut:
#
#   1. fetch_card_pool        (Beschaffung)
#   2. normalize_cards        (Host-Rewrite + node_type + Dedup)
#   3. select_final_cards     (Mix + LLM-Re-Rank)
#   4. annotate_cards_with_link (URL-Resolution → ``card['link']``)
#
# Der Caller bekommt eine fertige Liste von Cards mit ``link``-Feld.
# Solange ``CARD_PIPELINE_V2`` nicht aktiv ist, ruft chat.py das nicht
# produktiv — wir nutzen die Funktion für A/B-Log + Smoke-Tests.


async def run_pipeline_v2(
    *,
    user_message: str,
    guide_mode: bool = False,
    wanted_content_types: set[str] | None = None,
    collection_id: str | None = None,
    learning_resource_type_uri: str | None = None,
    discipline_uri: str | None = None,
    educational_context_uri: str | None = None,
    selected_node_ids: list[str] | None = None,
    repo_base: str | None = None,
    prefetched_pool: list[Any] | None = None,
) -> dict[str, Any]:
    """End-to-End-Lauf der Card-Pipeline v2.

    Wrapper-Funktion, die :func:`fetch_card_pool`, :func:`normalize_cards`,
    :func:`select_final_cards` und :func:`annotate_cards_with_link`
    hintereinander aufruft.

    Args:
        prefetched_pool: Wenn gegeben, wird :func:`fetch_card_pool`
            ÜBERSPRUNGEN und stattdessen dieser bereits beschaffte Pool
            als Eingabe für die Normalisierung benutzt. Genutzt in der
            Migrations-Phase, wo v1's MCP-Calls weiter laufen und v2 als
            reiner Curation-Layer (Normalize + Select + Link) drauf läuft.
            Spart einen kompletten MCP-Roundtrip und garantiert, dass v1
            und v2 auf dem gleichen Pool arbeiten — LLM-Re-Rank funktioniert
            dann konsistent, weil ``selected_node_ids`` aus dem v1-Pool
            im v2-Pool auch existieren.

    Returns:
        Ein Diagnose-Dict mit:
          * ``intent_kind`` — was die Heuristik abgeleitet hat
          * ``pool_size``, ``normalized_size``, ``final_size`` — Counts für
            den A/B-Log
          * ``cards`` — die finale Card-Liste mit ``link``-Feld
    """
    intent_kind = infer_intent_kind(
        user_message=user_message,
        wanted_content_types=wanted_content_types,
        collection_id=collection_id,
    )

    if prefetched_pool is not None:
        # Curation-Modus: Pool kommt vom Caller (v1-Cards). Pydantic-Models
        # in Dicts konvertieren, damit normalize_cards/select_final_cards
        # gleichmäßig arbeiten.
        pool: list[dict[str, Any]] = []
        for c in prefetched_pool:
            if isinstance(c, dict):
                pool.append(c)
            elif hasattr(c, "model_dump"):
                try:
                    pool.append(c.model_dump())
                except Exception:
                    pass
            else:
                try:
                    pool.append(dict(c))  # type: ignore[arg-type]
                except Exception:
                    pass
        logger.info(
            "run_pipeline_v2: using prefetched_pool of %d cards (no MCP fetch)",
            len(pool),
        )
    else:
        pool = await fetch_card_pool(
            query=user_message,
            intent_kind=intent_kind,
            collection_id=collection_id,
            learning_resource_type_uri=learning_resource_type_uri,
            discipline_uri=discipline_uri,
            educational_context_uri=educational_context_uri,
        )
    normalized = normalize_cards(
        pool, target_repo_base=repo_base, intent_kind=intent_kind,
    )
    final = select_final_cards(
        normalized,
        intent_kind=intent_kind,
        wanted_content_types=wanted_content_types,
        selected_node_ids=selected_node_ids,
        query=user_message,
    )
    annotated = annotate_cards_with_link(
        final,
        guide_mode=guide_mode,
        repo_base=repo_base,
        search_query=user_message or "",
        require_allowed=guide_mode,  # Im Lotsen-Modus strikt Allow-Liste
    )

    return {
        "intent_kind": intent_kind,
        "pool_size": len(pool),
        "normalized_size": len(normalized),
        "final_size": len(annotated),
        "cards": annotated,
    }


def summarize_pipeline_result(result: dict[str, Any]) -> str:
    """Eine kompakte, log-freundliche Zusammenfassung des Pipeline-Outputs.

    Format: ``[v2] intent=X pool=N>M>K | TYPE/ID/title-30 | ...``

    Schreibt jede Card als ``TYPE/ID/Titel-gekuerzt-30-Zeichen``. Wird vom
    A/B-Log in chat.py geloggt — leicht grep-bar, gut diff-bar gegen die
    v1-Liste. Bewusst ASCII-only ("``>``" statt Unicode-Pfeil), damit der
    Log auf jedem Stdout sauber landet (Windows-CP1252 inklusive).
    """
    parts: list[str] = []
    for c in result.get("cards") or []:
        nt = str(c.get("node_type") or "")[:3]  # tp/col/con
        nid = str(c.get("node_id") or "")[:8]
        t = str(c.get("title") or "")[:30]
        parts.append(f"{nt}/{nid}/{t}")
    return (
        f"[v2] intent={result.get('intent_kind', '?')} "
        f"pool={result.get('pool_size', 0)}>"
        f"{result.get('normalized_size', 0)}>"
        f"{result.get('final_size', 0)} | "
        + " | ".join(parts)
    )


__all__ = [
    "IntentKind",
    "NodeType",
    "infer_intent_kind",
    "fetch_card_pool",
    "normalize_cards",
    "build_card_link",
    "validate_card_link",
    "annotate_cards_with_link",
    "select_final_cards",
    "run_pipeline_v2",
    "summarize_pipeline_result",
]
