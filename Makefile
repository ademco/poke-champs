# One-word commands for the common tasks. Run `make help` to list them.
.DEFAULT_GOAL := help
PY := .venv/bin/python
# Load .env (DATABASE_URL, ANTHROPIC_API_KEY) if present and pass it to commands.
-include .env
export
# Pinned Showdown commit the committed snapshot was exported from.
SHOWDOWN_COMMIT ?= 3065d24d698bc7f88a401c6e6d0cb42e5684d1ea
# Damage-calc version our Python port is tested against.
SMOGON_CALC_VERSION ?= 0.12.0

help:  ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

setup:  ## create .venv and install dependencies
	@# Some macOS Python builds fail in ensurepip; fall back to pip's official bootstrap.
	test -x .venv/bin/pip || python3.12 -m venv .venv || \
	  (rm -rf .venv && python3.12 -m venv --without-pip .venv && \
	   curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python)
	.venv/bin/pip install -q -e ".[dev]"

db-up:  ## start Postgres+pgvector in Docker (256 MB cap)
	docker compose up -d --wait

db-down:  ## stop Postgres (data is kept in a Docker volume)
	docker compose down

migrate:  ## apply SQL migrations
	$(PY) -m pokechamp.db.migrate

ingest:  ## load the Showdown snapshot into Postgres (idempotent)
	$(PY) -m pokechamp.ingest.load_showdown

index:  ## build the RAG index (chunk + embed + store); first run downloads bge-small (~130 MB)
	$(PY) -m pokechamp.rag.index

search:  ## try a question (hybrid search by default; --mode vector|keyword|rerank): make search Q="how long does sleep last?"
	$(PY) -m pokechamp.rag.search "$(Q)"

analyze:  ## analyze a team, no API key needed: make analyze FILE=team.txt [SINGLES=1]
	$(PY) -m pokechamp.analyze "$(FILE)" $(if $(SINGLES),--singles)

ask:  ## grounded, cited answer (needs ANTHROPIC_API_KEY in .env): make ask Q="..."
	$(PY) -m pokechamp.answer.pipeline "$(Q)"

web:  ## the MVP web app at http://localhost:5000 (team analysis + questions)
	$(PY) -m pokechamp.web.app

eval-answers:  ## answer-quality + grounding eval (calls the API, ~$0.25/run on Haiku)
	$(PY) -m pokechamp.evals.answers --out evals/results/answers.json

eval-retrieval:  ## score every search configuration on evals/retrieval_set.yaml (needs `make index`)
	$(PY) -m pokechamp.evals.retrieval

checks:  ## run golden-set auto-checks against the database
	$(PY) -m pokechamp.evals.auto_checks

test:  ## lint + format check + all tests
	.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest

demo: db-up migrate ingest index checks  ## everything from zero: DB up, schema, data, RAG index, checks

SHOWDOWN_DIR := .cache/showdown

snapshot:  ## re-export data/snapshots from Showdown@SHOWDOWN_COMMIT (Node runs in Docker)
	@test -d $(SHOWDOWN_DIR)/.git || git init -q $(SHOWDOWN_DIR)
	git -C $(SHOWDOWN_DIR) fetch -q --depth 1 https://github.com/smogon/pokemon-showdown.git $(SHOWDOWN_COMMIT)
	git -C $(SHOWDOWN_DIR) checkout -q --force FETCH_HEAD
	docker run --rm $(DOCKER_ARGS) -v "$(CURDIR)":/work -w /work/$(SHOWDOWN_DIR) \
	  node:22.23.3-alpine sh /work/tools/showdown_export/run.sh $(SHOWDOWN_COMMIT)

fixtures:  ## regenerate reference answers: Showdown validator + @smogon/calc (Node in Docker)
	.venv/bin/python tools/showdown_export/build_legality_teams.py
	docker run --rm $(DOCKER_ARGS) -v "$(CURDIR)":/work -w /work/$(SHOWDOWN_DIR) \
	  -e SHOWDOWN_DIR=/work/$(SHOWDOWN_DIR) node:22.23.3-alpine \
	  node /work/tools/showdown_export/validate_teams.js /work
	docker run --rm $(DOCKER_ARGS) -v "$(CURDIR)":/work -w /work/.cache/calc node:22.23.3-alpine \
	  sh -c 'npm init -y >/dev/null && npm i --silent @smogon/calc@$(SMOGON_CALC_VERSION) && \
	  NODE_PATH=/work/.cache/calc/node_modules node /work/tools/calc_fixtures/generate.js /work'

.PHONY: help setup db-up db-down migrate ingest index search analyze ask web eval-answers eval-retrieval checks test demo snapshot fixtures
