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

---

## Phase 2: deterministic tools

**Built** (`src/pokechamp/tools/`)
- `repo.py`: a `Facts` interface with two backends, `DbFacts` (Postgres, for the app) and `SnapshotFacts` (committed JSON, for fast tests). A test proves they give identical answers, damage included.
- `stats.py`: the Champions stat formula (SP, level 50, IVs 31) and stat stages, in integer math.
- `speed.py`: final Speed with Tailwind, Choice Scarf, weather abilities and paralysis, and move order including Trick Room.
- `typechart.py`: effectiveness from the `type_chart` table, plus a per-type team weakness report.
- `team_parser.py`: Showdown text → structured sets. Pasted text is treated as **data**: a nickname like "IGNORE PREVIOUS INSTRUCTIONS" is just a string, and unknown lines become warnings.
- `legality.py`: machine-readable problem codes (`move_not_learnable:Incineroar:Knock Off`) plus human messages.
- `damage.py`: a Python port of `@smogon/calc` 0.12.0's Champions calculator, with integer-exact rounding (`mathutil.py`).
- Migration `002` adds move properties the calculator needs (multi-hit, secondary effects, recoil…); the export was updated to match.
- `make fixtures`: regenerates the reference answers with Showdown's TeamValidator and the real `@smogon/calc`, both run in Docker.

**Metrics**
| | Before | After |
|---|---|---|
| Golden-set auto-checks graded | 10 | **27/27 pass** (only the 6 usage-stat checks remain) |
| Damage scenarios matching @smogon/calc roll for roll | n/a | **78/78** (+1 deliberate refusal) |
| KO descriptions matching @smogon/calc's wording | n/a | **68/68** comparable cases |
| Teams where our legality verdict matches Showdown's validator | n/a | **26/26** (compared by problem category) |
| Tests | 47 | **192** |
| Mutation check: Python `round()` swapped for the game's rounding | n/a | 60 of 80 damage tests fail, as they should |

**What the cross-checks caught** (each would have shipped wrong answers)
- My first port crashed when Mold Breaker replaced the defender object (speeds were keyed by object identity).
- KO chance was computed from full HP even for a damaged defender, and its percentages were truncated where @smogon/calc rounds.
- Writing "Garchomp-Mega-Z @ Garchompite Z" is **legal** in Showdown. I had flagged it. Now it's accepted with the matching stone and rejected otherwise.
- Nicknames over 18 characters are illegal. I hadn't checked that; it also flags the prompt-injection test team.
- I had skipped item checks for illegal Pokémon. Items are holder-independent, so they're now always checked.
- Found in @smogon/calc itself: its Lash Out condition can never fire. We refuse Lash Out instead of copying the bug.

**Trade-offs**
- *Port to Python vs call @smogon/calc via Node.* Porting means one runtime in the container, ordinary unit tests, and a plain function call for the agent. The cost is keeping it in sync. That's mitigated by fixtures from a pinned calc version: an upgrade is "bump version → `make fixtures` → see what changed".
- *Refuse vs approximate.* When an ability, item or move needs a mechanic the port doesn't have (multi-hit, Parental Bond…), it raises `UnsupportedCalculation`. A wrong damage number stated confidently is worse than "I can't calculate that yet".
- *Compare legality by category, not message text.* Showdown stops at the first unlearnable move, while we list all of them. Matching categories checks the substance without coupling to wording.
- *One root cause per illegal Pokémon,* but holder-independent problems (item, nickname) are still reported.

**Interview questions**
1. *How do you know your damage calculator is right?*
   I don't trust my reading of the formula; I diff against a reference. `make fixtures` runs the real @smogon/calc 0.12.0 on 79 scenarios, each targeting one rule (weather both ways, crits ignoring boosts, screens in singles vs doubles, Multiscale vs Mold Breaker…). All 16 rolls must match exactly. To show the tests have teeth, swapping the game's round-half-down for Python's `round()` fails 60 of them.
2. *Why does the calculator sometimes refuse to answer?*
   Some mechanics need state the calculator doesn't have (how many hits Scale Shot lands, whether Parental Bond's second hit applies). Returning a single-hit number for a multi-hit move would be confidently wrong, and in a grounded assistant a refusal the agent can explain beats a hallucinated number. The unsupported list is explicit and documented.
3. *What's the point of the `Facts` interface?*
   The tools don't care where facts come from. Unit tests use the JSON snapshot (milliseconds, no database), the app uses Postgres, and one test asserts both give the same answers. It's the repository pattern, the same idea as Spring Data, and it keeps the math testable in isolation.

---

## Phase 3: unstructured corpus, chunking, embeddings, pgvector

**Built** (`src/pokechamp/rag/`)
- `corpus.py`: **904 documents**: Showdown descriptions of 515 legal moves, 215 abilities a legal Pokémon can have, and 166 legal items (MIT), plus 8 project-written mechanics notes (`data/corpus/notes/`), each citing the code it was verified from.
- `chunking.py`: heading-aware splitting, a ~160-word cap, one-sentence overlap, and a "Title > Section" prefix. → **926 chunks** (median 21 words, max 180).
- `embeddings.py`: an `Embedder` interface. `FastEmbedEmbedder` runs BAAI/bge-small-en-v1.5 (384 dimensions, ONNX on CPU, ~180 MB of packages, no PyTorch). `HashingEmbedder` is a deterministic test double.
- Migration `003`: the `vector` extension, `documents` and `chunks` tables, an HNSW cosine index, and a generated `tsvector` column with a GIN index (ready for Phase 4's hybrid search).
- `index.py`: an atomic, idempotent load (one transaction, embedding done *before* it opens). `search.py`: cosine top-k, filtered to the live regulation, with `hnsw.iterative_scan`.
- CI: model cache, `REQUIRE_MODEL=1`, a real-model index build with memory measurement, and a retrieval smoke test.

**Metrics (real model, measured in CI on a 2-vCPU GitHub runner)**
| | Value |
|---|---|
| Embed + index 926 chunks | 42.7 s (43.9 s wall clock) |
| Peak memory while indexing | **~1.05 GB RSS**. Fine on an 8 GB Mac, but higher than expected; the likely cause is 64-chunk batches (worth tuning, not urgent for a one-off batch job) |
| Retrieval smoke test (6 obvious questions, top 5) | passed (≥5/6) |
| "How long does sleep last in Champions?" → top hit | the status-conditions note's Sleep section, cosine 0.80 |
| Hashing test-double, same question set (for contrast) | finds Sleep/Stat Points, but misses "what does Intimidate do": no semantics, only shared words |

**Findings along the way**
- Showdown's text data has **Champions-specific descriptions** (`champions:` entries) for 17 moves, 2 abilities and 1 item, such as "Moonblast: 10% chance". For **18** other entries the Champions mod changes behavior without updated text, so those chunks say the description may describe main-series behavior. That's honesty in the data itself.
- A module-caching trap: Showdown's `Dex` merges mod tables *in place*, so reading them after loading made every entry look changed. They're now captured before the `Dex` loads.
- fastembed's `query_embed` does **not** add BGE's query instruction (checked in the 0.9.0 source, not assumed). Whether the prefix helps is a Phase 4 experiment.
- The cloud sandbox can't download the model (Hugging Face is blocked), so the real model runs in CI (cached) and on Adem's Mac. Unit tests use the hashing double.

**Trade-offs**
- *Local embeddings vs an API (Voyage).* Local means no key, no cost, no data leaving the machine, and reproducible results. The cost is ~1 GB of RAM while indexing and lower quality than the best hosted models. Phase 4 measures whether that quality gap matters on *our* questions before paying for anything.
- *HNSW at ~1k chunks.* An exact scan would be just as fast at this size. We use HNSW because it's what production uses, and its recall against an exact scan is measurable. `iterative_scan` keeps regulation filtering correct once several regulations share the table during a switchover.
- *Numbers stay out of chunks.* Entity documents describe effects, not base power or legality. Otherwise the LLM could quote a number from retrieved text instead of calling the tool that owns it.
- *Writing our own notes vs waiting for Bulbapedia.* The notes are short and each cites the code it was checked against. Bulbapedia (CC BY-NC-SA) can be added once its terms are confirmed.

**Interview questions**
1. *What is an embedding, and why cosine similarity?*
   A model maps text to a vector (384 numbers here) so that texts with similar meaning point in similar directions. Cosine similarity compares the angle, ignoring length, which is what the model was trained for. Search becomes "embed the question, return the nearest chunk vectors".
2. *How did you choose chunk size?*
   Chunks are the unit of retrieval. Too big and one vector blurs several topics; too small and a chunk loses its context. I split on document structure (headings) first, capped at ~160 words, overlapped by one sentence so facts on a boundary survive, and prefixed each chunk with "Title > Section" so a chunk saying "it lasts two turns" still says *what* lasts two turns. Phase 4 can vary these and measure.
3. *What does the HNSW index trade off, and what goes wrong with filters?*
   HNSW is a graph you navigate to find *approximate* nearest neighbours: far fewer comparisons, at the cost of sometimes missing the true nearest one. Filters are applied after the graph search, so a selective `WHERE` can return fewer than k rows. pgvector 0.8's `iterative_scan` keeps searching until enough rows pass the filter.
