---
title: Damage modifiers that matter in doubles
regulation: M-C
written: 2026-10-08
sources:
  - {source: showdown, ref: "data/mods/champions/scripts.ts modifyDamage (spread modifier)"}
  - {source: smogon_calc, ref: "calc/src/mechanics/champions.ts (screens, Helping Hand, Friend Guard)"}
---
# Damage modifiers that matter in doubles

## Spread moves
Moves that hit more than one target, such as Earthquake, Rock Slide, Heat Wave and Dazzling Gleam, deal 0.75× damage to each target when they hit more than one Pokémon. In singles, or if only one target remains, they deal full damage.

## Screens
Reflect halves physical damage and Light Screen halves special damage in singles. In doubles they reduce damage to about two-thirds (a 2732/4096 multiplier). Aurora Veil reduces both physical and special damage by the same amounts. Critical hits ignore screens. Brick Break and Psychic Fangs remove Reflect, Light Screen and Aurora Veil before dealing damage.

## Support moves and abilities
Helping Hand boosts the partner's move power by 1.5×. Friend Guard reduces damage the partner takes to 0.75×.

## Exact numbers
Exact damage ranges depend on stats, items, abilities and field conditions; use a damage calculation rather than estimating.
