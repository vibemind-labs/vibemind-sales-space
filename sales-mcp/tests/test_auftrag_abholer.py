"""Abholer fuer Auftraege an Sales (an = sales, von = brain). Ohne Datenbank, ohne Gateway.

Das Auftragsbuch ist im Speicher nachgebaut: `Buch.q` beantwortet genau die drei Huellen aus
db/auftrag-empfang.sql und die Kontaktsuche.
"""
import json
import logging

import pytest

import auftrag_abholer as ab
import auftrag_empfang
import auftrag_vertrag
import gateway

AID = "0123abcd-0000-4000-8000-000000000001"
K1 = "aaaaaaaa-0000-4000-8000-000000000001"
K2 = "aaaaaaaa-0000-4000-8000-000000000002"
K3 = "aaaaaaaa-0000-4000-8000-000000000003"
ARTEN = auftrag_vertrag.lade()


def auftrag(art="kontakt_finden", version=1, eingabe=None, aid=AID):
    return {"id": aid, "art": art, "art_version": version, "plan_id": "plan-1",
            "eingabe": {"suche": "Muster"} if eingabe is None else eingabe}


class Buch:
    """Mini-Auftragsbuch und Mini-Kontakte hinter `q`."""

    def __init__(self, *offen, kontakte=()):
        self.offen = list(offen)
        self.kontakte = list(kontakte)
        self.fertig: dict[str, dict] = {}
        self.fehler: dict[str, str] = {}
        self.sql: list[str] = []
        self.laeden: list[str] = []
        self.abschluss_ok = True

    def q(self, sql, params=()):
        self.sql.append(sql)
        if "sales_empfang_abschliessen" in sql or "sales_empfang_fehler" in sql:
            self.laeden.append(params[2])
        if "sales_empfang_naechster" in sql:
            self.laden = params[0]
            self.laeden.append(params[0])
            return [{"a": self.offen.pop(0) if self.offen else None}]
        if "sales_empfang_abschliessen" in sql:
            if self.abschluss_ok:
                self.fertig[params[0]] = json.loads(params[1])
            return [{"ok": self.abschluss_ok}]
        if "sales_empfang_fehler" in sql:
            self.fehler[params[0]] = params[1]
            return [{"ok": True}]
        if "from leads" in sql:
            self.muster = params[0]
            return list(self.kontakte)
        for tabelle, zeile in self.zahlen.items():      # Zaehlarten: nur count(*) auf je einer Tabelle
            if f"from {tabelle}" in sql:
                assert sql.lstrip().startswith("select count(*)"), sql
                self.zaehlparams = params
                return [zeile]
        raise AssertionError("unerwartete Abfrage")

    zahlen: dict = {}


def nie_verborgen(_enrichment):
    return False


def lauf(buch, **kw):
    kw.setdefault("verborgen", nie_verborgen)
    return ab.durchgang(buch.q, ARTEN, **kw)


# --- Datenbank-Schicht ---------------------------------------------------------------------------

def test_empfang_ruft_nur_die_drei_huellen():
    buch = Buch(auftrag())
    assert auftrag_empfang.naechster(buch.q, "sales")["id"] == AID
    assert auftrag_empfang.naechster(buch.q, "sales") is None
    assert auftrag_empfang.abschliessen(buch.q, AID, {"treffer": [], "anzahl": 0}, "sales") is True
    assert auftrag_empfang.fehler(buch.q, AID, "x" * 500, "sales") is True
    assert buch.laeden == ["sales", "sales", "sales", "sales"]     # jede Huelle bekommt den Laden
    assert len(buch.fehler[AID]) <= 300
    assert all("auftrag.sales_empfang_" in s for s in buch.sql)


# --- kontakt_finden ------------------------------------------------------------------------------

def test_kontakt_finden_meldet_treffer_ohne_adresse_und_nummer():
    buch = Buch(auftrag(), kontakte=[
        {"id": K1, "name": "Muster GmbH", "company": None, "enrichment": {}},
        {"id": K2, "name": "Erika Muster", "company": "Beispiel AG", "enrichment": None}])
    assert lauf(buch) == {"fertig": 1, "fehler": 0}
    ergebnis = buch.fertig[AID]
    assert ergebnis == {"anzahl": 2, "treffer": [
        {"kontakt_id": K1, "titel": "Muster GmbH", "link": f"/kontakte/{K1}"},
        {"kontakt_id": K2, "titel": "Erika Muster (Beispiel AG)", "link": f"/kontakte/{K2}"}]}
    suche = next(s for s in buch.sql if "from leads" in s)
    assert "email" not in suche and "phone" not in suche      # gesucht und gelesen wird nur der Name
    assert buch.muster == "%Muster%"


def test_kontakt_finden_laesst_verborgene_kontakte_weg():
    buch = Buch(auftrag(), kontakte=[
        {"id": K1, "name": "Muster privat", "company": None, "enrichment": {"_privat": {"privat": True}}},
        {"id": K2, "name": "Muster offen", "company": None, "enrichment": {}}])
    lauf(buch, verborgen=lambda e: bool(e and e.get("_privat")))
    assert [t["kontakt_id"] for t in buch.fertig[AID]["treffer"]] == [K2]


def test_kontakt_finden_hoechstens_zehn_und_platzhalter_entschaerft():
    viele = [{"id": f"aaaaaaaa-0000-4000-8000-{i:012d}", "name": f"Muster {i}", "company": None,
              "enrichment": {}} for i in range(25)]
    buch = Buch(auftrag(eingabe={"suche": "100%_x\\"}), kontakte=viele)
    lauf(buch)
    assert buch.fertig[AID]["anzahl"] == 10 and len(buch.fertig[AID]["treffer"]) == 10
    assert buch.muster == "%100\\%\\_x\\\\%"


def test_langer_name_wird_gekuerzt_statt_abgelehnt():
    buch = Buch(auftrag(), kontakte=[{"id": K1, "name": "M" * 400, "company": "F" * 400, "enrichment": {}}])
    assert lauf(buch) == {"fertig": 1, "fehler": 0}
    assert len(buch.fertig[AID]["treffer"][0]["titel"]) <= 200


# --- Ablehnungen ---------------------------------------------------------------------------------

@pytest.mark.parametrize("a, grund", [
    (auftrag(art="gibt_es_nicht"), ab.GRUND_UNBEKANNT),
    (auftrag(version=2), ab.GRUND_UNBEKANNT),
    (auftrag(version=None), ab.GRUND_UNBEKANNT),
    (auftrag(art="post_pruefen", version=1, eingabe={"zeitraum": "heute", "entwuerfe_anlegen": False}),
     ab.GRUND_UNBEKANNT),                                   # Version 1 gilt nicht mehr
    (auftrag(art="post_pruefen", version=2, eingabe={"zeitraum": "heute", "entwuerfe_anlegen": False}), ab.GRUND_GESPERRT),
    (auftrag(eingabe={"suche": "x"}), ab.GRUND_EINGABE),
    (auftrag(eingabe={"suche": "Muster", "mehr": 1}), ab.GRUND_EINGABE),
])
def test_abgelehnt_mit_grund_und_ohne_ausfuehrung(a, grund):
    buch = Buch(a, kontakte=[{"id": K1, "name": "Muster", "company": None, "enrichment": {}}])
    assert lauf(buch) == {"fertig": 0, "fehler": 1}
    assert buch.fehler[AID].startswith(grund)
    assert not buch.fertig
    assert not any("from leads" in s for s in buch.sql)


def test_freigeschaltet_ist_ohne_umgebung_nur_kontakt_finden(monkeypatch):
    monkeypatch.delenv("AUFTRAG_ARTEN_FREI", raising=False)
    assert ab.arten_frei() == {"kontakt_finden"}
    monkeypatch.setenv("AUFTRAG_ARTEN_FREI", " kontakt_finden , post_pruefen ")
    assert ab.arten_frei() == {"kontakt_finden", "post_pruefen"}
    monkeypatch.setenv("AUFTRAG_ARTEN_FREI", "")
    assert ab.arten_frei() == set()


def test_freigeschaltete_art_ohne_ausfuehrer_wird_abgelehnt():
    a = auftrag(art="post_pruefen", version=2, eingabe={"zeitraum": "heute", "entwuerfe_anlegen": False})
    buch = Buch(a)
    assert lauf(buch, frei={"post_pruefen"}, testkontakt=K3) == {"fertig": 0, "fehler": 1}
    assert buch.fehler[AID].startswith(ab.GRUND_NICHT_GEBAUT)


def test_veraendernde_art_ohne_testkontakt_wird_abgelehnt():
    a = auftrag(art="post_pruefen", version=2, eingabe={"zeitraum": "heute", "entwuerfe_anlegen": True})
    buch = Buch(a)
    assert lauf(buch, frei={"post_pruefen"}, testkontakt="") == {"fertig": 0, "fehler": 1}
    assert buch.fehler[AID].startswith(ab.GRUND_KEIN_TESTKONTAKT)


def test_ergebnis_in_falscher_form_wird_fehler(monkeypatch):
    monkeypatch.setitem(ab.AUSFUEHRER, "kontakt_finden",
                        lambda q, eingabe, verborgen: {"treffer": [{"telefon": "0"}], "anzahl": 1})
    buch = Buch(auftrag())
    assert lauf(buch) == {"fertig": 0, "fehler": 1}
    assert buch.fehler[AID].startswith(ab.GRUND_ERGEBNIS)
    assert not buch.fertig


def test_absturz_beim_ausfuehren_nennt_nur_den_typ(monkeypatch, caplog):
    def kaputt(q, eingabe, verborgen):
        raise RuntimeError("geheimer Inhalt aus einer Zeile")
    monkeypatch.setitem(ab.AUSFUEHRER, "kontakt_finden", kaputt)
    buch = Buch(auftrag(), auftrag(aid="0123abcd-0000-4000-8000-000000000002"))
    with caplog.at_level(logging.INFO, logger="auftrag-abholer"):
        assert lauf(buch) == {"fertig": 0, "fehler": 2}       # der zweite Auftrag wird trotzdem bedient
    assert buch.fehler[AID] == f"{ab.GRUND_ABSTURZ} (RuntimeError)"
    assert "geheimer Inhalt" not in caplog.text


def test_protokoll_nennt_nie_suchtext_oder_namen(caplog):
    buch = Buch(auftrag(eingabe={"suche": "Geheimsuche"}),
                kontakte=[{"id": K1, "name": "Geheimname", "company": None, "enrichment": {}}])
    with caplog.at_level(logging.DEBUG, logger="auftrag-abholer"):
        lauf(buch)
    assert "Geheimsuche" not in caplog.text and "Geheimname" not in caplog.text
    assert AID[:8] in caplog.text


def test_nur_auftraege_des_eigenen_ladens(monkeypatch):
    buch = Buch(auftrag())
    monkeypatch.delenv("LADEN_PRAEFIX", raising=False)
    lauf(buch)
    assert buch.laden == "sales"
    buch = Buch(auftrag())
    monkeypatch.setenv("LADEN_PRAEFIX", "zweiter")
    lauf(buch)
    assert buch.laden == "zweiter"


@pytest.mark.parametrize("schema, laden, erlaubt", [
    ("sales", "sales", True),
    ("sales_test", "sales-test", True),
    ("sales_test", "sales", False),        # die Testinstanz naehme sonst echte Auftraege weg (gleiche Rolle)
    ("sales", "sales-test", False),        # und der Betrieb die der Testinstanz
    ("sales", "zweiter", False),
    ("sales_zweiter", "zweiter", False),   # weitere Laeden haben keinen Zugang zum Auftragsbuch
    ("sales_test", "", False),
])
def test_start_nur_wenn_schema_und_laden_zusammenpassen(schema, laden, erlaubt):
    grund = ab.start_hindernis(schema, laden)
    assert (grund is None) is erlaubt
    if not erlaubt:
        assert schema in grund or "Laden" in grund


def test_durchgang_nimmt_hoechstens_die_grenze():
    buch = Buch(*[auftrag(aid=f"0123abcd-0000-4000-8000-{i:012d}") for i in range(8)])
    assert lauf(buch, hoechstens=3) == {"fertig": 3, "fehler": 0}
    assert len(buch.offen) == 5


def test_abschluss_abgelehnt_zaehlt_nicht_als_fertig():
    buch = Buch(auftrag())
    buch.abschluss_ok = False                                   # z. B. Frist inzwischen abgelaufen
    assert lauf(buch) == {"fertig": 0, "fehler": 1}


# --- Ein-Empfaenger-Bedingung --------------------------------------------------------------------

def test_empfaenger_erlaubt_nur_der_eine_testkontakt():
    assert ab.empfaenger_erlaubt(K1, testkontakt=K1) is True
    assert ab.empfaenger_erlaubt(K1.upper(), testkontakt=K1) is True
    assert ab.empfaenger_erlaubt(K2, testkontakt=K1) is False
    assert ab.empfaenger_erlaubt(K1, testkontakt="") is False
    assert ab.empfaenger_erlaubt(K1, testkontakt="kein-uuid") is False
    assert ab.empfaenger_erlaubt(None, testkontakt=K1) is False
    assert ab.empfaenger_erlaubt("", testkontakt="") is False


# --- Uebergabe an die Kennung im Gateway ---------------------------------------------------------

FUNKTION = {"type": "function", "function": {"name": "urteil_abgeben", "parameters": {"type": "object"}}}


def test_ohne_kennung_im_gateway_wird_nichts_gesendet(monkeypatch):
    rufe = []

    def http(methode, url, pfad, token, timeout_s, nutzlast=None, kopf=None):
        rufe.append((methode, pfad))
        return {"data": [{"id": "openclaw/main"}, {"id": "openclaw/auto"}]}
    monkeypatch.setattr(gateway, "_http", http)
    with pytest.raises(gateway.GatewayTransient):
        ab.agent_fragen(AID, "System", "Auftrag", FUNKTION, url="http://gw.invalid", token="t")
    assert rufe == [("GET", "/v1/models")]


def test_uebergabe_geht_nur_an_die_kennung_auftrag(monkeypatch):
    rufe = []

    def http(methode, url, pfad, token, timeout_s, nutzlast=None, kopf=None):
        rufe.append((methode, pfad, nutzlast, kopf))
        if methode == "GET":
            return {"data": [{"id": "openclaw/auftrag"}]}
        return {"choices": [{"message": {"tool_calls": [
            {"function": {"name": "urteil_abgeben", "arguments": "{\"ok\": true}"}}]}}]}
    monkeypatch.setattr(gateway, "_http", http)
    assert ab.agent_fragen(AID, "System", "Auftrag", FUNKTION, url="http://gw.invalid", token="t") == {"ok": True}
    _, _, nutzlast, kopf = rufe[1]
    assert nutzlast["model"] == "openclaw/auftrag"
    assert kopf["x-openclaw-agent-id"] == "auftrag"
    assert kopf["x-openclaw-session-key"] == f"agent:auftrag:vibemind:{AID}"
    assert nutzlast["tool_choice"]["function"]["name"] == "urteil_abgeben"


def test_uebergabe_ohne_gateway_zugang_sendet_nichts(monkeypatch):
    monkeypatch.setattr(gateway, "_http", lambda *a, **k: pytest.fail("darf nicht senden"))
    with pytest.raises(gateway.GatewayTransient):
        ab.agent_fragen(AID, "System", "Auftrag", FUNKTION, url="", token="")


# --- Zaehlarten ----------------------------------------------------------------------------------

from datetime import datetime, timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")
JETZT = datetime(2026, 11, 23, 10, 0, tzinfo=BERLIN)
ALLE = {"kontakt_finden", "termine_heute", "freigaben_zaehlen", "post_offen"}


def zaehlbuch(art, zahlen):
    buch = Buch(auftrag(art=art, eingabe={}))
    buch.zahlen = zahlen
    return buch


def test_freigaben_zaehlen_nur_pending_und_failed():
    buch = zaehlbuch("freigaben_zaehlen", {"drafts": {"wartend": 4, "fehlgeschlagen": 1}})
    assert lauf(buch, frei=ALLE) == {"fertig": 1, "fehler": 0}
    assert buch.fertig[AID] == {"wartend": 4, "fehlgeschlagen": 1}
    zaehlung = next(s for s in buch.sql if "from drafts" in s)
    assert "'pending'" in zaehlung and "'failed'" in zaehlung and "'approved'" not in zaehlung


def test_post_offen_zaehlt_chats_und_mails_ohne_inhalte(monkeypatch):
    monkeypatch.setattr(ab, "ANBINDUNG", {"chats_unbeantwortet": lambda: 5, "mails_offen_sql": lambda: "(true)"})
    buch = zaehlbuch("post_offen", {"post_mails": {"n": 2}})
    assert lauf(buch, frei=ALLE) == {"fertig": 1, "fehler": 0}
    assert buch.fertig[AID] == {"chats_unbeantwortet": 5, "mails_offen": 2}
    assert any("from post_mails m where (true)" in s for s in buch.sql)


def test_termine_heute_zaehlt_nur_was_heute_noch_ansteht(monkeypatch):
    def t(stunden, dauer=1, zone=True):
        b = JETZT + timedelta(hours=stunden)
        b = b if zone else b.replace(tzinfo=None)
        return {"beginn": b, "ende": b + timedelta(hours=dauer), "titel": "geheim", "ort": "geheim"}
    eintraege = [t(-3), t(-1, 2), t(2), t(5, zone=False), t(15), t(30)]   # vorbei, laeuft, 2x heute, morgen
    monkeypatch.setattr(ab, "ANBINDUNG", {"kalender": lambda: (eintraege, [{"quelle": "x", "grund": "y"}])})
    buch = Buch()
    ergebnis = ab.termine_heute(lambda sql, p=(): (buch.sql.append(sql), [{"n": 2}])[1], {}, nie_verborgen,
                                jetzt=JETZT)
    assert ergebnis == {"anzahl": 3, "anzahl_kunden": 2, "quellen_stumm": 1}
    auftrag_vertrag.pruefe_ergebnis(ARTEN["termine_heute"], ergebnis)
    assert "geheim" not in json.dumps(ergebnis)


@pytest.mark.parametrize("art", ["termine_heute", "post_offen"])
def test_zaehlart_ohne_anbindung_endet_mit_fehler(monkeypatch, art):
    monkeypatch.setattr(ab, "ANBINDUNG", {})
    buch = zaehlbuch(art, {"activities": {"n": 0}, "post_mails": {"n": 0}})
    assert lauf(buch, frei=ALLE) == {"fertig": 0, "fehler": 1}
    assert buch.fehler[AID] == f"{ab.GRUND_ABSTURZ} (LookupError)"


def test_zaehlarten_sind_ohne_freischaltung_gesperrt():
    buch = zaehlbuch("freigaben_zaehlen", {"drafts": {"wartend": 1, "fehlgeschlagen": 0}})
    assert lauf(buch) == {"fertig": 0, "fehler": 1}          # Vorgabe: nur kontakt_finden
    assert buch.fehler[AID].startswith(ab.GRUND_GESPERRT)
    assert not any("from drafts" in s for s in buch.sql)


def test_anbinden_liest_nur_die_zahl_aus_dem_posteingang():
    class Server:
        def posteingang(self, stunden):
            assert stunden == 48
            return json.dumps({"anzahl_unbeantwortet": 7, "eintraege": [{"kontakt": "geheim"}]})

        def belegungen(self, tage_voraus):
            return [], []

    class Post:
        @staticmethod
        def offen_sql():
            return "(false)"
    alt = dict(ab.ANBINDUNG)
    try:
        ab.anbinden(Server(), Post)
        assert ab.ANBINDUNG["chats_unbeantwortet"]() == 7
        assert ab.ANBINDUNG["kalender"]() == ([], [])
        assert ab.ANBINDUNG["mails_offen_sql"]() == "(false)"
    finally:
        ab.ANBINDUNG.clear()
        ab.ANBINDUNG.update(alt)
