// Pending tickets must refresh stale day data and settle only from final scores.
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const values = {}, store = {getItem:k=>values[k]||null,setItem:(k,v)=>values[k]=v,removeItem:k=>delete values[k]};
const document = {documentElement:{dataset:{}},addEventListener:()=>{},querySelector:(s)=>s==='#toast'?{textContent:'',classList:{add:()=>{},remove:()=>{}}}:null,querySelectorAll:()=>[]};
const ctx = {window:{},document,localStorage:store,navigator:{onLine:true},URL,console,setTimeout,clearTimeout,AbortController};
vm.createContext(ctx);const base='android/app/src/main/assets/www/';
vm.runInContext(fs.readFileSync(base+'core.js','utf8'),ctx);const PR=ctx.window.PR;
const today=PR.ymd(PR.tzNow()), id=today+'|England|A|B', live=today+'|England|C|D', uefa=today+'|Europe|E|F';
const makeLeg=(fixture,home,away)=>({fixture,sel:'O15',kickoff:today+' 08:00',status:'pending',home,away,odds:1.2});
values.pr_tickets_full=JSON.stringify([
 {id:'t',status:'pending',legs:[makeLeg(id,'A','B')]},
 {id:'live',status:'pending',legs:[makeLeg(live,'C','D')]},
 {id:'uefa',status:'pending',legs:[makeLeg(uefa,'E','F')]}
]);
const initial=[{id,score:{status:'NS',hg:null,ag:null}},
 {id:live,score:{status:'1H',hg:1,ag:1}},
 {id:uefa,country:'Europe',league:'UEFA Europa League',score:{status:'FT',hg:2,ag:0}}];
PR.state.days[today]={fixtures:initial};
vm.runInContext(fs.readFileSync(base+'slip.js','utf8'),ctx);
PR.settleTickets(false);
assert.ok(PR.tickets().every(t=>t.status==='pending'), 'missing, in-play and ambiguous scores stay pending');
let calls=0;
PR.loadDay=async (date,force)=>{assert.equal(force,true);calls++;PR.state.days[date]={fixtures:[
 {id,score:{status:'FT',hg:2,ag:0}},initial[1],initial[2]
]};};
PR.reconcileTickets().then(()=>{
 assert.equal(calls,1);assert.equal(PR.tickets().find(t=>t.id==='t').status,'won');
 assert.equal(PR.tickets().find(t=>t.id==='live').status,'pending');
 assert.equal(PR.tickets().find(t=>t.id==='uefa').status,'pending');
 console.log('Pending football tickets refresh and settle only from verified final results');
}).catch(e=>{console.error(e);process.exitCode=1;});
