// Pending tickets must refresh stale day data and settle only from final scores.
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const values = {}, store = {getItem:k=>values[k]||null,setItem:(k,v)=>values[k]=v,removeItem:k=>delete values[k]};
const document = {documentElement:{dataset:{}},addEventListener:()=>{},querySelector:(s)=>s==='#toast'?{textContent:'',classList:{add:()=>{},remove:()=>{}}}:null,querySelectorAll:()=>[]};
const ctx = {window:{},document,localStorage:store,navigator:{onLine:true},URL,console,setTimeout,clearTimeout,AbortController};
vm.createContext(ctx);const base='android/app/src/main/assets/www/';
vm.runInContext(fs.readFileSync(base+'core.js','utf8'),ctx);const PR=ctx.window.PR;
const today=PR.ymd(PR.tzNow()), id=today+'|England|A|B';
values.pr_tickets_full=JSON.stringify([{id:'t',status:'pending',legs:[{fixture:id,sel:'O15',kickoff:today+' 08:00',status:'pending',home:'A',away:'B',odds:1.2}]}]);
PR.state.days[today]={fixtures:[{id,score:null}]};
vm.runInContext(fs.readFileSync(base+'slip.js','utf8'),ctx);
let calls=0;
PR.loadDay=async (date,force)=>{assert.equal(force,true); calls++;PR.state.days[date]={fixtures:[{id,score:{status:'FT',hg:2,ag:0}}]};};
PR.reconcileTickets().then(()=>{
 assert.equal(calls,1);assert.equal(PR.tickets()[0].status,'won');
 console.log('Pending football tickets refresh and settle from final results');
}).catch(e=>{console.error(e);process.exitCode=1;});
