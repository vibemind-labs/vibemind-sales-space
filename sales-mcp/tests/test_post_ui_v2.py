"""Mail-Reiter v2 (Post-Einordnung v2, Task 8): Unterfaecher mit Zaehler,
„Zum Nachsehen“ mit zwei Vorschlaegen zum Uebernehmen, lernende Korrektur
(Absender-Regel vorgewaehlt, ersetzt statt zu verdoppeln) gegen sales_test.
"""
import json
import os


os.environ["SALES_DB_SCHEMA"] = "sales_test"
import server  # noqa: E402
import post_struktur as ps  # noqa: E402
# Anmeldung, Personen und Hilfen wie in test_ui_post.py (Fixtures per Import).
from test_ui_post import (_get, _mail, _post, _zeile, schema_wache,  # noqa: E402,F401
                          welt)  # noqa: F401

VORSCHLAEGE = {
    "sortierer": {"bereich": "business", "fach": "Tools & Dienste",
                  "unterfach": "GitHub", "begruendung": "Mail von GitHub"},
    "pruefer": {"bereich": "privat", "fach": "Rechnungen", "unterfach": "",
                "begruendung": "sieht nach Rechnung aus"},
}


def _unklar(besitzer="t8_anna", von="GitHub <noreply@github.com>",
            vorschlaege=VORSCHLAEGE, vorschau=None):
    m = _mail(besitzer, "privat", ps.UNKLAR, von=von)
    with server.pool.connection() as conn:
        conn.execute("update post_mails set vorschlaege = %s::jsonb, "
                     "vorschau = %s::jsonb, einordnung_version = 1 where id = %s",
                     (json.dumps(vorschlaege) if vorschlaege else None,
                      json.dumps(vorschau) if vorschau else None, m))
    return m


def _setze_unterfach(mail_id, unterfach):
    with server.pool.connection() as conn:
        conn.execute("update post_mails set unterfach = %s where id = %s",
                     (unterfach, mail_id))


def test_navigation_zeigt_unterfaecher_mit_zaehler():
    for u in ("Instagram", "Instagram", "LinkedIn"):
        _setze_unterfach(_mail("t8_anna", "privat", "Soziale Netzwerke"), u)
    _mail("t8_anna", "privat", "Soziale Netzwerke")      # ohne Unterfach
    seite = _get("t8_anna", "/post").text
    assert "unterfach=Instagram" in seite and "unterfach=LinkedIn" in seite
    # Nur wo mindestens eine Mail liegt.
    assert "unterfach=TikTok" not in seite
    import re
    treffer = re.search(r'unterfach=Instagram[^>]*>Instagram <span class="zaehler">(\d+)<', seite)
    assert treffer and treffer.group(1) == "2"


def test_filter_unterfach():
    a = _mail("t8_anna", "privat", "Soziale Netzwerke", betreff="Insta-Post")
    b = _mail("t8_anna", "privat", "Soziale Netzwerke", betreff="Linkedin-Post")
    _setze_unterfach(a, "Instagram")
    _setze_unterfach(b, "LinkedIn")
    seite = _get("t8_anna", "/post?bereich=privat&fach=Soziale+Netzwerke"
                            "&unterfach=Instagram").text
    assert "Insta-Post" in seite and "Linkedin-Post" not in seite
    # Unterfach ohne passendes Fach: leer, kein 500.
    assert ps.mails_suchen(ps.betrachter_laden("t8_anna"), unterfach="Instagram") == []
    assert ps.mails_suchen(ps.betrachter_laden("t8_anna"), bereich="privat",
                           fach="Rechnungen", unterfach="Instagram") == []


def test_regelhaken_vorgewaehlt():
    m = _mail("t8_anna")
    assert 'name="regel" value="ja" checked' in _get("t8_anna", f"/post/mail/{m}").text
    # Fremde Mail der Leitung: weiterhin gar kein Haken.
    assert 'name="regel"' not in _get("t8_lea", f"/post/mail/{m}").text


def test_vorschlag_knoepfe_in_der_mail():
    m = _unklar()
    seite = _get("t8_anna", f"/post/mail/{m}").text
    assert f"/post/mail/{m}/vorschlag" in seite
    assert "Sortierer: Business · Tools &amp; Dienste · GitHub" in seite
    assert "Prüfer: Privat · Rechnungen" in seite
    # Ein Vorschlag fuer „Zum Nachsehen“ selbst bekommt keinen Knopf.
    m2 = _unklar(vorschlaege={
        "sortierer": {"bereich": "privat", "fach": ps.UNKLAR, "unterfach": ""},
        "pruefer": VORSCHLAEGE["pruefer"]})
    seite2 = _get("t8_anna", f"/post/mail/{m2}").text
    assert "Sortierer:" not in seite2 and "Prüfer: Privat" in seite2
    # Normale Mail: keine Vorschlaege.
    assert "/vorschlag" not in _get("t8_anna", f"/post/mail/{_mail()}").text


def test_vorschlag_uebernehmen_setzt_mensch_und_regel():
    m = _unklar()
    r = _post("t8_anna", f"/post/mail/{m}/vorschlag",
              {"wahl": "sortierer", "regel": "ja"})
    assert r.status_code == 303
    z = _zeile(m)
    assert (z["bereich"], z["fach"], z["unterfach"]) == (
        "business", "Tools & Dienste", "GitHub")
    assert (z["einordnung_quelle"], z["einordnung_version"]) == ("mensch", 3)
    assert z["vorschlaege"] is None and z["vorschau"] is None and z["begruendung"] is None
    regeln = server._q("select fach, unterfach, besitzer, bereich from post_regeln")
    assert len(regeln) == 1
    assert (regeln[0]["bereich"], regeln[0]["fach"], regeln[0]["unterfach"],
            regeln[0]["besitzer"]) == ("business", "Tools & Dienste", "GitHub", "t8_anna")


def test_vorschlag_ohne_haken_keine_regel_und_ungueltige_wahl():
    m = _unklar()
    assert _post("t8_anna", f"/post/mail/{m}/vorschlag",
                 {"wahl": "irgendwas"}).status_code == 400
    assert _zeile(m)["fach"] == ps.UNKLAR
    assert _post("t8_anna", f"/post/mail/{m}/vorschlag",
                 {"wahl": "pruefer"}).status_code == 303
    assert _zeile(m)["fach"] == "Rechnungen"
    assert server._q("select count(*) n from post_regeln")[0]["n"] == 0


def test_vorschlag_wird_erneut_geprueft():
    boese = {"sortierer": {"bereich": "privat", "fach": "Gibt es nicht",
                           "unterfach": ""},
             "pruefer": {"bereich": "privat", "fach": ps.UNKLAR, "unterfach": ""}}
    m = _unklar(vorschlaege=boese)
    for wahl in ("sortierer", "pruefer"):
        assert _post("t8_anna", f"/post/mail/{m}/vorschlag",
                     {"wahl": wahl}).status_code == 400
    assert _zeile(m)["fach"] == ps.UNKLAR
    # Ungueltiges Unterfach wird wie ueberall zu „Sonstige“ gezwungen.
    m2 = _unklar(vorschlaege={"sortierer": {"bereich": "business",
                                            "fach": "Tools & Dienste",
                                            "unterfach": "Erfunden"}})
    _post("t8_anna", f"/post/mail/{m2}/vorschlag", {"wahl": "sortierer"})
    assert _zeile(m2)["unterfach"] == "Sonstige"


def test_vorschlag_fremde_mail_ohne_regel():
    m = _unklar(besitzer="t8_ben")
    # Zum Nachsehen ist privat: die Leitung sieht Bens Mail gar nicht ->
    # 403 statt Aenderung. Business-Vorschlag auf Bens sichtbarer Mail:
    r = _post("t8_lea", f"/post/mail/{m}/vorschlag", {"wahl": "sortierer", "regel": "ja"})
    assert r.status_code == 403
    assert _zeile(m)["fach"] == ps.UNKLAR
    # Auch Bens Business-Mail sieht die Leitung nicht (ein Container = ein
    # Nutzer): 403, nichts geaendert, keine Regel fuer Bens Post.
    m2 = _mail("t8_ben", "business", "Kunden & Anfragen", von="x@y.de")
    with server.pool.connection() as conn:
        conn.execute("update post_mails set vorschlaege = %s::jsonb where id = %s",
                     (json.dumps(VORSCHLAEGE), m2))
    r = _post("t8_lea", f"/post/mail/{m2}/vorschlag", {"wahl": "sortierer", "regel": "ja"})
    assert r.status_code == 403
    assert _zeile(m2)["fach"] == "Kunden & Anfragen"
    assert server._q("select count(*) n from post_regeln")[0]["n"] == 0


def test_vorschlag_braucht_csrf_und_recht():
    m = _unklar()
    assert _post("t8_anna", f"/post/mail/{m}/vorschlag", {"wahl": "sortierer"},
                 csrf=False).status_code == 403
    assert _post("t8_leser", f"/post/mail/{m}/vorschlag",
                 {"wahl": "sortierer"}).status_code == 403
    assert _post("t8_ben", f"/post/mail/{m}/vorschlag",
                 {"wahl": "sortierer"}).status_code == 403
    assert _zeile(m)["fach"] == ps.UNKLAR


def test_korrektur_regel_ersetzt_statt_verdoppelt():
    von = "Max <max@firma.de>"
    m1 = _mail("t8_anna", "business", ps.UNKLAR, von=von)
    m2 = _mail("t8_anna", "business", ps.UNKLAR, von=von)
    _post("t8_anna", f"/post/mail/{m1}/korrigieren",
          {"bereich": "business", "fach": "Rechnungen", "regel": "ja"})
    _post("t8_anna", f"/post/mail/{m2}/korrigieren",
          {"bereich": "privat", "fach": "Soziale Netzwerke",
           "unterfach": "LinkedIn", "regel": "ja"})
    regeln = server._q("select bereich, fach, unterfach from post_regeln")
    assert len(regeln) == 1
    assert (regeln[0]["bereich"], regeln[0]["fach"], regeln[0]["unterfach"]) == (
        "privat", "Soziale Netzwerke", "LinkedIn")
    z = _zeile(m2)
    assert (z["unterfach"], z["einordnung_version"], z["einordnung_quelle"]) == (
        "LinkedIn", 3, "mensch")
    # Anderer Besitzer mit gleichem Muster behaelt seine Regel.
    m3 = _mail("t8_ben", "business", ps.UNKLAR, von=von)
    _post("t8_ben", f"/post/mail/{m3}/korrigieren",
          {"bereich": "business", "fach": "Rechnungen", "regel": "ja"})
    assert server._q("select count(*) n from post_regeln")[0]["n"] == 2


def test_korrektur_ohne_unterfach_fach_ohne_unterfaecher():
    m = _mail("t8_anna", "business", ps.UNKLAR)
    _post("t8_anna", f"/post/mail/{m}/korrigieren",
          {"bereich": "business", "fach": "Rechnungen", "unterfach": "GitHub"})
    assert _zeile(m)["unterfach"] is None


def test_mensch_loescht_vorschau_und_vorschlaege_auch_bei_sensibel():
    vorschau = {"bereich": "privat", "fach": "Gesundheit", "unterfach": "",
                "begruendung": "Befund von Dr. Meier, Diagnose X"}
    m = _unklar(vorschau=vorschau)
    r = _post("t8_anna", f"/post/mail/{m}/korrigieren",
              {"bereich": "privat", "fach": "Gesundheit", "sensibel": "ja"})
    assert r.status_code == 303
    z = _zeile(m)
    assert z["vorschau"] is None and z["vorschlaege"] is None
    assert z["text"] is None and z["sensibel"] is True


def test_korrektur_verschiebt_die_modellkosten_nicht_auf_heute():
    """Jeder Modellaufruf zaehlt genau einmal, an seinem Tag: Eine Korrektur von Hand
    darf den Tag der urspruenglichen Einordnung nicht auf heute ziehen."""
    import post_abholen
    m = _mail("t8_anna", "privat", "Rechnungen")
    with server.pool.connection() as conn:
        conn.execute("update post_mails set einordnung_quelle = 'modell', modellaufrufe = 2, "
                     "eingeordnet_am = now() - interval '1 day' where id = %s", (m,))
        gestern = conn.execute("select eingeordnet_am from post_mails where id = %s",
                               (m,)).fetchone()
    vorher = post_abholen.modellaufrufe_heute()
    r = _post("t8_anna", f"/post/mail/{m}/korrigieren",
              {"bereich": "privat", "fach": "Soziale Netzwerke"})
    assert r.status_code == 303
    z = _zeile(m)
    assert z["einordnung_quelle"] == "mensch" and z["fach"] == "Soziale Netzwerke"
    assert z["eingeordnet_am"] == (gestern["eingeordnet_am"] if isinstance(gestern, dict)
                                   else gestern[0])
    assert z["modellaufrufe"] == 2
    assert post_abholen.modellaufrufe_heute() == vorher


def test_sensible_mail_liefert_keine_begruendung_der_vorschlaege():
    m = _unklar()
    with server.pool.connection() as conn:
        conn.execute("update post_mails set sensibel = true where id = %s", (m,))
    gelesen = ps.mail_lesen(ps.betrachter_laden("t8_anna"), m)
    assert "begruendung" not in json.dumps(gelesen["vorschlaege"])
    assert gelesen["vorschlaege"]["sortierer"]["fach"] == "Tools & Dienste"
    # Nicht sensibel: Begruendung bleibt fuer die Anzeige. Die Liste liefert
    # Vorschlaege gar nicht erst.
    with server.pool.connection() as conn:
        conn.execute("update post_mails set sensibel = false where id = %s", (m,))
    assert "begruendung" in ps.mail_lesen(ps.betrachter_laden("t8_anna"), m)["vorschlaege"]["sortierer"]
    assert "vorschlaege" not in ps.mails_suchen(ps.betrachter_laden("t8_anna"))[0]


def test_zum_nachsehen_nie_unter_business():
    import re
    m = _mail("t8_anna", "business", "Kunden & Anfragen", von="n@firma.de")
    seite = _get("t8_anna", f"/post/mail/{m}").text
    gruppe = re.search(r'<optgroup label="Business">(.*?)</optgroup>', seite, re.S).group(1)
    assert ps.UNKLAR not in gruppe
    assert ps.UNKLAR in re.search(r'<optgroup label="Privat">(.*?)</optgroup>', seite, re.S).group(1)
    r = _post("t8_anna", f"/post/mail/{m}/korrigieren",
              {"bereich": "business", "fach": ps.UNKLAR, "regel": "ja"})
    assert r.status_code == 303
    z = _zeile(m)
    assert (z["bereich"], z["fach"]) == ("privat", ps.UNKLAR)
    assert server._q("select count(*) n from post_regeln")[0]["n"] == 0


def test_absender_ohne_adresse_korrektur_gelingt_mit_standardformular():
    m = _unklar(von="Kein Absender")
    seite = _get("t8_anna", f"/post/mail/{m}").text
    assert 'name="regel"' not in seite
    r = _post("t8_anna", f"/post/mail/{m}/korrigieren",
              {"bereich": "business", "fach": "Rechnungen"})
    assert r.status_code == 303 and _zeile(m)["fach"] == "Rechnungen"
    m2 = _unklar(von="Kein Absender")
    assert _post("t8_anna", f"/post/mail/{m2}/vorschlag",
                 {"wahl": "sortierer"}).status_code == 303
    # Selbstgebauter Haken ohne Adresse: weiterhin 400, nichts geaendert.
    m3 = _unklar(von="Kein Absender")
    assert _post("t8_anna", f"/post/mail/{m3}/korrigieren",
                 {"bereich": "business", "fach": "Rechnungen",
                  "regel": "ja"}).status_code == 400
    assert _zeile(m3)["fach"] == ps.UNKLAR


PRUEFSPALTEN = ("enthaelt_anweisung", "dringlichkeit", "geprueft_am", "pruef_aufrufe",
                "pruef_versuche", "anweisung_entscheid", "anweisung_entschieden_am")


def _markiert(mail_id):
    """Geprueft, mit Anweisung an eine KI, und Felix hat die Mail fuer den Agenten gesperrt."""
    with server.pool.connection() as conn:
        conn.execute("update post_mails set enthaelt_anweisung = true, dringlichkeit = 'heute', "
                     "geprueft_am = now() - interval '1 day', pruef_aufrufe = 1, "
                     "anweisung_entscheid = 'gesperrt', anweisung_entschieden_am = now() "
                     "where id = %s", (mail_id,))
    z = _zeile(mail_id)
    return {s: z[s] for s in PRUEFSPALTEN}


def test_korrektur_und_neu_einordnen_lassen_pruefung_stehen():
    """Post-Assistent 3a, Review Focus 2: eine menschliche Korrektur (Formular und
    Vorschlag) und die Neu-Sortierung (anwenden) ordnen neu ein, die Pruefung und
    Felix' Sperre bleiben stehen."""
    import post_neu_einordnen
    # Korrektur ueber das Formular.
    m = _mail("t8_anna", "business", "Kunden & Anfragen", von="X <x@absender.de>")
    vorher = _markiert(m)
    assert _post("t8_anna", f"/post/mail/{m}/korrigieren",
                 {"bereich": "business", "fach": "Rechnungen", "sensibel": "ja"}).status_code == 303
    z = _zeile(m)
    assert (z["fach"], z["einordnung_quelle"], z["sensibel"]) == ("Rechnungen", "mensch", True)
    assert {s: z[s] for s in PRUEFSPALTEN} == vorher

    # Vorschlag uebernehmen (derselbe Speicherweg, eigener Einstieg).
    v = _unklar()
    vorher = _markiert(v)
    assert _post("t8_anna", f"/post/mail/{v}/vorschlag", {"wahl": "pruefer"}).status_code == 303
    z = _zeile(v)
    assert (z["fach"], z["einordnung_quelle"]) == ("Rechnungen", "mensch")
    assert {s: z[s] for s in PRUEFSPALTEN} == vorher

    # Neu-Sortierung: anwenden uebernimmt eine Vorschau in die echten Spalten.
    n = _mail("t8_anna", "business", "Sonstiges", von="Y <y@absender.de>")
    with server.pool.connection() as conn:
        conn.execute("update post_mails set einordnung_version = 1, vorschau = %s::jsonb "
                     "where id = %s",
                     (json.dumps({"bereich": "privat", "fach": "Rechnungen", "unterfach": None,
                                  "sensibel": False, "quelle": "pruefer", "begruendung": "neu",
                                  "vorschlaege": None, "aufrufe": 2, "aufmerksamkeit": False,
                                  "werbung_sicher": False}), n))
    vorher = _markiert(n)
    assert post_neu_einordnen.anwenden() == 1
    z = _zeile(n)
    assert (z["bereich"], z["fach"], z["einordnung_version"], z["vorschau"]) == \
        ("privat", "Rechnungen", 3, None)
    assert {s: z[s] for s in PRUEFSPALTEN} == vorher


# ---------------------------------------------------------------------------
# 3a Task 6: Dringlichkeit in der Liste, Hinweis bei Anweisung an eine KI
# ---------------------------------------------------------------------------

def _setze(mail_id, **spalten):
    sets = ", ".join(f"{k} = %s" for k in spalten)
    with server.pool.connection() as conn:
        conn.execute(f"update post_mails set {sets} where id = %s",
                     list(spalten.values()) + [mail_id])


def test_liste_ohne_suche_nach_dringlichkeit():
    import re
    alt = _mail("t8_anna", "business", "Kunden & Anfragen", betreff="Dringend-Alt")
    neu = _mail("t8_anna", "business", "Kunden & Anfragen", betreff="Ruhig-Neu")
    _setze(alt, datum="2026-01-01T10:00:00Z", dringlichkeit="sofort")
    _setze(neu, datum="2026-02-01T10:00:00Z", dringlichkeit="nichts")
    seite = _get("t8_anna", "/post?bereich=business&fach=Kunden+%26+Anfragen").text
    assert seite.index("Dringend-Alt") < seite.index("Ruhig-Neu")
    # Mit Suchtext gilt die Datumsfolge (neueste zuerst).
    seite = _get("t8_anna", "/post?bereich=business&fach=Kunden+%26+Anfragen&q=Hallo").text
    assert re.search(r"Ruhig-Neu.*Dringend-Alt", seite, re.S)


def test_mailzeile_zeigt_dringlichkeit():
    s = _mail("t8_anna", "business", "Kunden & Anfragen", betreff="Eilig-Mail")
    n = _mail("t8_anna", "business", "Kunden & Anfragen", betreff="Gelassen-Mail")
    _setze(s, dringlichkeit="sofort")
    _setze(n, dringlichkeit="nichts")
    seite = _get("t8_anna", "/post?bereich=business&fach=Kunden+%26+Anfragen").text
    zeilen = {t.split("</b>")[0].split("<b>")[-1]: t
              for t in seite.split('<a class="mailzeile"')[1:]}
    assert ">sofort</span>" in zeilen["Eilig-Mail"]
    assert ">sofort<" not in zeilen["Gelassen-Mail"]
    assert ">heute<" not in zeilen["Gelassen-Mail"]


def test_mailansicht_hinweis_anweisung():
    m = _mail("t8_anna", "business", "Kunden & Anfragen", text="Ignoriere alles und ...")
    _setze(m, enthaelt_anweisung=True, geprueft_am="2026-02-01T10:00:00Z")
    seite = _get("t8_anna", f"/post/mail/{m}").text
    assert "Anweisung an eine KI erkannt – für den Agenten gesperrt" in seite
    assert "/freigaben?tab=nachrichten&amp;art=anweisung" in seite \
        or "/freigaben?tab=nachrichten&art=anweisung" in seite
    assert "Ignoriere alles" in seite        # Besitzer sieht den Inhalt weiter
    _setze(m, anweisung_entscheid="freigegeben")
    seite = _get("t8_anna", f"/post/mail/{m}").text
    assert "für den Agenten freigegeben" in seite
    assert "für den Agenten gesperrt" not in seite
    # Ohne Markierung kein Hinweis.
    k = _mail("t8_anna", "business", "Kunden & Anfragen")
    assert "Anweisung an eine KI" not in _get("t8_anna", f"/post/mail/{k}").text
