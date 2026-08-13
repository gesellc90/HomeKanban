-- 0003_item_lead_days.sql — M8, Frage 4 der Fragerunde (docs/PLAN.md §9/§10, O3).
--
-- Rein additiv (CLAUDE.md §4): eine NOT NULL Spalte mit Default auf `items`, nichts entfernt.
-- Entschieden gegen die ursprüngliche Empfehlung aus §10 (O3): die Vorlaufzeit für den
-- Schwellenvorschlag (`reorder_level = ceil(rate × lead_days)`, M8) gilt pro Artikel, nicht
-- global. `HOMEKANBAN_LEAD_DAYS` bleibt als Vorbelegung für neu angelegte Artikel bestehen
-- (app/config.py), ab jetzt aber änderbar wie jedes andere Stammdatum.
--
-- Default 7 spiegelt den bisherigen globalen Standard (app/config.py, Settings.lead_days) —
-- bestehende Artikel starten mit demselben Wert, den sie bislang implizit über die
-- Einstellung hatten.

ALTER TABLE items ADD COLUMN lead_days INTEGER NOT NULL DEFAULT 7 CHECK (lead_days >= 1);
