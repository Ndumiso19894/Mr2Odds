// Current price-floor policy across the actual bundled normalizers, views, exports and unlocked slip.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const base = 'android/app/src/main/assets/www/';
const values = {};
const store = { getItem: k => values[k] || null, setItem: (k,v) => { values[k] = v; }, removeItem: k => { delete values[k]; } };
const elements = { '#view': { innerHTML: '' }, '#back': {}, '#slip-place': {}, '#slip-copy': {}, '#toast': { classList: {add(){}, remove(){}} } };
const document = { documentElement: {dataset:{}}, body:{classList:{add(){},remove(){}}}, addEventListener(){},
  querySelector: s => elements[s] || null, querySelectorAll: () => [] };
const ctx = {window:{}, document, localStorage:store, navigator:{onLine:true}, URL, console, setTimeout, clearTimeout, AbortController};
vm.createContext(ctx);
let core = fs.readFileSync(base+'core.js','utf8').replace('  return { native, settings,', '  return { testPrepDetail: prepDetail, native, settings,');
vm.runInContext(core, ctx);
let pages = fs.readFileSync(base+'pages.js','utf8')
  .replace('  function matchOverview(parts, f, s) {', '  PR.testOverview = matchOverview;\n  function matchOverview(parts, f, s) {')
  .replace('  function matchMarkets(parts, f) {', '  PR.testMarkets = matchMarkets;\n  function matchMarkets(parts, f) {')
  .replace('  function matchSheet(parts, f) {', '  PR.testSheet = matchSheet;\n  function matchSheet(parts, f) {');
vm.runInContext(pages, ctx);
vm.runInContext(fs.readFileSync(base+'export.js','utf8'), ctx);
const PR = ctx.window.PR;
for (const value of [undefined, null, '', 'bad', NaN, Infinity, [], true, 1.15, 1.159, '1.159']) assert.equal(PR.offeredPrice(value), false, String(value));
for (const value of [1.16, 1.17, '1.16', 2]) assert.equal(PR.offeredPrice(value), true, String(value));
const row = (sel, odds) => [sel,.9,.9,.8,odds,0,null,null];
const today = PR.ymd(PR.tzNow());
const f = {id:'f', date:today, home:'Home', away:'Away', country:'England', league:'Premier League', kickoff:today+' 23:59',
  sels:[row('O15',1.15), row('O25',1.16), row('O35',null), row('O45',1.159)],
  hi:[['O15',.9,1.15],['O25',.9,1.16]], bo:{O15:[.9,1.159],O25:[.9,1.16]}, top:['O15',.9,1.15], safe:['O25',.9,1.16]};
const bets = [{odds:1.15}, {odds:1.16}];
const d = PR.indexData({fixtures:[f], safe:{bets:bets.slice(),today:{bets:bets.slice(),groups:[{bets:bets.slice()}]}},
  shortlist:{primary:bets.slice()}, strong_markets:{bets:bets.slice()}, picks:{O15:[{sportybet:1.159},{sportybet:null},{sportybet:1.16}]}, tracker:{legacy:1.15}});
assert.deepEqual(Array.from(f.sels, s=>s.sel), ['O25','O35']);
assert.equal(f.hi.length,1); assert.equal(f.bo.O15,undefined); assert.equal(f.bo.O25[1],1.16);
assert.equal(f.top,null); assert.equal(f.safe[2],1.16);
assert.equal(d.safe.bets.length,1); assert.equal(d.safe.today.bets.length,1); assert.equal(d.safe.today.groups[0].bets.length,1);
assert.equal(d.shortlist.primary.length,1); assert.equal(d.strong_markets.bets.length,1); assert.equal(d.picks.O15.length,2);
assert.equal(d.tracker.legacy,1.15); // historical record is never rewritten
const detail = PR.testPrepDetail({id:'f',home:'Home',away:'Away',sels:[row('O15',1.15),row('O25',1.16),row('O35',null)],
  sportybet:{'1X2':[1.159,1.16,3.1],DC:{'1X':1.15,'12':1.2},BTTS:[1.15,2.3],OU:{'2.5':[1.159,1.16]},CORN:{'9.5':[1.15,1.25]}},
  odds:{home:1.15,away:1.16}, xg:{home:2,away:2,total:4}, p:{O15:.9,O25:.8,BTTS:.7}, league_avg:{}, teams:{home:{},away:{}},trends:{}});
assert.equal(detail.sportybet['1X2'][0],null); assert.equal(detail.sportybet['1X2'][1],1.16);
assert.equal(detail.sportybet.DC['1X'],undefined); assert.equal(detail.sportybet.DC['12'],1.2);
assert.equal(detail.sportybet.OU['2.5'][0],null); assert.equal(detail.sportybet.OU['2.5'][1],1.16);
assert.equal(detail.sportybet.CORN['9.5'][1],1.25); assert.equal(detail.odds.home,null); assert.equal(detail.odds.away,1.16);
PR.state.data=d; PR.finalFor=()=>null;
let parts=[]; PR.testOverview(parts,detail,null); let html=parts.join('');
assert.match(html,/1\.16/); assert.match(html,/3\.10/); assert.doesNotMatch(html,/1\.15(?:9)?\b/);
parts=[]; PR.testMarkets(parts,detail); html=parts.join('');
assert.match(html,/1\.16/); assert.match(html,/1\.25/); assert.doesNotMatch(html,/1\.15(?:9)?\b/);
let csv=PR.matchCsv(detail,null,[]); assert.match(csv,/O25/); assert.match(csv,/O35/); assert.doesNotMatch(csv,/1\.15(?:9)?\b/);
const sheet = {home:'Home',away:'Away',sheet_model:{ok:true,inputs:{},model:{},markets:[],v4:{ok:true,model:{},markets:[
  {name:'Too low',odds:1.159,fair:1.12},{name:'At floor',odds:1.16,fair:1.12},{name:'Model only',odds:null,fair:1.12}]}}};
parts=[]; PR.testSheet(parts,sheet); html=parts.join(''); assert.doesNotMatch(html,/Too low/); assert.match(html,/At floor/); assert.match(html,/Model only/);
csv=PR.sheetCsv(sheet); assert.doesNotMatch(csv,/Too low/); assert.match(csv,/At floor/); assert.match(csv,/1\.12/); // fair price is not a bookmaker quote
const report='\ufeffhome,odds_home,sportybet_over25,fair_odds,notes\r\n"Club, A",1.159,1.16,1.12,"quoted, text"\r\nB,1.15,1.25,1.13,"multi\nline"\r\n';
assert.equal(PR.filterCurrentMarketCsv(report),'\ufeffhome,odds_home,sportybet_over25,fair_odds,notes\r\n"Club, A",,1.16,1.12,"quoted, text"\r\nB,,1.25,1.13,"multi\nline"\r\n');
const md='| Match | Sportybet 1X2 | Fair odds |\n|---|---|---|\n| A | 1.15 / 1.16 | 1.12 |\n\n* **Sportybet:** goals O1.5 1.15 / U 1.25\n* Model xG 1.12';
const filtered=PR.filterCurrentMarketReport(md); assert.match(filtered,/– \/ 1\.16/); assert.match(filtered,/O1\.5 – \/ U 1\.25/); assert.match(filtered,/Fair odds/); assert.match(filtered,/Model xG 1\.12/);
// Existing unlocked short-priced legs remain removable but cannot be copied or locked.
values.pr_slip=JSON.stringify({items:[{fixture:'f',label:'Legacy',home:'Home',away:'Away',odds:1.15,p:.9}],stake:''});
values.pr_tickets_full=JSON.stringify([{id:'historic',status:'won',legs:[{odds:1.15}]}]);
const slipCode = fs.readFileSync(base+'slip.js','utf8').replace('  PR.inSlip =', '  PR.testValidSlipLeg = validSlipLeg;\n  PR.inSlip =');
vm.runInContext(slipCode,ctx);
assert.equal(PR.testValidSlipLeg({fixture:'f',sel:'O25',odds:1.16}),true);
assert.equal(PR.testValidSlipLeg({fixture:'f',sel:'O25',odds:1.2}),false); // newer price changed
assert.equal(PR.testValidSlipLeg({fixture:'f',sel:'O15',odds:1.3}),false); // now below floor / missing
assert.equal(PR.testValidSlipLeg({fixture:'f',sel:'O25',odds:1.16,sport:'tennis'}),false); // paused
let confirmed=false; PR.confirmBox=async()=>{confirmed=true;return true};
PR.pages.slip(); assert.match(elements['#view'].innerHTML,/price unavailable, changed or below 1\.16/);
assert.doesNotMatch(elements['#view'].innerHTML,/>1\.15</);
elements['#slip-place'].onclick().then(async ()=>{
  assert.equal(confirmed,false); assert.equal(JSON.parse(values.pr_slip).items[0].odds,1.15);
  assert.equal(JSON.parse(values.pr_tickets_full)[0].legs[0].odds,1.15);
  PR.nfetch=async()=>({code:200,body:report}); let saved=''; PR.saveTextFile=(name,text)=>{saved=text};
  await PR.downloadDayCsv(today); assert.equal(saved,PR.filterCurrentMarketCsv(report));
  await PR.downloadDayCsv('2020-01-01'); assert.equal(saved,report); // older published reports remain unchanged
  console.log('Current market price-floor UI and export tests passed');
}).catch(e=>{console.error(e);process.exitCode=1});
