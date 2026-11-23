"""Auftragsarten fuer Auftraege an Sales: Lader, Formpruefung, Pruefsumme. Ohne Datenbank."""
import pytest

import auftrag_vertrag as av

# Pruefsummen im Vertrag von vibemind-os (spaces/_contract/sales.contract.yaml). post_pruefen und
# kontakt_finden: origin/master 23.11.2026. Die drei Zaehlarten: Zweig cc/sales-zaehlarten, b8d08837
# (dort in tests/test_zaehlarten.py dieselben Werte). Aendert sich eine hier, ist die Kopie nicht woertlich.
PRUEFSUMMEN = {
    ("post_pruefen", 2): "33235cd08d2f890411d79c746073caaa735f47bfbec8bc4a44f8275be44e24f7",
    ("kontakt_finden", 1): "861ecd0af8279ca2c5164e005d07bee24fa38e315dcab1b5b3d26051f32a43b8",
    ("termine_heute", 1): "35aa4fb717ca0af4a1acffd9e134ce0cb96d4f25b26cfee5688599efda89d751",
    ("freigaben_zaehlen", 1): "74c669057e253527c633f03a2ed4c7d03010c7819a9e1f39fab9687a7998b98e",
    ("post_offen", 1): "9fbf2a71ec72649208efed8e842c893e7055f0bb74c63f97e2b634186c591a3f",
}
ZAEHLARTEN = {"termine_heute", "freigaben_zaehlen", "post_offen"}
KID = "0123abcd-0000-4000-8000-000000000001"


@pytest.fixture(scope="module")
def arten():
    return av.lade()


def test_alle_arten_geladen(arten):
    assert set(arten) == {"post_pruefen", "kontakt_finden"} | ZAEHLARTEN
    for art in {"kontakt_finden"} | ZAEHLARTEN:
        assert arten[art].veraendert is False
        assert arten[art].nachpruefung == "form"
    assert arten["post_pruefen"].veraendert is True


def test_jede_art_ist_woertlich_der_vertrag_von_vibemind(arten):
    assert {(a.art, a.version): av.art_hash(a) for a in arten.values()} == PRUEFSUMMEN


@pytest.mark.parametrize("art, felder", [
    ("termine_heute", ("anzahl", "anzahl_kunden", "quellen_stumm")),
    ("freigaben_zaehlen", ("wartend", "fehlgeschlagen")),
    ("post_offen", ("chats_unbeantwortet", "mails_offen")),
])
def test_zaehlarten_nehmen_nichts_und_melden_nur_zahlen(arten, art, felder):
    a = arten[art]
    av.pruefe_eingabe(a, {})
    with pytest.raises(av.FormFehler):
        av.pruefe_eingabe(a, {"suche": "x"})
    gut = dict.fromkeys(felder, 0)
    av.pruefe_ergebnis(a, gut)
    for falsch in ({felder[0]: 1}, {**gut, felder[0]: -1}, {**gut, felder[0]: "3"}, {**gut, felder[0]: 1.5},
                   {**gut, "titel": "Name"}):
        with pytest.raises(av.FormFehler):
            av.pruefe_ergebnis(a, falsch)


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
