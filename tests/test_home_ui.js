// Run with: node tests/test_home_ui.js
// Exercise the real bundled normalizer, collection filters and rendered shortlist/advisor.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const store = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
const view = { innerHTML: '' };
const document = { documentElement: { dataset: {} }, addEventListener: () => {},
  querySelector: (s) => s === '#view' ? view : null, querySelectorAll: () => [] };
const context = { window: {}, document, localStorage: store, navigator: { onLine: true }, URL, console,
  setTimeout, clearTimeout, AbortController };
vm.createContext(context);
const base = 'android/app/src/main/assets/www/';
vm.runInContext(fs.readFileSync(base + 'core.js', 'utf8'), context);
let code = fs.readFileSync(base + 'views.js', 'utf8');
code = code.replace('  function homeLaunchpad(collections)', '  PR.testCollections = homeCollections;\n  function homeLaunchpad(collections)');
code = code.replace('  function homeBoard(d, collections) {', '  PR.testHomeBoard = homeBoard;\n  function homeBoard(d, collections) {');
vm.runInContext(code, context);
let pages = fs.readFileSync(base + 'pages.js', 'utf8');
pages = pages.replace('  function matchForm(parts, f) {', '  PR.testMatchForm = matchForm;\n  function matchForm(parts, f) {');
pages = pages.replace('  function briefingPicks() {', '  PR.testBriefingPicks = briefingPicks;\n  function briefingPicks() {');
vm.runInContext(pages, context);
const PR = context.window.PR;
const today = PR.ymd(PR.tzNow());
const fixture = (name, selections, data_ok = true) => ({ id: `${today}|England|${name}|Away`, date: today,
  kickoff: today + ' 23:59', home: name, away: 'Away', country: 'England', league: 'Test', div: 'E0',
  data_ok, q: data_ok ? 'High' : 'Low', tier: 'main', sels: selections });
const selection = (code, p, odds = 1.3, diff = 0) => [code, p, p, .78, odds, diff, null, null];
const fixtures = [fixture('Qualifies', [selection('O15', .81), selection('O05', .97), selection('U55', .88), selection('KO35', .91, 1.16)]),
  fixture('Nearly', [selection('O15', .7996)]),
  fixture('Low', [selection('O15', .9)], false),
  fixture('No price', [selection('O15', .9, null)]),
  fixture('Too short', [selection('O15', .9, 1.15)]),
  fixture('Not rounded up', [selection('O15', .9, 1.159)]),
  fixture('Malformed price', [selection('O15', .9, 'bad')]),
  fixture('Disagreement', [selection('O15', .9, 1.3, 1)]),
  fixture('Lower bar', [selection('O25', .60)])];
const id = fixtures[0].id;
const d = PR.indexData({ fixtures, safe: { today: { date: today, bets: [{ fixture: id, home: 'Qualifies', away: 'Away', sel: 'O15', p: .81, odds: 1.3 }], groups: [] } },
  shortlist: { counts: { analysed: 1, screened: 1 }, rules: {}, primary: [{ fixture: id, home: 'Qualifies', away: 'Away', country: 'England', league: 'Test', kickoff: today + ' 23:59', rank: 1, market: 'goals', label: 'Over 1.5 goals', sel: 'O15', p: .81, odds: 1.3 }] }, groups: {} });
const old = PR.indexData({fixtures: [], picks: {BTTS: [{fixture: 'old'}], O15: []}, tracker: {BTTS: {settled: 4}}});
assert.equal(old.picks.BTTS.length, 1);
assert.equal(old.tracker.BTTS.settled, 4);
PR.state.data = d;
const collections = PR.testCollections(d);
assert.equal(collections.all.length, 3);
assert.equal(collections.high.length, 2); // O2.5 at 60% is not "high probability"
assert.equal(collections.eighty.length, 6); // multiple priced markets, including restricted, low-data and disagreement
assert.equal(collections.eighty.filter((r) => r.f.home === 'Qualifies').length, 4);
assert(collections.eighty.some((r) => r.s.sel === 'KO35' && r.s.odds === 1.16));
for (const name of ['No price', 'Too short', 'Not rounded up', 'Malformed price']) assert(!collections.eighty.some((r) => r.f.home === name));
assert(!collections.eighty.some((r) => r.f.home === 'Nearly')); // .7996 never rounds up
assert.equal(PR.strictShortlist(d).length, 1);
// Strict Advisor and Shortlist enforce the same price, quality, probability and timing gates.
const cases = [
  fixture('Valid floor', [selection('O15', .84, 1.16)]),
  fixture('Price too low', [selection('O15', .9, 1.15)]),
  fixture('Price too high', [selection('O15', .9, 1.91)]),
  fixture('Fair price fails', [selection('O15', .8, 1.18)]),
  fixture('Probability fails', [selection('O25', .54, 1.9)]),
  fixture('Quality fails', [selection('O15', .9, 1.3)]),
  fixture('Already started', [selection('O15', .9, 1.3)]),
];
cases[5].q = 'Low'; cases[6].kickoff = today + ' 00:00';
const checked = PR.indexData({fixtures: cases, shortlist: {primary: cases.map((f) => ({fixture:f.id, sel:f.sels[0][0], odds:f.sels[0][4], kickoff:f.kickoff}))}});
assert.deepEqual(Array.from(PR.strictShortlist(checked), (x) => x.fixture), [cases[0].id]);
PR.state.homeTab = 'eighty';
PR.addBtn = () => 'SHOULD_NOT_RENDER_ADD';
const board = PR.testHomeBoard(d, collections);
assert.match(board, /Analysis only, not a shortlist/);
assert.match(board, /Card-count proxy, not verified bookings/);
assert.doesNotMatch(board, /SHOULD_NOT_RENDER_ADD/);
assert.match(board, /6 markets · 3 matches/);
assert.match(board, /SportyBet price of at least 1\.16/);
PR.views.shortlist();
assert.match(view.innerHTML, /Qualifies v Away/);
assert.match(view.innerHTML, /BTTS yes/);
assert.match(view.innerHTML, /total or team corners overs/);
assert.match(view.innerHTML, /probability × odds must be at least 0\.95/);
assert.doesNotMatch(view.innerHTML, /appears after the next analysis run/);
// An old payload cannot sneak missing-price, low-data, restricted, outlier or duplicate picks into the Advisor.
for (const [name, sel] of [['Low', 'O15'], ['No price', 'O15'], ['Disagreement', 'O15'], ['Qualifies', 'O05'], ['Qualifies', 'O15']]) {
  const f = fixtures.find((x) => x.home === name);
  d.shortlist.primary.push({ fixture:f.id, sel, kickoff:f.kickoff, home:f.home, away:f.away });
}
assert.equal(PR.strictShortlist(d).length, 1);
PR.pages.advisor();
assert.match(view.innerHTML, /Strict Advisor shortlist/);
assert.match(view.innerHTML, /Qualifies/);
assert.doesNotMatch(view.innerHTML, /Biggest model-vs-market edges|High-confidence list/);
assert.equal(PR.testBriefingPicks().length, 1);
d.shortlist.primary = [];
PR.pages.advisor();
assert.match(view.innerHTML, /No strict Advisor selections/);
// Previously published current-day archives must hide paused fixtures without rewriting history.
const archived = (id, league) => ({ id, kickoff: today + ' 10:00', country: 'England', league,
  competition: league, home: id, away: 'Opponent', xg: [1,1], p: { O25: .5 },
  score: { hg: 1, ag: 0 }, bets: [] });
const day = { summary: { n: 2, finished: 2 }, fixtures: [archived('League Club', 'Premier League'), archived('Cup Club', 'FA Cup')] };
PR.state.days[today] = day;
PR.pages.day({ date: today });
assert.match(view.innerHTML, /League Club/);
assert.doesNotMatch(view.innerHTML, /Cup Club/);
assert.match(view.innerHTML, /1 matches · 1 finished/);
assert.equal(day.fixtures.length, 2); // stored archive remains intact
// Long names wrap in structured Form cards instead of overflowing a four-column table.
PR.state.teams[PR.slug('E0')] = {teams: {Qualifies: {last: [{date:'2026-10-01', opp:'A very long football club and academy name', venue:'H', gf:2, ga:1, league:'A very long competition name'}]}}};
const form = [];
PR.testMatchForm(form, fixtures[0]);
const formHtml = form.join('');
assert.match(formHtml, /form-result-main/);
assert.match(formHtml, /A very long football club and academy name/);
assert.match(formHtml, /A very long competition name/);
assert.doesNotMatch(formHtml, /<table/);
const css = fs.readFileSync(base + 'app.css', 'utf8');
assert.match(css, /\.form-opponent\s*\{[^}]*overflow-wrap:anywhere/);
assert.match(css, /\.form-result-main\s*\{[^}]*minmax\(0, 1fr\)/);
const oldDate = '2020-01-01';
PR.state.days[oldDate] = day;
PR.pages.day({ date: oldDate });
assert.match(view.innerHTML, /Cup Club/); // past history remains available
console.log('Home, shortlist, advisor and day UI regression tests passed');
