# Einfaches, lauffähiges Image für M0 (aarch64-tauglich, siehe docs/PLAN.md Annahme A3).
# Härtung (Nicht-Root, HEALTHCHECK, restart:, Speicherlimit) ist Aufgabe von M6.
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations

RUN pip install --no-cache-dir .

EXPOSE 8181

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8181"]
