// Export Pokémon Showdown's Champions data (current regulation) to one JSON snapshot.
//
// Why Node at all? Showdown's data lives in TypeScript files where each mod is a
// *patch* on the base game ("inherit: true"). Re-implementing that merge in
// Python would be fragile, so we let Showdown's own Dex + TeamValidator do it
// and only hand plain JSON to Python. This runs inside a throwaway Docker
// container (see run.sh): nothing is installed on the host.
//
// Usage: SHOWDOWN_DIR=/path/to/built/showdown node export.js <commit-sha> > snapshot.json

'use strict';

const path = require('path');

const SHOWDOWN_DIR = process.env.SHOWDOWN_DIR;
const COMMIT = process.argv[2];
if (!SHOWDOWN_DIR || !COMMIT) {
	console.error('usage: SHOWDOWN_DIR=... node export.js <commit-sha>');
	process.exit(2);
}

const {Dex, TeamValidator} = require(path.join(SHOWDOWN_DIR, 'dist/sim'));

// Current regulation only (project scope). Update these three lines for M-D.
const REGULATION = 'M-C';
const MOD = 'champions';
const FORMATS = {doubles: 'gen9championsvgc2026regmc', singles: 'gen9championsbssregmc'};

// Fan-made or non-mainline entries we never want, not even as "exists but illegal".
const EXCLUDED_NONSTANDARD = new Set(['CAP', 'Custom', 'LGPE', 'Future']);

const dex = Dex.mod(MOD);
const text = dex.loadTextData();
// Species legality is the same in both formats (same Flat Rules), so one
// validator answers "can this Pokémon / move be used".
const validator = new TeamValidator(FORMATS.doubles);

// Showdown's own ID rule. We key every row by toID(name) so Python lookups can
// compute IDs from names; Showdown itself gives all 16 typed Hidden Powers the
// same id ('hiddenpower'), which would collide.
const toID = name => name.toLowerCase().replace(/[^a-z0-9]/g, '');

const byId = (a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
const keep = entry => entry.exists && !EXCLUDED_NONSTANDARD.has(entry.isNonstandard);

// Showdown says "X does not exist in Gen 9" for anything outside the Champions
// roster; reword it so users (and the LLM) aren't told a real Pokémon doesn't exist.
function readableProblem(name, problem) {
	if (!problem) return null;
	if (problem.includes('does not exist')) return `${name} is not available in Pokémon Champions (Reg ${REGULATION}).`;
	return problem.replace(/^.*?\(/, '(').replace(/^\([^)]*\)\s*/, `${name} `).trim();
}

function speciesProblem(species) {
	// Battle-only formes (Megas, Mimikyu-Busted...) can't be written on a team;
	// they are legal if the form they come from is legal and, for Megas, the
	// stone is legal.
	if (species.battleOnly) {
		const base = dex.species.get(Array.isArray(species.battleOnly) ? species.battleOnly[0] : species.battleOnly);
		const baseProblem = validator.checkSpecies({species: base.name}, base, base, {});
		if (baseProblem) return readableProblem(base.name, baseProblem);
		if (species.requiredItem && dex.items.get(species.requiredItem).isNonstandard) {
			return `${species.requiredItem} is not available in Pokémon Champions (Reg ${REGULATION}).`;
		}
		return null;
	}
	return readableProblem(species.name, validator.checkSpecies({species: species.name}, species, species, {}));
}

// Gmax entries are sprite placeholders, not Pokémon (and Dynamax isn't in Champions).
const isGmax = s => /Gmax$/.test(s.forme || '');

const species = dex.species.all().filter(s => keep(s) && !isGmax(s)).sort(byId).map(s => {
	const problem = speciesProblem(s);
	return {
		id: s.id,
		name: s.name,
		num: s.num,
		base_species: s.baseSpecies,
		forme: s.forme || null,
		types: s.types,
		base_stats: s.baseStats,
		abilities: s.abilities,
		weightkg: s.weightkg,
		battle_only: Boolean(s.battleOnly),
		required_item: s.requiredItem || null,
		is_mega: Boolean(s.isMega),
		legal: problem === null,
		illegal_reason: problem,
	};
});

const moves = dex.moves.all().filter(keep).map(m => ({
	id: toID(m.name),
	name: m.name,
	num: m.num,
	type: m.type,
	category: m.category,
	base_power: m.basePower,
	accuracy: m.accuracy === true ? null : m.accuracy, // null = never misses
	pp: m.pp, // already capped at 20 by the Champions mod's init()
	priority: m.priority,
	target: m.target,
	flags: Object.keys(m.flags).sort(),
	short_desc: text.Moves[m.id]?.shortDesc ?? null,
	legal: !m.isNonstandard,
	// Fields the damage calculator needs (phase 2).
	multihit: m.multihit === undefined ? null : [].concat(m.multihit), // [2] or [2, 5]
	has_secondary: Boolean(m.secondary || m.secondaries?.length), // Sheer Force
	recoil: Boolean(m.recoil), // Reckless
	has_crash_damage: Boolean(m.hasCrashDamage), // Reckless
	override_offensive_stat: m.overrideOffensiveStat || null, // Body Press: 'def'
	override_defensive_stat: m.overrideDefensiveStat || null, // Psyshock: 'def'
	ignore_defensive: Boolean(m.ignoreDefensive), // Sacred Sword
	will_crit: Boolean(m.willCrit), // Flower Trick, Wicked Blow
})).sort(byId);

const abilities = dex.abilities.all().filter(keep).sort(byId).map(a => ({
	id: a.id,
	name: a.name,
	short_desc: text.Abilities[a.id]?.shortDesc ?? null,
	legal: !a.isNonstandard,
}));

const items = dex.items.all().filter(keep).sort(byId).map(i => ({
	id: i.id,
	name: i.name,
	short_desc: text.Items[i.id]?.shortDesc ?? null,
	mega_stone: i.megaStone || null, // {"Garchomp": "Garchomp-Mega-Z"}
	legal: !i.isNonstandard,
}));

// Learnsets for team-legal species only. getMovePool over-approximates (it
// includes prevo and event moves); checkCanLearn is the validator's own answer.
const learnsets = {};
for (const s of species) {
	if (!s.legal || s.battle_only) continue;
	const sp = dex.species.get(s.id);
	learnsets[s.id] = [...dex.species.getMovePool(sp.id)]
		.filter(moveId => {
			const move = dex.moves.get(moveId);
			return !move.isNonstandard && validator.checkCanLearn(move, sp) === null;
		})
		.sort();
}

const natures = [...dex.natures.all()].sort(byId).map(n => ({
	name: n.name,
	plus: n.plus || null,
	minus: n.minus || null,
}));

// damageTaken codes: 0 = normal, 1 = weak (2x), 2 = resist (0.5x), 3 = immune.
const MULT = {0: 1, 1: 2, 2: 0.5, 3: 0};
const types = dex.types.all().filter(t => t.name !== 'Stellar' && !t.isNonstandard);
const typeChart = [];
for (const atk of types) {
	for (const def of types) {
		typeChart.push({attacking: atk.name, defending: def.name, multiplier: MULT[def.damageTaken[atk.name]]});
	}
}

const formats = Object.entries(FORMATS).map(([gameType, id]) => {
	const format = Dex.formats.get(id);
	const rules = Dex.formats.getRuleTable(format);
	return {
		id,
		name: format.name,
		game_type: gameType,
		team_size: rules.minTeamSize,
		picked_team_size: rules.pickedTeamSize,
		level: rules.adjustLevel,
		sp_total: rules.evLimit,
		sp_max_per_stat: 32, // hardcoded in sim/team-validator.ts, not a rule
		item_clause: rules.has('itemclause'),
		species_clause: rules.has('speciesclause'),
		banned: [...rules.keys()].filter(k => k.startsWith('-')).sort(),
	};
});

const snapshot = {
	meta: {
		source: 'showdown',
		source_url: 'https://github.com/smogon/pokemon-showdown',
		license: 'MIT',
		showdown_commit: COMMIT,
		exported_at: new Date().toISOString(),
		regulation: REGULATION,
		mod: MOD,
	},
	formats,
	species,
	moves,
	abilities,
	items,
	learnsets,
	natures,
	type_chart: typeChart,
};

process.stdout.write(JSON.stringify(snapshot, null, 1) + '\n');
