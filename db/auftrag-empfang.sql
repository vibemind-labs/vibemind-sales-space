-- Auftragsbuch: Sales als EMPFAENGER fuer Auftraege des Gehirns (an = 'sales', von = 'brain').
--
-- NICHT EINGESPIELT. Nur geschrieben; einspielen darf sie der Betreiber nach eigenem Ja.
-- Voraussetzung: vibemind-os Migrationen 096, 098 und 100 (Schema `auftrag`, Spalten art_version/plan_id).
-- Idempotent, eine Transaktion, rein additiv: keine bestehende Funktion und keine Tabelle wird geaendert.
--
-- Drei SECURITY-DEFINER-Huellen fuer die Rolle sales_app (sales-mcp/auftrag_empfang.py):
--   sales_empfang_naechster(laden, leihdauer)  offen -> in_arbeit, genau EIN Mal je Auftrag
--   sales_empfang_abschliessen(id, ergebnis, laden)   in_arbeit -> fertig
--   sales_empfang_fehler(id, grund, laden)            in_arbeit -> fehler
-- Jede fasst nur Zeilen mit an = 'sales' UND von = 'brain' an. Auftraege, die Sales selbst gibt
-- (von = 'sales'), und Auftraege an andere Empfaenger bleiben unerreichbar.
--
-- Kein zweiter Versuch: Ein Auftrag, der in Arbeit liegen bleibt (Absturz des Abholers), wird beim
-- naechsten Aufruf `fehler` und nie neu vergeben. Ob schon etwas geschehen ist, zeigt dann der Space,
-- nicht eine Wiederholung (Auftragsvertrag 8.7).
--
-- Diese Datei schaltet KEINE Auftragsart frei. Was das Gehirn anlegen darf, steht in
-- auftrag.brain_arten und ist ein eigener Schritt (docs/12_AUFTRAG_EMPFANG.md).
BEGIN;

SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION auftrag.sales_empfang_naechster(p_laden text, p_lease interval) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = auftrag, pg_temp AS $$
DECLARE a auftrag.auftraege;
BEGIN
    IF coalesce(btrim(p_laden), '') = '' THEN RAISE EXCEPTION 'Der Laden fehlt'; END IF;
    IF p_lease IS NULL OR p_lease <= interval '0' OR p_lease > interval '15 minutes' THEN
        RAISE EXCEPTION 'Leihdauer ausserhalb 0 bis 15 Minuten'; END IF;

    -- Liegengebliebene Auftraege dieses Ladens abschliessen statt neu vergeben.
    UPDATE auftrag.auftraege
       SET stand = 'fehler', fehler = 'Bearbeitung bei Sales abgebrochen', vergeben_bis = NULL,
           geaendert = now(),
           verlauf = array_append(verlauf, jsonb_build_object(
               'stand', 'fehler', 'zeit', now(), 'fehler', 'Bearbeitung bei Sales abgebrochen'))
     WHERE an = 'sales' AND von = 'brain' AND laden = p_laden
       AND stand = 'in_arbeit' AND vergeben_bis < now();

    SELECT * INTO a FROM auftrag.auftraege
     WHERE an = 'sales' AND von = 'brain' AND laden = p_laden
       AND stand = 'offen' AND frist_bis > now()
     ORDER BY angelegt
     LIMIT 1
     FOR UPDATE SKIP LOCKED;
    IF a.id IS NULL THEN RETURN NULL; END IF;

    UPDATE auftrag.auftraege
       SET stand = 'in_arbeit', versuche = versuche + 1, vergeben_bis = now() + p_lease,
           geaendert = now(),
           verlauf = array_append(verlauf, jsonb_build_object('stand', 'in_arbeit', 'zeit', now()))
     WHERE id = a.id
    RETURNING * INTO a;

    -- Nur was der Abholer braucht; Mandant, Verlauf und Ergebnis gehen nicht mit.
    RETURN jsonb_build_object('id', a.id, 'art', a.art, 'art_version', a.art_version,
                              'eingabe', a.eingabe, 'plan_id', a.plan_id, 'frist_bis', a.frist_bis);
END $$;

-- Nur im eigenen Laden und nur, solange die Leihdauer laeuft: wer zu spaet kommt, schliesst nichts ab.
CREATE OR REPLACE FUNCTION auftrag.sales_empfang_abschliessen(p_id uuid, p_ergebnis jsonb, p_laden text)
    RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = auftrag, pg_temp AS $$
BEGIN
    IF coalesce(btrim(p_laden), '') = '' THEN RETURN false; END IF;
    IF jsonb_typeof(p_ergebnis) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
    IF pg_column_size(p_ergebnis) > 65536 THEN RETURN false; END IF;
    UPDATE auftrag.auftraege
       SET stand = 'fertig', ergebnis = p_ergebnis, vergeben_bis = NULL, geaendert = now(),
           verlauf = array_append(verlauf, jsonb_build_object('stand', 'fertig', 'zeit', now()))
     WHERE id = p_id AND an = 'sales' AND von = 'brain' AND laden = p_laden
       AND stand = 'in_arbeit' AND frist_bis > now() AND vergeben_bis >= now();
    RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION auftrag.sales_empfang_fehler(p_id uuid, p_fehler text, p_laden text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = auftrag, pg_temp AS $$
DECLARE v_fehler text := left(coalesce(nullif(btrim(p_fehler), ''), 'Fehler ohne Angabe'), 300);
BEGIN
    IF coalesce(btrim(p_laden), '') = '' THEN RETURN false; END IF;
    UPDATE auftrag.auftraege
       SET stand = 'fehler', fehler = v_fehler, vergeben_bis = NULL, geaendert = now(),
           verlauf = array_append(verlauf, jsonb_build_object('stand', 'fehler', 'zeit', now(), 'fehler', v_fehler))
     WHERE id = p_id AND an = 'sales' AND von = 'brain' AND laden = p_laden AND stand = 'in_arbeit';
    RETURN FOUND;
END $$;

-- Neue Funktionen sind fuer PUBLIC ausfuehrbar: zuerst alles entziehen, dann nur sales_app.
-- Der Laden kommt vom Aufrufer. Das traegt nur, solange ausschliesslich sales_app (der Basis-Laden) diese
-- Huellen ausfuehren darf; weitere Laeden haben im Schema `auftrag` keine Rechte (wie in 096). Bekommt je
-- ein zweiter Laden Zugang, muss der Laden hier aus der Rolle abgeleitet werden statt uebergeben.
REVOKE ALL ON FUNCTION auftrag.sales_empfang_naechster(text, interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION auftrag.sales_empfang_abschliessen(uuid, jsonb, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION auftrag.sales_empfang_fehler(uuid, text, text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION auftrag.sales_empfang_naechster(text, interval) TO sales_app;
GRANT EXECUTE ON FUNCTION auftrag.sales_empfang_abschliessen(uuid, jsonb, text) TO sales_app;
GRANT EXECUTE ON FUNCTION auftrag.sales_empfang_fehler(uuid, text, text) TO sales_app;

COMMIT;
