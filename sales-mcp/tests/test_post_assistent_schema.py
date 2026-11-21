"""Schema fuer Pruefung und Dringlichkeit (Post-Assistent 3a, Task 1)."""
import os

import psycopg
import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402

SPALTEN = ("enthaelt_anweisung", "dringlichkeit", "geprueft_am",
           "pruef_aufrufe", "pruef_versuche", "anweisung_entscheid",
           "anweisung_entschieden_am")
KONTO = "k-t1-assistent-schema"


@pytest.fixture(scope="session", autouse=True)
def schema_wache():
    assert server.SCHEMA == "sales_test"


def _aufraeumen():
    with server.pool.connection() as conn:
        conn.execute("delete from sales_test.post_mails where konto_id in "
                     "(select id from sales_test.post_konten where kennung=%s)",
                     (KONTO,))
        conn.execute("delete from sales_test.post_konten where kennung=%s",
                     (KONTO,))
        conn.execute("delete from sales_test.freigabe_eintraege "
                     "where quelle_ref = 't1-assistent-schema'")


@pytest.fixture
def mail_id():
    _aufraeumen()
    konto = server._q(
        "insert into post_konten (besitzer, kennung, anbieter, adresse, "
        "quelle) values ('t1_anna', %s, 'gmx', 'a@b.de', 'ui') returning id",
        (KONTO,))[0]["id"]
    mid = server._q(
        "insert into post_mails (konto_id, imap_uid, message_id, besitzer, "
        "von, betreff, text, auszug, bereich, fach) values "
        "(%s, 1, 't1-mid', 't1_anna', 'x@y.de', 'B', 'T', 'T', 'business', "
        "'Kunden & Anfragen') returning id", (konto,))[0]["id"]
    yield mid
    _aufraeumen()


def test_spalten_da():
    rows = server._q("select column_name from information_schema.columns "
                     "where table_schema='sales_test' and "
                     "table_name='post_mails'")
    da = {r["column_name"] for r in rows}
    assert set(SPALTEN) <= da


def test_dringlichkeit_check(mail_id):
    with pytest.raises(psycopg.errors.CheckViolation):
        server._q("update post_mails set dringlichkeit='bald' where id=%s",
                  (mail_id,))
    server._q("update post_mails set dringlichkeit='kann_warten' "
              "where id=%s", (mail_id,))


def test_entscheid_check(mail_id):
    with pytest.raises(psycopg.errors.CheckViolation):
        server._q("update post_mails set anweisung_entscheid='vielleicht' "
                  "where id=%s", (mail_id,))
    server._q("update post_mails set anweisung_entscheid='gesperrt' "
              "where id=%s", (mail_id,))


def test_freigabe_art_post():
    _aufraeumen()
    server._q("insert into freigabe_eintraege (kennung, herkunft, art, "
              "quelle_ref, titel) values ('fg-aaaaaaaaaa', 'post', "
              "'post_anweisung', 't1-assistent-schema', 'Test')")
    _aufraeumen()
