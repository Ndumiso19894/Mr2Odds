// Run with: node tests/test_final_picks_ui.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const view = {innerHTML: ''};
const toastEl = {classList:{add(){}, remove(){}}};
const saved = {};
const document = {documentElement: {dataset: {}}, addEventListener: () => {}, querySelector: (s) => s === '#view' ? view : s === '#toast' ? toastEl : null, querySelectorAll: () => []};
const context = {window: {}, document, localStorage: {getItem: (k) => saved[k] || null, setItem: (k,v) => { saved[k] = v; }, removeItem: (k) => { delete saved[k]; }}, navigator: {onLine: true}, URL, console, setTimeout, clearTimeout, AbortController};
vm.createContext(context);
const base = 'android/app/src/main/assets/www/';
vm.runInContext(fs.readFileSync(base + 'core.js', 'utf8'), context);
vm.runInContext(fs.readFileSync(base + 'views.js', 'utf8'), context);
const PR = context.window.PR;
const sast = (ms) => new Date(ms + 2 * 3600000).toISOString().slice(0, 16).replace('T', ' ');
const now = Date.now(), generated = sast(now), today = generated.slice(0, 10);
// Use 23:59 today; tests also work in the last minute of the day.
const ko = today + ' 23:59';
const sel = (p = .84, odds = 1.18, market = .80, code = 'O15', diff = 0, model = p) => [code, p, model, market, odds, diff, null, null];
const fixture = (name, selection = sel()) => ({ id: `${today}|England|${name}|Away`, date: today, kickoff: ko, home: name, away: 'Away', country: 'England', league: 'Premier League', data_ok: true, q: 'High', sels: [selection] });
const fixtures = [fixture('At floor'), fixture('Below floor', sel(.84, 1.17999)), fixture('No odds', sel(.84, null)),
  fixture('Not rounded', sel(.79999, 1.30)), fixture('At 80', sel(.80, 1.30)),
  fixture('Fair fails', sel(.80, 1.224999, .80)), fixture('Fair passes', sel(.80, 1.225, .80)),
  fixture('Market missing', sel(.84, 1.2, null)), fixture('Model missing', sel(.84, 1.2, .8, 'O15', 0, null)),
  fixture('Gap fails', sel(.84, 1.2, .75999)), fixture('Gap passes', sel(.84, 1.2, .76)),
  fixture('Diff flagged', sel(.84, 1.2, .8, 'O15', 1)), fixture('Medium', sel()),
  fixture('Low', sel()), fixture('No quality', sel()), fixture('Started', sel()), fixture('Tomorrow', sel()),
  fixture('Cup', sel()), fixture('Old shortlist price', sel(.84, 1.17)), fixture('Outside shortlist', sel()),
  fixture('Cancelled', sel()), fixture('Live', sel()), fixture('Offered corners', sel(.81, 1.3, .78, 'CO85'))];
fixtures.find(x => x.home === 'Medium').q = 'Medium';
fixtures.find(x => x.home === 'Low').data_ok = false;
fixtures.find(x => x.home === 'No quality').q = null;
fixtures.find(x => x.home === 'Started').kickoff = today + ' 00:00';
fixtures.find(x => x.home === 'Tomorrow').date = '2099-01-01';
fixtures.find(x => x.home === 'Cup').league = 'FA Cup';
fixtures.find(x => x.home === 'Cancelled').livescore_id = '1';
fixtures.find(x => x.home === 'Live').livescore_id = '2';
PR.state.live['1'] = {status: 'Postp'}; PR.state.live['2'] = {status: '25'};
const d = PR.indexData({ meta: { generated, tz: 'SAST' }, fixtures,
  shortlist: { primary: fixtures.filter(x => x.home !== 'Outside shortlist').map(x => ({ fixture:x.id, sel:x.sels[0][0], odds:1.3, home:'wrong stale name', away:'wrong', kickoff:x.kickoff })) } });
PR.state.data = d;
const info = PR.finalPicksInfo(d);
assert.equal(info.status, 'ready');
// At 23:59 SAST, there can no longer be a valid upcoming fixture today.
const names = Array.from(info.picks, x => x.home);
if (generated.slice(11) !== '23:59') {
  assert.deepEqual(names, ['Gap passes', 'At floor', 'Offered corners', 'At 80', 'Fair passes']);
  assert(info.picks.every(x => x.odds >= 1.18));
  assert.equal(info.picks[0].away, 'Away');
  PR.addBtn = (fid, code, odds) => `<button data-test-add="${fid}" data-price="${odds}">+</button>`;
  PR.views.finalpicks();
  assert.match(view.innerHTML, /Final Picks/);
  assert.match(view.innerHTML, /At floor v Away/);
  assert.match(view.innerHTML, /Over 1\.5/);
  assert.match(view.innerHTML, /1\.18/);
  assert.match(view.innerHTML, /Premier League/);
  assert.match(view.innerHTML, /data-test-add/);
  assert.doesNotMatch(view.innerHTML, /Below floor|wrong stale name|Outside shortlist/);
}
// Use the real slip implementation: the current index price wins over stale detail,
// and a pick that no longer meets the 1.18 floor cannot be added from this view.
if (generated.slice(11) !== '23:59') {
  vm.runInContext(fs.readFileSync(base + 'slip.js', 'utf8'), context);
  PR.render = () => {};
  PR.detailCached = () => ({sels:[{sel:'O15',p:.84,odds:1.30}]});
  PR.state.tab = 'finalpicks'; PR.state.stack = [];
  const f = fixtures.find(x => x.home === 'At floor');
  PR.slipToggle(f.id, 'O15');
  assert.equal(PR.inSlip(f.id, 'O15'), true);
  assert.equal(JSON.parse(saved.pr_slip).items[0].odds, 1.18);
  PR.slipToggle(f.id, 'O15');
  f.sels[0].odds = 1.17;
  PR.slipToggle(f.id, 'O15');
  assert.equal(PR.inSlip(f.id, 'O15'), false);
  f.sels[0].odds = 1.18;
}
assert(PR.TABS.includes('finalpicks'));
PR.views.home(); assert.match(view.innerHTML, /data-tab-go="finalpicks"/);
PR.views.more(); assert.match(view.innerHTML, /data-tab-go="finalpicks"/);
for (const [meta, status] of [
  [{generated:sast(now - 91 * 60000),tz:'SAST'}, 'stale'],
  [{generated:sast(now + 7 * 60000),tz:'SAST'}, 'stale'],
  [{generated:'2026-99-02 08:00',tz:'SAST'}, 'unavailable'],
  [{generated, tz:'UTC'}, 'unavailable'],
  [{tz:'SAST'}, 'unavailable']]) {
  d.meta = meta; assert.equal(PR.finalPicksInfo(d).status,status); assert.equal(PR.finalPicksInfo(d).picks.length,0);
}
PR.views.finalpicks(); assert.match(view.innerHTML, /valid SAST publication timestamp/);
d.meta = {generated, tz:'SAST'}; d.shortlist.primary = []; PR.views.finalpicks();
assert.match(view.innerHTML, /No qualifying Final Picks/);
assert.match(view.innerHTML, /not been separately backtested/);
assert.match(fs.readFileSync(base + 'app.js','utf8'), /state\.tab === 'finalpicks'/);
console.log('Final Picks policy, freshness, UI and navigation tests passed');
