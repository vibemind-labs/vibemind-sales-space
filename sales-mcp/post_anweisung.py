"""Freigabe-Eingang "Anweisung an eine KI" (Post-Assistent 3a, Task 5).

Mails, in denen die Pruefung eine Anweisung an eine KI gefunden hat, liest der
Agent nur als Kopf (post_struktur.AGENT_LESBAR_SQL). Hier wartet jede solche Mail
auf /freigaben, bis ihr Besitzer sie fuer den Agenten freigibt oder gesperrt laesst.

Der Eintrag traegt nur den festen Titel, leere `details` und den Link auf die
Mail (die nur der Besitzer oeffnen kann) - nie Betreff, Absender oder Text. Der
Freigabe-Bote spiegelt die Art nicht nach Rowboat (fe.NICHT_NACH_ROWBOAT).
"""
from __future__ import annotations

import uuid

import freigabe_eingang as fe
import post_struktur
import server

HERKUNFT = "post"
ART = "post_anweisung"
TITEL = "Mail mit Anweisung an eine KI – bitte prüfen"
ENTSCHEIDE = ("freigegeben", "gesperrt")
_VON = "post-anweisung"
_GRENZE = 200

# Eine Mail wartet auf den Besitzer, solange sie eingeordnet, markiert, nicht
# entschieden und nicht sensibel ist (sensible liest der Agent ohnehin nie).
_WARTET_SQL = ("m.status = 'eingeordnet' and m.enthaelt_anweisung is true "
               "and m.anweisung_entscheid is null and m.sensibel is false")


def eintraege_nachziehen() -> int:
    """Eintraege an den Stand der Mails angleichen; gibt die Zahl neuer Eintraege zurueck.

    Erst schliessen (Mail weg, geloescht, entschieden, nicht mehr markiert), dann
    fuer jede wartende Mail ohne offenen Eintrag einen anlegen."""
    veraltet = server._q(
        "select e.quelle_ref from freigabe_eintraege e where e.herkunft = %s "
        "and e.status = 'offen' and not exists (select 1 from post_mails m "
        f"where m.id::text = e.quelle_ref and {_WARTET_SQL})", (HERKUNFT,))
    for z in veraltet:
        fe.schliessen(HERKUNFT, z["quelle_ref"], "erledigt", _VON)
    wartend = server._q(
        f"select m.id from post_mails m where {_WARTET_SQL} and not exists "
        "(select 1 from freigabe_eintraege e where e.herkunft = %s "
        "and e.quelle_ref = m.id::text and e.status = 'offen') "
        "order by m.datum desc nulls last, m.id limit %s", (HERKUNFT, _GRENZE))
    neu = 0
    for z in wartend:
        mid = str(z["id"])
        _, angelegt = fe.eintragen(HERKUNFT, ART, mid, TITEL, link=f"/post/mail/{mid}",
                                   details={})
        neu += 1 if angelegt else 0
    return neu


def entscheiden(mail_id: str, entscheid: str, von: str) -> bool:
    """Der Besitzer gibt eine markierte Mail fuer den Agenten frei oder laesst sie
    gesperrt. False (und nichts aendert sich) fuer jeden anderen, einen unbekannten
    Entscheid oder eine Mail, die nicht mehr markiert und unentschieden ist."""
    if entscheid not in ENTSCHEIDE:
        return False
    besitzer = post_struktur.container_besitzer()
    if not besitzer or von != besitzer:
        return False
    try:
        mid = str(uuid.UUID(str(mail_id)))
    except ValueError:
        return False
    z = server._q(
        "update post_mails set anweisung_entscheid = %s, anweisung_entschieden_am = now() "
        "where id = %s and besitzer = %s and enthaelt_anweisung is true "
        "and anweisung_entscheid is null returning id", (entscheid, mid, besitzer))
    if not z:
        return False
    if entscheid == "freigegeben":
        fe.schliessen(HERKUNFT, mid, "erledigt", von)
    else:
        fe.schliessen(HERKUNFT, mid, "verworfen", von, vermerk="gesperrt")
    return True
