"""Competition coverage registry — the scanner's world map.

Read-only, no network: reads the Livescore stage archive (data/ls/stages/*.json) plus the
model's football-data league lists and writes, next to the league browser:

* data/app/leagues/status.json  — machine-readable registry, one entry per competition:
  Country | Competition | Provider ID | Season | Fixtures | Historical data | Stats quality |
  Eligible | Status | Reason
* data/app/leagues/STATUS.md    — the same registry as a readable dashboard

Statuses: ACTIVE · UPCOMING · FINISHED · DATA_ERROR. "Eligible" means the model has a
moderate-or-better sample (>= 5 archived matches) for most teams of the competition, using the
same sample tiers quality._score_sample already uses (5 -> 0.55, 10 -> 0.8, 20 -> 1.0). Nothing
here feeds the model; it is a report on what the scanner is doing.

Usage:
    python3 coverage.py <state_dir>   # manual run (reads <state>/data/ls/stages, writes <state>/data/app/leagues)
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import competition_policy

log = logging.getLogger("coverage")

MIN_TEAM_MATCHES = 5     # quality._score_sample tier boundary: >=5 matches -> 0.55 (moderate)
RECENT_FOR_STATS = 30    # how many most-recent finished matches the stats-quality sample uses
STALE_DAYS = 7           # a stage not refreshed for this long is noted (feed gap), still listed


def _events(d: dict) -> list[tuple[str, dict]]:
    """[(eid, event)] for every parseable archived event, newest first."""
    out = []
    for eid, rec in (d.get("events") or {}).items():
        if not isinstance(rec, (list, tuple)) or len(rec) < 6:
            continue
        esd, _hid, home, _aid, away, hg, ag, _hth, _hta = (list(rec) + [None] * 9)[:9]
        try:
            ko = datetime.strptime(str(esd), "%Y%m%d%H%M%S")
        except (TypeError, ValueError):
            try:
                ko = datetime.strptime(str(esd), "%Y%m%d%H%M")
            except (TypeError, ValueError):
                continue
        if not home or not away:
            continue
        out.append((str(eid), {"ko": ko, "home": str(home), "away": str(away), "hg": hg, "ag": ag}))
    out.sort(key=lambda x: x[1]["ko"], reverse=True)
    return out


def _current_season_label(finished: list[dict]) -> str | None:
    """Season label from the most recent result (July–June convention), e.g. 2026-09 -> '2026-27'."""
    if not finished:
        return None
    d = finished[0]["ko"]
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}-{str(y + 1)[-2:]}"


def assess_stage(d: dict, now: datetime, n_fix: int, next_fixture: str | None) -> dict:
    """One registry entry for one archived stage (a dict loaded from the stage JSON file)."""
    key = d.get("key") or ""
    evts = _events(d)
    finished = [e for _eid, e in evts if e["hg"] is not None and e["ag"] is not None]
    teams = Counter()
    for e in finished:
        teams[e["home"]] += 1
        teams[e["away"]] += 1
    # events hold every archived match (current season + any backfilled earlier seasons),
    # so the archive size is simply the finished count; `earlier` is the backfill breakdown.
    season = _current_season_label(finished)
    earlier = {k: v for k, v in (d.get("backfill") or {}).items() if isinstance(v, int) and v > 0}
    total_hist = len(finished)

    # stats quality: share of the most recent finished matches that carry match statistics.
    # stats_probe distinguishes "the provider publishes no statistics for this competition"
    # (8+ empty answers) from "collection still in progress" (time/request budgets per run).
    stats = {eid for eid, st in (d.get("stats") or {}).items() if st}
    probe = d.get("stats_probe") or {}
    provider_dead = bool(probe) and probe.get("tried", 0) >= 8 and probe.get("hit", 0) == 0
    n_recent = min(RECENT_FOR_STATS, len(finished))
    n_with = sum(1 for eid, e in evts[:RECENT_FOR_STATS]
                 if e["hg"] is not None and e["ag"] is not None and eid in stats)
    stats_pct = (n_with / n_recent) if n_recent else None

    fetch_failures = [k for k, v in (d.get("backfill") or {}).items() if v == -1]
    fetched = d.get("fetched") or ""
    stale = False
    try:
        stale = bool(fetched) and (now - datetime.strptime(fetched, "%Y-%m-%d %H:%M")) > timedelta(days=STALE_DAYS)
    except ValueError:
        stale = False

    # ---- status
    if not finished:
        if n_fix:
            status, reason = "UPCOMING", "fixtures published, no finished matches in the archive yet"
        elif fetch_failures:
            status = "DATA_ERROR"
            reason = "no matches archived and season fetch(es) failed: " + ", ".join(sorted(fetch_failures))
        else:
            status, reason = "UPCOMING", "no finished matches in the archive yet"
    elif not n_fix and finished[0]["ko"] < now - timedelta(days=45):
        status, reason = "FINISHED", f"last result {finished[0]['ko']:%Y-%m-%d}, nothing scheduled"
    else:
        status = "ACTIVE"
        bits = []
        if n_fix:
            bits.append(f"{n_fix} fixture(s) in the scan window")
        if stale:
            bits.append(f"not refreshed since {fetched} (feed gap)")
        reason = "; ".join(bits) or f"latest result {finished[0]['ko']:%Y-%m-%d}"

    # ---- eligibility (existing model sample tiers, applied to the teams of this competition)
    if teams:
        ok = sum(1 for n in teams.values() if n >= MIN_TEAM_MATCHES)
        eligible = ok / len(teams) >= 0.5
        why = (f"{ok}/{len(teams)} teams have >= {MIN_TEAM_MATCHES} archived matches — "
               + ("model samples moderate or better" if eligible else "model samples are thin; predictions carry small-sample labels"))
    else:
        eligible, why = False, "no finished matches to build team samples from"
    if status == "UPCOMING":
        eligible, why = False, "season not started — becomes eligible as results are archived"
    elif status == "DATA_ERROR":
        eligible = False

    return {
        "country": d.get("country") or "", "competition": d.get("league") or "",
        "provider": "livescore", "provider_id": key,
        "season": season, "fixtures": n_fix, "next_fixture": next_fixture,
        "historical_matches": total_hist, "seasons": earlier,
        "stats_quality": {"recent_window": n_recent, "with_stats": n_with,
                          "pct": round(stats_pct, 3) if stats_pct is not None else None,
                          "provider_publishes": False if provider_dead else True},
        "teams": len(teams), "eligible": eligible, "status": status,
        "reason": why if (not teams and status != "DATA_ERROR") or status == "UPCOMING" else reason,
        "fetched": fetched or None,
    }


def football_data_rows() -> list[dict]:
    """The football-data.co.uk side of the registry (hard-coded model feeds, stable IDs)."""
    import scanner  # local import: keeps this module importable standalone
    rows = []
    for code, (country, name) in sorted(scanner.MAIN_LEAGUES.items(), key=lambda kv: (kv[1][0], kv[1][1])):
        rows.append({"country": country, "competition": name, "provider": "football-data", "provider_id": code,
                     "season": "current", "fixtures": None, "next_fixture": None,
                     "historical_matches": None, "seasons": {},
                     "stats_quality": {"recent_window": None, "with_stats": None, "pct": 1.0},
                     "teams": None, "eligible": True, "status": "ACTIVE",
                     "reason": "primary feed — full history, odds, xG, shots, corners and cards"})
    for country in sorted(scanner.EXTRA_LEAGUES):
        code = scanner.EXTRA_LEAGUES[country]
        rows.append({"country": country, "competition": f"{country} (football-data file)", "provider": "football-data",
                     "provider_id": code, "season": "current", "fixtures": None, "next_fixture": None,
                     "historical_matches": None, "seasons": {},
                     "stats_quality": {"recent_window": None, "with_stats": None, "pct": None},
                     "teams": None, "eligible": True, "status": "ACTIVE",
                     "reason": "football-data new-league file — goals and odds; xG/shots where published"})
    return rows


def build(stages_dir: Path, out_dir: Path, now: datetime,
          window: dict[str, int] | None = None, nexts: dict[str, str] | None = None) -> dict:
    """Write status.json + STATUS.md. `window` maps stage key -> in-window fixture count;
    `nexts` maps stage key -> next kickoff 'YYYY-MM-DD HH:MM'. Returns the summary dict."""
    stages_dir = Path(stages_dir)
    if not list(stages_dir.glob("*.json")) and list((stages_dir / "stages").glob("*.json")):
        stages_dir = stages_dir / "stages"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    window = window or {}
    nexts = nexts or {}

    entries = []
    for path in sorted(stages_dir.glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or not d.get("key") or not competition_policy.allows_record(d):
            continue
        key = d["key"]
        entries.append(assess_stage(d, now, int(window.get(key, 0)), nexts.get(key)))

    entries += football_data_rows()
    entries.sort(key=lambda x: (x["country"].lower(), x["competition"].lower()))

    statuses = Counter(e["status"] for e in entries)
    summary = {
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "counts": {
            "competitions": len(entries),
            "countries": len({e["country"] for e in entries if e["country"]}),
            "eligible": sum(1 for e in entries if e["eligible"]),
            "active": statuses["ACTIVE"], "upcoming": statuses["UPCOMING"],
            "finished": statuses["FINISHED"], "data_error": statuses["DATA_ERROR"],
            "livescore_stages": sum(1 for e in entries if e["provider"] == "livescore"),
            "football_data": sum(1 for e in entries if e["provider"] == "football-data"),
        },
        "competitions": entries,
    }
    (out_dir / "status.json").write_text(json.dumps(summary, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # human-readable dashboard
    lines = ["# League coverage status", "",
             f"_Generated {now:%Y-%m-%d %H:%M}. Read-only dashboard: what the scanner has, per competition. "
             "**Eligible** = the model has >= 5 archived matches for at least half of the competition's teams "
             "(the model's own 'moderate' sample tier); the model keeps predicting on thinner samples too, "
             "with the evidence size shown on every selection. Nothing here feeds the model._", "",
             f"**{summary['counts']['competitions']} competitions · {summary['counts']['countries']} countries · "
             f"{summary['counts']['eligible']} eligible · {statuses['ACTIVE']} active · "
             f"{statuses['UPCOMING']} upcoming · {statuses['FINISHED']} finished · {statuses['DATA_ERROR']} data errors**", "",
             "| Country | Competition | Provider ID | Season | Fixtures | Historical data | Stats quality | Eligible | Status | Reason |",
             "|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|"]
    for e in entries:
        hist = (f"{e['historical_matches']} archived matches" if e["historical_matches"] is not None else "full seasons")
        if e.get("seasons"):
            s = ", ".join(f"{k} ({v})" for k, v in sorted(e["seasons"].items())[:3])
            hist += f" · earlier: {s}"
        sq = e["stats_quality"]
        if e["provider"] == "football-data":
            sq_txt = "100% (feed)"
        elif not sq.get("provider_publishes", True):
            sq_txt = "provider publishes none"
        elif sq["pct"] is None:
            sq_txt = "no recent window yet"
        elif sq["pct"] >= 0.99:
            sq_txt = f"{int(round(100 * sq['pct']))}% of last {sq['recent_window']}"
        else:
            sq_txt = f"{int(round(100 * sq['pct']))}% of last {sq['recent_window']} (collecting)"
        lines.append(f"| {e['country']} | {e['competition']} | `{e['provider_id']}` | {e['season'] or '–'} | "
                     f"{e['fixtures'] if e['fixtures'] is not None else '–'} | {hist} | {sq_txt} | "
                     f"{'yes' if e['eligible'] else 'no'} | {e['status']} | {e['reason']} |")
    (out_dir / "STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("coverage registry: %d competitions (%d countries, %d eligible)",
             summary["counts"]["competitions"], summary["counts"]["countries"], summary["counts"]["eligible"])
    return summary


if __name__ == "__main__":  # manual run: python3 coverage.py <state_dir>
    import sys
    state = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    build(state / "data" / "ls" / "stages", datetime.now(), state / "data" / "app" / "leagues")
