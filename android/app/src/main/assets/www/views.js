/* Mr 2 Odds — tab views: Home, Bets, Live, Matches, Days. */
(function (PR) {
  'use strict';
  const { $, $$, esc, pct, f1, f2, signed, state, settings, fx, pill, koShort, koTime, dayName, toast, selLabel, selShort, selGroup,
    GROUPS, GROUP_ICON, liveVerdict, isLive, isFT, segmented, select, contactCard, matchRow, tzNow, parseLocal, ymd, icon, flag, badge, fxBadge, teamSpan, isUnder } = PR;
  const sh = (ico, title, cls) => `<h2><span class="ico ${cls || ''}">${icon(ico)}</span>${title}</h2>`;
  const view = () => $('#view');
  const MK = { O15: 'Over 1.5 goals', O25: 'Over 2.5 goals', BTTS: 'Both teams to score' };
  const FAMILY = { goals: ['goals', 'btts', 'team'], corners: ['corners'], cards: ['cards'] };
  const majorOnly = () => settings.leagues === 'major';
  const inScope = (f) => !majorOnly() || !f || f.major;

  // ------------------------------------------------------------------ live data (shared by Live tab, Home strip, match page)
  const live = PR.live;
  live.for = (f) => f && f.livescore_id ? state.live[f.livescore_id] : null;
  live.tracked = function () {
    const d = state.data; const ids = new Set(d.tracked || []);
    if (PR.ticketFixtures) PR.ticketFixtures().forEach((id) => ids.add(id));
    if (PR.favList) PR.favList().forEach((f) => ids.add(f.fixture));
    return (d.fixtures || []).filter((f) => ids.has(f.id)).sort((a, b) => a.kickoff.localeCompare(b.kickoff));
  };
  const LIVE_STATUS = (e) => e.Eps || '';
  let refreshFlight = null;
  live.refresh = function (manual) {
    if (refreshFlight) return refreshFlight;
    refreshFlight = refreshLive(manual).finally(() => { refreshFlight = null; });
    return refreshFlight;
  };
  async function refreshLive(manual) {
    const d = state.data; if (!d) return;
    const tracked = live.tracked().filter((f) => f.livescore_id);
    const now = tzNow(); const days = new Set(tracked.map((f) => f.kickoff.slice(0, 10))); days.add(ymd(now));
    if (now.getHours() < 3) days.add(ymd(new Date(now.getTime() - 86400000)));
    const want = new Set(tracked.map((f) => f.livescore_id));
    const byEid = {}; (d.fixtures || []).forEach((f) => { if (f.livescore_id) byEid[f.livescore_id] = f; });
    let changed = state.liveAll == null, successful = 0, stale = false;
    const goalEvents = []; const all = []; const seenAll = new Set(); const phaseEvents = [];
    for (const day of days) {
      try {
        const url = `https://prod-public-api.livescore.com/v1/api/app/date/soccer/${day.replace(/-/g, '')}/${settings.tzOffset}?MD=1`;
        const j = await PR.getJson(url); successful++;
        state.liveResource = url;
        const info = PR.resources ? PR.resources.status(url) : { checkedAt: Date.now() };
        const saved = !!(info.stale || info.offline || info.error); stale = stale || saved;
        (j.Stages || []).forEach((st) => (st.Events || []).forEach((e) => {
          const eid = String(e.Eid); const status = LIVE_STATUS(e);
          const ns = !status || status === 'NS';
          const cur = { status, hg: !ns && e.Tr1 != null && e.Tr1 !== '' ? +e.Tr1 : null, ag: !ns && e.Tr2 != null && e.Tr2 !== '' ? +e.Tr2 : null, ht: [e.Trh1, e.Trh2], t: info.checkedAt, cached: saved };
          const prev = state.live[eid];
          if (!prev || prev.status !== cur.status || prev.hg !== cur.hg || prev.ag !== cur.ag) changed = true;
          state.live[eid] = cur;
          if (!saved && want.has(eid) && prev && prev.hg != null && cur.hg != null && (cur.hg + cur.ag) > (prev.hg + prev.ag)) goalEvents.push(eid);
          if (!saved && want.has(eid) && prev && prev.status !== cur.status && (cur.status === 'HT' || isFT(cur))) phaseEvents.push(eid);
          if (isLive(cur) && !seenAll.has(eid)) {
            seenAll.add(eid);
            const t1 = (e.T1 || [])[0] || {}, t2 = (e.T2 || [])[0] || {};
            all.push({ eid, status, hg: cur.hg, ag: cur.ag, home: t1.Nm || '?', away: t2.Nm || '?', img: [t1.Img, t2.Img], country: st.Cnm || '', league: st.Snm || '', fixture: byEid[eid] ? byEid[eid].id : null, esd: String(e.Esd || '') });
          }
        }));
      } catch (e) { if (manual) toast('Live scores unavailable (' + e.message + ')'); }
    }
    if (!successful) { PR.statusLine(); return; }
    state.liveStale = stale;
    state.liveAll = all; state.lastLiveAll = Date.now();
    state.lastLive = Date.now();
    const dot = $('#live-dot'); if (dot) dot.classList.toggle('on', live.inPlay().length > 0);
    for (const f of tracked) {
      const s = state.live[f.livescore_id]; if (!s || s.hg == null || (s.hg + s.ag) === 0) continue;
      const key = `${s.hg}-${s.ag}`; const c = state.incidents[f.livescore_id]; if (c && c.key === key) continue;
      try {
        const j = await PR.getJson(`https://prod-public-api.livescore.com/v1/api/app/incidents/soccer/${f.livescore_id}`);
        const items = [];
        Object.values(j.Incs || {}).forEach((lst) => lst.forEach((x) => { [x].concat(x.Incs || []).forEach((y) => {
          const t = { 36: 'goal', 37: 'own goal', 39: 'penalty', 40: 'missed penalty', 43: 'yellow', 44: 'second yellow', 45: 'red' }[y.IT];
          if (!t) return; items.push({ min: y.Min, team: y.Nm === 1 ? 'H' : 'A', type: t, player: y.Pn || [y.Fn, y.Ln].filter(Boolean).join(' '), score: y.Sc });
        }); }));
        items.sort((a, b) => (a.min || 0) - (b.min || 0));
        state.incidents[f.livescore_id] = { key, items };
      } catch (e) { /* ignore */ }
    }
    const top = state.stack[state.stack.length - 1];
    if ((manual || changed) && (((state.tab === 'live' || state.tab === 'home') && !top) || top && top.type === 'match')) PR.render();
    else PR.statusLine();
    goalEvents.forEach(announceGoal);
    phaseEvents.forEach(announcePhase);
    if (PR.settleTickets) PR.settleTickets(true);
  };
  function announcePhase(eid) {
    const f = live.tracked().find((x) => x.livescore_id === eid); const s = state.live[eid]; if (!f || !s) return;
    const ht = s.status === 'HT';
    if (ht && !settings.htAlerts) return; if (!ht && !settings.ftAlerts) return;
    const bets = betsFor(f.id).map((b) => `${b.label}: ${liveVerdict(b.sel, s).text}`).join(' · ');
    const title = `${ht ? '⏸ Half-time' : '🏁 Full-time'}  ${f.home} ${s.hg} – ${s.ag} ${f.away}`;
    const text = (bets ? bets + ' · ' : '') + f.competition;
    if (PR.native && PR.native.notify) { try { PR.native.notify('match', (ht ? 5000 : 6000) + (parseInt(eid, 10) % 1000), title, text, 'live'); } catch (e) { /* ignore */ } } else toast(title);
  }
  function betsFor(fid) {
    const d = state.data, out = [], sf = d.safe || { bets: [] };
    ((sf.today && sf.today.bets) || []).filter((b) => b.fixture === fid).forEach((b) => out.push({ label: b.label, sel: b.sel }));
    (sf.bets || []).filter((b) => b.fixture === fid && !out.some((o) => o.sel === b.sel)).forEach((b) => out.push({ label: b.label, sel: b.sel }));
    if (PR.tickets) PR.tickets().forEach((t) => { if (t.status === 'pending') t.legs.filter((l) => l.fixture === fid && !out.some((o) => o.sel === l.sel)).forEach((l) => out.push({ label: '🎫 ' + l.label, sel: l.sel })); });
    return out;
  }
  function announceGoal(eid) {
    if (!settings.goalAlerts) return;
    const f = live.tracked().find((x) => x.livescore_id === eid); const s = state.live[eid]; if (!f || !s) return;
    const inc = state.incidents[eid]; const goals = inc ? inc.items.filter((it) => ['goal', 'own goal', 'penalty'].includes(it.type)) : [];
    const last = goals.length ? goals[goals.length - 1] : null;
    const scorer = last ? `${last.player || ''} ${last.min != null ? last.min + "'" : ''}${last.type !== 'goal' ? ' (' + last.type + ')' : ''}`.trim() : '';
    const title = `⚽ GOAL  ${f.home} ${s.hg} – ${s.ag} ${f.away}`;
    const text = (scorer ? scorer + ' · ' : '') + `${s.status} · ${f.competition}`;
    if (PR.native && PR.native.notifyGoal) PR.native.notifyGoal(eid, `${s.hg}-${s.ag}`, title, text); else toast(title);
  }
  live.schedule = function () {
    clearInterval(state.liveTimer);
    state.liveTimer = setInterval(() => {
      if (document.hidden || !state.data) return;
      const top = state.stack[state.stack.length - 1];
      if (!(state.tab === 'live' || state.tab === 'home' || (top && top.type === 'match'))) return;
      const now = tzNow();
      const active = (state.tab === 'live' && state.liveView === 'all') || live.tracked().some((f) => { const s = live.for(f); const ko = parseLocal(f.kickoff); return isLive(s) || (ko && !isFT(s) && Math.abs(now - ko) < 3 * 3600 * 1000); });
      if (active) live.refresh(false);
    }, Math.max(20, settings.liveEvery) * 1000);
  };
  live.inPlay = () => live.tracked().filter((f) => isLive(live.for(f)));

  // ------------------------------------------------------------------ bets helpers
  const sameDay = (b) => String((b && b.kickoff) || '').slice(0, 10) === ymd(tzNow());
  function safeList(group) {
    const sf = state.data.safe || { bets: [] };
    let lst = (sf.bets || []).filter((b) => inScope(fx(b.fixture)) && !PR.isDropped(b.sel));
    if (group && group !== 'all') lst = lst.filter((b) => (FAMILY[group] || [group]).includes(b.group));
    return lst;
  }
  function betStatus(b) {
    if (b.status && b.status !== 'pending') return b.status === 'hit' || b.status === 'won' ? { cls: 'good', text: '✅ won' } : b.status === 'void' ? { cls: '', text: 'void' } : { cls: 'bad', text: '❌ lost' };
    const f = fx(b.fixture); const s = live.for(f);
    return liveVerdict(b.sel, s);
  }
  function safeRow(b, opts) {
    opts = opts || {}; const f = fx(b.fixture); const st = betStatus(b);
    const tap = `class="tap" data-fx="${esc(b.fixture)}"`;
    return `<tr ${tap}><td class="tiny muted nowrap">${esc(opts.time ? koTime(b.kickoff) : koShort(b.kickoff))}</td>
      <td><div class="row" style="gap:6px">${badge(b.home, b.badges && b.badges.home, 20)}${badge(b.away, b.badges && b.badges.away, 20)}<div class="b grow">${teamSpan(b.home, b.country, (f && f.div) || '')} <span class="muted">v</span> ${teamSpan(b.away, b.country, (f && f.div) || '')}</div></div>
      <div class="sel"><b>${esc(b.label)}</b></div><div class="tiny muted">${flag(b.country)} ${esc(b.league)}${b.q ? ` · <span class="${b.q === 'High' ? 'pos' : b.q === 'Low' ? 'warn' : ''}">data ${esc(b.q)}</span>` : ''}${b.p_sb != null ? ` · market ${pct(b.p_sb)}` : ''}${st.text !== 'not started' ? ` · <span class="${st.cls}">${esc(st.text)}</span>` : ''}</div></td>
      <td class="right nowrap"><b>${f2(b.odds)}</b>${b.odds ? '<div class="tiny muted">Sportybet</div>' : ''}</td><td class="right"><div class="row" style="gap:0;justify-content:flex-end">${pill(b.p, 0.8, 0.7)}${PR.addBtn ? PR.addBtn(b.fixture, b.sel, b.odds) : ''}</div></td></tr>`;
  }
  function selRow(f, s) {
    return `<tr class="tap" data-fx="${esc(f.id)}"><td class="tiny muted nowrap">${esc(koShort(f.kickoff))}</td>
      <td><div class="match">${teamSpan(f.home, f.country, f.div)} <span class="muted">v</span> ${teamSpan(f.away, f.country, f.div)}</div><div class="sel"><b>${esc(selLabel(s.sel, f.home, f.away))}</b></div><div class="tiny muted">${flag(f.country)} ${esc(f.competition)}${s.diff ? ' · <span class="warn">views differ</span>' : ''}</div></td>
      <td class="right nowrap">${s.odds ? `<b>${f2(s.odds)}</b>` : '<span class="muted">–</span>'}</td><td class="right"><div class="row" style="gap:0;justify-content:flex-end">${pill(s.p, 0.8, 0.7)}${PR.addBtn ? PR.addBtn(f.id, s.sel, s.odds) : ''}</div>${s.ev != null ? `<div class="tiny good" style="text-align:right">edge +${Math.round(s.ev * 100)}%</div>` : ''}</td></tr>`;
  }
  function botdCard(compact) {
    const sf = state.data.safe || {}; const today = sf.today || { bets: [] };
    const over = (b) => b && !PR.isDropped(b.sel);
    const bets = (today.bets || []).filter(over); const groups = (today.groups || []).map((g) => ({ ...g, bets: (g.bets || []).filter(over) })).filter((g) => g.bets.length);
    const settled = bets.filter((b) => b.status && b.status !== 'pending'); const won = settled.filter((b) => b.status === 'hit' || b.status === 'won').length;
    const rec = (sf.summary && sf.summary.botd) || {};
    const head = `<div class="section-head">${sh('star', 'Bets of the day', 'amber')}${compact ? `<button class="link" data-bets="today">Details ${icon('next')}</button>` : `<span class="tiny muted">${esc(dayName(today.date || ''))}</span>`}</div>`;
    if (!bets.length) return head + `<div class="card empty small">Today's card is built from the first analysis of the day (07:00) and topped up section by section during the day — every market Sportybet prices — no price under <b>1.16</b> is offered at all.</div>`;
    const sec = (g) => `<div class="botd-sec">${esc(g.title)} <span class="muted">· ${g.bets.length}</span></div><table class="tbl">${g.bets.slice(0, compact ? 2 : 7).map((b) => safeRow(b, { time: true })).join('')}</table>`;
    const body = groups.length ? groups.map(sec).join('') : `<table class="tbl">${bets.map((b) => safeRow(b, { time: true })).join('')}</table>`;
    return head + `<div class="card botd">${body}
      <div class="row tiny muted" style="margin-top:6px"><div class="grow">${settled.length ? `Today: ${won}/${settled.length} won${bets.length > settled.length ? ` · ${bets.length - settled.length} to play` : ''}` : `${bets.length} singles in ${groups.length || 1} section${groups.length === 1 ? '' : 's'} · overs only · Sportybet prices`}</div>${rec.all && rec.all.n ? `<div>record ${rec.all.won}/${rec.all.n} (${pct(rec.all.rate)})</div>` : ''}</div></div>`;
  }
  PR.safeRow = safeRow; PR.betStatus = betStatus;

  // ------------------------------------------------------------------ V2 components (signal card + scan hero) — real data only
  function signalCard(b, opts) {
    opts = opts || {};
    const f = fx(b.fixture); const st = betStatus(b); const p = (f && f.p) || {};
    const lv = f ? live.for(f) : null;
    const mid = lv && lv.hg != null ? `<span class="score">${lv.hg}\u2013${lv.ag}</span>` : 'VS';
    const time = lv ? (lv.status || 'LIVE') : koShort(b.kickoff);
    const qcls = b.q === 'High' ? '' : b.q === 'Low' ? 'na' : 'moderate';
    const top = opts.bare ? '' : `<div class="signal-top"><span class="competition">${flag(b.country)} ${esc(b.league || '')}</span><span class="time ${lv ? 'live-txt' : ''}">${esc(time)}</span></div>`;
    return `<article class="signal tap${opts.bare ? ' bare' : ''}" data-fx="${esc(b.fixture)}">
      ${top}
      <div class="teams">
        <div class="team">${badge(b.home, f && f.badges && f.badges.home, 40)}<div class="team-name">${teamSpan(b.home, b.country, (f && f.div) || '')}</div></div>
        <div class="vs">${mid}</div>
        <div class="team">${badge(b.away, f && f.badges && f.badges.away, 40)}<div class="team-name">${teamSpan(b.away, b.country, (f && f.div) || '')}</div></div>
      </div>
      <div class="model-grid">
        <div class="model-box"><label>Home</label><strong>${pct(p.H || 0)}</strong><div class="progress"><i style="width:${Math.round((p.H || 0) * 100)}%"></i></div></div>
        <div class="model-box"><label>Draw</label><strong>${pct(p.D || 0)}</strong><div class="progress d"><i style="width:${Math.round((p.D || 0) * 100)}%"></i></div></div>
        <div class="model-box"><label>Away</label><strong>${pct(p.A || 0)}</strong><div class="progress a"><i style="width:${Math.round((p.A || 0) * 100)}%"></i></div></div>
      </div>
      <div class="market-strip">
        <div><div class="market-name">${esc(b.label)}</div>${b.q ? `<div class="quality ${qcls}">data ${esc(b.q)}</div>` : ''}</div>
        <div class="market-values">
          <div><small>Model</small><b>${pct(b.p)}</b></div>
          <div><small>Market</small><b>${b.p_sb != null ? pct(b.p_sb) : 'N/A'}</b></div>
          <div><small>Price</small><b>${b.odds ? f2(b.odds) : 'N/A'}</b></div>
        </div>
      </div>
      <div class="row" style="justify-content:flex-end;margin-top:8px;gap:8px">${st.text !== 'not started' ? `<span class="tiny ${st.cls}">${esc(st.text)}</span>` : ''}${PR.addBtn ? PR.addBtn(b.fixture, b.sel, b.odds) : ''}</div>
    </article>`;
  }
  function scanHero() {
    const d = state.data; const all = d.fixtures || [];
    const safe = safeList('all'); const picks = d.picks || {};
    const valueN = Object.keys(picks).reduce((n, k) => n + (Array.isArray(picks[k]) ? picks[k].length : 0), 0);
    const strongN = all.filter((f) => f.data_ok && f.priced).length;
    const card = (cls, ico, title, count, cta, attrs) => `<button class="scan-stat" ${attrs}><span class="tile ${cls}">${icon(ico)}</span>
      <span class="grow"><strong>${title}</strong><span class="n">${count}</span><span class="go">${cta} ${icon('next', 'sm')}</span></span></button>`;
    return `<div class="scan-top"><span class="date-pill">${icon('calendar', 'sm')} ${esc(dayName(ymd(tzNow())))}</span></div>
      ${card('g', 'trend', 'High model probability', `${safe.length} signal${safe.length === 1 ? '' : 's'}`, 'View signals', 'data-bets="safest"')}
      ${card('y', 'swap', 'Model &gt; Market', `${valueN} market difference${valueN === 1 ? '' : 's'}`, 'View differences', 'data-bets="picks"')}
      ${card('b', 'check', 'Strong data', `${strongN} matches`, 'View matches', 'data-tab-go="matches"')}`;
  }

  // ------------------------------------------------------------------ HOME board: today's bets, every market
  // A bet of the day = a selection that clears its model bar (1X2 ≥55%, corners ≥65%, every other market ≥70%)
  // AND carries a Sportybet price of at least 1.16 (policy.PRICE_FLOOR, 2026-10-27). "High probability" = model
  // ≥70% on any market, in its own tab.
  const HOME_BAR = { result: 0.55, corners: 0.65 };
  const HOME_HIGH = 0.70;
  // user rule 2026-10-17: Over 2.5 and BTTS START from 55%; team goals, double chance and every under are gone (core.js isDropped)
  const barOf = (sel, g) => (PR.SEL_FLOOR[sel] != null ? PR.SEL_FLOOR[sel] : (HOME_BAR[g] || 0.70));
  const highOf = (sel) => (PR.SEL_FLOOR[sel] != null ? PR.SEL_FLOOR[sel] : HOME_HIGH);
  const HOME_EV_MIN_ODDS = 1.13;   // positive-EV tab: Sportybet price at least 1.13 (user rule, 2026-10-09)
  const evOf = (s) => s.p * s.odds - 1;   // expected return per 1 staked at Sportybet's price, model probability
  const HOME_SORTS = [['p', 'Model probability ↓'], ['ev', 'EV ↓'], ['odds_d', 'Odds ↓'], ['odds_a', 'Odds ↑'], ['ko', 'Kick-off'], ['league', 'League']];
  function homeBets(d) {
    const today = ymd(tzNow());
    // 2026-10-27: the old rule only dropped a selection when model AND price were under 1.15; the floor is now
    // absolute — at 1.12–1.15 the bookmaker's hold needs ~89 % to break even, so nothing shorter is offered.
    const worth = (s) => !(s.odds && s.odds < 1.16);
    return (d.fixtures || []).filter((f) => f.date === today && inScope(f)).flatMap((f) => (f.sels || [])
      .filter((s) => s && s.p != null && s.p > 0 && s.p < 1 && s.odds && s.odds > 1 && worth(s) && !PR.isOutlier(s) && !PR.isDropped(s.sel)
        && s.p >= barOf(s.sel, selGroup(s.sel)))
      .map((s) => ({ f, s, g: selGroup(s.sel) })));
  }
  function homeEvBets(d) {
    const today = ymd(tzNow());
    return (d.fixtures || []).filter((f) => f.date === today && inScope(f)).flatMap((f) => (f.sels || [])
      .filter((s) => s && s.p != null && s.p > 0 && s.p < 1 && s.odds && s.odds >= HOME_EV_MIN_ODDS && !PR.isOutlier(s) && !PR.isDropped(s.sel)
        && s.p >= barOf(s.sel, selGroup(s.sel)) && evOf(s) > 0)
      .map((s) => ({ f, s, g: selGroup(s.sel) })));
  }
  // ------------------------------------------------------------------ HOME: high-conviction shortlist (server-built, shortlist.py)
  const SL_ORDER = ['result', 'dc', 'goals', 'btts', 'team', 'cards', 'corners'];   // market grouping order (GROUPS names)
  /** ONE MARKET PER MATCH (user rule, app-wide): from candidate rows keep only the strongest market of each
   *  match. Strength = probability above the market's bar; callers that rank by EV pass their own score. */
  function bestPerMatch(rows, fidOf, scoreOf) {
    const m = new Map();
    rows.forEach((r) => { const k = fidOf(r); const c = m.get(k); if (!c || scoreOf(r) > scoreOf(c) + 1e-9) m.set(k, r); });
    return [...m.values()];
  }
  PR.views.shortlist = function () {
    const d = state.data; const sl = d.shortlist || {}; const c = sl.counts || {}; const R = sl.rules || {};
    const parts = [];
    const np = (sl.primary || []).length;
    const yr = sl.yesterday_results || {};
    parts.push(`<div class="hero-row"><div><div class="kicker">High-conviction shortlist</div><h1>Shortlist</h1></div><span class="quality">today only</span></div>`);
    if (yr && yr.settled) {
      parts.push(`<div class="card compact"><div class="row"><div class="grow"><div class="b">📋 Yesterday’s shortlist (${esc(yr.day || '')})</div><div class="tiny muted">${yr.hits} of ${yr.settled} settled selection${yr.settled === 1 ? '' : 's'} won (${pct(yr.hit_rate)})</div></div><span class="pill ${yr.hit_rate >= 0.7 ? 'hi' : 'mid'}">${yr.hits}/${yr.settled}</span></div></div>`);
    }
    if (!sl.counts) {
      parts.push(`<div class="card empty">The high-conviction shortlist appears after the next analysis run (every 30 minutes).</div>`);
      view().innerHTML = parts.join('');
      return;
    }
    state.slMk = state.slMk || 'any';
    parts.push(`<div class="chips small-chips" style="margin:0 0 10px"><button class="chip tapchip ${state.slMk === 'any' ? 'on' : ''}" data-slmk="any">All markets <b>${np}</b></button>${SL_ORDER.filter((g) => (sl.primary || []).some((x) => x.market === g)).map((g) => `<button class="chip tapchip ${state.slMk === g ? 'on' : ''}" data-slmk="${g}">${GROUP_ICON[g] || ''} ${esc(GROUPS[g] || g)} <b>${(sl.primary || []).filter((x) => x.market === g).length}</b></button>`).join('')}</div>`);
    const na = (v, f) => (v == null ? 'N/A' : f(v));
    const art = {}; ((sl.article || {}).items || []).forEach((a) => { art[a.id] = a; });
    const artId = (x) => `${x.home}|${x.away}|${x.kickoff}`;
    const wdl = (s) => (s || '').split('').map((c) => `<span style="display:inline-block;width:16px;height:16px;line-height:16px;text-align:center;border-radius:4px;font-size:10px;font-weight:700;color:#04121f;margin-right:2px;background:${c === 'W' ? '#22c55e' : c === 'D' ? '#64748b' : '#ef4444'}">${c}</span>`).join('');
    const probBar = (st) => { const p = (st.p || 0) * 100, b = (st.bar || 0.7) * 100, m = st.p_mkt != null ? st.p_mkt * 100 : null;
      return `<div style="position:relative;height:14px;background:#0b1c30;border:1px solid #1e3a5f;border-radius:7px;margin:6px 0 2px"><div style="position:absolute;top:0;bottom:0;left:0;width:${Math.min(p, 100).toFixed(1)}%;background:linear-gradient(90deg,#0e7a4f,#00c86f);border-radius:7px 0 0 7px"></div><div style="position:absolute;top:-2px;bottom:-2px;left:${b.toFixed(1)}%;width:2px;background:#fbbf24"></div>${m != null ? `<div style="position:absolute;top:-2px;bottom:-2px;left:${Math.max(m, 0).toFixed(1)}%;width:2px;background:#e2e8f0"></div>` : ''}</div><div class="tiny muted">Model ${p.toFixed(0)}% (green) · <span style="color:#fbbf24">|</span> market bar ${b.toFixed(0)}%${m != null ? ` · <span style="color:#e2e8f0">|</span> market ${m.toFixed(0)}%` : ''}</div>`; };
    const artBlock = (a) => `<div style="margin-top:8px;padding-top:8px;border-top:1px solid #14273d"><div class="b">📝 The analysis</div><div class="tiny muted" style="margin:4px 0">${esc(a.home)} form ${wdl(a.form.h)} · ${esc(a.away)} form ${wdl(a.form.a)} <span class="muted">(newest first)</span></div>${probBar(a.stats)}${(a.paras || []).slice(0, 2).map((t) => `<div class="tiny" style="margin-top:6px;color:#b8c7da">${esc(t)}</div>`).join('')}<button class="btn" data-pick-open="${esc(a.id)}" style="margin-top:8px;width:100%">Read the full analysis</button></div>`;
    const card = (x) => `<div class="card compact tap" data-fx="${esc(x.fixture || '')}">
      <div class="row"><span class="pill hi">#${x.rank}</span><div class="grow"><div class="b">${esc(x.home)} v ${esc(x.away)}</div><div class="tiny muted">${flag(x.country)} ${esc(x.league)} · ${esc(koShort(x.kickoff))}</div></div><span class="tiny good b">QUALIFIED FOR FURTHER REVIEW</span></div>
      <div class="b" style="margin-top:6px">${GROUP_ICON[x.market] || ''} ${esc(x.label)} @ ${na(x.odds, f2)}</div>
      <table class="tbl" style="margin-top:4px">
        <tr><td>Model probability (raw)</td><td class="right b">${pct(x.p)}</td></tr>
        <tr><td>Calibrated probability</td><td class="right">${na(x.p_cal, pct)}</td></tr>
        <tr><td>Bookmaker implied (margin removed)</td><td class="right">${na(x.p_sb, pct)} <span class="tiny muted">raw ${na(x.implied_raw, pct)}</span></td></tr>
        <tr><td>Estimated edge</td><td class="right ${x.edge_pp > 0 ? 'good' : ''}">${na(x.edge_pp, (v) => `${v > 0 ? '+' : ''}${f1(v)} pp`)}</td></tr>
        <tr><td>Expected value</td><td class="right">${na(x.ev, (v) => `${v > 0 ? '+' : ''}${f1(100 * v)}%`)}</td></tr>
        <tr><td>Data quality · confidence</td><td class="right">${esc(x.quality)} · ${esc(x.confidence)}</td></tr></table>
      ${(x.support || []).length ? `<div class="tiny" style="margin-top:4px"><b>Evidence:</b> ${x.support.map(esc).join(' · ')}</div>` : ''}
      <div class="tiny" style="margin-top:2px"><b>Main risk:</b> ${esc(x.risk || 'N/A')}</div>
      ${art[artId(x)] ? artBlock(art[artId(x)]) : ''}
      ${(x.correlated || []).length ? `<div class="tiny muted" style="margin-top:2px">Same match, correlated (not separate bets): ${x.correlated.map(esc).join(', ')}</div>` : ''}
      <div class="row" style="justify-content:flex-end;margin-top:6px">${PR.addBtn && x.odds ? PR.addBtn(x.fixture, x.sel, x.odds) : ''}</div></div>`;
    const prim = (sl.primary || []).filter((x) => state.slMk === 'any' || x.market === state.slMk);
    parts.push(`<div class="card compact"><div class="b">A · Primary shortlist — today's matches only</div><div class="tiny muted">Odds band ${f2(R.min_odds || 1.16)}–${f2(R.max_odds || 1.90)} · top ${R.max_per_market || 10} per market · Overs only (Unders ignored) · Analysed ${c.analysed} · screened ${c.screened} · watchlist ${c.watchlist} · rejected ${c.rejected}</div></div>`);
    if (prim.length) {
      SL_ORDER.forEach((g) => {
        const items = prim.filter((x) => x.market === g);
        if (!items.length) return;
        parts.push(`<div class="card compact mk-rail ${esc(g)}"><div class="comp-head">${GROUP_ICON[g] || `${icon('star', 'sm')} `} ${esc(GROUPS[g] || g)} · ${items.length}</div>${items.map(card).join('')}</div>`);
      });
      const rest = prim.filter((x) => !SL_ORDER.includes(x.market));
      if (rest.length) parts.push(`<div class="card compact"><div class="comp-head">${icon('star', 'sm')} Other markets · ${rest.length}</div>${rest.map(card).join('')}</div>`);
    } else {
      parts.push(`<div class="card empty small"><b>NO QUALIFYING SELECTIONS${state.slMk === 'any' ? '' : ' IN THIS MARKET'}.</b> Nothing passed every gate — standards are not lowered to fill the list.</div>`);
    }
    if ((sl.watchlist || []).length) parts.push(`<div class="card compact"><div class="b">B · Secondary watchlist</div><table class="tbl" style="margin-top:4px">${sl.watchlist.map((x) => `<tr class="tap" data-fx="${esc(x.fixture || '')}"><td><div class="b">${esc(x.home)} v ${esc(x.away)}</div><div class="tiny muted">${esc(x.label)} @ ${na(x.odds, f2)} · model ${pct(x.p)}</div><div class="tiny">Not yet qualified: ${esc((x.reasons || [])[0] || '')}</div></td></tr>`).join('')}</table></div>`);
    if ((sl.rejected_patterns || []).length) parts.push(`<div class="card compact"><div class="b">C · Rejected (${c.rejected})</div><div class="tiny muted" style="margin-top:4px">Main reasons: ${sl.rejected_patterns.map((r) => `${esc(r[0])} <b>${r[1]}</b>`).join(' · ')}</div></div>`);
    const tr = sl.track || {}; const trow = (k, n) => { const t = tr[k] || {}; return t.n ? `<tr><td>${n}</td><td class="right">${t.n}</td><td class="right">${pct(t.hit_rate)}</td><td class="right">${pct(t.expected)}</td><td class="right">${t.roi == null ? 'N/A' : `${t.roi > 0 ? '+' : ''}${f1(100 * t.roi)}%`}</td></tr>` : ''; };
    const trBody = trow('primary', 'Shortlist') + trow('watchlist', 'Watchlist') + trow('rejected', 'Rejected');
    parts.push(`<div class="card compact"><div class="b">Daily decision summary</div><div class="small" style="margin-top:4px">${esc(sl.verdict || '')}</div>
      <div class="tiny muted" style="margin-top:4px">${(sl.markets || []).length ? `Markets on the shortlist: ${sl.markets.map((m) => `${esc(GROUPS[m[0]] || m[0])} ${m[1]}`).join(', ')}. ` : ''}</div>
      ${trBody ? `<table class="tbl head" style="margin-top:6px"><tr><th>Track record</th><th class="right">Settled</th><th class="right">Hit</th><th class="right">Expected</th><th class="right">Flat ROI</th></tr>${trBody}</table>` : '<div class="tiny muted" style="margin-top:4px">Track record: every decision is logged before kick-off and settled — the numbers appear once results come in.</div>'}</div>`);
    parts.push(`<div class="card tiny muted"><b>How the shortlist is built</b> — every priced selection of every analysed match goes through the same gates. <b>Rejected</b> if: the match failed data checks, no Sportybet price (N/A, never assumed), odds <b>under ${f2(R.min_odds || 1.16)} or over ${f2(R.max_odds || 1.90)}</b> (the high-conviction band), probability under its market bar (1X2 and Over 2.5 from 55%, corners 65%, every other goals line 70%), or a model/market gap over ${R.max_edge_pp || 12} pp (data fault). <b>Watchlist</b> if: data quality Low, Low confidence, a model-v-data warning, a research conflict, carried prices, or a price under <b>95 % of the pick's own fair price</b> (the 2026-10-27 price check — 65 % of the old book failed it). <b>EV and edge are not gates</b> — strength and data support decide (user rule 2026-10-11); value hunting lives on the Positive EV tab. <b>Every league with enough data</b> (user rule 2026-10-17): the top divisions, the 22 main European divisions, the African leagues and every other league whose archive has a real table, a deep results history and match statistics — no cups, no women/youth/friendlies, no Australia (Japan and the J-League are in), and both teams need 8+ recent matches with data or the match is not analysed at all. <b>Double chance, team goals, cards, BTTS, Over 0.5 and every under are dropped</b> (2026-10-27 model audit): they lost money for months — double chance −16.7 %, team goals −6.4 %, cards −9.4 %, BTTS −7.0 %, Over 0.5 −5.9 % — so the shortlist now competes in <b>Over 1.5, Over 2.5, corners and 1X2</b>, and nothing priced under <b>1.16</b> is offered at all. The same diet applies to the Leagues browser, the fixtures list and search. Every pick below carries a <b>data-written analysis</b> (form chips, model-v-market bar, deep reasoning) — written from the model's own numbers, never invented. One selection per match; each market — Over 1.5, Over 2.5, corners, 1X2, then the other goals lines — claims its own <b>top ${R.max_per_market || 10}</b> matches in turn, so Over 1.5 cannot take every slot — picking the bests, never padding. Ranked by the <b>market-anchored edge</b> (published probability minus the de-vigged price, never more than 3 points) and the price actually on offer, not by probability alone. Calibrated probability is N/A (no validated live calibration). <b>Today's matches only; Overs only (Unders are ignored).</b> A shortlist for your review — never an instruction to bet, never guaranteed.</div>`);
    view().innerHTML = parts.join('');
    $$('[data-slmk]').forEach((b) => { b.onclick = () => { state.slMk = b.dataset.slmk; PR.render(); window.scrollTo(0, 0); }; });
    $$('[data-pick-open]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); const a = art[b.dataset.pickOpen]; if (a) { state.pickArt = a; PR.push({ type: 'pick' }); } }; });
  };


  PR.views.x12 = function () {
    const d = state.data; const sl = d.shortlist || {}; const rows = sl.x12 || [];
    const R = sl.rules || {};
    const parts = [];
    parts.push(`<div class="hero-row"><div><div class="kicker">Match result</div><h1>1X2</h1></div><span class="quality">today only</span></div>`);
    parts.push(`<div class="card compact"><div class="b">Home, draw or away — one pick per match</div><div class="tiny muted">Independent of the Shortlist winner. Model bar 60%. Sportybet prices ${f2(1.20)}–${f2(3.50)}. Overs-side policy still applies (no double chance). Statistical information, not betting advice. 18+.</div></div>`);
    if (!sl.counts) {
      parts.push(`<div class="card empty">The 1X2 board appears after the next analysis run (every 30 minutes).</div>`);
      view().innerHTML = parts.join('');
      return;
    }
    const na = (v, f) => (v == null ? 'N/A' : f(v));
    const card = (x) => `<div class="card compact tap" data-fx="${esc(x.fixture || '')}">
      <div class="row"><span class="pill hi">#${x.rank}</span><div class="grow"><div class="b">${esc(x.home)} v ${esc(x.away)}</div><div class="tiny muted">${flag(x.country)} ${esc(x.league)} · ${esc(koShort(x.kickoff))}</div></div></div>
      <div class="b" style="margin-top:6px">🏆 ${esc(x.label)} @ ${na(x.odds, f2)}</div>
      <table class="tbl" style="margin-top:4px">
        <tr><td>Model probability</td><td class="right b">${pct(x.p)}</td></tr>
        <tr><td>Bookmaker implied (margin removed)</td><td class="right">${na(x.p_sb, pct)}</td></tr>
        <tr><td>Data quality · confidence</td><td class="right">${esc(x.quality)} · ${esc(x.confidence)}</td></tr></table>
      <div class="row" style="justify-content:flex-end;margin-top:6px">${PR.addBtn && x.odds ? PR.addBtn(x.fixture, x.sel, x.odds) : ''}</div></div>`;
    if (rows.length) {
      parts.push(`<div class="card compact mk-rail result"><div class="comp-head">🏆 Match result · ${rows.length}</div>${rows.map(card).join('')}</div>`);
    } else {
      parts.push(`<div class="card empty small"><b>NO QUALIFYING 1X2 SELECTIONS.</b> Nothing cleared the 55% bar with a verified Sportybet price in ${f2(1.20)}–${f2(3.50)}.</div>`);
    }
    parts.push(`<div class="card tiny muted"><b>How 1X2 is built</b> — every analysed match is screened for home / draw / away from <b>55%</b>. One selection per match (the strongest 1X2). This tab does not steal slots from Over 2.5 or the corner lines on the Shortlist. Not an instruction to bet.</div>`);
    view().innerHTML = parts.join('');
  };

  // ------------------------------------------------------------------ SEQUENCES: the user's betting windows
  // "I bet in the morning for matches playing 7-12, 12-16, 16-20 and 20-midnight." The Sequences tab is
  // the day's SHORTLIST split into those windows — the exact same rule-approved picks (every gate of
  // shortlist.py: data checks, verified prices, odds band 1.16-1.90, market bars, EV >= 0, believable
  // gaps, quality/confidence, Overs only, one strongest market per match across ALL markets). Nothing
  // looser, nothing goals-biased: corners, cards, result, DC, BTTS and team goals all compete on the
  // same score, and the strongest wins the match's slot.
  const SEQ_WINDOWS = [
    ['early', 'Early hours', '00:00 \u2013 07:00', 0, 7, '#94a3b8'],
    ['morning', 'Morning sequence', '07:00 \u2013 12:00', 7, 12, '#fbbf24'],
    ['midday', 'Midday sequence', '12:00 \u2013 16:00', 12, 16, '#38bdf8'],
    ['afternoon', 'Afternoon sequence', '16:00 \u2013 20:00', 16, 20, '#00c86f'],
    ['evening', 'Evening sequence', '20:00 \u2013 midnight', 20, 24, '#a78bfa'],
  ];
  PR.views.sequences = function () {
    const d = state.data; const sl = d.shortlist || {}; const now = tzNow();
    const parts = [];
    parts.push(`<div class="hero-row"><div><div class="kicker">Bet in sequences</div><h1>Sequences</h1></div><span class="quality">shortlist rules</span></div>`);
    if (!sl.counts) {
      parts.push(`<div class="card empty">The sequences appear after the next analysis run (every 30 minutes) \u2014 they are the day's shortlist split into your betting windows.</div>`);
      view().innerHTML = parts.join('');
      return;
    }
    // the day's qualified picks only (kickoff still ahead); every window counts, even when empty
    const prim = (sl.primary || []).filter((x) => x.fixture && parseLocal(x.kickoff) > now);
    const buckets = SEQ_WINDOWS.map(([k, name, range, lo, hi, col]) => ({ k, name, range, lo, hi, col, items: [] }));
    prim.forEach((x) => {
      const h = +String(x.kickoff).slice(11, 13);
      (buckets.find((b) => h >= b.lo && h < b.hi) || buckets[0]).items.push(x);
    });
    buckets.forEach((b) => b.items.sort((a, b2) => String(a.kickoff).localeCompare(String(b2.kickoff))));
    parts.push(`<div class="card small"><b>Your day in sequences</b> \u2014 ${prim.length} qualified pick${prim.length === 1 ? '' : 's'} left today, split into your betting windows. These are the <b>same picks as the Shortlist</b>: one strongest market per match with <b>all markets competing</b> (1X2, Over 1.5, Over 2.5, corners), odds 1.16\u20131.90, Overs only, data-checked \u2014 EV is not a gate. Updates every 30 minutes; matches drop out at kick-off.</div>`);
    buckets.forEach((b) => {
      const head = `<div class="card compact" style="border-left:3px solid ${b.col}"><div class="comp-head">${esc(b.name)} <span class="tiny muted">\u00b7 ${esc(b.range)} \u00b7 ${b.items.length} pick${b.items.length === 1 ? '' : 's'}</span></div>`;
      if (!b.items.length) { parts.push(head + `<div class="tiny muted" style="padding:2px 0 4px">No qualified pick in this window right now \u2014 the next run (every 30 minutes) fills it if matches qualify.</div></div>`); return; }
      parts.push(head + `<table class="tbl" style="margin-top:2px">${b.items.map((x) => `<tr class="tap" data-fx="${esc(x.fixture)}"><td class="tiny muted nowrap">${esc(koTime(x.kickoff))}</td>
          <td><div class="b">${esc(x.home)} v ${esc(x.away)}</div><div class="tiny muted">${GROUP_ICON[x.market] || ''} ${esc(x.label)} \u00b7 ${flag(x.country)} ${esc(x.league || '')}</div></td>
          <td class="right nowrap"><b>${x.odds ? f2(x.odds) : '\u2013'}</b></td>
          <td class="right">${pill(x.p, 0.8, 0.7)}</td></tr>`).join('')}</table>
        <div class="tiny muted" style="padding:4px 0 6px">Whole window as one sequence: <b>${(() => { const od = b.items.reduce((acc, x) => acc * (x.odds || 1), 1); const pp = b.items.reduce((acc, x) => acc * (x.p_cal || x.p || 0.5), 1); return f2(od) + ' combined \u00b7 model ' + (100 * pp).toFixed(0) + '% it lands'; })()}</b> (per-pick odds multiplied — informational, not an advised bet).</div></div>`);
    });
    parts.push(`<div class="card tiny muted"><b>Same rules as the Shortlist</b> \u2014 every gate applies: the match passed the data checks, Sportybet prices it, odds 1.16\u20131.90, a price of at least 95 % of the pick's own fair price, the model clears that market's bar (1X2 and Over 2.5 from 55%, corners 65%, every other goals line 70%), a believable model/market gap, solid data quality. EV is not a gate \u2014 strength and data support decide. One market per match: the strongest across <b>all</b> markets \u2014 ranked by the market-anchored edge and the price on offer, never probability alone. Overs only; today only; a pick for your review, never an instruction to bet.</div>`);
    view().innerHTML = parts.join('');
  };

  // Display-only collections: use existing eligibility and ranking; never recalculate a probability.
  function homeCollections(d) {
    const strength = (r) => (r.s.p - barOf(r.s.sel, r.g)) * 100 + r.s.p * 10;
    const eligible = homeBets(d);
    const all = bestPerMatch(eligible, (r) => r.f.id, strength);
    const high = all.filter((r) => r.s.p >= highOf(r.s.sel));
    // Filter BEFORE choosing one market per match: a lower-bar 79% line must not hide an 80% line.
    // Compare the actual published number, not a rounded percentage or a bookmaker implied probability.
    const eighty = bestPerMatch(eligible.filter((r) => Number.isFinite(r.s.p) && r.s.p >= 0.80), (r) => r.f.id, strength);
    const ev = bestPerMatch(homeEvBets(d), (r) => r.f.id, (r) => evOf(r.s));
    return { all, high, eighty, ev };
  }
  function homeLaunchpad(collections) {
    const tile = (cls, ico, title, sub, attrs) => `<button class="home-quick ${cls}" ${attrs}>
      <span class="quick-icon">${icon(ico)}</span><strong>${title}</strong><span class="quick-caption">${sub}</span><span class="quick-arrow" aria-hidden="true">${icon('next', 'sm')}</span></button>`;
    return `<nav class="home-launchpad" aria-label="Home collections">
      ${tile('advisor', 'shield', 'Bet Advisor', 'Analysis &amp; record', 'data-page-go="advisor"')}
      ${tile('daily', 'star', 'Bets of the Day', `${collections.all.length} selections today`, `data-home-open="all" aria-pressed="${!state.homeTab || state.homeTab === 'all'}"`)}
      ${tile('eighty', 'trend', '80%+ Markets', `${collections.eighty.length} qualifying today`, `data-home-open="eighty" aria-pressed="${state.homeTab === 'eighty'}"`)}
    </nav>`;
  }
  function homeBoard(d, collections) {
    const { all, high, eighty, ev: evAll } = collections || homeCollections(d);
    const tab = ['high', 'eighty', 'ev'].includes(state.homeTab) ? state.homeTab : 'all';
    const mk = state.homeMk || 'any'; const sort = state.homeSort || (tab === 'ev' ? 'ev' : 'p');
    const base = tab === 'eighty' ? eighty : tab === 'high' ? high : tab === 'ev' ? evAll : all;
    const groups = Object.keys(GROUPS).filter((g) => base.some((r) => r.g === g));
    const rows = base.filter((r) => mk === 'any' || r.g === mk);
    const cmp = { p: (a, b) => b.s.p - a.s.p, ev: (a, b) => evOf(b.s) - evOf(a.s), odds_d: (a, b) => b.s.odds - a.s.odds, odds_a: (a, b) => a.s.odds - b.s.odds,
      ko: (a, b) => String(a.f.kickoff).localeCompare(String(b.f.kickoff)) || b.s.p - a.s.p,
      league: (a, b) => String(a.f.league || a.f.competition || '').localeCompare(String(b.f.league || b.f.competition || '')) || b.s.p - a.s.p }[sort] || ((a, b) => b.s.p - a.s.p);
    rows.sort(cmp);
    const matches = new Set(rows.map((r) => r.f.id)).size;
    const row = ({ f, s, g }) => { const lv = live.for(f); const st = lv && lv.hg != null ? `<span class="live-txt">${esc(lv.status || 'LIVE')} ${lv.hg}–${lv.ag}</span>` : esc(koTime(f.kickoff));
      return `<tr class="tap" data-fx="${esc(f.id)}"><td class="tiny muted nowrap">${st}</td>
        <td><div class="b">${GROUP_ICON[g] || ''} ${esc(s.label || selLabel(s.sel, f.home, f.away))}</div><div class="tiny muted">${flag(f.country)} ${esc(f.league || f.competition || '')} · ${teamSpan(f.home, f.country, f.div)} v ${teamSpan(f.away, f.country, f.div)}</div></td>
        <td class="right nowrap"><b>${f2(s.odds)}</b>${s.p_sb != null ? `<div class="tiny muted">${pct(s.p_sb)} implied</div>` : ''}${evOf(s) > 0 ? `<div class="tiny good">EV +${f1(100 * evOf(s))}%</div>` : ''}</td>
        <td class="right nowrap">${pill(s.p, 0.8, 0.7)} ${PR.addBtn ? PR.addBtn(f.id, s.sel, s.odds) : ''}</td></tr>`; };
    const out = [];
    out.push(`<section id="home-board" class="home-board-head" tabindex="-1"><div class="kicker">Your matchday collections</div><h2>${tab === 'eighty' ? '80%+ probability markets' : tab === 'high' ? 'High probability' : tab === 'ev' ? 'Positive EV' : 'Bets of the Day'}</h2><p>${tab === 'eighty' ? 'Published model probability of at least 80%. No lower-probability fillers.' : 'Explore today’s selections. Open a match for the full analysis.'}</p></section>`);
    out.push(`<div class="card compact home-board-controls">${segmented([['all', `${icon('star')} Bets of the Day (${all.length})`], ['eighty', `${icon('trend')} 80%+ (${eighty.length})`], ['high', `${icon('trend')} High probability (${high.length})`], ['ev', `${icon('tag')} Positive EV (${evAll.length})`]], tab, 'ht')}
      <div class="chips small-chips" style="margin-top:6px"><button class="chip tapchip ${mk === 'any' ? 'on' : ''}" data-hmk="any">All markets <b>${base.length}</b></button>${groups.map((g) => `<button class="chip tapchip ${mk === g ? 'on' : ''}" data-hmk="${g}">${GROUP_ICON[g]} ${esc(GROUPS[g])} <b>${base.filter((r) => r.g === g).length}</b></button>`).join('')}</div>
      <div class="row" style="margin-top:6px"><div class="grow tiny muted">${rows.length} bet${rows.length === 1 ? '' : 's'} · ${matches} match${matches === 1 ? '' : 'es'}</div><span class="tiny muted">Sort&nbsp;</span>${select('home-sort', HOME_SORTS, sort)}</div></div>`);
    const shown = Math.min(rows.length, state.homeShow || 100);
    if (rows.length) out.push(`<div class="card compact"><table class="tbl head home-selection-table" style="margin-top:4px"><tr><th>Time</th><th>Match · bet</th><th class="right">Sportybet</th><th class="right">Model</th></tr>${rows.slice(0, shown).map(row).join('')}</table>${shown < rows.length ? `<div class="row" style="justify-content:center;margin-top:8px"><button class="btn" id="home-more">Show ${Math.min(100, rows.length - shown)} more · ${rows.length - shown} left</button></div>` : ''}</div>`);
    else out.push(`<div class="card empty small">${tab === 'ev' ? `No bet the model supports has positive EV at a Sportybet price of ${f2(HOME_EV_MIN_ODDS)} or more today${mk !== 'any' ? ' in this market' : ''}.` : tab === 'eighty' ? `No eligible priced market has a published model probability of 80% or more today${mk !== 'any' ? ' in this market' : ''}. The threshold is never lowered to fill this collection.` : tab === 'high' ? `No priced bet reaches ${pct(HOME_HIGH)} today${mk !== 'any' ? ' in this market' : ''} yet.` : `No priced bet clears its model bar today${mk !== 'any' ? ' in this market' : ''} yet.`} The board fills as Sportybet prices and probabilities firm up.${majorOnly() ? ' (Major leagues only — change in Settings.)' : ''}</div>`);
    if (tab === 'eighty') out.push(`<div class="card tiny muted"><b>80% is a filter, not a promise.</b> This collection uses the unrounded published model probability (≥0.80), today’s fixtures, existing market restrictions, data checks and odds floor of 1.16. One qualifying market per match. Saved data may be out of date; check the cache/updated indicator. A selection can still lose.</div>`);
    if (tab === 'ev') out.push(`<div class="card tiny muted"><b>Positive EV</b> — bets the model supports (same bars: 1X2 and Over 2.5 ≥55%, corners ≥65%, every other goals line ≥70%) whose Sportybet price is <b>${f2(HOME_EV_MIN_ODDS)} or more</b> and pays more than the model thinks is fair: <b>EV = model probability × odds − 1 &gt; 0</b>. EV +5% means the model expects 5c back per R1 staked over many such bets — an estimate that is only as good as the model, not a guarantee. Gaps of 15+ points over the price stay quarantined as data faults.</div>`);
    out.push(`<div class="card tiny muted"><b>How this board is built</b> — <b>one bet per match</b>: the model names each match's strongest market and lists only that one (the match page still shows every market). Today's matches, all markets. A bet appears when the model clears its bar (<b>1X2 and Over 2.5 from 55%</b>, <b>corners 65%</b>, <b>every other goals line 70%</b>) <b>and</b> Sportybet prices it at <b>1.16 or more</b>. <b>High probability</b> = model ≥70% on any market (Over 2.5 and 1X2 from 55%). The price anchors the published probability (25 % model / 75 % de-vigged market); selections 15+ points above the price are quarantined as data faults. A high probability is not a certainty.</div>`);
    if (!PR._homeRefreshed && (d.fixtures || []).length && !(d.fixtures || []).some((f) => (f.sels || []).length)) { PR._homeRefreshed = true; setTimeout(() => PR.loadData(false), 250); }
    return out.join('');
  }
  function wireHomeBoard() {
    const openBoard = (tab) => {
      state.homeTab = tab; state.homeMk = 'any'; state.homeSort = null; state.homeShow = 100; PR.render();
      const board = $('#home-board'); if (board) { board.focus({ preventScroll: true }); board.scrollIntoView({ block: 'start', behavior: 'auto' }); }
    };
    $$('[data-ht]').forEach((b) => { b.setAttribute('aria-pressed', String(b.dataset.ht === (state.homeTab || 'all'))); b.onclick = () => openBoard(b.dataset.ht); });
    $$('[data-home-open]').forEach((b) => { b.onclick = () => openBoard(b.dataset.homeOpen); });
    $$('[data-hmk]').forEach((b) => { b.onclick = () => { state.homeMk = b.dataset.hmk; state.homeShow = 100; PR.render(); }; });
    const so = $('#home-sort'); if (so) so.onchange = (e) => { state.homeSort = e.target.value; state.homeShow = 100; PR.render(); };
    const mo = $('#home-more'); if (mo) mo.onclick = () => { const y = window.scrollY; state.homeShow = (state.homeShow || 100) + 100; PR.render(); window.scrollTo(0, y); };
  }

  // ------------------------------------------------------------------ STRONG MARKETS FOR THE DAY
  // One home section. 2026-10-27 (model review): probability at least 78% (was 75%), a real Sportybet price of 1.16
  // or more, and only Over 1.5 total goals and corners — team goals (-6.4 % ROI) and bookings (-9.4 %) left with
  // their families. Built server-side in appdata.strong_markets_payload from policy.is_strong_market, so the filter
  // lives in one place. Total corners get their own room (appdata.STRONG_CAPS) so team-corner lines cannot fill it.
  function strongMarketsCard(d) {
    const sm = d.strong_markets || {};
    const bets = sm.bets || [];
    const pMin = sm.min_p || 0.78, oMin = sm.min_odds || 1.16;
    const kick = `<div class="section-head"><h2><span class="ico amber">${icon('star')}</span>Strong markets for the day</h2><span class="tiny muted">${bets.length} selection${bets.length === 1 ? '' : 's'} · ${pct(pMin)}+ · ${f2(oMin)}+</span></div>`;
    if (!bets.length) {
      return kick + `<div class="card empty small">Nothing clears <b>${pct(pMin)}</b> at a real price of <b>${f2(oMin)}</b> or better yet today. This section only carries Over 1.5 total goals and corners — it fills as prices and probabilities firm up.</div>`;
    }
    const fam = { corner_total: 'Total corners', corner_team: 'Team corners', o15: 'Over 1.5 goals' };
    const rows = bets.map((x) => `<tr class="tap" data-fx="${esc(x.id)}">
      <td class="tiny muted nowrap">${esc(koTime(x.kickoff))}</td>
      <td><div class="b">${esc(x.label || x.sel)}</div><div class="tiny muted">${flag(x.country)} ${teamSpan(x.home, x.country)} v ${teamSpan(x.away, x.country)} · ${esc(fam[x.family] || '')}</div></td>
      <td class="right nowrap"><b>${f2(x.odds)}</b><div class="tiny muted">price</div></td>
      <td class="right nowrap">${pill(x.p, 0.88, 0.78)}<div class="tiny muted">model</div></td></tr>`).join('');
    return kick + `<div class="card compact"><table class="tbl head"><tr><th>Time</th><th>Match · market</th><th class="right">Sportybet</th><th class="right">Model</th></tr>${rows}</table>
      <div class="tiny muted" style="padding:6px 0 2px">Model probability <b>${pct(pMin)} or more</b> and a real price of <b>${f2(oMin)}+</b>, in Over 1.5 total goals and corners only. One row per market; no accumulators. A probability is not a certainty — this is information for your review, never an instruction to bet.</div></div>`;
  }

  // ------------------------------------------------------------------ HOME
  // The drill-down and its Home count must use the same local-day definition.
  function matchdayFixtures(fixtures, analysedOnly) {
    const today = ymd(tzNow());
    return fixtures.filter((f) => f.date === today && (!analysedOnly || f.data_ok));
  }
  function matchdayStats(fixtures, signals, liveN) {
    const stat = (key, n, label, description) => `<button type="button" class="matchday-stat" data-matchday="${key}" aria-label="${esc(description)}"><b>${n}</b><span>${label}</span></button>`;
    return `<div class="hero-nums matchday-stats">${stat('fixtures', fixtures.length, 'Fixtures', 'View today’s fixtures')}${stat('analysed', fixtures.filter((f) => f.data_ok).length, 'Analysed', 'View all analysed matches today')}${stat('signals', signals.length, 'Signals', 'View today’s high-probability signals')}${stat('live', liveN, 'Live', 'View matches in play')}</div>`;
  }
  function openMatchday(key) {
    if (key === 'fixtures' || key === 'analysed') {
      state.search = ''; // An older search must not silently hide this collection.
      state.matchFilter = key === 'analysed' ? 'analysed' : 'today';
      state.sort = 'ko'; state.matchesView = 'time';
      PR.setTab('matches');
    } else if (key === 'signals') {
      state.betsView = 'safest'; state.betGroup = 'all'; state.safestAll = false;
      PR.setTab('bets');
    } else if (key === 'live') {
      // Match the counter: worldwide when loaded, tracked in-play until then.
      state.liveView = Array.isArray(state.liveAll) ? 'all' : 'tracked';
      PR.setTab('live');
    }
  }
  PR.views.home = function () {
    const d = state.data, m = d.meta, sf = d.safe || { bets: [] }; const parts = [];
    const todayFixtures = matchdayFixtures(d.fixtures, false);
    const collections = homeCollections(d);
    const inPlay = live.inPlay(); const cov = m.coverage || {};
    const safe = safeList('all').filter(sameDay);   // only matches played on this day — never future fixtures
    const dayLabel = String(dayName(m.generated || '')).replace(/^Today · /, '');
    const liveN = Array.isArray(state.liveAll) ? state.liveAll.length : inPlay.length;
    const genDt = parseLocal(m.generated || '');
    const ageMin = genDt ? Math.max(0, Math.round((tzNow() - genDt) / 60000)) : null;
    const hAlerts = Array.isArray(m.health_alerts) ? m.health_alerts : [];
    const feedWarn = !!(m.odds_asof || hAlerts.length || (ageMin != null && ageMin > 65));
    const feedBadge = `<span class="tiny ${feedWarn ? 'warn' : 'good'}" style="margin-left:6px">● ${m.odds_asof ? 'Cached prices' : feedWarn ? 'Degraded feed' : 'Feed live'}</span>`;
    parts.push(`<div class="hero-row matchday-head"><div><div class="kicker">${esc(dayLabel)}</div><h1>Your matchday.</h1></div><span class="quality updated-pill">${icon('refresh', 'sm')} Updated ${esc(koTime(m.generated || ''))}${feedBadge}</span></div>`);
    parts.push(homeLaunchpad(collections));
    parts.push(`<section class="card hero matchday-hero home-stadium">
      <div class="pitch-art" aria-hidden="true"><i></i><span></span></div>
      <div class="matchday-heading"><div><div class="eyebrow">THE MATCHDAY PICTURE</div><div class="matchday-intro">One game. Every angle.</div></div><span class="coverage-tag">${cov.competitions || '–'} competitions</span></div>
      ${matchdayStats(todayFixtures, safe, liveN)}
      <div class="matchday-foot"><span>Next update <b>${esc(koTime(m.next_run || ''))}</b></span><span class="coverage-line">${cov.priced || 0} priced${m.odds_asof ? ` · prices from ${esc(koTime(m.odds_asof))} (book refresh blocked)` : ' by Sportybet'}</span></div>
      ${inPlay.length ? `<div class="live-strip" data-tab-go="live"><span class="status-dot live"></span><div class="grow"><b>${inPlay.length} tracked in play</b> · ${inPlay.slice(0, 2).map((f) => { const s = live.for(f); return `${esc(f.home)} ${s.hg}–${s.ag} ${esc(f.away)}`; }).join(' · ')}${inPlay.length > 2 ? ' …' : ''}</div>${icon('next', 'sm')}</div>` : ''}</section>`);
    if (state.homeTab !== 'eighty') parts.push(strongMarketsCard(d));
    if (PR.APP_VERSION && settings.seenVersion !== PR.APP_VERSION) {
      parts.push(`<div class="card whatsnew"><div class="row"><div class="grow"><b>${icon('sparkle', 'sm')} New in Mr 2 Odds ${esc(PR.APP_VERSION)}</b></div><button class="link" id="wn-close">${icon('x')}</button></div>
        <ul><li><b>A fresh Home</b> — football-inspired visuals and direct access to Bet Advisor and Bets of the Day.</li><li><b>80%+ Markets</b> — a dedicated collection filtered by the actual published model probability, never rounded up to qualify.</li><li><b>Same analysis, faster access</b> — prediction calculations, saved settings and cache-first loading remain unchanged. A high probability is never a guarantee.</li></ul></div>`);
    }
    const favs = (PR.favList ? PR.favList() : []).map((x) => fx(x.fixture)).filter(Boolean).sort((a, b) => a.kickoff.localeCompare(b.kickoff));
    if (favs.length && state.homeTab !== 'eighty') parts.push(`<div class="section-head"><h2><span class="ico amber">${icon('star')}</span>Your matches</h2><button class="link" data-tab-go="matches" data-mf-go="fav">All ${favs.length} ${icon('next')}</button></div><div class="card compact">${favs.slice(0, 5).map((f) => { const s = live.for(f); return matchRow(f, { live: s, sub: `${flag(f.country)} ${esc(f.competition)}${f.safe ? ` · 📈 <b>${esc(selShort(f.safe[0]))}</b> ${pct(f.safe[1])}` : ''}`, right: s && s.hg != null ? '' : `<span class="pill ${f.p.O25 >= 0.6 ? 'hi' : ''}">O2.5 ${pct(f.p.O25)}</span>` }); }).join('')}</div>`);
    parts.push(homeBoard(d, collections));
    // Keep the full first-run release notes accessible, but don't let them push today's board below the opening viewport.
    const whatsNewIndex = parts.findIndex((html) => html.includes('class="card whatsnew"'));
    if (whatsNewIndex >= 0) parts.push(parts.splice(whatsNewIndex, 1)[0]);
    if (state.homeTab !== 'eighty' && PR.ticketsCard && PR.tickets().some((t) => t.status === 'pending')) parts.push(PR.ticketsCard(true));
    parts.push(PR.editorCard(true));
    parts.push(contactCard(true));
    view().innerHTML = parts.join('');
    wireCommon(); wireHomeBoard(); if (PR.wireTickets) PR.wireTickets();
    const wn = $('#wn-close'); if (wn) wn.onclick = () => { settings.seenVersion = PR.APP_VERSION; PR.saveSettings(); PR.render(); };
  };
  function wireCommon() {
    $$('[data-matchday]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); openMatchday(b.dataset.matchday); }; });
    $$('[data-bets]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); state.betsView = b.dataset.bets; PR.setTab('bets'); }; });
    $$('[data-tab-go]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); if (b.dataset.mfGo) state.matchFilter = b.dataset.mfGo; PR.setTab(b.dataset.tabGo); }; });
    $$('[data-page-go]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); PR.push({ type: b.dataset.pageGo }); }; });
  }

  // ------------------------------------------------------------------ BETS
  const leagueChips = () => `<div class="chips small-chips"><button class="chip tapchip ${!majorOnly() ? 'on' : ''}" data-lg="all">🌍 All leagues</button><button class="chip tapchip ${majorOnly() ? 'on' : ''}" data-lg="major">🏆 Major leagues</button></div>`;
  PR.views.bets = function () {
    const parts = []; const v = state.betsView || 'today';
    parts.push(scanHero());
    parts.push(`<div class="card compact sticky-ish">${segmented([['today', `${icon('star')} Today`], ['top', `${icon('shield')} Top leagues`], ['safest', `${icon('trend')} High prob.`], ['goals', `${icon('ball')} Goals`], ['corners', `${icon('corner')} Corners`], ['cards', `${icon('card')} Cards`], ['picks', `${icon('trend')} Model picks`]], v, 'bv')}</div>`);
    if (v === 'today') renderToday(parts);
    else if (v === 'top') renderTop(parts);
    else if (v === 'safest') renderSafest(parts);
    else if (v === 'picks') renderPicks(parts);
    else renderFamily(parts, v);
    parts.push(`<div class="card compact tap" id="guide-link"><div class="row"><span class="ico">${icon('info')}</span><div class="grow"><b>What do these markets mean?</b><div class="tiny muted">Over 1.5, Over 2.5, corners and 1X2 — and how the probabilities are made.</div></div>${icon('next')}</div></div>`);
    view().innerHTML = parts.join('');
    $$('[data-bv]').forEach((b) => { b.onclick = () => { state.betsView = b.dataset.bv; PR.render(); window.scrollTo(0, 0); }; });
    $$('[data-scope]').forEach((b) => { b.onclick = () => { state.safestAll = b.dataset.scope === 'all'; PR.render(); }; });
    $$('[data-lg]').forEach((b) => { b.onclick = () => { settings.leagues = b.dataset.lg; PR.saveSettings(); PR.render(); }; });
    const hp = $('#f-hip'); if (hp) hp.onchange = (e) => { settings.hiP = +e.target.value; PR.saveSettings(); PR.render(); };
    const mg = $('#f-group'); if (mg) mg.onchange = (e) => { state.betGroup = e.target.value; PR.render(); };
    $$('[data-more]').forEach((b) => { b.onclick = () => { state.expanded[b.dataset.more] = true; PR.render(); }; });
    const g = $('#guide-link'); if (g) g.onclick = () => PR.push({ type: 'guide' });
    $$('[data-board]').forEach((b) => { b.onclick = () => { state.board = b.dataset.board; PR.render(); }; });
    wireCommon(); if (PR.wireTickets) PR.wireTickets();
  };
  // 2026-10-27: BTTS and bookings left the policy, so their chips would rank an empty board — gone.
  const BOARDS = [['H', 'Home wins'], ['A', 'Away wins'], ['O15', 'Over 1.5'], ['O25', 'Over 2.5'], ['CO95', 'Corners 9.5+']];
  function renderTop(parts) {
    const key = state.board || 'H'; const title = (BOARDS.find((b) => b[0] === key) || [])[1] || key;
    parts.push(`<div class="card compact">${leagueChips()}<div class="chips small-chips" style="margin-top:6px">${BOARDS.map(([k, l]) => `<button class="chip tapchip ${key === k ? 'on' : ''}" data-board="${k}">${l}</button>`).join('')}</div>
      <div class="tiny muted" style="margin-top:4px">${majorOnly() ? 'The 38 major leagues (top divisions of Europe, the Americas and Asia plus England / Scotland / Germany / Italy / Spain / France lower tiers)' : 'Every competition'} ranked by the probability of <b>${esc(title)}</b>. Price = Sportybet where the match is priced; + adds the selection to your slip.</div></div>`);
    const now = tzNow();
    const lst = (state.data.fixtures || []).filter((f) => inScope(f) && f.data_ok && f.bo && f.bo[key] && parseLocal(f.kickoff) > now).map((f) => ({ f, p: f.bo[key][0], odds: f.bo[key][1] })).sort((a, b) => b.p - a.p);
    if (!lst.length) { parts.push(`<div class="card empty">Nothing to show for ${esc(title)}${key === 'CO95' ? ' — corners need match statistics for both teams' : ''}.</div>`); return; }
    const max = state.expanded['top_' + key] ? lst.length : 20;
    parts.push(`<div class="card compact"><table class="tbl head"><tr><th></th><th>Match</th><th class="right">Price</th><th class="right">Prob.</th></tr>${lst.slice(0, max).map(({ f, p, odds }) => `<tr class="tap" data-fx="${esc(f.id)}"><td class="tiny muted nowrap">${esc(koShort(f.kickoff))}</td><td><div class="row" style="gap:6px">${fxBadge(f, 'home').replace('s24', 's20')}${fxBadge(f, 'away').replace('s24', 's20')}<div class="b grow">${teamSpan(f.home, f.country, f.div)} <span class="muted">v</span> ${teamSpan(f.away, f.country, f.div)}</div></div><div class="tiny muted">${flag(f.country)} ${esc(f.competition)} · ${esc(selLabel(key, f.home, f.away))}</div></td><td class="right nowrap">${odds ? `<b>${f2(odds)}</b>` : '<span class="muted">–</span>'}</td><td class="right"><div class="row" style="gap:0;justify-content:flex-end">${pill(p, 0.7, 0.6)}${PR.addBtn ? PR.addBtn(f.id, key, odds) : ''}</div></td></tr>`).join('')}</table>${lst.length > max ? `<button class="btn wide" data-more="top_${key}">Show all ${lst.length}</button>` : ''}</div>`);
  }
  /** fixtures already used by today's official day card — a match may appear only once on a screen */
  function botdIds() {
    const today = (state.data.safe || {}).today || {}; const out = new Set();
    (today.bets || []).forEach((b) => { if (b && b.fixture) out.add(b.fixture); });
    (today.groups || []).forEach((gx) => (gx.bets || []).forEach((b) => { if (b && b.fixture) out.add(b.fixture); }));
    return out;
  }
  /** the two pick groups: strong markets (any odds) and value (mispriced by Sportybet) — one market per
   *  match per screen: matches already on the day card are skipped, value skips the strong list's matches */
  function groupsCards(parts, exclude) {
    const excl = exclude || new Set();
    const g = (state.data.groups) || {};
    const notUnder = (x) => x.f && !excl.has(x.f.id) && !PR.isDropped(x.p.sel);
    const strong = bestPerMatch((g.strong || []).map((p) => ({ p, f: fx(p.id) })).filter(notUnder), (x) => x.f.id, (x) => x.p.p);
    const sIds = new Set(strong.map((x) => x.f.id));
    const value = bestPerMatch((g.value || []).map((p) => ({ p, f: fx(p.id) })).filter((x) => notUnder(x) && !sIds.has(x.f.id)), (x) => x.f.id, (x) => (x.p.ev || 0) * 100 + x.p.p);
    parts.push(`<div class="section-head">${sh('shield', 'Today’s strong markets', 'green')}<span class="tiny muted">${strong.length}</span></div>`);
    if (!strong.length) parts.push(`<div class="card empty small">No strong market in this window yet — the list fills in as the probabilities firm up.</div>`);
    else {
      const max = state.expanded.grp_strong ? strong.length : 15;
      parts.push(`<div class="card compact"><div class="tiny muted" style="margin-bottom:6px">Today's matches only — <b>one market per match</b> (the model's strongest), each at 70%+ published probability and a price of <b>1.16 or more</b>, highest probability first.</div>
        <table class="tbl head"><tr><th></th><th>Match · selection</th><th class="right">Price</th><th class="right">Model</th></tr>${strong.slice(0, max).map(({ p, f }) => selRow(f, p)).join('')}</table>
        ${strong.length > max ? `<button class="btn wide" data-more="grp_strong">Show all ${strong.length}</button>` : ''}</div>`);
    }
    parts.push(`<div class="section-head">${sh('trend', 'Value', 'amber')}<span class="tiny muted">${value.length}</span></div>`);
    if (!value.length) parts.push(`<div class="card empty small">No value selection right now — nothing is mispriced enough by the market with solid stats behind it.</div>`);
    else {
      const max = state.expanded.grp_value ? value.length : 15;
      parts.push(`<div class="card compact"><div class="tiny muted" style="margin-bottom:6px">Markets <b>Sportybet</b> misprices — <b>one per match</b> (the biggest edge): the model probability beats the price by at least <b>8%</b> expected value at 60%+ probability, with strong data behind it.</div>
        <table class="tbl head"><tr><th></th><th>Match · selection</th><th class="right">Price</th><th class="right">Model</th></tr>${value.slice(0, max).map(({ p, f }) => selRow(f, p)).join('')}</table>
        ${value.length > max ? `<button class="btn wide" data-more="grp_value">Show all ${value.length}</button>` : ''}</div>`);
    }
  }
  function renderToday(parts) {
    groupsCards(parts, botdIds());
    parts.push(botdCard(false));
    if (PR.ticketsCard) parts.push(PR.ticketsCard(false));
    const rec = ((state.data.safe || {}).summary || {}).botd || {};
    parts.push(`<div class="card small"><b>How the card is picked</b><div class="muted" style="margin-top:4px">Four blocks: <b>Goals</b> (Over 1.5), <b>Over 2.5</b>, <b>1X2</b> and <b>Corners</b> — filled in that order so <b>1X2 claims its matches first (up to five picks a day)</b>, then Over 2.5, then the rest. Team goals, bookings, BTTS and double chance left the card with their families (2026-10-27). Each block shows at most 7 of the strongest qualifying bets — if only one or two meet the bar, only those are listed, and a block with none disappears. Goals needs ≥70%; Over 2.5 needs ≥55% <i>and</i> recent form backing the pick; 1X2 needs ≥70% <i>and</i> recent form; Corners need ≥65%. Overs only, one market per match across the whole card, and nothing priced under <b>1.16</b> is offered at all (2026-10-27). Picks are made by the first analysis that sees them and kept for the day; every one is graded automatically.</div>
      ${rec.all && rec.all.n ? `<table class="tbl head" style="margin-top:8px"><tr><th>Bets of the day</th><th class="right">Won</th><th class="right">Hit</th><th class="right">Exp.</th><th class="right">Return</th></tr>${[['All time', rec.all], ['Last 30 days', rec['30d']]].filter(([, s]) => s && s.n).map(([n, s]) => `<tr><td>${n}</td><td class="right">${s.won}/${s.n}</td><td class="right"><b>${pct(s.rate)}</b></td><td class="right muted">${pct(s.exp_rate)}</td><td class="right ${s.roi > 0 ? 'good' : s.roi < 0 ? 'bad' : ''}">${signed(s.roi)}</td></tr>`).join('')}</table>` : '<div class="tiny muted" style="margin-top:6px">The record starts with the first settled card.</div>'}</div>`);
  }
  function renderSafest(parts) {
    const sf = state.data.safe || {}; const all = safeList(state.betGroup || 'all');
    const winAll = !!state.safestAll;
    const lst = bestPerMatch(winAll ? all : all.filter(sameDay), (b) => b.fixture, (b) => b.p);
    const nToday = all.filter(sameDay).length;
    const groupOptions = [['all', 'All markets'], ['goals', 'Goals (Over 1.5 / 2.5)'], ['corners', 'Corners']];
    parts.push(`<div class="card compact">${leagueChips()}<div class="chips small-chips" style="margin-top:6px">
      <button class="chip tapchip ${!winAll ? 'on' : ''}" data-scope="today">📅 Today (${nToday})</button>
      <button class="chip tapchip ${winAll ? 'on' : ''}" data-scope="all">🗓 Next 60 days (${all.length})</button></div>
      <div class="filters" style="margin-top:6px"><label>Market ${select('f-group', groupOptions, state.betGroup || 'all')}</label></div>
      <div class="tiny muted">One selection per match (the strongest). High-probability selection = <b>model probability</b> of at least ${pct(sf.min_p || 0.7)} (football data only), in the goals, corners and 1X2 markets — the price anchors the published probability and nothing under <b>1.16</b> is offered. <b>Today</b> shows matches kicking off this day; the 60-day view lists every upcoming analysed match. A high probability is not a certainty: expect roughly ${pct(sf.min_p || 0.7)}–85% of these to land. Each one shows its data quality and is graded in Days.</div></div>`);
    if (!lst.length) parts.push(`<div class="card empty">${winAll ? 'No high-probability selection in this window' : 'No high-probability selection for today’s matches'}${majorOnly() ? ' for the major leagues' : ''}.</div>`);
    else {
      const max = state.expanded.safest ? lst.length : 30;
      parts.push(`<div class="card compact"><table class="tbl head"><tr><th></th><th>Match · selection</th><th class="right">Price</th><th class="right">Model</th></tr>${lst.slice(0, max).map((b) => safeRow(b)).join('')}</table>
        ${lst.length > max ? `<button class="btn wide" data-more="safest">Show all ${lst.length}</button>` : ''}</div>`);
    }
    const ss = (sf.summary || {}).bets || {};
    if (ss.all && ss.all.n) parts.push(`<div class="card small"><b>Track record</b> — high-probability selections settled: ${ss.all.won}/${ss.all.n} hit (${pct(ss.all.rate)}, expected ${pct(ss.all.exp_rate)}) · flat-stake return ${signed(ss.all.roi)}${ss['30d'] && ss['30d'].n ? ` · last 30 days ${ss['30d'].won}/${ss['30d'].n}` : ''} · ${ss.pending || 0} pending. Full breakdown under ☰ › Performance.</div>`);
  }
  function renderFamily(parts, fam) {
    const minP = settings.hiP || 0.7; const groups = FAMILY[fam] || [fam];
    const famFloor = (sel) => (minP <= 0.7 && PR.SEL_FLOOR[sel] != null ? PR.SEL_FLOOR[sel] : minP);   // Over 2.5 starts from 55% (user rule 2026-10-17)
    const safe = bestPerMatch(safeList(fam), (b) => b.fixture, (b) => b.p);
    const title = { goals: 'Goals markets', corners: 'Corners' }[fam] || fam;
    parts.push(`<div class="card compact">${leagueChips()}<div class="filters" style="margin-top:6px"><label>Probability ≥ ${select('f-hip', [[0.7, '70%'], [0.75, '75%'], [0.8, '80%'], [0.85, '85%'], [0.9, '90%']], minP)}</label></div>
      <div class="tiny muted">${fam === 'goals' ? 'Over 1.5, Over 2.5 and the other goals lines (Over 2.5 starts from 55%).' : 'Total corners — modelled for the leagues with corner statistics (the 22 main European leagues) and priced by Sportybet.'} High-probability selections first, then every other selection at or above the threshold.</div></div>`);
    if (safe.length) parts.push(`<div class="card compact"><div class="row"><div class="grow b">${icon('trend', 'sm')} High-probability ${title.toLowerCase()}</div><span class="chip good">${safe.length}</span></div><table class="tbl">${safe.map((b) => safeRow(b)).join('')}</table></div>`);
    // other high-probability selections need the per-match details; use the index's top/safe and the priced flag
    const lst = [];
    (state.data.fixtures || []).forEach((f) => { if (!inScope(f) || !f.data_ok) return; (f.hi || []).forEach((x) => { const s = { sel: x[0], p: x[1], odds: x[2] }; if (s.p >= famFloor(s.sel) && !PR.isDropped(s.sel) && groups.includes(selGroup(s.sel)) && !safe.some((b) => b.fixture === f.id)) lst.push({ f, s }); }); });
    const bestFam = bestPerMatch(lst, (x) => x.f.id, (x) => x.s.p).sort((a, b) => b.s.p - a.s.p);
    lst.length = 0; bestFam.forEach((x) => lst.push(x));
    if (lst.length) {
      const key = 'fam_' + fam; const max = state.expanded[key] ? lst.length : 25;
      parts.push(`<div class="card compact"><div class="row"><div class="grow b">${icon('trend', 'sm')} Other selections ≥ ${pct(minP)}${minP <= 0.7 ? ' · Over 2.5 from 55%' : ''}</div><span class="chip">${lst.length}</span></div><table class="tbl">${lst.slice(0, max).map((x) => selRow(x.f, x.s)).join('')}</table>${lst.length > max ? `<button class="btn wide" data-more="${key}">Show all ${lst.length}</button>` : ''}</div>`);
    } else if (!safe.length) parts.push(`<div class="card empty">Nothing at or above ${pct(minP)} in ${title.toLowerCase()} right now.</div>`);
  }
  function renderPicks(parts) {
    const d = state.data, m = d.meta;
    parts.push(`<div class="card small">${leagueChips()}<div style="margin-top:6px"><b>Goals shortlists</b> — the matches most likely to produce goals, ranked by probability (⭐ = threshold, ⭐⭐⭐ = very strong). Each match appears once, in the goals market the model rates strongest. These are match ratings, not priced bets: use them to pick games to watch or to build your own selections.</div></div>`);
    // ONE MARKET PER MATCH: each match appears only in the goals market the model rates strongest
    const claimed = new Map();
    for (const mk of ['O15', 'O25', 'BTTS']) for (const p of (d.picks[mk] || [])) {
      const cur = claimed.get(p.fixture);
      if (!cur || p.p > cur.p.p) claimed.set(p.fixture, { mk, p });
    }
    for (const mk of ['O15', 'O25', 'BTTS']) {
      const lst = [...claimed.entries()].filter(([, v]) => v.mk === mk).map(([, v]) => v.p).filter((p) => inScope(fx(p.fixture)));
      parts.push(`<div class="card compact"><div class="row"><div class="grow"><b>${MK[mk]}</b> <span class="muted small">· threshold ${pct(m.thresholds[mk])}</span></div><span class="chip">${lst.length}</span></div>`);
      if (!lst.length) parts.push(`<div class="muted small">None met the criteria.</div>`);
      else parts.push(`<table class="tbl">${lst.map((p) => { const f = fx(p.fixture); if (!f) return ''; return `<tr class="tap" data-fx="${esc(f.id)}"><td class="tiny muted nowrap">${esc(koShort(f.kickoff))}</td><td><div class="row" style="gap:6px">${fxBadge(f, 'home').replace('s24', 's20')}${fxBadge(f, 'away').replace('s24', 's20')}<div class="b grow">${teamSpan(f.home, f.country, f.div)} v ${teamSpan(f.away, f.country, f.div)}</div></div><div class="tiny muted">${flag(f.country)} ${esc(f.competition)}</div></td><td class="right">${p.sportybet ? `<b>${f2(p.sportybet)}</b>` : '<span class="muted">–</span>'}</td><td class="right">${pill(p.p, 0.7, 0.6)}<div class="stars">${esc(p.stars)}</div></td></tr>`; }).join('')}</table>`);
      parts.push(`<div class="tiny muted" style="margin-top:6px">Backtest: ${esc(m.backtest[mk] || '')}</div></div>`);
    }
    const t = d.tracker || {};
    parts.push(`<div class="card"><b>Shortlist tracker</b><table class="tbl head" style="margin-top:6px"><tr><th>Market</th><th class="right">Settled</th><th class="right">Hit</th><th class="right">30d</th><th class="right">Pending</th></tr>${['O15', 'O25', 'BTTS'].map((mk) => { const s = t[mk] || {}; return `<tr><td>${MK[mk]}</td><td class="right">${s.settled || 0}</td><td class="right">${pct(s.rate)}</td><td class="right">${pct(s.recent_rate)}</td><td class="right">${s.pending || 0}</td></tr>`; }).join('')}</table></div>`);
  }

  // ------------------------------------------------------------------ LIVE
  PR.views.live = function () {
    const d = state.data; const tracked = live.tracked(); const parts = []; const v = state.liveView || 'tracked';
    const nLive = tracked.filter((f) => isLive(live.for(f))).length; const all = state.liveAll || [];
    parts.push(`<div class="card row compact"><div class="grow small"><span class="status-dot ${nLive || all.length ? 'live' : ''}"></span>${v === 'all' ? `${all.length} match${all.length === 1 ? '' : 'es'} in play worldwide` : `${tracked.length} tracked · ${nLive} in play`}${state.lastLive ? ' · updated ' + new Date(state.lastLive).toTimeString().slice(0, 5) : ''}</div><button class="btn" id="live-refresh">Refresh</button></div>`);
    parts.push(`<div class="card compact">${segmented([['tracked', `${icon('target')} Tracked (${tracked.length})`], ['all', `${icon('live')} All in play (${all.length})`]], v, 'lv')}</div>`);
    if (v === 'all') {
      if (state.liveAll == null) parts.push(PR.skeleton(6));
      else if (!all.length) parts.push(`<div class="card empty">No match is in play right now.</div>`);
      else {
        const groups = {}; all.forEach((e) => { const k = `${e.country} · ${e.league}`; (groups[k] = groups[k] || []).push(e); });
        const keys = Object.keys(groups).sort((a, b) => (groups[b].some((e) => e.fixture) ? 1 : 0) - (groups[a].some((e) => e.fixture) ? 1 : 0) || a.localeCompare(b));
        parts.push('<div class="card compact">');
        keys.forEach((k) => {
          const g = groups[k]; parts.push(`<div class="comp-head">${flag(g[0].country)} ${esc(k)}</div>`);
          g.forEach((e) => {
            const fid = e.fixture || `${ymd(tzNow())}|${e.country || ''}|${e.home}|${e.away}`;
            const m = { id: fid, home: e.home, away: e.away, badges: { home: e.img[0], away: e.img[1] }, country: e.country, competition: e.league, kickoff: '' };
            state.liveTeams = state.liveTeams || {};
            state.liveTeams[fid] = [e.home, e.away, e.country || ''];   // country pins the name fallback (wrong-match guard)
            const f = e.fixture ? fx(e.fixture) : null; const sub = f ? `<span class="chip brand">analysed</span>${f.safe ? ` <b>${esc(selLabel(f.safe[0], f.home, f.away))}</b> · ${esc(liveVerdict(f.safe[0], state.live[e.eid]).text)}` : ''}` : '';
            parts.push(matchRow(m, { live: state.live[e.eid], tap: true, short: true, sub, right: '' })); });
        });
        parts.push('</div>');
      }
    } else {
      if (!tracked.length) parts.push(`<div class="card empty">Nothing to follow in this window.</div>`);
      const betsByFx = {}; const sf = d.safe || { bets: [] };
      ((sf.today && sf.today.bets) || []).forEach((b) => { (betsByFx[b.fixture] = betsByFx[b.fixture] || []).push({ label: b.label, sel: b.sel, odds: b.odds, kind: 'botd' }); });
      (sf.bets || []).forEach((b) => { (betsByFx[b.fixture] = betsByFx[b.fixture] || []).push({ label: b.label, sel: b.sel, odds: b.odds, kind: 'safe' }); });
      Object.entries(d.picks || {}).forEach(([mk, lst]) => lst.forEach((p) => { (betsByFx[p.fixture] = betsByFx[p.fixture] || []).push({ label: MK[mk], sel: mk, kind: 'pick' }); }));
      const rank = (f) => { const s = live.for(f); return isLive(s) ? 0 : isFT(s) ? 2 : 1; };
      const ordered = tracked.slice().sort((x, y) => rank(x) - rank(y) || x.kickoff.localeCompare(y.kickoff));
      ordered.forEach((f) => {
        const g = rank(f);
        const s = live.for(f); const inc = f.livescore_id && state.incidents[f.livescore_id];
        const seen = new Set();
        const chips = (betsByFx[f.id] || []).filter((b) => { const k = b.sel; if (seen.has(k)) return false; seen.add(k); return true; })
          .map((b) => { const vd = liveVerdict(b.sel, s); return `<span class="chip ${vd.cls}">${b.kind === 'botd' ? '⭐ ' : b.kind === 'safe' ? '📈 ' : ''}${esc(b.label)}${b.odds ? ' @ ' + f2(b.odds) : ''} · ${esc(vd.text)}</span>`; }).join('');
        const goals = inc && g !== 1 ? inc.items.filter((it) => ['goal', 'own goal', 'penalty'].includes(it.type)) : [];
        const bub = g === 0 ? `<span class="lc-badge">${esc((s && s.status) || 'LIVE')}</span>`
          : g === 2 ? `<span class="lc-badge ft">FT</span>`
          : `<span class="lc-badge up">${esc(koTime(f.kickoff))}</span>`;
        const vd0 = f.safe ? liveVerdict(f.safe[0], s) : null;
        const meta = g === 0 ? (vd0 ? esc(vd0.text) : 'in play')
          : g === 2 ? 'finished'
          : `${esc(koShort(f.kickoff))}`;
        parts.push(`<div class="live-card tap" data-fx="${esc(f.id)}">
          <div class="lc-top">${bub}<span class="lc-comp">${flag(f.country)} ${esc(f.competition)}</span></div>
          <div class="lc-grid">
            <div>
              <div class="lc-team">${badge(f.home, f.badges && f.badges.home, 22)}<span class="nm" data-team="${esc(f.home)}" data-country="${esc(f.country)}" data-div="${esc(f.div)}">${esc(f.home)}</span><span class="score">${s && s.hg != null ? s.hg : '\u2013'}</span></div>
              <div class="lc-team">${badge(f.away, f.badges && f.badges.away, 22)}<span class="nm" data-team="${esc(f.away)}" data-country="${esc(f.country)}" data-div="${esc(f.div)}">${esc(f.away)}</span><span class="score">${s && s.ag != null ? s.ag : '\u2013'}</span></div>
            </div>
            <div class="lc-meta"><span class="chip brand">O2.5 ${pct(f.p.O25)}</span><span class="lc-verdict">${meta}</span></div>
          </div>
          ${(chips || goals.length) ? `<div class="lc-extra">${chips ? `<div class="chips">${chips}</div>` : ''}${goals.length ? `<div class="tiny muted" style="margin-top:4px">${goals.map((it) => `⚽ ${esc(it.player || '')} ${it.min != null ? it.min + "'" : ''}${it.team === 'A' ? ' (away)' : ''}`).join(' · ')}</div>` : ''}</div>` : ''}
        </div>`);
      });
    }
    parts.push(`<div class="tiny muted" style="padding:0 6px">Scores from a public live feed (unofficial). Auto-refresh every ${settings.liveEvery}s while this tab is open. The settled results in Days are the final word.</div>`);
    view().innerHTML = parts.join('');
    const b = $('#live-refresh'); if (b) b.onclick = (e) => { e.stopPropagation(); toast('Refreshing…'); live.refresh(true); };
    $$('[data-lv]').forEach((x) => { x.onclick = () => { state.liveView = x.dataset.lv; PR.render(); if (x.dataset.lv === 'all' && Date.now() - state.lastLiveAll > 20000) live.refresh(false); }; });
  };
  function incidentLine(it) {
    const ico = { goal: '⚽', 'own goal': '⚽ (og)', penalty: '⚽ (pen)', 'missed penalty': '❌ pen', yellow: '🟨', 'second yellow': '🟨🟥', red: '🟥' }[it.type] || '';
    return `${ico} ${it.min != null ? it.min + "'" : ''} ${esc(it.player || '')}${it.score ? ` <span class="muted">(${it.score[0]}–${it.score[1]})</span>` : ''}`;
  }
  PR.incidentLine = incidentLine;

  // ------------------------------------------------------------------ MATCHES
  const PINNED = ['England', 'Spain', 'Italy', 'Germany', 'France', 'Netherlands', 'Portugal', 'Belgium', 'Turkiye', 'Scotland', 'South Africa', 'UEFA Champions League', 'UEFA Europa League'];
  function matchSub(f, withComp) {
    const b = f.safe || f.top || null;
    return `${withComp ? flag(f.country) + ' ' + esc(f.competition) + ' · ' : ''}xG ${f1(f.xg[0])}–${f1(f.xg[1])}${b ? ` · ${f.safe ? '📈 ' : ''}<b>${esc(selShort(b[0]))}</b> ${pct(b[1])} @ ${f2(b[2])}` : f.priced ? '' : ' · <span class="muted">no price</span>'}${f.data_ok ? '' : ' · <span class="warn">low data</span>'}${f.time_known === false ? ' · <span class="muted">time tbc</span>' : ''}`;
  }
  function matchRight(f, s) { return s && s.hg != null ? '' : `<span class="tiny muted">O2.5 ${pill(f.p.O25, 0.6, 0.5)}</span><span class="tiny muted">BTTS ${pill(f.p.BTTS, 0.6, 0.5)}</span>`; }
  /** Global search: while typing, also surface matching LEAGUES and CLUBS (not just the window's fixtures). */
  function globalSearchParts(parts, q, d) {
    const ql = q.toLowerCase();
    const lix = (state.lg && state.lg.idx && state.lg.idx.leagues) || [];
    const leagues = lix.filter((x) => (x.league || '').toLowerCase().includes(ql) || (x.country || '').toLowerCase().includes(ql)).slice(0, 5);
    const clubs = new Map();
    (d.fixtures || []).forEach((f) => {
      [f.home, f.away].forEach((name) => { if (name && !clubs.has(name.toLowerCase())) clubs.set(name.toLowerCase(), { name, country: f.country || '', div: f.div || '' }); });
    });
    Object.values(state.teams || {}).forEach((tp) => {
      if (!tp) return;
      Object.keys(tp.teams || {}).forEach((name) => { if (!clubs.has(name.toLowerCase())) clubs.set(name.toLowerCase(), { name, country: tp.country || '', div: tp.div || '' }); });
    });
    let clubHits = [...clubs.values()].filter((c) => c.name.toLowerCase().includes(ql));
    if (!state.teamIdx) PR.loadTeamIndex().then((j) => { if (j) PR.render(); });
    if (state.teamIdx) {
      const have = new Set(clubs.keys());
      (state.teamIdx.teams || []).forEach((t) => {
        const k = (t.n || '').toLowerCase();
        if (k.includes(ql) && !have.has(k)) { have.add(k); clubHits.push({ name: t.n, country: t.c || '', div: t.d || '' }); }
      });
    }
    clubHits = clubHits.slice(0, 6);
    if (!leagues.length && !clubHits.length) return;
    const E = encodeURIComponent;
    parts.push(`<div class="card compact"><div class="comp-head">Top matches — leagues &amp; clubs</div>`);
    leagues.forEach((x) => parts.push(`<div class="list-item tap" data-gs="league|${E(x.slug)}" style="padding:8px 10px"><div class="row" style="gap:8px">${icon('trophy', 'sm')}<div class="grow"><div class="b" style="font-size:13px">${esc(x.league)}</div><div class="tiny muted">${flag(x.country)} ${esc(x.country || '')}${x.season ? ' · ' + esc(x.season) : ''}</div></div>${x.next ? `<span class="tiny muted">next ${esc(koShort(x.next))}</span>` : ''}</div></div>`));
    clubHits.forEach((c) => parts.push(`<div class="list-item tap" data-gs="team|${E(c.name)}|${E(c.country)}|${E(c.div)}" style="padding:8px 10px"><div class="row" style="gap:8px">${badge(c.name, null, 24)}<div class="grow b" style="font-size:13px">${esc(c.name)}</div><span class="tiny muted">${flag(c.country)} ${esc(c.country || '')}</span></div></div>`));
    parts.push('</div>');
  }
  PR.views.matches = function () {
    const d = state.data; const q = (state.search || '').trim().toLowerCase(); const key = state.sort || 'ko'; const filt = state.matchFilter || 'all'; const mode = state.matchesView || 'time';
    let lst = d.fixtures.filter((f) => !q || `${f.home} ${f.away} ${f.competition} ${f.country}`.toLowerCase().includes(q));
    if (filt === 'today' || filt === 'analysed') lst = matchdayFixtures(lst, filt === 'analysed');
    else if (filt === 'priced') lst = lst.filter((f) => f.priced);
    else if (filt === 'safe') lst = lst.filter((f) => f.safe);
    else if (filt === 'major') lst = lst.filter((f) => f.major);
    else if (filt === 'ok') lst = lst.filter((f) => f.data_ok);
    else if (filt === 'live') lst = lst.filter((f) => isLive(live.for(f)));
    else if (filt === 'fav') lst = lst.filter((f) => PR.isFav(f.id));
    const best = (f) => (f.top ? f.top[1] : 0);
    const parts = [`<div class="card compact"><div class="searchbar"><div class="field">${icon('search')}<input id="fx-search" placeholder="Search team, league or country" value="${esc(state.search || '')}">${q ? `<button class="link" id="fx-clear">${icon('x')}</button>` : ''}</div></div>
      <div style="margin-top:8px">${segmented([['time', `${icon('clock')} By time`], ['comp', `${icon('trend')} By country & competition`]], mode, 'mmode')}</div>
      <div class="chips small-chips" style="margin-top:6px">${[['all', `All ${d.fixtures.length}`], ['today', 'Today'], ['analysed', 'Analysed today'], ['live', '🔴 Live'], ['fav', '★ Favourites'], ['major', '🏆 Major'], ['priced', 'Priced'], ['safe', '📈 High probability'], ['ok', 'Enough data']].map(([k, l]) => `<button class="chip tapchip ${filt === k ? 'on' : ''}" data-mf="${k}">${l}</button>`).join('')}
      ${mode === 'time' ? select('fx-sort', [['ko', 'Kick-off'], ['safe', 'Best bet first'], ['O25', 'Over 2.5'], ['O15', 'Over 1.5'], ['BTTS', 'BTTS'], ['H', 'Home win']], key) : ''}</div></div>`];
    if (q) globalSearchParts(parts, q, d);
    if (!q && (filt === 'all' || filt === 'live')) {
      // matches that finished earlier today (or yesterday evening) leave the current analysis — point to the day archive
      const today = ymd(tzNow()); const dayRec = state.days[today]; const have = new Set(d.fixtures.map((f) => f.id));
      const gone = dayRec && dayRec.fixtures ? dayRec.fixtures.filter((f) => !have.has(f.id) && f.score && f.score.hg != null).length : null;
      if (gone == null && !state.days[today + '_loading']) { state.days[today + '_loading'] = true; PR.loadDay(today).then(() => PR.render()).catch(() => {}); }
      if (gone) parts.push(`<div class="card compact list-item tap" data-day-results="${today}"><div class="row"><span>🏁</span><div class="grow small"><b>${gone} match${gone === 1 ? '' : 'es'} finished earlier today</b><div class="tiny muted">Final scores, statistics, goals and how the bets settled</div></div>${icon('next')}</div></div>`);
    }
    if (!lst.length) parts.push(`<div class="card empty">${filt === 'fav' ? 'No favourite matches yet — open a match and tap ☆ in its header.' : filt === 'analysed' && !q ? 'No analysed matches for today yet.' : filt === 'today' && !q ? 'No fixtures for today yet.' : `No matches found${q ? ` for “${esc(q)}”` : ''}.`}</div>`);
    else if (mode === 'time') {
      lst = lst.slice().sort((a, b) => key === 'ko' ? a.kickoff.localeCompare(b.kickoff) || a.competition.localeCompare(b.competition) : key === 'safe' ? best(b) - best(a) : key === 'H' ? (b.x12[0] || 0) - (a.x12[0] || 0) : (b.p[key] || 0) - (a.p[key] || 0));
      const max = state.expanded.matches ? lst.length : 250; let lastDay = null, lastHour = null;
      lst.slice(0, max).forEach((f) => {
        const day = f.kickoff.slice(0, 10), hour = f.kickoff.slice(11, 13) + ':00';
        if (key === 'ko' && day !== lastDay) { if (lastDay) parts.push('</div>'); parts.push(`<h2 class="section">${esc(dayName(day))}</h2><div class="card compact">`); lastDay = day; lastHour = null; }
        else if (key !== 'ko' && !lastDay) { parts.push('<div class="card compact">'); lastDay = 'x'; }
        if (key === 'ko' && hour !== lastHour) { parts.push(`<div class="hour-head">${esc(hour)}</div>`); lastHour = hour; }
        const s = live.for(f);
        parts.push(matchRow(f, { live: s, short: true, sub: matchSub(f, true), right: matchRight(f, s) }));
      });
      if (lastDay) parts.push('</div>');
      if (lst.length > max) parts.push(`<button class="btn wide" data-more="matches">Show all ${lst.length}</button>`);
    } else {
      // country -> competition accordions
      const byC = {}; lst.forEach((f) => { (byC[f.country] = byC[f.country] || {}); (byC[f.country][f.competition] = byC[f.country][f.competition] || []).push(f); });
      const countries = Object.keys(byC).sort((a, b) => { const pa = PINNED.indexOf(a), pb = PINNED.indexOf(b); return (pa < 0 ? 99 : pa) - (pb < 0 ? 99 : pb) || a.localeCompare(b); });
      const open = state.openCountries || (state.openCountries = new Set(q ? countries : countries.slice(0, 3)));
      if (q) countries.forEach((c) => open.add(c));
      parts.push(`<div class="row" style="padding:0 6px 4px"><div class="grow tiny muted">${countries.length} countries · ${Object.values(byC).reduce((a, c) => a + Object.keys(c).length, 0)} competitions</div><button class="link" id="acc-all">${open.size >= countries.length ? 'Collapse all' : 'Expand all'}</button></div>`);
      parts.push('<div class="card compact">');
      countries.forEach((c) => {
        const comps = byC[c]; const n = Object.values(comps).reduce((a, l) => a + l.length, 0); const nl = Object.values(comps).reduce((a, l) => a + l.filter((f) => isLive(live.for(f))).length, 0); const isOpen = open.has(c);
        parts.push(`<div class="acc-head ${isOpen ? 'open' : ''}" data-acc="${esc(c)}"><span>${flag(c)}</span><span>${esc(c)}</span>${nl ? `<span class="status-dot live"></span>` : ''}<span class="cnt">${Object.keys(comps).length} · ${n} match${n === 1 ? '' : 'es'}</span><span class="chev">${icon('next')}</span></div>`);
        if (!isOpen) return;
        Object.keys(comps).sort().forEach((comp) => {
          parts.push(`<div class="comp-head">${esc(comp.replace(c + ' · ', ''))}</div>`);
          comps[comp].sort((a, b) => a.kickoff.localeCompare(b.kickoff)).forEach((f) => { const s = live.for(f); parts.push(matchRow(f, { live: s, short: false, sub: matchSub(f, false), right: matchRight(f, s) })); });
        });
      });
      parts.push('</div>');
    }
    view().innerHTML = parts.join('');
    const inp = $('#fx-search');
    inp.oninput = (e) => { state.search = e.target.value; PR.render(); const i = $('#fx-search'); i.focus(); i.setSelectionRange(i.value.length, i.value.length); };
    $$('[data-day-results]').forEach((b) => { b.onclick = () => { state.dayView = 'results'; PR.push({ type: 'day', date: b.dataset.dayResults }); }; });
    if (state.focusSearch) { state.focusSearch = false; inp.focus(); }
    const cl = $('#fx-clear'); if (cl) cl.onclick = () => { state.search = ''; PR.render(); };
    const so = $('#fx-sort'); if (so) so.onchange = (e) => { state.sort = e.target.value; PR.render(); };
    $$('[data-mf]').forEach((b) => { b.onclick = () => { state.matchFilter = b.dataset.mf; PR.render(); }; });
    $$('[data-mmode]').forEach((b) => { b.onclick = () => { state.matchesView = b.dataset.mmode; PR.render(); }; });
    $$('[data-gs]').forEach((el) => { el.onclick = () => { const g = el.dataset.gs.split('|'); const D = (s) => decodeURIComponent(s); if (g[0] === 'league' && PR.openLeague) PR.openLeague(D(g[1])); else if (g[0] === 'team') PR.openTeam(D(g[1]), D(g[2]), D(g[3])); }; });
    $$('[data-more]').forEach((b) => { b.onclick = () => { state.expanded[b.dataset.more] = true; PR.render(); }; });
    $$('[data-acc]').forEach((b) => { b.onclick = () => { const o = state.openCountries; if (o.has(b.dataset.acc)) o.delete(b.dataset.acc); else o.add(b.dataset.acc); PR.render(); }; });
    const all = $('#acc-all'); if (all) all.onclick = () => { const cs = Object.keys(d.fixtures.reduce((a, f) => { a[f.country] = 1; return a; }, {})); if (state.openCountries.size >= cs.length) state.openCountries = new Set(); else state.openCountries = new Set(cs); PR.render(); };
  };

  // ------------------------------------------------------------------ LOW ODDS (all markets priced 1.19 – 1.45)
  // Every market the bookmaker prices between 1.19 and 1.45 for one day, in one list. The analysis index is
  // the only feed that carries prices, and it is published as a rolling window (today → this time tomorrow),
  // so the day chips are exactly the days inside that window. A row is a normal match row: tap it and the
  // match page opens with that fixture (the selection is the line the price belongs to).
  const LO_ODDS = 1.19, HI_ODDS = 1.45;
  const loInBand = (s) => !!s && s.odds != null && s.odds >= LO_ODDS && s.odds <= HI_ODDS && s.p != null && s.p > 0 && s.p < 1;
  const LO_SORTS = [['odds', 'Odds · low → high'], ['oddsdesc', 'Odds · high → low'], ['p', 'Model probability'], ['ko', 'Kick-off'], ['league', 'League']];
  function loDays(d) {
    const map = new Map();
    (d.fixtures || []).forEach((f) => {
      const sels = (f.sels || []).filter((x) => loInBand(x) && !isUnder(x && x.sel));
      if (!sels.length) return;
      const day = String(f.date || (f.kickoff || '').slice(0, 10));
      if (!map.has(day)) map.set(day, { day, rows: [], matches: 0, from: null, to: null });
      const e = map.get(day);
      e.rows.push(...sels.map((s) => ({ f, s })));
      e.matches++;
      const ko = (f.kickoff || '').slice(11, 16);
      if (ko) { if (!e.from || ko < e.from) e.from = ko; if (!e.to || ko > e.to) e.to = ko; }
    });
    return [...map.values()].sort((a, b) => a.day.localeCompare(b.day));
  }
  PR.views.lowodds = function () {
    const d = state.data || {};
    const days = loDays(d);
    const parts = [];
    const priced = (d.fixtures || []).filter((f) => (f.sels || []).length).length;
    if (!days.length) {
      parts.push(`<div class="hero-row"><div><div class="kicker">Low odds</div><h1>1.19 – 1.45</h1></div></div>`);
      parts.push(`<div class="card empty">No market is priced between ${f2(LO_ODDS)} and ${f2(HI_ODDS)} in the current publication${priced ? '' : ' — the prices have not arrived with this analysis yet'}.<br><span class="tiny muted">The list fills in with each analysis run; pull down on Home to refresh.</span></div>`);
      // a phone holding an outdated copy would show an empty page — fetch once (flag stops any loop)
      if (!priced && !PR._loRefreshed) { PR._loRefreshed = true; setTimeout(() => PR.loadData(false), 250); }
      view().innerHTML = parts.join('');
      return;
    }
    const today = ymd(tzNow());
    const pick = days.some((x) => x.day === state.loDay) ? state.loDay : (days.find((x) => x.day >= today) || days[days.length - 1]).day;
    state.loDay = pick;
    const cur = days.find((x) => x.day === pick);
    const sort = state.loSort || 'odds';
    const byKo = (a, b) => String(a.f.kickoff).localeCompare(String(b.f.kickoff));
    const cmp = {
      odds: (a, b) => a.s.odds - b.s.odds || byKo(a, b),
      oddsdesc: (a, b) => b.s.odds - a.s.odds || byKo(a, b),
      p: (a, b) => b.s.p - a.s.p || a.s.odds - b.s.odds,
      ko: (a, b) => byKo(a, b) || a.s.odds - b.s.odds,
      league: (a, b) => String(a.f.country || '').localeCompare(String(b.f.country || '')) ||
        String(a.f.league || a.f.competition || '').localeCompare(String(b.f.league || b.f.competition || '')) || byKo(a, b),
    }[sort] || ((a, b) => a.s.odds - b.s.odds || byKo(a, b));
    const rows = bestPerMatch(cur.rows.slice(), (r) => r.f.id, (r) => r.s.p).sort(cmp);
    parts.push(`<div class="hero-row"><div><div class="kicker">Low odds</div><h1>1.19 – 1.45</h1></div><span class="quality">${rows.length} market${rows.length === 1 ? '' : 's'}</span></div>`);
    parts.push(`<div class="card compact"><div class="row"><div class="grow small"><b>${rows.length} market${rows.length === 1 ? '' : 's'} in the window</b> · ${cur.matches} match${cur.matches === 1 ? '' : 'es'}${cur.from ? ` · kick-off ${esc(cur.from)}–${esc(cur.to)}` : ''}</div></div>
      ${days.length > 1 ? `<div class="chips small-chips" style="margin-top:6px">${days.map((x) => `<button class="chip tapchip ${x.day === pick ? 'on' : ''}" data-lo-day="${esc(x.day)}">${esc(dayName(x.day))} <b>${x.rows.length}</b></button>`).join('')}</div>` : ''}
      <div class="row" style="margin-top:8px"><div class="grow tiny muted">Sort</div>${select('lo-sort', LO_SORTS, sort)}</div></div>`);
    parts.push(`<div class="card compact" style="margin-top:8px"><table class="tbl head" style="margin-top:4px"><tr><th>Kick-off</th><th>Match · market</th><th class="right">Price</th><th class="right">Model</th></tr>
      ${rows.map(({ f, s }) => `<tr class="tap" data-fx="${esc(f.id)}">
        <td class="tiny muted nowrap">${esc(koTime(f.kickoff))}</td>
        <td><div class="b">${esc(s.label || selLabel(s.sel, f.home, f.away))}</div>
          <div class="tiny muted">${flag(f.country)} ${esc(f.league || f.competition || '')} · ${teamSpan(f.home, f.country, f.div)} v ${teamSpan(f.away, f.country, f.div)}</div></td>
        <td class="right nowrap"><b>${f2(s.odds)}</b>${s.p_sb != null ? `<div class="tiny muted">${pct(s.p_sb)} implied</div>` : ''}</td>
        <td class="right nowrap">${pill(s.p, 0.8, 0.7)} ${s.diff_pp != null ? `<div class="tiny ${s.diff_pp > 0 ? 'good' : 'muted'}">${s.diff_pp > 0 ? '+' : ''}${f1(s.diff_pp)} pp</div>` : ''} ${PR.addBtn ? PR.addBtn(f.id, s.sel, s.odds) : ''}</td></tr>`).join('')}</table></div>`);
    parts.push(`<div class="card tiny muted"><b>What this page is</b> — every selection the bookmaker prices from <b>${f2(LO_ODDS)} to ${f2(HI_ODDS)}</b>, all markets, one day: the short-priced end of the board where a single goal usually decides it. Price = Sportybet's decimal odds; Model = this app's probability; implied = what the price itself says. A price in this band is not a safe bet — it is the market saying "likely", and the model is often less sure than that. Tap any row for the full match page.</div>`);
    view().innerHTML = parts.join('');
    $$('[data-lo-day]').forEach((b) => { b.onclick = () => { state.loDay = b.dataset.loDay; PR.render(); }; });
    const so = $('#lo-sort'); if (so) so.onchange = (e) => { state.loSort = e.target.value; PR.render(); };
  };

  // ------------------------------------------------------------------ DAYS
  PR.views.days = function () {
    const d = state.data; const days = (d.history && d.history.days) || []; const parts = [];
    const asc = state.daysOld === true;
    const ordered = asc ? days.slice().reverse() : days;
    parts.push(`<div class="hero-row"><div><div class="kicker">Analysed fixtures</div><h1>Day by day</h1></div><span class="quality">kept permanently</span></div>`);
    parts.push(`<div class="card small"><b>Every analysed fixture, sorted by date</b> — each day lists its matches with the final score and how the bets of the day, high-probability selections and shortlists did. Results and statistics fill in within a few hours of the final whistle. <b>Nothing is ever deleted:</b> once the model captures a fixture it stays on record permanently.</div>`);
    parts.push(`<div class="chips small-chips" style="margin-bottom:8px"><button class="chip tapchip ${!asc ? 'on' : ''}" data-dsort="new">⬇ Newest first</button><button class="chip tapchip ${asc ? 'on' : ''}" data-dsort="old">⬆ Oldest first</button></div>`);
    if (!days.length) parts.push(`<div class="card empty">History starts with the next analysis.</div>`);
    const rate = (o, hitKey) => { if (!o || !o.n) return '–'; const settled = o.n - (o.pending || 0); return settled ? `${o[hitKey]}/${settled}${o.pending ? ' · ' + o.pending + ' open' : ''}` : `${o.n} open`; };
    parts.push(`<div class="card compact">${ordered.map((x) => `<div class="list-item tap day" data-day="${esc(x.date)}"><div class="main"><div class="match">${esc(dayName(x.date))}</div>
      <div class="meta">${x.n} matches${x.finished ? ` · ${x.finished} finished` : ''}${x.goals_avg != null ? ` · ${f1(x.goals_avg)} goals/match · O2.5 ${pct(x.o25_rate)} · BTTS ${pct(x.btts_rate)}` : ''}</div>
      <div class="chips">${x.botd && x.botd.n ? `<span class="chip ${chipCls(x.botd, 'hit')}">⭐ day card ${rate(x.botd, 'hit')}</span>` : ''}${x.safes && x.safes.n ? `<span class="chip ${chipCls(x.safes, 'hit')}">${icon('trend')} high-prob. ${rate(x.safes, 'hit')}</span>` : ''}${x.picks && x.picks.n ? `<span class="chip ${chipCls(x.picks, 'hit')}">${icon('star')} picks ${rate(x.picks, 'hit')}</span>` : ''}</div></div><div class="chev">${icon('next')}</div></div>`).join('')}</div>`);
    view().innerHTML = parts.join('');
    $$('[data-day]').forEach((b) => { b.onclick = () => { state.dayView = 'results'; PR.push({ type: 'day', date: b.dataset.day }); }; });
    $$('[data-dsort]').forEach((b) => { b.onclick = () => { state.daysOld = b.dataset.dsort === 'old'; PR.render(); }; });
  };
  function chipCls(o, k) { const settled = o.n - (o.pending || 0); if (!settled) return ''; const r = o[k] / settled; return r >= 0.6 ? 'good' : r <= 0.35 ? 'bad' : 'warn'; }
  PR.chipCls = chipCls;

  // ------------------------------------------------------------------ MORE (secondary football destinations, insights, activity and app tools)
  PR.views.more = function () {
    const d = state.data;
    const tickets = PR.tickets ? PR.tickets() : [];
    const pendingTickets = tickets.filter((t) => t.status === 'pending').length;
    const parts = [];
    const row = (icn, title, sub, attrs, right) => `<button class="more-row" ${attrs}><span class="tile">${icon(icn)}</span><span class="grow"><span class="b">${title}</span><span class="s">${sub}</span></span>${right || `<span class="chev">${icon('next')}</span>`}</button>`;
    const group = (title, rows) => `<section class="more-group"><h2 class="more-group-title">${title}</h2><div class="more-list">${rows.join('')}</div></section>`;
    parts.push(`<div class="hero-row more-head"><div><div class="kicker">Tools &amp; insights</div><h1>Explore</h1></div></div>`);
    parts.push(group('Match centre', [
      row('calendar', 'Days', 'Analysed fixtures · day by day', 'data-tab-go="days"'),
      row('trophy', 'Leagues', 'Worldwide competitions', 'data-tab-go="leagues"'),
      row('tag', 'Low odds', 'Sportybet prices from 1.19 to 1.45', 'data-tab-go="lowodds"'),
      row('target', 'Shortlist', 'Today’s high-conviction picks · grouped by market', 'data-tab-go="shortlist"'),
      row('star', '1X2', 'Match result · home, draw or away · today', 'data-tab-go="x12"'),
      row('clock', 'Sequences', 'Your betting windows · today’s matches', 'data-tab-go="sequences"'),
    ]));
    parts.push(group('Model & results', [
      row('users', 'Teams', 'Stats, form &amp; trends', 'data-page-go="teams"'),
      row('chart', 'Performance', 'Your results &amp; calibration', 'data-page-go="performance"'),
      row('shield', 'Bet advisor', 'Today’s advised picks &amp; staking', 'data-page-go="advisor"'),
      row('sparkle', 'Best of the day', 'Grounded daily shortlist', 'data-page-go="best"'),
      row('swap', 'All markets', 'Today · 1X2, Over 1.5, Over 2.5, corners · high to low', 'data-page-go="marketsboard"'),
      row('info', 'Guide to the markets', 'FAQ &amp; how the model works', 'data-page-go="guide"'),
      row('doc', 'Full analysis', 'The complete daily report', 'data-page-go="analysis"'),
    ]));
    parts.push(group('Your activity', [
      row('ticket', 'Tickets', pendingTickets ? `${pendingTickets} awaiting result` : 'My selections &amp; history', 'data-page-go="tickets"', pendingTickets ? `<span class="cnt">${pendingTickets}</span>` : undefined),
    ]));
    parts.push(group('App & support', [
      row('settings', 'Settings', 'App preferences', 'data-page-go="settings"'),
      row('download', 'Download today’s data (CSV)', 'Spreadsheet of the whole window', 'id="more-csv"'),
      row('chat', 'Contact on WhatsApp', 'Questions, feedback &amp; support', 'id="more-contact"'),
    ]));
    parts.push(`<div class="card version-card" style="margin-top:12px"><div class="b">Mr 2 Odds ${esc(PR.APP_VERSION || '')}</div><div class="tiny muted">Model \u00b7 Data \u00b7 Performance</div></div>`);
    view().innerHTML = parts.join('');
    wireCommon(); if (PR.wireTickets) PR.wireTickets();
    const csv = $('#more-csv'); if (csv) csv.onclick = () => PR.downloadDayCsv();
    const ct = $('#more-contact'); if (ct) ct.onclick = () => { if (PR.native && PR.native.openUrl) PR.native.openUrl(`https://wa.me/${PR.CONTACT.whatsapp}`); else window.open(`https://wa.me/${PR.CONTACT.whatsapp}`); };
  };
})(window.PR);
