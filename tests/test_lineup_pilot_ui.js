const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{}, document:{documentElement:{dataset:{}}, addEventListener(){}},
  localStorage:{getItem(){return null},setItem(){},removeItem(){}}, navigator:{onLine:true},
  URL, console, setTimeout, clearTimeout, AbortController};
vm.createContext(context);
const base = 'android/app/src/main/assets/www/';
vm.runInContext(fs.readFileSync(base+'core.js','utf8'), context);
const code = fs.readFileSync(base+'pages.js','utf8').replace('  function lineupPilotBlock(f) {',
  '  PR.testPilot = lineupPilotBlock;\n  function lineupPilotBlock(f) {');
vm.runInContext(code, context);
const pilot = context.window.PR.testPilot;
assert.equal(pilot({}), '');
const f = {home:'Home',away:'Away',lineup_context:{status:'confirmed',source:'<source>',observed_at:'2026-11-04T10:00:00+00:00',
  home:{status:'ok',sample:5,regulars:[{name:'<Player>',starts:4}],not_starting:[{name:'<Player>',starts:4}]},
  away:{status:'collecting',sample:1,regulars:[],not_starting:[]}}};
let html=pilot(f);
assert.match(html,/Imported confirmed XI snapshot/);
assert.match(html,/&lt;Player&gt; \(4\/5\)/);
assert.doesNotMatch(html, /<Player>/);
assert.match(html,/Not starting in the captured XI/);
assert.match(html,/at least 3 previous line-ups/);
assert.match(html,/not used in probabilities/);
f.lineup_context.status='not_confirmed';
html=pilot(f);
assert.match(html,/No pre-match XI/);
assert.doesNotMatch(html,/Not starting in the captured XI/);
console.log('Lineup pilot UI tests passed');
