// Exercises the bundled client policy against the same examples as Python.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const store = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
const doc = { documentElement: { dataset: {} }, addEventListener: () => {}, querySelector: () => null, querySelectorAll: () => [] };
const ctx = { window: {}, document: doc, localStorage: store, navigator: { onLine: true }, URL, console, setTimeout, clearTimeout, AbortController };
vm.createContext(ctx);
const base = 'android/app/src/main/assets/www/';
vm.runInContext(fs.readFileSync(base + 'core.js', 'utf8'), ctx);
vm.runInContext(fs.readFileSync(base + 'views.js', 'utf8'), ctx);
const PR = ctx.window.PR;
for (const c of JSON.parse(fs.readFileSync('tests/competition_cases.json'))) {
  assert.equal(PR.competitionAllowed(c.record), c.allowed, JSON.stringify(c.record));
}
const f = (id, league) => ({id, country:'England', league, home:'A', away:'B', sels:[], kickoff:'2026-11-04 12:00'});
const d = PR.indexData({ fixtures:[f('league','Premier League'), f('cup','FA Cup')],
  safe:{bets:[f('l','Premier League'), f('c','FA Cup')], today:{bets:[f('l','Premier League'), f('c','FA Cup')], groups:[{bets:[f('c','FA Cup')]}]}},
  shortlist:{primary:[f('l','Premier League'), f('c','FA Cup')], x12:[f('c','FA Cup')]},
  strong_markets:{bets:[f('l','Premier League'), f('c','FA Cup')]}});
assert.equal(d.fixtures.length, 1);
assert.equal(d.safe.bets.length, 1);
assert.equal(d.safe.today.bets.length, 1);
assert.equal(d.safe.today.groups[0].bets.length, 0);
assert.equal(d.shortlist.primary.length, 1);
assert.equal(d.shortlist.x12.length, 0);
assert.equal(d.strong_markets.bets.length, 1);

// The Live tab talks to the upstream day feed directly, so it must apply the same policy.
PR.state.data = d; PR.state.tab = 'bets'; PR.state.liveAll = null;
PR.getJson = async () => ({Stages:[
  {Cnm:'England', Snm:'Premier League', Ccd:'england', Scd:'premier-league', Events:[{Eid:'1', Eps:"40'", Tr1:'0', Tr2:'0', T1:[{Nm:'A'}], T2:[{Nm:'B'}]}]},
  {Cnm:'England', Snm:'FA Cup', Ccd:'england', Scd:'fa-cup', Events:[{Eid:'2', Eps:"40'", Tr1:'0', Tr2:'0', T1:[{Nm:'C'}], T2:[{Nm:'D'}]}]},
  {Cnm:'England', Snm:'Premier League', Ccd:'england', Scd:'premier-league', Events:[{Eid:'3', Eps:"40'", Tr1:'0', Tr2:'0', T1:[{Nm:'A U21'}], T2:[{Nm:'B'}]}]}
]});
PR.render = () => {}; PR.statusLine = () => {};
PR.live.refresh(true).then(() => {
  assert.equal(PR.state.liveAll.length, 1);
  assert.equal(PR.state.liveAll[0].eid, '1');
  console.log('Competition policy and live-feed UI tests passed');
}).catch((e) => { console.error(e); process.exitCode = 1; });
for (const c of JSON.parse(fs.readFileSync('tests/recommendation_cases.json'))) {
  assert.equal(!PR.isDropped(c.sel), c.allowed, `recommendation ${c.sel}`);
}
