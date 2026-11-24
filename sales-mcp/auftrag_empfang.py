"""Duenne DB-Schicht fuer Auftraege, die Sales EMPFAENGT (Schema `auftrag`, db/auftrag-empfang.sql).

Gegenstueck zu auftrag_buch.py (dort ist Sales Absender). sales_app darf nur die drei Huellen
`auftrag.sales_empfang_*` aufrufen; jede fasst nur Auftraege mit an = 'sales' und von = 'brain' an.
`q` wird uebergeben, damit die Tests ohne Datenbank laufen.
"""
from __future__ import annotations

import json

# Wie lange ein uebernommener Auftrag in Arbeit sein darf, bevor er als abgebrochen gilt (kein zweiter Versuch).
LEIHDAUER = "2 minutes"
FEHLER_MAXLAENGE = 300


def naechster(q, laden: str) -> dict | None:
    """Aeltesten offenen Auftrag an Sales in diesem Laden uebernehmen (offen -> in_arbeit); None, wenn
    keiner wartet. Ein Auftrag wird genau einmal vergeben: bleibt er liegen, wird er `fehler`."""
    zeilen = q("select auftrag.sales_empfang_naechster(%s, %s::interval) as a", (laden, LEIHDAUER))
    return zeilen[0]["a"] if zeilen and zeilen[0]["a"] else None


def abschliessen(q, aid: str, ergebnis: dict, laden: str) -> bool:
    """in_arbeit -> fertig mit Ergebnis, nur im eigenen Laden und nur innerhalb der Leihdauer.
    False, wenn der Auftrag nicht mehr in Arbeit ist."""
    z = q("select auftrag.sales_empfang_abschliessen(%s::uuid, %s::jsonb, %s) as ok",
          (aid, json.dumps(ergebnis, ensure_ascii=False), laden))
    return bool(z and z[0]["ok"])


def fehler(q, aid: str, grund: str, laden: str) -> bool:
    """in_arbeit -> fehler mit kurzem Grund (nie mit Werten aus der Eingabe), nur im eigenen Laden."""
    z = q("select auftrag.sales_empfang_fehler(%s::uuid, %s, %s) as ok",
          (aid, grund[:FEHLER_MAXLAENGE], laden))
    return bool(z and z[0]["ok"])
