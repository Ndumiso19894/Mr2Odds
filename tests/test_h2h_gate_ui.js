const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const view = {innerHTML:''};
const document = {documentElement:{dataset:{}},addEventListener(){},
  querySelector(s){return s==='#view' ? view : null},querySelectorAll(){return []}};
const ctx={window:{},document,localStorage:{getItem(){return null},setItem(){},removeItem(){}},
  navigator:{onLine:true},URL,console,setTimeout,clearTimeout,AbortController};
vm.createContext(ctx);
const base='android/app/src/main/assets/www/';
vm.runInContext(fs.readFileSync(base+'core.js','utf8'),ctx);
vm.runInContext(fs.readFileSync(base+'pages.js','utf8'),ctx);
const PR=ctx.window.PR;
const proof={eligible:true,reason:'eligible',meetings:6,last_meeting:'2098-01-01'};
const fixture=(id,name,gate) => ({id,d:id,kickoff:'2099-01-05 12:00',country:'England',league:'Premier League',competition:'Premier League',
  home:name,away:'Away',xg:[1,1],p:{O25:.5},bets:[],h2h_gate:gate});
const allowed=fixture('yes','Allowed',proof), missing=fixture('no','OldMissing',undefined),
  stale=fixture('stale','OldStale',proof);
PR.state.data={meta:{h2h_gate:{eligible_fixture_ids:['yes']}}};
assert.equal(PR.h2hPredictionVisible(allowed),true);
assert.equal(PR.h2hPredictionVisible(missing),false);
assert.equal(PR.h2hPredictionVisible(stale),false);
assert.equal(PR.h2hPredictionVisible({...missing,kickoff:'2000-01-01 12:00'}),true);
assert.equal(PR.h2hPredictionVisible({...allowed,h2h_gate:{...proof,meetings:5}}),false);
PR.state.days['2099-01-05']={fixtures:[allowed,missing,stale],summary:{}};
PR.pages.day({date:'2099-01-05'});
assert.match(view.innerHTML,/Allowed/);
assert.doesNotMatch(view.innerHTML,/OldMissing|OldStale/);
assert.equal(PR.state.days['2099-01-05'].fixtures.length,3); // archive remains untouched
PR.state.data={meta:{}};
assert.equal(PR.h2hPredictionVisible(missing),true); // pre-policy publications remain compatible
console.log('H2H gate hides stale upcoming analyses without deleting history');
