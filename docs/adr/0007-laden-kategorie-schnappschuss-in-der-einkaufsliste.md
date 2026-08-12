# 0007 — Laden/Kategorie werden beim Anfügen einer Position eingefroren

- **Status:** entschieden
- **Datum:** 2026-08-12
- **Meilenstein:** M7

## Kontext

M7 sortiert und gruppiert die Einkaufsliste nach dem Weg durch den Laden: zuerst nach
`stores.position`, innerhalb nach `categories.position` (§7, §9). Dafür muss jede Position der
Liste wissen, zu welchem Laden und welcher Kategorie sie gehört.

`items.category_id`/`items.store_id` existieren bereits seit M1. Zwei Wege standen offen:

- **Live-Join auf `items`** bei jedem Rendern/Export: keine Migration, immer aktuell — aber die
  Liste kann sich zwischen zwei Exporten umsortieren, wenn zu Hause ein Artikel einem anderen
  Laden zugeordnet wird, während er im Supermarkt schon auf der Liste steht.
- **Snapshot-Spalten** auf `shopping_list_lines`, gesetzt beim Anfügen der Position — genau das
  Muster, das `name_snapshot`/`unit_snapshot` seit M1 für den Artikelnamen vorgeben (§3: „Wird ein
  Artikel umbenannt, während die Liste im Supermarkt offen ist, soll die Liste nicht plötzlich
  anders heißen“).

Der Widerspruch ist derselbe wie bei `name_snapshot`: Eine offene Liste ist ein bereits erteilter
Einkaufsauftrag, kein Live-Blick in die Datenbank.

## Entscheidung

**Snapshot, konsistent mit der Namenskopie.** `shopping_list_lines` bekommt vier zusätzliche,
nullable Spalten (additive Migration `0002_shopping_list_taxonomy_snapshots.sql`):

- `store_snapshot TEXT`, `store_position_snapshot INTEGER`
- `category_snapshot TEXT`, `category_position_snapshot INTEGER`

Gesetzt werden sie **nur beim Anfügen** einer neuen Position (`app/domain/shopping.py`,
`plan_reconciliation` → `LineToAppend`), aus dem zu diesem Zeitpunkt aktuellen Stand von
`items.category_id`/`items.store_id` (aufgelöst in `app/services/shopping.py::reconcile`). Wird
ein Artikel danach umgehängt, ändert sich die bereits angefügte Position nicht — genau wie beim
Namen. `app/domain/grouping.py` gruppiert und sortiert über diese eingefrorenen Werte, nicht über
einen Join.

Eingefroren wird nicht nur der **Name**, sondern auch die **Position** von Laden/Kategorie: Die
Liste soll für die Sortierung ohne weiteren Zugriff auf `categories`/`stores` auskommen — auch
wenn ein Laden zwischenzeitlich umbenannt oder (ohne zugeordnete Artikel, siehe unten) gelöscht
wurde.

## Alternativen

- **Live-Join auf `items`** (siehe Kontext): verworfen, weil er der Begründung aus §3 widerspricht
  und den einzigen Zweck der Gruppierung — eine Liste, die im Laden verlässlich stimmt — wieder
  aufweicht.
- **Nur IDs statt Text/Position snapshotten**, mit Live-Nachschlagen von Name/Reihenfolge beim
  Rendern: spart zwei Spalten, aber verlöre dieselbe Stabilität wie oben, sobald ein Laden
  umbenannt oder gelöscht wird, und bräuchte für gelöschte Läden ohnehin einen Rückfallwert. Die
  vier reinen Textspalten sind der einfachere, dem bestehenden Muster treue Weg.

## Konsequenzen

**Leichter:** Die Gruppierungslogik (`app/domain/grouping.py`) bleibt reine Funktion ohne SQL —
sie sieht nur Werte, keine IDs, die nachgeschlagen werden müssten. Eine Liste im Supermarkt bleibt
stabil, auch wenn zu Hause an der Taxonomie gearbeitet wird.

**Schwerer:** Vier zusätzliche Spalten, die nur für neu angefügte Positionen befüllt werden —
Positionen aus der Zeit vor M7 (bzw. vor der ersten Zuordnung eines Artikels) bleiben mit
`NULL` stehen und landen in der Gruppe „Sonstiges“. Das ist gewollt (§9 M7 Definition of Done:
„Artikel ohne Zuordnung landen in ‚Sonstiges‘ und verschwinden nicht“), aber eine Schemaentscheidung
über die Bedeutung einer Listenposition ist nachträglich teuer — ein Rückweg auf Live-Join würde
alle vier Spalten funktionslos machen, ohne sie zu benötigen.

**Neu bewertet würde die Entscheidung**, wenn sich zeigt, dass Läden im Alltag so oft umbenannt
oder Artikel so oft umgehängt werden, dass „schon angefügte Positionen zeigen den alten Laden“
mehr verwirrt als die Konsistenz mit dem Namen nützt.
