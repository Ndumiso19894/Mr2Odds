/* Durable cache-first repository. No UI/framework or prediction logic. */
(function (root) {
  'use strict';
  function create(options) {
    const memory = new Map(), reading = new Map(), flights = new Map(), failures = new Map(), listeners = new Set();
    const now = options.now || Date.now;
    const policies = Object.assign({ latest: 5 * 60000, fixtures: 10 * 60000, detail: 15 * 60000,
      teams: 6 * 3600000, standings: 30 * 60000, history: 24 * 3600000, images: 7 * 86400000, live: 30000 }, options.policies);
    let active = 0, generation = 0, offline = false;
    const queue = [], used = new Set(), invalidated = new Map();
    const online = () => !options.online || options.online();
    const emit = (event) => listeners.forEach((fn) => { try { fn(event); } catch (_) { /* isolate views */ } });
    function key(url) {
      const u = new URL(url);
      // Only the legacy cache-buster is discarded. TZ/MD/provider query parameters retain their identity.
      u.searchParams.delete('t'); u.hash = ''; return u.href;
    }
    function ttl(url) {
      if (url.includes('prod-public-api.livescore.com')) return policies.live;
      if (/\/latest\.json$/.test(url)) return policies.latest;
      if (/\/days\/\d{4}-\d\d-\d\d\.json$/.test(url)) {
        const date = url.match(/\d{4}-\d\d-\d\d/)[0];
        return now() - Date.parse(date + 'T00:00:00Z') > 3 * 86400000 ? policies.history : policies.latest;
      }
      if (/\/reports\//.test(url)) {
        const date = url.match(/\d{4}-\d\d-\d\d/);
        return date && now() - Date.parse(date[0] + 'T00:00:00Z') > 3 * 86400000 ? policies.history : policies.latest;
      }
      if (/\/teams\/|\/badges\.json$/.test(url)) return /badges/.test(url) ? policies.images : policies.teams;
      if (/\/leagues\//.test(url)) return /fixtures\.json$/.test(url) ? policies.fixtures : policies.standings;
      return policies.detail;
    }
    function schedule(fn) {
      return new Promise((resolve, reject) => { queue.push({ fn, resolve, reject }); pump(); });
    }
    function pump() {
      while (active < 2 && queue.length) {
        const task = queue.shift(); active++;
        Promise.resolve().then(task.fn).then(task.resolve, task.reject).finally(() => { active--; pump(); });
      }
    }
    function trim(keep) {
      let size = Array.from(memory.values()).reduce((n, e) => n + e.body.length, 0);
      for (const [url, entry] of memory) {
        if (memory.size <= 40 && size <= 8 * 1024 * 1024) break;
        if (url === keep || /\/latest\.json$/.test(url)) continue;
        memory.delete(url); size -= entry.body.length;
      }
    }
    async function persist(url, entry, changed) {
      const epoch = generation;
      const disk = Object.assign({}, entry); delete disk.data; delete disk.persisted;
      try {
        if (changed || !entry.persisted) await options.store.put(url, disk);
        else await options.store.touch(url, entry.checkedAt, entry);
        entry.persisted = true;
      } catch (_) {
        if (epoch !== generation) return;
        try { await options.store.put(url, disk); entry.persisted = true; } catch (_) { entry.persisted = false; }
      }
    }
    function decode(entry, url, validate) {
      if (!entry || !entry.body) return null;
      try {
        const data = entry.data || JSON.parse(entry.body);
        if (!options.validate(url, data) || (validate && !validate(data))) return null;
        if (!Number.isFinite(entry.checkedAt) || entry.checkedAt > now() + 60000) entry.checkedAt = 0;
        entry.data = data; return entry;
      } catch (_) { return null; }
    }
    async function read(url, validate) {
      const epoch = generation;
      let entry = decode(memory.get(url), url, validate);
      if (entry) return entry;
      if (!reading.has(url)) reading.set(url, Promise.resolve().then(() => options.store.get(url)).catch(() => null).finally(() => reading.delete(url)));
      const raw = await reading.get(url);
      if (raw && raw.retryAt > now()) failures.set(url, { until: raw.retryAt, code: raw.errorCode, count: raw.failureCount || 1 });
      entry = decode(raw, url, validate);
      if (entry && epoch === generation) {
        entry.persisted = true; memory.set(url, entry);
        // Parsed memory is bounded separately from the durable database.
        trim(url);
      }
      return epoch === generation ? entry : null;
    }
    function stale(url, e) { return !e || now() - e.checkedAt >= ttl(url) || Array.from(invalidated).some(([prefix, time]) => url.startsWith(prefix) && e.checkedAt < time); }
    function status(url) {
      const k = key(url), e = memory.get(k), f = failures.get(k);
      return { cached: !!e, offline: !online() || offline, stale: stale(k, e), persisted: !!(e && e.persisted),
        checkedAt: e ? e.checkedAt : 0, updatedAt: e ? e.updatedAt : 0,
        retryAt: f ? f.until : 0, error: f ? f.code : null };
    }
    async function sync(url, validate) {
      if (flights.has(url)) return flights.get(url);
      const blocked = failures.get(url);
      if (!online() || (blocked && blocked.until > now())) return null;
      const epoch = generation;
      const promise = schedule(async () => {
        if (epoch !== generation || !online()) return null;
        const previous = await read(url, validate);
        let r;
        // At most two attempts per cycle; only idempotent reads, never retry a malformed response/404/rate limit.
        for (let attempt = 0; attempt < 2; attempt++) {
          if (Array.from(failures).some(([key, f]) => (f.code === 403 || f.code === 429) && f.until > now() && new URL(key).origin === new URL(url).origin)) return null;
          r = await options.fetch(url, { etag: previous && previous.etag, modified: previous && previous.modified });
          if (!(r.code === 0 || r.code >= 500) || attempt === 1 || !online()) break;
          await (options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms))))(1000);
        }
        if (epoch !== generation) return null; // Clear-cache must not be undone by an older request.
        if (r.code === 304 && previous) {
          previous.checkedAt = now(); previous.etag = r.etag || previous.etag; previous.modified = r.modified || previous.modified; failures.delete(url); offline = false;
          if (options.store.failure) options.store.failure(url, null).catch(() => {});
          // Metadata only: don't rewrite/parse the payload on 304.
          await persist(url, previous, false);
          if (epoch !== generation) return null;
          emit({ type: 'status', url }); return previous.data;
        }
        if (r.code !== 200) throw Object.assign(new Error('HTTP ' + r.code), { code: r.code, retryAfter: r.retryAfter });
        if (previous && previous.body === r.body) {
          previous.checkedAt = now(); previous.etag = r.etag || previous.etag; previous.modified = r.modified || previous.modified;
          failures.delete(url); offline = false;
          if (options.store.failure) options.store.failure(url, null).catch(() => {});
          await persist(url, previous, false);
          if (epoch !== generation) return null;
          emit({ type: 'status', url }); return previous.data;
        }
        let data;
        try { data = JSON.parse(r.body); } catch (_) { throw Object.assign(new Error('Invalid JSON'), { code: 'invalid' }); }
        if (!options.validate(url, data) || (validate && !validate(data))) throw Object.assign(new Error('Invalid data'), { code: 'invalid' });
        if (previous) {
          const stamp = (d) => Date.parse((d.meta && d.meta.generated) || d.generated || d.updated || '');
          if (stamp(data) < stamp(previous.data)) throw Object.assign(new Error('Older publication'), { code: 'invalid' });
          if (url.includes('/teams/') && previous.data.teams && data.teams &&
              Object.keys(previous.data.teams).length && !Object.keys(data.teams).length)
            throw Object.assign(new Error('Empty team replacement'), { code: 'invalid' });
          for (const field of ['fixtures', 'leagues', 'teams']) {
            if (!/\/leagues\/(?!index\.json|fixtures\.json)/.test(url) && Array.isArray(previous.data[field]) && previous.data[field].length && Array.isArray(data[field]) && !data[field].length)
              throw Object.assign(new Error('Empty replacement'), { code: 'invalid' });
          }
        }
        const changed = !previous || previous.body !== r.body;
        const entry = { body: r.body, data: changed ? data : previous.data, etag: r.etag || '', modified: r.modified || '',
          checkedAt: now(), updatedAt: changed ? now() : previous.updatedAt };
        memory.set(url, entry); failures.delete(url); offline = false;
        trim(url);
        await persist(url, entry, changed);
        if (epoch !== generation) return null;
        if (options.store.failure) await options.store.failure(url, null).catch(() => {});
        emit({ type: changed ? 'changed' : 'status', url, data: entry.data });
        return entry.data;
      }).catch(async (error) => {
        if (epoch !== generation) return null;
        const old = failures.get(url), count = Math.min((old ? old.count : 0) + 1, 6);
        let wait = Math.min(15 * 60000, 30000 * Math.pow(2, count - 1));
        if (error.code === 429 || error.code === 403) wait = Math.max(wait, 15 * 60000);
        if (error.retryAfter) wait = Math.max(wait, Math.min(24 * 3600000, error.retryAfter));
        failures.set(url, { count, until: now() + wait, code: error.code || 0 });
        if (options.store.failure) await options.store.failure(url, failures.get(url)).catch(() => {});
        if (!error.code) offline = true;
        emit({ type: 'status', url });
        throw error;
      }).finally(() => { if (flights.get(url) === promise) flights.delete(url); });
      flights.set(url, promise); return promise;
    }
    async function get(url, opts) {
      opts = opts || {}; url = key(url); used.delete(url); used.add(url); if (used.size > 100) used.delete(used.values().next().value);
      const entry = await read(url, opts.validate);
      if (entry) {
        if (opts.force || stale(url, entry)) sync(url, opts.validate).catch(() => {});
        return entry.data;
      }
      const value = await sync(url, opts.validate);
      if (value && (!opts.validate || opts.validate(value))) return value;
      throw new Error(online() ? 'Waiting before retry' : 'Offline — no saved copy');
    }
    function reconnect() {
      offline = false;
      // A connectivity transition releases only network-error cooldowns, not server rate limits.
      failures.forEach((f, k) => { if (!f.code) failures.delete(k); });
      emit({ type: 'status' });
      Array.from(used).slice(-12).forEach((url) => { if (status(url).stale) sync(url).catch(() => {}); });
    }
    async function pullShared(url) {
      url = key(url);
      let disk; try { disk = await options.store.get(url); } catch (_) { return; }
      const previous = memory.get(url);
      if (disk && disk.retryAt > now()) failures.set(url, { until: disk.retryAt, code: disk.errorCode, count: disk.failureCount || 1 });
      else if (disk && previous && disk.checkedAt > previous.checkedAt) failures.delete(url);
      if (previous && disk && disk.body === previous.body) {
        previous.checkedAt = Math.max(previous.checkedAt, disk.checkedAt || 0);
        previous.etag = disk.etag || previous.etag; previous.modified = disk.modified || previous.modified;
        emit({ type: 'status', url }); return;
      }
      const entry = decode(disk, url);
      if (entry) { entry.persisted = true; memory.set(url, entry); trim(url); emit({ type: 'changed', url, data: entry.data }); }
    }
    async function seed(url, data, checkedAt) {
      const epoch = generation;
      url = key(url);
      if (await read(url) || !options.validate(url, data) || epoch !== generation) return;
      const entry = { body: JSON.stringify(data), data, etag: '', modified: '', checkedAt: checkedAt || 1, updatedAt: checkedAt || 1 };
      const disk = Object.assign({}, entry); delete disk.data;
      memory.set(url, entry); trim(url);
      try { await options.store.put(url, disk); entry.persisted = true; } catch (_) { /* legacy copy stays, usable from RAM */ }
    }
    async function clear() { generation++; memory.clear(); reading.clear(); flights.clear(); failures.clear(); used.clear(); invalidated.clear(); await options.store.clear(); emit({ type: 'status' }); }
    return { get, status, reconnect, clear, seed, pullShared, invalidate(prefix) { invalidated.set(prefix, now()); }, ttl, key, policies, subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); } };
  }
  // Browser harness fallback. Android uses SQLite through the asynchronous native bridge instead.
  function browserStore() {
    let database;
    function open() {
      if (!database) database = new Promise((resolve, reject) => {
        const request = indexedDB.open('pr-resources-v1', 1);
        request.onupgradeneeded = () => request.result.createObjectStore('resources');
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      });
      return database;
    }
    async function transaction(mode, fn) {
      const db = await open();
      return new Promise((resolve, reject) => {
        const tx = db.transaction('resources', mode), store = tx.objectStore('resources'); let value;
        const req = fn(store); if (req) req.onsuccess = () => { value = req.result; };
        tx.oncomplete = () => resolve(value); tx.onerror = tx.onabort = () => reject(tx.error);
      });
    }
    return { get: (key) => transaction('readonly', (s) => s.get(key)),
      put: (key, entry) => transaction('readwrite', (s) => s.put(entry, key)),
      touch: (key, checkedAt, metadata) => transaction('readwrite', (s) => {
        const r = s.get(key); r.onsuccess = () => { if (r.result) { r.result.checkedAt = checkedAt; if (metadata) { r.result.etag = metadata.etag; r.result.modified = metadata.modified; } s.put(r.result, key); } };
        return null;
      }), clear: () => transaction('readwrite', (s) => s.clear()) };
  }
  const exported = { create, browserStore };
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  else root.PRResourceCache = exported;
})(typeof window !== 'undefined' ? window : globalThis);
