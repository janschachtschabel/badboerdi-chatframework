"""Webseiten-Tour — geführte Besucherführung (deterministische State Machine).

Reine Logik: Pfad-Normalisierung, Gruppen-Matching, Ankunfts-Advance und
Schritt-Rendering. KEIN DB-/Pydantic-Zugriff — der Aufrufer (``chat.py``)
liest/persistiert ``tour_state`` und baut die ``ChatResponse``. Texte, URLs
und das Gruppe→Angebot-Mapping kommen aus ``01-base/website-tour.yaml``
(Domänwissen, Studio-pflegbar) via ``config_loader.load_website_tour_config``.

Schritt-Reihenfolge (linear):

    intro  →  group  →  group_page  →  content  →  solutions  →  contact
    (Start)   (/home)   (Gruppe)       (Gruppen-   (Bildungs-    (Mitmachen,
                                        seite)       inhalte)      final)

``group`` rückt per Gruppen-Reply vor, alle anderen Schritte per Ankunft
(``tick`` + passender ``page``). Navigation = ``__guide__|Label|URL``-
Quick-Replies (1-Klick "Bring mich hin").

Der Funnel kann MITTEN starten: ``detect_entry(page, cfg)`` bildet das
Flow-Modell (``flows:`` in website-tour.yaml) ab — Zielgruppenseite → direkt
``solutions`` (B1), Produkt-/Angebotsseite → ``solutions`` (C1), /mitmachen/
→ ``contact`` (D1/D2), sonst ``intro``/``group``. Ziel des Funnels ist immer
die Anfrage/Kontakt auf ``contact_hub`` (/mitmachen/).
"""
from __future__ import annotations

import re
from typing import Any

# Magic-Prefix für Navigations-Quick-Replies — identisch zu
# guide_qr_injector.GUIDE_QR_PREFIX, damit das Frontend sie als
# "Bring mich hin"-Buttons rendert.
GUIDE_QR_PREFIX = "__guide__|"

# Lineare Schritt-Reihenfolge (group advanced per Reply, Rest per Ankunft).
STEP_ORDER = ["intro", "group", "group_page", "content", "solutions", "contact"]


# ── Helpers ─────────────────────────────────────────────────────────

def _norm_path(p: str) -> str:
    """Pfad normalisieren für den Ankunfts-Vergleich.

    lowercase, Host/Query/Fragment entfernt, genau ein führender ``/``,
    kein trailing ``/`` (außer Root). So matcht ``/home/`` == ``/home`` ==
    ``https://wp-test…/home/?x=1``.
    """
    s = (p or "").strip()
    s = re.sub(r"^https?://[^/]+", "", s, flags=re.IGNORECASE)
    s = s.split("?", 1)[0].split("#", 1)[0]
    s = s.strip().lower()
    if not s.startswith("/"):
        s = "/" + s
    if len(s) > 1:
        s = s.rstrip("/")
    return s


def _full_url(base_host: str, path: str) -> str:
    return (base_host or "").rstrip("/") + (path or "")


def _nav_qr(label: str, base_host: str, path: str) -> str:
    return f"{GUIDE_QR_PREFIX}{label}|{_full_url(base_host, path)}"


def _md_link(label: str, base_host: str, path: str) -> str:
    return f"[{label}]({_full_url(base_host, path)})"


def _group_by_id(cfg: dict[str, Any], gid: str) -> dict[str, Any] | None:
    for g in cfg.get("groups", []) or []:
        if g.get("id") == gid:
            return g
    return None


# ── Gruppen-Matching (Reply → Gruppe) ───────────────────────────────

def match_group(message: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Freitext / QR-Klick → Gruppe. Treffer auf ``label`` oder ``synonyms``
    (case-insensitive; Kandidat als Teilstring der Nachricht oder exakt)."""
    msg = (message or "").strip().lower()
    if not msg:
        return None
    for g in cfg.get("groups", []) or []:
        cands = [g.get("label", "")] + list(g.get("synonyms") or [])
        for c in cands:
            c = (c or "").strip().lower()
            if len(c) < 3:
                continue
            if c == msg or c in msg:
                return g
    return None


def _group_by_angebot_path(cfg: dict[str, Any], path: str) -> dict[str, Any] | None:
    """Rückwärts-Lookup: Angebots-/Produkt-Pfad → zugehörige Gruppe (erste
    Gruppe, die dieses Angebot listet). Für Einstiegspunkt C1 (Besucher
    startet die Tour direkt auf einer Produktseite)."""
    p = _norm_path(path)
    if not p or p == "/":
        return None
    for g in cfg.get("groups", []) or []:
        for a in g.get("angebote") or []:
            if _norm_path(a.get("path", "")) == p:
                return g
    return None


def detect_entry(page: str, cfg: dict[str, Any]) -> tuple[str, str]:
    """Aktuelle Seite beim Tour-Start → (start_step, group_id).

    Setzt das Flow-Modell (``flows:`` in website-tour.yaml) technisch um, damit
    die Tour MITTEN im Funnel einsteigen kann statt immer auf /home/:

      * /home/                 → ("group", "")     A*: Selbstzuordnung
      * Zielgruppenseite       → ("solutions", id) B1: Gruppe bekannt
      * Produkt-/Angebotsseite  → ("solutions", id) C1: Gruppe per Rückwärts-Lookup
      * /mitmachen/(…)         → ("contact", "")   D1/D2: schon am Konversions-Ziel
      * sonst / unbekannt      → ("intro", "")      voller Funnel ab Startseite
    """
    p = _norm_path(page)
    home = _norm_path(cfg.get("home_path", "/home/"))
    contact = _norm_path(cfg.get("contact_hub", "/mitmachen/"))
    if not p or p == "/":
        return ("intro", "")
    if p == home:
        return ("group", "")
    # B1 — Zielgruppen-Landingpage
    for g in cfg.get("groups", []) or []:
        if _norm_path(g.get("page", "")) == p:
            return ("solutions", g.get("id", ""))
    # C1 — Produkt-/Angebotsseite
    g = _group_by_angebot_path(cfg, p)
    if g is not None:
        return ("solutions", g.get("id", ""))
    # D1/D2 — Mitmach-/Anfrage-Seite (inkl. Unterseiten)
    if p == contact or p.startswith(contact + "/"):
        return ("contact", "")
    # sonst: voller Funnel ab Startseite
    return ("intro", "")


# ── Ankunfts-Logik ──────────────────────────────────────────────────

def expected(step: str, group_id: str, cfg: dict[str, Any]) -> tuple[str | None, list[str], str | None]:
    """Erwartete Ziele eines Schritts → (advance_path, explore_paths, next_step).

    advance_path = Pfad, dessen Ankunft zum next_step vorrückt (None = kein
    Arrival-Advance, z.B. ``group`` rückt per Reply vor). explore_paths =
    Pfade, deren Ankunft den AKTUELLEN Schritt erneut zeigt (kein Advance).
    """
    home = _norm_path(cfg.get("home_path", "/home/"))
    if step == "intro":
        return home, [], "group"
    if step == "group":
        return None, [home], "group_page"
    if step == "group_page":
        g = _group_by_id(cfg, group_id) or {}
        return _norm_path(g.get("page", "")), [], "content"
    if step == "content":
        return _norm_path(cfg.get("content_hub", "/bildungsinhalte/")), [], "solutions"
    if step == "solutions":
        g = _group_by_id(cfg, group_id) or {}
        expl = [_norm_path(a.get("path", "")) for a in (g.get("angebote") or []) if a.get("path")]
        expl += [_norm_path(s.get("path", "")) for s in (cfg.get("content_sublinks") or []) if s.get("path")]
        # Die Zielgruppenseite zählt in der Lösungen-Phase als Explore-Seite
        # (B1-Einstieg / Reload dort → kein irreführendes "nudge").
        if g.get("page"):
            expl.append(_norm_path(g.get("page", "")))
        return _norm_path(cfg.get("contact_hub", "/mitmachen/")), expl, "contact"
    return None, [], None


# ── Rendering ───────────────────────────────────────────────────────

def _nav_for_step(step: str, cfg: dict[str, Any], group_id: str = "") -> str | None:
    """Einzelner Weiter-Button (``__guide__``-QR) eines Schritts, falls vorhanden."""
    base = cfg.get("base_host", "")
    steps = cfg.get("steps", {}) or {}
    g = _group_by_id(cfg, group_id) or {}
    glabel = g.get("label", "")

    def fmt(s: str) -> str:
        return (s or "").replace("{group}", glabel)

    if step == "intro":
        lbl = (steps.get("intro", {}) or {}).get("nav_label", "Zur Startseite")
        return _nav_qr(lbl, base, cfg.get("home_path", "/home/"))
    if step == "group_page":
        st = steps.get("group_page", {}) or {}
        return _nav_qr(fmt(st.get("nav_label", "Zur Seite")), base, g.get("page", "/"))
    if step == "content":
        st = steps.get("content", {}) or {}
        return _nav_qr(st.get("nav_label", "Zu den Bildungsinhalten"), base,
                       cfg.get("content_hub", "/bildungsinhalte/"))
    if step == "solutions":
        st = steps.get("solutions", {}) or {}
        return _nav_qr(st.get("nav_label", "Weiter zum Abschluss"), base,
                       cfg.get("contact_hub", "/mitmachen/"))
    return None


def render(step: str, cfg: dict[str, Any], group_id: str = "", *, kind: str = "normal") -> dict[str, Any]:
    """Schritt → {text, quick_replies, final}.

    kind: ``normal`` | ``unsure`` (group: Re-Ask) | ``nudge`` (falsche Seite) |
    ``explore`` (Ankunft auf Explore-Seite in der Lösungen-Phase).
    """
    base = cfg.get("base_host", "")
    steps = cfg.get("steps", {}) or {}
    g = _group_by_id(cfg, group_id) or {}
    glabel = g.get("label", "")
    nav = _nav_for_step(step, cfg, group_id)

    def fmt(s: str) -> str:
        return (s or "").replace("{group}", glabel)

    if kind == "nudge":
        return {"text": (cfg.get("nudge") or "").strip(),
                "quick_replies": [nav] if nav else [], "final": False}
    if kind == "explore":
        return {"text": (cfg.get("explore") or "").strip(),
                "quick_replies": [nav] if nav else [], "final": False}

    # Einstieg mitten im Funnel (B1/C1): Begrüßung + relevante Angebote +
    # Weiter-zur-Anfrage-Button. nav = "Weiter zur Anfrage" → /mitmachen/.
    if kind == "entry" and step == "solutions":
        st = steps.get("solutions", {}) or {}
        entry_txt = fmt((cfg.get("entry", {}) or {}).get("solutions", "")).strip()
        parts = [entry_txt] if entry_txt else []
        angs = g.get("angebote") or []
        if angs:
            lbl = fmt(st.get("angebote_label", "Für dich relevant"))
            bullets = "\n".join(
                "- " + _md_link(a.get("label", ""), base, a.get("path", ""))
                for a in angs if a.get("path")
            )
            parts.append(f"**{lbl}:**\n{bullets}")
        return {"text": "\n\n".join(p for p in parts if p),
                "quick_replies": [nav] if nav else [], "final": False}

    if step == "intro":
        return {"text": (cfg.get("intro") or "").strip(),
                "quick_replies": [nav] if nav else [], "final": False}

    if step == "group":
        st = steps.get("group", {}) or {}
        text = (st.get("text") or "").strip()
        if kind == "unsure" and st.get("unsure_text"):
            text = (st.get("unsure_text") or "").strip() + "\n\n" + text
        qrs = [grp.get("label", "") for grp in (cfg.get("groups") or []) if grp.get("label")]
        if st.get("unsure_label"):
            qrs.append(st["unsure_label"])
        return {"text": text, "quick_replies": qrs, "final": False}

    if step == "group_page":
        st = steps.get("group_page", {}) or {}
        return {"text": fmt(st.get("text", "")).strip(),
                "quick_replies": [nav] if nav else [], "final": False}

    if step == "content":
        st = steps.get("content", {}) or {}
        return {"text": fmt(st.get("text", "")).strip(),
                "quick_replies": [nav] if nav else [], "final": False}

    if step == "solutions":
        st = steps.get("solutions", {}) or {}
        parts = [fmt(st.get("text", "")).strip()]
        subs = cfg.get("content_sublinks") or []
        if subs:
            lbl = st.get("sublinks_label", "Zum Stöbern")
            links = " · ".join(
                _md_link(s.get("label", ""), base, s.get("path", ""))
                for s in subs if s.get("path")
            )
            parts.append(f"**{lbl}:** {links}")
        angs = g.get("angebote") or []
        if angs:
            lbl = fmt(st.get("angebote_label", "Für dich relevant"))
            bullets = "\n".join(
                "- " + _md_link(a.get("label", ""), base, a.get("path", ""))
                for a in angs if a.get("path")
            )
            parts.append(f"**{lbl}:**\n{bullets}")
        return {"text": "\n\n".join(p for p in parts if p),
                "quick_replies": [nav] if nav else [], "final": False}

    if step == "contact":
        st = steps.get("contact", {}) or {}
        parts = [(st.get("text") or "").strip()]
        links = cfg.get("contact_links") or []
        if links:
            lbl = st.get("links_label", "Hier geht's weiter")
            ll = " · ".join(
                _md_link(l.get("label", ""), base, l.get("path", ""))
                for l in links if l.get("path")
            )
            parts.append(f"**{lbl}:** {ll}")
        return {"text": "\n\n".join(p for p in parts if p),
                "quick_replies": [], "final": True}

    # Fallback (unbekannter Schritt) → Intro.
    return {"text": (cfg.get("intro") or "").strip(),
            "quick_replies": [nav] if nav else [], "final": False}
