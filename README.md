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
make search Q="how long does sleep last?"   # try the vector search
make test    # lint + tests (DB tests run when Postgres is up)
make help    # everything else
```

## Docs

- [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md): every source, its license, and what we use it for
- [`docs/RUBRIC.md`](docs/RUBRIC.md): answer-quality rubric for the LLM judge
- [`evals/golden_set.yaml`](evals/golden_set.yaml): the fixed test set every phase is graded on

## Credits

Game data from [Pokémon Showdown](https://github.com/smogon/pokemon-showdown) (MIT). Pokémon and all related names are trademarks of Nintendo, Creatures Inc. and GAME FREAK inc. This is an unofficial, non-commercial fan project.
