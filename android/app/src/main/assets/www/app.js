/* Mr 2 Odds — boot: header menu, update banner, native callbacks, timers. */
(function (PR) {
  'use strict';
  const { $, $$, state, settings, esc, toast } = PR;

  // header buttons + menu
  $$('#tabs button').forEach((b) => { b.onclick = () => PR.setTab(b.dataset.tab); });
  $('#btn-refresh').onclick = () => { PR.loadData(true); if (state.tab === 'live' || state.tab === 'home') PR.live.refresh(true); };
  $('#btn-menu').onclick = (e) => { e.stopPropagation(); PR.toggleMenu(); };
  $('#btn-search').onclick = (e) => { e.stopPropagation(); PR.closeMenu(); state.focusSearch = true; state.stack = []; if (state.tab === 'matches') PR.render(); else PR.setTab('matches'); const i = $('#fx-search'); if (i) { i.focus(); i.scrollIntoView({ block: 'start', behavior: 'smooth' }); } };
  $$('#menu [data-page]').forEach((b) => { b.onclick = () => { PR.closeMenu(); const t = b.dataset.page; state.stack = []; PR.push({ type: t }); }; });
  $('#menu [data-csv]').onclick = () => { PR.closeMenu(); PR.downloadDayCsv(); };
  $('#menu [data-contact]').onclick = () => { PR.closeMenu(); if (PR.native && PR.native.openUrl) PR.native.openUrl(`https://wa.me/${PR.CONTACT.whatsapp}`); else window.open(`https://wa.me/${PR.CONTACT.whatsapp}`); };
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { if (state.tab === 'live' || state.tab === 'home') PR.live.refresh(false); updateCheck(); } });

  // updates — instant check (launch, foreground, worker); no banner/popup: the Android notification
  // reports a new version and tapping it starts the install immediately.
  const UPDATE_MIN_GAP = 120000; let lastUpdateCheck = 0;
  function updateCheck() {
    if (!PR.native || !PR.native.checkUpdate) return;
    const now = Date.now(); if (now - lastUpdateCheck < UPDATE_MIN_GAP) return;
    lastUpdateCheck = now;
    try { PR.native.checkUpdate(); } catch (e) { /* ignore */ }
  }
  PR.startUpdate = function () {
    if (!state.update || !PR.native || !PR.native.installUpdate) return;
    state.updateStage = 'downloading'; toast('Opening the download…');
    PR.native.installUpdate(state.update.url);
  };
  /** release notes (markdown-ish) -> list items */
  PR.notesList = function (notes) {
    return String(notes || '').replace(/PlayReport(?: ZA)?/g, 'Mr 2 Odds').split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !/^#/.test(l) && !/^Mr 2 Odds for Android/.test(l) && !/^Download Mr 2 Odds/.test(l))
      .map((l) => l.replace(/^[-*•]\s*/, '')).slice(0, 10);
  };
  window.__updateInfo = function (info) {
    state.update = info || null; state.updateStage = null;
    if (state.updateChecked === 'manual') {
      state.updateChecked = null;
      if (info) { toast(`Version ${info.version} available — starting download…`); PR.startUpdate(); }
      else toast('You have the latest version');
    }
    // automatic checks stay silent — the native notification is the single update surface
    const top = state.stack[state.stack.length - 1]; if (top && top.type === 'settings') PR.render();
  };
  /** The download finished and Android is asking to install it — the app never installs by itself. */
  window.__updateInstalling = function () { toast('Verified — Android will ask you to install it'); };
  /** CSV "save as" result from the native picker */
  window.__saveDone = function (ok) { toast(ok ? 'Saved — open it with Google Sheets or Excel' : 'Not saved'); };
  window.__updateProgress = function (stage) { state.updateStage = stage; if (stage === 'failed') toast('Could not open the download — try again'); else if (stage === 'browser') toast('Downloading — when it finishes, tap the file and choose Install'); };

  // native entry points
  window.app = {
    refresh() { PR.loadData(true).then(() => { if (state.tab === 'live' || state.tab === 'home') PR.live.refresh(true); }); },
    back: () => PR.back(),
    // "safest" is the signals destination (Scan → High prob.) — used by signal notifications
    setTab: (t) => { if (t === 'safest') { state.betsView = 'safest'; PR.setTab('bets'); } else PR.setTab(t); },
    /** A match notification was tapped: key is "match|<fixture id or livescore id>" — open that match directly. */
    openNotifMatch(key) {
      const k = String(key || '').replace(/^match\|/, '');
      if (!k) return;
      let tries = 0, dayTried = false;
      const hit = (list) => (list || []).find((x) => x && (x.id === k || (x.livescore_id != null && String(x.livescore_id) === k)));
      const open = (f) => { PR.openMatch(f.id); PR.render(); };
      const tick = () => {
        const d = PR.state.data;
        const f = d && ((d._byId && d._byId[k]) || hit(d.fixtures));
        if (f) { open(f); return; }
        if (/^\d{4}-\d{2}-\d{2}/.test(k)) {           // fixture id of a future/past day -> its day file
          if (!dayTried) {
            dayTried = true;
            // the tap can arrive while the phone is still connecting: give the day file a few tries
            const dayFile = (left) => PR.loadDay(k.slice(0, 10)).then((rec) => {
              const g = hit(rec && rec.fixtures);
              if (g) open(g);
              else if (left > 1) setTimeout(() => dayFile(left - 1), 1200);
              else toast('Stats for this match are not available yet.');
            }).catch(() => { if (left > 1) setTimeout(() => dayFile(left - 1), 1200); else toast('Stats for this match are not available yet.'); });
            dayFile(3);
          }
          return;
        }
        if (d && !dayTried && tries >= 4) {              // livescore id: yesterday's games live in the day files
          dayTried = true;
          const y = PR.ymd(new Date(PR.tzNow().getTime() - 86400000));
          Promise.all([PR.loadDay(PR.ymd(PR.tzNow())).catch(() => null), PR.loadDay(y).catch(() => null)])
            .then((recs) => {
              const g = recs.map((r) => r && hit(r.fixtures)).find(Boolean);
              g ? open(g) : toast('Stats for this match are not available yet.');
            });
          return;
        }
        if (tries++ < 60) setTimeout(tick, 500);
        else toast('Stats for this match are not available yet.');
      };
      tick();
    },
    /** A tennis notification was tapped: key is "tennis|<livescore id>" — switch to the tennis section
     *  and open that exact match (the match page loads its own detail file, newest first). */
    openNotifTennis(key) {
      const k = String(key || '').replace(/^tennis\|/, '');
      if (!k) return;
      const go = () => PR.push({ type: 'tennisMatch', id: k });
      if (PR.tennis && PR.tennis.setSport && settings.sport !== 'tennis') {
        PR.tennis.setSport('tennis');
        setTimeout(go, 80);                       // let the sport switch finish before stacking the page
      } else go();
    },
    onResume() { PR.refreshVisible(true); if (state.data && Date.now() - (state.data._loadedAt || 0) > 5 * 60000) PR.loadData(false); if (state.tab === 'live' || state.tab === 'home') PR.live.refresh(false); updateCheck(); const top = state.stack[state.stack.length - 1]; if (top && top.type === 'settings') PR.render(); },
    onPermission(granted) { toast(granted ? 'Notifications on — new bets, analysis, goals and updates' : 'Notifications are off — you can enable them in Settings'); const top = state.stack[state.stack.length - 1]; if (top && top.type === 'settings') PR.render(); },
    state, settings, PR,
  };

  // boot: cached first, then network
  const cached = PR.stored ? PR.stored('pr_latest') : localStorage.getItem('pr_latest');
  if (cached) { try { const saved = JSON.parse(cached); if (!PR.validResource(PR.rawUrl('data/app/latest.json'), saved)) throw new Error('Invalid saved copy'); state.data = PR.indexData(saved); PR.statusLine(); PR.render(); } catch (e) { /* ignore */ } }
  PR.loadBadges().then(() => { if (state.data) PR.render(); });
  PR.loadData(false).then(() => { if (state.data) { PR.live.refresh(false); setTimeout(() => PR.prefetchDetails(), 1500); } });
  PR.live.schedule();
  if (PR.native && PR.native.setPref) { try { PR.native.setPref('goals', !!settings.goalAlerts); PR.native.setPref('ht', !!settings.htAlerts); PR.native.setPref('ft', settings.ftAlerts !== false); PR.native.setPref('ko', settings.koAlerts !== false); if (PR.saveFavs) PR.saveFavs(); PR.native.setPref('bets', settings.betAlerts !== false); PR.native.setPref('reports', settings.reportAlerts !== false); PR.native.setPref('tennis', false); } catch (e) { /* ignore */ } }
  if (PR.reconcileTickets) setTimeout(() => PR.reconcileTickets(), 2500);
  updateCheck(); // instant — no startup delay
})(window.PR);
