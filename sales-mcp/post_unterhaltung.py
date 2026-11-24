"""Unterhaltungen und Erbe gesendeter Mails (Post-Assistent Stufe 1, Task 4).

Mails desselben Besitzers werden ueber Message-ID, In-Reply-To und References zu einer
Unterhaltung (`unterhaltung`, uuid) verknuepft - nie ueber Besitzer hinweg, und nie ueber
eine Ersatz-Kennung (`message_id_ersatz`: ein Platzhalter beweist keine Identitaet).

Eine gesendete Antwort erbt vom beantworteten Eingang den Bereich und den Schutz: ist die
Bezugsmail sensibel, wird es die Antwort auch (und ihr Inhalt wird geleert). Ebenso erbt
die gesendete Kopie einer Mail an mich selbst von ihrem Eingangs-Zwilling. `sensibel`
geht nie zurueck. Kein Modellaufruf; im Protokoll nie Inhalte, Adressen oder Message-IDs.

Bewusst hingenommene Restrisiken (Security-Re-Reviews):
- F3: Wer den From-Kopf mit einer eigenen Adresse faelscht und die Message-ID einer
  gesendeten Mail wiederverwendet, gilt als Zwilling. Das macht nur strenger: der
  gespeicherte Inhalt der gesendeten Mail kann geleert werden (wenn das Modell die
  Faelschung sensibel einstuft), und die Faelschung steht in derselben Unterhaltung.
  Lockern kann sie nichts - kein Bereich wird business, nichts wird lesbarer.
- R1: Eine fremde Kopie der Message-ID einer gesendeten Mail wird nur erkannt, wenn
  die echte gesendete Zeile gespeichert ist. Fehlt sie noch (noch nicht abgeholt) oder
  fuer immer (vor dem Stichtag, im Gesendet-Ordner geloescht, vom Mailprogramm nie dort
  abgelegt), zaehlt die Kopie als gewoehnliche Bezugsmail einer spaeteren Antwort.
"""
from __future__ import annotations

import logging
import uuid

import post_erledigt
import server

GRENZE = 500
LOG = logging.getLogger("sales-post")


def _eigen_sql(alias: str) -> str:
    """SQL: der Absender der Zeile `alias` ist eine eigene Kontoadresse ihres Besitzers
    (post_konten.adresse, gleicher Besitzer, nie eine leere), ohne Gross/Klein. Der
    Absender wird streng zerlegt (post_erledigt.absender_streng_sql: genau eine Adresse,
    sonst NULL). Nur so ist ein Eingang ein Zwilling: die Message-ID einer gesendeten
    Mail kennt jeder Empfaenger und koennte sie in einer fremden Mail wiederverwenden."""
    absender = post_erledigt.absender_streng_sql(alias)
    return (f"exists (select 1 from post_konten k where k.besitzer = {alias}.besitzer "
            f"and nullif(btrim(k.adresse), '') is not null "
            f"and lower(btrim(k.adresse)) = {absender})")


def _bezug_zulaessig_sql(alias: str) -> str:
    """SQL: die Zeile `alias` darf als Bezug/Nachbar ueber ihre Message-ID dienen. Ein
    Eingang, dessen Message-ID auch als eigene gesendete Mail desselben Besitzers vorliegt,
    zaehlt nur mit eigener Absenderadresse - sonst ist er eine fremde Kopie dieser ID und
    die gesendete Zeile ist der Bezug (Security-Re-Review F1)."""
    eigen = _eigen_sql(alias)          # prueft auch den Alias (isidentifier)
    return (f"({alias}.richtung = 'gesendet' or {eigen} "
            f"or not exists (select 1 from post_mails s where s.besitzer = {alias}.besitzer "
            f"and s.richtung = 'gesendet' and not s.message_id_ersatz "
            f"and s.message_id = {alias}.message_id))")


def zuordnen(conn, mail_id) -> str:
    """Haengt die Mail in ihre Unterhaltung und gibt deren Kennung zurueck.

    Laeuft in der Transaktion des Aufrufers. Verschmelzen mehrere Ketten, gewinnt die
    Kennung der aeltesten Mail (datum, dann id); alle Mails der verlorenen Kennungen
    werden mit EINEM Update umgestellt."""
    mail = conn.execute(
        "select m.id, m.besitzer, m.message_id, m.message_id_ersatz, m.in_reply_to, "
        "m.referenzen, m.unterhaltung, m.richtung, "
        f"(m.richtung = 'eingang' and {_eigen_sql('m')}) as eigener_eingang, "
        f"not {_bezug_zulaessig_sql('m')} as fremde_kopie "
        "from post_mails m where m.id = %s", (mail_id,)).fetchone()
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
    # Eingang UND als gesendet vor). Zwilling ist nur das Paar gesendet <-> Eingang mit
    # eigener Absenderadresse (N1). Platzhalter verbinden in keiner Richtung. Eine fremde
    # Kopie einer eigenen gesendeten Message-ID ist weder Bezug noch Ziel von Bezuegen (F1).
    nachbarn = conn.execute(
        "select n.id, n.unterhaltung from post_mails n where n.besitzer = %s and n.id <> %s "
        "and ((not n.message_id_ersatz and n.message_id = any(%s) "
        f"     and {_bezug_zulaessig_sql('n')}) "
        "or (not %s and not %s::boolean "
        "    and (n.in_reply_to = %s or n.referenzen @> array[%s]::text[] "
        "               or (not n.message_id_ersatz and n.message_id = %s and ("
        f"                  (%s::text = 'gesendet' and n.richtung = 'eingang' "
        f"                   and {_eigen_sql('n')})"
        "                   or (%s::boolean and n.richtung = 'gesendet'))))))",
        (besitzer, mail["id"], bezug, mail["message_id_ersatz"], mail["fremde_kopie"],
         mail["message_id"], mail["message_id"], mail["message_id"], mail["richtung"],
         mail["eigener_eingang"])).fetchall()
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
# derselben Message-ID gewinnt immer die eigene gesendete Zeile, dann die kleinste id: eine
# Eingangskopie dieser ID - auch mit (vielleicht gefaelschter) eigener Absenderadresse -
# ist nie Bezug, solange die echte gesendete Zeile da ist. Ohne eigene Absenderadresse
# zaehlt eine solche Kopie gar nicht (F1). Den Schutz einer echten Selbst-Kopie bekommt
# die gesendete Zeile ueber den Zwilling und reicht ihn beim naechsten Lauf weiter.
# Dazu der Zwilling (I2): dieselbe Mail als Eingang (Mail an mich selbst), gleicher
# Besitzer, beide ohne Platzhalter, Absender eine eigene Kontoadresse (N1). Der Zwilling
# macht nur strenger, nie lockerer: sensibel, wenn irgendein Zwilling ODER die Bezugsmail
# es ist; beim Bereich hat die Bezugsmail Vorrang, und die Zwillinge tragen nur `privat`
# bei (ueber alle Zwillinge, bool_or).
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
  select g2.id as gid,
         case when t.privat or b.bereich = 'privat' then 'privat'
              else b.bereich end as bereich,
         coalesce(t.sensibel, false) or coalesce(b.sensibel, false) as sensibel
  from post_mails g2
  left join lateral (
    select bool_or(t.sensibel) as sensibel, bool_or(t.bereich = 'privat') as privat
    from post_mails t
    where t.besitzer = g2.besitzer and t.id <> g2.id and t.richtung = 'eingang'
      and not t.message_id_ersatz and not g2.message_id_ersatz
      and t.message_id = g2.message_id
      and """ + _eigen_sql("t") + """) t on true
  left join lateral (
    select b.bereich, b.sensibel from post_mails b
    where (g2.in_reply_to is not null or cardinality(g2.referenzen) > 0)
      and b.besitzer = g2.besitzer and b.id <> g2.id and not b.message_id_ersatz
      and (b.message_id = g2.in_reply_to or b.message_id = any(g2.referenzen))
      and """ + _bezug_zulaessig_sql("b") + """
    order by (b.message_id = g2.in_reply_to) desc,
             array_position(g2.referenzen, b.message_id) desc nulls last,
             (b.richtung = 'gesendet') desc, b.id
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
