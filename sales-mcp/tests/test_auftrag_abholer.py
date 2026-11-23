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
        self.abschluss_ok = True

    def q(self, sql, params=()):
        self.sql.append(sql)
        if "sales_empfang_naechster" in sql:
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
        raise AssertionError("unerwartete Abfrage")


def nie_verborgen(_enrichment):
    return False


def lauf(buch, **kw):
    kw.setdefault("verborgen", nie_verborgen)
    return ab.durchgang(buch.q, ARTEN, **kw)


# --- Datenbank-Schicht ---------------------------------------------------------------------------

def test_empfang_ruft_nur_die_drei_huellen():
    buch = Buch(auftrag())
    assert auftrag_empfang.naechster(buch.q)["id"] == AID
    assert auftrag_empfang.naechster(buch.q) is None
    assert auftrag_empfang.abschliessen(buch.q, AID, {"treffer": [], "anzahl": 0}) is True
    assert auftrag_empfang.fehler(buch.q, AID, "x" * 500) is True
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
    (auftrag(art="post_pruefen", eingabe={"zeitraum": "heute", "entwuerfe_anlegen": False}), ab.GRUND_GESPERRT),
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
    a = auftrag(art="post_pruefen", eingabe={"zeitraum": "heute", "entwuerfe_anlegen": False})
    buch = Buch(a)
    assert lauf(buch, frei={"post_pruefen"}, testkontakt=K3) == {"fertig": 0, "fehler": 1}
    assert buch.fehler[AID].startswith(ab.GRUND_NICHT_GEBAUT)


def test_veraendernde_art_ohne_testkontakt_wird_abgelehnt():
    a = auftrag(art="post_pruefen", eingabe={"zeitraum": "heute", "entwuerfe_anlegen": True})
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
