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
const pages = fs.readFileSync(base+'pages.js','utf8').replace('  function briefingVerified(x, det) {', '  PR.testBriefingVerified = briefingVerified;\n  function briefingVerified(x, det) {');
vm.runInContext(pages,ctx);
const PR=ctx.window.PR;
const fixture=(id,name,gate) => ({id,d:id,kickoff:'2099-01-05 12:00',country:'England',league:'Premier League',competition:'Premier League',
  home:name,away:'Away',xg:[1,1],p:{O25:.5},bets:[],h2h_gate:gate});
const allowed=fixture('yes','Enough',{eligible:true,meetings:3}), missing=fixture('no','Unknown',undefined),
  limited=fixture('limited','Limited',{eligible:false,meetings:2});
// Legacy gate metadata and old archives no longer suppress upcoming fixtures.
PR.state.data={meta:{h2h_gate:{minimum_meetings:3,eligible_fixture_ids:['yes']}}};
for (const f of [allowed,missing,limited]) assert.equal(PR.h2hPredictionVisible(f),true);
PR.state.days['2099-01-05']={fixtures:[allowed,missing,limited],summary:{}};
PR.pages.day({date:'2099-01-05'});
assert.match(view.innerHTML,/Enough/); assert.match(view.innerHTML,/Unknown/); assert.match(view.innerHTML,/Limited/);
assert.equal(PR.state.days['2099-01-05'].fixtures.length,3);
// Briefing retains team-data checks, but missing/old H2H never excludes a candidate.
const recent = Array.from({length:5}, (_,i) => ({date:new Date(Date.now() - (i+1)*86400000).toISOString().slice(0,10), gf:i, ga:0}));
const detail = {teams:{home:{last5:recent},away:{last5:recent}},h2h:[]};
assert.equal(PR.testBriefingVerified({sel:'O15',kickoff:'2099-01-05 12:00'},detail),true);
detail.h2h = [{date:'2000-01-01',hg:1,ag:0}];
assert.equal(PR.testBriefingVerified({sel:'O15',kickoff:'2099-01-05 12:00'},detail),true);
detail.teams.home.last5 = [];
assert.equal(PR.testBriefingVerified({sel:'O15',kickoff:'2099-01-05 12:00'},detail),false);
console.log('H2H is optional; old and new fixtures remain visible');
