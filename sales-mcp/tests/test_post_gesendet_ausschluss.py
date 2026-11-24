"""Gesendete Mails ueberall dort ausschliessen, wo nur Eingang gemeint ist
(Post-Assistent Stufe 1, Task 6).

Verteidigt: Faecher, Listen, Warteschlangen, Aufraeumen und Tagesgrenze meinen nur
eingehende Post; die Suche findet beide Richtungen; der Agent sieht eine gesendete
Mail nur als Kopf; schreibende Routen und Bot-Werkzeuge lehnen gesendete Mails mit
festem Text ab und aendern nichts. Nur gegen sales_test.
"""
import inspect
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
import ui  # noqa: E402
import bewerbungs_eingang  # noqa: E402
import post_abholen  # noqa: E402
import post_anweisung  # noqa: E402
import post_einordnung  # noqa: E402
import post_erledigt  # noqa: E402
import post_freigabe  # noqa: E402
import post_herkunft  # noqa: E402
import post_neu_einordnen  # noqa: E402
import post_ordnen  # noqa: E402
import post_struktur as ps  # noqa: E402
import post_werbung  # noqa: E402
import post_ziel  # noqa: E402
import ui_post  # noqa: E402
from gateway import GatewayTransient  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

BESITZER = "t6_felix"
EIGENE_ADRESSE = "t6-felix@firma.example"
HOST = {"host": "127.0.0.1:8791"}
ROUTEN_TEXT = "Gesendete Mails lassen sich hier nicht ändern."
BOT_FEHLER = "Diese Mail wurde gesendet und lässt sich nicht beantworten oder einstufen."
EINGANG = "eingang"
FILTER = "richtung = 'eingang'"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


def _leeren():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_mails, sales_test.post_konten, "
                     "sales_test.post_regeln, sales_test.post_loeschfreigaben cascade")
        conn.execute("delete from sales_test.leads where lower(email) = %s", (EIGENE_ADRESSE,))
        conn.execute("delete from sales_test.benutzer_abteilungen where benutzer = %s",
                     (BESITZER,))
        conn.execute("delete from sales_test.benutzer where name = %s", (BESITZER,))


@pytest.fixture
def welt(monkeypatch):
    """Ein Konto mit je einer eingehenden Zeile (eingeordnet, Fach Kunden, ziel null)
    und einer gesendeten Zeile. Beide business und nicht sensibel, damit auch der
    Agent sie sehen koennte; beide tragen dasselbe Suchwort."""
    vorher = ui.UI_SESSION_SECRET
    ui.UI_SESSION_SECRET = "test-geheimnis-nur-fuer-t6"
    monkeypatch.setenv("POST_BESITZER", BESITZER)
    _leeren()
    with server.pool.connection() as conn:
        conn.execute("insert into sales_test.benutzer (name, rolle, passwort_hash, aktiv, "
                     "leitung) values (%s, 'freigeben', 'x', true, false)", (BESITZER,))
        konto = conn.execute(
            "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) "
            "values (%s, 'haupt', 'gmx', %s, 'env') returning id",
            (BESITZER, EIGENE_ADRESSE)).fetchone()["id"]
        eingang = conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, an, "
            "betreff, text, auszug, datum, bereich, fach, sensibel, status, richtung, ordner, "
            "einordnung_quelle) values (%s, 1, 't6-ein@x', %s, 'Kunde <kunde@kunde.example>', "
            "%s, 'Projektplan Frage', 'Wie steht der Projektplan?', 'Wie steht', now(), "
            "'business', 'Kunden & Anfragen', false, 'eingeordnet', 'eingang', 'INBOX', "
            "'modell') returning id", (konto, BESITZER, EIGENE_ADRESSE)).fetchone()["id"]
        gesendet = conn.execute(
            "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, an, "
            "betreff, text, auszug, datum, bereich, sensibel, status, richtung, ordner, "
            "ordner_uid, kalenderteil, dringlichkeit) values (%s, 2, 't6-raus@x', %s, %s, "
            "'kunde@kunde.example', 'Re: Projektplan Frage', 'Entwurfstext zum Projektplan', "
            "'Entwurfstext', now(), 'business', false, 'gesendet', 'gesendet', 'Gesendet', 5, "
            "true, 'heute') returning id",
            (konto, BESITZER, EIGENE_ADRESSE)).fetchone()["id"]
    yield {"konto": str(konto), "eingang": str(eingang), "gesendet": str(gesendet)}
    ui.UI_SESSION_SECRET = vorher
    _leeren()


def _b():
    return ps.betrachter_laden(BESITZER)


def _zeile(mail_id) -> dict:
    return server._q("select * from post_mails where id = %s", (mail_id,))[0]


def _setzen(mail_id, **werte) -> None:
    sets = ", ".join(f"{k} = %s" for k in werte)
    server._q(f"update post_mails set {sets} where id = %s returning id",
              (*werte.values(), mail_id))


def _ids(zeilen) -> set:
    return {str(z["id"]) for z in zeilen}


def _client():
    c = TestClient(ui.app)
    c.cookies.set(ui.SITZUNG_COOKIE, ui._sitzung_bauen(BESITZER, time.time() + 3600))
    return c


# --- Listen, Faecher, Zahlen ------------------------------------------------------

def test_listen_und_faecher_ohne_gesendete(welt, monkeypatch):
    assert _ids(ps.mails_suchen(_b())) == {welt["eingang"]}
    for ansicht in ps.ZIEL_ANSICHTEN:
        _setzen(welt["gesendet"], ziel=None if ansicht == "aufmerksamkeit" else ansicht)
        _setzen(welt["eingang"], ziel=None if ansicht == "aufmerksamkeit" else ansicht)
        zeilen = server._q(f"select m.id from post_mails m where m.besitzer = %s "
                           f"and {ps.ziel_sql(ansicht)}", (BESITZER,))
        assert _ids(zeilen) == {welt["eingang"]}, ansicht
    _setzen(welt["gesendet"], ziel=None)
    _setzen(welt["eingang"], ziel=None)

    seite = _client().get("/post", headers=HOST, follow_redirects=False)
    assert seite.status_code == 200
    # faecher_zahlen: nur die eingehende Mail, kein Topf „(ohne Fach)“ fuer die gesendete.
    assert 'Alle <span class="zaehler">1</span>' in seite.text
    assert "(ohne Fach)" not in seite.text
    assert "Noch nicht eingeordnet" not in seite.text
    # kontostand: eine eingeordnete, nichts Neues, kein Fehler.
    assert '<td data-label="Eingeordnet">1</td>' in seite.text
    assert '<td data-label="Neu">0</td>' in seite.text
    assert "Re: Projektplan Frage" not in seite.text

    monkeypatch.setattr(post_ziel, "ALTBESTAND_AB", date(2026, 1, 1))
    for mid in (welt["eingang"], welt["gesendet"]):
        _setzen(mid, ziel="posteingang", abgeglichen_am=datetime.now(timezone.utc))
    zeilen, gesamt = post_erledigt.mails_offen(_b())
    assert _ids(zeilen) == {welt["eingang"]} and gesamt == 1


def test_suche_findet_beide_richtungen(welt):
    zeilen = ps.mails_suchen(_b(), suche="Projektplan")
    assert _ids(zeilen) == {welt["eingang"], welt["gesendet"]}
    assert {str(z["id"]): z["richtung"] for z in zeilen} == {
        welt["eingang"]: "eingang", welt["gesendet"]: "gesendet"}
    # Ausdruecklich gewaehlte Richtung gilt auch ohne Suche; Unbekanntes liefert nichts.
    assert _ids(ps.mails_suchen(_b(), richtung="gesendet")) == {welt["gesendet"]}
    assert _ids(ps.mails_suchen(_b(), suche="Projektplan", richtung="eingang")) == {
        welt["eingang"]}
    assert ps.mails_suchen(_b(), richtung="quer") == []


def test_kein_ziel_kein_verschieben_fuer_gesendete(welt, monkeypatch):
    post_ziel.ziele_aktualisieren()
    assert _zeile(welt["gesendet"])["ziel"] is None
    assert _zeile(welt["eingang"])["ziel"] is not None      # Kontrolle: Eingang bekam eins
    assert post_ziel.ziel_frisch(welt["gesendet"]) is None

    # Auch mit (kuenstlich) gesetztem Ziel bewegt post_ordnen eine gesendete Mail nie.
    _setzen(welt["eingang"], ziel="posteingang")            # liegt schon in der INBOX
    _setzen(welt["gesendet"], ziel="zur_info")
    monkeypatch.setattr(post_ordnen, "MODUS", "voll")
    zeilen = server._q(post_ordnen._OFFENE_SQL, {"konto": welt["konto"], "besitzer": BESITZER,
                                                 "voll": True, "n": 50})
    assert welt["gesendet"] not in _ids(zeilen)
    aufrufe = []

    def verbinden(zeile):
        aufrufe.append(zeile["kennung"])
        raise AssertionError("post_ordnen darf fuer gesendete Mails nicht verbinden")
    bilanz = post_ordnen.ordnen(verbinden=verbinden)
    assert aufrufe == []
    assert (bilanz["verschoben"], bilanz["geloescht"], bilanz["fehler"]) == (0, 0, 0)
    assert _zeile(welt["gesendet"])["ordner"] == "Gesendet"


def test_warteschlangen_ohne_gesendete(welt, monkeypatch):
    # Kuenstlich so, als waere die gesendete Zeile ungeprueft und unversucht.
    _setzen(welt["gesendet"], geprueft_am=None, versuche=0, pruef_versuche=0,
            enthaelt_anweisung=True, anweisung_entscheid=None)
    _setzen(welt["eingang"], enthaelt_anweisung=True, anweisung_entscheid=None)

    gesehen = []

    def nachpruefen(mail, konto):
        gesehen.append(mail["id"])
        return "fehler"

    def einordnen(mail, konto):
        gesehen.append(mail["id"])
        raise GatewayTransient("pause")
    monkeypatch.setattr(post_abholen, "_nachpruefen_eine", nachpruefen)
    monkeypatch.setattr(post_einordnung, "einordnen", einordnen)
    post_abholen.einordnen_offene(50)
    assert welt["gesendet"] not in gesehen
    assert welt["eingang"] in gesehen                       # Kontrolle: Eingang wird nachgeprueft

    alt = server._q(f"select m.id from post_mails m where {post_neu_einordnen._altbestand('m.')}")
    assert welt["gesendet"] not in _ids(alt)
    assert post_freigabe.offene_mails(BESITZER) == len(_ids(alt))
    assert sum(j["eingeordnet"] for j in post_freigabe.jahre(BESITZER)) == 1

    herkunft = server._q(f"select id {post_herkunft._OFFEN_SQL}", (welt["konto"],))
    assert _ids(herkunft) == {welt["eingang"]}

    wartet = server._q(f"select m.id from post_mails m where {post_anweisung._WARTET_SQL}")
    assert _ids(wartet) == {welt["eingang"]}

    # Gesendete Zeilen kosten nie einen Modellaufruf: auch kuenstliche Kosten zaehlen nicht.
    vorher = post_abholen.modellaufrufe_heute()
    _setzen(welt["gesendet"], modellaufrufe=7, eingeordnet_am=datetime.now(timezone.utc))
    assert post_abholen.modellaufrufe_heute() == vorher


def test_eingang_filter_steht_in_jeder_eingangs_abfrage():
    """Der Status allein ist nicht der Vertrag: jede Eingangs-Abfrage nennt die Richtung.
    sichtbar_sql bleibt ohne Richtungsfilter (die Suche braucht beide)."""
    teile = {
        "ziel_sql": [ps.ziel_sql(z) for z in ps.ZIEL_ANSICHTEN],
        "AGENT_LESBAR_SQL": [ps.AGENT_LESBAR_SQL],
        "post_ordnen._OFFENE_SQL": [post_ordnen._OFFENE_SQL],
        "post_erledigt": [post_erledigt.offen_sql(), post_erledigt._kandidaten_sql()],
        "post_freigabe._LOESCHBAR": [post_freigabe._LOESCHBAR],
        "post_neu_einordnen._altbestand": [post_neu_einordnen._altbestand("m.")],
        "post_herkunft._OFFEN_SQL": [post_herkunft._OFFEN_SQL],
        "post_anweisung._WARTET_SQL": [post_anweisung._WARTET_SQL],
    }
    for name, sqls in teile.items():
        for sql in sqls:
            assert FILTER in sql, name
    for b in (ps.BETREIBER_AGENT, ps.Betrachter(BESITZER, False, ())):
        assert "richtung" not in ps.sichtbar_sql(b)[0]


# Abfragen, die im Funktionsrumpf stehen (keine Modulkonstante): derselbe Waechter ueber
# den SQL-Text, hier der Quelltext der Funktion. Die Zahl ist die der Eingangs-Abfragen
# darin - faellt einer der ausdruecklichen Filter weg, sinkt sie. Viele dieser Stellen
# sind heute nur ueber den Status-CHECK sicher, das Verhalten allein faende es nicht.
@pytest.mark.parametrize("modul, funktion, anzahl", [
    (post_ziel, "_bleibt", 1),
    (post_ziel, "ziel_frisch", 1),
    (post_ziel, "ziele_aktualisieren", 2),          # Lesen und Schreiben
    (post_werbung, "bleibt_immer_absender", 1),
    (post_werbung, "regel_vorschlagen", 1),
    (post_neu_einordnen, "_unklar_laufend", 1),
    (post_freigabe, "jahre", 1),
    (post_freigabe, "offene_mails", 1),
    (post_abholen, "einordnen_offene", 2),          # neu und nachpruefen
    (post_abholen, "modellaufrufe_heute", 4),       # vier Kostenarten
    (post_abholen, "_kopf_zeilen", 1),
    (post_anweisung, "entscheiden", 1),
    (server, "_post_uid_aufloesen", 1),
    (server, "_sammelstelle_leer", 1),
    (post_erledigt, "erledigen", 1),
    (post_erledigt, "wieder_oeffnen", 1),
    (bewerbungs_eingang, "_mails", 1),
    (ui_post, "routen", 3),                         # faecher_zahlen, konten_sichtbar, kontostand
])
def test_eingang_filter_in_funktionsrumpf(modul, funktion, anzahl):
    quelle = inspect.getsource(getattr(modul, funktion))
    assert quelle.count(FILTER) == anzahl, f"{modul.__name__}.{funktion}"


# --- Schreibende Routen ----------------------------------------------------------

@pytest.mark.parametrize("pfad, daten", [
    ("korrigieren", {"bereich": "business", "fach": "Rechnungen"}),
    ("vorschlag", {"wahl": "sortierer"}),
    ("ziel", {"ziel": "zur_info"}),
    ("erledigt", {"art": "erledigt"}),
    ("wieder-offen", {}),
    ("kontakt", {}),
])
def test_schreibende_routen_lehnen_gesendete_ab(welt, pfad, daten):
    """Review Focus 5: fester Text, die ganze Zeile unveraendert, kein Kontakt."""
    vorher = _zeile(welt["gesendet"])
    r = _client().post(f"/post/mail/{welt['gesendet']}/{pfad}",
                       data={**daten, "csrf": ui.CSRF_TOKEN}, headers=HOST,
                       follow_redirects=False)
    assert r.status_code == 400, (pfad, r.status_code)
    assert ROUTEN_TEXT in r.text
    assert _zeile(welt["gesendet"]) == vorher
    assert not server._q("select 1 from leads where lower(email) = %s", (EIGENE_ADRESSE,))


def test_schreibende_route_gilt_weiter_fuer_eingang(welt):
    r = _client().post(f"/post/mail/{welt['eingang']}/ziel",
                       data={"ziel": "zur_info", "csrf": ui.CSRF_TOKEN}, headers=HOST,
                       follow_redirects=False)
    assert r.status_code == 303
    assert _zeile(welt["eingang"])["ziel"] == "zur_info"


def test_erledigen_und_wieder_oeffnen_lehnen_gesendete_ab(welt):
    assert post_erledigt.erledigen(_b(), welt["gesendet"], "erledigt") is False
    _setzen(welt["gesendet"], erledigt_am=datetime.now(timezone.utc), erledigt_art="erledigt")
    vorher = _zeile(welt["gesendet"])
    assert post_erledigt.wieder_oeffnen(_b(), welt["gesendet"]) is False
    assert _zeile(welt["gesendet"]) == vorher


# --- Agent / Bot -----------------------------------------------------------------

def test_agent_liste_ohne_gesendete_suche_nur_kopf(welt):
    # Kuenstlich „geprueft und unbedenklich“: die Sperre darf nicht nur an geprueft_am haengen.
    for mid in (welt["eingang"], welt["gesendet"]):
        _setzen(mid, geprueft_am=datetime.now(timezone.utc), enthaelt_anweisung=False)
    liste = json.loads(server.postfach_lesen())
    assert {m["uid"] for m in liste["mails"]} == {f"post:{welt['eingang']}"}

    such = json.loads(server.postfach_lesen(suche="Projektplan"))
    mails = {m["uid"]: m for m in such["mails"]}
    assert set(mails) == {f"post:{welt['eingang']}", f"post:{welt['gesendet']}"}
    g = mails[f"post:{welt['gesendet']}"]
    assert g["von"] == EIGENE_ADRESSE and g["betreff"] == "Re: Projektplan Frage"
    # M5: der Treffer sagt, dass er gesendet ist und sich nicht beantworten laesst.
    assert g["richtung"] == "gesendet"
    assert g["hinweis"] == server.AGENT_HINWEIS["gesendet"]
    assert "gesendet" in g["hinweis"] and "nicht beantworten" in g["hinweis"]
    assert g["auszug"] is None and g["dringlichkeit"] is None and g["kalenderteil"] is False
    assert "Entwurfstext" not in json.dumps(such, ensure_ascii=False)
    # Kontrolle: die eingehende, gepruefte Mail ist lesbar.
    assert "hinweis" not in mails[f"post:{welt['eingang']}"]
    assert mails[f"post:{welt['eingang']}"]["richtung"] == "eingang"

    einzeln = json.loads(server.postfach_mail_lesen(f"post:{welt['gesendet']}"))
    assert einzeln["text"] is None and einzeln["an"] is None and einzeln["anhaenge"] == []
    assert einzeln["hinweis"] == server.AGENT_HINWEIS["nicht_geprueft"]


def test_beantworten_lehnt_gesendete_ab(welt, monkeypatch):
    imap = []

    def kein_imap(*a, **k):
        imap.append(a)
        raise AssertionError("kein IMAP-Zugriff fuer gesendete Mails")
    for name in ("eingerichtet", "lesen", "verschieben", "konfiguriert"):
        monkeypatch.setattr(server.postfach, name, kein_imap)
    entwuerfe = server._q("select count(*) as n from drafts")[0]["n"]
    uid = f"post:{welt['gesendet']}"
    assert json.loads(server.mail_beantworten(uid, "Danke!")) == {"fehler": BOT_FEHLER}
    assert json.loads(server.mail_einstufen(uid, "spam", "Betrug")) == {"fehler": BOT_FEHLER}
    assert imap == []
    assert server._q("select count(*) as n from drafts")[0]["n"] == entwuerfe


def test_sammelstelle_nur_mit_gesendeten_gilt_als_leer(welt):
    assert server._sammelstelle_leer() is False
    server._q("delete from post_mails where id = %s returning id", (welt["eingang"],))
    assert server._sammelstelle_leer() is True


def test_bewerbungen_ohne_gesendete(welt):
    zeilen = bewerbungs_eingang._mails(welt["konto"], BESITZER,
                                       datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert _ids(zeilen) == {welt["eingang"]}
