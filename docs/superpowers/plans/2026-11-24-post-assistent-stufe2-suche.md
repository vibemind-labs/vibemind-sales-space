# Post-Assistent Stufe 2: Suche nach Bedeutung (hybrid)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jede Mail der Sammelstelle, eingehend wie gesendet, bekommt Vektoren. Diese werden am PC mit Ollama (`qwen3-embedding:0.6b`, 1024 Dimensionen) berechnet. Eine Suche mischt Bedeutung und Wörter zu einer Rangliste. Posteingang-Suchfeld und Agent nutzen denselben Weg. Ist der PC aus, wird nur nach Wörtern gesucht, und die Antwort sagt das.

**Architecture:**
- Eine Tabelle `post_vektoren` mit HNSW-Index (Kosinus).
- Ein Datenbank-Auslöser löscht die Vektoren einer Mail, sobald sich ihr Inhalt oder ihr Schutz ändert. So kann kein Codeweg veraltete oder geschützte Inhalte im Index lassen.
- Das neue Modul `post_vektor.py` zerlegt Mails in Teile und ruft Ollama auf. `sales-post` holt fehlende Vektoren in jeder Runde mit kurzer Zeitgrenze nach.
- Das neue Modul `post_suche.py` stellt Vektor- und Wort-Teilabfrage zusammen und mischt sie per Reciprocal Rank Fusion. Beide Teilabfragen tragen `sichtbar_sql` und die Agenten-Regeln.

**Tech Stack:** Python 3 (sales-mcp, urllib), PostgreSQL mit pgvector 0.8.0 (Typ `vector` liegt im Schema `public`), Ollama am PC über das Tailnet, Starlette-UI, pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-post-assistent-design.md`, Abschnitt 5 / **Stufe 2**, dazu §2 und §6. Setzt Stufe 1 (`richtung`) und 3a (Agenten-Sperre) voraus.

## Global Constraints

- Kein Modell auf der VM. Eingebettet wird nur am PC (Spec §6, Ansatz A).
- Einbetten blockiert nie die Runde. Ist der PC nicht erreichbar, wird übersprungen. Neue Mails bekommen ihren Vektor in der nächsten Runde mit erreichbarem PC (Spec 2.2).
- „Der Sichtbarkeitsfilter gilt in beiden Teilabfragen, nie erst danach“ (Spec 2.3).
- Ist der PC aus, wird nur nach Wörtern gesucht. Die Antwort trägt `nur_wortsuche: true`, das UI zeigt den Hinweis, der Agent sagt es dazu (Spec 2.4).
- Sensible Mails werden nur mit Betreff und Absender eingebettet (Spec 2.1).
- Nur der Env-**Name** steht in Git: `POST_EMBEDDING_URL`. Der Wert ist die Ollama-Adresse am PC übers Tailnet, dieselbe, die der Lern-Embedder nutzt. `OLLAMA_URL` ist es **nicht**: Es zeigt bei sales-claw auf das KI-Tor (`sales-ki`).
- Keine Mailtexte, Betreffe, Suchfragen oder Adressen in Logs. Logs nennen nur Anzahlen, Mail-IDs und Ausnahmetypen.
- Ladenfest: Migration je Schema, Code nur über `server._q`.
- Tests ohne Live-`.env` und ohne echtes Ollama. Ollama wird im Test durch einen lokalen HTTP-Stub auf `127.0.0.1` ersetzt.
- Nicht deployen und nichts auf `sales` ohne Felix' OK. Der Plan endet vor dem Ausrollen.
- Conventional Commits mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Feste Werte:
  - `MODELL = "qwen3-embedding:0.6b"`, `DIMENSIONEN = 1024`
  - Teil 0 = Kopf (`Betreff`, `Von`, `An`). Die Teile 1 bis 6 sind Text, je 2000 Zeichen mit 200 Zeichen Überlappung. Darüber hinaus wird nichts eingebettet.
  - Frage-Präfix (Qwen3-Embedding, nur für Suchfragen): `Instruct: Finde E-Mails, die zu dieser Suche passen\nQuery: `
  - Ollama: `POST /api/embed` mit `keep_alive: "2m"` und `truncate: true`. Zeitgrenze je Anfrage `POST_EMBEDDING_TIMEOUT_S` (Standard 20), Zeitgrenze je Runde 45 s, höchstens 32 Teile je Anfrage.
  - RRF mit `k = 60`, je Teilabfrage höchstens 100 Kandidaten.

**Rulings dieses Plans:**
- **V1:** Für den Agenten zählen nur Teile, die er auch lesen darf. Bei nicht lesbaren Mails (ungeprüft, markiert, gesendet) ist das nur Teil 0. Bei lesbaren Mails sind es Teil 0 und die Textteile, die vor `post_struktur.PRUEF_TEXT_MAX` beginnen. Die Wortsuche des Agenten prüft bei nicht lesbaren Mails nur Betreff und Absender. Grund: Die Rangliste soll nichts über Text verraten, den der Agent nicht sehen darf. Das schließt den offenen Punkt „Suche als Orakel“ aus 3a. Kosten, falls falsch: Der Agent findet markierte Mails nur über den Kopf.
- **V2:** Die Wortsuche des Besitzers bleibt unverändert (`suchtext`).
- **V3:** Der Autostart von Ollama am PC existiert schon (Aufgabe „VibeMind Ollama“, `scripts/ollama-pc.ps1`, am 24.11. registriert und laufend). Er wird nicht neu gebaut. Das Runbook prüft ihn nur mit `-Pruefen`.

**Arbeitsplatz und Testlauf:** wie im Plan von Stufe 1, mit Worktree `wt-sales-stufe2` auf Zweig `cc/post-assistent-stufe2`. Die Basis ist der Kopf von `cc/post-assistent-stufe1`. VM-Pfade `/tmp/wt-s2`, `/tmp/wt-s2.env`. Vorher sind WORKBOARD und Vault zu prüfen und ein eigener Claim `cc-post-stufe2` zu setzen.

## Review Focus

1. **Der PC geht mitten in einer Runde aus** (Zeitüberschreitung nach Teil 10 von 40). Erwartung: Die bis dahin berechneten Mails sind vollständig gespeichert, eine Mail mit halbem Teilsatz gibt es nicht, und die Runde läuft weiter. Test in Task 3: `test_pc_faellt_mitten_aus_keine_halben_mails`.
2. **Eine Mail wird nachträglich sensibel** (Stufe 1, Erbe) oder ihr Inhalt wird beim Aufräumen gelöscht. Erwartung: Ihre Textvektoren sind sofort weg, und beim nächsten Nachholen entsteht nur Teil 0. Test in Task 1: `test_ausloeser_loescht_vektoren_bei_schutz_oder_inhalt`.
3. **Der Agent sucht mit einer Frage, die nur im Text einer markierten Mail steht.** Erwartung: Die Mail erscheint nicht über ihren Text, weder per Vektor noch per Wort. Über den Betreff darf sie als Kopf erscheinen. Test in Task 4: `test_agent_findet_markierte_mail_nicht_ueber_text`.
4. **Ollama liefert eine falsche Dimension oder Müll** (anderes Modell geladen). Erwartung: Nichts wird gespeichert, die Runde meldet `vektoren_fehler`, und die Suche fällt auf Wörter zurück. Test in Task 2: `test_falsche_dimension_wird_verworfen`.
5. **Die Suchfrage ist leer, besteht nur aus Leerzeichen oder hat 10.000 Zeichen.** Erwartung: Leer bedeutet keine Suche, wie bisher. Überlange Fragen werden auf 500 Zeichen gekürzt, es gibt keinen Fehler. Test in Task 4: `test_fragen_leer_und_ueberlang`.

---

### Task 1: Vektor-Tabelle und Auslöser

**Files:**
- Modify: `db/post-sammelstelle.sql` (neuer Block am Ende)
- Test: `sales-mcp/tests/test_post_vektor_schema.py` (neu)

**Interfaces:**
- Produces: Tabelle `post_vektoren`:
  - `mail_id` uuid, Fremdschlüssel auf `post_mails(id)`, on delete cascade
  - `teil` smallint, CHECK 0–6
  - `vektor` `public.vector(1024)` not null
  - `modell` text not null
  - `erstellt_am` timestamptz default now()
  - Primärschlüssel `(mail_id, teil)`
  - Index `using hnsw (vektor public.vector_cosine_ops)`
- Produces: Spalte `post_mails.vektor_am timestamptz`. Null heißt: fehlt, nachholen.
- Produces: Auslöser `post_mails_vektor_veraltet`, `before update` auf `post_mails`. Ändert sich einer der Werte `betreff`, `von`, `an`, `text`, `sensibel` oder `status` (`is distinct from`), setzt er `new.vektor_am = null` und löscht die Zeilen in `post_vektoren` für die Mail. Die Auslöser-Funktion wird je Schema angelegt (`:"schema".post_vektor_veraltet()`).

- [ ] **Step 1: Write the failing tests**
  - `test_tabelle_und_index_da`: Es gibt `post_vektoren` und einen HNSW-Index.
  - `test_ausloeser_loescht_vektoren_bei_schutz_oder_inhalt` (Review Focus 2): Ein Vektor für Teil 0 und Teil 1 ist angelegt. Danach wird `sensibel=true` gesetzt. Beide Zeilen sind weg, und `vektor_am` ist null. Dasselbe gilt für eine Änderung an `text`.
  - `test_ausloeser_ignoriert_andere_spalten`: Ändern sich `ziel`, `erledigt_am` oder `dringlichkeit`, bleiben die Vektoren stehen.
  - `test_mail_loeschen_kaskadiert`: Wird die Zeile in `post_mails` gelöscht, verschwinden auch ihre Vektoren.
- [ ] **Step 2:** Test laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Migration schreiben und zweimal auf `sales_test` einspielen.
- [ ] **Step 4:** Test laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(post): Vektor-Tabelle mit Ausloeser fuer veraltete Inhalte`

### Task 2: Zerlegen und Einbetten

**Files:**
- Create: `sales-mcp/post_vektor.py`
- Test: `sales-mcp/tests/test_post_vektor.py` (neu, mit HTTP-Stub-Fixture auf `127.0.0.1:<freier Port>`)

**Interfaces:**
- Produces: `post_vektor.teile(mail: dict) -> list[tuple[int, str]]`.
  - Teil 0 enthält `Betreff: …\nVon: …\nAn: …`. Bei sensiblen Mails fehlt `An`, und es gibt nur Teil 0.
  - Teile 1 bis 6 enthalten den Text, mit Weißraum zusammengefasst, in Stücken zu 2000 Zeichen mit 200 Überlappung.
  - Leerer Text ergibt nur Teil 0. Leerer Kopf und leerer Text ergeben `[]`.
- Produces: `post_vektor.einbetten(texte: list[str], frage: bool = False) -> list[list[float]] | None`.
  - Ein `POST {POST_EMBEDDING_URL}/api/embed` mit `{"model": MODELL, "input": [...], "keep_alive": "2m", "truncate": true}`. Bei `frage=True` steht das Frage-Präfix vor jedem Text.
  - Gibt `None` zurück, wenn die URL leer ist, Ollama nicht erreichbar ist oder die Zeit abläuft. Es wirft dann nicht.
  - Wirft `post_vektor.Unbrauchbar`, wenn die Antwort keine Liste mit passender Länge und `DIMENSIONEN` Werten je Vektor ist.
  - Logs enthalten nie Texte.
- Produces: `post_vektor.bereit() -> bool`. Ist `POST_EMBEDDING_URL` gesetzt und antwortet `GET /api/tags` in 3 s?

- [ ] **Step 1: Write the failing tests**
  - `test_teile_kopf_und_text`: Ein Text mit 4500 Zeichen ergibt die Teile 0, 1, 2 und 3. Teil 2 beginnt mit den letzten 200 Zeichen von Teil 1.
  - `test_teile_sensibel_nur_kopf_ohne_empfaenger`
  - `test_teile_hoechstens_sechs_textteile`: Ein Text mit 20.000 Zeichen ergibt die Teile 0 bis 6.
  - `test_einbetten_sendet_modell_praefix_und_keep_alive`: Der Stub sieht `model`, `keep_alive` und bei `frage=True` das Präfix.
  - `test_ohne_url_oder_pc_aus_none`: Ohne URL kommt `None`, bei einem geschlossenen Port ebenfalls, und das jeweils in weniger als `POST_EMBEDDING_TIMEOUT_S`.
  - `test_falsche_dimension_wird_verworfen` (Review Focus 4): Der Stub liefert 768 Werte. Das wirft `Unbrauchbar`.
  - `test_logs_ohne_text`: caplog enthält nach einem Fehler weder den eingebetteten Text noch die Frage.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(post): Mails zerlegen und am PC einbetten`

### Task 3: Fehlende Vektoren in jeder Runde nachholen

**Files:**
- Modify: `sales-mcp/post_vektor.py` (neu `nachholen`)
- Modify: `sales-mcp/post_abholen.py` (`eine_runde`)
- Modify: `docker-compose.yml` (`sales-post`: `POST_EMBEDDING_URL: ${POST_EMBEDDING_URL:-}`, `POST_EMBEDDING_TIMEOUT_S: ${POST_EMBEDDING_TIMEOUT_S:-}`)
- Test: `sales-mcp/tests/test_post_vektor.py`

**Interfaces:**
- Produces: `post_vektor.nachholen(zeitgrenze_s: float = 45.0) -> dict`, Rückgabe `{"eingebettet": n, "status": "ok" | "pc_aus" | "aus" | "unbrauchbar"}`.
  - Kandidaten sind Mails mit `vektor_am is null` und `status <> 'geloescht'`, beide Richtungen, neueste zuerst.
  - Eine Mail wird nur ganz gespeichert: alle ihre Teile und `vektor_am = now()` in einer Transaktion.
  - Gesammelt wird zu Anfragen mit höchstens 32 Teilen. Nach Ablauf der Zeitgrenze oder bei `None` ist Schluss.
  - `aus` heißt: keine URL gesetzt. Dann gibt es keine Anfrage und kein Log je Runde.
  - Das Kennzeichen `vektor_am` wird über einen Abgleich gesetzt, der den Auslöser nicht auslöst. Der Auslöser prüft nur die Inhaltsspalten.
  - Beim Speichern wird die Mailzeile `for update` gesperrt. Haben sich `betreff`, `von`, `an`, `text` oder `sensibel` seit dem Lesen geändert, wird nichts gespeichert, und die Mail kommt in der nächsten Runde wieder. Test: `test_inhalt_aendert_sich_waehrend_einbetten`.
- `eine_runde` ruft `nachholen` nach dem Abholen und der Unterhaltung. Es läuft ohne Modellaufruf der Tagesgrenze, also auch in der Kundenpause. Ein Fehler kostet die Runde nicht, geloggt wird nur der Typ. Die Bilanz bekommt `vektoren`.

- [ ] **Step 1: Write the failing tests**
  - `test_nachholen_speichert_alle_teile_und_markiert`
  - `test_pc_faellt_mitten_aus_keine_halben_mails` (Review Focus 1): Der Stub antwortet auf die zweite Anfrage nicht mehr. Die Mails der ersten Anfrage sind vollständig, alle anderen haben `vektor_am is null`, und es gibt keine Mail mit nur einem Teil ihrer Teile.
  - `test_ohne_url_status_aus_ohne_anfrage`
  - `test_zeitgrenze_beendet_runde`: Ein Stub mit 2 s Verzögerung und `zeitgrenze_s=3` führt zu höchstens 2 Anfragen.
  - `test_runde_laeuft_bei_fehler_weiter`: `nachholen` wirft, `eine_runde` endet trotzdem mit einer Bilanz.
  - `test_kein_modellaufruf_gezaehlt`: `modellaufrufe_heute()` bleibt unverändert.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** `tests/test_post_vektor.py tests/test_post_abholen.py` laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(post): fehlende Vektoren je Runde am PC nachholen`

### Task 4: Hybride Suche

**Files:**
- Create: `sales-mcp/post_suche.py`
- Test: `sales-mcp/tests/test_post_suche.py` (neu)

**Interfaces:**
- Consumes: `post_struktur.sichtbar_sql`, `_spalten(agent=…)`, `AGENT_LESBAR_SQL`, `PRUEF_TEXT_MAX`, und den Filter von Stufe 1, damit Listen ohne gesendete Mails bleiben. Die Suche hat **keinen** Richtungsfilter.
- Produces: `post_suche.suchen(b: Betrachter, frage: str, bereich: str = "", fach: str = "", konto_id: str = "", grenze: int = 50, versatz: int = 0) -> dict` mit `{"treffer": list[dict], "nur_wortsuche": bool}`.
  - Die Felder je Treffer kommen wie bei `mails_suchen` aus `_spalten(agent=b.ist_agent)`. Dazu kommen `richtung` und `unterhaltung`.
  - Eine leere oder nur aus Leerzeichen bestehende Frage ergibt `{"treffer": [], "nur_wortsuche": False}`. Fragen werden auf 500 Zeichen gekürzt.
  - Die Frage wird einmal per `einbetten([frage], frage=True)` eingebettet. Liefert das `None` oder `Unbrauchbar`, gilt `nur_wortsuche = True`, und es wird nur nach Wörtern gesucht.
  - Vektor-Teilabfrage: `order by v.vektor <=> %s::public.vector limit 100` über `post_vektoren v join post_mails m`, mit `sichtbar_sql` und den Filtern **in der Abfrage**. Je Mail zählt der beste Teil.
  - Für den Agenten gilt Ruling V1: Teil 0 immer. Textteile nur, wenn die Mail lesbar ist (`AGENT_LESBAR_SQL`) und `(teil - 1) * 1800 < PRUEF_TEXT_MAX`.
  - Wort-Teilabfrage: `suchtext @@ websearch_to_tsquery('german', …)`, `limit 100`, mit denselben Filtern. Für den Agenten wird bei nicht lesbaren Mails nur `to_tsvector('german', coalesce(betreff,'') || ' ' || coalesce(von,''))` geprüft.
  - Mischung: RRF, `summe 1/(60 + rang)` über beide Listen, absteigend sortiert, dann `versatz`/`grenze`.

- [ ] **Step 1: Write the failing tests.** Fixture: drei sichtbare Mails mit festen Vektoren und eine Mail eines anderen Besitzers. Der Stub bettet Fragen auf einen festen Vektor ein.
  - `test_bedeutung_findet_ohne_gemeinsames_wort`: Die Frage „Rechnung begleichen“ findet die Mail mit „Zahlung offen“, deren Vektor nahe liegt.
  - `test_beide_listen_gemischt`: Eine Mail, die nur über Wörter passt, und eine, die nur über die Bedeutung passt, erscheinen beide. Eine Mail, die in beiden passt, steht vorn.
  - `test_sichtbarkeit_in_beiden_teilabfragen`: Die Mail des anderen Besitzers erscheint nie, auch wenn ihr Vektor der nächste ist (sie wäre Platz 1).
  - `test_pc_aus_nur_wortsuche`: Ist der Stub aus, gilt `nur_wortsuche` true, und die Wort-Treffer kommen trotzdem.
  - `test_agent_findet_markierte_mail_nicht_ueber_text` (Review Focus 3)
  - `test_agent_textteil_hinter_fenster_zaehlt_nicht`: Eine lesbare Mail, deren passender Teil hinter `PRUEF_TEXT_MAX` liegt, wird für den Agenten nicht über diesen Teil gefunden. Felix findet sie.
  - `test_gesendete_in_der_suche`: Eine gesendete Mail wird gefunden und trägt `richtung='gesendet'`.
  - `test_fragen_leer_und_ueberlang` (Review Focus 5)
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(post): hybride Suche nach Bedeutung und Woertern`

### Task 5: Posteingang und Agent nutzen die neue Suche

**Files:**
- Modify: `sales-mcp/ui_post.py` (Suchfeld der Liste `/post`)
- Modify: `sales-mcp/ui.py` (`_posteingang_suche`, um Zeile 8998)
- Modify: `sales-mcp/server.py` (`_sammelstelle_lesen` mit Suche; Ausgabe von `postfach_lesen` um `nur_wortsuche`)
- Test: `sales-mcp/tests/test_ui_post.py`, `sales-mcp/tests/test_post_bot.py`

**Interfaces:**
- Consumes: `post_suche.suchen`.
- Mit Suchtext rufen alle drei Wege `post_suche.suchen` auf, ohne Suchtext bleiben sie bei `mails_suchen`.
- UI: Bei `nur_wortsuche` steht über den Treffern der feste Text `Suche nach Bedeutung gerade nicht möglich (PC aus) – nur Wortsuche.`
- Agent: Die Antwort von `postfach_lesen` trägt `nur_wortsuche`. `AGENTS.md` (sales-claw) bekommt einen Satz: Ist `nur_wortsuche` true, sagt der Agent Felix, dass nur nach Wörtern gesucht wurde.

- [ ] **Step 1: Write the failing tests**
  - `test_suchfeld_nutzt_hybride_suche`: GET `/post?suche=…` als Besitzer findet die Bedeutungs-Mail.
  - `test_hinweis_bei_pc_aus`: Ist der Stub aus, steht der feste Hinweistext auf der Seite.
  - `test_agent_suche_meldet_nur_wortsuche`: `postfach_lesen(suche=…)` mit Stub aus enthält `"nur_wortsuche": true`.
  - `test_liste_ohne_suche_unveraendert`: Ohne Suchtext bleibt die Reihenfolge so wie bei `mails_suchen`, mit Dringlichkeit.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** `tests/test_ui_post.py tests/test_post_ui_v2.py tests/test_post_bot.py tests/test_post_suche.py` laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(post): Posteingang und Agent suchen nach Bedeutung`

### Task 6: Gesamtlauf und Runbook

**Files:**
- Modify: `docs/03_RUNBOOK.md` (Abschnitt „Post-Assistent Stufe 2 ausrollen“)

- [ ] **Step 1:** Volle Testsuite auf dem Zweig und auf der Basis, nacheinander. Vergleich der Test-Kennungen mit `comm`, `comm -13` muss leer sein.
- [ ] **Step 2: Runbook-Abschnitt**, jeder Schritt nur mit Felix' OK:
  1. Voraussetzung: Stufe 1 ist ausgerollt.
  2. Am PC: `scripts/ollama-pc-aufgabe.ps1 -Pruefen` meldet die Aufgabe als registriert. `ollama list` enthält `qwen3-embedding:0.6b`. Den freien Commit-Speicher messen (Lehre 21.11./23.11.: mindestens 8 GB Abstand zur CommitLimit).
  3. Von der VM aus: `curl -s -m 5 <Adresse>/api/tags` antwortet. Die Adresse ist dieselbe, die `~/learning/deployment/embedding-llm_config.yml` nutzt, nur ohne `/v1`.
  4. In `~/sales-claw/.env` `POST_EMBEDDING_URL=<Adresse>` eintragen. Den Wert nie ausgeben.
  5. Die Migration zweimal auf `sales` einspielen.
  6. `sales-ui` und `sales-mcp` neu erstellen, danach `sales-post`, jeweils mit `--no-deps --no-build`.
  7. Probe:
     - Bilanz `vektoren.status == ok`
     - `select count(*) from sales.post_vektoren` steigt
     - eine Suche im Posteingang ohne gemeinsames Wort findet eine passende Mail
  8. Dauer des Bestands: Die Zahl, die nach der ersten Stunde ohne Vektor bleibt, wird gemessen und Felix genannt.
  9. Rückweg: `POST_EMBEDDING_URL` leeren und `sales-post` neu erstellen. Die Suche fällt dann auf Wörter zurück. Die Vektoren bleiben stehen, es wird nichts gelöscht.
- [ ] **Step 3:** VM aufräumen, Commit `docs(post): Runbook Stufe 2 ausrollen`. Der Zweig wird gepusht, nicht gemergt und nicht ausgerollt.
