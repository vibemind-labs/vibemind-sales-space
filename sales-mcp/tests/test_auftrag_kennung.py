"""Die Gateway-Kennung `auftrag` (Auftraege des Gehirns): Saat und Abholer muessen zusammenpassen.

Die Kennung hat KEIN Werkzeug. Damit kann ein Auftrag aus dem Auftragsbuch nie eine Freigabe
ausloesen, egal was im Auftrag oder in einer gelesenen Mail steht.
"""
import json
from pathlib import Path

import auftrag_abholer

WURZEL = Path(__file__).resolve().parents[2]


def _saat() -> dict:
    return json.loads((WURZEL / "config" / "openclaw.json").read_text(encoding="utf-8"))


def _agent(name: str) -> dict:
    treffer = [a for a in _saat()["agents"]["list"] if a.get("id") == name]
    assert len(treffer) == 1, f"Agent {name} fehlt in der Saat oder steht doppelt"
    return treffer[0]


def test_saat_kennt_die_kennung_des_abholers_ohne_werkzeuge():
    a = _agent(auftrag_abholer.AGENT)
    assert a["tools"] == {"deny": ["*"]}
    assert "allow" not in a["tools"]


def test_kennung_hat_eigenes_modell_ohne_rueckfall_und_eigenen_arbeitsordner():
    a = _agent(auftrag_abholer.AGENT)
    # Ohne eigenen Eintrag gaelte die Vorgabe mit Rueckfall auf ein fremdes Gratis-Modell.
    assert a["model"]["primary"].startswith("anthropic/")
    assert a["model"]["fallbacks"] == []
    assert a["workspace"] == "/home/node/.openclaw/workspace-auftrag"
    assert a["workspace"] != _saat()["agents"]["defaults"]["workspace"]


def test_main_bleibt_der_erste_agent():
    assert _saat()["agents"]["list"][0]["id"] == "main"
