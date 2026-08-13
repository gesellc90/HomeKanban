#!/bin/sh
# Preflight-Check für ops/BETRIEB.md Phase 0/1/2/3 — fragt maschinell prüfbare Vorbedingungen ab
# und berichtet deutsch. Kein Ersatz für das Handbuch, nur eine Abkürzung für die Handgriffe, die
# sich automatisieren lassen. Aufruf: sh ops/preflight.sh [--port PORT]
#
# Nichts hier verändert etwas — reines Nachsehen, keine Schreibzugriffe.

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
PORT="${HOMEKANBAN_PORT:-8181}"
FAILED=0

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
done

ok()   { printf '  [ok]   %s\n' "$1"; }
warn() { printf '  [warn] %s\n' "$1"; }
fail() { printf '  [fail] %s\n' "$1"; FAILED=1; }

echo "== Docker =="
if command -v docker >/dev/null 2>&1; then
  ok "docker gefunden: $(docker --version)"
else
  fail "docker nicht gefunden — siehe ops/BETRIEB.md Phase 0.1"
fi

if docker compose version >/dev/null 2>&1; then
  ok "docker compose gefunden: $(docker compose version --short 2>/dev/null || echo vorhanden)"
else
  fail "docker compose (Plugin) nicht gefunden — siehe ops/BETRIEB.md Phase 0.1"
fi

echo "== Port $PORT =="
if command -v ss >/dev/null 2>&1; then
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[.:]$PORT\$"; then
    fail "Port $PORT scheint belegt — vollständige Ausgabe: ss -ltnp | grep $PORT (ops/BETRIEB.md Phase 1)"
  else
    ok "Port $PORT ist frei (ss -ltn)"
  fi
else
  warn "ss nicht gefunden — Port manuell mit 'ss -ltnp' prüfen (ops/BETRIEB.md Phase 1)"
fi

echo "== .env =="
if [ -f "$ENV_FILE" ]; then
  ok ".env vorhanden"
  for var in HOMEKANBAN_BASE_URL HOMEKANBAN_PORT HOMEKANBAN_DB_PATH HOMEKANBAN_API_KEY \
             HOMEKANBAN_BACKUP_DIR HOMEKANBAN_BACKUP_KEEP TZ; do
    if grep -Eq "^${var}=.+" "$ENV_FILE"; then
      ok "$var gesetzt"
    else
      fail "$var fehlt oder ist leer in .env (siehe .env.example)"
    fi
  done
else
  fail ".env fehlt — mit 'cp .env.example .env' anlegen (ops/BETRIEB.md Phase 3)"
fi

echo "== mDNS =="
if command -v avahi-resolve >/dev/null 2>&1; then
  if avahi-resolve -n homekanban.local >/dev/null 2>&1; then
    ok "homekanban.local löst auf: $(avahi-resolve -n homekanban.local 2>/dev/null | awk '{print $2}')"
  else
    warn "homekanban.local löst (noch) nicht auf — normal vor ops/BETRIEB.md Phase 2, sonst dort nachschlagen"
  fi
else
  warn "avahi-resolve nicht gefunden — mDNS manuell von einem zweiten Gerät prüfen (ops/BETRIEB.md Phase 2)"
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "Alle harten Prüfungen bestanden. Details und die übrigen, nicht automatisierbaren Schritte: ops/BETRIEB.md."
  exit 0
else
  echo "Mindestens eine Prüfung ist fehlgeschlagen — Details oben, Abhilfe jeweils mit Verweis auf ops/BETRIEB.md."
  exit 1
fi
