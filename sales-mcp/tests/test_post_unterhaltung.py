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
         besitzer="felix") -> str:
    """Eine Mail einfuegen und - wie `_speichern` - in derselben Transaktion zuordnen."""
    konto = _zeile(kennung)
    with server.pool.connection() as conn, conn.transaction():
        mail_id = conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, an, betreff, "
            "datum, text, auszug, anhaenge, status, bereich, richtung, in_reply_to, referenzen, "
            "sensibel, message_id_ersatz) values (%s, %s, %s, %s, 'a@example.org', "
            "'b@example.org', 'Betreff', %s, %s, %s, '{x.pdf}', %s, %s, %s, %s, %s, %s, %s) "
            "returning id",
            (konto["id"], next(_uids), message_id, besitzer, BASIS + timedelta(days=tage),
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
    post_unterhaltung.nachziehen()
    z = _zeile_von(antwort)
    assert z["sensibel"] is True and z["bereich"] == "privat"
    assert z["text"] is None and z["auszug"] is None and z["an"] is None
    assert z["anhaenge"] == []


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
    assert set(bilanz["unterhaltung"]) == {"zugeordnet", "geerbt"}
