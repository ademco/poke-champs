# PokéChamp v2

A grounded assistant for **Pokémon Champions** (the official VGC game for the 2026 season). It answers mechanics and meta questions with cited sources and analyzes Showdown-format teams. Every claim states its regulation and its source.

> 🚧 Work in progress, built in phases. See [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md).

## Design in one paragraph

Structured facts (stats, legality, learnsets, usage) live in PostgreSQL and are reached through **tools**. Unstructured text (mechanics explanations) goes through **RAG** with pgvector. The LLM never does math: stat, speed, type and damage calculations are deterministic, unit-tested Python. Every record carries `source`, `license`, `regulation` and `retrieved_at`.

## Quick start

Needs Python 3.12, Docker and git (no Node; it only runs inside Docker).

```bash
make setup   # .venv + dependencies
make demo    # Postgres up -> schema -> Showdown data -> RAG index -> golden-set checks
make web     # the app: http://localhost:5000
```

In the app:
- **Analyze a team** (works offline, no API key): paste a Showdown export and get legality problems, final stats, Speed order (with Tailwind and Scarf) and shared type weaknesses. Every number comes from deterministic tools, never from an LLM.
- **Ask a question**: a cited answer from Claude, grounded in the mechanics notes and Showdown data. Needs `ANTHROPIC_API_KEY` in `.env` (`cp .env.example .env`, then paste your key). A question costs well under $0.01 on Claude Haiku 5.5.

Terminal versions and the rest:
```bash
make analyze FILE=team.txt                 # team report in the terminal
make ask Q="how long does sleep last?"     # cited answer (needs the key)
make search Q="..."                        # raw search results (hybrid: vector + keyword)
make test                                  # lint + tests (DB tests run when Postgres is up)
make help                                  # everything else
```

## Docs

- [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md): every source, its license, and what we use it for
- [`docs/RUBRIC.md`](docs/RUBRIC.md): answer-quality rubric for the LLM judge
- [`evals/golden_set.yaml`](evals/golden_set.yaml): the fixed test set every phase is graded on

## Credits

Game data from [Pokémon Showdown](https://github.com/smogon/pokemon-showdown) (MIT). Pokémon and all related names are trademarks of Nintendo, Creatures Inc. and GAME FREAK inc. This is an unofficial, non-commercial fan project.
