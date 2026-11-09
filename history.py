"""Day-by-day history for the app: data/app/days/YYYY-MM-DD.json (one file per match date).

Each run upserts the fixtures of its window into the files of their match dates, fills in final scores
(football-data results first, Livescore.com for the last few days), attaches every bet that touched the match
(shortlist picks, safest bets, safest trebles, parlays) with its outcome and writes a per-day summary.
latest.json only carries a light index of the days; the app loads a day file on demand."""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import appdata
import livescore
import safe

log = logging.getLogger("history")

KEEP_DAYS = 60
LIVESCORE_BACK_DAYS = 3


def _f(x, nd=3):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def fixture_id(date: str, country: str, home: str, away: str) -> str:
    return f"{date}|{country}|{home}|{away}"


class Days:
    def __init__(self, root: Path, now: datetime):
        self.root = root
        self.now = now
        self.days: dict[str, dict] = {}
        self._loaded: dict[str, str] = {}
        root.mkdir(parents=True, exist_ok=True)
        cutoff = (now - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
        for p in sorted(root.glob("20??-??-??.json")):
            if p.stem < cutoff:
                p.unlink(missing_ok=True)
                continue
            try:
                self.days[p.stem] = json.loads(p.read_text(encoding="utf-8"))
                self._loaded[p.stem] = _dumps({k: v for k, v in self.days[p.stem].items() if k != "updated"})
            except (ValueError, OSError):
                continue

    # ------------------------------------------------------------------ fixtures of this run
    def upsert(self, rows: list, comp, ls_map: dict, sels_of) -> None:
        for r in rows:
            fx = r.fx
            date = fx["date"].strftime("%Y-%m-%d")
            day = self.days.setdefault(date, {"date": date, "fixtures": []})
            fid = fixture_id(date, fx["country"], fx["home"], fx["away"])
            ls = ls_map.get(fx.name) or {}
            x12 = r.extra.x12 or {}
            rec = {
                "id": fid, "d": appdata.detail_key(fid), "kickoff": fx["kickoff"].strftime("%Y-%m-%d %H:%M"), "country": fx["country"],
                "league": fx["league"], "div": fx["div"], "competition": comp(r), "home": fx["home"], "away": fx["away"],
                "home_long": (r.sb_event or {}).get("home") or ls.get("home") or fx["home"],
                "away_long": (r.sb_event or {}).get("away") or ls.get("away") or fx["away"],
                "xg": [_f(r.mod_h, 2), _f(r.mod_a, 2)],           # football-data model xG
                "mxg": None if r.mkt_h != r.mkt_h else [_f(r.mkt_h, 2), _f(r.mkt_a, 2)],   # market xG (comparison only)
                "q": ((r.audit or {}).get("quality") or {}).get("overall"),
                "p": {"O15": _f(r.p_final["O15"]), "O25": _f(r.p_final["O25"]), "BTTS": _f(r.p_final["BTTS"])},
                "x12": [_f(x12.get("H")), _f(x12.get("D")), _f(x12.get("A"))],
                "top": [s for s in sels_of(r)[:3]],
                "data_ok": bool(r.data_ok),
                "h2h_evidence": getattr(r, "h2h_evidence", {}),
            }
            old = next((f for f in day["fixtures"] if f["id"] == fid), None)
            if old:
                rec["livescore_id"] = ls.get("eid") or old.get("livescore_id")
                rec["score"] = old.get("score")
                old.clear()
                old.update(rec)
            else:
                rec["livescore_id"] = ls.get("eid")
                rec["score"] = None
                day["fixtures"].append(rec)

    # ------------------------------------------------------------------ scores
    def fill_scores(self, results: pd.DataFrame, archive=None) -> pd.DataFrame:
        """Fill final scores from results + Livescore (day feed and archive, incl. half-time score and match
        statistics). Returns extra result rows (Livescore) for the settlers."""
        ls_by_eid = {}
        want_days = set()
        today = self.now.date()
        for date, day in self.days.items():
            for f in day["fixtures"]:
                if not f.get("livescore_id"):
                    continue
                score = f.get("score")
                if score and score.get("regulation_confirmed") is not None:
                    continue
                ko = datetime.strptime(f["kickoff"], "%Y-%m-%d %H:%M").date()
                if 0 <= (today - ko).days <= LIVESCORE_BACK_DAYS:
                    want_days.add(ko)
        for d in sorted(want_days):
            try:
                for e in livescore.fetch_day(datetime(d.year, d.month, d.day), int(self.now.utcoffset().total_seconds() // 3600)):
                    ls_by_eid[e["eid"]] = e
            except Exception as exc:  # noqa: BLE001
                log.warning("Livescore day %s failed: %s", d, exc)
        extra = []
        now_naive = self.now.replace(tzinfo=None)
        for date, day in self.days.items():
            for f in day["fixtures"]:
                if f.get("score"):
                    score = f["score"]
                    e = ls_by_eid.get(str(f.get("livescore_id")))
                    if score.get("regulation_confirmed") is None and e and e.get("status") == "FT" and (score.get("hg"),score.get("ag")) == (e.get("hg"),e.get("ag")) and score.get("hg") is not None:
                        score["regulation_confirmed"] = True
                    continue
                ko = datetime.strptime(f["kickoff"], "%Y-%m-%d %H:%M")
                if ko > now_naive - timedelta(hours=1, minutes=45):
                    continue
                row = safe._lookup(results, f["country"], f["home"], f["away"], date)
                if row is not None:
                    f["score"] = {"hg": int(row["hg"]), "ag": int(row["ag"]), "status": "FT", "src": "results",
                                  "hc": _int(row.get("hc")), "ac": _int(row.get("ac")),
                                  "hcards": _int(safe._cards(row, "h")), "acards": _int(safe._cards(row, "a"))}
                    continue
                e = ls_by_eid.get(str(f.get("livescore_id")))
                if e:
                    st = e.get("status", "")
                    if st in ("Postp.", "Canc.", "Aband."):
                        f["score"] = {"hg": None, "ag": None, "status": st, "src": "livescore"}
                    elif e.get("hg") is not None and e.get("ag") is not None and st in ("FT", "AET", "AP", "Awarded"):
                        f["score"] = {"hg": int(e["hg"]), "ag": int(e["ag"]), "status": st, "src": "livescore", "regulation_confirmed": st == "FT"}
                        if st == "FT":
                            extra.append({"country": f["country"], "div": f["div"], "league": f["league"],
                                          "date": pd.Timestamp(date), "home": f["home"], "away": f["away"],
                                          "hg": float(e["hg"]), "ag": float(e["ag"])})
        if archive is not None:
            self._enrich(archive)
        return pd.DataFrame(extra) if extra else pd.DataFrame()

    STAT_KEYS = ("hc", "ac", "hy", "ay", "hr", "ar", "hs", "as", "hst", "ast", "hposs", "aposs", "hf", "af")
    STATS_RETRY_HOURS = 6      # late statistics can arrive after the original three early attempts
    ENRICH_BUDGET_S = 70.0    # Livescore requests per run for the archive (statistics + goal incidents)

    def _apply_stats(self, sc: dict, st: list) -> None:
        vals = (list(st) + [None] * len(self.STAT_KEYS))[:len(self.STAT_KEYS)]
        for k, v in zip(self.STAT_KEYS, vals):
            if v is not None:
                sc[k] = _int(v)
        for side in ("h", "a"):
            yellow, red = _int(sc.get(side + "y")), _int(sc.get(side + "r"))
            if yellow is not None and red is not None:
                sc[side + "cards"] = yellow + red

    def _enrich(self, archive) -> None:
        """Half-time scores, match statistics (corners, cards, shots, possession, fouls) and goal / red-card incidents
        for every finished match of the last days — first from the Livescore archive, then straight from Livescore
        (one statistics call and one incidents call per match, a few probes at most, within a time budget), so the
        archive keeps the live stats of every analysed match, not just the stages playing today."""
        import time
        import worldfeed
        try:
            archive.load_all()
        except Exception:  # noqa: BLE001
            return
        today = self.now.date()
        t0 = time.time()
        n = n_fetch = n_inc = n_empty = 0
        budget_left = lambda: time.time() - t0 < self.ENRICH_BUDGET_S  # noqa: E731
        for date, day in sorted(self.days.items(), reverse=True):      # newest days first
            for f in day["fixtures"]:
                eid = f.get("livescore_id")
                if not eid:
                    continue
                ko = datetime.strptime(f["kickoff"], "%Y-%m-%d %H:%M").date()
                if (today - ko).days > 6:
                    continue
                sc = f.get("score")
                if sc is None:
                    ev = archive.event_for(str(eid))
                    if ev and ev["hg"] is not None:
                        sc = f["score"] = {"hg": int(ev["hg"]), "ag": int(ev["ag"]), "status": "FT", "src": "archive"}
                if not sc or sc.get("hg") is None:
                    continue
                if sc.get("hth") is None:
                    ev = archive.event_for(str(eid))
                    if ev and ev.get("hth") is not None:
                        sc["hth"], sc["hta"] = _int(ev["hth"]), _int(ev["hta"])
                # -- statistics: archive first, then a rate-limited direct probe
                if sc.get("hc") is None or sc.get("ac") is None or sc.get("hs") is None:
                    st = archive.stats_for(str(eid))
                    if st:
                        self._apply_stats(sc, st)
                        n += 1
                    # Existing archives may have exhausted three early probes before
                    # match statistics became available. Recheck missing data at a
                    # bounded interval instead of leaving those matches pending forever.
                    next_probe = sc.get("st_next") or ""
                    try:
                        due = not next_probe or datetime.fromisoformat(next_probe) <= self.now.replace(tzinfo=None)
                    except (ValueError, TypeError):
                        due = True
                    if (sc.get("hc") is None or sc.get("ac") is None or sc.get("hs") is None) and due and budget_left():
                        st = worldfeed.fetch_stats(str(eid))
                        if st is not None:
                            sc["stp"] = sc.get("stp", 0) + 1
                            sc["st_next"] = (self.now.replace(tzinfo=None) + timedelta(hours=self.STATS_RETRY_HOURS)).isoformat()
                            if st:
                                self._apply_stats(sc, st)
                                n += 1
                                n_fetch += 1
                            else:
                                n_empty += 1
                # -- goal / red-card incidents (scorers and minutes), fetched once per finished match
                if "inc" not in sc and sc.get("inp", 0) < 2 and budget_left():
                    try:
                        items = livescore.incidents(str(eid))
                    except Exception:  # noqa: BLE001
                        items = None
                    if items is None:
                        continue
                    sc["inp"] = sc.get("inp", 0) + 1
                    keep = [[it.get("minute"), it["team"], it["type"], (it.get("player") or "")[:40], it.get("score")]
                            for it in items if it["type"] in ("goal", "own_goal", "penalty", "missed_penalty", "red", "second_yellow")]
                    goals_seen = sum(1 for it in keep if it[2] in ("goal", "own_goal", "penalty"))
                    if keep or sc["hg"] + sc["ag"] == 0 or sc["inp"] >= 2:
                        sc["inc"] = keep
                        if keep:
                            n_inc += 1
                    # a scoreline with goals but no incidents yet: probe once more next run
                    if goals_seen == 0 and sc["hg"] + sc["ag"] > 0 and sc["inp"] < 2:
                        sc.pop("inc", None)
        if n or n_inc or n_empty:
            log.info("History: match statistics added to %d fixture(s) (%d fetched directly, %d without stats), "
                     "goal incidents for %d, %.0fs", n, n_fetch, n_empty, n_inc, time.time() - t0)

    # ------------------------------------------------------------------ bets on each fixture
    def annotate(self, tracker: pd.DataFrame, parlays: pd.DataFrame, accas: pd.DataFrame, bets: pd.DataFrame) -> None:
        by_id: dict[str, dict] = {}
        for day in self.days.values():
            day["accas"], day["parlays"] = [], []
            for f in day["fixtures"]:
                f["bets"] = []
                by_id[f["id"]] = f

        def outcome(f, sel):
            sc = f.get("score")
            if not sc or sc.get("hg") is None:
                return "void" if sc and sc.get("status") in ("Postp.", "Canc.", "Aband.") else "pending"
            ok = safe.settle(sel, sc["hg"], sc["ag"], sc.get("hc"), sc.get("ac"), sc.get("hcards"), sc.get("acards"))
            return "pending" if ok is None else ("hit" if ok else "miss")

        if tracker is not None and not tracker.empty:
            for r in tracker.itertuples():
                f = by_id.get(fixture_id(r.match_date, r.country, r.home, r.away))
                if f is None:
                    continue
                st = {"hit": "hit", "miss": "miss", "void": "void"}.get(r.status) or outcome(f, r.market)
                f["bets"].append({"kind": "pick", "sel": r.market, "label": safe.label(r.market), "p": _f(r.p_final),
                                  "odds": _f(r.odds, 2), "status": st})
        if bets is not None and not bets.empty:
            for r in bets.itertuples():
                f = by_id.get(fixture_id(r.match_date, r.country, r.home, r.away))
                if f is None:
                    continue
                st = r.status if r.status in ("hit", "miss", "void") else outcome(f, r.sel)
                botd = str(getattr(r, "botd", "") or "")
                botd = botd if botd and botd != "nan" else ""
                kind = "botd" if str(getattr(r, "kind", "") or "") == "botd" else "safe"
                f["bets"].append({"kind": kind, "sel": r.sel, "label": safe.label(r.sel, f["home"], f["away"]),
                                  "p": _f(r.p), "odds": _f(r.odds, 2), "status": st, "botd": botd or False})

        def add_multi(df, kind, id_col):
            if df is None or df.empty:
                return
            for r in df.itertuples():
                try:
                    legs = json.loads(r.legs)
                except (TypeError, ValueError):
                    continue
                created = str(r.created)[:10]
                legs_out = []
                for l in legs:
                    fid = fixture_id(l.get("date", ""), l.get("country", ""), l.get("home", ""), l.get("away", ""))
                    f = by_id.get(fid)
                    st = outcome(f, l["sel"]) if f is not None else ({"won": "hit", "lost": "miss"}.get(l.get("result")) or "pending")
                    lab = safe.label(l["sel"], l.get("home", "Home"), l.get("away", "Away"))
                    legs_out.append({"fixture": fid, "home": l.get("home"), "away": l.get("away"), "kickoff": l.get("kickoff"),
                                     "sel": l["sel"], "label": lab, "odds": _f(l.get("odds"), 2), "p": _f(l.get("p")),
                                     "status": st, "score": (f or {}).get("score") and f"{f['score']['hg']}-{f['score']['ag']}"
                                     if f and f.get("score") and f["score"].get("hg") is not None else None})
                    if f is not None:
                        f["bets"].append({"kind": kind, "id": getattr(r, id_col), "sel": l["sel"], "label": lab,
                                          "odds": _f(l.get("odds"), 2), "p": _f(l.get("p")), "status": st})
                # file the multi under the day of its first kick-off (what people look up), else its creation day
                leg_dates = sorted(str(l.get("date", ""))[:10] for l in legs if l.get("date"))
                day = self.days.get(leg_dates[0]) if leg_dates else None
                if day is None:
                    day = self.days.get(created)
                if day is not None:
                    day[kind + "s"].append({"id": getattr(r, id_col), "created": r.created, "odds": _f(r.odds, 2),
                                            "p": _f(r.p), "status": r.status, "legs": legs_out})
        add_multi(accas, "acca", "acca_id")
        add_multi(parlays, "parlay", "parlay_id")

    # ------------------------------------------------------------------ summaries / write
    def summarise(self) -> list[dict]:
        index = []
        for date in sorted(self.days, reverse=True):
            day = self.days[date]
            fx = day["fixtures"]
            fin = [f for f in fx if f.get("score") and f["score"].get("hg") is not None]
            goals = [f["score"]["hg"] + f["score"]["ag"] for f in fin]
            s = {"n": len(fx), "finished": len(fin),
                 "goals_avg": round(sum(goals) / len(goals), 2) if goals else None,
                 "o25_rate": round(sum(1 for g in goals if g >= 3) / len(goals), 3) if goals else None,
                 "btts_rate": round(sum(1 for f in fin if f["score"]["hg"] > 0 and f["score"]["ag"] > 0) / len(fin), 3) if fin else None}
            for kind in ("pick", "safe", "botd"):
                if kind == "botd":
                    b = [x for f in fx for x in f.get("bets", []) if x.get("botd")]
                else:
                    b = [x for f in fx for x in f.get("bets", []) if x["kind"] == kind]
                s[kind if kind == "botd" else kind + "s"] = {"n": len(b), "hit": sum(1 for x in b if x["status"] == "hit"),
                                 "miss": sum(1 for x in b if x["status"] == "miss"),
                                 "pending": sum(1 for x in b if x["status"] == "pending")}
            for kind in ("accas", "parlays"):
                lst = day.get(kind, [])
                s[kind] = {"n": len(lst), "won": sum(1 for x in lst if x["status"] == "won"),
                           "lost": sum(1 for x in lst if x["status"] == "lost"),
                           "pending": sum(1 for x in lst if x["status"] == "pending")}
            day["summary"] = s
            index.append({"date": date, **s})
        return index

    def write(self) -> int:
        """Write only the day files whose content changed (keeps the repo history small)."""
        written = 0
        for date, day in self.days.items():
            day["fixtures"].sort(key=lambda f: f["kickoff"])
            body = _dumps({k: v for k, v in day.items() if k != "updated"})
            if self._loaded.get(date) == body and (self.root / f"{date}.json").exists():
                continue
            day["updated"] = self.now.strftime("%Y-%m-%d %H:%M")
            (self.root / f"{date}.json").write_text(_dumps(day), encoding="utf-8")
            written += 1
        return written


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str, sort_keys=True)


def _int(x):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        return int(x)
    except (TypeError, ValueError):
        return None
