-- 0002_shopping_list_taxonomy_snapshots.sql — M7, Frage 1 der Fragerunde (docs/PLAN.md §9).
--
-- Rein additiv (CLAUDE.md §4): vier nullable Spalten auf `shopping_list_lines`, nichts entfernt.
-- Entschieden: Laden/Kategorie werden wie `name_snapshot`/`unit_snapshot` beim Anfügen der
-- Position eingefroren, statt live aus `items` gelesen zu werden — die Liste im Supermarkt soll
-- sich nicht unter der Hand umsortieren, wenn zu Hause ein Artikel umgehängt wird (§3).
--
-- Position von Laden/Kategorie wird mit eingefroren (`*_position_snapshot`), nicht nur der Name:
-- Die Liste ist ein abgeschlossener Einkaufsauftrag und soll für sortiertes Gruppieren ohne
-- weiteren Zugriff auf `categories`/`stores` auskommen — auch wenn ein Laden zwischenzeitlich
-- umbenannt oder (ohne zugeordnete Artikel) gelöscht wurde.

ALTER TABLE shopping_list_lines ADD COLUMN store_snapshot TEXT;
ALTER TABLE shopping_list_lines ADD COLUMN store_position_snapshot INTEGER;
ALTER TABLE shopping_list_lines ADD COLUMN category_snapshot TEXT;
ALTER TABLE shopping_list_lines ADD COLUMN category_position_snapshot INTEGER;
