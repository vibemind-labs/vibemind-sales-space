"""Unterhaltungen und Erbe gesendeter Mails (Post-Assistent Stufe 1, Task 4).

DB-Tests nur gegen sales_test. Mails werden direkt eingefuegt und wie `_speichern` mit
`zuordnen` in dieselbe Transaktion gehaengt; ein Test geht durch das echte Abholen.
"""
import itertools
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_post_abholen import (  # noqa: E402,F401  (Fixtures wirken nur im eigenen Namensraum)
    Attrappe, _einordnung, _konto, _mail, _mails, _zeile, kein_modell, saubere_tabellen, schema_wache)

import post_abholen  # noqa: E402
import post_einordnung  # noqa: E402
import post_unterhaltung  # noqa: E402
import server  # noqa: E402

BASIS = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
_uids = itertools.count(1)


def _roh(kennung, message_id, tage=0, richtung="eingang", in_reply_to=None, referenzen=(),
         bereich=None, sensibel=False, ersatz=False, zuordnen=True, text="Inhalt",
         besitzer="felix", von="a@example.org") -> str:
    """Eine Mail einfuegen und - wie `_speichern` - in derselben Transaktion zuordnen."""
    konto = _zeile(kennung)
    with server.pool.connection() as conn, conn.transaction():
        mail_id = conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, an, betreff, "
            "datum, text, auszug, anhaenge, status, bereich, richtung, in_reply_to, referenzen, "
            "sensibel, message_id_ersatz) values (%s, %s, %s, %s, %s, "
            "'b@example.org', 'Betreff', %s, %s, %s, '{x.pdf}', %s, %s, %s, %s, %s, %s, %s) "
            "returning id",
            (konto["id"], next(_uids), message_id, besitzer, von, BASIS + timedelta(days=tage),
             None if sensibel else text, None if sensibel else text,
             "gesendet" if richtung == "gesendet" else "neu", bereich, richtung, in_reply_to,
             list(referenzen), sensibel, ersatz)).fetchone()["id"]
        if zuordnen:
            post_unterhaltung.zuordnen(conn, mail_id)
    return str(mail_id)


def _zeile_von(mail_id) -> dict:
    with server.pool.connection() as conn:
        return conn.execute("select * from post_mails where id = %s", (mail_id,)).fetchone()


def _unt(mail_id):
    return _zeile_von(mail_id)["unterhaltung"]


def test_antwort_haengt_am_original():
    _konto()
    m1 = _roh("gmx-test", "m1@x")
    antwort = _roh("gmx-test", "g1@x", tage=1, richtung="gesendet", in_reply_to="m1@x")
    assert _unt(m1) is not None and _unt(m1) == _unt(antwort)


def test_reihenfolge_egal():
    _konto()
    antwort = _roh("gmx-test", "g1@x", tage=1, richtung="gesendet", in_reply_to="m1@x")
    m1 = _roh("gmx-test", "m1@x")
    assert _unt(m1) is not None and _unt(m1) == _unt(antwort)


def test_zwei_ketten_verschmelzen():
    _konto()
    a1 = _roh("gmx-test", "a1@x", tage=0)
    a2 = _roh("gmx-test", "a2@x", tage=2, in_reply_to="a1@x", referenzen=["a1@x"])
    b1 = _roh("gmx-test", "b1@x", tage=1)
    b2 = _roh("gmx-test", "b2@x", tage=3, in_reply_to="b1@x", referenzen=["b1@x"])
    assert _unt(a1) == _unt(a2) != _unt(b1) and _unt(b1) == _unt(b2)
    aelteste = _unt(a1)
    m = _roh("gmx-test", "m@x", tage=4, in_reply_to="b2@x", referenzen=["a2@x", "b2@x"])
    assert {_unt(i) for i in (a1, a2, b1, b2, m)} == {aelteste}


def test_ersatz_kennung_verbindet_nicht():
    _konto()
    e1 = _roh("gmx-test", "gmx-test:1@sales-post", ersatz=True)
    e2 = _roh("gmx-test", "gmx-test:1@sales-post", tage=1, ersatz=True)
    antwort = _roh("gmx-test", "g1@x", tage=2, richtung="gesendet",
                   in_reply_to="gmx-test:1@sales-post")
    assert len({_unt(e1), _unt(e2), _unt(antwort)}) == 3


def test_nie_ueber_besitzer_hinweg():
    _konto("felix", "felix-k")
    _konto("ivan", "ivan-k")
    f = _roh("felix-k", "gleich@x", besitzer="felix")
    i = _roh("ivan-k", "gleich@x", besitzer="ivan")
    fa = _roh("felix-k", "fa@x", tage=1, besitzer="felix", in_reply_to="gleich@x")
    ia = _roh("ivan-k", "ia@x", tage=1, besitzer="ivan", in_reply_to="gleich@x")
    assert _unt(f) != _unt(i)
    assert _unt(fa) == _unt(f) and _unt(ia) == _unt(i)


def test_gesendet_erbt_bereich():
    _konto()
    with server.pool.connection() as conn:
        conn.execute("update post_konten set standard_bereich = 'business'")
    eingang = _roh("gmx-test", "m1@x", bereich="privat")
    antwort = _roh("gmx-test", "g1@x", tage=1, richtung="gesendet", in_reply_to="m1@x",
                   bereich="business")
    ohne_bezug = _roh("gmx-test", "g2@x", tage=2, richtung="gesendet", bereich="business")
    erg = post_unterhaltung.nachziehen()
    assert erg["geerbt"] == 1
    assert _zeile_von(antwort)["bereich"] == "privat"
    assert _zeile_von(ohne_bezug)["bereich"] == "business"
    assert _zeile_von(eingang)["bereich"] == "privat"
    assert post_unterhaltung.nachziehen()["geerbt"] == 0      # zweiter Lauf: nichts mehr zu tun


def test_erbe_nimmt_letzte_vorhandene_referenz():
    _konto()
    _roh("gmx-test", "r1@x", bereich="privat")
    antwort = _roh("gmx-test", "g1@x", tage=1, richtung="gesendet", bereich="business",
                   in_reply_to="fehlt@x", referenzen=["r1@x", "fehlt@x"])
    post_unterhaltung.nachziehen()
    assert _zeile_von(antwort)["bereich"] == "privat"


def test_antwort_auf_sensible_mail_wird_nachtraeglich_sensibel():
    _konto()
    antwort = _roh("gmx-test", "g1@x", tage=1, richtung="gesendet", in_reply_to="m1@x",
                   bereich="business", text="Vertraulicher Antworttext")
    assert _zeile_von(antwort)["sensibel"] is False
    _roh("gmx-test", "m1@x", bereich="privat", sensibel=True)      # Bezug kommt spaeter
    with server.pool.connection() as conn:
        conn.execute("update post_mails set urspruengliche_adresse = 'x@example.org' "
                     "where id = %s", (antwort,))
    post_unterhaltung.nachziehen()
    z = _zeile_von(antwort)
    assert z["sensibel"] is True and z["bereich"] == "privat"
    assert z["text"] is None and z["auszug"] is None and z["an"] is None
    assert z["anhaenge"] == []
    assert z["urspruengliche_adresse"] is None


def test_erbe_geht_nie_ueber_besitzer_hinweg():
    _konto("felix", "felix-k")
    _konto("ivan", "ivan-k")
    _roh("felix-k", "gleich@x", besitzer="felix", bereich="privat", sensibel=True)
    ivan = _roh("ivan-k", "ia@x", tage=1, richtung="gesendet", besitzer="ivan",
                in_reply_to="gleich@x", bereich="business", text="Ivans Text")
    assert post_unterhaltung.nachziehen()["geerbt"] == 0
    z = _zeile_von(ivan)
    assert z["bereich"] == "business" and z["sensibel"] is False and z["text"] == "Ivans Text"


def test_sensibel_geht_nie_zurueck():
    _konto()
    eingang = _roh("gmx-test", "m1@x", sensibel=True)
    antwort = _roh("gmx-test", "g1@x", tage=1, richtung="gesendet", in_reply_to="m1@x")
    post_unterhaltung.nachziehen()
    assert _zeile_von(antwort)["sensibel"] is True
    with server.pool.connection() as conn:
        conn.execute("update post_mails set sensibel = false where id = %s", (eingang,))
    post_unterhaltung.nachziehen()
    assert _zeile_von(antwort)["sensibel"] is True


def test_nachziehen_ordnet_nachtraeglich_zu_und_zaehlt():
    _konto()
    a = _roh("gmx-test", "m1@x", zuordnen=False)
    b = _roh("gmx-test", "g1@x", tage=1, richtung="gesendet", in_reply_to="m1@x", zuordnen=False)
    assert post_unterhaltung.nachziehen()["zugeordnet"] == 2
    assert _unt(a) is not None and _unt(a) == _unt(b)
    assert post_unterhaltung.nachziehen()["zugeordnet"] == 0


def test_abholen_ordnet_zu_in_beliebiger_reihenfolge():
    _konto()
    antwort = _mail("<g1@x>", in_reply_to="<m1@x>", datum="Tue, 03 Nov 2026 10:00:00 +0100")
    original = _mail("<m1@x>", datum="Mon, 02 Nov 2026 10:00:00 +0100")
    kasten = Attrappe({1: antwort, 2: original})
    post_abholen.konto_abholen(_zeile("gmx-test"), kasten)
    zeilen = _mails()
    assert len(zeilen) == 2 and zeilen[0]["unterhaltung"] is not None
    assert zeilen[0]["unterhaltung"] == zeilen[1]["unterhaltung"]


def test_nachziehen_fehler_kostet_runde_nicht(monkeypatch, caplog):
    _konto()
    kasten = Attrappe({1: _mail("<e1@x>")})
    monkeypatch.setattr(post_abholen.post_konten, "verbinden", lambda zeile: kasten)
    monkeypatch.setattr(post_einordnung, "einordnen", lambda mail, konto: _einordnung())

    def kaputt(*a, **k):
        raise RuntimeError("geheim@example.org <e1@x> Betreff")
    monkeypatch.setattr(post_unterhaltung, "nachziehen", kaputt)
    with caplog.at_level(logging.DEBUG):
        bilanz = post_abholen.eine_runde()
    assert bilanz["abgeholt"] == 1 and bilanz["eingeordnet"] == 1
    assert "unterhaltung" not in bilanz
    text = caplog.text
    assert "RuntimeError" in text
    assert "geheim" not in text and "e1@x" not in text and "Betreff" not in text


def test_runde_traegt_unterhaltung_in_die_bilanz(monkeypatch):
    _konto()
    kasten = Attrappe({1: _mail("<e1@x>")})
    monkeypatch.setattr(post_abholen.post_konten, "verbinden", lambda zeile: kasten)
    monkeypatch.setattr(post_einordnung, "einordnen", lambda mail, konto: _einordnung())
    bilanz = post_abholen.eine_runde()
    assert set(bilanz["unterhaltung"]) == {"zugeordnet", "geerbt", "fehler"}


def test_runde_sensibel_im_selben_durchlauf(monkeypatch):
    _konto()
    antwort = _roh("gmx-test", "g1@x", tage=1, richtung="gesendet", in_reply_to="e1@x",
                   bereich="business", text="Antworttext")
    kasten = Attrappe({1: _mail("<e1@x>")})
    monkeypatch.setattr(post_abholen.post_konten, "verbinden", lambda zeile: kasten)
    monkeypatch.setattr(post_einordnung, "einordnen",
                        lambda mail, konto: _einordnung(sensibel=True))
    post_abholen.eine_runde()
    z = _zeile_von(antwort)
    assert z["sensibel"] is True and z["text"] is None and z["bereich"] == "business"


@pytest.mark.parametrize("fall", ["pause", "wirft"])
def test_nachziehen_laeuft_auch_ohne_einordnen(monkeypatch, fall):
    _konto()
    antwort = _roh("gmx-test", "g1@x", tage=1, richtung="gesendet", in_reply_to="e1@x")
    _roh("gmx-test", "e1@x", sensibel=True)
    kasten = Attrappe({})
    monkeypatch.setattr(post_abholen.post_konten, "verbinden", lambda zeile: kasten)
    if fall == "pause":
        monkeypatch.setattr(post_abholen, "kunde_aktiv", lambda: True)
        post_abholen.eine_runde()
    else:
        def kaputt(bilanz):
            raise RuntimeError("x")
        monkeypatch.setattr(post_abholen, "_einordnen", kaputt)
        with pytest.raises(RuntimeError):
            post_abholen.eine_runde()
    assert _zeile_von(antwort)["sensibel"] is True


def test_eine_kaputte_zuordnung_stoppt_weder_rest_noch_erbe(monkeypatch, caplog):
    _konto()
    antwort = _roh("gmx-test", "g1@x", tage=1, richtung="gesendet", in_reply_to="m1@x",
                   zuordnen=False)
    _roh("gmx-test", "m1@x", tage=0, sensibel=True, zuordnen=False)
    schlecht = _roh("gmx-test", "x1@x", tage=2, zuordnen=False)
    gut = _roh("gmx-test", "y1@x", tage=3, zuordnen=False)
    echt = post_unterhaltung.zuordnen

    def fake(conn, mail_id):
        if str(mail_id) == schlecht:
            raise RuntimeError("geheim@example.org x1@x")
        return echt(conn, mail_id)
    monkeypatch.setattr(post_unterhaltung, "zuordnen", fake)
    with caplog.at_level(logging.DEBUG):
        erg = post_unterhaltung.nachziehen()
    assert erg["fehler"] == 1 and erg["zugeordnet"] == 3
    assert _unt(schlecht) is None and _unt(gut) is not None and _unt(antwort) is not None
    assert _zeile_von(antwort)["sensibel"] is True
    assert "RuntimeError" in caplog.text
    assert "geheim" not in caplog.text and "x1@x" not in caplog.text


def test_stopp_beendet_nur_die_zuordnung():
    _konto()
    a = _roh("gmx-test", "m1@x", zuordnen=False)
    antwort = _roh("gmx-test", "g1@x", tage=1, richtung="gesendet", in_reply_to="m1@x",
                   bereich="business", zuordnen=False)
    with server.pool.connection() as conn:
        conn.execute("update post_mails set bereich = 'privat' where id = %s", (a,))
    erg = post_unterhaltung.nachziehen(stopp=lambda: True)
    assert erg["zugeordnet"] == 0 and _unt(a) is None
    assert erg["geerbt"] == 1 and _zeile_von(antwort)["bereich"] == "privat"


def test_speichern_behaelt_mail_und_stand_wenn_zuordnen_scheitert(monkeypatch, caplog):
    _konto()

    def kaputt(conn, mail_id):
        raise RuntimeError("geheim@example.org <e1@x>")
    monkeypatch.setattr(post_unterhaltung, "zuordnen", kaputt)
    with caplog.at_level(logging.DEBUG):
        assert post_abholen.konto_abholen(_zeile("gmx-test"), Attrappe({1: _mail("<e1@x>")})) == 1
    zeilen = _mails()
    assert len(zeilen) == 1 and zeilen[0]["unterhaltung"] is None
    assert _zeile("gmx-test")["letzte_uid"] == 1
    assert "RuntimeError" in caplog.text and "geheim" not in caplog.text
    monkeypatch.undo()
    assert post_unterhaltung.nachziehen()["zugeordnet"] == 1
    assert _mails()[0]["unterhaltung"] is not None



# --- Fix-Welle: Mail an mich selbst (I2), Sperrschluessel (M10a) -----------------------

# Eigene Kontoadresse von "gmx-test" (siehe _konto); bewusst mit Namen und Grossschreibung.
EIGEN = "Felix <GMX-Test@gmx.de>"


def test_zwilling_teilt_unterhaltung_und_erbt_schutz():
    _konto()
    raus = _roh("gmx-test", "selbst@x", richtung="gesendet", bereich="business",
                text="Notiz an mich")
    eingang = _roh("gmx-test", "selbst@x", bereich="privat", von=EIGEN)
    assert _unt(raus) is not None and _unt(raus) == _unt(eingang)
    with server.pool.connection() as conn:
        conn.execute("update post_mails set sensibel = true where id = %s", (eingang,))
    post_unterhaltung.nachziehen()
    z = _zeile_von(raus)
    assert z["sensibel"] is True and z["bereich"] == "privat"
    assert z["text"] is None and z["auszug"] is None and z["an"] is None
    assert z["anhaenge"] == []
    assert post_unterhaltung.nachziehen()["geerbt"] == 0


@pytest.mark.parametrize("gesendet_zuerst", [True, False], ids=["gesendet-zuerst", "falsch-zuerst"])
def test_gefaelschter_zwilling_aendert_nichts(gesendet_zuerst):
    """N1: eine fremde Mail mit der Message-ID einer gesendeten Mail ist kein Zwilling -
    kein Bereich, kein Leeren, keine gemeinsame Unterhaltung."""
    _konto()

    def falsch():
        return _roh("gmx-test", "raus@x", bereich="business", sensibel=True,
                    von="Mallory <mallory@example.org>")

    def echt():
        return _roh("gmx-test", "raus@x", tage=1, richtung="gesendet", bereich="privat",
                    text="Privater Text")
    if gesendet_zuerst:
        raus, f = echt(), falsch()
    else:
        f, raus = falsch(), echt()
    assert _unt(raus) != _unt(f)
    assert post_unterhaltung.nachziehen()["geerbt"] == 0
    z = _zeile_von(raus)
    assert z["bereich"] == "privat" and z["sensibel"] is False and z["text"] == "Privater Text"
    assert z["an"] == "b@example.org" and z["anhaenge"] == ["x.pdf"]
    assert _unt(raus) != _unt(f)


def test_zwilling_nie_ueber_besitzer_oder_platzhalter():
    _konto("felix", "felix-k")
    _konto("ivan", "ivan-k")
    felix = _roh("felix-k", "gleich@x", besitzer="felix", bereich="privat", sensibel=True,
                 von="felix-k@gmx.de")
    ivan = _roh("ivan-k", "gleich@x", richtung="gesendet", besitzer="ivan",
                bereich="business", text="Ivans Text")
    e1 = _roh("felix-k", "felix-k:1@sales-post", ersatz=True, bereich="privat", sensibel=True,
              von="felix-k@gmx.de")
    e2 = _roh("felix-k", "felix-k:1@sales-post", richtung="gesendet", ersatz=True,
              bereich="business", text="Platzhaltertext")
    assert _unt(felix) != _unt(ivan) and _unt(e1) != _unt(e2)
    assert post_unterhaltung.nachziehen()["geerbt"] == 0
    for mid, text in ((ivan, "Ivans Text"), (e2, "Platzhaltertext")):
        z = _zeile_von(mid)
        assert z["sensibel"] is False and z["text"] == text and z["bereich"] == "business"


def test_privater_zwilling_macht_privat():
    _konto()
    _roh("gmx-test", "selbst@x", bereich="privat", von=EIGEN)
    raus = _roh("gmx-test", "selbst@x", tage=1, richtung="gesendet", bereich="business")
    assert post_unterhaltung.nachziehen()["geerbt"] == 1
    z = _zeile_von(raus)
    assert z["bereich"] == "privat" and z["sensibel"] is False and z["text"] == "Inhalt"


def test_business_zwilling_lockert_nie():
    _konto()
    _roh("gmx-test", "selbst@x", bereich="business", von=EIGEN)
    raus = _roh("gmx-test", "selbst@x", tage=1, richtung="gesendet", bereich="privat")
    assert post_unterhaltung.nachziehen()["geerbt"] == 0
    assert _zeile_von(raus)["bereich"] == "privat"


def test_bezugsmail_geht_beim_bereich_vor_zwilling_nur_strenger():
    _konto()
    _roh("gmx-test", "r1@x", bereich="privat")
    _roh("gmx-test", "selbst@x", bereich="business", von=EIGEN)
    raus = _roh("gmx-test", "selbst@x", tage=1, richtung="gesendet", in_reply_to="r1@x",
                bereich="business")
    post_unterhaltung.nachziehen()
    assert _zeile_von(raus)["bereich"] == "privat"


def test_privater_zwilling_schlaegt_business_bezug_sensibel_aus_beiden():
    _konto()
    _roh("gmx-test", "r1@x", bereich="business")
    _roh("gmx-test", "selbst@x", bereich="privat", von=EIGEN)
    raus = _roh("gmx-test", "selbst@x", tage=1, richtung="gesendet", in_reply_to="r1@x",
                bereich="business")
    post_unterhaltung.nachziehen()
    assert _zeile_von(raus)["bereich"] == "privat"
    # Sensibel kommt aus jedem Bezug, auch wenn der Zwilling es nicht ist.
    with server.pool.connection() as conn:
        conn.execute("update post_mails set sensibel = true where message_id = 'r1@x'")
    post_unterhaltung.nachziehen()
    assert _zeile_von(raus)["sensibel"] is True


# --- Sicherheitsrunde 2: fremde Kopie als Bezug (F1), strenger Absender (F2), leere
# Kontoadresse (F4), alle Zwillinge zaehlen (bool_or) ------------------------------------

@pytest.mark.parametrize("falsch_vor_antwort", [True, False], ids=["falsch-vorher", "falsch-nachher"])
def test_fremde_kopie_einer_gesendeten_id_ist_kein_bezug(falsch_vor_antwort):
    """F1: Felix sendet A (privat); eine fremde Mail traegt A's Message-ID (business,
    sensibel); Felix antwortet mit B auf A. B bleibt privat, behaelt den Inhalt und
    gehoert nicht zur Unterhaltung der fremden Mail."""
    _konto()
    a = _roh("gmx-test", "a@x", richtung="gesendet", bereich="privat", text="A-Text")

    def falsch():
        return _roh("gmx-test", "a@x", tage=1, bereich="business", sensibel=True,
                    von="Mallory <mallory@example.org>")

    def antwort():
        return _roh("gmx-test", "b@x", tage=2, richtung="gesendet", in_reply_to="a@x",
                    referenzen=["a@x"], bereich="privat", text="B-Text")
    if falsch_vor_antwort:
        f = falsch()
        b = antwort()
    else:
        b = antwort()
        f = falsch()
    post_unterhaltung.nachziehen()
    z = _zeile_von(b)
    assert z["bereich"] == "privat" and z["sensibel"] is False and z["text"] == "B-Text"
    assert z["an"] == "b@example.org" and z["anhaenge"] == ["x.pdf"]
    assert _unt(b) == _unt(a) and _unt(f) not in (_unt(a), _unt(b))


def test_echte_selbstkopie_schuetzt_die_antwort_ueber_die_gesendete_zeile():
    """F1, Gegenprobe: die echte Kopie (Mail an mich selbst, eigene Adresse) macht A
    sensibel (Zwilling); B erbt es von A, der gesendeten Zeile - in derselben Runde
    (Erbe bis zum Fixpunkt)."""
    _konto()
    a = _roh("gmx-test", "a@x", richtung="gesendet", bereich="privat", text="A-Text")
    kopie = _roh("gmx-test", "a@x", tage=1, bereich="privat", sensibel=True, von=EIGEN)
    b = _roh("gmx-test", "b@x", tage=2, richtung="gesendet", in_reply_to="a@x",
             bereich="privat", text="B-Text")
    post_unterhaltung.nachziehen()
    assert _zeile_von(a)["sensibel"] is True
    assert _zeile_von(b)["sensibel"] is True and _zeile_von(b)["text"] is None
    assert _unt(a) == _unt(kopie) == _unt(b)


def test_erbe_bis_zum_fixpunkt_in_einer_runde():
    """Runde 4: Selbst-Kopie sensibel -> gesendete A -> Antwort B -> Antwort C, alles in
    EINEM nachziehen; der Inhalt aller drei ist danach leer."""
    _konto()
    a = _roh("gmx-test", "a@x", richtung="gesendet", bereich="business", text="A-Text")
    _roh("gmx-test", "a@x", tage=1, bereich="privat", sensibel=True, von=EIGEN)
    b = _roh("gmx-test", "b@x", tage=2, richtung="gesendet", in_reply_to="a@x",
             bereich="business", text="B-Text")
    c = _roh("gmx-test", "c@x", tage=3, richtung="gesendet", in_reply_to="b@x",
             bereich="business", text="C-Text")
    erg = post_unterhaltung.nachziehen()
    for mid in (a, b, c):
        z = _zeile_von(mid)
        assert z["sensibel"] is True and z["bereich"] == "privat", mid
        assert z["text"] is None and z["auszug"] is None and z["an"] is None
        assert z["anhaenge"] == []
    assert erg["geerbt"] >= 3
    assert post_unterhaltung.nachziehen()["geerbt"] == 0


def test_erbe_grenze_meldet_nur_die_zahl(monkeypatch, caplog):
    aufrufe = []

    def immer_eins(conn, mail_id=None):
        aufrufe.append(mail_id)
        return 1
    monkeypatch.setattr(post_unterhaltung, "erben", immer_eins)
    with caplog.at_level(logging.DEBUG):
        erg = post_unterhaltung.nachziehen()
    assert len(aufrufe) == post_unterhaltung.ERBE_DURCHLAEUFE_MAX == 10
    assert erg["geerbt"] == 10 and aufrufe == [None] * 10
    meldungen = [r.getMessage() for r in caplog.records if "Erbe" in r.getMessage()]
    assert meldungen == ["Erbe nach 10 Durchlaeufen nicht fertig"]


def test_gesendete_zeile_geht_als_bezug_vor_gefaelschter_eigener_kopie():
    """Rangfolge: liegt die echte gesendete A vor, ist sie der Bezug - nie eine
    Eingangskopie von A, auch nicht mit (gefaelschter) eigener Absenderadresse."""
    _konto()
    _roh("gmx-test", "a@x", richtung="gesendet", bereich="privat", text="A-Text")
    _roh("gmx-test", "a@x", tage=1, bereich="business", von=EIGEN)
    b = _roh("gmx-test", "b@x", tage=2, richtung="gesendet", in_reply_to="a@x",
             referenzen=["a@x"], bereich="privat", text="B-Text")
    post_unterhaltung.nachziehen()
    z = _zeile_von(b)
    assert z["bereich"] == "privat" and z["sensibel"] is False and z["text"] == "B-Text"


@pytest.mark.parametrize("von", [
    '"Felix <gmx-test@gmx.de>" <mallory@example.org>',     # Anzeigename mit <eigene>
    "<gmx-test@gmx.de>, <mallory@example.org>",            # Adressliste
    '"gmx-test@gmx.de" <mallory@example.org>',             # Anzeigename sieht aus wie eigene
    "gmx-test@gmx.de, mallory@example.org",                # Liste ohne Klammern
])
def test_getarnter_absender_ist_kein_zwilling(von):
    """F2: weder Anzeigename noch Adressliste schmuggeln die eigene Adresse durch."""
    _konto()
    raus = _roh("gmx-test", "raus@x", richtung="gesendet", bereich="privat",
                text="Privater Text")
    f = _roh("gmx-test", "raus@x", tage=1, bereich="privat", sensibel=True, von=von)
    assert post_unterhaltung.nachziehen()["geerbt"] == 0
    z = _zeile_von(raus)
    assert z["sensibel"] is False and z["text"] == "Privater Text"
    assert _unt(raus) != _unt(f)


@pytest.mark.parametrize("von, erwartet", [
    ("Felix <GMX-Test@gmx.de>", "gmx-test@gmx.de"),
    ("gmx-test@gmx.de", "gmx-test@gmx.de"),
    ("  <gmx-test@gmx.de>  ", "gmx-test@gmx.de"),
    ('"Baumann, Felix" <felix@own.de>', "felix@own.de"),
    ('"felix@own.de" <attacker@evil.de>', "attacker@evil.de"),
    ("felix@own.de <attacker@evil.de>", None),       # Adresse vor dem <...> (N-a)
    ("Felix Baumann <felix@own.de>", "felix@own.de"),
    ("attacker@evil.de, <felix@own.de>", None),      # Adressliste, eigene zuletzt
    ("g: attacker@evil.de;, <felix@own.de>", None),  # Gruppe vor dem <...>
    ("attacker@evil.de <felix@own.de>", None),
    ('"Baumann; Felix: x@y" <felix@own.de>', "felix@own.de"),   # nur in "..." erlaubt
    # Re-Review 3: Escapes im Zitat, Kommentare, offene Zitate
    (r'"a\"b"@evil.de, "c" <felix@own.de>', None),
    ('(" ) attacker@evil.de ( ") <felix@own.de>', None),
    ('"Felix Baumann <felix@own.de>', None),            # Zitat nie geschlossen
    ('Felix "Baumann <felix@own.de>', None),
    (r'"Felix \" <felix@own.de>', None),           # geschlossen nur per Escape
    ('(Firma) <felix@own.de>', None),                    # Kommentar: fail closed
    (r'"Baumann \"FB\" Felix" <felix@own.de>', "felix@own.de"),
    ('<felix@own.de>', "felix@own.de"),
    ('"Felix <felix@own.de>" <attacker@evil.de>', None),
    ("<felix@own.de>, <attacker@evil.de>", None),
    ("<felix@own.de> attacker@evil.de", None),
    ("felix@own.de, attacker@evil.de", None),
    ("fe\u212alix@own.de", None),            # KELVIN SIGN, lower() koennte falten
    ("", None),
    ("   ", None),
    (None, None),
])
def test_absender_streng(von, erwartet):
    import post_erledigt
    with server.pool.connection() as conn:
        z = conn.execute(f"select {post_erledigt.absender_streng_sql('m')} as a "
                         "from (select %s::text as von) m", (von,)).fetchone()
    assert z["a"] == erwartet


def test_absender_streng_nach_decode_header():
    """N-a: `von` entsteht per decode_header ueber den ganzen Kopf - ein kodiertes Wort
    darf keine zweite Adresse vor die eigene schieben."""
    import email
    import post_erledigt
    import postfach
    roh = email.message_from_string(
        "From: attacker@evil.de =?utf-8?q?=2C_=3Cfelix=40own.de=3E?=\n\nx")
    von = postfach._kopf(roh, "From")
    assert "<felix@own.de>" in von and von.startswith("attacker@evil.de")
    with server.pool.connection() as conn:
        z = conn.execute(f"select {post_erledigt.absender_streng_sql('m')} as a "
                         "from (select %s::text as von) m", (von,)).fetchone()
    assert z["a"] is None


def test_absender_sql_alias_geprueft_und_alter_wert_gleich():
    import post_erledigt
    assert post_erledigt.ABSENDER_SQL == (
        "lower(coalesce(substring(m.von from '<([^>]+)>'), trim(m.von)))")
    assert post_erledigt.absender_sql("t") == post_erledigt.ABSENDER_SQL.replace("m.", "t.")
    for f in (post_erledigt.absender_sql, post_erledigt.absender_streng_sql,
              post_unterhaltung._eigen_sql, post_unterhaltung._bezug_zulaessig_sql):
        for schlecht in ("m.von", "m; drop", "", "1m"):
            with pytest.raises(ValueError):
                f(schlecht)


def test_leere_kontoadresse_ist_nie_eigen():
    """F4: ein Konto ohne Adresse und eine Mail ohne Absender ergeben keinen Zwilling."""
    _konto()
    with server.pool.connection() as conn:
        conn.execute("insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
                     "values ('felix', 'leer-k', 'gmx', '  ', 'ui')")
    raus = _roh("gmx-test", "raus@x", richtung="gesendet", bereich="privat",
                text="Privater Text")
    f = _roh("gmx-test", "raus@x", tage=1, bereich="privat", sensibel=True, von="")
    assert post_unterhaltung.nachziehen()["geerbt"] == 0
    assert _zeile_von(raus)["sensibel"] is False and _unt(raus) != _unt(f)


def test_alle_zwillinge_zaehlen():
    """Nit: sensibel aus dem einen, privat aus dem anderen Zwilling - beides gilt."""
    _konto()
    _roh("gmx-test", "selbst@x", bereich="business", sensibel=True, von=EIGEN)
    _roh("gmx-test", "selbst@x", tage=1, bereich="privat", von=EIGEN)
    raus = _roh("gmx-test", "selbst@x", tage=2, richtung="gesendet", bereich="business")
    post_unterhaltung.nachziehen()
    z = _zeile_von(raus)
    assert z["sensibel"] is True and z["bereich"] == "privat" and z["text"] is None


def test_sperrschluessel_traegt_das_schema(monkeypatch):
    _konto()
    mail_id = _roh("gmx-test", "m1@x", zuordnen=False)
    schluessel = []

    class Mitschnitt:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, params=None):
            if "pg_advisory_xact_lock" in sql:
                schluessel.append(params[0])
            return self._conn.execute(sql, params)
    with server.pool.connection() as conn, conn.transaction():
        post_unterhaltung.zuordnen(Mitschnitt(conn), mail_id)
    assert schluessel == [f"post_unterhaltung:{server.SCHEMA}:felix"]

# --- Task 7: Unterhaltung lesen ---------------------------------------------

def _felix():
    import post_struktur
    return post_struktur.Betrachter(name="felix", leitung=False, abteilungen=())


def test_unterhaltung_lesen_beide_richtungen():
    import post_struktur
    _konto()
    m1 = _roh("gmx-test", "u1@x", tage=0)
    m2 = _roh("gmx-test", "u2@x", tage=1, richtung="gesendet", in_reply_to="u1@x")
    m3 = _roh("gmx-test", "u3@x", tage=2, in_reply_to="u2@x")
    fremd = _roh("gmx-test", "u9@x", tage=1)
    for start in (m1, m2, m3):
        eintraege = post_struktur.unterhaltung_lesen(_felix(), start)
        assert [str(x["id"]) for x in eintraege] == [m1, m2, m3]
        assert [x["richtung"] for x in eintraege] == ["eingang", "gesendet", "eingang"]
        assert {"id", "richtung", "von", "an", "betreff", "datum", "auszug"} <= set(eintraege[0])
    assert [str(x["id"]) for x in post_struktur.unterhaltung_lesen(_felix(), fremd)] == [fremd]


def test_unterhaltung_respektiert_sichtbarkeit(monkeypatch):
    import post_struktur
    _konto()
    m1 = _roh("gmx-test", "v1@x", bereich="business")
    m2 = _roh("gmx-test", "v2@x", tage=1, richtung="gesendet", in_reply_to="v1@x",
              bereich="business")
    anna = post_struktur.Betrachter(name="anna", leitung=True, abteilungen=("Vertrieb",))
    assert post_struktur.unterhaltung_lesen(anna, m1) == []
    assert post_struktur.unterhaltung_lesen(_felix(), "kein-uuid") == []
    monkeypatch.setenv("POST_BESITZER", "felix")
    eintraege = post_struktur.unterhaltung_lesen(post_struktur.BETREIBER_AGENT, m1)
    gesendet = [x for x in eintraege if str(x["id"]) == m2]
    assert gesendet and gesendet[0]["auszug"] is None and gesendet[0]["an"] is None
    monkeypatch.delenv("POST_BESITZER")
    assert post_struktur.unterhaltung_lesen(post_struktur.BETREIBER_AGENT, m1) == []


def test_unterhaltung_lesen_grenze_behaelt_neueste_und_angesehene():
    import post_struktur
    _konto()
    ids = [_roh("gmx-test", "g1@x", tage=0)]
    for n in range(2, 6):
        ids.append(_roh("gmx-test", f"g{n}@x", tage=n - 1, in_reply_to=f"g{n - 1}@x"))
    neueste = post_struktur.unterhaltung_lesen(_felix(), ids[4], grenze=3)
    assert [str(x["id"]) for x in neueste] == ids[2:]
    aelteste = post_struktur.unterhaltung_lesen(_felix(), ids[0], grenze=3)
    assert [str(x["id"]) for x in aelteste] == [ids[0], ids[3], ids[4]]


def test_sichtbar_sql_alias_und_standard_unveraendert(monkeypatch):
    import post_struktur as ps
    monkeypatch.setenv("POST_BESITZER", "felix")
    anna = ps.Betrachter(name="anna", leitung=True, abteilungen=("Vertrieb",))
    assert ps.sichtbar_sql(_felix()) == ("(m.besitzer = %s)", ["felix"])
    assert ps.sichtbar_sql(anna) == ("(m.besitzer = %s)", ["anna"])
    assert ps.sichtbar_sql(ps.BETREIBER_AGENT) == (
        "(m.bereich = 'business' and m.sensibel is false and m.besitzer = %s)", ["felix"])
    assert ps.sichtbar_sql(_felix(), "u") == ("(u.besitzer = %s)", ["felix"])
    w, p = ps.sichtbar_sql(ps.BETREIBER_AGENT, "u")
    assert "m." not in w and w.count("u.") == 3 and p == ["felix"]
    monkeypatch.delenv("POST_BESITZER")
    assert ps.sichtbar_sql(ps.BETREIBER_AGENT, "u") == ("false", [])
