// Validate the teams in tests/fixtures/legality_teams.json with Showdown's own
// TeamValidator and record its verdicts in tests/fixtures/showdown_validation.json.
// Our Python legality checker is tested against these. Runs in Docker via
// `make fixtures`, using the Showdown build that `make snapshot` creates.
'use strict';

const fs = require('fs');
const path = require('path');

const SHOWDOWN_DIR = process.env.SHOWDOWN_DIR;
const ROOT = process.argv[2] || '/work';
const {Teams, TeamValidator} = require(path.join(SHOWDOWN_DIR, 'dist/sim'));
const FORMATS = {doubles: 'gen9championsvgc2026regmc', singles: 'gen9championsbssregmc'};

const {teams} = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests/fixtures/legality_teams.json')));
const results = {};
for (const t of teams) {
	const team = Teams.import(t.text);
	const problems = new TeamValidator(FORMATS[t.game_type]).validateTeam(team) || [];
	results[t.id] = {legal: problems.length === 0, problems};
}
fs.writeFileSync(
	path.join(ROOT, 'tests/fixtures/showdown_validation.json'),
	JSON.stringify({meta: {validator: 'Pokémon Showdown TeamValidator'}, results}, null, 1) + '\n'
);
console.log(`validated ${teams.length} teams`);
