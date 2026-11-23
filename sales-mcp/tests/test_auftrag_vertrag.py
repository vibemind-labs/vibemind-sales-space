"""Auftragsarten fuer Auftraege an Sales: Lader, Formpruefung, Pruefsumme. Ohne Datenbank."""
import pytest

import auftrag_vertrag as av

# Pruefsummen im Vertrag von vibemind-os (spaces/_contract/sales.contract.yaml, Stand origin/master
# 23.11.2026). Aendert sich eine hier, ist die Kopie nicht mehr woertlich.
PRUEFSUMMEN = {
    ("post_pruefen", 2): "33235cd08d2f890411d79c746073caaa735f47bfbec8bc4a44f8275be44e24f7",
    ("kontakt_finden", 1): "861ecd0af8279ca2c5164e005d07bee24fa38e315dcab1b5b3d26051f32a43b8",
}
KID = "0123abcd-0000-4000-8000-000000000001"


@pytest.fixture(scope="module")
def arten():
    return av.lade()


def test_beide_arten_geladen(arten):
    assert set(arten) == {"post_pruefen", "kontakt_finden"}
    assert arten["kontakt_finden"].veraendert is False
    assert arten["kontakt_finden"].nachpruefung == "form"
    assert arten["post_pruefen"].veraendert is True


def test_jede_art_ist_woertlich_der_vertrag_von_vibemind(arten):
    assert {(a.art, a.version): av.art_hash(a) for a in arten.values()} == PRUEFSUMMEN


def test_ergebnis_post_pruefen_v2_nur_pfade_und_saubere_kennungen(arten):
    a = arten["post_pruefen"]
    punkt = {"punkt_id": "0123456789abcdef", "titel": "Rückfrage", "frist": None,
             "link": "/post/aufraeumen#p1", "entwurf_id": "e_42-a"}
    av.pruefe_ergebnis(a, {"faellig": [punkt], "anzahl_gelesen": 3, "kontakte_neu": 0})
    av.pruefe_ergebnis(a, {"faellig": [{**punkt, "entwurf_id": None}], "anzahl_gelesen": 0, "kontakte_neu": 0})
    for falsch in ({"link": "https://anderswo.example/x"}, {"link": "//anderswo.example/x"},
                   {"link": "/mit leerzeichen"}, {"link": "/zeile\n"}, {"link": "relativ"},
                   {"entwurf_id": "a/b"}, {"entwurf_id": ""}, {"entwurf_id": "x" * 65}):
        with pytest.raises(av.FormFehler):
            av.pruefe_ergebnis(a, {"faellig": [{**punkt, **falsch}], "anzahl_gelesen": 0, "kontakte_neu": 0})


def test_eingabe_kontakt_finden(arten):
    a = arten["kontakt_finden"]
    av.pruefe_eingabe(a, {"suche": "Muster"})
    for falsch in ({}, {"suche": "x"}, {"suche": "a" * 101}, {"suche": "Muster", "mehr": 1}, {"suche": 7}, []):
        with pytest.raises(av.FormFehler):
            av.pruefe_eingabe(a, falsch)


def test_fehlertext_nennt_nie_den_wert(arten):
    geheim = "streng-geheimer-suchtext-" + "x" * 90
    with pytest.raises(av.FormFehler) as e:
        av.pruefe_eingabe(arten["kontakt_finden"], {"suche": geheim, geheim: 1})
    assert geheim not in str(e.value)
    assert "suche" in str(e.value)


def test_ergebnis_kontakt_finden(arten):
    a = arten["kontakt_finden"]
    treffer = {"kontakt_id": KID, "titel": "Muster GmbH", "link": f"/kontakte/{KID}"}
    av.pruefe_ergebnis(a, {"treffer": [treffer], "anzahl": 1})
    av.pruefe_ergebnis(a, {"treffer": [], "anzahl": 0})
    falsch = (
        {"treffer": [treffer]},                                   # anzahl fehlt
        {"treffer": [treffer] * 11, "anzahl": 11},                # mehr als zehn
        {"treffer": [{**treffer, "kontakt_id": "42"}], "anzahl": 1},
        {"treffer": [{**treffer, "telefon": "0"}], "anzahl": 1},   # kein Feld ausserhalb der Form
        {"treffer": [{**treffer, "link": "https://anderswo.example/x"}], "anzahl": 1},
    )
    for f in falsch:
        with pytest.raises(av.FormFehler):
            av.pruefe_ergebnis(a, f)


def test_kaputte_datei_wird_abgelehnt(tmp_path):
    datei = tmp_path / "arten.yaml"
    datei.write_text("auftragsarten:\n  - art: x\n", encoding="utf-8")
    with pytest.raises(av.VertragsFehler):
        av.lade(datei)
    datei.write_text("auftragsarten:\n  - art: offen\n    version: 1\n    veraendert: false\n    frist_min: 5\n"
                     "    nachpruefung: form\n    beschreibung: x\n    eingabe: {type: object}\n"
                     "    ergebnis: {type: object, additionalProperties: false}\n", encoding="utf-8")
    with pytest.raises(av.VertragsFehler):   # eingabe ist nicht geschlossen
        av.lade(datei)
