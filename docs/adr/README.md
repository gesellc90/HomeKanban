# Architekturentscheidungen (ADRs)

Hier liegen kurze Notizen zu technischen Entscheidungen mit Tragweite — eine Datei je
Entscheidung, benannt `NNNN-kurzer-titel.md` (z. B. `0001-sqlite-migrationen.md`).
Eine Seite genügt. Ziel ist, dass in einem Jahr noch nachvollziehbar ist, **warum** etwas so ist.

Nicht jede Kleinigkeit braucht ein ADR. Ein ADR lohnt sich, wenn die Entscheidung schwer
umkehrbar ist, mehrere vertretbare Optionen hatte oder jemand sie später garantiert hinterfragt.

## Vorlage

```markdown
# NNNN — Titel der Entscheidung

- **Status:** vorgeschlagen | entschieden | ersetzt durch NNNN
- **Datum:** JJJJ-MM-TT
- **Meilenstein:** M?

## Kontext

Welches Problem stand an? Welche Randbedingungen gelten (Raspberry Pi, nur Heimnetz,
keine Cloud, SQLite, keine CI)?

## Entscheidung

Was wurde festgelegt — in einem klaren Satz, im Aktiv.

## Alternativen

- **Option B:** kurz, und warum nicht.
- **Option C:** kurz, und warum nicht.

## Konsequenzen

Was wird dadurch leichter, was schwerer? Was müsste passieren, damit die Entscheidung neu
bewertet wird?
```

## Übersicht

| Nr. | Entscheidung | Status |
| --- | --- | --- |
| [0001](0001-ganzzahlige-mengen.md) | Ganzzahlige Mengen statt Dezimalwerte | entschieden |
| [0002](0002-bewegungsjournal-als-wahrheit.md) | Bewegungsjournal als Wahrheit, `items.stock` als Cache | entschieden |
| [0003](0003-direktes-sql-statt-orm.md) | Direktes SQL statt ORM | entschieden |
| [0004](0004-druckoptimiertes-html-fuer-etiketten.md) | Druckoptimiertes HTML statt PDF-Bibliothek für Etiketten | entschieden |
| [0005](0005-idempotente-entnahmebuchung.md) | Idempotente Entnahmebuchung über Unique-Index statt Vorab-Prüfung | entschieden |
| [0006](0006-restmenge-erst-mit-der-naechsten-liste.md) | Restmenge nach Teilkauf kommt erst mit der nächsten Liste | entschieden |
| [0007](0007-laden-kategorie-schnappschuss-in-der-einkaufsliste.md) | Laden/Kategorie werden beim Anfügen einer Position eingefroren | entschieden |
