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
| — | noch keine | — |
