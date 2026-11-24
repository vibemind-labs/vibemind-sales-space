# Post-Assistent Stufe 1: Gesendete Mails holen und verknüpfen

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sales-post` holt die gesendeten Mails jedes aktiven Kontos (ganze Historie, nur lesend) in die Sammelstelle. Jede Mail gehört zu einer Unterhaltung. Gesendete Mails erben Bereich und `sensibel` von der Mail, auf die sie antworten. Sie erscheinen in der Suche und in der Unterhaltung, aber nie in Fächern, Listen, Warteschlangen oder beim Aufräumen am Server.

**Architecture:**
- `post_mails` bekommt die Spalten `richtung`, `in_reply_to`, `referenzen`, `unterhaltung` und `kopf_nachgelesen`. Gesendete Zeilen tragen immer den eigenen Status `gesendet`. Ein CHECK erzwingt das.
- Der Stand des Gesendet-Ordners liegt in einer neuen Tabelle je Konto und Richtung. Der INBOX-Stand bleibt unverändert in `post_konten`.
- Ein neues Modul `post_unterhaltung.py` verknüpft die Mails einer Kette und lässt gesendete Mails erben.
- Jede Stelle, die heute nur eingehende Mails meint, filtert ausdrücklich `richtung = 'eingang'`. Der Status allein ist nicht der Vertrag.

**Tech Stack:** Python 3 (sales-mcp), PostgreSQL (Supabase, Schemas `sales`/`sales_test`), imaplib, Starlette-UI, pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-post-assistent-design.md`, Abschnitt 5 / **Stufe 1**, dazu §2 (Anti-Ziele) und §6. Stufe 2 und 3b–3d bekommen eigene Pläne. 3a ist gebaut (Zweig `cc/post-assistent-3a`). Diese Stufe setzt 3a voraus: die Agenten-Sperre über `geprueft_am`.

## Global Constraints

- Mailserver nur lesend: `select(..., readonly=True)`, nur `UID SEARCH`, `UID FETCH` mit `BODY.PEEK[...]`/`RFC822` und `STATUS`. Nie `STORE`, `COPY`, `MOVE`, `EXPUNGE` oder `APPEND` (Spec §2 Nicht-Ziele).
- Abholen kostet keine Modellaufrufe. Gesendete Mails werden nie vom Modell sortiert oder nachgeprüft und zählen nicht zur Tagesgrenze (Spec Stufe 1.1/1.4).
- Gesendete Mails stehen nicht in den Posteingang-Fächern, sondern in der Unterhaltung und in der Suche (Spec 1.4).
- Sichtbarkeit wie bei eingehenden Mails: alles über `post_struktur.sichtbar_sql` (Spec 1.8). `sichtbar_sql` bekommt **keinen** Richtungsfilter, denn die Suche braucht beide Richtungen.
- Anti-Ziel: Private Mailinhalte erreichen niemanden außer Felix. Gesendete Mails sind für den Agenten **nicht geprüft** (`geprueft_am` null) und erscheinen dort nur mit Absender, Betreff und Hinweis (3a-Sperre, Ruling S1 unten).
- „Keine Geheimnisse und kein Kundentext in Logs; Fehlertexte fest formuliert“ (Spec §6). Logs nennen nur Konto-Kennung, Mail-ID, Anzahl und Ausnahmetyp. Ordnernamen, Message-IDs und Kopfzeilen kommen nicht ins Log.
- Ladenfest: Migrationen laufen je Schema (`-v schema=…`). Code nutzt nur `server._q`. Unterhaltungen verbinden nie Mails verschiedener `besitzer`.
- Tests laufen nie mit der Live-`.env`. Die Test-Env-Datei enthält nur `SALES_DB_URL` und `SALES_DB_SCHEMA=sales_test`.
- Nicht deployen, `sales-auto` nicht starten und keine SQL-Schreibzugriffe auf `sales` ohne Felix' OK. Der Plan endet vor dem Ausrollen.
- Conventional Commits. Jeder Commit endet mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Feste Werte:
  - `RICHTUNGEN = ("eingang", "gesendet")`, Standard `eingang`
  - Status gesendeter Zeilen: `gesendet`
  - `REFERENZEN_MAX = 20` (die letzten 20 Einträge von `References`), je Kennung höchstens `KOPF_MAX` Zeichen
  - `GESENDET_STAPEL = 50` Mails je Konto und Runde, `KOPF_STAPEL = 200` Kopfzeilen je Konto und Runde

**Rulings dieses Plans (Spec lässt es offen oder schweigt):**
- **S1:** Gesendete Mails bekommen kein Prüf-Urteil und gelten für den Agenten als nicht geprüft, er sieht nur den Kopf. Grund: Sie zitieren oft fremden Mailtext, auch Weiterleitungen. Ob sie in 3b lesbar werden, entscheidet der 3b-Plan. Kosten, falls falsch: Der Agent liest Felix' eigene Antworten erst nach 3b.
- **S2:** Der Stand des INBOX-Ordners bleibt in `post_konten`, der Stand des Gesendet-Ordners kommt in die neue Tabelle `post_ordner_stand`. So gibt es keine Datenmigration am laufenden Stand. Kosten, falls falsch: zwei Orte für den Stand.
- **S3:** `sensibel` einer gesendeten Mail ergibt sich aus den festen Mustern über **Empfänger und Betreff**, denn der Absender ist Felix. Dazu kommt die Bezugsmail. Wird eine gesendete Mail nachträglich sensibel, werden Text, Auszug, Empfänger und Anhänge geleert, genau wie beim Speichern sensibler Mails. Kosten, falls falsch: wenige gesendete Mails ohne Text.
- **S4:** Der Abgleich (`post_erledigt`) bleibt in dieser Stufe unverändert (Spec 1.5 „muss nicht“).
- **S5:** Die Kontaktansicht (`ui._kontakt_mails_bereich`, Absender = Kontakt) bleibt unverändert. Gesendete Mails an einen Kontakt zeigt sie erst später.

**Arbeitsplatz und Testlauf (für alle Tasks gleich):**
- **Vor dem Start:** WORKBOARD und Vault prüfen. Am 24.11. hielt `cc-sales-abholer` sales-claw und `feat/stufe-1-fundament`. Solange ein fremder Claim offen ist, nicht anfangen, sondern Felix fragen. Danach einen eigenen Claim `cc-post-stufe1` setzen.
- **Basis:** das lokale `feat/stufe-1-fundament` mit 3a (Worktree `wt-sales-post`), zusammengeführt mit `origin/feat/stufe-1-fundament`. Am 24.11. lag der lokale Stand 14 Commits vor und 33 hinter GitHub. Den Merge macht der Controller vor Task 1, prüft ihn mit der vollen Testsuite und legt dann den Worktree `C:\Users\User\ClaudeWork\wt-sales-stufe1` auf dem neuen Zweig `cc/post-assistent-stufe1` an.
- **Tests** laufen auf der VM `offload-vm`:
  1. Den Zweigstand per `git archive HEAD | ssh offload-vm 'mkdir -p /tmp/wt-s1 && tar -x -C /tmp/wt-s1'` hinüberkopieren.
  2. Tests starten:
     ```
     docker run --rm --network sales-claw_default --env-file /tmp/wt-s1.env -e PYTHONDONTWRITEBYTECODE=1 -v /tmp/wt-s1:/work -w /work/sales-mcp --entrypoint python sales-claw-sales-mcp:local -m pytest -q -p no:cacheprovider <tests>
     ```
     `/tmp/wt-s1.env` hat die Rechte 0600 und enthält nur die zwei erlaubten Zeilen. Den Wert von `SALES_DB_URL` liest man per `grep '^SALES_DB_URL=' ~/sales-claw/.env`, ohne ihn auszugeben.
  3. Es läuft immer nur ein Lauf auf `sales_test`. Vorher prüfen: `docker ps --filter ancestor=sales-claw-sales-mcp:local`.
- Die Vergleichsbasis kommt aus `git archive` des Basis-Commits, nie aus `git stash`. FAILED-Listen vergleicht man mit `comm` und nur über die Test-Kennungen (`^[A-Z]* tests/`). Mitgeschnittene Logzeilen enthalten zufällige UUIDs.
- Migrationen auf `sales_test`: `ssh offload-vm 'docker exec -i debian-supabase-db-1 psql -q -U supabase_admin -d postgres -v ON_ERROR_STOP=1 -v schema=sales_test' < db/post-sammelstelle.sql`, immer zweimal, um die Idempotenz zu prüfen.

## Review Focus

1. **Eine Mail an sich selbst** liegt mit derselben Message-ID in INBOX und Gesendet. Erwartung: zwei Zeilen, eine je Richtung, und keine verschluckt die andere. Test in Task 3: `test_mail_an_mich_selbst_zwei_zeilen`.
2. **UIDVALIDITY wechselt nur im Gesendet-Ordner.** Erwartung: Nur gesendete Zeilen dieses Kontos werden umnummeriert, eingehende bleiben unberührt. Umgekehrt genauso. Test in Task 3: `test_uidvalidity_wechsel_trennt_richtungen`.
3. **Ein Konto hat keinen `\Sent`-Ordner, oder er lässt sich nicht wählen.** Erwartung: INBOX wird wie bisher abgeholt, und die Runde zählt keinen Kontofehler. Test in Task 3: `test_ohne_gesendet_ordner_laeuft_eingang_weiter`.
4. **Eine gesendete Antwort auf eine sensible Mail wird abgeholt, bevor die Bezugsmail da ist.** Erwartung: Sobald die Bezugsmail da ist, wird die gesendete Mail sensibel und verliert Text, Auszug, Empfänger und Anhänge. Test in Task 4: `test_antwort_auf_sensible_mail_wird_nachtraeglich_sensibel`.
5. **Felix ruft für eine gesendete Mail direkt eine schreibende Route auf** (korrigieren, Vorschlag, Ziel, erledigt, wieder offen, Kontakt). Erwartung: Die Route lehnt ab, nichts ändert sich, nichts wird am Server verschoben. Test in Task 6: `test_schreibende_routen_lehnen_gesendete_ab`.

---

### Task 1: Spalten, Stand-Tabelle und Regeln in der Datenbank

**Files:**
- Modify: `db/post-sammelstelle.sql` (neuer Block am Ende, idempotent, Muster der `do $$ … execute format(...)`-Blöcke um Zeile 220–290)
- Test: `sales-mcp/tests/test_post_stufe1_schema.py` (neu)

**Interfaces:**
- Produces: neue Spalten in `post_mails`:

  | Spalte | Typ | Bedeutung |
  |---|---|---|
  | `richtung` | text not null default `'eingang'`, CHECK in `RICHTUNGEN` | |
  | `in_reply_to` | text, null | Message-ID ohne `<>` |
  | `referenzen` | text[] not null default `'{}'` | höchstens `REFERENZEN_MAX` |
  | `unterhaltung` | uuid, null | null heißt noch nicht zugeordnet |
  | `kopf_nachgelesen` | boolean not null default false | |

- Produces: Status-CHECK um `gesendet` erweitert. Neuer CHECK `post_mails_richtung_status`: `(richtung = 'gesendet') = (status = 'gesendet')`.
- Produces: Unique `(konto_id, imap_uid)` wird ersetzt durch `post_mails_konto_richtung_uid` unique `(konto_id, richtung, imap_uid)`. Der alte Constraint-Name wird per `pg_constraint` gesucht, nicht geraten.
- Produces: Indizes `(besitzer, in_reply_to)`, GIN auf `referenzen`, `(besitzer, unterhaltung)`.
- Produces: Tabelle `post_ordner_stand`:
  - `konto_id` uuid, Fremdschlüssel auf `post_konten`, on delete cascade
  - `richtung` text, CHECK `= 'gesendet'`
  - `ordner` text not null
  - `uidvalidity` bigint
  - `letzte_uid` bigint
  - `altbestand_fertig` boolean not null default false
  - Primärschlüssel `(konto_id, richtung)`

- [ ] **Step 1: Write the failing test** `test_post_stufe1_schema.py`, mit der Schema-Wache wie in `test_post_assistent_schema.py`:
  - `test_spalten_und_tabelle_da`: Alle fünf Spalten und `post_ordner_stand` sind vorhanden.
  - `test_gesendet_braucht_status_gesendet`: Ein Insert mit `richtung='gesendet', status='neu'` wirft `CheckViolation`, ebenso `richtung='eingang', status='gesendet'`. `gesendet`/`gesendet` geht durch.
  - `test_gleiche_uid_je_richtung_erlaubt`: Zwei Zeilen desselben Kontos mit `imap_uid=7`, eine je Richtung, gehen durch. Eine zweite `eingang`-Zeile mit UID 7 wirft `UniqueViolation`.
  - `test_bestand_ist_eingang`: Eine Zeile ohne Angabe hat `richtung='eingang'`, `referenzen='{}'` und `kopf_nachgelesen=false`.
- [ ] **Step 2:** Migration noch nicht eingespielt, Test laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Block in `db/post-sammelstelle.sql` schreiben, zweimal auf `sales_test` einspielen. Der zweite Lauf muss ohne Fehler durchgehen.
- [ ] **Step 4:** Test laufen lassen, dazu `tests/test_post_assistent_schema.py` und `tests/test_post_abholen.py`. Erwartet: PASS. `on conflict (konto_id, imap_uid)` in `post_abholen._speichern` findet seinen Constraint nicht mehr, deshalb ändert Task 3 die Stelle. Scheitert `test_post_abholen.py` hier daran, gehört die Anpassung von `on conflict` auf `(konto_id, richtung, imap_uid)` in diesen Commit.
- [ ] **Step 5: Commit** `feat(post): Richtung, Unterhaltung und Gesendet-Stand in der Sammelstelle`

### Task 2: Kopfzeilen In-Reply-To und References lesen

**Files:**
- Modify: `sales-mcp/post_abholen.py` (`_mail_zerlegen`, `_speichern`)
- Test: `sales-mcp/tests/test_post_abholen.py`

**Interfaces:**
- Produces: `post_abholen._kennungen(kopf: str | None) -> list[str]`. Liefert die Message-IDs aus `<…>`, ohne spitze Klammern und in der Reihenfolge des Kopfs. Kennungen mit Leerzeichen oder über `KOPF_MAX` Zeichen werden verworfen. Ohne spitze Klammern kommt eine leere Liste zurück.
- Produces: `_mail_zerlegen(...)` liefert zusätzlich `"in_reply_to": str | None` (erste Kennung aus `In-Reply-To`) und `"referenzen": list[str]` (die letzten `REFERENZEN_MAX` aus `References`). `_speichern` schreibt beide und setzt `kopf_nachgelesen = true`. `_unlesbar` liefert `None` und `[]`.
- Die Kopfzeilen werden auch bei sensiblen Mails gespeichert. Es sind Kennungen, kein Inhalt, und die Unterhaltung braucht sie.

- [ ] **Step 1: Write the failing tests**
  - `test_antwortkoepfe_gespeichert`: Eine Mail mit `In-Reply-To: <a@x>` und `References: <r1@x> <a@x>` ergibt in der Zeile `in_reply_to == "a@x"`, `referenzen == ["r1@x", "a@x"]` und `kopf_nachgelesen is True`.
  - `test_referenzen_gedeckelt`: 300 Kennungen in `References` ergeben die letzten 20 in Kopfreihenfolge. Eine Kennung mit 5000 Zeichen wird verworfen.
  - `test_kaputte_koepfe_kein_absturz`: `In-Reply-To: kein-klammerausdruck` ergibt `None`. Die Mail wird normal gespeichert.
  - `test_sensible_mail_behaelt_kennungen`: Ein Sicherheitscode-Betreff macht die Mail sensibel. Text ist `None`, `referenzen` ist gefüllt.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** `tests/test_post_abholen.py` laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(post): Antwortkoepfe beim Abholen speichern`

### Task 3: Gesendet-Ordner lesend abholen

**Files:**
- Modify: `sales-mcp/post_abholen.py` (`_uidvalidity_pruefen`, `_ersatz_wiederfinden`, `_speichern`, `eine_runde`; neu `gesendet_abholen`)
- Modify: `sales-mcp/post_imap.py` (neu `ordner_groesse`)
- Test: `sales-mcp/tests/test_post_abholen.py` (Attrappe erweitern), `sales-mcp/tests/test_post_gesendet.py` (neu)

**Interfaces:**
- Consumes: Task 1 (Spalten, `post_ordner_stand`), Task 2 (`_mail_zerlegen` mit Kennungen).
- Produces: `post_abholen.gesendet_abholen(zeile: dict, kasten, stapel: int = GESENDET_STAPEL) -> int`, Rückgabe sind die neu gespeicherten Mails.
  - Den Ordner findet `post_imap.gesendet_ordner(kasten)`. Ohne `\Sent`-Ordner gibt die Funktion `0` zurück und schreibt nichts.
  - Der Ordner wird mit `readonly=True` gewählt. Stand und UIDVALIDITY kommen aus `post_ordner_stand`. Hat der Ordner seit dem letzten Lauf einen anderen Namen, wird das wie ein UIDVALIDITY-Wechsel behandelt.
  - Die Reihenfolge und das Nachfiltern von `n:*` laufen wie in `konto_abholen`.
- Produces: `_speichern(zeile, uid, mail, richtung: str = "eingang")`. Für `gesendet` gilt:
  - Status `gesendet`, `ordner` = Ordnername, `fach` null, `einordnung_quelle` null, `geprueft_am` null.
  - `bereich` = `standard_bereich` des Kontos (Task 4 überschreibt ihn per Erbe).
  - `sensibel` nach Ruling S3: `_sensibel_nach_muster` über Empfänger statt Absender, plus Betreff.
  - Die Dublettensuche, `_ersatz_wiederfinden` und die Umnummerierung bei UIDVALIDITY-Wechseln arbeiten nur innerhalb derselben Richtung.
  - `on conflict (konto_id, richtung, imap_uid) do nothing`. Der Stand geht in `post_konten` (eingang) bzw. `post_ordner_stand` (gesendet), in derselben Transaktion wie die Mail.
- Produces: `post_imap.ordner_groesse(kasten, ordner: str) -> int | None` über `STATUS (MESSAGES)`, nur lesend. Dazu der Aufruf `python post_abholen.py --gesendet-groessen`. Er gibt je aktivem Konto `<kennung> <anzahl|unbekannt>` aus, ohne Ordnernamen, und speichert nichts.
- `eine_runde`: Je Konto läuft erst `konto_abholen` und dann `gesendet_abholen` auf **derselben** Verbindung. Dafür öffnet `eine_runde` den Kasten selbst und gibt ihn an beide weiter. Ein Fehler im Gesendet-Teil zählt in die neue Bilanz `gesendet_fehler` und loggt nur den Typ. Er kostet nicht das INBOX-Abholen und zählt nicht in `konten_fehler`. Die Bilanz bekommt `gesendet`.

- [ ] **Step 1: Attrappe erweitern.** `Attrappe` in `test_post_abholen.py` bekommt optional `ordner: dict[str, dict[int, bytes]]` und `uidvalidity` je Ordner. `select` merkt sich den gewählten Ordner. `list()` liefert LIST-Zeilen, der Gesendet-Ordner mit `\Sent`. `status()` liefert MESSAGES. Bestehende Tests bleiben unverändert grün (Standard: nur INBOX).
- [ ] **Step 2: Write the failing tests** in `test_post_gesendet.py`:
  - `test_gesendete_mails_landen_mit_status_gesendet`: Zwei Mails im Ordner `Gesendet` (`\Sent`) ergeben zwei Zeilen mit `richtung='gesendet'`, `status='gesendet'`, `ordner='Gesendet'` und `geprueft_am is None`. Die Attrappe sah nur `readonly=True`-Selects und keinen verbotenen Befehl.
  - `test_gesendet_zaehlt_nicht_zur_tagesgrenze`: `modellaufrufe_heute()` ist vorher und nachher gleich. `einordnen_offene(10)` mit einem Fake-Gateway, das jeden Aufruf mit `pytest.fail` quittiert, ruft für gesendete Zeilen nichts auf.
  - `test_mail_an_mich_selbst_zwei_zeilen` (Review Focus 1)
  - `test_uidvalidity_wechsel_trennt_richtungen` (Review Focus 2): Ein Wechsel in Gesendet nummeriert nur gesendete Zeilen negativ um. Die `imap_uid` der Eingangszeilen bleibt gleich.
  - `test_ohne_gesendet_ordner_laeuft_eingang_weiter` (Review Focus 3): Es gibt keinen `\Sent`-Ordner, oder `select` auf ihn antwortet `NO`. INBOX-Mails werden gespeichert, `bilanz["konten_fehler"] == 0`, und im zweiten Fall ist `bilanz["gesendet_fehler"] == 1`.
  - `test_ordnerwechsel_gilt_als_neuanfang`: Heißt der Ordner beim zweiten Lauf anders, wird von vorn geholt, und es entstehen keine Dubletten.
  - `test_gesendet_sensibel_nach_empfaenger`: Erfüllen Empfänger oder Betreff ein Muster aus `post_einordnung.SENSIBEL_MUSTER`, ist `sensibel` true und der Text `None`.
  - `test_ganze_historie_in_stapeln`: 120 Mails ergeben nach drei Läufen mit `stapel=50` 120 Zeilen und `altbestand_fertig`.
  - `test_groessen_ohne_ordnernamen`: Die Ausgabe von `--gesendet-groessen` enthält die Kennung und die Zahl, aber nicht den Ordnernamen.
- [ ] **Step 3:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 4:** Implementieren.
- [ ] **Step 5:** `tests/test_post_gesendet.py tests/test_post_abholen.py tests/test_post_einordnung.py` laufen lassen. Erwartet: PASS.
- [ ] **Step 6: Commit** `feat(post): Gesendet-Ordner lesend abholen`

### Task 4: Unterhaltungen und Erbe gesendeter Mails

**Files:**
- Create: `sales-mcp/post_unterhaltung.py`
- Modify: `sales-mcp/post_abholen.py` (`_speichern` ruft `zuordnen`; `eine_runde` ruft `nachziehen` nach dem Abholen)
- Test: `sales-mcp/tests/test_post_unterhaltung.py` (neu)

**Interfaces:**
- Produces: `post_unterhaltung.zuordnen(conn, mail_id) -> str`. Gibt die Unterhaltungs-Kennung der Mail zurück.
  - Nachbarn sind Mails desselben `besitzer`, deren `message_id` in `in_reply_to`/`referenzen` dieser Mail steht, oder deren `in_reply_to`/`referenzen` die `message_id` dieser Mail enthält.
  - Kennungen mit `message_id_ersatz` verbinden nie.
  - Haben Nachbarn Kennungen, gewinnt die Kennung der ältesten Mail (nach `datum`, dann `id`). Alle Mails mit einer verlorenen Kennung werden auf die Gewinnerin umgestellt. Ohne Nachbarn bekommt die Mail eine neue Kennung.
- Produces: `post_unterhaltung.nachziehen(grenze: int = 500) -> dict`, Rückgabe `{"zugeordnet": n, "geerbt": m}`. Zwei Schritte:
  1. `zuordnen` für bis zu `grenze` Mails mit `unterhaltung is null`, neueste zuerst.
  2. Erbe in einem Update über alle gesendeten Zeilen mit Bezugsmail:
     - Die Bezugsmail ist die Mail mit `message_id = in_reply_to`, sonst die letzte vorhandene aus `referenzen`, beim selben `besitzer`.
     - `bereich` = Bereich der Bezugsmail, falls er gesetzt ist.
     - `sensibel = sensibel or bezug.sensibel`.
     - Wird `sensibel` dabei true, werden `text`, `auszug`, `an` und `anhaenge` geleert.
     - Gesendete Mails ohne Bezug behalten den Standardbereich.
- `eine_runde` ruft `nachziehen` nach dem Abholen aller Konten. Es läuft ohne Modell, also auch in der Kundenpause. Ein Fehler kostet die Runde nicht, geloggt wird nur der Typ. Die Bilanz bekommt `unterhaltung`.

- [ ] **Step 1: Write the failing tests**
  - `test_antwort_haengt_am_original`: Ein Eingang `m1` und eine gesendete Antwort mit `in_reply_to=m1` haben dieselbe `unterhaltung`.
  - `test_reihenfolge_egal`: Wird die Antwort vor dem Original gespeichert, haben trotzdem beide dieselbe Kennung.
  - `test_zwei_ketten_verschmelzen`: Eine Mail, die beide Ketten referenziert, führt zu einer gemeinsamen Kennung, nämlich der der ältesten Mail.
  - `test_ersatz_kennung_verbindet_nicht`: Zwei Mails mit gleicher Ersatz-ID bleiben getrennt.
  - `test_nie_ueber_besitzer_hinweg`: Gleiche Message-ID bei `felix` und `ivan` ergibt getrennte Kennungen.
  - `test_gesendet_erbt_bereich`: Ein Eingang `privat` und eine gesendete Antwort aus einem Konto mit Standardbereich `business` ergeben nach `nachziehen()` für die Antwort `bereich == 'privat'`.
  - `test_antwort_auf_sensible_mail_wird_nachtraeglich_sensibel` (Review Focus 4)
  - `test_sensibel_geht_nie_zurueck`: Wird die Bezugsmail später nicht mehr als sensibel geführt, bleibt die gesendete Mail sensibel.
  - `test_nachziehen_fehler_kostet_runde_nicht`: `nachziehen` wirft. `eine_runde` läuft zu Ende, und das Log enthält nur den Typ.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** `tests/test_post_unterhaltung.py tests/test_post_gesendet.py tests/test_post_abholen.py` laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(post): Unterhaltungen verknuepfen, gesendete Mails erben Bereich und Schutz`

### Task 5: Kopfzeilen des Bestands nachlesen

**Files:**
- Modify: `sales-mcp/post_imap.py` (neu `antwortkoepfe_lesen`)
- Modify: `sales-mcp/post_abholen.py` (neu `koepfe_nachlesen`; `eine_runde`)
- Test: `sales-mcp/tests/test_post_gesendet.py`

**Interfaces:**
- Produces: `post_imap.antwortkoepfe_lesen(kasten, ordner: str, uids: list[int]) -> dict[int, tuple[str | None, str | None, str | None]]`. Liefert je UID `(message_id, in_reply_to, references)` als Rohtext. Es ist ein einziges `UID FETCH <menge> (BODY.PEEK[HEADER.FIELDS (MESSAGE-ID IN-REPLY-TO REFERENCES)])` im lesend gewählten Ordner. Fehlende UIDs fehlen im Ergebnis.
- Produces: `post_abholen.koepfe_nachlesen(zeile: dict, kasten, stapel: int = KOPF_STAPEL) -> int`. Gibt die Zahl der als `kopf_nachgelesen` markierten Zeilen zurück. Ablauf:
  - Bearbeitet werden eingehende Zeilen des Kontos mit `kopf_nachgelesen = false`, neueste zuerst.
  - Der Fundort ist `ordner` + `ordner_uid`, bei `ordner = 'INBOX'` die `imap_uid`. Zeilen mit `imap_uid < 0` und `ordner = 'INBOX'` werden übersprungen.
  - Nur wenn die gelesene Message-ID der gespeicherten entspricht, werden `in_reply_to`/`referenzen` geschrieben.
  - Ist die Mail nicht gefunden, weicht die ID ab oder ist es eine `message_id_ersatz`-Zeile, wird nur `kopf_nachgelesen = true` gesetzt.
  - Weicht die UIDVALIDITY von INBOX von `post_konten.uidvalidity` ab, werden die INBOX-Zeilen in dieser Runde übersprungen.
  - Danach `post_unterhaltung.zuordnen` für jede Zeile, die Kennungen bekam.
- `eine_runde`: Nach `gesendet_abholen` folgt auf derselben Verbindung `koepfe_nachlesen`, mit derselben Fehlertrennung (Bilanz `koepfe_fehler`, `koepfe`).

- [ ] **Step 1: Write the failing tests**
  - `test_bestand_bekommt_antwortkoepfe`: Eine alte Eingangszeile ohne Köpfe und eine Attrappe mit passenden Kopfzeilen ergeben nach `koepfe_nachlesen` gefüllte Kennungen, `kopf_nachgelesen` und eine Unterhaltung mit einer schon gespeicherten gesendeten Mail.
  - `test_verschobene_mail_am_neuen_ort`: Für eine Zeile mit `ordner='Zur Info', ordner_uid=9` wird im Ordner `Zur Info` UID 9 gelesen.
  - `test_fremde_message_id_wird_nicht_uebernommen`: Unter der UID liegt eine andere Mail. Die Kennungen bleiben leer, `kopf_nachgelesen` ist true.
  - `test_nur_peek`: Die Attrappe sah ausschließlich `BODY.PEEK[HEADER.FIELDS` und nie `RFC822` für diese Zeilen.
  - `test_stapel_und_reihenfolge`: Von 450 offenen Zeilen werden mit `stapel=200` die neuesten 200 bearbeitet.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** `tests/test_post_gesendet.py tests/test_post_unterhaltung.py tests/test_post_abholen.py` laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(post): Antwortkoepfe des Bestands lesend nachholen`

### Task 6: Gesendete Mails überall dort ausschließen, wo nur Eingang gemeint ist

**Files:** (Fundstellen aus der Durchsicht vom 24.11.; Zeilen ungefähr)
- Modify: `sales-mcp/post_struktur.py`
  - `ziel_sql`
  - `mails_suchen`: neuer Parameter `richtung: str = ""`; ohne `suche` gilt Eingang, mit `suche` beide Richtungen
- Modify: `sales-mcp/post_abholen.py`
  - `einordnen_offene`, beide Teile der Warteschlange
  - `modellaufrufe_heute`
- Modify: `sales-mcp/post_ziel.py`
  - `_SPALTEN`/`_bleibt`
  - `ziel_frisch`
  - `ziele_aktualisieren`
- Modify: `sales-mcp/post_ordnen.py`: `_OFFENE_SQL`
- Modify: `sales-mcp/post_freigabe.py`
  - `_LOESCHBAR`
  - `jahre`
  - `offene_mails`
- Modify: `sales-mcp/post_neu_einordnen.py`: `_altbestand`, `_unklar_laufend`
- Modify: `sales-mcp/post_herkunft.py`: `_OFFEN_SQL`
- Modify: `sales-mcp/post_werbung.py`
  - `bleibt_immer_absender`
  - `regel_vorschlagen`
- Modify: `sales-mcp/post_erledigt.py`
  - `offen_sql`
  - `_kandidaten_sql`
  - `erledigen`/`wieder_oeffnen`: lehnen gesendete Mails ab
- Modify: `sales-mcp/post_anweisung.py`: `_WARTET_SQL`
- Modify: `sales-mcp/ui_post.py`
  - `faecher_zahlen`
  - `konten_sichtbar`
  - `kontostand`
  - Routen `korrigieren`, `vorschlag`, `ziel_setzen`, `mail_erledigt`, `mail_wieder_offen` und `mail_kontakt`: lehnen gesendete Mails mit dem festen Text `Gesendete Mails lassen sich hier nicht ändern.` ab
- Modify: `sales-mcp/server.py`
  - `_sammelstelle_leer`
  - `_sammelstelle_lesen`: Liste nur Eingang, Suche beide Richtungen
  - `_post_uid_aufloesen`: Eine gesendete Mail ergibt den festen Fehler `Diese Mail wurde gesendet und lässt sich nicht beantworten oder einstufen.`
- Modify: `sales-mcp/bewerbungs_eingang.py`: `_mails`
- Test: `sales-mcp/tests/test_post_gesendet_ausschluss.py` (neu)

**Interfaces:**
- Consumes: Task 1–3.
- Jede genannte Abfrage bekommt ausdrücklich `richtung = 'eingang'`, mit dem Alias der Abfrage. `sichtbar_sql` bleibt ohne Richtungsfilter.

- [ ] **Step 1: Write the failing tests.** Fixture: ein Konto mit je einer eingehenden Zeile (`eingeordnet`, Fach `Kunden`, `ziel` null) und einer gesendeten Zeile.
  - `test_listen_und_faecher_ohne_gesendete`: `mails_suchen(besitzer)` ohne Suche, `ziel_sql("aufmerksamkeit")`, `faecher_zahlen`, `kontostand` und `post_erledigt.mails_offen` enthalten bzw. zählen nur die eingehende Zeile.
  - `test_suche_findet_beide_richtungen`: `mails_suchen(besitzer, suche=<Wort aus beiden>)` liefert beide Zeilen. Jede trägt `richtung`.
  - `test_kein_ziel_kein_verschieben_fuer_gesendete`: Nach `post_ziel.ziele_aktualisieren()` ist das `ziel` der gesendeten Zeile null. Mit `POST_ORDNEN=voll` und einer Attrappe sieht `post_ordnen` keine gesendete Zeile.
  - `test_warteschlangen_ohne_gesendete`: Die Warteschlange von `einordnen_offene`, `post_neu_einordnen._altbestand`, `post_freigabe.offene_mails`/`jahre`, `post_herkunft._OFFEN_SQL` und `post_anweisung._WARTET_SQL` enthält keine gesendete Zeile, auch wenn sie künstlich `geprueft_am is null` und `versuche = 0` hat.
  - `test_schreibende_routen_lehnen_gesendete_ab` (Review Focus 5): Jede der sechs Routen antwortet für die gesendete Mail mit dem festen Text, und die Zeile ist danach unverändert (Vergleich der ganzen Zeile).
  - `test_agent_liste_ohne_gesendete_suche_nur_kopf`: `postfach_lesen` ohne Suche enthält die gesendete Mail nicht. Mit Suche enthält es sie nur mit Absender, Betreff und Hinweis (3a-Sperre).
  - `test_beantworten_lehnt_gesendete_ab`: `mail_beantworten` und `mail_einstufen` auf die `post:`-uid der gesendeten Mail ergeben den festen Fehler und keinen IMAP-Zugriff.
  - `test_sammelstelle_nur_mit_gesendeten_gilt_als_leer`: Liegen für den Besitzer nur gesendete Zeilen vor, ist `_sammelstelle_leer()` true, wie vorher.
  - `test_bewerbungen_ohne_gesendete`: `bewerbungs_eingang._mails` liefert die gesendete Zeile nicht.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Covering-Lauf mit `tests/test_post_*.py tests/test_ui_post.py tests/test_post_ui_v2.py tests/test_mail_beantworten.py tests/test_postfach.py tests/test_bewerbungs_eingang.py`. Erwartet: PASS, abgesehen von den Altlasten aus der 3a-Basis (3× `test_post_anbinden`).
- [ ] **Step 5: Commit** `fix(post): gesendete Mails nie in Faechern, Warteschlangen oder beim Aufraeumen`

### Task 7: Unterhaltung im Posteingang zeigen

**Files:**
- Modify: `sales-mcp/post_struktur.py` (neu `unterhaltung_lesen`)
- Modify: `sales-mcp/ui_post.py` (Mailansicht `/post/mail/{mail_id}`, Trefferliste der Suche)
- Test: `sales-mcp/tests/test_ui_post.py`, `sales-mcp/tests/test_post_unterhaltung.py`

**Interfaces:**
- Produces: `post_struktur.unterhaltung_lesen(b: Betrachter, mail_id: str, grenze: int = 50) -> list[dict]`.
  - Liefert alle Mails derselben `unterhaltung`, die `sichtbar_sql(b)` erlaubt, nach `datum` aufsteigend.
  - Felder: `id`, `richtung`, `von`, `an`, `betreff`, `datum`, `auszug`. Für den Agenten gilt `_spalten(agent=True)`.
  - Ist die Mail selbst unsichtbar oder unbekannt, kommt `[]` zurück.
- UI: Die Mailansicht zeigt unter der Mail die Unterhaltung als Liste. Gesendete Mails tragen dort das Etikett `Gesendet`, jede Zeile verlinkt `/post/mail/<id>`. Treffer der Suche tragen bei gesendeten Mails ebenfalls `Gesendet`. Eine gesendete Mail hat in ihrer Ansicht keine Knöpfe zum Korrigieren, Erledigen, Ziel oder Kontakt. Die Gestaltung bleibt dem Bauenden überlassen (Spec §7).

- [ ] **Step 1: Write the failing tests**
  - `test_unterhaltung_lesen_beide_richtungen`: Eingang, gesendete Antwort und Rückantwort ergeben drei Einträge in Datumsreihenfolge mit den passenden `richtung`-Werten.
  - `test_unterhaltung_respektiert_sichtbarkeit`: Ein anderer Betrachter (Teammitglied) bekommt `[]`. Der Agent bekommt die gesendete Mail nur ohne `auszug`.
  - `test_mailansicht_zeigt_unterhaltung_und_etikett`: GET `/post/mail/<eingang>` als Besitzer enthält den Betreff der gesendeten Antwort und `Gesendet`.
  - `test_gesendete_ansicht_ohne_knoepfe`: Die Ansicht einer gesendeten Mail enthält keine der Formular-Aktionen `/korrigieren`, `/ziel`, `/erledigt` und `/kontakt`.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** `tests/test_ui_post.py tests/test_post_ui_v2.py tests/test_post_unterhaltung.py` laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(post): Unterhaltung mit gesendeten Mails in der Mailansicht`

### Task 8: Gesamtlauf und Runbook

**Files:**
- Modify: `docs/03_RUNBOOK.md` (neuer Abschnitt „Post-Assistent Stufe 1 ausrollen“, nach „Post-Assistent 3a ausrollen“)

- [ ] **Step 1: Volle Testsuite** auf dem Zweig und auf der Basis (Merge-Commit vor Task 1), nacheinander. Die Test-Kennungen vergleicht man mit `comm`, `comm -13 basis zweig` muss leer sein. Beide Richtungen kommen in den Bericht.
- [ ] **Step 2: Runbook-Abschnitt** mit diesen Schritten, jeder nur mit Felix' OK:
  1. Voraussetzung: 3a ist ausgerollt.
  2. Gesendet-Ordner messen: `docker compose exec -T sales-post python post_abholen.py --gesendet-groessen`. Nur lesend; die Zahlen dem Felix nennen. Je 50 Mails pro Runde alle 2 Minuten ergeben die Dauer.
  3. Migration zweimal auf `sales` einspielen.
  4. Zuerst die Leser neu erstellen (`sales-ui`, `sales-mcp`, beide mit `up -d --no-deps --no-build`), danach `sales-post`. Grund: Alte Leser würden gesendete Zeilen in „Aufmerksamkeit“ zeigen.
  5. Probe:
     - nach einer Runde Bilanz `gesendet > 0`, `gesendet_fehler == 0`
     - in der UI erscheint eine Unterhaltung mit `Gesendet`
     - in keinem Fach steht eine gesendete Mail
     - `select count(*) from sales.post_mails where richtung='gesendet' and ziel is not null` ergibt 0
  6. Rückweg: nur `sales-post` auf den alten Stand. Die Leser bleiben neu, weil gesendete Zeilen schon da sind. Nichts wird gelöscht.
- [ ] **Step 3:** VM aufräumen (`/tmp/wt-s1*`), `git status` sauber, Commit `docs(post): Runbook Stufe 1 ausrollen`. Der Zweig wird gepusht, nicht gemergt und nicht ausgerollt.
