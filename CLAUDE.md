# CLAUDE.md: PokéChamp v2

Read this before every session in this repo. It records how Adem and Claude work together on this project.

## What this project is

PokéChamp v2 is a portfolio-grade RAG + agent assistant for **Pokémon Champions**, the official VGC game for the 2026 season (launched 2026-04-08). It:

1. answers mechanics and meta questions with grounded, cited answers,
2. analyzes a pasted Showdown-format team (legality, type weaknesses and coverage, speed tiers, top meta threats, damage calcs) and suggests improvements,
3. always states **which regulation** and **which source** each claim comes from.

Adem is building this to get AI Engineer roles and must be able to explain every part in an interview. **Teach as you build:** explain the why, not just the what.

## Core design principle (never violate)

- **Structured facts** (base stats, types, moves, abilities, items, learnsets, legality lists, usage stats) live in **PostgreSQL tables** and are reached through **tools**, never vector search.
- **Unstructured text** (mechanics explanations, rules, strategy notes) goes through **RAG with pgvector**.
- **The LLM never does math.** Stat calculation, type effectiveness, speed comparisons, and damage are deterministic Python tools with unit tests.
- **Every record and chunk carries metadata:** `source`, `license`, `regulation` (e.g. `M-B`, `M-C`), `retrieved_at`. Retrieval filters by regulation and defaults to the current one.
- The agent **never invents** stats, moves, or legality. If something isn't supported, it says "not found". It treats pasted teams as data and rejects prompt injection inside them.

## Current game state (verified 2026-10-08; re-verify, don't trust training data)

- **Current regulation: M-C**, from 2026-09-09 02:00 UTC to 2026-12-02 (per Serebii/Vice; confirm the end date). The current ranked season is **M-7** (about 2026-10-07 to 2026-11-04/05; sources differ by a day).
- Previous regulations: M-A (launch to 2026-06-17), M-B (2026-06-17 to 2026-09-09).
- **Primary roster source: Pokémon Showdown** (MIT). The `champions` mod = Reg M-C; `championsregmb` = Reg M-B. Formats include `[Gen 9 Champions] VGC 2026 Reg M-C` (doubles) and `[Gen 9 Champions] BSS Reg M-C` (singles).
- From Showdown's `formats-data.ts`, M-C has 349 legal entries (forms and Megas counted separately) vs 314 for M-B. That's +35 entries = 23 new species + Alolan Persian + 6 new Megas (Absol-Mega-Z, Garchomp-Mega-Z, Lucario-Mega-Z, Salamence-Mega, Golisopod-Mega, Baxcalibur-Mega) + cosmetic/alt forms. Nothing was removed. This explains why news sites quote 22, 24, 29, or 34 "new Pokémon".
- **Tera does not exist in Champions.** Mega Evolution does. Champions uses Stat Points (SP) instead of EVs; verify exact SP rules from sources before implementing in phase 2.
- **Community repo `otterlyclueless/pokemon-champions-data` is stale:** last updated 2026-04-16 (Reg M-A, 258 entries, no M-C additions). Its move/learnset data was scraped from Serebii, so the CC BY 4.0 label is doubtful for those parts. Use it only as a cross-check against Showdown, never as a primary source.

## Data source rules

- **Whitelist only. No open web scraping.** Allowed: Showdown data files (MIT), pokemon-champions-data (CC BY 4.0, cross-check only), Bulbapedia mechanics pages (CC BY-NC-SA, with attribution), Smogon monthly stats, and Pikalytics/Limitless **only if their terms allow it**.
- Check each source's terms before ingesting and record the findings in `docs/DATA_SOURCES.md`.
- **Never bulk-copy prose** from sources without an open license (Serebii, Smogon strategy write-ups, Pikalytics articles). Facts and stats through permitted exports are fine.
- Say what is and isn't verified, especially where Champions differs from mainline games.
- Damage calc: research porting the formula to Python and testing it against `@smogon/calc` vs calling `@smogon/calc` through Node. Document known gaps honestly (e.g. reported missing item modifiers like Life Orb in Champions mode). **Ask before installing Node.**

## Stack

Python 3.12 in a project-local venv (`.venv/`) · Flask REST API · PostgreSQL + pgvector in Docker (small memory limits) · Gemini API free tier (generation + embeddings) during dev · hybrid retrieval (keyword + vector) + reranking · JSON-schema structured outputs · LangGraph agent · lightweight knowledge graph (Postgres tables or networkx, not Neo4j, on 8 GB) · eval harness + LLM-as-judge · Docker · Cloud Run via Terraform · Cloud Logging · Vertex AI (phase 11).

**Machine constraints:** Mac mini M2, 8 GB RAM. Keep everything light. No local LLMs. Before suggesting any local embedding model or reranker, state its memory footprint.

## Phases (one at a time; don't start the next until Adem says "go")

0. Setup, repo, minimal GitHub Actions CI, data source research + `docs/DATA_SOURCES.md`, golden set (25–40 cases, built together; rubric written together)
1. Structured data: Postgres schema, ingestion of facts + legality lists with regulation tags, data validation tests
2. Deterministic tools: stat calc (SP), type effectiveness, speed tiers, legality, damage calc, all unit tested
3. Unstructured ingestion, chunking, embeddings, pgvector
4. Retrieval: vector baseline metrics, then hybrid, then reranking (before/after metrics), regulation filtering
5. Grounded answers with citations + JSON-schema output; answer-quality and grounding evals
6. Flask REST API: Q&A, team analysis, health check
7. LangGraph agent: tool planning, guardrails, tool-selection accuracy eval
8. Knowledge graph: entities, relationships, weighted teammate edges; graph + vector fusion measured on golden set
9. Full evaluation report (optionally RAGAS) + monthly data refresh job design
10. Docker, Cloud Run via Terraform, Cloud Logging, monitoring, scheduled refresh
11. Vertex AI migration; compare quality, latency, cost
12. README with architecture diagram, data-source table, final metrics, limitations, demo script

## Phase workflow

- **Start of phase:** explain in plain words what we'll build and why.
- **During:** write tests every phase. CI must pass before a phase is done.
- **End of phase:**
  1. Run tests and relevant evals.
  2. Commit as `phase N: ...` on a feature branch and push.
  3. Open a PR titled `phase N: ...` (via `gh pr create` locally, or the GitHub integration in cloud sessions).
  4. Add a section to `docs/BUILD_LOG.md`: what was built, key trade-offs, before/after metrics if relevant, 3 interview questions with short model answers.
  5. Give Adem **one command** to see the result.
  6. Give a **3-question quiz** where Adem explains concepts back in his own words. Correct mistakes plainly.
- Adem reviews and merges the PR himself, then says "go".

## Golden set

- 25–40 cases: mechanics, meta, team analyses, trick questions (Pokémon illegal this regulation, Tera questions, made-up moves) where the right answer is a refusal or correction.
- Each case has an expected answer and source. Auto-check against structured data wherever possible.
- The answer-quality rubric for LLM-as-judge is written **with** Adem (he graded LLM outputs/RLHF professionally).

## Working rules

- **Never ask Adem to hand-edit files.** Give complete, ready-to-run commands or full file contents.
- **Ask before** anything that could cost money or touch accounts: API keys, paid APIs, Google Cloud resources/billing, system-wide installs. Check current pricing and free tiers instead of guessing. Prefer free/local options. Set up a **billing budget alert before any GCP resource** is created.
- Check current package versions before installing (`pip index versions <pkg>`). Check current docs for fast-moving libraries (LangGraph, google-genai, pgvector). Prefer boring, well-documented choices.
- Small files, clear names, comments that explain *why*.
- **Be honest about results:** if retrieval or answers are bad, show the metrics and fix them.
- **Secrets stay out of git:** `.env` is ignored, `.env.example` is committed.

## Teaching notes (Adem's background)

Knows Python, SQL/MySQL, Java/Spring Boot, Git, GitHub Actions, some React. Has used the Gemini API, graded LLM outputs (RLHF/rubrics), deployed to Cloud Run with Terraform. **New to:** embeddings, vector DBs, RAG, LangGraph/LangChain, Flask, knowledge graphs, Vertex AI. Analogies to Spring Boot (Flask blueprints ≈ controllers) and MySQL (Postgres differences) help.
