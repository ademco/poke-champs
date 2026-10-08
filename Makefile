# One-word commands for the common tasks. Run `make help` to list them.
.DEFAULT_GOAL := help
PY := .venv/bin/python
# Pinned Showdown commit the committed snapshot was exported from.
SHOWDOWN_COMMIT ?= 3065d24d698bc7f88a401c6e6d0cb42e5684d1ea

help:  ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup:  ## create .venv and install dependencies
	python3.12 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"

db-up:  ## start Postgres+pgvector in Docker (256 MB cap)
	docker compose up -d --wait

db-down:  ## stop Postgres (data is kept in a Docker volume)
	docker compose down

migrate:  ## apply SQL migrations
	$(PY) -m pokechamp.db.migrate

ingest:  ## load the Showdown snapshot into Postgres (idempotent)
	$(PY) -m pokechamp.ingest.load_showdown

checks:  ## run golden-set auto-checks against the database
	$(PY) -m pokechamp.evals.auto_checks

test:  ## lint + format check + all tests
	.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest

demo: db-up migrate ingest checks  ## everything from zero: DB up, schema, data, checks

SHOWDOWN_DIR := .cache/showdown

snapshot:  ## re-export data/snapshots from Showdown@SHOWDOWN_COMMIT (Node runs in Docker)
	@test -d $(SHOWDOWN_DIR)/.git || git init -q $(SHOWDOWN_DIR)
	git -C $(SHOWDOWN_DIR) fetch -q --depth 1 https://github.com/smogon/pokemon-showdown.git $(SHOWDOWN_COMMIT)
	git -C $(SHOWDOWN_DIR) checkout -q --force FETCH_HEAD
	docker run --rm $(DOCKER_ARGS) -v "$(CURDIR)":/work -w /work/$(SHOWDOWN_DIR) \
	  node:22.23.3-alpine sh /work/tools/showdown_export/run.sh $(SHOWDOWN_COMMIT)

.PHONY: help setup db-up db-down migrate ingest checks test demo snapshot
