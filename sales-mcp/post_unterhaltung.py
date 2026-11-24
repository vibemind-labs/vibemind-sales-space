"""Unterhaltungen und Erbe gesendeter Mails (Post-Assistent Stufe 1, Task 4).

Mails desselben Besitzers werden ueber Message-ID, In-Reply-To und References zu einer
Unterhaltung (`unterhaltung`, uuid) verknuepft - nie ueber Besitzer hinweg, und nie ueber
eine Ersatz-Kennung (`message_id_ersatz`: ein Platzhalter beweist keine Identitaet).

Eine gesendete Antwort erbt vom beantworteten Eingang den Bereich und den Schutz: ist die
Bezugsmail sensibel, wird es die Antwort auch (und ihr Inhalt wird geleert). `sensibel`
geht nie zurueck. Kein Modellaufruf; im Protokoll nie Inhalte, Adressen oder Message-IDs.
"""
from __future__ import annotations

import uuid

import server

GRENZE = 500


def zuordnen(conn, mail_id) -> str:
    """Haengt die Mail in ihre Unterhaltung und gibt deren Kennung zurueck.

    Laeuft in der Transaktion des Aufrufers. Verschmelzen mehrere Ketten, gewinnt die
    Kennung der aeltesten Mail (datum, dann id); alle Mails der verlorenen Kennungen
    werden mit EINEM Update umgestellt."""
    mail = conn.execute(
        "select id, besitzer, message_id, message_id_ersatz, in_reply_to, referenzen, "
        "unterhaltung from post_mails where id = %s", (mail_id,)).fetchone()
    if mail is None:
        raise LookupError("Mail nicht gefunden")
    besitzer = mail["besitzer"]
    # Ein Fetcher-Prozess ist der Normalfall; die Sperre haelt auch zwei Zuordnungen
    # desselben Besitzers auseinander (faellt mit dem Transaktionsende).
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))", ("post_unterhaltung:" + besitzer,))
    bezug = [k for k in [mail["in_reply_to"], *(mail["referenzen"] or [])] if k]
    nachbarn = conn.execute(
        "select id, unterhaltung from post_mails where besitzer = %s and id <> %s and ("
        "(not message_id_ersatz and message_id = any(%s)) "
        "or (not %s and (in_reply_to = %s or referenzen @> array[%s]::text[])))",
        (besitzer, mail["id"], bezug, mail["message_id_ersatz"], mail["message_id"],
         mail["message_id"])).fetchall()
    kennungen = {n["unterhaltung"] for n in nachbarn if n["unterhaltung"] is not None}
    if mail["unterhaltung"] is not None:
        kennungen.add(mail["unterhaltung"])
    if kennungen:
        sieger = conn.execute(
            "select unterhaltung from post_mails where besitzer = %s "
            "and unterhaltung = any(%s) order by datum nulls last, id limit 1",
            (besitzer, list(kennungen))).fetchone()["unterhaltung"]
    else:
        sieger = uuid.uuid4()
    verlierer = [k for k in kennungen if k != sieger]
    lose = [n["id"] for n in nachbarn if n["unterhaltung"] is None]
    conn.execute(
        "update post_mails set unterhaltung = %s where besitzer = %s and "
        "(id = %s or id = any(%s) or unterhaltung = any(%s)) "
        "and unterhaltung is distinct from %s",
        (sieger, besitzer, mail["id"], lose, verlierer, sieger))
    return str(sieger)


# Die Bezugsmail einer gesendeten Mail: In-Reply-To, sonst die letzte vorhandene aus
# References; beim selben Besitzer, nie ueber einen Platzhalter. Bei mehreren Zeilen mit
# derselben Message-ID gewinnt der Eingang, dann die kleinste id.
_ERBE_SQL = """
update post_mails g set
  bereich = coalesce(x.bereich, g.bereich),
  sensibel = g.sensibel or x.sensibel,
  text = case when g.sensibel or x.sensibel then null else g.text end,
  auszug = case when g.sensibel or x.sensibel then null else g.auszug end,
  an = case when g.sensibel or x.sensibel then null else g.an end,
  urspruengliche_adresse = case when g.sensibel or x.sensibel
                                then null else g.urspruengliche_adresse end,
  anhaenge = case when g.sensibel or x.sensibel then '{}'::text[] else g.anhaenge end
from (
  select g2.id as gid, b.bereich, b.sensibel
  from post_mails g2
  cross join lateral (
    select b.bereich, b.sensibel from post_mails b
    where b.besitzer = g2.besitzer and b.id <> g2.id and not b.message_id_ersatz
      and (b.message_id = g2.in_reply_to or b.message_id = any(g2.referenzen))
    order by (b.message_id = g2.in_reply_to) desc,
             array_position(g2.referenzen, b.message_id) desc nulls last,
             (b.richtung = 'eingang') desc, b.id
    limit 1) b
  where g2.richtung = 'gesendet'
) x
where g.id = x.gid
  and ((x.bereich is not null and g.bereich is distinct from x.bereich)
       or (x.sensibel and not g.sensibel))
"""


def nachziehen(grenze: int = GRENZE) -> dict:
    """Ordnet bis zu `grenze` Mails ohne Unterhaltung zu (neueste zuerst) und gleicht
    gesendete Mails an ihre Bezugsmail an. Gibt {"zugeordnet": n, "geerbt": m} zurueck."""
    with server.pool.connection() as conn:
        ids = [z["id"] for z in conn.execute(
            "select id from post_mails where unterhaltung is null "
            "order by datum desc nulls last, id desc limit %s", (grenze,)).fetchall()]
    for mail_id in ids:
        with server.pool.connection() as conn, conn.transaction():
            zuordnen(conn, mail_id)
    with server.pool.connection() as conn, conn.transaction():
        geerbt = conn.execute(_ERBE_SQL).rowcount
    return {"zugeordnet": len(ids), "geerbt": geerbt}
