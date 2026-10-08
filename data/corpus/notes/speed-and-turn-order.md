---
title: Speed and turn order
regulation: M-C
written: 2026-10-08
sources:
  - {source: smogon_calc, ref: "calc/src/mechanics/util.ts getFinalSpeed"}
  - {source: showdown, ref: "data/mods/champions/scripts.ts getActionSpeed"}
---
# Speed and turn order

## Who moves first
Moves with higher priority always go first (for example Fake Out, Extreme Speed, Sucker Punch and Protect have positive priority). Among moves of the same priority, the Pokémon with higher Speed moves first. Equal Speed is decided at random.

## Speed modifiers
- Tailwind doubles the Speed of the user's side for a few turns.
- Choice Scarf multiplies the holder's Speed by 1.5.
- Paralysis halves Speed.
- Weather abilities double Speed in their weather: Chlorophyll (sun), Swift Swim (rain), Sand Rush (sandstorm), Slush Rush (snow).
- Stat stages apply too: +1 Speed is 1.5×, -1 is about 0.67×.

## Trick Room
Under Trick Room, slower Pokémon move first within the same priority bracket. Speed-lowering natures and 0 Speed Stat Points are common on Trick Room teams.
