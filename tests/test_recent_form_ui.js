const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{}, document:{documentElement:{dataset:{}},addEventListener(){}},
  localStorage:{getItem(){return null},setItem(){},removeItem(){}},navigator:{onLine:true},
  URL, console, setTimeout, clearTimeout, AbortController};
vm.createContext(context);
const base='android/app/src/main/assets/www/';
vm.runInContext(fs.readFileSync(base+'core.js','utf8'),context);
const code=fs.readFileSync(base+'pages.js','utf8').replace('  function matchData(parts, f) {',
  '  PR.testMatchData = matchData;\n  function matchData(parts, f) {');
vm.runInContext(code,context);
const PR=context.window.PR;
const f={home:'H',away:'A',div:'LS:test/league',country:'Test',league:'League',xg:{total:2},
  p:{O15:.8,O25:.5,O35:.3,BTTS:.5},quality:{overall:'High',score:.9,components:{}},evidence:{},
  explain:{league:{},home:{},away:{},lambda_home:{value:1,terms:[1,1,1]},lambda_away:{value:1,terms:[1,1,1]},steps:[],
    recent_form:{status:'applied'},model_signals:{status:'disabled_pending_backtest'}},
  h2h_meta:{n:0,label:'No data',used_by_model:true,note:'Eligible subset used.'}};
let parts=[];PR.testMatchData(parts,f);let html=parts.join('');
assert.match(html,/Recent form applied/);
assert.match(html,/not prospectively validated/);
assert.match(html,/used by the model: <b>yes, eligible subset<\/b>/);
assert.match(html,/Squad availability is not used/);
f.explain.recent_form={status:'baseline_fallback',reason:'ambiguous same-day team history'};
f.h2h_meta.used_by_model=false;
parts=[];PR.testMatchData(parts,f);html=parts.join('');
assert.match(html,/Recent form not applied \(ambiguous same-day team history\); the baseline is retained/);
assert.match(html,/used by the model: <b>no<\/b>/);
console.log('Recent-form applied, fallback and H2H display tests passed');
