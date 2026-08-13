# Betriebshandbuch — Deployment auf dem Raspberry Pi

Dieses Handbuch führt dich **in einem Durchlauf** vom unberührten Pi bis zur abgenommenen,
benutzten Installation — inklusive der Nachholpunkte aus M4 (Kurzbefehl), M5 (Etikettendruck,
Messung, Scanprobe), M7 (gruppierter Export) und M9 (Cron, Off-Pi-Kopie, Restore mit Container).
M6 selbst (docs/PLAN.md §9) besteht fast nur aus Härtung, die schon erledigt ist — der eigentliche
Meilenstein ist dieser Durchlauf.

**Reihenfolge ist keine Empfehlung, sondern eine Abhängigkeitskette:** Der Portnachweis (Phase 1)
und die endgültige `BASE_URL` müssen **vor** dem Etikettendruck (Phase 7) feststehen — jede
Änderung danach bedeutet Neudruck aller Etiketten (R6). Artikel müssen angelegt sein (Phase 6),
bevor Etiketten gedruckt werden können (Phase 7). Etiketten müssen kleben, bevor der
Scan-Alltagstest (Phase 8) Sinn ergibt. Es braucht echte Buchungen, bevor der Kurzbefehl (Phase 9)
etwas Sinnvolles exportiert. Bitte die Phasen **der Reihe nach** abarbeiten, nicht vorgreifen.

Verwendete Beispielwerte in diesem Dokument: Pi-Adresse `192.168.0.15` (README.md), Repo-Pfad
`/home/pi/HomeKanban`, Compose-Projektverzeichnis `/home/pi/HomeKanban/ops`. Ersetze sie, wo sie
bei dir abweichen.

**Abkürzung für Phase 0–3:** `sh ops/preflight.sh` fragt die maschinell prüfbaren Teile (Docker
vorhanden, Port frei, `.env` vollständig, `homekanban.local` auflösbar) in einem Lauf ab und
berichtet deutsch. Ersetzt die Phasen unten nicht, spart aber das Abtippen der einzelnen Befehle.

---

## Phase 0 — Vorbedingungen auf dem Pi

**0.1 Docker und das Compose-Plugin installieren** (falls noch nicht vorhanden):

```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

Danach ab- und wieder anmelden (oder `newgrp docker`), damit die Gruppenmitgliedschaft greift.
**Erwartetes Ergebnis:**

```sh
docker --version          # Docker version 2x.x.x, ...
docker compose version    # Docker Compose version v2.x.x
```

**Wenn nicht:** `docker compose version` meldet „unknown command“ → `sudo apt-get update && sudo
apt-get install -y docker-compose-plugin` (get.docker.com bringt das Plugin normalerweise schon
mit; auf manchen älteren Raspberry Pi OS-Images fehlt es einzeln).

**0.2 Repository klonen/aktualisieren:**

```sh
git clone <repo-url> /home/pi/HomeKanban
cd /home/pi/HomeKanban
git checkout main   # oder der vom Nutzer vorgegebene Branch
```

**Erwartetes Ergebnis:** `git status` zeigt „nothing to commit, working tree clean“ auf dem
gewünschten Branch.

**0.3 Eigentümerschaft eines bereits bestehenden `/data`-Volumes prüfen.** Ein **frisches**
benanntes Volume übernimmt beim ersten Mount Eigentümer und Rechte von `/data` aus dem Image
(`homekanban:homekanban`, feste UID/GID 1000, siehe `ops/Dockerfile`). Lief hier schon einmal ein
**ungehärteter** Container (vor M6, als der Prozess noch als `root` lief), gehört das bestehende
Volume weiterhin `root` — der neue, nicht-root laufende Prozess kann dann nicht mehr schreiben und
der Start scheitert mit einem Berechtigungsfehler in den Logs.

**Test, ob das zutrifft** (nur relevant, falls vorher schon einmal `docker compose up` in diesem
Repo lief):

```sh
docker run --rm -v homekanban-data:/data alpine stat -c '%U:%G' /data
```

**Erwartetes Ergebnis:** `1000:1000` (oder „kein Volume vorhanden“ — dann ist es ohnehin ein
frischer Start, weiter mit Phase 1). **Wenn `root:root` oder etwas anderes:**

```sh
docker run --rm -v homekanban-data:/data alpine chown -R 1000:1000 /data
```

Einmalig, danach ist das Volume dauerhaft korrekt — das ist kein Schritt, der bei jedem Update
wiederholt werden muss.

---

## Phase 1 — Portnachweis (A1) und `BASE_URL` endgültig festzurren

**Muss vor jedem Etikettendruck erledigt sein — siehe Warnung oben.**

```sh
ss -ltnp
```

**Erwartetes Ergebnis:** Eine Liste lauschender Ports. Prüfe, ob `8181` (der Vorgabewert aus
`docs/PLAN.md` §8) in der `Local Address:Port`-Spalte auftaucht.

**Wenn `8181` frei ist:** `HOMEKANBAN_PORT=8181` bleibt wie vorgegeben, `HOMEKANBAN_BASE_URL` bleibt
`http://homekanban.local:8181` (M5, R6). Weiter mit Phase 2.

**Wenn `8181` belegt ist** (z. B. von „Hängt!“, R4): einen freien Port wählen (`ss -ltnp` erneut
mit einer Testzahl, oder einfach eine unauffällige vierstellige Zahl wie `8182` probieren) und **an
beiden folgenden Stellen konsistent eintragen, bevor irgendetwas gedruckt wird**:

1. `HOMEKANBAN_PORT=<neuer-port>` in `.env` (Phase 3).
2. `HOMEKANBAN_BASE_URL=http://homekanban.local:<neuer-port>` in `.env` (Phase 3) — der Port steckt
   in der URL, die zum QR-Code wird.

Der interne Container-Port bleibt `8181` (`ops/Dockerfile` `EXPOSE`/`CMD`) — nur die linke Seite
der Portzuordnung in `ops/compose.yaml` (`"${HOMEKANBAN_PORT:-8181}:8181"`) ändert sich, und das
automatisch über `HOMEKANBAN_PORT`.

**Notiere dir jetzt den entgültigen Port und die BASE_URL** — sie werden weiter unten mehrfach
gebraucht und stehen am Ende dieses Dokuments im Ergebnis-Abschnitt.

---

## Phase 2 — mDNS-Alias `homekanban.local` (Avahi)

`homekanban.local` ist bewusst ein **eigener** Name, nicht `raspberrypi.local` (M5) — er übersteht
eine Umbenennung oder einen Hardwaretausch des Pi, solange der Alias mitwandert.

**2.1 Avahi prüfen/installieren:**

```sh
systemctl is-active avahi-daemon
```

**Wenn nicht `active`:** `sudo apt-get install -y avahi-daemon && sudo systemctl enable --now
avahi-daemon`.

**2.2 Alias als eigenen systemd-Dienst einrichten** (überlebt Neustarts, unabhängig vom
HomeKanban-Container):

```sh
sudo tee /etc/systemd/system/homekanban-mdns.service > /dev/null <<'EOF'
[Unit]
Description=Avahi-Alias homekanban.local fuer HomeKanban
After=avahi-daemon.service
Requires=avahi-daemon.service

[Service]
ExecStart=/usr/bin/avahi-publish -a -R homekanban.local 192.168.0.15
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

**Ersetze `192.168.0.15` durch die tatsächliche, feste Adresse deines Pi**, falls abweichend
(README.md nennt `192.168.0.15` als aktuelle Adresse). Eine Adresse, die der Router nicht per
DHCP-Reservierung fest vergibt, macht diesen Alias bei der nächsten Adressvergabe falsch — eine
DHCP-Reservierung im Router ist deshalb empfehlenswert, unabhängig von HomeKanban.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now homekanban-mdns.service
systemctl status homekanban-mdns.service --no-pager
```

**Erwartetes Ergebnis:** `active (running)`.

**2.3 Test von einem zweiten Gerät** (Handy im selben WLAN, **nicht** dem Pi selbst — mDNS testet
man nicht auf der eigenen Maschine):

```sh
ping homekanban.local
```

oder im Handy-Browser `http://homekanban.local` öffnen (noch ohne Port — an dieser Stelle ist noch
kein Container gestartet, ein Verbindungsfehler *nach* der Namensauflösung ist hier normal und kein
Problem; ein Fehler **„Host nicht gefunden“/„kann Server nicht finden“** wäre das eigentliche
Warnsignal).

**Wenn nicht:** Firewall auf dem Pi prüfen (`sudo ufw status`, falls aktiv — mDNS braucht UDP 5353
offen), und ob das Handy im selben WLAN/Subnetz hängt wie der Pi (mDNS routet nicht über
Subnetzgrenzen).

---

## Phase 3 — `.env` anlegen samt API-Key-Erzeugung

```sh
cd /home/pi/HomeKanban
cp .env.example .env
```

Öffne `.env` und trage ein:

- `HOMEKANBAN_PORT` und `HOMEKANBAN_BASE_URL` — die in Phase 1 notierten, endgültigen Werte.
- `HOMEKANBAN_API_KEY` — erzeugen mit:

  ```sh
  python3 -c "import secrets; print(secrets.token_urlsafe(24))"
  ```

  Den ausgegebenen Wert einfügen. Ohne diesen Wert antwortet der Kurzbefehl-Export später mit
  `503` (§8) — er wird für Phase 9 gebraucht.
- Restliche Werte (`HOMEKANBAN_DB_PATH`, `HOMEKANBAN_UNDO_WINDOW_MINUTES`, `HOMEKANBAN_LEAD_DAYS`,
  `HOMEKANBAN_BACKUP_DIR`, `HOMEKANBAN_BACKUP_KEEP`, `TZ`, `LOG_LEVEL`) können auf den Vorgaben aus
  `.env.example` bleiben, sofern keine besonderen Gründe dagegensprechen.

**Erwartetes Ergebnis:**

```sh
grep -c '^HOMEKANBAN_API_KEY=.\+' .env   # 1 — der Schlüssel ist nicht leer
```

**Wenn nicht:** `.env` erneut öffnen, die Zeile `HOMEKANBAN_API_KEY=` muss einen Wert **nach** dem
Gleichheitszeichen tragen, ohne Leerzeichen und ohne Anführungszeichen.

---

## Phase 4 — Erster Start

```sh
cd /home/pi/HomeKanban/ops
docker compose --env-file ../.env up -d --build
```

**Denk an `--env-file ../.env` — ohne dieses Flag löst Compose `${HOMEKANBAN_PORT:-8181}` in
`ops/compose.yaml` nicht aus deiner `.env` auf, sondern fällt still auf `8181` zurück** (siehe
Kommentar in `ops/compose.yaml`). Wie lange der erste Build braucht (und ob dabei etwas kompiliert
statt ein fertiges Wheel zu laden — A3, `uvicorn[standard]`), gehört in den Ergebnis-Abschnitt am
Ende dieses Dokuments.

**Prüfschritt Build-Dauer:** Läuft der erste Build länger als etwa 5 Minuten oder erscheinen Zeilen
wie `Building wheel for uvloop` / `Building wheel for httptools`, wird auf dem Pi kompiliert statt
ein fertiges `aarch64`-Wheel geladen (Annahme A3 wäre für dieses Paket nicht bestätigt). Das ist
kein Fehler, nur langsam. **Dokumentierter Rückweg**, falls das stört: In `pyproject.toml`
`"uvicorn[standard]>=0.32"` zu `"uvicorn>=0.32"` ändern (schlankes uvicorn ohne `uvloop`/
`httptools`/`watchfiles`, alles reines Python) und neu bauen. Das ist eine bewusste, im Repo zu
dokumentierende Abweichung, kein automatischer Fallback — nur bei tatsächlichem Bedarf ändern.

**4.1 `/healthz` vom Pi selbst:**

```sh
curl -s http://localhost:${HOMEKANBAN_PORT:-8181}/healthz
```

(oder die tatsächlich in Phase 1 gewählte Portnummer direkt einsetzen). **Erwartetes Ergebnis:**
`{"status":"ok"}`.

**Wenn nicht:** `docker compose --env-file ../.env logs homekanban --tail=50` ansehen. Ein
`503` mit Invarianten-Fehler ist auf einer frischen Datenbank ausgeschlossen (noch keine Artikel);
ein Verbindungsfehler bedeutet meist, dass der Container gar nicht läuft — `docker compose
--env-file ../.env ps` prüfen.

**4.2 `/healthz` vom Handy** (im selben WLAN): `http://homekanban.local:<port>/healthz` im
Browser öffnen. **Erwartetes Ergebnis:** dieselbe JSON-Antwort wie oben, dieses Mal über den
mDNS-Namen erreicht — bestätigt Phase 2 und Phase 4 zusammen.

**4.3 „Hängt!“ unbeeinträchtigt (R4):**

```sh
docker ps
```

**Erwartetes Ergebnis:** Sowohl der `homekanban`- als auch der „Hängt!“-Container laufen
(`Up ...`), unter unterschiedlichen Portzuordnungen. Öffne zusätzlich die gewohnte
„Hängt!“-Adresse im Browser — sie muss wie vorher funktionieren.

**Wenn nicht:** Portkollision trotz Phase 1 (zwei Dienste auf demselben Host-Port sind in Compose
gar nicht erst startbar — dann hätte schon 4.1 einen Fehler gezeigt) oder ein Ressourcenengpass
(`docker stats` auf Speicher-/CPU-Auslastung prüfen).

---

## Phase 5 — Autostart nach Neustart

```sh
sudo reboot
```

Nach dem Wiederhochfahren (ohne selbst etwas zu starten):

```sh
curl -s http://localhost:${HOMEKANBAN_PORT:-8181}/healthz
```

**Erwartetes Ergebnis:** `{"status":"ok"}`, **ohne** dass du `docker compose up` erneut ausgeführt
hast. Das prüft zwei Dinge gleichzeitig: `restart: unless-stopped` in `ops/compose.yaml` (der
Container startet mit dem Docker-Daemon neu) und dass der Docker-Daemon selbst beim Booten startet
(bei einer Installation über `get.docker.com` ist das der Standard).

**Wenn nicht:** `systemctl is-enabled docker` prüfen (`enabled` erwartet; sonst `sudo systemctl
enable docker`) und `docker compose --env-file ../.env ps` — steht der Container auf `Exited`,
war er beim letzten `docker compose stop`/`down` schon angehalten (`restart:` startet nur
Container neu, die beim Herunterfahren liefen, kein `down`-Container).

---

## Phase 6 — Echte Artikel anlegen (R8: klein anfangen)

10–15 Artikel plus die dazugehörigen Kategorien/Läden über die Oberfläche anlegen
(`http://homekanban.local:<port>/artikel/neu`), **oder** alternativ per Stammdaten-Import über
`http://homekanban.local:<port>/stammdaten`, falls eine JSON/CSV-Vorbereitung existiert (M9, §7).

**Erwartetes Ergebnis:** Das Board (`/`) zeigt die angelegten Artikel in den passenden Spalten.

Kein „wenn nicht“ an dieser Stelle — das ist der Punkt, an dem der Haushalt beginnt, echte Daten
statt Beispieldaten zu benutzen (R8). `ops/seed.py` ist ausdrücklich **kein** Teil dieses Schritts.

---

## Phase 7 — Etiketten: Kalibrierung, Druck, Klebe- und Scanprobe

**Ab hier ist `BASE_URL` aus Phase 1 endgültig** — jede spätere Änderung bedeutet Neudruck. Die
vollständige Anleitung mit Rastergrößen und Scanabstands-Tabelle steht in
[`ops/ETIKETTEN.md`](ETIKETTEN.md); hier nur die Reihenfolge und die Prüfschritte:

**7.1 Kalibrierseite drucken und messen:**
`http://homekanban.local:<port>/etiketten/kalibrierung` öffnen, drucken, die aufgedruckte
100-mm-Referenzstrecke mit einem Lineal nachmessen.

**Erwartetes Ergebnis:** gemessene Strecke ≈ 100 mm (±1 mm ist unauffällig).

**Wenn nicht:** Im Druckdialog Skalierung auf **100 %** setzen, „An Seite anpassen“ **aus**stellen,
Papierformat **A4** statt Letter wählen — dann erneut drucken und messen, bevor es weitergeht.

**7.2 Bogen drucken:** `/etiketten` → Artikel auswählen, Raster wählen (Voreinstellung
70 × 37 mm) → `/etiketten/druck` → drucken.

**7.3 Kleben:** Etiketten an den jeweiligen Entnahmeorten anbringen (nicht am Vorratsschrank,
siehe R3 in `docs/PLAN.md` §10).

**7.4 Scanprobe:** Mit der Handykamera aus **20 cm Entfernung** scannen, dazu einmal bei
**schlechtem Licht** (z. B. Schranktür halb geschlossen, oder abends ohne Zusatzlicht).

**Erwartetes Ergebnis:** Die Kamera erkennt den Code ohne Nachjustieren der Entfernung, öffnet die
Entnahmeseite.

**Wenn nicht:** Näher heran und den Abstand notieren, bei dem es zuverlässig funktioniert (gehört
in den Ergebnis-Abschnitt). Bei kleinen Rastern (48,5 × 25,4 mm) ist laut `ops/ETIKETTEN.md` die
20-cm-Vorgabe „knapp erfüllt“ — ein größeres Raster (70 × 37 mm) probieren, falls es nicht reicht.

---

## Phase 8 — Zwei-Tap-Buchung vom Handy am geklebten Etikett

Ein geklebtes Etikett mit dem Handy scannen, auf der Entnahmeseite „−1 entnommen“ tippen.

**Erwartetes Ergebnis:** Zwei Berührungen insgesamt (Scan bestätigen, Button drücken) bis die
Ergebnisseite mit neuem Bestand erscheint — der M3-Anspruch aus `docs/PLAN.md` §5, jetzt im
Echtbetrieb statt im Test bestätigt.

**Wenn nicht:** Mehr als zwei Taps nötig meint meist einen Zwischenschritt der Kamera-App (manche
Kamera-Apps zeigen erst eine Miniaturvorschau des Links, bevor sie ihn öffnen) — das ist ein
Verhalten der jeweiligen Kamera-App, kein Fehler von HomeKanban; in `docs/PLAN.md` A5 als Annahme
vermerkt.

---

## Phase 9 — Kurzbefehl einrichten und ausführen

Vollständige Anleitung: [`docs/KURZBEFEHL.md`](../docs/KURZBEFEHL.md). Kurz zusammengefasst:

1. `HOMEKANBAN_API_KEY` (aus Phase 3) und die endgültige `BASE_URL` (aus Phase 1) in den
   Kurzbefehl eintragen.
2. Vorlagennotiz „Einkauf“ mit Checkliste anlegen (`docs/KURZBEFEHL.md` Abschnitt 2).
3. Kurzbefehl bauen (Abschnitt 3) und einmal ausführen.

**Erwartetes Ergebnis:** Die Notiz „Einkauf“ enthält abhakbare Punkte, ein Punkt je Artikel unter
der Schwelle — plus, falls Läden zugeordnet sind (M7), eine Gruppenüberschrift je Laden als
zusätzlichen (bewusst in Kauf genommenen) Punkt.

**Wenn nicht:** `docs/KURZBEFEHL.md` Abschnitt 5 („Wenn die Checkliste nicht klappt“) mit zwei
erprobten Rückwegen (manuell einmal formatieren, oder Apple Erinnerungen statt Notizen).

**Notiere**, welcher der drei Wege bei dir funktioniert hat — das gehört in den
Ergebnis-Abschnitt und schließt R1 endgültig ab.

---

## Phase 10 — Nebenläufigkeit: zwei Geräte gleichzeitig (R7)

Zwei Handys (oder ein Handy und ein Laptop-Browser), **gleichzeitig** je eine Buchung auf zwei
**verschiedenen** Artikeln auslösen (auf „Los“ zählen und beide möglichst zeitgleich tippen —
exakte Gleichzeitigkeit ist nicht nötig, ein enges Zeitfenster reicht).

**Erwartetes Ergebnis:** Beide Buchungen gelingen, keine `database is locked`-Fehlerseite, keine
500er-Seite. Seit ADR 0008 (siehe unten) öffnet jede Anfrage ihre eigene Datenbankverbindung statt
sich eine zu teilen — der lokale Nachweis dafür ist `tests/web/test_scan.py::
TestConcurrentDoubleTap`, hier am echten Pi mit echten Geräten zu bestätigen.

**Wenn nicht:** `docker compose --env-file ../.env logs homekanban --tail=100` nach
`sqlite3.OperationalError`/`InterfaceError` durchsuchen und mit dem im PR-Bericht genannten
Testlauf (30 von 30 lokalen Läufen grün) abgleichen — ein Fehler hier trotz grüner Tests wäre ein
neuer Befund, kein bekannter.

---

## Phase 11 — Backup-Cron, Backup auslösen, Off-Pi-Kopie

Vollständiger Weg: [`ops/BACKUP.md`](BACKUP.md). Kurzfassung für diesen Durchlauf:

**11.1 Cron-Eintrag einrichten** (`crontab -e`, siehe `ops/BACKUP.md` Abschnitt „Der Cron-Lauf —
im Container“):

```cron
10 3 * * * cd /home/pi/HomeKanban/ops && docker compose --env-file ../.env exec -T homekanban \
  python ops/backup.py --db-path /data/homekanban.db --backup-dir /data/backups
```

**11.2 Backup einmal von Hand auslösen** (nicht auf 3:10 Uhr warten):

```sh
cd /home/pi/HomeKanban/ops
docker compose --env-file ../.env exec -T homekanban \
  python ops/backup.py --db-path /data/homekanban.db --backup-dir /data/backups
```

**Erwartetes Ergebnis:** Ausgabe `Backup geschrieben: /data/backups/<Zeitstempel>.db.gz`.

**11.3 Datei prüfen:**

```sh
docker compose --env-file ../.env exec -T homekanban ls -la /data/backups
```

**Erwartetes Ergebnis:** mindestens eine `.db.gz`-Datei mit plausibler Größe (nicht 0 Byte).

**Wenn nicht:** Exit-Code und stderr der Ausgabe aus 11.2 lesen — `ops/backup.py` meldet
Fehlschläge auf Deutsch, nie als Stacktrace (siehe `ops/BACKUP.md`).

**11.4 Off-Pi-Kopie — bewusst offener Punkt (Frage 3 der M6-Fragerunde):** Zum Zeitpunkt dieses
Durchlaufs steht noch kein Gerät im Haushalt dafür fest. Diese Kopie **fehlt deshalb noch** — R5
ist damit nur zum Teil erledigt. Sobald ein Gerät (USB-Platte, NAS, Laptop) feststeht, den Weg aus
`ops/BACKUP.md` Abschnitt „Backup-Ziel außerhalb des Pi“ einrichten. Bis dahin mindestens einmal
von Hand:

```sh
docker compose --env-file ../.env cp homekanban:/data/backups/<Dateiname>.db.gz .
```

… und die Datei auf ein zweites Gerät bringen, damit wenigstens eine Kopie außerhalb der SD-Karte
existiert.

---

## Phase 12 — Restore-Rundlauf mit Container

Der Teil, der in M9 ausdrücklich ungeprüft blieb (kein Docker in der Entwicklungsumgebung).
Vollständiger Weg: [`ops/BACKUP.md`](BACKUP.md) Abschnitt „Restore — Schritt für Schritt“.

1. `docker compose --env-file ../.env stop homekanban`
2. Bestand vor dem simulierten Ausfall notieren (Board-Ansicht oder ein Screenshot).
3. Datenbank absichtlich entfernen:
   `docker run --rm -v homekanban-data:/data alpine rm /data/homekanban.db`
   (die `-wal`/`-shm`-Dateien dürfen liegen bleiben — `ops/restore.py` legt sie beiseite).
4. Restore mit dem in Phase 11 erzeugten Backup:

   ```sh
   docker compose --env-file ../.env run --rm homekanban \
     python ops/restore.py --backup-file /data/backups/<Dateiname>.db.gz \
     --db-path /data/homekanban.db
   ```

5. `docker compose --env-file ../.env up -d`
6. `curl -s http://localhost:${HOMEKANBAN_PORT:-8181}/healthz` → `{"status":"ok"}`.
7. Board öffnen, Bestand mit der Notiz aus Schritt 2 vergleichen.

**Erwartetes Ergebnis:** Identischer Bestand vor und nach dem simulierten Kartentod, `/healthz`
grün.

**Wenn nicht:** `docker compose --env-file ../.env logs homekanban --tail=100` — ein `503` von
`/healthz` bedeutet einen Invarianten-Verstoß und ist ernst zu nehmen (Journal und `items.stock`
stimmen nicht überein); in diesem Fall **nicht** weitermachen, sondern das restaurierte
`homekanban.db.vor-restore-<Zeitstempel>` (von `ops/restore.py` beiseitegelegt) als Ausgangspunkt
für eine genauere Untersuchung behalten.

**Notiere das Datum dieses Rundlaufs** — es gehört in den Ergebnis-Abschnitt und schließt den in
M9 offen gelassenen Punkt ab.

---

## Phase 13 — Abnahme durch ein zweites Haushaltsmitglied

Ein zweites Haushaltsmitglied öffnet `http://homekanban.local:<port>` auf dem **eigenen** Handy
(nicht deinem), ohne dass du etwas vorher einrichtest — das prüft, dass der mDNS-Alias und der
Port tatsächlich im ganzen Heimnetz funktionieren, nicht nur auf den bisher benutzten Geräten.

**Erwartetes Ergebnis:** Das Board lädt, ein Etikett lässt sich scannen und buchen.

---

## Abnahme-Checkliste

Definition of Done von M6 (docs/PLAN.md §9) und die Nachholpunkte aus M4/M5/M7/M9, zeilenweise:

- [ ] Phase 0: Docker + Compose-Plugin installiert, Repo auf dem richtigen Branch, `/data`-Volume
      gehört `1000:1000`.
- [ ] Phase 1: Port geprüft (A1), `HOMEKANBAN_PORT`/`HOMEKANBAN_BASE_URL` endgültig.
- [ ] Phase 2: `homekanban.local` von einem zweiten Gerät aus erreichbar.
- [ ] Phase 3: `.env` vollständig, `HOMEKANBAN_API_KEY` gesetzt.
- [ ] Phase 4: `/healthz` vom Pi **und** vom Handy `200`; „Hängt!“ läuft unbeeinträchtigt weiter
      (R4).
- [ ] Phase 5: Nach `reboot` ohne Handgriff erreichbar.
- [ ] Phase 6: 10–15 echte Artikel angelegt (R8).
- [ ] Phase 7 / M5-Nachholpunkt: Kalibrierseite gemessen, Bogen gedruckt, geklebt, aus 20 cm **und**
      bei schlechtem Licht scanbar.
- [ ] Phase 8: Zwei-Tap-Buchung am geklebten Etikett bestätigt.
- [ ] Phase 9 / M4- **und** M7-Nachholpunkt: Kurzbefehl durchgeführt, Notiz enthält abhakbare
      Punkte (inklusive gruppiertem Export mit Ladenüberschriften, falls Läden zugeordnet sind).
- [ ] Phase 10: Zwei Geräte buchen gleichzeitig ohne `database is locked` (R7, ADR 0008).
- [ ] Phase 11 / M9-Nachholpunkt (teilweise): Backup-Cron eingerichtet, Backup ausgelöst und
      geprüft.
- [ ] Phase 11.4 / R5 (**bewusst ggf. weiterhin offen**): Off-Pi-Kopie eingerichtet — nur abhakbar,
      sobald ein Zielgerät im Haushalt feststeht.
- [ ] Phase 12 / M9-Nachholpunkt: Restore-Rundlauf **mit Container** durchgeführt, Bestand nach dem
      Restore identisch zum Stand davor.
- [ ] Phase 13: Zweites Haushaltsmitglied hat die App auf dem eigenen Handy geöffnet.

**Erst wenn alle Zeilen außer ggf. der Off-Pi-Kopie abgehakt sind, ist M6 als „erledigt“ zu
markieren** — das entscheidet der Nutzer nach diesem Durchlauf, siehe docs/PLAN.md §9.

---

## Ergebnis-Abschnitt (zum Ausfüllen nach dem Durchlauf)

| Feld | Wert |
| --- | --- |
| Gemessener freier Port (Phase 1) | |
| Tatsächliche `HOMEKANBAN_BASE_URL` | |
| Gemessene Kalibrierstrecke (Soll: 100 mm, Phase 7.1) | |
| Erreichter Scanabstand (Soll: ≥ 20 cm, Phase 7.4) | |
| Build-Dauer beim ersten Start (Phase 4), kompiliert? (ja/nein) | |
| Welcher Kurzbefehl-Weg hat funktioniert? (automatisch / Rückfall 1 / Rückfall 2, Phase 9) | |
| Datum des Restore-Rundlaufs mit Container (Phase 12) | |
| Off-Pi-Backup-Ziel eingerichtet? (Gerät, Datum, oder „noch offen“) | |
| Datum der Abnahme durch ein zweites Haushaltsmitglied (Phase 13) | |

---

## Laufender Betrieb

Alle Befehle aus `/home/pi/HomeKanban/ops`, mit `--env-file ../.env` (siehe Warnung in
`ops/compose.yaml` — ohne dieses Flag verliert `HOMEKANBAN_PORT` seine Wirkung auf den
Host-Port).

**Start:**

```sh
docker compose --env-file ../.env up -d
```

**Stopp** (Container angehalten, Volume bleibt erhalten):

```sh
docker compose --env-file ../.env stop
```

**Update** (M6-Fragerunde, Frage 4: auf dem Pi bauen, kein zweiter Rechner nötig):

```sh
cd /home/pi/HomeKanban
git pull
cd ops
docker compose --env-file ../.env up -d --build
curl -s http://localhost:${HOMEKANBAN_PORT:-8181}/healthz
```

Ein Update, das eine Migration mitbringt, wendet sie beim Start automatisch an
(`app/main.py::lifespan`, `app/migrate.py`) — vor einem Update mit größeren Schemaänderungen
trotzdem ein frisches Backup ziehen (Phase 11.2), CLAUDE.md §4 verlangt das für jede destruktive
Datenoperation.

**Log lesen:**

```sh
docker compose --env-file ../.env logs -f homekanban        # laufend mitlesen
docker compose --env-file ../.env logs homekanban --tail=100  # letzte 100 Zeilen
```

Logs sind seit M6 auf `max-size: 10m, max-file: 3` begrenzt (`ops/compose.yaml`) — sie wachsen
nicht unbegrenzt auf der SD-Karte (R5).

**Datenbank sichern:** [`ops/BACKUP.md`](BACKUP.md), Kurzfassung in Phase 11 oben.

**Was tun, wenn nichts geht:**

1. `docker compose --env-file ../.env ps` — läuft der Container überhaupt?
2. `docker compose --env-file ../.env logs homekanban --tail=100` — steht dort ein Python-Traceback
   oder eine deutsche Fehlermeldung?
3. `curl -s http://localhost:${HOMEKANBAN_PORT:-8181}/healthz` — antwortet der Prozess innerhalb
   des Containers überhaupt, auch wenn von außen nichts ankommt (dann liegt es an Port/mDNS, nicht
   an der App)?
4. `docker stats --no-stream homekanban` — läuft der Container gegen das Speicherlimit
   (`mem_limit: 256m`, `ops/compose.yaml`)? Ein `OOMKilled` in `docker inspect homekanban` bestätigt
   das; dann den Wert in `ops/compose.yaml` erhöhen.
5. Führt nichts davon weiter: Restore aus dem letzten bekannt guten Backup (Phase 12) — ein
   SD-Karten-Tod kostet mit M9/M6 Bastelzeit, keine Daten (docs/PLAN.md §9, M9, Ziel).

**Weiterführende Dokumente** (hier bewusst nicht dupliziert):
[`ops/BACKUP.md`](BACKUP.md) (Sicherung, Aufbewahrung, Restore, Stammdaten-Export/-Import),
[`ops/ETIKETTEN.md`](ETIKETTEN.md) (Etikettenformat, Rastergrößen, Scanreichweite),
[`docs/KURZBEFEHL.md`](../docs/KURZBEFEHL.md) (Apple-Kurzbefehl Schritt für Schritt),
[`docs/adr/0008-verbindung-je-anfrage.md`](../docs/adr/0008-verbindung-je-anfrage.md) (R7-Fix,
Hintergrund zu Phase 10).
