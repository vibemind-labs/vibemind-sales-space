"""Gesendet-Ordner lesend abholen (Post-Assistent Stufe 1, Task 3).

DB-Tests nur gegen sales_test. Die IMAP-Attrappe aus test_post_abholen meldet jeden
schreibenden Befehl und jedes `select` ohne readonly=True als Testfehler.
"""
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_post_abholen import (  # noqa: E402,F401  (Fixtures wirken nur im eigenen Namensraum)
    Attrappe, _einordnung, _konto, _mail, _mails, _zeile, kein_modell, saubere_tabellen, schema_wache)

import post_abholen  # noqa: E402
import post_einordnung  # noqa: E402
import server  # noqa: E402

ORDNER = "Gesendet"


def _raus(message_id="<g1@x>", an="Anna Beispiel <anna@example.org>", betreff="Angebot",
          text="Hallo Anna, anbei das Angebot.", datum="Mon, 02 Nov 2026 11:00:00 +0100") -> bytes:
    m = EmailMessage()
    m["From"] = "gmx-test@gmx.de"
    m["To"] = an
    m["Subject"] = betreff
    m["Date"] = datum
    m["Message-ID"] = message_id
    m.set_content(text)
    return m.as_bytes()


def _gesendet_mails() -> list:
    return _mails("richtung = 'gesendet'")


def _stand() -> dict | None:
    with server.pool.connection() as conn:
        return conn.execute("select * from post_ordner_stand").fetchone()


def test_gesendete_mails_landen_mit_status_gesendet():
    _konto()
    kasten = Attrappe({}, ordner={ORDNER: {1: _raus("<g1@x>"), 2: _raus("<g2@x>", betreff="Zwei")}},
                      sent=ORDNER)
    assert post_abholen.gesendet_abholen(_zeile("gmx-test"), kasten) == 2
    rows = _gesendet_mails()
    assert [r["imap_uid"] for r in rows] == [1, 2]
    assert {r["richtung"] for r in rows} == {"gesendet"}
    assert {r["status"] for r in rows} == {"gesendet"}
    assert {r["ordner"] for r in rows} == {ORDNER}
    assert all(r["geprueft_am"] is None and r["fach"] is None
               and r["einordnung_quelle"] is None for r in rows)
    assert {r["bereich"] for r in rows} == {_zeile("gmx-test")["standard_bereich"]}
    assert rows[0]["kopf_nachgelesen"] is True
    assert kasten.selects and all(s == (f'"{ORDNER}"', True) for s in kasten.selects)
    assert kasten.verboten == []
    stand = _stand()
    assert stand["ordner"] == ORDNER and stand["letzte_uid"] == 2
    assert stand["altbestand_fertig"] is True and stand["uidvalidity"] == 1
    # Der INBOX-Stand bleibt unberuehrt.
    assert _zeile("gmx-test")["letzte_uid"] is None


def test_gesendet_zaehlt_nicht_zur_tagesgrenze(monkeypatch):
    _konto()
    vorher = post_abholen.modellaufrufe_heute()
    kasten = Attrappe({}, ordner={ORDNER: {1: _raus("<g1@x>"), 2: _raus("<g2@x>")}}, sent=ORDNER)
    post_abholen.gesendet_abholen(_zeile("gmx-test"), kasten)
    assert post_abholen.modellaufrufe_heute() == vorher

    def verboten(*a, **k):
        pytest.fail("fuer gesendete Mails darf kein Modell gerufen werden")
    monkeypatch.setattr(post_einordnung.einordnen, "__defaults__", (verboten,))
    monkeypatch.setattr(post_einordnung.nachpruefen, "__defaults__", (verboten,))
    assert post_abholen.einordnen_offene(10) == 0
    assert {r["status"] for r in _gesendet_mails()} == {"gesendet"}
    assert post_abholen.modellaufrufe_heute() == vorher


def test_mail_an_mich_selbst_zwei_zeilen():
    _konto()
    selbst = _raus("<selbst@x>", an="gmx-test@gmx.de", betreff="Notiz")
    kasten = Attrappe({1: selbst}, ordner={ORDNER: {1: selbst}}, sent=ORDNER)
    zeile = _zeile("gmx-test")
    assert post_abholen.konto_abholen(zeile, kasten) == 1
    assert post_abholen.gesendet_abholen(zeile, kasten) == 1
    rows = _mails("message_id = 'selbst@x'")
    assert sorted(r["richtung"] for r in rows) == ["eingang", "gesendet"]
    assert {r["status"] for r in rows if r["richtung"] == "gesendet"} == {"gesendet"}
    # Ein weiterer Lauf legt nichts doppelt an.
    assert post_abholen.gesendet_abholen(_zeile("gmx-test"), kasten) == 0
    assert len(_mails()) == 2


def test_uidvalidity_wechsel_trennt_richtungen():
    _konto()
    a, b, c = (_raus(f"<{n}@x>", betreff=n.upper()) for n in "abc")
    kasten = Attrappe({1: _mail("<e1@x>"), 2: _mail("<e2@x>")},
                      ordner={ORDNER: {1: a, 2: b}}, sent=ORDNER,
                      ordner_uidvalidity={ORDNER: 7})
    post_abholen.konto_abholen(_zeile("gmx-test"), kasten)
    post_abholen.gesendet_abholen(_zeile("gmx-test"), kasten)
    # Nur der Gesendet-Ordner wird neu nummeriert; A und B sind dort nicht mehr.
    neu = Attrappe({1: _mail("<e1@x>"), 2: _mail("<e2@x>")}, ordner={ORDNER: {1: c}},
                   sent=ORDNER, ordner_uidvalidity={ORDNER: 8})
    post_abholen.konto_abholen(_zeile("gmx-test"), neu)
    assert post_abholen.gesendet_abholen(_zeile("gmx-test"), neu) == 1
    assert [r["imap_uid"] for r in _mails("richtung = 'eingang'")] == [1, 2]
    assert sorted(r["imap_uid"] for r in _gesendet_mails()) == [-2, -1, 1]
    assert _stand()["uidvalidity"] == 8
    assert _zeile("gmx-test")["uidvalidity"] == 1
    # Umgekehrt: Wechsel nur in INBOX laesst die gesendeten Zeilen stehen.
    inbox_neu = Attrappe({1: _mail("<e9@x>")}, uidvalidity=2, ordner={ORDNER: {1: c}},
                         sent=ORDNER, ordner_uidvalidity={ORDNER: 8})
    post_abholen.konto_abholen(_zeile("gmx-test"), inbox_neu)
    assert sorted(r["imap_uid"] for r in _gesendet_mails()) == [-2, -1, 1]
    assert sorted(r["imap_uid"] for r in _mails("richtung = 'eingang'")) == [-2, -1, 1]


@pytest.mark.parametrize("fall", ["ohne-sent", "select-nein"])
def test_ohne_gesendet_ordner_laeuft_eingang_weiter(monkeypatch, fall):
    _konto()
    if fall == "ohne-sent":
        kasten = Attrappe({1: _mail("<e1@x>")}, ordner={ORDNER: {1: _raus()}}, sent=None)
    else:
        kasten = Attrappe({1: _mail("<e1@x>")}, ordner={ORDNER: {1: _raus()}}, sent=ORDNER,
                          select_nein={ORDNER})
    monkeypatch.setattr(post_abholen.post_konten, "verbinden", lambda zeile: kasten)
    monkeypatch.setattr(post_einordnung, "einordnen", lambda mail, konto: _einordnung())
    bilanz = post_abholen.eine_runde()
    assert bilanz["abgeholt"] == 1 and bilanz["konten_fehler"] == 0
    assert bilanz["gesendet"] == 0
    assert bilanz["gesendet_fehler"] == (1 if fall == "select-nein" else 0)
    assert len(_mails("richtung = 'eingang'")) == 1 and _gesendet_mails() == []
    assert kasten.verboten == []


def test_runde_holt_gesendet_auf_derselben_verbindung(monkeypatch):
    _konto()
    kasten = Attrappe({1: _mail("<e1@x>")}, ordner={ORDNER: {1: _raus()}}, sent=ORDNER)
    verbindungen = []
    monkeypatch.setattr(post_abholen.post_konten, "verbinden",
                        lambda zeile: verbindungen.append(1) or kasten)
    monkeypatch.setattr(post_einordnung, "einordnen", lambda mail, konto: _einordnung())
    bilanz = post_abholen.eine_runde()
    assert verbindungen == [1]
    assert bilanz["abgeholt"] == 1 and bilanz["gesendet"] == 1
    assert sorted(r["richtung"] for r in _mails()) == ["eingang", "gesendet"]


def test_ordnerwechsel_gilt_als_neuanfang():
    _konto()
    mails = {1: _raus("<g1@x>", betreff="Eins"), 2: _raus("<g2@x>", betreff="Zwei")}
    post_abholen.gesendet_abholen(_zeile("gmx-test"),
                                  Attrappe({}, ordner={ORDNER: mails}, sent=ORDNER))
    neu = Attrappe({}, ordner={"Gesendete Objekte": mails}, sent="Gesendete Objekte")
    assert post_abholen.gesendet_abholen(_zeile("gmx-test"), neu) == 0
    assert neu.geholt == [1, 2]                 # von vorn geholt
    rows = _gesendet_mails()
    assert len(rows) == 2 and {r["imap_uid"] for r in rows} == {1, 2}
    assert {r["ordner"] for r in rows} == {"Gesendete Objekte"}
    assert _stand()["ordner"] == "Gesendete Objekte"


def test_gesendet_sensibel_nach_empfaenger():
    _konto()
    kasten = Attrappe({}, ordner={ORDNER: {
        1: _raus("<s1@x>", an="security@bank.example", betreff="Rueckfrage"),
        2: _raus("<s2@x>", betreff="Ihr Sicherheitscode"),
        3: _raus("<s3@x>", betreff="Normal"),
    }}, sent=ORDNER)
    post_abholen.gesendet_abholen(_zeile("gmx-test"), kasten)
    rows = {r["imap_uid"]: r for r in _gesendet_mails()}
    for uid in (1, 2):
        assert rows[uid]["sensibel"] is True
        assert rows[uid]["text"] is None and rows[uid]["auszug"] is None
        assert rows[uid]["an"] is None and rows[uid]["anhaenge"] == []
    assert rows[3]["sensibel"] is False and rows[3]["text"] and rows[3]["an"]


def test_ganze_historie_in_stapeln():
    _konto()
    kasten = Attrappe({}, ordner={ORDNER: {u: _raus(f"<h{u}@x>", betreff=f"B{u}")
                                           for u in range(1, 121)}}, sent=ORDNER)
    summe = 0
    for lauf in range(3):
        summe += post_abholen.gesendet_abholen(_zeile("gmx-test"), kasten, stapel=50)
        if lauf < 2:
            assert _stand()["altbestand_fertig"] is False
    assert summe == 120 and len(_gesendet_mails()) == 120
    assert _stand()["altbestand_fertig"] is True and _stand()["letzte_uid"] == 120
    assert post_abholen.gesendet_abholen(_zeile("gmx-test"), kasten, stapel=50) == 0


def test_groessen_ohne_ordnernamen(monkeypatch, capsys):
    _konto("felix", "gmx-test")
    _konto("felix", "ohne-sent")
    raus = {1: _raus(), 2: _raus("<g2@x>"), 3: _raus("<g3@x>")}
    kaesten = {"gmx-test": Attrappe({}, ordner={"Meine Post Raus": raus}, sent="Meine Post Raus"),
               "ohne-sent": Attrappe({1: _mail()})}
    monkeypatch.setattr(post_abholen.post_konten, "verbinden",
                        lambda zeile: kaesten[zeile["kennung"]])
    assert post_abholen.main(["--gesendet-groessen"]) == 0
    aus = capsys.readouterr().out
    assert "gmx-test 3" in aus and "ohne-sent unbekannt" in aus
    assert "Meine Post Raus" not in aus
    assert _mails() == [] and _stand() is None          # speichert nichts
    assert all(k.verboten == [] for k in kaesten.values())
