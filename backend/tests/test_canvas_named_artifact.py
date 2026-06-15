"""named_artifact_label — robuster Fallback für klar-benannte, aber ungelistete
Material-Typen (eval-1eda-Befund GS-4.3).

Kontrakt: liefert das wörtliche Artefakt-Nomen NUR, wenn der Nutzer einen
konkreten Typ benennt, der KEIN bekannter Alias/Typ ist. Generische Nomen
(„Material", „Inhalt") und bekannte Typen geben "" → echte Slot-Klärung (M03)
bzw. der reguläre Alias-Pfad bleiben intakt.

Die Assertions sind selbst-konsistent: wo es auf „unbekannter Typ" ankommt,
wird das via ``resolve_material_type(...) is None`` abgesichert — unabhängig
vom konkreten Vokabular der ausgelieferten Config.
"""

from __future__ import annotations

from app.services.canvas_service import named_artifact_label, resolve_material_type


def test_named_unlisted_artifact_is_returned():
    noun = "Argumentationshilfe"
    assert resolve_material_type(noun) is None  # Vorbedingung: kein bekannter Typ
    assert named_artifact_label(f"Erstell mir eine {noun} zum Klimawandel") == noun


def test_generic_noun_returns_empty():
    # „Material" ist generisch → Slot-Klärung bleibt korrekt.
    assert named_artifact_label("mach mir ein Material dazu") == ""


def test_known_type_returns_empty_handled_via_alias_path():
    # „Arbeitsblatt" ist ein bekannter Typ → nicht hier, sondern via Alias-Pfad.
    assert resolve_material_type("Arbeitsblatt") is not None
    assert named_artifact_label("Erstell mir ein Arbeitsblatt zu Brüchen") == ""


def test_empty_and_none_inputs():
    assert named_artifact_label("") == ""
    assert named_artifact_label(None) == ""
    assert named_artifact_label("zeig mir mal was") == ""


def test_classifier_type_unlisted_takes_precedence():
    cand = "Lernplakat"
    assert resolve_material_type(cand) is None
    # Auch ohne passendes Nomen im Text: klassifizierter, ungelisteter Typ gewinnt.
    assert named_artifact_label("mach das mal", classifier_type=cand) == cand


def test_classifier_type_generic_is_ignored():
    # generischer Classifier-Typ → fällt auf Message-Scan zurück → hier leer.
    assert named_artifact_label("mach das mal", classifier_type="material") == ""
