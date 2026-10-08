# Data sources

Last reviewed: **2026-10-08**. Every record and chunk we store carries `source`, `license`, `regulation`, and `retrieved_at`. Nothing is ingested unless it appears here **and** in `src/pokechamp/sources.py` (a test keeps the two in sync).

**Rule:** facts and stats from permitted sources are fine. Prose is only copied from openly licensed sources, with attribution. No open-web scraping.

## Summary

| Key | Source | License / terms | Status | What we use it for |
|---|---|---|---|---|
| `showdown` | [Pokémon Showdown](https://github.com/smogon/pokemon-showdown) | MIT (verified: `LICENSE`) | ✅ approved | Primary source of facts: base stats, types, abilities, Champions legality, learnsets, items, move changes, mechanics code |
| `smogon_calc` | [@smogon/calc](https://github.com/smogon/damage-calc) (npm 0.12.0) | MIT (verified: `LICENSE`) | ✅ approved | Reference outputs: our Python port matches 78/78 scenarios roll for roll |
| `project_notes` | [data/corpus/notes/](../data/corpus/notes) | Project-authored; summarizes the MIT sources each note cites | ✅ approved | Mechanics explanations for RAG (SP, status, formats, Mega, move changes) |
| `community_data` | [otterlyclueless/pokemon-champions-data](https://github.com/otterlyclueless/pokemon-champions-data) | CC BY 4.0 (verified: `LICENSE`), see caveats | 🔎 reference only | Cross-check only |
| `bulbapedia` | [Bulbapedia](https://bulbapedia.bulbagarden.net/wiki/Bulbapedia:Copyrights) | CC BY-NC-SA 2.5 (per search results; page not opened) | ⏳ pending | Mechanics prose for RAG, with attribution |
| `smogon_stats` | [smogon.com/stats](https://www.smogon.com/stats/) | No explicit license found yet | ⏳ pending | Monthly usage %, sets, teammates |
| `pikalytics` | [Pikalytics](https://www.pikalytics.com) | Terms not found | ⏳ pending | Usage only if terms allow |
| `limitless` | [Limitless API](https://docs.limitlesstcg.com/developer.html) | Public API, terms not found | ⏳ pending | Tournament teams only if terms allow |

**Not allowed (no open license, so no copying prose):** Serebii, Smogon strategy write-ups (analyses), Pikalytics articles, Game8, Victory Road, Pokémon Zone. We may *read* them to sanity-check a fact, but nothing from them is stored.

**Pokémon IP:** names, sprites and game data belong to Nintendo / Creatures / GAME FREAK / The Pokémon Company. The open licenses above cover each project's own code and compilation work, not the franchise. This is a non-commercial portfolio project; we store no sprites or official artwork.

## How each source was checked

### `showdown`: Pokémon Showdown (MIT) ✅
- License: MIT, `Copyright (c) 2011-2026 Guangcong Luo and other contributors`. Keep the notice when redistributing derived data.
- Champions support: `config/formats.ts` has `[Gen 9 Champions] VGC 2026 Reg M-C` (doubles), `BSS Reg M-C` (singles), and the same for Reg M-B. The `champions` mod is the current regulation (M-C); `championsregmb` is M-B.
- Facts read directly from code on 2026-10-08:
  - **Stat Points:** 66 total (`sim/dex-formats.ts`), max 32 per stat and IVs fixed at 31 (`sim/team-validator.ts`).
  - **Stat formula at level 50** (`data/mods/champions/scripts.ts`): `HP = base + SP + 75`; other stats = `floor((base + SP + 20) × nature)`.
  - **Rules** (`data/mods/champions/rulesets.ts`, Flat Rules): level 50, Species Clause, Item Clause = 1, Mythicals and Restricted Legendaries banned, bring 6 and pick 4 (doubles) or 3 (singles).
  - **No Terastallization:** `canTerastallize` returns `null`. Mega Evolution works through the held Mega Stone.
  - **Status changes:** full paralysis 1/8 (mainline 1/4); sleep 1–2 turns (mainline 1–3); freeze has a 25% thaw chance per turn and a guaranteed thaw by turn 3.
  - **Moves:** 23 moves have changed power or accuracy. The PP rule differs from mainline (`calculatePP`).
  - **Roster:** M-C has 349 legal entries (including forms and Megas) vs 314 in M-B. M-C adds 35 entries (23 new species, Alolan Persian, 6 new Megas, and some forms); nothing was removed.
- **How we ingest it (phase 1):** `make snapshot` fetches the pinned commit with git, then builds Showdown and runs `tools/showdown_export/export.js` inside a `node:22.23.3-alpine` container. Showdown's own `Dex` merges the Champions patches, and its `TeamValidator` decides legality and learnsets. The output, `data/snapshots/showdown_champions.json` (~1.5 MB, MIT), is committed, so CI and fresh clones need no Node, and each refresh is a reviewable diff. `make ingest` loads it into Postgres in one transaction. Every row references an `ingestion_runs` row that records the source, license, commit SHA and export time.
- **Current snapshot:** showdown@`3065d24d698bc7f88a401c6e6d0cb42e5684d1ea` (2026-10-08). It has 1,371 species (382 legal: the 349 regulation entries plus 33 cosmetic or in-battle forms), 937 moves (515 legal), 577 items (166 legal), 317 abilities, and 17,364 learnset rows.
- **Reproducibility check:** the Docker export and a direct Node export produced identical JSON (apart from the timestamp).
- **Excluded on purpose:** CAP, Custom, LGPE, Future and Gigantamax placeholder entries. Real Pokémon that aren't in Champions are kept with `legal = false` and a reason, so the assistant can tell "not in this regulation" apart from "doesn't exist".

### RAG corpus (phase 3)
- **Showdown descriptions** (`data/text/*.ts`, MIT) for legal moves (515), abilities that a legal Pokémon can have (215), and legal items (166). The export uses Showdown's Champions-specific text where it exists (17 moves, 2 abilities, 1 item). For the 18 entries whose behavior the Champions mod changes *without* updated text, the chunk says so explicitly.
- **Project notes** (`data/corpus/notes/`, 8 files): short mechanics explanations, each listing the Showdown/@smogon/calc source it was verified from in its front matter.
- Not yet included: Bulbapedia (terms pending; the sandbox can't reach it).

### `smogon_calc`: @smogon/calc (MIT) ✅
- License: MIT (`Copyright (c) 2013-2025 Honko and other contributors`). Latest npm version is 0.12.0; the repo was last updated 2026-10-08.
- It has a dedicated Champions mode (`calc/src/mechanics/champions.ts`, treated as "gen 0"), and its Champions stat formula matches Showdown's.
- **The Life Orb gap (verified 2026-10-08):** third parties reported missing item modifiers like Life Orb in Champions mode. In 0.12.0 Life Orb **is** applied (the fixture `lifeorb-extremespeed` shows "Life Orb Dragonite … 64-75"), so the gap was real only in older versions.
- **How we use it:** `src/pokechamp/tools/damage.py` is a Python port of `calculateChampions`. `make fixtures` runs the real `@smogon/calc@0.12.0` in a `node:22.23.3-alpine` container on 79 scenarios (`tests/fixtures/damage_scenarios.json`) and records its answers. All 78 supported scenarios match roll for roll, and 68 of 68 comparable KO descriptions match word for word. There's **no Node install on your Mac**.
- **Known gaps in our port (deliberate refusals, not silent errors):** multi-hit moves, Parental Bond, Forecast, Electromorphosis, Stakeout, Plus/Minus, Rivalry, Klutz, Protosynthesis/Quark Drive, terrain seeds, Metronome (item), and these moves: Assurance, Terrain Pulse, Fling, Triple Axel, Shell Side Arm, Steel Roller, Poltergeist, Aura Wheel, Raging Bull, Nature Power, Lash Out, Pain Split, Final Gambit, fixed-damage moves, Grav Apple, Misty Explosion, Flying Press, Nihil Light. Each raises `UnsupportedCalculation`.
- **Bug we found in @smogon/calc:** its Lash Out check (`countBoosts(...) < 0`) can never be true, because `countBoosts` only sums positive boosts. We refuse Lash Out rather than copy the bug.

### `community_data`: pokemon-champions-data (CC BY 4.0) 🔎
- `LICENSE`: "Creative Commons Attribution 4.0 International. Copyright (c) 2026 Pokemon Champions Data Contributors."
- **Stale:** `meta/version.json` says `lastUpdated: 2026-04-16` (Reg M-A, 258 entries). It has none of the M-C additions (no Rillaboom, Baxcalibur or Arboliva).
- **Mixed origin:** move stats, PP and learnsets were "scraped April 16 2026" from Serebii. The CC BY license can't grant rights the compiler didn't have, so we treat it as a cross-check only.
- Its own `mechanics/stat-formula.md` says the SP formula is "under verification". Showdown's code is more authoritative, so we don't use the repo's formula.
- **Cross-check (2026-10-08):** 256 of its 258 entries matched our Showdown snapshot, with **0 base-stat and 0 type mismatches**. The 2 unmatched were naming differences (Paldean Tauros has three breeds in Showdown; "Mega Meowstic" is split into male and female). Its "Floette" is Showdown's Floette-Eternal.

### `bulbapedia`: Bulbapedia (CC BY-NC-SA 2.5) ⏳
- Bulbapedia's copyright page (as shown in [search results](https://bulbapedia.bulbagarden.net/wiki/BP:Copyrights)) puts content edited since 2007-04-15 under CC BY-NC-SA 2.5. Some pages copied from Wikipedia are under the GFDL instead.
- What that means for us: attribution is required, use must be **non-commercial**, and derivatives must be **share-alike**. Stored chunks keep a page URL and revision ID, and the README credits Bulbapedia. Any repo file containing Bulbapedia text inherits CC BY-NC-SA, so chunks are kept out of git (they live only in the database).
- **Still to verify:** the page couldn't be opened from the cloud sandbox (host blocked). Also check whether Bulbapedia allows automated fetching. Bulbagarden's MediaWiki API and robots.txt decide *how* we fetch, not just whether.

### `smogon_stats`: Smogon usage stats ⏳
- Data shape (from third-party projects that consume it): `https://www.smogon.com/stats/{YYYY-MM}/chaos/{format}-{rating}.json`, with files switching from `.json.gz` to plain `.json` from 2026-08. Format IDs are `gen9championsvgc2026regmc` (doubles) and `gen9championsbssregmc` (singles). The first M-C month is 2026-09.
- **Not verified directly:** smogon.com is blocked from the cloud sandbox. No explicit license was found; these are public statistics generated from Showdown ladder games. We store only aggregate numbers (facts), never forum prose.

### `pikalytics` ⏳ and `limitless` ⏳
- Pikalytics: its Ko-fi page mentions terms of service, but I couldn't read them. **Not used until verified.**
- Limitless: the public developer API (docs.limitlesstcg.com) needs no key for most endpoints, has rate limits, and gives keys "only to public-facing projects that have a legitimate use-case". Terms not read. **Not used until verified.**

## Open verification tasks (run from your Mac; the cloud sandbox blocks these hosts)

```bash
# 1. Does Smogon publish Champions stats, and what are the exact file names?
curl -s https://www.smogon.com/stats/2026-09/chaos/ | grep -o 'gen9champions[a-z0-9-]*\.json' | sort -u

# 2. Open these and note what they say about reuse and automated access:
open https://bulbapedia.bulbagarden.net/wiki/Bulbapedia:Copyrights
open https://bulbapedia.bulbagarden.net/robots.txt
open https://www.pikalytics.com            # look for Terms / ToS link in the footer
open https://docs.limitlesstcg.com/developer.html
```

Paste the results back and I'll update this file and flip statuses from ⏳ to ✅ or ❌.

## Regulation timeline

| Code | Start (UTC) | End (UTC) | Showdown formats | Evidence |
|---|---|---|---|---|
| M-A | 2026-04-08 | 2026-06-17 | none (predates per-regulation formats) | Launch coverage, pokemon.com M-B announcement |
| M-B | 2026-06-17 | 2026-09-09 02:00 | `gen9championsvgc2026regmb`, `gen9championsbssregmb` | Showdown `championsregmb` mod |
| M-C | 2026-09-09 02:00 | 2026-12-02 (Serebii/Vice; unofficial) | `gen9championsvgc2026regmc`, `gen9championsbssregmc` | Showdown `champions` mod |

The current ranked season is M-7 (about 2026-10-07 to 2026-11-04/05; sources differ by a day).
