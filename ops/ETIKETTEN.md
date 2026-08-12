# Etiketten — Format, Größe und Scanbarkeit

Kurznotiz aus M5 (docs/PLAN.md §9, Artefakte). Das Betriebshandbuch `BETRIEB.md` entsteht erst in
M6; hier steht nur, was vor dem ersten Etikettendruck bekannt sein muss.

## Was in den Codes steckt

Jeder QR-Code enthält **ausschließlich** die Entnahme-URL des Artikels:

```
http://homekanban.local:8181/e/<qr_token>
```

- `http://homekanban.local:8181` ist `HOMEKANBAN_BASE_URL` (docs/PLAN.md §8).
- `<qr_token>` sind 22 Zeichen aus `secrets.token_urlsafe(16)`, stabil über die gesamte Lebensdauer
  des Artikels — eine Umbenennung ändert ihn **nicht** (R9).
- Gesamtlänge 53 Zeichen → **QR-Version 4, 33 × 33 Module**, Fehlerkorrektur **M** (15 %).

> docs/PLAN.md §5 ging ursprünglich von Version 3 aus. Das ist zu optimistisch: Version 3 fasst bei
> Stufe M nur 42 Byte, die URL braucht 53. Für Version 3 müsste `HOMEKANBAN_BASE_URL` auf
> höchstens 17 Zeichen schrumpfen (z. B. `http://pi.local` ohne Port). Praktisch bedeutet
> Version 4 gegenüber 3 nur rund 12 % kleinere Module bei gleicher Etikettengröße.

## Eine Änderung der BASE_URL macht alle Etiketten wertlos

**Das ist Risiko R6 und der Grund für diese Notiz.** Ändert sich `HOMEKANBAN_BASE_URL` — anderer
Hostname, anderer Port, später ein Reverse Proxy mit Pfadpräfix —, zeigen **sämtliche geklebten
Codes ins Nichts**. Es gibt keine Migration dafür: Jedes Etikett müsste neu gedruckt und neu
geklebt werden.

Daraus folgt für den Betrieb:

- `HOMEKANBAN_BASE_URL` **nicht ohne Neudruck ändern.** Gehört so auch in `BETRIEB.md` (M6).
- Der mDNS-Name `homekanban.local` muss auf dem Pi eingerichtet sein (Avahi-Alias oder
  CNAME) — mit dem Nutzer in M5 bewusst statt `raspberrypi.local` gewählt, damit die Etiketten
  auch eine Umbenennung oder einen Hardwaretausch des Pi überleben.
- **Offen bis M6:** Ob Port `8181` auf dem Pi frei ist, ist bis heute Annahme A1. Vor dem ersten
  Etikettendruck einmal `ss -ltnp` auf dem Pi ausführen und bestätigen, dass „Hängt!“ den Port
  nicht belegt. Wird ein anderer Port nötig, muss er **vor** dem Druck feststehen.

## Etikettengröße und Scanreichweite

Die Definition of Done verlangt: vom geklebten Etikett aus **20 cm** scanbar. Faustregel für
Handykameras: erreichbarer Scanabstand ≈ 10 × Kantenlänge des Codes (ohne Ruhezone).

Mit Version 4 (33 Module) ergibt das für die angebotenen Raster:

| Raster | je Bogen | QR-Fläche ca. | Modulkante ca. | Scanabstand ca. | Urteil |
| --- | --- | --- | --- | --- | --- |
| 70 × 37 mm | 24 | 30 mm | 0,81 mm | ~30 cm | komfortabel |
| 63,5 × 38,1 mm | 21 | 31 mm | 0,84 mm | ~31 cm | komfortabel |
| 48,5 × 25,4 mm | 40 | 21 mm | 0,57 mm | ~20 cm | erfüllt die Vorgabe knapp |

**Untergrenze:** Unter etwa 22 mm QR-Kantenlänge wird die 20-cm-Vorgabe unsicher — besonders bei
schlechtem Licht im Vorratsschrank, mit älteren Handykameras oder bei Tintenstrahldruck auf
saugendem Papier. Ein 25-mm-Etikett ist damit die praktische Untergrenze, und auch nur, wenn der
QR-Code fast die ganze Fläche einnimmt.

Alle Zahlen sind gerechnet, **nicht gemessen** — siehe unten.

## Auf dem Etikett steht

QR-Code und Artikelname, sonst nichts. Mit dem Nutzer in M5 so entschieden: Der Klartextname bleibt,
weil ein Etikett ohne ihn im Schrank nicht zuzuordnen ist, wenn es sich löst (R9); die abtippbare
URL wurde bewusst weggelassen, weil sie auf kleinen Rastern nur auf Kosten der QR-Fläche stehen
würde. Der kopierbare Link bleibt stattdessen auf der Artikel-Detailseite in der App.

## Vor dem ersten Druck

1. Port prüfen (`ss -ltnp`) und `HOMEKANBAN_BASE_URL` in `.env` endgültig setzen.
2. `/etiketten/kalibrierung` aufrufen, ausdrucken, die 100-mm-Strecke mit dem Lineal messen.
   Weicht sie ab: Skalierung im Druckdialog auf 100 %, „An Seite anpassen“ aus, A4 statt Letter.
3. Erst danach `/etiketten` → Auswahl → Bogen drucken.
4. Probedruck auf Normalpapier über den Etikettenbogen halten und gegen das Licht prüfen, ob die
   Kästen auf der Stanzung liegen.

## Was noch ungeprüft ist

Nichts davon wurde auf Papier verifiziert — es gibt in der Entwicklungsumgebung weder Drucker noch
Kamera. Ungeprüft sind: Maßhaltigkeit des Browserdrucks auf echtem Papier, Verhalten des
Druckertreibers und seiner Skalierung, Lesbarkeit der gedruckten Codes aus 20 cm, Lesbarkeit bei
schlechtem Licht. Erweist sich der Browserdruck als nicht maßhaltig, ist ReportLab die in
ADR 0004 vorgemerkte Rückfallposition — dann wäre ADR 0004 zu **ersetzen**, nicht zu ergänzen.
