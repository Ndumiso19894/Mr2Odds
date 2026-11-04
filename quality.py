"""
Evidence, data-quality and explanation layer of the football-data model (data-first engine).

Everything here is *descriptive*: it never changes a probability. It answers the questions
"what sample is this number based on?", "how good is the data?", "why does the model say 1.35 goals?"
and "where do model and market disagree?", using the actual inputs of the model.

Vocabulary used everywhere (kept apart on purpose):
  historical frequency  = what happened in the sample ("scored in 9 of 10" -> 90 %)
  model probability     = output of the Dixon-Coles score matrix built from football data only
  market implied        = bookmaker price with the margin removed (comparison layer, never a model input)

Evidence labels by sample size: Very small 1-4, Small 5-9, Moderate 10-19, Strong 20-39, Very strong 40+.
Missing data is reported as N/A (None) and lowers the data-quality score; it is never replaced by zero.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

OUTLIER_MARGIN = 4          # 4-0, 5-1, 0-4 ...
OUTLIER_TOTAL = 7           # 4-4, 5-2 ...
FRIENDLY_MIN_COMPETITIVE = 8

EVIDENCE = ((1, "Very small"), (5, "Small"), (10, "Moderate"), (20, "Strong"), (40, "Very strong"))
QUALITY_WEIGHTS = {"completeness": 0.20, "sample": 0.30, "recency": 0.15, "consistency": 0.10,
                   "competition": 0.10, "venue": 0.10, "verification": 0.05}


# ----------------------------------------------------------------------------- helpers
def evidence_label(n: int | float | None) -> str:
    """Sample-size label. 0 / None -> 'No data'."""
    if n is None or (isinstance(n, float) and math.isnan(n)) or n < 1:
        return "No data"
    label = "Very small"
    for lo, name in EVIDENCE:
        if n >= lo:
            label = name
    return label


def _nan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def _f(v, nd=2):
    return None if _nan(v) else round(float(v), nd)


def _mean(vals) -> float | None:
    vals = [float(v) for v in vals if not _nan(v)]
    return round(sum(vals) / len(vals), 2) if vals else None


def _count(vals) -> int:
    return sum(1 for v in vals if not _nan(v))


def is_friendly(league: str | None) -> bool:
    return "friendl" in (league or "").lower()


def season_starts(results: pd.DataFrame, now: datetime) -> dict[str, pd.Timestamp]:
    """Inferred current-season start per division: the end of the latest gap of >= 35 days between match days
    (within the last 400 days); when no such gap exists the calendar rule (1 July) is used."""
    out: dict[str, pd.Timestamp] = {}
    if results.empty:
        return out
    today = pd.Timestamp(now.date())
    default = pd.Timestamp(year=today.year if today.month >= 7 else today.year - 1, month=7, day=1)
    recent = results[results["date"] >= today - pd.Timedelta(days=400)]
    for div, grp in recent.groupby("div"):
        days = np.sort(grp["date"].dt.normalize().unique())
        start = None
        if len(days) > 1:
            gaps = np.diff(days).astype("timedelta64[D]").astype(int)
            idx = np.where(gaps >= 35)[0]
            if len(idx):
                start = pd.Timestamp(days[idx[-1] + 1])
        if start is None:
            start = default
        elif start > today - pd.Timedelta(days=21) and len(days) > 1:
            # the gap just ended (season began within three weeks): that is still the current season
            pass
        out[str(div)] = start
    return out


# ----------------------------------------------------------------------------- team sample
def match_record(r, season_start: pd.Timestamp | None) -> dict:
    """Serialisable raw observation from a perspective row (team's point of view)."""
    g = lambda k: getattr(r, k, float("nan"))  # noqa: E731
    total = int(r.gf) + int(r.ga)
    kinds = []
    if abs(int(r.gf) - int(r.ga)) >= OUTLIER_MARGIN:
        kinds.append("margin")
    if total >= OUTLIER_TOTAL:
        kinds.append("total")
    return {
        "date": r.date.strftime("%Y-%m-%d"), "venue": r.venue, "opp": r.opp, "gf": int(r.gf), "ga": int(r.ga),
        "league": r.league, "div": r.div,
        "friendly": is_friendly(r.league),
        "season": "current" if season_start is not None and r.date >= season_start else "previous",
        "outlier": kinds or None,
        "xg_for": _f(g("xg_for")), "xg_against": _f(g("xg_against")),
        "shots_for": _f(g("s_for"), 0), "shots_against": _f(g("s_against"), 0),
        "sot_for": _f(g("sot_for"), 0), "sot_against": _f(g("sot_against"), 0),
        "corners_for": _f(g("c_for"), 0), "corners_against": _f(g("c_against"), 0),
        "cards_for": _f(g("k_for"), 0), "cards_against": _f(g("k_against"), 0),
        "eid": (getattr(r, "eid", None) or None) if isinstance(getattr(r, "eid", None), str) else None,
    }


def split_stats(ms: list[dict]) -> dict | None:
    """Plain (unweighted) historical frequencies of a list of match records. None when the list is empty.
    Stats that are missing from every match are N/A (None), never 0."""
    if not ms:
        return None
    n = len(ms)
    gf = [m["gf"] for m in ms]; ga = [m["ga"] for m in ms]
    tot = [a + b for a, b in zip(gf, ga)]
    out = {
        "n": n, "label": evidence_label(n),
        "gf": round(sum(gf) / n, 2), "ga": round(sum(ga) / n, 2), "total": round(sum(tot) / n, 2),
        "o15": sum(t >= 2 for t in tot), "o25": sum(t >= 3 for t in tot), "o35": sum(t >= 4 for t in tot),
        "btts": sum(a > 0 and b > 0 for a, b in zip(gf, ga)), "cs": sum(b == 0 for b in ga), "fts": sum(a == 0 for a in gf),
        "scored": sum(a > 0 for a in gf), "w": sum(a > b for a, b in zip(gf, ga)), "d": sum(a == b for a, b in zip(gf, ga)),
        "l": sum(a < b for a, b in zip(gf, ga)),
    }
    for key in ("xg", "shots", "sot", "corners", "cards"):
        f_vals = [m.get(f"{key}_for") for m in ms]; a_vals = [m.get(f"{key}_against") for m in ms]
        k = _count(f_vals)
        out[f"{key}_n"] = k
        out[f"{key}_for"] = _mean(f_vals) if k else None
        out[f"{key}_against"] = _mean(a_vals) if k else None
    return out


def composition(ms: list[dict], excluded_friendlies: int, own_div: str | None, now: datetime) -> dict:
    n = len(ms)
    comps: dict[str, int] = {}
    for m in ms:
        comps[m["league"]] = comps.get(m["league"], 0) + 1
    own_n = sum(1 for m in ms if own_div and m["div"] == own_div)
    dates = sorted(m["date"] for m in ms)
    last = datetime.strptime(dates[-1], "%Y-%m-%d") if dates else None
    return {
        "n": n, "label": evidence_label(n),
        "current_season": sum(1 for m in ms if m["season"] == "current"),
        "previous_season": sum(1 for m in ms if m["season"] == "previous"),
        "home": sum(1 for m in ms if m["venue"] == "H"), "away": sum(1 for m in ms if m["venue"] == "A"),
        "competitions": dict(sorted(comps.items(), key=lambda kv: -kv[1])),
        "mixed_competitions": len(comps) > 1,
        "own_competition_share": round(own_n / n, 2) if n else None,
        "friendlies_included": sum(1 for m in ms if m["friendly"]),
        "friendlies_excluded": excluded_friendlies,
        "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None,
        "days_since_last": (datetime(now.year, now.month, now.day) - last).days if last else None,
        "with_xg": _count([m.get("xg_for") for m in ms]), "with_shots": _count([m.get("sot_for") for m in ms]),
        "with_corners": _count([m.get("corners_for") for m in ms]), "with_cards": _count([m.get("cards_for") for m in ms]),
    }


def outliers(ms: list[dict]) -> list[dict]:
    """Extreme results kept in the sample but flagged, with their effect on the last-10 scoring averages."""
    out = []
    last10 = ms[:10]
    for m in ms:
        if not m.get("outlier"):
            continue
        item = {"date": m["date"], "opp": m["opp"], "venue": m["venue"], "score": f"{m['gf']}-{m['ga']}",
                "kind": ", ".join(m["outlier"]), "eid": m.get("eid")}
        if m in last10 and len(last10) > 1:
            rest = [x for x in last10 if x is not m]
            item["last10_gf_with"] = round(sum(x["gf"] for x in last10) / len(last10), 2)
            item["last10_gf_without"] = round(sum(x["gf"] for x in rest) / len(rest), 2)
            item["last10_ga_with"] = round(sum(x["ga"] for x in last10) / len(last10), 2)
            item["last10_ga_without"] = round(sum(x["ga"] for x in rest) / len(rest), 2)
        out.append(item)
    return out


def recent_signal(ms: list[dict], baseline_gf: float | None, baseline_ga: float | None) -> dict:
    """Last-5 / last-10 scoring versus the long-term (time-weighted) baseline. Information only: the model's
    exponential time-weighting already includes recent matches; recent form never overrides the baseline."""
    def block(k):
        s = ms[:k]
        if not s:
            return None
        return {"n": len(s), "gf": round(sum(m["gf"] for m in s) / len(s), 2), "ga": round(sum(m["ga"] for m in s) / len(s), 2)}
    l5, l10 = block(5), block(10)
    out = {"last5": l5, "last10": l10, "baseline_gf": _f(baseline_gf), "baseline_ga": _f(baseline_ga), "attack": None, "defence": None}
    if l5 and not _nan(baseline_gf) and l5["n"] >= 5:
        d = l5["gf"] - baseline_gf
        out["attack"] = "stronger than baseline" if d >= 0.5 else ("weaker than baseline" if d <= -0.5 else "in line with baseline")
        out["attack_diff"] = round(d, 2)
    if l5 and not _nan(baseline_ga) and l5["n"] >= 5:
        d = l5["ga"] - baseline_ga
        out["defence"] = "leakier than baseline" if d >= 0.5 else ("tighter than baseline" if d <= -0.5 else "in line with baseline")
        out["defence_diff"] = round(d, 2)
    return out


def team_evidence(p, own_div: str | None, now: datetime) -> dict:
    """Everything the app / audit needs about one team's sample. `p` is a scanner.TeamProfile."""
    ms = list(getattr(p, "matches", []) or [])
    comp = composition(ms, getattr(p, "friendlies_excluded", 0), own_div, now)
    return {
        "team": p.name,
        "composition": comp,
        "splits": {"all": split_stats(ms), "home": split_stats([m for m in ms if m["venue"] == "H"]),
                   "away": split_stats([m for m in ms if m["venue"] == "A"]),
                   "current": split_stats([m for m in ms if m["season"] == "current"]),
                   "previous": split_stats([m for m in ms if m["season"] == "previous"])},
        "recent": recent_signal(ms, p.gf, p.ga),
        "outliers": outliers(ms),
        "ratings": {"att_raw": _f(getattr(p, "att_raw", None), 3), "def_raw": _f(getattr(p, "def_raw", None), 3),
                    "att_venue_raw": _f(getattr(p, "att_venue_raw", None), 3), "def_venue_raw": _f(getattr(p, "def_venue_raw", None), 3),
                    "venue_share": _f(getattr(p, "venue_share", None), 3),
                    "att_blend": _f(getattr(p, "att_blend", None), 3), "def_blend": _f(getattr(p, "def_blend", None), 3),
                    "att": _f(p.att, 3), "def": _f(p.dfc, 3), "n_eff": _f(p.n_eff, 1), "n": int(p.n), "venue_n": int(p.venue_n),
                    "opp_att_faced": _f(getattr(p, "opp_att", None), 3), "opp_def_faced": _f(getattr(p, "opp_def", None), 3),
                    "att_opp_adj": _f(getattr(p, "att_opp_adj", None), 3), "def_opp_adj": _f(getattr(p, "def_opp_adj", None), 3)},
        "matches": ms,
    }


MATCH_COLS = ("date", "venue", "opp", "gf", "ga", "league", "div", "friendly", "season", "outlier", "xg_for", "xg_against",
              "shots_for", "shots_against", "sot_for", "sot_against", "corners_for", "corners_against", "cards_for", "cards_against", "eid")


def compact_matches(ms: list[dict]) -> dict:
    """Column-oriented form of the raw match list for the app export (same content, ~60% smaller)."""
    return {"cols": list(MATCH_COLS), "rows": [[m.get(c) for c in MATCH_COLS] for m in ms]}


def expand_matches(obj) -> list[dict]:
    if isinstance(obj, dict) and "cols" in obj:
        return [dict(zip(obj["cols"], row)) for row in obj.get("rows") or []]
    return list(obj or [])


# ----------------------------------------------------------------------------- head-to-head
def h2h_evidence(h2h: list[dict], now: datetime) -> dict:
    n = len(h2h or [])
    out = {"n": n, "label": evidence_label(n), "used_by_model": False,
           "note": "Head-to-head is shown for context only; it is not a model input. Sample of this size cannot support "
                   "conclusions on its own." if n < 5 else "Head-to-head is shown for context only; it is not a model input."}
    if n:
        tot = [m["hg"] + m["ag"] for m in h2h]
        out.update({"avg_goals": round(float(np.mean(tot)), 2), "o25": sum(t >= 3 for t in tot), "o15": sum(t >= 2 for t in tot),
                    "btts": sum(m["hg"] > 0 and m["ag"] > 0 for m in h2h),
                    "first_date": min(m["date"] for m in h2h).strftime("%Y-%m-%d"),
                    "last_date": max(m["date"] for m in h2h).strftime("%Y-%m-%d"),
                    "competitions": sorted({m["league"] for m in h2h})})
    return out


# ----------------------------------------------------------------------------- data quality
def _score_sample(n_eff_h: float, n_eff_a: float, n_h: int, n_a: int) -> float:
    n = min(n_h, n_a)
    if n >= 20:
        s = 1.0
    elif n >= 10:
        s = 0.8
    elif n >= 5:
        s = 0.55
    elif n >= 1:
        s = 0.3
    else:
        return 0.0
    if min(n_eff_h, n_eff_a) < 4:      # very little recent, weighted evidence
        s = min(s, 0.3)
    return s


def data_quality(r, ev_h: dict, ev_a: dict, h2h: dict, now: datetime) -> dict:
    """Transparent per-match data-quality assessment. It is NOT a prediction and does not change any probability;
    it drives the confidence wording. Each component is 0-1 with a plain-language reason."""
    fx = r.fx
    comp_h, comp_a = ev_h["composition"], ev_a["composition"]
    reasons: dict[str, str] = {}
    comps: dict[str, float] = {}

    # completeness: which of the critical fields exist (goals always do when a match is in the sample)
    fields = {"goals (home sample)": comp_h["n"] > 0, "goals (away sample)": comp_a["n"] > 0,
              "shots on target": comp_h["with_shots"] > 0 and comp_a["with_shots"] > 0,
              "xG": comp_h["with_xg"] > 0 and comp_a["with_xg"] > 0,
              "corners": comp_h["with_corners"] > 0 and comp_a["with_corners"] > 0,
              "cards": comp_h["with_cards"] > 0 and comp_a["with_cards"] > 0,
              "head-to-head": h2h["n"] > 0, "bookmaker price": bool(r.sb)}
    weights = {"goals (home sample)": 3, "goals (away sample)": 3, "shots on target": 1, "xG": 1, "corners": 1, "cards": 1,
               "head-to-head": 0.5, "bookmaker price": 0.5}
    have = sum(weights[k] for k, ok in fields.items() if ok); tot = sum(weights.values())
    comps["completeness"] = have / tot
    missing = [k for k, ok in fields.items() if not ok]
    reasons["completeness"] = f"{int(round(100 * have / tot))}% of tracked fields present" + (f"; missing: {', '.join(missing)}" if missing else "")

    comps["sample"] = _score_sample(r.home.n_eff, r.away.n_eff, comp_h["n"], comp_a["n"])
    reasons["sample"] = (f"{fx['home']}: {comp_h['n']} matches ({comp_h['label']}), {fx['away']}: {comp_a['n']} matches "
                         f"({comp_a['label']}); weighted {r.home.n_eff:.1f} / {r.away.n_eff:.1f}")

    ds = [d for d in (comp_h["days_since_last"], comp_a["days_since_last"]) if d is not None]
    worst = max(ds) if ds else None
    comps["recency"] = 0.0 if worst is None else (1.0 if worst <= 14 else 0.8 if worst <= 30 else 0.5 if worst <= 60 else 0.25)
    reasons["recency"] = "no recent match" if worst is None else f"last match {worst} day{'s' if worst != 1 else ''} ago (older of the two teams)"

    # consistency: how far the two samples sit from what the model says, and internal contradictions (recent v baseline)
    incons = []
    for side, ev in (("home", ev_h), ("away", ev_a)):
        rc = ev["recent"]
        if rc.get("attack_diff") is not None and abs(rc["attack_diff"]) >= 0.8:
            incons.append(f"{ev['team']}: last-5 attack {rc['attack_diff']:+.2f} goals v baseline")
        if rc.get("defence_diff") is not None and abs(rc["defence_diff"]) >= 0.8:
            incons.append(f"{ev['team']}: last-5 defence {rc['defence_diff']:+.2f} goals v baseline")
        recent_out = [o for o in ev["outliers"] if "last10_gf_with" in o]
        if recent_out or (ev["composition"]["n"] and len(ev["outliers"]) / ev["composition"]["n"] > 0.15):
            incons.append(f"{ev['team']}: {len(recent_out) or len(ev['outliers'])} extreme result{'s' if (len(recent_out) or len(ev['outliers'])) > 1 else ''} "
                          f"{'in the last 10' if recent_out else 'in sample'}")
    comps["consistency"] = max(0.4, 1.0 - 0.2 * len(incons))
    reasons["consistency"] = "; ".join(incons) if incons else "recent form in line with the baseline, no extreme results"

    shares = [s for s in (comp_h["own_competition_share"], comp_a["own_competition_share"]) if s is not None]
    own = min(shares) if shares else 0.0
    fr = comp_h["friendlies_included"] + comp_a["friendlies_included"]
    comps["competition"] = (1.0 if own >= 0.8 else 0.75 if own >= 0.6 else 0.5 if own >= 0.4 else 0.3) * (0.7 if fr else 1.0)
    reasons["competition"] = f"{int(round(100 * own))}% of the smaller sample is from this competition" + (
        f"; {fr} friendlies included (too few competitive matches to exclude them)" if fr else "")

    vn = min(r.home.venue_n, r.away.venue_n)
    comps["venue"] = 1.0 if vn >= 10 else 0.75 if vn >= 5 else 0.5 if vn >= 2 else 0.25 if vn else 0.0
    reasons["venue"] = f"{fx['home']} home matches: {r.home.venue_n}, {fx['away']} away matches: {r.away.venue_n} in sample"

    src = str(fx.get("source") or "")
    ver = 1.0 if src == "main" else 0.85
    comps["verification"] = ver
    reasons["verification"] = ("football-data.co.uk results (verified feed) + Livescore" if src == "main"
                               else "Livescore results archive (final scores; match statistics where published)")

    score = sum(QUALITY_WEIGHTS[k] * comps[k] for k in QUALITY_WEIGHTS)
    overall = "High" if score >= 0.75 else "Medium" if score >= 0.5 else "Low"
    if comp_h["n"] < 5 or comp_a["n"] < 5:
        overall = "Low"
    critical_missing = [k for k in ("goals (home sample)", "goals (away sample)") if not fields[k]]
    return {"score": round(score, 2), "overall": overall,
            "components": {k: {"score": round(v, 2), "reason": reasons[k]} for k, v in comps.items()},
            "missing_fields": missing, "critical_missing": critical_missing,
            "sources": sorted({reasons["verification"]}),
            "collected": now.strftime("%Y-%m-%d %H:%M"),
            "note": "Data quality describes the evidence behind the numbers. It changes the confidence wording, never the probability."}


def confidence(p: float | None, quality: dict, n_min: int) -> str:
    """Confidence wording for one probability: a function of data quality and the smaller sample."""
    if _nan(p):
        return "N/A"
    q = quality["overall"]
    if q == "High" and n_min >= 10:
        return "High"
    if q == "Low" or n_min < 5:
        return "Low"
    return "Medium"


# ----------------------------------------------------------------------------- explanation + warnings
def explanation(r, ev_h: dict, ev_a: dict, config: dict) -> dict:
    """The lambda decomposition in the model's actual numbers (nothing generic)."""
    da = r.div_avg
    H, A = r.home, r.away
    kt, ks, kv = config["SHRINK_K"], config["SHRINK_K_STRENGTH"], config["VENUE_K"]
    return {
        "league": {"div": str(r.fx["div"]), "mu_home": _f(da.mu_h, 3), "mu_away": _f(da.mu_a, 3), "n_eff": _f(da.n_eff, 1),
                   "o25_rate": _f(da.o25_rate, 3), "btts_rate": _f(da.btts_rate, 3)},
        "home": ev_h["ratings"], "away": ev_a["ratings"],
        "lambda_home": {"formula": "league home average x home attack x away defence, then any experimental data adjustments",
                        "terms": [_f(da.mu_h, 3), _f(H.att, 3), _f(A.dfc, 3)], "value": _f(r.mod_h, 3)},
        "lambda_away": {"formula": "league away average x away attack x home defence, then any experimental data adjustments",
                        "terms": [_f(da.mu_a, 3), _f(A.att, 3), _f(H.dfc, 3)], "value": _f(r.mod_a, 3)},
        "model_signals": getattr(r, "model_signals", {}),
        "settings": {"half_life_days": config["HALF_LIFE_DAYS"], "max_matches": config["MAX_MATCHES_PER_TEAM"],
                     "shrink_k_tempo": kt, "shrink_k_strength": ks, "venue_k": kv, "dc_rho": config["DC_RHO"],
                     "lambda_clip": [0.15, 4.5]},
        "steps": [
            "1. Every past match of the team (last 40, max 400 days, friendlies excluded when enough competitive matches exist) is "
            "expressed as goals scored / conceded relative to the average of that competition (league-normalised).",
            f"2. Matches are time-weighted (half-life {config['HALF_LIFE_DAYS']} days) and averaged: raw attack and defence ratings.",
            f"3. Venue-specific rates are blended in with weight n_venue / (n_venue + {kv}).",
            f"4. Ratings are shrunk towards the league average (1.00): the attack/defence ratio (strength) with K = {ks} and the "
            f"overall tempo with K = {kt} weighted matches — small samples stay close to the average.",
            "5. Baseline expected goals (lambda) = league venue average x attack x opponent's defence.",
            "6. Experimental xG/xGA and shots-on-target corrections may adjust lambda when data is sufficient; they have not been backtested. See model_signals for the current status.",
            f"7. The resulting lambdas form a Dixon-Coles score matrix (rho {config['DC_RHO']}), 0-10 goals per team; goal and result probabilities are read from it.",
            "Bookmaker prices are not used anywhere in these steps.",
        ],
    }


def market_layer(r) -> dict:
    """Model v market per priced selection: model %, price, implied % (margin removed), difference, EV."""
    from safe import label as _label, selections as _selections  # local import: safe imports nothing from here
    out = {"xg": {"model_home": _f(r.mod_h), "model_away": _f(r.mod_a), "model_total": _f(r.mod_h + r.mod_a),
                  "market_home": _f(r.mkt_h), "market_away": _f(r.mkt_a),
                  "market_total": None if _nan(r.mkt_h) else _f(r.mkt_h + r.mkt_a),
                  "market_source": getattr(r, "mkt_source", None) if not _nan(r.mkt_h) else None,
                  "gap_total": None if _nan(r.mkt_h) else _f(r.mod_h + r.mod_a - r.mkt_h - r.mkt_a)},
           "x12_market": getattr(r, "x12_market", None), "selections": []}
    for s in _selections(r):
        if s.p_sb is None and s.odds is None:
            continue
        out["selections"].append({"sel": s.sel, "label": _label(s.sel, r.fx["home"], r.fx["away"]),
                                  "p_model": round(s.p_model, 3), "p_market": _f(s.p_sb, 3),
                                  "odds": _f(s.odds), "diff_pp": None if s.p_sb is None else round(100 * (s.p_model - s.p_sb), 1),
                                  "ev": None if not s.odds else round(s.p_model * s.odds - 1, 3)})
    return out


def warnings_for(r, ev_h: dict, ev_a: dict, h2h: dict, quality: dict, market: dict, config: dict) -> list[dict]:
    """Automatic model-v-raw-data checks. Levels: 'warn' (act with care) and 'info' (worth knowing)."""
    W: list[dict] = []

    def add(code, level, text):
        W.append({"code": code, "level": level, "text": text})

    ch, ca = ev_h["composition"], ev_a["composition"]
    top_p = max(r.p_model.get("O15", 0), (r.extra.tg or {}).get("H_o05", 0), (r.extra.tg or {}).get("A_o05", 0))
    for team, c in ((ev_h["team"], ch), (ev_a["team"], ca)):
        if c["n"] < 5:
            add("insufficient_sample", "warn", f"{team}: only {c['n']} match{'es' if c['n'] != 1 else ''} in the sample ({c['label']} evidence)")
        elif c["n"] < 10:
            add("small_sample", "info", f"{team}: {c['n']} matches in the sample (Small evidence)")
        if c["days_since_last"] is not None and c["days_since_last"] > 45:
            add("old_data", "warn", f"{team}: last match {c['days_since_last']} days ago — ratings rely on older results")
        if c["mixed_competitions"] and (c["own_competition_share"] or 0) < 0.7:
            add("mixed_competitions", "info", f"{team}: {int(round(100 * (c['own_competition_share'] or 0)))}% of the sample is from this competition "
                                              f"({', '.join(f'{k} {v}' for k, v in list(c['competitions'].items())[:3])})")
        if c["friendlies_included"]:
            add("friendlies", "info", f"{team}: {c['friendlies_included']} friendl{'ies' if c['friendlies_included'] > 1 else 'y'} kept in the sample "
                                       f"(fewer than {FRIENDLY_MIN_COMPETITIVE} competitive matches)")
    if top_p >= 0.85 and quality["overall"] == "Low":
        add("high_p_low_quality", "warn", f"High model probability ({int(round(100 * top_p))}%) with Low data quality — treat with care")
    if top_p >= 0.85 and min(ch["n"], ca["n"]) < 10:
        add("high_p_weak_evidence", "warn", f"High model probability ({int(round(100 * top_p))}%) rests on {min(ch['n'], ca['n'])} matches for one team")
    for side, ev in (("home", ev_h), ("away", ev_a)):
        rc = ev["recent"]
        if rc.get("attack") and "baseline" in rc["attack"] and "in line" not in rc["attack"]:
            add("form_v_baseline", "info", f"{ev['team']}: recent attack {rc['attack']} ({rc['last5']['gf']:.2f} v {rc['baseline_gf']:.2f} goals per game, last 5 v weighted sample)")
        if rc.get("defence") and "in line" not in (rc["defence"] or ""):
            add("form_v_baseline", "info", f"{ev['team']}: recent defence {rc['defence']} ({rc['last5']['ga']:.2f} v {rc['baseline_ga']:.2f} conceded per game)")
        for o in ev["outliers"]:
            if "last10_gf_with" in o:
                add("outlier", "info", f"{ev['team']}: recent scoring average affected by extreme result {o['score']} "
                                       f"{'v' if o['venue'] == 'H' else '@'} {o['opp']} ({o['date']}): last-10 goals for {o['last10_gf_with']:.2f} with / "
                                       f"{o['last10_gf_without']:.2f} without, against {o['last10_ga_with']:.2f} / {o['last10_ga_without']:.2f}")
        splits = ev["splits"]
        for key, nm in (("home", "home"), ("away", "away")):
            st = splits.get(key)
            if st and st["n"] <= 3 and st["n"] and (st["o25"] == st["n"] or st["btts"] == st["n"] or st["cs"] == st["n"]):
                add("perfect_small", "warn", f"{ev['team']}: 100% rates in {nm} matches come from only {st['n']} match{'es' if st['n'] > 1 else ''} — not meaningful")
    if h2h["n"] and h2h["n"] < 5:
        add("h2h_small", "info", f"Head-to-head sample: {h2h['n']} match{'es' if h2h['n'] > 1 else ''} — evidence strength {h2h['label']}; context only")
    xg = market["xg"]
    if xg["gap_total"] is not None and abs(xg["gap_total"]) >= 0.5:
        add("model_v_market_xg", "info", f"Model total xG {xg['model_total']:.2f} v market {xg['market_total']:.2f} ({xg['gap_total']:+.2f}) — "
                                         f"{'the model sees more goals than the market' if xg['gap_total'] > 0 else 'the market sees more goals than the model'}")
    big = [s for s in market["selections"] if s["diff_pp"] is not None and abs(s["diff_pp"]) >= 12 and s["sel"] in ("O15", "O25", "BTTS", "H", "A", "HO05", "AO05")]
    if big:
        worst = max(big, key=lambda s: abs(s["diff_pp"]))
        add("model_v_market", "info", f"Model / market disagreement on {worst['sel']}: model {int(round(100 * worst['p_model']))}% v market "
                                      f"{int(round(100 * worst['p_market']))}% ({worst['diff_pp']:+.0f} pp)")
    miss = [k for k in quality["missing_fields"] if k in ("shots on target", "xG")]
    if miss:
        add("missing_fields", "info", f"No {' / '.join(miss)} data for these teams — the model uses goals only (shown as N/A, never as 0)")
    return W


# ----------------------------------------------------------------------------- audit report (markdown)
def _pct(p) -> str:
    return "N/A" if _nan(p) else f"{100 * float(p):.0f}%"


def _row(*cells) -> str:
    return "| " + " | ".join("N/A" if c is None else str(c) for c in cells) + " |"


def _split_row(name: str, st: dict | None) -> str:
    if not st:
        return _row(name, "0", "No data", *["N/A"] * 9)
    n = st["n"]
    return _row(name, n, st["label"], f"{st['gf']:.2f}", f"{st['ga']:.2f}", f"{st['o15']}/{n} ({100 * st['o15'] / n:.0f}%)",
                f"{st['o25']}/{n} ({100 * st['o25'] / n:.0f}%)", f"{st['btts']}/{n} ({100 * st['btts'] / n:.0f}%)",
                f"{st['cs']}/{n}", f"{st['scored']}/{n}",
                "N/A" if st["sot_for"] is None else f"{st['sot_for']:.1f} / {st['sot_against']:.1f} (n={st['sot_n']})",
                "N/A" if st["corners_for"] is None else f"{st['corners_for']:.1f} / {st['corners_against']:.1f} (n={st['corners_n']})")


def recompute(d: dict) -> list:
    """Rebuild the score matrix from the published λ values and rho (plain math, independent of scanner.py) and
    return [(key, name, published_p, recomputed_p)] for the main lines — the audit's self-check."""
    import math
    ex = d.get("explain") or {}
    lh, la = (ex.get("lambda_home") or {}).get("value"), (ex.get("lambda_away") or {}).get("value")
    rho = (ex.get("settings") or {}).get("dc_rho", 0.0) or 0.0
    if lh is None or la is None:
        return []
    n = 11
    ph = [math.exp(-lh) * lh ** k / math.factorial(k) for k in range(n)]
    pa = [math.exp(-la) * la ** k / math.factorial(k) for k in range(n)]
    M = [[ph[i] * pa[j] for j in range(n)] for i in range(n)]
    if rho:
        M[0][0] *= 1 - lh * la * rho
        M[1][0] *= 1 + la * rho
        M[0][1] *= 1 + lh * rho
        M[1][1] *= 1 - rho
    tot = sum(sum(r) for r in M)
    M = [[max(v, 1e-12) / tot for v in r] for r in M]
    def s(cond):
        return sum(M[i][j] for i in range(n) for j in range(n) if cond(i, j))
    p = d.get("p") or {}
    x12 = d.get("x12") or {}
    out = [("O15", "Over 1.5", p.get("O15"), s(lambda i, j: i + j >= 2)),
           ("O25", "Over 2.5", p.get("O25"), s(lambda i, j: i + j >= 3)),
           ("O35", "Over 3.5", p.get("O35"), s(lambda i, j: i + j >= 4)),
           ("BTTS", "Both teams to score", p.get("BTTS"), s(lambda i, j: i >= 1 and j >= 1))]
    if x12:
        out += [("H", "Home win", x12.get("H"), s(lambda i, j: i > j)), ("D", "Draw", x12.get("D"), s(lambda i, j: i == j)),
                ("A", "Away win", x12.get("A"), s(lambda i, j: i < j))]
    return out


def audit_markdown(d: dict) -> str:
    """Full data-audit report for one exported match detail (appdata detail dict)."""
    q = d.get("quality") or {}; ex = d.get("explain") or {}; mk = d.get("market") or {}; ev = d.get("evidence") or {}
    xg = d.get("xg") or {}; p = d.get("p") or {}; h2h = d.get("h2h_meta") or {}
    L = [f"# Data audit — {d['home']} v {d['away']}", "",
         f"{d.get('competition', '')} ({d.get('country', '')}) · kick-off {d.get('kickoff', '')} · generated {d.get('generated', q.get('collected', ''))}", "",
         "Vocabulary: **historical frequency** = what happened in the sample; **model probability** = football-data model "
         "(Dixon-Coles); **market implied** = bookmaker price with the margin removed (comparison only, never a model input).", ""]
    # 1. data quality
    L += ["## 1. Data quality", "", f"**Overall: {q.get('overall', 'N/A')}** (score {q.get('score', 'N/A')} / 1.00) — {q.get('note', '')}", "",
          "| Component | Score | Reason |", "|---|---|---|"]
    for k, v in (q.get("components") or {}).items():
        L.append(_row(k, f"{v['score']:.2f}", v["reason"]))
    L += ["", f"Missing fields: {', '.join(q.get('missing_fields') or []) or 'none'}. Sources: {'; '.join(q.get('sources') or [])}. "
              f"Data collected: {q.get('collected', 'N/A')}.", ""]
    # 2. team profiles + composition
    for side in ("home", "away"):
        e = ev.get(side) or {}
        c = e.get("composition") or {}
        rt = e.get("ratings") or {}
        L += [f"## 2{'a' if side == 'home' else 'b'}. Team profile — {e.get('team', d[side])} ({side})", "",
              f"* Sample: **{c.get('n', 0)} matches** ({c.get('label', 'No data')} evidence), {c.get('first_date', 'N/A')} → {c.get('last_date', 'N/A')}, "
              f"last match {c.get('days_since_last', 'N/A')} days ago",
              f"* Composition: current season {c.get('current_season', 0)}, previous {c.get('previous_season', 0)}; home {c.get('home', 0)}, away {c.get('away', 0)}; "
              f"competitions: {', '.join(f'{k} ({v})' for k, v in (c.get('competitions') or {}).items())}"
              f"{'; MIXED competitions' if c.get('mixed_competitions') else ''}; friendlies included {c.get('friendlies_included', 0)}, excluded {c.get('friendlies_excluded', 0)}",
              f"* Fields present: xG in {c.get('with_xg', 0)}, shots on target in {c.get('with_shots', 0)}, corners in {c.get('with_corners', 0)}, cards in {c.get('with_cards', 0)} of {c.get('n', 0)} matches",
              f"* Ratings (1.00 = competition average): raw attack {rt.get('att_raw')} / defence {rt.get('def_raw')}; venue raw {rt.get('att_venue_raw')} / {rt.get('def_venue_raw')} "
              f"(venue weight {rt.get('venue_share')}); after venue blend {rt.get('att_blend')} / {rt.get('def_blend')}; **after shrinkage {rt.get('att')} / {rt.get('def')}** "
              f"(weighted matches {rt.get('n_eff')})",
              f"* Opponent context (information only, not a model input): average opponent attack faced {rt.get('opp_att_faced')} / defence faced {rt.get('opp_def_faced')}; "
              f"opponent-adjusted raw attack {rt.get('att_opp_adj')} / defence {rt.get('def_opp_adj')}", ""]
        rc = e.get("recent") or {}
        l5, l10 = rc.get("last5") or {}, rc.get("last10") or {}
        L += ["**Recent form v baseline** (historical frequencies; the model's time-weighting already includes them)", "",
              f"* Last 5: {l5.get('gf', 'N/A')} scored / {l5.get('ga', 'N/A')} conceded per game (n={l5.get('n', 0)}); last 10: {l10.get('gf', 'N/A')} / {l10.get('ga', 'N/A')} (n={l10.get('n', 0)}); "
              f"weighted baseline {rc.get('baseline_gf', 'N/A')} / {rc.get('baseline_ga', 'N/A')}",
              f"* Recent attack: {rc.get('attack') or 'N/A (fewer than 5 matches)'} · recent defence: {rc.get('defence') or 'N/A'}", ""]
        L += ["**Home / away splits** (plain historical frequencies)", "",
              "| Split | n | Evidence | GF | GA | O1.5 | O2.5 | BTTS | Clean sheets | Scored | SOT for/ag | Corners for/ag |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        sp = e.get("splits") or {}
        for key, nm in (("all", "All"), ("home", "Home"), ("away", "Away"), ("current", "Current season"), ("previous", "Previous season")):
            L.append(_split_row(nm, sp.get(key)))
        L.append("")
        outs = e.get("outliers") or []
        if outs:
            L.append("**Extreme results in the sample** (kept, flagged):")
            for o in outs:
                extra = (f" — last-10 goals for {o['last10_gf_with']} with / {o['last10_gf_without']} without; against {o['last10_ga_with']} / {o['last10_ga_without']}"
                         if "last10_gf_with" in o else "")
                L.append(f"* {o['date']}: {o['score']} {'v' if o['venue'] == 'H' else '@'} {o['opp']} ({o['kind']}){extra}")
            L.append("")
        L += ["<details><summary>Matches used (raw observations)</summary>", "", "| Date | Venue | Opponent | Score | Competition | Season | xG f/a | SOT f/a | Corners f/a | Cards f/a | Flag |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for m in expand_matches(e.get("matches")):
            L.append(_row(m["date"], "H" if m["venue"] == "H" else "A", m["opp"], f"{m['gf']}-{m['ga']}", m["league"], m["season"],
                          None if m.get("xg_for") is None else f"{m['xg_for']} / {m['xg_against']}",
                          None if m.get("sot_for") is None else f"{int(m['sot_for'])} / {int(m['sot_against'])}",
                          None if m.get("corners_for") is None else f"{int(m['corners_for'])} / {int(m['corners_against'])}",
                          None if m.get("cards_for") is None else f"{int(m['cards_for'])} / {int(m['cards_against'])}",
                          ("friendly " if m.get("friendly") else "") + (", ".join(m["outlier"]) if m.get("outlier") else "")))
        L += ["", "</details>", ""]
    # 3. H2H
    L += ["## 3. Head-to-head", "", f"* Sample: **{h2h.get('n', 0)} match{'es' if h2h.get('n', 0) != 1 else ''}** — evidence strength **{h2h.get('label', 'No data')}**; "
                                      f"used by the model: **no** (context only)"]
    if h2h.get("n"):
        L.append(f"* {h2h.get('first_date')} → {h2h.get('last_date')} · avg {h2h.get('avg_goals')} goals · O2.5 in {h2h.get('o25')}/{h2h['n']} · BTTS in {h2h.get('btts')}/{h2h['n']} · "
                 f"{', '.join(h2h.get('competitions') or [])}")
        for m in d.get("h2h") or []:
            L.append(f"  * {m.get('date')}: {m.get('home')} {m.get('hg')}-{m.get('ag')} {m.get('away')} ({m.get('league', '')})")
    L += [f"* {h2h.get('note', '')}", ""]
    # 4. model
    lh, la = ex.get("lambda_home") or {}, ex.get("lambda_away") or {}
    lg = ex.get("league") or {}
    L += ["## 4. Model (football data only)", "",
          f"* League baseline ({lg.get('div')}): {lg.get('mu_home')} home + {lg.get('mu_away')} away goals per match (weighted n {lg.get('n_eff')}); "
          f"O2.5 in {_pct(lg.get('o25_rate'))}, BTTS in {_pct(lg.get('btts_rate'))} of league matches",
          f"* **Model xG home {xg.get('model_home')}** = {lh.get('formula')} = {' × '.join(str(t) for t in lh.get('terms') or [])}",
          f"* **Model xG away {xg.get('model_away')}** = {la.get('formula')} = {' × '.join(str(t) for t in la.get('terms') or [])}",
          f"* Model total {xg.get('model_total')}", "",
          "| Market | Model probability | Confidence |", "|---|---|---|"]
    conf = d.get("confidence") or {}
    for k, nm in (("O15", "Over 1.5"), ("O25", "Over 2.5"), ("O35", "Over 3.5"), ("BTTS", "Both teams to score")):
        L.append(_row(nm, _pct(p.get(k)), conf.get(k, "N/A")))
    x12 = d.get("x12") or {}
    if x12:
        L.append(_row("Home / draw / away", f"{_pct(x12.get('H'))} / {_pct(x12.get('D'))} / {_pct(x12.get('A'))}", conf.get("X12", "N/A")))
    tg = d.get("tg") or {}
    if tg:
        L.append(_row("Team to score (home / away)", f"{_pct(tg.get('H_o05'))} / {_pct(tg.get('A_o05'))}", conf.get("TG", "N/A")))
    L += ["", "Steps:"] + [f"* {s}" for s in ex.get("steps") or []] + [""]
    # 4b. independent recomputation from the published inputs (pure Python, no scanner import)
    rc = recompute(d)
    if rc:
        L += ["**Independent recomputation** — Dixon-Coles matrix rebuilt here from λ home / λ away and rho as published above; "
              "a mismatch would mean the file and the model disagree:", "",
              "| Market | Published | Recomputed | Match |", "|---|---|---|---|"]
        for k, nm, pub, new in rc:
            L.append(_row(nm, _pct(pub), _pct(new), "✅" if pub is not None and abs(pub - new) < 0.006 else "⚠️ differs"))
        L.append("")
    # 5. market comparison
    L += ["## 5. Market comparison (separate layer)", "",
          f"* Market xG: home {xg.get('market_home')} / away {xg.get('market_away')} / total {xg.get('market_total')} "
          f"(source: {xg.get('market_source') or 'N/A'}) — v model total {xg.get('model_total')}"
          + (f" → gap {mk.get('xg', {}).get('gap_total'):+.2f}" if (mk.get('xg') or {}).get('gap_total') is not None else ""), "",
          "| Selection | Model % | Sportybet price | Implied % | Difference (pp) | EV |", "|---|---|---|---|---|---|"]
    for s in mk.get("selections") or []:
        L.append(_row(s.get("label") or s["sel"], _pct(s["p_model"]), s["odds"], _pct(s["p_market"]), s["diff_pp"], None if s["ev"] is None else f"{100 * s['ev']:+.1f}%"))
    L += ["", "Difference = model − market implied; EV = model probability × price − 1. The market never feeds back into the model.", ""]
    # 6. warnings
    L += ["## 6. Warnings and checks", ""]
    ws = d.get("warnings") or []
    L += [f"* {'⚠️' if w['level'] == 'warn' else 'ℹ️'} {w['text']}" for w in ws] or ["* none"]
    L += ["", "## 7. Traceability", "",
          "final probability ← Dixon-Coles score matrix ← λ home / λ away ← league baseline × shrunk ratings ← time-weighted, league-normalised "
          "goals of the matches listed above ← results feeds (football-data.co.uk / Livescore).", ""]
    return "\n".join(L)
