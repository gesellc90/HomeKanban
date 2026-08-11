# HomeKanban — alle Checks laufen lokal. Dieses Projekt nutzt bewusst keine GitHub Actions.
#
# Solange die Toolchain noch nicht steht (Meilenstein M0), melden sich die Targets als
# "noch nicht konfiguriert" und blockieren weder Commit noch Push.

.DEFAULT_GOAL := help
SHELL := /bin/sh

PYTHON ?= python3.12
VENV   ?= .venv

.PHONY: help hooks setup fmt lint test check clean

help: ## Verfügbare Targets anzeigen
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

hooks: ## Versionierte Git-Hooks aktivieren (einmalig nach dem Klonen)
	@git config core.hooksPath .githooks
	@chmod +x .githooks/* 2>/dev/null || true
	@echo "Git-Hooks aktiv: .githooks (pre-commit, pre-push)"

setup: ## Entwicklungsumgebung einrichten
	@if [ -f pyproject.toml ] || [ -f requirements-dev.txt ]; then \
		[ -d $(VENV) ] || $(PYTHON) -m venv $(VENV); \
		if [ -f requirements-dev.txt ]; then $(VENV)/bin/pip install -r requirements-dev.txt; \
		else $(VENV)/bin/pip install -e '.[dev]'; fi; \
		$(MAKE) hooks; \
	else \
		echo "setup: noch keine Abhängigkeiten definiert (kommt in M0) — übersprungen"; \
		$(MAKE) hooks; \
	fi

fmt: ## Code formatieren
	@if [ -x $(VENV)/bin/ruff ]; then \
		$(VENV)/bin/ruff format . && $(VENV)/bin/ruff check --fix .; \
	else \
		echo "fmt: Formatter noch nicht konfiguriert (kommt in M0) — übersprungen"; \
	fi

lint: ## Statische Prüfung (Format, Ruff, mypy auf app/domain)
	@if [ -x $(VENV)/bin/ruff ]; then \
		$(VENV)/bin/ruff format --check . && $(VENV)/bin/ruff check .; \
	else \
		echo "lint: Linter noch nicht konfiguriert (kommt in M0) — übersprungen"; \
	fi
	@if [ -x $(VENV)/bin/mypy ]; then \
		$(VENV)/bin/mypy; \
	else \
		echo "lint: mypy noch nicht konfiguriert (kommt in M0) — übersprungen"; \
	fi

test: ## Tests ausführen
	@if [ -x $(VENV)/bin/pytest ] && [ -d tests ]; then \
		$(VENV)/bin/pytest -q; \
	else \
		echo "test: noch keine Tests vorhanden (kommt ab M1) — übersprungen"; \
	fi

check: lint test ## Alles prüfen, was vor einem Push laufen muss
	@echo "check: abgeschlossen"

clean: ## Caches entfernen
	@rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "clean: Caches entfernt"
