/* Mr 2 Odds — core: settings, data access, native bridge, helpers, navigation.
   The published analysis (latest.json, day files, team files) is read through the native bridge;
   nothing about the publishing backend is ever shown. */
window.PR = (function () {
  'use strict';
  const native = window.Android || null;
  const RAW_BASE = (native && native.rawBase && native.rawBase()) || 'https://raw.githubusercontent.com/perfectndumiso1-netizen/goals-scanner/data/';
  const DATA_URL = (native && native.dataUrl && native.dataUrl()) || (RAW_BASE + 'data/app/latest.json');
  const CONTACT = { whatsapp: '27738212664', whatsappShown: '073 821 2664', email: 'msanindumiso@gmail.com' };
  const APP_VERSION = (native && native.version && native.version()) || '';
  /** localStorage first; when it is empty (fresh install, WebView data cleared) the copy kept in native preferences is restored */
  function stored(key) {
    let v = null;
    try { v = localStorage.getItem(key); } catch (e) { v = null; }
    if (v == null && native && native.getString) {
      try { v = native.getString(key.replace(/^pr_/, '')); if (v != null) localStorage.setItem(key, v); } catch (e) { v = null; }
    }
    return v;
  }
  function persist(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* quota */ }
    if (native && native.setString) { try { native.setString(key.replace(/^pr_/, ''), value); } catch (e) { /* ignore */ } }
  }
  /** Secondary caches (badges, tennis) are big enough to hit the phone's 5 MB web-storage quota on their own.
   *  A full phone must never look like a network failure, and a cache that cannot be written must not throw:
   *  write, and if the phone is full first free the day/team cache and retry, then hand the bytes to the
   *  native store (`str_<key>`), which lives outside the WebView's quota. Returns true when it was kept. */
  function saveAux(key, value) {
    try { localStorage.setItem(key, value); return true; } catch (e) { /* full */ }
    try { cache.prune(true); localStorage.setItem(key, value); return true; } catch (e) { /* still full */ }
    if (native && native.setString) { try { native.setString(key.replace(/^pr_/, ''), value); return true; } catch (e) { /* ignore */ } }
    return false;   // nothing was lost: the data is already live in memory for this session
  }
  let savedSettings = {};
  try { savedSettings = JSON.parse(stored('pr_settings') || '{}'); } catch (e) { savedSettings = {}; }
  const settings = Object.assign({ liveEvery: 60, tzOffset: 2, goalAlerts: true, htAlerts: false, ftAlerts: true, betAlerts: true, reportAlerts: true, minP: 0.70, hiP: 0.70, theme: 'dark', seenVersion: '', leagues: 'all', sport: 'football' },
    savedSettings, { sport: 'football', tennisAlerts: false });
  const state = { data: null, tab: 'home', stack: [], live: {}, incidents: {}, liveTimer: null, lastLive: 0, loading: false, q: '',
    update: null, updateStage: null, days: {}, teams: {}, reports: {}, details: {}, betsView: 'today', search: '', sort: 'ko', matchFilter: 'all',
    liveView: 'tracked', liveAll: null, lastLiveAll: 0, dayView: 'results', matchView: 'overview', teamView: 'overview', menuOpen: false, expanded: {}, badges: {}, dark: false,
    teamIdx: null, teamIdxLoading: false, lgSort: 'country', lgTableSort: 'pts', scrolls: {}, tabHist: [] };
  const BADGE_BASE = 'https://lsm-static-prod.livescore.com/medium/';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  function saveSettings() { if (resources) resources.policies.live = Math.max(20, Math.min(30, settings.liveEvery)) * 1000; persist('pr_settings', JSON.stringify(settings)); }

  // ------------------------------------------------------------------ fetch bridge
  let fid = 0; const pending = {};
  window.__fetchDone = function (id, code, body, metadata) { const cb = pending[id]; delete pending[id]; if (cb) cb(Object.assign({ code, body }, metadata)); };
  function nfetch(url, ua, validators) {
    if (native && native.fetch) return new Promise((resolve) => {
      const id = ++fid, timer = setTimeout(() => { delete pending[id]; resolve({ code: 0, body: 'Request timed out' }); }, 50000);
      pending[id] = (r) => { clearTimeout(timer); resolve(r); };
      if (validators && native.fetchConditional) native.fetchConditional(id, url, ua || null, validators.etag || null, validators.modified || null);
      else native.fetch(id, url, ua || null);
    });
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    const headers = {};
    if (validators && validators.etag) headers['If-None-Match'] = validators.etag;
    else if (validators && validators.modified) headers['If-Modified-Since'] = validators.modified;
    return fetch(url, { headers, signal: controller.signal }).then(async (r) => ({ code: r.status, body: r.status === 304 ? '' : await r.text(),
      etag: r.headers.get('ETag') || '', modified: r.headers.get('Last-Modified') || '',
      retryAfter: /^\d+$/.test(r.headers.get('Retry-After') || '') ? Number(r.headers.get('Retry-After')) * 1000 : Math.max(0, Date.parse(r.headers.get('Retry-After')) - Date.now()) || 0 }))
      .catch(() => ({ code: 0, body: 'Connection unavailable' })).finally(() => clearTimeout(timer));
  }
  let cid = 0; const cachePending = {};
  window.__cacheDone = function (id, value) { const cb = cachePending[id]; delete cachePending[id]; if (cb) cb(value); };
  function cacheCall(method, args) {
    return new Promise((resolve, reject) => {
      const id = ++cid, timer = setTimeout(() => { delete cachePending[id]; reject(new Error('Storage unavailable')); }, 5000);
      cachePending[id] = (value) => { clearTimeout(timer); if (value === false) reject(new Error('Storage unavailable')); else resolve(value); };
      try { native[method].apply(native, [id].concat(args)); } catch (e) { clearTimeout(timer); delete cachePending[id]; reject(e); }
    });
  }
  function validRows(rows, date) {
    if (!Array.isArray(rows)) return false;
    const ids = new Set();
    return rows.every((f) => {
      if (!f || typeof f.id !== 'string' || !f.id || ids.has(f.id)) return false;
      ids.add(f.id);
      if (f.sels && (!Array.isArray(f.sels) || new Set(f.sels.map((s) => Array.isArray(s) ? s[0] : s.sel)).size !== f.sels.length)) return false;
      return (!date || f.id.slice(0, 10) === date) && (!f.kickoff || f.id.slice(0, 10) === f.kickoff.slice(0, 10));
    });
  }
  function validResource(url, j) {
    if (!j || typeof j !== 'object' || Array.isArray(j) || !Object.keys(j).length) return false;
    const path = new URL(url).pathname, part = path.split('/data/app/')[1] || '';
    if (path.includes('/reports/')) return typeof j.md === 'string' && j.md.trim().length > 0 && !/^\s*</.test(j.md);
    if (part === 'latest.json') return !!(j.meta && typeof j.meta.generated === 'string' && /^\d{4}-\d\d-\d\d/.test(j.meta.generated) && j.version >= 3 && j.safe && j.picks && j.history && Array.isArray(j.tracked) && (!j.safe.bets || Array.isArray(j.safe.bets) && new Set(j.safe.bets.map((b) => b.id)).size === j.safe.bets.length) && validRows(j.fixtures) && j.fixtures.length);
    const detail = part.match(/^fx\/([a-f0-9]{12})\.json$/);
    if (detail) { const row = fx(j.id); return (!j.sels || Array.isArray(j.sels)) && (!j.h2h || Array.isArray(j.h2h)) && (!row || j.home === row.home && j.away === row.away) && typeof j.id === 'string' && sha1hex(j.id).slice(0, 12) === detail[1] && typeof j.home === 'string' && typeof j.away === 'string' && (!j.kickoff || j.id.slice(0, 10) === j.kickoff.slice(0, 10)); }
    const day = part.match(/^days\/(\d{4}-\d\d-\d\d)\.json$/);
    if (day) return j.date === day[1] && validRows(j.fixtures, day[1]);
    if (part === 'leagues/index.json') return Array.isArray(j.leagues) && new Set(j.leagues.map((l) => l.slug)).size === j.leagues.length;
    if (part === 'leagues/fixtures.json') return Array.isArray(j.fixtures);
    if (part.startsWith('leagues/')) return typeof j.key === 'string' && part === 'leagues/' + j.key.replace(/\//g, '__').replace(/[^A-Za-z0-9_.-]+/g, '_') + '.json' && Array.isArray(j.table) && Array.isArray(j.results) && Array.isArray(j.fixtures);
    if (part === 'badges.json') return Object.values(j).every((v) => typeof v === 'string' && !v.includes('..') && !/^(?:https?:|\/)/.test(v));
    if (part === 'teams/teams-index.json') return Array.isArray(j.teams);
    if (part.startsWith('teams/')) return typeof j.div === 'string' && part === 'teams/' + slug(j.div) + '.json' && !!j.teams && typeof j.teams === 'object' && !Array.isArray(j.teams);
    if (url.includes('/date/soccer/')) return Array.isArray(j.Stages);
    return true;
  }
  const resources = window.PRResourceCache ? window.PRResourceCache.create({
    fetch: (url, validators) => nfetch(url, null, validators).then((r) => url.includes('/reports/') && r.code === 200 ? Object.assign({}, r, { body: JSON.stringify({ md: r.body }) }) : r), validate: validResource,
    online: () => native && native.online ? native.online() : navigator.onLine !== false,
    policies: { live: Math.max(20, Math.min(30, settings.liveEvery)) * 1000 },
    store: native && native.cacheRead ? {
      get: (key) => cacheCall('cacheRead', [key]), put: (key, value) => cacheCall('cacheWrite', [key, JSON.stringify(value)]),
      touch: (key, time, headers) => cacheCall('cacheTouch', [key, time, headers ? headers.etag : null, headers ? headers.modified : null]),
      failure: (key, value) => cacheCall('cacheFailure', [key, value ? JSON.stringify(value) : null]), clear: () => cacheCall('cacheClear', [])
    } : window.PRResourceCache.browserStore()
  }) : null;
  function managed(url) { return (url.startsWith(RAW_BASE + 'data/app/') && /\.json(?:\?|$)/.test(url)) || (url.startsWith(RAW_BASE + 'reports/') && /\.md(?:\?|$)/.test(url)) || url.startsWith('https://prod-public-api.livescore.com/v1/api/app/'); }
  // The native shell only answers for the hosts this app actually uses (Security.kt holds the list), so the
  // page refuses anything else itself: a bad link or a corrupted cache entry fails loudly here instead of
  // turning the app into a fetcher for whatever URL it was handed.
  const API_HOSTS = ['raw.githubusercontent.com', 'api.github.com', 'prod-public-api.livescore.com', 'lsm-static-prod.livescore.com'];
  function hostAllowed(url) {
    // absolute https URLs only: every call site builds one, and a relative or scheme-less URL fails closed
    try {
      const u = new URL(url);
      return u.protocol === 'https:' && (u.port === '' || u.port === '443') && API_HOSTS.indexOf(u.hostname) >= 0;
    }
    catch (e) { return false; }
  }
  async function getJson(url, ua, options) {
    if (!hostAllowed(url)) throw new Error(`blocked host: ${String(url).slice(0, 80)}`);
    if (resources && managed(url)) return resources.get(url, options);
    const r = await nfetch(url, ua);
    if (r.code !== 200) throw new Error(`HTTP ${r.code}`);
    if (url.startsWith(RAW_BASE + 'reports/')) return { md: r.body };
    return JSON.parse(r.body);
  }
  const rawUrl = (path) => RAW_BASE + path;

  async function migrateResource(url, legacyKey) {
    if (!resources || resources.status(url).cached) return;
    let record;
    try {
      const raw = legacyKey === 'pr_latest' ? stored(legacyKey) : localStorage.getItem(cache.key(legacyKey));
      if (!raw) return;
      record = JSON.parse(raw);
      await resources.seed(url, legacyKey === 'pr_latest' ? record : record.d, legacyKey === 'pr_latest' ? record._loadedAt : record.t);
      if (resources.status(url).persisted) {
        localStorage.removeItem(legacyKey === 'pr_latest' ? legacyKey : cache.key(legacyKey));
        if (legacyKey === 'pr_latest' && native && native.setString) native.setString('latest', '');
      }
    } catch (_) { /* valid existing copies are never erased after a migration failure */ }
  }
  // ------------------------------------------------------------------ formatting helpers
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pct = (x) => (x == null || isNaN(x)) ? '–' : Math.round(x * 100) + '%';
  const f1 = (x) => (x == null || isNaN(x)) ? '–' : Number(x).toFixed(1);
  const f2 = (x) => (x == null || isNaN(x)) ? '–' : Number(x).toFixed(2);
  const signed = (x) => (x == null || isNaN(x)) ? '–' : (x >= 0 ? '+' : '') + (x * 100).toFixed(1) + '%';
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function parseLocal(s) { if (!s) return null; const m = String(s).match(/(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/); if (!m) return null; return new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0)); }
  function tzNow() { const n = new Date(); return new Date(n.getTime() + (settings.tzOffset * 60 + n.getTimezoneOffset()) * 60000); }
  function ymd(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
  function dayName(dateStr) { const d = parseLocal(dateStr); if (!d) return dateStr; const t = tzNow(); const today = ymd(t); const tom = ymd(new Date(t.getTime() + 86400000)); const yest = ymd(new Date(t.getTime() - 86400000)); const ds = dateStr.slice(0, 10); const nice = `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`; return ds === today ? `Today · ${nice}` : ds === tom ? `Tomorrow · ${nice}` : ds === yest ? `Yesterday · ${nice}` : nice; }
  function niceDate(dateStr) { const d = parseLocal(dateStr); return d ? `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}` : dateStr; }
  const koTime = (s) => (s || '').slice(11, 16);
  function koShort(s) { const d = parseLocal(s); if (!d) return s || ''; return `${DAYS[d.getDay()]} ${s.slice(11, 16)}`; }
  /** in-app confirm (Android WebView swallows window.confirm) */
  function confirmBox(title, text, okLabel) {
    return new Promise((resolve) => {
      const m = $('#modal'); if (!m) { resolve(window.confirm(`${title}\n\n${text}`)); return; }
      $('#modal-title').textContent = title; $('#modal-text').textContent = text || ''; $('#modal-ok').textContent = okLabel || 'OK';
      m.hidden = false;
      const done = (v) => { m.hidden = true; $('#modal-ok').onclick = null; $('#modal-cancel').onclick = null; m.onclick = null; resolve(v); };
      $('#modal-ok').onclick = () => done(true); $('#modal-cancel').onclick = () => done(false);
      m.onclick = (e) => { if (e.target === m) done(false); };
    });
  }
  // favourite matches (kept on the phone; tracked for goal / HT / FT alerts and kick-off reminders)
  let favs = [];
  try { favs = JSON.parse(stored('pr_favs_full') || localStorage.getItem('pr_favs') || '[]'); } catch (e) { favs = []; }
  const isFav = (id) => favs.some((f) => f.fixture === id);
  function saveFavs() {
    const keep = ymd(new Date(tzNow().getTime() - 2 * 86400000));
    favs = favs.filter((f) => f.kickoff.slice(0, 10) >= keep);
    persist('pr_favs_full', JSON.stringify(favs));
    if (native && native.setString) { try { native.setString('favs', JSON.stringify(favs.map((f) => ({ eid: f.eid, kickoff: f.kickoff, home: f.home, away: f.away, competition: f.competition })))); } catch (e) { /* ignore */ } }
  }
  function toggleFav(id) {
    const f = fx(id); if (!f) return;
    if (isFav(id)) { favs = favs.filter((x) => x.fixture !== id); toast('Removed from favourites'); }
    else { favs.push({ fixture: id, eid: f.livescore_id || null, kickoff: f.kickoff, home: f.home, away: f.away, competition: f.competition, country: f.country }); toast('Added to favourites — you will get goal and kick-off alerts'); }
    saveFavs(); render();
  }
  function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2400); }
  function pill(p, hi, mid) { const cls = p >= (hi || 0.7) ? 'hi' : p >= (mid || 0.6) ? 'mid' : ''; return `<span class="pill ${cls}">${pct(p)}</span>`; }
  function bar(p, cls) { return `<span class="bar"><span class="fill ${cls || ''}" style="width:${Math.round((p || 0) * 100)}%"></span></span>`; }
  function wdl(gf, ga) { return gf > ga ? 'W' : gf < ga ? 'L' : 'D'; }
  function formBadges(items) { return `<span class="form">${(items || []).map((r) => `<i class="f ${r}">${r}</i>`).join('')}</span>`; }
  const icon = (name, cls) => `<svg class="ic ${cls || ''}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const FLAGS = { England: '🏴󠁧󠁢󠁥󠁮󠁧󠁿', Scotland: '🏴󠁧󠁢󠁳󠁣󠁴󠁿', Wales: '🏴󠁧󠁢󠁷󠁬󠁳󠁿', Spain: '🇪🇸', Italy: '🇮🇹', Germany: '🇩🇪', France: '🇫🇷', Netherlands: '🇳🇱', Belgium: '🇧🇪', Portugal: '🇵🇹', Turkey: '🇹🇷', Greece: '🇬🇷',
    USA: '🇺🇸', Mexico: '🇲🇽', Argentina: '🇦🇷', Brazil: '🇧🇷', Japan: '🇯🇵', China: '🇨🇳', Norway: '🇳🇴', Sweden: '🇸🇪', Denmark: '🇩🇰', Finland: '🇫🇮', Poland: '🇵🇱', Romania: '🇷🇴', Russia: '🇷🇺',
    Austria: '🇦🇹', Switzerland: '🇨🇭', Ireland: '🇮🇪', Australia: '🇦🇺', 'South Africa': '🇿🇦', Turkiye: '🇹🇷', Croatia: '🇭🇷', Serbia: '🇷🇸', Czechia: '🇨🇿', 'Czech Republic': '🇨🇿',
    Slovakia: '🇸🇰', Slovenia: '🇸🇮', Hungary: '🇭🇺', Bulgaria: '🇧🇬', Ukraine: '🇺🇦', Israel: '🇮🇱', Egypt: '🇪🇬', Morocco: '🇲🇦', Algeria: '🇩🇿', Tunisia: '🇹🇳', Nigeria: '🇳🇬', Ghana: '🇬🇭', Kenya: '🇰🇪',
    'Saudi Arabia': '🇸🇦', Qatar: '🇶🇦', 'United Arab Emirates': '🇦🇪', UAE: '🇦🇪', Iran: '🇮🇷', Iraq: '🇮🇶', India: '🇮🇳', 'South Korea': '🇰🇷', 'Korea Republic': '🇰🇷', Colombia: '🇨🇴', Chile: '🇨🇱',
    Uruguay: '🇺🇾', Peru: '🇵🇪', Ecuador: '🇪🇨', Paraguay: '🇵🇾', Bolivia: '🇧🇴', Venezuela: '🇻🇪', Canada: '🇨🇦', Iceland: '🇮🇸', Cyprus: '🇨🇾', 'Northern Ireland': '🇬🇧', Guatemala: '🇬🇹', 'Costa Rica': '🇨🇷',
    Honduras: '🇭🇳', 'El Salvador': '🇸🇻', Panama: '🇵🇦', Jamaica: '🇯🇲', Estonia: '🇪🇪', Latvia: '🇱🇻', Lithuania: '🇱🇹', Belarus: '🇧🇾', Kazakhstan: '🇰🇿', Georgia: '🇬🇪', Armenia: '🇦🇲', Azerbaijan: '🇦🇿',
    Uzbekistan: '🇺🇿', Vietnam: '🇻🇳', Thailand: '🇹🇭', Indonesia: '🇮🇩', Malaysia: '🇲🇾', Singapore: '🇸🇬', Philippines: '🇵🇭', 'New Zealand': '🇳🇿', Bosnia: '🇧🇦', 'Bosnia and Herzegovina': '🇧🇦',
    'North Macedonia': '🇲🇰', Albania: '🇦🇱', Montenegro: '🇲🇪', Kosovo: '🇽🇰', Moldova: '🇲🇩', Luxembourg: '🇱🇺', Malta: '🇲🇹', 'Faroe Islands': '🇫🇴', Andorra: '🇦🇩', Gibraltar: '🇬🇮', Tanzania: '🇹🇿',
    Uganda: '🇺🇬', Zambia: '🇿🇲', Zimbabwe: '🇿🇼', Cameroon: '🇨🇲', Senegal: '🇸🇳', 'Ivory Coast': '🇨🇮', "Cote d'Ivoire": '🇨🇮', Angola: '🇦🇴', Mozambique: '🇲🇿', Botswana: '🇧🇼', Namibia: '🇳🇦',
    Ethiopia: '🇪🇹', Rwanda: '🇷🇼', Sudan: '🇸🇩', Libya: '🇱🇾', Jordan: '🇯🇴', Kuwait: '🇰🇼', Bahrain: '🇧🇭', Oman: '🇴🇲', Lebanon: '🇱🇧', Syria: '🇸🇾', 'Hong Kong': '🇭🇰', Bangladesh: '🇧🇩',
    'Costa Rica ': '🇨🇷', Nicaragua: '🇳🇮', 'Dominican Republic': '🇩🇴', Cuba: '🇨🇺', 'Trinidad and Tobago': '🇹🇹', Haiti: '🇭🇹', Fiji: '🇫🇯' };
  const flag = (country) => FLAGS[country] || (/^(UEFA|CONMEBOL|CONCACAF|CAF|AFC|FIFA|World|Europe|International|Friendl|Olympic|Africa|Asia|Copa)/i.test(country || '') ? '🏆' : '🌍');
  function hue(name) { let h = 0; for (const c of String(name || '')) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
  const initials = (name) => String(name || '?').replace(/\b(FC|CF|SC|AFC|Utd|United|City|Town|Athletic|Club|De|Los|Las|La|El)\b/g, '').trim().split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase() || '?';
  /** team badge: Livescore image when known, otherwise an initials disc coloured from the name */
  function badge(name, img, size) {
    img = img || state.badges[name];
    const cls = `badge s${size || 24}`;
    if (!img) return `<span class="${cls} nb" style="--h:${hue(name)}"><i>${esc(initials(name))}</i></span>`;
    return `<span class="${cls}" style="--h:${hue(name)}"><img src="${esc(BADGE_BASE + img)}" alt="" loading="lazy" decoding="async" onerror="this.parentNode.classList.add('nb');this.remove()"><i>${esc(initials(name))}</i></span>`;
  }
  const fxBadge = (f, side) => badge(f[side], f.badges && f.badges[side]);
  /** Sofascore-style match row: kick-off / status column, two team lines with badges and score, optional right block */
  /** team name wrapped in a tappable link to that team's stats page (AiScore-style) */
  function teamSpan(name, country, div) {
    return `<span class="tmn" data-team="${esc(name)}" data-country="${esc(country || '')}" data-div="${esc(div || '')}">${esc(name)}</span>`;
  }
  function matchRow(m, opts) {
    opts = opts || {}; const s = opts.live; const sc = s && s.hg != null ? s : (m.score && m.score.hg != null ? m.score : null);
    const status = sc ? (sc.status || '') : ''; const liveNow = sc && isLive(sc); const ft = sc && isFT(sc);
    const left = sc ? `<div class="minute ${liveNow ? 'on' : 'ft'}">${esc(liveNow ? status : ft ? 'FT' : status)}</div>${ft || liveNow ? '' : ''}` : `<div class="ko">${esc(opts.short ? koTime(m.kickoff) : koShort(m.kickoff)).replace(' ', '<br>')}</div>`;
    const hw = sc && sc.hg > sc.ag, aw = sc && sc.ag > sc.hg;
    const tm = (side, won) => `<div class="tm ${won ? 'won' : ''}">${badge(m[side], m.badges && m.badges[side], 22)}<span class="nm" data-team="${esc(m[side])}" data-country="${esc(m.country || '')}" data-div="${esc(m.div || '')}">${esc(opts.long ? (m[side + '_long'] || m[side]) : m[side])}</span>${sc ? `<span class="sc">${side === 'home' ? sc.hg : sc.ag}</span>` : ''}</div>`;
    return `<div class="mrow ${opts.tap === false ? '' : 'tap'} ${liveNow ? 'is-live' : ''}" data-fx="${esc(m.id)}"><div class="mrow-l">${left}</div>
      <div class="mrow-m">${tm('home', hw)}${tm('away', aw)}${opts.sub != null ? `<div class="sub">${opts.sub}</div>` : `<div class="sub">${flag(m.country)} ${esc(m.competition || m.league || '')}</div>`}</div>
      ${opts.right ? `<div class="mrow-r">${opts.right}</div>` : ''}</div>`;
  }
  const skeleton = (n) => `<div class="card sk">${Array.from({ length: n || 3 }).map(() => '<div class="sk-row"><span class="sk-b"></span><span class="sk-l"></span></div>').join('')}</div>`;
  /** 0–1 → SVG ring */
  function ring(p, label, size) {
    size = size || 64; const r = (size - 8) / 2, c = 2 * Math.PI * r, v = Math.max(0, Math.min(1, p || 0));
    const cls = v >= 0.8 ? 'hi' : v >= 0.6 ? 'mid' : 'lo';
    return `<div class="ring ${cls}" style="width:${size}px"><svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}"><circle class="tr" cx="${size / 2}" cy="${size / 2}" r="${r}"/><circle class="pr" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${(c * (1 - v)).toFixed(1)}"/></svg><div class="rv">${pct(p)}</div>${label ? `<div class="rl">${label}</div>` : ''}</div>`;
  }
  // ------------------------------------------------------------------ theme
  const darkMedia = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function applyTheme() {
    const t = settings.theme || 'system'; document.documentElement.dataset.theme = t;
    state.dark = t === 'dark' || (t === 'system' && !!(darkMedia && darkMedia.matches));
    if (native && native.setTheme) { try { native.setTheme(state.dark); } catch (e) { /* ignore */ } }
  }
  if (darkMedia && darkMedia.addEventListener) darkMedia.addEventListener('change', () => { if ((settings.theme || 'system') === 'system') applyTheme(); });
  applyTheme();
  function md(text) {
    let html;
    const clean = String(text || '').replace(/PlayReport(?: ZA)?|Goals Scanner/g, 'Mr 2 Odds').replace(/https?:\/\/(?:www\.)?(?:github\.com|raw\.githubusercontent\.com)\/\S*/g, '');
    try { html = marked.parse(clean, { gfm: true, breaks: false }); } catch (e) { return `<pre>${esc(clean)}</pre>`; }
    const box = document.createElement('div'); box.innerHTML = html;
    box.querySelectorAll('a[href]').forEach((a) => { if (/github\.com|githubusercontent\.com/i.test(a.href)) { const s = document.createElement('span'); s.textContent = a.textContent; a.replaceWith(s); } });
    box.querySelectorAll('table').forEach((t) => { const n = t.querySelector('tr') ? t.querySelector('tr').children.length : 0; if (n > 4) t.classList.add('wide'); });
    return box.innerHTML;
  }

  // ------------------------------------------------------------------ selections (codes shared with the model)
  const GROUPS = { result: 'Match result', dc: 'Double chance', goals: 'Total goals', btts: 'Both teams to score', team: 'Team goals', corners: 'Corners', cards: 'Cards' };
  const GROUP_ICON = { result: '🏆', dc: '🛡️', goals: '⚽', btts: '🔁', team: '🎯', corners: '🚩', cards: '🟨' };
  const line = (code) => parseInt(code.replace(/\D/g, ''), 10) / 10;
  /** user rule: Unders are ignored everywhere — Overs only. Under codes: U25, HU05/AU15 (team), CU85 / CHU35 / CAU55 (corners),
   *  KU35 / KHU25 / KAU25 (cards) and NBTTS (no BTTS). The old pattern let the team-level corner and card unders through. */
  const isUnder = (sel) => /^(?:NBTTS|(?:[HA]|C[HA]?|K[HA]?)?U\d+)$/.test(sel || '');
  /** user rules 2026-10-17: team goals (HO05, AU15 …) and double chance (1X, 12, X2) are dropped altogether, and
   *  Over 2.5 and BTTS START from a 55% model probability (everything else keeps its own bar). The server applies the
   *  same policy (policy.py); the app repeats it so a payload published before the change cannot show them either. */
  // 2026-10-27 model review: the families the Python policy dropped (policy.family_of) — unders, double chance,
  // cards / bookings, BTTS and Over 0.5 — are hidden client-side too, so an old cached payload cannot resurrect them.
  const isDropped = (sel) => isUnder(sel) || sel === '1X' || sel === '12' || sel === 'X2'
    || sel === 'BTTS' || sel === 'NBTTS' || sel === 'O05'
    || /^K[HA]?[OU]\d+$/.test(sel || '') || /^[HA][OU]\d+$/.test(sel || '');
  const SEL_FLOOR = { O25: 0.55, BTTS: 0.55, H: 0.55, D: 0.55, A: 0.55 };
  function selGroup(sel) {
    if (sel === 'H' || sel === 'D' || sel === 'A') return 'result';
    if (sel === '1X' || sel === '12' || sel === 'X2') return 'dc';
    if (sel === 'BTTS' || sel === 'NBTTS') return 'btts';
    if (sel[0] === 'O' || sel[0] === 'U') return 'goals';
    if (sel[0] === 'H' || sel[0] === 'A') return 'team';
    if (sel[0] === 'C') return 'corners';
    return 'cards';
  }
  function selLabel(sel, home, away) {
    home = home || 'Home'; away = away || 'Away';
    if (sel === 'H') return `${home} to win`; if (sel === 'A') return `${away} to win`; if (sel === 'D') return 'Draw';
    if (sel === '1X') return `${home} or draw`; if (sel === '12') return `${home} or ${away}`; if (sel === 'X2') return `Draw or ${away}`;
    if (sel === 'BTTS') return 'Both teams to score'; if (sel === 'NBTTS') return 'Not both teams to score';
    if (/^[OU]\d+$/.test(sel)) return `${sel[0] === 'O' ? 'Over' : 'Under'} ${line(sel).toFixed(1)} goals`;
    if (/^[HA][OU]\d+$/.test(sel)) return `${sel[0] === 'H' ? home : away} ${sel[1] === 'O' ? 'over' : 'under'} ${line(sel).toFixed(1)} goals`;
    if (/^C[HA][OU]\d+$/.test(sel)) return `${sel[1] === 'H' ? home : away} ${sel[2] === 'O' ? 'over' : 'under'} ${line(sel).toFixed(1)} corners`;
    if (/^K[HA][OU]\d+$/.test(sel)) return `${sel[1] === 'H' ? home : away} ${sel[2] === 'O' ? 'over' : 'under'} ${line(sel).toFixed(1)} cards`;
    if (sel[0] === 'C') return `${sel[1] === 'O' ? 'Over' : 'Under'} ${line(sel).toFixed(1)} corners`;
    if (sel[0] === 'K') return `${sel[1] === 'O' ? 'Over' : 'Under'} ${line(sel).toFixed(1)} cards`;
    return sel;
  }
  function selShort(sel) {
    const m = { H: '1', D: 'X', A: '2', '1X': '1X', '12': '12', X2: 'X2', BTTS: 'BTTS', NBTTS: 'No BTTS' };
    if (m[sel]) return m[sel];
    if (/^[OU]\d+$/.test(sel)) return `${sel[0] === 'O' ? 'O' : 'U'}${line(sel)}`;
    if (/^[HA][OU]\d+$/.test(sel)) return `${sel[0] === 'H' ? 'Home' : 'Away'} ${sel[1] === 'O' ? 'O' : 'U'}${line(sel)}`;
    if (sel[0] === 'C') return `Corners ${sel[1]}${line(sel)}`;
    if (sel[0] === 'K') return `Cards ${sel[1]}${line(sel)}`;
    return sel;
  }
  /** true / false / null (undecidable from goals) for a finished score */
  function settleSel(sel, hg, ag) {
    if (hg == null || ag == null) return null;
    const tot = hg + ag;
    if (sel === 'H') return hg > ag; if (sel === 'D') return hg === ag; if (sel === 'A') return ag > hg;
    if (sel === '1X') return hg >= ag; if (sel === '12') return hg !== ag; if (sel === 'X2') return ag >= hg;
    if (sel === 'BTTS') return hg > 0 && ag > 0; if (sel === 'NBTTS') return !(hg > 0 && ag > 0);
    if (/^[OU]\d+$/.test(sel)) return sel[0] === 'O' ? tot > line(sel) : tot < line(sel);
    if (/^[HA][OU]\d+$/.test(sel)) { const g = sel[0] === 'H' ? hg : ag; return sel[1] === 'O' ? g > line(sel) : g < line(sel); }
    return null;
  }
  /** provisional verdict while a match is in play */
  function liveVerdict(sel, s) {
    if (!s || s.status === 'NS' || s.hg == null) return { cls: '', text: 'not started' };
    const h = s.hg, a = s.ag, tot = h + a, ft = isFT(s), ok = settleSel(sel, h, a);
    if (ok == null) return { cls: '', text: ft ? 'settled later' : 'in play' };
    if (ft) return ok ? { cls: 'good', text: '✅ won' } : { cls: 'bad', text: '❌ lost' };
    if (/^[OU]\d+$/.test(sel) || /^[HA][OU]\d+$/.test(sel)) {
      const L = line(sel); const over = sel.includes('O');
      const g = /^[HA]/.test(sel) ? (sel[0] === 'H' ? h : a) : tot;
      if (over) return g > L ? { cls: 'good', text: '✅ landed' } : { cls: 'warn', text: `needs ${Math.ceil(L - g)} more` };
      return g < L ? { cls: 'warn', text: `on track (${g} so far)` } : { cls: 'bad', text: '❌ lost' };
    }
    if (sel === 'BTTS') return ok ? { cls: 'good', text: '✅ landed' } : { cls: 'warn', text: 'waiting' };
    if (sel === 'NBTTS') return ok ? { cls: 'warn', text: 'on track' } : { cls: 'bad', text: '❌ lost' };
    return ok ? { cls: 'good', text: 'winning now' } : { cls: 'bad', text: 'losing now' };
  }
  const isLive = (s) => s && s.status && s.status !== 'NS' && !['FT', 'AET', 'AP', 'Postp.', 'Canc.', 'Aband.'].includes(s.status);
  const isFT = (s) => s && ['FT', 'AET', 'AP'].includes(s.status);

  // ------------------------------------------------------------------ data
  /** sels rows: [sel, p (model), p_model, p_market (implied, comparison only), odds, disagreement flag, diff pp, EV] */
  const selObj = (x) => Array.isArray(x) ? { sel: x[0], p: x[1], p_model: x[2], p_sb: x[3], odds: x[4], diff: !!x[5], diff_pp: x.length > 6 ? x[6] : (x[2] != null && x[3] != null ? Math.round(1000 * (x[2] - x[3])) / 10 : null), ev: x.length > 7 ? x[7] : (x[2] != null && x[4] ? Math.round(1000 * (x[2] * x[4] - 1)) / 1000 : null) } : x;
  function indexData(d) {
    d._byId = {}; (d.fixtures || []).forEach((f) => { d._byId[f.id] = f; f.sels = (f.sels || []).map(selObj); f.p = f.p || {}; f.xg = f.xg || [null, null]; f.x12 = f.x12 || [null, null, null]; f.major = f.tier !== 'world'; });
    if (d.safe && d.safe.bets) d.safe.bets.forEach((b) => { const f = d._byId[b.fixture]; b.major = f ? f.major : true; });
    return d;
  }
  const fx = (id) => state.data && state.data._byId[id];
  /** on-phone cache of the small data files (per-match analysis, day history, team pages): pages open instantly
   *  from the cache and are refreshed in the background when the publication is newer than the cached copy */
  const CACHE_MAX = 400;      // entries …
  const CACHE_KB = 600;       // … and the whole cache stays under this (JSON characters) — WebView localStorage is small
  const cache = {
    // v1.6.61: namespace bumped pr_c -> pr_d and legacy pr_c:* entries are swept on boot — a cache entry
    // written by an older build must never survive an app update (wrong-match data could persist for
    // users who hit the pre-1.6.57 bug even after updating)
    key: (k) => 'pr_d:' + k,
    get(k) { try { const v = localStorage.getItem(this.key(k)); return v ? JSON.parse(v) : null; } catch (e) { return null; } },
    put(k, data, stamp) {
      const body = JSON.stringify({ t: Date.now(), s: stamp || '', d: data });
      let prev = 0; try { const old = localStorage.getItem(this.key(k)); prev = old ? old.length : 0; } catch (e) { prev = 0; }
      try { localStorage.setItem(this.key(k), body); this.bytes = (this.bytes || 0) - prev + body.length; }
      catch (e) { this.prune(true); try { localStorage.setItem(this.key(k), body); this.bytes = null; } catch (e2) { /* give up */ } }
      this.count = (this.count || 0) + 1;
      if (this.bytes == null || this.count % 10 === 0 || this.bytes > CACHE_KB * 1024) this.prune(false);
    },
    /** Oldest-first eviction. `hard` (a write just hit the quota) drops at least half the cache;
     *  otherwise the cache is trimmed when it grows past CACHE_MAX entries or CACHE_KB kilobytes. */
    prune(hard) {
      const items = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (!k || !k.startsWith('pr_d:')) continue;
        const v = localStorage.getItem(k) || '';
        let t = 0; try { t = (JSON.parse(v) || {}).t || 0; } catch (e) { t = 0; }
        items.push({ k, t, b: v.length });
      }
      if (!items.length) return;
      items.sort((a, b) => a.t - b.t);
      let total = items.reduce((a, x) => a + x.b, 0), n = items.length;
      const over = () => n > CACHE_MAX || total > CACHE_KB * 1024;
      if (!hard && !over()) return;
      if (hard) {
        const d = Math.max(Math.ceil(n / 2), 1);
        items.slice(0, d).forEach((x) => { localStorage.removeItem(x.k); total -= x.b; }); n -= d;
      }
      for (let i = 0; over() && i < items.length; i++) {
        const x = items[i];
        if (!localStorage.getItem(x.k)) continue;
        localStorage.removeItem(x.k); total -= x.b; n -= 1;
      }
      this.bytes = total;   // running size used by put() to keep the cache inside its budget
    },
    size() { let n = 0, b = 0; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith('pr_d:')) { n++; b += (localStorage.getItem(k) || '').length; } } return { n, kb: Math.round(b / 1024) }; },
    clear() { const keys = []; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith('pr_d:')) keys.push(k); } keys.forEach((k) => localStorage.removeItem(k)); },
  };
  try {   // one-time sweep of the pre-1.6.61 cache namespace (see key() above)
    const stale = []; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith('pr_c:')) stale.push(k); }
    stale.forEach((k) => localStorage.removeItem(k));
  } catch (e) { /* storage unavailable */ }
  const pubStamp = () => (state.data && state.data.meta ? String(state.data.meta.generated || '').replace(/\D/g, '') : '');
  /** sha1 hex — lets the app derive a fixture's detail-file key (data/app/fx/<key>.json) even when the
      fixture is not in the 24-hour index (server key = sha1(fixture_id)[:12]). */
  function sha1hex(str) {
    const data = unescape(encodeURIComponent(str));
    const n = data.length;
    const total = Math.ceil((n + 9) / 64) * 64;
    const bytes = new Uint8Array(total);
    for (let i = 0; i < n; i++) bytes[i] = data.charCodeAt(i);
    bytes[n] = 0x80;
    const bitLen = n * 8;
    bytes[total - 4] = (bitLen >>> 24) & 255; bytes[total - 3] = (bitLen >>> 16) & 255;
    bytes[total - 2] = (bitLen >>> 8) & 255; bytes[total - 1] = bitLen & 255;
    let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0;
    const w = new Int32Array(80);
    for (let b = 0; b < total; b += 64) {
      for (let i = 0; i < 16; i++) w[i] = (bytes[b + i * 4] << 24) | (bytes[b + i * 4 + 1] << 16) | (bytes[b + i * 4 + 2] << 8) | bytes[b + i * 4 + 3];
      for (let i = 16; i < 80; i++) { const x = w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]; w[i] = (x << 1) | (x >>> 31); }
      let a = h0, bb = h1, c = h2, d = h3, e = h4;
      for (let i = 0; i < 80; i++) {
        let f, k;
        if (i < 20) { f = (bb & c) | (~bb & d); k = 0x5a827999; }
        else if (i < 40) { f = bb ^ c ^ d; k = 0x6ed9eba1; }
        else if (i < 60) { f = (bb & c) | (bb & d) | (c & d); k = 0x8f1bbcdc; }
        else { f = bb ^ c ^ d; k = 0xca62c1d6; }
        const t = (((a << 5) | (a >>> 27)) + f + e + k + w[i]) | 0;
        e = d; d = c; c = (bb << 30) | (bb >>> 2); bb = a; a = t;
      }
      h0 = (h0 + a) | 0; h1 = (h1 + bb) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0; h4 = (h4 + e) | 0;
    }
    return [h0, h1, h2, h3, h4].map((x) => (x >>> 0).toString(16).padStart(8, '0')).join('');
  }
  /** full analysis of one match (per-match file); session memory first, then the on-phone cache, then the network */
  const detailKey = (id, d) => d || (fx(id) && fx(id).d) ||
    (id && String(id).includes('|') && !String(id).startsWith('live:') ? sha1hex(String(id)).slice(0, 12) : null);
  function detailCached(id, d) {
    const k = detailKey(id, d);
    if (k && resources && state.details[k] && !state.details[k].error) loadDetail(id, d).catch(() => {});
    return k ? state.details[k] || null : null;
  }
  function prepDetail(j) { j.sels = (j.sels || []).map(selObj); j.trends = j.trends || {}; j.teams = j.teams || { home: {}, away: {} }; j.h2h = j.h2h || []; return j; }
  async function fetchDetail(k, stamp) {
    const j = prepDetail(await getJson(rawUrl(`data/app/fx/${k}.json`) + '?t=' + (stamp || Math.floor(Date.now() / 900000))));
    state.details[k] = j; cache.put('fx/' + k, j, stamp); return j;
  }
  async function loadDetail(id, d) {
    const k = detailKey(id, d); if (!k) throw new Error('no detail key');
    if (resources) {
      await migrateResource(rawUrl(`data/app/fx/${k}.json`), 'fx/' + k);
      const row = fx(id);
      const j = await getJson(rawUrl(`data/app/fx/${k}.json`), null, { validate: (value) => String(value.id) === String(id) && (!row || value.home === row.home && value.away === row.away) });
      state.details[k] = prepDetail(j); trimModels(state.details, k, 32); return state.details[k];
    }
    if (state.details[k] && !state.details[k].error) return state.details[k];
    const stamp = pubStamp();
    const c = cache.get('fx/' + k);
    if (c && c.d) {
      const j = prepDetail(c.d);
      // a cached file that belongs to another match must never be shown (wrong-stats bug). The file must
      // PROVE its identity: matching id (an entry without one is legacy poison — refetch) and, when the
      // 24-hour index row is known, the very same teams.
      const fchk = fx(id);
      if (!j || !j.id || !id || String(j.id) !== String(id)
          || (fchk && (String(j.home || '') !== String(fchk.home) || String(j.away || '') !== String(fchk.away)))) {
        return fetchDetail(k, stamp);
      }
      const f = fx(id); state.details[k] = j;
      // a match that is still in the current publication may have a fresher analysis: refresh quietly
      if (f && !f.frozen && c.s !== stamp) fetchDetail(k, stamp).then(() => render()).catch(() => { /* keep cache */ });
      return j;
    }
    return fetchDetail(k, stamp);
  }
  /** warm the cache for the pages the user is most likely to open (bets of the day, safest bets, favourites) */
  function prefetchDetails() {
    if (!state.data) return;
    const d = state.data; const stamp = pubStamp(); const want = [];
    ((d.safe && d.safe.today && d.safe.today.bets) || []).forEach((b) => want.push(b.fixture));
    ((d.safe && d.safe.bets) || []).slice(0, 12).forEach((b) => want.push(b.fixture));
    favs.forEach((f) => want.push(f.fixture));
    const keys = []; want.forEach((id) => { const k = detailKey(id); if (k && !keys.includes(k)) keys.push(k); });
    let i = 0;
    const next = () => {
      if (i >= keys.length || i >= 30) return;
      const k = keys[i++]; const c = cache.get('fx/' + k);
      if (c && c.s === stamp) { next(); return; }
      (resources ? getJson(rawUrl(`data/app/fx/${k}.json`)) : fetchDetail(k, stamp)).catch(() => { /* ignore */ }).finally(() => setTimeout(next, 150));
    };
    next(); // Serial warm-up; the repository caps total foreground requests at two.
  }
  /** Keep the published index on the phone for the next cold start. A full analysis is large and the
   *  WebView's localStorage is small (and shared with the on-phone cache), so a write that does not fit
   *  must never look like a network failure: the derived lookup map is dropped (it is rebuilt on load),
   *  the cache is trimmed and the write is retried once — if it still does not fit, the analysis simply
   *  stays in memory for this session. Returns whether a saved copy exists. */
  function saveLatest(d) {
    const strip = (o) => JSON.stringify(o, (k, v) => (k === '_byId' ? undefined : v));   // _byId is derived: rebuilt by indexData()
    const tryWrite = (body) => {
      try {
        localStorage.setItem('pr_latest', body);
        if (native && native.setString && body.length < 300000) { try { native.setString('latest', body); } catch (e0) { /* ignore */ } }
        return true;
      } catch (e) { return false; }
    };
    let body = strip(d);
    if (tryWrite(body)) return true;
    cache.prune(true);                                     // the cache is expendable, the analysis is not
    if (tryWrite(body)) return true;
    // still bigger than this phone's storage allows: the market rows of unpriced matches carry no
    // prices and only duplicate the shortlists — drop them and keep a usable offline copy
    const light = Object.assign({}, d, { _light: true, fixtures: (d.fixtures || []).map((f) => (f.priced ? f : Object.assign({}, f, { sels: [] }))) });
    body = strip(light);
    if (tryWrite(body)) return true;
    return false;
  }
  async function loadData(force) {
    if (state.loading) return; state.loading = true; $('#btn-refresh').classList.add('spin');
    if (!state.data) $('#view').innerHTML = skeleton(6);
    try {
      await migrateResource(DATA_URL, 'pr_latest');
      const raw = await getJson(DATA_URL, null, { force: !!force });
      if (state.data !== raw) { state.data = indexData(raw); if (!resources) state.data._cached = saveLatest(state.data); render(); }
      state.data._loadedAt = resources ? resources.status(DATA_URL).checkedAt : Date.now();
      statusLine(); if (force) toast(resources ? 'Checking for updates — saved data stays visible' : 'Updated');
    } catch (e) {
      if (!state.data) { let c = null; try { c = stored('pr_latest'); } catch (_) { /* keep memory */ } if (c) { try { const j = JSON.parse(c); if (validResource(DATA_URL, j)) { state.data = indexData(j); render(); } } catch (_) { /* invalid legacy copy */ } } }
      statusLine();
      if (force) toast(state.data ? 'Could not refresh — showing saved data' : 'No saved data yet. Check your connection.');
      if (!state.data) $('#view').innerHTML = '<div class="empty">No saved data yet.<br>Check your connection and pull to refresh.</div>';
    } finally { state.loading = false; $('#btn-refresh').classList.remove('spin'); if (native && native.refreshDone) native.refreshDone(); }
  }
  function screenResource() {
    const top = state.stack[state.stack.length - 1];
    if (top && top.type === 'match') { const k = detailKey(top.id, top.d); if (k) return rawUrl(`data/app/fx/${k}.json`); }
    if (top && top.type === 'day') return rawUrl(`data/app/days/${top.date}.json`);
    if (top && top.type === 'team' && top.div) return rawUrl(`data/app/teams/${slug(top.div)}.json`);
    if (top && top.type === 'league') return rawUrl('data/app/leagues/' + top.slug);
    if (top && top.type === 'analysis') return rawUrl(`reports/${top.date || ((state.data.history || {}).reports || [])[0] || state.data.meta.generated.slice(0, 10)}.md`);
    if (state.tab === 'leagues') return rawUrl('data/app/leagues/' + (state.lgTab === 'fixtures' ? 'fixtures.json' : 'index.json'));
    if (state.tab === 'live' && state.liveResource) return state.liveResource;
    return DATA_URL;
  }
  function statusLine() {
    if (!resources) return;
    const v = $('#view'); if (!v) return;
    let el = $('#data-status');
    if (!el) { el = document.createElement('div'); el.id = 'data-status'; el.className = 'tiny muted data-status'; el.setAttribute('role', 'status'); v.prepend(el); }
    const info = resources.status(screenResource());
    const m = state.data && state.data.meta;
    let text = info.offline ? 'Offline · saved information' : info.error ? 'Refresh unavailable · saved information' : info.stale ? 'Saved information · refresh due' : 'Downloaded information';
    if (info.checkedAt) text += ' · checked ' + new Date(info.checkedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (m && screenResource() === DATA_URL) {
      text += ' · published ' + m.generated;
      const published = parseLocal(m.generated); if (published && tzNow() - published > 60 * 60000) text += ' · publication may be out of date';
    }
    if ((state.tab === 'live' && (info.stale || info.offline || info.error)) || state.liveStale && (state.tab === 'live' || state.tab === 'home' || (state.stack[state.stack.length - 1] || {}).type === 'match')) text += ' · scores are not confirmed current';
    if (el.textContent !== text) el.textContent = text;
  }
  async function loadDay(date) {
    if (resources) { await migrateResource(rawUrl(`data/app/days/${date}.json`), 'days/' + date); const j = await getJson(rawUrl(`data/app/days/${date}.json`)); state.days[date] = j; trimModels(state.days, date, 14); return j; }
    if (state.days[date] && state.days[date].fixtures) return state.days[date];
    const c = cache.get('days/' + date); const today = ymd(tzNow());
    const fetchIt = async () => { const j = await getJson(rawUrl(`data/app/days/${date}.json`) + '?t=' + Math.floor(Date.now() / 300000)); state.days[date] = j; cache.put('days/' + date, j, date < today ? 'final' : pubStamp()); return j; };
    if (c && c.d) {
      state.days[date] = c.d;
      // past days settle over a few hours (results, statistics); refresh them in the background until they are a day old
      if (date >= today || (c.s !== 'final' && Date.now() - c.t > 30 * 60000) || (date >= ymd(new Date(tzNow().getTime() - 86400000)) && Date.now() - c.t > 30 * 60000)) fetchIt().then(() => render()).catch(() => { /* keep cache */ });
      return c.d;
    }
    return fetchIt();
  }
  /** A published league table is only trusted when it can be one. The server now publishes a table for
   *  league-format competitions only (teamstats.league_like: teams must face several different opponents);
   *  this shape check is the second line of defence, so a phone still holding an older publication — or a
   *  competition whose pool is not a round-robin — never shows a pool of clubs as "standings". Real tables
   *  hold at most 36-40 teams (the group stages of the big competitions); anything larger is a cup, a
   *  qualifying round or a friendly list. Returns the table, or null when it cannot be one. */
  const TABLE_MAX_TEAMS = 48;      // the biggest real tables are 36-40 rows; a "table" of hundreds is a pool
  function realTable(table) {
    if (!Array.isArray(table) || !table.length || table.length > TABLE_MAX_TEAMS) return null;
    return table.some((r) => r && typeof r.p === 'number' && r.p > 0) ? table : null;
  }
  /** A model probability that towers over the price is not value — it is a data fault. The live feed has
   *  friendlies priced 0.6% for a team the model rates 29%, and cup qualifiers priced 17% for a team the
   *  model rates 64%. Sorted by probability those legs lead the board, which is exactly how a punter picks
   *  them. Anything at or above this gap is quarantined from the raw board (the same edge gate the old acca builder used
   *  rejects the same legs server-side). Returns true when the leg should be hidden. */
  const OUTLIER_PP = 0.15;        // against the de-vigged market view
  const OUTLIER_RAW_PP = 0.25;    // …and a looser one against the raw price, used only when there is no
  const isOutlier = (s) => {      //    de-vigged view (the price alone still contains the bookmaker's margin)
    if (!s || !(s.odds > 1) || s.p_model == null || s.p_model <= 0) return false;
    if (s.p_sb != null && s.p_sb > 0) return (s.p_model - s.p_sb) >= OUTLIER_PP;
    return (s.p_model - 1 / s.odds) >= OUTLIER_RAW_PP;
  };
  const slug = (div) => String(div || '').replace(/[^A-Za-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  async function loadTeams(div) {
    const k = slug(div);
    if (resources) { await migrateResource(rawUrl(`data/app/teams/${k}.json`), 'teams/' + k); const j = await getJson(rawUrl(`data/app/teams/${k}.json`)); state.teams[k] = j; trimModels(state.teams, k, 12); return j; }
    if (state.teams[k]) return state.teams[k];
    const c = cache.get('teams/' + k);
    const fetchIt = async () => { const j = await getJson(rawUrl(`data/app/teams/${k}.json`) + '?t=' + Math.floor(Date.now() / 3600000)); state.teams[k] = j; cache.put('teams/' + k, j, ymd(tzNow())); return j; };
    if (c && c.d) { state.teams[k] = c.d; if (c.s !== ymd(tzNow())) fetchIt().then(() => render()).catch(() => { /* keep cache */ }); return c.d; }
    return fetchIt();
  }
  function teamsCached(div) { if (resources && state.teams[slug(div)]) loadTeams(div).catch(() => {}); return state.teams[slug(div)] || null; }
  /** Sportybet deep link for a match (public event page — opens in their app/site, no login to view). */
  function sbSlug(s) {
    s = String(s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    return (s.replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')) || 'football';
  }
  function sbEventUrl(ev) {
    if (!ev || !ev.id) return null;
    const h = ev.home && ev.away ? `${sbSlug(ev.home)}_v_${sbSlug(ev.away)}` : '';
    return `https://www.sportybet.com/za/sport/sr:sport:1/${sbSlug(ev.country || 'football')}/${sbSlug(ev.tournament || 'football')}/${h}/${ev.id}/`;
  }
  /** Sportybet booking-code share link (loads the code in the Sportybet app/site). */
  function sbShareUrl(code) {
    const c = String(code || '').replace(/[^A-Za-z0-9]/g, '');
    return c ? `https://www.sportybet.com/za/?shareCode=${c}` : null;
  }
  function openSportybet(ev) { const u = sbEventUrl(ev); if (u) openExternal(u); }
  function openBookingCode(code) { const u = sbShareUrl(code); if (u) openExternal(u); }
  function openExternal(u) { if (PR.native && PR.native.openUrl) PR.native.openUrl(u); else window.open(u, '_blank'); }
  /** Copy text to the clipboard (WebView-safe fallbacks), returns success. */
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall through */ }
    try {
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.focus(); ta.select();
      const ok = document.execCommand('copy'); ta.remove(); return ok;
    } catch (e) { return false; }
  }
  /** Global club index (data/app/teams/teams-index.json) for team search — every team in the model pool. */
  async function loadTeamIndex() {
    if (resources) { await migrateResource(rawUrl('data/app/teams/teams-index.json'), 'teams-idx'); state.teamIdx = await getJson(rawUrl('data/app/teams/teams-index.json')); return state.teamIdx; }
    if (state.teamIdx) return state.teamIdx;
    if (state.teamIdxLoading) return null;
    state.teamIdxLoading = true;
    try {
      const j = await getJson(rawUrl('data/app/teams/teams-index.json') + '?t=' + Math.floor(Date.now() / 3600000));
      state.teamIdx = j; PR.cache.put('teams-idx', j, j.generated || '');
    } catch (e) {
      const c = PR.cache.get('teams-idx');
      if (c && c.d) state.teamIdx = c.d;
    } finally { state.teamIdxLoading = false; }
    return state.teamIdx;
  }
  async function loadBadges() {
    if (resources) { try { state.badges = await getJson(rawUrl('data/app/badges.json')); } catch (_) { /* offline */ } return; }
    try { const c = stored('pr_badges'); if (c) state.badges = JSON.parse(c); } catch (e) { /* ignore */ }
    try { const j = await getJson(rawUrl('data/app/badges.json') + '?t=' + Math.floor(Date.now() / 86400000)); if (j && typeof j === 'object') { state.badges = j; saveAux('pr_badges', JSON.stringify(j)); } } catch (e) { /* offline: keep cache */ }
  }

  // ------------------------------------------------------------------ navigation (primary shell: Home / Scan / Live / Matches / More —
  // Low odds, Shortlist, Sequences, Days and Leagues remain valid secondary destinations under More)
  const TABS = ['home', 'bets', 'live', 'matches', 'lowodds', 'shortlist', 'x12', 'sequences', 'days', 'leagues', 'more'];
  const TAB_TITLE = { home: 'Mr 2 Odds', bets: 'Scan', live: 'Live', matches: 'Matches', lowodds: 'Low odds 1.19 – 1.45', more: 'More', days: 'Days', leagues: 'Leagues', shortlist: 'Shortlist', x12: '1X2', sequences: 'Sequences' };
  const MORE_TABS = ['lowodds', 'shortlist', 'x12', 'sequences', 'days', 'leagues'];
  const NAV_PREF_KEYS = ['sort', 'matchFilter', 'matchesView', 'homeTab', 'homeSort', 'homeMk', 'homeShow', 'slMk', 'betsView', 'liveView', 'lgSort', 'lgTableSort', 'betGroup', 'board'];
  function navKey() {
    const top = state.stack[state.stack.length - 1];
    if (top) return 'p:' + top.type + ':' + String(top.id || top.name || top.slug || top.date || '');
    return 't:' + state.tab;
  }
  function rememberScroll() {
    state.scrolls = state.scrolls || {};
    state.scrolls[navKey()] = window.scrollY || 0;
  }
  function restoreScroll() {
    const y = (state.scrolls || {})[navKey()] || 0;
    const go = () => window.scrollTo(0, y);
    go();
    requestAnimationFrame(go);
    setTimeout(go, 0);
  }
  function persistNav() {
    const n = { tab: state.tab };
    NAV_PREF_KEYS.forEach((k) => { if (state[k] != null) n[k] = state[k]; });
    if (typeof state.safestAll === 'boolean') n.safestAll = state.safestAll;
    persist('pr_nav', JSON.stringify(n));
  }
  function loadNav() {
    try {
      const n = JSON.parse(stored('pr_nav') || '{}');
      if (!n || typeof n !== 'object') return;
      NAV_PREF_KEYS.forEach((k) => { if (n[k] != null) state[k] = n[k]; });
      if (typeof n.safestAll === 'boolean') state.safestAll = n.safestAll;
      if (n.tab && TABS.includes(n.tab)) state.tab = n.tab;
    } catch (e) { /* ignore */ }
  }
  loadNav();
  function paintChrome(tab) {
    const navTab = MORE_TABS.includes(tab) ? 'more' : tab;
    const ttl = $('#top .title'); if (ttl) ttl.textContent = TAB_TITLE[tab] || 'Mr 2 Odds';
    $$('#tabs button').forEach((b) => {
      const active = b.dataset.tab === navTab;
      b.classList.toggle('active', active);
      if (active) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    });
  }
  function render(quiet) {
    if (!state.data && !(state.stack.length && state.stack[state.stack.length - 1].type === 'settings')) return;
    closeMenu();
    const top = state.stack[state.stack.length - 1];
    if (state.data && (state.data.version || 1) < 3 && !(top && top.type === 'settings')) {
      $('#view').innerHTML = `<div class="card empty">This version of Mr 2 Odds needs the new analysis format.<br>It arrives with the next scheduled analysis — pull down to refresh later.</div>`;
      return;
    }
    const v = $('#view'); if (quiet !== true) { v.classList.remove('enter'); void v.offsetWidth; v.classList.add('enter'); }
    document.body.classList.toggle('depth', !!top);
    paintChrome(state.tab);
    if (top) PR.pages[top.type](top); else PR.views[state.tab]();
    injectSearch();
    statusLine();
    persistNav();
    if (resources) setTimeout(refreshVisible, 0);
  }
  function setTab(tab, opts) {
    opts = opts || {};
    if (tab === 'today') tab = 'home';
    if (!TABS.includes(tab)) tab = 'home';
    // already on this destination: tapping the tab again pops a match/team page back to the list
    if (!opts.boot && !opts.fromBack && tab === state.tab) {
      if (state.stack.length) {
        rememberScroll();
        state.stack = [];
        render();
        restoreScroll();
      }
      return;
    }
    rememberScroll();
    if (!opts.boot && !opts.fromBack) {
      state.tabHist = state.tabHist || [];
      state.tabHist.push(state.tab);
      if (state.tabHist.length > 16) state.tabHist.shift();
    }
    state.tab = tab;
    state.stack = [];
    render();
    if (opts.restore) restoreScroll();
    else window.scrollTo(0, 0);
    if (tab === 'live' && state.data && Date.now() - state.lastLive > 15000) PR.live.refresh(false);
  }
  function push(page) { rememberScroll(); state.stack.push(page); render(); window.scrollTo(0, 0); }
  function replace(page) { state.stack[state.stack.length - 1] = page; render(); }
  function back() {
    if (state.menuOpen) { closeMenu(); return true; }
    rememberScroll();
    if (state.stack.length) { state.stack.pop(); render(); restoreScroll(); return true; }
    if (state.tab !== 'home') {
      const hist = state.tabHist || [];
      let prev = null;
      while (hist.length) {
        const t = hist.pop();
        if (t && t !== state.tab && TABS.includes(t)) { prev = t; break; }
      }
      setTab(prev || 'home', { fromBack: true, restore: true });
      return true;
    }
    return false;
  }
  /** The day-file record of a fixture (final score, half-time, statistics, goal incidents, bets) once its day is loaded. */
  function dayRecord(id) {
    if (!id) return null; const date = String(id).slice(0, 10); const day = state.days[date];
    return day && day.fixtures ? (day.fixtures.find((x) => x.id === id) || null) : null;
  }
  /** Final score + stats of a finished match from the archive (day files). Loads the day in the background for
   *  matches that kicked off more than two hours ago; returns null until it is there. */
  function finalFor(f) {
    if (!f || !f.kickoff) return null;
    const date = f.kickoff.slice(0, 10); const r = dayRecord(f.id);
    if (r) return r.score && r.score.hg != null ? r.score : null;
    const ko = parseLocal(f.kickoff);
    if (ko && tzNow() - ko > 2 * 3600000 && !(state.days[date] && state.days[date].fixtures) && !state.days[date + '_loading']) {
      state.days[date + '_loading'] = true; loadDay(date).then(() => render()).catch(() => { state.days[date + '_loading'] = false; });
    }
    return null;
  }
  /** Stored incidents ([minute, team, type, player, score] rows) in the live-incident item shape. */
  function storedIncidents(sc) {
    if (!sc || !Array.isArray(sc.inc)) return null;
    const T = { own_goal: 'own goal', second_yellow: 'second yellow', missed_penalty: 'missed penalty' };
    return sc.inc.map((r) => ({ min: r[0], team: r[1], type: T[r[2]] || r[2], player: r[3], score: r[4] }));
  }
  function openMatch(id, d) {
    const go = () => { state.matchView = 'overview'; push({ type: 'match', id, d: d || null }); };
    if (fx(id) || d || dayRecord(id)) return go();
    // not in the 24-hour index: the match page resolves the fixture from its detail file (sha1 key) or the
    // 60-day day archive — every fixture with published stats stays reachable
    if (id && String(id).includes('|') && !String(id).startsWith('live:')) return go();
    const date = ymd(tzNow());
    const teams = (state.liveTeams || {})[id];
    const idp = String(id || '').split('|');
    loadDay(date).then(() => {
      const day = state.days[date];
      // exact id first; the name fallback must also match the country (two countries can field the same
      // club names on the same day) — a looser match once opened the wrong match
      const rec = day && day.fixtures ? day.fixtures.find((x) => x.id === id
        || (teams && teams.length > 2 ? x.home === teams[0] && x.away === teams[1] && x.country === teams[2] : false)
        || (idp.length > 3 && x.home === idp[2] && x.away === idp.slice(3).join('|') && x.country === idp[1])) : null;
      if (rec) { state.matchView = 'overview'; push({ type: 'match', id: rec.id, d: null }); }
      else toast('Stats for this match are not available yet.');
    }).catch(() => toast('Stats for this match are not available yet.'));
  }
  function openTeam(name, country, div) { state.teamView = 'overview'; push({ type: 'team', name, country, div }); }
  function toggleMenu() { state.menuOpen = !state.menuOpen; $('#menu').classList.toggle('open', state.menuOpen); }
  function closeMenu() { state.menuOpen = false; const m = $('#menu'); if (m) m.classList.remove('open'); }

  // ------------------------------------------------------------------ shared UI fragments
  const EDITOR = { name: 'Ndumiso Msani', role: 'Founder & Football Analyst', place: 'Mthwalume, KwaZulu-Natal',
    bio: 'Founder of Mr 2 Odds and a football analyst with a data-first approach. Ndumiso built the platform to turn thousands of match results, prices and team statistics into a small number of disciplined, graded selections every day — specialising in the goals and corners markets across world football. Every pick is published before kick-off and graded against the final result.' };
  function editorCard(compact) {
    // compact: round avatar next to the name (home page); full: portrait photo with the profile (About / Guide)
    if (!compact) return `<div class="card"><div class="editor full"><div class="portrait"><img src="editor.jpg" alt="${esc(EDITOR.name)}" onerror="this.parentNode.style.display='none'"></div><div class="grow"><div class="b" style="font-size:17px">${esc(EDITOR.name)}</div><div class="small muted">${esc(EDITOR.role)}</div><div class="small muted">${esc(EDITOR.place)}</div><div class="small" style="margin-top:8px">${esc(EDITOR.bio)}</div></div></div>
      <div class="tiny muted" style="margin-top:8px">Every selection published here is graded automatically against the final result — the record under Performance is the only opinion that counts. Statistical information, not betting advice. 18+.</div></div>`;
    return `<div class="card"><div class="editor"><div class="avatar"><img src="editor_sq.jpg" alt="" onerror="this.style.display='none'"></div><div class="grow"><div class="b">${esc(EDITOR.name)}</div><div class="small muted">${esc(EDITOR.role)} · ${esc(EDITOR.place)}</div>${compact ? '' : `<div class="small" style="margin-top:6px">${esc(EDITOR.bio)}</div>`}</div></div>
      ${compact ? '' : `<div class="tiny muted" style="margin-top:8px">Every selection published here is graded automatically against the final result — the record under Performance is the only opinion that counts. Statistical information, not betting advice. 18+.</div>`}</div>`;
  }
  function contactCard(compact) {
    return `<div class="card contact"><div class="row"><div class="grow"><b>Contact</b>${compact ? '' : '<div class="small muted">Questions, feedback or a request? Get in touch.</div>'}</div></div>
      <div class="contact-row"><a class="btn wa" href="https://wa.me/${CONTACT.whatsapp}">${icon('chat')} WhatsApp ${esc(CONTACT.whatsappShown)}</a>
      <a class="btn" href="mailto:${esc(CONTACT.email)}">${icon('mail')} ${esc(CONTACT.email)}</a></div></div>`;
  }
  /** True when two club strings name the same side (short vs long bookmaker name is fine; different clubs are not). */
  function namesAgree(a, b) {
    if (!a || !b) return false;
    const n = (s) => String(s).normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
    const stop = /^(fc|afc|cf|sc|ac|club|de|the|ud|cd|fk|sk)$/;
    const toks = (s) => n(s).split(' ').filter((t) => t && !stop.test(t));
    const ta = toks(a), tb = toks(b);
    if (!ta.length || !tb.length) return false;
    const sa = ta.join(' '), sb2 = tb.join(' ');
    if (sa === sb2 || sa.includes(sb2) || sb2.includes(sa)) return true;
    const A = new Set(ta), B = new Set(tb);
    let hit = 0; A.forEach((t) => { if (B.has(t) && t.length >= 3) hit++; });
    if (hit) return true;
    const stem = (t) => t.slice(0, Math.min(5, t.length));
    return ta.some((x) => tb.some((y) => stem(x) === stem(y) && Math.min(x.length, y.length) >= 4));
  }
  function displayName(f, side) {
    const name = (f && f[side]) || '';
    const long = f && f[side + '_long'];
    return (long && namesAgree(name, long)) ? long : name;
  }
  function fittedSbEvent(f) {
    const ev = f && f.sportybet_event;
    if (!ev || !ev.id) return null;
    if (ev.home && f.home && !namesAgree(f.home, ev.home)) return null;
    if (ev.away && f.away && !namesAgree(f.away, ev.away)) return null;
    return ev;
  }
  function teamLink(f, side) {
    const name = side === 'home' ? f.home : f.away;
    return `<a class="team" href="#" data-team="${esc(name)}" data-country="${esc(f.country)}" data-div="${esc(f.div)}">${esc(displayName(f, side))}</a>`;
  }
  function matchLine(f, extra) { return matchRow(f, { right: extra || '' }); }
  function segmented(items, current, attr) {
    return `<div class="seg">${items.map(([k, label]) => `<button class="${k === current ? 'on' : ''}" data-${attr}="${k}">${label}</button>`).join('')}</div>`;
  }
  function select(id, options, current) {
    return `<select id="${id}">${options.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(current) ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  }
  function scoreBox(s, f) {
    if (s && s.hg != null) return `<div class="right"><div class="score">${s.hg} – ${s.ag}</div>${isFT(s) ? `<span class="minute ft">${esc(s.status)}</span>` : isLive(s) ? `<span class="minute">${esc(s.status)}</span>` : `<span class="minute ft">${esc(koShort(f.kickoff))}</span>`}</div>`;
    return `<div class="right"><div class="score muted">v</div><span class="minute ft">${esc(koShort(f.kickoff))}</span></div>`;
  }
  const statusIcon = (st) => ({ hit: '✅', won: '✅', miss: '❌', lost: '❌', void: '∅', pending: '⏳' }[st] || '');

  // ------------------------------------------------------------------ global click handling
  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-team]');
    if (t) { e.preventDefault(); e.stopPropagation(); openTeam(t.dataset.team, t.dataset.country, t.dataset.div); return; }
    const m = e.target.closest('[data-fx]');
    if (m && (m.classList.contains('tap') || m.tagName === 'A' || m.tagName === 'BUTTON')) { e.preventDefault(); openMatch(m.dataset.fx, m.dataset.d || null); return; }
    const a = e.target.closest('a[href]');
    if (a && /^(https?:|mailto:|tel:)/.test(a.getAttribute('href')) && native && native.openUrl) { e.preventDefault(); native.openUrl(a.href); return; }
    if (state.menuOpen && !e.target.closest('#menu') && !e.target.closest('#btn-menu') && !e.target.closest('#btn-search')) closeMenu();
  });

  // ------------------------------------------------------------------ universal search (bar on every page)
  // One bar, everything: matches, bets/markets, teams, leagues, days and the app's own pages.
  // The input repaints only the results panel (never the whole view), so focus is never lost while typing.
  const PLACES = [
    { label: 'Bets of the day', icn: 'star', go: { tab: 'bets' } }, { label: 'Live scores', icn: 'live', go: { tab: 'live' } },
    { label: 'Matches', icn: 'calendar', go: { tab: 'matches' } }, { label: 'Low odds 1.19 – 1.45', icn: 'tag', go: { tab: 'lowodds' } },
    { label: 'Shortlist', icn: 'target', go: { tab: 'shortlist' } }, { label: '1X2', icn: 'star', go: { tab: 'x12' } }, { label: 'Days', icn: 'history', go: { tab: 'days' } },
    { label: 'Leagues', icn: 'trophy', go: { tab: 'leagues' } },
    { label: 'Tickets', icn: 'ticket', go: { page: 'tickets' } }, { label: 'Teams', icn: 'users', go: { page: 'teams' } },
    { label: 'Performance', icn: 'chart', go: { page: 'performance' } }, { label: 'Bet advisor', icn: 'shield', go: { page: 'advisor' } },
    { label: 'All markets', icn: 'swap', go: { page: 'marketsboard' } }, { label: 'Guide to the markets', icn: 'info', go: { page: 'guide' } },
    { label: 'Full analysis', icn: 'doc', go: { page: 'analysis' } },
    { label: 'Settings', icn: 'settings', go: { page: 'settings' } },
  ];
  function searchResults(qs) {
    const q = (qs || '').trim().toLowerCase();
    if (q.length < 2) return '';
    const d = state.data || { fixtures: [] };
    const hit = (t) => String(t || '').toLowerCase().includes(q);
    const grp = (name, rows) => (rows.length ? `<div class="gs-h">${name}</div>${rows.join('')}` : '');
    const out = [];
    // matches (analysis window)
    const fx = (d.fixtures || []).filter((f) => hit(f.home) || hit(f.away) || hit(f.league || f.competition) || hit(f.country)).slice(0, 6)
      .map((f) => `<div class="list-item tap gsr" data-gsf="${esc(f.id)}"><span class="ko">${esc(koShort(f.kickoff))}</span><div class="main"><div class="match">${esc(f.home)} v ${esc(f.away)}</div><div class="meta">${flag(f.country)} ${esc(f.league || f.competition || '')}</div></div>${icon('next')}</div>`);
    out.push(grp('Matches', fx));
    // bets / markets (priced selections whose label matches — the only group that needs a longer query)
    if (q.length >= 3) {
      const bets = [];
      const seenFx = new Set();
      for (const f of (d.fixtures || [])) {
        if (!Array.isArray(f.sels) || seenFx.has(f.id)) continue;
        for (const s of f.sels) {
          if (!s || !s.sel || isDropped(s.sel)) continue;
          const lbl = selLabel(s.sel, f.home, f.away);
          if (lbl && hit(lbl) && s.odds) {
            seenFx.add(f.id);   // one market per match here too
            bets.push(`<div class="list-item tap gsr" data-gsf="${esc(f.id)}"><span class="ko">${esc(koShort(f.kickoff))}</span><div class="main"><div class="match">${esc(lbl)} <span class="tiny muted">@ ${f2(s.odds)}</span></div><div class="meta">${esc(f.home)} v ${esc(f.away)}</div></div>${icon('next')}</div>`);
            break;
          }
        }
        if (bets.length >= 6) break;
      }
      out.push(grp('Bets', bets));
    }
    // teams (worldwide index, loaded on demand)
    const tIdx = state.teamIdx;
    if (!tIdx) PR.loadTeamIndex().then((j) => { if (j && (state.q || '').trim().toLowerCase() === q) paintResults(); }).catch(() => { /* offline */ });
    const teams = tIdx ? (tIdx.teams || []).filter((t) => hit(t.n)).slice(0, 6)
      .map((t) => `<div class="list-item tap gsr" data-gsteam="${esc(t.n)}|${esc(t.c)}|${esc(t.d)}"><span class="ko">${badge(t.n, null, 24)}</span><div class="main"><div class="match">${esc(t.n)}</div><div class="meta">${flag(t.c)} ${esc(t.c || '')} · ${esc(t.l || '')}</div></div>${icon('next')}</div>`) : [];
    out.push(grp('Teams', teams));
    // leagues
    const lidx = (PR.leaguesIndex && PR.leaguesIndex()) || null;
    const lgs = lidx ? (lidx.leagues || []).filter((x) => hit(x.league) || hit(x.country)).slice(0, 5)
      .map((x) => `<div class="list-item tap gsr" data-gslg="${esc(x.slug)}"><span class="ko">${x.table ? icon('trophy') : flag(x.country)}</span><div class="main"><div class="match">${esc(x.league)}</div><div class="meta">${esc(x.country || '')}${x.next ? ` · next ${esc(koShort(x.next))}` : ''}</div></div>${icon('next')}</div>`) : [];
    out.push(grp('Leagues', lgs));
    // days (archive)
    const days = ((d.history || {}).days || []).filter((x) => hit(x.date) || hit(dayName(x.date))).slice(0, 3)
      .map((x) => `<div class="list-item tap gsr" data-gsday="${esc(x.date)}"><span class="ko">${icon('calendar')}</span><div class="main"><div class="match">${esc(dayName(x.date))}</div><div class="meta">${x.n} matches</div></div>${icon('next')}</div>`);
    out.push(grp('Days', days));
    // app pages
    const places = PLACES.filter((p) => hit(p.label)).slice(0, 4)
      .map((p) => `<div class="list-item tap gsr" data-gsgo='${esc(JSON.stringify(p.go))}'><span class="ko">${icon(p.icn)}</span><div class="main"><div class="match">${esc(p.label)}</div></div>${icon('next')}</div>`);
    out.push(grp('Go to', places));
    const body = out.filter(Boolean).join('');
    return body ? body : `<div class="gs-h">No match, team, league, bet or page matches “${esc(qs.trim())}”.</div>`;
  }
  function paintResults() {
    const box = $('#gq-res'); if (!box) return;
    box.innerHTML = searchResults(state.q);
    $$('#gq-res .gsr').forEach((el) => {
      el.onclick = () => {
        state.q = '';       // a fresh page starts with a clean bar
        if (el.dataset.gsf) openMatch(el.dataset.gsf);
        else if (el.dataset.gsteam) { const p = el.dataset.gsteam.split('|'); openTeam(p.slice(0, -2).join('|'), p[p.length - 2], p[p.length - 1]); }
        else if (el.dataset.gslg) { state.stack = []; setTab('leagues'); PR.openLeague(el.dataset.gslg); }
        else if (el.dataset.gsday) { state.stack = []; setTab('days'); state.dayView = 'results'; push({ type: 'day', date: el.dataset.gsday }); }
        else if (el.dataset.gsgo) { try { const g = JSON.parse(el.dataset.gsgo); if (g.tab) setTab(g.tab); else push({ type: g.page }); } catch (e) { /* ignore */ } }
      };
    });
  }
  function injectSearch() {
    const v = $('#view'); if (!v) return;
    const had = document.activeElement && document.activeElement.id === 'gq';
    const old = $('#gsearch-wrap'); if (old) old.remove();
    v.insertAdjacentHTML('afterbegin',
      `<div class="searchbar gs" id="gsearch-wrap"><div class="field">${icon('search', 'sm')}<input id="gq" type="search" placeholder="Search matches, teams, leagues, bets…" value="${esc(state.q || '')}" autocomplete="off">${(state.q || '') ? '<button class="gs-x" id="gq-x" aria-label="Clear">' + icon('x', 'sm') + '</button>' : ''}</div><div id="gq-res"></div></div>`);
    const inp = $('#gq');
    if (inp) {
      let t = null;
      inp.oninput = () => { state.q = inp.value; clearTimeout(t); t = setTimeout(paintResults, 140); };
      if (had) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
      const x = $('#gq-x'); if (x) x.onclick = () => { state.q = ''; inp.value = ''; paintResults(); inp.focus(); };
    }
    paintResults();
  }

  function trimModels(map, keep, limit) {
    const keys = Object.keys(map).filter((k) => map[k] && typeof map[k] === 'object');
    while (keys.length > limit) { const key = keys.shift(); if (key !== keep) delete map[key]; }
  }
  let repaintTimer;
  function quietRender() {
    clearTimeout(repaintTimer);
    repaintTimer = setTimeout(() => {
      if (document.hidden || !state.data) return;
      const scroll = window.scrollY, focused = document.activeElement, search = focused && focused.id === 'gq';
      const position = search ? focused.selectionStart : null;
      render(true); window.scrollTo(0, scroll);
      if (search && $('#gq')) { $('#gq').focus(); try { $('#gq').setSelectionRange(position, position); } catch (_) { /* search input */ } }
    }, 80);
  }
  if (resources) resources.subscribe((event) => {
    statusLine();
    if (event.type !== 'changed') return;
    const j = event.data, part = new URL(event.url).pathname.split('/data/app/')[1] || '';
    if (part === 'latest.json') {
      const old = pubStamp(); state.data = indexData(j); state.data._loadedAt = resources.status(DATA_URL).checkedAt;
      if (old && old !== pubStamp()) resources.invalidate(rawUrl('data/app/fx/'));
    } else if (part.startsWith('fx/')) {
      const k = part.slice(3, -5), row = fx(j.id);
      if (!row || row.home === j.home && row.away === j.away) state.details[k] = prepDetail(j);
    } else if (part.startsWith('days/')) { state.days[part.slice(5, -5)] = j; }
    else if (part === 'teams/teams-index.json') state.teamIdx = j;
    else if (part.startsWith('teams/')) state.teams[part.slice(6, -5)] = j;
    else if (part === 'badges.json') state.badges = j;
    else if (part.startsWith('leagues/') && state.lg) {
      const file = part.slice(8);
      if (file === 'index.json') { state.lg.idx = j; state.lg.idxStale = false; }
      else if (file === 'fixtures.json') { state.lg.fx = j; state.lg.fxStale = false; }
      else state.lg.det[file] = j;
    } else if (event.url.includes('/reports/')) state.reports[event.url.match(/(\d{4}-\d\d-\d\d)\.md/)[1] + '|report'] = j;
    else if (event.url.includes('/date/soccer/') && window.PR && PR.live.refresh) {
      PR.live.refresh(false).then(() => PR.live.refresh(false)); return;
    } else if (event.url.includes('prod-public-api.livescore.com')) {
      const extra = event.url.match(/\/(statistics|lineups|incidents)\/soccer\/(\d+)/);
      if (extra && state.lsx) state.lsx[extra[1] + ':' + extra[2]] = { t: resources.status(event.url).checkedAt, data: j };
    }
    trimModels(state.details, part.slice(3, -5), 32); trimModels(state.teams, part.slice(6, -5), 12); trimModels(state.days, part.slice(5, -5), 14); trimModels(state.reports, '', 8);
    const visible = resources.key(screenResource());
    const top = state.stack[state.stack.length - 1];
    const match = top && top.type === 'match' && fx(top.id);
    if (event.url === visible || part === 'latest.json' || part === 'badges.json' ||
        part === 'teams/teams-index.json' && state.q || match && event.url.includes('/soccer/' + match.livescore_id)) quietRender();
  });
  function refreshVisible(fromDisk) {
    if (!resources || document.hidden) return;
    if (fromDisk === true) { resources.pullShared(DATA_URL).then(() => refreshVisible()); return; }
    getJson(DATA_URL).catch(() => {});
    getJson(screenResource()).catch(() => {});
  }
  function connectionChanged() { if (resources) resources.reconnect(); refreshVisible(); statusLine(); }
  if (window.addEventListener) {
    window.addEventListener('online', connectionChanged);
    window.addEventListener('offline', statusLine);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) { refreshVisible(true); statusLine(); } });
    setInterval(refreshVisible, 60000);
  }
  async function clearDataCache() {
    if (resources) await resources.clear();
    try { localStorage.removeItem('pr_latest'); cache.clear(); } catch (_) { /* unavailable legacy store */ }
    if (native && native.setString) { try { native.setString('latest', ''); } catch (_) { /* unavailable legacy preference */ } }
    state.data = null; state.days = {}; state.teams = {}; state.details = {}; state.teamIdx = null; state.reports = {};
    if (state.lg) { state.lg.idx = null; state.lg.fx = null; state.lg.det = {}; state.lg.error = null; state.lg.fxError = null; }
    state.stack = []; await loadData(true);
  }

  return { native, settings, state, $, $$, saveSettings, nfetch, getJson, resources, migrateResource, validResource, refreshVisible, connectionChanged, clearDataCache, rawUrl, esc, pct, f1, f2, signed, DAYS, MONTHS, parseLocal, tzNow, ymd, stored, persist, cache, prefetchDetails, pubStamp,
    dayName, niceDate, koTime, koShort, toast, pill, bar, wdl, formBadges, md, GROUPS, GROUP_ICON, selGroup, isUnder, isDropped, SEL_FLOOR, selLabel, selShort, settleSel,
    liveVerdict, isLive, isFT, indexData, fx, loadDetail, detailCached, detailKey, loadData, saveLatest, saveAux, statusLine, isOutlier, loadDay, dayRecord, finalFor, storedIncidents, loadTeams, teamsCached, loadTeamIndex, realTable, slug, TABS, render, setTab, push, replace,
    sbEventUrl, sbShareUrl, openSportybet, openBookingCode, openExternal, copyText, namesAgree, displayName, fittedSbEvent,
    back, openMatch, openTeam, toggleMenu, closeMenu, contactCard, editorCard, teamLink, teamSpan, matchLine, matchRow, segmented, select, scoreBox, statusIcon, CONTACT, APP_VERSION,
    confirmBox, isFav, toggleFav, favList: () => favs, saveFavs,
    icon, flag, badge, fxBadge, skeleton, ring, applyTheme, loadBadges, BADGE_BASE, searchResults, injectSearch,
    views: {}, pages: {}, live: {} };
})();
