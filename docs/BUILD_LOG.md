# Build log

One section per phase: what was built, key trade-offs, metrics, and interview prep.

---

## Phase 0: setup, CI, data-source research, golden set

**Built**
- Python 3.12 project (`pyproject.toml`, src layout, exact-pinned deps), `.env.example`, `.gitignore`.
- GitHub Actions CI: `ruff check`, `ruff format --check`, `pytest` on every PR and push to `main`.
- `pokechamp.regulations`: the single source of truth for which regulation is current (M-C), with exact UTC switchover times and Showdown format IDs.
- `pokechamp.sources`: whitelist of data sources with license and approval status. A test keeps it in sync with `docs/DATA_SOURCES.md`.
- `docs/DATA_SOURCES.md`: license and terms research for each source, including what couldn't be verified and why.
- `evals/golden_set.yaml`: **38 cases** (12 mechanics, 6 meta, 9 team analysis, 11 trick; 18 doubles-specific, 4 singles-specific, 16 both). 23 of 38 (61%) have exact auto-checks against structured data. The file is validated by a pydantic schema, and I checked that typos, unknown check kinds and missing sources are all rejected.
- `docs/RUBRIC.md`: draft LLM-judge rubric with anchored 0–2 scales, to finalize together.

**Key findings**
- Current regulation **M-C** (2026-09-09 02:00 UTC → 2026-12-02), confirmed from Showdown's code, not just news sites.
- Showdown's code answers mechanics questions the community repo marks "unverified": SP 66/32, IVs fixed at 31, the stat formula, and changed paralysis/sleep/freeze.
- The community dataset is stale (M-A, April) and partly scraped from Serebii, so it's demoted to cross-check only.
- `@smogon/calc` has a Champions mode, and the reported Life Orb gap looks fixed in the current source (to be confirmed by tests in phase 2).
- The cloud sandbox can't reach smogon.com, Bulbapedia, Pikalytics or Limitless, so those sources stay "pending" until checked from a normal network.

**Trade-offs**
- *Golden set expected values come from code, not memory.* Every legality, learnset, stat and type fact was computed from Showdown's data files with a script. One hand-reasoned weakness count was wrong and got caught that way.
- *Meta cases have no frozen numbers.* Usage changes monthly, so those cases say *how* to check (`usage_top` against the latest usage table) instead of *what* the answer is.
- *Pydantic with `extra="forbid"`* on the golden set: a misspelled YAML key fails CI instead of silently being ignored.
- *Exact pins* (`==`) over ranges: reproducible CI matters more than auto-upgrades for a portfolio repo. Upgrades become deliberate PRs.

**Metrics:** none yet (there's no system to measure).

**Interview questions**
1. *Why build the eval set before the system?*
   So the target can't move. If you write tests after seeing outputs, you unconsciously pick questions the system already handles. A fixed set also gives before/after numbers for every change (e.g. adding a reranker).
2. *Why are some expected answers "computed at eval time"?*
   Usage stats change every month. Freezing them in the test would make the test wrong, not the system. The case stores the *check* (top-N from the usage table for the right format), so the expected value is always current.
3. *How did you decide which data sources to trust?*
   License first (can we legally store it?), then authority (is it the simulator's own code or a scrape?), then freshness. Showdown is MIT and *is* the rules engine, so it's primary. The CC BY community repo is stale and partly derived from a non-licensed site, so it's only a cross-check.

### Phase 0 follow-up: scope = current regulation only

Adem decided the assistant covers **only the live regulation** (M-C now) and gets updated when M-D launches. Changes:
- The golden set no longer expects M-B answers. Questions *about* M-B stay as inputs (people will ask), but the expected behavior is "only M-C is covered" plus the M-C answer. 4 cases were reworded and one M-B comparison case was replaced with an M-C legality case.
- `regulations.is_supported()`, plus a test that fails whenever a golden case targets a non-live regulation. When M-D is added, CI goes red until the set is re-verified. That's intentional: it's the reminder.
- We still tag every record with its regulation. *Interview angle:* "Why tag if you only support one?" Because the switchover is a data migration: load the new data, flip `current`, delete the old tag. Without tags you can't tell stale rows from fresh ones, and stale legality data is exactly how an assistant ends up confidently wrong.

---

## Phase 1: structured data in Postgres

**Built**
- `docker-compose.yml`: Postgres 17 + pgvector 0.8.7, capped at **256 MB** (it uses ~34 MB with all data loaded). Host port 5433, so it can't clash with a Homebrew Postgres.
- `tools/showdown_export/`: a Node script, run **inside Docker**, that asks Showdown's own `Dex` and `TeamValidator` for the merged M-C data and writes `data/snapshots/showdown_champions.json`.
- Schema (`src/pokechamp/db/migrations/001_structured_facts.sql`): `species`, `moves`, `abilities`, `items`, `learnsets`, `natures`, `type_chart`, `formats`, plus `ingestion_runs` for provenance. A ~40-line migration runner works like Flyway.
- `pokechamp.ingest.load_showdown`: an atomic, idempotent loader (one transaction: record the run, delete this regulation's rows, COPY the new ones).
- `pokechamp.facts`: the first read-only lookups (species, item, move, learnset), which become phase 2's tools.
- `pokechamp.evals.auto_checks`: runs the golden set's checks against the database.
- `Makefile`: `make demo` goes from nothing to a loaded, checked database. CI now runs a Postgres service container plus an end-to-end migrate → load → check step.

**Metrics**
| | Before | After |
|---|---|---|
| Golden-set auto-checks gradeable from data | 0 | **10/10 pass** |
| Still waiting on phase-2 tools / usage data | 33 | 23 (stat 5, team_legality 5, type_weakness 4, speed 2, damage 1, usage 6) |
| Load time (empty DB → loaded) | n/a | ~1 s load, ~5 s for `make demo` |
| Cross-check vs community dataset | n/a | 256/258 matched, **0** stat/type mismatches |

**Bugs caught along the way (and the test that now guards each)**
- All 16 typed Hidden Powers share Showdown's id `hiddenpower`. The primary key rejected the load and the transaction rolled back cleanly. → IDs are now derived from names; `test_ids_are_unique_and_derived_from_names`.
- Gigantamax sprite placeholders like `charizardgmax` were marked "legal" through their base form. → excluded from the export; the learnset-coverage test would catch any regression.
- Showdown phrases "not in Champions" as "does not exist in Gen 9". → reworded at export, so the assistant never claims a real Pokémon doesn't exist.

**Trade-offs**
- *Showdown's code does the merging, not my parser.* The Champions data is a set of patches on the base game. Re-implementing that in Python would be a second, untested copy of the rules. Running Showdown's own `Dex` costs one Docker step, but legality then comes from the engine that runs the real ladder.
- *Committed snapshot vs re-downloading every time.* It's 1.5 MB of MIT data. Committing it means CI needs no Node or network, and a refresh shows up as a git diff you can review ("Psyshield Bash 70 → 90").
- *Provenance through a foreign key, not repeated columns.* Each row has `run_id` → `ingestion_runs` (source, license, commit, retrieved_at). That's smaller, and every row from one load is guaranteed to have identical provenance.
- *Delete-and-reload vs upsert.* The data is small, and delete-and-reload removes things that disappear from the game. Upserts would leave them behind.
- *`regulation` in every primary key,* even though we serve one regulation. It makes the M-D switchover a data operation, not a schema change.

**Interview questions**
1. *How do you make a data load safe to re-run and safe to fail?*
   Put the whole load in one transaction: insert the run record, delete the old rows, COPY the new ones. If anything throws, Postgres rolls everything back and readers keep the old data. Re-running gives the same end state (idempotent). We proved it by loading a deliberately broken snapshot: the test asserts nothing changed, and when I temporarily removed the transaction, that test failed.
2. *Why not let the LLM or vector search answer "can Incineroar learn Knock Off?"*
   It's a yes/no fact with one correct answer that changes by regulation. A SQL lookup against a learnset table validated by Showdown's own TeamValidator is exact, cheap and citable (`run_id` → commit SHA). An LLM's memory is from mainline games, where Incineroar *can* learn it, so it would be confidently wrong.
3. *What do the database constraints buy you if Python already validates?*
   Defense in depth. Pydantic checks the file's shape; the database enforces truths across rows: foreign keys (no learnset move that doesn't exist), CHECKs (multipliers only 0/0.5/1/2; `legal` ⇔ no ban reason), and primary keys. The Hidden Power bug got past the Python models and was caught by the primary key.
