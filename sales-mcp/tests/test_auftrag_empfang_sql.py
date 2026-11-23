"""db/auftrag-empfang.sql: die Huellen bleiben eng und passen zu auftrag_empfang.py. Ohne Datenbank.

Die Datei selbst wird hier nicht ausgefuehrt (das Schema `auftrag` gibt es in keiner Test-DB);
geprueft wird ihr Text gegen die Regeln, die sie halten muss.
"""
import re
from pathlib import Path

import auftrag_empfang

WURZEL = Path(__file__).resolve().parents[2]
SQL = (WURZEL / "db" / "auftrag-empfang.sql").read_text(encoding="utf-8")
HUELLEN = {"sales_empfang_naechster": "text, interval", "sales_empfang_abschliessen": "uuid, jsonb",
           "sales_empfang_fehler": "uuid, text"}


def _koerper(name: str) -> str:
    treffer = re.search(rf"CREATE OR REPLACE FUNCTION auftrag\.{name}\(.*?\$\$(.*?)\$\$;", SQL, re.S)
    assert treffer, f"{name} fehlt"
    return treffer.group(0)


def test_genau_die_drei_huellen_und_sonst_keine_funktion():
    assert set(re.findall(r"CREATE OR REPLACE FUNCTION auftrag\.(\w+)", SQL)) == set(HUELLEN)


def test_jede_huelle_fasst_nur_auftraege_des_gehirns_an_sales_an():
    for name in HUELLEN:
        koerper = _koerper(name)
        assert "SECURITY DEFINER SET search_path = auftrag, pg_temp" in koerper
        for anweisung in re.findall(r"(?:UPDATE|SELECT \* INTO a FROM) auftrag\.auftraege.*?;", koerper, re.S):
            if "WHERE id = a.id" in anweisung:        # die soeben unter Sperre gewaehlte Zeile
                continue
            assert "an = 'sales' AND von = 'brain'" in anweisung, name


def test_kein_zweiter_versuch():
    koerper = _koerper("sales_empfang_naechster")
    waehlen = re.search(r"SELECT \* INTO a FROM auftrag\.auftraege.*?;", koerper, re.S).group(0)
    assert "stand = 'offen'" in waehlen and "in_arbeit" not in waehlen
    assert "FOR UPDATE SKIP LOCKED" in waehlen and "laden = p_laden" in waehlen


def test_rechte_nur_fuer_sales_app():
    for name, signatur in HUELLEN.items():
        assert f"REVOKE ALL ON FUNCTION auftrag.{name}({signatur}) FROM PUBLIC;" in SQL
        assert f"GRANT EXECUTE ON FUNCTION auftrag.{name}({signatur}) TO sales_app;" in SQL
    assert len(re.findall(r"^GRANT ", SQL, re.M)) == len(HUELLEN)


def test_datei_schaltet_nichts_frei_und_aendert_nichts_bestehendes():
    ohne_kommentar = "\n".join(z for z in SQL.splitlines() if not z.lstrip().startswith("--"))
    for verboten in ("brain_arten", "ALTER TABLE", "DROP ", "INSERT INTO", "DELETE FROM", "CREATE TABLE"):
        assert verboten not in ohne_kommentar, verboten
    assert ohne_kommentar.strip().startswith("BEGIN;") and ohne_kommentar.strip().endswith("COMMIT;")


def test_python_schicht_ruft_dieselben_signaturen():
    rufe = []

    def q(sql, params=()):
        rufe.append((sql, params))
        return [{"a": None, "ok": True}]
    auftrag_empfang.naechster(q, "sales")
    auftrag_empfang.abschliessen(q, "0123abcd-0000-4000-8000-000000000001", {})
    auftrag_empfang.fehler(q, "0123abcd-0000-4000-8000-000000000001", "x")
    for (sql, params), (name, signatur) in zip(rufe, HUELLEN.items()):
        assert f"auftrag.{name}(" in sql
        assert len(params) == len(signatur.split(","))
