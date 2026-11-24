# Post-Assistent 3c + 3d: Privat nur im Besitzer-Chat, Morgenübersicht und Hinweise

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Private Mails bekommt der Agent nur, wenn Felix selbst über seine WhatsApp-Nummer mit ihm spricht.
- Jeden Morgen um 7:30 Uhr (Europe/Berlin) kommt die Übersicht in diesen Chat.
- Tagsüber kommt höchstens dreimal eine kurze Nachricht zu Mails mit `dringlichkeit = sofort`, nie zwischen 20 und 7 Uhr.

**Architecture:** Gebaut wird der Rückfall der Spec (3c), denn OpenClaw 2026.7.1 gibt Agent oder Sitzung nicht an MCP-Server weiter. Am 24.11. in `/app/docs/cli/mcp.md` geprüft: Es gibt nur feste Header je Server.
- **Eigener Agent `besitzer`** in OpenClaw. Er bekommt Felix' WhatsApp-Direktnachrichten per `bindings[]`, denselben Arbeitsbereich und Ton wie `main` und zusätzlich die privaten Post-Werkzeuge.
- **Eigener Dienst `sales-post-mcp`:** Er stellt die privaten Werkzeuge an einem eigenen MCP-Zugang bereit, geschützt durch einen festen Schlüssel-Header. Alle anderen Agenten bekommen diese Werkzeuge per `tools.deny` gesperrt. `main` bleibt am HTTP-Gateway (Rowboat, Brain) und sieht nur Business.
- **Morgenübersicht:** ein Cron-Agentenlauf am Agenten `besitzer`.
- **Eilige Hinweise:** ein Cron-Befehl ohne Modell. Er fragt alle 15 Minuten `sales-post-mcp` nach fälligen Hinweisen und stellt den Text per WhatsApp zu.

**Tech Stack:** Python 3 (sales-mcp-Abbild, MCP streamable-http, Starlette), OpenClaw 2026.7.1 (Agenten, Bindings, Cron), PostgreSQL, pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-post-assistent-design.md`, Abschnitt 5 / Stufe 3 / **3c** und **3d**, dazu §1 (Zielbild), §2 und §8 (offener Punkt Besitzer-Chat). Setzt 3b voraus (`post_werkzeuge`).

## Global Constraints

- „Private Mails bekommt der Agent nur, wenn Felix selbst mit ihm spricht … Nie in Kundenantworten (`sales-auto`), nie für Teammitglieder, nie über andere Agenten oder das HTTP-Gateway (Rowboat, Brain, Debugger).“ (Spec 3c)
- „Durchgesetzt durch Werkzeug-Rechte, nicht im Prompt.“ (Spec 3c)
- „Sensible Mails (Kopf nur gespeichert) bleiben auch im Besitzer-Chat bei Absender und Betreff.“ (Spec 3c) Auch im Besitzer-Chat gilt: Inhalt nur von geprüften, unbedenklichen Mails (3a).
- „Für Felix ändert sich nichts: gleiche Nummer, gleicher Agent im Ton.“ (Spec 3c)
- Morgenübersicht täglich **7:30 Uhr Europe/Berlin**. Sie kostet einen Agentenaufruf am Tag und zählt nicht zur Tagesgrenze der Sortierung (Spec 3d).
- Hinweise nur bei `dringlichkeit = sofort`, **höchstens 3 am Tag, nicht zwischen 20 und 7 Uhr**. Gesendete Hinweise werden vermerkt, damit keiner doppelt kommt (Spec 3d).
- Kein automatisches Versenden von Mails. Entwürfe nur auf Felix' Wort (Spec §2, 3d).
- Der Schlüssel des privaten Zugangs steht nie in Git, nie in `AGENTS.md`, nie in einer Ausgabe. In OpenClaw steht er als Env-Verweis, nicht als Klartext (`openclaw mcp doctor` meldet Klartext-Header).
- Keine Mailinhalte, Betreffe oder Telefonnummern in Logs. Felix' Nummer steht nie in Git, nur in der Gateway-Konfiguration.
- Änderungen an der OpenClaw-Konfiguration und an Cron-Jobs geschehen nur im Ausrollen, mit Felix' OK. Die Prüfungen in Task 1 laufen in einem **Wegwerf-Container**, nie am Live-Gateway `sales-claw`.
- Conventional Commits mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Feste Werte:
  - Agent-ID `besitzer`, Dienst `sales-post-mcp`, MCP-Servername in OpenClaw `post-besitzer`
  - Env `POST_BESITZER_MCP_SCHLUESSEL` (in `sales-post-mcp` und im Gateway), Header `X-Post-Besitzer-Schluessel`
  - `HINWEISE_MAX_TAG = 3`, Ruhezeit 20:00–07:00 Europe/Berlin, Hinweis-Abfrage alle 15 Minuten
  - Hinweistext je Mail: `Dringend: <Absender> – <Betreff> (seit <HH:MM>)`. Mehrere Mails stehen zeilenweise in einer Nachricht, eine Nachricht zählt als ein Hinweis.

## Entscheidungspunkte

Task 1 klärt drei Fragen in einem Wegwerf-Container. Die Antworten legen fest, wie Task 4 und das Runbook aussehen:
- **E1: Sperre der MCP-Werkzeuge je Agent.** Werkzeugnamen im Probe, z. B. `post-besitzer__post_suchen`. Greift `agents.list[].tools.deny` mit Muster (`post-besitzer__*`) oder nur mit exakten Namen? Für Task 4 reichen exakte Namen.
- **E2: Agentenwahl am HTTP-Gateway.** Kann ein Aufrufer von `/v1/chat/completions` den Agenten `besitzer` wählen (Modell `openclaw/besitzer` oder Sitzung `agent:besitzer:…`)? Lässt sich das per Konfiguration verbieten? **Lässt es sich nicht verbieten, bricht der Bauende hier ab und fragt Felix.** Ohne Sperre könnten Rowboat oder Brain private Mails lesen, und das ist ein Anti-Ziel.
- **E3: Zustellung per Cron.** Stellt ein Befehls-Job mit `--announce --channel whatsapp` bei leerer Ausgabe **nichts** zu? Gibt es `curl` oder `node` im Gateway-Abbild für die Abfrage?

## Review Focus

1. **Rowboat oder Brain rufen das HTTP-Gateway mit Agent `main` und fragen nach privaten Mails.** Erwartung: `main` hat die privaten Werkzeuge nicht, die Antwort enthält nichts Privates. Prüfung im Runbook per echter Probe. Test in Task 2: `test_normaler_zugang_sieht_nie_privat`.
2. **Der Schlüssel-Header fehlt, ist falsch oder kommt von einem anderen Dienst im Compose-Netz.** Erwartung: Der private Zugang antwortet 401 und gibt keine Werkzeugliste und keine Daten heraus. Test in Task 2: `test_privater_zugang_ohne_schluessel_401`.
3. **Um 19:59 und 20:01 Uhr, über die Zeitumstellung und nach dem dritten Hinweis.** Erwartung: Um 19:59 geht ein Hinweis raus, um 20:01 keiner, nach drei Hinweisen keiner mehr bis Mitternacht. Danach gilt um 7:00 eine neue Tageszählung. Test in Task 3: `test_hinweise_ruhezeit_und_tagesgrenze`.
4. **Die Hinweis-Abfrage läuft zweimal gleichzeitig** (Cron-Wiederholung nach einem Fehler). Erwartung: Keine Mail wird doppelt gemeldet. Test in Task 3: `test_hinweise_doppelt_abgefragt_kein_doppel`.
5. **Eine `sofort`-Mail ist markiert oder sensibel.** Erwartung: Der Hinweis nennt nur Absender und Betreff, wie bei jeder Mail, und nie Text. Eine markierte Mail wird zusätzlich als `– bitte in den Freigaben prüfen` gekennzeichnet. Test in Task 3: `test_hinweis_markiert_und_sensibel_nur_kopf`.

---

### Task 1: Prüfungen E1–E3 im Wegwerf-Container

**Files:**
- Create: `docs/superpowers/specs/2026-11-24-openclaw-besitzer-pruefung.md` (Ergebnisse mit Befehl, Ausgabe gekürzt und ohne Geheimnisse)

- [ ] **Step 1:** Einen Wegwerf-Container aus `ghcr.io/openclaw/openclaw:2026.7.1-slim` starten:
  - eigenes leeres State-Volume, kein Kanal, kein Port nach außen
  - zwei Agenten `main` und `besitzer`
  - ein Stub-MCP-Server (Python, im selben Wegwerf-Netz) mit zwei Werkzeugen
  - `besitzer` darf alles, `main` hat die Werkzeuge in `tools.deny`
- [ ] **Step 2 (E1):** `openclaw mcp probe` notiert die Werkzeugnamen. `openclaw agent --agent main --session-key agent:main:probe -m 'Liste deine Werkzeuge' --json` (Modell per Stub-Provider oder `--tools` leer, damit kein echter Modellaufruf nötig ist) zeigt, ob die gesperrten Werkzeuge fehlen. Das wird mit Muster und mit exakten Namen geprüft.
- [ ] **Step 3 (E2):** Die Gateway-Doku (`/app/docs/gateway/*`) nach einer Agentenbeschränkung für `/v1/chat/completions` durchsuchen und im Container einen Aufruf mit `model: "openclaw/besitzer"` absetzen. Ergebnis: verbietbar ja oder nein, mit dem Konfigurationsschlüssel.
- [ ] **Step 4 (E3):** Einen Befehls-Job mit leerer Ausgabe und `--announce` gegen einen Webhook-Stub statt WhatsApp anlegen und `openclaw cron run` ausführen. Notieren, ob zugestellt wird. Prüfen, ob `curl` und `node` im Abbild vorhanden sind.
- [ ] **Step 5:** Den Container und das Volume entfernen. Das Ergebnisdokument committen: `docs(post): Pruefung OpenClaw fuer den Besitzer-Chat`.
- [ ] **Step 6: Entscheidung.** Ist E2 nicht verbietbar: hier anhalten und Felix fragen, nichts weiter bauen. Liefert E3 bei leerer Ausgabe trotzdem eine Nachricht: Die Hinweis-Abfrage gibt den Text über `--announce`-freie Zustellung im Skript selbst aus (`openclaw message send` im Befehl). Das notieren und in Task 4 verwenden.

### Task 2: Privater Zugang `sales-post-mcp`

**Files:**
- Modify: `sales-mcp/post_struktur.py`
  - `Betrachter` bekommt das Feld `privat: bool = False`
  - neuer `BESITZER_CHAT`
  - `sichtbar_sql` behandelt ihn
- Create: `sales-mcp/post_besitzer_mcp.py` (eigener MCP-Server mit den drei 3b-Werkzeugen als `BESITZER_CHAT` und der Route `/hinweise` aus Task 3)
- Modify: `docker-compose.yml` (Dienst `sales-post-mcp`: gleiches Abbild `sales-claw-sales-mcp:local`, Befehl `python post_besitzer_mcp.py`, nur DB-Zugang, `POST_BESITZER`, `SALES_DB_SCHEMA` und `POST_BESITZER_MCP_SCHLUESSEL`, kein Port nach außen, `restart: unless-stopped`)
- Test: `sales-mcp/tests/test_post_besitzer_mcp.py` (neu)

**Interfaces:**
- Produces: `BESITZER_CHAT = Betrachter(name="besitzer-chat", leitung=True, abteilungen=(), ist_agent=True, privat=True)`. `sichtbar_sql(BESITZER_CHAT)` ergibt `(m.besitzer = %s)` mit dem Container-Besitzer, ohne Bereichsgrenze. Ohne `POST_BESITZER` ergibt es `false`. Die Sperre aus 3a und das Leeren sensibler Inhalte gelten weiter, weil `ist_agent` true ist.
- Produces: `post_besitzer_mcp.app` mit den MCP-Werkzeugen `post_suchen`, `post_mail_lesen` und `post_uebersicht`. Sie sind dünne Hüllen um `post_werkzeuge` mit `BESITZER_CHAT`, und ihre Beschreibungen tragen den DATUM-Satz wie in 3b.
- Jede Anfrage ohne gültigen Header `X-Post-Besitzer-Schluessel` bekommt 401. Der Vergleich geschieht mit `hmac.compare_digest`. Ist das Env leer, antwortet jede Anfrage mit 503, und der Dienst gibt nie Daten heraus.

- [ ] **Step 1: Write the failing tests**
  - `test_besitzer_chat_sieht_privat_aber_nicht_sensiblen_text`: Eine private Mail wird gefunden und ist lesbar, sofern sie geprüft ist. Von einer sensiblen Mail kommen nur Absender und Betreff.
  - `test_besitzer_chat_haelt_3a_sperre`: Eine markierte private Mail erscheint nur als Kopf mit Hinweis.
  - `test_normaler_zugang_sieht_nie_privat` (Review Focus 1): `server.post_suchen` (3b) findet die private Mail nicht.
  - `test_privater_zugang_ohne_schluessel_401` (Review Focus 2): Ohne Header, mit falschem Header und mit leerem Env antwortet der Dienst 401 bzw. 503. Die Antwort enthält keinen Werkzeugnamen.
  - `test_schluessel_nie_im_log`: caplog enthält nach einer abgewiesenen Anfrage den Schlüssel nicht.
- [ ] **Step 2:** Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** `tests/test_post_besitzer_mcp.py tests/test_post_werkzeuge.py tests/test_post_sichtbarkeit.py` laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(post): privater Post-Zugang nur fuer den Besitzer-Chat`

### Task 3: Fällige Hinweise

**Files:**
- Modify: `db/post-sammelstelle.sql` (Tabelle `post_hinweise`: `mail_id` uuid als Primärschlüssel mit Fremdschlüssel und cascade, `gemeldet_am` timestamptz not null default now(), `nachricht` uuid not null)
- Create: `sales-mcp/post_hinweise.py`
- Modify: `sales-mcp/post_besitzer_mcp.py` (Route `GET /hinweise`, gleicher Schlüssel-Header)
- Test: `sales-mcp/tests/test_post_hinweise.py` (neu)

**Interfaces:**
- Produces: `post_hinweise.faellige(jetzt: datetime | None = None) -> str`. Gibt den Nachrichtentext zurück oder `""`, wenn nichts fällig ist. Kandidaten sind Mails, die **alle** diese Bedingungen erfüllen:
  - eingehend und offen (`offen_sql`)
  - `dringlichkeit = 'sofort'`
  - sichtbar für `BESITZER_CHAT`
  - eingegangen in den letzten 24 Stunden
  - noch nicht in `post_hinweise`

  Ruhezeit und Tagesgrenze werden über die unterschiedlichen `nachricht`-Kennungen seit 0:00 Berliner Zeit gezählt. In einer Transaktion werden die Kandidaten `for update skip locked` gesperrt, in `post_hinweise` eingetragen und dann zum Text zusammengesetzt. Es geht also höchstens einmal raus, auch wenn die Zustellung danach scheitert. Je Nachricht kommen höchstens 5 Mails, die übrigen in den nächsten Nachrichten des Tages.
- Produces: `GET /hinweise` mit gültigem Header → `200 text/plain; charset=utf-8` mit dem Text von `faellige()`, leer bei nichts.

- [ ] **Step 1: Write the failing tests**
  - `test_sofort_mail_wird_einmal_gemeldet`: Die erste Abfrage liefert den Text mit Absender und Betreff, die zweite ist leer.
  - `test_hinweise_ruhezeit_und_tagesgrenze` (Review Focus 3): feste Uhrzeiten 19:59, 20:01 und 06:59 sowie drei Meldungen hintereinander. Dazu ein Datum am Tag der Zeitumstellung (letzter Sonntag im Oktober).
  - `test_hinweise_doppelt_abgefragt_kein_doppel` (Review Focus 4): Zwei Verbindungen fragen gleichzeitig ab, jede Mail steht genau einmal in einer der Antworten.
  - `test_hinweis_markiert_und_sensibel_nur_kopf` (Review Focus 5)
  - `test_erledigte_oder_alte_nicht`: Eine erledigte Mail und eine 25 Stunden alte Mail werden nicht gemeldet.
  - `test_route_braucht_schluessel`: Ohne Header antwortet `/hinweise` mit 401 und trägt nichts ein.
- [ ] **Step 2:** Migration zweimal auf `sales_test` einspielen und die Tests laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Tests laufen lassen. Erwartet: PASS.
- [ ] **Step 5: Commit** `feat(post): faellige dringende Hinweise fuer den Besitzer-Chat`

### Task 4: Gateway-Einrichtung als Skript und Runbook

**Files:**
- Create: `deploy/post-besitzer-anbinden.sh`. Idempotent nach dem Muster von `deploy/post-anbinden.sh`. Es schreibt nur über die `openclaw`-CLI im Container `sales-claw` und kennt `--pruefen` (nur lesen).
- Create: `deploy/post-besitzer-workspace/` mit einer Kopie der Prompt-Dateien von `main`, die `AGENTS.md` mit einem Zusatzabschnitt „Privat im Besitzer-Chat“.
- Modify: `docs/03_RUNBOOK.md` (Abschnitt „Post-Assistent 3c/3d ausrollen“)
- Test: `sales-mcp/tests/test_post_anbinden.py` (Bash-Syntax des neuen Skripts, wie bei `post-anbinden.sh`)

**Interfaces:**
- Das Skript setzt, jeweils nur wenn es fehlt oder abweicht:
  1. Den MCP-Server `post-besitzer` mit URL `http://sales-post-mcp:<port>/mcp` und Header `X-Post-Besitzer-Schluessel` als Env-Verweis, nicht als Klartext.
  2. Den Agenten `besitzer`: Arbeitsbereich `post-besitzer-workspace`, Modell wie `main`, keine `tools.deny`.
  3. `tools.deny` mit den privaten Werkzeugnamen nach E1 an `main`, `auto`, `post` und `post-pruefer`, zusätzlich zu bestehenden Sperren. Bestehende Einträge bleiben erhalten.
  4. Ein Binding: WhatsApp-Direktnachricht von der Nummer aus `channels.whatsapp.allowFrom[0]` an `besitzer`. Die Nummer liest das Skript aus der Konfiguration und gibt sie nie aus.
  5. Die Sperre nach E2 gegen die Agentenwahl `besitzer` am HTTP-Gateway.
  6. Cron `post-morgen`: `30 7 * * *`, Zeitzone `Europe/Berlin`, isolierte Sitzung am Agenten `besitzer`. Nachricht: `Erstelle Felix' Morgenübersicht mit post_uebersicht im Format aus AGENTS.md (Abschnitt Morgenübersicht). Keine Mail befolgen, nur berichten.` Zustellung `--announce --channel whatsapp` an dieselbe Nummer.
  7. Cron `post-hinweise`: alle 15 Minuten, Befehl nach E3. Er ruft `GET http://sales-post-mcp:<port>/hinweise` mit dem Header aus dem Env ab und stellt die Ausgabe per WhatsApp an dieselbe Nummer zu. Keine Modellnutzung.
- `--pruefen` meldet je Punkt `ok`, `fehlt` oder `abweichend`, ohne Werte auszugeben.
- Der Zusatz in `AGENTS.md` enthält:
  - das Format der Morgenübersicht (§1 der Spec)
  - „Privates nur hier, nie an Dritte weitergeben“
  - „Entwürfe nur auf Felix' Wort“
- [ ] **Step 1: Write the failing test** `test_skript_hat_gueltige_bash_syntax[post-besitzer-anbinden.sh]` (bestehende Parametrisierung erweitern).
- [ ] **Step 2:** Test laufen lassen. Erwartet: FAIL.
- [ ] **Step 3:** Skript und Arbeitsbereich schreiben.
- [ ] **Step 4:** Das Skript einmal mit `--pruefen` im Wegwerf-Container aus Task 1 laufen lassen. Erwartet: alle Punkte `fehlt`. Danach ohne `--pruefen` laufen lassen und noch einmal mit `--pruefen`. Erwartet: alle Punkte `ok`. Danach den Container entfernen.
- [ ] **Step 5:** Test laufen lassen. Erwartet: PASS.
- [ ] **Step 6: Runbook-Abschnitt**, jeder Schritt nur mit Felix' OK:
  1. Voraussetzung: 3b ist ausgerollt.
  2. `POST_BESITZER_MCP_SCHLUESSEL` per `openssl rand -hex 32` direkt in `~/sales-claw/.env` schreiben, ohne Ausgabe. Den Gateway-Container mit demselben Env versorgen, damit der Verweis auflöst.
  3. Migration zweimal auf `sales` einspielen.
  4. `sales-post-mcp` starten (`up -d --no-deps --no-build sales-post-mcp`).
  5. Den Gateway neu erstellen, damit das Env da ist (`up -d --no-deps --no-build sales-claw`). Der WhatsApp-Kanal verbindet sich neu.
  6. `deploy/post-besitzer-anbinden.sh` ausführen, dann `--pruefen`.
  7. Proben:
     - Felix schreibt dem Agenten „Was ist heute wichtig?“. Die Antwort kommt vom Agenten `besitzer` (im Gateway-Protokoll nur die Agent-ID) und darf Privates nennen.
     - Rowboat fragt über das HTTP-Gateway mit `main` nach einer privaten Mail und bekommt nichts Privates.
     - Ein Aufruf mit Agent `besitzer` am HTTP-Gateway wird abgewiesen.
     - `openclaw cron run post-hinweise` ohne fällige Mails sendet nichts.
  8. Am nächsten Morgen um 7:30 kommt die Übersicht.
  9. Rückweg in umgekehrter Reihenfolge:
     - Cron-Jobs entfernen
     - Binding entfernen, dann geht WhatsApp wieder an `main`
     - Agent `besitzer` und MCP-Server entfernen
     - `sales-post-mcp` stoppen
     - Die Tabelle `post_hinweise` bleibt stehen.
- [ ] **Step 7:** Volle Testsuite auf dem Zweig und auf der Basis, nacheinander, `comm -13` leer. VM aufräumen. Commit `feat(post): Besitzer-Chat im Gateway einrichten, Runbook 3c/3d`. Der Zweig wird gepusht, nicht gemergt und nicht ausgerollt.
