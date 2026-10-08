"""Lookup tables for the damage calculator.

Copied from @smogon/calc 0.12.0 (MIT, calc/src/items.ts and
mechanics/champions.ts). Kept separate from the formula so the engine stays
readable and the tables can be diffed when @smogon/calc updates.
"""

# Type-boosting held items: x1.2 base power (4915/4096) for moves of that type.
ITEM_BOOST_TYPE = {
    "Draco Plate": "Dragon", "Dragon Fang": "Dragon", "Dread Plate": "Dark",
    "Black Glasses": "Dark", "Earth Plate": "Ground", "Soft Sand": "Ground",
    "Fist Plate": "Fighting", "Black Belt": "Fighting", "Flame Plate": "Fire",
    "Charcoal": "Fire", "Icicle Plate": "Ice", "Never-Melt Ice": "Ice",
    "Insect Plate": "Bug", "Silver Powder": "Bug", "Iron Plate": "Steel",
    "Metal Coat": "Steel", "Meadow Plate": "Grass", "Rose Incense": "Grass",
    "Miracle Seed": "Grass", "Mind Plate": "Psychic", "Odd Incense": "Psychic",
    "Twisted Spoon": "Psychic", "Fairy Feather": "Fairy", "Pixie Plate": "Fairy",
    "Sky Plate": "Flying", "Sharp Beak": "Flying", "Splash Plate": "Water",
    "Sea Incense": "Water", "Wave Incense": "Water", "Mystic Water": "Water",
    "Spooky Plate": "Ghost", "Spell Tag": "Ghost", "Stone Plate": "Rock",
    "Rock Incense": "Rock", "Hard Stone": "Rock", "Toxic Plate": "Poison",
    "Poison Barb": "Poison", "Zap Plate": "Electric", "Magnet": "Electric",
    "Silk Scarf": "Normal", "Pink Bow": "Normal", "Polkadot Bow": "Normal",
}  # fmt: skip

# Resist berries: halve a super-effective hit of that type (Chilan: any Normal hit).
BERRY_RESIST_TYPE = {
    "Chilan Berry": "Normal", "Occa Berry": "Fire", "Passho Berry": "Water",
    "Wacan Berry": "Electric", "Rindo Berry": "Grass", "Yache Berry": "Ice",
    "Chople Berry": "Fighting", "Kebia Berry": "Poison", "Shuca Berry": "Ground",
    "Coba Berry": "Flying", "Payapa Berry": "Psychic", "Tanga Berry": "Bug",
    "Charti Berry": "Rock", "Kasib Berry": "Ghost", "Haban Berry": "Dragon",
    "Colbur Berry": "Dark", "Babiri Berry": "Steel", "Roseli Berry": "Fairy",
}  # fmt: skip

# Defender abilities that Mold Breaker switches off (champions.ts list).
MOLD_BREAKER_IGNORES = frozenset({
    "Aura Guard", "Armor Tail", "Aroma Veil", "Battle Armor", "Big Pecks", "Bulletproof",
    "Clear Body", "Contrary", "Damp", "Disguise", "Dry Skin", "Earth Eater", "Eelevate",
    "Filter", "Flash Fire", "Flower Veil", "Fluffy", "Friend Guard", "Fur Coat",
    "Grass Pelt", "Guard Dog", "Heatproof", "Heavy Metal", "Hyper Cutter", "Illuminate",
    "Immunity", "Inner Focus", "Insomnia", "Keen Eye", "Leaf Guard", "Levitate",
    "Light Metal", "Lightning Rod", "Limber", "Magic Bounce", "Magma Armor",
    "Marvel Scale", "Mirror Armor", "Motor Drive", "Multiscale", "Oblivious", "Overcoat",
    "Own Tempo", "Punk Rock", "Purifying Salt", "Queenly Majesty", "Sand Veil",
    "Sap Sipper", "Shell Armor", "Shield Dust", "Snow Cloak", "Solid Rock", "Soundproof",
    "Sticky Hold", "Storm Drain", "Sturdy", "Sweet Veil", "Tangled Feet", "Telepathy",
    "Thermal Exchange", "Thick Fat", "Unaware", "Vital Spirit", "Volt Absorb",
    "Water Absorb", "Water Bubble", "Water Veil", "White Smoke",
})  # fmt: skip

# Things @smogon/calc models that this port does NOT (yet). The calculator
# refuses instead of returning a number that silently ignores them.
UNSUPPORTED_ABILITIES = frozenset({
    "Parental Bond",  # second hit
    "Forecast",  # Castform type change
    "Electromorphosis", "Stakeout", "Plus", "Minus",  # need battle-state toggles
    "Rivalry",  # needs genders
    "Klutz",  # item suppression
    "Protosynthesis", "Quark Drive",  # booster/terrain state
})  # fmt: skip
UNSUPPORTED_ITEMS = frozenset({
    "Electric Seed", "Grassy Seed", "Misty Seed", "Psychic Seed",  # seed boosts
    "Metronome",  # needs consecutive-use count
})  # fmt: skip
UNSUPPORTED_MOVES = frozenset({
    "Assurance", "Terrain Pulse", "Fling", "Triple Axel", "Shell Side Arm",
    "Steel Roller", "Poltergeist", "Aura Wheel", "Raging Bull", "Nature Power",
    "Lash Out", "Struggle", "Pain Split", "Final Gambit",
    "Seismic Toss", "Night Shade", "Dragon Rage", "Sonic Boom",
    "Grav Apple", "Misty Explosion", "Flying Press", "Nihil Light",
})  # fmt: skip
