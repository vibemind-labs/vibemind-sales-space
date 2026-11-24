"""Die Zaehlarten des Abholers sagen dieselbe Zahl wie die Seiten der Oberflaeche. Gegen sales_test.

Regel (Koordination VibeMind, 23.11.2026): Die Zahl im Antwortsatz muss die sein, die der Ladenbesitzer
auf der zugehoerigen Seite sieht. Je Art werden beide Wege gegen dieselben Testdaten gerechnet:

- freigaben_zaehlen: Menue-Zaehler /freigaben (ohne Zusatz aus Marketing und Bewerbungen) und
  `anzahl_fehlgeschlagen` aus server.entwuerfe_offen.
- post_offen: Menue-Zaehler /posteingang und die Gesamtzahl der Seite Mails fuer den Ladenbesitzer; eine
  Mail eines anderen Teammitglieds zaehlt nicht.
- termine_heute: Tagesansicht des Kalenders (kalender_sicht.ereignisse) und die Kachel "Termine heute".

Kein echter Kalender: kalender.termine_lesen ist in jedem Test eine Attrappe. Kein Netz zu Marketing oder
zur Bewerbungs-Zentrale: deren Zaehler sind auf 0 gestellt.
"""
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
server = pytest.importorskip("server")        # braucht die Test-Datenbank; lokal ohne sie: uebersprungen
import auftrag_abholer as ab  # noqa: E402
import kalender  # noqa: E402
import kalender_sicht  # noqa: E402
import post_erledigt  # noqa: E402
import post_struktur  # noqa: E402
import ui  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")
BESITZER = "t9_inhaber"
ANDERE = "t9_kollegin"
NAMEN = (BESITZER, ANDERE)


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test", f"Testsuite laeuft gegen Schema '{server.SCHEMA}', erlaubt ist nur sales_test"


def _aufraeumen():
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.post_mails, sales_test.post_konten, sales_test.activities, "
                     "sales_test.drafts, sales_test.leads, sales_test.eigene_termine cascade")
        conn.execute("delete from sales_test.benutzer_abteilungen where benutzer = any(%s)", (list(NAMEN),))
        conn.execute("delete from sales_test.benutzer where name = any(%s)", (list(NAMEN),))


@pytest.fixture(autouse=True)
def welt(monkeypatch):
    from datetime import date
    import post_ziel
    monkeypatch.setattr(post_ziel, "ALTBESTAND_AB", date(2020, 1, 1))
    monkeypatch.setenv("POST_BESITZER", BESITZER)
    # Nie ein echter Kalender, nie Netz zu Marketing oder Bewerbungen.
    monkeypatch.setattr(kalender, "termine_lesen", lambda *a, **k: ([], None))
    monkeypatch.setattr(ui.ui_freigabe_newsletter, "anzahl_offen", lambda _ui: 0)
    monkeypatch.setattr(ui.ui_freigabe_bewerbung, "anzahl_offen", lambda _ui: 0)
    monkeypatch.setattr(server.medien, "liste", lambda *a, **k: [])
    monkeypatch.setattr(ab, "ANBINDUNG", {})
    _aufraeumen()
    with server.pool.connection() as conn:
        for name in NAMEN:
            conn.execute("insert into sales_test.benutzer (name, rolle, passwort_hash, aktiv, leitung) "
                         "values (%s, 'freigeben', 'x', true, false)", (name,))
    ab.anbinden(server, post_erledigt, post_struktur, kalender_sicht, kalender)
    yield
    _aufraeumen()


def _lead(name="Kontakt T9"):
    return str(server._q("insert into leads (name, source) values (%s, 'test') returning id", (name,))[0]["id"])


def _entwurf(status, kanal="whatsapp"):
    server._q("insert into drafts (lead_id, channel, recipient, body, status) values (%s, %s, 'x', 'Text', %s) "
              "returning id", (_lead(), kanal, status))


def _offene_mail(besitzer, nr):
    konto = server._q(
        "insert into post_konten (besitzer, kennung, anbieter, adresse, quelle) values (%s, %s, 'gmx', %s, 'ui') "
        "on conflict (kennung) do update set besitzer = excluded.besitzer returning id",
        (besitzer, f"k-{besitzer}", f"{besitzer}@example.org"))[0]["id"]
    m = server._q(
        "insert into post_mails (konto_id, imap_uid, message_id, besitzer, von, betreff, text, auszug, bereich, "
        "fach, sensibel, anhaenge, status, einordnung_quelle) values (%s, %s, %s, %s, 'a@example.org', 'Betreff', "
        "'Text', 'Text', 'business', 'Kunden & Anfragen', false, '{}', 'eingeordnet', 'modell') returning id",
        (konto, nr, f"t9-m{nr}", besitzer))[0]["id"]
    server._q("update post_mails set ziel = 'posteingang', abgeglichen_am = now(), datum = now() - interval '2 hours' "
              "where id = %s returning id", (m,))


def _kundenantwort():
    server._q("insert into activities (lead_id, type, payload, actor, created_at) values "
              "(%s, 'kundenantwort', %s, 'human', now() - interval '1 hour') returning id",
              (_lead(), json.dumps({"kanal": "whatsapp", "text": "Frage", "richtung": "eingehend",
                                    "message_id": "t9-wa"})))


def test_freigaben_zaehlen_wie_menue_und_seite():
    for status in ("pending", "pending", "pending", "failed", "approved", "sent"):
        _entwurf(status)
    _entwurf("approved", kanal="linkedin")            # steht in entwuerfe_offen, wartet aber nicht
    ergebnis = ab.freigaben_zaehlen(server._q, {}, None)
    assert ergebnis["wartend"] == ui._zaehler_abfragen()["/freigaben"] == 3
    assert ergebnis["fehlgeschlagen"] == json.loads(server.entwuerfe_offen())["anzahl_fehlgeschlagen"] == 1


def test_post_offen_wie_menue_und_seite_mails_des_besitzers():
    _kundenantwort()
    _kundenantwort()
    for nr in (1, 2):
        _offene_mail(BESITZER, nr)
    _offene_mail(ANDERE, 3)                            # sieht nur die Kollegin
    ergebnis = ab.post_offen(server._q, {}, None)
    seite_mails = post_erledigt.mails_offen(post_struktur.betrachter_laden(BESITZER))[1]
    assert ergebnis["chats_unbeantwortet"] == ui._zaehler_abfragen()["/posteingang"] == 2
    assert ergebnis["mails_offen"] == seite_mails == 2


def test_termine_heute_wie_tagesansicht_und_startseite(monkeypatch):
    jetzt = datetime.now(BERLIN).replace(hour=12, minute=0, second=0, microsecond=0)
    handy = [{"beginn": jetzt - timedelta(hours=3), "ende": jetzt - timedelta(hours=2), "titel": "a", "ort": "",
              "uid": "t9-1"},
             {"beginn": jetzt + timedelta(hours=2), "ende": jetzt + timedelta(hours=3), "titel": "b", "ort": "",
              "uid": "t9-2"},
             {"beginn": jetzt + timedelta(days=1), "ende": jetzt + timedelta(days=1, hours=1), "titel": "c",
              "ort": "", "uid": "t9-3"}]
    monkeypatch.setattr(kalender, "termine_lesen", lambda *a, **k: (handy, None))
    for _ in range(2):
        server._q("insert into activities (lead_id, type, payload, actor) values (%s, 'termin', %s, 'human') "
                  "returning id", (_lead(), json.dumps({"datum": jetzt.date().isoformat()})))
    ergebnis = ab.termine_heute(server._q, {}, None, jetzt=jetzt)
    von = jetzt.replace(hour=0)
    tagesansicht = kalender_sicht.ereignisse(von, von + timedelta(days=1), BESITZER)
    kachel = server._q(ab.SQL_KUNDENTERMINE_HEUTE, (jetzt.date().isoformat(),))[0]["n"]
    assert ergebnis["anzahl"] == len(tagesansicht["ereignisse"]) == 2
    assert ergebnis["anzahl_kunden"] == kachel == 2
    assert ergebnis["quellen_stumm"] == len(tagesansicht["hinweise"]) == 0


def test_stummer_kalender_wird_gezaehlt(monkeypatch):
    monkeypatch.setattr(kalender, "termine_lesen", lambda *a, **k: ([], "Kalender nicht erreichbar (Timeout)."))
    ergebnis = ab.termine_heute(server._q, {}, None)
    assert ergebnis["quellen_stumm"] >= 1
