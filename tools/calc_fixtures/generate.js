// Run @smogon/calc (pinned version, Champions mode = gen 0) on every scenario in
// tests/fixtures/damage_scenarios.json and write the reference answers to
// tests/fixtures/damage_expected.json. Our Python port must match these roll
// for roll. Runs in Docker via `make fixtures`; no Node on the host.
'use strict';

const fs = require('fs');
const path = require('path');
const calcPkg = require('@smogon/calc/package.json');
const {calculate, Generations, Pokemon, Move, Field} = require('@smogon/calc');

const ROOT = process.argv[2] || '/work';
const gen = Generations.get(0); // gen 0 = Pokémon Champions in @smogon/calc

function pokemon(spec) {
	return new Pokemon(gen, spec.species, {
		nature: spec.nature || 'Serious',
		evs: spec.sp || {}, // Champions: the EV slots hold Stat Points
		ability: spec.ability,
		item: spec.item,
		boosts: spec.boosts,
		status: spec.status || '',
		curHP: spec.cur_hp,
		abilityOn: spec.ability_on,
		alliesFainted: spec.allies_fainted,
	});
}

function side(s = {}) {
	return {
		isReflect: !!s.reflect, isLightScreen: !!s.light_screen, isAuroraVeil: !!s.aurora_veil,
		isHelpingHand: !!s.helping_hand, isFriendGuard: !!s.friend_guard, isTailwind: !!s.tailwind,
	};
}

const {scenarios} = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests/fixtures/damage_scenarios.json')));
const out = {};
for (const s of scenarios) {
	const f = s.field || {};
	const singles = s.spread === false || f.game_type === 'singles';
	try {
		const r = calculate(
			gen, pokemon(s.attacker), pokemon(s.defender), new Move(gen, s.move, {isCrit: !!s.crit}),
			new Field({
				gameType: singles ? 'Singles' : 'Doubles', weather: f.weather, terrain: f.terrain,
				attackerSide: side(f.attacker_side), defenderSide: side(f.defender_side),
			})
		);
		const dmg = typeof r.damage === 'number' ? Array(16).fill(r.damage) : r.damage;
		// kochance()/desc() throw on zero damage, so they're optional extras.
		const optional = fn => { try { return fn(); } catch (e) { return ''; } };
		out[s.id] = {
			rolls: Array.isArray(dmg[0]) ? null : dmg,
			multi: Array.isArray(dmg[0]),
			ko: optional(() => r.kochance().text),
			desc: optional(() => r.desc()),
		};
	} catch (e) {
		out[s.id] = {error: String(e.message || e)};
	}
}
const payload = {meta: {calc: `@smogon/calc@${calcPkg.version}`, generated_at: new Date().toISOString()}, results: out};
fs.writeFileSync(path.join(ROOT, 'tests/fixtures/damage_expected.json'), JSON.stringify(payload, null, 1) + '\n');
console.log(`wrote ${Object.keys(out).length} results with ${payload.meta.calc}`);
