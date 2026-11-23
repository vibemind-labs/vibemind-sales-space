"""Der Auftrag-Abholer: nimmt Auftraege des Gehirns an Sales aus dem Auftragsbuch und erledigt sie.

Weg eines Auftrags (an = sales, von = brain):
1. uebernehmen (offen -> in_arbeit, auftrag_empfang.naechster);
2. Art und Version muessen in auftrag_arten.yaml stehen, sonst `fehler` - nie raten;
3. die Art muss freigeschaltet sein (AUFTRAG_ARTEN_FREI, Vorgabe: nur kontakt_finden);
4. eine veraendernde Art braucht den einen Testkontakt (AUFTRAG_TEST_KONTAKT_ID), sonst `fehler`;
5. Eingabe gegen die Form pruefen, ausfuehren, Ergebnis gegen die Form pruefen;
6. abschliessen (in_arbeit -> fertig) oder `fehler` mit kurzem Grund.

Was hier NIE geschieht: Es wird nichts freigegeben und nichts versendet. Dieser Dienst kennt weder
die Freigabe-Werkzeuge noch einen Versandweg.

kontakt_finden erledigt der Abholer selbst, ohne Sprachmodell. Braucht eine spaetere Art ein
Urteil, fragt er die Kennung `auftrag` im Gateway (agent_fragen): ein Agent OHNE Werkzeuge
(config/openclaw.json, tools.deny ["*"]) mit einem fest vorgegebenen Funktionsaufruf. Der Agent
kann damit nichts aufrufen, auch keine Freigabe; ausgefuehrt wird hier. Vor jeder Uebergabe
prueft gateway.funktion_aufrufen, dass es die Kennung gibt - eine unbekannte Kennung wuerde das
Gateway still MIT allen Werkzeugen anlegen.

Ins Protokoll kommen nur Kennung (gekuerzt), Art und Stand; nie Eingabe, Ergebnis oder Namen.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import uuid

import auftrag_empfang
import auftrag_vertrag
import gateway

LOG = logging.getLogger("auftrag-abholer")

TAKT_S = 2
HOECHSTENS_JE_DURCHGANG = 5
ERLAUBTE_SCHEMAS = ("sales", "sales_test")
AGENT = "auftrag"
TREFFER_HOECHSTENS = 10
TITEL_MAXLAENGE = 200
_STOPP = threading.Event()

# Gruende fuer `fehler` im Auftragsbuch: kurze Saetze ohne Werte aus dem Auftrag.
GRUND_UNBEKANNT = "Auftragsart oder Version ist bei Sales nicht bekannt"
GRUND_GESPERRT = "Auftragsart ist bei Sales nicht freigeschaltet"
GRUND_KEIN_TESTKONTAKT = "Veraendernde Auftragsart ohne festgelegten Testkontakt"
GRUND_NICHT_GEBAUT = "Auftragsart ist bei Sales noch nicht ausfuehrbar"
GRUND_EINGABE = "Eingabe passt nicht zur Form der Auftragsart"
GRUND_ERGEBNIS = "Ergebnis passt nicht zur Form der Auftragsart"
GRUND_ABSTURZ = "Ausfuehrung bei Sales gescheitert"


def arten_frei() -> set[str]:
    """Freigeschaltete Arten. Ohne Umgebungswert nur kontakt_finden; ein leerer Wert schaltet alles ab."""
    roh = os.environ.get("AUFTRAG_ARTEN_FREI")
    if roh is None:
        return {"kontakt_finden"}
    return {teil.strip() for teil in roh.split(",") if teil.strip()}


def _uuid(wert: object) -> str | None:
    try:
        return str(uuid.UUID(str(wert)))
    except (ValueError, AttributeError, TypeError):
        return None


def empfaenger_erlaubt(kontakt_id: object, *, testkontakt: str | None = None) -> bool:
    """Ein-Empfaenger-Bedingung der Testzeit: nur der eine festgelegte Kontakt darf Empfaenger eines
    Entwurfs sein. Fehlt die Festlegung oder ist sie keine Kennung, ist niemand erlaubt."""
    if testkontakt is None:
        testkontakt = os.environ.get("AUFTRAG_TEST_KONTAKT_ID", "")
    erlaubt = _uuid(testkontakt.strip()) if testkontakt else None
    return erlaubt is not None and _uuid(kontakt_id) == erlaubt


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def kontakt_finden(q, eingabe: dict, verborgen) -> dict:
    """Kontakte, deren Name den Suchtext enthaelt. Gelesen werden nur Kennung, Name und Firma;
    Adresse und Nummer verlassen die Datenbank nicht. `verborgen(enrichment)` nimmt private,
    archivierte und zur Loeschung vermerkte Kontakte heraus."""
    zeilen = q("select id, name, company, enrichment from leads "
               "where name ilike %s escape '\\' order by updated_at desc limit 50",
               (_like(eingabe["suche"]),))
    treffer = []
    for z in zeilen:
        if verborgen(z.get("enrichment")):
            continue
        kid = str(z["id"])
        name = str(z.get("name") or "").strip()
        firma = str(z.get("company") or "").strip()
        titel = f"{name} ({firma})" if firma else name
        treffer.append({"kontakt_id": kid, "titel": titel[:TITEL_MAXLAENGE], "link": f"/kontakte/{kid}"})
        if len(treffer) == TREFFER_HOECHSTENS:
            break
    return {"treffer": treffer, "anzahl": len(treffer)}


# Anbindung der Zaehlarten an sales-mcp, gesetzt in main() (anbinden). Nur lesende Wege:
#   "kalender"            () -> (eintraege, luecken)   server.belegungen(tage_voraus=1)
#   "chats_unbeantwortet" () -> int                    server.posteingang: anzahl_unbeantwortet
#   "mails_offen_sql"     () -> str                    post_erledigt.offen_sql()
# Bewusst NICHT benutzt: postfach_lesen (schreibt im Rueckfall), entwuerfe_offen (zaehlt auch
# freigegebene LinkedIn-Entwuerfe mit). Fehlt eine Anbindung, endet der Auftrag mit `fehler`.
ANBINDUNG: dict = {}
ZEITZONE = "Europe/Berlin"


def _anbindung(name: str):
    fn = ANBINDUNG.get(name)
    if fn is None:
        raise LookupError(name)          # nur der Typ geht ins Auftragsbuch
    return fn


def _heute_ende(jetzt):
    from datetime import datetime, time, timedelta
    return datetime.combine(jetzt.date() + timedelta(days=1), time.min, tzinfo=jetzt.tzinfo)


def termine_heute(q, eingabe: dict, verborgen, *, jetzt=None) -> dict:
    """Termine, die heute noch anstehen (alle Kalender, wie sie der Agent sieht), Kundentermine von
    heute laut Kundenakte, und wie viele Kalender gerade nichts sagen. Nur Zahlen."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    jetzt = jetzt or datetime.now(ZoneInfo(ZEITZONE))
    ende = _heute_ende(jetzt)
    eintraege, luecken = _anbindung("kalender")()
    anzahl = 0
    for e in eintraege:
        beginn, schluss = e.get("beginn"), e.get("ende") or e.get("beginn")
        if not (isinstance(beginn, datetime) and isinstance(schluss, datetime)):
            continue
        # Der eigene Kalender kann Zeiten ohne Zone liefern (wie server.py beim Buchen): Ortszeit.
        beginn = beginn if beginn.tzinfo else beginn.replace(tzinfo=jetzt.tzinfo)
        schluss = schluss if schluss.tzinfo else schluss.replace(tzinfo=jetzt.tzinfo)
        if beginn < ende and schluss >= jetzt:
            anzahl += 1
    kunden = q("select count(*) as n from activities a where a.type = 'termin' and a.payload->>'datum' = %s",
               (jetzt.date().isoformat(),))[0]["n"]
    return {"anzahl": min(anzahl, 500), "anzahl_kunden": min(int(kunden), 500),
            "quellen_stumm": min(len(luecken), 50)}


def freigaben_zaehlen(q, eingabe: dict, verborgen) -> dict:
    """Entwuerfe, die auf die Freigabe warten (nur `pending`), und fehlgeschlagene. Nur Zahlen."""
    z = q("select count(*) filter (where status = 'pending') as wartend, "
          "count(*) filter (where status = 'failed') as fehlgeschlagen from drafts")[0]
    return {"wartend": min(int(z["wartend"]), 10000), "fehlgeschlagen": min(int(z["fehlgeschlagen"]), 10000)}


def post_offen(q, eingabe: dict, verborgen) -> dict:
    """Unbeantwortete Kundennachrichten in den Chat-Kanaelen und offene Mails. Nur Zahlen."""
    chats = int(_anbindung("chats_unbeantwortet")())
    mails = q(f"select count(*) as n from post_mails m where {_anbindung('mails_offen_sql')()}")[0]["n"]
    return {"chats_unbeantwortet": min(chats, 10000), "mails_offen": min(int(mails), 10000)}


# Art -> Funktion(q, eingabe, verborgen) -> Ergebnis. Eine Art ohne Eintrag ist nicht ausfuehrbar.
AUSFUEHRER = {"kontakt_finden": kontakt_finden, "termine_heute": termine_heute,
              "freigaben_zaehlen": freigaben_zaehlen, "post_offen": post_offen}


def anbinden(server, post_erledigt) -> None:
    """Die Zaehlarten an die lesenden Wege von sales-mcp haengen (nur in main)."""
    import json

    def chats() -> int:
        roh = server.posteingang(stunden=48)
        daten = json.loads(roh) if isinstance(roh, str) else roh
        return int(daten["anzahl_unbeantwortet"])
    ANBINDUNG.update({"kalender": lambda: server.belegungen(tage_voraus=1),
                      "chats_unbeantwortet": chats,
                      "mails_offen_sql": post_erledigt.offen_sql})


def agent_fragen(aid: str, system: str, auftrag: str, funktion: dict, *,
                 url: str | None = None, token: str | None = None, timeout_s: float = 120) -> dict:
    """Die Kennung `auftrag` im Gateway um ein Urteil in fester Form bitten; liefert die Argumente des
    vorgegebenen Funktionsaufrufs. Gibt es die Kennung nicht oder fehlt der Zugang, wird nichts gesendet."""
    url = os.environ.get("OPENCLAW_URL", "") if url is None else url
    token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "") if token is None else token
    if not url.strip() or not token.strip():
        raise gateway.GatewayTransient("Gateway-Zugang fehlt - nichts gesendet.")
    return gateway.funktion_aufrufen(AGENT, f"agent:{AGENT}:vibemind:{aid}", system, auftrag, funktion,
                                     url=url, token=token, timeout_s=timeout_s)


def _ablehnung(a: dict, arten: dict, frei: set[str], testkontakt: str) -> tuple[object, str | None]:
    """(Auftragsart, None) oder (None, Grund)."""
    art = arten.get(a.get("art")) if isinstance(a.get("art"), str) else None
    if art is None or a.get("art_version") != art.version:
        return None, GRUND_UNBEKANNT
    if art.art not in frei:
        return None, GRUND_GESPERRT
    if art.veraendert and _uuid(testkontakt.strip() if testkontakt else "") is None:
        return None, GRUND_KEIN_TESTKONTAKT
    if art.art not in AUSFUEHRER:
        return None, GRUND_NICHT_GEBAUT
    return art, None


def bearbeiten(q, a: dict, arten: dict, *, frei: set[str], testkontakt: str, verborgen) -> bool:
    """Einen uebernommenen Auftrag erledigen. True nur, wenn er auf `fertig` steht."""
    aid = str(a.get("id"))
    kurz = aid[:8]
    art, grund = _ablehnung(a, arten, frei, testkontakt)
    if grund is None:
        try:
            auftrag_vertrag.pruefe_eingabe(art, a.get("eingabe"))
        except auftrag_vertrag.FormFehler as e:
            grund = f"{GRUND_EINGABE}: {e}"
    if grund is None:
        try:
            ergebnis = AUSFUEHRER[art.art](q, a["eingabe"], verborgen)
        except Exception as e:  # noqa: BLE001 - nur der Typ, der Text kann Inhalte tragen
            grund = f"{GRUND_ABSTURZ} ({type(e).__name__})"
    if grund is None:
        try:
            auftrag_vertrag.pruefe_ergebnis(art, ergebnis)
        except auftrag_vertrag.FormFehler as e:
            grund = f"{GRUND_ERGEBNIS}: {e}"
    if grund is not None:
        auftrag_empfang.fehler(q, aid, grund, laden())
        LOG.warning("Auftrag %s art=%s: fehler (%s)", kurz, str(a.get("art"))[:40], grund.split(":")[0])
        return False
    if not auftrag_empfang.abschliessen(q, aid, ergebnis, laden()):
        LOG.warning("Auftrag %s art=%s: Abschluss nicht angenommen (nicht mehr in Arbeit)", kurz, art.art)
        return False
    LOG.info("Auftrag %s art=%s: fertig", kurz, art.art)
    return True


def laden() -> str:
    """Der eigene Laden, wie ihn auftrag_bote bestimmt; nur dessen Auftraege werden uebernommen."""
    return os.environ.get("LADEN_PRAEFIX", "").strip() or "sales"


def durchgang(q, arten: dict, *, verborgen, frei: set[str] | None = None, testkontakt: str | None = None,
              hoechstens: int = HOECHSTENS_JE_DURCHGANG) -> dict:
    frei = arten_frei() if frei is None else frei
    testkontakt = os.environ.get("AUFTRAG_TEST_KONTAKT_ID", "") if testkontakt is None else testkontakt
    zaehler = {"fertig": 0, "fehler": 0}
    for _ in range(hoechstens):
        a = auftrag_empfang.naechster(q, laden())
        if a is None:
            break
        try:
            ok = bearbeiten(q, a, arten, frei=frei, testkontakt=testkontakt, verborgen=verborgen)
        except Exception as e:  # noqa: BLE001 - ein kaputter Auftrag haelt die anderen nicht auf
            LOG.error("Auftrag %s: %s", str(a.get("id"))[:8], type(e).__name__)
            ok = False
        zaehler["fertig" if ok else "fehler"] += 1
    return zaehler


def start_hindernis(schema: str, eigener_laden: str) -> str | None:
    """Grund, aus dem der Abholer nicht arbeiten darf; None, wenn Schema und Laden zusammenpassen.

    `sales` und `sales_test` benutzen dieselbe Datenbank-Rolle. Die Huellen trennen nur nach dem Laden,
    den der Abholer selbst nennt. Eine Testinstanz mit dem Laden `sales` naehme dem Betrieb deshalb echte
    Auftraege weg und beantwortete sie aus den Testdaten."""
    if schema not in ERLAUBTE_SCHEMAS:
        return f"Schema {schema} wird nicht bedient (nur sales oder sales_test)"
    if not eigener_laden:
        return "Der Laden fehlt"
    if schema == "sales" and eigener_laden != "sales":
        return f"Schema {schema} gehoert zum Laden sales, nicht zu einem anderen Laden"
    if schema == "sales_test" and eigener_laden == "sales":
        return f"Schema {schema} darf nie mit dem Laden sales laufen (LADEN_PRAEFIX der Testinstanz setzen)"
    return None


def verborgen_aus_server(server):
    """Dieselben Regeln wie in den Werkzeugen: privat, archiviert oder zur Loeschung vermerkt."""
    def verborgen(enrichment) -> bool:
        return bool(server._privat(enrichment) or server._archiviert(enrichment)
                    or server._loeschantrag(enrichment) is not None)
    return verborgen


def _stopp_anfordern(signum, _rahmen) -> None:
    LOG.info("%s empfangen - nach diesem Durchgang ist Schluss.", signal.Signals(signum).name)
    _STOPP.set()


def _logging_einrichten() -> None:
    if LOG.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


def main() -> int:
    import server  # erst hier: der Import oeffnet den Datenbank-Pool

    _logging_einrichten()
    signal.signal(signal.SIGTERM, _stopp_anfordern)
    signal.signal(signal.SIGINT, _stopp_anfordern)
    hindernis = start_hindernis(server.SCHEMA, laden())
    if hindernis:
        # Kein Exit: mit restart: unless-stopped wuerde daraus eine Neustartschleife.
        LOG.error("%s - der Abholer wartet, ohne einen Auftrag anzufassen.", hindernis)
        _STOPP.wait()
        return 0
    import post_erledigt

    arten = auftrag_vertrag.lade()
    verborgen = verborgen_aus_server(server)
    anbinden(server, post_erledigt)
    LOG.info("Start: schema=%s laden=%s takt=%ds frei=%s arten=%s", server.SCHEMA, laden(), TAKT_S,
             ",".join(sorted(arten_frei())) or "-",
             ",".join(f"{a.art}v{a.version}:{auftrag_vertrag.art_hash(a)[:8]}" for a in arten.values()))
    while not _STOPP.is_set():
        try:
            durchgang(server._q, arten, verborgen=verborgen)
        except Exception as e:  # noqa: BLE001 - z. B. Datenbank kurz weg: weiter im Takt
            LOG.error("Durchgang abgebrochen: %s", type(e).__name__)
        _STOPP.wait(TAKT_S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
