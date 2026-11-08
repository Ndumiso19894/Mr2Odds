"""Plain-language trends for a fixture: team trends (overall + at this venue), combined match trends and
head-to-head trends. Built from the same results pool the model uses (goals everywhere; half-time, corners and
cards where the feed publishes them). Each trend: {"t": text, "k": hits, "n": sample, "r": rate, "kind": ..., "side": ...}.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

N_RECENT = 10          # "last 10" window for rate trends
N_VENUE = 8            # last 8 home/away games for venue trends
MIN_N = 5
MIN_VENUE_N = 4
MAX_TEAM = 6
MAX_VENUE = 3
MAX_MATCH = 4
MAX_H2H = 3


def _long(results: pd.DataFrame) -> pd.DataFrame:
    """One row per team per match, newest first, with the count columns the trends need."""
    if results is None or results.empty:
        return pd.DataFrame()
    r = results
    get = lambda c: r[c] if c in r.columns else pd.Series(np.nan, index=r.index)
    hy, ay, hr, ar = get("hy"), get("ay"), get("hr"), get("ar")
    # Incomplete or conflicting card components are unknown, not zero.
    hk = hy + hr
    ak = ay + ar
    hth, hta = get("hth"), get("hta")
    hid, aid = get("home_id"), get("away_id")
    base = {"country": r["country"], "date": r["date"], "league": r["league"]}
    h = pd.DataFrame({**base, "team": r["home"], "opp": r["away"], "tid": hid, "venue": "H", "gf": r["hg"], "ga": r["ag"],
                      "htf": hth, "hta_": hta, "cf": get("hc"), "ca": get("ac"), "kf": hk, "ka": ak})
    a = pd.DataFrame({**base, "team": r["away"], "opp": r["home"], "tid": aid, "venue": "A", "gf": r["ag"], "ga": r["hg"],
                      "htf": hta, "hta_": hth, "cf": get("ac"), "ca": get("hc"), "kf": ak, "ka": hk})
    lg = pd.concat([h, a], ignore_index=True)
    lg["total"] = lg["gf"] + lg["ga"]
    lg["ht_total"] = lg["htf"] + lg["hta_"]
    lg["corners"] = lg["cf"] + lg["ca"]
    lg["cards"] = lg["kf"] + lg["ka"]
    lg["res"] = np.where(lg["gf"] > lg["ga"], "W", np.where(lg["gf"] < lg["ga"], "L", "D"))
    return lg.sort_values("date", ascending=False).reset_index(drop=True)


TEAM_ROWS_CACHE: dict = {}   # (id(lg), country, team, team_id) -> slice; cleared by the scanner each run


def clear_caches() -> None:
    TEAM_ROWS_CACHE.clear()


def team_rows(lg: pd.DataFrame, country: str, team: str, team_id: str | None = None) -> pd.DataFrame:
    key = (id(lg), country, team, team_id)
    hit = TEAM_ROWS_CACHE.get(key)
    if hit is not None:
        return hit
    if lg.empty:
        return lg
    if team_id and isinstance(team_id, str) and team_id.strip():
        m = lg[lg["tid"] == team_id]
        if not m.empty:
            TEAM_ROWS_CACHE[key] = m
            return m
    out = lg[(lg["country"] == country) & (lg["team"] == team)]
    TEAM_ROWS_CACHE[key] = out
    return out


# ----------------------------------------------------------------------------- rules
# (key, kind, column expression, threshold, positive text, negative text, negative threshold)
def _rules(name: str):
    return [
        ("o15", "goals", lambda d: d["total"] >= 2, 0.8, "Over 1.5 goals in {k} of {n}", None, None),
        ("o25", "goals", lambda d: d["total"] >= 3, 0.7, "Over 2.5 goals in {k} of {n}", "Under 2.5 goals in {k2} of {n}", 0.7),
        ("o35", "goals", lambda d: d["total"] >= 4, 0.6, "Over 3.5 goals in {k} of {n}", None, None),
        ("btts", "goals", lambda d: (d["gf"] > 0) & (d["ga"] > 0), 0.7, "Both teams scored in {k} of {n}", "One side failed to score in {k2} of {n}", 0.7),
        ("scored", "goals", lambda d: d["gf"] > 0, 0.9, f"{name} scored in {{k}} of {{n}}", f"{name} failed to score in {{m}} of {{n}}", 0.4),
        ("conceded", "goals", lambda d: d["ga"] > 0, 0.9, f"{name} conceded in {{k}} of {{n}}", f"{name} kept a clean sheet in {{m}} of {{n}}", 0.5),
        ("two_plus", "goals", lambda d: d["gf"] >= 2, 0.6, f"{name} scored 2+ in {{k}} of {{n}}", None, None),
        ("ht_goal", "ht", lambda d: d["ht_total"] >= 1, 0.8, "A goal before half-time in {k} of {n}", "Goalless at half-time in {m} of {n}", 0.5),
        ("c95", "corners", lambda d: d["corners"] >= 10, 0.7, "Over 9.5 corners in {k} of {n}", "Under 9.5 corners in {k2} of {n}", 0.7),
        ("c105", "corners", lambda d: d["corners"] >= 11, 0.6, "Over 10.5 corners in {k} of {n}", None, None),
        ("cteam", "corners", lambda d: d["cf"] >= 5, 0.75, f"{name} won 5+ corners in {{k}} of {{n}}", None, None),
        ("k35", "cards", lambda d: d["cards"] >= 4, 0.7, "Over 3.5 cards in {k} of {n}", "Under 3.5 cards in {k2} of {n}", 0.7),
        ("k45", "cards", lambda d: d["cards"] >= 5, 0.6, "Over 4.5 cards in {k} of {n}", None, None),
        ("kteam", "cards", lambda d: d["kf"] >= 2, 0.75, f"{name} shown 2+ cards in {{k}} of {{n}}", None, None),
    ]


def _streak(res: pd.Series, allowed: set[str]) -> int:
    n = 0
    for v in res:
        if v in allowed:
            n += 1
        else:
            break
    return n


def _eval(rows: pd.DataFrame, name: str, side: str, venue: bool, n_max: int, min_n: int, limit: int) -> list[dict]:
    out = []
    if rows.empty:
        return out
    suffix = (" home games" if rows["venue"].iloc[0] == "H" else " away games") if venue else ""
    for key, kind, fn, thr, pos_txt, neg_txt, neg_thr in _rules(name):
        col = fn(rows)
        # only matches where the underlying stat is known
        known = rows["total"].notna() if kind == "goals" else (
            rows["ht_total"].notna() if kind == "ht" else rows["corners"].notna() if kind == "corners" else rows["cards"].notna())
        d = col[known].head(n_max)
        n = int(len(d))
        if n < min_n:
            continue
        k = int(d.sum())
        rate = k / n
        if rate >= thr:
            strength = (rate - thr) / (1 - thr + 1e-9) + 0.02 * n
            out.append({"t": pos_txt.format(k=k, n=n) + suffix, "k": k, "n": n, "r": round(rate, 2), "kind": kind,
                        "side": side, "s": round(strength, 3)})
        elif neg_txt and (1 - rate) >= neg_thr:
            m = n - k
            strength = ((1 - rate) - neg_thr) / (1 - neg_thr + 1e-9) + 0.02 * n
            out.append({"t": neg_txt.format(k=k, m=m, k2=m, n=n) + suffix, "k": m, "n": n, "r": round(1 - rate, 2),
                        "kind": kind, "side": side, "s": round(strength, 3)})
    # result streaks (overall only)
    if not venue and len(rows) >= 3:
        res = rows["res"].head(N_RECENT)
        for allowed, txt, min_len in (({"W"}, "{name} won the last {s}", 3), ({"W", "D"}, "{name} unbeaten in the last {s}", 4),
                                      ({"L"}, "{name} lost the last {s}", 3), ({"L", "D"}, "{name} without a win in the last {s}", 4)):
            s = _streak(res, allowed)
            if s >= min_len:
                out.append({"t": txt.format(name=name, s=s), "k": s, "n": s, "r": 1.0, "kind": "form", "side": side,
                            "s": round(0.5 + 0.1 * s, 3)})
                break
        scored = _streak((rows["gf"] > 0).map({True: "Y", False: "N"}).head(20), {"Y"})
        if scored >= 6:
            out.append({"t": f"{name} scored in {scored} consecutive matches", "k": scored, "n": scored, "r": 1.0,
                        "kind": "goals", "side": side, "s": round(0.6 + 0.05 * scored, 3)})
    out.sort(key=lambda x: -x["s"])
    seen, dedup = set(), []
    for x in out:
        if x["t"] in seen:
            continue
        seen.add(x["t"])
        dedup.append(x)
    return dedup[:limit]


def _short(name: str) -> str:
    return name if len(name) <= 18 else name[:17].rstrip() + "…"


def team_trends(lg: pd.DataFrame, country: str, team: str, venue: str, team_id: str | None = None) -> dict:
    rows = team_rows(lg, country, team, team_id)
    name = _short(team)
    overall = _eval(rows, name, venue, False, N_RECENT, MIN_N, MAX_TEAM)
    at_venue = _eval(rows[rows["venue"] == venue], name, venue, True, N_VENUE, MIN_VENUE_N, MAX_VENUE)
    return {"all": overall, "venue": at_venue, "n": int(min(len(rows), N_RECENT))}


def match_trends(lg: pd.DataFrame, country: str, home: str, away: str, home_id=None, away_id=None) -> list[dict]:
    """Statements that hold for both teams' recent matches together (last 10 each)."""
    h = team_rows(lg, country, home, home_id).head(N_RECENT)
    a = team_rows(lg, country, away, away_id).head(N_RECENT)
    if len(h) < MIN_N or len(a) < MIN_N:
        return []
    both = pd.concat([h, a], ignore_index=True)
    out = []
    checks = [
        ("goals", lambda d: d["total"] >= 3, 0.65, "Over 2.5 goals in {k} of the teams' last {n} matches"),
        ("goals", lambda d: d["total"] >= 2, 0.85, "Over 1.5 goals in {k} of the teams' last {n} matches"),
        ("goals", lambda d: (d["gf"] > 0) & (d["ga"] > 0), 0.65, "Both teams scored in {k} of the teams' last {n} matches"),
        ("goals", lambda d: d["total"] <= 2, 0.65, "Under 2.5 goals in {k} of the teams' last {n} matches"),
        ("ht", lambda d: d["ht_total"] >= 1, 0.8, "A first-half goal in {k} of the teams' last {n} matches"),
        ("corners", lambda d: d["corners"] >= 10, 0.65, "Over 9.5 corners in {k} of the teams' last {n} matches"),
        ("cards", lambda d: d["cards"] >= 4, 0.65, "Over 3.5 cards in {k} of the teams' last {n} matches"),
    ]
    for kind, fn, thr, txt in checks:
        known = both["total"].notna() if kind == "goals" else (
            both["ht_total"].notna() if kind == "ht" else both["corners"].notna() if kind == "corners" else both["cards"].notna())
        d = fn(both)[known]
        n = int(len(d))
        if n < 2 * MIN_N:
            continue
        k = int(d.sum())
        rate = k / n
        if rate >= thr:
            out.append({"t": txt.format(k=k, n=n), "k": k, "n": n, "r": round(rate, 2), "kind": kind, "side": "M",
                        "s": round((rate - thr) / (1 - thr + 1e-9), 3)})
    avg_h, avg_a = float(h["total"].mean()), float(a["total"].mean())
    if not math.isnan(avg_h) and not math.isnan(avg_a):
        out.append({"t": f"Average goals in recent games: {_short(home)} {avg_h:.1f} · {_short(away)} {avg_a:.1f}", "k": 0,
                    "n": int(len(h) + len(a)), "r": None, "kind": "info", "side": "M", "s": 0.0})
    out.sort(key=lambda x: -x["s"])
    return out[:MAX_MATCH + 1]


def h2h_trends(h2h: list[dict], home: str, away: str) -> list[dict]:
    """h2h: newest-first dicts with home, away, hg, ag (as produced by scanner.head_to_head)."""
    if len(h2h) < 3:
        return []
    n = len(h2h)
    tot = [m["hg"] + m["ag"] for m in h2h]
    out = []
    k = sum(1 for t in tot if t >= 3)
    if k / n >= 0.6:
        out.append({"t": f"Over 2.5 goals in {k} of the last {n} meetings", "k": k, "n": n, "r": round(k / n, 2), "kind": "goals", "side": "H2H", "s": k / n})
    k = sum(1 for t in tot if t <= 2)
    if k / n >= 0.6:
        out.append({"t": f"Under 2.5 goals in {k} of the last {n} meetings", "k": k, "n": n, "r": round(k / n, 2), "kind": "goals", "side": "H2H", "s": k / n})
    k = sum(1 for m in h2h if m["hg"] > 0 and m["ag"] > 0)
    if k / n >= 0.6:
        out.append({"t": f"Both teams scored in {k} of the last {n} meetings", "k": k, "n": n, "r": round(k / n, 2), "kind": "goals", "side": "H2H", "s": k / n})
    wins_h = sum(1 for m in h2h if (m["hg"] > m["ag"]) == (m["home"] == home) and m["hg"] != m["ag"])
    wins_a = sum(1 for m in h2h if (m["hg"] > m["ag"]) == (m["home"] == away) and m["hg"] != m["ag"])
    draws = sum(1 for m in h2h if m["hg"] == m["ag"])
    out.append({"t": f"Last {n} meetings: {_short(home)} {wins_h} · draws {draws} · {_short(away)} {wins_a} · avg {sum(tot) / n:.1f} goals",
                "k": 0, "n": n, "r": None, "kind": "info", "side": "H2H", "s": 0.0})
    return out[:MAX_H2H + 1]


def for_fixture(lg: pd.DataFrame, fx, h2h: list[dict]) -> dict:
    country, home, away = fx["country"], fx["home"], fx["away"]
    hid = fx.get("home_id") if hasattr(fx, "get") else None
    aid = fx.get("away_id") if hasattr(fx, "get") else None
    hid = hid if isinstance(hid, str) and hid else None
    aid = aid if isinstance(aid, str) and aid else None
    return {
        "home": team_trends(lg, country, home, "H", hid),
        "away": team_trends(lg, country, away, "A", aid),
        "match": match_trends(lg, country, home, away, hid, aid),
        "h2h": h2h_trends(h2h, home, away),
    }
