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
          text="Hallo Anna, anbei das Angebot.", datum="Mon, 02 Nov 2026 11:00:00 +0100",
          cc=None) -> bytes:
    m = EmailMessage()
    m["From"] = "gmx-test@gmx.de"
    m["To"] = an
    m["Subject"] = betreff
    if cc:
        m["Cc"] = cc
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
    kasten = Attrappe({1: _mail("<e1@x>")}, ordner={ORDNER: {1: _raus("<g1@x>"),
                                                            2: _raus("<g2@x>")}}, sent=ORDNER)
    zeile = _zeile("gmx-test")
    post_abholen.konto_abholen(zeile, kasten)
    vorher = post_abholen.modellaufrufe_heute()
    post_abholen.gesendet_abholen(_zeile("gmx-test"), kasten)
    assert post_abholen.modellaufrufe_heute() == vorher

    aufrufe = []
    monkeypatch.setattr(post_einordnung, "einordnen",
                        lambda mail, konto: aufrufe.append(mail["id"]) or _einordnung())
    # Positive Kontrolle: die eingehende `neu`-Zeile wird sortiert, die gesendeten nicht.
    assert post_abholen.einordnen_offene(10) == 1
    eingang = _mails("richtung = 'eingang'")[0]
    assert aufrufe == [str(eingang["id"])] and eingang["status"] == "eingeordnet"
    assert {r["status"] for r in _gesendet_mails()} == {"gesendet"}


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
    # Kein Logger-/Socket-Zustand darf in andere Tests lecken (propagate=False, Handler).
    monkeypatch.setattr(post_abholen, "_logging_einrichten", lambda: None)
    monkeypatch.setattr(post_abholen.socket, "setdefaulttimeout", lambda *a: None)
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


def test_gesendet_sensibel_nach_cc(monkeypatch):
    _konto()
    kasten = Attrappe({}, ordner={ORDNER: {
        1: _raus("<c1@x>", betreff="Rueckfrage", cc="Bank <security@bank.example>")}}, sent=ORDNER)
    post_abholen.gesendet_abholen(_zeile("gmx-test"), kasten)
    r = _gesendet_mails()[0]
    assert r["sensibel"] is True and r["text"] is None and r["an"] is None


def test_unlesbare_gesendete_mail(monkeypatch):
    _konto()
    monkeypatch.setattr(post_abholen, "_mail_zerlegen",
                        lambda *a: (_ for _ in ()).throw(ValueError("kaputt")))
    kasten = Attrappe({}, ordner={ORDNER: {1: _raus()}}, sent=ORDNER)
    assert post_abholen.gesendet_abholen(_zeile("gmx-test"), kasten) == 1
    r = _gesendet_mails()[0]
    assert r["status"] == "gesendet" and r["fehler"] and r["kopf_nachgelesen"] is False
    assert _stand()["letzte_uid"] == 1


def test_ordner_groesse_liest_nur_die_klammerliste():
    import post_imap

    class K:
        def status(self, name, namen):
            return "OK", [b'"Post MESSAGES 9" (MESSAGES 4)']
    assert post_imap.ordner_groesse(K(), "Post MESSAGES 9") == 4

    class Ohne:
        def status(self, name, namen):
            return "OK", [b'"Post MESSAGES 9" (UIDNEXT 3)']
    assert post_imap.ordner_groesse(Ohne(), "Post MESSAGES 9") is None


# --- Antwortkoepfe des Bestands nachlesen (Task 5) ------------------------------

def _alt(konto, uid, message_id, *, ordner="INBOX", ordner_uid=None, datum="2026-10-01T10:00:00Z",
         richtung="eingang", ersatz=False):
    """Eine Bestandszeile ohne Antwortkoepfe (kopf_nachgelesen = false)."""
    gesendet = richtung == "gesendet"
    with server.pool.connection() as conn:
        return conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, betreff, "
            "datum, status, richtung, ordner, ordner_uid, message_id_ersatz, bereich) "
            "values (%s, %s, %s, 'felix', 'a@x.example', 'Angebot', %s::timestamptz, %s, %s, %s, "
            "%s, %s, 'privat') returning id",
            (konto["id"], uid, message_id, datum, "gesendet" if gesendet else "neu", richtung,
             ordner, ordner_uid, ersatz)).fetchone()["id"]


def _zeile_id(mail_id) -> dict:
    with server.pool.connection() as conn:
        return conn.execute("select * from post_mails where id = %s", (mail_id,)).fetchone()


def _antwort(message_id, in_reply_to=None, references=None) -> bytes:
    return _mail(message_id=message_id, in_reply_to=in_reply_to, references=references)


def test_bestand_bekommt_antwortkoepfe():
    konto = _konto()
    raus = _alt(konto, 1, "s1@x", richtung="gesendet", ordner="Gesendet",
                datum="2026-09-30T10:00:00Z")
    alt = _alt(konto, 7, "m7@x")
    kasten = Attrappe({7: _antwort("<m7@x>", in_reply_to="<s1@x>", references="<a@x> <s1@x>")})
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 1
    z = _zeile_id(alt)
    assert z["kopf_nachgelesen"] is True and z["in_reply_to"] == "s1@x"
    assert z["referenzen"] == ["a@x", "s1@x"]
    assert z["unterhaltung"] is not None
    assert _zeile_id(raus)["unterhaltung"] == z["unterhaltung"]
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 0   # nichts mehr offen


def test_gesendete_zeilen_bleiben_unberuehrt():
    konto = _konto()
    raus = _alt(konto, 1, "s1@x", richtung="gesendet", ordner="Gesendet")
    kasten = Attrappe({}, ordner={"Gesendet": {1: _antwort("<s1@x>", in_reply_to="<x@x>")}})
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 0
    assert _zeile_id(raus)["kopf_nachgelesen"] is False and kasten.befehle == []


def test_verschobene_mail_am_neuen_ort():
    konto = _konto()
    alt = _alt(konto, 3, "m3@x", ordner="Zur Info", ordner_uid=9)
    kasten = Attrappe({3: _antwort("<andere@x>")},
                      ordner={"Zur Info": {9: _antwort("<m3@x>", in_reply_to="<v@x>")}})
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 1
    assert [(o, b, u) for o, b, u, _ in kasten.befehle] == [("Zur Info", "fetch", "9")]
    z = _zeile_id(alt)
    assert z["in_reply_to"] == "v@x" and z["kopf_nachgelesen"] is True


def test_fremde_message_id_wird_nicht_uebernommen():
    konto = _konto()
    alt = _alt(konto, 7, "m7@x")
    kasten = Attrappe({7: _antwort("<fremd@x>", in_reply_to="<s1@x>", references="<s1@x>")})
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 1
    z = _zeile_id(alt)
    assert z["in_reply_to"] is None and z["referenzen"] == [] and z["kopf_nachgelesen"] is True


def test_fehlende_mail_und_platzhalter_werden_nur_markiert():
    konto = _konto()
    weg = _alt(konto, 5, "m5@x")
    ersatz = _alt(konto, 6, "x:6@sales-post", ersatz=True)
    kasten = Attrappe({6: _antwort("<x:6@sales-post>", in_reply_to="<s1@x>")})
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 2
    for i in (weg, ersatz):
        z = _zeile_id(i)
        assert z["kopf_nachgelesen"] is True and z["in_reply_to"] is None


def test_nur_peek():
    konto = _konto()
    _alt(konto, 7, "m7@x")
    _alt(konto, 8, "m8@x", ordner="Zur Info", ordner_uid=2)
    kasten = Attrappe({7: _antwort("<m7@x>")}, ordner={"Zur Info": {2: _antwort("<m8@x>")}})
    post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten)
    assert len(kasten.befehle) == 2 and kasten.geholt == [] and kasten.verboten == []
    for _o, befehl, _u, teil in kasten.befehle:
        assert befehl == "fetch"
        assert teil == "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID IN-REPLY-TO REFERENCES)])"
        assert "RFC822" not in teil
    assert all(readonly is True for _m, readonly in kasten.selects)


def test_stapel_und_reihenfolge():
    konto = _konto()
    with server.pool.connection() as conn:
        for n in range(1, 451):
            conn.execute(
                "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, status, "
                "datum, bereich) values (%s, %s, %s, 'felix', 'a@x.example', 'neu', "
                "'2026-01-01T00:00:00Z'::timestamptz + make_interval(mins => %s), 'privat')",
                (konto["id"], n, f"m{n}@x", n))
    kasten = Attrappe({})
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten, stapel=200) == 200
    erledigt = [r["imap_uid"] for r in _mails("kopf_nachgelesen")]
    assert erledigt == list(range(251, 451))
    assert len(kasten.befehle) == 1                      # ein UID FETCH je Ordner


def test_uidvalidity_abweichung_laesst_inbox_zeilen_liegen():
    konto = _konto()
    with server.pool.connection() as conn:
        conn.execute("update post_konten set uidvalidity = 5 where id = %s", (konto["id"],))
    inbox = _alt(konto, 7, "m7@x")
    moved = _alt(konto, 8, "m8@x", ordner="Zur Info", ordner_uid=2)
    kasten = Attrappe({7: _antwort("<m7@x>")}, uidvalidity=6,
                      ordner={"Zur Info": {2: _antwort("<m8@x>")}})
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 1
    assert _zeile_id(inbox)["kopf_nachgelesen"] is False
    assert _zeile_id(moved)["kopf_nachgelesen"] is True


def test_negative_inbox_uid_wird_uebersprungen():
    konto = _konto()
    alt = _alt(konto, -3, "m3@x")
    kasten = Attrappe({})
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 0
    assert _zeile_id(alt)["kopf_nachgelesen"] is False


def test_zuordnung_scheitert_kopf_bleibt(monkeypatch):
    konto = _konto()
    alt = _alt(konto, 7, "m7@x")
    import post_unterhaltung
    monkeypatch.setattr(post_unterhaltung, "zuordnen",
                        lambda conn, mail_id: (_ for _ in ()).throw(ValueError("kaputt")))
    kasten = Attrappe({7: _antwort("<m7@x>", in_reply_to="<s1@x>")})
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 1
    z = _zeile_id(alt)
    assert z["in_reply_to"] == "s1@x" and z["kopf_nachgelesen"] is True


def test_runde_trennt_kopf_fehler(monkeypatch):
    _konto()
    monkeypatch.setattr(post_abholen.post_konten, "aktive_konten", lambda: [_zeile("gmx-test")])
    kasten = Attrappe({})
    monkeypatch.setattr(post_abholen.post_konten, "verbinden", lambda z: kasten)
    monkeypatch.setattr(post_abholen, "koepfe_nachlesen",
                        lambda z, k, **kw: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(post_abholen, "_einordnen", lambda b: None)
    monkeypatch.setattr(post_abholen, "_unterhaltungen_nachziehen", lambda b: None)
    monkeypatch.setattr(post_abholen, "_anweisungen_nachziehen", lambda b: None)
    monkeypatch.setattr(post_abholen, "_aufraeumen", lambda b: None)
    bilanz = post_abholen.eine_runde()
    assert bilanz["koepfe_fehler"] == 1 and bilanz["koepfe"] == 0 and bilanz["konten_fehler"] == 0


# --- Fix round 1 -------------------------------------------------------------------

@pytest.mark.parametrize("nach_literal", [False, True], ids=["uid-vor-literal", "uid-nach-literal"])
def test_uid_vor_oder_nach_dem_literal(nach_literal):
    konto = _konto()
    alt = _alt(konto, 7, "m7@x")
    kasten = Attrappe({7: _antwort("<m7@x>", in_reply_to="<s1@x>")})
    kasten.uid_nach_literal = nach_literal
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 1
    assert _zeile_id(alt)["in_reply_to"] == "s1@x"


def test_antwort_ohne_erkennbare_uid_laesst_zeilen_offen():
    konto = _konto()
    alt = _alt(konto, 7, "m7@x")
    kasten = Attrappe({7: _antwort("<m7@x>", in_reply_to="<s1@x>")})
    kasten.uid_nirgends = True
    fehler = {}
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten, fehler=fehler) == 0
    assert _zeile_id(alt)["kopf_nachgelesen"] is False and fehler["n"] == 1


def test_ordnerfehler_stoppt_die_anderen_ordner_nicht():
    konto = _konto()
    a = _alt(konto, 3, "a@x", ordner="Alpha", ordner_uid=1, datum="2026-10-05T10:00:00Z")
    b = _alt(konto, 4, "b@x", ordner="Beta", ordner_uid=2, datum="2026-10-01T10:00:00Z")
    kasten = Attrappe({}, ordner={"Alpha": {1: _antwort("<a@x>")},
                                  "Beta": {2: _antwort("<b@x>", in_reply_to="<s1@x>")}})
    kasten.kopf_fehler["Alpha"] = RuntimeError("busy")
    fehler = {}
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten, fehler=fehler) == 1
    assert _zeile_id(a)["kopf_nachgelesen"] is False
    assert _zeile_id(b)["in_reply_to"] == "s1@x" and fehler["n"] == 1


def test_verbindungsabbruch_beendet_sauber():
    import imaplib
    konto = _konto()
    a = _alt(konto, 3, "a@x", ordner="Alpha", ordner_uid=1, datum="2026-10-05T10:00:00Z")
    b = _alt(konto, 4, "b@x", ordner="Beta", ordner_uid=2, datum="2026-10-01T10:00:00Z")
    kasten = Attrappe({}, ordner={"Alpha": {1: _antwort("<a@x>")}, "Beta": {2: _antwort("<b@x>")}})
    kasten.kopf_fehler["Alpha"] = imaplib.IMAP4.abort("socket error")
    fehler = {}
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten, fehler=fehler) == 0
    assert fehler["n"] == 1
    assert _zeile_id(a)["kopf_nachgelesen"] is False and _zeile_id(b)["kopf_nachgelesen"] is False
    assert {o for o, *_ in kasten.befehle} == {"Alpha"}   # Beta wurde nicht mehr angefasst


def test_inbox_select_scheitert_andere_ordner_laufen():
    konto = _konto()
    inbox = _alt(konto, 7, "m7@x")
    moved = _alt(konto, 8, "m8@x", ordner="Zur Info", ordner_uid=2)
    kasten = Attrappe({7: _antwort("<m7@x>")}, ordner={"Zur Info": {2: _antwort("<m8@x>")}},
                      select_nein={"INBOX"})
    fehler = {}
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten, fehler=fehler) == 1
    assert _zeile_id(inbox)["kopf_nachgelesen"] is False
    assert _zeile_id(moved)["kopf_nachgelesen"] is True and fehler["n"] == 1


def test_nur_verschobene_zeilen_waehlen_inbox_nicht():
    konto = _konto()
    _alt(konto, 8, "m8@x", ordner="Zur Info", ordner_uid=2)
    kasten = Attrappe({}, ordner={"Zur Info": {2: _antwort("<m8@x>")}})
    post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten)
    assert all("INBOX" not in m for m, _r in kasten.selects) and kasten.selects


def test_fehlender_ordner_markiert_die_zeilen():
    konto = _konto()
    z = _alt(konto, 8, "m8@x", ordner="Weg", ordner_uid=2)
    kasten = Attrappe({})
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 1
    assert _zeile_id(z)["kopf_nachgelesen"] is True and kasten.befehle == []


@pytest.mark.parametrize("uid", [None, 0, -4])
def test_verschobene_zeile_ohne_gueltige_ordner_uid(uid):
    """Kein Abruf moeglich: nur markiert, blockiert den Stapel nicht."""
    konto = _konto()
    z = _alt(konto, 8, "m8@x", ordner="Zur Info", ordner_uid=uid)
    kasten = Attrappe({}, ordner={"Zur Info": {}})
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 1
    assert _zeile_id(z)["kopf_nachgelesen"] is True and kasten.befehle == []


def test_message_id_vergleich_ignoriert_klammern_und_leerraum():
    konto = _konto()
    alt = _alt(konto, 7, "ABC@x")
    kasten = Attrappe({7: _antwort("<ABC@x>")})
    kasten.kopf_roh[7] = "Message-ID:  <ABC@x> \r\nIn-Reply-To: <s@x>\r\n"
    assert post_abholen.koepfe_nachlesen(_zeile("gmx-test"), kasten) == 1
    assert _zeile_id(alt)["in_reply_to"] == "s@x"
