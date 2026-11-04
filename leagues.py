"""Worldwide league browser data for the app's Leagues tab.

Builds two artifacts from the Livescore stage archive (data/ls/stages/*.json, maintained by
worldfeed.py) plus a short upcoming-fixture window:

* data/app/leagues/index.json          - one compact entry per competition stage (all countries, cups,
                                         women's, youth — every stage the public feed publishes)
* data/app/leagues/<stage-slug>.json   - on-demand detail: league table (where the format allows it),
                                         the 40 most recent results, and the next fixtures

This module is strictly additive: it reads the archive and writes new app-data files. It never feeds
the model — the stage archive stays the model's world history, and nothing in here changes a probability.

Data-first rules honoured:
* a table is only published for league-format stages (teams that play several opponents); knockout
  rounds and two-legged ties show results/fixtures only — a bracket is not a table;
* half-time scores are N/A where the feed has none; postponed/cancelled matches simply never appear
  as results (they only surface as fixtures until they are played);
* "fetched" is stamped on every file so the app can show how fresh the data is.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import competition_policy

from teamstats import CALENDAR_YEAR   # season-boundary convention (presentation only — never model input)

log = logging.getLogger("leagues")

RESULTS_KEEP = 40       # most recent finished matches published per stage
FIXTURES_KEEP = 12      # upcoming fixtures published per stage
FIXTURE_HOURS = 48      # look-ahead for the fixtures list when no coverage window is passed (standalone runs)
FIXTURE_WINDOW_DAYS = 60  # how far ahead the Leagues tab's fixture lists reach (coverage window)
_MIN_TEAMS = 4          # a table needs at least this many teams
TREND_MIN_N = 5         # a trend window needs at least this many matches, otherwise N/A (never 0)


def slug(key: str) -> str:
    """Stage key 'country/league' -> filename (same convention as worldfeed.Archive._path)."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", key.replace("/", "__")) + ".json"


def _evt(eid, rec) -> dict | None:
    """One archived event [esd, home_id, home, away_id, away, hg, ag, (hth, hta)] -> dict, or None."""
    if not isinstance(rec, (list, tuple)) or len(rec) < 7:
        return None
    esd, _hid, home, _aid, away, hg, ag = rec[:7]
    hth = rec[7] if len(rec) > 7 else None
    hta = rec[8] if len(rec) > 8 else None
    try:
        ko = datetime.strptime(str(esd), "%Y%m%d%H%M%S")
    except ValueError:
        try:
            ko = datetime.strptime(str(esd), "%Y%m%d%H%M")
        except ValueError:
            return None
    if not home or not away:
        return None
    finished = hg is not None and ag is not None
    return {"eid": str(eid), "ko": ko, "home": str(home), "away": str(away), "hg": hg, "ag": ag,
            "hth": hth, "hta": hta, "finished": finished}


def _ko(rec) -> str:
    return rec["ko"].strftime("%Y-%m-%d %H:%M")


def compute_table(evts: list[dict]) -> list[dict]:
    """Standings from finished events: P W D L GF GA GD Pts + last-5 form (oldest first) + home/away splits."""
    split = lambda: {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0}  # noqa: E731
    teams: dict[str, dict] = {}
    for e in sorted(evts, key=lambda x: x["ko"]):
        for side, other in (("home", "away"), ("away", "home")):
            t = teams.setdefault(e[side], {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "res": [],
                                           "h": split(), "a": split()})
            sc, op = (e["hg"], e["ag"]) if side == "home" else (e["ag"], e["hg"])
            t["p"] += 1
            t["gf"] += sc
            t["ga"] += op
            r = "W" if sc > op else ("D" if sc == op else "L")
            t[r.lower()] += 1
            t["res"].append(r)
            s = t["h"] if side == "home" else t["a"]
            s["p"] += 1
            s["gf"] += sc
            s["ga"] += op
            s[r.lower()] += 1
    rows = []
    for name, t in teams.items():
        h, a = t["h"], t["a"]
        rows.append({"team": name, "p": t["p"], "w": t["w"], "d": t["d"], "l": t["l"],
                     "gf": t["gf"], "ga": t["ga"], "gd": t["gf"] - t["ga"],
                     "pts": 3 * t["w"] + t["d"], "form": "".join(t["res"][-5:][::-1]),
                     "h": {"p": h["p"], "w": h["w"], "d": h["d"], "l": h["l"], "gf": h["gf"], "ga": h["ga"],
                           "pts": 3 * h["w"] + h["d"]},
                     "a": {"p": a["p"], "w": a["w"], "d": a["d"], "l": a["l"], "gf": a["gf"], "ga": a["ga"],
                           "pts": 3 * a["w"] + a["d"]}})
    rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["team"].lower()))
    for i, r in enumerate(rows, 1):
        r["pos"] = i
    return rows


def _rate(n: int, d: int):
    return round(n / d, 3) if d else None


def _window_trend(evts: list[dict], stats: dict) -> dict | None:
    """Aggregate trend for one list of finished events (newest first). None when too few matches:
    a trend is only computed from real data — insufficient windows stay N/A, never zero."""
    n = len(evts)
    if n < TREND_MIN_N:
        return None
    tot = [e["hg"] + e["ag"] for e in evts]
    home_g = [e["hg"] for e in evts]
    away_g = [e["ag"] for e in evts]
    # corners / cards: only over the matches that actually carry match statistics (N/A otherwise)
    corner_n = card_n = 0
    corners = cards = 0
    for e in evts:
        st = stats.get(e["eid"])
        if st and len(st) >= 6:
            if st[0] is not None and st[1] is not None:
                corners += st[0] + st[1]; corner_n += 1
            if None not in (st[2], st[3], st[4], st[5]):
                cards += st[2] + st[4] + st[3] + st[5]; card_n += 1
    return {
        "n": n,
        "avg_goals": round(sum(tot) / n, 2),
        "o05": _rate(sum(1 for t in tot if t >= 1), n),
        "o15": _rate(sum(1 for t in tot if t >= 2), n),
        "o25": _rate(sum(1 for t in tot if t >= 3), n),
        "o35": _rate(sum(1 for t in tot if t >= 4), n),
        "btts": _rate(sum(1 for e in evts if e["hg"] > 0 and e["ag"] > 0), n),
        "home_win": _rate(sum(1 for e in evts if e["hg"] > e["ag"]), n),
        "draw": _rate(sum(1 for e in evts if e["hg"] == e["ag"]), n),
        "away_win": _rate(sum(1 for e in evts if e["ag"] > e["hg"]), n),
        "home_goals": round(sum(home_g) / n, 2),
        "away_goals": round(sum(away_g) / n, 2),
        "home_clean_sheet": _rate(sum(1 for e in evts if e["ag"] == 0), n),
        "away_clean_sheet": _rate(sum(1 for e in evts if e["hg"] == 0), n),
        "home_failed_to_score": _rate(sum(1 for e in evts if e["hg"] == 0), n),
        "away_failed_to_score": _rate(sum(1 for e in evts if e["ag"] == 0), n),
        "avg_corners": round(corners / corner_n, 2) if corner_n else None,
        "corners_n": corner_n,
        "avg_cards": round(cards / card_n, 2) if card_n else None,
        "cards_n": card_n,
    }


def league_trends(finished: list[dict], season_start, stats: dict) -> dict:
    """Per-league trend block: last 5/10/20, current season, previous season, plus the
    descriptive last-10-vs-season change. All windows are data-driven; None = N/A."""
    season = [e for e in finished if e["ko"] >= season_start]
    previous = [e for e in finished if e["ko"] < season_start]
    out = {
        "last5": _window_trend(finished[:5], stats),
        "last10": _window_trend(finished[:10], stats),
        "last20": _window_trend(finished[:20], stats),
        "season": _window_trend(season, stats),
        "previous_season": _window_trend(previous, stats),
        "season_from": season_start.strftime("%Y-%m-%d") if season_start else None,
    }
    # change detection: last 10 vs season average (descriptive only — never a recommendation)
    a, b = out["last10"], out["season"]
    if a and b:
        out["change_last10_vs_season"] = {
            "avg_goals": round(a["avg_goals"] - b["avg_goals"], 2),
            "o25": round(a["o25"] - b["o25"], 3) if (a["o25"] is not None and b["o25"] is not None) else None,
            "btts": round(a["btts"] - b["btts"], 3) if (a["btts"] is not None and b["btts"] is not None) else None,
        }
    return out


def league_like(evts: list[dict]) -> bool:
    """True when the stage looks like a league/group format: enough teams, and most of them have
    played several different opponents. Knockout rounds (1 opponent per team) fail this test."""
    opp: dict[str, set[str]] = defaultdict(set)
    for e in evts:
        if e["finished"]:
            opp[e["home"]].add(e["away"])
            opp[e["away"]].add(e["home"])
    if len(opp) < _MIN_TEAMS:
        return False
    return sum(1 for o in opp.values() if len(o) >= 3) / len(opp) >= 0.5


def _season(backfill: dict | None) -> str | None:
    """The season label of the stage: the season with the most archived matches (the main season)."""
    if not backfill:
        return None
    best = None
    for season, n in backfill.items():
        if not isinstance(n, int) or n <= 0:
            continue  # -1 sentinel = fetch failed for that season
        if best is None or (n, str(season)) > (best[1], str(best[0])):
            best = (season, n)
    return best[0] if best else None


def _stage_data(path: Path) -> dict | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not d.get("key"):
        return None
    return d


def _upcoming(now: datetime, tz_hours: int = 2) -> list[dict]:
    """Not-started matches of the next FIXTURE_HOURS from the public day feed (best effort)."""
    import worldfeed  # local import: keeps this module importable without the feed's deps

    out: dict[str, dict] = {}
    for off in range(12, FIXTURE_HOURS, 24):
        day = now + timedelta(hours=off)
        try:
            for e in worldfeed.fetch_day(day, tz_hours):
                if e["status"] == "NS" and e["eid"] not in out and competition_policy.allowed(
                        e.get("country"), e.get("league"), home=e.get("home"), away=e.get("away"),
                        key=f"{e.get('ccd', '')}/{e.get('scd', '')}"):
                    out[e["eid"]] = e
        except Exception as exc:  # noqa: BLE001
            log.warning("leagues: fixture day %s failed: %s", day.date(), exc)
    return list(out.values())


def _window_events(events: list[dict] | None, now: datetime, days: int = 60) -> dict[str, list[dict]]:
    """Group pre-fetched coverage-window events by stage (not-started, within the next `days`).

    The scanner passes the day-feed events it already fetched for the model — the Leagues tab's
    fixture lists then span the whole coverage window with zero extra requests.
    """
    out: dict[str, list[dict]] = defaultdict(list)
    if not events:
        return out
    lo, hi = now - timedelta(minutes=5), now + timedelta(days=days)
    for e in events:
        if not competition_policy.allowed(e.get("country"), e.get("league"), home=e.get("home"), away=e.get("away"),
                                          key=f"{e.get('ccd', '')}/{e.get('scd', '')}"):
            continue
        if e.get("status") != "NS" or not (lo <= e["kickoff"] <= hi):
            continue
        if e.get("ccd") and e.get("scd"):
            out[f"{e['ccd']}/{e['scd']}"].append(e)
    return out


def build(stages_dir: Path, now: datetime, out_dir: Path, tz_hours: int = 2, events: list[dict] | None = None) -> int:
    """Publish index.json + one detail file per stage. Returns the number of league files written.

    `events` = the scanner's coverage-window day-feed events (naive SAST kick-offs); when given, the
    fixture lists span the whole coverage window (60 days) with no extra network. Falls back to a
    short day-feed look-ahead when called standalone.
    """
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)   # feed kick-offs are naive display-time (SAST), like worldfeed.upcoming
    stages_dir = Path(stages_dir)
    if not list(stages_dir.glob("*.json")) and list((stages_dir / "stages").glob("*.json")):
        stages_dir = stages_dir / "stages"  # tolerate being handed the data/ls dir
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    up_by_stage = _window_events(events, now, days=FIXTURE_WINDOW_DAYS) if events else defaultdict(list)
    if not events:
        for e in _upcoming(now, tz_hours):
            up_by_stage[f"{e['ccd']}/{e['scd']}"].append(e)

    # per-stage status from the coverage registry (coverage.build runs first in the scanner)
    status_by_key: dict[str, dict] = {}
    status_file = out_dir / "status.json"
    if status_file.exists():
        try:
            for e in json.loads(status_file.read_text(encoding="utf-8")).get("competitions", []):
                if e.get("provider") == "livescore":
                    status_by_key[e["provider_id"]] = e
        except (OSError, ValueError):
            pass

    index: list[dict] = []
    slugs: set[str] = set()
    n = 0
    for path in sorted(stages_dir.glob("*.json")):
        d = _stage_data(path)
        if not d or not competition_policy.allows_record(d):
            continue
        evts = [ev for ev in (_evt(eid, v) for eid, v in (d.get("events") or {}).items()) if ev]
        if not evts:
            continue
        finished = sorted((e for e in evts if e["finished"]), key=lambda e: e["ko"], reverse=True)
        teams = {e["home"] for e in evts} | {e["away"] for e in evts}
        key = d["key"]
        up = sorted((e for e in up_by_stage.get(key, []) if e["kickoff"] >= now - timedelta(minutes=5)),
                    key=lambda e: e["kickoff"])
        # season boundary (existing convention, shared with the team pages)
        season_start = None
        if finished:
            latest = finished[0]["ko"]
            if (d.get("country") or "") in CALENDAR_YEAR:
                season_start = datetime(latest.year, 1, 1)
            else:
                y = latest.year if latest.month >= 7 else latest.year - 1
                season_start = datetime(y, 7, 1)
        # standings are the CURRENT season's table (backfilled earlier seasons stay in the
        # results/trends, never mixed into the table)
        season_events = [e for e in finished if season_start is None or e["ko"] >= season_start]
        table = compute_table(season_events) if (season_events and league_like(evts) and len(teams) >= _MIN_TEAMS) else []
        st = status_by_key.get(key)
        entry = {"slug": path.name, "country": d.get("country") or "", "league": d.get("league") or "",
                 "teams": len(teams), "played": len(finished),
                 "season": (st or {}).get("season") or _season(d.get("backfill")),
                 "table": bool(table), "next": up[0]["kickoff"].strftime("%Y-%m-%d %H:%M") if up else None,
                 "fetched": d.get("fetched") or None}
        if st:
            entry["status"] = st["status"]
            entry["eligible"] = st["eligible"]
            sq = st.get("stats_quality") or {}
            entry["stats"] = {"n": sq.get("with_stats"), "total": sq.get("recent_window"),
                              "pct": sq.get("pct"), "publishes": sq.get("provider_publishes", True)}
            entry["hist"] = st.get("historical_matches")
            entry["earlier"] = dict(list((st.get("seasons") or {}).items())[:2])
        index.append(entry)
        detail = {"key": key, "country": entry["country"], "league": entry["league"], "season": entry["season"],
                  "fetched": entry["fetched"], "teams": entry["teams"], "played": entry["played"],
                  "teams_div": f"LS:{key}",  # the model pool's division for this stage = the team pages' key
                  "generated": now.strftime("%Y-%m-%d %H:%M"),
                  "status": (st or {}).get("status"), "eligible": (st or {}).get("eligible"),
                  "status_reason": (st or {}).get("reason"),
                  "stats": entry.get("stats"), "hist": entry.get("hist"), "earlier": entry.get("earlier"),
                  "trends": league_trends(finished, season_start, d.get("stats") or {}) if finished else None,
                  "table": table,
                  "results": [{"ko": _ko(e), "home": e["home"], "away": e["away"], "hg": e["hg"], "ag": e["ag"],
                               "hth": e["hth"], "hta": e["hta"]} for e in finished[:RESULTS_KEEP]],
                  "fixtures": [{"ko": e["kickoff"].strftime("%Y-%m-%d %H:%M"), "home": e["home"], "away": e["away"]}
                                for e in up[:FIXTURES_KEEP]]}
        (out_dir / path.name).write_text(json.dumps(detail, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        slugs.add(path.name)
        n += 1

    index.sort(key=lambda x: (x["country"].lower(), x["league"].lower()))
    summary = {
        "active": sum(1 for e in index if e.get("status") == "ACTIVE"),
        "upcoming": sum(1 for e in index if e.get("status") == "UPCOMING"),
        "finished": sum(1 for e in index if e.get("status") == "FINISHED"),
        "data_error": sum(1 for e in index if e.get("status") == "DATA_ERROR"),
        "eligible": sum(1 for e in index if e.get("eligible") is True),
        "collecting": sum(1 for e in index if (e.get("stats") or {}).get("publishes")
                          and (e.get("stats") or {}).get("pct") is not None and e["stats"]["pct"] < 0.99),
        "no_stats": sum(1 for e in index if (e.get("stats") or {}).get("publishes") is False),
    }
    (out_dir / "index.json").write_text(json.dumps(
        {"generated": now.strftime("%Y-%m-%d %H:%M"), "count": len(index), "summary": summary, "leagues": index},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # drop detail files of stages that no longer exist (renamed competitions) —
    # the coverage registry (status.json / STATUS.md) lives in this directory too
    for old in out_dir.glob("*.json"):
        if old.name not in ("index.json", "status.json") and old.name not in slugs:
            try:
                old.unlink()
            except OSError:
                pass
    log.info("leagues: %d stages published (index + detail)", n)
    return n


def add_news(out_dir: Path, league_fn, team_fn) -> int:
    """Patch the published league details with a News section (context only — never a model input).

    league_fn(league_name, country) -> [headlines]; team_fn(team_name) -> [headlines].
    Both are backed by the scanner's TTL cache, so repeated runs within the TTL cost no network.
    Only competitions with an upcoming fixture are served fresh news; the rest keep their last
    cached section. Returns the number of detail files patched."""
    out_dir = Path(out_dir)
    idx = out_dir / "index.json"
    if not idx.exists():
        return 0
    try:
        rows = json.loads(idx.read_text(encoding="utf-8")).get("leagues") or []
    except (OSError, ValueError):
        return 0
    n = 0
    for row in sorted((r for r in rows if r.get("next")), key=lambda r: r["next"]):
        p = out_dir / row["slug"]
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        top = [t["team"] for t in (d.get("table") or [])[:2]] or \
            list({e["home"] for e in (d.get("results") or [])[:5]} | {e["away"] for e in (d.get("results") or [])[:5]})[:3]
        try:
            d["news"] = {
                "league": league_fn(d.get("league") or row.get("league") or "", d.get("country") or row.get("country") or "") or [],
                "teams": {t: (team_fn(t) or []) for t in top},
            }
            p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            n += 1
        except Exception as exc:  # noqa: BLE001 — one bad league must not kill the rest
            log.warning("league news failed for %s: %s", row.get("slug"), exc)
    return n


if __name__ == "__main__":  # manual run: python3 leagues.py <state_dir>
    import sys
    state = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    build(state / "data" / "ls" / "stages", datetime.now(), state / "data" / "app" / "leagues")
