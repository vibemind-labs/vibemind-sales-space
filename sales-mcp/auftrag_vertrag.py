"""Auftragsarten, die Sales als Empfaenger annimmt: laden, Form pruefen, Pruefsumme.

Die Form ist dieselbe wie im Vertrag von vibemind-os (spaces/auftragsbuch/vertrag.py): gleiche
Felder, gleiche Pruefsumme je Art. So laesst sich auf beiden Seiten nachweisen, dass dieselbe
Fassung gilt. Fehlertexte nennen nur Regel und Feldpfad, nie Werte. Rein: keine Datenbank.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

SPACE = "sales"
DATEI = Path(__file__).with_name("auftrag_arten.yaml")
_ART_MUSTER = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
_PFLICHT = ("art", "version", "veraendert", "frist_min", "nachpruefung", "beschreibung", "eingabe", "ergebnis")
_ERLAUBT = set(_PFLICHT) | {"nachpruefung_grund"}


class VertragsFehler(ValueError):
    """Die Datei der Auftragsarten ist unvollstaendig oder verletzt eine Regel."""


class FormFehler(ValueError):
    """Ein Wert passt nicht zum Schema der Auftragsart (ohne den Wert zu nennen)."""


@dataclass(frozen=True)
class Auftragsart:
    space: str
    art: str
    version: int
    veraendert: bool
    frist_min: int
    nachpruefung: str
    nachpruefung_grund: str
    beschreibung: str
    eingabe: dict
    ergebnis: dict


def _ganzzahl(wert: object) -> bool:
    return isinstance(wert, int) and not isinstance(wert, bool)


def _geschlossen(schema: object) -> bool:
    """Jedes Objekt im Schema (auf jeder Tiefe) schliesst unbekannte Felder aus."""
    if isinstance(schema, list):
        return all(_geschlossen(t) for t in schema)
    if not isinstance(schema, dict):
        return True
    typ = schema.get("type")
    ist_objekt = typ == "object" or (isinstance(typ, list) and "object" in typ)
    if ist_objekt and schema.get("additionalProperties") is not False:
        return False
    return all(_geschlossen(t) for t in schema.values())


def _schema(name: str, roh: object, ort: str) -> dict:
    if not isinstance(roh, dict) or roh.get("type") != "object":
        raise VertragsFehler(f"{ort}: {name} braucht type: object auf oberster Ebene")
    try:
        Draft202012Validator.check_schema(roh)
    except SchemaError:
        raise VertragsFehler(f"{ort}: {name} ist kein gueltiges JSON Schema") from None
    if not _geschlossen(roh):
        raise VertragsFehler(f"{ort}: {name} braucht additionalProperties: false an jedem Objekt")
    return roh


def _baue(roh: object) -> Auftragsart:
    if not isinstance(roh, dict):
        raise VertragsFehler("jeder Eintrag in auftragsarten muss ein Objekt sein")
    art = roh.get("art")
    ort = f"art {art if isinstance(art, str) else '?'}"
    if set(roh) - _ERLAUBT or [f for f in _PFLICHT if f not in roh]:
        raise VertragsFehler(f"{ort}: Felder fehlen oder sind unbekannt")
    if not isinstance(art, str) or not _ART_MUSTER.match(art):
        raise VertragsFehler(f"{ort}: art muss {_ART_MUSTER.pattern} entsprechen")
    if not _ganzzahl(roh["version"]) or roh["version"] < 1:
        raise VertragsFehler(f"{ort}: version muss eine ganze Zahl >= 1 sein")
    if not isinstance(roh["veraendert"], bool):
        raise VertragsFehler(f"{ort}: veraendert muss true oder false sein")
    if not _ganzzahl(roh["frist_min"]) or not 1 <= roh["frist_min"] <= 120:
        raise VertragsFehler(f"{ort}: frist_min muss eine ganze Zahl von 1 bis 120 sein")
    if roh["nachpruefung"] not in ("form", "beleg"):
        raise VertragsFehler(f"{ort}: nachpruefung muss form oder beleg sein")
    grund = roh.get("nachpruefung_grund", "")
    if not isinstance(grund, str) or not isinstance(roh["beschreibung"], str) or not roh["beschreibung"].strip():
        raise VertragsFehler(f"{ort}: beschreibung und nachpruefung_grund muessen Text sein")
    if roh["veraendert"] and roh["nachpruefung"] == "form" and not grund.strip():
        raise VertragsFehler(f"{ort}: eine veraendernde Art mit nachpruefung form braucht einen Grund")
    return Auftragsart(
        space=SPACE, art=art, version=roh["version"], veraendert=roh["veraendert"],
        frist_min=roh["frist_min"], nachpruefung=roh["nachpruefung"], nachpruefung_grund=grund,
        beschreibung=roh["beschreibung"],
        eingabe=_schema("eingabe", roh["eingabe"], ort), ergebnis=_schema("ergebnis", roh["ergebnis"], ort))


def lade(datei: Path = DATEI) -> dict[str, Auftragsart]:
    """Alle Auftragsarten der Datei; Schluessel ist der Name der Art."""
    try:
        inhalt = yaml.safe_load(Path(datei).read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise VertragsFehler("auftragsarten: kein gueltiges YAML") from None
    liste = inhalt.get("auftragsarten") if isinstance(inhalt, dict) else None
    if not isinstance(liste, list):
        raise VertragsFehler("auftragsarten muss eine Liste sein")
    arten: dict[str, Auftragsart] = {}
    for roh in liste:
        a = _baue(roh)
        if a.art in arten:
            raise VertragsFehler(f"art {a.art}: doppelt vorhanden")
        arten[a.art] = a
    return arten


def _felder(schema: object) -> set[str]:
    """Alle Feldnamen, die das Schema unter `properties` nennt (auf jeder Tiefe)."""
    if isinstance(schema, list):
        return set().union(*(_felder(t) for t in schema)) if schema else set()
    if not isinstance(schema, dict):
        return set()
    namen = set(schema.get("properties") or {}) if isinstance(schema.get("properties"), dict) else set()
    for teil in schema.values():
        namen |= _felder(teil)
    return namen


def _pruefe(name: str, schema: dict, wert: object) -> None:
    bekannt = _felder(schema)

    def pfad(teile) -> str:
        text = "/".join(str(t) if isinstance(t, int) or t in bekannt else "?" for t in teile)
        return text or "(Wurzel)"

    fehler = sorted({f"Regel '{e.validator}' bei '{pfad(e.absolute_path)}'"
                     for e in Draft202012Validator(schema).iter_errors(wert)})
    if fehler:
        raise FormFehler(f"{name} verletzt das Schema: " + "; ".join(fehler))


def pruefe_eingabe(a: Auftragsart, wert: object) -> None:
    _pruefe("eingabe", a.eingabe, wert)


def pruefe_ergebnis(a: Auftragsart, wert: object) -> None:
    _pruefe("ergebnis", a.ergebnis, wert)


def art_hash(a: Auftragsart) -> str:
    """sha256 ueber die kanonische JSON-Form einer Art; in vibemind-os gleich berechenbar."""
    text = json.dumps(asdict(a), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
