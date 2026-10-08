---
title: Stat Points (SP) in Pokémon Champions
regulation: M-C
written: 2026-10-08
sources:
  - {source: showdown, ref: "sim/dex-formats.ts (evLimit 66 for champions mods)"}
  - {source: showdown, ref: "sim/team-validator.ts (max 32 Stat Points per stat; IVs must be 31)"}
  - {source: showdown, ref: "data/mods/champions/scripts.ts statModify"}
---
# Stat Points (SP) in Pokémon Champions

## What replaced EVs
Pokémon Champions does not use EVs (Effort Values). Each Pokémon instead gets Stat Points: 66 SP in total, and at most 32 SP in any single stat. IVs are not customizable: every IV is fixed at 31. All ranked battles are played at level 50.

## How SP turn into stats
At level 50 each Stat Point adds exactly one point to the stat before the nature is applied:
- HP = base HP + SP + 75
- Every other stat = (base stat + SP + 20), multiplied by the nature (1.1 for a boosting nature, 0.9 for a hindering one, 1.0 otherwise), rounded down.

Example: Garchomp has base 102 Speed. With 32 SP in Speed and a Jolly nature: (102 + 32 + 20) × 1.1 = 169.4, so 169 Speed.

## Writing SP in a team export
Showdown's team format still writes the spread on the "EVs:" line, for example "EVs: 2 HP / 32 Atk / 32 Spe". In Champions those numbers are Stat Points, not EVs, so values like 252 are not valid.

## Common spreads
Because the cap is 32 per stat and 66 total, a fully offensive spread is 32 in an attacking stat, 32 in Speed and 2 left over. Two stats can be maxed, plus 2 spare points.
