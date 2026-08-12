# Der Apple-Kurzbefehl: Einkaufsliste in Apple Notes

Diese Anleitung baut den Kurzbefehl von Grund auf. Sie setzt kein Vorwissen über die App
„Kurzbefehle“ voraus — jeder Schritt steht so da, wie er auf dem iPhone erscheint.

**Was am Ende passiert:** Du tippst vor dem Losfahren auf den Kurzbefehl. Das iPhone fragt den
Pi nach der Einkaufsliste, der Pi gleicht sie ab und antwortet mit einer Zeile pro Artikel. Die
Zeilen landen in einer festen Notiz „Einkauf“ — im Laden hakst du dort ab, offline, ohne WLAN
und ohne die App. Zu Hause öffnest du `/liste` und tippst „Alles gekauft“.

> **Wichtig:** Das Abhaken in der Notiz bucht **nichts**. Die Notiz ist die Ansicht im Laden, die
> App ist die Buchung. Wer das trennt, spart sich doppelte Arbeit — siehe Risiko R2 in
> `PLAN.md` §10.

---

## 1. Vorbereitung auf dem Pi

### Den API-Schlüssel setzen

Der Export ist der einzige Endpunkt der App mit Authentifizierung (Leitentscheidung L12). Ohne
gesetzten Schlüssel verweigert er den Dienst mit `503` und schreibt den Grund ins Log.

In der Datei `.env` neben `compose.yaml` (die Datei liegt **nicht** im Git, siehe CLAUDE.md §4):

```
HOMEKANBAN_API_KEY=hier-einen-langen-zufaelligen-wert-eintragen
```

Einen brauchbaren Wert erzeugt auf dem Pi zum Beispiel:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

Danach den Container neu starten, damit er die Variable liest:

```bash
docker compose up -d
```

Der Schlüssel ist kein Passwort im eigentlichen Sinn — die App ist ohnehin nur im Heimnetz
erreichbar. Er verhindert, dass ein anderes Gerät im Netz versehentlich einen Export auslöst.

### Die Basis-URL kennen

Alles unten verwendet als Beispiel `http://raspberrypi.local:8181`. Setze stattdessen den Wert
ein, der bei dir in `HOMEKANBAN_BASE_URL` steht. Ob der Pi erreichbar ist, prüfst du am
schnellsten im Safari auf dem iPhone: `http://raspberrypi.local:8181/` muss das Board zeigen.

### Den Aufruf einmal testen

Bevor du den Kurzbefehl baust, prüfe die Schnittstelle vom Rechner aus:

```bash
curl -X POST "http://raspberrypi.local:8181/api/shopping-list/export" \
     -H "X-API-Key: DEIN-SCHLUESSEL"
```

Erwartete Antwort — eine Zeile je Artikel, ohne Laden-/Kategoriepflege wie hier:

```
Spülmaschinentabs — 1 Packung
Klopapier — 10 Rollen
Kaffee — 2 Packungen
```

**Seit M7 (Kategorien & Läden):** Sind Artikeln Läden zugeordnet, gruppiert der Server die Antwort
danach — mit dem Ladennamen als eigener Zeile davor:

```
REWE
Klopapier — 10 Rollen
Aldi
Kaffee — 2 Packungen
Sonstiges
Spülmaschinentabs — 1 Packung
```

**Wichtig:** Der nächste Schritt (Abschnitt 3, „Text teilen“) kennt keine Überschriften — er teilt
stur an Zeilenumbrüchen. Jede Ladenzeile wird dadurch selbst zu einem Häkchen in der Notiz, das
nichts zum Abhaken hat außer sich selbst. Das ist bewusst so entschieden (siehe `docs/PLAN.md`,
M7-Fragerunde, Frage 2): Die sichtbare Struktur im Laden — „ich bin jetzt bei REWE“ — wiegt
schwerer als der eine überflüssige Punkt je Gruppe. Ist keinem einzigen Artikel im Haushalt ein
Laden zugeordnet, bleibt die Antwort wie im ersten Beispiel ohne jede Überschrift.

Ist gerade nichts zu kaufen, ist die Antwort **leer**. Das ist richtig so und kein Fehler.

| Antwort | Bedeutung |
| --- | --- |
| `401` | Schlüssel fehlt oder ist falsch |
| `503` | Auf dem Server ist `HOMEKANBAN_API_KEY` nicht gesetzt |
| leer, `200` | Es gibt gerade nichts zu kaufen |

---

## 2. Die Vorlagennotiz anlegen

Das ist der Schritt, an dem der ganze Ablauf hängt — und zugleich der einzige, den Apple nicht
offiziell unterstützt (Risiko R1). Shortcuts hat **keine** Aktion „Notiz als Checkliste
erzeugen“. Der gangbare Weg: Eine Notiz, deren **letzter Block bereits eine Checkliste ist**.
Angehängte Zeilen führen diese Checkliste fort und werden dadurch selbst zu Häkchen.

1. Notizen öffnen, neue Notiz anlegen.
2. In die erste Zeile den Titel schreiben: **Einkauf**
3. Eine Zeile darunter gehen.
4. Über das Format-Symbol (**Aa**) **Checkliste** einschalten.
5. Einen Platzhalterpunkt eintippen, zum Beispiel `—` oder `Liste folgt`.
   Der Punkt muss stehen bleiben: Eine leere Checkliste am Ende erkennt Notes nicht zuverlässig
   als Checkliste.
6. Notiz schließen. Sie muss dauerhaft existieren — **nicht** nach jedem Einkauf löschen.

Die Notiz sieht dann so aus:

```
Einkauf
☐ Liste folgt
```

---

## 3. Den Kurzbefehl bauen

Kurzbefehle öffnen → **+** → dem Kurzbefehl den Namen **Einkaufsliste holen** geben.
Dann diese vier Aktionen in dieser Reihenfolge hinzufügen:

### Aktion 1 — „URL“

Suche nach **URL** und trage ein:

```
http://raspberrypi.local:8181/api/shopping-list/export
```

### Aktion 2 — „Inhalte von URL abrufen“

Suche nach **Inhalte von URL abrufen**. Sie greift automatisch die URL von oben auf.
Tippe auf **Pfeil ▸**, um die Details aufzuklappen, und stelle ein:

- **Methode:** `POST`
  Das ist kein Formalismus: Der Aufruf löst den Abgleich aus und wird protokolliert
  (`exported_at`, `export_count`). Ein `GET` mit Nebenwirkung wäre genau der Fehler, den der
  QR-Flow der App bewusst vermeidet.
- **Header:** auf **Neuer Header** tippen
  - Schlüssel: `X-API-Key`
  - Wert: dein Schlüssel aus `.env`
- **Anfragetext:** `Datei` beziehungsweise leer lassen — es wird nichts gesendet.

> Wenn dir das Eintragen des Headers zu fummelig ist, geht auch der Schlüssel in der URL:
> `…/api/shopping-list/export?key=DEIN-SCHLUESSEL`. Dann entfällt Aktion 2s Header komplett.
> Beides ist gleichwertig; im Heimnetz ohne HTTPS macht es keinen Unterschied.

### Aktion 3 — „Text teilen“

Suche nach **Text teilen**.

- Eingabe: das Ergebnis von „Inhalte von URL abrufen“ (setzt Kurzbefehle selbst ein)
- **Trennzeichen:** `Neue Zeilen`

Damit wird aus dem Textblock eine Liste einzelner Zeilen.

### Aktion 4 — „An Notiz anhängen“

Suche nach **An Notiz anhängen**.

- Text: das Ergebnis von „Text teilen“
- Notiz: **Einkauf** auswählen (die Notiz aus Schritt 2)

Fertig. Kurzbefehl sichern.

### Auf den Home-Bildschirm legen

Im Kurzbefehl oben auf **ⓘ** → **Zum Home-Bildschirm hinzufügen**. Dann ist der Weg von
„losfahren“ bis „Liste steht“ ein einziger Tap.

---

## 4. Der Ablauf im Alltag

1. **Vor dem Losfahren:** Kurzbefehl tippen. Notizen öffnen, Notiz „Einkauf“ — die Punkte
   stehen da.
2. **Im Laden:** abhaken. Braucht kein Netz und keine App.
3. **Zu Hause:** `http://raspberrypi.local:8181/liste` öffnen.
   - Alles bekommen → **„Alles gekauft“**. Ein Tap, alle Bestände stehen auf ihrem Sollbestand.
   - Etwas nicht oder anders bekommen → bei der Position **„Andere Menge“** eintragen und
     **„Buchen“**. Der Bestand steigt um genau diese Menge; liegt er danach immer noch unter dem
     Mindestbestand, steht der Artikel sofort wieder im Nachkaufen und ist bei der nächsten Liste
     wieder dabei.
   - Etwas gar nicht bekommen → Position einfach offen lassen.
4. **Zum Schluss:** **„Einkauf abschließen“**. Alles, was offen geblieben ist, wandert zurück ins
   Nachkaufen; die Liste ist erledigt und schleppt sich nicht über Wochen.
5. **Die Notiz aufräumen:** Die abgehakten Punkte in „Einkauf“ löschen, den Platzhalterpunkt
   stehen lassen. Sonst wächst die Notiz mit jedem Einkauf.

---

## 5. Wenn die Checkliste nicht klappt

Das Verhalten von Notes ist von Apple nicht zugesichert und kann sich mit einer iOS-Version
ändern. Kommt der Text als Fließtext statt als Häkchen an, gibt es zwei erprobte Rückwege
(Risiko R1 in `PLAN.md` §10).

### Rückfall 1 — einmal manuell formatieren

Nach dem Anhängen in der Notiz die neuen Zeilen markieren, **Aa** antippen, **Checkliste**
wählen. Ein Tap pro Einkauf, kein Datenverlust, keine Änderung am Kurzbefehl. Das ist der
pragmatische Weg, wenn das automatische Fortführen der Checkliste bei dir nicht greift.

Prüfe vorher trotzdem die Vorlagennotiz: Der häufigste Grund ist, dass der **letzte** Block der
Notiz keine Checkliste (mehr) ist — etwa weil der Platzhalterpunkt gelöscht wurde oder unter der
Checkliste noch eine normale Textzeile steht.

### Rückfall 2 — Apple Erinnerungen statt Notizen

In Erinnerungen sind Häkchen offiziell unterstützt; es gibt keinen Formatierungstrick und nichts,
was mit einer iOS-Version kippen kann. Der Kurzbefehl ist derselbe, nur die letzte Aktion wird
getauscht:

- Aktion 4 durch **Erinnerung hinzufügen** ersetzen
- Liste: eine eigene Liste **Einkauf** anlegen
- Titel: das Ergebnis von „Text teilen“

Kurzbefehle wiederholt die Aktion dann automatisch für jede Zeile und legt eine Erinnerung pro
Artikel an. Nachteil gegenüber Notizen: Erledigte Erinnerungen verschwinden, statt zum Aufräumen
stehen zu bleiben — dafür ist das Abhaken selbst zuverlässiger.

---

## 6. Fehlersuche

| Symptom | Ursache und Abhilfe |
| --- | --- |
| Kurzbefehl meldet einen Fehler mit `401` | Schlüssel falsch geschrieben, oder der Header heißt nicht exakt `X-API-Key`. |
| Kurzbefehl meldet `503` | Auf dem Pi fehlt `HOMEKANBAN_API_KEY` in `.env`, oder der Container wurde danach nicht neu gestartet. |
| Kurzbefehl hängt oder meldet „nicht erreichbar“ | Das iPhone ist nicht im Heimnetz (Mobilfunk statt WLAN), oder der `.local`-Name wird nicht aufgelöst. Zum Prüfen die URL im Safari öffnen. |
| Es wird ein leerer Punkt angehängt | Sollte nicht vorkommen: Die Antwort endet bewusst ohne Zeilenumbruch. Tritt es trotzdem auf, in „Text teilen“ prüfen, ob wirklich `Neue Zeilen` als Trennzeichen eingestellt ist. |
| Es passiert gar nichts, die Notiz bleibt leer | Es gab nichts zu kaufen — die Antwort war leer. Auf dem Board prüfen, ob überhaupt ein Artikel in „Nachkaufen“ steht. |
| Ein Artikel fehlt, obwohl er leer ist | Sein Bestand liegt noch **über** dem Mindestbestand. Entweder wurde eine Entnahme nicht gescannt (dann auf der Artikelseite „Bestand korrigieren“) oder der Mindestbestand ist zu niedrig gesetzt. |
| Ein Artikel steht doppelt in der Notiz | Die Notiz wurde zweimal befüllt, ohne dazwischen aufzuräumen. Die App erzeugt keine zweite Liste — ein zweiter Export gleicht dieselbe Liste ab. Alte Punkte in der Notiz löschen. |

---

## 7. Was noch offen ist

Dieser Ablauf ist auf dem Entwicklungsrechner **nicht** überprüfbar: Weder das Verhalten von
Apple Notes noch der Kurzbefehl selbst lassen sich von einer Testsuite abdecken (`PLAN.md` §6
sagt das ausdrücklich). Der eine Punkt der Definition of Done von M4, der offen bleibt, ist
deshalb:

> Der Kurzbefehl ist auf dem iPhone durchgeführt und die Notiz enthält abhakbare Punkte.

Bitte einmal durchspielen und notieren, welcher der drei Wege bei dir funktioniert hat:
das automatische Fortführen der Checkliste, Rückfall 1 oder Rückfall 2. Danach kann die Anleitung
auf den tatsächlich funktionierenden Weg eingekürzt werden.

**Seit M7 zusätzlich offen:** Ob die Ladenüberschrift als eigener, harmloser Punkt in der Notiz
ankommt — wie in Abschnitt 1 beschrieben — und ob sich das im Alltag beim Abhaken im Laden als
störend erweist, ist ebenfalls nicht lokal prüfbar und wartet auf denselben ersten Durchlauf auf
dem iPhone.
