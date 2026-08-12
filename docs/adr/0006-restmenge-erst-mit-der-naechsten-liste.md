# 0006 — Restmenge nach Teilkauf kommt erst mit der nächsten Liste

- **Status:** entschieden
- **Datum:** 2026-08-11
- **Meilenstein:** M4

## Kontext

§4 Regel 5 („Teilkauf“) verlangte ursprünglich, dass ein Artikel, dessen Bestand nach dem Abhaken
weiter unter der Meldeschwelle liegt, „beim nächsten Abgleich eine neue Position mit dem Rest“
erhält. Das ist der Alltagsfall aus Szenario 2: Es standen zwei Packungen Kaffee auf der Liste,
im Laden gab es nur eine.

Mit dem Schema aus §3 lässt sich das innerhalb derselben Liste nicht umsetzen. Der partielle
Unique-Index

```sql
CREATE UNIQUE INDEX ux_shopping_list_lines_active
    ON shopping_list_lines (list_id, item_id)
    WHERE dropped_at IS NULL;
```

erlaubt je Liste höchstens **eine nicht verworfene** Position pro Artikel. Eine *abgehakte*
Position hat `dropped_at IS NULL` und zählt damit mit. Ein Abgleich, der für den teilweise
gekauften Artikel eine zweite Position anfügt, läuft also in einen `sqlite3.IntegrityError` —
und damit in eine 500er-Seite mitten im Ablauf, den M4 flüssig machen soll.

Die Regel und das Schema widersprechen sich; eines von beiden muss nachgeben.

## Entscheidung

**Das Schema bleibt, die Regel wird präzisiert.** Der Abgleich fügt eine Position nur für Artikel
an, die in der offenen Liste **keine nicht verworfene** Position haben — eine abgehakte Position
blockiert das Anfügen.

Fachlich heißt das: Ein teilweise gekaufter Artikel fällt sofort zurück auf **NACHKAUFEN** (das
gilt unverändert, der Bestand entscheidet), bekommt seine Restposition aber erst mit der
**nächsten** Liste, also beim ersten Abgleich nach „Einkauf abschließen“. Sichtbar ist der Bedarf
die ganze Zeit — auf dem Board, in der Spalte Nachkaufen.

## Alternativen

- **Den Index verengen** auf „nicht verworfen **und** nicht abgehakt“. Dann könnte eine offene
  Restposition sofort in derselben Liste entstehen. Verworfen: Das ist eine Migration an einem
  Index, die schwerer umkehrbar ist als eine Regelpräzisierung, und sie schwächt genau den Schutz,
  für den der Index da ist — ein Artikel könnte dann mit einer abgehakten *und* einer offenen
  Position gleichzeitig in derselben Liste stehen. Im Laden auf dem iPhone ist das verwirrend:
  „Kaffee“ stünde zweimal untereinander, einmal durchgestrichen, einmal nicht.
- **Die abgehakte Position wiederverwenden** (`checked_at` leeren, `suggested_qty` auf den Rest
  setzen). Ohne Migration möglich, verletzt aber §6 („Abgehakte Positionen bleiben unverändert
  stehen“): Die Liste änderte sich unter der Hand, bereits Gekauftes wirkte wieder offen, und die
  Zuordnung zwischen `restock`-Bewegung und Position (`movements.line_id`) würde mehrdeutig.

## Konsequenzen

**Leichter:** Keine Schemaänderung in M4, keine Migration, kein Rückweg zu beschreiben. Der
Abgleich bleibt eine reine Funktion über den aktuellen Zustand (`app/domain/shopping.py`), ohne
Sonderfall für Teilkäufe. Die Liste im Laden bleibt eindeutig: ein Artikel, eine Zeile.

**Schwerer:** Wer denselben Artikel im selben Einkauf zweimal besorgen will, bekommt dafür keine
zweite Zeile. Praktisch fällt das kaum ins Gewicht — wer merkt, dass eine Packung zu wenig im
Wagen liegt, korrigiert beim Abhaken die Menge, statt eine zweite Zeile zu erwarten.

**Neu bewertet würde die Entscheidung**, wenn sich im Alltag zeigt, dass Teilkäufe häufig sind
*und* zwischen zwei Listen mehrere Tage vergehen — dann würde der Rest zu lange unsichtbar in
„Nachkaufen“ liegen, und die Index-Alternative wäre den Migrationsschritt wert. Der frühe
Echtbetrieb ab M3 liefert dazu die Daten.
