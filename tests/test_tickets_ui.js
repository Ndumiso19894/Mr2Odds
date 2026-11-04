// Existing tennis tickets can reconcile without enabling tennis scans or the tennis tab.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const values = {};
const store = { getItem: (k) => values[k] || null, setItem: (k, v) => { values[k] = v; }, removeItem: (k) => { delete values[k]; } };
const toast = { classList: { add: () => {}, remove: () => {} } };
const document = { documentElement: { dataset: {} }, addEventListener: () => {}, querySelector: (s) => s === '#toast' ? toast : null, querySelectorAll: () => [] };
const context = { window: {}, document, localStorage: store, navigator: { onLine: true }, URL, console, setTimeout, clearTimeout, AbortController };
vm.createContext(context);
const base = 'android/app/src/main/assets/www/';
vm.runInContext(fs.readFileSync(base + 'core.js', 'utf8'), context);
const PR = context.window.PR;
const today = PR.ymd(PR.tzNow());
const leg = (eid, market, selection, line) => ({eid, fixture: eid, sport:'tennis', market, selection, line,
  kickoff:today + ' 08:00', home:'A', away:'B', status:'pending', odds:1.4});
values.pr_tickets_full = JSON.stringify([
  {id:'win', status:'pending', legs:[leg('1', 'winner', 'player_a', null)]},
  {id:'push', status:'pending', legs:[leg('1', 'total_games', 'over', 21)]},
  {id:'retired', status:'pending', legs:[leg('2', 'winner', 'player_a', null)]},
  {id:'retired-games', status:'pending', legs:[leg('2', 'total_games', 'over', 19.5)]},
  {id:'waiting', status:'pending', legs:[leg('3', 'winner', 'player_a', null)]}
]);
vm.runInContext(fs.readFileSync(base + 'slip.js', 'utf8'), context);
let urls = [];
PR.getJson = async (url) => { urls.push(url); return {Stages:[{Events:[
  {Eid:'1', Ewt:2, Eps:'FT', Tr1S1:'6', Tr2S1:'4', Tr1S2:'6', Tr2S2:'5'},
  {Eid:'2', Ewt:2, Eps:'Retired', Tr1S1:'6', Tr2S1:'4'}
]}]}; };
PR.loadDay = async () => { throw Error('Tennis legs should not load football day files'); };
PR.toast = () => {};
PR.reconcileTickets().then(() => {
  const t = JSON.parse(values.pr_tickets_full);
  assert.equal(t.find((x) => x.id === 'win').status, 'won');
  assert.equal(t.find((x) => x.id === 'push').status, 'void');
  assert.equal(t.find((x) => x.id === 'retired').status, 'pending');
  assert.equal(t.find((x) => x.id === 'retired-games').status, 'void');
  assert.equal(t.find((x) => x.id === 'waiting').status, 'pending');
  assert.equal(urls.length, 1);
  assert.match(urls[0], /date\/tennis\//);
  console.log('Existing tennis ticket reconciliation tests passed');
}).catch((err) => { console.error(err); process.exitCode = 1; });
