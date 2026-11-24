"""Schema fuer gesendete Mails (Post-Assistent Stufe 1, Task 1)."""
import os

import psycopg
import pytest

os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402

SPALTEN = ("richtung", "in_reply_to", "referenzen", "unterhaltung",
           "kopf_nachgelesen")
KONTO = "k-s1-t1-schema"


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


@pytest.fixture
def konto():
    _aufraeumen()
    kid = server._q(
        "insert into post_konten (besitzer, kennung, anbieter, adresse, "
        "quelle) values ('s1_anna', %s, 'gmx', 'a@b.de', 'ui') returning id",
        (KONTO,))[0]["id"]
    yield kid
    _aufraeumen()


def _mail(konto, uid, richtung=None, status=None):
    cols, vals = ["konto_id", "imap_uid", "message_id", "besitzer", "von",
                  "betreff", "text", "auszug"], [konto, uid, f"s1-{uid}-{richtung}",
                                                 "s1_anna", "x@y.de", "B", "T", "T"]
    if richtung:
        cols.append("richtung")
        vals.append(richtung)
    if status:
        cols.append("status")
        vals.append(status)
    ph = ", ".join(["%s"] * len(vals))
    return server._q(f"insert into post_mails ({', '.join(cols)}) values ({ph}) "
                     "returning id", tuple(vals))[0]["id"]


def test_spalten_und_tabelle_da():
    rows = server._q("select column_name from information_schema.columns "
                     "where table_schema='sales_test' and table_name='post_mails'")
    assert set(SPALTEN) <= {r["column_name"] for r in rows}
    rows = server._q("select column_name from information_schema.columns "
                     "where table_schema='sales_test' and "
                     "table_name='post_ordner_stand'")
    assert {"konto_id", "richtung", "ordner", "uidvalidity", "letzte_uid",
            "altbestand_fertig"} <= {r["column_name"] for r in rows}


def test_gesendet_braucht_status_gesendet(konto):
    with pytest.raises(psycopg.errors.CheckViolation):
        _mail(konto, 1, "gesendet", "neu")
    with pytest.raises(psycopg.errors.CheckViolation):
        _mail(konto, 2, "eingang", "gesendet")
    _mail(konto, 3, "gesendet", "gesendet")


def test_gleiche_uid_je_richtung_erlaubt(konto):
    _mail(konto, 7, "eingang")
    _mail(konto, 7, "gesendet", "gesendet")
    with pytest.raises(psycopg.errors.UniqueViolation):
        server._q("insert into post_mails (konto_id, imap_uid, message_id, "
                  "besitzer, von, betreff, text, auszug) values "
                  "(%s, 7, 's1-dup', 's1_anna', 'x@y.de', 'B', 'T', 'T')",
                  (konto,))


def test_bestand_ist_eingang(konto):
    mid = _mail(konto, 5)
    r = server._q("select richtung, referenzen, kopf_nachgelesen, "
                  "in_reply_to, unterhaltung from post_mails where id=%s",
                  (mid,))[0]
    assert r["richtung"] == "eingang"
    assert list(r["referenzen"]) == []
    assert r["kopf_nachgelesen"] is False
    assert r["in_reply_to"] is None and r["unterhaltung"] is None


def test_nachzieh_indizes_da():
    rows = server._q("select indexname, indexdef from pg_indexes where schemaname='sales_test' "
                     "and tablename='post_mails' and indexname in "
                     "('post_mails_ohne_unterhaltung_idx','post_mails_gesendet_bezug_idx')")
    assert {r["indexname"] for r in rows} == {"post_mails_ohne_unterhaltung_idx",
                                              "post_mails_gesendet_bezug_idx"}
    assert all(" WHERE " in r["indexdef"] for r in rows)
