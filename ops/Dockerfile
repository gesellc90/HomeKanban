# Gehärtetes Image für M6 (docs/PLAN.md §9): Nicht-Root, HEALTHCHECK, aarch64-tauglich (A3).
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
# Nur die beiden CLI-Skripte, die im Container laufen sollen (Backup-Cron, Frage 2 der
# M6-Fragerunde: "Alles im Container") — nicht das restliche ops/ (Dockerfile, compose.yaml,
# Markdown-Anleitungen), das im Image keinen Zweck hat.
COPY ops/backup.py ops/restore.py ./ops/

RUN pip install --no-cache-dir .

# Nicht-Root mit fester UID/GID (M6, CLAUDE.md §4). /data ist der Mountpunkt des benannten Volumes
# aus ops/compose.yaml: Ein *frisches* Volume übernimmt beim ersten Mount Eigentümer und Rechte
# dieses Verzeichnisses aus dem Image — ein *bereits bestehendes* Volume (z. B. aus M0–M5, als der
# Container noch als root lief) tut das nicht automatisch. Der Weg für diesen Fall steht in
# ops/BETRIEB.md, Phase 0.
RUN groupadd --gid 1000 homekanban \
    && useradd --uid 1000 --gid homekanban --no-create-home --shell /usr/sbin/nologin homekanban \
    && mkdir -p /data \
    && chown homekanban:homekanban /data
USER homekanban

EXPOSE 8181

# Kein curl/wget im slim-Image (CLAUDE.md §4: keine neue Abhängigkeit) — ein einzeiliger
# urllib-Aufruf gegen /healthz genügt. urlopen() wirft bei jeder Antwort ungleich 2xx (also auch
# beim 503 der Invariantenprüfung, app/api/health.py) eine HTTPError, wodurch der Python-Prozess
# mit einem von Null verschiedenen Exit-Code endet — genau das Signal, das HEALTHCHECK braucht.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8181/healthz', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8181"]
