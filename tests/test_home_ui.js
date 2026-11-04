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
vm.runInContext(code, context);
vm.runInContext(fs.readFileSync(base + 'pages.js', 'utf8'), context);
const PR = context.window.PR;
const today = PR.ymd(PR.tzNow());
const fixture = (name, selections, data_ok = true) => ({ id: `${today}|England|${name}|Away`, date: today,
  kickoff: today + ' 23:59', home: name, away: 'Away', country: 'England', league: 'Test',
  data_ok, tier: 'main', sels: selections });
const selection = (code, p, odds = 1.3, diff = 0) => [code, p, p, .78, odds, diff, null, null];
const fixtures = [fixture('Qualifies', [selection('O15', .81)]),
  fixture('Nearly', [selection('O15', .7996)]),
  fixture('Low', [selection('O15', .9)], false),
  fixture('No price', [selection('O15', .9, null)]),
  fixture('Disagreement', [selection('O15', .9, 1.3, 1)]),
  fixture('Lower bar', [selection('O25', .60)])];
const id = fixtures[0].id;
const d = PR.indexData({ fixtures, safe: { today: { date: today, bets: [{ fixture: id, home: 'Qualifies', away: 'Away', sel: 'O15', p: .81, odds: 1.3 }], groups: [] } },
  shortlist: { counts: { analysed: 1, screened: 1 }, rules: {}, primary: [{ fixture: id, home: 'Qualifies', away: 'Away', country: 'England', league: 'Test', kickoff: today + ' 23:59', rank: 1, market: 'goals', label: 'Over 1.5 goals', sel: 'O15', p: .81, odds: 1.3 }] }, groups: {} });
PR.state.data = d;
const collections = PR.testCollections(d);
assert.equal(collections.all.length, 3);
assert.equal(collections.high.length, 2); // O2.5 at 60% is not "high probability"
assert.equal(collections.eighty.length, 1); // .7996 is never rounded into the 80% collection
assert.equal(collections.eighty[0].f.home, 'Qualifies');
PR.views.shortlist();
assert.match(view.innerHTML, /Qualifies v Away/);
assert.doesNotMatch(view.innerHTML, /appears after the next analysis run/);
PR.pages.advisor();
assert.match(view.innerHTML, /Qualifies/);
d.safe.today.date = '2000-01-01';
PR.pages.advisor();
assert.match(view.innerHTML, /No bets-of-the-day card is available for today/);
console.log('Home, shortlist and advisor UI regression tests passed');
