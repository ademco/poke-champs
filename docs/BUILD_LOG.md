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
