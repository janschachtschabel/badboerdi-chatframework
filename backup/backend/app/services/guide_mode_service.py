"""Webseiten-Guide-Modus — Card-URL-Filter + Allow-List-Checks.

Die Frontend-Component zeigt einen "Bring mich hin"-Button neben jeder
Card, deren ``guide_url`` gesetzt ist. Diese URL wählen wir hier aus —
aus den verschiedenen URL-Feldern, die die WLO-MCP-Tools liefern, mit
einer pro Domain konfigurierten Allow-Liste.

Wichtig: nur Hostnamen aus ``guide-mode.yaml.allowed_hosts`` werden zu
Guide-Zielen. Das verhindert, dass der Bot User auf eine
Drittwebseite (Verlag, Wikipedia, …) navigiert und die User dort vom
Widget abgeschnitten sind.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from app.services.config_loader import load_guide_mode_config

logger = logging.getLogger(__name__)

# Modul-globaler Cache des geladenen Configs. Re-Loaded sich automatisch,
# wenn der Inhalt sich ändert — dafür nutzt _load_yaml's mtime-Check.
# (Kostenlos, weil _load_yaml selbst memoised + invalidiert.)
def _cfg() -> dict[str, Any]:
    return load_guide_mode_config()


def _normalize_host(host: str | None) -> str:
    """Lowercase + drop ``:port`` + remove leading ``www.`` for matching."""
    if not host:
        return ""
    h = host.strip().lower()
    # Drop port if present
    if ":" in h:
        h = h.split(":", 1)[0]
    # Remove leading "www." so the allow-list doesn't have to list both
    if h.startswith("www."):
        h = h[4:]
    return h


def _host_matches_pattern(host: str, pattern: str) -> bool:
    """True if ``host`` matches ``pattern`` (exact OR ``*.example.com``).

    Wildcards match ANY number of leading subdomain components, so
    ``*.openeduhub.net`` matches ``foo.openeduhub.net`` and
    ``a.b.openeduhub.net`` but NOT the bare ``openeduhub.net``. List the
    bare host separately if you want it covered.
    """
    if not host or not pattern:
        return False
    pattern = pattern.strip().lower()
    if pattern.startswith("*."):
        suffix = pattern[1:]  # ".openeduhub.net"
        return host.endswith(suffix) and host != pattern[2:]
    return host == pattern


def host_is_allowed(host: str | None) -> bool:
    """True if ``host`` is on the configured guide-mode allow-list."""
    h = _normalize_host(host)
    if not h:
        return False
    for pattern in _cfg().get("allowed_hosts", []) or []:
        if _host_matches_pattern(h, pattern):
            return True
    return False


def is_guide_eligible_url(url: str | None) -> bool:
    """True if the URL is non-empty and points to an allow-listed host."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return host_is_allowed(parsed.hostname)


# Regex zum Umschreiben von edu-sharing-Render-URLs auf die Sammlungs-
# Browse-Ansicht. Greift host-agnostisch (Staging, Production, beliebige
# edu-sharing-Instanzen) und nur auf den charakteristischen Pfad:
#   https://<host>/edu-sharing/components/render/<uuid>
# wird zu:
#   https://<host>/edu-sharing/components/collections?id=<uuid>
import re as _re_es
_ES_RENDER_RE = _re_es.compile(
    r"^(https?://[^/]+/edu-sharing/components/)render/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(.*)$",
    _re_es.IGNORECASE,
)


def _is_collection_card(card: dict[str, Any]) -> bool:
    """True, wenn die Card eine Sammlung ist (``node_type == "collection"``).

    Greift sowohl für reine Sammlungen als auch für Themenseiten-Cards
    (Sammlungen mit ``topic_pages`` befüllt). Für letztere ist der Rewrite
    trotzdem safe: der ``_ES_RENDER_RE``-Regex matched ausschließlich
    edu-sharing-Render-URLs (``/edu-sharing/components/render/<uuid>``);
    externe Themenseiten-URLs (z.B. ``wirlernenonline.de/themenseite/…``)
    bleiben unverändert.

    Vorher gab's ein ``_is_pure_collection_card`` mit zusätzlicher Pflicht
    ``topic_pages`` leer — das führte dazu, dass Themenseiten-Cards, deren
    ``topic_page_url`` nicht allow-listed war oder fehlte, auf die Render-
    URL zurückfielen und KEIN Rewrite bekamen. Resultat: Inline-Klick
    landete auf der Sammlungs-Detailseite statt im Inhaltsbereich.
    """
    return card.get("node_type") == "collection"


def _rewrite_collection_render_to_browse(url: str) -> str:
    """Sammlungs-Render-URLs (Detail einer Sammlung als Node) auf die
    Sammlungs-Browse-Ansicht umschreiben — dort sieht der User direkt die
    enthaltenen Materialien statt nur die Metadaten der Sammlung selbst.

    Host bleibt unverändert (Production, Staging, eigene edu-sharing-
    Installation funktionieren alle gleich). Non-Render-URLs bleiben
    durchgereicht.
    """
    if not isinstance(url, str):
        return url
    m = _ES_RENDER_RE.match(url)
    if not m:
        return url
    prefix, uuid, suffix = m.group(1), m.group(2), m.group(3)
    return f"{prefix}collections?id={uuid}{suffix}"


def pick_guide_url(card: dict[str, Any] | Any) -> str | None:
    """Pick the first allow-listed URL from a card's URL fields.

    Honours ``url_fields_priority`` from guide-mode.yaml — typically
    ``topic_page_url`` first (because users often want the curated
    themepage rather than the bare collection render), then
    ``wlo_url``/``url``/``content_url``/``preview_url``.

    For topic-page-cards, also checks each entry in ``card['topic_pages']``
    so the persona-preferred variant URL surfaces too.

    **Sammlungs-Spezialfall**: Wenn die Card eine reine Sammlung ist (keine
    Themenseite-Variante), wird die gepickt Render-URL auf die Sammlungs-
    Browse-Ansicht (``/components/collections?id=…``) umgeschrieben — dort
    landet der Lotsen-Klick direkt im Inhaltsbereich der Sammlung statt auf
    deren Metadaten-Detailseite.

    Returns ``None`` when no field has an allow-listed URL.
    """
    if not card:
        return None
    # Allow both dicts and Pydantic model-likes (with ``.model_dump`` or attrs)
    if hasattr(card, "model_dump") and not isinstance(card, dict):
        try:
            card = card.model_dump()
        except Exception:
            pass
    if not isinstance(card, dict):
        try:
            card = dict(card)  # type: ignore[arg-type]
        except Exception:
            return None

    cfg = _cfg()
    priority = cfg.get("url_fields_priority") or [
        "topic_page_url", "wlo_url", "url", "content_url", "preview_url",
    ]

    picked: str | None = None
    for field in priority:
        val = card.get(field)
        if isinstance(val, str) and is_guide_eligible_url(val):
            picked = val
            break

    if picked is None:
        # Topic-page variants — each variant is {variant_id, target_group, label, url}
        for tp in card.get("topic_pages") or []:
            if isinstance(tp, dict):
                url = tp.get("url")
                if isinstance(url, str) and is_guide_eligible_url(url):
                    picked = url
                    break

    if picked is None:
        return None

    # Sammlungs-Cards: Render-URL → Browse-Ansicht umschreiben (siehe
    # oben). Greift host-agnostisch, dadurch funktionieren beliebige
    # edu-sharing-Instanzen (Staging, Production, eigene Hosts).
    # Auch Themenseiten-Cards profitieren: wenn ihre topic_page_url nicht
    # allow-listed war und der Fallback auf wlo_url (= render) griff,
    # wird die Render-URL ebenfalls zur Browse-Ansicht. Externe Themenseiten-
    # URLs (wirlernenonline.de/themenseite/…) bleiben unverändert, weil der
    # Rewrite-Regex nur auf edu-sharing-render-URLs matched.
    if _is_collection_card(card):
        picked = _rewrite_collection_render_to_browse(picked)

    return picked


def annotate_cards_with_guide_url(
    cards: list[Any],
    *,
    enabled: bool,
    host: str | None,
    max_targets: int | None = None,
) -> int:
    """Mutate the first ``max_targets`` cards in-place: set ``guide_url``
    if the user is on an allow-listed host AND the card has an
    eligible target URL.

    No-op when ``enabled`` is false or ``host`` isn't on the allow list.
    Returns the number of cards that received a ``guide_url``.
    """
    if not enabled:
        return 0
    if not host_is_allowed(host):
        return 0
    if not cards:
        return 0
    if max_targets is None:
        # Read from config — but DO NOT coerce 0 to a default (the `or`
        # clause used to do that, which silently turned the documented
        # "0 = unlimited" into a hard cap of 5). Only fall back to 5
        # when the key is missing or non-int.
        raw = _cfg().get("max_guide_targets_per_turn")
        if raw is None:
            max_targets = 5
        else:
            try:
                max_targets = int(raw)
            except (TypeError, ValueError):
                max_targets = 5

    annotated = 0
    for c in cards:
        if max_targets > 0 and annotated >= max_targets:
            break
        url = pick_guide_url(c)
        if not url:
            continue
        # Pydantic model? set via setattr; dict? key assignment.
        try:
            if isinstance(c, dict):
                c["guide_url"] = url
            else:
                setattr(c, "guide_url", url)
            annotated += 1
        except Exception as e:
            logger.debug("guide_url annotation skipped for card: %s", e)
    return annotated
