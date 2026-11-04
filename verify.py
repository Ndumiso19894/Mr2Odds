"""Data checks before a publication is promoted to the app (and before the ledgers are trusted).

`check_publication()` inspects the staged export (latest.json, meta.json, alerts.json, per-match files) and the
ledger, and returns (errors, warnings). Any error blocks the promotion: the app keeps the previous publication and
the run reports the problem on Telegram / in the log instead of publishing something broken.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path

import safe
import competition_policy
import recommendation_policy as rec_policy

MAX_LATEST_MB = 4.0
STATUSES = {"pending", "hit", "miss", "void"}


def _archive_ids(staging: Path) -> set:
    """Fixture ids present in the day archive (the 60-day history files).

    High-probability selections and shortlist picks can legitimately point at matches outside the
    published app window (they are analysed early, up to 60 days ahead); the app renders them from
    the bet objects themselves and the Days tab carries their detail.
    """
    out = set()
    days_dir = staging.parent / "days"
    if days_dir.is_dir():
        for p in days_dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for f in d.get("fixtures") or []:
                if f.get("id"):
                    out.add(f["id"])
    return out


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


def _prob(x) -> bool:
    return _num(x) and -1e-9 <= x <= 1 + 1e-9


def check_publication(staging: Path, live: Path, ledger: Path, now: datetime, expect_fixtures: int) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    latest_p = staging / "latest.json"
    if not latest_p.exists():
        return ["latest.json missing"], warns
    if latest_p.stat().st_size > MAX_LATEST_MB * 1e6:
        errors.append(f"latest.json too large ({latest_p.stat().st_size / 1e6:.1f} MB)")
    try:
        d = json.loads(latest_p.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"latest.json is not valid JSON: {exc}"], warns
    if d.get("version") != 3:
        errors.append(f"unexpected format version {d.get('version')}")
    meta = d.get("meta") or {}
    if meta.get("generated") != now.strftime("%Y-%m-%d %H:%M"):
        errors.append(f"meta.generated {meta.get('generated')!r} != run time")
    fixtures = d.get("fixtures") or []
    if expect_fixtures and not fixtures:
        errors.append("no fixtures in the publication although the scan had rows")
    ids = set()
    n_detail_missing = 0
    for f in fixtures:
        fid = f.get("id")
        if not fid or fid in ids:
            errors.append(f"duplicate or empty fixture id {fid!r}")
            continue
        ids.add(fid)
        if not competition_policy.allows_record(f):
            errors.append(f"paused competition in published fixture {fid}")
        try:
            datetime.strptime(f.get("kickoff", ""), "%Y-%m-%d %H:%M")
        except ValueError:
            errors.append(f"bad kickoff {f.get('kickoff')!r} for {fid}")
        p = f.get("p") or {}
        for k in ("O15", "O25", "BTTS"):
            if p.get(k) is not None and not _prob(p[k]):
                errors.append(f"probability {k}={p[k]!r} out of range for {fid}")
        if _prob(p.get("O15")) and _prob(p.get("O25")) and p["O25"] > p["O15"] + 1e-6:
            errors.append(f"P(O2.5) > P(O1.5) for {fid}")
        x12 = f.get("x12") or []
        if len(x12) == 3 and all(_num(v) for v in x12) and abs(sum(x12) - 1) > 0.05:
            warns.append(f"1X2 probabilities sum to {sum(x12):.2f} for {fid}")
        xg = f.get("xg") or []
        if len(xg) == 2 and all(_num(v) for v in xg) and (min(xg) < 0 or max(xg) > 6):
            warns.append(f"odd expected goals {xg} for {fid}")
        # Home collections consume these rows directly; a valid detail file alone cannot fill them.
        if not f.get("frozen"):
            selections = f.get("sels")
            if not isinstance(selections, list):
                errors.append(f"fixture {fid} missing index selections")
            else:
                seen_sels = set()
                for selection in selections:
                    if not isinstance(selection, list) or len(selection) < 6 or not isinstance(selection[0], str):
                        errors.append(f"malformed index selection for {fid}")
                        continue
                    if selection[0] in seen_sels or not _prob(selection[1]) or not _prob(selection[2]):
                        errors.append(f"duplicate or invalid index selection {selection[0]} for {fid}")
                    seen_sels.add(selection[0])
        key = f.get("d")
        if key and not (staging / "fx" / f"{key}.json").exists() and not (live / "fx" / f"{key}.json").exists():
            n_detail_missing += 1
        for side in ("home", "away"):
            if not f.get(side):
                errors.append(f"missing {side} team for {fid}")
    if n_detail_missing:
        (errors if n_detail_missing > 3 else warns).append(f"{n_detail_missing} fixture(s) without a detail file")
    # ---- data-first engine: the detail files must carry the evidence layer and no market-contaminated probability
    n_checked = n_noq = n_blend = 0
    for f in fixtures:
        key = f.get("d")
        fp = staging / "fx" / f"{key}.json"
        if not key or not fp.exists() or f.get("frozen"):
            continue
        try:
            det = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        n_checked += 1
        q = det.get("quality") or {}
        if q.get("overall") not in ("High", "Medium", "Low"):
            n_noq += 1
        for s in det.get("sels") or []:
            if len(s) >= 3 and _num(s[1]) and _num(s[2]) and abs(s[1] - s[2]) > 1e-6:
                n_blend += 1
                break
        xg = det.get("xg") or {}
        if _num(xg.get("home")) and _num(xg.get("model_home")) and abs(xg["home"] - xg["model_home"]) > 1e-6:
            n_blend += 1
    if n_checked and n_noq:
        (errors if n_noq > 3 else warns).append(f"{n_noq} of {n_checked} detail files without a data-quality assessment")
    if n_blend:
        errors.append(f"{n_blend} detail file(s) where a published probability / xG differs from the football-data model "
                      "(market contamination)")
    shortlist = d.get("shortlist") or {}
    if not isinstance(shortlist.get("primary"), list) or not isinstance(shortlist.get("counts"), dict):
        errors.append("shortlist payload missing primary selections or counts")
    else:
        seen_shortlist = set()
        by_id = {f.get("id"): f for f in fixtures}
        for pick in shortlist["primary"]:
            fid = pick.get("fixture")
            f = by_id.get(fid)
            if not f or fid in seen_shortlist:
                errors.append(f"shortlist has unknown or repeated fixture {fid}")
            elif f.get("date") != now.strftime("%Y-%m-%d") or f.get("kickoff", "") <= now.strftime("%Y-%m-%d %H:%M"):
                errors.append(f"shortlist fixture is not upcoming today: {fid}")
            seen_shortlist.add(fid)
    sf = d.get("safe") or {}
    min_p, min_odds = float(sf.get("min_p") or 0.7), float(sf.get("min_odds") or 1.3)
    known = ids | _archive_ids(staging)
    for b in sf.get("bets") or []:
        if b.get("fixture") not in known:
            errors.append(f"safest bet on unknown fixture {b.get('fixture')}")
        if not b.get("live"):
            if not _num(b.get("p")) or b["p"] < min_p - 1e-6:
                errors.append(f"safest bet below the probability rule: {b.get('label')} {b.get('p')}")
            if not _num(b.get("odds")) or b["odds"] < min_odds - 1e-6:
                errors.append(f"safest bet below the price rule: {b.get('label')} {b.get('odds')}")
        if not rec_policy.allowed(b.get("sel")):
            errors.append(f"disabled market in safest bets: {b.get('sel')}")
    seen_match = set()
    for b in (sf.get("bets") or []):
        if b.get("live"):
            continue
        m = (b.get("home"), b.get("away"))
        if m in seen_match:
            warns.append(f"more than one market on {m[0]} v {m[1]} in safest bets")
        seen_match.add(m)
    today = sf.get("today") or {}
    section_keys = {g[0] for g in safe.BOTD_GROUPS}
    card_matches = {}
    for b in today.get("bets") or []:
        if not competition_policy.allows_record(b):
            errors.append(f"paused competition in day card {b.get('id')}")
        if not rec_policy.allowed(b.get("sel")) or safe.botd_group(b.get("sel", "")) != b.get("section"):
            errors.append(f"disabled market or incorrect section in day card {b.get('id')}")
        if b.get("status") not in STATUSES:
            errors.append(f"bad status {b.get('status')!r} on day-card bet {b.get('id')}")
        if b.get("section") not in section_keys:
            errors.append(f"unknown day-card section {b.get('section')!r}")
        m = (b.get("home"), b.get("away"))
        if m in card_matches and card_matches[m] != b.get("sel"):
            warns.append(f"two markets on {m[0]} v {m[1]} in the day card")
        card_matches[m] = b.get("sel")
    for mkt, lst in (d.get("picks") or {}).items():
        if lst and not rec_policy.allowed(mkt):
            errors.append(f"disabled market in new shortlist picks: {mkt}")
        for pk in lst:
            if pk.get("fixture") not in known:
                errors.append(f"{mkt} pick on unknown fixture {pk.get('fixture')}")
    for name in ("meta.json", "alerts.json", "badges.json"):
        p = staging / name
        if not p.exists():
            errors.append(f"{name} missing")
            continue
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except ValueError as exc:
            errors.append(f"{name} is not valid JSON: {exc}")
    # ledger invariants
    if ledger.exists():
        try:
            with ledger.open(encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            seen = set()
            for r in rows:
                k = (r.get("match_date"), r.get("home"), r.get("away"), r.get("sel"))
                if k in seen:
                    errors.append(f"duplicate ledger row {k}")
                seen.add(k)
                if r.get("status") not in STATUSES:
                    errors.append(f"bad ledger status {r.get('status')!r} for {k}")
                try:
                    pv = float(r.get("p") or "nan")
                    if not (0 <= pv <= 1):
                        errors.append(f"ledger probability out of range for {k}")
                except ValueError:
                    errors.append(f"ledger probability not numeric for {k}")
                if r.get("status") in ("hit", "miss") and not (r.get("score") or "").strip():
                    warns.append(f"settled ledger row without a score: {k}")
        except (OSError, csv.Error) as exc:
            errors.append(f"ledger unreadable: {exc}")
    return errors, warns
