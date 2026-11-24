"""Higgsfield-Uebergaenge auf der Werkbank-Seite (24.11.2026): Karten je Stelle, Freigabe je Clip mit aenderbarem
Auftragstext, die Dateiroute fuer Uebergang und Standbilder. Die Marketing-API ist gefaelscht (wie in
test_werkbank_ui). Geprueft wird vor allem, dass NUR ein angemeldeter Mensch mit Schreibrecht auf dieser Seite etwas
freigeben kann und dass genau der gesehene Preis und der getippte Text weitergehen."""
import os

os.environ["SALES_DB_SCHEMA"] = "sales_test"

import pytest  # noqa: E402

import marketing_pult  # noqa: E402
import medien  # noqa: E402
import ui  # noqa: E402
from test_werkbank_ui import (AID, AID_FREMD, HOST, anonym, get, klient, leser, post, pult, rumpf)  # noqa: E402,F401

HID = "0123abcd-7777-7777-7777-777777777777"
START, ENDE = "wb-0123abcd-s02-f0-z.jpg", "wb-0123abcd-s03-f1-a.jpg"
CLIP = "wb-0123abcd-h03-f1.mp4"
SEITE = f"/marketing/werkbank/{AID}"
PROMPT = 'A paper cutter slices the slide <b>"clean"</b>'


def _clip(stand="vorgeschlagen", **mehr):
    c = {"id": HID, "art": "uebergang", "stand": stand, "versuch": 1, "nach_nr": 3, "von_nr": 2, "start_bild": START,
         "end_bild": ENDE, "prompt": PROMPT, "modell": "kling3_0", "dauer_s": 3, "preis": 5.25, "preis_bestellt": None,
         "datei": None, "clip_dauer_s": None, "fehler": None, "hinweis": None, "aktuell": True}
    c.update(mehr)
    return c


@pytest.fixture
def hf(pult, monkeypatch):  # noqa: F811
    """Szene 3 hat einen Higgsfield-Uebergang; `pult.hf` ist die Antwort von GET /werkbank/<aid>/hf (None = die
    API kennt den Weg nicht)."""
    pult.werk["szenen"][2]["uebergang"] = "higgsfield"
    pult.hf = {"clips": [_clip()], "credits": 0, "bestellt": 0, "vorbereitung": []}
    alt = pult.anfrage

    def anfrage(methode, pfad, daten=None, roh=False, zeitlimit=None):
        if methode == "GET" and pfad.startswith(f"/werkbank/{AID}/hf?"):
            pult.aufrufe.append((methode, pfad, daten))
            if pult.hf is None:
                raise marketing_pult.PultFehler("abgelehnt", "Not Found")
            return pult.hf
        return alt(methode, pfad, daten, roh, zeitlimit)
    monkeypatch.setattr(marketing_pult, "anfrage", anfrage)
    return pult


def senden(c, aktion, daten, csrf=True, headers=None):
    if csrf:
        daten = {"csrf": ui.CSRF_TOKEN, **daten}
    return c.post(f"/aktion/{aktion}", headers={**HOST, **(headers or {})}, follow_redirects=False, data=daten)


def erzeugen(c, **anders):
    return senden(c, "werkbank-hf-urteil", {"aid": AID, "hid": HID, "urteil": "erzeugen", "prompt": PROMPT,
                                            "preis": "5.25", **anders})


# --- Karten -----------------------------------------------------------------------------------------

def test_ohne_higgsfield_stelle_keine_karten_und_keine_anfrage(klient, pult):  # noqa: F811
    html = rumpf(get(klient, SEITE))
    assert "Higgsfield" not in html and not any("/hf" in a[1] for a in pult.aufrufe)


def test_vorschlag_zeigt_bilder_preis_und_aenderbaren_text(klient, hf):  # noqa: F811
    html = rumpf(get(klient, SEITE))
    assert "Higgsfield-Übergänge" in html and "Übergang von Szene 2 zu Szene 3" in html
    assert f'src="/marketing/werkbank/datei/{START}"' in html and f'src="/marketing/werkbank/datei/{ENDE}"' in html
    assert "Erzeugen für 5,25 Credits" in html and 'name="preis" value="5.25"' in html
    assert 'name="urteil" value="erzeugen"' in html and 'name="urteil" value="verwerfen"' in html
    assert '<textarea name="prompt"' in html and 'maxlength="1000"' in html
    assert "&lt;b&gt;" in html and "<b>&quot;clean" not in html and '<b>"clean' not in html      # Text ist maskiert
    assert "Bestellt wird erst mit deinem Klick" in html and "Kling 3.0" in html
    assert html.index('class="hf-zeile"') < html.index("<b>Szene 3</b>")         # der Uebergang steht vor seiner Szene
    assert "wartet auf deine Freigabe" in html and "Bisher bestellt" not in html


def test_leserolle_sieht_die_seite_nicht(leser, hf):  # noqa: F811
    r = get(leser, SEITE)                       # die Lese-Rolle hat keinen Zugang zur Werkbank (wie die Szenenseite)
    assert r.status_code == 403 and "werkbank-hf-" not in r.text and "Credits" not in r.text
    assert not hf.aufrufe


def test_bestellt_hat_keine_knoepfe(klient, hf):  # noqa: F811
    hf.hf = {"clips": [_clip("bestellt")], "credits": 5.25, "bestellt": 1, "vorbereitung": []}
    html = rumpf(get(klient, SEITE))
    assert "Der Clip entsteht bei Higgsfield" in html and "werkbank-hf-" not in html
    assert "Bisher bestellt: 1 Clip, 5,25 Credits." in html


def test_fertig_zeigt_den_clip_und_nochmal_mit_aenderung(klient, hf):  # noqa: F811
    hf.hf = {"clips": [_clip("fertig", datei=CLIP, preis_bestellt=5.25, clip_dauer_s=2.0)], "credits": 14, "bestellt": 2,
             "vorbereitung": []}
    html = rumpf(get(klient, SEITE))
    assert f'<video controls preload="metadata" src="/marketing/werkbank/datei/{CLIP}"' in html
    assert "Gekostet: 5,25 Credits." in html and 'action="/aktion/werkbank-hf-nochmal"' in html
    assert "Das bestellt noch nichts" in html and 'value="verwerfen"' in html and 'value="erzeugen"' not in html
    assert "Bisher bestellt: 2 Clips, 14 Credits." in html


def test_fertig_aber_ueberholt_bietet_kein_nochmal(klient, hf):  # noqa: F811
    hf.hf["clips"] = [_clip("fertig", datei=CLIP, preis_bestellt=5.25, aktuell=False)]
    html = rumpf(get(klient, SEITE))
    assert "Eine der beiden Szenen hat sich geändert" in html and "werkbank-hf-nochmal" not in html


def test_fehler_zeigt_den_grund(klient, hf):  # noqa: F811
    hf.hf["clips"] = [_clip("fehler", fehler="Die Bestellung ist unklar. Bitte bei Higgsfield nachsehen <x>.")]
    html = rumpf(get(klient, SEITE))
    assert "Die Bestellung ist unklar. Bitte bei Higgsfield nachsehen &lt;x&gt;." in html
    assert "werkbank-hf-nochmal" in html and 'value="verwerfen"' in html and 'value="erzeugen"' not in html


def test_stelle_in_vorbereitung_kann_uebersprungen_werden(klient, hf):  # noqa: F811
    hf.hf = {"clips": [], "credits": 0, "bestellt": 0, "vorbereitung": [3]}
    html = rumpf(get(klient, SEITE))
    assert "Übergang vor Szene 3" in html and "Der Vorschlag wird vorbereitet" in html
    assert 'action="/aktion/werkbank-hf-ohne"' in html and 'name="nr" value="3"' in html
    assert "Vorschlag wird vorbereitet" in html.split('class="hf-zeile"')[1][:200]


def test_api_kennt_die_uebergaenge_nicht_seite_bleibt_heil(klient, hf):  # noqa: F811
    hf.hf = None
    r = get(klient, SEITE)
    assert r.status_code == 200 and "Higgsfield-Übergänge" not in rumpf(r) and "<b>Szene 3</b>" in rumpf(r)


def test_fremde_kennung_oder_dateiname_in_der_antwort_wird_nicht_gezeigt(klient, hf):  # noqa: F811
    hf.hf["clips"] = [_clip(id="../../x"), _clip("fertig", datei="../geheim.mp4", start_bild="x.jpg", end_bild=CLIP)]
    html = rumpf(get(klient, SEITE))
    assert "geheim" not in html and "x.jpg" not in html and "<img" not in html and "<video" not in html


# --- Freigabe ---------------------------------------------------------------------------------------

def test_erzeugen_schickt_text_und_gesehenen_preis(klient, hf):  # noqa: F811
    r = erzeugen(klient, prompt="  Mein  eigener\nText  ")
    assert r.status_code == 303 and r.headers["location"] == f"{SEITE}?hinweis=hf_erzeugen#hf"
    methode, pfad, daten = hf.posts()[0]
    assert (methode, pfad) == ("POST", f"/werkbank/hf/{HID}/urteil") and len(hf.posts()) == 1
    assert daten == {"urteil": "erzeugen", "prompt": "Mein eigener Text", "preis_gesehen": 5.25,
                     "mandant": "vibemind", "von": "mira"}
    assert "Freigegeben" in rumpf(get(klient, r.headers["location"].split("#")[0]))


def test_verwerfen_braucht_weder_text_noch_preis(klient, hf):  # noqa: F811
    r = senden(klient, "werkbank-hf-urteil", {"aid": AID, "hid": HID, "urteil": "verwerfen"})
    assert r.status_code == 303 and r.headers["location"] == f"{SEITE}?hinweis=hf_verworfen#hf"
    assert hf.posts()[0][2] == {"urteil": "verwerfen", "mandant": "vibemind", "von": "mira"}


@pytest.mark.parametrize("preis", ["", "5,25", "abc", "-1", "1e3", "5.25; drop", "99999"])
def test_erzeugen_ohne_brauchbaren_preis_bestellt_nicht(klient, hf, preis):  # noqa: F811
    r = erzeugen(klient, preis=preis)
    assert r.status_code == 422 and not hf.posts() and "Nichts wurde bestellt" in r.text


@pytest.mark.parametrize("prompt", ["", "   ", "x" * 1001, "mit​nullbreite", "mit\x07klingel"])
def test_erzeugen_mit_ungueltigem_text_bestellt_nicht(klient, hf, prompt):  # noqa: F811
    r = erzeugen(klient, prompt=prompt)
    assert r.status_code == 422 and not hf.posts()


@pytest.mark.parametrize("anders", [{"hid": "x"}, {"hid": "../../x"}, {"aid": "x"}, {"urteil": "passt"}, {"urteil": ""}])
def test_ungueltige_angaben_werden_nicht_gesendet(klient, hf, anders):  # noqa: F811
    assert erzeugen(klient, **anders).status_code == 404 and not hf.posts()


def test_ohne_csrf_403(klient, hf):  # noqa: F811
    assert erzeugen(klient, csrf="falsch").status_code == 403
    assert senden(klient, "werkbank-hf-urteil", {"aid": AID, "hid": HID, "urteil": "erzeugen", "prompt": "x",
                                                 "preis": "5.25"}, csrf=False).status_code == 403
    assert not hf.posts()


def test_leserolle_kann_nichts_freigeben(leser, hf):  # noqa: F811
    for aktion, daten in (("werkbank-hf-urteil", {"hid": HID, "urteil": "erzeugen", "prompt": "x", "preis": "5.25"}),
                          ("werkbank-hf-nochmal", {"hid": HID, "prompt": "x"}), ("werkbank-hf-ohne", {"nr": "3"})):
        assert senden(leser, aktion, {"aid": AID, **daten}).status_code == 403
    assert not hf.posts()


def test_ohne_anmeldung_wird_nichts_freigegeben(anonym, hf):  # noqa: F811
    for aktion in ("werkbank-hf-urteil", "werkbank-hf-nochmal", "werkbank-hf-ohne"):
        r = senden(anonym, aktion, {"aid": AID, "hid": HID, "urteil": "erzeugen", "prompt": "x", "preis": "5.25", "nr": "3"})
        assert r.status_code in (303, 401, 403) and "/login" in r.headers.get("location", "/login")
    assert not hf.posts()


@pytest.mark.parametrize("kopf", [{"origin": "https://boese.example"}, {"sec-fetch-site": "cross-site"},
                                  {"origin": "null"}])
def test_anfrage_von_fremder_seite_wird_abgewiesen(klient, hf, kopf):  # noqa: F811
    r = senden(klient, "werkbank-hf-urteil", {"aid": AID, "hid": HID, "urteil": "erzeugen", "prompt": "x",
                                              "preis": "5.25"}, headers=kopf)
    assert r.status_code == 403 and not hf.posts()


def test_ablehnung_der_api_zeigt_den_grund_und_den_getippten_text(klient, hf):  # noqa: F811
    hf.fehler = marketing_pult.PultFehler("abgelehnt", "Der Preis hat sich geändert. Bitte die Seite neu laden <x>.")
    r = erzeugen(klient, prompt="Mein Text <i>")
    assert r.status_code == 409 and len(hf.posts()) == 1
    assert "Der Preis hat sich geändert. Bitte die Seite neu laden &lt;x&gt;." in r.text
    assert "Nichts wurde bestellt" in r.text and "Mein Text &lt;i&gt;" in r.text and f'href="{SEITE}#hf"' in r.text


def test_api_antwortet_nicht_ausgang_offen(klient, hf):  # noqa: F811
    hf.fehler = marketing_pult.PultFehler("nicht_erreichbar", "URLError")
    r = erzeugen(klient)
    assert r.status_code == 503 and "Ob dein Klick ankam, ist offen" in r.text and len(hf.posts()) == 1


def test_nochmal_legt_einen_vorschlag_an(klient, hf):  # noqa: F811
    r = senden(klient, "werkbank-hf-nochmal", {"aid": AID, "hid": HID, "prompt": "Neuer Text"})
    assert r.status_code == 303 and r.headers["location"] == f"{SEITE}?hinweis=hf_nochmal#hf"
    assert hf.posts() == [("POST", f"/werkbank/hf/{HID}/nochmal",
                           {"prompt": "Neuer Text", "mandant": "vibemind", "von": "mira"})]
    assert senden(klient, "werkbank-hf-nochmal", {"aid": AID, "hid": HID, "prompt": ""}).status_code == 422
    assert len(hf.posts()) == 1


def test_ohne_uebergang_weiter(klient, hf):  # noqa: F811
    r = senden(klient, "werkbank-hf-ohne", {"aid": AID, "nr": "3"})
    assert r.status_code == 303 and r.headers["location"] == f"{SEITE}?hinweis=hf_ohne#hf"
    assert hf.posts() == [("POST", f"/werkbank/{AID}/hf/3/ohne", {"mandant": "vibemind", "von": "mira"})]
    assert senden(klient, "werkbank-hf-ohne", {"aid": AID, "nr": "3x"}).status_code == 404
    assert senden(klient, "werkbank-hf-ohne", {"aid": AID, "nr": ""}).status_code == 404 and len(hf.posts()) == 1


# --- Dateien ----------------------------------------------------------------------------------------

def test_uebergang_und_standbilder_ueber_die_werkbank_route(klient, pult, tmp_path):  # noqa: F811
    (tmp_path / CLIP).write_bytes(b"video" * 50)
    (tmp_path / START).write_bytes(b"\xff\xd8\xff" + b"bild" * 50)
    r = get(klient, f"/marketing/werkbank/datei/{CLIP}")
    assert r.status_code == 200 and r.content == b"video" * 50 and r.headers["content-type"] == "video/mp4"
    b = get(klient, f"/marketing/werkbank/datei/{START}")
    assert b.status_code == 200 and b.headers["content-type"] == "image/jpeg" and b.content[:3] == b"\xff\xd8\xff"
    teil = get(klient, f"/marketing/werkbank/datei/{CLIP}", headers={"range": "bytes=0-4"})
    assert teil.status_code == 206 and teil.content == b"video"


@pytest.mark.parametrize("name", ["wb-99998888-h03-f1.mp4", "wb-99998888-s02-f0-z.jpg", "wb-0123abcd-s02-f0-m.jpg",
                                  "wb-0123abcd-s02-f0-z.png", "wb-0123abcd-h3-f1.mp4", "wb-0123abcd-h03-f1.mp4.teil",
                                  "wb-0123abcd-s02-f0-z.JPG"])
def test_fremde_oder_falsche_namen_404(klient, pult, tmp_path, name):  # noqa: F811
    (tmp_path / name).write_bytes(b"x" * 100)
    assert get(klient, f"/marketing/werkbank/datei/{name}").status_code == 404


def test_uebergang_ohne_anmeldung_umleitung(anonym, tmp_path):  # noqa: F811
    (tmp_path / CLIP).write_bytes(b"x" * 100)
    r = get(anonym, f"/marketing/werkbank/datei/{CLIP}")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_uebergang_und_standbild_sind_kein_medium_und_kein_fertiges_video():
    for name in (CLIP, START, ENDE, "wb-0123abcd-h100-f12.mp4"):
        assert medien.verborgen(name) and medien.werkbank_hf_datei(name) and medien.werkbankname_verdaechtig(name)
        assert medien.pruefe_anhang(name)[0] is None
        assert not medien.werkbankdatei(name)          # der Bote nimmt sie nie als fertiges Video eines Auftrags
    assert medien.werkbankname_verdaechtig("WB-0123ABCD-H03-F1.MP4") and medien.werkbankname_verdaechtig(" " + START)
    for name in ("wb-0123abcd-h3-f1.mp4", "wb-0123abcd-s02-f0-m.jpg", "wb-0123abcd-s02-f0-z.png", "urlaub-z.jpg"):
        assert not medien.werkbank_hf_datei(name)
