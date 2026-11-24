"""Feste Faecherstruktur der Post-Sammelstelle (Spec §4, vom Betreiber bestaetigt).

Die Liste liegt hier als Daten, nicht verstreut im Prompt: der Agent darf nur
aus ihr waehlen, ein neues Fach legt ein Mensch bewusst an.
"""

import email.utils
import re

BEREICHE = ("privat", "business")

# Richtung einer Mail (Stufe 1): eingegangen oder vom Besitzer gesendet. Faecher,
# Listen, Warteschlangen und Aufraeumen meinen nur `eingang`; Suche und
# Unterhaltung beide. Der Status allein ist nicht der Vertrag.
RICHTUNGEN = ("eingang", "gesendet")

# Dringlichkeit einer Mail, von dringend nach unwichtig (Spec 3a).
DRINGLICHKEITEN = ("sofort", "heute", "kann_warten", "nichts")


def dringender(a: str | None, b: str | None) -> str | None:
    """Die dringendere von zwei Stufen; None zaehlt nicht."""
    stufen = [x for x in (a, b) if x in DRINGLICHKEITEN]
    return min(stufen, key=DRINGLICHKEITEN.index) if stufen else None

# „Zum Nachsehen“ ist das Fach fuer alles, was nicht sicher zuzuordnen ist
# (Sortierer und Pruefer uneins); solche Mails liegen immer privat, damit nur
# der Besitzer sie sieht, bis ein Mensch sie einordnet. Der Konstantenname
# bleibt UNKLAR, damit Aufrufer sich nicht aendern muessen.
UNKLAR = "Zum Nachsehen"

FAECHER: dict[str, tuple[str, ...]] = {
    "privat": (
        "Familie & Freunde", "Käufe & Bestellungen", "Rechnungen",
        "Behörden & Versicherung", "Gesundheit", "Abos & Newsletter",
        "Soziale Netzwerke", "Konten & Sicherheit", "Werbung", UNKLAR,
    ),
    "business": (
        "Kunden & Anfragen", "Partner & Netzwerk", "Veranstaltungen",
        "Rechnungen", "Tools & Dienste", "Soziale Netzwerke",
        "Konten & Sicherheit", "Bewerbungen & Jobs", "Newsletter & Branche",
        "Werbung", UNKLAR,
    ),
}

# Dritte Ebene (Spec §4): nur wo unten genannt; „Sonstige“ faengt den Rest.
SOZIAL = ("Instagram", "LinkedIn", "TikTok", "YouTube", "Facebook & Meta",
          "X", "Bluesky", "Mastodon", "Threads", "Sonstige")
ANBIETER = ("GitHub", "Notion", "Vercel", "OpenRouter", "Tailscale",
            "Anthropic", "OpenAI", "Google", "Namecheap", "Hashnode", "dev.to",
            "Spotify", "Cal.com", "Calendly", "Adobe", "Nebius", "Tavily",
            "HubSpot", "Sonstige")
# Gilt in beiden Bereichen. Konten & Sicherheit kennt Netzwerke UND Anbieter;
# „Sonstige“ steht nur einmal (aus ANBIETER).
UNTERFAECHER: dict[str, tuple[str, ...]] = {
    "Soziale Netzwerke": SOZIAL,
    "Tools & Dienste": ANBIETER,
    "Konten & Sicherheit": SOZIAL[:-1] + ANBIETER,
}

# Faecher, in denen Post des Absenders nie als Werbung gilt (Spec §4): wer hier
# auch nur eine Mail hat, wird nicht zum Werbe-Absender und nichts von ihm wird
# automatisch geloescht. Rechnungen & Co. liegen in beiden Bereichen unter
# demselben Namen.
BLEIBT_IMMER = frozenset({
    "Rechnungen", "Käufe & Bestellungen", "Konten & Sicherheit",
    "Behörden & Versicherung", "Gesundheit", "Familie & Freunde",
    "Kunden & Anfragen", "Partner & Netzwerk",
})


def absender_adresse(von: str) -> str:
    """Reine Mailadresse aus einem From-Wert, kleingeschrieben; leer ohne „@“."""
    adresse = email.utils.parseaddr(von or "")[1].strip().lower()
    return adresse if "@" in adresse else ""


def absender_muster(adresse: str) -> str:
    """Regel-Muster, das GENAU diese Adresse trifft (Ruling R12).

    Wörtlich (re.escape): „+“ und „.“ sind keine Musterzeichen. Verankert an
    Anfang/Ende oder an <, >, Leerzeichen, Anführungszeichen, weil
    post_einordnung re.search benutzt: sonst träfe a@x.de auch ba@x.de oder
    a@x.de.evil.com. Groß/klein ignoriert die Einordnung selbst."""
    return r'(^|[<\s"])' + re.escape(adresse) + r'($|[>\s"])'


# Faecher, die es nur unter business gibt: Firmenwerkzeuge sind Firmensache,
# sie ziehen den Bereich auf business (Spec §5, „Fach passt nicht zum Bereich“).
NUR_BUSINESS = frozenset({
    "Kunden & Anfragen", "Partner & Netzwerk", "Veranstaltungen",
    "Tools & Dienste", "Bewerbungen & Jobs", "Newsletter & Branche",
})

# Steht im Auftrag von Sortierer und Pruefer; privat betont, dass es den
# Inhaber persoenlich betreffen muss (im Zweifel gehoert Post zur Firma).
BESCHREIBUNG: dict[tuple[str, str], str] = {
    ("business", "Kunden & Anfragen"):
        "Anfragen, Angebote, laufende Kundengespräche.",
    ("business", "Partner & Netzwerk"):
        "Kooperationen, Förderer, Hochschulen, persönliche Kontakte aus dem Netzwerk.",
    ("business", "Veranstaltungen"):
        "Einladungen, Anmeldungen, Tickets, Event-Plattformen (Luma, Easyfairs, Meetups).",
    ("business", "Rechnungen"):
        "Rechnungen, Zahlungen, Quittungen der Firma.",
    ("business", "Tools & Dienste"):
        "Mitteilungen von Software und Diensten, die die Firma nutzt (Produkt, Konto, Abrechnung).",
    ("business", "Soziale Netzwerke"):
        "Mitteilungen der Firmenkanäle in sozialen Netzwerken.",
    ("business", "Konten & Sicherheit"):
        "Login- und Bestätigungscodes, Passwort, Sicherheitswarnungen, Kontoänderungen.",
    ("business", "Bewerbungen & Jobs"):
        "Bewerbungen an die Firma, Jobplattformen.",
    ("business", "Newsletter & Branche"):
        "Fach-Newsletter, Branchennews, Substack.",
    ("business", "Werbung"):
        "Unaufgeforderte Verkaufsmails, Cold Outreach.",
    ("business", UNKLAR):
        "Sortierer und Prüfer sind uneins oder beide unsicher.",
    ("privat", "Familie & Freunde"):
        "Persönliche Post von Familie und Freunden an den Inhaber.",
    ("privat", "Käufe & Bestellungen"):
        "Bestellbestätigungen, Versand und Lieferung privater Einkäufe des Inhabers.",
    ("privat", "Rechnungen"):
        "Rechnungen, Zahlungen und Quittungen, die den Inhaber persönlich betreffen.",
    ("privat", "Behörden & Versicherung"):
        "Post von Behörden, Krankenkasse und Versicherungen, die den Inhaber persönlich betrifft.",
    ("privat", "Gesundheit"):
        "Arzttermine, Befunde, Rezepte, die den Inhaber persönlich betreffen.",
    ("privat", "Abos & Newsletter"):
        "Private Abos und Newsletter, die der Inhaber persönlich bezieht.",
    ("privat", "Soziale Netzwerke"):
        "Mitteilungen privater Konten in sozialen Netzwerken, die den Inhaber persönlich betreffen.",
    ("privat", "Konten & Sicherheit"):
        "Login- und Bestätigungscodes, Passwort, Sicherheitswarnungen zu privaten Konten des Inhabers.",
    ("privat", "Werbung"):
        "Unaufgeforderte Werbung an den Inhaber persönlich.",
    ("privat", UNKLAR):
        "Sortierer und Prüfer sind uneins oder beide unsicher; nur der Inhaber sieht es.",
}


def unterfach_gueltig(fach: str, unterfach: "str | None") -> bool:
    """Fach ohne Unterfaecher: nur leer gueltig; sonst nur Werte der Liste."""
    erlaubt = UNTERFAECHER.get(fach)
    if erlaubt is None:
        return not unterfach
    return unterfach in erlaubt


def unterfach_zwingen(fach: str, unterfach: "str | None") -> "str | None":
    """Macht aus einem beliebigen Modellwert einen gueltigen: ungueltig oder
    leer wird „Sonstige“ (Fach mit Unterfaechern) bzw. None (Fach ohne)."""
    if fach not in UNTERFAECHER:
        return None
    return unterfach if unterfach in UNTERFAECHER[fach] else "Sonstige"


def bereich_fuer(fach: str, standard: str) -> str:
    """Bereich fuer ein Fach, das Katalog oder Regel nennt: reine Business-
    Faecher ziehen nach business; sonst gilt der Standardbereich des Kontos,
    falls das Fach dort existiert, sonst der andere Bereich mit dem Fach."""
    if fach in NUR_BUSINESS:
        return "business"
    if fach in FAECHER.get(standard, ()):
        return standard
    for br in BEREICHE:
        if br != standard and fach in FAECHER[br]:
            return br
    return standard


def fach_gueltig(bereich: str, fach: str) -> bool:
    """True, wenn `fach` in `bereich` existiert (Zum Nachsehen gilt in beiden)."""
    return fach in FAECHER.get(bereich, ())


# ---------------------------------------------------------------------------
# Sichtbarkeit (Spec §6, §7, §14.3): EINE Stelle entscheidet, welche Mails
# eine Person oder der Bot sehen darf. Jede Seite, Suche und jedes Bot-
# Werkzeug geht hierdurch; ein Fehler waere ein Datenleck privater Post.
# ---------------------------------------------------------------------------
import os
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class Betrachter:
    name: str
    leitung: bool
    abteilungen: tuple[str, ...]
    ist_agent: bool = False


# Der Bot handelt fuer den Betreiber DIESES Containers (Ein Container = ein
# Nutzer, DSGVO): `sichtbar_sql` begrenzt ihn auf dessen Business-Mails.
# leitung/abteilungen sind fuer Mails ohne Wirkung.
BETREIBER_AGENT = Betrachter(name="agent", leitung=True, abteilungen=(),
                             ist_agent=True)


def container_besitzer() -> str:
    """Benutzername, dem dieser Container gehoert (`POST_BESITZER`). Wird bei
    jedem Aufruf gelesen; leer, wenn nicht gesetzt."""
    return os.environ.get("POST_BESITZER", "").strip()


def mail_verlauf_erlaubt(name: "str | None") -> bool:
    """Wahr genau dann, wenn `name` der Besitzer dieses Containers ist. Nur
    dann darf zu einem Kontakt der Mailverlauf gezeigt werden."""
    return bool(name) and container_besitzer() == name


def betrachter_laden(name: str) -> "Betrachter | None":
    """Betrachter aus `benutzer` + `benutzer_abteilungen`; None, wenn
    unbekannt oder deaktiviert (ein gesperrter Zugang sieht nichts)."""
    import server
    zeilen = server._q(
        "select name, leitung from benutzer where name = %s and aktiv",
        (name,))
    if not zeilen:
        return None
    abt = server._q(
        "select abteilung from benutzer_abteilungen where benutzer = %s "
        "order by abteilung", (name,))
    return Betrachter(name=zeilen[0]["name"],
                      leitung=bool(zeilen[0]["leitung"]),
                      abteilungen=tuple(a["abteilung"] for a in abt))


def sichtbar_sql(b: Betrachter, alias: str = "m") -> tuple[str, list]:
    """(WHERE-Fragment mit %s-Platzhaltern, Parameter) fuer `from post_mails <alias>`
    (Standard `m`; `alias` fuer Unterabfragen).

    Ein Container = ein Nutzer (DSGVO): Mails sieht nur ihr Besitzer, egal in
    welchem Bereich - Leitung und Abteilungen nicht. Der Bot sieht nur die
    nicht sensiblen Business-Mails des Container-Besitzers; ist keiner
    gesetzt, nichts.
    """
    if b.ist_agent:
        besitzer = container_besitzer()
        if not besitzer:
            return ("false", [])
        return (f"({alias}.bereich = 'business' and {alias}.sensibel is false "
                f"and {alias}.besitzer = %s)", [besitzer])
    return (f"({alias}.besitzer = %s)", [b.name])


# 3a: Den Inhalt einer Mail liest der Agent nur, wenn sie geprueft ist und
# keine Anweisung an eine KI enthaelt - oder der Besitzer sie freigegeben hat.
# Hat der Besitzer sie gesperrt, bleibt sie gesperrt, auch wenn eine spaetere
# Pruefung sie als unbedenklich einstuft (R9).
# Gesendete Mails liest der Agent nie (Ruling S1): ausdruecklich hier, nicht nur,
# weil sie kein geprueft_am bekommen.
AGENT_LESBAR_SQL = (
    "(m.richtung = 'eingang' "
    "and m.geprueft_am is not null "
    "and m.anweisung_entscheid is distinct from 'gesperrt' "
    "and (m.enthaelt_anweisung is false "
    "or m.anweisung_entscheid = 'freigegeben'))")

# Pruefenster (Final-Fix F1, R6): so viel einer Mail sehen Sortierer und
# Nachpruefung (post_einordnung nimmt die Werte von hier) - und mehr bekommt
# der Agent auch von einer lesbaren Mail nicht. Text, Empfaenger und
# Anhangnamen, die die Pruefung nie sah, gelten nicht als geprueft.
PRUEF_TEXT_MAX = 4000        # Zeichen Text
PRUEF_KOPF_MAX = 300         # Zeichen je Kopfwert (Absender, Betreff, Empfaenger, Anhangname)
PRUEF_ANHAENGE_MAX = 50      # Anhangnamen


def _spalten(mit_vorschlaegen: bool = False, agent: bool = False) -> str:
    # Text, Auszug, Anhaenge und Empfaenger sensibler Mails werden schon in
    # SQL geleert: sie verlassen die Datenbank gar nicht erst (Spec §5: nur
    # Konto, Absender, Datum, Betreff, Fach, Markierung), auch nicht fuer den
    # Besitzer. `is not false` behandelt NULL wie sensibel (fail closed).
    s = "m.sensibel is not false"
    an, anhaenge, auszug, text = "m.an", "m.anhaenge", "m.auszug", "m.text"
    if agent:
        import postfach
        # Fuer den Agenten zusaetzlich alles, was nicht lesbar ist (3a): nur
        # Kopf. `is not true` statt `not`, damit ein SQL-NULL in der Pruefung
        # (geprueft, aber ohne Ergebnis) den Text nicht durchlaesst.
        lesbar = f"({AGENT_LESBAR_SQL}) is true"
        s = f"({s} or ({AGENT_LESBAR_SQL}) is not true)"
        hinweis = (f", case when {lesbar} then null "
                   "when m.enthaelt_anweisung is true "
                   "or m.anweisung_entscheid = 'gesperrt' then 'anweisung' "
                   "else 'nicht_geprueft' end as agent_hinweis")
        # Die Dringlichkeit stammt aus demselben Modellaufruf, der den
        # (womoeglich praeparierten) Text las - bei Nur-Kopf-Mails nicht an
        # den Agenten (Spec 3a.5: nur Absender, Betreff, Hinweis).
        dringlichkeit = f"case when {s} then null else m.dringlichkeit end"
        # Auch eine lesbare Mail nur so weit, wie die Pruefung sie sah (F1).
        # Die Zahlen sind Konstanten dieses Moduls, keine Eingaben.
        n, kopf = int(PRUEF_TEXT_MAX), int(PRUEF_KOPF_MAX)
        text = f"left(m.text, {n})"
        an = f"left(m.an, {kopf})"
        anhaenge = (f"array(select left(a.name, {kopf}) from unnest("
                    f"m.anhaenge[1:{int(PRUEF_ANHAENGE_MAX)}]) with ordinality "
                    "as a(name, nr) order by a.nr)")
        # Der gespeicherte Auszug zieht Leerraum zusammen und kann so ueber
        # das Fenster hinausreichen: bei langem Text neu aus dem Fenster.
        # NULL-Text faellt in den else-Zweig und bleibt NULL (fail closed).
        auszug = (f"case when length(m.text) <= {n} then m.auszug else "
                  f"left(btrim(regexp_replace(left(m.text, {n}), '\\s+', ' ', 'g')), "
                  f"{int(postfach.AUSZUG_MAX)}) end")
        hinweis += (f", case when {s} then false "
                    f"else coalesce(length(m.text) > {n}, false) end as text_gekuerzt")
    else:
        hinweis = ""
        dringlichkeit = "m.dringlichkeit"
    return ("m.id, m.konto_id, m.besitzer, m.von, m.betreff, m.datum, "
            "m.richtung, "
            "m.bereich, m.fach, m.unterfach, m.sensibel, m.status, m.gesehen_am, "
            f"m.ziel, m.ordner, m.ordner_am, {dringlichkeit} as dringlichkeit, "
            "m.enthaelt_anweisung, m.anweisung_entscheid, "
            f"case when {s} then false else m.kalenderteil end as kalenderteil, "
            f"case when {s} then null else {an} end as an, "
            f"case when {s} then '{{}}'::text[] else {anhaenge} end as anhaenge, "
            f"case when {s} then null else {auszug} end as auszug, "
            f"case when {s} then null else {text} end as text"
            + hinweis
            + (", " + _vorschlaege_spalte(s) if mit_vorschlaegen else ""))


def _vorschlaege_spalte(sensibel_sql: str) -> str:
    # Die Modell-Begruendung ist freier Text ueber die Mail. Bei sensiblen
    # Mails (Spec §5) darf sie die Datenbank nicht verlassen, auch wenn sie
    # dort - gegen die Regel - doch stuende: Tiefenverteidigung, die
    # Einordnung schreibt sie fuer solche Mails ohnehin nicht.
    return (f"case when {sensibel_sql} then (select jsonb_object_agg(e.key, "
            "case when jsonb_typeof(e.value) = 'object' then e.value - 'begruendung' "
            "else e.value end) from jsonb_each(m.vorschlaege) e) "
            "else m.vorschlaege end as vorschlaege")


ZIEL_ANSICHTEN = ("aufmerksamkeit", "zur_info", "to_review")


def ziel_sql(ziel: str) -> str:
    """WHERE-Fragment (ohne Parameter) fuer eine Reiter-Ansicht; leer ohne Filter.

    Geloeschte Mails stehen in keinem Mail-Reiter. `aufmerksamkeit` nimmt zusaetzlich
    Mails ohne Ziel mit: was noch nicht entschieden ist, muss sichtbar bleiben.
    Reiter zeigen nur eingehende Mails (gesendete stehen in Unterhaltung und Suche)."""
    if ziel == "aufmerksamkeit":
        return ("(m.richtung = 'eingang' and m.status <> 'geloescht' "
                "and (m.ziel = 'posteingang' or m.ziel is null))")
    if ziel in ("zur_info", "to_review"):
        return (f"(m.richtung = 'eingang' and m.status <> 'geloescht' "
                f"and m.ziel = '{ziel}')")
    return ""


def mails_suchen(b: Betrachter, suche: str = "", bereich: str = "",
                 fach: str = "", konto_id: str = "", grenze: int = 50,
                 versatz: int = 0, unterfach: str = "", ziel: str = "",
                 nach_dringlichkeit: bool = False, richtung: str = "") -> list[dict]:
    """Mails, die `b` sehen darf, neueste zuerst. `nach_dringlichkeit`
    sortiert erst nach Dringlichkeit: sofort, heute, dann kann_warten und
    ungepruefte gemeinsam (der Altbestand rutscht nicht nach unten), zuletzt
    nichts; innerhalb eines Rangs nach Datum.

    `richtung` (eingang/gesendet) filtert ausdruecklich. Leer gilt: ohne
    `suche` nur eingehende Mails (Liste), mit `suche` beide Richtungen."""
    import server
    if ziel and ziel not in ZIEL_ANSICHTEN:
        return []
    if richtung and richtung not in RICHTUNGEN:
        return []
    sucht = bool(suche and suche.strip())
    if not richtung and not sucht:
        richtung = "eingang"
    if bereich and bereich not in BEREICHE:
        return []
    if fach:
        gueltig = (fach_gueltig(bereich, fach) if bereich
                   else any(fach_gueltig(x, fach) for x in BEREICHE))
        if not gueltig:
            return []
    # Ein Unterfach gibt es nur unter einem Fach, das es kennt.
    if unterfach and unterfach not in UNTERFAECHER.get(fach, ()):
        return []
    if konto_id:
        try:
            konto_id = str(uuid.UUID(str(konto_id)))
        except ValueError:
            return []
    where, params = sichtbar_sql(b)
    teile = [where]
    if ziel:
        teile.append(ziel_sql(ziel))
    if bereich:
        teile.append("m.bereich = %s")
        params.append(bereich)
    if fach:
        teile.append("m.fach = %s")
        params.append(fach)
    if unterfach:
        teile.append("m.unterfach = %s")
        params.append(unterfach)
    if konto_id:
        teile.append("m.konto_id = %s")
        params.append(konto_id)
    if richtung:
        teile.append("m.richtung = %s")
        params.append(richtung)
    if sucht:
        # Die Suche deckt alle Reiter ab, geloeschte Mails aber nie.
        teile.append("m.status <> 'geloescht'")
        teile.append("m.suchtext @@ websearch_to_tsquery('german', %s)")
        params.append(suche)
    params += [max(1, min(int(grenze), 200)), max(0, int(versatz))]
    rang = ("case m.dringlichkeit when 'sofort' then 0 when 'heute' then 1 "
            "when 'nichts' then 3 else 2 end, " if nach_dringlichkeit else "")
    return server._q(
        f"select {_spalten(agent=b.ist_agent)} from post_mails m where "
        + " and ".join(teile)
        + f" order by {rang}m.datum desc nulls last, m.gesehen_am desc "
          "limit %s offset %s", params)


def mail_lesen(b: Betrachter, mail_id: str) -> "dict | None":
    """Eine Mail, wenn `b` sie sehen darf; sonst None (auch bei unbekannter
    oder kaputter id - kein Unterschied, damit nichts durchsickert). Der
    Agent bekommt ungepruefte oder markierte Mails nur als Kopf mit
    `agent_hinweis` (3a)."""
    import server
    try:
        mid = str(uuid.UUID(str(mail_id)))
    except ValueError:
        return None
    where, params = sichtbar_sql(b)
    zeilen = server._q(
        f"select {_spalten(mit_vorschlaegen=True, agent=b.ist_agent)} "
        "from post_mails m "
        f"where m.id = %s and {where}",
        [mid] + params)
    return zeilen[0] if zeilen else None


def unterhaltung_lesen(b: Betrachter, mail_id: str, grenze: int = 50) -> list[dict]:
    """Mails der Unterhaltung von `mail_id`, die `b` sehen darf, nach Datum
    aufsteigend (beide Richtungen). Ist die Mail selbst unsichtbar, unbekannt
    oder ohne Unterhaltung, kommt `[]`. Ist die Unterhaltung laenger als `grenze`,
    bleiben die neuesten `grenze` Mails, und die angesehene Mail ist immer dabei.
    Sichtbarkeit und Agenten-Sperre kommen aus `sichtbar_sql` und `_spalten`;
    es gibt hier keine zweite Regel."""
    import server
    try:
        mid = str(uuid.UUID(str(mail_id)))
    except ValueError:
        return []
    where, params = sichtbar_sql(b)
    innen, innen_params = sichtbar_sql(b, "u")
    return server._q(
        "select * from (select "
        f"{_spalten(agent=b.ist_agent)} from post_mails m where {where} "
        "and m.status <> 'geloescht' and m.unterhaltung is not null "
        "and m.unterhaltung = (select u.unterhaltung from post_mails u "
        f"where u.id = %s and {innen}) "
        "order by (m.id = %s) desc, m.datum desc nulls last, m.gesehen_am desc, m.id desc "
        "limit %s) x order by x.datum asc nulls last, x.gesehen_am asc, x.id",
        params + [mid] + innen_params + [mid, max(1, min(int(grenze), 200))])
