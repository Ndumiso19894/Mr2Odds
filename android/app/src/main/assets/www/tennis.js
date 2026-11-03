/* Mr 2 Odds — TENNIS section (separate from football).
   Reads only the tennis scanner's published files (data/app/tennis/…, tennis-data branch). Nothing here touches the
   football data, views, pages or trackers: the sport switch wraps the five tab views and renders the tennis version
   when settings.sport === 'tennis'; otherwise the original football view runs untouched (plus the switch bar).
   Wording is statistical: model probability, fair odds, bookmaker odds, market implied, edge, data quality —
   never "safe" / "banker" / "lock". Missing data is N/A, never 0. */
(function (PR) {
  'use strict';
  const { $, $$, esc, state, settings, icon, koShort, segmented, pct, toast } = PR;
  const TENNIS_BASE = 'https://raw.githubusercontent.com/perfectndumiso1-netizen/goals-scanner/tennis-data/';
  const LS = 'https://prod-public-api.livescore.com/v1/api/app';
  const T = { data: null, details: {}, days: {}, index: null, live: null, liveAt: 0, liveLoading: false, view: 'today', family: 'all', matchView: 'overview',
    liveView: 'inplay', mf: 'all', search: '', loading: false, error: null, loadedAt: 0, timer: null };
  PR.tennis = T;
  const view = () => $('#view');
  const isTennis = () => settings.sport === 'tennis';
  if (!document.getElementById('tennis-css')) {
    const st = document.createElement('style'); st.id = 'tennis-css';
    st.textContent = `.sport-bar{display:flex;gap:3px;margin:0 0 10px;background:var(--card-2);border:1px solid var(--line);padding:3px;border-radius:10px}
.sport-bar button{flex:1;border:0;background:transparent;color:var(--muted);border-radius:7px;padding:8px 10px;font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .2s,color .2s}
.sport-bar button.on{background:var(--seg-on);color:var(--brand-text);box-shadow:var(--seg-shadow)}
.sport-bar button.on.tn{color:var(--good)}
.tn-hero .eyebrow{color:var(--good)}
.tn-item{padding:9px 0;border-top:1px solid var(--line-2)}.tn-item:first-child{border-top:0;padding-top:4px}
.tn-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:4px;margin-top:6px}.tn-grid>div{background:var(--card-2);border:1px solid var(--line-2);border-radius:8px;padding:5px 2px;text-align:center;font-size:12px;font-weight:600;line-height:1.25}
.tn-grid .cap{display:block;font-size:9px;font-weight:600;color:var(--muted);letter-spacing:.4px;text-transform:uppercase}.tn-grid>div.hi{background:var(--accent-soft);border-color:transparent;color:var(--good)}.tn-grid>div.mid{background:var(--warn-soft);border-color:transparent;color:var(--warn)}
.tn-grid>div.neg{color:var(--bad)}.tn-grid>div.pos{color:var(--good)}
.tn-sets{display:inline-flex;gap:6px;font-variant-numeric:tabular-nums;font-weight:700}.tn-sets span{min-width:12px;text-align:center}.tn-sets span.lost{color:var(--muted);font-weight:500}
.tn-ev{display:inline-block;font-size:10px;font-weight:700;padding:1px 6px;border-radius:5px;background:var(--chip);color:var(--muted);margin-left:4px}
.tn-ev.s{background:var(--accent-soft);color:var(--good)}.tn-ev.w{background:var(--warn-soft);color:var(--warn)}
.tn-wl{display:inline-flex;gap:2px}.tn-wl i{font-style:normal;width:16px;height:16px;border-radius:4px;font-size:10px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;color:#fff;background:var(--neutral-fill)}
.tn-wl i.W{background:var(--good)}.tn-wl i.L{background:var(--bad)}
.tn-strong{font-size:10px;font-weight:700;color:var(--good);background:var(--accent-soft);border-radius:5px;padding:1px 6px;margin-left:4px;letter-spacing:.4px}
.sport-bar .cnt{display:inline-block;min-width:18px;padding:0 5px;border-radius:999px;background:var(--chip);color:var(--muted);font-size:11px;margin-left:6px;line-height:18px;font-weight:600}
.sport-bar button.on .cnt{background:var(--brand-soft);color:var(--brand-text)}
.sport-bar button.on.tn .cnt{background:var(--accent-soft);color:var(--good)}
.tn-fb .ico{background:var(--accent-soft);color:var(--good);font-size:15px}
.tn-fb-foot{display:flex;align-items:center;gap:8px;margin-top:6px}`;
    document.head.appendChild(st);
  }
  // ------------------------------------------------------------------ helpers
  const cell = (cap, val, cls) => `<div class="${cls || ''}"><span class="cap">${cap}</span>${val}</div>`;
  const edgeCls = (x) => (x == null || isNaN(x)) ? '' : x >= 0 ? 'pos' : 'neg';
  const head = (title, sub, right) => `<div class="detail-head"><button class="back" id="back" aria-label="Back">${icon('back')}</button><div class="grow"><div class="b">${title}</div>${sub ? `<div class="tiny muted">${sub}</div>` : ''}</div>${right || ''}</div>`;
  const wireBack = () => { const b = $('#back'); if (b) b.onclick = () => PR.back(); };
  const pc = (x, d) => (x == null || isNaN(x)) ? 'N/A' : (x * 100).toFixed(d == null ? 1 : d) + '%';
  const od = (x) => (x == null || isNaN(x)) ? 'N/A' : Number(x).toFixed(2);
  const pp = (x) => (x == null || isNaN(x)) ? 'N/A' : (x >= 0 ? '+' : '') + Number(x).toFixed(1) + ' pp';
  const f1 = (x) => (x == null || isNaN(x)) ? 'N/A' : Number(x).toFixed(1);
  const qcls = (s) => s >= 80 ? 'hi' : s >= 60 ? 'mid' : '';
  const ppill = (p) => `<span class="pill ${p >= 0.7 ? 'hi' : p >= 0.6 ? 'mid' : ''}">${pc(p, 0)}</span>`;
  const sh = (ico, title, cls) => `<h2><span class="ico ${cls || ''}">${icon(ico)}</span>${title}</h2>`;
  const MARKET = { winner: 'Match winner', total_games: 'Total games', p1_games: 'Player games', p2_games: 'Player games', game_handicap: 'Game handicap' };
  const FAMILIES = [['all', 'All markets'], ['Match winner', 'Match winner'], ['Total games', 'Total games'], ['Player games', 'Player games'], ['Game handicap', 'Game handicap']];
  const EVIDENCE = [[40, 'Very strong'], [20, 'Strong'], [10, 'Moderate'], [5, 'Small'], [1, 'Very small']];
  function evidenceLabel(n) { if (!n || n < 1) return 'No data'; for (const [lo, name] of EVIDENCE) if (n >= lo) return name; return 'Very small'; }
  const evChip = (n, what) => `<span class="tn-ev ${n >= 20 ? 's' : n >= 10 ? '' : 'w'}">${n || 0} ${what || 'matches'} · ${evidenceLabel(n)}</span>`;
  const IOC = { RSA: '🇿🇦', USA: '🇺🇸', ESP: '🇪🇸', ITA: '🇮🇹', FRA: '🇫🇷', GER: '🇩🇪', GBR: '🇬🇧', AUS: '🇦🇺', ARG: '🇦🇷', BRA: '🇧🇷', SRB: '🇷🇸', RUS: '🇷🇺', CZE: '🇨🇿', POL: '🇵🇱', GRE: '🇬🇷', NOR: '🇳🇴', DEN: '🇩🇰', SUI: '🇨🇭', CAN: '🇨🇦', JPN: '🇯🇵', CHN: '🇨🇳', KAZ: '🇰🇿', BUL: '🇧🇬', NED: '🇳🇱', BEL: '🇧🇪', AUT: '🇦🇹', CRO: '🇭🇷', HUN: '🇭🇺', ROU: '🇷🇴', UKR: '🇺🇦', BLR: '🇧🇾', SWE: '🇸🇪', FIN: '🇫🇮', POR: '🇵🇹', CHI: '🇨🇱', COL: '🇨🇴', PER: '🇵🇪', MEX: '🇲🇽', IND: '🇮🇳', KOR: '🇰🇷', TPE: '🇹🇼', TUN: '🇹🇳', EGY: '🇪🇬', TUR: '🇹🇷', SVK: '🇸🇰', SLO: '🇸🇮', LAT: '🇱🇻', LTU: '🇱🇹', EST: '🇪🇪', GEO: '🇬🇪', ISR: '🇮🇱', BIH: '🇧🇦', MDA: '🇲🇩', URU: '🇺🇾', ECU: '🇪🇨', BOL: '🇧🇴', THA: '🇹🇭', INA: '🇮🇩', PHI: '🇵🇭', NZL: '🇳🇿', IRL: '🇮🇪', LUX: '🇱🇺', MON: '🇲🇨', CYP: '🇨🇾', ARM: '🇦🇲', UZB: '🇺🇿', AZE: '🇦🇿', MAR: '🇲🇦', ZIM: '🇿🇼', NGR: '🇳🇬', VEN: '🇻🇪', PAR: '🇵🇾', DOM: '🇩🇴', HKG: '🇭🇰', VIE: '🇻🇳' };
  const flag = (ioc) => IOC[ioc] || '';
  /** UTC "YYYY-MM-DD HH:MM" → local (SAST by default) "Day HH:MM" */
  function localStart(s, timeOnly) {
    if (!s) return '';
    const m = String(s).match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/); if (!m) return s;
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) + (PR.settings.tzOffset || 0) * 3600000);
    const hm = `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
    return timeOnly ? hm : `${PR.DAYS[d.getUTCDay()]} ${hm}`;
  }
  const todaySast = () => { const d = new Date(Date.now() + (PR.settings.tzOffset || 0) * 3600000); return d.toISOString().slice(0, 10); };
  const dayLabel = (day) => { if (!day) return ''; const t = todaySast(); if (day === t) return 'Today'; const d = new Date(day + 'T00:00:00Z'); const n = new Date(t + 'T00:00:00Z'); const diff = Math.round((d - n) / 86400000); if (diff === 1) return 'Tomorrow'; if (diff === -1) return 'Yesterday'; return `${PR.DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${PR.MONTHS[d.getUTCMonth()]}`; };
  const wl = (list) => `<span class="tn-wl">${(list || []).map((r) => `<i class="${r.won ? 'W' : 'L'}">${r.won ? 'W' : 'L'}</i>`).join('')}</span>`;
  const rankTxt = (p) => p && p.last_rank && p.last_rank.rank ? `#${p.last_rank.rank}` : '';
  const formTxt = (p) => p && p.form10 && p.form10.n ? `${p.form10.wins}–${p.form10.n - p.form10.wins} last ${p.form10.n}` : '';

  // ------------------------------------------------------------------ data
  T.load = async function (force) {
    if (T.loading) return;
    if (!force && T.data && Date.now() - T.loadedAt < 5 * 60000) return;
    T.loading = true; T.error = null;
    if (!T.data) { try { const c = PR.stored ? PR.stored('pr_tennis_latest') : localStorage.getItem('pr_tennis_latest'); if (c) T.data = JSON.parse(c); } catch (e) { /* ignore */ } }
    try {
      const j = await PR.getJson(TENNIS_BASE + 'data/app/tennis/latest.json?t=' + Math.floor(Date.now() / 60000));
      if (j && j.meta && j.meta.sport === 'tennis') { T.data = j; T.loadedAt = Date.now(); (PR.saveAux || (() => false))('pr_tennis_latest', JSON.stringify(j)); }
    } catch (e) { T.error = String(e.message || e); }
    T.loading = false;
    // The football Home also receives a small tennis strip; redraw it when that independent feed
    // finishes loading so a fresh install does not need another navigation to reveal the strip.
    if (isTennis() || state.tab === 'home') { PR.render(); T.statusLine(); }
  };
  T.detail = function (id) {
    const key = String(id);
    if (T.details[key]) return T.details[key];
    T.details[key] = { loading: true };
    PR.getJson(TENNIS_BASE + `data/app/tennis/matches/${key}.json?t=` + Math.floor(Date.now() / 60000))
      .then((j) => { T.details[key] = j; }).catch((e) => { T.details[key] = { error: String(e.message || e) }; })
      .then(() => { const top = state.stack[state.stack.length - 1]; if (top && top.type === 'tennisMatch' && String(top.id) === key) PR.render(); });
    return T.details[key];
  };
  T.day = function (day) {
    if (T.days[day] && !T.days[day].stale) return T.days[day];
    const cur = T.days[day] || { loading: true }; T.days[day] = cur;
    PR.getJson(TENNIS_BASE + `data/app/tennis/days/${day}.json?t=` + Math.floor(Date.now() / 300000))
      .then((j) => { T.days[day] = j; }).catch((e) => { T.days[day] = cur.matches ? cur : { error: String(e.message || e) }; })
      .then(() => { if (isTennis()) PR.render(); });
    return cur;
  };
  T.loadIndex = function () {
    if (T.index && Date.now() - (T.index._at || 0) < 5 * 60000) return T.index;
    if (!T.index) T.index = { loading: true, _at: 0 }; else T.index._at = Date.now();
    PR.getJson(TENNIS_BASE + 'data/app/tennis/days/index.json?t=' + Math.floor(Date.now() / 300000))
      .then((j) => { T.index = { days: j.days || [], _at: Date.now() }; }).catch((e) => { T.index = T.index && T.index.days ? T.index : { error: String(e.message || e), _at: Date.now() }; })
      .then(() => { if (isTennis() && state.tab === 'days') PR.render(); });
    return T.index;
  };
  const SKIP = /doubles|davis cup|billie jean|laver cup|united cup|team tournaments|hopman|exhibition|itf|juniors|wheelchair|legends/i;
  /** Livescore tennis day feed (ATP/WTA/Challengers singles), in the user's timezone; refreshed at most once a minute */
  T.liveRefresh = async function (manual) {
    // the rate limit counts attempts, not successes: a feed that is down must not be re-requested on every
    // render (the view below calls this on each render, so a failed try that left the limit untouched turned
    // into render → refresh → render, which starves the event loop on a phone with no connection)
    if (T.liveLoading) return; if (!manual && T.live && Date.now() - Math.max(T.liveAt || 0, T.liveTry || 0) < 55000) return;
    T.liveLoading = true;
    const hadErr = T.liveErr || null;
    let ok = false;
    try {
      const day = todaySast().replace(/-/g, '');
      const j = await PR.getJson(`${LS}/date/tennis/${day}/${PR.settings.tzOffset || 0}?MD=1`);
      const events = [];
      (j.Stages || []).forEach((st) => {
        const cat = (st.Cnm || '').trim(), name = (st.Snm || '').trim(); if (SKIP.test(`${cat} ${name}`)) return;
        if (!/^(ATP|WTA|Challenger|Grand Slam|Olympic)/i.test(cat) && !/challenger/i.test(name)) return;
        (st.Events || []).forEach((ev) => {
          const t1 = ev.T1 || [], t2 = ev.T2 || []; if (t1.length !== 1 || t2.length !== 1) return;
          const sets = []; for (let i = 1; i <= 5; i++) { const a = ev['Tr1S' + i], b = ev['Tr2S' + i]; if (a == null || a === '' || b == null || b === '') break; sets.push([+a, +b]); }
          const eps = String(ev.Eps || ''); const epr = ev.Epr;
          const finished = epr === 2 || eps === 'FT' || /^ret|^w\.?o|^def/i.test(eps);
          const live = !finished && (epr === 1 || (sets.length > 0 && eps !== 'NS') || /set|in play/i.test(eps));
          events.push({ id: String(ev.Eid), category: cat, tournament: name, p1: t1[0].Nm, p2: t2[0].Nm, ioc1: t1[0].CoId, ioc2: t2[0].CoId, sets, sw: [ev.Tr1, ev.Tr2], status: eps, live, finished,
            start: ev.Esd ? String(ev.Esd) : '', winner: ev.Ewt || (finished && ev.Tr1 != null && ev.Tr2 != null ? (+ev.Tr1 > +ev.Tr2 ? 1 : +ev.Tr2 > +ev.Tr1 ? 2 : null) : null), pts: ev.Tr1G != null ? [ev.Tr1G, ev.Tr2G] : null });
        });
      });
      T.live = events; T.liveAt = Date.now(); T.liveErr = null; ok = true;
    } catch (e) { if (!T.live) T.live = []; T.liveErr = String(e.message || e); }
    T.liveLoading = false;
    T.liveTry = Date.now();
    // re-render only when something changed — a repeat failure is already on screen
    if (isTennis() && !state.stack.length && (state.tab === 'live' || state.tab === 'home') && (ok || T.liveErr !== hadErr)) PR.render();
  };
  T.liveFor = (id) => (T.live || []).find((e) => e.id === String(id)) || null;

  // ------------------------------------------------------------------ favourites (tennis's own list, like football's)
  let tFavs = [];
  try { tFavs = JSON.parse(PR.stored('pr_tennis_favs') || '[]') || []; } catch (e) { tFavs = []; }
  const isTFav = (id) => tFavs.some((f) => String(f.id) === String(id));
  const tnFavList = () => tFavs;
  const localStartFull = (s) => {
    const m = String(s || '').match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/); if (!m) return '';
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) + (PR.settings.tzOffset || 0) * 3600000);
    const p = (x) => String(x).padStart(2, '0');
    return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
  };
  function saveTFavs() {
    const keep = todaySast();
    tFavs = tFavs.filter((f) => (f.kickoff || '').slice(0, 10) >= keep);
    PR.persist('pr_tennis_favs', JSON.stringify(tFavs));
    try { if (PR.native && PR.native.setString) PR.native.setString('tennis_favs', JSON.stringify(tFavs.map((f) => ({ eid: String(f.id), kickoff: f.kickoff, home: f.home, away: f.away, competition: [f.category, f.tournament].filter(Boolean).join(' · '), label: 'Tennis' })))); } catch (e) { /* ignore */ }
  }
  function toggleTFav(m) {
    if (!m || !m.id) return;
    const id = String(m.id);
    if (isTFav(id)) { tFavs = tFavs.filter((f) => String(f.id) !== id); toast('Removed from favourites'); }
    else {
      const ko = localStartFull(m.start);
      if (ko && ko.slice(0, 10) < todaySast()) { toast('This match already started — too late to track it'); return; }
      tFavs.push({ id, kickoff: ko, home: m.p1 && m.p1.name, away: m.p2 && m.p2.name, tournament: m.tournament || '', category: m.category || '' });
      toast('Added to favourites — kick-off and result alerts');
    }
    saveTFavs(); PR.render();
  }
  PR.tennisFavBtn = function (m) {
    if (!m || !m.id) return '';
    const on = isTFav(m.id);
    return `<button class="tnfavbtn ${on ? 'on' : ''}" data-tnfav="${esc(m.id)}" title="${on ? 'Remove from favourites' : 'Add to favourites'}" aria-label="Favourite">${on ? '★' : '☆'}</button>`;
  };
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-tnfav]'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    const m = matchById(b.dataset.tnfav);
    if (m) toggleTFav(m);
    else { const lv = T.liveFor && T.liveFor(b.dataset.tnfav); if (lv && lv.start && lv.start.length === 12) toggleTFav({ id: lv.id, start: `${lv.start.slice(0, 4)}-${lv.start.slice(4, 6)}-${lv.start.slice(6, 8)} ${lv.start.slice(8, 10)}:${lv.start.slice(10, 12)}`, p1: { name: lv.p1 }, p2: { name: lv.p2 }, tournament: lv.tournament, category: lv.category }); }
  }, true);
  T.statusLine = function () {
    const el = $('#status-line'); if (!el || !isTennis()) return;
    const d = T.data;
    const txt = d ? `🎾 Tennis · updated ${esc(koShort(d.meta.generated_sast || d.meta.generated))} · ${(d.matches || []).length} matches · ${(d.selections || []).length} selections` : '🎾 Tennis analysis · loading…';
    if (el.textContent !== txt) el.textContent = txt;
  };

  // ------------------------------------------------------------------ sport switch (wraps the five tab views; football untouched)
  function sportBar() {
    const fb = state.data && state.data.safe && state.data.safe.today && state.data.safe.today.bets ? state.data.safe.today.bets.length : null;
    const tn = T.data && T.data.selections ? T.data.selections.length : null;
    return `<div class="sport-bar" id="sport-bar"><button class="${isTennis() ? '' : 'on'}" data-sport="football">⚽ Football${fb != null ? `<span class="cnt">${fb}</span>` : ''}</button><button class="${isTennis() ? 'on tn' : ''}" data-sport="tennis">🎾 Tennis${tn != null ? `<span class="cnt">${tn}</span>` : ''}</button></div>`;
  }
  function addSportBar() {
    const v = view(); if (!v || $('#sport-bar')) return;
    v.insertAdjacentHTML('afterbegin', sportBar());
    $$('#sport-bar button').forEach((b) => { b.onclick = () => T.setSport(b.dataset.sport); });
  }
  /** Tennis on the FOOTBALL home screen (Sofascore-style: both sports visible on one page) — the day's tennis selections,
      grouped by market, inserted right after the football "Bets of the day" card. Tennis keeps its own data and tracker. */
  function addTennisCard() {
    const v = view(); if (!v || $('#tn-fb-card')) return;
    const d = T.data; const sels = (d && d.selections) || []; const secs = (d && d.sections) || []; const strong = (d && d.strong) || []; const inPlay = (T.live || []).filter((e) => e.live).length;
    const headHtml = `<div class="section-head tn-fb" id="tn-fb-head"><h2><span class="ico">🎾</span>Tennis · selections of the day</h2><button class="link" data-sport-go="tennis">Open tennis ${icon('next')}</button></div>`;
    let body;
    if (!d) body = `<div class="card empty small" id="tn-fb-card">${T.error ? 'Tennis analysis could not be loaded — pull down to refresh.' : 'Loading the tennis analysis…'}</div>`;
    else if (!sels.length) body = `<div class="card empty small" id="tn-fb-card">No tennis match clears the selection rules right now (model ≥ 60%, data quality ≥ 60%). ${(d.matches || []).length} matches analysed — open the tennis section for every market.</div>`;
    else {
      let left = 4;
      const rows = secs.map((g) => { if (left <= 0) return ''; const take = g.selections.slice(0, Math.min(2, left)); left -= take.length; return `<div class="botd-sec">${esc(g.title)} <span class="muted">· ${g.selections.length}</span></div><table class="tbl">${take.map((x) => selRow(x, { day: true })).join('')}</table>`; }).join('');
      body = `<div class="card botd" id="tn-fb-card">${rows}<div class="tn-fb-foot tiny muted"><div class="grow">${sels.length} matches · one preferred market each · ${strong.length} strong${inPlay ? ` · <span class="good">${inPlay} in play</span>` : ''}</div><button class="link" data-sport-go="tennis" data-tn-view="today">All ${sels.length} ${icon('next')}</button></div></div>`;
    }
    // after the football "Bets of the day" card (section head + card), else after the hero
    const heads = $$('#view .section-head'); const botd = heads.find((h) => /Bets of the day/i.test(h.textContent));
    const anchor = botd && botd.nextElementSibling ? botd.nextElementSibling : $('#view .card.hero');
    if (anchor) anchor.insertAdjacentHTML('afterend', headHtml + body); else v.insertAdjacentHTML('beforeend', headHtml + body);
    // one-time intro (dismissible) so the new placement is noticed after the update
    const hero = $('#view .card.hero');
    if (hero && !settings.tnIntroSeen && !$('#tn-intro')) {
      hero.insertAdjacentHTML('beforebegin', `<div class="card tn-fb" id="tn-intro"><div class="row"><span class="ico">🎾</span><div class="grow"><b>New: tennis is on your home screen</b><div class="tiny muted">The ⚽ / 🎾 bar above switches the whole app between the two sports. The tennis strip and the "Tennis · selections of the day" card below sit on this page — one preferred market per match, strong markets, and a match page with Overview / Markets / Stats / Data.</div>
        <div class="row" style="gap:8px;margin-top:8px"><button class="btn primary" data-sport-go="tennis">Open tennis</button><button class="btn" id="tn-intro-ok">Got it</button></div></div></div></div>`);
    }
    // plus a one-line strip directly under the hero, so tennis is visible above the fold (the football card can be long)
    if (hero && d && !$('#tn-fb-strip')) {
      const top = sels[0];
      hero.insertAdjacentHTML('afterend', `<div class="card compact tap tn-fb" id="tn-fb-strip" data-sport-go="tennis"><div class="row"><span class="ico">🎾</span><div class="grow"><b>Tennis · ${sels.length} selection${sels.length === 1 ? '' : 's'} of the day</b><div class="tiny muted">${top ? `${strong.length} strong · top: ${esc(top.label)} ${pc(top.model_p, 0)} @ ${od(top.book_odds)} · ${esc(top.tournament)}` : `${(d.matches || []).length} matches analysed · every market with model, fair odds, Sportybet, implied and edge`}${inPlay ? ` · <span class="good">${inPlay} in play</span>` : ''}</div></div>${icon('next')}</div></div>`);
    }
    $$('[data-sport-go]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); if (b.dataset.tnView) T.view = b.dataset.tnView; settings.tnIntroSeen = PR.APP_VERSION || '1'; PR.saveSettings(); T.setSport('tennis'); }; });
    const ok = $('#tn-intro-ok'); if (ok) ok.onclick = (e) => { e.stopPropagation(); settings.tnIntroSeen = PR.APP_VERSION || '1'; PR.saveSettings(); PR.render(); };
  }
  T.setSport = function (sport) {
    if ((sport === 'tennis') === isTennis()) return;
    settings.sport = sport; PR.saveSettings(); state.stack = [];
    if (sport === 'tennis') { T.load(false); T.liveRefresh(false); } else if (PR.statusLine) PR.statusLine();
    PR.setTab(state.tab || 'home');
    PR.toast(sport === 'tennis' ? '🎾 Tennis — separate data, model and tracker' : '⚽ Football');
  };
  T.views = {};
  ['home', 'bets', 'live', 'matches', 'days'].forEach((tab) => {
    const orig = PR.views[tab];
    PR.views[tab] = function () {
      if (isTennis()) {
        try { T.views[tab](); } catch (e) { view().innerHTML = `<div class="card empty">The tennis screen hit an error (${esc(e.message || e)}). Pull to refresh.</div>`; }
        T.statusLine();
        if (tab === 'live' || tab === 'home') T.liveRefresh(false);
      } else { orig.apply(this, arguments); }   // football Home no longer carries tennis (user, 2026-10-09) — the ⚽ / 🎾 bar opens it
      addSportBar();
    };
  });
  // refresh button (app.js assigns it after this file loads → wrap on the next tick); pull-to-refresh goes through app.refresh → PR.loadData, also wrapped
  setTimeout(() => {
    const btn = $('#btn-refresh'); if (btn) { const prev = btn.onclick; btn.onclick = function (e) { if (isTennis()) { T.load(true); T.liveRefresh(true); T.index = null; Object.keys(T.days).forEach((k) => { T.days[k].stale = true; }); } if (prev) return prev.call(this, e); }; }
    const origLoad = PR.loadData; if (origLoad) PR.loadData = function (force) { if (isTennis() && force) { T.load(true); T.liveRefresh(true); } return origLoad.apply(this, arguments); };
    if (isTennis()) { T.load(false); T.liveRefresh(false); } else setTimeout(() => T.load(false), 1200);
  }, 0);
  T.timer = setInterval(() => { if (!isTennis() || document.hidden) return; T.statusLine(); if (!state.stack.length && (state.tab === 'live' || (state.tab === 'home' && (T.live || []).some((e) => e.live)))) T.liveRefresh(false); }, 60000);
  // the ⋮ menu entry switches sport (kept as a page type for older links)
  PR.pages.tennis = function () { T.setSport('tennis'); if (isTennis() && state.stack.length) { state.stack = []; PR.render(); } };
  const menuBtn = document.querySelector('#menu [data-page="tennis"]');
  if (menuBtn) { menuBtn.removeAttribute('data-page'); menuBtn.setAttribute('data-sport-menu', '1'); menuBtn.innerHTML = '🎾 / ⚽ Switch sport'; menuBtn.onclick = () => { PR.closeMenu(); T.setSport(isTennis() ? 'football' : 'tennis'); }; }

  // ------------------------------------------------------------------ shared rows
  const notLoaded = () => `<div class="card empty">${T.error ? `Tennis analysis could not be loaded (${esc(T.error)}). It is published four times a day — pull down to refresh.` : 'Loading tennis analysis…'}</div>`;
  const matchById = (id) => ((T.data && T.data.matches) || []).find((m) => String(m.id) === String(id));
  function setsHtml(e) {
    if (!e || !e.sets || !e.sets.length) return '';
    return `<span class="tn-sets">${e.sets.map(([a, b]) => `<span class="${a < b ? 'lost' : ''}">${a}</span>`).join('')}</span>`;
  }
  function setsHtml2(e) { if (!e || !e.sets || !e.sets.length) return ''; return `<span class="tn-sets">${e.sets.map(([a, b]) => `<span class="${b < a ? 'lost' : ''}">${b}</span>`).join('')}</span>`; }
  /** Sofascore-style match row: time / status, two player lines, model % or score on the right */
  function matchRow(m, opts) {
    opts = opts || {}; const lv = opts.live || T.liveFor(m.id);
    const res = m.result; const finished = (lv && lv.finished) || !!res;
    const live = lv && lv.live;
    const left = live ? `<div class="minute on">${esc(lv.status || 'live')}</div>` : finished ? `<div class="minute ft">${res && res.retired ? 'Ret.' : 'FT'}</div>` : `<div class="ko">${esc(localStart(m.start)).replace(' ', '<br>')}</div>`;
    const w1 = finished ? ((lv && lv.winner === 1) || (res && res.winner === 1)) : false, w2 = finished ? ((lv && lv.winner === 2) || (res && res.winner === 2)) : false;
    const scoreSrc = lv && lv.sets && lv.sets.length ? lv : (res && res.score ? { sets: res.score.split(' ').map((s) => s.split('-').map(Number)) } : null);
    const ln = (p, won, sets) => `<div class="tm ${won ? 'won' : ''}"><span class="nm">${flag(p.ioc)} ${esc(p.name)} <span class="tiny muted">${rankTxt(p)}${p.rating != null ? ` · ${Math.round(p.rating)}` : ''}</span></span>${sets || ''}</div>`;
    const sub = opts.sub != null ? opts.sub : `${esc(m.category)} · ${esc(m.tournament)}${m.qualifying ? ' (Q)' : ''} · ${esc(m.surface || 'surface N/A')}`;
    const right = opts.right != null ? opts.right : `<div>${ppill(m.p.a)}</div><div>${ppill(m.p.b)}</div>`;
    return `<div class="mrow tap ${live ? 'is-live' : ''}" data-tennis="${esc(m.id)}"><div class="mrow-l">${left}</div>
      <div class="mrow-m">${ln(m.p1, w1, scoreSrc ? setsHtml(scoreSrc) : '')}${ln(m.p2, w2, scoreSrc ? setsHtml2(scoreSrc) : '')}<div class="sub">${sub}</div></div>
      <div class="mrow-r">${right}${PR.tennisFavBtn ? PR.tennisFavBtn(m) : ''}</div></div>`;
  }
  const outcome = (won) => won === '1' ? '<span class="good">✅ won</span>' : won === '0' ? '<span class="bad">❌ lost</span>' : won === 'void' ? '<span class="muted">void</span>' : '';
  /** selection row (football safeRow layout): time · match + selection + context · odds · model pill */
  function selRow(x, opts) {
    opts = opts || {}; const m = opts.match || matchById(x.match_id) || {};
    const lv = T.liveFor(x.match_id); const won = x.won; const live = lv && lv.live;
    const name = x.match || (m.p1 ? `${m.p1.name} v ${m.p2.name}` : '');
    return `<tr class="tap" data-tennis="${esc(x.match_id)}"><td class="tiny muted nowrap">${esc(opts.day ? localStart(x.start) : localStart(x.start, true))}</td>
      <td><div class="b">${esc(name)}</div><div class="sel"><b>${esc(x.label)}</b>${x.strong ? '<span class="tn-strong">STRONG</span>' : ''}</div>
      <div class="tiny muted">${esc(x.tournament || m.tournament || '')} · ${esc(MARKET[x.market] || x.market)} · market ${pc(x.implied_fair, 0)} · <span class="${x.quality >= 80 ? 'pos' : x.quality < 60 ? 'warn' : ''}">data ${x.quality}%</span>${won ? ` · ${outcome(won)}` : live ? ` · <span class="good">live ${esc(lv.status)}</span>` : ''}</div></td>
      <td class="right nowrap"><b>${od(x.book_odds)}</b><div class="tiny muted">fair ${od(x.fair_odds)}</div></td><td class="right"><div class="row" style="gap:0;justify-content:flex-end">${ppill(x.model_p)}${PR.tennisAddBtn ? PR.tennisAddBtn(x.match_id, x) : ''}</div></td></tr>`;
  }
  const rulesCard = (d) => `<div class="card tiny muted"><b>How selections are chosen.</b> ${esc((d.rules || {}).day || '')}. <b>STRONG</b> = ${esc((d.rules || {}).strong || '')}. Ranked by model probability — the bookmaker is a check, never an input. A 70% selection still loses three times in ten; data quality describes the evidence, not the chance of winning.</div>`;
  function perfCard(tr, compact) {
    if (!tr || !tr.settled) return compact ? '' : `<div class="card empty small">No settled tennis selections yet — results are graded automatically after each match (retirements void the game markets).</div>`;
    const rows = [['day', 'Selections of the day'], ['strong', 'Strong markets'], ['highlight', 'Model above market'], ['favourite', 'Rating favourite (every priced match)']]
      .map(([k, l]) => [l, (tr.by_kind || {})[k]]).filter(([, v]) => v && v.settled);
    const line = (l, v) => `<tr><td>${esc(l)}</td><td class="right"><b>${v.won}/${v.settled}</b></td><td class="right">${pc(v.hit_rate, 0)}</td><td class="right muted">${pc(v.avg_model_p, 0)}</td><td class="right ${v.flat_return_units > 0 ? 'good' : v.flat_return_units < 0 ? 'bad' : ''}">${v.flat_return_units > 0 ? '+' : ''}${v.flat_return_units == null ? 'N/A' : v.flat_return_units.toFixed(1)}</td></tr>`;
    return `<div class="section-head">${sh('chart', 'Tennis record', 'green')}</div><div class="card compact"><table class="tbl head"><tr><th>Group</th><th class="right">Won</th><th class="right">Hit</th><th class="right">Model avg</th><th class="right">Units</th></tr>${rows.map(([l, v]) => line(l, v)).join('')}${compact ? '' : Object.entries(tr.by_market || {}).filter(([, v]) => v.settled).map(([k, v]) => line(`Market: ${MARKET[k] || k}`, v)).join('')}</table>
      <div class="tiny muted" style="margin-top:4px">Hit rate should sit close to the average model probability if the model is calibrated; ${tr.settled} settled so far (${evidenceLabel(tr.settled)} sample). Units = flat 1-unit stake at the recorded Sportybet price.</div></div>`;
  }

  // ------------------------------------------------------------------ HOME
  T.views.home = function () {
    if (!T.data) T.load(false);
    const d = T.data; const parts = [];
    if (!d) { view().innerHTML = notLoaded(); return; }
    const meta = d.meta, matches = d.matches || [], sels = d.selections || [], strong = d.strong || [], hl = d.highlights || [];
    const inPlay = (T.live || []).filter((e) => e.live);
    const today = todaySast(); const todaySels = sels.filter((s) => s.day_sast === today), tomorrowSels = sels.filter((s) => s.day_sast > today);
    parts.push(`<div class="card hero tn-hero"><div class="eyebrow">🎾 Tennis analysis · updated four times a day</div><div class="b" style="font-size:17px">${esc(PR.dayName(meta.generated_sast || ''))} · ${esc(koShort(meta.generated_sast || meta.generated).split(' ').pop())} SAST</div>
      <div class="tiny muted">${esc(meta.coverage)} · next ${meta.lookahead_hours} h · ${meta.priced || 0} priced by Sportybet</div>
      <div class="hero-nums"><div><b>${matches.length}</b><span>matches</span></div><div><b>${sels.length}</b><span>selections</span></div><div><b>${strong.length}</b><span>strong markets</span></div><div><b>${inPlay.length}</b><span>in play</span></div></div>
      ${inPlay.length ? `<div class="live-strip" data-tn-tab="live"><span class="status-dot live"></span><div class="grow"><b>${inPlay.length} in play</b> · ${inPlay.slice(0, 2).map((e) => `${esc(e.p1.split(' ').pop())} ${e.sets.map((s) => s.join('-')).join(' ')} ${esc(e.p2.split(' ').pop())}`).join(' · ')}${inPlay.length > 2 ? ' …' : ''}</div>${icon('next', 'sm')}</div>` : ''}</div>`);
    // selections of the day (grouped by market, like the football card)
    parts.push(`<div class="section-head">${sh('star', 'Selections of the day', 'amber')}<button class="link" data-tn-bets="today">Details ${icon('next')}</button></div>`);
    const secs = d.sections || [];
    if (!sels.length) parts.push(`<div class="card empty small">No match clears the selection rules right now (model ≥ 60%, data quality ≥ 60%, both players with 30+ rated matches). The next scan may add some.</div>`);
    else {
      const body = secs.map((g) => `<div class="botd-sec">${esc(g.title)} <span class="muted">· ${g.selections.length}</span></div><table class="tbl">${g.selections.slice(0, 4).map((x) => selRow(x, { day: true })).join('')}</table>`).join('');
      const settled = sels.filter((x) => x.won === '0' || x.won === '1');
      parts.push(`<div class="card botd">${body}<div class="row tiny muted" style="margin-top:6px"><div class="grow">${sels.length} matches · one preferred market each · ${strong.length} strong${todaySels.length && tomorrowSels.length ? ` · ${todaySels.length} today, ${tomorrowSels.length} tomorrow` : ''}</div>${settled.length ? `<div>${settled.filter((x) => x.won === '1').length}/${settled.length} won</div>` : ''}</div></div>`);
    }
    // your matches (favourites)
    const tf = tFavs.map((f) => matchById(f.id)).filter(Boolean).sort((a, b) => String(a.start).localeCompare(String(b.start)));
    if (tf.length) parts.push(`<div class="section-head">${sh('star', 'Your matches', 'amber')}</div><div class="card compact">${tf.slice(0, 5).map((m) => matchRow(m, { sub: `${esc(localStart(m.start))} · ${esc(m.category)} · ${esc(m.tournament)}${m.selection ? ` · <b>${esc(m.selection.label)}</b> ${pc(m.selection.model_p, 0)}` : ''}` })).join('')}</div>`);
    // strong markets
    if (strong.length) parts.push(`<div class="section-head">${sh('trend', 'Strong markets', 'green')}<button class="link" data-tn-bets="strong">All ${strong.length} ${icon('next')}</button></div><div class="card compact"><table class="tbl">${strong.slice(0, 5).map((x) => selRow(x, { day: true })).join('')}</table><div class="tiny muted" style="margin-top:4px">Model ≥ 70% and market implied ≥ 50%. Rows of the same match are correlated.</div></div>`);
    // model above market
    if (hl.length) parts.push(`<div class="section-head">${sh('alert', 'Model above market')}<button class="link" data-tn-bets="highlights">All ${hl.length} ${icon('next')}</button></div><div class="card compact"><table class="tbl">${hl.slice(0, 3).map((x) => selRow(x, { day: true })).join('')}</table><div class="tiny muted" style="margin-top:4px">Disagreements of 5–20 pp with the bookmaker — evidence to check, not recommendations. Every one is tracked.</div></div>`);
    // next matches
    const nowMs = Date.now(); const upcoming = matches.filter((m) => { const lv = T.liveFor(m.id); return !(lv && lv.finished) && Date.parse(m.start.replace(' ', 'T') + ':00Z') > nowMs - 3 * 3600000; }).sort((a, b) => a.start.localeCompare(b.start)).slice(0, 6);
    parts.push(`<div class="section-head">${sh('calendar', 'Next matches')}<button class="link" data-tn-tab="matches">All matches ${icon('next')}</button></div><div class="card compact">${upcoming.map((m) => matchRow(m, { sub: `${esc(m.category)} · ${esc(m.tournament)}${m.selection ? ` · <b>${esc(m.selection.label)}</b> ${pc(m.selection.model_p, 0)} @ ${od(m.selection.book_odds)}` : ''}` })).join('') || '<div class="empty small">No upcoming matches in the window.</div>'}</div>`);
    parts.push(perfCard(d.tracker, true));
    parts.push(`<div class="card compact"><div class="row" style="flex-wrap:wrap"><div class="grow b">Explore tennis</div></div><div class="chips"><button class="chip tapchip" data-tn-bets="all">${icon('target', 'sm')} All priced markets</button><button class="chip tapchip" data-tn-tab="days">${icon('history', 'sm')} Past days &amp; results</button><button class="chip tapchip" data-tn-guide="1">${icon('info', 'sm')} How the tennis model works</button></div></div>`);
    if (PR.editorCard) parts.push(PR.editorCard(true));
    if (PR.contactCard) parts.push(PR.contactCard(true));
    parts.push(`<div class="card"><div class="tiny muted">${esc(meta.note || '')} ${esc(meta.licence || '')} Statistical information, not betting advice. 18+.</div></div>`);
    view().innerHTML = parts.join('');
    wire();
  };
  function wire() {
    $$('[data-tn-bets]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); T.view = b.dataset.tnBets; PR.setTab('bets'); }; });
    $$('[data-tn-tab]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); PR.setTab(b.dataset.tnTab); }; });
    $$('[data-tn-guide]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); PR.push({ type: 'tennisGuide' }); }; });
    $$('[data-tnv]').forEach((b) => { b.onclick = () => { T.view = b.dataset.tnv; PR.render(); }; });
    $$('[data-tnf]').forEach((b) => { b.onclick = () => { T.family = b.dataset.tnf; PR.render(); }; });
    $$('[data-tnl]').forEach((b) => { b.onclick = () => { T.liveView = b.dataset.tnl; PR.render(); }; });
    $$('[data-tnm]').forEach((b) => { b.onclick = () => { T.mf = b.dataset.tnm; PR.render(); }; });
    $$('[data-tn-day]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); PR.push({ type: 'tennisDay', day: b.dataset.tnDay }); }; });
    $$('[data-tnfavs]').forEach((b) => { b.onclick = () => { T.favOnly = !T.favOnly; PR.render(); }; });
  }

  // ------------------------------------------------------------------ BETS (selections)
  T.views.bets = function () {
    if (!T.data) T.load(false);
    const d = T.data; if (!d) { view().innerHTML = notLoaded(); return; }
    const v = ['today', 'strong', 'highlights', 'all'].includes(T.view) ? T.view : 'today';
    const parts = [`<div class="card compact sticky-ish">${segmented([['today', `${icon('star')} Selections`], ['strong', `${icon('trend')} Strong`], ['highlights', `${icon('alert')} Model &gt; market`], ['all', `${icon('target')} All priced`]], v, 'tnv')}</div>`];
    const famChips = `<div class="chips small-chips" style="margin:2px 0 8px">${FAMILIES.map(([k, l]) => `<button class="chip tapchip ${T.family === k ? 'on' : ''}" data-tnf="${k}">${l}</button>`).join('')}</div>`;
    const byFam = (list) => T.family === 'all' ? list : list.filter((x) => (x.family || MARKET[x.market]) === T.family);
    if (v === 'today') {
      parts.push(rulesCard(d));
      const secs = (d.sections || []).filter((g) => T.family === 'all' || g.title === T.family);
      parts.push(famChips);
      if (!secs.length) parts.push('<div class="card empty">No selections in this group right now.</div>');
      secs.forEach((g) => parts.push(`<div class="section-head"><h2>${esc(g.title)} <span class="muted tiny">· ${g.selections.length}</span></h2></div><div class="card compact"><table class="tbl">${g.selections.map((x) => selRow(x, { day: true })).join('')}</table></div>`));
    } else if (v === 'strong') {
      const list = byFam(d.strong || []);
      parts.push(`<div class="card tiny muted"><b>Strong markets.</b> Every Sportybet-priced market where the model gives ≥ 70% and the bookmaker's margin-free probability is ≥ 50%. Several rows of one match are the same match — not independent evidence. Not a "safe bet" list: a 75% market loses one time in four.</div>`, famChips);
      parts.push(list.length ? `<div class="card compact"><table class="tbl">${list.map((x) => selRow(x, { day: true })).join('')}</table></div>` : '<div class="card empty">No strong markets in this group right now.</div>');
    } else if (v === 'highlights') {
      const list = (d.highlights || []).filter((x) => T.family === 'all' || MARKET[x.market] === T.family);
      parts.push(`<div class="card tiny muted"><b>Model above market.</b> ${esc((d.rules || {}).highlight || '')}. A disagreement means the model and the bookmaker weigh the evidence differently — the tracker records every one so the claim can be checked against results.</div>`, famChips);
      parts.push(list.length ? `<div class="card compact"><table class="tbl">${list.map((x) => selRow(x, { day: true })).join('')}</table></div>` : '<div class="card empty">No disagreement clears the thresholds in this group right now.</div>');
    } else {
      const ms = (d.matches || []).filter((m) => m.odds).sort((a, b) => b.p.a > 0.5 ? (b.p.a - a.p.a) : 0).sort((a, b) => Math.max(b.p.a, b.p.b) - Math.max(a.p.a, a.p.b));
      parts.push(`<div class="card tiny muted"><b>All priced matches</b> ranked by the model's favourite probability, with the Sportybet winner price, market implied and edge. Tap a match for total games, player games and handicap.</div>`);
      parts.push(`<div class="card compact"><table class="tbl head"><tr><th>Match</th><th class="right">Model</th><th class="right">Odds</th><th class="right">Edge</th></tr>${ms.map((m) => { const fa = m.p.a >= 0.5; const p = fa ? m.p.a : m.p.b; const o = fa ? m.odds.a : m.odds.b; const imp = fa ? m.odds.implied_a : (m.odds.implied_a == null ? null : 1 - m.odds.implied_a); const edge = imp == null ? null : (p - imp) * 100;
        return `<tr class="tap" data-tennis="${esc(m.id)}"><td><div class="b">${esc(fa ? m.p1.name : m.p2.name)} <span class="muted tiny">to beat</span> ${esc(fa ? m.p2.name : m.p1.name)}</div><div class="tiny muted">${esc(localStart(m.start))} · ${esc(m.tournament)} · data ${m.quality.score}%${m.selection ? ` · preferred: <b>${esc(m.selection.label)}</b> ${pc(m.selection.model_p, 0)}` : ''}</div></td><td class="right">${ppill(p)}</td><td class="right nowrap"><b>${od(o)}</b><div class="tiny muted">mkt ${pc(imp, 0)}</div></td><td class="right ${edgeCls(edge)}">${pp(edge)}</td></tr>`; }).join('')}</table></div>`);
    }
    if (PR.ticketsCard && PR.tickets && PR.tickets().some((t) => t.status === 'pending')) parts.push(PR.ticketsCard(true));
    parts.push(`<div class="card compact tap" data-tn-guide="1"><div class="row"><span class="ico">${icon('info')}</span><div class="grow"><b>How the tennis model works</b><div class="tiny muted">Ratings, surface, best-of-3 vs best-of-5, games, and why the bookmaker is never an input.</div></div>${icon('next')}</div></div>`);
    view().innerHTML = parts.join('');
    wire();
  };

  // ------------------------------------------------------------------ LIVE
  T.views.live = function () {
    if (!T.data) T.load(false);
    const parts = [];
    const v = T.liveView === 'all' ? 'all' : 'inplay';
    parts.push(`<div class="card compact sticky-ish">${segmented([['inplay', `${icon('live')} In play`], ['all', `${icon('calendar')} Today's matches`]], v, 'tnl')}</div>`);
    if (!T.live) { parts.push(T.liveErr ? `<div class="card empty">Live scores unavailable (${esc(T.liveErr)}).</div>` : '<div class="card empty">Loading live scores…</div>'); view().innerHTML = parts.join(''); wire(); T.liveRefresh(false); return; }
    const list = v === 'inplay' ? T.live.filter((e) => e.live) : T.live.slice();
    if (!list.length) parts.push(`<div class="card empty">${v === 'inplay' ? 'No ATP/WTA/Challenger singles match is in play right now.' : 'No matches today in the covered tours.'}</div>`);
    const groups = new Map(); list.forEach((e) => { const k = `${e.category} · ${e.tournament}`; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(e); });
    groups.forEach((evs, k) => {
      evs.sort((a, b) => (b.live - a.live) || (a.finished - b.finished) || a.start.localeCompare(b.start));
      parts.push(`<div class="card compact"><div class="row" style="padding:4px 0 2px"><div class="grow b">${esc(k)}</div><span class="tiny muted">${evs.length}</span></div>${evs.map((e) => {
        const m = matchById(e.id); const p1 = { name: e.p1, ioc: e.ioc1, rating: m && m.p1.rating, last_rank: m && m.p1.last_rank }, p2 = { name: e.p2, ioc: e.ioc2, rating: m && m.p2.rating, last_rank: m && m.p2.last_rank };
        const start = e.start ? `${e.start.slice(0, 4)}-${e.start.slice(4, 6)}-${e.start.slice(6, 8)} ${e.start.slice(8, 10)}:${e.start.slice(10, 12)}` : '';
        const fake = { id: e.id, start: m ? m.start : start, p1, p2, p: m ? m.p : { a: null, b: null }, category: e.category, tournament: e.tournament, surface: m && m.surface, qualifying: m && m.qualifying, result: e.finished ? { winner: e.winner, retired: /^ret|^w\.?o/i.test(e.status) } : null };
        const right = m ? `<div>${ppill(m.p.a)}</div><div>${ppill(m.p.b)}</div>` : '<span class="tiny muted">not analysed</span>';
        const sub = `${esc(e.category)} · ${esc(e.tournament)}${e.live && e.pts ? ` · <b>${esc(e.pts[0])}–${esc(e.pts[1])}</b>` : ''}${m && m.selection ? ` · <b>${esc(m.selection.label)}</b> ${pc(m.selection.model_p, 0)}` : ''}`;
        const row = matchRow(fake, { live: e, right, sub });
        return m ? row : row.replace('mrow tap', 'mrow').replace(/data-tennis="[^"]*"/, '');
      }).join('')}</div>`);
    });
    parts.push(`<div class="card tiny muted">Scores from Livescore for today (${esc(dayLabel(todaySast()))}, SAST), refreshed every minute while this screen is open. Only matches that were in the analysis window open a page; ITF, doubles and team events are outside coverage. Livescore publishes no tennis statistics.</div>`);
    view().innerHTML = parts.join('');
    wire();
  };

  // ------------------------------------------------------------------ MATCHES
  T.views.matches = function () {
    if (!T.data) T.load(false);
    const d = T.data; if (!d) { view().innerHTML = notLoaded(); return; }
    const parts = [];
    const q = (T.search || '').trim().toLowerCase();
    parts.push(`<div class="card compact sticky-ish"><div class="row"><input id="fx-search" type="search" placeholder="Search player or tournament…" value="${esc(T.search || '')}" style="flex:1"></div>
      ${segmented([['all', 'All'], ['atp', 'ATP'], ['wta', 'WTA'], ['ch', 'Challengers'], ['sel', `${icon('star')} With selection`]], T.mf, 'tnm')}${tFavs.length ? `<div class="chips small-chips" style="margin-top:6px"><button class="chip tapchip ${T.favOnly ? 'on' : ''}" data-tnfavs="1">${icon('star', 'sm')} Favourites (${tFavs.length})</button></div>` : ''}</div>`);
    let ms = (d.matches || []).slice();
    if (T.favOnly) ms = ms.filter((m) => isTFav(m.id));
    if (T.mf === 'atp') ms = ms.filter((m) => m.tour === 'atp' && !/challenger/i.test(m.category));
    else if (T.mf === 'wta') ms = ms.filter((m) => m.tour === 'wta' && !/challenger|125/i.test(m.category));
    else if (T.mf === 'ch') ms = ms.filter((m) => /challenger|125/i.test(m.category));
    else if (T.mf === 'sel') ms = ms.filter((m) => m.selection);
    if (q) ms = ms.filter((m) => `${m.p1.name} ${m.p2.name} ${m.tournament} ${m.category}`.toLowerCase().includes(q));
    const groups = new Map();
    ms.sort((a, b) => (a.category + a.tournament + a.start).localeCompare(b.category + b.tournament + b.start)).forEach((m) => { const k = `${m.category} · ${m.tournament}`; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(m); });
    groups.forEach((list, k) => {
      const m0 = list[0];
      parts.push(`<div class="card compact"><div class="row" style="padding:4px 0 2px"><div class="grow b">${esc(k)}</div><span class="chip">${esc(m0.surface || 'surface N/A')}</span><span class="chip">Bo${m0.best_of}</span></div>${list.map((m) => matchRow(m, { sub: `${esc(localStart(m.start))}${m.qualifying ? ' · qualifying' : ''} · data ${m.quality.score}%${m.selection ? ` · <b>${esc(m.selection.label)}</b> ${pc(m.selection.model_p, 0)} @ ${od(m.selection.book_odds)}` : m.odds ? ` · odds ${od(m.odds.a)} / ${od(m.odds.b)}` : ' · no price'}` })).join('')}</div>`);
    });
    if (!ms.length) parts.push(`<div class="card empty">${q ? 'No match found.' : 'No ATP/WTA/Challenger singles matches in the next 36 hours.'}</div>`);
    parts.push(`<div class="card tiny muted">${ms.length} of ${(d.matches || []).length} matches · window ${d.meta.lookahead_hours} h · ratings shown next to each name (Elo from results; 1500 = new player), ranking = last known ATP/WTA ranking in the archive.</div>`);
    view().innerHTML = parts.join('');
    wire();
    const inp = $('#fx-search'); if (inp) { inp.oninput = () => { T.search = inp.value; clearTimeout(T._st); T._st = setTimeout(() => { const pos = inp.selectionStart; PR.render(); const i2 = $('#fx-search'); if (i2) { i2.focus(); try { i2.setSelectionRange(pos, pos); } catch (e) { /* ignore */ } } }, 250); }; if (state.focusSearch) { state.focusSearch = false; inp.focus(); } }
  };

  // ------------------------------------------------------------------ DAYS
  T.views.days = function () {
    const idx = T.loadIndex(); const parts = [];
    parts.push(`<div class="card tiny muted"><b>Day by day.</b> Every analysed match with its final result and how the selection of the day was graded — kept so the record can be checked, not just today's card.</div>`);
    if (!idx || idx.loading) parts.push('<div class="card empty">Loading days…</div>');
    else if (idx.error && !idx.days) parts.push(`<div class="card empty">Day history unavailable (${esc(idx.error)}).</div>`);
    else if (!(idx.days || []).length) parts.push('<div class="card empty">No day files yet — the first ones appear after today\'s matches finish.</div>');
    else parts.push(`<div class="card compact"><table class="tbl head"><tr><th>Day</th><th class="right">Matches</th><th class="right">Selections</th><th class="right">Won</th></tr>${idx.days.map((x) => `<tr class="tap" data-tn-day="${esc(x.day)}"><td><b>${esc(dayLabel(x.day))}</b><div class="tiny muted">${esc(x.day)}${x.strong ? ` · ${x.strong} strong` : ''}</div></td><td class="right">${x.matches}<div class="tiny muted">${x.finished || 0} finished</div></td><td class="right">${x.selections || 0}</td><td class="right">${x.settled ? `<b class="${x.won / x.settled >= 0.6 ? 'good' : ''}">${x.won}/${x.settled}</b>` : '<span class="muted">–</span>'}</td></tr>`).join('')}</table></div>`);
    if (T.data) parts.push(perfCard(T.data.tracker, false));
    view().innerHTML = parts.join('');
    wire();
  };
  PR.pages.tennisDay = function (page) {
    const day = page.day; const j = T.day(day);
    const parts = [head(`🎾 ${esc(dayLabel(day))}`, `${esc(day)} · tennis`)];
    if (!j || j.loading) { parts.push('<div class="card empty">Loading day…</div>'); view().innerHTML = parts.join(''); wireBack(); return; }
    if (j.error) { parts.push(`<div class="card empty">Day file unavailable (${esc(j.error)}).</div>`); view().innerHTML = parts.join(''); wireBack(); return; }
    const ms = j.matches || []; const sels = ms.filter((m) => m.selection).map((m) => ({ ...m.selection, match_id: m.id, match: `${m.p1.name} v ${m.p2.name}`, start: m.start, tournament: m.tournament, quality: m.quality.score }));
    const settled = sels.filter((x) => x.won === '0' || x.won === '1'); const won = settled.filter((x) => x.won === '1').length;
    const s = j.summary || {};
    parts.push(`<div class="card compact"><div class="chips small-chips"><span class="chip">${ms.length} matches</span><span class="chip">${s.finished || 0} finished</span><span class="chip">${sels.length} selections</span>${settled.length ? `<span class="chip ${won / settled.length >= 0.6 ? 'ok' : ''}">${won}/${settled.length} won</span>` : ''}${sels.some((x) => x.won === 'void') ? `<span class="chip">${sels.filter((x) => x.won === 'void').length} void</span>` : ''}</div></div>`);
    if (sels.length) {
      const fams = ['Match winner', 'Total games', 'Player games', 'Game handicap'];
      parts.push(`<div class="section-head">${sh('star', 'Selections of the day', 'amber')}</div><div class="card botd">${fams.map((f) => { const l = sels.filter((x) => (x.family || MARKET[x.market]) === f).sort((a, b) => b.model_p - a.model_p); return l.length ? `<div class="botd-sec">${f} <span class="muted">· ${l.length}</span></div><table class="tbl">${l.map((x) => selRow(x, { match: ms.find((m) => String(m.id) === String(x.match_id)) })).join('')}</table>` : ''; }).join('')}</div>`);
    }
    const groups = new Map(); ms.slice().sort((a, b) => (a.category + a.tournament + a.start).localeCompare(b.category + b.tournament + b.start)).forEach((m) => { const k = `${m.category} · ${m.tournament}`; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(m); });
    parts.push(`<div class="section-head">${sh('calendar', 'All matches')}</div>`);
    groups.forEach((list, k) => parts.push(`<div class="card compact"><div class="row" style="padding:4px 0 2px"><div class="grow b">${esc(k)}</div><span class="chip">${esc(list[0].surface || 'surface N/A')}</span></div>${list.map((m) => matchRow(m, { live: null, sub: `${esc(localStart(m.start))} · ${m.result ? `<b>${esc(m.result.score || '')}</b>${m.result.retired ? ' (ret.)' : ''}` : 'no result yet'}${m.selection ? ` · ${esc(m.selection.label)} ${outcome(m.selection.won) || pc(m.selection.model_p, 0)}` : ''}` })).join('')}</div>`));
    parts.push(`<div class="card tiny muted">Results from Livescore; retirements settle the winner market only (game markets void). Model probabilities are the pre-match values published that day.</div>`);
    view().innerHTML = parts.join('');
    wireBack(); wire();
  };

  // ------------------------------------------------------------------ MATCH PAGE (Overview / Markets / Stats / Data — mirrors the football match page)
  PR.pages.tennisMatch = function (page) {
    const det = T.detail(page.id);
    const slim = matchById(page.id);
    const title = det && det.p1 ? `${esc(det.p1.name)} v ${esc(det.p2.name)}` : slim ? `${esc(slim.p1.name)} v ${esc(slim.p2.name)}` : 'Tennis match';
    const parts = [head(title, det && det.tournament ? `${esc(det.category)} · ${esc(det.tournament)}${det.qualifying ? ' (Q)' : ''} · ${esc(det.surface || 'surface N/A')} · best of ${det.best_of} · ${esc(localStart(det.start))}` : '', PR.tennisFavBtn(matchById(page.id)))];
    if (!det || det.loading) { parts.push('<div class="card empty">Loading match analysis…</div>'); view().innerHTML = parts.join(''); wireBack(); return; }
    if (det.error) { parts.push(`<div class="card empty">This analysis could not be loaded (${esc(det.error)}). ${slim ? '' : 'It may be older than the seven days kept on the server.'}</div>`); view().innerHTML = parts.join(''); wireBack(); return; }
    const p1 = det.p1, p2 = det.p2, q = det.quality || {}, f1_ = p1.features || {}, f2_ = p2.features || {};
    const lv = T.liveFor(det.id); const res = (slim && slim.result) || null;
    // header card: players, ranking, rating, form, probability
    const pl = (p, f, prob, side) => `<div class="grow" style="${side === 'b' ? 'text-align:right' : ''}"><div class="b" style="font-size:15px">${side === 'a' ? flag(p.ioc) + ' ' : ''}${esc(p.name)}${side === 'b' ? ' ' + flag(p.ioc) : ''}</div>
      <div class="tiny muted">${f.last_rank && f.last_rank.rank ? `rank #${f.last_rank.rank} <span class="muted">(${esc(f.last_rank.date)})</span> · ` : 'rank N/A · '}rating ${p.rating != null ? Math.round(p.rating) : 'N/A'}</div>
      <div class="tiny muted">${f.form && f.form.last10 && f.form.last10.n ? `${f.form.last10.wins}–${f.form.last10.n - f.form.last10.wins} last ${f.form.last10.n}` : 'form N/A'} ${wl((f.recent_matches || []).slice(0, 5).reverse())}</div>
      <div style="margin-top:6px">${ppill(prob)}</div></div>`;
    parts.push(`<div class="card"><div class="row" style="align-items:flex-start;gap:12px">${pl(p1, f1_, det.p.a, 'a')}<div class="tiny muted" style="text-align:center;padding-top:6px">${lv && lv.live ? `<span class="minute on">${esc(lv.status)}</span><br>${lv.sets.map((s) => s.join('-')).join(' ')}` : (lv && lv.finished) || res ? `FT<br>${lv && lv.sets.length ? lv.sets.map((s) => s.join('-')).join(' ') : res ? esc(res.score || '') : ''}` : 'v'}</div>${pl(p2, f2_, det.p.b, 'b')}</div>
      <div class="row" style="margin-top:8px;gap:6px;flex-wrap:wrap"><span class="chip ${q.score >= 80 ? 'ok' : q.score < 60 ? 'warn' : ''}">data quality ${q.score}% · ${esc(q.overall)}</span><span class="chip">set ${pc(det.p.set, 0)}</span>${det.games && det.games.expected_total != null ? `<span class="chip">expected ${det.games.expected_total.toFixed(1)} games</span>` : ''}${det.h2h_record && (det.h2h_record[0] + det.h2h_record[1]) ? `<span class="chip">H2H ${det.h2h_record[0]}–${det.h2h_record[1]}</span>` : ''}</div></div>`);
    const mv = ['overview', 'markets', 'stats', 'data'].includes(T.matchView) ? T.matchView : 'overview';
    parts.push(segmented([['overview', 'Overview'], ['markets', 'Markets'], ['stats', 'Stats'], ['data', 'Data']], mv, 'tmv'));
    if (mv === 'overview') overview(parts, det);
    else if (mv === 'markets') markets(parts, det);
    else if (mv === 'stats') stats(parts, det);
    else dataTab(parts, det);
    parts.push(`<div class="card"><div class="tiny muted">${esc((T.data && T.data.meta && T.data.meta.licence) || '')} Statistical information, not betting advice. 18+.</div></div>`);
    view().innerHTML = parts.join('');
    wireBack();
    $$('[data-tmv]').forEach((b) => { b.onclick = () => { T.matchView = b.dataset.tmv; PR.render(); }; });
  };
  const selCard = (x, title, cls) => `<div class="card ${cls || ''}"><div class="row"><div class="grow"><div class="tiny muted" style="text-transform:uppercase;letter-spacing:.4px;font-weight:700">${title}</div><div class="b" style="font-size:16px">${esc(x.label)}${x.strong ? '<span class="tn-strong">STRONG</span>' : ''}</div><div class="tiny muted">${esc(MARKET[x.market] || x.market)}${x.why ? ` · ${esc(x.why)}` : ''}${x.won ? ` · ${outcome(x.won)}` : ''}</div></div>${ppill(x.model_p)}</div>
    <div class="tn-grid">${cell('MODEL', pc(x.model_p))}${cell('FAIR', od(x.fair_odds))}${cell('SPORTYBET', od(x.book_odds))}${cell('IMPLIED', pc(x.implied_fair))}${cell('EDGE', pp(x.edge_pp), edgeCls(x.edge_pp))}</div></div>`;
  function overview(parts, det) {
    const p1 = det.p1, p2 = det.p2;
    if (det.selection) parts.push(selCard(det.selection, 'Selection of the day · preferred market'));
    else parts.push(`<div class="card"><div class="tiny muted" style="text-transform:uppercase;letter-spacing:.4px;font-weight:700">Selection of the day</div><div class="b">None for this match</div><div class="tiny muted">${esc(det.selection_note || 'No market clears the selection rules.')}</div></div>`);
    const others = (det.strong || []).filter((x) => !det.selection || x.market !== det.selection.market || x.selection !== det.selection.selection || x.line !== det.selection.line);
    if (others.length) parts.push(`<div class="card compact"><div class="b">Other strong markets <span class="tiny muted">· model ≥ 70%</span></div>${others.map((x) => `<div class="tn-item"><div class="row"><div class="grow b">${esc(x.label)}</div>${ppill(x.model_p)}</div><div class="tn-grid">${cell('MODEL', pc(x.model_p))}${cell('FAIR', od(x.fair_odds))}${cell('SPORTYBET', od(x.book_odds))}${cell('IMPLIED', pc(x.implied_fair))}${cell('EDGE', pp(x.edge_pp), edgeCls(x.edge_pp))}</div></div>`).join('')}</div>`);
    if (det.highlights && det.highlights.length) parts.push(`<div class="card compact"><div class="b">Model above market <span class="tiny muted">· disagreement, not a recommendation</span></div>${det.highlights.map((x) => `<div class="tn-item"><div class="row"><div class="grow">${esc(x.label)} <span class="chip ok">${esc(x.flag || '')}</span></div><span class="${edgeCls(x.edge_pp)}"><b>${pp(x.edge_pp)}</b></span></div></div>`).join('')}</div>`);
    // model probability + set scores
    const ss = det.set_scores || {};
    parts.push(`<div class="card compact"><div class="row"><div class="grow b">Model probability</div><span class="tiny muted">P(A) + P(B) = 100%</span></div>
      <table class="tbl"><tr><td>${esc(p1.name)}</td><td class="right b">${pc(det.p.a)}</td><td class="right tiny muted">fair ${od(1 / det.p.a)}</td></tr><tr><td>${esc(p2.name)}</td><td class="right b">${pc(det.p.b)}</td><td class="right tiny muted">fair ${od(1 / det.p.b)}</td></tr></table>
      <div class="b" style="margin-top:8px">Set scores · best of ${det.best_of}</div><table class="tbl head"><tr><th>Score</th><th class="right">${esc(p1.name.split(' ').pop())}</th><th class="right">${esc(p2.name.split(' ').pop())}</th></tr>
      ${Object.keys(ss).filter((k) => +k.split('-')[0] > +k.split('-')[1]).sort().map((k) => { const r = k.split('-').reverse().join('-'); return `<tr><td>${k} / ${r}</td><td class="right">${pc(ss[k])}</td><td class="right">${pc(ss[r])}</td></tr>`; }).join('')}</table>
      <div class="tiny muted" style="margin-top:4px">Set probability ${pc(det.p.set)} → match probability through the explicit best-of-${det.best_of} formula${det.p.reference_bo3 != null && det.best_of === 5 ? ` (best-of-3 reference ${pc(det.p.reference_bo3)})` : ''}.</div></div>`);
    if (det.warnings && det.warnings.length) parts.push(`<div class="card compact"><div class="b">${icon('alert', 'sm')} Warnings</div><ul class="notes">${det.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul></div>`);
    if (det.explain && det.explain.steps) parts.push(`<div class="card compact"><div class="b">How the probability was built</div><ol class="notes">${det.explain.steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol><div class="tiny muted">Every number above is the model's own value for this match. Bookmaker prices are never an input.</div></div>`);
  }
  function markets(parts, det) {
    const rows = det.markets || [];
    parts.push(`<div class="card tiny muted"><b>Vocabulary.</b> MODEL = the data-only model probability · FAIR = 1 / model · SPORTYBET = bookmaker price (comparison only, never a model input) · IMPLIED = bookmaker probability with the margin removed · EDGE = model − implied in points. LOW DATA CONFIDENCE marks game markets built on stale or thin serve/return data.</div>`);
    if (!rows.length) { parts.push('<div class="card empty">No bookmaker prices found for this match — model probabilities only.</div>'); return; }
    const fams = [['winner', 'Match winner'], ['total_games', 'Total games'], ['p1_games', `${det.p1.name} games`], ['p2_games', `${det.p2.name} games`], ['game_handicap', 'Game handicap']];
    const sel = det.selection;
    fams.forEach(([k, title]) => {
      const list = rows.filter((r) => r.market === k); if (!list.length) return;
      parts.push(`<div class="card compact"><div class="b">${esc(title)}</div>${list.map((r) => { const isSel = sel && sel.market === r.market && sel.selection === r.selection && sel.line === r.line; const isStrong = (det.strong || []).some((x) => x.market === r.market && x.selection === r.selection && x.line === r.line);
        return `<div class="tn-item ${isSel ? 'hl' : ''}"><div class="row"><div class="grow ${r.flag || isSel ? 'b' : ''}">${esc(r.label)}${isSel ? ' <span class="chip brand">preferred</span>' : ''}${isStrong ? '<span class="tn-strong">STRONG</span>' : ''}${r.low_confidence ? ' <span class="chip warn">low data confidence</span>' : ''}${r.flag ? ` <span class="chip ok">${esc(r.flag)}</span>` : ''}</div><div class="row" style="gap:0;justify-content:flex-end;align-items:center">${ppill(r.model_p)}${PR.tennisAddBtn ? PR.tennisAddBtn(det.id, r) : ''}</div></div>
          <div class="tn-grid">${cell('MODEL', pc(r.model_p))}${cell('FAIR', od(r.fair_odds))}${cell('SPORTYBET', od(r.book_odds))}${cell('IMPLIED', pc(r.implied_fair))}${cell('EDGE', pp(r.edge_pp), edgeCls(r.edge_pp))}</div></div>`; }).join('')}</div>`);
    });
    if (det.games) parts.push(`<div class="card compact"><div class="b">Games model</div><div class="tiny muted">Expected total ${det.games.expected_total != null ? det.games.expected_total.toFixed(1) : 'N/A'} games · service points won on an average day: ${esc(det.p1.name)} ${pc(det.games.pa)}, ${esc(det.p2.name)} ${pc(det.games.pb)} (split pinned to the match probability; day-form spread validated in the backtest). Expected-total error in the backtest ≈ 5 games, so game markets need a larger model/market gap before they are flagged.</div></div>`);
  }
  function stats(parts, det) {
    const p1 = det.p1, p2 = det.p2, A = p1.features || {}, B = p2.features || {};
    const s1 = A.serve || {}, s2 = B.serve || {}, r1 = A.ret || {}, r2 = B.ret || {}, pr1 = A.profile || {}, pr2 = B.profile || {};
    const cmp = (label, a, b, fmt, higher) => { fmt = fmt || ((x) => x); const av = a == null || isNaN(a) ? null : +a, bv = b == null || isNaN(b) ? null : +b; if (av == null && bv == null) return `<tr><td class="right muted">N/A</td><td class="mid"><div class="k">${label}</div></td><td class="muted">N/A</td></tr>`;
      const tot = (av || 0) + (bv || 0); const wa = tot ? (av || 0) / tot : 0.5; const cls = (x, y) => (x == null || y == null || x === y) ? '' : ((x > y) === !!higher ? 'lead' : '');
      return `<tr><td class="right ${cls(av, bv)}">${av == null ? '<span class="muted">N/A</span>' : fmt(av)}</td><td class="mid"><div class="k">${label}</div><div class="duo"><span class="l" style="width:${Math.round(wa * 100)}%"></span><span class="r" style="width:${Math.round((1 - wa) * 100)}%"></span></div></td><td class="${cls(bv, av)}">${bv == null ? '<span class="muted">N/A</span>' : fmt(bv)}</td></tr>`; };
    const rate = (o) => o && o.n ? o.wins / o.n : null; const rateTxt = (o) => (x) => o && o.n ? `${o.wins}/${o.n}` : 'N/A';
    const P = (x) => pc(x, 0), R = (x) => Math.round(x), F1 = (x) => Number(x).toFixed(1), F2 = (x) => Number(x).toFixed(2);
    parts.push(`<div class="card compact"><div class="row"><div class="grow b">${esc(p1.name)}</div><div class="tiny muted">samples</div><div class="b">${esc(p2.name)}</div></div>
      <div class="row" style="gap:6px;margin-top:4px;flex-wrap:wrap">${evChip(p1.n)}<span class="grow"></span>${evChip(p2.n)}</div>
      <table class="cmp">${cmp('Rating (Elo, results only)', p1.rating, p2.rating, R, true)}${cmp(`${esc(det.surface || 'Surface')} rating`, p1.surface_rating, p2.surface_rating, R, true)}
      ${cmp('Last known ranking', A.last_rank && A.last_rank.rank, B.last_rank && B.last_rank.rank, (x) => '#' + x, false)}
      ${cmp('Rated matches', p1.n, p2.n, R, true)}${cmp(`Matches on ${esc(det.surface || 'this surface')}`, p1.n_surface, p2.n_surface, R, true)}
      ${cmp('Form · last 5', rate(A.form && A.form.last5), rate(B.form && B.form.last5), (x) => P(x), true)}${cmp('Form · last 10', rate(A.form && A.form.last10), rate(B.form && B.form.last10), P, true)}${cmp('Form · last 20', rate(A.form && A.form.last20), rate(B.form && B.form.last20), P, true)}
      ${cmp(`${esc(det.surface || 'Surface')} form · last 10`, rate(A.surface_form && A.surface_form.last10), rate(B.surface_form && B.surface_form.last10), P, true)}
      ${cmp('Results vs rating expectation (last 10)', A.form_vs_expectation && A.form_vs_expectation.value, B.form_vs_expectation && B.form_vs_expectation.value, (x) => (x >= 0 ? '+' : '') + Math.round(x * 100) + ' pp', true)}
      ${cmp('Days since last match', A.days_since_last, B.days_since_last, R, false)}</table>
      <div class="tiny muted" style="margin-top:4px">Form = wins / matches in the sample (historical frequency, not a probability). Ratings: 1500 for a new player; a 100-point gap ≈ 61% for the higher-rated player in a best-of-3 (scale 500). Ranking is the last one recorded in the archive, not today's.</div></div>`);
    const serveNote = (s) => s && s.n ? `${Math.round(s.n)} matches with statistics to ${esc(s.as_of)}${s.stale ? ' · STALE' : ''}${s.low_confidence ? ' · LOW DATA CONFIDENCE' : ''}` : 'no serve statistics in the data';
    parts.push(`<div class="card compact"><div class="row"><div class="grow b">Serve &amp; return</div></div><div class="tiny muted">${esc(p1.name)}: ${serveNote(s1)} · ${esc(p2.name)}: ${serveNote(s2)}</div>
      <table class="cmp">${cmp('Serve points won', s1.spw, s2.spw, P, true)}${cmp('1st serve in', s1.first_in, s2.first_in, P, true)}${cmp('1st serve points won', s1.first_won, s2.first_won, P, true)}${cmp('2nd serve points won', s1.second_won, s2.second_won, P, true)}
      ${cmp('Service games held', s1.hold, s2.hold, P, true)}${cmp('Aces per match', s1.aces_per_match, s2.aces_per_match, F1, true)}${cmp('Double faults per match', s1.df_per_match, s2.df_per_match, F1, false)}${cmp('Break points saved', s1.bp_saved, s2.bp_saved, P, true)}
      ${cmp('Return points won', r1.rpw, r2.rpw, P, true)}${cmp('Break points converted', r1.bp_converted, r2.bp_converted, P, true)}${cmp('Break points created per match', r1.bp_created_per_match, r2.bp_created_per_match, F1, true)}${cmp('Break of serve rate', r1.break_rate, r2.break_rate, P, true)}</table>
      <div class="tiny muted" style="margin-top:4px">From the match-statistics archive (through ${esc((T.data && T.data.meta && T.data.meta.archive_end) || 'June 2026')}); Livescore publishes no tennis statistics, so these age and are flagged stale after 240 days. N/A = not in the data — never assumed.</div></div>`);
    parts.push(`<div class="card compact"><div class="row"><div class="grow b">Match profile</div><div class="tiny muted">last ${pr1.n || 0} / ${pr2.n || 0} completed matches</div></div>
      <table class="cmp">${cmp('Average total games', pr1.avg_total_games, pr2.avg_total_games, F1, true)}${cmp('Straight-sets share', pr1.straight_sets_share, pr2.straight_sets_share, P, true)}${cmp('Deciding-set share', pr1.deciding_set_share, pr2.deciding_set_share, P, false)}${cmp('Tiebreaks per match', pr1.tiebreaks_per_match, pr2.tiebreaks_per_match, F2, false)}
      ${cmp('Tiebreaks won', pr1.tiebreak_record && pr1.tiebreak_record[1] ? pr1.tiebreak_record[0] / pr1.tiebreak_record[1] : null, pr2.tiebreak_record && pr2.tiebreak_record[1] ? pr2.tiebreak_record[0] / pr2.tiebreak_record[1] : null, P, true)}</table>
      <div class="tiny muted" style="margin-top:4px">Tiebreak record ${pr1.tiebreak_record ? `${pr1.tiebreak_record[0]}–${pr1.tiebreak_record[1] - pr1.tiebreak_record[0]}` : 'N/A'} / ${pr2.tiebreak_record ? `${pr2.tiebreak_record[0]}–${pr2.tiebreak_record[1] - pr2.tiebreak_record[0]}` : 'N/A'}. Frequencies of the sample, not model probabilities.</div></div>`);
    // last 10 matches per player
    const last = (p, f) => { const rm = f.recent_matches || []; return `<div class="card compact"><div class="row"><div class="grow b">${esc(p.name)} · last ${rm.length} matches</div>${wl(rm.slice().reverse())}</div>
      ${rm.length ? `<table class="tbl head"><tr><th>Date</th><th>Opponent</th><th class="right">Score</th><th class="right">Exp.</th></tr>${rm.map((r) => `<tr><td class="tiny muted nowrap">${esc(r.date.slice(5))}<div>${esc((r.surface || '?').slice(0, 4))}</div></td><td><div class="${r.won ? 'b' : ''}"><i class="tn-wl"><i class="${r.won ? 'W' : 'L'}">${r.won ? 'W' : 'L'}</i></i> ${esc(r.opponent || r.opp_pid || '?')} <span class="tiny muted">${r.opp_rank ? `#${r.opp_rank} · ` : ''}${r.opp_rating ? `rating ${r.opp_rating}` : ''}</span></div><div class="tiny muted">${esc(r.tournament || '')}${r.round ? ` · ${esc(r.round)}` : ''}${r.retired ? ' · ret.' : ''}</div></td><td class="right nowrap tiny">${esc(r.score || (r.games ? `${r.games[0]}–${r.games[1]} games` : 'N/A'))}</td><td class="right tiny ${r.expected == null ? 'muted' : r.won === (r.expected >= 0.5) ? '' : 'warn'}">${r.expected == null ? 'N/A' : pc(r.expected, 0)}</td></tr>`).join('')}</table>
      <div class="tiny muted" style="margin-top:4px">Score as recorded (winner first). Exp. = the model's pre-match probability for ${esc(p.name.split(' ').pop())} at the time — a low value on a win means an upset.</div>` : '<div class="empty small">No recent matches in the data.</div>'}</div>`; };
    parts.push(last(p1, A), last(p2, B));
    // H2H
    const h = det.h2h || [];
    parts.push(`<div class="card compact"><div class="row" style="gap:6px;flex-wrap:wrap"><span class="b">Head to head</span>${evChip(h.length, 'meetings')}<span class="chip warn">context only — not a model input</span></div>
      ${h.length ? `<div class="tiny muted" style="margin:4px 0">${esc(p1.name)} ${det.h2h_record[0]} – ${det.h2h_record[1]} ${esc(p2.name)}</div><table class="tbl">${h.map((x) => `<tr><td class="tiny muted nowrap">${esc(x.date)}</td><td><div class="b">${esc(x.winner_name || x.winner)}</div><div class="tiny muted">${esc(x.tournament || '')}${x.round ? ` · ${esc(x.round)}` : ''} · ${esc(x.surface || 'surface N/A')}</div></td><td class="right nowrap tiny">${esc(x.score || '')}</td></tr>`).join('')}</table>` : '<div class="tiny muted" style="margin-top:4px">No previous meeting in the data.</div>'}</div>`);
  }
  function dataTab(parts, det) {
    const q = det.quality || {}, ex = det.explain || {}, inp = ex.inputs || {};
    parts.push(`<div class="card tiny muted"><b>Vocabulary.</b> Historical frequency = what happened in the sample. Model probability = the results-only rating model. Market implied = the bookmaker price with its margin removed (comparison only). Data quality = completeness and freshness of the evidence — not a probability. Missing data is N/A, never 0.</div>`);
    if (q.items) parts.push(`<div class="card compact"><div class="row"><div class="grow b">${icon('shield', 'sm')} Data quality</div><span class="chip ${q.score >= 80 ? 'ok' : q.score < 60 ? 'warn' : ''}">${esc(q.overall)} · ${q.score}%</span></div>
      <table class="tbl" style="margin-top:6px">${q.items.map((it) => `<tr><td class="nowrap" style="text-transform:capitalize">${esc(it.check.replace(/_/g, ' '))}</td><td><span class="chip ${it.status === 'PASS' ? 'ok' : it.status === 'FAIL' ? 'bad' : 'warn'}">${esc(it.status)}</span></td><td class="tiny muted">${esc(it.detail)}</td></tr>`).join('')}</table>
      <div class="tiny muted" style="margin-top:6px">Score = share of checks passed (partial / stale count half). High ≥ 80, Medium ≥ 60.</div></div>`);
    const idn = (p) => { const i = p.identity || {}; return `<tr><td>${esc(p.name)}</td><td><span class="chip ${i.how === 'exact' ? 'ok' : i.how === 'new' ? 'warn' : ''}">${esc(i.how || 'N/A')}</span></td><td class="tiny muted">${i.pid ? `archive id ${esc(i.pid)}` : 'not in the archive'}${i.score != null ? ` · match score ${Number(i.score).toFixed(2)}` : ''}${i.name && i.name !== p.name ? ` · archive name ${esc(i.name)}` : ''}</td></tr>`; };
    parts.push(`<div class="card compact"><div class="b">Player identity</div><table class="tbl">${idn(det.p1)}${idn(det.p2)}</table><div class="tiny muted">How the Livescore name was matched to the historical record (exact / alias / fuzzy / new). A "new" player has no history: rating 1500, wide uncertainty.</div></div>`);
    parts.push(`<div class="card compact"><div class="b">Model inputs</div><table class="tbl"><tr><td>Overall ratings</td><td class="right">${inp.rating_a != null ? Math.round(inp.rating_a) : 'N/A'} · ${inp.rating_b != null ? Math.round(inp.rating_b) : 'N/A'}</td></tr><tr><td>${esc(det.surface || 'Surface')} ratings</td><td class="right">${inp.surface_rating_a != null ? Math.round(inp.surface_rating_a) : 'N/A'} · ${inp.surface_rating_b != null ? Math.round(inp.surface_rating_b) : 'N/A'}</td></tr>
      <tr><td>Rated matches (all / surface)</td><td class="right">${inp.n_a != null ? inp.n_a : 'N/A'} / ${inp.ns_a != null ? inp.ns_a : 'N/A'} · ${inp.n_b != null ? inp.n_b : 'N/A'} / ${inp.ns_b != null ? inp.ns_b : 'N/A'}</td></tr><tr><td>Surface weight · K schedule</td><td class="right">${inp.surface_weight != null ? inp.surface_weight : 'N/A'} · ${esc(inp.k_schedule || 'N/A')}</td></tr>
      ${inp.dominance ? `<tr><td>Serve-point baseline (tour · surface)</td><td class="right">${pc(inp.dominance.baseline)}</td></tr><tr><td>Serve traits A / B</td><td class="right">${pp(inp.dominance.serve_a * 100)} / ${pp(inp.dominance.serve_b * 100)}</td></tr><tr><td>Return traits A / B</td><td class="right">${pp(inp.dominance.return_a * 100)} / ${pp(inp.dominance.return_b * 100)}</td></tr><tr><td>Day-form spread σ</td><td class="right">${inp.dominance.sigma}</td></tr>` : '<tr><td>Games model</td><td class="right muted">N/A (no serve data)</td></tr>'}</table>
      <div class="tiny muted">Parameters validated walk-forward on 2019–2026 (tennis/BACKTEST_RESULTS.md): winner accuracy 63.8%, Brier 0.221, calibration gaps ≤ 3 pp. Surface: ${esc((det.surface_info || {}).source || 'N/A')}.</div></div>`);
    parts.push(`<div class="card compact"><div class="b">Sources &amp; freshness</div><ul class="notes"><li>Results and statistics: Jeff Sackmann's ATP/WTA archive (mirror) to ${esc((T.data && T.data.meta && T.data.meta.archive_end) || 'June 2026')} — CC BY-NC-SA 4.0.</li><li>Results since then: Livescore (scores only — no statistics, no surface, no round).</li><li>Prices: Sportybet ZA, fetched at scan time (${esc(det.odds && det.odds.start ? det.odds.start : 'no price')}); comparison layer only.</li><li>Analysis generated ${esc((T.data && T.data.meta && T.data.meta.generated_sast) || '')} SAST.</li></ul></div>`);
  }
  // ------------------------------------------------------------------ GUIDE
  PR.pages.tennisGuide = function () {
    const parts = [head('🎾 How the tennis model works', 'Separate from the football model')];
    parts.push(`<div class="card"><ul class="notes">
      <li><b>Ratings.</b> Every player has an Elo rating built only from match results (2005 → today), overall and per surface; the two are blended 50/50. New players start at 1500 with wide uncertainty.</li>
      <li><b>Set → match.</b> The rating gap gives a set probability; the match probability follows the explicit best-of-3 (2-0 / 2-1) or best-of-5 (3-0 / 3-1 / 3-2) formula, so Grand Slam men's matches are treated differently.</li>
      <li><b>Games.</b> A serve-point Markov chain (serve/return traits from the statistics archive, pinned to the match probability) gives total games, player games and handicap probabilities. Its average error is about 5 games, so game markets need a larger model/market gap to be flagged.</li>
      <li><b>Bookmaker.</b> Sportybet prices are shown next to the model — MODEL / FAIR / SPORTYBET / IMPLIED / EDGE — and are never an input.</li>
      <li><b>Selections of the day.</b> One preferred market per match: the highest model probability (≥ 60%) among priced markets — odds never filter — with data quality ≥ 60% and both players having 30+ rated matches. <b>STRONG</b> = model ≥ 70%.</li>
      <li><b>Data quality</b> is a completeness score (identity, surface, samples, freshness…), not a win probability.</li>
      <li><b>Validation.</b> Walk-forward backtest 2019–2026: accuracy 63.8% (ranking baseline 61.6%), Brier 0.221, calibration within 3 pp in every band. Every published selection is tracked and graded against results.</li>
      <li><b>Limits.</b> No injury or withdrawal news; serve statistics age after the archive snapshot; ITF, doubles and team events are outside coverage. Statistical information, not betting advice. 18+.</li></ul></div>`);
    view().innerHTML = parts.join(''); wireBack();
  };

  // taps on tennis rows (separate attribute from football's data-fx / data-team)
  document.addEventListener('click', (e) => {
    const r = e.target.closest('[data-tennis]');
    if (r && !e.target.closest('[data-tn-bets],[data-tn-tab],[data-tn-guide],[data-tn-day]')) { e.preventDefault(); PR.push({ type: 'tennisMatch', id: r.dataset.tennis }); }
  });
})(window.PR);
