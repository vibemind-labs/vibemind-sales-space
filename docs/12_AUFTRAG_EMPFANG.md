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
| `post_pruefen` | 1 | ja | nein | nein, wird mit Grund abgelehnt |

`kontakt_finden` sucht nur im Namen und liest nur Kennung, Name und Firma. Adresse und Nummer verlassen die
Datenbank nicht. Private, archivierte und zur Löschung vermerkte Kontakte werden nicht gemeldet.

`post_pruefen` ist wörtlich die Form aus dem Vertrag von vibemind-os; ein Test hält die Prüfsumme fest.
Vor dem Freischalten braucht die Form eine Version 2: `link` und `entwurf_id` haben dort noch kein Muster.

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
| `AUFTRAG_ARTEN_FREI` | freigeschaltete Arten, durch Komma getrennt; leer schaltet alles ab | `kontakt_finden` |
| `AUFTRAG_TEST_KONTAKT_ID` | Kennung des einen Testkontakts für verändernde Arten | leer |
| `OPENCLAW_URL`, `OPENCLAW_GATEWAY_TOKEN` | nur für Arten mit Urteil; heute nicht nötig | leer |

Der Gateway-Token ist Betreiber-Zugang. Er kommt erst in die Umgebung dieses Dienstes, wenn eine Art ihn
braucht.

## Tests

Ohne Datenbank und ohne Env-Datei, aus `sales-mcp/`:

```
python -m pytest tests/test_auftrag_vertrag.py tests/test_auftrag_abholer.py tests/test_auftrag_kennung.py tests/test_auftrag_empfang_sql.py -q -p no:cacheprovider
```

Nicht getestet: die SQL-Datei gegen eine echte Datenbank, der Dienst im Container, die Verdrahtung
`verborgen_aus_server` mit dem echten `server.py`, der Agent `auftrag` in einem laufenden Gateway.

## Ausrollen (nicht ausgeführt)

Reihenfolge einhalten. Nach jedem Schritt steht der alte Stand ohne Schaden still, weil ohne Freischaltung
im Auftragsbuch kein Auftrag an Sales entstehen kann.

1. **Prüfen, bevor etwas eingespielt wird.** Die Hüllen in `db/auftrag-empfang.sql` einmal in einer
   Transaktion mit `ROLLBACK` gegen die echte Datenbank laufen lassen (legt nichts an) und danach im
   Testschema mit einem angelegten Probe-Auftrag durchspielen: übernehmen, abschließen, zweites Übernehmen
   liefert nichts.
2. **Migration einspielen:** `db/auftrag-empfang.sql`. Rein additiv, drei neue Funktionen.
   Rückweg: `DROP FUNCTION auftrag.sales_empfang_naechster(text, interval)`, ebenso die beiden anderen.
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
         - AUFTRAG_ARTEN_FREI=${AUFTRAG_ARTEN_FREI:-kontakt_finden}
         - AUFTRAG_TEST_KONTAKT_ID=${AUFTRAG_TEST_KONTAKT_ID:-}
       logging:
         driver: json-file
         options:
           max-size: "10m"
           max-file: "3"
   ```

   Namentlich starten, nie mit einem blanken `docker compose up -d`. Rückweg: Dienst stoppen und entfernen.
4. **Start prüfen:** Die erste Protokollzeile nennt Schema, Laden, freigeschaltete Arten und je Art die
   ersten acht Zeichen der Prüfsumme. Diese Prüfsumme mit dem Stand in vibemind-os vergleichen.
5. **Freischalten im Auftragsbuch** (Schritt der VibeMind-Seite, nicht dieses Repos): eine Zeile in
   `auftrag.brain_arten` für `('sales', 'kontakt_finden', 1)`, dazu die Art im Vertrag und im Verzeichnis
   von vibemind-os. Erst danach kann das Gehirn einen Auftrag an Sales anlegen.
   Rückweg: die Zeile wieder löschen.
6. **Probe:** einen Auftrag `kontakt_finden` über das Gehirn anlegen und im Auftragsbuch nachlesen:
   `fertig`, Ergebnis in der Form, keine Adresse und keine Nummer.
7. **Gegenproben, je einmal echt:** Abholer gestoppt (Auftrag wird nach der Frist `abgelaufen`),
   unbekannte Version (wird `fehler` mit Grund), gesperrte Art (wird `fehler` mit Grund).

Die Kennung `auftrag` im laufenden Gateway wird erst eingetragen, wenn eine Art sie braucht. Die Saat in
`config/openclaw.json` wirkt nur auf eine frische Installation; für das laufende Gateway braucht es dann
ein Skript nach dem Muster von `deploy/post-anbinden.sh` (Eintrag setzen, `GET /v1/models` prüfen, bei
Ablehnung abbrechen). Dieses Skript gibt es noch nicht.

## Offen

- Der Laden kommt beim Aufruf der Hüllen vom Abholer selbst. Das trägt, solange nur die Rolle des
  Basis-Ladens die Hüllen ausführen darf. Bekommt ein zweiter Laden Zugang zum Auftragsbuch, muss der Laden
  in der Datenbank aus der Rolle abgeleitet werden. Ob `sales` und `sales_test` dieselbe Rolle benutzen, ist nicht geprüft.
- Herzschlag und Überwachung des Abholers (`deploy/smoke.sh`, `deploy/wache.sh`) fehlen.
- Der lesende Zugang für die Nachprüfung `beleg` fehlt.
- `post_pruefen` Version 2 mit Mustern für `link` und `entwurf_id`, danach der Ausführer.
- Wohin die Migration endgültig gehört: Die übrigen Dateien des Schemas `auftrag` liegen in vibemind-os.
