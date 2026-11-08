"""Worldwide coverage without an API key, built on Livescore.com's public app feed.

* fixture spine: every football match on the days inside the scan window (all countries, cups, women's, youth)
* results archive: one compact JSON per competition stage under data/ls/stages/, filled from the stage feed
  (whole current season) and topped up from the day feeds, so history accumulates across seasons
* results frame: the archive as a football-data-shaped DataFrame, appended to the model's history pool so the
  same team-form model, settlement, trends and team pages work for any league in the world

Teams are keyed by Livescore team id (stable) where the model needs a team's history; display uses the names.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import livescore

log = logging.getLogger("worldfeed")

BASE = livescore.BASE
STAGE_MAX_AGE_H = 6          # refresh a stage's season feed at most every 6 hours
BUDGET_S = 150               # stop refreshing stages after this many seconds (rest is picked up next run)
FINISHED = {"FT"}            # only regulation-time results feed the model (AET/pens scores are not 90-minute scores)
DIV_PREFIX = "LS:"


def stage_key(ccd: str, scd: str) -> str:
    return f"{ccd}/{scd}"


def div_code(ccd: str, scd: str) -> str:
    return f"{DIV_PREFIX}{ccd}/{scd}"


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _event(e: dict, st: dict) -> dict | None:
    try:
        t1, t2 = e["T1"][0], e["T2"][0]
        if t1.get("tbd") or t2.get("tbd") or not t1.get("Nm") or not t2.get("Nm"):
            return None
        ko = datetime.strptime(str(e["Esd"]), "%Y%m%d%H%M%S")
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    return {
        "eid": str(e.get("Eid")), "kickoff": ko, "status": str(e.get("Eps") or ""),
        "country": st.get("Cnm") or "", "league": st.get("Snm") or "", "ccd": st.get("Ccd") or "", "scd": st.get("Scd") or "",
        "home": t1["Nm"], "away": t2["Nm"], "home_id": str(t1.get("ID") or ""), "away_id": str(t2.get("ID") or ""),
        "home_img": t1.get("Img") or None, "away_img": t2.get("Img") or None,
        "home_co": t1.get("CoNm") or "", "away_co": t2.get("CoNm") or "",
        "hg": _int(e.get("Tr1")), "ag": _int(e.get("Tr2")), "hth": _int(e.get("Trh1")), "hta": _int(e.get("Trh2")),
    }


def fetch_day(day: datetime, tz_offset_hours: int = 2) -> list[dict]:
    """Every match on `day` with stage codes and team ids (kick-offs in the given UTC offset)."""
    d = livescore._get(f"{BASE}/date/soccer/{day:%Y%m%d}/{int(tz_offset_hours)}?MD=1")
    out = []
    for st in (d or {}).get("Stages", []):
        for e in st.get("Events", []):
            ev = _event(e, st)
            if ev:
                out.append(ev)
    return out


def fetch_stage(ccd: str, scd: str, tz_offset_hours: int = 2, quiet: bool = False) -> tuple[dict | None, list[dict]]:
    """Whole season of one competition stage (fixtures + results + league table meta)."""
    d = livescore._get(f"{BASE}/stage/soccer/{ccd}/{scd}/{int(tz_offset_hours)}?MD=1", quiet=quiet)
    for st in (d or {}).get("Stages", []):
        meta = {"country": st.get("Cnm") or "", "league": st.get("Snm") or "", "ccd": ccd, "scd": scd,
                "badge": st.get("badgeUrl") or None}
        events = [ev for ev in (_event(e, st) for e in st.get("Events", [])) if ev]
        return meta, events
    return None, []


# ----------------------------------------------------------------------------- archive
STAT_KEYS = ("hc", "ac", "hy", "ay", "hr", "ar", "hs", "as", "hst", "ast", "hposs", "aposs", "hf", "af")


def fetch_stats(eid: str) -> list | None:
    """Match statistics of a finished match: [hc, ac, hy, ay, hr, ar, hs, as, hst, ast, hposs, aposs, hf, af]
    or [] when Livescore has no statistics for it; None on a network error (retry later)."""
    try:
        r = requests.get(f"{BASE}/statistics/soccer/{eid}", headers={"User-Agent": livescore.UA, "Accept": "application/json"},
                         timeout=20)
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            return None
        data = r.json() if r.text.strip() else {}
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(data, dict):
        return []
    teams = {int(t.get("Tnb", 0)): t for t in (data.get("Stat") or []) if isinstance(t, dict)}
    h, a = teams.get(1), teams.get(2)
    if not h or not a:
        return []

    def g(t, k):
        v = t.get(k)
        return int(v) if isinstance(v, (int, float)) else None

    def shots(t):
        parts = [g(t, "Shon"), g(t, "Shof"), g(t, "Shbl")]
        return None if all(p is None for p in parts) else sum(p or 0 for p in parts)

    def cards(t, k):
        # a second yellow (YRcs) is both a yellow and a red, as in the football-data convention
        v, yr = g(t, k), g(t, "YRcs")
        return None if v is None else v + (yr or 0)

    return [g(h, "Cos"), g(a, "Cos"), cards(h, "Ycs"), cards(a, "Ycs"), cards(h, "Rcs"), cards(a, "Rcs"),
            shots(h), shots(a), g(h, "Shon"), g(a, "Shon"), g(h, "Pss"), g(a, "Pss"), g(h, "Fls"), g(a, "Fls"), g(h, "Shof"), g(a, "Shof")]


class Archive:
    """data/ls/stages/<ccd>__<scd>.json  +  data/ls/teams.json (id -> [name, img, country]).
    Each stage file: {key, country, league, fetched, events {eid: [esd, hid, home, aid, away, hg, ag, hth, hta]},
    stats {eid: [hc, ac, hy, ay, hr, ar, hs, as, hst, ast, hposs, aposs, hf, af] | []}}."""

    def __init__(self, root: Path):
        self.root = root
        self.stages_dir = root / "stages"
        self.stages_dir.mkdir(parents=True, exist_ok=True)
        self.teams_file = root / "teams.json"
        try:
            self.teams = json.loads(self.teams_file.read_text(encoding="utf-8")) if self.teams_file.exists() else {}
        except (OSError, ValueError):
            self.teams = {}
        self._cache: dict[str, dict] = {}
        self._dirty: set[str] = set()

    # -- files
    def _path(self, key: str) -> Path:
        return self.stages_dir / (re.sub(r"[^A-Za-z0-9_.-]+", "_", key.replace("/", "__")) + ".json")

    def load(self, key: str) -> dict:
        if key in self._cache:
            return self._cache[key]
        p = self._path(key)
        data = None
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
        if not data:
            data = {"key": key, "country": "", "league": "", "fetched": None, "events": {}}
        self._cache[key] = data
        return data

    def merge(self, key: str, meta: dict | None, events: list[dict], fetched: datetime | None = None) -> int:
        """Add finished events (regulation time) to a stage file; returns the number of new/changed results."""
        data = self.load(key)
        if meta:
            data["country"] = meta.get("country") or data["country"]
            data["league"] = meta.get("league") or data["league"]
        if fetched is not None:
            data["fetched"] = fetched.strftime("%Y-%m-%d %H:%M")
        changed = 0
        for ev in events:
            if ev["status"] not in FINISHED or ev["hg"] is None or ev["ag"] is None:
                continue
            rec = [ev["kickoff"].strftime("%Y%m%d%H%M"), ev["home_id"], ev["home"], ev["away_id"], ev["away"],
                   ev["hg"], ev["ag"], ev["hth"], ev["hta"]]
            if data["events"].get(ev["eid"]) != rec:
                data["events"][ev["eid"]] = rec
                changed += 1
            for side in ("home", "away"):
                tid = ev[f"{side}_id"]
                if tid:
                    cur = self.teams.get(tid)
                    new = [ev[side], ev[f"{side}_img"], ev[f"{side}_co"]]
                    if cur != new:
                        self.teams[tid] = new
        if changed or fetched is not None or meta:
            self._dirty.add(key)
        return changed

    def save(self) -> int:
        n = 0
        for key in self._dirty:
            data = self._cache[key]
            self._path(key).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            n += 1
        self._dirty.clear()
        self.teams_file.write_text(json.dumps(self.teams, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return n

    # -- refresh policy
    def refresh(self, wanted: dict[str, int], now: datetime, tz_offset_hours: int = 2,
                max_age_h: float = STAGE_MAX_AGE_H, budget_s: float = BUDGET_S) -> dict:
        """Fetch the season feed of the stages in `wanted` {key: priority} that are missing or stale."""
        t0 = time.time()
        order = sorted(wanted.items(), key=lambda kv: -kv[1])
        done = skipped = failed = 0
        for key, _prio in order:
            data = self.load(key)
            fetched = data.get("fetched")
            if fetched:
                try:
                    age = (now.replace(tzinfo=None) - datetime.strptime(fetched, "%Y-%m-%d %H:%M")).total_seconds() / 3600
                except ValueError:
                    age = 1e9
                if age < max_age_h:
                    continue
            if time.time() - t0 > budget_s:
                skipped += 1
                continue
            ccd, scd = key.split("/", 1)
            meta, events = fetch_stage(ccd, scd, tz_offset_hours)
            if meta is None:
                failed += 1
                # remember the attempt so a dead stage is not retried every run
                self.merge(key, None, [], fetched=now)
                continue
            self.merge(key, meta, events, fetched=now)
            done += 1
        log.info("Livescore stages: %d refreshed, %d skipped (budget), %d failed, %d wanted, %.0fs",
                 done, skipped, failed, len(wanted), time.time() - t0)
        return {"refreshed": done, "skipped": skipped, "failed": failed}

    def absorb_days(self, events: list[dict], now: datetime) -> int:
        """Merge finished matches of the day feeds (results appear here before the stage feed refresh)."""
        by_stage: dict[str, list[dict]] = {}
        for ev in events:
            if ev["status"] in FINISHED and ev["ccd"] and ev["scd"]:
                by_stage.setdefault(stage_key(ev["ccd"], ev["scd"]), []).append(ev)
        n = 0
        for key, evs in by_stage.items():
            n += self.merge(key, {"country": evs[0]["country"], "league": evs[0]["league"]}, evs)
        return n

    # -- previous seasons (Livescore serves them under "<stage>-YYYY-YYYY" / "<stage>-YYYY")
    def backfill(self, wanted: dict[str, int], now: datetime, tz_offset_hours: int = 2, seasons: int = 2,
                 budget_s: float = 45.0, max_requests: int = 60) -> dict:
        """Add up to `seasons` earlier seasons of every wanted stage (tried once per season variant, remembered in the
        stage file), so head-to-head, form and league history are complete outside football-data's leagues."""
        t0 = time.time()
        y = now.year if now.month >= 7 else now.year - 1
        variants = []
        for k in range(1, seasons + 1):
            variants.append((f"{y - k}-{y - k + 1}", f"-{y - k}-{y - k + 1}"))     # European seasons
            variants.append((f"{y - k + 1}", f"-{y - k + 1}"))                     # calendar-year seasons
        order = sorted(wanted.items(), key=lambda kv: -kv[1])
        req = added = 0
        for key, _prio in order:
            if req >= max_requests or time.time() - t0 > budget_s:
                break
            data = self.load(key)
            done = data.setdefault("backfill", {})
            ok_seasons = sum(1 for v in done.values() if isinstance(v, int) and v > 0)
            if ok_seasons >= seasons or len(done) >= len(variants):
                continue
            ccd, scd = key.split("/", 1)
            base = re.sub(r"-\d{4}(-\d{4})?$", "", scd)      # "primera-c-2026" -> "primera-c"
            for label, suffix in variants:
                if label in done or ok_seasons >= seasons or req >= max_requests:
                    continue
                if base + suffix == scd:                         # that is the current season itself
                    done[label] = 0
                    continue
                req += 1
                meta, events = fetch_stage(ccd, base + suffix, tz_offset_hours, quiet=True)
                if meta is None or not events:
                    done[label] = -1
                    continue
                n = self.merge(key, None, events)
                done[label] = len(events)
                ok_seasons += 1
                added += n
                self._dirty.add(key)
            self._dirty.add(key)
        log.info("Livescore backfill: %d request(s), %d earlier-season result(s) added, %.0fs", req, added, time.time() - t0)
        return {"requests": req, "added": added}

    # -- match statistics (corners, cards, shots, possession)
    def refresh_stats(self, wanted: dict[str, int], now: datetime, budget_s: float = 60.0, max_n: int = 400,
                      recent_days: int = 3) -> dict:
        """Fetch statistics for finished matches without them: the last `recent_days` of every wanted stage first,
        then the older backlog of the highest-priority stages, within a time / request budget."""
        t0 = time.time()
        recent_cut = int((now - timedelta(days=recent_days)).strftime("%Y%m%d%H%M"))
        old_cut = int((now - timedelta(days=400)).strftime("%Y%m%d%H%M"))
        order = sorted(wanted.items(), key=lambda kv: -kv[1])
        todo_recent, todo_old = [], []
        for key, _prio in order:
            data = self.load(key)
            stats = data.setdefault("stats", {})
            probe = data.setdefault("stats_probe", {"tried": 0, "hit": 0})
            # competitions where Livescore publishes no statistics: after 8 empty answers only probe one recent
            # match per run (to notice if they start appearing) and skip the older backlog entirely
            dead = probe["tried"] >= 8 and probe["hit"] == 0
            n_recent_stage = 0
            for eid, rec in sorted((data.get("events") or {}).items(), key=lambda kv: kv[1][0], reverse=True):
                if eid in stats:
                    continue
                try:
                    esd = int(rec[0])
                except (TypeError, ValueError, IndexError):
                    continue
                if esd >= recent_cut:
                    if dead and n_recent_stage >= 1:
                        continue
                    n_recent_stage += 1
                    todo_recent.append((key, eid, esd))
                elif not dead and esd >= old_cut:
                    todo_old.append((key, eid, esd))
        todo_old.sort(key=lambda x: -x[2])
        done = empty = failed = 0
        for key, eid, _esd in todo_recent + todo_old:
            if done + empty + failed >= max_n or time.time() - t0 > budget_s:
                break
            st = fetch_stats(eid)
            if st is None:
                failed += 1
                continue
            data = self._cache[key]
            data["stats"][eid] = st
            data["stats_probe"]["tried"] += 1
            self._dirty.add(key)
            if st:
                data["stats_probe"]["hit"] += 1
                done += 1
            else:
                empty += 1
        log.info("Livescore statistics: %d fetched, %d without stats, %d failed, %d still missing, %.0fs",
                 done, empty, failed, len(todo_recent) + len(todo_old) - done - empty - failed, time.time() - t0)
        return {"fetched": done, "empty": empty, "failed": failed}

    def load_all(self) -> None:
        for p in self.stages_dir.glob("*.json"):
            key = p.stem.replace("__", "/")
            if key not in self._cache:
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                self._cache[data.get("key") or key] = data

    def stats_for(self, eid: str) -> list | None:
        for data in self._cache.values():
            st = (data.get("stats") or {}).get(eid)
            if st:
                return st
        return None

    def event_for(self, eid: str) -> dict | None:
        """{hg, ag, hth, hta, kickoff} of an archived (finished) match."""
        for data in self._cache.values():
            rec = (data.get("events") or {}).get(eid)
            if rec:
                esd, _hid, _home, _aid, _away, hg, ag, hth, hta = rec
                return {"hg": hg, "ag": ag, "hth": hth, "hta": hta, "kickoff": esd}
        return None

    # -- model input
    def results_frame(self, since: datetime) -> pd.DataFrame:
        rows = []
        cutoff = int(since.strftime("%Y%m%d%H%M"))
        for p in self.stages_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            key = data.get("key") or p.stem.replace("__", "/")
            ccd, _, scd = key.partition("/")
            div = div_code(ccd, scd)
            stats = data.get("stats") or {}
            for eid, rec in (data.get("events") or {}).items():
                try:
                    esd, hid, home, aid, away, hg, ag, hth, hta = rec
                except (TypeError, ValueError):
                    continue
                if int(esd) < cutoff:
                    continue
                st = stats.get(eid) or []
                st = (st + [None] * 16)[:16] if st else [None] * 16
                rows.append((data.get("country") or "", div, data.get("league") or "", esd[:8], home, away, hid, aid,
                             hg, ag, hth, hta, eid, *st,
                             f"Livescore:{key}", f"{esd[8:10]}:{esd[10:12]}" if len(esd) >= 12 else None))
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["country", "div", "league", "d", "home", "away", "home_id", "away_id",
                                         "hg", "ag", "hth", "hta", "eid",
                                         "hc", "ac", "hy", "ay", "hr", "ar", "hs", "as", "hst", "ast", "hposs", "aposs", "hf", "af", "hsoff", "asoff",
                                         "_source_ref", "_history_kickoff"])
        df["date"] = pd.to_datetime(df["d"], format="%Y%m%d")
        df = df.drop(columns=["d"])
        for c in ("hg", "ag"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        for c in ("hth", "hta"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        for c in ("hxg", "axg"):
            df[c] = np.nan
        for c in ("hc", "ac", "hy", "ay", "hr", "ar", "hs", "as", "hst", "ast", "hposs", "aposs", "hf", "af", "hsoff", "asoff"):
            df[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
        df["referee"] = ""
        return df

    def badge_map(self) -> dict[str, str]:
        return {v[0]: v[1] for v in self.teams.values() if v and v[0] and v[1]}


# ----------------------------------------------------------------------------- spine
def window_days(start: datetime, end: datetime) -> list[datetime]:
    days = []
    d = start.date()
    while d <= end.date():
        days.append(datetime(d.year, d.month, d.day))
        d += timedelta(days=1)
    return days


def fetch_window(start: datetime, end: datetime, tz_offset_hours: int = 2, back_days: int = 1) -> list[dict]:
    """Day feeds covering [start - back_days, end] (yesterday is included so late finals reach the archive)."""
    events: dict[str, dict] = {}
    for day in window_days(start - timedelta(days=back_days), end):
        try:
            for ev in fetch_day(day, tz_offset_hours):
                events[ev["eid"]] = ev
        except Exception as exc:  # noqa: BLE001
            log.warning("Livescore day %s failed: %s", day.date(), exc)
    return list(events.values())


def upcoming(events: list[dict], start: datetime, end: datetime) -> list[dict]:
    s, e = start.replace(tzinfo=None), end.replace(tzinfo=None)
    return [ev for ev in events if ev["status"] == "NS" and s <= ev["kickoff"] <= e]


def fixtures_frame(events: list[dict], tz) -> pd.DataFrame:
    """Livescore events as scanner fixtures (same columns as load_fixtures, source='world', no feed odds)."""
    rows = []
    for ev in events:
        ko = ev["kickoff"].replace(tzinfo=tz)
        rows.append({
            "source": "world", "code": "LS", "country": ev["country"], "div": div_code(ev["ccd"], ev["scd"]),
            "league": ev["league"], "date": pd.Timestamp(ko.date()), "time": ko.strftime("%H:%M"),
            "home": ev["home"], "away": ev["away"], "home_id": ev["home_id"], "away_id": ev["away_id"],
            "odds_over": np.nan, "odds_under": np.nan, "b365_over": np.nan, "b365_under": np.nan,
            "odds_h": np.nan, "odds_d": np.nan, "odds_a": np.nan, "bfe_h": np.nan, "bfe_d": np.nan, "bfe_a": np.nan,
            "bfe_over": np.nan, "bfe_under": np.nan, "max_over": np.nan, "max_under": np.nan, "referee": "",
            "kickoff": ko, "time_known": True, "eid": ev["eid"],
        })
    return pd.DataFrame(rows)


def ls_entry(ev: dict) -> dict:
    """Shape used by history.Days / appdata (same keys as livescore.fetch_day events)."""
    return {"eid": ev["eid"], "country": ev["country"], "league": ev["league"], "home": ev["home"], "away": ev["away"],
            "kickoff": ev["kickoff"], "status": ev["status"], "hg": ev["hg"], "ag": ev["ag"], "ht": (ev["hth"], ev["hta"]),
            "home_img": ev["home_img"], "away_img": ev["away_img"], "ccd": ev["ccd"]}


def stage_priorities(fixtures: pd.DataFrame) -> dict[str, int]:
    """Stages with matches in the window, most matches first."""
    out: dict[str, int] = {}
    if fixtures is None or fixtures.empty:
        return out
    for div in fixtures["div"]:
        if str(div).startswith(DIV_PREFIX):
            key = str(div)[len(DIV_PREFIX):]
            out[key] = out.get(key, 0) + 1
    return out


def known_stages(stages_dir: Path) -> set[str]:
    """Stage keys of every archived stage file (the archive is never pruned, so this is all-time)."""
    keys: set[str] = set()
    for p in Path(stages_dir).glob("*.json"):
        keys.add(p.stem.replace("__", "/", 1))
    return keys
