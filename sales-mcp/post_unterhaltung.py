"""Unterhaltungen und Erbe gesendeter Mails (Post-Assistent Stufe 1, Task 4).

Mails desselben Besitzers werden ueber Message-ID, In-Reply-To und References zu einer
Unterhaltung (`unterhaltung`, uuid) verknuepft - nie ueber Besitzer hinweg, und nie ueber
eine Ersatz-Kennung (`message_id_ersatz`: ein Platzhalter beweist keine Identitaet).

Eine gesendete Antwort erbt vom beantworteten Eingang den Bereich und den Schutz: ist die
Bezugsmail sensibel, wird es die Antwort auch (und ihr Inhalt wird geleert). Ebenso erbt
die gesendete Kopie einer Mail an mich selbst von ihrem Eingangs-Zwilling. `sensibel`
geht nie zurueck. Kein Modellaufruf; im Protokoll nie Inhalte, Adressen oder Message-IDs.
"""
from __future__ import annotations

import logging
import uuid

import server

GRENZE = 500
LOG = logging.getLogger("sales-post")


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
    # Mit Schema im Schluessel: derselbe Besitzername in zwei Laeden sperrt sich nicht.
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))",
                 (f"post_unterhaltung:{server.SCHEMA}:{besitzer}",))
    bezug = [k for k in [mail["in_reply_to"], *(mail["referenzen"] or [])] if k]
    # Nachbarn: die Mails, auf die sie sich bezieht; die Mails, die sich auf sie beziehen;
    # und ihr Zwilling mit derselben Message-ID (eine Mail an mich selbst liegt als
    # Eingang UND als gesendet vor). Platzhalter verbinden in keiner Richtung.
    nachbarn = conn.execute(
        "select id, unterhaltung from post_mails where besitzer = %s and id <> %s and ("
        "(not message_id_ersatz and message_id = any(%s)) "
        "or (not %s and (in_reply_to = %s or referenzen @> array[%s]::text[] "
        "               or (not message_id_ersatz and message_id = %s))))",
        (besitzer, mail["id"], bezug, mail["message_id_ersatz"], mail["message_id"],
         mail["message_id"], mail["message_id"])).fetchall()
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
# Dazu der Zwilling (I2): dieselbe Mail als Eingang (Mail an mich selbst), gleicher
# Besitzer, beide ohne Platzhalter. Sein Bereich geht vor (wenn gesetzt); sensibel wird
# die gesendete Mail, wenn der Zwilling ODER die Bezugsmail es ist.
# `%(gid)s`: NULL = alle gesendeten Mails (nachziehen), sonst nur diese eine (Speichern).
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
  select g2.id as gid, coalesce(t.bereich, b.bereich) as bereich,
         coalesce(t.sensibel, false) or coalesce(b.sensibel, false) as sensibel
  from post_mails g2
  left join lateral (
    select t.bereich, t.sensibel from post_mails t
    where t.besitzer = g2.besitzer and t.id <> g2.id and t.richtung = 'eingang'
      and not t.message_id_ersatz and not g2.message_id_ersatz
      and t.message_id = g2.message_id
    order by t.sensibel desc, (t.bereich is null), t.id
    limit 1) t on true
  left join lateral (
    select b.bereich, b.sensibel from post_mails b
    where (g2.in_reply_to is not null or cardinality(g2.referenzen) > 0)
      and b.besitzer = g2.besitzer and b.id <> g2.id and not b.message_id_ersatz
      and (b.message_id = g2.in_reply_to or b.message_id = any(g2.referenzen))
    order by (b.message_id = g2.in_reply_to) desc,
             array_position(g2.referenzen, b.message_id) desc nulls last,
             (b.richtung = 'eingang') desc, b.id
    limit 1) b on true
  where g2.richtung = 'gesendet'
    and (%(gid)s::uuid is null or g2.id = %(gid)s::uuid)
    and (t.sensibel is not null or b.sensibel is not null)
) x
where g.id = x.gid
  and ((x.bereich is not null and g.bereich is distinct from x.bereich)
       or (x.sensibel and not g.sensibel))
"""


def erben(conn, mail_id=None) -> int:
    """Gleicht gesendete Mails an Bezugsmail und Zwilling an (Bereich, sensibel) und gibt
    die Zahl der geaenderten Zeilen zurueck. `mail_id`: nur diese eine Mail (beim
    Speichern), sonst alle. Laeuft in der Transaktion des Aufrufers."""
    return conn.execute(_ERBE_SQL, {"gid": None if mail_id is None else str(mail_id)}).rowcount


def nachziehen(grenze: int = GRENZE, stopp=None) -> dict:
    """Ordnet bis zu `grenze` Mails ohne Unterhaltung zu (neueste zuerst) und gleicht
    gesendete Mails an ihre Bezugsmail an. Gibt {"zugeordnet": n, "geerbt": m, "fehler": k}
    zurueck. `stopp`: Aufrufbare ohne Argumente (z. B. Event.is_set); ist sie wahr, endet
    nur die Zuordnung, das Erbe laeuft immer. Eine Mail, deren Zuordnung scheitert, kostet
    weder den Rest noch das Erbe; im Protokoll nur der Typ."""
    with server.pool.connection() as conn:
        ids = [z["id"] for z in conn.execute(
            "select id from post_mails where unterhaltung is null "
            "order by datum desc nulls last, id desc limit %s", (grenze,)).fetchall()]
    zugeordnet = fehler = 0
    for mail_id in ids:
        if stopp is not None and stopp():
            break
        try:
            with server.pool.connection() as conn, conn.transaction():
                zuordnen(conn, mail_id)
            zugeordnet += 1
        except Exception as e:  # noqa: BLE001 - eine Mail haelt die anderen nicht auf
            fehler += 1
            LOG.warning("Unterhaltung nicht zugeordnet (%s)", type(e).__name__)
    with server.pool.connection() as conn, conn.transaction():
        geerbt = erben(conn)
    return {"zugeordnet": zugeordnet, "geerbt": geerbt, "fehler": fehler}
