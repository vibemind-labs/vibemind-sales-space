# Aufträge empfangen: Sales als Empfänger im Auftragsbuch

Stand 23.11.2026. **Gebaut und getestet, nicht ausgerollt.** Nichts aus diesem Dokument ist in einer
Datenbank oder auf einem Rechner eingespielt. Jeder Schritt unter „Ausrollen" braucht ein eigenes Ja des
Betreibers.

## Was es ist

Das Gehirn von VibeMind legt Aufträge fester Art ins Auftragsbuch (Schema `auftrag`, `von = brain`,
`an = sales`). Der Dienst `auftrag-abholer` nimmt sie dort ab, erledigt sie und schreibt ein Ergebnis in
fester Form zurück. Bisher war Sales im Auftragsbuch nur Absender (`auftrag_buch.py`, `auftrag_bote.py`).

| Datei | Aufgabe |
|---|---|
| `sales-mcp/auftrag_arten.yaml` | Die bekannten Auftragsarten mit Eingabe- und Ergebnisform |
| `sales-mcp/auftrag_vertrag.py` | Lader, Formprüfung, Prüfsumme je Art |
| `sales-mcp/auftrag_empfang.py` | Datenbank-Schicht über drei Hüllen |
| `sales-mcp/auftrag_abholer.py` | Der Dienst |
| `db/auftrag-empfang.sql` | Die drei Hüllen und ihre Rechte |
| `config/openclaw.json`, Agent `auftrag` | Kennung im Gateway für Arten, die ein Urteil brauchen |

## Was der Abholer nie tut

- Er gibt nichts frei und versendet nichts. Er kennt weder die Freigabe-Werkzeuge noch einen Versandweg.
- Er führt nur Arten aus, die in `AUFTRAG_ARTEN_FREI` stehen. Ohne den Wert ist das nur `kontakt_finden`.
- Er rät nicht: Unbekannte Art, unbekannte Version oder falsche Form enden mit `fehler` und einem kurzen
  Grund ohne Werte aus dem Auftrag.
- Er versucht nichts zweimal. Ein Auftrag, der in Arbeit liegen bleibt, wird `fehler`.
- Im Protokoll stehen nur die gekürzte Auftragsnummer, die Art und der Stand.

## Auftragsarten

| Art | Version | verändert | freigeschaltet | ausführbar |
|---|---|---|---|---|
| `kontakt_finden` | 1 | nein | ja (Vorgabe) | ja, ohne Sprachmodell |
| `post_pruefen` | 2 | ja | nein | nein, wird mit Grund abgelehnt |
| `termine_heute` | 1 | nein | nein | ja, ohne Sprachmodell |
| `freigaben_zaehlen` | 1 | nein | nein | ja, ohne Sprachmodell |
| `post_offen` | 1 | nein | nein | ja, ohne Sprachmodell |

Die drei Zählarten stehen wörtlich im Vertrag von vibemind-os (Zweig `cc/sales-zaehlarten`, noch nicht auf
master, Fassung 2); der Test hält ihre Prüfsummen fest. Regel: Die Zahl ist die, die der Ladenbesitzer (`POST_BESITZER`) auf der zugehörigen Seite sieht. Die
Zählarten benutzen deshalb dieselben lesenden Wege wie die Seiten:

| Art | Feld | gleiche Zahl wie |
|---|---|---|
| `termine_heute` | `anzahl` | Tagesansicht des Kalenders (`kalender_sicht.ereignisse`, ganzer Tag) |
| | `anzahl_kunden` | Kachel „Termine heute" der Startseite |
| | `quellen_stumm` | Hinweise der Tagesansicht auf Kalender ohne Antwort |
| `freigaben_zaehlen` | `wartend` | Zähler am Menü „Freigaben", ohne den Zusatz aus Marketing und Bewerbungen |
| | `fehlgeschlagen` | Block „fehlgeschlagen" der Freigaben (`entwuerfe_offen`) |
| `post_offen` | `chats_unbeantwortet` | Zähler am Menü „Posteingang" |
| | `mails_offen` | Gesamtzahl der Seite „Mails" für den Ladenbesitzer |

Nicht benutzt: `postfach_lesen` (speichert im Rückfall Mails), `entwuerfe_offen` als Zahl der Wartenden
(zählt freigegebene LinkedIn-Entwürfe mit), der Zusatz aus Marketing und Bewerbungen (Netzabruf zu anderen
Diensten, im Abholer nur ein kalter Zwischenspeicher).

Der Kalenderabruf beim Anbieter ist ein einzelner lesender Aufruf je Auftrag ohne Wiederholung; `anbinden`
begrenzt seine Wartezeit auf 8 Sekunden. Ohne `POST_BESITZER` enden `termine_heute` und `post_offen` mit
`fehler`.

`tests/test_auftrag_zaehlen_wie_seite.py` rechnet beide Wege gegen dieselben Daten in `sales_test`. Er braucht
die Test-Datenbank und läuft nur in der vollen Reihe; lokal ohne sie wird er übersprungen. Ein echter
Kalender wird dort nie gefragt.

`kontakt_finden` sucht nur im Namen und liest nur Kennung, Name und Firma. Adresse und Nummer verlassen die
Datenbank nicht. Private, archivierte und zur Löschung vermerkte Kontakte werden nicht gemeldet.

Beide Arten sind wörtlich die Formen aus dem Vertrag von vibemind-os (`spaces/_contract/sales.contract.yaml`);
ein Test hält beide Prüfsummen fest. `post_pruefen` steht auf Version 2: `link` ist ein Pfad ab `/`, beginnt
nicht mit `//` und enthält kein Leerzeichen; `entwurf_id` ist `^[A-Za-z0-9_-]{1,64}$` oder leer. Ein Auftrag
mit Version 1 wird als unbekannte Version abgelehnt.

## Die Kennung im Gateway

Der Agent `auftrag` hat kein einziges Werkzeug (`tools.deny ["*"]`), ein eigenes Modell ohne Rückfall und
einen eigenen Arbeitsordner. Braucht eine Art ein Urteil, fragt der Abholer ihn mit einem fest vorgegebenen
Funktionsaufruf (`auftrag_abholer.agent_fragen`) und führt das Ergebnis selbst aus. Der Agent kann damit
nichts aufrufen, auch keine Freigabe, gleichgültig was in einem Auftrag oder in einer gelesenen Mail steht.

Vor jeder Übergabe prüft `gateway.funktion_aufrufen`, dass `openclaw/auftrag` in `GET /v1/models` steht.
Fehlt die Kennung, wird nichts gesendet. Das ist nötig, weil das Gateway eine unbekannte Kennung still mit
allen Werkzeugen anlegt.

Heute ruft keine freigeschaltete Art den Agenten auf.

## Verändernde Arten: genau ein Empfänger

Solange getestet wird, darf eine verändernde Art nur einen einzigen, vom Betreiber festgelegten Kontakt als
Empfänger haben. Seine Kennung steht in `AUFTRAG_TEST_KONTAKT_ID`, nie im Repo.

- Fehlt der Wert, lehnt der Abholer jede verändernde Art ab, auch eine freigeschaltete.
- `auftrag_abholer.empfaenger_erlaubt(kontakt_id)` ist die Prüfung, die jeder künftige Ausführer vor dem
  Anlegen eines Entwurfs aufrufen muss.
- Auch für diesen Kontakt entsteht nur ein wartender Entwurf. Freigegeben wird in der Oberfläche.

## Umgebung des Dienstes

| Wert | Bedeutung | Vorgabe |
|---|---|---|
| `SALES_DB_URL`, `SALES_DB_SCHEMA` | wie die anderen Dienste; bedient werden nur `sales` und `sales_test` | – |
| `LADEN_PRAEFIX` | der eigene Laden; nur dessen Aufträge werden übernommen | `sales` |
| `AUFTRAGSBUCH_LADEN` | Pflicht: derselbe Wert wie `AUFTRAGSBUCH_LADEN` beim Gehirn; muss gleich `LADEN_PRAEFIX` sein | – |
| `AUFTRAG_ARTEN_FREI` | freigeschaltete Arten, durch Komma getrennt; leer schaltet alles ab | `kontakt_finden` |
| `AUFTRAG_TEST_KONTAKT_ID` | Kennung des einen Testkontakts für verändernde Arten | leer |
| `POST_BESITZER` | Ladenbesitzer, mit dessen Augen die Zählarten sehen; wie bei sales-ui | leer |
| `OPENCLAW_URL`, `OPENCLAW_GATEWAY_TOKEN` | nur für Arten mit Urteil; heute nicht nötig | leer |

Der Gateway-Token ist Betreiber-Zugang. Er kommt erst in die Umgebung dieses Dienstes, wenn eine Art ihn
braucht.

## Betrieb

- **Start nur bei passendem Schema und Laden.** `sales` läuft nur mit dem Laden `sales`. `sales_test`
  läuft nie mit dem Laden `sales`: Beide Schemas benutzen dieselbe Datenbank-Rolle, und die Hüllen trennen
  nur nach dem Laden. Eine Testinstanz braucht deshalb einen eigenen `LADEN_PRAEFIX`. Passt es nicht,
  schreibt der Abholer den Grund ins Protokoll und fasst keinen Auftrag an.
- **Start nur, wenn der Laden dem des Gehirns gleicht.** `AUFTRAGSBUCH_LADEN` ist Pflicht und muss gleich
  `LADEN_PRAEFIX` sein. Fehlt er oder weicht er ab, meldet der Abholer „AUFTRAGSBUCH_LADEN fehlt" oder
  „LADEN_PRAEFIX und AUFTRAGSBUCH_LADEN sind verschieden" und fasst keinen Auftrag an; die Meldung nennt keinen
  Wert. Ohne diesen Schutz liefe jeder Auftrag an Sales still ab. Die Startzeile sagt bei Gleichheit
  `auftragsbuch_laden=gleich`. Der Abholer liest den Wert aus seiner Umgebung, nicht aus dem Auftragsbuch:
  Die Rolle von Sales darf dort nur die drei Hüllen aufrufen.
- **Fehlergründe** sind feste Sätze (`GRUND_*` in `auftrag_abholer.py`), bei Form- und Ausführungsfehlern mit
  einem Zusatz nach „:" (Feldpfad oder Name der Ausnahme, nie ein Wert). Das Gehirn zeigt nur Gründe aus seiner
  Positivliste; ein neuer Grund muss dort eingetragen werden.
- **Ablaufen hängt am Auftrag-Boten.** `auftrag.ablaufen()` ruft nur der Dienst `auftrag-bote` auf. Steht
  er, wird kein Auftrag nach seiner Frist `abgelaufen`, auch keiner an Sales. Der Abholer selbst übernimmt
  einen Auftrag nach Fristende nicht mehr, er bleibt dann `offen` liegen.
- **Ein Auftrag wird genau einmal übernommen.** Bleibt er länger als die Leihdauer in Arbeit, wird er beim
  nächsten Durchgang `fehler`.

## Wo die Migration liegt

Die drei Hüllen ziehen unverändert in Namen und Signatur nach vibemind-os um, als
`101_auftragsbuch_empfang.sql` neben den übrigen Dateien des Schemas `auftrag`. Eingespielt wird die Datei
von dort. `db/auftrag-empfang.sql` in diesem Repo ist der Stand, gegen den der Abholer gebaut und getestet
ist, und wird danach zum Verweis.

## Tests

Ohne Datenbank und ohne Env-Datei, aus `sales-mcp/`:

```
python -m pytest tests/test_auftrag_vertrag.py tests/test_auftrag_abholer.py tests/test_auftrag_kennung.py tests/test_auftrag_empfang_sql.py -q -p no:cacheprovider
```

Mit Test-Datenbank zusätzlich `tests/test_auftrag_zaehlen_wie_seite.py` (Zahl wie auf der Seite).

Nicht getestet: die SQL-Datei gegen eine echte Datenbank, der Dienst im Container, die Verdrahtung
`verborgen_aus_server` und `anbinden` mit dem echten `server.py`, der Vergleich mit den Seiten (braucht
`sales_test`), der Agent `auftrag` in einem laufenden Gateway.

## Ausrollen (nicht ausgeführt)

Reihenfolge einhalten. Nach jedem Schritt steht der alte Stand ohne Schaden still, weil ohne Freischaltung
im Auftragsbuch kein Auftrag an Sales entstehen kann.

1. **Prüfen, bevor etwas eingespielt wird.** Die Hüllen in `db/auftrag-empfang.sql` einmal in einer
   Transaktion mit `ROLLBACK` gegen die echte Datenbank laufen lassen (legt nichts an) und danach im
   Testschema mit einem angelegten Probe-Auftrag durchspielen: übernehmen, abschließen, zweites Übernehmen
   liefert nichts.
2. **Migration einspielen:** `101_auftragsbuch_empfang.sql` aus vibemind-os, **nicht** `db/auftrag-empfang.sql`.
   101 enthält dieselben drei Hüllen mit denselben Signaturen und Bedingungen. Sie ist aber nicht rein additiv:
   Sie ersetzt `_vergeben` und `brain_lesen` und legt die Hüllen und die Rolle für Rowboat an. Rückweg und
   Reihenfolge stehen dort. Die Datei hier nach 101 einzuspielen ersetzt nur die drei Sales-Hüllen durch
   gleichwertige Fassungen; nötig ist das nicht.
3. **Abbild neu bauen** (`jsonschema` ist als Abhängigkeit dazugekommen) und den Dienst eintragen. Der
   Eintrag für `docker-compose.yml`, nach dem Muster von `auftrag-bote`:

   ```yaml
     auftrag-abholer:
       build: ./sales-mcp
       image: sales-claw-sales-mcp:local
       container_name: ${LADEN_PRAEFIX:-sales}-auftrag-abholer
       command: python -m auftrag_abholer
       restart: unless-stopped
       environment:
         - SALES_DB_URL=${SALES_DB_URL}
         - SALES_DB_SCHEMA=${SALES_DB_SCHEMA:-sales}
         - TZ=${TZ:-Europe/Berlin}
         - LADEN_PRAEFIX=${LADEN_PRAEFIX:-sales}
         - AUFTRAGSBUCH_LADEN=${AUFTRAGSBUCH_LADEN:?gleich dem Wert beim Gehirn}
         - AUFTRAG_ARTEN_FREI=${AUFTRAG_ARTEN_FREI:-kontakt_finden}
         - AUFTRAG_TEST_KONTAKT_ID=${AUFTRAG_TEST_KONTAKT_ID:-}
         - POST_BESITZER=${POST_BESITZER:-}
         - CALDAV_TIMEOUT_S=8
         # dazu die Kalender-Zugangsdaten wie bei sales-mcp, nur wenn termine_heute freigeschaltet wird
       logging:
         driver: json-file
         options:
           max-size: "10m"
           max-file: "3"
   ```

   Namentlich starten, nie mit einem blanken `docker compose up -d`. Rückweg: Dienst stoppen und entfernen.
4. **Start prüfen:** Die erste Protokollzeile nennt Schema, Laden, freigeschaltete Arten und je Art die
   ersten acht Zeichen der Prüfsumme. Diese Prüfsumme mit dem Stand in vibemind-os vergleichen.
   Der Laden muss auf beiden Seiten gleich sein: `LADEN_PRAEFIX` hier und `AUFTRAGSBUCH_LADEN` beim Gehirn.
   Dafür bekommt der Abholer `AUFTRAGSBUCH_LADEN` mit dem Wert des Gehirns und startet nur bei Gleichheit
   (Startzeile `auftragsbuch_laden=gleich`). Dass dieser Wert wirklich der des Gehirns ist, prüft der Abholer
   nicht; beim Eintragen den Wert aus der Umgebung des Gehirns übernehmen.
5. **Freischalten im Auftragsbuch** (Schritt der VibeMind-Seite, nicht dieses Repos): eine Zeile in
   `auftrag.brain_arten` für `('sales', 'kontakt_finden', 1)`, dazu die Art im Vertrag und im Verzeichnis
   von vibemind-os. Erst danach kann das Gehirn einen Auftrag an Sales anlegen.
   Rückweg: die Zeile wieder löschen.
6. **Probe:** einen Auftrag `kontakt_finden` über das Gehirn anlegen und im Auftragsbuch nachlesen:
   `fertig`, Ergebnis in der Form, keine Adresse und keine Nummer. Bleibt der Auftrag `offen`, zuerst den
   Laden auf beiden Seiten vergleichen (Schritt 4).
7. **Gegenproben, je einmal echt:** Abholer gestoppt (Auftrag wird nach der Frist `abgelaufen`),
   unbekannte Version (wird `fehler` mit Grund), gesperrte Art (wird `fehler` mit Grund).

Die Kennung `auftrag` im laufenden Gateway wird erst eingetragen, wenn eine Art sie braucht. Die Saat in
`config/openclaw.json` wirkt nur auf eine frische Installation; für das laufende Gateway braucht es dann
ein Skript nach dem Muster von `deploy/post-anbinden.sh` (Eintrag setzen, `GET /v1/models` prüfen, bei
Ablehnung abbrechen). Dieses Skript gibt es noch nicht.

## Offen

- Der Laden kommt beim Aufruf der Hüllen vom Abholer selbst. Das trägt, solange nur die Rolle des
  Basis-Ladens die Hüllen ausführen darf. Bekommt ein zweiter Laden Zugang zum Auftragsbuch, muss der Laden
  in der Datenbank aus der Rolle abgeleitet werden. `sales` und `sales_test` benutzen dieselbe Rolle; dagegen
  steht die Startprüfung (Abschnitt „Betrieb").
- Herzschlag und Überwachung des Abholers (`deploy/smoke.sh`, `deploy/wache.sh`) fehlen.
- Der lesende Zugang für die Nachprüfung `beleg` fehlt.
- Der Ausführer für `post_pruefen` (Version 2 der Form ist da).
- Die Freischaltung von `kontakt_finden` wartet auf zwei Dinge im Gehirn: die Sperre für Agenten, die
  heute alle Werkzeug-Server sehen, und die Herkunftsregel samt Ergebnistext ohne Personendaten.
