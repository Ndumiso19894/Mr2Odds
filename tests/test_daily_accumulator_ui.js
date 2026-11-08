const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const view = {innerHTML:''}, toast = {classList:{add(){},remove(){}}}, saved = {};
const document = {documentElement:{dataset:{}}, body:{classList:{add(){},remove(){}}}, addEventListener(){}, querySelector:s=>s==='#view'?view:s==='#toast'?toast:null, querySelectorAll:()=>[]};
const c={window:{},document,localStorage:{getItem:k=>saved[k]||null,setItem:(k,v)=>saved[k]=v,removeItem:k=>delete saved[k]},navigator:{onLine:true},URL,console,setTimeout,clearTimeout,AbortController};
vm.createContext(c); const base='android/app/src/main/assets/www/';
for (const file of ['core.js','views.js','slip.js']) vm.runInContext(fs.readFileSync(base+file,'utf8'),c);
const PR=c.window.PR, stamp=new Date(Date.now()+7200000).toISOString().slice(0,16).replace('T',' '), today=stamp.slice(0,10);
if (stamp.slice(11)==='23:59') { console.log('Midnight boundary: skip upcoming-match UI test'); process.exit(0); }
const fixtures=Array.from({length:20},(_,i)=>({id:`${today}|England|Club ${i}|Away`,date:today,kickoff:today+' 23:59',home:`Club ${i}`,away:'Away',country:'England',league:'Premier League',data_ok:true,q:'High',sels:[['O15',.84,.84,.8,1.2,0,null,null]]}));
const rows=fixtures.map(f=>({fixture:f.id,sel:'O15',odds:1.2,kickoff:f.kickoff}));
const raw={meta:{generated:stamp,tz:'SAST'},fixtures,shortlist:{primary:rows},daily_accumulators:{generated:stamp,date:today,accumulators:[],alternatives:[],research:{accumulators:[],alternatives:[]}}};
for(let i=0;i<3;i++) raw.daily_accumulators.accumulators.push({odds:2.99,legs:fixtures.slice(i*6,i*6+6).map(f=>({match_id:f.id,sel:'O15',odds:1.2}))});
raw.daily_accumulators.alternatives=fixtures.slice(18).map(f=>({match_id:f.id,best_sel:'O15',best_odds:1.2}));
raw.daily_accumulators.research.accumulators=[{match_id:fixtures[0].id,news:[{team:'<img>',title:'<script>alert(1)</script>',source:'Test',when:'today'}]}];
const d=PR.indexData(raw); PR.state.data=d; PR.state.tab='dailyaccumulators';
assert.equal(PR.dailyPicksInfo(d).groups.length,3); assert.equal(PR.dailyPicksInfo(d).alternatives.length,2);
PR.views.dailyaccumulators(); assert.match(view.innerHTML,/Acca 1/); assert.match(view.innerHTML,/combined 2\.99/); assert.match(view.innerHTML,/Club 0 v Away/); assert.match(view.innerHTML,/&lt;script&gt;/); assert.doesNotMatch(view.innerHTML,/<script>alert/);
PR.render=()=>{}; PR.slipToggle(fixtures[0].id,'O15'); assert(PR.inSlip(fixtures[0].id,'O15')); PR.slipToggle(fixtures[0].id,'O15');
// New price, started match, stale timestamp and duplicate fixture invalidate whole tickets.
fixtures[0].sels[0].odds=1.17; assert.equal(PR.dailyPicksInfo(d).groups.length,2); PR.slipToggle(fixtures[0].id,'O15'); assert(!PR.inSlip(fixtures[0].id,'O15'));
fixtures[0].sels[0].odds=1.2; d.daily_accumulators.accumulators[1].legs[0].match_id=fixtures[0].id; assert.equal(PR.dailyPicksInfo(d).groups.length,2);
d.meta.generated='2020-01-01 00:00'; assert.equal(PR.dailyPicksInfo(d).status,'stale'); assert.equal(PR.dailyPicksInfo(d).groups.length,0);
console.log('Daily accumulator validation, UI, slip and freshness tests passed');
