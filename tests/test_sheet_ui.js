// Exercise the real Sheet comparison rendering and CSV, without an Android runtime.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{}, document:{documentElement:{dataset:{}}, addEventListener(){}},
  localStorage:{getItem(){return null},setItem(){},removeItem(){}}, navigator:{onLine:true},
  URL, console, setTimeout, clearTimeout, AbortController};
vm.createContext(context);
const base = 'android/app/src/main/assets/www/';
vm.runInContext(fs.readFileSync(base+'core.js','utf8'), context);
const code = fs.readFileSync(base+'pages.js','utf8').replace('  function matchSheet(parts, f) {',
  '  PR.testMatchSheet = matchSheet;\n  function matchSheet(parts, f) {');
vm.runInContext(code, context);
vm.runInContext(fs.readFileSync(base+'export.js','utf8'), context);
const PR = context.window.PR;
const match = {home:'H', away:'A', xg:{model_home:1,model_away:1,model_total:2},
  sheet_model:{ok:true, inputs:{home_current_n:4, home_xg_n:3}, model:{lambda_h:0,lambda_a:1,lambda_total:1,x12_sum:.99,matrix_residual:.01},
    markets:[], missing:[], v4:{ok:false,missing:['away_xg'],model:{},markets:[]}}};
let parts=[]; PR.testMatchSheet(parts, match); let html=parts.join('');
assert.match(html, /Sheet engine/); // zero is a valid lambda
assert.match(html, /V4 unavailable: away_xg/);
assert.match(html, /not a live copy/);
match.sheet_model.v4={ok:true,missing:[],model:{lambda_h:2,lambda_a:.5,lambda_total:2.5},
  markets:[{name:'Home Win',p:.7,fair:1.43,playreport:.6}], note:'Uncalibrated'};
parts=[]; PR.testMatchSheet(parts, match); html=parts.join('');
assert.match(html, /Experimental and not calibrated/);
assert.match(html, /Home Win/);
const csv=PR.sheetCsv(match);
assert.match(csv,/V4 COMPARISON/); assert.match(csv,/Home Win,0.7,1.43,0.6/);
assert.match(csv,/CSV values only/);
console.log('Sheet comparison UI and CSV tests passed');
