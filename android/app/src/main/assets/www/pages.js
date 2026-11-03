/* Mr 2 Odds — stacked pages: match, team, day, analysis, performance, guide, settings. */
(function (PR) {
  'use strict';
  const { $, $$, esc, pct, f1, f2, signed, state, settings, fx, pill, koShort, koTime, dayName, niceDate, toast, selLabel, selGroup,
    GROUPS, liveVerdict, isLive, isFT, segmented, select, contactCard, teamLink, teamSpan, statusIcon, formBadges, wdl, md, icon, flag, badge, fxBadge, matchRow, ring, skeleton, parseLocal, tzNow, ymd, teamsCached, displayName } = PR;
  const GICON = { result: 'shield', dc: 'swap', goals: 'ball', btts: 'swap', team: 'target', corners: 'corner', cards: 'card' };
  const view = () => $('#view');
  const live = PR.live;
  const MK = { O15: 'Over 1.5 goals', O25: 'Over 2.5 goals', BTTS: 'Both teams to score' };
  const head = (title, sub, right) => `<div class="detail-head"><button class="back" id="back" aria-label="Back">${icon('back')}</button><div class="grow"><div class="b">${title}</div>${sub ? `<div class="tiny muted">${sub}</div>` : ''}</div>${right || ''}</div>`;
  function wireBack() { const b = $('#back'); if (b) b.onclick = () => PR.back(); }
  function ensureTeams(div) { if (!PR.teamsCached(div)) PR.loadTeams(div).then(() => PR.render()).catch(() => { state.teams[PR.slug(div)] = { missing: true }; PR.render(); }); }
  const rec = (div, name) => { const t = PR.teamsCached(div); return t && t.teams ? t.teams[name] : null; };
  /** League position of a team — shown only when the competition actually has a table (see PR.realTable). */
  const posOf = (div, r) => { if (!r || !r.pos) return null; const t = PR.teamsCached(div); return PR.realTable(t && t.table) ? r.pos : null; };
  const ord = (n) => { const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return s[(v - 20) % 10] || s[v] || s[0]; };
  // index rows keep xg/x12 as arrays, detail files as objects — read both
  const xgH = (f) => Array.isArray(f.xg) ? f.xg[0] : (f.xg || {}).home;
  const xgA = (f) => Array.isArray(f.xg) ? f.xg[1] : (f.xg || {}).away;
  const x12 = (f, k) => Array.isArray(f.x12) ? f.x12[{ H: 0, D: 1, A: 2 }[k]] : (f.x12 || {})[k];

  // ------------------------------------------------------------------ live extras (statistics, line-ups) fetched on demand
  const LS = 'https://prod-public-api.livescore.com/v1/api/app';
  state.lsx = state.lsx || {};
  function lsx(kind, eid, ttlMs) {
    const key = `${kind}:${eid}`; const c = state.lsx[key];
    if (c && (c.loading || Date.now() - c.t < ttlMs)) return c.data || null;
    state.lsx[key] = { loading: true, t: Date.now(), data: c ? c.data : null };
    PR.getJson(`${LS}/${kind}/soccer/${eid}`).then((j) => { state.lsx[key] = { t: Date.now(), data: j || {} }; PR.render(); }).catch(() => { state.lsx[key] = { t: Date.now(), data: c ? c.data : {} }; });
    return c ? c.data : null;
  }
  const fmtValue = (v) => v == null ? '–' : v >= 1e9 ? `€${(v / 1e9).toFixed(2)}bn` : v >= 1e6 ? `€${(v / 1e6).toFixed(1)}M` : `€${Math.round(v / 1e3)}K`;
  PR.fmtValue = fmtValue;
  function statsCard(f, s, sc) {
    // in play / finished: Livescore statistics; older finished matches: the stats saved in the day file
    let st = null;
    if (f.livescore_id && s && s.hg != null) {
      const j = lsx('statistics', f.livescore_id, isLive(s) ? 60000 : 3600000);
      const T = j && j.Stat ? Object.fromEntries(j.Stat.map((t) => [t.Tnb, t])) : null;
      if (T && T[1] && T[2]) {
        const g = (t, k) => t[k] == null ? null : +t[k]; const shots = (t) => (g(t, 'Shon') || 0) + (g(t, 'Shof') || 0) + (g(t, 'Shbl') || 0);
        st = [['Possession', g(T[1], 'Pss'), g(T[2], 'Pss'), '%'], ['Shots', shots(T[1]), shots(T[2])], ['On target', g(T[1], 'Shon'), g(T[2], 'Shon')], ['Corners', g(T[1], 'Cos'), g(T[2], 'Cos')], ['Fouls', g(T[1], 'Fls'), g(T[2], 'Fls')], ['Offsides', g(T[1], 'Ofs'), g(T[2], 'Ofs')], ['Yellow cards', g(T[1], 'Ycs'), g(T[2], 'Ycs')], ['Red cards', g(T[1], 'Rcs'), g(T[2], 'Rcs')]];
      }
    }
    if (!st && sc && (sc.hc != null || sc.hs != null || sc.hposs != null)) st = [['Possession', sc.hposs, sc.aposs, '%'], ['Shots', sc.hs, sc.as], ['On target', sc.hst, sc.ast], ['Corners', sc.hc, sc.ac], ['Fouls', sc.hf, sc.af], ['Yellow cards', sc.hy, sc.ay], ['Red cards', sc.hr, sc.ar]];
    state.lastStats = st ? st.filter(([, a, b]) => a != null || b != null) : null;
    if (!st) return '';
    const rows = st.filter(([, a, b]) => a != null || b != null).map(([k, a, b, unit]) => { const tot = (a || 0) + (b || 0); const wa = tot ? (a || 0) / tot : 0, wb = tot ? (b || 0) / tot : 0;
      return `<div class="statbar"><span class="${a > b ? 'lead' : ''}">${a == null ? '–' : a}${unit || ''}</span><div><div class="k">${k}</div><div class="duo"><span class="l" style="width:${Math.round(wa * 50)}%"></span><span class="r" style="width:${Math.round(wb * 50)}%"></span></div></div><span class="${b > a ? 'lead' : ''}">${b == null ? '–' : b}${unit || ''}</span></div>`; }).join('');
    return rows ? `<div class="card compact"><div class="row"><div class="grow b">${icon('chart', 'sm')} Match statistics</div><span class="tiny muted">${s && isLive(s) ? 'live' : 'full time'}</span></div>${rows}</div>` : '';
  }
  function lineupsBlock(f, s, x) {
    // Predicted XI (2026-10-12): when the official XI is not published yet, show our projection from the
    // club's archived confirmed line-ups — clearly labelled, never "official", never a model input.
    const projTeam = (t, name, side) => { if (!t || t.status !== 'ok') return '';
      const pl = (n, i) => `<div class="pl"><span class="no">${i < 11 ? i + 1 : ''}</span><span class="grow">${esc(n)}</span></div>`;
      const list = (t.xi || []).map((n, i) => pl(n, i)).join('') + ((t.bench || []).length ? `<h4>Probable subs</h4>${t.bench.map((n) => pl(n, 11)).join('')}` : '');
      return `<div><div class="b row" style="gap:6px">${fxBadge(f, side).replace('s24', 's20')}${teamSpan(name, f.country, f.div)}</div><div class="tiny muted">${esc(t.formation || '')} · projected from ${t.based_on} archived XI${t.based_on === 1 ? '' : 's'}${t.last ? ` · last ${esc(t.last)}` : ''}</div><h4>Predicted XI</h4>${list}</div>`; };
    const proj = (x && x.lineup_proj) || null;
    const projCard = (intro) => `<div class="card">${intro ? `<div class="tiny muted" style="margin-bottom:6px">${intro}</div>` : ''}<div class="lineup">${projTeam(proj.home, f.home, 'home')}${projTeam(proj.away, f.away, 'away')}</div><div class="tiny muted" style="margin-top:8px">${esc((proj && proj.note) || '')}</div></div>`;
    if (!f.livescore_id) {
      if (proj) return projCard('');
      return `<div class="card tiny muted">Line-ups are not available for this match.</div>`;
    }
    const ko = parseLocal(f.kickoff); const soon = ko && (ko - tzNow()) < 2 * 3600000;
    if (!soon && !(s && s.hg != null)) {
      if (proj) return projCard(`Official line-ups land about an hour before kick-off (${esc(koShort(f.kickoff))}). Until then, our projection:`);
      return `<div class="card empty">Line-ups are published about an hour before kick-off (${esc(koShort(f.kickoff))}).</div>`;
    }
    const j = lsx('lineups', f.livescore_id, s && isLive(s) ? 300000 : 1800000);
    if (j == null && proj) return projCard('');
    if (j == null) return skeleton(6);
    const lu = (j.Lu || []);
    if (!lu.length) {
      if (proj) return projCard('Official line-ups not published yet — our projection until they land:');
      const hp = (proj && proj.home) || {};
      const collecting = hp.status === 'collecting' ? ` Our projection needs ${hp.need || 3}+ archived line-ups per club (${hp.have || 0} archived so far for ${esc(f.home)}).` : '';
      return `<div class="card empty">Line-ups not published yet — check back closer to kick-off.${collecting}</div>`;
    }
    const team = (t, name, side) => { const ps = (t.Ps || []); const xi = ps.filter((p) => p.Pos >= 1 && p.Pos <= 4).sort((a, b) => a.Pos - b.Pos || (a.Fp || '').localeCompare(b.Fp || '')); const subs = ps.filter((p) => p.Pos === 5); const coach = ps.find((p) => p.Pos === 10);
      const pl = (p) => `<div class="pl"><span class="no">${p.Snu != null ? p.Snu : ''}</span><span class="grow">${esc(p.Snm || [p.Fn, p.Ln].filter(Boolean).join(' '))}</span>${p.Mo != null ? `<span class="pos">${p.Pos === 5 ? '▲' : '▼'} ${p.Mo}'</span>` : `<span class="pos">${esc((p.Pon || '').slice(0, 3).toUpperCase())}</span>`}</div>`;
      return `<div><div class="b row" style="gap:6px">${fxBadge(f, side).replace('s24', 's20')}${teamSpan(name, f.country, f.div)}</div>${t.Fo ? `<div class="tiny muted">${t.Fo.join('-')}</div>` : ''}<h4>Starting XI</h4>${xi.map(pl).join('')}${subs.length ? `<h4>Substitutes</h4>${subs.map(pl).join('')}` : ''}${coach ? `<h4>Coach</h4><div class="pl"><span class="no"></span><span>${esc(coach.Snm || [coach.Fn, coach.Ln].filter(Boolean).join(' '))}</span></div>` : ''}</div>`; };
    const h = lu.find((t) => t.Tnb === 1) || lu[0], a = lu.find((t) => t.Tnb === 2) || lu[1];
    return `<div class="card"><div class="lineup">${h ? team(h, f.home, 'home') : ''}${a ? team(a, f.away, 'away') : ''}</div><div class="tiny muted" style="margin-top:8px">Source: public live feed. ▼ substituted off · ▲ came on.</div></div>`;
  }

  // ------------------------------------------------------------------ MATCH PAGE
  PR.pages.match = function (page) {
    const f0 = fx(page.id); const key = PR.detailKey(page.id, page.d);
    let x = PR.detailCached(page.id, page.d);
    // wrong-stats guard: a detail that belongs to another match is never rendered — drop it, refetch
    // once from the network, and if the source itself is poisoned fall back to the fixture row (always right)
    if (x && page.id && x.id && String(x.id) !== String(page.id)) { state.details[key] = null; x = null; }
    if (!x && key && !state.details[key + '_loading'] && !state.details[key + '_bad']) {
      state.details[key + '_loading'] = true;
      PR.loadDetail(page.id, page.d).then(() => {
        const j = PR.detailCached(page.id, page.d);
        if (j && j.id && page.id && String(j.id) !== String(page.id)) state.details[key + '_bad'] = true;
        PR.render();
      }).catch((e) => { state.details[key] = { error: e.message }; PR.render(); }).finally(() => { delete state.details[key + '_loading']; });
    }
    if (x && x.error) x = null;
    // final identity net (wrong-stats bug): the analysis must name the very match that was tapped —
    // when the index row is known, its teams must match; a mismatched file is dropped, never rendered
    { const fchk = fx(page.id); if (x && fchk && (String(x.home || '') !== String(fchk.home) || String(x.away || '') !== String(fchk.away))) { state.details[key] = null; x = null; } }
    const drec = PR.dayRecord(page.id);
    const archived = !x && !f0 && drec && (state.details[key] && state.details[key].error || !key);
    if (archived) { archiveMatchPage(drec); return; }
    const f = x || f0;
    if (!f) {
      // not in the 24-hour index and no detail yet: fall back to the 60-day day archive (loads the day file if needed)
      const idp = String(page.id || '').split('|');
      const dt = idp[0];
      const day = /^\d{4}-\d{2}-\d{2}$/.test(dt) ? state.days[dt] : null;
      const rec = day && day.fixtures ? day.fixtures.find((r2) => r2.id === page.id || (idp.length > 3 && r2.home === idp[2] && r2.away === idp.slice(3).join('|') && r2.country === idp[1])) : null;
      if (rec) { archiveMatchPage(rec); wireBack(); return; }
      if (/^\d{4}-\d{2}-\d{2}$/.test(dt) && !state.days[dt] && !state.days[dt + '_loading'] && !state.days[dt + '_failed']) {
        state.days[dt + '_loading'] = true;
        view().innerHTML = head('Match') + skeleton(6); wireBack();
        PR.loadDay(dt).then(() => { state.days[dt + '_loading'] = false; PR.render(); }).catch(() => { state.days[dt + '_loading'] = false; state.days[dt + '_failed'] = true; PR.render(); });
        return;
      }
      view().innerHTML = head('Match') + (state.details[key] && state.details[key].error ? `<div class="card empty">Stats for this match are not available.</div>` : skeleton(6));
      wireBack(); return;
    }
    ensureTeams(f.div);
    const fin = PR.finalFor(f);
    const s0 = live.for(f); const s = s0 && s0.hg != null ? s0 : (fin ? { status: 'FT', hg: fin.hg, ag: fin.ag, ht: [fin.hth, fin.hta], t: 0, stored: true } : s0);
    const d = state.data; const v = state.matchView || 'overview';
    const th = rec(f.div, f.home), ta = rec(f.div, f.away);
    const fav = PR.isFav(f.id);
    const parts = [head(`${flag(f.country)} ${esc(f.competition)}`, `${esc(dayName(f.kickoff))} · ${esc(koTime(f.kickoff))} ${esc(d.meta.tz)}${f.time_known === false ? ' (time to be confirmed)' : ''}${f.referee ? ' · referee ' + esc(f.referee) : ''}`,
      f0 ? `<button class="favbtn ${fav ? 'on' : ''}" id="fav-btn" title="${fav ? 'Remove from favourites' : 'Add to favourites'}" aria-label="Favourite">${fav ? '★' : '☆'}</button>` : '')];
    const form = (p) => p && p.last5 ? formBadges(p.last5.slice().reverse().map((m) => wdl(m.gf, m.ga))) : '';
    const teams = (x && x.teams) || { home: {}, away: {} };
    const sq = (x && x.squad) || {}; const val = (side) => sq[side] && sq[side].value ? `<div class="value-tag">💶 ${fmtValue(sq[side].value)}</div>` : '';
    parts.push(`<div class="card mhead"><div class="teams">
      <div class="t">${fxBadge(f, 'home').replace('s24', 's56')}${teamLink(f, 'home')}<div class="tiny muted">${posOf(f.div, th) ? `${posOf(f.div, th)}${ord(posOf(f.div, th))} · ${th.all.pts} pts` : 'Home'}</div>${form(teams.home)}${val('home')}</div>
      <div class="mid">${s && s.hg != null ? `<div class="score big">${s.hg} – ${s.ag}</div><div class="minute ${isLive(s) ? 'on' : 'ft'}">${esc(isFT(s) ? 'FT' : s.status)}</div>${s.ht && s.ht[0] != null && s.ht[0] !== '' ? `<div class="tiny muted">HT ${esc(s.ht[0])}–${esc(s.ht[1])}</div>` : ''}` : `<div class="score big muted">${esc(koTime(f.kickoff))}</div><div class="tiny muted">${esc(koShort(f.kickoff).split(' ')[0])} · ${esc(d.meta.tz)}</div>`}</div>
      <div class="t">${fxBadge(f, 'away').replace('s24', 's56')}${teamLink(f, 'away')}<div class="tiny muted">${posOf(f.div, ta) ? `${posOf(f.div, ta)}${ord(posOf(f.div, ta))} · ${ta.all.pts} pts` : 'Away'}</div>${form(teams.away)}${val('away')}</div></div>
      <div class="x12"><div class="lbl"><span>${esc(f.home)} ${pct(x12(f, 'H'))}</span><span>Draw ${pct(x12(f, 'D'))}</span><span>${esc(f.away)} ${pct(x12(f, 'A'))}</span></div>
        <div class="tri"><span class="h" style="width:${Math.round((x12(f, 'H') || 0) * 100)}%"></span><span class="d" style="width:${Math.round((x12(f, 'D') || 0) * 100)}%"></span><span class="a" style="width:${Math.round((x12(f, 'A') || 0) * 100)}%"></span></div></div>
      <div class="chips small-chips" style="margin-top:6px;justify-content:center">${qualityChip(f)}${f.data_ok ? '' : '<span class="chip warn">⚠️ low data — never shortlisted</span>'}</div>
      ${PR.sbEventUrl(PR.fittedSbEvent(f)) ? `<a class="sb-open" href="${esc(PR.sbEventUrl(PR.fittedSbEvent(f)))}" style="display:flex;align-items:center;justify-content:center;gap:6px;margin-top:8px;padding:8px;border-radius:10px;background:var(--chip);font-size:13px;font-weight:600;color:var(--text)">${icon('target', 'sm')} Open in Sportybet — their live odds &amp; slip</a>` : ''}</div>`);
    const segTabs = [['overview', 'Overview'], ['form', 'Form'], ['markets', 'Markets'], ['sheet', 'Sheet'], ['trends', 'Trends'], ['stats', 'Stats'],
      ...(fin ? [['report', 'Report']] : []), ['table', 'Table'], ['h2h', 'H2H'], ['news', 'News'], ['data', 'Data'], ['lineups', 'Line-ups']];
    parts.push(`<div class="card compact">${segmented(segTabs, v, 'mv')}</div>`);
    if (v === 'lineups') parts.push(lineupsBlock(f, s, x));
    else if (v === 'report') matchReport(parts, f, fin, betsOn(f.id));
    else if (!x) parts.push(skeleton(5));
    else if (v === 'overview') matchOverview(parts, x, s);
    else if (v === 'form') matchForm(parts, f);
    else if (v === 'trends') matchTrends(parts, x);
    else if (v === 'markets') matchMarkets(parts, x);
    else if (v === 'sheet') matchSheet(parts, x);
    else if (v === 'stats') matchStats(parts, x, th, ta);
    else if (v === 'table') matchTable(parts, f, th, ta);
    else if (v === 'news') matchNews(parts, f, x);
    else if (v === 'data') matchData(parts, x);
    else matchH2H(parts, x);
    if (x) parts.push(`<div class="card compact"><div class="small muted">Detailed stats of this analysis as a spreadsheet file — probabilities, prices, team profiles, recent form, head-to-head, trends, corners & cards (opens in Google Sheets / Excel).</div><button class="btn" id="dl-csv" style="margin-top:8px;width:100%">${icon('download', 'sm')} Download stats (CSV)</button></div>`);
    view().innerHTML = parts.join('');
    wireBack();
    const fb = $('#fav-btn'); if (fb) fb.onclick = () => PR.toggleFav(f.id);
    const dl = $('#dl-csv'); if (dl) dl.onclick = () => PR.downloadMatchCsv(x, s, state.lastStats);
    const dls = $('#dl-sheet'); if (dls) dls.onclick = () => PR.downloadSheetCsv(x);
    $$('[data-mv]').forEach((b) => { b.onclick = () => { state.matchView = b.dataset.mv; PR.render(); }; });
  };
  /** Full-time report tab: a readable narrative of the finished match — result, how it went, and every
   *  model check against the real outcome. Presentation only; probabilities are the same numbers as always. */
  function matchReport(parts, f, fin, bets) {
    const card = matchReportCard(f, fin, bets || []);
    parts.push(card || `<div class="card empty small">Waiting for the final result \u2014 the report appears once the match ends and the statistics are captured (usually within a couple of hours of full time).</div>`);
  }
  function matchReportCard(f, sc, bets) {
    if (!sc || sc.hg == null) return '';
    const hg = sc.hg, ag = sc.ag, tot = hg + ag;
    const H = displayName(f, 'home'), A = displayName(f, 'away');
    const bits = [];
    if (sc.hth != null) bits.push(`Half-time ${sc.hth}\u2013${sc.hta}.`);
    if (sc.hs != null && sc.as != null) bits.push(`Shots ${sc.hs}\u2013${sc.as}${sc.hst != null ? ` (${sc.hst}\u2013${sc.ast} on target)` : ''}.`);
    if (sc.hposs != null && sc.aposs != null) bits.push(`Possession ${sc.hposs}%\u2013${sc.aposs}%.`);
    if (sc.hc != null && sc.ac != null) bits.push(`Corners ${sc.hc}\u2013${sc.ac}${sc.hy != null ? ` \u00b7 bookings ${sc.hy}\u2013${sc.ay}${sc.hr != null || sc.ar != null ? ` \u00b7 reds ${sc.hr || 0}\u2013${sc.ar || 0}` : ''}` : ''}.`);
    let scorers = '';
    try {
      const inc = (PR.storedIncidents(sc) || []).filter((it) => ['goal', 'own goal', 'penalty'].includes(it.type));
      if (inc.length) scorers = inc.map((it) => `${it.min != null ? it.min + "'" : ''} ${it.player || (it.team === 'H' ? f.home : f.away)}`).join(' \u00b7 ');
    } catch (e) { scorers = ''; }
    const p = f.p || {};
    const checks = [];
    const add = (label, prob, ok) => { if (prob != null) checks.push({ label, prob, ok }); };
    add('Over 1.5 goals', p.O15, tot >= 2);
    add('Over 2.5 goals', p.O25, tot >= 3);
    add('Both teams to score', p.BTTS, hg > 0 && ag > 0);
    const x = f.x12;
    if (Array.isArray(x) && x[0] != null && x[1] != null && x[2] != null) {
      let pi = 0; if (x[1] > x[pi]) pi = 1; if (x[2] > x[pi]) pi = 2;
      const ai = hg > ag ? 0 : hg < ag ? 2 : 1;
      add(`${['Home win', 'Draw', 'Away win'][pi]} (1X2)`, x[pi], pi === ai);
    }
    const rows = checks.map((c) => `<tr><td>${esc(c.label)}</td><td class="right"><b>${pct(c.prob)}</b></td><td class="right">${c.ok ? '<span class="good">\u2713 landed</span>' : '<span class="muted">\u2717 missed</span>'}</td></tr>`).join('');
    const betChips = (bets || []).length ? `<div class="chips" style="margin-top:8px">${bets.map((b) => `<span class="chip ${b.status === 'hit' || b.status === 'won' ? 'good' : b.status === 'miss' || b.status === 'lost' ? 'bad' : ''}">${b.botd ? '\u2b50 ' : ''}${esc(b.label || '')} ${statusIcon(b.status)}</span>`).join('')}</div>` : '';
    return `<div class="card"><div class="row"><div class="grow b">\u270d\ufe0f Match report</div><span class="chip">full time</span></div>
      <div class="b" style="font-size:16px;margin-top:6px">${esc(H)} <b>${hg}\u2013${ag}</b> ${esc(A)}</div>
      <div class="tiny muted" style="margin-top:4px">${bits.join(' ') || 'No match statistics were published for this competition \u2014 the final score is kept.'}</div>
      ${scorers ? `<div class="tiny muted" style="margin-top:4px">Goals: ${esc(scorers)}</div>` : ''}
      ${checks.length ? `<div class="b" style="margin-top:10px">How the model saw it</div><table class="tbl head" style="margin-top:4px"><tr><th>Market</th><th class="right">Model</th><th class="right">Outcome</th></tr>${rows}</table>
      <div class="tiny muted" style="margin-top:4px">A probability is not a result \u2014 each check above is graded automatically in Days.</div>` : ''}
      ${betChips}</div>`;
  }
  /** Goals / red cards: live incidents while the match is on, the stored ones from the archive afterwards. */
  function eventsCard(f, fin) {
    const live = f.livescore_id && state.incidents[f.livescore_id];
    const items = live && live.items.length ? live.items : PR.storedIncidents(fin);
    if (!items || !items.length) return '';
    const side = (t) => `<div class="ev ${t === 'H' ? 'h' : 'a'}">`;
    return `<div class="card compact"><div class="row"><div class="grow b">${icon('ball', 'sm')} Match events</div><span class="tiny muted">${live && live.items.length ? 'live' : 'archive'}</span></div>
      <div class="events">${items.map((it) => `${side(it.team)}<span class="who">${it.team === 'H' ? esc(f.home) : esc(f.away)}</span><span class="what">${PR.incidentLine(it)}</span></div>`).join('')}</div></div>`;
  }
  /** Match page for a finished match whose detailed analysis file has been retired: everything comes from the
   *  day archive (final score, half-time, statistics, goals, the model's numbers at kick-off and the bets). */
  function archiveMatchPage(r) {
    const sc = r.score || {}; const fin = sc.hg != null ? sc : null; const d = state.data;
    const f = { id: r.id, home: r.home, away: r.away, home_long: r.home_long, away_long: r.away_long, country: r.country, league: r.league, competition: r.competition, div: r.div, kickoff: r.kickoff, livescore_id: r.livescore_id, badges: r.badges, p: r.p || {}, xg: r.xg, x12: r.x12, data_ok: r.data_ok };
    const s = fin ? { status: sc.status || 'FT', hg: sc.hg, ag: sc.ag, ht: [sc.hth, sc.hta], t: 0 } : (sc.status ? { status: sc.status, hg: null, ag: null } : null);
    const parts = [head(`${flag(f.country)} ${esc(f.competition || f.league || '')}`, `${esc(dayName(f.kickoff))} · ${esc(koTime(f.kickoff))} ${esc(d.meta.tz)} · archive`)];
    parts.push(`<div class="card mhead"><div class="teams">
      <div class="t">${fxBadge(f, 'home').replace('s24', 's56')}<div class="nm b">${esc(displayName(f, 'home'))}</div><div class="tiny muted">Home</div></div>
      <div class="mid">${s && s.hg != null ? `<div class="score big">${s.hg} – ${s.ag}</div><div class="minute ft">FT</div>${s.ht && s.ht[0] != null ? `<div class="tiny muted">HT ${s.ht[0]}–${s.ht[1]}</div>` : ''}` : `<div class="score big muted">${esc(koTime(f.kickoff))}</div><div class="tiny muted">${esc(s && s.status ? s.status : 'no result recorded')}</div>`}</div>
      <div class="t">${fxBadge(f, 'away').replace('s24', 's56')}<div class="nm b">${esc(displayName(f, 'away'))}</div><div class="tiny muted">Away</div></div></div>
      ${Array.isArray(f.x12) && f.x12[0] != null ? `<div class="x12"><div class="lbl"><span>${esc(f.home)} ${pct(f.x12[0])}</span><span>Draw ${pct(f.x12[1])}</span><span>${esc(f.away)} ${pct(f.x12[2])}</span></div><div class="tri"><span class="h" style="width:${Math.round(f.x12[0] * 100)}%"></span><span class="d" style="width:${Math.round(f.x12[1] * 100)}%"></span><span class="a" style="width:${Math.round(f.x12[2] * 100)}%"></span></div></div>` : ''}</div>`);
    const rep = matchReportCard(f, sc, r.bets || []);
    if (rep) parts.push(rep);
    const st = statsCard(f, s, fin); if (st) parts.push(st);
    else if (fin) parts.push(`<div class="card tiny muted">No match statistics were published for this competition. The final score${fin.inc ? ' and goals are' : ' is'} kept.</div>`);
    const evs = eventsCard(f, fin); if (evs) parts.push(evs);
    if (f.xg || (f.p && f.p.O25 != null)) parts.push(`<div class="card compact"><div class="b">Model at kick-off</div><div class="grid4" style="margin-top:6px">${Array.isArray(f.xg) ? `<div class="cell"><div class="k">Model xG</div><div class="v">${f1(f.xg[0])} – ${f1(f.xg[1])}</div></div>` : ''}<div class="cell"><div class="k">Over 1.5</div><div class="v">${pct(f.p.O15)}</div></div><div class="cell"><div class="k">Over 2.5</div><div class="v">${pct(f.p.O25)}</div></div><div class="cell"><div class="k">BTTS</div><div class="v">${pct(f.p.BTTS)}</div></div></div>
      ${(r.top || []).length ? `<div class="tiny muted" style="margin-top:6px">Top priced selections at the time: ${r.top.map((t) => `${esc(t.label || t[0] || '')}${t.p != null ? ' ' + pct(t.p) : ''}${t.odds ? ' @ ' + f2(t.odds) : ''}`).join(' · ')}</div>` : ''}</div>`);
    const bets = r.bets || [];
    if (bets.length) parts.push(`<div class="card compact"><div class="b">Bets on this match</div><div class="chips" style="margin-top:6px">${bets.map((b) => `<span class="chip ${b.status === 'hit' ? 'good' : b.status === 'miss' ? 'bad' : ''}">${b.botd ? '⭐ ' : ''}${esc(b.label)}${b.odds ? ' @ ' + f2(b.odds) : ''} ${statusIcon(b.status)}</span>`).join('')}</div></div>`);
    const ah2h = r.h2h || [];
    if (ah2h.length) {
      const wins = (name) => ah2h.filter((m) => (m.home === name && m.hg > m.ag) || (m.away === name && m.ag > m.hg)).length;
      const dr = ah2h.filter((m) => m.hg === m.ag).length;
      parts.push(`<div class="card compact"><div class="row"><div class="grow b">Head to head · last ${ah2h.length}</div><span class="chip">previous meetings</span></div>
        ${h2hTrend(ah2h, f.home, f.away)}
        <div class="h2h-bar"><span class="h" style="flex:${wins(f.home) || 0.001}">${wins(f.home)}</span><span class="d" style="flex:${dr || 0.001}">${dr}</span><span class="a" style="flex:${wins(f.away) || 0.001}">${wins(f.away)}</span></div><div class="lbl tiny muted row"><span class="grow">${esc(f.home)} wins</span><span>draws</span><span class="grow right">${esc(f.away)} wins</span></div>
        <table class="tbl" style="margin-top:6px">${ah2h.map((m) => `<tr class="tap" data-fx="${esc(histId(m.date, m.country || f.country, m.home, m.away))}"><td class="tiny muted nowrap">${esc(m.date || '')}</td><td class="${m.hg > m.ag ? 'b' : ''}"><div class="row" style="gap:6px">${esc(m.home)}</div></td><td class="right nowrap"><b>${m.hg} – ${m.ag}</b></td><td class="${m.ag > m.hg ? 'b' : ''}">${esc(m.away)}</td><td class="tiny muted">${esc(m.league || '')}</td></tr>`).join('')}</table></div>`);
    }
    parts.push(`<div class="card tiny muted">The full pre-match analysis (trends, markets, data audit) is kept permanently — once Mr 2 Odds analyses a fixture, that analysis, its result, statistics and goals stay on record.</div>`);
    view().innerHTML = parts.join('');
    wireBack();
  }
  function matchOverview(parts, f, s) {
    const xg = f.xg || {}; const q = f.quality || null; const conf = f.confidence || {};
    const mk = xg.market_home != null ? `<div class="cell" style="display:inline-block;margin-left:10px"><div class="k">Market xG</div><div class="v muted">${f1(xg.market_home)} – ${f1(xg.market_away)}</div><div class="tiny muted">total ${f2(xg.market_total)}</div></div>` : `<div class="cell" style="display:inline-block;margin-left:10px"><div class="k">Market xG</div><div class="v muted">N/A</div><div class="tiny muted">no prices</div></div>`;
    const x12 = f.x12;
    const ringSet = Array.isArray(x12) ? `${ring(x12[0] || 0, 'Home win')}${ring(x12[1] || 0, 'Draw')}${ring(x12[2] || 0, 'Away win')}` : `${ring(f.p.O15, 'Over 1.5')}${ring(f.p.O25, 'Over 2.5')}${ring(f.p.BTTS, 'BTTS')}`;
    parts.push(`<div class="card"><div class="model-head"><span class="t">Model</span><span class="tiny muted">1X2 \u00b7 football data only</span></div>
      <div class="row"><div class="grow"><div class="cell" style="display:inline-block"><div class="k">Model xG</div><div class="v">${f1(xgH(f))} – ${f1(xgA(f))}</div><div class="tiny muted">total ${f2(xg.total)}</div></div>${mk}</div>
      <div class="rings" style="flex:2">${ringSet}</div></div>
      <div class="tiny muted" style="margin-top:8px"><b>Model probabilities</b> from football data only (goals, form, venue, league baseline) — bookmaker prices are compared, never blended in. Confidence ${esc(conf.O25 || 'N/A')}${q ? ` · data quality ${esc(q.overall)}` : ''} · samples ${(f.teams.home || {}).n || 0} / ${(f.teams.away || {}).n || 0} matches · league avg ${f2((f.league_avg.home_goals || 0) + (f.league_avg.away_goals || 0))} goals, O2.5 in ${pct(f.league_avg.o25)}${xg.market_total != null ? ` · model v market total ${(xg.total - xg.market_total) >= 0 ? '+' : ''}${f2(xg.total - xg.market_total)}` : ''}</div></div>`);
    if (f.scores && f.scores.length) {
      const cov = f.scores.reduce((a, sc) => a + (sc[2] || 0), 0);
      parts.push(`<div class="card compact"><div class="row"><div class="grow b">Most likely scorelines</div><span class="tiny muted">Dixon-Coles model</span></div>
        <div class="chips" style="margin-top:6px">${f.scores.map((sc) => `<span class="chip"><b>${sc[0]}-${sc[1]}</b> ${pct(sc[2])}</span>`).join('')}</div>
        <div class="tiny muted" style="margin-top:6px">Top ${f.scores.length} scorelines carry ${pct(cov)} of the model's probability — the most likely boards, not a forecast of the exact score.</div></div>`);
    }
    const warns = (f.warnings || []).filter((w) => w.level === 'warn');
    if (warns.length) parts.push(`<div class="card compact"><div class="b">${icon('alert', 'sm')} Checks</div><div class="small" style="margin-top:4px">${warns.slice(0, 4).map((w) => `<div>⚠️ ${esc(w.text)}</div>`).join('')}</div><div class="tiny muted" style="margin-top:4px">All checks under Data.</div></div>`);
    const fin0 = PR.finalFor(f);
    const sc0 = statsCard(f, s, fin0); if (sc0) parts.push(sc0);
    else if (s && s.hg != null && !isLive(s)) parts.push(`<div class="card tiny muted">No match statistics were published for this competition (Livescore covers statistics for the bigger leagues only). The final score and goals are kept.</div>`);
    const evs = eventsCard(f, fin0); if (evs) parts.push(evs);
    const bets = betsOn(f.id);
    if (bets.length) parts.push(`<div class="card compact"><div class="b">Bets on this match</div><div class="chips" style="margin-top:6px">${bets.map((b) => { const vd = liveVerdict(b.sel, s); return `<span class="chip ${vd.cls}">${esc(b.kind)}: ${esc(b.label)}${b.odds ? ' @ ' + f2(b.odds) : ''} · ${esc(vd.text)}</span>`; }).join('')}</div></div>`);
    const best = f.sels.filter((x) => x.odds).slice(0, 5);
    if (best.length) parts.push(`<div class="card compact"><div class="row"><div class="grow b">${icon('target', 'sm')} Highest model probabilities (priced)</div><span class="tiny muted">+ adds to your slip</span></div><table class="tbl">${best.map((x) => `<tr><td><div class="b">${esc(selLabel(x.sel, f.home, f.away))}</div><div class="tiny muted">${esc(GROUPS[selGroup(x.sel)])} · market implied ${pct(x.p_sb)}${x.diff_pp != null ? ` · ${x.diff_pp >= 0 ? '+' : ''}${f1(x.diff_pp)} pp` : ''}</div></td><td class="right"><b>${f2(x.odds)}</b></td><td class="right"><div class="row" style="gap:0;justify-content:flex-end">${pill(x.p, 0.8, 0.7)}${PR.addBtn ? PR.addBtn(f.id, x.sel, x.odds) : ''}</div></td></tr>`).join('')}</table></div>`);
    // non-Trends surfaces show only the 3 strongest trends (user rule 2026-10-13) — the Trends tab keeps everything
    const tr = f.trends || {}; const topTrends = [].concat((tr.match || []).filter((t) => t.kind !== 'info'), (tr.home && tr.home.all) || [], (tr.away && tr.away.all) || [], tr.h2h || [])
      .sort((a, b) => (b.s || 0) - (a.s || 0)).slice(0, 3);
    if (topTrends.length) parts.push(`<div class="card compact tap" id="go-trends"><div class="row"><div class="grow b">${icon('trend', 'sm')} Trends</div><span class="tiny muted">all ${icon('next', 'sm')}</span></div><div class="trends">${topTrends.map(trendLine).join('')}</div></div>`);
    const sb = f.sportybet || {};
    if (Object.keys(sb).length) {
      const ou = sb.OU || {};
      parts.push(`<div class="card compact"><div class="b">Sportybet prices</div><table class="tbl head" style="margin-top:6px"><tr><th>Market</th><th class="right">1 / Over / Yes</th><th class="right">X</th><th class="right">2 / Under / No</th></tr>
        ${sb['1X2'] ? `<tr><td>Match result</td><td class="right">${f2(sb['1X2'][0])}</td><td class="right">${f2(sb['1X2'][1])}</td><td class="right">${f2(sb['1X2'][2])}</td></tr>` : ''}
        ${sb.DC ? `<tr><td>Double chance 1X · 12 · X2</td><td class="right">${f2(sb.DC['1X'])}</td><td class="right">${f2(sb.DC['12'])}</td><td class="right">${f2(sb.DC.X2)}</td></tr>` : ''}
        ${['0.5', '1.5', '2.5', '3.5', '4.5'].filter((l) => ou[l]).map((l) => `<tr><td>Goals ${l}</td><td class="right">${f2(ou[l][0])}</td><td></td><td class="right">${f2(ou[l][1])}</td></tr>`).join('')}
        ${sb.BTTS ? `<tr><td>Both teams to score</td><td class="right">${f2(sb.BTTS[0])}</td><td></td><td class="right">${f2(sb.BTTS[1])}</td></tr>` : ''}</table>
        <div class="tiny muted" style="margin-top:4px">Prices are payout information and a comparison layer — they never change the model probability. All lines under Markets.</div></div>`);
    } else parts.push(`<div class="card tiny muted">No Sportybet price for this match — no market comparison available.</div>`);
    setTimeout(() => { const g = $('#go-trends'); if (g) g.onclick = () => { state.matchView = 'trends'; PR.render(); }; }, 0);
  }
  const TICON = { goals: '⚽', ht: '⏱️', corners: '🚩', cards: '🟨', form: '📈', info: 'ℹ️' };
  function trendLine(t) {
    const r = t.r == null ? null : Math.round(t.r * 100);
    const ev = t.n > 0 && t.kind !== 'info' ? `<span class="tiny muted"> · ${t.n} match${t.n === 1 ? '' : 'es'}, ${evidenceLabel(t.n).toLowerCase()} evidence</span>` : '';
    return `<div class="trend ${t.kind}"><span class="ti">${TICON[t.kind] || '•'}</span><span class="tt">${esc(t.t)}${ev}</span>${r != null && t.n > 0 && t.kind !== 'form' ? `<span class="tr" title="historical frequency"><span class="bar"><span class="fill ${r >= 80 ? 'hi' : r >= 65 ? 'mid' : ''}" style="width:${r}%"></span></span><b>${r}%</b></span>` : ''}</div>`;
  }
  function matchTrends(parts, f) {
    const tr = f.trends || {}; const any = (tr.match || []).length || (tr.home && tr.home.all.length) || (tr.away && tr.away.all.length) || (tr.h2h || []).length;
    parts.push(`<div class="card tiny muted">Streaks and <b>historical frequencies</b> from the last 10 matches of each team (and the last 5 at this venue), all competitions. "9 of 10" is what happened (90% frequency), not a probability — the model probabilities on the Overview already include recent form. Samples this small are weak evidence on their own.</div>`);
    if (!any) { parts.push(`<div class="card empty">Not enough recent matches for trends.</div>`); return; }
    const block = (title, items, sub) => items && items.length ? `<div class="card compact"><div class="row"><div class="grow b">${title}</div>${sub ? `<span class="tiny muted">${sub}</span>` : ''}</div><div class="trends">${items.map(trendLine).join('')}</div></div>` : '';
    parts.push(block(`${icon('swap', 'sm')} Match trends`, tr.match));
    parts.push(block(`${fxBadge(f, 'home').replace('s24', 's20')} ${esc(f.home)}`, tr.home && tr.home.all, `last ${tr.home ? tr.home.n : 0}`));
    parts.push(block(`${fxBadge(f, 'home').replace('s24', 's20')} ${esc(f.home)} at home`, tr.home && tr.home.venue));
    parts.push(block(`${fxBadge(f, 'away').replace('s24', 's20')} ${esc(f.away)}`, tr.away && tr.away.all, `last ${tr.away ? tr.away.n : 0}`));
    parts.push(block(`${fxBadge(f, 'away').replace('s24', 's20')} ${esc(f.away)} away`, tr.away && tr.away.venue));
    parts.push(block(`${icon('history', 'sm')} Head to head`, tr.h2h));
  }
  function betsOn(fid) {
    const d = state.data, out = [], sf = d.safe || { bets: [] };
    ((sf.today && sf.today.bets) || []).filter((b) => b.fixture === fid).forEach((b) => out.push({ kind: '⭐ Bet of the day', label: b.label, sel: b.sel, odds: b.odds }));
    sf.bets.filter((b) => b.fixture === fid && !out.some((o) => o.sel === b.sel)).forEach((b) => out.push({ kind: '📈 High probability', label: b.label, sel: b.sel, odds: b.odds }));
    Object.entries(d.picks || {}).forEach(([mk, lst]) => lst.filter((p) => p.fixture === fid).forEach(() => out.push({ kind: 'Shortlist', label: MK[mk], sel: mk })));
    if (PR.tickets) PR.tickets().forEach((t) => { if (t.status === 'pending') t.legs.filter((l) => l.fixture === fid).forEach((l) => out.push({ kind: '🎫 My ticket', label: l.label, sel: l.sel, odds: l.odds })); });
    return out;
  }
  function matchMarkets(parts, f) {
    const groups = {};
    f.sels.forEach((s) => { (groups[selGroup(s.sel)] = groups[selGroup(s.sel)] || []).push(s); });
    parts.push(`<div class="card tiny muted">Every modelled market. <b>Model</b> = football-data model probability (used for ranking). <b>Market</b> = Sportybet price with the margin removed — a comparison, never an input. <b>Diff</b> = model − market in points; <b>EV</b> = model % × price − 1. Rows at ≥ 70% model probability are highlighted; ⚠ = model / market disagreement of more than 12 points. Tap <b>+</b> to put a priced selection on your bet slip.</div>`);
    Object.keys(GROUPS).forEach((g) => {
      const items = groups[g]; if (!items) return;
      const order = { result: ['H', 'D', 'A'], dc: ['1X', '12', 'X2'], btts: ['BTTS', 'NBTTS'] }[g];
      const sorted = order ? items.slice().sort((a, b) => order.indexOf(a.sel) - order.indexOf(b.sel)) : items.slice().sort((a, b) => a.sel.localeCompare(b.sel, undefined, { numeric: true }));
      parts.push(`<div class="card compact"><div class="row" style="margin:4px 0 2px"><span class="ico">${icon(GICON[g] || 'ball')}</span><b>${GROUPS[g]}</b>${(g === 'corners' || g === 'cards') && lowCount(f, g) ? '<span class="chip warn" style="margin-left:6px">LOW DATA CONFIDENCE</span>' : ''}</div><table class="tbl head" style="margin-top:4px"><tr><th>Selection</th><th class="right">Market</th><th class="right">Diff</th><th class="right">Price · EV</th><th class="right">Model</th></tr>
        ${sorted.map((s) => `<tr class="${s.p >= 0.7 ? 'hl' : ''}"><td>${esc(selLabel(s.sel, f.home, f.away))}${s.diff ? ' <span class="warn">⚠</span>' : ''}</td><td class="right muted">${pct(s.p_sb)}</td><td class="right muted">${s.diff_pp == null ? '–' : `${s.diff_pp >= 0 ? '+' : ''}${Math.round(s.diff_pp)}`}</td><td class="right">${s.odds ? `<b>${f2(s.odds)}</b><div class="tiny ${s.ev > 0.02 ? 'pos' : 'muted'}">${s.ev == null ? '' : (s.ev >= 0 ? '+' : '') + Math.round(100 * s.ev) + '%'}</div>` : '<span class="muted">–</span>'}</td><td class="right"><div class="row" style="gap:0;justify-content:flex-end">${pill(s.p_model, 0.8, 0.7)}${PR.addBtn ? PR.addBtn(f.id, s.sel, s.odds) : ''}</div></td></tr>`).join('')}</table></div>`);
    });
    const sb = f.sportybet || {};
    const lines = (obj, label) => obj ? `<tr><td>${label}</td><td colspan="4" class="tiny">${Object.entries(obj).sort((a, b) => +a[0] - +b[0]).map(([k, v]) => `<span class="chip">${k}: ${f2(v[0])} / ${f2(v[1])}</span>`).join(' ')}</td></tr>` : '';
    if (sb.CORN || sb.CARDS || sb.CORNH || sb.CORN1H) parts.push(`<div class="card compact"><div class="b">More Sportybet lines (over / under)</div><table class="tbl" style="margin-top:4px">${lines(sb.CORN, 'Corners')}${lines(sb.CORN1H, '1st-half corners')}${lines(sb.CORNH, 'Home corners')}${lines(sb.CORNA, 'Away corners')}${lines(sb.CARDS, 'Cards')}${lines(sb.CARDSH, 'Home cards')}${lines(sb.CARDSA, 'Away cards')}</table></div>`);
    if (f.corners || f.cards) parts.push(`<div class="card compact"><div class="b">Expected counts (own corner / card models)</div><div class="grid4" style="margin-top:6px">${f.corners ? `<div class="cell"><div class="k">Corners</div><div class="v">${f1(f.corners.total)}</div><div class="tiny muted">${f1(f.corners.home)} – ${f1(f.corners.away)}${countN(f.corners)}</div></div>` : ''}${f.cards ? `<div class="cell"><div class="k">Cards</div><div class="v">${f1(f.cards.total)}</div><div class="tiny muted">${f1(f.cards.home)} – ${f1(f.cards.away)}${countN(f.cards)}</div></div>` : ''}</div></div>`);
    else parts.push(`<div class="card tiny muted">Corners and cards are modelled for the 22 main European leagues, where match statistics are published.</div>`);
  }
  /** User's Google Sheet V1 bookmaker model, filled with this match. Comparison only. */
  function matchSheet(parts, f) {
    const sm = f.sheet_model;
    if (!sm) {
      parts.push(`<div class="card empty">The sheet model was not on this analysis yet — it is filled on the next scan. Mr 2 Odds's own numbers on the other tabs are unchanged.</div>`);
      return;
    }
    const inp = sm.inputs || {};
    const eng = sm.model || {};
    const cell = (v, d) => (v == null || v === '') ? '<span class="muted">N/A</span>' : esc(String(d ? d(v) : v));
    parts.push(`<div class="card tiny muted"><b>Your Google Sheet model (V1)</b> — the same MATCH_INPUT → MODEL_ENGINE → SCORE_MATRIX → MARKETS formulas, filled with <b>this match's available data</b>. Mr 2 Odds's Dixon-Coles model is not changed; the two sit side by side so you can compare them. Missing inputs are N/A, never invented.</div>`);
    parts.push(`<div class="card compact"><div class="b">${icon('info', 'sm')} Match information</div>
      <table class="tbl" style="margin-top:6px">
        <tr><td>Competition</td><td>${cell(inp.competition)}</td></tr>
        <tr><td>Season</td><td>${cell(inp.season)}</td></tr>
        <tr><td>Date</td><td>${cell(inp.date)}</td></tr>
        <tr><td>Home</td><td>${cell(inp.home)}</td></tr>
        <tr><td>Away</td><td>${cell(inp.away)}</td></tr>
        <tr><td>Venue</td><td>${cell(inp.venue)}</td></tr>
      </table></div>`);
    parts.push(`<div class="card compact"><div class="b">${icon('chart', 'sm')} V1 statistical inputs</div>
      <table class="tbl head" style="margin-top:6px"><tr><th>Input</th><th class="right">Value</th></tr>
        <tr><td>Home goals scored / home game</td><td class="right">${cell(inp.home_gf_home, f2)}</td></tr>
        <tr><td>Home goals conceded / home game</td><td class="right">${cell(inp.home_ga_home, f2)}</td></tr>
        <tr><td>Away goals scored / away game</td><td class="right">${cell(inp.away_gf_away, f2)}</td></tr>
        <tr><td>Away goals conceded / away game</td><td class="right">${cell(inp.away_ga_away, f2)}</td></tr>
        <tr><td>League average home goals / game</td><td class="right">${cell(inp.lg_home, f2)}</td></tr>
        <tr><td>League average away goals / game</td><td class="right">${cell(inp.lg_away, f2)}</td></tr>
      </table>
      <div class="tiny muted" style="margin-top:6px">Home sample ${inp.home_venue_n || 0} games · away sample ${inp.away_venue_n || 0}. When a venue split is empty we use overall goals / game (still real data). Context kept for the sheet but not used by V1: xG ${cell(inp.home_xg, f2)} / ${cell(inp.away_xg, f2)}, SOT ${cell(inp.home_sot, f1)} / ${cell(inp.away_sot, f1)}.</div>
      ${(sm.missing || []).length ? `<div class="tiny warn" style="margin-top:4px">Not available: ${esc((sm.missing || []).join('; '))}.</div>` : ''}</div>`);
    if (!sm.ok || !eng.lambda_h) {
      parts.push(`<div class="card empty">V1 cannot run until the six statistical inputs are present. Nothing was invented.</div>`);
    } else {
      parts.push(`<div class="card compact"><div class="b">${icon('sparkle', 'sm')} Sheet engine (unchanged formulas)</div>
        <table class="tbl head" style="margin-top:6px"><tr><th></th><th class="right">Sheet</th><th class="right">Mr 2 Odds</th></tr>
          <tr><td>Expected home goals (λH)</td><td class="right"><b>${f2(eng.lambda_h)}</b></td><td class="right">${f2((f.xg || {}).model_home)}</td></tr>
          <tr><td>Expected away goals (λA)</td><td class="right"><b>${f2(eng.lambda_a)}</b></td><td class="right">${f2((f.xg || {}).model_away)}</td></tr>
          <tr><td>Expected total</td><td class="right">${f2(eng.lambda_total)}</td><td class="right">${f2((f.xg || {}).model_total)}</td></tr>
        </table>
        <div class="tiny muted" style="margin-top:4px">Sheet: league home × home attack × away defence (raw venue rates, no shrinkage). Mr 2 Odds: league × shrunk ratings × Dixon-Coles. 1X2 sheet sum ${eng.x12_sum != null ? Math.round(eng.x12_sum * 1000) / 10 + '%' : '—'} (0–7 matrix residual ${eng.matrix_residual != null ? Math.round(eng.matrix_residual * 10000) / 100 + ' pp' : '—'}).</div></div>`);
      const rows = (sm.markets || []).map((m) => {
        const sp = m.p, pp = m.playreport;
        return `<tr><td>${esc(m.name)}</td><td class="right"><b>${pct(sp)}</b><div class="tiny muted">${m.fair != null ? f2(m.fair) : ''}</div></td><td class="right">${pp == null ? '<span class="muted">—</span>' : pct(pp)}</td></tr>`;
      }).join('');
      parts.push(`<div class="card compact"><div class="b">${icon('ticket', 'sm')} Market probabilities &amp; fair odds</div>
        <table class="tbl head" style="margin-top:6px"><tr><th>Market</th><th class="right">Sheet · fair</th><th class="right">Mr 2 Odds</th></tr>${rows}</table>
        <div class="tiny muted" style="margin-top:4px">Fair odds = 1 / sheet probability. Mr 2 Odds column is this app's model for the same market (blank when that market is not modelled the same way, e.g. Over 0.5).</div></div>`);
    }
    parts.push(`<div class="card compact"><div class="small muted">Download this match's filled MATCH_INPUT + MARKETS as a spreadsheet file (opens in Google Sheets / Excel). Calculations are the sheet's V1 formulas; Mr 2 Odds's model is not in this file except as a comparison column.</div><button class="btn" id="dl-sheet" style="margin-top:8px;width:100%">${icon('download', 'sm')} Download sheet model (CSV)</button></div>`);
  }
  // ------------------------------------------------------------------ DATA / AUDIT TAB (data-first engine)
  const EVIDENCE = [[40, 'Very strong'], [20, 'Strong'], [10, 'Moderate'], [5, 'Small'], [1, 'Very small']];
  function evidenceLabel(n) { if (!n || n < 1) return 'No data'; for (const [lo, name] of EVIDENCE) if (n >= lo) return name; return 'Very small'; }
  function evChip(n) { const l = evidenceLabel(n); const cls = n >= 20 ? 'ok' : n >= 10 ? '' : 'warn'; return `<span class="chip ${cls}">${n || 0} match${n === 1 ? '' : 'es'} · ${l}</span>`; }
  function qualityChip(f) { const q = f.quality || (f.q ? { overall: f.q } : null); if (!q) return ''; const cls = q.overall === 'High' ? 'ok' : q.overall === 'Low' ? 'warn' : ''; return `<span class="chip ${cls}">data quality ${esc(q.overall)}${q.score != null ? ' · ' + q.score : ''}</span>`; }
  function lowCount(f, g) { const c = g === 'corners' ? f.corners : f.cards; return c && c.low_confidence; }
  function countN(c) { return c && c.n ? ` · ${c.n[0]} / ${c.n[1]} matches with stats${c.low_confidence ? ' · LOW DATA CONFIDENCE' : ''}` : ''; }
  const na = (v, fmt) => v == null ? '<span class="muted">N/A</span>' : (fmt || ((x) => x))(v);
  function expandMatches(m) { return m && m.cols ? (m.rows || []).map((r) => { const o = {}; m.cols.forEach((c, i) => { o[c] = r[i]; }); return o; }) : (m || []); }
  function matchData(parts, f) {
    const q = f.quality, ev = f.evidence, ex = f.explain, mk = f.market, h2h = f.h2h_meta, conf = f.confidence || {};
    if (!q || !ev) { parts.push(`<div class="card empty">No data audit for this match yet — it was analysed before the data-first engine. The next scan adds it.</div>`); return; }
    parts.push(`<div class="card tiny muted"><b>Vocabulary.</b> Historical frequency = what happened in the sample ("scored in 9 of 10" = 90%). Model probability = the football-data model. Market implied = the bookmaker price with the margin removed (comparison only, never a model input). Missing data is shown as N/A, never as 0.</div>`);
    // 0. live research / context (present only for fixtures the research layer has covered)
    //    Base probability -> any bounded context adjustment -> final probability, with the facts and sources.
    const cx = f.context;
    if (cx) {
      const cqc = cx.quality === 'HIGH' ? 'ok' : (cx.quality === 'LOW' || cx.quality === 'INSUFFICIENT') ? 'warn' : '';
      const b25 = cx.base ? cx.base.O25 : null, f25 = cx.final ? cx.final.O25 : null;
      const t = cx.totals || {};
      const d25 = (b25 != null && f25 != null) ? (f25 - b25) * 100 : 0;
      const ppTxt = t.applied && Math.abs(d25) > 0.05 ? `${d25 > 0 ? '+' : '−'}${f1(Math.abs(d25))} pp on O2.5` : 'no adjustment';
      const adj = (cx.adjustments || []).filter((a) => a.lam_pct); 
      const rows = (cx.adjustments || []).map((a) => `<tr><td class="nowrap" style="text-transform:capitalize">${esc(a.cat)}</td><td class="right"><b>${a.lam_pct ? (a.lam_pct > 0 ? '+' : '−') + f1(Math.abs(a.lam_pct)) + '%' : '0'}</b></td><td class="tiny muted">${esc(a.reason || '')}${a.sources && a.sources.length ? ` <i>(${esc(a.sources.join(', '))})</i>` : ''}</td></tr>`).join('');
      const facts = (cx.facts || []).slice(0, 10).map((x) => `<div style="margin:3px 0">${x.stale ? '🕒' : (x.kind && x.kind.indexOf('_out') >= 0 ? '⚠️' : '•')} ${esc(x.text)}${x.source ? ` <span class="tiny muted">— ${esc(x.source)}${x.retrieved_at ? `, ${esc(x.retrieved_at.replace('T', ' ').replace('Z', ''))} UTC` : ''}${x.stale ? ' (stale)' : ''}</span>` : ''}</div>`).join('');
      parts.push(`<div class="card compact"><div class="row"><div class="grow b">${icon('search', 'sm')} Live research &amp; context</div><span class="chip ${cqc}">research quality ${esc(cx.quality || 'N/A')}</span></div>
        <div class="small" style="margin-top:6px"><b>Base probability</b> (statistical model) O2.5 ${pct(b25)} · BTTS ${pct(cx.base ? cx.base.BTTS : null)} → <b>live context: ${ppTxt}</b> → <b>final O2.5 ${pct(f25)}</b></div>
        <table class="tbl" style="margin-top:6px">${rows}</table>
        <div class="tiny muted" style="margin-top:6px">${esc((cx.quality_reasons || []).join(' · '))}${cx.updated ? ` · updated ${esc(cx.updated.replace('T', ' ').replace('Z', ''))} UTC` : ''} · ${cx.n_facts || 0} fact(s)${(cx.conflicts || []).length ? ` · ⚠️ ${(cx.conflicts || []).length} conflicting source(s), no adjustment` : ''}</div>
        ${(cx.conflicts || []).length ? `<div class="tiny" style="margin-top:4px">${(cx.conflicts || []).map((c) => `⚠️ ${esc(c.subject)}: ${esc(c.source_a)} vs ${esc(c.source_b)} — ${esc(c.resolution)}; impact: ${esc(c.impact)}`).join('<br>')}</div>` : ''}
        <div class="small" style="margin-top:6px"><b>Facts &amp; sources</b>${facts || '<div class="tiny muted">No facts recorded for this match.</div>'}</div>
        <div class="tiny muted" style="margin-top:6px">Researched free sources only: the fixture feed (confirmed line-ups), reputable news (reported, never a first-party confirmation), Open-Meteo weather for severe conditions, and our own results archive for scheduling. Missing information is shown as N/A. Bookmaker odds are never an input here.</div></div>`);
    }
    // 1. data quality
    const qcls = q.overall === 'High' ? 'ok' : q.overall === 'Low' ? 'warn' : '';
    parts.push(`<div class="card compact"><div class="row"><div class="grow b">${icon('shield', 'sm')} Data quality</div><span class="chip ${qcls}">${esc(q.overall)} · ${q.score}</span></div>
      <table class="tbl" style="margin-top:6px">${Object.entries(q.components || {}).map(([k, v]) => `<tr><td class="nowrap" style="text-transform:capitalize">${esc(k)}</td><td class="right"><b>${Math.round(v.score * 100)}%</b></td><td class="tiny muted">${esc(v.reason)}</td></tr>`).join('')}</table>
      <div class="tiny muted" style="margin-top:6px">${q.missing_fields && q.missing_fields.length ? `Missing: ${esc(q.missing_fields.join(', '))}. ` : ''}Sources: ${esc((q.sources || []).join('; '))}. Collected ${esc(q.collected || '')}. ${esc(q.note || '')}</div></div>`);
    // 2. warnings
    const ws = f.warnings || [];
    parts.push(`<div class="card compact"><div class="b">${icon('alert', 'sm')} Checks &amp; warnings</div><div class="small" style="margin-top:4px">${ws.length ? ws.map((w) => `<div style="margin:3px 0">${w.level === 'warn' ? '⚠️' : 'ℹ️'} ${esc(w.text)}</div>`).join('') : '<span class="muted">No warnings — the model and the raw data agree, samples are adequate.</span>'}</div></div>`);
    // 3. model explanation
    if (ex) {
      const lg = ex.league || {}, lh = ex.lambda_home || {}, la = ex.lambda_away || {};
      const rt = (r) => r ? `raw ${na(r.att_raw, f2)} / ${na(r.def_raw, f2)} → venue blend ${na(r.att_blend, f2)} / ${na(r.def_blend, f2)} (venue weight ${na(r.venue_share, pct)}) → <b>after shrinkage ${na(r.att, f2)} / ${na(r.def, f2)}</b>, weighted matches ${na(r.n_eff, f1)}${r.opp_att_faced != null ? `<div class="tiny muted">opponents faced: attack ${f2(r.opp_att_faced)} / defence ${f2(r.opp_def_faced)} (info only; opponent-adjusted raw ${na(r.att_opp_adj, f2)} / ${na(r.def_opp_adj, f2)})</div>` : ''}` : 'N/A';
      parts.push(`<div class="card compact"><div class="b">${icon('trend', 'sm')} Why ${f1(f.xg.total)} goals? — the model's own numbers</div>
        <div class="small" style="margin-top:6px"><div><b>League baseline</b> (${esc([f.country, f.league].filter(Boolean).join(' · ') || lg.div || f.div)}${lg.n_eff ? `, ${Math.round(lg.n_eff)} weighted league matches` : ''}): ${na(lg.mu_home, f2)} home + ${na(lg.mu_away, f2)} away goals per match · O2.5 in ${na(lg.o25_rate, pct)}, BTTS in ${na(lg.btts_rate, pct)} of league matches</div>
        <div style="margin-top:6px"><b>${esc(f.home)}</b> attack / defence (1.00 = league average): ${rt(ex.home)}</div>
        <div style="margin-top:6px"><b>${esc(f.away)}</b> attack / defence: ${rt(ex.away)}</div>
        <div style="margin-top:8px" class="b">Model xG ${esc(f.home)} ${na(lh.value, f2)} = ${(lh.terms || []).map(f2).join(' × ')}</div><div class="tiny muted">${esc(lh.formula || '')}</div>
        <div style="margin-top:4px" class="b">Model xG ${esc(f.away)} ${na(la.value, f2)} = ${(la.terms || []).map(f2).join(' × ')}</div><div class="tiny muted">${esc(la.formula || '')}</div>
        <table class="tbl head" style="margin-top:8px"><tr><th>Market</th><th class="right">Model</th><th class="right">Confidence</th></tr>
        <tr><td>Over 1.5 / 2.5 / 3.5</td><td class="right">${pct(f.p.O15)} / ${pct(f.p.O25)} / ${pct(f.p.O35)}</td><td class="right">${esc(conf.O25 || 'N/A')}</td></tr>
        <tr><td>Both teams to score</td><td class="right">${pct(f.p.BTTS)}</td><td class="right">${esc(conf.BTTS || 'N/A')}</td></tr>
        <tr><td>Home / draw / away</td><td class="right">${pct(x12(f, 'H'))} / ${pct(x12(f, 'D'))} / ${pct(x12(f, 'A'))}</td><td class="right">${esc(conf.X12 || 'N/A')}</td></tr></table>
        <details style="margin-top:6px"><summary class="tiny muted">How the number is built (steps)</summary><ol class="tiny muted" style="padding-left:18px;margin:4px 0">${(ex.steps || []).map((t) => `<li>${esc(t.replace(/^\d+\. /, ''))}</li>`).join('')}</ol></details></div></div>`);
    }
    // 4. team samples
    ['home', 'away'].forEach((side) => {
      const e = ev[side]; if (!e) return; const c = e.composition || {}; const sp = e.splits || {}; const rc = e.recent || {};
      const comps = Object.entries(c.competitions || {}).map(([k, v]) => `${esc(k)} ${v}`).join(', ');
      const srow = (name, st) => st ? `<tr><td class="nowrap">${name}<div class="tiny muted">${st.n} · ${esc(st.label)}</div></td><td class="right">${f2(st.gf)} / ${f2(st.ga)}</td><td class="right">${st.o15}/${st.n}</td><td class="right">${st.o25}/${st.n}</td><td class="right">${st.btts}/${st.n}</td><td class="right">${st.cs}/${st.n}</td><td class="right tiny">${st.sot_for == null ? '<span class="muted">N/A</span>' : `${f1(st.sot_for)} / ${f1(st.sot_against)}`}</td><td class="right tiny">${st.corners_for == null ? '<span class="muted">N/A</span>' : `${f1(st.corners_for)} / ${f1(st.corners_against)}`}</td></tr>` : `<tr><td class="nowrap">${name}<div class="tiny muted">0 · No data</div></td><td colspan="7" class="muted tiny">N/A</td></tr>`;
      const ms = expandMatches(e.matches);
      parts.push(`<div class="card compact"><div class="row"><div class="grow b row" style="gap:6px">${fxBadge(f, side)}${teamSpan(f[side], f.country, f.div)}</div>${evChip(c.n)}</div>
        <div class="tiny muted" style="margin-top:4px">Sample: ${esc(c.first_date || '')} → ${esc(c.last_date || '')}, last match ${na(c.days_since_last)} days ago · current season ${c.current_season || 0}, previous ${c.previous_season || 0} · home ${c.home || 0}, away ${c.away || 0} · ${comps}${c.mixed_competitions ? ' · <b>mixed competitions</b>' : ''}${c.friendlies_included ? ` · <b>${c.friendlies_included} friendlies included</b>` : ''}${c.friendlies_excluded ? ` · ${c.friendlies_excluded} friendlies excluded` : ''}<br>Fields present: xG ${c.with_xg || 0}, shots on target ${c.with_shots || 0}, corners ${c.with_corners || 0}, cards ${c.with_cards || 0} of ${c.n || 0} matches</div>
        <div class="small" style="margin-top:6px"><b>Recent form v baseline</b> (historical, informational): last 5 ${rc.last5 ? `${f2(rc.last5.gf)} scored / ${f2(rc.last5.ga)} conceded` : 'N/A'} · last 10 ${rc.last10 ? `${f2(rc.last10.gf)} / ${f2(rc.last10.ga)}` : 'N/A'} · weighted baseline ${na(rc.baseline_gf, f2)} / ${na(rc.baseline_ga, f2)}<br>Recent attack: <b>${esc(rc.attack || 'N/A (fewer than 5 matches)')}</b> · recent defence: <b>${esc(rc.defence || 'N/A')}</b></div>
        <div style="overflow-x:auto;margin-top:6px"><table class="tbl head" style="min-width:100%"><tr><th>Split</th><th class="right">GF / GA</th><th class="right">O1.5</th><th class="right">O2.5</th><th class="right">BTTS</th><th class="right">CS</th><th class="right">SOT f/a</th><th class="right">Corn f/a</th></tr>
        ${srow('All', sp.all)}${srow('Home', sp.home)}${srow('Away', sp.away)}${srow('This season', sp.current)}${srow('Previous', sp.previous)}</table></div>
        <div class="tiny muted">Historical frequencies of the sample (plain counts). The model uses time-weighted, league-normalised versions of these.</div>
        ${(e.outliers || []).length ? `<div class="small" style="margin-top:6px"><b>Extreme results</b> (kept, flagged):${e.outliers.map((o) => `<div>• ${esc(o.date)} ${esc(o.score)} ${o.venue === 'H' ? 'v' : '@'} ${esc(o.opp)}${o.last10_gf_with != null ? ` — last-10 goals for ${f2(o.last10_gf_with)} with / ${f2(o.last10_gf_without)} without` : ''}</div>`).join('')}</div>` : ''}
        <details style="margin-top:6px"><summary class="tiny muted">Matches used (${ms.length}) — raw observations</summary><table class="tbl" style="margin-top:4px">${ms.map((m) => `<tr class="${m.outlier ? 'hl' : ''}"><td class="tiny muted nowrap">${esc(m.date)}</td><td><div class="row" style="gap:6px"><i class="f ${wdl(m.gf, m.ga)}">${wdl(m.gf, m.ga)}</i><span class="nowrap">${m.venue === 'H' ? 'v' : '@'} ${esc(m.opp)}</span></div><div class="tiny muted">${esc(m.league || '')} · ${esc(m.season || '')}${m.friendly ? ' · friendly' : ''}${m.outlier ? ' · extreme' : ''}</div></td><td class="right nowrap"><b>${m.gf} – ${m.ga}</b></td><td class="tiny muted right nowrap">${m.xg_for != null ? `xG ${f2(m.xg_for)}/${f2(m.xg_against)}` : ''}${m.sot_for != null ? `<br>SOT ${m.sot_for}/${m.sot_against}` : ''}${m.corners_for != null ? `<br>corn ${m.corners_for}/${m.corners_against}` : ''}</td></tr>`).join('')}</table></details></div>`);
    });
    // 5. head-to-head strength
    if (h2h) parts.push(`<div class="card compact"><div class="row"><div class="grow b">${icon('history', 'sm')} Head-to-head evidence</div><span class="chip ${h2h.n >= 5 ? '' : 'warn'}">H2H sample: ${h2h.n} · ${esc(h2h.label)}</span></div><div class="tiny muted" style="margin-top:4px">${h2h.n ? `${esc(h2h.first_date)} → ${esc(h2h.last_date)} · avg ${f1(h2h.avg_goals)} goals · O2.5 in ${h2h.o25}/${h2h.n} · BTTS in ${h2h.btts}/${h2h.n} · ` : ''}used by the model: <b>no</b>. ${esc(h2h.note || '')}</div></div>`);
    // 6. market comparison
    if (mk) {
      const x = mk.xg || {}; const xm = mk.x12_market;
      parts.push(`<div class="card compact"><div class="b">${icon('tag', 'sm')} Market comparison (separate layer)</div>
        <table class="tbl head" style="margin-top:6px"><tr><th></th><th class="right">Home</th><th class="right">Away</th><th class="right">Total</th></tr>
        <tr><td>Model xG</td><td class="right"><b>${f2(x.model_home)}</b></td><td class="right"><b>${f2(x.model_away)}</b></td><td class="right"><b>${f2(x.model_total)}</b></td></tr>
        <tr><td>Market xG${x.market_source ? `<div class="tiny muted">${esc(x.market_source)}</div>` : ''}</td><td class="right">${na(x.market_home, f2)}</td><td class="right">${na(x.market_away, f2)}</td><td class="right">${na(x.market_total, f2)}${x.gap_total != null ? `<div class="tiny muted">gap ${x.gap_total >= 0 ? '+' : ''}${f2(x.gap_total)}</div>` : ''}</td></tr>
        ${xm ? `<tr><td>1X2 model</td><td class="right">${pct(x12(f, 'H'))}</td><td class="right">${pct(x12(f, 'A'))}</td><td class="right tiny muted">draw ${pct(x12(f, 'D'))}</td></tr><tr><td>1X2 market implied<div class="tiny muted">${esc(xm.source || '')}</div></td><td class="right">${pct(xm.H)}</td><td class="right">${pct(xm.A)}</td><td class="right tiny muted">draw ${pct(xm.D)}</td></tr>` : ''}</table>
        <div class="tiny muted" style="margin-top:4px">Per-selection model / market / difference / EV: see the Markets tab. The model is never tuned to agree with the bookmaker.</div></div>`);
    }
    parts.push(`<div class="card tiny muted"><b>Traceability:</b> final probability ← Dixon-Coles score matrix ← model xG ← league baseline × shrunk ratings ← time-weighted, league-normalised goals of the matches listed above ← results feeds (football-data.co.uk / Livescore).</div>`);
  }
  function cmpRow(label, a, b, fmt, higherBetter) {
    fmt = fmt || f2; const av = a == null || isNaN(a) ? null : +a, bv = b == null || isNaN(b) ? null : +b;
    if (av == null && bv == null) return '';
    const tot = (av || 0) + (bv || 0); const wa = tot ? (av || 0) / tot : 0.5;
    const cls = (x, y) => (x == null || y == null || x === y) ? '' : ((x > y) === !!higherBetter ? 'lead' : '');
    return `<tr><td class="right ${cls(av, bv)}">${fmt(av)}</td><td class="mid"><div class="k">${label}</div><div class="duo"><span class="l" style="width:${Math.round(wa * 100)}%"></span><span class="r" style="width:${Math.round((1 - wa) * 100)}%"></span></div></td><td class="${cls(bv, av)}">${fmt(bv)}</td></tr>`;
  }
  // "scored in recent matches" row: each side shows its own denominator (season last ≤10) — never a hardcoded /10
  function scRow(label, z1, z2) {
    const den = (z) => Math.min(10, (z.all && z.all.p) || 0);
    const val = (z) => { const d = den(z); return (z.scored_in_last == null || !d) ? null : z.scored_in_last; };
    const av = val(z1), bv = val(z2);
    if (av == null && bv == null) return '';
    const txt = (v, z) => (v == null ? '–' : `${v}/${den(z)}`);
    const tot = (av || 0) + (bv || 0); const wa = tot ? (av || 0) / tot : 0.5;
    const cls = (x, y) => (x == null || y == null || x === y) ? '' : (x > y ? 'lead' : '');
    return `<tr><td class="right ${cls(av, bv)}">${txt(av, z1)}</td><td class="mid"><div class="k">${label}</div><div class="duo"><span class="l" style="width:${Math.round(wa * 100)}%"></span><span class="r" style="width:${Math.round((1 - wa) * 100)}%"></span></div></td><td class="${cls(bv, av)}">${txt(bv, z2)}</td></tr>`;
  }
  function matchStats(parts, f, th, ta) {
    const H = f.teams.home || {}, A = f.teams.away || {};
    const outOf = (n) => (x) => x == null ? '–' : `${x}/${n}`;
    const sq = f.squad || {};
    parts.push(`<div class="card compact"><div class="row"><div class="grow b row" style="gap:6px">${fxBadge(f, 'home')}${esc(f.home)}</div><div class="tiny muted">team samples</div><div class="b row" style="gap:6px">${esc(f.away)}${fxBadge(f, 'away')}</div></div>
      <div class="row small-chips" style="gap:6px;margin-top:4px;flex-wrap:wrap"><span class="tiny muted">${esc(f.home)}:</span>${evChip(H.n || 0)}<span class="grow"></span><span class="tiny muted">${esc(f.away)}:</span>${evChip(A.n || 0)}</div>
      <table class="cmp">${sq.home || sq.away ? cmpRow('Squad value (Transfermarkt)', sq.home && sq.home.value, sq.away && sq.away.value, fmtValue, true) + cmpRow('Average age', sq.home && sq.home.avg_age, sq.away && sq.away.avg_age, f1, false) : ''}${cmpRow('Goals scored / game', H.gf, A.gf, f2, true)}${cmpRow('Goals conceded / game', H.ga, A.ga, f2, false)}
      ${cmpRow('Home / away goals for', H.venue_gf, A.venue_gf, f2, true)}${cmpRow('Home / away goals against', H.venue_ga, A.venue_ga, f2, false)}
      ${cmpRow('Attack strength', H.att, A.att, f2, true)}${cmpRow('Defence (lower = better)', H.def, A.def, f2, false)}
      ${cmpRow('xG for (last ≤10)', H.xg_for, A.xg_for, f2, true)}${cmpRow('xG against (last ≤10)', H.xg_against, A.xg_against, f2, false)}
      ${cmpRow('Shots on target for (last ≤10)', H.sot_for, A.sot_for, f1, true)}${cmpRow('Shots on target against (last ≤10)', H.sot_against, A.sot_against, f1, false)}
      ${cmpRow('Over 1.5 rate', H.o15, A.o15, pct, true)}${cmpRow('Over 2.5 rate', H.o25, A.o25, pct, true)}${cmpRow('Over 3.5 rate', H.o35, A.o35, pct, true)}
      ${cmpRow('Over 2.5 at home / away', H.venue_o25, A.venue_o25, pct, true)}${cmpRow('BTTS at home / away', H.venue_btts, A.venue_btts, pct, true)}
      ${cmpRow('BTTS rate', H.btts, A.btts, pct, true)}${cmpRow('Clean sheets', H.cs, A.cs, pct, true)}${cmpRow('Failed to score', H.fts, A.fts, pct, false)}
      ${cmpRow('Goals / game, last 5', H.form5_goals, A.form5_goals, f2, true)}${cmpRow('Over 1.5 in last matches', H.last_o15, A.last_o15, outOf(H.last_n || 10), true)}${cmpRow('Over 2.5 in last matches', H.last_o25, A.last_o25, outOf(H.last_n || 10), true)}${cmpRow('BTTS in last matches', H.last_btts, A.last_btts, outOf(H.last_n || 10), true)}</table>
      <div class="tiny muted">${H.n || 0} / ${A.n || 0} matches used (time-weighted ${f1(H.n_eff)} / ${f1(A.n_eff)}); ${H.venue_n || 0} home / ${A.venue_n || 0} away games in the venue splits (${evidenceLabel(H.venue_n || 0)} / ${evidenceLabel(A.venue_n || 0)}). Rates are historical frequencies of each sample, not model probabilities; xG and shots on target are N/A where the feed has none. Bars compare the two teams.</div></div>`);
    const t = PR.teamsCached(f.div);
    if (th && ta) {
      const sp = (r) => r.all;
      parts.push(`<div class="card compact"><div class="row"><div class="grow b">This season</div><div class="tiny muted">since ${esc(th.season_from)} · ${sp(th).p || 0} / ${sp(ta).p || 0} matches (${sp(th).evidence || evidenceLabel(sp(th).p)} / ${sp(ta).evidence || evidenceLabel(sp(ta).p)})</div></div>
        <table class="cmp">${cmpRow('League position', posOf(f.div, th), posOf(f.div, ta), (x) => x == null ? '–' : x + ord(x), false)}${cmpRow('Points (played)', sp(th).pts, sp(ta).pts, (x) => x == null ? '–' : x, true)}
        ${cmpRow('Points per game', sp(th).ppg, sp(ta).ppg, f2, true)}${cmpRow('Won', sp(th).w, sp(ta).w, (x) => x, true)}${cmpRow('Drawn', sp(th).d, sp(ta).d, (x) => x, true)}${cmpRow('Lost', sp(th).l, sp(ta).l, (x) => x, false)}
        ${cmpRow('Goals for / game', sp(th).gf_avg, sp(ta).gf_avg, f2, true)}${cmpRow('Goals against / game', sp(th).ga_avg, sp(ta).ga_avg, f2, false)}
        ${cmpRow('Corners for / game', th.avg.corners_for, ta.avg.corners_for, f1, true)}${cmpRow('Corners against / game', th.avg.corners_against, ta.avg.corners_against, f1, false)}
        ${cmpRow('Cards / game', th.avg.cards_for, ta.avg.cards_for, f1, false)}${scRow('Scored in recent matches', th, ta)}</table>
        <div class="tiny muted">Home record ${teamSpan(f.home, f.country, f.div)}: ${th.home.w}W ${th.home.d}D ${th.home.l}L · away record ${teamSpan(f.away, f.country, f.div)}: ${ta.away.w}W ${ta.away.d}D ${ta.away.l}L. Tap a team name for the full page.</div></div>`);
    } else if (t && t.missing) parts.push(`<div class="card tiny muted">Season table not available for this competition yet.</div>`);
    else parts.push(`<div class="card tiny muted">Loading season stats…</div>`);
  }
  const histId = (date, country, home, away) => `${date || ''}|${country || ''}|${home || ''}|${away || ''}`;
  /** Most-recent-meetings trend line: W/D/W + goal-market hits over the last 5 head-to-heads (newest first). */
  function h2hTrend(h2h, home, away) {
    const last = (h2h || []).slice(0, 5);
    if (!last.length) return '';
    const w = (name) => last.filter((m) => (m.home === name && m.hg > m.ag) || (m.away === name && m.ag > m.hg)).length;
    const d = last.filter((m) => m.hg === m.ag).length;
    const o25 = last.filter((m) => m.hg + m.ag >= 3).length;
    const btts = last.filter((m) => m.hg > 0 && m.ag > 0).length;
    return `<div class="tiny" style="margin-top:6px"><b>Last ${last.length} meeting${last.length === 1 ? '' : 's'}:</b> ${esc(home)} ${w(home)}W · Draw ${d} · ${esc(away)} ${w(away)}W · O2.5 ${o25}/${last.length} · BTTS ${btts}/${last.length}</div>`;
  }
  function h2hTable(rows, f) {
    return `<table class="tbl" style="margin-top:6px">${rows.map((m) => `<tr class="tap" data-fx="${esc(histId(m.date, m.country || f.country, m.home, m.away))}"><td class="tiny muted nowrap">${esc(m.date)}</td><td class="${m.hg > m.ag ? 'b' : ''}"><div class="row" style="gap:6px">${badge(m.home, m.home === f.home ? (f.badges || {}).home : m.home === f.away ? (f.badges || {}).away : null, 22)}<span data-team="${esc(m.home)}" data-country="${esc(m.country || f.country)}" data-div="${esc(f.div)}">${esc(m.home)}</span></div></td><td class="right nowrap"><b>${m.hg} – ${m.ag}</b></td><td class="${m.ag > m.hg ? 'b' : ''}"><div class="row" style="gap:6px;justify-content:flex-end"><span data-team="${esc(m.away)}" data-country="${esc(m.country || f.country)}" data-div="${esc(f.div)}">${esc(m.away)}</span>${badge(m.away, m.away === f.home ? (f.badges || {}).home : m.away === f.away ? (f.badges || {}).away : null, 22)}</div></td><td class="tiny muted">${esc(m.league || '')}</td></tr>`).join('')}</table>`;
  }
  function matchH2H(parts, f) {
    const h2h = f.h2h || [];
    const hm = f.h2h_meta;
    // AiScore-style form strips first: last five results of each team (W/D/L, tap-free, colour-coded)
    const th = f.teams.home || {}, ta = f.teams.away || {};
    const strip = (name, list, side) => `<div class="row" style="gap:4px;align-items:center;margin-top:4px"><span class="grow tiny" style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" data-team="${esc(f[side] || name)}" data-country="${esc(f.country)}" data-div="${esc(f.div)}">${esc(name)}</span>${(list || []).slice(0, 5).map((m) => `<span class="fcol"><span class="chip ${m.gf > m.ga ? 'good' : m.gf < m.ga ? 'bad' : ''}" title="${esc((m.venue === 'H' ? 'v ' : '@ ') + m.opp + ' ' + m.gf + '–' + m.ga + (m.opp_s ? ' · ' + m.opp_s + ' opponent' : ''))}">${wdl(m.gf, m.ga)}</span>${m.opp_s ? `<span class="fstr ${m.opp_s}" title="${m.opp_s === 'strong' ? 'Strong opponent' : m.opp_s === 'weak' ? 'Weak opponent' : 'Average opponent'}">${m.opp_s === 'strong' ? '▲' : m.opp_s === 'weak' ? '▼' : '–'}</span>` : ''}</span>`).join('') || '<span class="tiny muted">no recent matches</span>'}</div>`;
    if ((th.last5 || []).length || (ta.last5 || []).length) {
      const anyS = (th.last5 || []).concat(ta.last5 || []).some((m) => m.opp_s);
      parts.push(`<div class="card compact"><div class="b">Recent form</div>${strip(displayName(f, 'home'), th.last5, 'home')}${strip(displayName(f, 'away'), ta.last5, 'away')}${anyS ? `<div class="tiny muted" style="margin-top:6px">▲ strong opponent · – average · ▼ weak opponent — the opponent's level relative to its own league</div>` : ''}</div>`);
    }
    // recent goals: average scored / conceded over the last 5 and 10, with the home/away split (user ask 2026-10-01)
    const avgWin = (ms) => (ms && ms.length) ? { n: ms.length,
      gf: ms.reduce((a, m) => a + (m.gf || 0), 0) / ms.length, ga: ms.reduce((a, m) => a + (m.ga || 0), 0) / ms.length } : null;
    const recAvg = (name) => {
      const rp = rec(f.div, name);
      const ms = (rp && rp.last) || [];
      if (!ms.length) return null;
      const t10 = ms.slice(0, 10);
      return { l5: avgWin(ms.slice(0, 5)), l10: avgWin(t10),
               h: avgWin(t10.filter((m) => m.venue === 'H')), a: avgWin(t10.filter((m) => m.venue === 'A')) };
    };
    const chipsOf = (av) => {
      const c = [];
      if (av.l5) c.push(`<span class="chip">last ${av.l5.n} <b>${f2(av.l5.gf)}</b> / <b>${f2(av.l5.ga)}</b></span>`);
      if (av.l10 && av.l10.n !== (av.l5 && av.l5.n)) c.push(`<span class="chip">last ${av.l10.n} <b>${f2(av.l10.gf)}</b> / <b>${f2(av.l10.ga)}</b></span>`);
      if (av.h) c.push(`<span class="chip">home · ${av.h.n} <b>${f2(av.h.gf)}</b> / <b>${f2(av.h.ga)}</b></span>`);
      if (av.a) c.push(`<span class="chip">away · ${av.a.n} <b>${f2(av.a.gf)}</b> / <b>${f2(av.a.ga)}</b></span>`);
      return c.join('');
    };
    const avH = recAvg(f.home), avA = recAvg(f.away);
    if (avH || avA) {
      const line = (nm, side, av) => av ? `<div class="row" style="gap:6px;flex-wrap:wrap;margin-top:4px">${fxBadge(f, side)}<span class="b" data-team="${esc(f[side] || nm)}" data-country="${esc(f.country)}" data-div="${esc(f.div)}">${esc(nm)}</span>${chipsOf(av)}</div>` : '';
      parts.push(`<div class="card compact"><div class="row"><div class="grow b">Recent goals — averages per match</div><span class="tiny muted">scored / conceded</span></div>
        ${line(displayName(f, 'home'), 'home', avH)}${line(displayName(f, 'away'), 'away', avA)}
        <div class="tiny muted" style="margin-top:6px">From each club's matches on record (up to 10, all competitions); the home/away split is over the last 10. Averages of what happened — not probabilities.</div></div>`);
    }
    if (hm && hm.n) parts.push(`<div class="card compact"><div class="row" style="gap:6px;flex-wrap:wrap"><span class="b">H2H sample</span>${evChip(hm.n)}<span class="chip ${hm.used_by_model ? '' : 'warn'}">${hm.used_by_model ? 'used by the model' : 'context only — not a model input'}</span></div><div class="tiny muted" style="margin-top:4px">${esc(hm.note || '')}${hm.first_date ? ` Meetings ${esc(hm.first_date)} → ${esc(hm.last_date)}` : ''}${(hm.competitions || []).length ? ` · ${esc(hm.competitions.join(', '))}` : ''}. Figures below are historical frequencies of ${hm.n} match${hm.n === 1 ? '' : 'es'}.</div></div>`);
    if (h2h.length) {
      const tot = h2h.map((m) => m.hg + m.ag);
      const wins = (name) => h2h.filter((m) => (m.home === name && m.hg > m.ag) || (m.away === name && m.ag > m.hg)).length;
      const draws = h2h.filter((m) => m.hg === m.ag).length;
      parts.push(`<div class="card compact"><div class="row"><div class="grow b">Head to head · last ${h2h.length}</div><span class="chip">${f1(tot.reduce((a, b) => a + b, 0) / tot.length)} goals avg</span><span class="chip">O2.5 ${tot.filter((t) => t >= 3).length}/${tot.length}</span><span class="chip">BTTS ${h2h.filter((m) => m.hg > 0 && m.ag > 0).length}/${tot.length}</span></div>
        ${h2hTrend(h2h, f.home, f.away)}
        <div class="h2h-bar"><span class="h" style="flex:${wins(f.home) || 0.001}">${wins(f.home)}</span><span class="d" style="flex:${draws || 0.001}">${draws}</span><span class="a" style="flex:${wins(f.away) || 0.001}">${wins(f.away)}</span></div><div class="lbl tiny muted row"><span class="grow">${esc(f.home)} wins</span><span>draws</span><span class="grow right">${esc(f.away)} wins</span></div>
        ${h2hTable(h2h.slice(0, 5), f)}${h2h.length > 5 ? `<details><summary class="tiny muted">Earlier meetings (${h2h.length - 5})</summary>${h2hTable(h2h.slice(5), f)}</details>` : ''}</div>`);
      const venue = h2h.filter((m) => m.home === f.home);
      if (venue.length) parts.push(`<div class="card compact"><div class="row"><div class="grow b">At ${esc(f.home)} · last ${Math.min(5, venue.length)}</div><span class="chip">O2.5 ${venue.slice(0, 5).filter((m) => m.hg + m.ag >= 3).length}/${Math.min(5, venue.length)}</span><span class="chip">BTTS ${venue.slice(0, 5).filter((m) => m.hg > 0 && m.ag > 0).length}/${Math.min(5, venue.length)}</span></div>${h2hTable(venue.slice(0, 5), f)}</div>`);
    } else parts.push(`<div class="card tiny muted">No previous meeting on record between these two teams.</div>`);
    const recent = (p, name, side, list, title) => `<div class="card compact"><div class="b row" style="gap:6px">${fxBadge(f, side)}${esc(name)} <span class="muted" style="font-weight:500">— ${title}</span></div><table class="tbl" style="margin-top:4px">${(list || []).map((m) => `<tr class="tap" data-fx="${esc(histId(m.date, f.country, m.venue === 'H' ? name : m.opp, m.venue === 'H' ? m.opp : name))}"><td class="tiny muted nowrap">${esc(m.date)}</td><td><div class="row" style="gap:6px"><i class="f ${wdl(m.gf, m.ga)}">${wdl(m.gf, m.ga)}</i>${badge(m.opp, null, 22)}<span class="nowrap">${m.venue === 'H' ? 'v' : '@'} ${esc(m.opp)}</span></div></td><td class="right nowrap"><b>${m.gf} – ${m.ga}</b></td><td class="tiny muted">${esc(m.league || '')}</td></tr>`).join('') || '<tr><td class="muted">no matches</td></tr>'}</table></div>`;
    const H = f.teams.home || {}, A = f.teams.away || {};
    parts.push(recent(H, displayName(f, 'home'), 'home', H.last5, 'last 5'));
    parts.push(recent(H, displayName(f, 'home'), 'home', H.venue_last5, 'last 5 at home'));
    parts.push(recent(A, displayName(f, 'away'), 'away', A.last5, 'last 5'));
    parts.push(recent(A, displayName(f, 'away'), 'away', A.venue_last5, 'last 5 away'));
  }

  // ------------------------------------------------------------------ FORM TAB
  function matchForm(parts, f) {
    const tp = teamsCached(f.div) || {};
    const rec = (side) => ((tp.teams || {})[side === 'home' ? f.home : f.away]) || null;
    const rowsOf = (ms) => (ms || []).map((m) =>
      `<tr><td class="tiny muted nowrap">${esc(m.date)}</td><td><div class="row" style="gap:6px"><i class="f ${wdl(m.gf, m.ga)}">${wdl(m.gf, m.ga)}</i>${badge(m.opp, null, 22)}<span class="nowrap">${m.venue === 'H' ? 'v' : '@'} ${esc(m.opp)}</span></div></td><td class="right nowrap"><b>${m.gf} – ${m.ga}</b></td><td class="tiny muted nowrap">${esc(m.league || '')}</td></tr>`).join('');
    const block = (side, name, r) => {
      const last = (r && r.last) || [];
      const venue = side === 'home' ? 'H' : 'A';
      const ven = last.filter((m) => m.venue === venue).slice(0, 5);
      const t10 = (r && r.trends && r.trends.last10) || null;
      const t5 = (r && r.trends && r.trends.last5) || null;
      const chips = [];
      if (t10) chips.push(`<span class="chip">last ${t10.n}: ${t10.pts} pts · ${t10.gf_avg} gf / ${t10.ga_avg} ga</span>`);
      if (t10) chips.push(`<span class="chip">O1.5 ${pct(t10.o15)} · O2.5 ${pct(t10.o25)}</span>`);
      if (t5) chips.push(`<span class="chip">last ${t5.n}: ${t5.pts} pts</span>`);
      return `<div class="card compact"><div class="row" style="gap:6px;flex-wrap:wrap"><div class="grow b row" style="gap:6px">${fxBadge(f, side)}${esc(name)}</div>${chips.join('')}</div>
        ${last.length ? `<table class="tbl" style="margin-top:4px"><tr><th>Date</th><th>Match (all comps.)</th><th class="right">Score</th><th>Competition</th></tr>${rowsOf(last)}</table>` : `<div class="tiny muted" style="margin-top:6px">N/A — not enough recent matches to show form.</div>`}
        ${ven.length ? `<div class="b tiny" style="margin-top:8px">Last ${ven.length} ${side === 'home' ? 'at home' : 'away'}</div><table class="tbl" style="margin-top:2px">${rowsOf(ven)}</table>` : ''}</div>`;
    };
    parts.push(`<div class="card tiny muted">Recent results of both clubs (all competitions, most recent first). Points and rates are historical frequencies, not model inputs — the model's own numbers live on the Overview.</div>`);
    parts.push(block('home', displayName(f, 'home'), rec('home')));
    parts.push(block('away', displayName(f, 'away'), rec('away')));
  }

  // ------------------------------------------------------------------ TABLE TAB
  function matchTable(parts, f, th, ta) {
    const tp = teamsCached(f.div);
    const tbl = PR.realTable(tp && tp.table);
    if (!tbl || !tbl.length) {
      parts.push(`<div class="card empty">No standings for this competition${(f.competition || '').toLowerCase().includes('cup') || (f.league || '').toLowerCase().includes('cup') ? ' (knockout format — a bracket is not a table)' : ''}.</div>`);
      return;
    }
    const hl = (name) => name === f.home || name === f.away;
    parts.push(`<div class="card compact"><div class="row" style="gap:6px;flex-wrap:wrap"><div class="grow b">${icon('chart', 'sm')} ${esc(f.competition || f.league || 'Standings')}</div><span class="tiny muted">${tp.season_from ? 'season from ' + esc(tp.season_from) : ''} · ${tbl.length} teams</span></div>
      <div class="tbl-wrap"><table class="tbl table head" style="margin-top:4px;min-width:540px"><tr><th>#</th><th>Team</th><th class="right">P</th><th class="right">W-D-L</th><th class="right">GF</th><th class="right">GA</th><th class="right">GD</th><th class="right">Pts</th><th class="right">Form</th></tr>
      ${tbl.map((r) => `<tr class="${hl(r.team) ? 'hl' : ''}"><td class="muted">${r.pos}</td><td><div class="tname">${badge(r.team, null, 20)}<span class="nm" data-team="${esc(r.team)}" data-country="${esc(f.country)}" data-div="${esc(f.div)}">${esc(r.team)}${r.team === f.home ? ' <span class="tiny">H</span>' : r.team === f.away ? ' <span class="tiny">A</span>' : ''}</span></div></td><td class="right">${r.p}</td><td class="right">${r.w}-${r.d}-${r.l}</td><td class="right">${r.gf}</td><td class="right">${r.ga}</td><td class="right">${r.gd > 0 ? '+' : ''}${r.gd}</td><td class="right b">${r.pts}</td><td class="right">${r.form ? formBadges(r.form.split('')) : '<span class="tiny muted">–</span>'}</td></tr>`).join('')}</table></div></div>`);
    // home / away record of the two clubs
    const rec = (side) => ((tp.teams || {})[side === 'home' ? f.home : f.away]) || null;
    const half = (side, name, r) => {
      if (!r) return '';
      const s = side === 'home' ? r.home : r.away;
      if (!s || !s.p) return '';
      return `<div class="card compact"><div class="b row" style="gap:6px">${fxBadge(f, side)}${esc(name)} <span class="muted" style="font-weight:500">— ${side === 'home' ? 'home' : 'away'} record</span></div>
        <div class="grid4" style="margin-top:6px"><div class="cell"><div class="k">P</div><div class="v">${s.p}</div></div><div class="cell"><div class="k">W-D-L</div><div class="v">${s.w}-${s.d}-${s.l}</div></div><div class="cell"><div class="k">GF / GA</div><div class="v">${s.gf} / ${s.ga}</div></div><div class="cell"><div class="k">O2.5</div><div class="v">${pct(s.o25)}</div></div></div></div>`;
    };
    parts.push(half('home', displayName(f, 'home'), rec('home')));
    parts.push(half('away', displayName(f, 'away'), rec('away')));
  }

  // ------------------------------------------------------------------ NEWS TAB
  PR.wireNewsLinks = function () {
    setTimeout(() => {
      $$('[data-newslink]').forEach((el) => { if (el.dataset.wired) return; el.dataset.wired = '1'; el.onclick = () => {
        const u = el.dataset.newslink; if (!u) return;
        // in-app reader first (the article is downloaded and saved on the phone); original site stays one tap away
        PR.push({ type: 'reader', link: u, title: el.dataset.nt || '', source: el.dataset.ns || '', when: el.dataset.nw || '' });
      }; });
    }, 0);
  };
  // reputable outlets only (mirrors the capture-time allow-list in news.py)
  const NEWS_OK = ['bbc', 'guardian', 'sky sports', 'espn', 'goal', 'the athletic', 'reuters', 'associated press',
    'telegraph', 'daily mail', 'mirror', 'independent', 'talksport', 'marca', 'kicker', 'sportschau',
    'gazzetta', 'tuttosport', 'corriere dello sport', 'football italia', 'transfermarkt',
    'supersport', 'kick off', 'sport24', 'news24', 'timeslive', 'iol', 'cbs sports', 'fox sports',
    'nbc sports', 'sporting news', 'premier league', 'laliga', 'bundesliga', 'léquipe', 'lequipe'];
  function newsOk(it) {
    const src = String((it && it.source) || '').trim().toLowerCase();
    if (!src) return false;
    return NEWS_OK.some((n) => src === n || src.startsWith(n + ' ') || src.startsWith(n + '-') || src.startsWith(n + ':'));
  }
  PR.newsOk = newsOk;
  function newsItem(it) {
    if (!newsOk(it)) return '';                 // reputable sources only
    const when = it.when ? esc(String(it.when).replace('T', ' ').slice(0, 16)) : '';
    const b = { '24h': 'chip good', '3d': 'chip', '7d': 'chip warn' }[it.bucket] || 'chip';
    return `<div class="news-item tap" data-newslink="${esc(it.link || '')}" data-nt="${esc(it.title || '')}" data-ns="${esc(it.source || '')}" data-nw="${when}"><div class="row" style="gap:6px;align-items:flex-start"><div class="grow"><div class="b" style="font-size:13px">${esc(it.title || '(untitled)')}</div><div class="tiny muted" style="margin-top:2px">${esc(it.source || '')}${when ? ' · ' + when : ''} ${b ? `<span class="${b}" style="margin-left:4px">${it.bucket === '24h' ? '24 h' : it.bucket === '3d' ? '3 d' : '7 d'}</span>` : ''}</div></div></div></div>`;
  }
  PR.newsItem = newsItem;
  function matchNews(parts, f, x) {
    const raw = x.news || {};
    const news = { match: (raw.match || []).filter(newsOk), home: (raw.home || []).filter(newsOk), away: (raw.away || []).filter(newsOk) };
    const sec = (title, items) => (items && items.length ? `<div class="card compact"><div class="b" style="margin-bottom:4px">${title}</div>${items.map(newsItem).join('')}</div>` : '');
    const total = news.match.length + news.home.length + news.away.length;
    if (!total) {
      parts.push(`<div class="card empty">No recent headlines from reputable outlets for this match or either club yet. Only established sources (BBC, Sky Sports, official sites …) are shown; news refreshes at most every 6 hours with each scan.</div>`);
    } else {
      parts.push(`<div class="card tiny muted">Reputable outlets only — tap a headline to read the article inside Mr 2 Odds (downloaded and saved on your phone; “Open original” is one tap away). News is never used by the prediction model.</div>`);
      parts.push(sec(`${icon('sparkle', 'sm')} This match`, news.match));
      parts.push(sec(`${icon('ball', 'sm')} ${esc(f.home)}`, news.home));
      parts.push(sec(`${icon('ball', 'sm')} ${esc(f.away)}`, news.away));
    }
    PR.wireNewsLinks();
  }

  // ------------------------------------------------------------------ team TREND tab
  function teamTrends(parts, r) {
    const t = r.trends;
    if (!t || (!t.last5 && !t.last10 && !t.season)) {
      parts.push(`<div class="card empty">Not enough finished matches yet to compute trend windows (minimum 3 per window).</div>`);
      return;
    }
    const W = [['last5', 'L5'], ['last10', 'L10'], ['last20', 'L20'], ['season', 'Season'], ['previous_season', 'Prev. season']];
    const pctf = (v) => (v == null ? 'N/A' : Math.round(v * 100) + '%');
    const num2 = (v) => (v == null ? 'N/A' : String(Math.round(v * 100) / 100));
    const inN = (w, k) => (w && w.n ? `${w[k]}/${w.n}` : 'N/A');
    const M = [
      ['pts', 'Points', (w) => (w ? w.pts : null)], ['ppg', 'Pts / game', (w) => (w ? w.ppg : null), num2],
      ['gf_avg', 'Goals for / game', (w) => (w ? w.gf_avg : null), num2], ['ga_avg', 'Goals against / game', (w) => (w ? w.ga_avg : null), num2],
      ['o15', 'Over 1.5 goals', (w) => (w ? w.o15 : null), pctf], ['o25', 'Over 2.5 goals', (w) => (w ? w.o25 : null), pctf], ['o35', 'Over 3.5 goals', (w) => (w ? w.o35 : null), pctf],
      ['btts', 'Both teams scored', (w) => (w ? w.btts : null), pctf], ['cs', 'Clean sheets', (w) => (w ? w.cs : null), pctf], ['fts', 'Failed to score', (w) => (w ? w.fts : null), pctf],
      ['win', 'Win rate', (w) => (w ? w.win : null), pctf],
      ['scored_in_n', 'Scored in', (w) => (w ? `${w.scored_in_n}/${w.n}` : null)], ['conceded_in_n', 'Conceded in', (w) => (w ? `${w.conceded_in_n}/${w.n}` : null)],
    ];
    const rows = M.map(([k, label, get, fmt]) => {
      const cells = W.map(([wk, wl]) => {
        const w = t[wk]; const v = get(w);
        return `<div class="cell"><span class="cl">${wl}${w ? ` · ${w.n}` : ''}</span><b>${v == null ? 'N/A' : (fmt ? fmt(v) : v)}</b></div>`;
      }).join('');
      return `<div class="trend-metric"><div class="k">${label}</div><div class="v">${cells}</div></div>`;
    }).join('');
    parts.push(`<div class="card tiny muted">Trend windows for ${esc(pageName(r))}, computed only from published results. A window needs at least 3 finished matches — thinner windows show N/A, never a guess. “Prev. season” is the part of the archive before the current season start; it is N/A when the archive does not reach back that far. These are historical frequencies, not model probabilities.</div>`);
    parts.push(`<div class="card compact"><div class="b" style="margin-bottom:2px">Trend windows</div><div class="tiny muted" style="margin-bottom:4px">n = matches in window · swipe sideways for all windows</div><div class="tbl-wrap"><div class="trend-grid">${rows}</div></div></div>`);
  }
  function pageName(r) { return r && r.name ? r.name : 'this team'; }

  // ------------------------------------------------------------------ TEAM PAGE
  PR.pages.team = function (page) {
    ensureTeams(page.div);
    // a league without a published team index (knockout cups etc.) — or a missing / wrong division file:
    // resolve the team's division from the global team search index so the profile still opens
    if (!page.div || (PR.teamsCached(page.div) || {}).missing) {
      const cur = PR.teamsCached(page.div);
      if (!cur || cur.missing) {
        const idx = state.teamIdx;
        const hit = idx && (idx.teams || []).find((x) => x.n === page.name && (!page.country || x.c === page.country));
        if (hit && hit.d) { page.div = hit.d; ensureTeams(page.div); }
        else if (!idx && !page._idxTried && !state.teamIdxLoading) {
          page._idxTried = true; state.teamIdxLoading = true;
          PR.loadTeamIndex().then(() => PR.render()).catch(() => PR.render());
        }
      }
    }
    const t = PR.teamsCached(page.div); const v = state.teamView || 'overview';
    const parts = [head(esc(page.name), esc(page.country))];
    if (!t) { parts.push(skeleton(6)); view().innerHTML = parts.join(''); wireBack(); return; }
    const r = t.teams && t.teams[page.name];
    if (!r) { parts.push(`<div class="card empty">No season data for ${esc(page.name)} yet.</div>`); view().innerHTML = parts.join(''); wireBack(); return; }
    const a = r.all;
    parts.push(`<div class="card"><div class="thead">${badge(page.name, null, 56)}<div class="grow"><div class="h1">${esc(page.name)}</div><div class="small muted">${flag(page.country)} ${esc(t.league)} · ${posOf(page.div, r) ? `${posOf(page.div, r)}${ord(posOf(page.div, r))} of ${r.teams_in_league}` : ''} · ${a.pts} pts from ${a.p}</div>${r.squad && r.squad.value ? `<div class="value-tag">💶 Squad value ${fmtValue(r.squad.value)} · avg age ${f1(r.squad.avg_age)} · ${r.squad.size} players</div>` : ''}<div style="margin-top:4px">${formBadges(r.form.split(''))}</div></div></div>
      <div class="grid4" style="margin-top:8px"><div class="cell"><div class="k">Record</div><div class="v">${a.w}-${a.d}-${a.l}</div><div class="tiny muted">W-D-L</div></div><div class="cell"><div class="k">Goals</div><div class="v">${a.gf} : ${a.ga}</div><div class="tiny muted">${f2(a.gf_avg)} / ${f2(a.ga_avg)} per game</div></div><div class="cell"><div class="k">Points / game</div><div class="v">${f2(a.ppg)}</div><div class="tiny muted">streak ${esc(r.streak || '–')}</div></div><div class="cell"><div class="k">Over 2.5</div><div class="v">${pct(a.o25)}</div><div class="tiny muted">BTTS ${pct(a.btts)}</div></div></div></div>`);
    const tbl = PR.realTable(t.table);      // a cup / friendly pool publishes no table (a bracket is not a table)
    const tv = (v === 'table' && !tbl) ? 'overview' : v;
    parts.push(`<div class="card compact">${segmented([['overview', 'Overview'], ['trends', 'Trends'], ['matches', 'Matches'], ...(tbl ? [['table', 'Table']] : [])], tv, 'tv')}</div>`);
    if (tv === 'trends') teamTrends(parts, r);
    else if (tv === 'overview') {
      const row = (label, k, fmt) => `<tr><td>${label}</td><td class="right">${(fmt || pct)(r.all[k])}</td><td class="right">${(fmt || pct)(r.home[k])}</td><td class="right">${(fmt || pct)(r.away[k])}</td></tr>`;
      parts.push(`<div class="card compact"><div class="b">Season splits</div><table class="tbl head" style="margin-top:4px"><tr><th></th><th class="right">All</th><th class="right">Home</th><th class="right">Away</th></tr>
        <tr><td>Played</td><td class="right">${r.all.p}</td><td class="right">${r.home.p}</td><td class="right">${r.away.p}</td></tr>
        <tr><td>W-D-L</td><td class="right">${r.all.w}-${r.all.d}-${r.all.l}</td><td class="right">${r.home.w}-${r.home.d}-${r.home.l}</td><td class="right">${r.away.w}-${r.away.d}-${r.away.l}</td></tr>
        ${row('Points / game', 'ppg', f2)}${row('Goals for / game', 'gf_avg', f2)}${row('Goals against / game', 'ga_avg', f2)}${row('Win rate', 'win')}
        ${row('Over 1.5 goals', 'o15')}${row('Over 2.5 goals', 'o25')}${row('Over 3.5 goals', 'o35')}${row('Both teams scored', 'btts')}${row('Clean sheets', 'cs')}${row('Failed to score', 'fts')}</table></div>`);
      const av = r.avg;
      const scN = Math.min(10, a.p || 0); // scored/conceded_in_last count the season's last ≤10 matches
      const sFmt = (v) => (scN && v != null) ? `${v}/${scN}` : 'N/A';
      const sSub = scN ? `last ${scN} match${scN === 1 ? '' : 'es'}` : 'no matches yet';
      const advBits = [];
      if (r.avg_n) {
        if (r.avg_n.xg) advBits.push(`xG in ${r.avg_n.xg}`);
        if (r.avg_n.sot) advBits.push(`shots on target in ${r.avg_n.sot}`);
        if (r.avg_n.corners) advBits.push(`corners in ${r.avg_n.corners}`);
        if (r.avg_n.cards) advBits.push(`cards in ${r.avg_n.cards}`);
      }
      const advNote = advBits.length ? ` · ${advBits.join(', ')} of them (missing = N/A)` : (r.avg_n ? ' · xG, shots on target, corners and cards are not published for this competition' : '');
      parts.push(`<div class="card compact"><div class="b">Averages per game</div><div class="grid4" style="margin-top:6px">
        ${av.xg_for != null ? `<div class="cell"><div class="k">xG for / against</div><div class="v">${f2(av.xg_for)} / ${f2(av.xg_against)}</div></div>` : ''}
        ${av.sot_for != null ? `<div class="cell"><div class="k">Shots on target</div><div class="v">${f1(av.sot_for)} / ${f1(av.sot_against)}</div><div class="tiny muted">for / against</div></div>` : ''}
        ${av.corners_for != null ? `<div class="cell"><div class="k">Corners</div><div class="v">${f1(av.corners_for)} / ${f1(av.corners_against)}</div><div class="tiny muted">for / against</div></div>` : ''}
        ${av.cards_for != null ? `<div class="cell"><div class="k">Cards</div><div class="v">${f1(av.cards_for)} / ${f1(av.cards_against)}</div><div class="tiny muted">for / against</div></div>` : ''}
        <div class="cell"><div class="k">Goals for / game</div><div class="v">${f2(a.gf_avg)}</div><div class="tiny muted">${a.gf} in ${a.p} games</div></div><div class="cell"><div class="k">Goals against / game</div><div class="v">${f2(a.ga_avg)}</div><div class="tiny muted">${a.ga} in ${a.p} games</div></div>
        <div class="cell"><div class="k">Scored in</div><div class="v">${sFmt(r.scored_in_last)}</div><div class="tiny muted">${sSub}</div></div><div class="cell"><div class="k">Conceded in</div><div class="v">${sFmt(r.conceded_in_last)}</div><div class="tiny muted">${sSub}</div></div></div>
        <div class="tiny muted" style="margin-top:4px">Season since ${esc(r.season_from)} · sample ${a.p || 0} match${a.p === 1 ? '' : 'es'} (${a.evidence || evidenceLabel(a.p)}; home ${r.home.p || 0}, away ${r.away.p || 0}) · historical frequencies, not model probabilities${advNote} · league average ${f2(t.avg_goals)} goals, O2.5 ${pct(t.o25_rate)}, BTTS ${pct(t.btts_rate)}.</div></div>`);
      const upcoming = state.data.fixtures.filter((f) => f.country === page.country && (f.home === page.name || f.away === page.name));
      if (upcoming.length) parts.push(`<div class="card compact"><div class="b">In this analysis</div>${upcoming.map((f) => PR.matchLine(f, `<div class="nums"><span class="pill ${f.p.O25 >= 0.6 ? 'hi' : ''}">O2.5 ${pct(f.p.O25)}</span></div>`)).join('')}</div>`);
    } else if (tv === 'matches') {
      parts.push(`<div class="card compact"><div class="b">Last ${r.last.length} matches</div><table class="tbl" style="margin-top:4px">${r.last.map((m) => `<tr class="tap" data-fx="${esc(histId(m.date, page.country, m.venue === 'H' ? page.name : m.opp, m.venue === 'H' ? m.opp : page.name))}"><td class="tiny muted nowrap">${esc(m.date)}</td><td><div class="row" style="gap:6px"><i class="f ${m.r}">${m.r}</i>${badge(m.opp, null, 22)}<a href="#" class="team" data-team="${esc(m.opp)}" data-country="${esc(page.country)}" data-div="${esc(page.div)}">${m.venue === 'H' ? 'v' : '@'} ${esc(m.opp)}</a></div></td><td class="right nowrap"><b>${m.gf} – ${m.ga}</b></td><td class="tiny muted">${esc(m.league || '')}</td></tr>`).join('')}</table></div>`);
    } else if (!tbl) {
      parts.push(`<div class="card empty">No standings for this competition.</div>`);
    } else {
      parts.push(`<div class="card compact"><div class="b">${esc(t.league)} table</div><div class="tiny muted">${t.matches} matches since ${esc(t.season_from)}</div><div class="tbl-wrap"><table class="tbl head table" style="margin-top:4px;min-width:560px"><tr><th>#</th><th>Team</th><th class="right">P</th><th class="right">W</th><th class="right">D</th><th class="right">L</th><th class="right">GF</th><th class="right">GA</th><th class="right">GD</th><th class="right">Pts</th></tr>
        ${tbl.map((x) => `<tr class="${x.team === page.name ? 'hl' : ''}"><td class="muted">${x.pos}</td><td><div class="tname">${badge(x.team, null, 22)}<a href="#" class="team" data-team="${esc(x.team)}" data-country="${esc(page.country)}" data-div="${esc(page.div)}">${esc(x.team)}</a></div></td><td class="right">${x.p}</td><td class="right">${x.w}</td><td class="right">${x.d}</td><td class="right">${x.l}</td><td class="right">${x.gf}</td><td class="right">${x.ga}</td><td class="right">${x.gd > 0 ? '+' : ''}${x.gd}</td><td class="right b">${x.pts}</td></tr>`).join('')}</table></div></div>`);
    }
    view().innerHTML = parts.join('');
    wireBack();
    $$('[data-tv]').forEach((b) => { b.onclick = () => { state.teamView = b.dataset.tv; PR.render(); }; });
  };

  // ------------------------------------------------------------------ DAY PAGE
  PR.pages.day = function (page) {
    const day = state.days[page.date];
    if (!day) {
      if (!state.days[page.date + '_loading']) { state.days[page.date + '_loading'] = true; PR.loadDay(page.date).then(() => PR.render()).catch((e) => { state.days[page.date] = { error: e.message }; PR.render(); }); }
      view().innerHTML = head(esc(dayName(page.date))) + skeleton(8); wireBack(); return;
    }
    if (day.error) { view().innerHTML = head(esc(dayName(page.date))) + `<div class="card empty">Could not load this day (${esc(day.error)}).</div>`; wireBack(); return; }
    const s = day.summary || {}; const v = state.dayView || 'results';
    const parts = [head(esc(dayName(page.date)), `${s.n || 0} matches · ${s.finished || 0} finished${s.goals_avg != null ? ` · ${f1(s.goals_avg)} goals/match` : ''}`)];
    const box = (label, o, k) => { if (!o || !o.n) return `<div class="cell"><div class="k">${label}</div><div class="v muted">–</div><div class="tiny muted">none</div></div>`; const settled = o.n - (o.pending || 0);
      return settled ? `<div class="cell"><div class="k">${label}</div><div class="v ${PR.chipCls(o, k)}">${o[k]}/${settled}</div><div class="tiny muted">${o.pending ? o.pending + ' still open' : 'all settled'}</div></div>` : `<div class="cell"><div class="k">${label}</div><div class="v">${o.n}</div><div class="tiny muted">open · not settled yet</div></div>`; };
    parts.push(`<div class="card"><div class="grid4">${box('⭐ Bets of the day', s.botd, 'hit')}${box(icon('trend', 'sm') + ' High probability', s.safes, 'hit')}${box(icon('star', 'sm') + ' Shortlist', s.picks, 'hit')}</div>
      ${s.finished ? `<div class="tiny muted" style="margin-top:6px">Finished matches: Over 2.5 in ${pct(s.o25_rate)}, BTTS in ${pct(s.btts_rate)}.</div>` : ''}</div>`);
    parts.push(`<div class="card compact">${segmented([['results', 'Results'], ['bets', 'Bets']], v, 'dv')}</div>`);
    const openable = (f) => true;   // live analysis, retained detail file, or the archive record itself
    const tapAttrs = (f) => openable(f) ? `class="tap" data-fx="${esc(f.id)}" ${f.d ? `data-d="${esc(f.d)}"` : ''}` : '';
    if (v === 'results') {
      let lastComp = null;
      const fxs = day.fixtures.slice().sort((a, b) => a.competition.localeCompare(b.competition) || a.kickoff.localeCompare(b.kickoff));
      parts.push('<div class="card compact">');
      fxs.forEach((f) => {
        if (f.competition !== lastComp) { parts.push(`<div class="comp-head">${flag(f.country)} ${esc(f.competition)}</div>`); lastComp = f.competition; }
        const sc = f.score; const fin = sc && sc.hg != null;
        const seenB = new Set();
        const marks = (f.bets || []).filter((b) => { const k = b.sel; if (seenB.has(k)) return false; seenB.add(k); return true; }).map((b) => `<span class="chip ${b.status === 'hit' ? 'good' : b.status === 'miss' ? 'bad' : ''}">${b.botd ? '⭐' : icon(b.kind === 'safe' ? 'trend' : 'star')} ${esc(b.label)}${b.odds ? ' @ ' + f2(b.odds) : ''} ${statusIcon(b.status)}</span>`).join('');
        const stats = fin && sc.hc != null ? `<span class="tiny muted">HT ${sc.hth != null ? `${sc.hth}–${sc.hta}` : '–'} · corners ${sc.hc}–${sc.ac}${sc.hy != null ? ` · 🟨 ${sc.hy}–${sc.ay}` : ''}${sc.hr ? ` · 🟥 ${sc.hr}` : ''}${sc.ar ? `–${sc.ar}` : ''}</span>` : fin && sc.hth != null ? `<span class="tiny muted">HT ${sc.hth}–${sc.hta}</span>` : '';
        const row = matchRow(f, { tap: !!openable(f), short: true, sub: (stats ? stats : '') + (marks ? `<div class="chips">${marks}</div>` : ''), right: fin ? '' : `<span class="tiny muted">xG ${f1(f.xg[0])}–${f1(f.xg[1])}</span><span class="tiny muted">O2.5 ${pct(f.p.O25)}</span>` });
        parts.push(f.d ? row.replace('<div class="mrow', `<div data-d="${esc(f.d)}" class="mrow`) : row);
      });
      parts.push('</div>');
    } else {
      const botd = []; const safeBets = []; const picks = [];
      day.fixtures.forEach((f) => (f.bets || []).forEach((b) => { if (b.botd) botd.push({ f, b }); else if (b.kind === 'safe') safeBets.push({ f, b }); else if (b.kind === 'pick') picks.push({ f, b }); }));
      const table = (lst, showP) => `<div class="card compact"><table class="tbl">${lst.map(({ f, b }) => `<tr ${tapAttrs(f)}><td class="tiny muted nowrap">${esc(koTime(f.kickoff))}</td><td><div class="b">${esc(f.home)} v ${esc(f.away)}</div><div class="tiny muted">${esc(b.label)}${showP ? ` · ${pct(b.p)}` : ''} · ${flag(f.country)} ${esc(f.competition)}</div></td><td class="right nowrap">${f.score && f.score.hg != null ? `<b>${f.score.hg}–${f.score.ag}</b>` : '<span class="muted">–</span>'}</td><td class="right nowrap">${b.odds ? f2(b.odds) + ' ' : ''}${statusIcon(b.status)}</td></tr>`).join('')}</table></div>`;
      if (botd.length) parts.push(`<h2 class="section">⭐ Bets of the day</h2>` + table(botd));
      if (safeBets.length) parts.push(`<h2 class="section">${icon('trend')} High-probability selections</h2>` + table(safeBets));
      if (picks.length) parts.push(`<h2 class="section">${icon('star')} Shortlist picks</h2>` + table(picks, true));
      if (!botd.length && !safeBets.length && !picks.length) parts.push(`<div class="card empty">No bets were recorded for this day.</div>`);
    }
    view().innerHTML = parts.join('');
    wireBack();
    $$('[data-dv]').forEach((b) => { b.onclick = () => { state.dayView = b.dataset.dv; PR.render(); }; });
  };

  // ------------------------------------------------------------------ ANALYSIS (full report)
  PR.pages.analysis = function (page) {
    const d = state.data; const dates = d.history.reports || []; const date = page.date || dates[0] || (d.meta.generated || '').slice(0, 10);
    const key = `${date}|report`;
    if (!state.reports[key]) {
      state.reports[key] = { loading: true };
      PR.getJson(PR.rawUrl(`reports/${date}.md`)).then((j) => { state.reports[key] = j; PR.render(); }).catch(() => { state.reports[key] = { md: '_Analysis unavailable offline — download it once when connected._' }; PR.render(); });
    }
    const rep = state.reports[key];
    const parts = [head('Full analysis', esc(niceDate(date)))];
    if (dates.length > 1) parts.push(`<div class="card compact"><div class="row"><div class="grow tiny muted">Archive</div>${select('an-date', dates.map((r) => [r, r]), date)}</div></div>`);
    parts.push(`<div class="card md">${rep.md ? md(rep.md) : '<div class="empty">Loading analysis…</div>'}</div>`);
    view().innerHTML = parts.join('');
    wireBack();
    const sel = $('#an-date'); if (sel) sel.onchange = (e) => PR.replace({ type: 'analysis', date: e.target.value });
  };

  // ------------------------------------------------------------------ PERFORMANCE
  // ---- deep-dive: the full data-written analysis of one shortlist pick (2026-10-11) ----
  PR.pages.pick = function () {
    const a = state.pickArt;
    const parts = [head('\uD83D\uDCDD Deep analysis', a ? `${a.home} v ${a.away}` : '')];
    if (!a) {
      parts.push('<div class="card empty">Open a pick from the Shortlist to read its full analysis.</div>');
      view().innerHTML = parts.join(''); wireBack(); return;
    }
    const st = a.stats || {};
    const p = (st.p || 0) * 100, b = (st.bar || 0) * 100, m = st.p_mkt != null ? st.p_mkt * 100 : null;
    const chips = (f) => (f || '').split('').map((c) => `<span style="display:inline-block;width:24px;height:24px;line-height:24px;text-align:center;border-radius:6px;font-size:13px;font-weight:700;color:#04121f;margin-right:4px;background:${c === 'W' ? '#22c55e' : c === 'D' ? '#64748b' : '#ef4444'}">${c}</span>`).join('');
    const w = 300;
    const X = (v) => Math.max(0, Math.min(w, Math.round(v / 100 * w)));
    parts.push(`<div class="card mhead"><div class="b" style="font-size:16px">${esc(a.title || '')}</div>
      <div class="row" style="margin-top:10px;justify-content:space-around"><div style="text-align:center"><div class="tiny muted">Model</div><div class="score">${p.toFixed(0)}%</div></div><div style="text-align:center"><div class="tiny muted">Bar</div><div class="score muted">${b.toFixed(0)}%</div></div>${m != null ? `<div style="text-align:center"><div class="tiny muted">Market</div><div class="score muted">${m.toFixed(0)}%</div></div>` : ''}</div>
      <div style="position:relative;height:18px;background:#0b1c30;border:1px solid #1e3a5f;border-radius:9px;margin-top:10px"><div style="position:absolute;top:0;bottom:0;left:0;width:${X(p)}px;background:linear-gradient(90deg,#0e7a4f,#00c86f);border-radius:9px 0 0 9px"></div><div style="position:absolute;top:-3px;bottom:-3px;left:${X(b)}px;width:3px;background:#fbbf24"></div>${m != null ? `<div style="position:absolute;top:-3px;bottom:-3px;left:${X(m)}px;width:3px;background:#e2e8f0"></div>` : ''}</div>
      <div class="tiny muted" style="margin-top:4px">Green = the model \u00b7 <span style="color:#fbbf24">|</span> = the evidence bar the pick must clear${m != null ? ' \u00b7 <span style="color:#e2e8f0">|</span> = the de-vigged market' : ''}</div></div>`);
    parts.push(`<div class="card"><div class="ph-label">Last five \u2014 newest first</div>
      <div class="row" style="justify-content:space-around;margin-top:6px"><div><div class="tiny muted b">${esc(a.home)}</div><div>${chips(a.form && a.form.h)}</div></div>
      <div><div class="tiny muted b">${esc(a.away)}</div><div>${chips(a.form && a.form.a)}</div></div></div></div>`);
    (a.paras || []).forEach((t) => parts.push(`<div class="card compact"><div class="small" style="color:#c9d6e6">${esc(t)}</div></div>`));
    parts.push(`<div class="card tiny muted">Written from the model's own tracked data \u2014 nothing invented; anything missing shows N/A. A pick for your review, never an instruction to bet.</div>`);
    view().innerHTML = parts.join(''); wireBack();
  };
  PR.pages.performance = function () {
    const d = state.data; const sf = (d.safe || {}).summary || {}; const parts = [head('Performance', 'Auto-graded from official results')];
    // reference cards on top: all-time stats, calibration band, market types
    const bAll = (sf.bets || {}).all || {};
    const nAll = bAll.n || 0; const rate = bAll.rate || 0; const exp = bAll.exp_rate || 0;
    parts.push(`<div class="card perf-hero"><div class="ph-label">All time</div>
      <div class="perf-tri"><div><b>${nAll}</b><span>Selections</span></div><div><b>${nAll ? pct(rate) : '–'}</b><span>Hit rate</span></div><div><b>${nAll ? pct(exp) : '–'}</b><span>Avg. model</span></div></div></div>`);
    if (nAll) {
      const dpp = (rate - exp) * 100; const ad = Math.abs(dpp);
      const vcls = ad <= 2 ? 'ok' : ad <= 5 ? 'warn' : 'bad';
      const vtext = ad <= 2 ? 'Excellent calibration' : ad <= 5 ? 'Close to the model' : dpp < 0 ? 'Model running hot' : 'Model running conservative';
      parts.push(`<div class="card" style="margin-top:10px"><div class="ph-label">Calibration</div>
        <div class="calib-row"><span class="muted">Model predicted</span><b>${pct(exp)}</b></div>
        <div class="calib-row"><span class="muted">Actual result</span><b>${pct(rate)}</b></div>
        <div class="calib-bar"><i style="width:${Math.max(2, Math.min(100, rate * 100)).toFixed(1)}%"></i></div>
        <div class="calib-verdict ${vcls}">${vtext} \u00b7 ${dpp >= 0 ? '+' : ''}${f1(dpp)} pp</div></div>`);
    }
    parts.push(`<div class="card" style="margin-top:10px"><div class="ph-label">Market types</div>
      <div class="mkt-types">
        <button class="mkt-type" data-mkt-go="goals">${icon('ball')}<span>O1.5</span></button>
        <button class="mkt-type" data-mkt-go="goals">${icon('trend')}<span>O2.5</span></button>
        <button class="mkt-type" data-mkt-go="top">${icon('shield')}<span>1X2</span></button>
        <button class="mkt-type" data-mkt-go="corners">${icon('corner')}<span>Corners</span></button>
      </div></div>`);
    const row = (name, s, wonKey) => s && s.n ? `<tr><td>${name}</td><td class="right">${s[wonKey || 'won']}/${s.n}</td><td class="right"><b>${pct(s.rate)}</b></td><td class="right muted">${pct(s.exp_rate)}</td><td class="right">${f2(s.avg_odds)}</td><td class="right ${s.roi > 0 ? 'good' : s.roi < 0 ? 'bad' : ''}"><b>${signed(s.roi)}</b></td></tr>` : `<tr><td>${name}</td><td class="right muted">0/0</td><td class="right muted">–</td><td class="right muted">–</td><td class="right muted">–</td><td class="right muted">–</td></tr>`;
    const tbl = (rows) => `<table class="tbl head perf" style="margin-top:6px"><tr><th>Scope</th><th class="right">Won</th><th class="right">Hit</th><th class="right">Exp.</th><th class="right">Odds</th><th class="right">Return</th></tr>${rows}</table>`;
    const bo = sf.botd || {};
    parts.push(`<div class="card"><div class="row"><span class="ico amber">${icon('star')}</span><b>Bets of the day</b></div>${tbl(row('All time', bo.all) + row('Last 30 days', bo['30d']) + Object.values(bo.by_section || {}).map((s) => row(s.title || '', s)).join(''))}<div class="tiny muted">${bo.pending || 0} pending. Up to three picks per section (1X2 · Over 1.5 · Over 2.5 · Corners), overs only.</div></div>`);
    const bg = (sf.bets || {}).by_group || {};
    parts.push(`<div class="card"><div class="row"><span class="ico green">${icon('trend')}</span><b>High-probability selections</b></div>${tbl(row('All time', (sf.bets || {}).all) + row('Last 30 days', (sf.bets || {})['30d']) + Object.entries(bg).map(([g, s]) => row(GROUPS[g] || g, s)).join(''))}<div class="tiny muted">${(sf.bets || {}).pending || 0} pending. "Exp." is the model's own predicted hit rate — if the real rate stays below it for weeks, the model is over-confident. Return = flat-stake profit per unit staked.</div></div>`);
    const t = d.tracker || {};
    parts.push(`<div class="card"><div class="row"><span class="ico">${icon('trend')}</span><b>Goals shortlists</b></div><table class="tbl head" style="margin-top:6px"><tr><th>Market</th><th class="right">Settled</th><th class="right">Hit</th><th class="right">30d</th><th class="right">Pending</th></tr>${['O15', 'O25', 'BTTS'].map((mk) => { const s = t[mk] || {}; return `<tr><td>${MK[mk]}</td><td class="right">${s.settled || 0}</td><td class="right">${pct(s.rate)}</td><td class="right">${pct(s.recent_rate)}</td><td class="right">${s.pending || 0}</td></tr>`; }).join('')}</table>
      <div class="tiny muted">Backtest 2023–26 (52,000 matches): Over 1.5 shortlist 87%, Over 2.5 67%, BTTS 64%.</div></div>`);
    const bench = (d.meta || {}).bench;
    if (bench && bench.rows && bench.rows.length) {
      parts.push(`<div class="card"><div class="row"><span class="ico">${icon('shield', 'sm')}</span><b>Model vs the market</b><span class="tiny muted">${esc(bench.window || '')}</span></div>
        <table class="tbl head perf" style="margin-top:6px"><tr><th>Market</th><th class="right">Model</th><th class="right">Bookmaker</th></tr>${bench.rows.map((r2) => `<tr><td>${esc(r2[0])}</td><td class="right"><b>${Number(r2[1]).toFixed(4)}</b></td><td class="right">${r2[2] == null ? '<span class="muted">-</span>' : Number(r2[2]).toFixed(4)}</td></tr>`).join('')}</table>
        <div class="tiny muted" style="margin-top:6px">Log-loss, lower is better · ${esc(bench.window || '')}${bench.n ? `, n=${Number(bench.n).toLocaleString('en-US')}` : ''} · snapshot ${esc(bench.as_of || '')}. ${esc(bench.note || '')}</div></div>`);
    }
    const bias = (d.meta || {}).bias;
    if (bias && ((bias.fl || []).length || (bias.o25 || []).length)) {
      const bl = (rows) => (rows || []).map((b) => `${b[0]}: <b>${b[3] > 0 ? '+' : ''}${b[3]} pp</b>`).join(' · ');
      parts.push(`<div class="card"><div class="row"><span class="ico amber">${icon('alert', 'sm')}</span><b>Market bias</b><span class="tiny muted">${esc(bias.as_of || '')}</span></div>
        <div class="small" style="margin-top:4px">Longshots priced 5-20% win less than implied — ${bl(bias.fl)}. Over-2.5 bands landing more than implied — ${bl(bias.o25)}.</div>
        <div class="tiny muted" style="margin-top:6px">${esc(bias.note || '')}</div></div>`);
    }
    parts.push(`<div class="note">Everything on this page is graded automatically from final scores. Bookings and corner bets settle from the match statistics feed a few hours after full time. Statistical information, not betting advice.</div>`);
        // ---- shortlist track + live calibration (2026-10-11): the honest picture of the filter ----
    const sl = d.shortlist || {}; const trk = sl.track || {}; const cal = ((sl.rules || {}).calibration) || {};
    const trow2 = (k, n) => { const t = trk[k] || {}; return t.n ? `<tr><td>${n}</td><td class="right">${t.n}</td><td class="right"><b>${pct(t.hit_rate)}</b></td><td class="right muted">${pct(t.expected)}</td><td class="right ${t.roi > 0 ? 'good' : t.roi < 0 ? 'bad' : ''}">${t.roi == null ? '\u2013' : `${t.roi > 0 ? '+' : ''}${f1(100 * t.roi)}%`}</td></tr>` : ''; };
    const trkBody = trow2('primary', 'Shortlist') + trow2('watchlist', 'Watchlist') + trow2('rejected', 'Rejected');
    if (trkBody) parts.push(`<div class="card"><div class="row"><span class="ico green">${icon('target')}</span><b>Shortlist track record</b></div>
      <table class="tbl head" style="margin-top:6px"><tr><th>Class</th><th class="right">Settled</th><th class="right">Actual</th><th class="right">Model said</th><th class="right">Flat ROI</th></tr>${trkBody}</table>
      <div class="tiny muted" style="margin-top:4px">Every shortlist decision is logged before kick-off and settled against the final score \u2014 this table is the filter's report card.</div></div>`);
    const live = Object.entries(cal.groups || {}).filter(([, g]) => g.status === 'live');
    if (live.length) {
      const W = 280, H = 130, X = (v) => (v * W).toFixed(1), Y = (v) => (H - v * H).toFixed(1);
      const g0 = live[0][1], curve = g0.curve || [];
      const pts = curve.map(([x, y]) => `${X(x)},${Y(y)}`).join(' ');
      parts.push(`<div class="card"><div class="row"><span class="ico">${icon('chart')}</span><b>Live calibration</b><span class="tiny muted">${esc(cal.status || '')}</span></div>
        <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-height:${H + 10}px;margin-top:8px;background:#0b1c30;border-radius:10px;border:1px solid #1e3a5f">
          <line x1="0" y1="${H}" x2="${W}" y2="0" stroke="#1e3a5f" stroke-dasharray="4 4"/>
          <polyline points="${pts}" fill="none" stroke="#00c86f" stroke-width="2.5"/>
        </svg>
        <div class="tiny muted" style="margin-top:4px">Green line: what the model's raw probability is worth in reality (${esc(live[0][0])}: settled ${g0.n_holdout} recent picks, Brier ${g0.brier_raw} \u2192 ${g0.brier_cal}). Diagonal = perfect. Applied to the displayed probability where live \u2014 the gates are untouched.</div></div>`);
      const rows = Object.entries(cal.groups || {}).map(([g, gg]) => `<tr><td>${esc(g)}</td><td class="right">${gg.n_train || 0}/${gg.n_holdout || 0}</td><td class="right ${gg.status === 'live' ? 'good' : 'muted'}">${esc(gg.status || '')}</td><td class="right">${gg.brier_raw == null ? '\u2013' : gg.brier_raw}</td><td class="right">${gg.brier_cal == null ? '\u2013' : gg.brier_cal}</td></tr>`).join('');
      parts.push(`<div class="card compact"><table class="tbl head" style="margin-top:2px"><tr><th>Market</th><th class="right">Train/Holdout</th><th class="right">Status</th><th class="right">Brier raw</th><th class="right">Brier cal</th></tr>${rows}</table></div>`);
    } else if (cal.status) {
      parts.push(`<div class="card tiny muted"><b>Calibration map:</b> ${esc(cal.status)}. It goes live only after it beats the raw model on recent, unseen picks \u2014 until then the raw model probability is shown.</div>`);
    }
    const bm = trk.by_market || [];
    if (bm.length) parts.push(`<div class="card compact"><div class="b">Shortlist by market</div><table class="tbl head" style="margin-top:4px"><tr><th>Market</th><th class="right">Settled</th><th class="right">Actual</th><th class="right">Model said</th></tr>${bm.map((r) => `<tr><td>${esc(GROUPS[r[0]] || r[0])}</td><td class="right">${r[1]}</td><td class="right"><b>${pct(r[2])}</b></td><td class="right muted">${pct(r[3])}</td></tr>`).join('')}</table></div>`);
    const bnds = trk.bands || [];
    if (bnds.length) parts.push(`<div class="card compact"><div class="b">Predicted vs actual, by probability band</div><table class="tbl head" style="margin-top:4px"><tr><th>Band</th><th class="right">Settled</th><th class="right">Actual</th><th class="right">Model said</th></tr>${bnds.map((r) => `<tr><td>${r[0].toFixed(2)}\u2013${r[1].toFixed(2)}</td><td class="right">${r[2]}</td><td class="right"><b>${pct(r[3])}</b></td><td class="right muted">${pct(r[4])}</td></tr>`).join('')}</table></div>`);
view().innerHTML = parts.join('');
    wireBack();
    $$('[data-mkt-go]').forEach((b) => { b.onclick = () => { state.betsView = b.dataset.mktGo; PR.setTab('bets'); }; });
  };

  // ------------------------------------------------------------------ PAGE: all markets (today's groups, strongest first)
  PR.pages.marketsboard = function () {
    const d = state.data || {};
    const today = ymd(tzNow());
    const all = (d.fixtures || []).filter((f) => f.date === today && f.p);
    const parts = [head('All markets', "today's groups · strongest first")];
    // the only selection rule that involves odds (2026-10-27): nothing priced below 1.16 is offered at all, because
    // at 1.12-1.15 the bookmaker's hold needs ~89 % to break even (matches are never dropped, only the selection)
    const worth = (s) => !(s.odds && s.odds < 1.16);
    const okP = (s) => s && s.p != null && s.p > 0 && s.p < 1 && worth(s) && !PR.isOutlier(s) && !PR.isDropped(s.sel);   // fantasy gaps are quarantined
    const meta = (f) => `<div class="tiny muted">${flag(f.country)} ${esc(f.league || f.competition || '')} · ${teamSpan(f.home, f.country, f.div)} v ${teamSpan(f.away, f.country, f.div)}</div>`;
    const selRow = (f, s) => `<tr class="tap" data-fx="${esc(f.id)}"><td class="tiny muted nowrap">${esc(koTime(f.kickoff))}</td><td><div class="b">${esc(s.label || selLabel(s.sel, f.home, f.away))}</div>${meta(f)}</td>
      <td class="right tiny">${s.p_sb != null ? pct(s.p_sb) : '<span class="muted">–</span>'}${s.diff_pp != null ? `<div class="${s.diff_pp > 0 ? 'good' : ''}">${s.diff_pp > 0 ? '+' : ''}${f1(s.diff_pp)} pp</div>` : ''}</td>
      <td class="right nowrap">${pill(s.p, 0.8, 0.7)} ${s.odds ? `<span class="tiny muted">${f2(s.odds)}</span>` : ''} ${PR.addBtn ? PR.addBtn(f.id, s.sel, s.odds || null) : ''}</td></tr>`;
    const tableOf = (rows) => `<table class="tbl head" style="margin-top:4px"><tr><th>Kick-off</th><th>Match · selection</th><th class="right">Market</th><th class="right">Model</th></tr>${rows.map((r) => selRow(r.f, r.s)).join('')}</table>`;
    const gather = (test) => all.flatMap((f) => (f.sels || []).filter((s) => okP(s) && test(s)).map((s) => ({ f, s })))
      .sort((a, b) => b.s.p - a.s.p);
    // every group renders every single time — a group with nothing in it stays in place as an empty card
    // (user rule, 2026-10-01), so the page never reshuffles around gaps. Four groups since 2026-10-27: the
    // bookings and BTTS families are gone, so their cards would be empty forever.
    const shell = (title, ico, label, sub, body) =>
      `<div class="card compact" style="margin-top:8px"><div class="row"><span class="ico">${ico}</span><div class="grow b">${title}</div>
        <span class="tiny muted">${body ? label : 'empty · nothing qualifies'}</span></div>
        ${body || `<div class="tiny muted" style="margin-top:6px">No ${title} selection meets the bar for today yet — the group stays in place.</div>`}
        <div class="tiny muted" style="margin-top:4px">${sub}</div></div>`;
    // 1. 1X2 — strongest outcome per match first, all three probabilities in the line
    const x12rows = all.map((f) => {
      const x = f.x12 || [];
      const pr = [[f.home + ' (1)', x[0]], ['Draw (X)', x[1]], [f.away + ' (2)', x[2]]].filter((e) => e[1] != null && e[1] > 0 && e[1] < 1);
      if (!pr.length) return null;
      const top = pr.slice().sort((a, b) => b[1] - a[1])[0];
      return { f, top, pr };
    }).filter(Boolean).sort((a, b) => b.top[1] - a.top[1]);
    const x12Body = x12rows.length ? `<table class="tbl head" style="margin-top:4px"><tr><th>Kick-off</th><th>Match · strongest outcome</th><th class="right">Model</th></tr>
      ${x12rows.map((r) => `<tr class="tap" data-fx="${esc(r.f.id)}"><td class="tiny muted nowrap">${esc(koTime(r.f.kickoff))}</td>
        <td><div class="b">${esc(r.top[0])} <b>${pct(r.top[1])}</b></div><div class="tiny muted">${flag(r.f.country)} ${esc(r.f.league || r.f.competition || '')} · ${r.pr.map((e) => `${esc(e[0].replace(/ \(\d\)$/, ''))} ${pct(e[1])}`).join(' · ')}</div></td>
        <td class="right">${pill(r.top[1], 0.8, 0.7)}</td></tr>`).join('')}</table>` : '';
    let total = x12rows.length;
    parts.push(shell('1X2', '🏆', `${x12rows.length} match${x12rows.length === 1 ? '' : 'es'} · strongest first`,
      'Model 1X2 from the Dixon-Coles score matrix — football data only.', x12Body));
    const add = (title, ico, test, sub) => {
      const rows = gather(test);
      total += rows.length;
      parts.push(shell(title, ico, `${rows.length} pick${rows.length === 1 ? '' : 's'} · high to low`, sub, rows.length ? tableOf(rows) : ''));
    };
    add('Corners', '🚩', (s) => selGroup(s.sel) === 'corners', 'Total corners — modelled for leagues with corner statistics.');
    add('Over 2.5', '⚽', (s) => s.sel === 'O25', 'Total goals 2.5 — over only (starts from a 55% model probability).');
    add('Over 1.5', '⚽', (s) => s.sel === 'O15', 'Total goals 1.5 — over only.');
    if (all.length) {
      parts.splice(1, 0, `<div class="card tiny muted"><b>${all.length} analysed match${all.length === 1 ? '' : 'es'} today</b> · ${total} selections across the groups below · every group sorted by <b>model probability, high → low</b>. Prices set the anchor of the published probability and nothing priced under <b>1.16</b> is offered.</div>`);
    } else {
      parts.push(`<div class="card empty">No analysed matches for today yet — the groups will fill in as the analysis publishes.</div>`);
    }
    const hidden = all.reduce((n, f) => n + (f.sels || []).filter((s) => PR.isOutlier(s)).length, 0);
    if (hidden) parts.push(`<div class="card tiny muted"><b>${hidden}</b> selection${hidden === 1 ? '' : 's'} on this board ${hidden === 1 ? 'is' : 'are'} <b>quarantined</b>: the model rates ${hidden === 1 ? 'it' : 'them'} 15+ points above the price, and a gap that wide is a data fault (a friendly or a cup qualifier the model cannot rate), not value. They are not shown as picks anywhere.</div>`);
    parts.push(`<div class="card tiny muted"><b>How to read this page</b> — each group lists today's selections sorted by <b>model probability (high to low)</b>. Model = the raw football-data probability, Market = de-margined bookmaker implied, and the number shown first is the <b>25 % model / 75 % market blend</b> we publish. A selection priced under <b>1.16</b> is not offered (the match itself stays with its other markets). A high probability is not a certainty.</div>`);
    // self-heal: a phone holding an outdated analysis copy would show only 1X2 (the index carries no
    // selections yet) — fetch the latest analysis once and re-render; the flag stops any loop
    if (!PR._mbRefreshed && (!all.length || !all.some((f) => (f.sels || []).length))) {
      PR._mbRefreshed = true;
      setTimeout(() => PR.loadData(false), 250);
    }
    view().innerHTML = parts.join('');
    wireBack();
  };

  // ------------------------------------------------------------------ PAGE: team search (V2 More hub → Teams)
  // Picks clubs straight out of the 60-day fixture window and hands each row to the
  // existing team page (form · venues · H2H · fixtures). No new data source.
  PR.pages.teams = function () {
    const d = state.data || {}; const q = (state.tmQ || '').trim().toLowerCase();
    const seen = new Map();
    (d.fixtures || []).forEach((f) => {
      if (!f) return;
      [[f.home, f.league || f.competition], [f.away, f.league || f.competition]].forEach(([n, l]) => {
        if (!n) return;
        const k = String(n).toLowerCase();
        if (!seen.has(k)) seen.set(k, { n, c: f.country || '', l: l || '', d: f.div || '' });
      });
    });
    const all = [...seen.values()].sort((a, b) => a.n.localeCompare(b.n));
    const list = q ? all.filter((t) => t.n.toLowerCase().includes(q) || t.l.toLowerCase().includes(q) || t.c.toLowerCase().includes(q)) : all;
    const parts = [head('Teams', `${all.length} clubs in the current fixture window · tap one for form, venues and fixtures`)];
    parts.push(`<div class="searchbar" style="margin-bottom:10px"><div class="field">${icon('search', 'sm')}<input id="tm-search" type="search" placeholder="Search team, league or country" value="${esc(state.tmQ || '')}" autocomplete="off"></div></div>`);
    const show = list.slice(0, 80);
    if (!show.length) parts.push(`<div class="card empty small">No team matches \u201c${esc(state.tmQ)}\u201d.</div>`);
    else parts.push(`<div class="card compact">${show.map((t) => `<div class="lg-row tap" data-tmq="${esc(t.n)}|${esc(t.c)}|${esc(t.d)}"><div class="lg-ic">${badge(t.n, null, 24)}</div><div class="grow"><div class="b">${esc(t.n)}</div><div class="tiny muted">${flag(t.c)} ${esc(t.c)}${t.l ? ' · ' + esc(t.l) : ''}</div></div></div>`).join('')}</div>`);
    if (list.length > show.length) parts.push(`<div class="tiny muted" style="margin-top:8px">Showing first ${show.length} of ${list.length} clubs \u2014 keep typing to narrow it down.</div>`);
    parts.push(`<div class="tiny muted" style="margin:10px 4px 18px">Team pages combine recent form, home/away splits, head-to-head and upcoming fixtures from the same analysis files.</div>`);
    view().innerHTML = parts.join('');
    wireBack();
    const sIn = $('#tm-search'); if (sIn) sIn.oninput = (e) => { state.tmQ = e.target.value; PR.render(); const n = $('#tm-search'); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } };
    $$('[data-tmq]').forEach((el) => el.onclick = () => { const pp = el.dataset.tmq.split('|'); PR.openTeam(pp[0], pp[1], pp.slice(2).join('|')); });
  };

  // ------------------------------------------------------------------ BEST OF THE DAY (☰ dropdown)
  // The day's best bets, sectioned by market. Every pick clears a model bar first (results ≥60%,
  // goals ≥70%, corners ≥65%, priced at 1.16+ — odds never filter); home/away wins are
  // then confirmed against the clubs' own venue/road runs from the detail file. All performance
  // numbers below are presentation only — no model maths lives on this page.
  PR.pages.best = function () {
    const d = state.data || {};
    const today = ymd(tzNow());
    const all = (d.fixtures || []).filter((f) => f.date === today && f.data_ok && f.p);
    const parts = [head('Best of the day', 'the bets to enter today · kick-offs in SAST')];
    const selsOf = (f) => f.sels || [];
    const detOf = (f) => { const x = PR.detailCached(f.id, f.d); return x && !x.error && x.teams ? x : null; };
    const detFailed = (f) => { const k = PR.detailKey(f.id, f.d); const x = k && state.details[k]; return !!(x && x.error); };
    const tally = (list) => {
      const t = { n: 0, w: 0, d: 0, l: 0, gf: 0, ga: 0 };
      (list || []).forEach((m) => { t.n++; t.gf += m.gf || 0; t.ga += m.ga || 0; if (m.gf > m.ga) t.w++; else if (m.gf === m.ga) t.d++; else t.l++; });
      return t;
    };

    // ---- candidates from the published index (model bars applied here)
    const resCand = (code) => all.map((f) => {
      const e = selsOf(f).find((s) => s.sel === code);
      if (!e || e.p == null || e.p < 0.60 || !e.odds || f.q === 'Low') return null;
      return { f, p: e.p, odds: e.odds, ev: e.ev, sel: code };
    }).filter(Boolean).sort((a, b) => b.p - a.p);

    // 2026-10-27: bookings left the policy, so the card carries four blocks — goals, Over 2.5, 1X2, corners.
    const goalCand = []; const coCand = [];
    all.forEach((f) => {
      (f.hi || []).forEach((h) => {
        const [code, p, odds] = h;
        if (p == null || !odds) return;
        const g = selGroup(code);
        if (g === 'goals') {
          const e = selsOf(f).find((s) => s.sel === code);
          goalCand.push({ f, p, odds, ev: e ? e.ev : null, sel: code });
        }
      });
      ['CO'].forEach((pref) => {
        const list = selsOf(f).filter((s) => s.sel.startsWith(pref) && s.p != null && s.p >= 0.65 && s.p < 1 &&
          s.odds && f.q !== 'Low');
        if (!list.length) return;
        const e = list.sort((a, b) => b.p - a.p)[0];
        coCand.push({ f, p: e.p, odds: e.odds, ev: e.ev, sel: e.sel });
      });
    });
    goalCand.sort((a, b) => b.p - a.p); coCand.sort((a, b) => b.p - a.p);
    // goals: strongest few of each family so one market can't flood the card
    const famN = {};
    const goalsShown = goalCand.filter((it) => {
      const fam = it.sel === 'O15' ? 'O15' : 'O25+';
      famN[fam] = (famN[fam] || 0) + 1;
      return famN[fam] <= 3;
    });

    // ---- club-performance confirmation for the result picks (detail file venue/road splits)
    const resultRow = (it) => {
      const det = detOf(it.f);
      if (!det) {
        return { ok: true, why: detFailed(it.f)
          ? '<div class="tiny muted">club form data unavailable — model bar only</div>'
          : '<div class="tiny muted">checking club form…</div>' };
      }
      const H = det.teams.home || {}, A = det.teams.away || {};
      const vt = tally(H.venue_last5);                                  // home club's last games at its venue
      const rt = tally((A.last5 || []).filter((m) => m.venue === 'A')); // away club's last games on the road
      const homeStrong = ((H.venue_n || 0) >= 3 && H.venue_gf != null && H.venue_ga != null)
        ? ((H.venue_gf - H.venue_ga) >= 0.3 || (vt.n >= 3 && vt.w >= 3 && vt.l <= 1))
        : (vt.n >= 3 && ((vt.w >= 3 && vt.l <= 1) || (vt.gf - vt.ga) / vt.n >= 0.3));
      const awayStrong = rt.n >= 3 && ((rt.w >= 3 && rt.l <= 1) || (rt.gf - rt.ga) / rt.n >= 0.3);
      const ok = it.sel === 'H' ? (homeStrong && !awayStrong) : (awayStrong && !homeStrong);
      if (!ok) return { ok: false };
      const homeSeg = vt.n
        ? `${esc(H.name || it.f.home)}: <b>${vt.w}-${vt.d}-${vt.l}</b> at home (last ${vt.n})${H.venue_gf != null ? ` · ${f1(H.venue_gf)}–${f1(H.venue_ga)} avg` : ''}`
        : (H.venue_n ? `${esc(H.name || it.f.home)}: <b>${H.venue_n}</b> home games${H.venue_gf != null ? ` · ${f1(H.venue_gf)}–${f1(H.venue_ga)} avg` : ''}` : '');
      const awaySeg = rt.n
        ? `${esc(A.name || it.f.away)}: <b>${rt.w}-${rt.d}-${rt.l}</b> on the road (last ${rt.n})`
        : `${esc(A.name || it.f.away)}: little road data`;
      const why = it.sel === 'H'
        ? `<div class="tiny" style="margin-top:2px">🏠 ${homeSeg} · ✈ ${awaySeg}</div>`
        : `<div class="tiny" style="margin-top:2px">✈ ${awaySeg} · 🏠 ${homeSeg}</div>`;
      return { ok: true, why };
    };
    const applyResult = (code) => resCand(code).map((it) => ({ it, r: resultRow(it) }))
      .filter((x) => x.r.ok).map((x) => Object.assign({}, x.it, { why: x.r.why }));
    const home = applyResult('H');
    const away = applyResult('A');

    // ---- performance evidence lines for the other markets (shown, never gated)
    const goalRate = (t, sel) => {
      if (!t) return null;
      if (sel === 'O15' && t.last_n) return `O1.5 in ${t.last_o15}/${t.last_n}`;
      if (sel === 'O25' && t.last_n) return `O2.5 in ${t.last_o25}/${t.last_n}`;
      if (sel === 'O35' && t.o35 != null) return `O3.5 in ${pct(t.o35)} of games`;
      if (t.o25 != null) return `O2.5 in ${pct(t.o25)} of games`;
      return null;
    };
    const goalsWhy = (it) => {
      const det = detOf(it.f);
      if (!det) return detFailed(it.f) ? '' : '<div class="tiny muted">loading club stats…</div>';
      const H = det.teams.home || {}, A = det.teams.away || {};
      const g = selGroup(it.sel);
      if (g === 'team') {
        const t = it.sel[0] === 'H' ? H : A;
        const atHome = it.sel[0] === 'H';
        const scored = atHome && t.venue_gf != null ? f1(t.venue_gf) : (t.gf != null ? f1(t.gf) : null);
        return `<div class="tiny" style="margin-top:2px">${esc(t.name || it.f.home)}: <b>${scored != null ? scored : '–'}</b> goals/game${atHome ? ' at home' : ''}${t.form5_goals != null ? ` · last 5: ${f1(t.form5_goals)}/game` : ''}</div>`;
      }
      if (g === 'btts') {
        const hs = H.btts != null ? `${pct(H.btts)}${H.venue_btts != null ? ` (${pct(H.venue_btts)} at home)` : ''}` : null;
        const as = A.btts != null ? pct(A.btts) : null;
        if (!hs && !as) return '';
        return `<div class="tiny" style="margin-top:2px">BTTS rate — ${esc(H.name || it.f.home)}: <b>${hs || '–'}</b> · ${esc(A.name || it.f.away)}: <b>${as || '–'}</b></div>`;
      }
      const hr = goalRate(H, it.sel), ar = goalRate(A, it.sel);
      const venue = it.sel === 'O15' ? H.venue_o15 : it.sel === 'O25' ? H.venue_o25 : null;
      if (!hr && !ar) return '';
      return `<div class="tiny" style="margin-top:2px">${esc(H.name || it.f.home)}: <b>${hr || '–'}</b>${venue != null ? ` · ${pct(venue)} at home` : ''} · ${esc(A.name || it.f.away)}: <b>${ar || '–'}</b></div>`;
    };
    const statsWhy = (it, kind) => {
      const det = detOf(it.f);
      if (!det) return detFailed(it.f) ? '' : '<div class="tiny muted">loading stats…</div>';
      const s = det[kind];
      if (!s || s.total == null) return `<div class="tiny muted">${kind === 'corners' ? 'Corner' : 'Card'} averages are not modelled for this league.</div>`;
      const ref = kind === 'cards' && det.referee ? ` · ref <b>${esc(det.referee)}</b>` : '';
      return `<div class="tiny" style="margin-top:2px">${kind === 'corners' ? 'Avg' : 'Expected'} <b>${f1(s.home)} v ${f1(s.away)}</b> ${kind === 'corners' ? 'corners' : 'cards'} · ${s.n[0]}+${s.n[1]} games (${esc(s.evidence || '')})${s.low_confidence ? ' · thin data' : ''}${ref}</div>`;
    };

    // ---- progressive detail loads (bounded): performance evidence lives in each match's detail file
    const shown = {
      home: state.expanded.bw_h ? home : home.slice(0, 10),
      away: state.expanded.bw_a ? away : away.slice(0, 10),
      goals: state.expanded.bw_goals ? goalCand : goalsShown,
      co: state.expanded.bw_co ? coCand : coCand.slice(0, 8),
    };
    let budget = 18;
    const kick = (f) => {
      if (budget <= 0 || !f.d) return;
      const k = PR.detailKey(f.id, f.d);
      if (!k || state.details[k] || state.details[k + '_loading']) return;
      budget -= 1;
      state.details[k + '_loading'] = true;
      PR.loadDetail(f.id, f.d).then(() => PR.render())
        .catch((e) => { state.details[k] = { error: e.message }; PR.render(); })
        .finally(() => { delete state.details[k + '_loading']; });
    };
    const seenK = new Set();
    Object.keys(shown).forEach((kk) => shown[kk].forEach((it) => { if (!seenK.has(it.f.id)) { seenK.add(it.f.id); kick(it.f); } }));

    // ---- render
    parts.push(`<div class="card small"><b>How these picks are made</b><div class="muted" style="margin-top:4px">Each pick clears its model bar first — home/away wins <b>≥60%</b>, goals <b>≥70%</b> (Over 2.5 from <b>55%</b>), corners <b>≥65%</b> — and a Sportybet price of <b>1.16 or more</b> (bookings, team goals, BTTS, double chance and Over 0.5 left the board in the 2026-10-27 audit). The probability shown is <b>25 % model / 75 % de-vigged market</b>: the market had been out-forecasting the model. Home and away wins are then confirmed against the clubs' own runs: one side's <b>venue form</b> against the other's <b>road form</b> — the kind of streak you'd back yourself. Prices are Sportybet's; the model itself never changes.</div></div>`);
    const secHead = (ico, title, n) => `<div class="section-head"><h2><span class="ico">${icon(ico)}</span>${title}</h2>${n ? `<span class="tiny muted">${n} pick${n === 1 ? '' : 's'}</span>` : ''}</div>`;
    const pickRow = (it) => {
      const f = it.f;
      return `<tr class="tap" data-fx="${esc(f.id)}"><td class="tiny muted nowrap">${esc(koShort(f.kickoff))}</td>
        <td><div class="row" style="gap:6px">${fxBadge(f, 'home').replace('s24', 's20')}${fxBadge(f, 'away').replace('s24', 's20')}<div class="b grow">${teamSpan(f.home, f.country, f.div)} <span class="muted">v</span> ${teamSpan(f.away, f.country, f.div)}</div></div>
          <div class="sel"><b>${esc(selLabel(it.sel, f.home, f.away))}</b></div>
          <div class="tiny muted">${flag(f.country)} ${esc(f.competition)}</div>${it.why || ''}</td>
        <td class="right nowrap"><b>${f2(it.odds)}</b></td>
        <td class="right"><div class="row" style="gap:0;justify-content:flex-end">${pill(it.p, 0.7, 0.6)}${PR.addBtn ? PR.addBtn(f.id, it.sel, it.odds) : ''}</div>${it.ev != null ? `<div class="tiny good" style="text-align:right">edge +${Math.round(it.ev * 100)}%</div>` : ''}</td></tr>`;
    };
    const tbl = (rows, key, capN, kind) => {
      if (!rows.length) return null;
      const max = state.expanded[key] ? rows.length : capN;
      const rowWith = (it) => pickRow(Object.assign({}, it, { why: it.why != null ? it.why
        : kind === 'goals' ? goalsWhy(it)
          : kind === 'co' ? statsWhy(it, 'corners') : '' }));
      return `<div class="card compact"><table class="tbl head">${rows.slice(0, max).map(rowWith).join('')}</table>${rows.length > max
        ? `<button class="btn wide" data-more="${key}">Show all ${rows.length}</button>`
        : (state.expanded[key] ? `<button class="btn wide" data-less="${key}">Show less</button>` : '')}</div>`;
    };
    const section = (ico, title, rows, key, capN, empty, kind) => {
      parts.push(secHead(ico, title, rows.length));
      const t = tbl(rows, key, capN, kind);
      parts.push(t || `<div class="card empty small">${empty}</div>`);
    };
    section('shield', 'Home wins', home, 'bw_h', 10, 'No home-win pick clears 60% with the club runs behind it right now.');
    section('swap', 'Away wins', away, 'bw_a', 10, 'No away-win pick clears 60% with the club runs behind it right now.');
    const goalsRows = state.expanded.bw_goals ? goalCand : goalsShown;
    section('ball', 'Goals · Over 1.5 & Over 2.5', goalsRows, 'bw_goals', 12, 'No goals pick at 70%+ with a price right now.', 'goals');
    section('corner', 'Corners', coCand, 'bw_co', 8, 'No corners pick at 65%+ — corner stats cover the modelled leagues only.', 'co');
    parts.push(`<div class="note">A probability is not a certainty — a 70% pick still loses three times in ten. Statistical information, not betting advice. 18+.</div>`);
    view().innerHTML = parts.join('');
    wireBack();
    $$('[data-more]').forEach((b) => { b.onclick = () => { state.expanded[b.dataset.more] = true; PR.render(); }; });
    $$('[data-less]').forEach((b) => { b.onclick = () => { state.expanded[b.dataset.less] = false; PR.render(); }; });
  };


  // ------------------------------------------------------------------ GUIDE
  PR.pages.guide = function () {
    const parts = [head('Guide', 'Markets, probabilities and how to read Mr 2 Odds')];
    const sec = (ico, title, body) => `<div class="card guide"><div class="row"><span class="ico">${icon(ico)}</span><b>${title}</b></div><div class="small" style="margin-top:6px">${body}</div></div>`;
    parts.push(sec('ball', 'Over goals', `<p><b>Over 1.5</b> wins when the match has 2 or more goals; <b>Over 2.5</b> needs 3 or more. The half-goal line means there is never a push. Own goals count, extra time does not (90 minutes plus stoppage time only).</p><p>Typical prices: Over 1.5 around 1.20–1.40 in open leagues; Over 2.5 around 1.70–2.10.</p>`));
    parts.push(sec('swap', 'Both teams to score (BTTS / GG)', `<p><b>Yes</b> wins if each team scores at least once, whatever the result — 1-1 and 3-2 win, 2-0 loses. <b>No</b> is the opposite. On Sportybet this is the "GG / NG" market.</p><p><b>Mr 2 Odds no longer publishes BTTS picks</b> (2026-10-27 audit): the family returned −7.0 % over 183 priced bets, and the unpriced forward test was 15 points too optimistic. The probability still appears on the match page for context; it is not offered as a selection.</p>`));
    parts.push(sec('target', 'What Mr 2 Odds no longer offers', `<p>The 2026-10-27 audit re-graded every settled pick and turned families off for good: <b>double chance</b> (−16.7 % over 300 priced bets), <b>team goals</b> (−6.4 %, home team to score −10.1 %), <b>cards / bookings</b> (−9.4 %), <b>BTTS</b> (−7.0 %) and <b>Over 0.5</b> (−5.9 %) — plus <b>every under</b> (user rule). The boards now compete in <b>Over 1.5, Over 2.5, corners and 1X2</b>, Over 2.5 and 1X2 start from <b>55%</b>, corners from <b>65%</b>, <b>nothing priced under 1.16 is offered</b>, and a pick priced under 95 % of its own fair price waits on the watchlist. Old tickets and the track record still settle and display normally.</p>`));
    parts.push(sec('corner', 'Corners', `<p><b>Over 9.5 corners</b> wins with 10 or more corners in the match (both teams together). Corners awarded but not taken before the final whistle still count. Modelled for the 22 main European leagues, from each team's corners for and against; average is about 10 per match.</p>`));
    parts.push(sec('card', 'Cards / bookings', `<p><b>Over 3.5 cards</b> wins with 4 or more cards. On Sportybet a yellow counts 1 and a straight red 2 (a second yellow = yellow + red = 3 for that player); some books use "booking points" (10/25) instead — check the market name. Cards to the bench or after the whistle usually do not count. Modelled from team and referee averages in the main European leagues. <b>Mr 2 Odds no longer publishes card picks</b> (2026-10-27 — −9.4 % over the priced sample); the card statistics still feed the match page and the leagues browser.</p>`));
    parts.push(sec('shield', 'Match result', `<p><b>1X2</b>: home win, draw or away win after 90 minutes. Shown on every match page for context; Mr 2 Odds's high-probability selections stay in the goals, corners and 1X2 markets, must carry a price of 1.16 or more, and are shown with the model-anchored probability.</p>`));
    parts.push(sec('trend', 'How the probabilities are made (data-first)', `<p>Every probability starts from <b>football data</b> and is then anchored to the price — a 25 % model / 75 % de-vigged-market blend (2026-10-27 audit: the market forecast better than the model over 3,910 settled priced picks, and the blend scored best on Brier and log-loss). The raw model number is shown beside it as <b>model</b>. Each team gets a time-weighted attack and defence rating from its last 60 competitive matches (recent games weighted most, league-normalised, home and away blended, shrunk towards the league average when the sample is small). League baseline × attack × opponent's defence gives the <b>Model xG</b> of each team, and a Dixon-Coles Poisson score matrix turns that into a probability for every line.</p><p>Bookmaker prices have two jobs: the margin is removed and the implied probability shown with the difference in points and the EV, and — since the audit — that de-vigged number <b>sets the anchor for the published probability</b>. The blend is capped at market + 3 points and at 90 % (80 % when nothing is priced), so a wild model value can never be published. <b>Market xG</b> (from the prices) is shown next to Model xG as a comparison.</p><p>Every statistic carries its sample size — Very small 1–4, Small 5–9, Moderate 10–19, Strong 20–39, Very strong 40+ — and each match has a <b>data quality</b> assessment (completeness, sample, recency, consistency, competition, home/away relevance, source) under the <b>Data</b> tab, with the raw matches used, the extreme results flagged and the model's own numbers. Data quality drives the confidence wording, never the probability. Missing data is shown as N/A, never as 0.</p><p><b>High-probability selection</b> = published probability of at least 70% (its market bar, whichever is higher) in the goals, corners and 1X2 markets, <b>priced at 1.16 or more</b> and at least 95 % of its own fair price — the price anchors the probability now, so it is a gate as well as a display. <b>⭐ Bets of the day</b> = the best of those at 07:00, one market per match. <b>Low data</b> = fewer than four useful matches for a team; those games are shown but never selected. No selection is ever certain — a 75% probability loses one time in four.</p>`));
    parts.push(sec('ticket', 'Bet slip & tickets', `<p>Tap <b>+</b> next to any priced selection (match page › Markets, high-probability selections, bets of the day) to put it on your slip — one selection per match, like a real multiple. Press <b>Done</b> to lock the ticket: Mr 2 Odds multiplies the prices, records an optional stake, and then follows the scores. Goals markets settle from the final score; corners and cards settle from the match statistics a few hours after full time. You get a notification when the ticket is won or lost, and ☰ › <b>My tickets</b> keeps your record.</p><p>This is a private record on your phone — nothing is placed with a bookmaker.</p>`));
    parts.push(sec('info', 'Reading the numbers honestly', `<p>A 75% bet loses one time in four. A card of five 75% singles has all five winning only about 24% of the time — that is why Mr 2 Odds shows singles and grades every one of them, and does not build accumulators. Compare the <b>Hit</b> and <b>Exp.</b> columns under Performance: they should be close over a few weeks.</p><p>Coverage: every competition on the live feed, worldwide, including women's and youth leagues, priced by Sportybet South Africa. Prices move; check the price before you bet. Statistical information, not betting advice. 18+, bet responsibly.</p>`));
    parts.push(sec('star', 'Bets of the day, favourites & alerts', `<p><b>⭐ Bets of the day</b> is built on Over 1.5, Over 2.5, 1X2 and corners (up to seven picks a block); <b>1X2 claims its matches first — up to five picks a day</b> — then <b>Over 2.5</b> gets its place, then the rest: 1X2 needs ≥70% and Over 2.5 needs ≥55%, all with recent form backing them; corners need ≥65%. Every one must carry a price of 1.16 or more. Overs only, one market per match, picked by the first analysis of the day and graded separately — so the performance page can compare the markets fairly. Every match page has <b>Download stats (CSV)</b> and the ☰ menu downloads the whole day's analysis as a spreadsheet file. <b>Top leagues</b> ranks the major leagues by home wins, away wins, overs, corners and bookings.</p><p>Tap <b>☆</b> in a match header to make it a favourite: you get goal, half-time, full-time and kick-off alerts for it, it appears under Your matches on Home, and in the ★ filter of Matches.</p>`));
    parts.push(PR.editorCard(false));
    parts.push(contactCard(false));
    view().innerHTML = parts.join('');
    wireBack();
  };

  // ------------------------------------------------------------------ SETTINGS
  function notifState() { if (!PR.native || !PR.native.notificationsAllowed) return null; try { return !!PR.native.notificationsAllowed(); } catch (e) { return null; } }
  PR.pages.settings = function () {
    const parts = [head('Settings')];
    const allowed = notifState();
    parts.push(`<div class="card settings"><h2>${icon('bell')} Notifications</h2>
      <div class="row"><div class="grow small">${allowed === false ? '<span class="chip bad">off</span> Allow notifications to get new bets, analysis, goal and update alerts.' : allowed ? '<span class="chip good">on</span> Checked about every 15 minutes in the background' : 'Notifications are only available in the Android app.'}</div>
      ${allowed === false ? '<button class="btn primary" id="s-notif">Allow</button>' : ''}</div>
      <label class="row" style="margin-top:10px"><input type="checkbox" id="s-bets" ${settings.betAlerts !== false ? 'checked' : ''}> <span class="grow">📈 New high-probability selections (found by the half-hourly refresh)</span></label>
      <label class="row" style="margin-top:6px"><input type="checkbox" id="s-reports" ${settings.reportAlerts !== false ? 'checked' : ''}> <span class="grow">📊 Full analysis published (07:00 · 12:00 · 17:00)</span></label>
      <label class="row" style="margin-top:6px"><input type="checkbox" id="s-goals" ${settings.goalAlerts ? 'checked' : ''}> <span class="grow">⚽ Score changes (goals with the scorer) in tracked matches — bets of the day, high-probability selections, shortlist and your tickets</span></label>
      <label class="row" style="margin-top:6px"><input type="checkbox" id="s-ht" ${settings.htAlerts ? 'checked' : ''}> <span class="grow">⏸ Half-time results of tracked matches</span></label>
      <label class="row" style="margin-top:6px"><input type="checkbox" id="s-ft" ${settings.ftAlerts !== false ? 'checked' : ''}> <span class="grow">🏁 Full-time results of tracked matches · tickets won / lost</span></label>
      <label class="row" style="margin-top:6px"><input type="checkbox" id="s-ko" ${settings.koAlerts !== false ? 'checked' : ''}> <span class="grow">⏰ Kick-off reminders (15 min before) for favourites and ticket matches</span></label></div>`);
    const SOUNDS = [['goals', 'goal', '⚽ Goal (crowd & horn)'], ['tickets', 'tickets', '🎫 Ticket won / lost'], ['kickoff', 'kickoff', '⏰ Kick-off'], ['match', 'fulltime', '🏁 Half / full time'], ['bets', 'selection', '📈 New selection'], ['reports', 'report', '📊 Report published'], ['', 'card', '🟨 Referee whistle (gallery)']];
    parts.push(`<div class="card settings"><h2>${icon('bell')} Notification sounds</h2>
      <div class="small muted">Each alert type has its own short sound so you know what arrived without looking. Tap ▶ to preview; the gear opens Android's settings for that alert (sound, vibration, silent).</div>
      <div class="sounds">${SOUNDS.map(([ch, file, label]) => `<div class="row snd"><button class="btn sm" data-play="${file}">▶</button><span class="grow">${label}</span>${ch && PR.native && PR.native.openChannelSettings ? `<button class="btn sm" data-chan="${ch}" title="Android settings">${icon('settings', 'sm')}</button>` : ''}</div>`).join('')}</div></div>`);
    parts.push(`<div class="card settings"><h2>${icon('moon')} Appearance</h2>${segmented([['system', 'System'], ['light', 'Light'], ['dark', 'Dark']], settings.theme || 'system', 'th')}
      <div class="tiny muted" style="margin-top:6px">System follows your phone's dark-mode setting.</div></div>`);
    parts.push(`<div class="card settings"><h2>${icon('clock')} Display</h2>
      <label>Leagues shown in Bets and on Home</label>${segmented([['all', '🌍 All leagues'], ['major', '🏆 Major leagues only']], settings.leagues || 'all', 'lgs')}
      <label>Live auto-refresh (seconds, min 20)</label><input id="s-live" type="number" value="${settings.liveEvery}">
      <label>Analysis timezone offset from UTC (hours; South Africa = 2)</label><input id="s-tz" type="number" value="${settings.tzOffset}">
      <div style="margin-top:12px"><button class="btn primary" id="s-save">Save</button><button class="btn" id="s-clear">Clear saved data</button></div>
      <div class="tiny muted" style="margin-top:6px">${(() => { if (PR.resources) return 'Downloaded analysis is saved on this phone (up to 32 MB) and checked for updates in the background.'; const c = PR.cache.size(); return `${c.n} analysed pages saved on this phone (${c.kb} KB) — they open instantly and refresh in the background.`; })()}</div></div>`);
    parts.push(`<div class="card settings"><h2>${icon('info')} App</h2><div class="row"><div class="grow small">Mr 2 Odds ${PR.APP_VERSION ? 'v' + PR.APP_VERSION : '(browser preview)'}${state.update ? ` · <b>v${esc(state.update.version)} available</b>` : ' · up to date'}</div>
      ${state.update ? `<button class="btn primary" id="s-install">Update</button>` : `<button class="btn" id="s-check">Check for update</button>`}</div>
      ${state.update && PR.notesList(state.update.notes).length ? `<div class="small" style="margin-top:8px"><b>What's new in ${esc(state.update.version)}</b><ul class="notes">${PR.notesList(state.update.notes).map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>` : ''}
      <div class="tiny muted" style="margin-top:6px">Updates are downloaded and checked against the release's own SHA-256 digest before anything happens; Android then asks you to install. The app never installs anything by itself and asks for no install permission. Your tickets, favourites and settings are kept.</div>
      <div style="margin-top:8px"><button class="btn" id="s-whatsnew">What's new in this version</button></div></div>`);
    parts.push(PR.editorCard(false));
    parts.push(contactCard(false));
    parts.push(`<div class="card small"><b>About Mr 2 Odds</b><div class="muted" style="margin-top:4px">Football analysis for every competition worldwide, refreshed every 30 minutes with a full report at 07:00, 12:00 and 17:00 SAST: expected goals, probabilities for every market, high-probability selections, bets of the day, trends, head-to-head, live scores and an audited day-by-day record. Live scores come from a public feed and never influence the model.</div>
      <div class="muted" style="margin-top:6px">Statistical information, not betting advice. Bet responsibly — 18+.</div></div>`);
    view().innerHTML = parts.join('');
    wireBack();
    const pref = (k, v) => { if (PR.native && PR.native.setPref) { try { PR.native.setPref(k, !!v); } catch (e) { /* ignore */ } } };
    $('#s-save').onclick = () => { settings.liveEvery = Math.max(20, +$('#s-live').value || 60); settings.tzOffset = +$('#s-tz').value || 0; PR.saveSettings(); live.schedule(); toast('Saved'); PR.back(); };
    $('#s-clear').onclick = () => { PR.clearDataCache().then(() => toast('Saved data cleared')).catch(() => toast('Could not clear saved data')); };
    $('#s-goals').onchange = (e) => { settings.goalAlerts = e.target.checked; PR.saveSettings(); pref('goals', settings.goalAlerts); };
    $('#s-bets').onchange = (e) => { settings.betAlerts = e.target.checked; PR.saveSettings(); pref('bets', settings.betAlerts); };
    $('#s-reports').onchange = (e) => { settings.reportAlerts = e.target.checked; PR.saveSettings(); pref('reports', settings.reportAlerts); };
    $('#s-ht').onchange = (e) => { settings.htAlerts = e.target.checked; PR.saveSettings(); pref('ht', settings.htAlerts); };
    $('#s-ko').onchange = (e) => { settings.koAlerts = e.target.checked; PR.saveSettings(); pref('ko', settings.koAlerts); };
    $('#s-ft').onchange = (e) => { settings.ftAlerts = e.target.checked; PR.saveSettings(); pref('ft', settings.ftAlerts); };
    $$('[data-th]').forEach((b) => { b.onclick = () => { settings.theme = b.dataset.th; PR.saveSettings(); PR.applyTheme(); PR.render(); }; });
    $$('[data-lgs]').forEach((b) => { b.onclick = () => { settings.leagues = b.dataset.lgs; PR.saveSettings(); PR.render(); }; });
    const n = $('#s-notif'); if (n) n.onclick = () => { if (PR.native && PR.native.requestNotifications) PR.native.requestNotifications(); };
    const wn = $('#s-whatsnew'); if (wn) wn.onclick = () => { settings.seenVersion = ''; PR.saveSettings(); state.stack = []; PR.setTab('home'); };
    const c = $('#s-check'); if (c) c.onclick = () => { toast('Checking…'); state.updateChecked = 'manual'; if (PR.native && PR.native.checkUpdate) PR.native.checkUpdate(); else toast('Updates are only available in the Android app'); };
    const i = $('#s-install'); if (i) i.onclick = () => PR.startUpdate();
    $$('[data-play]').forEach((b) => { b.onclick = () => { try { const a = new Audio(`sounds/pr_${b.dataset.play}.wav`); a.volume = 0.9; a.play().catch(() => toast('Preview not available here')); } catch (e) { toast('Preview not available here'); } }; });
    $$('[data-chan]').forEach((b) => { b.onclick = () => { try { PR.native.openChannelSettings(b.dataset.chan); } catch (e) { toast('Open Android Settings → Apps → Mr 2 Odds → Notifications'); } }; });
  };

  // ------------------------------------------------------------------ IN-APP NEWS READER
  // Headline tap → the article is downloaded once and saved on the phone, then read inside Mr 2 Odds
  // (no redirect to an external browser). "Open original" stays available on every screen of the reader.
  const artHash = (str) => { let x = 5381; for (let i = 0; i < String(str).length; i++) x = ((x << 5) + x + String(str).charCodeAt(i)) | 0; return (x >>> 0).toString(36); };
  function extractArticle(html) {
    if (typeof DOMParser === 'undefined') return null;
    try {
      const doc = new DOMParser().parseFromString(html, 'text/html');
      ['script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript', 'form', 'iframe', 'button'].forEach((t) => doc.querySelectorAll(t).forEach((n) => n.remove()));
      const root = doc.querySelector('article') || doc.querySelector('main') || doc.querySelector('[role=main]') || doc.body;
      if (!root) return null;
      let ps = Array.from(root.querySelectorAll('p')).map((n) => (n.textContent || '').trim()).filter((t) => t.length > 60);
      if (ps.length < 3) ps = Array.from(root.querySelectorAll('p, h2, h3, li')).map((n) => (n.textContent || '').trim()).filter((t) => t.length > 60);
      ps = ps.slice(0, 60);
      if (ps.join('').length < 300) return null;
      return ps;
    } catch (e) { return null; }
  }
  PR.pages.reader = function (page) {
    const link = page.link || '';
    const ck = 'pr_art_' + artHash(link);
    const shell = (body) => {
      view().innerHTML = head(esc(page.source || 'News'), esc((page.title || '').slice(0, 90))) + body;
      wireBack();
      const ob = $('#rd-open');
      if (ob) ob.onclick = () => { if (PR.native && PR.native.openUrl) PR.native.openUrl(link); else window.open(link, '_blank'); };
    };
    const renderText = (paras, saved) => shell(`
      <div class="card">
        <div class="b" style="font-size:15.5px;line-height:1.35">${esc(page.title || '')}</div>
        <div class="tiny muted" style="margin-top:4px">${esc(page.source || '')}${page.when ? ' · ' + esc(page.when) : ''}${saved ? ' · <span class="good">saved on this phone</span>' : ''}</div>
        <div style="margin-top:10px">${paras.map((t) => `<p style="font-size:14.5px;line-height:1.6;margin:0 0 10px">${esc(t)}</p>`).join('')}</div>
      </div>
      <button class="btn wide" id="rd-open">${icon('next', 'sm')} Open the original article</button>
      <div class="note">Downloaded for reading inside Mr 2 Odds and kept on this phone. The source owns the full article — open it for images, video and comments.</div>`);
    const fail = () => {
      const top = state.stack[state.stack.length - 1];
      if (!top || top.type !== 'reader') return;   // never overwrite a page the user has moved on to
      shell(`<div class="card empty">The article could not be downloaded (offline, or the source blocks downloads).<div style="margin-top:10px"><button class="btn" id="rd-open">Open the original site</button></div></div>`);
    };
    let cached = null;
    try { cached = JSON.parse(PR.stored(ck) || 'null'); } catch (e) { cached = null; }
    if (cached && Array.isArray(cached.paras) && cached.paras.length) { renderText(cached.paras, true); return; }
    shell(`<div class="card">${skeleton(4)}<div class="tiny muted" style="margin-top:6px">Downloading the article…</div></div>`);
    if (!link) { fail(); return; }
    PR.nfetch(link).then((r) => {
      const paras = r && r.code === 200 && r.body ? extractArticle(r.body) : null;
      if (!paras) { fail(); return; }
      try { PR.persist(ck, JSON.stringify({ t: Date.now(), paras })); } catch (e) { /* quota */ }
      if (state.stack[state.stack.length - 1] && state.stack[state.stack.length - 1].type === 'reader') renderText(paras, false);
    }).catch(() => fail());
  };

  // ------------------------------------------------------------------ BET ADVISOR OF THE DAY
  // A daily advisory built only from what the model already publishes: the day's card, the strongest
  // signals, the biggest edges and the high-confidence list — plus staking discipline. No new maths.
  PR.pages.advisor = function () {
    const d = state.data || {}; const sf = d.safe || {}; const today = ymd(tzNow());
    const parts = [head(`Bet advisor · ${esc(dayName(today))}`, 'Statistical information from the model — not betting advice')];
    const record = d.advisor || {};
    const metric = (v) => v == null ? '—' : (100 * Number(v)).toFixed(1) + '%';
    parts.push(`<section class="advisor-hero"><img class="pr-disc" src="logo.png" alt="Mr 2 Odds"><div class="b">ADVISOR · LIVE RECORD</div><div class="small muted">Two daily editions · 08:00 &amp; 16:00 SAST</div>
      <div class="advisor-metrics"><div><b>${metric(record.hit_rate)}</b><span>settled hit rate</span></div><div><b>${record.settled || 0}</b><span>settled picks</span></div><div><b>${metric(record.roi)}</b><span>flat-stake ROI</span></div></div>
      <div class="tiny muted" style="margin-top:12px">${record.wins || 0} won · ${record.losses || 0} lost · ${record.pending || 0} pending · ${record.void || 0} void. ${Number(record.profit_units || 0).toFixed(2)} units profit. Tracking ${record.since ? 'since ' + esc(record.since) : 'starts with the next publication'}; no historical backfill. First published prices, 1-unit singles; not combined-card returns.</div></section>`);
    if (record.markets && Object.keys(record.markets).length) parts.push(`<div class="card compact"><div class="b">Advisor record by market</div><table class="tbl"><tr><th>Market</th><th>W / L</th><th>Hit rate</th><th>ROI</th></tr>${Object.entries(record.markets).map(([sel,r]) => `<tr><td>${esc(selLabel(sel))}</td><td>${r.wins} / ${r.losses}</td><td>${metric(r.hit_rate)}</td><td>${metric(r.roi)}</td></tr>`).join('')}</table><div class="tiny muted">Pending and void picks are excluded from hit rate and ROI. Small samples are not proof of an edge.</div></div>`);
    if ((record.recent || []).length) parts.push(`<div class="card compact"><div class="b">Advisor selection ledger</div><table class="tbl">${record.recent.map((r) => `<tr><td><div class="b">${esc(r.home)} v ${esc(r.away)}</div><div class="tiny muted">${esc(r.label || r.sel)} @ ${f2(r.odds)} · ${esc(r.match_date)}</div></td><td>${esc(String(r.status || 'pending').toUpperCase())}</td></tr>`).join('')}</table></div>`);
    const row = (b) => `<tr class="tap" data-fx="${esc(b.fixture || b.id)}"><td><div class="b">${esc(b.label || selLabel(b.sel, (fx(b.fixture || b.id) || {}).home, (fx(b.fixture || b.id) || {}).away))}</div><div class="tiny muted">${teamSpan(b.home || ((fx(b.fixture || b.id) || {}).home) || '', b.country, (fx(b.fixture || b.id) || {}).div)} v ${teamSpan(b.away || ((fx(b.fixture || b.id) || {}).away) || '', b.country, (fx(b.fixture || b.id) || {}).div)}${b.q ? ' · data ' + esc(b.q) : ''}</div></td><td class="right nowrap"><b>${b.odds ? f2(b.odds) : '–'}</b></td><td class="right">${pill(b.p, 0.8, 0.7)}</td></tr>`;
    const groups = (sf.today && sf.today.groups) || [];
    const dayBets = (sf.today && sf.today.bets) || [];
    if (dayBets.length) {
      const shown = groups.filter((g) => (g.bets || []).length);
      (shown.length ? shown : [{ title: 'Recommendations', bets: dayBets }]).forEach((g) => {
        parts.push(`<div class="card compact"><div class="row"><div class="grow b">${icon('shield', 'sm')} ${esc(g.title)}</div><span class="tiny muted">${g.bets.length} pick${g.bets.length === 1 ? '' : 's'}</span></div>
          <table class="tbl">${g.bets.slice(0, 6).map(row).join('')}</table></div>`);
      });
      parts.push(`<div class="card small"><b>How the advisor picks</b><div class="muted" style="margin-top:4px">Every line above is a model selection that cleared its bar on <b>today's matches only</b>: ≥70% model probability (Over 2.5 ≥55%, corners ≥65%), one market per match, nothing priced under <b>1.16</b>. Nothing is chosen by hand.</div></div>`);
    } else {
      parts.push(`<div class="card empty">The advisor's card appears with the first analysis of the day (about 07:00) and fills section by section as probabilities firm up.</div>`);
    }
    const val = ((d.groups || {}).value || []).slice(0, 5);
    if (val.length) parts.push(`<div class="card compact"><div class="row"><div class="grow b">${icon('trend', 'sm')} Biggest model-vs-market edges</div><span class="tiny muted">value</span></div>
      <table class="tbl">${val.map((v) => { const f = fx(v.id) || {}; return `<tr class="tap" data-fx="${esc(v.id)}"><td><div class="b">${esc(selLabel(v.sel, f.home, f.away))}</div><div class="tiny muted">${esc(f.home || '')} v ${esc(f.away || '')}</div></td><td class="right nowrap"><b>${v.odds ? f2(v.odds) : '–'}</b></td><td class="right good">+${Math.round((v.ev || 0) * 100)} pp</td></tr>`; }).join('')}</table></div>`);
    const strong = ((d.groups || {}).strong || []).slice(0, 5);
    if (strong.length) parts.push(`<div class="card compact"><div class="row"><div class="grow b">${icon('star', 'sm')} Strongest signals</div><span class="tiny muted">≥ 70%</span></div>
      <table class="tbl">${strong.map((v) => { const f = fx(v.id) || {}; return `<tr class="tap" data-fx="${esc(v.id)}"><td><div class="b">${esc(selLabel(v.sel, f.home, f.away))}</div><div class="tiny muted">${esc(f.home || '')} v ${esc(f.away || '')}${v.q ? ' · data ' + esc(v.q) : ''}</div></td><td class="right">${pill(v.p, 0.8, 0.7)}</td></tr>`; }).join('')}</table></div>`);
    const conf = (sf.bets || []).filter((b) => String(b.kickoff || '').slice(0, 10) === today).slice(0, 5);
    if (conf.length) parts.push(`<div class="card compact"><div class="row"><div class="grow b">${icon('check', 'sm')} High-confidence list</div><span class="tiny muted">today</span></div>
      <table class="tbl">${conf.map(row).join('')}</table></div>`);
    parts.push(`<div class="card"><div class="b">Staking discipline</div><div class="small" style="margin-top:4px">
      <div>• Flat stakes — the same unit on every pick; never chase a loss with a bigger stake.</div>
      <div>• A 70% probability still loses about three times in ten — expect run-downs and stay with the plan.</div>
      <div>• Odds never decide what makes the card — model probability, data quality and form do; the price is shown on every pick.</div>
      <div>• Check <b>Performance</b> weekly: if the real hit rate sits below the model's predicted rate for weeks, bet smaller.</div>
      </div><div class="row" style="margin-top:8px;gap:8px"><button class="btn grow" id="adv-perf">Performance &amp; calibration</button><button class="btn grow" id="adv-best">Best of the day</button></div></div>`);
    // The briefing lives here and only here (user rule 2026-10-27): the Bet Advisor tab is where a viewer watches the
    // day's card read out slowly, match by match, in the same order as the Telegram/YouTube video.
    parts.push(`<div class="card compact briefing-cta"><div class="row"><div class="grow"><div class="b">${icon('sparkle', 'sm')} Today’s briefing</div><div class="tiny muted">Opens with yesterday’s full card — every selection from every video — then today’s <b>Over 1.5 goals &amp; corners</b> picks (Advisor Over 2.5 as fallback) one at a time, with the reasons, both clubs’ last five and the head to head. Only matches with recent stats and a recent head to head appear; no match is repeated. Silent slides, one music track, kick-off times in SAST, and the pacing is deliberately slow. A shortlist for your review — never an instruction to bet.</div></div></div>
      <div class="row" style="gap:8px;margin-top:8px"><button class="btn" id="btn-briefing">${icon('live', 'sm')} Watch briefing</button><button class="btn" id="btn-briefing-dl">${icon('download', 'sm')} Download 16:9 video</button></div></div>`);
    parts.push(`<div class="note">Statistical information, not betting advice. Never stake money you cannot afford to lose.</div>`);
    view().innerHTML = parts.join('');
    wireBack();
    const bp = $('#adv-perf'); if (bp) bp.onclick = () => PR.push({ type: 'performance' });
    const bb = $('#adv-best'); if (bb) bb.onclick = () => PR.push({ type: 'best' });
    const wb = $('#btn-briefing'); if (wb) wb.onclick = () => PR.push({ type: 'briefing' });
    const wd = $('#btn-briefing-dl'); if (wd) wd.onclick = () => PR.push({ type: 'briefing', download: true });
  };

  // ------------------------------------------------------------------ BET ADVISOR BRIEFING (16:9 video-style player + download)
  // The on-phone briefing mirrors the Telegram/YouTube video (2026-10-21) and lives ONLY on the Bet Advisor tab
  // (user rule 2026-10-27): a match is up to THREE slides — the pick, why it is here (reasons, trends, home/away), and
  // the record (head to head plus both clubs' last five). Over 1.5 and corners first; Advisor Over 2.5 fallback.
  // Five to eight verified matches, combined odds 2.00–3.30 (target 2.50), with no repeat from earlier editions.
  const REEL_MIN_P = 0.65;               // the same floor the YouTube/TikTok cuts use
  const REEL_MIN_ODDS = 1.16;
  const REEL_MAX_PICKS = 8;              // slower pacing means fewer matches per video
  const GATE_MIN_RESULTS = 5;            // recent results per club, with a score
  const GATE_MIN_H2H = 2;                // head-to-head meetings with a score
  function reelMarket(x) {
    return /^(O15|O25|C[HA]?O\d+)$/.test(String((x && x.sel) || '').toUpperCase());
  }
  function briefingClub(name) {
    return String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ')
      .replace(/\b(fc|cf|sc|ac|afc|club)\b/g, '').trim();
  }
  function briefingPicks() {
    const d = state.data || {};
    const sast = new Date(Date.now()+7200000).toISOString();
    const shown = new Set((((d.advisor || {}).shown_today) || []).map((p) => [briefingClub(p.home),briefingClub(p.away)].sort().join('|')));
    return (((d.advisor || {}).picks) || []).filter((x) => {
      const floor = x.sel === 'O25' ? 0.55 : REEL_MIN_P;
      return !shown.has([briefingClub(x.home),briefingClub(x.away)].sort().join('|')) && reelMarket(x) && Number(x.p) >= floor && Number(x.p) < 1
        && Number(x.odds) >= REEL_MIN_ODDS && Number(x.odds) <= 3.30
        && String(x.kickoff || '').slice(0,10) === sast.slice(0,10)
        && String(x.kickoff || '').slice(11,16) > sast.slice(11,16);
    });
  }
  function briefingCard(candidates) {
    for (const fallback of [false, true]) {
      const groups = {};
      candidates.filter((p) => fallback || p.sel !== 'O25').forEach((p) => {
        const key = [briefingClub(p.home),briefingClub(p.away)].sort().join('|');
        if (!groups[key]) groups[key] = {};
        groups[key][p.sel] = p;
      });
      let states = {0: [{odds:1, p:1, picks:[]}]};
      Object.keys(groups).sort().forEach((key) => {
        const next = {};
        Object.keys(states).forEach((n) => { next[n] = states[n].slice(); });
        Object.keys(states).forEach((n) => {
          if (Number(n) >= REEL_MAX_PICKS) return;
          states[n].forEach((r) => Object.values(groups[key]).forEach((p) => {
            const odds = r.odds * Number(p.odds);
            if (odds > 3.30) return;
            const count = Number(n)+1;
            if (!next[count]) next[count] = [];
            next[count].push({odds, p:r.p * Number(p.p), picks:r.picks.concat([p])});
          }));
        });
        states = {};
        Object.keys(next).forEach((n) => {
          const buckets = {};
          next[n].forEach((r) => { const k = Math.round(r.odds*1000); if (!buckets[k] || r.p > buckets[k].p) buckets[k] = r; });
          states[n] = Object.values(buckets);
        });
      });
      const choices = Object.keys(states).filter((n) => Number(n)>=5).flatMap((n) => states[n]).filter((r) => r.odds>=2 && r.odds<=3.30);
      choices.sort((a,b) => Math.abs(a.odds-2.5)-Math.abs(b.odds-2.5) || b.p-a.p);
      if (choices.length) return choices[0].picks;
    }
    return [];
  }

  /** the stats gate: both clubs' last five with scores, and at least two head-to-head meetings with scores */
  function briefingVerified(x, det) {
    if (!det || !det.teams) return false;
    if (String(x.sel || '').startsWith('C')) {
      const c = det.corners || {};
      if (!Array.isArray(c.n) || c.n.length !== 2 || c.n.some((n) => Number(n)<5) || !(Number(c.home)>0 && Number(c.away)>0)) return false;
    }
    const distinct = (list, a, b) => {
      const seen = {};
      return (list || []).filter((m) => m[a] != null && m[b] != null && Number(m[a]) >= 0 && Number(m[b]) >= 0 && m.date && String(m.date).slice(0,10) < String(x.kickoff).slice(0,10)).filter((m) => {
        const key = `${String(m.date || '').slice(0, 10)}|${Number(m[a])}|${Number(m[b])}`;
        if (seen[key]) return false;
        seen[key] = 1;
        return true;
      });
    };
    const rows = (side) => distinct(((det.teams || {})[side] || {}).last5, 'gf', 'ga');
    const h2h = distinct(det.h2h, 'hg', 'ag');
    const age = (list) => Math.min(...list.map((m) => (Date.now()-Date.parse(String(m.date).slice(0,10)+'T00:00:00+02:00'))/86400000));
    return age(rows('home')) <= 200 && age(rows('away')) <= 200 && age(h2h) <= 1100 && rows('home').length >= GATE_MIN_RESULTS && rows('away').length >= GATE_MIN_RESULTS
      && h2h.length >= GATE_MIN_H2H;
  }
  function marketLabel(sel) {
    const s = String(sel || '').toUpperCase();
    const m = s.match(/^O(\d+)$/);
    if (m) return `Over ${(Number(m[1]) / 10).toFixed(1)} goals`;
    return selLabel(s); // includes total and team corners
  }
  /** the two numbers THE PICK slide is about: the model's Over 1.5, and the market line it was anchored to */
  function briefingMarketRows(x) {
    const sel = String(x.sel || '').toUpperCase();
    const rows = [{ sel, label: marketLabel(sel), p:Number(x.p), odds:Number(x.odds), picked:true }];
    if (Number(x.p_sb)>0 && Number(x.p_sb)<1) rows.push({sel:sel+'#market',label:'Market price (de-vigged)',p:Number(x.p_sb),picked:false,market:true});
    return rows;
  }
  function briefingFeatured(x) { return x; } // prices locked by the card planner

  function briefingDetail(x) {
    const f = (state.data && fx(x.fixture)) || {};
    return PR.detailCached(x.fixture, f.d) || {};
  }
  function briefingChance(p) {
    if (!(p > 0)) return '';
    return p >= 0.95 ? 'better than nine in ten' : p >= 0.85 ? 'around nine in ten'
      : p >= 0.70 ? 'about three in four' : p >= 0.60 ? 'about two in three'
        : p >= 0.52 ? 'better than half' : 'around half';
  }
  /** the reasons, from the same numbers the video quotes: the model, its projected goals, the base rate, the edge */
  function briefingReasons(x, det) {
    const out = [];
    const pv = Number(x.p);
    if (pv > 0) out.push(`Model gives it ${Math.round(pv * 100)}% — ${briefingChance(pv)}`);
    const xg = Array.isArray(det.xg) ? det.xg : (det.xg && [det.xg.home, det.xg.away]);
    if (xg && xg.length === 2 && Number(xg[0]) >= 0 && Number(xg[1]) >= 0) {
      out.push(`Projected goals ${Number(xg[0]).toFixed(2)} – ${Number(xg[1]).toFixed(2)}`);
    }
    const sel = String(x.sel || '').toUpperCase();
    const side = /^AO/.test(sel) ? 'away' : /^HO/.test(sel) ? 'home' : '';
    const prof = side ? ((det.teams || {})[side] || {}) : ((det.teams || {}).home || {});
    if (side && Number(prof.fts) >= 0) {
      const team = side === 'away' ? x.away : x.home;
      out.push(`${team} have failed to score in ${Number(prof.fts) <= 0.25 ? 'only ' : ''}${Math.round(prof.fts * 100)}% of their matches`);
    } else if (['O15','O25'].includes(sel) && Number(prof[sel.toLowerCase()]) > 0) {
      out.push(`${marketLabel(sel)} has landed in ${Math.round(prof[sel.toLowerCase()] * 100)}% of ${x.home}’s matches`);
    }
    const psb = Number(x.p_sb);
    if (pv > 0 && psb > 0) {
      const gap = (pv - psb) * 100;
      if (Math.abs(gap) >= 1) out.push(`Model sits ${gap > 0 ? '+' : ''}${gap.toFixed(1)} points ${gap > 0 ? 'above' : 'below'} the market price`);
    }
    return out.slice(0, 4);
  }
  function briefingTrends(det) {
    const tr = det.trends || {};
    const groups = [tr.match || [], (tr.home || {}).all || [], (tr.away || {}).all || [], tr.h2h || []];
    const seen = {}; const out = [];
    groups.forEach((g) => (g || []).forEach((it) => {
      const t = String((it && it.t) || '').trim();
      if (!t || t.length > 110 || seen[t.toLowerCase()]) return;
      seen[t.toLowerCase()] = 1;
      out.push(t.charAt(0).toUpperCase() + t.slice(1));
    }));
    return out.slice(0, 3);
  }
  function briefingVenue(x, det) {
    const teams = det.teams || {};
    const out = [];
    if (teams.home && Number(teams.home.venue_gf) >= 0) {
      out.push(`At home: ${Number(teams.home.venue_gf).toFixed(2)} scored · ${Number(teams.home.venue_ga).toFixed(2)} conceded`);
    }
    if (teams.away && Number(teams.away.venue_gf) >= 0) {
      out.push(`Away: ${Number(teams.away.venue_gf).toFixed(2)} scored · ${Number(teams.away.venue_ga).toFixed(2)} conceded`);
    }
    return out;
  }
  function briefingRecent(det, side) {
    // a club cannot play twice on one date with the same score: that pair is the same match from two feeds, and
    // showing it twice is how a "last five" became three matches (fixed at the source 2026-10-28, guarded here)
    const team = (det.teams || {})[side] || {};
    const seen = {};
    const out = [];
    (team.last5 || []).forEach((m) => {
      if (!(Number(m.gf) >= 0 && Number(m.ga) >= 0)) return;
      const key = `${String(m.date || '').slice(0, 10)}|${Number(m.gf)}|${Number(m.ga)}`;
      if (seen[key]) return;
      seen[key] = 1;
      out.push({
        opp: m.opp || '', gf: Number(m.gf), ga: Number(m.ga),
        res: Number(m.gf) > Number(m.ga) ? 'W' : Number(m.gf) < Number(m.ga) ? 'L' : 'D',
      });
    });
    return out.slice(0, 5);
  }
  function briefingH2h(x, det) {
    const seen = {};
    const meetings = (det.h2h || []).filter((m) => Number(m.hg) >= 0 && Number(m.ag) >= 0).filter((m) => {
      const key = `${String(m.date || '').slice(0, 10)}|${Number(m.hg)}|${Number(m.ag)}`;
      if (seen[key]) return false;
      seen[key] = 1;
      return true;
    });
    const rows = meetings.slice(0, 5).map((m) => {
      const homeIsUs = String(m.home || '').toLowerCase() === String(x.home || '').toLowerCase();
      const gf = homeIsUs ? Number(m.hg) : Number(m.ag);
      const ga = homeIsUs ? Number(m.ag) : Number(m.hg);
      return {
        date: String(m.date || '').slice(0, 10), home: m.home || '', away: m.away || '',
        hg: Number(m.hg), ag: Number(m.ag), res: gf > ga ? 'W' : gf < ga ? 'L' : 'D',
      };
    });
    if (!rows.length) return null;
    const w = rows.filter((r) => r.res === 'W').length;
    const d = rows.filter((r) => r.res === 'D').length;
    const goals = rows.reduce((a, r) => a + r.hg + r.ag, 0) / rows.length;
    return { rows, line: `${w}W · ${d}D · ${rows.length - w - d}L in the last ${rows.length} meetings · ${goals.toFixed(1)} goals a game` };
  }
  function briefingSlides() {
    // only matches whose own numbers check out (recent results both sides + a recent head to head) reach a slide,
    // exactly like the pipeline's `reel_verify` gate — an unverifiable match is left out, never shown half-explained
    const picks = briefingCard(briefingPicks().filter((x) => briefingVerified(x, briefingDetail(x))));
    if (picks.length < 5) return [];
    const sl = (state.data && state.data.shortlist) || {};
    const yr = ((state.data || {}).advisor || {}).video_recap || {};
    // Every selection yesterday's videos carried (morning, noon and evening), not just the last one.
    const yItems = Array.isArray(yr.items) ? yr.items.filter((r) => r && ['hit', 'miss', 'void'].includes(r.result)) : [];
    const meta = (state.data && state.data.meta) || {};
    const when = meta.generated || '';
    const slides = [
      {
        kicker: 'Mr 2 Odds · 16:9 Briefing',
        title: 'Today’s shortlist',
        sub: `${picks.length} selection${picks.length === 1 ? '' : 's'} · ${esc(when)} SAST`,
        line: 'Results recap & today’s selections · SAST',
      },
      {
        kicker: 'Please bet responsibly · 18+',
        title: 'Disclaimer',
        sub: 'Statistical information, not betting advice.',
        line: 'Not for persons under the age of 18. Do not bet with money you cannot afford to lose. There is no such thing as a sure bet.',
      },
    ];
    if (yItems.length) {
      const settled = yItems.filter((r) => r.result === 'hit' || r.result === 'miss');
      const hits = settled.filter((r) => r.result === 'hit').length;
      const byOdds = (rows) => rows.slice().sort((a, b) => Number(b.odds || 0) - Number(a.odds || 0))[0];
      const bestWin = byOdds(settled.filter((r) => r.result === 'hit'));
      const badLoss = byOdds(settled.filter((r) => r.result === 'miss'));
      const say = (r, won) => r ? `${r.home} v ${r.away}: ${r.label || r.sel} ${won ? 'landed' : 'missed'}${r.score ? ' (' + r.score + ')' : ''}.` : '';
      const recap = [bestWin ? `Standout win — ${say(bestWin, true)}` : '', badLoss ? `The one that got away — ${say(badLoss, false)}` : '']
        .filter(Boolean).join(' ');
      // Paged like the video (RECAP_ROWS = 9): a 20-selection card on one slide would sit still for a minute and a
      // half. Page one carries the record, the standout and the one that got away; the rest are the card itself.
      const ROWS = 9;
      const pages = [];
      for (let k = 0; k < yItems.length; k += ROWS) pages.push(yItems.slice(k, k + ROWS));
      pages.forEach((rows, n) => {
        const part = pages.length > 1 ? ` · part ${n + 1} of ${pages.length}` : '';
        slides.push({
          kicker: `Yesterday’s card · every video · ${yr.day || ''}${part}`,
          title: n === 0 ? (settled.length ? `${hits} of ${settled.length} selections won` : 'Yesterday’s results recap')
            : `${rows.length} more from yesterday`,
          sub: n === 0 && settled.length
            ? `Hit rate ${Math.round((100 * hits) / settled.length)}% across every selection yesterday’s videos carried`
            : `Every selection yesterday’s videos carried${part}`,
          line: rows.map((r) => `${r.home} v ${r.away}: ${r.label || r.sel} (${r.result === 'hit' ? 'WON' : r.result === 'miss' ? 'LOST' : 'VOID'}${r.score ? ' ' + r.score : ''})`).join(' · '),
          note: n === 0 ? recap : '',
        });
      });
    }
    picks.forEach((raw, i) => {
      // the video features the strongest market the match offers, so do the same here
      const rows = briefingMarketRows(raw);
      const x = briefingFeatured(raw, rows);
      const det = briefingDetail(x);
      const comp = [x.country, x.league].filter(Boolean).join(' · ');
      const kicker = `Match ${i + 1} of ${picks.length}${comp ? ' · ' + comp : ''}`;
      const odds = x.odds ? f2(x.odds) : 'N/A';
      const chart = rows.map((r) => ({ label: r.label, p: r.p, picked: !!r.picked, market:!!r.market }));
      slides.push({
        stage: 'pick', kicker: `${kicker} · the pick`, title: `${x.home} v ${x.away}`,
        sub: `${x.label || 'Over 1.5 goals'} @ ${odds} · Kick-off ${esc(koTime(x.kickoff))} SAST`,
        line: `${Number(x.p) > 0 ? 'Model ' + Math.round(Number(x.p) * 100) + '%' : 'Model N/A'}`
          + (Number(x.p_sb) > 0 ? ` · market ${Math.round(Number(x.p_sb) * 100)}%` : ' · the book did not price it'),
        pick: x, bars: chart,
      });
      const reasons = briefingReasons(x, det);
      const trends = briefingTrends(det).filter((t) => !/under/i.test(t) && (!String(x.sel).startsWith('C') || /corner/i.test(t)));
      const venue = briefingVenue(x, det);
      if (reasons.length || trends.length || venue.length) {
        slides.push({
          stage: 'evidence', kicker: `${kicker} · why it’s here`, title: x.label || `${x.home} v ${x.away}`,
          sub: reasons[0] || '', line: reasons.slice(1).join(' · '),
          bullets: [...reasons.slice(1), ...venue, ...trends],
        });
      }
      const h2h = briefingH2h(x, det);
      const home = briefingRecent(det, 'home');
      const away = briefingRecent(det, 'away');
      if (h2h || home.length || away.length) {
        slides.push({
          stage: 'record', kicker: `${kicker} · the record`, title: 'Head to head & recent form',
          sub: h2h ? h2h.line : '', line: '',
          h2h: h2h ? h2h.rows : null,
          recent: [home.length ? { team: x.home, rows: home } : null, away.length ? { team: x.away, rows: away } : null].filter(Boolean),
        });
      }
    });
    slides.push({
      kicker: 'Mr 2 Odds',
      title: 'That’s the list',
      sub: 'Like, share or subscribe if this helped — no pressure.',
      line: 'Statistical information, not betting advice. 18+. © Mr 2 Odds. All rights reserved.',
    });
    const combined = picks.reduce((v,p) => v*Number(p.odds),1);
    slides.push({stage:'evidence', kicker:'Bet Advisor · the full card', title:`Combined odds ${combined.toFixed(2)}`,
      sub:picks.map((p) => Number(p.odds).toFixed(2)).join(' × ') + ' = ' + combined.toFixed(2),
      bullets:picks.map((p) => `${p.home} v ${p.away}: ${p.label || marketLabel(p.sel)} @ ${f2(p.odds)}`),
      note:'Prices can change. All legs must win. No guaranteed return. 18+.'});
    return slides;
  }
  function briefingHold(slide) {
    // No voice on the phone either (user rule 2026-10-21). 2026-10-27: the pacing was still too quick to read, so the
    // phone player uses the same, much slower timing as the video: `music.READ_WPS` 1.85 words a second, and
    // `shortlist_reel.stage_seconds` — pick 6.5 + 0.9 a bar, evidence/record 4.5 + 1.3 a line, floors 6.5 / 7.5 /
    // 8.5 s and a 16 s cap. A viewer gets time to read the stats before the next screen.
    const stage = slide && slide.stage;
    if (stage) {
      const lines = ((slide.bullets || []).length + (slide.h2h || []).length
        + ((slide.recent || []).reduce((a, r) => Math.max(a, r.rows.length), 0)));
      const bars = (slide.bars || []).length;
      const secs = stage === 'pick' ? 6.5 + 0.9 * Math.max(1, bars) : 4.5 + 1.3 * Math.max(1, lines);
      const floor = stage === 'pick' ? 6.5 : stage === 'evidence' ? 7.5 : 8.5;
      return Math.round(Math.min(16, Math.max(floor, secs)) * 1000);
    }
    const words = String(((slide && slide.title) || '') + ' ' + ((slide && slide.sub) || '') + ' ' + ((slide && slide.line) || '')).replace(/Mr 2 Odds/g, 'Mr2Odds').trim().split(/\s+/).filter(Boolean).length;
    // 4 s–45 s at 1.85 words a second: a results card is something to scan, and a long one still ends.
    return Math.min(45000, Math.max(4000, Math.round((words / 1.85) * 1000)));
  }
  /** the market chart, drawn the same way as THE PICK slide: 50–100% axis, the pick green and on top */
  function briefingBarsHtml(bars) {
    if (!bars || !bars.length) return '';
    const top = Math.max.apply(null, bars.map((b) => b.p));
    if (bars.length < 2 && !bars[0].picked) bars[0].picked = true;
    const rows = bars.map((b) => {
      const pct = Math.max(2, Math.min(100, ((b.p - 0.5) / 0.5) * 100));
      return `<div class="barrow${b.picked ? ' on' : ''}"><span class="bl">${esc(b.label)}</span>
        <span class="bt"><i style="width:${pct.toFixed(1)}%"></i></span>
        <span class="bp">${Math.round(b.p * 100)}%</span></div>`;
    }).join('');
    return `<div class="bars">${rows}</div>
      <div class="axis"><span>50%</span><span>75%</span><span>100%</span></div>
      <div class="tiny muted">${(() => {
        const model = Math.round(100 * (bars.find((b) => b.picked) || bars[0]).p);
        const mkt = bars.find((b) => b.market);
        if (!mkt) return 'The model’s own number — the book did not price this one';
        const gap = model - Math.round(100 * mkt.p);
        if (gap === 0) return `Model and market agree at ${model}% — no edge claimed`;
        return `Model ${model}% · market ${Math.round(100 * mkt.p)}% · ${Math.abs(gap)} pts ${gap > 0 ? 'above' : 'below'}`;
      })()}</div>`;
  }
  function briefingSlideHtml(s) {
    const bars = s.bars ? briefingBarsHtml(s.bars) : '';
    const bullets = (s.bullets || []).length ? `<ul class="bul">${s.bullets.map((b) => `<li>${esc(b)}</li>`).join('')}</ul>` : '';
    const h2h = (s.h2h || []).length ? `<div class="tiny muted">Head to head</div><ul class="bul">${s.h2h.map((r) => `<li>${esc(r.date)} · ${esc(r.home)} v ${esc(r.away)} · ${r.hg}–${r.ag} <b>${r.res}</b></li>`).join('')}</ul>` : '';
    const recent = (s.recent || []).length ? s.recent.map((t) => `<div class="tiny muted">${esc(t.team)}</div><ul class="bul">${t.rows.map((r) => `<li>${esc(r.opp)} · ${r.gf}–${r.ga} <b>${r.res}</b></li>`).join('')}</ul>`).join('') : '';
    return `<img class="pr-disc" src="logo.png" alt="Mr 2 Odds"><div class="kicker">${esc(s.kicker)}</div><h2>${esc(s.title)}</h2><div class="sub">${esc(s.sub || '')}</div><div class="line">${esc(s.line || '')}</div>${bars}${bullets}${h2h}${recent}${s.note ? `<div class="note">${esc(s.note)}</div>` : ''}`;
  }
  function briefingRecord(slides, done) {
    // Canvas webm — best-effort. Some WebViews cannot record; caller falls back to HTML.
    try {
      const W = 1280, H = 720, fps = 15;
      const c = document.createElement('canvas'); c.width = W; c.height = H;
      const g = c.getContext('2d');
      const logo = new Image(); logo.src = 'logo.png';
      const stream = c.captureStream(fps);
      const rec = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8' });
      const chunks = [];
      let animation = null;
      rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onstop = () => { cancelAnimationFrame(animation); stream.getTracks().forEach((t) => t.stop()); done(new Blob(chunks, { type: 'video/webm' })); };
      rec.start();
      let i = 0;
      const started = performance.now();
      const wrapText = (text, x, y, width, step, maxLines) => {
        let line = '', count = 0;
        for (const word of String(text || '').split(/\s+/)) {
          if (g.measureText(line+' '+word).width > width && line) {
            g.fillText(line,x,y); y += step; count++; line = '';
            if (count >= maxLines) return y;
          }
          line += (line ? ' ' : '')+word;
        }
        if (line) { g.fillText(line,x,y); y += step; }
        return y;
      };
      const paint = () => {
        if (i >= slides.length || rec.state === 'inactive') return;
        const s = slides[i];
        const gradient = g.createLinearGradient(0,0,W,H); gradient.addColorStop(0,'#090c1f'); gradient.addColorStop(1,'#163f50');
        g.fillStyle = gradient; g.fillRect(0,0,W,H);
        g.strokeStyle='#2ce1cc55'; g.strokeRect(35,35,W-70,H-70);
        if (logo.complete && logo.naturalWidth) {
          g.save(); g.translate(W-100,100); g.rotate((performance.now()-started)/8000*2*Math.PI);
          g.beginPath();g.arc(0,0,40,0,Math.PI*2);g.clip();g.drawImage(logo,-40,-40,80,80);g.restore();
        }
        g.fillStyle='#2ce1cc';g.font='700 21px sans-serif';wrapText(s.kicker,65,80,W-220,26,1);
        g.fillStyle='#f2f8ff';g.font='700 38px sans-serif';let y=wrapText(s.title,65,140,W-210,44,2)+10;
        g.fillStyle='#bbd2df';g.font='23px sans-serif';y=wrapText(s.sub,65,y,W-130,29,2)+8;
        g.fillStyle='#d6e4ef';g.font='20px sans-serif';y=wrapText(s.line,65,y,W-130,25,3)+8;
        if ((s.bars || []).length) s.bars.forEach((bar) => {
          g.fillStyle=bar.picked?'#2ce1cc':'#bbd2df';g.font='20px sans-serif';
          g.fillText(`${bar.label} · ${Math.round(bar.p*100)}%`,65,y);
          g.fillRect(65,y+10,Math.max(2,(bar.p-.5)*2)*(W-170),8);y+=55;
        });
        const lines = [...(s.bullets || [])];
        (s.h2h || []).forEach((r) => lines.push(`${r.date} · ${r.home} v ${r.away}: ${r.hg}–${r.ag}`));
        (s.recent || []).forEach((t) => { lines.push(t.team); t.rows.forEach((r) => lines.push(`${r.opp}: ${r.gf}–${r.ga} ${r.res}`)); });
        // Two columns for the long record; retain all five results per club and the H2H.
        const half=Math.ceil(lines.length/2), long=lines.length>9;
        g.font=(long?'17':'20')+'px sans-serif';g.fillStyle='#d6e4ef';
        lines.forEach((line,n) => {
          const column=long && n>=half?1:0, row=column?n-half:n;
          wrapText(line,65+column*585,y+row*(long?24:32),long?555:W-130,long?22:28,1);
        });
        if (s.note) {g.font='17px sans-serif';g.fillStyle='#bbd2df';wrapText(s.note,65,610,W-130,22,1);}
        g.fillStyle='#2ce1cc';g.fillRect(65,645,(i+1)/slides.length*(W-130),4);
        g.font='16px sans-serif';g.fillStyle='#bbd2df';g.fillText('Mr 2 Odds · Statistical information, not betting advice · 18+',65,680);
        animation = requestAnimationFrame(paint);
      };
      paint();
      const step = () => {
        i += 1;
        if (i >= slides.length) { rec.stop(); return; }
        setTimeout(step,briefingHold(slides[i]));
      };
      setTimeout(step,briefingHold(slides[i]));
    } catch (e) { done(null); }
  }
  function saveBlob(name, blob, mime) {
    if (!blob) return false;
    const reader = new FileReader();
    reader.onloadend = () => {
      const data = String(reader.result || '');
      const b64 = data.split(',')[1] || '';
      if (PR.native && PR.native.saveBase64 && b64.length < 900000) {
        try { PR.native.saveBase64(name, mime, b64); toast('Choose where to save the video…'); return; } catch (e) { /* fall through */ }
      }
      const a = document.createElement('a'); a.href = data; a.download = name; a.click();
      toast('Video saved');
    };
    reader.readAsDataURL(blob);
    return true;
  }
  PR.pages.briefing = function (page) {
    // Warm the fixture detail files first: the evidence and record slides read the same trends, head-to-head and
    // last-five results the video does (data/app/fx/<key>.json). The market chart comes from the fixture index, so
    // it renders even with no network; a failed detail fetch simply means fewer slides, never an empty one.
    const picksNow = briefingPicks();
    const warm = picksNow.map((x) => {
      const f = fx(x.fixture) || {};
      return (x.fixture ? PR.loadDetail(x.fixture, f.d) : Promise.resolve(null)).catch(() => null);
    });
    const paintBriefing = () => {
    const slides = briefingSlides();
    const parts = [head('Bet advisor briefing', 'Goals & corners · 5–8 matches · 08:00 / 16:00 SAST')];
    if (slides.length < 2) {
      parts.push('<div class="card empty">No qualifying card yet. A briefing requires at least five verified Advisor matches at combined odds 2.00–3.30. Over 1.5 and corners first; Advisor Over 2.5 only as fallback.</div>');
      view().innerHTML = parts.join(''); wireBack(); return;
    }
    parts.push(`<div class="briefing" id="briefing">
      <div class="brief-stage" id="brief-stage"></div>
      <div class="brief-bar"><span id="brief-pos">1 / ${slides.length}</span>
        <input id="brief-seek" type="range" min="0" max="${slides.length - 1}" value="0">
      </div>
      <div class="row" style="gap:8px;margin-top:10px">
        <button class="btn" id="brief-prev">Prev</button>
        <button class="btn" id="brief-play" style="flex:1">Play</button>
        <button class="btn" id="brief-next">Next</button>
      </div>
      <button class="btn" id="brief-dl" style="width:100%;margin-top:8px">${icon('download', 'sm')} Download video</button>
      <div class="tiny muted" style="margin-top:8px">The on-phone briefing is silent and follows the videos: every match gets THE PICK with a chart of its markets, WHY IT’S HERE and THE RECORD, and each slide stays up only as long as there is something new on it. The download is a video of these slides you can keep. Statistical information, not betting advice. 18+.</div>
    </div>`);
    view().innerHTML = parts.join(''); wireBack();
    let i = 0, playing = false, timer = null;
    const stage = $('#brief-stage'), pos = $('#brief-pos'), seek = $('#brief-seek');
    const show = (n) => {
      i = Math.max(0, Math.min(slides.length - 1, n));
      const s = slides[i];
      stage.innerHTML = briefingSlideHtml(s);
      pos.textContent = `${i + 1} / ${slides.length}`;
      seek.value = i;
    };
    const stop = () => {
      playing = false; if (timer) { clearTimeout(timer); timer = null; }
      const bp = $('#brief-play'); if (bp) bp.textContent = 'Play';
    };
    const next = () => { if (i >= slides.length - 1) { stop(); return; } show(i + 1); if (playing) go(); };
    const go = () => {
      playing = true; const bp = $('#brief-play'); if (bp) bp.textContent = 'Pause';
      if (timer) clearTimeout(timer);
      timer = setTimeout(next, briefingHold(slides[i]));
    };
    show(0);
    $('#brief-prev').onclick = () => { stop(); show(i - 1); };
    $('#brief-next').onclick = () => { stop(); show(i + 1); };
    $('#brief-play').onclick = () => { if (playing) stop(); else go(); };
    seek.oninput = () => { stop(); show(+seek.value); };
    const dl = () => {
      toast('Building your video…');
      briefingRecord(slides, (blob) => {
        if (blob && blob.size > 1000) { saveBlob(`Mr 2 Odds-briefing-${ymd(tzNow())}.webm`, blob, 'video/webm'); return; }
        PR.saveTextFile(`Mr 2 Odds-briefing-${ymd(tzNow())}.html`, briefingHtml(slides), 'text/html');
      });
    };
    $('#brief-dl').onclick = dl;
    if (page && page.download) setTimeout(dl, 400);
    };
    view().innerHTML = head('Shortlist briefing', 'Video · three slides a match · downloadable')
      + '<div class="card empty">Preparing the briefing — loading each match’s trends and record…</div>';
    wireBack();
    Promise.all(warm).then(paintBriefing, paintBriefing);
  };
})(window.PR);
