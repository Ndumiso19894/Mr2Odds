"""Structured export for the Android app (format v3).

data/app/latest.json   slim index: meta, every fixture in the window (list fields only), shortlists, safest bets,
                       bets of the day, trackers, history index — small enough to refresh often
data/app/fx/<key>.json full detail for one fixture (stats, markets, selections, trends, h2h) — loaded on demand
data/app/meta.json     tiny heartbeat for the background checker (generated, run, alerts, tracked live ids)
data/app/alerts.json   the last new-bet alerts (id, time, title, text) — the app notifies the ones it has not seen
data/app/badges.json   team short name -> Livescore badge path (grows with every run)
The app reads everything straight from GitHub (raw.githubusercontent.com, `data` branch) — the repo is the backend.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import competition_policy
import recommendation_policy as rec_policy
import sheet_model
import lineup_pilot
from mr2odds import daily_accumulator

log = logging.getLogger("scanner")

VERSION = 3
KEEP_DETAIL_DAYS = 14


def _f(x, nd=3):
    """float or None (NaN-safe), rounded."""
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)) or (isinstance(x, str) and x == ""):
            return None
        v = float(x)
        return None if math.isnan(v) else round(v, nd)
    except (TypeError, ValueError):
        return None


def _price(x):
    """Exact quoted decimal price or None; never round up into the eligibility band."""
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def fixture_id(date: str, country: str, home: str, away: str) -> str:
    return f"{date}|{country}|{home}|{away}"


def detail_key(fid: str) -> str:
    return hashlib.sha1(fid.encode("utf-8")).hexdigest()[:12]


def _lines(d: dict | None) -> dict | None:
    if not d:
        return None
    return {str(k): [_price(v[0]), _price(v[1])] if isinstance(v, (tuple, list)) else _price(v) for k, v in d.items()}


def _sb(sb: dict | None) -> dict | None:
    if not sb:
        return None
    out = {}
    if sb.get("1X2"):
        out["1X2"] = [_price(x) for x in sb["1X2"]]
    if sb.get("DC"):
        out["DC"] = {k: _price(v) for k, v in sb["DC"].items()}
    if sb.get("BTTS"):
        out["BTTS"] = [_price(x) for x in sb["BTTS"]]
    for k in ("OU", "TGH", "TGA", "CORN", "CORNH", "CORNA", "CORN1H", "CARDS", "CARDSH", "CARDSA"):
        if sb.get(k):
            out[k] = _lines(sb[k])
    return out


def _count(exp, probs: dict | None) -> dict | None:
    if exp is None:
        return None
    import quality
    n_min = min(int(getattr(exp, "h_n", 0) or 0), int(getattr(exp, "a_n", 0) or 0))
    return {"home": _f(exp.eh, 2), "away": _f(exp.ea, 2), "total": _f(exp.eh + exp.ea, 2),
            "n": [int(getattr(exp, "h_n", 0) or 0), int(getattr(exp, "a_n", 0) or 0)],
            "evidence": quality.evidence_label(n_min), "low_confidence": n_min < 10,
            "p": {side: {str(k): _f(v, 3) for k, v in d.items()} for side, d in (probs or {}).items()}}


def _date(d) -> str:
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)


def _matches(lst) -> list[dict]:
    return [{"date": _date(m["date"]), "venue": m["venue"], "opp": m["opp"], "gf": m["gf"], "ga": m["ga"],
             "league": m.get("league")} for m in (lst or [])]


def _profile(t) -> dict:
    return {"name": t.name, "n": int(t.n), "n_eff": _f(t.n_eff, 1), "venue_n": int(t.venue_n), "gf": _f(t.gf, 2), "ga": _f(t.ga, 2),
            "venue_gf": _f(t.venue_gf, 2), "venue_ga": _f(t.venue_ga, 2), "att": _f(t.att, 2), "def": _f(t.dfc, 2),
            "o15": _f(t.rate_o15), "o25": _f(t.rate_o25), "o35": _f(t.rate_o35), "btts": _f(t.rate_btts),
            "cs": _f(t.rate_cs), "fts": _f(t.rate_fts), "last_n": int(t.last_n), "last_o15": int(t.last_o15),
            "last_o25": int(t.last_o25), "last_btts": int(t.last_btts), "form5_goals": _f(t.form5_goals, 2),
            "xg_for": _f(t.xg_for, 2), "xg_against": _f(t.xg_against, 2),
            "sot_for": _f(t.sot_for, 2), "sot_against": _f(t.sot_against, 2),
            "venue_o15": _f(getattr(t, "venue_rate_o15", None)), "venue_o25": _f(getattr(t, "venue_rate_o25", None)),
            "venue_btts": _f(getattr(t, "venue_rate_btts", None)),
            "last5": _matches(t.last5), "venue_last5": _matches(getattr(t, "venue_last5", None)),
            "evidence": _label(t.n), "venue_evidence": _label(t.venue_n),
            "friendlies_excluded": int(getattr(t, "friendlies_excluded", 0) or 0)}


def _label(n) -> str:
    import quality
    return quality.evidence_label(n)


def _compact_evidence(ev: dict | None) -> dict | None:
    """Raw match lists in column form (quality.compact_matches) to keep the per-match file small."""
    if not ev:
        return ev
    import quality
    out = {}
    for side, e in ev.items():
        e2 = dict(e)
        e2["matches"] = quality.compact_matches(e.get("matches") or [])
        out[side] = e2
    return out


def update_badges(path: Path, rows: list, ls_map: dict, extra: dict | None = None, src: Path | None = None) -> dict:
    """Persistent {team short name: Livescore image path}; grows with every run, so league tables and
    history pages can show badges for teams that are not in today's fixtures. Reads `src` (the live file) when
    writing to a staging directory."""
    src = src or path
    try:
        badges = json.loads(src.read_text(encoding="utf-8")) if src.exists() else {}
    except (OSError, ValueError):
        badges = {}
    changed = False
    for name, img in (extra or {}).items():
        if img and badges.get(name) != img:
            badges[name] = img
            changed = True
    for r in rows:
        ls = ls_map.get(r.fx.name) or {}
        for side in ("home", "away"):
            img = ls.get(f"{side}_img")
            name = r.fx[side]
            if img and badges.get(name) != img:
                badges[name] = img
                changed = True
    if changed or not path.exists() or src != path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(sorted(badges.items())), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return badges


BOARD_SELS = ("H", "D", "A", "O15", "O25", "BTTS", "CO95", "KO35")


def _board(sels: list[dict]) -> dict:
    """{sel: [p, odds|None]} for the standard board selections (home / away win, O1.5, O2.5, BTTS, corners 9.5, cards 3.5)."""
    out = {}
    for d in sels:
        if d["sel"] in BOARD_SELS and d.get("p") is not None:
            out[d["sel"]] = [round(d["p"], 3), _price(d.get("odds"))]
    return out


def _best(sels: list[dict], groups: tuple | None, min_odds: float, min_p: float) -> list | None:
    """[sel, p, odds] of the most probable priced selection (optionally restricted to groups / safety rules)."""
    best = None
    for d in sels:
        if not d.get("odds") or d["odds"] <= 1 or d.get("p") is None:
            continue
        if (d["odds"] < min_odds or d["p"] < min_p or d["diff"] or not rec_policy.allowed(d["sel"])
                or rec_policy.outlier(d.get("p_model"), d.get("p_sb"), d["odds"])):
            continue
        if groups is not None and d["group"] not in groups:
            continue
        if best is None or (d["p"], d["odds"]) > (best[1], best[2]):
            best = [d["sel"], round(d["p"], 3), round(d["odds"], 2)]
    return best



def _selection_rows(sels: list[dict]) -> list[list]:
    """Compact selections used by both the fixture index and detail files."""
    return [[d["sel"], d["p"], d["p_model"], d["p_sb"], d["odds"],
             1 if d["diff"] else 0, d.get("diff_pp"), d.get("ev")] for d in sels]


def shortlist_payload(index: list[dict], now: datetime) -> dict:
    """Screen today's upcoming published fixtures, without manufacturing missing prices or probabilities."""
    import safe
    today = now.strftime("%Y-%m-%d")
    current = now.strftime("%Y-%m-%d %H:%M")
    candidates, results = [], []
    analysed = screened = 0
    for f in index:
        if f.get("date") != today or f.get("kickoff", "") <= current or not f.get("data_ok"):
            continue
        analysed += 1
        for sel, p, model, market, odds, diff, *rest in f.get("sels", []):
            group = safe.group(sel)
            if not rec_policy.allowed(sel):
                continue
            screened += 1
            bar = 0.55 if sel in ("H", "D", "A", "O25", "BTTS") else 0.65 if group == "corners" else 0.70
            if p is None or not 0 < p < 1 or odds is None or odds <= 1 or diff:
                continue
            # Without a two-way market view, apply the same raw-price outlier check as the app.
            if rec_policy.outlier(model, market, odds):
                continue
            x = {"fixture": f["id"], "home": f["home"], "away": f["away"], "country": f["country"],
                 "league": f["league"], "kickoff": f["kickoff"], "sel": sel, "market": group,
                 "label": safe.label(sel, f["home"], f["away"]), "p": p, "p_sb": market,
                 "odds": odds, "quality": f.get("q") or "N/A", "confidence": "N/A"}
            if group == "result" and p >= 0.60 and 1.20 <= odds <= 3.50:
                results.append(x)
            if p >= bar and rec_policy.PRICE_FLOOR <= odds <= 1.90 and odds * p >= 0.95 and f.get("q") != "Low":
                candidates.append(x)
    def unique(items):
        seen, out = set(), []
        for x in sorted(items, key=lambda x: (-x["p"], -x["odds"], x["fixture"])):
            if x["fixture"] not in seen:
                seen.add(x["fixture"])
                out.append(dict(x, rank=len(out) + 1))
        return out
    primary = unique(candidates)
    return {"primary": primary, "x12": unique(results),
            "counts": {"analysed": analysed, "screened": screened},
            "rules": {"min_odds": rec_policy.PRICE_FLOOR, "max_odds": 1.90}}

def carry_over(prev: dict | None, index: list, bets: list, tracked: set, now: datetime, hours: float = 3.0) -> int:
    """Fixtures of the previous publication that kicked off in the last `hours` and are no longer in the scan window
    are appended unchanged ("frozen"), together with their safest bets and tracked flags; returns how many."""
    if not prev:
        return 0
    now_naive = now.replace(tzinfo=None)
    cur_ids = {f["id"] for f in index}
    prev_tracked = set(prev.get("tracked") or [])
    frozen_ids = set()
    for f in prev.get("fixtures") or []:
        if not competition_policy.allows_record(f):
            continue
        if f.get("id") in cur_ids:
            continue
        try:
            ko = datetime.strptime(str(f.get("kickoff")), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if not (now_naive - timedelta(hours=hours) <= ko <= now_naive + timedelta(minutes=5)):
            continue
        f = dict(f)
        f["frozen"] = True
        index.append(f)
        cur_ids.add(f["id"])
        frozen_ids.add(f["id"])
        if f["id"] in prev_tracked:
            tracked.add(f["id"])
    index.sort(key=lambda f: (f.get("kickoff") or "", f.get("competition") or ""))
    have = {b["id"] for b in bets}
    for b in (prev.get("safe") or {}).get("bets") or []:
        if not rec_policy.allowed(b.get("sel")):
            continue
        if b.get("id") in have or b.get("fixture") not in frozen_ids:
            continue
        bets.append(dict(b, live=True))
        tracked.add(b["fixture"])
    return len(frozen_ids)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    if not path.exists() or path.read_text(encoding="utf-8") != body:
        path.write_text(body, encoding="utf-8")


def export(path: Path, *, ctx: dict, rows: list, all_rows: list | None = None, picks: dict, tracker_summary: dict, notes: list[str], ls_map: dict,
           helpers: dict, reports_dir: Path, tz_label: str, thresholds: dict, backtest: dict, repo: str | None,
           days_index: list | None = None, safe_summary: dict | None = None, botd: list | None = None, botd_groups: list | None = None,
           alerts: list | None = None, coverage: dict | None = None, safe_groups: tuple = (), extra_badges: dict | None = None,
           report_run: bool = True, live_dir: Path | None = None, daily_accumulators: dict | None = None) -> Path:
    render_details, stars, comp = helpers["render_details"], helpers["stars"], helpers["comp"]
    selections = helpers.get("selections") or (lambda r: [])
    now: datetime = ctx["now"]
    sf = ctx.get("safe") or {}
    min_odds, min_p = float(sf.get("min_odds") or 1.3), float(sf.get("min_p") or 0.7)
    app_dir = path.parent                      # where this publication is written (may be a staging directory)
    live_dir = live_dir or app_dir             # where the app currently reads from (previous publication)
    fx_dir = app_dir / "fx"
    tracked = set()
    index = []
    ids_by_key = {}
    quality_by_key: dict = {}
    conf_by_key: dict = {}
    badges = update_badges(app_dir / "badges.json", rows, ls_map, extra_badges, src=live_dir / "badges.json")
    live_eids = []
    value_cands = []   # priced selections with a model-vs-market edge (advisor "biggest edges" card)
    # the fixture-id map must cover every analysed fixture, not just the published window: shortlist picks
    # (and the high-probability list) can point at matches weeks ahead of the app window
    for r in all_rows or []:
        all_fx = r.fx
        all_date = all_fx["date"].strftime("%Y-%m-%d")
        all_key = (all_date, all_fx["country"], all_fx["home"], all_fx["away"])
        ids_by_key.setdefault(all_key, fixture_id(all_date, all_fx["country"], all_fx["home"], all_fx["away"]))
    # the previous publication: matches that have kicked off are carried over unchanged ("frozen") for 3 hours so the
    # app keeps their pre-match analysis, live status, bets and tickets while they are in play
    prev = None
    prev_path = live_dir / path.name
    try:
        prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else None
    except (OSError, ValueError):
        prev = None
    for r in rows:
        fx = r.fx
        date = fx["date"].strftime("%Y-%m-%d")
        fid = fixture_id(date, fx["country"], fx["home"], fx["away"])
        key = detail_key(fid)
        ids_by_key[(date, fx["country"], fx["home"], fx["away"])] = fid
        _q = ((r.audit or {}).get("quality") or {})
        quality_by_key[(date, fx["country"], fx["home"], fx["away"])] = _q.get("overall")
        _c = ((r.audit or {}).get("confidence") or {})
        conf_by_key[(date, fx["country"], fx["home"], fx["away"])] = _c.get("O15")
        ls = ls_map.get(fx.name)
        x12 = r.extra.x12 or {}
        sels = selections(r)
        top = _best(sels, None, rec_policy.PRICE_FLOOR, 0.0)
        hi = sorted([[d["sel"], round(d["p"], 3), round(d["odds"], 2) if d.get("odds") else None] for d in sels
                     if d.get("p") is not None and d["p"] >= 0.70 and not d["diff"] and rec_policy.allowed(d["sel"])
                     and d.get("odds") and d["odds"] >= rec_policy.PRICE_FLOOR
                     and not rec_policy.outlier(d.get("p_model"), d.get("p_sb"), d["odds"])], key=lambda x: -x[1])[:12]
        for d in sels:   # biggest model-vs-market edges (already-computed EV, presentation only)
            if fx["date"].strftime("%Y-%m-%d") == now.strftime("%Y-%m-%d") and r.data_ok and rec_policy.allowed(d["sel"]) and d.get("odds") and d["odds"] >= rec_policy.PRICE_FLOOR and not rec_policy.outlier(d.get("p_model"), d.get("p_sb"), d["odds"]) and d.get("ev") is not None and d["ev"] > 0 and d["p"] is not None and not d.get("diff"):
                value_cands.append({"id": fid, "sel": d["sel"], "odds": round(d["odds"], 2),
                                    "ev": round(d["ev"], 3), "p": round(d["p"], 3)})
        safe_best = _best(sels, safe_groups or None, min_odds, min_p) if r.data_ok else None
        eid = (ls or {}).get("eid")
        slim = {
            "id": fid, "d": key, "date": date, "kickoff": fx["kickoff"].strftime("%Y-%m-%d %H:%M"),
            "time_known": bool(fx.get("time_known", True)),
            "country": fx["country"], "league": fx["league"], "div": fx["div"], "competition": comp(r),
            "home": fx["home"], "away": fx["away"], "tier": fx.get("source") or "main",
            "data_ok": bool(r.data_ok), "basis": r.basis,
            "xg": [_f(r.mod_h, 2), _f(r.mod_a, 2)],
            "mxg": None if math.isnan(r.mkt_h) else [_f(r.mkt_h, 2), _f(r.mkt_a, 2)],
            "q": (((r.audit or {}).get("quality") or {}).get("overall")),
            "n": [int(r.home.n), int(r.away.n)],
            "p": {"O15": _f(r.p_final["O15"]), "O25": _f(r.p_final["O25"]), "BTTS": _f(r.p_final["BTTS"])},
            "x12": [_f(x12.get("H")), _f(x12.get("D")), _f(x12.get("A"))],
            "priced": bool(r.sb), "top": top, "safe": safe_best, "hi": hi, "bo": _board(sels),
            "sels": _selection_rows(sels),
            "badges": {"home": badges.get(fx["home"]), "away": badges.get(fx["away"])},
            "livescore_id": eid,
            # full Sportybet event meta so the app can deep-link the match into Sportybet ("open in Sportybet")
            "sportybet_event": ({"id": r.sb_event["id"], "country": r.sb_event.get("country"),
                                  "tournament": r.sb_event.get("tournament"), "home": r.sb_event.get("home"),
                                  "away": r.sb_event.get("away")} if r.sb_event else None),
        }
        index.append(slim)
        detail = dict(slim)
        detail.update({
            # Exact probabilities from the same Dixon–Coles matrix, not prices or picks.
            "scores": [[int(h), int(a), _f(p, 6)] for h, a, p in getattr(r, "scores", [])],
            "home_long": (r.sb_event or {}).get("home") or (ls or {}).get("home") or fx["home"],
            "away_long": (r.sb_event or {}).get("away") or (ls or {}).get("away") or fx["away"],
            "referee": (fx.get("referee") or None) or None,
            # xg.home/away/total = the football-data MODEL (kept under the old keys for older app builds);
            # market_* = market-implied expected goals, a separate comparison layer, never blended in
            "xg": {"home": _f(r.mod_h, 2), "away": _f(r.mod_a, 2), "total": _f(r.mod_h + r.mod_a, 2),
                   "model_home": _f(r.mod_h, 2), "model_away": _f(r.mod_a, 2), "model_total": _f(r.mod_h + r.mod_a, 2),
                   "market_home": _f(r.mkt_h, 2), "market_away": _f(r.mkt_a, 2),
                   "market_total": None if math.isnan(r.mkt_h) else _f(r.mkt_h + r.mkt_a, 2),
                   "market_source": r.mkt_source or None},
            "p": {"O15": _f(r.p_model["O15"]), "O25": _f(r.p_model["O25"]), "O35": _f(r.p_model["O35"]),
                  "BTTS": _f(r.p_model["BTTS"]), "model_O25": _f(r.p_model["O25"]), "model_BTTS": _f(r.p_model["BTTS"]),
                  "market_O25": _f((r.fair or {}).get("O25", r.p_market_o25)), "market_O15": _f((r.fair or {}).get("O15")),
                  "market_BTTS": _f((r.fair or {}).get("BTTS"))},
            "x12_market": ({k: _f(v) for k, v in r.x12_market.items() if k in ("H", "D", "A")} | {"source": r.x12_market.get("source")})
            if r.x12_market else None,
            "stars": {m: stars(r.p_final[m], m) for m in ("O15", "O25", "BTTS")},
            "x12": {k: _f(v) for k, v in x12.items() if k in ("H", "D", "A", "1X", "12", "X2")} | (
                {"source": x12.get("source")} if x12.get("source") else {}),
            "team_goals": {k: _f(v) for k, v in (r.extra.tg or {}).items()},
            "corners": _count(r.extra.corners, r.extra.corner_p),
            "cards": _count(r.extra.cards, r.extra.card_p),
            "odds": {"home": _price(fx.get("odds_h")), "draw": _price(fx.get("odds_d")), "away": _price(fx.get("odds_a")),
                     "over25": _price(fx.get("odds_over")), "under25": _price(fx.get("odds_under")),
                     "bfe_over25": _price(fx.get("bfe_over")), "bfe_under25": _price(fx.get("bfe_under"))},
            "sportybet": _sb(r.sb_full or r.sb),
            "teams": {"home": _profile(r.home), "away": _profile(r.away)},
            "sheet_model": sheet_model.for_match(r, comp(r)),
            "lineup_context": lineup_pilot.context(fx, ctx.get("lineup_as_of", now), ctx.get("lineup_archive") or []),
            "league_avg": {"home_goals": _f(r.div_avg.mu_h, 2), "away_goals": _f(r.div_avg.mu_a, 2),
                           "o25": _f(r.div_avg.o25_rate)},
            "h2h": [{"date": _date(m["date"]), "home": m["home"], "away": m["away"], "hg": int(m["hg"]), "ag": int(m["ag"]),
                     "league": m.get("league")} for m in r.h2h[:10]],
            "league_ctx": {"btts": _f(getattr(r.div_avg, "btts_rate", None))},
            # sels: [sel, p (model), p_model, p_market (implied), odds, disagreement flag, diff pp, EV]
            "sels": _selection_rows(sels),
            "trends": r.trends or {},
            # per-fixture news (home / away / the fixture itself). Context only — never a model input.
            "news": getattr(r, "news", None) or None,
            "squad": getattr(r, "squad", None) or None,
            # ---- data-first engine: evidence, quality, explanation, warnings (quality.py)
            "quality": (r.audit or {}).get("quality"),
            "confidence": (r.audit or {}).get("confidence"),
            "evidence": _compact_evidence((r.audit or {}).get("evidence")),
            "h2h_meta": (r.audit or {}).get("h2h"),
            "explain": (r.audit or {}).get("explain"),
            "market": (r.audit or {}).get("market"),
            "warnings": (r.audit or {}).get("warnings"),
            "generated": now.strftime("%Y-%m-%d %H:%M"),
        })
        _write(fx_dir / f"{key}.json", detail)
    # prune detail files of fixtures older than a few days (day pages keep their own summary)
    # (old detail files are pruned by scanner.promote_publication using the match date inside each file)
    # shortlists
    picks_out = {}
    for mkt, lst in picks.items():
        picks_out[mkt] = []
        for r in lst:
            fx = r.fx
            _key = (fx["date"].strftime("%Y-%m-%d"), fx["country"], fx["home"], fx["away"])
            fid = ids_by_key.get(_key) or fixture_id(*_key)   # fall back to the deterministic id if the map missed it
            tracked.add(fid)
            picks_out[mkt].append({"fixture": fid, "p": _f(r.p_final[mkt]), "stars": stars(r.p_final[mkt], mkt),
                                   "sportybet": _price(helpers["sb_price"](r, mkt))})
    # safest bets of this run + bets of the day
    safe_out = {"min_odds": sf.get("min_odds"), "min_p": sf.get("min_p"), "groups": list(safe_groups),
                "bets": [], "today": {"date": now.strftime("%Y-%m-%d"), "bets": []}, "summary": safe_summary or {}}
    for b in sf.get("bets") or []:
        fid = ids_by_key.get(b.key) or fixture_id(*b.key)
        tracked.add(fid)
        safe_out["bets"].append({"id": f"{b.key[0]}|{b.home}|{b.away}|{b.sel}", "fixture": fid, "home": b.home, "away": b.away,
                                 "kickoff": b.kickoff, "league": b.league, "country": b.key[1],
                                 "sel": b.sel, "group": b.group, "label": b.label, "p": _f(b.p), "p_model": _f(b.p_model),
                                 "p_sb": _f(b.p_sb), "odds": _price(b.odds), "fair": _f(1 / b.p, 2) if b.p else None,
                                 "q": quality_by_key.get(b.key), "conf": conf_by_key.get(b.key),
                                 "badges": {"home": badges.get(b.home), "away": badges.get(b.away)}})
    for b in botd or []:
        fid = ids_by_key.get((b["kickoff"][:10], b["country"], b["home"], b["away"])) or \
            fixture_id(b["kickoff"][:10], b["country"], b["home"], b["away"])
        tracked.add(fid)
        bkey = (b["kickoff"][:10], b["country"], b["home"], b["away"])
        safe_out["today"]["bets"].append({**b, "fixture": fid, "q": quality_by_key.get(bkey), "conf": conf_by_key.get(bkey),
                                          "badges": {"home": badges.get(b["home"]), "away": badges.get(b["away"])}})
    frozen = carry_over(prev, index, safe_out["bets"], tracked, now)
    if frozen:
        log.info("App data: %d started fixture(s) carried over from the previous publication", frozen)
    by_bet_id = {b["id"]: b for b in safe_out["today"]["bets"]}
    safe_out["today"]["groups"] = [{"key": g["key"], "title": g["title"], "min_p": g.get("min_p"),
                                    "bets": [by_bet_id[b["id"]] for b in g["bets"] if b["id"] in by_bet_id]} for g in (botd_groups or [])]
    for f in index:
        if f["id"] in tracked and f.get("livescore_id"):
            live_eids.append(f["livescore_id"])

    tracker_out = {m: {k: (_f(v) if isinstance(v, float) else v) for k, v in info.items()}
                   for m, info in (tracker_summary or {}).items()
                   if isinstance(info, dict) and "settled" in info and m in ("O15", "O25", "BTTS")}
    reports = sorted({p.stem for p in reports_dir.glob("20??-??-??.md")}, reverse=True)[:60]
    meta = {
        "generated": now.strftime("%Y-%m-%d %H:%M"), "tz": tz_label, "run": ctx["run"], "report_run": bool(report_run),
        "window_start": (ctx.get("app_start") or ctx["start"]).strftime("%Y-%m-%d %H:%M"),
        "window_end": (ctx.get("app_end") or ctx["end"]).strftime("%Y-%m-%d %H:%M"),
        "fixtures": len(rows), "notes": notes, "repo": repo,
        "report_md": f"reports/{now:%Y-%m-%d}.md", "csv": f"reports/{now:%Y-%m-%d}.csv",
        "thresholds": {m: t["p"] for m, t in thresholds.items()}, "backtest": backtest,
        "next_run": ctx["window_end"].strftime("%Y-%m-%d %H:%M"), "refresh_minutes": 30,
        "coverage": coverage or {}, "model_signals": ctx.get("model_signals"),
    }
    # ---- blocks for the Mr 2 Odds web layer: advisor live record, shortlist report card, value/strong groups.
    # Pure presentation of what the tracker and picks already contain — no new model maths.
    def _nanfree(x):
        return None if (x is None or (isinstance(x, float) and math.isnan(x))) else _f(x)

    _ov = tracker_summary.get("overall") or {}
    _SELBLBL = {"O15": "Over 1.5 goals", "O25": "Over 2.5 goals", "BTTS": "Both teams to score"}
    advisor = {
        "hit_rate": _nanfree(_ov.get("hit_rate")), "settled": _ov.get("settled", 0),
        "wins": _ov.get("wins", 0), "losses": _ov.get("losses", 0),
        "pending": _ov.get("pending", 0), "void": _ov.get("void", 0),
        "roi": _nanfree(_ov.get("roi")), "profit_units": _f(_ov.get("profit_units") or 0.0, 2),
        "since": _ov.get("first_date") or None,
        "markets": {m: {"wins": i.get("hits", 0), "losses": i["settled"] - i.get("hits", 0),
                        "hit_rate": _nanfree(i.get("rate")), "roi": _nanfree(i.get("roi"))}
                    for m, i in tracker_summary.items()
                    if isinstance(i, dict) and "settled" in i and m in ("O15", "O25", "BTTS")},
        "recent": [{"home": x["home"], "away": x["away"], "sel": x["market"],
                    "label": _SELBLBL.get(x["market"], x["market"]), "odds": x["odds"],
                    "match_date": x["match_date"], "status": x["status"], "score": x.get("score")}
                   for x in (tracker_summary.get("recent") or [])],
    }
    advisor_picks, shown_today = [], []
    for _mkt, _lst in picks.items():
        for _r in _lst:
            if _r.fx["date"].strftime("%Y-%m-%d") != now.strftime("%Y-%m-%d"):
                continue
            _sp = helpers["sb_price"](_r, _mkt)
            advisor_picks.append({"home": _r.fx["home"], "away": _r.fx["away"], "sel": _mkt,
                                  "p": _f(_r.p_final[_mkt]), "odds": _f(_sp, 2),
                                  "kickoff": _r.fx["kickoff"].strftime("%Y-%m-%d %H:%M")})
            if _r.fx["kickoff"] <= now:
                shown_today.append({"home": _r.fx["home"], "away": _r.fx["away"]})
    advisor["picks"] = advisor_picks
    advisor["shown_today"] = shown_today

    shortlist = shortlist_payload(index, now)
    # Use the exact same shortlist and indexed SportyBet prices as Final Picks.
    # Build inside staging so an incomplete run cannot publish accumulator data.
    daily_accumulators = daily_accumulator.daily_selection(index, shortlist, now, fx_dir)
    # The existing tracker records global goals picks, not these screened selections.
    # Do not present its historical classes as this shortlist's performance.
    shortlist["track"] = {}
    shortlist["rules"]["calibration"] = {"status": "raw model", "groups": {}}

    # strong signals (>=70% already filtered upstream) with the fixture's data-quality label
    strong_cands = [(s[1], s[0], f["id"], f.get("q"))
                    for f in index if f.get("date") == now.strftime("%Y-%m-%d") and f.get("data_ok")
                    for s in f.get("sels", []) if s[1] is not None and s[1] >= .70 and s[4] is not None
                    and s[4] >= 1.16 and not s[5]
                    and rec_policy.allowed(s[0]) and not rec_policy.outlier(s[2], s[3], s[4])]
    strong_sorted = sorted(strong_cands, key=lambda x: -x[0])[:5]
    groups = {"value": sorted(value_cands, key=lambda x: -x["ev"])[:5],
              "strong": [{"id": fid, "sel": sel, "p": p, "q": q} for p, sel, fid, q in strong_sorted]}

    # ---- strong markets for the day (home section): the model's high-probability Over 1.5 total
    # goals and total corners that carry a real Sportybet price. One row per market, per family caps
    # so one family cannot fill the section. (Presentation of already-published probabilities/prices.)
    STRONG_MIN_P, STRONG_MIN_ODDS = 0.78, 1.16
    STRONG_CAPS = {"o15": 10, "corner_total": 8}
    strong_by_fam: dict = {}
    for r in rows:
        fx = r.fx
        if not r.data_ok or fx["date"].strftime("%Y-%m-%d") != now.strftime("%Y-%m-%d"):
            continue
        fid = fixture_id(fx["date"].strftime("%Y-%m-%d"), fx["country"], fx["home"], fx["away"])
        for d in selections(r):
            sel = d["sel"]
            family = "o15" if sel == "O15" else ("corner_total" if sel.startswith("CO") else None)
            if family is None:
                continue
            if d["p"] is None or d["p"] < STRONG_MIN_P or d.get("diff"):
                continue
            if not d.get("odds") or d["odds"] < STRONG_MIN_ODDS or rec_policy.outlier(d.get("p_model"), d.get("p_sb"), d["odds"]):
                continue
            strong_by_fam.setdefault(family, []).append(
                {"id": fid, "sel": sel, "label": d.get("label"), "family": family,
                 "kickoff": fx["kickoff"].strftime("%Y-%m-%d %H:%M"), "country": fx["country"],
                 "home": fx["home"], "away": fx["away"], "odds": d["odds"], "p": d["p"]})
    strong_bets = [b for fam in ("o15", "corner_total") for b in sorted(strong_by_fam.get(fam, []),
                 key=lambda x: -x["p"])[:STRONG_CAPS[fam]]]
    strong_markets = {"bets": sorted(strong_bets, key=lambda x: -x["p"]),
                      "min_p": STRONG_MIN_P, "min_odds": STRONG_MIN_ODDS}

    # safe.botd = the bets-of-the-day settlement record (performance page reads it at the top level)
    safe_out["botd"] = (safe_summary or {}).get("botd") or {}
    data = {
        "version": VERSION, "meta": meta,
        "fixtures": index, "picks": picks_out, "safe": safe_out, "tracker": tracker_out,
        "advisor": advisor, "shortlist": shortlist, "groups": groups,
        "strong_markets": strong_markets,
        "daily_accumulators": daily_accumulators,
        "tracked": sorted(tracked), "history": {"reports": reports, "days": days_index or []},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    # heartbeat + alerts for the background checker
    alerts = alerts or []
    _write(app_dir / "alerts.json", alerts[-50:])
    app_meta = {
        "version": VERSION, "generated": meta["generated"], "run": meta["run"], "report_run": bool(report_run),
        "next_run": meta["next_run"], "fixtures": len(rows), "safe_bets": len(safe_out["bets"]),
        "botd": [b["id"] for b in safe_out["today"]["bets"]],
        "alerts": [a["id"] for a in alerts[-30:]], "tracked_eids": sorted(set(live_eids)),
    }
    if ctx.get("model_signals") is not None:
        app_meta["model_signals"] = ctx["model_signals"]
    if ctx.get("analysis_cache"):
        app_meta["analysis_cache"] = ctx["analysis_cache"]
    if report_run:
        # Count the actual upcoming shortlist, not the unrelated global goals tracker picks.
        # Refresh runs omit it so the worker does not re-announce an unchanged shortlist.
        app_meta["counts_shortlist"] = {"primary": len(shortlist["primary"])}
    _write(app_dir / "meta.json", app_meta)
    return path
