#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PlayReport scanner (v4)
==================
Automated football scanner, three times a day (07:00 / 12:00 / 17:00 SAST):
  * goals shortlists  – Over 1.5, Over 2.5, Both Teams To Score (experimental signals unvalidated)
  * extra markets     – 1X2 / double chance, team goals, corners and cards (markets.py, backtested)
  * Sportybet prices  – real prices for the user's bookmaker (sporty.py), value check vs fair price
  * parlays           – 3 per run inside the 2.70-3.50 odds band, built from priced legs only (parlays.py),
                        recorded in data/parlays.csv and auto-graded
  * delivery          – Markdown + CSV in the repo, PDF report + PDF parlay dossier on Telegram

Data source: football-data.co.uk (free, no API key)
  * fixtures.csv / new_league_fixtures.csv -> upcoming matches (+ market odds where published)
  * season result files                    -> team form, goals, xG / shots where available

Outputs (relative to the repo root):
  reports/YYYY-MM-DD.md          full report (latest run of the day; earlier runs are overwritten)
  reports/YYYY-MM-DD-parlays.md  parlay dossier: full stats + headlines for every parlay match
  reports/YYYY-MM-DD.csv         every scanned match with every computed number
  reports/latest.md              copy of the newest report
  reports/pdf/                   PDF versions (not committed; sent to Telegram)
  data/tracker.csv               shortlist picks, auto-settled once results arrive
  data/parlays.csv               parlay ledger, auto-graded
  README.md                      the block between <!-- SCAN:START --> and <!-- SCAN:END --> is refreshed

Optional: a Telegram push if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in the environment.

Everything tunable lives in CONFIG below (most values can also be overridden with env vars).
"""
from __future__ import annotations

import html
import history_integrity
import cross_provider
import io
import json
import logging
import math
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

import markets
import model_signals
import recent_form
import h2h_gate
import h2h_evidence
import quality
import news as news_mod
import parlays as parlay_mod
import sporty
import livescore
import trends as trends_mod
import acache
import squads as squads_mod
import worldfeed
import appdata
import lineup_pilot
import competition_policy
import recommendation_policy as rec_policy
import verify
import safe as safe_mod
import history as history_mod
import teamstats

try:
    import pdfgen
except Exception:  # noqa: BLE001 - reportlab missing: Markdown/Telegram text still work
    pdfgen = None

# ----------------------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent
# machine-written state (ledgers, archives, app data, reports) lives in STATE_DIR — on GitHub that is the `data`
# branch checkout, so the code branch's history never grows with the half-hourly runs
STATE = Path(os.getenv("STATE_DIR") or ROOT).resolve()
REPORTS_DIR = STATE / "reports"
DATA_DIR = STATE / "data"
FX_DIR = DATA_DIR / "app" / "fx"
LS_DIR = DATA_DIR / "ls"
CACHE_DIR = DATA_DIR / "cache"
TRACKER_FILE = DATA_DIR / "tracker.csv"
PARLAY_FILE = DATA_DIR / "parlays.csv"
APP_FILE = DATA_DIR / "app" / "latest.json"
DAYS_DIR = DATA_DIR / "app" / "days"
TEAMS_DIR = DATA_DIR / "app" / "teams"
SAFE_BETS_FILE = DATA_DIR / "safe_bets.csv"
SAFE_ACCAS_FILE = DATA_DIR / "safe_accas.csv"
PDF_DIR = REPORTS_DIR / "pdf"
README_FILE = ROOT / "README.md"

BASE = "https://www.football-data.co.uk"
FIXTURES_URL = f"{BASE}/fixtures.csv"
FEED_TZ = ZoneInfo("Europe/London")  # football-data.co.uk publishes kick-off times in UK time
NEW_FIXTURES_URL = f"{BASE}/new_league_fixtures.csv"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------------------- config
CONFIG = {
    # timezone used for the scan window, all displayed times and report dates
    "TIMEZONE": os.getenv("TIMEZONE", "Africa/Johannesburg"),
    "TZ_LABEL": os.getenv("TZ_LABEL", "SAST"),
    # matches kicking off between "now" and now + WINDOW_HOURS are scanned
    "WINDOW_HOURS": _env_float("WINDOW_HOURS", 24),
    # coverage window: fixtures up to COVER_DAYS out are discovered and analysed in every run, so the
    # model gathers history/stats early and matches are analysed long before kick-off. The app
    # publication still carries only the APP_WINDOW_HOURS window (the Matches tab stays "today").
    "COVER_DAYS": int(_env_float("COVER_DAYS", 60)),
    "APP_WINDOW_HOURS": _env_float("APP_WINDOW_HOURS", 24),
    # per-fixture news is only useful close to kick-off; far-future fixtures get no news fetch
    "NEWS_HOURS": _env_float("NEWS_HOURS", 72),
    # form weighting: a match HALF_LIFE_DAYS ago counts half as much as one played today
    "HALF_LIFE_DAYS": 120,
    "MAX_HISTORY_DAYS": 400,
    "MAX_MATCHES_PER_TEAM": 40,
    # minimum (time-weighted) matches per team before a match may be shortlisted
    "MIN_EFF_MATCHES": 4.0,
    # Bayesian shrinkage of team strengths towards league average (in matches).
    # Backtested 2023-26: K=40 is far better calibrated than small values (goal form is noisy).
    "SHRINK_K": 40.0,
    # how quickly venue-specific (home/away) form takes over from overall form (backtest: matters little)
    "VENUE_K": 20.0,
    # Dixon-Coles low-score correction (fitted on 2023-25 scores)
    "DC_RHO": -0.05,
    # weight of market-implied expected goals when odds exist. Backtest: the market beats the model
    # at every weight below ~0.9, so the model only fine-tunes the market where odds are published.
    "SHRINK_K_STRENGTH": 5.0,   # shrinkage of the attack/defence *ratio* (team strength) — validated 2026-09-28, see backtest/RESULTS.md
    # shortlist rules: final probability >= p; tiers give ⭐⭐ / ⭐⭐⭐ ratings (values from the backtest)
    "THRESHOLDS": {
        "O15": {"p": _env_float("MIN_P_O15", 0.84), "tiers": (0.87, 0.90)},
        "O25": {"p": _env_float("MIN_P_O25", 0.60), "tiers": (0.64, 0.68)},
        "BTTS": {"p": _env_float("MIN_P_BTTS", 0.60), "tiers": (0.63, 0.66)},
    },
    # Historical baseline hit-rates; these do not validate the experimental model.
    "BACKTEST": {
        "O15": "87% of shortlisted matches (⭐⭐ 88%, ⭐⭐⭐ 95%) over 900 picks",
        "O25": "67% of shortlisted matches (⭐⭐ 71%, ⭐⭐⭐ 77%) over 1,675 picks",
        "BTTS": "64% of shortlisted matches (⭐⭐ 65%, ⭐⭐⭐ 71%) over 1,800 picks",
    },
    "MAX_PICKS": int(_env_float("MAX_PICKS", 15)),
    # scheduled run hours (local time). Each run builds parlays for kick-offs before the next run.
    "RUN_HOURS": sorted({int(h) for h in os.getenv("RUN_HOURS", "7,12,17").split(",") if h.strip().isdigit()}) or [7, 12, 17],
    "PARLAYS_PER_RUN": int(_env_float("PARLAYS_PER_RUN", 3)),
    "PARLAY_ODDS": (_env_float("PARLAY_MIN_ODDS", 2.70), _env_float("PARLAY_MAX_ODDS", 3.50)),
    "PARLAY_MIN_MATCHES": 4,          # fewer priced matches before the next run -> use the whole 24 h window
    "SPORTYBET": os.getenv("SPORTYBET", "1") != "0",
    "NEWS": os.getenv("NEWS", "1") != "0",
    "PDF": os.getenv("PDF", "1") != "0",
    "LIVESCORE": os.getenv("LIVESCORE", "1") != "0",   # Livescore.com ids for the app's live tab
    "WORLD": os.getenv("WORLD", "1") != "0",           # every competition on Livescore (priced by Sportybet) — v4
    "FULL_MARKETS_MAX": int(_env_float("FULL_MARKETS_MAX", 160)),   # per-event Sportybet market fetches (corners / cards)
    "BOTD_N": int(_env_float("BOTD_N", 3)),            # bets of the day: picks per section
    "REPORT_MAX_ROWS": int(_env_float("REPORT_MAX_ROWS", 60)),
    "DETAIL_MAX": int(os.getenv("DETAIL_MAX", "12")),        # match dossiers in the report / PDF
    "BACKFILL_SEASONS": int(_env_float("BACKFILL_SEASONS", 2)),   # earlier Livescore seasons to archive per competition
    "BACKFILL_BUDGET_S": _env_float("BACKFILL_BUDGET_S", 45),
    # major competitions to keep in the stage archive (and the app's Leagues tab) at all times, even
    # between matchdays: every stage key was verified against the public Livescore feed in Sep 2026.
    # Discovered stages (anything in the last three day feeds) and already-archived stages are added
    # to this automatically on every run, so the list only needs a manual entry for a new code.
    "SEED_STAGES": os.getenv("SEED_STAGES", "england/premier-league,england/championship,spain/laliga,spain/laliga-2,italy/serie-a,germany/bundesliga,germany/2-bundesliga,france/ligue-1,france/ligue-2,portugal/primeira-liga,scotland/scotland-premiership,turkey/super-lig,switzerland/super-league,greece/super-league,poland/ekstraklasa,ukraine/premier-league,romania/liga-1,croatia/1st-league,denmark/superliga,norway/eliteserien,sweden/allsvenskan,finland/veikkausliiga,austria/bundesliga,belgium/belgian-pro-league-2025,israel/premier-league,ireland/league-of-ireland-premier-division,wales/cymru-premier,south-africa/premiership,egypt/premier-league,morocco/botola-pro,algeria/ligue-1-2025,nigeria/npfl,ghana/premier-league,tanzania/premier-league,botswana/premier-league,brazil/serie-a,argentina/liga-profesional-clausura,chile/primera-division,colombia/primera-a-clausura,uruguay/primera-division-clausura,paraguay/division-profesional-clausura,peru/primera-division-clausura,ecuador/serie-a,venezuela/primera-division-clausura,usa/major-league-soccer-2026,mexico/liga-mx-apertura,japan/j-league-2025,iran/persian-gulf-pro-league,saudi-arabia/saudi-professional-league,qatar/qatar-stars-league,indonesia/super-league,australia/northern"),
    "STATS_BUDGET_S": _env_float("STATS_BUDGET_S", 75),      # Livescore match statistics per run: time budget
    "STATS_MAX": int(_env_float("STATS_MAX", 400)),          # ... and request cap
    "WORLD_COUNT_MIN_N": int(_env_float("WORLD_COUNT_MIN_N", 5)),  # corners/cards outside the main leagues need this many matches with stats per team
    # per-fixture news for the app's Match Center (context only — never a model input):
    # distinct headline queries fetched per run (the rest is served from the 6 h TTL cache)
    "NEWS_BUDGET": int(_env_float("NEWS_BUDGET", 90)),
    "NEWS_TTL_H": _env_float("NEWS_TTL_H", 6),
    "H2H_SEASONS": int(_env_float("H2H_SEASONS", 5)),  # seasons of main-league history kept for head-to-head
    "REQUEST_TIMEOUT": 30,
    "USER_AGENT": "Mozilla/5.0 (compatible; GoalsScanner/1.0)",
    # optional: restrict to some competitions, e.g. LEAGUES="E0,SP1,I1,D1,F1,BRA"
    "LEAGUES": [s.strip() for s in os.getenv("LEAGUES", "").split(",") if s.strip()],
}

TZL = CONFIG["TZ_LABEL"]

MARKETS = {
    "O15": "Over 1.5 goals",
    "O25": "Over 2.5 goals",
    "BTTS": "Both teams to score",
}

# football-data.co.uk main divisions: code -> (country, competition)
MAIN_LEAGUES = {
    "E0": ("England", "Premier League"),
    "E1": ("England", "Championship"),
    "E2": ("England", "League One"),
    "E3": ("England", "League Two"),
    "EC": ("England", "National League"),
    "SC0": ("Scotland", "Premiership"),
    "SC1": ("Scotland", "Championship"),
    "SC2": ("Scotland", "League One"),
    "SC3": ("Scotland", "League Two"),
    "D1": ("Germany", "Bundesliga"),
    "D2": ("Germany", "2. Bundesliga"),
    "I1": ("Italy", "Serie A"),
    "I2": ("Italy", "Serie B"),
    "SP1": ("Spain", "La Liga"),
    "SP2": ("Spain", "Segunda División"),
    "F1": ("France", "Ligue 1"),
    "F2": ("France", "Ligue 2"),
    "N1": ("Netherlands", "Eredivisie"),
    "B1": ("Belgium", "Pro League"),
    "P1": ("Portugal", "Primeira Liga"),
    "T1": ("Turkey", "Süper Lig"),
    "G1": ("Greece", "Super League"),
}

# "extra" leagues: country name used in new_league_fixtures.csv -> file code
EXTRA_LEAGUES = {
    "Argentina": "ARG", "Austria": "AUT", "Brazil": "BRA", "China": "CHN",
    "Denmark": "DNK", "Finland": "FIN", "Ireland": "IRL", "Japan": "JPN",
    "Mexico": "MEX", "Norway": "NOR", "Poland": "POL", "Romania": "ROU",
    "Russia": "RUS", "Sweden": "SWE", "Switzerland": "SWZ", "USA": "USA",
}

log = logging.getLogger("scanner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": CONFIG["USER_AGENT"]})


# ----------------------------------------------------------------------------- helpers
def fetch(url: str) -> bytes | None:
    """Download a file with a few retries. Returns None on 404 or persistent failure."""
    for attempt in range(3):
        try:
            r = SESSION.get(url, timeout=CONFIG["REQUEST_TIMEOUT"])
            if r.status_code == 404:
                return None
            if r.status_code == 200 and len(r.content) > 40:
                return r.content
            log.warning("HTTP %s for %s", r.status_code, url)
        except requests.RequestException as exc:
            log.warning("Request failed (%s): %s", url, exc)
        time.sleep(2 * (attempt + 1))
    return None


def read_csv(content: bytes | None, sep: str = ",") -> pd.DataFrame | None:
    if content is None:
        return None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(content), sep=sep, encoding=enc,
                             on_bad_lines="skip", skip_blank_lines=True)
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except Exception:  # noqa: BLE001
            continue
    return None


def parse_dates(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    d = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    miss = d.isna()
    if miss.any():
        d[miss] = pd.to_datetime(s[miss], format="%d/%m/%y", errors="coerce")
    return d


def num(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(np.nan, index=df.index, dtype="float64")


def wmean(values, weights) -> float:
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    m = ~np.isnan(v)
    if m.sum() == 0 or w[m].sum() <= 0:
        return float("nan")
    return float((v[m] * w[m]).sum() / w[m].sum())


def poisson_cdf(k: int, lam: float) -> float:
    return sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k + 1))


def season_codes(now: datetime) -> list[str]:
    """Current and previous season codes as used by football-data.co.uk, e.g. ['2627', '2526']."""
    y = now.year if now.month >= 7 else now.year - 1
    cur = f"{y % 100:02d}{(y + 1) % 100:02d}"
    prev = f"{(y - 1) % 100:02d}{y % 100:02d}"
    return [cur, prev]


def pct(x) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.0f}%"


def f2(x) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.2f}"


def stars(p: float, mkt: str) -> str:
    t2, t3 = CONFIG["THRESHOLDS"][mkt]["tiers"]
    if p >= t3:
        return "⭐⭐⭐"
    if p >= t2:
        return "⭐⭐"
    return "⭐"


MAXG = 10  # score matrix size (goals 0..10)


def score_matrix(lh: float, la: float, rho: float = 0.0) -> np.ndarray:
    """Score probabilities P(home=i, away=j); rho != 0 applies the Dixon-Coles low-score correction."""
    g = np.arange(MAXG + 1)
    ph = np.exp(-lh) * lh ** g / np.array([math.factorial(int(k)) for k in g])
    pa = np.exp(-la) * la ** g / np.array([math.factorial(int(k)) for k in g])
    M = np.outer(ph, pa)
    if rho:
        M[0, 0] *= 1 - lh * la * rho
        M[1, 0] *= 1 + la * rho
        M[0, 1] *= 1 + lh * rho
        M[1, 1] *= 1 - rho
        M = np.clip(M, 1e-12, None)
    return M / M.sum()


def probs_from_matrix(M: np.ndarray) -> dict:
    g = np.arange(MAXG + 1)
    tot = g[:, None] + g[None, :]
    return {"O15": float(M[tot >= 2].sum()), "O25": float(M[tot >= 3].sum()), "O35": float(M[tot >= 4].sum()),
            "O05": float(M[tot >= 1].sum()), "O45": float(M[tot >= 5].sum()), "O55": float(M[tot >= 6].sum()),
            "BTTS": float(M[1:, 1:].sum()),
            "HW": float(M[g[:, None] > g[None, :]].sum()), "AW": float(M[g[:, None] < g[None, :]].sum())}


def market_lambdas(odds_h, odds_d, odds_a, odds_over, odds_under):
    """Expected goals implied by the market: total from the Over/Under 2.5 price, split from 1X2.
    Returns (lam_h, lam_a) or None when any price is missing."""
    vals = [odds_h, odds_d, odds_a, odds_over, odds_under]
    if any(v is None or (isinstance(v, float) and math.isnan(v)) or v <= 1 for v in vals):
        return None
    p_over = (1 / odds_over) / (1 / odds_over + 1 / odds_under)
    inv = np.array([1 / odds_h, 1 / odds_d, 1 / odds_a])
    p_h, _, p_a = inv / inv.sum()
    lo, hi = 0.3, 7.0
    for _ in range(40):                                  # total goals matching P(over 2.5)
        mid = (lo + hi) / 2
        if 1 - poisson_cdf(2, mid) < p_over:
            lo = mid
        else:
            hi = mid
    lt = (lo + hi) / 2
    lo, hi = 0.05, 0.95
    for _ in range(30):                                  # home share matching P(home) - P(away)
        s = (lo + hi) / 2
        P = probs_from_matrix(score_matrix(lt * s, lt * (1 - s)))
        if P["HW"] - P["AW"] < p_h - p_a:
            lo = s
        else:
            hi = s
    s = (lo + hi) / 2
    return lt * s, lt * (1 - s)


# ----------------------------------------------------------------------------- data loading
NUM_RESULT_COLS = ("hg", "ag", "hxg", "axg", "hs", "as", "hst", "ast", "hsoff", "asoff", "hc", "ac", "hy", "ay", "hr", "ar", "hth", "hta")
RESULT_COLS = ["country", "div", "league", "date", "home", "away", *NUM_RESULT_COLS, "referee", "home_id", "away_id"]


def empty_results() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="float64" if c in NUM_RESULT_COLS
                                      else ("datetime64[ns]" if c == "date" else "object"))
                         for c in RESULT_COLS})


def without_unverified_replay_prices(fixtures: pd.DataFrame) -> pd.DataFrame:
    """A SCAN_NOW override is not evidence that current prices existed then."""
    result = fixtures.copy()
    for col in result.columns:
        if col.startswith(("odds_", "b365_", "bfe_", "max_")):
            result[col] = np.nan
    return result


def prediction_history_as_of(results: pd.DataFrame, cutoff: datetime) -> pd.DataFrame:
    """Conservative prediction history, shared by every model and evidence path.

    Historical result feeds do not record when a final score/statistic was first
    available, and their dates are day-only. Exclude the cutoff day as well as
    the future: a same-day kickoff is not proof that its result was available.
    This is not a point-in-time reconstruction of later backfilled statistics.
    Settlement uses a separate, unfiltered-by-this-function result frame.
    """
    if results.empty:
        return results.copy()
    dates = pd.to_datetime(results["date"], errors="coerce")
    return results.loc[dates < pd.Timestamp(cutoff.date())].copy()


def fetch_cached(url: str, name: str) -> bytes | None:
    """Immutable downloads (finished seasons) are kept under data/cache so the half-hourly runs stay light."""
    p = CACHE_DIR / name
    if p.exists():
        return p.read_bytes()
    content = fetch(url)
    if content:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        except OSError:
            pass
    return content


def load_main_results(divs: set[str], seasons: list[str], live_seasons: tuple[str, ...] = ()) -> pd.DataFrame:
    frames = []
    for div in sorted(divs):
        for season in seasons:
            url = f"{BASE}/mmz4281/{season}/{div}.csv"
            df = read_csv(fetch(url) if season in live_seasons else fetch_cached(url, f"fd_{season}_{div}.csv"))
            if df is None or not {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"} <= set(df.columns):
                log.info("No data for %s %s", div, season)
                continue
            df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
            if df.empty:
                continue
            country, league = MAIN_LEAGUES[div]
            frames.append(pd.DataFrame({
                "country": country, "div": div, "league": league,
                "date": parse_dates(df["Date"]),
                "home": df["HomeTeam"].astype(str).str.strip(),
                "away": df["AwayTeam"].astype(str).str.strip(),
                "hg": num(df, "FTHG"), "ag": num(df, "FTAG"),
                "hxg": num(df, "HxG"), "axg": num(df, "AxG"),
                "hs": num(df, "HS"), "as": num(df, "AS"), "hst": num(df, "HST"), "ast": num(df, "AST"),
                "hc": num(df, "HC"), "ac": num(df, "AC"),
                "hy": num(df, "HY"), "ay": num(df, "AY"), "hr": num(df, "HR"), "ar": num(df, "AR"),
                "hth": num(df, "HTHG"), "hta": num(df, "HTAG"),
                "referee": df["Referee"].astype(str).str.strip() if "Referee" in df.columns else "",
                "home_id": None, "away_id": None,
                "_source_ref": f"football-data:mmz4281/{season}/{div}.csv",
                "_history_kickoff": df["Time"].astype(str).str.strip().where(df["Time"].notna(), None) if "Time" in df else None,
            }))
            log.info("Loaded %s %s: %d matches", div, season, len(df))
    return pd.concat(frames, ignore_index=True) if frames else empty_results()


def load_extra_results(codes: set[str], since: datetime) -> pd.DataFrame:
    frames = []
    for code in sorted(codes):
        df = read_csv(fetch(f"{BASE}/new/{code}.csv"))
        if df is None or not {"Date", "Home", "Away", "HG", "AG"} <= set(df.columns):
            log.info("No data for extra league %s", code)
            continue
        df = df.dropna(subset=["Date", "Home", "Away", "HG", "AG"])
        league = df["League"].astype(str).str.strip()
        out = pd.DataFrame({
            "country": df["Country"].astype(str).str.strip(),
            "div": code + ":" + league, "league": league,
            "date": parse_dates(df["Date"]),
            "home": df["Home"].astype(str).str.strip(),
            "away": df["Away"].astype(str).str.strip(),
            "hg": num(df, "HG"), "ag": num(df, "AG"),
            "hxg": np.nan, "axg": np.nan, "hs": np.nan, "as": np.nan, "hst": np.nan, "ast": np.nan,
            "hc": np.nan, "ac": np.nan, "hy": np.nan, "ay": np.nan, "hr": np.nan, "ar": np.nan, "hth": np.nan, "hta": np.nan,
            "referee": "", "home_id": None, "away_id": None,
            "_source_ref": f"football-data:new/{code}.csv",
            "_history_kickoff": df["Time"].astype(str).str.strip().where(df["Time"].notna(), None) if "Time" in df else None,
        })
        out = out[out["date"] >= since]
        frames.append(out)
        log.info("Loaded %s: %d matches since %s", code, len(out), since.date())
    return pd.concat(frames, ignore_index=True) if frames else empty_results()


def load_fixtures(tz: ZoneInfo) -> pd.DataFrame:
    """All upcoming fixtures from both feeds, normalised to one schema."""
    rows = []

    df = read_csv(fetch(FIXTURES_URL))
    if df is not None and "Div" in df.columns:
        df = df.dropna(subset=["Div", "Date", "HomeTeam", "AwayTeam"])
        df = df[df["Div"].isin(MAIN_LEAGUES)]
        dates = parse_dates(df["Date"])
        for i, r in df.iterrows():
            if pd.isna(dates[i]):
                continue
            country, league = MAIN_LEAGUES[r["Div"]]
            rows.append({
                "source": "main", "code": r["Div"], "country": country, "div": r["Div"],
                "league": league, "date": dates[i], "time": str(r.get("Time", "")).strip(),
                "home": str(r["HomeTeam"]).strip(), "away": str(r["AwayTeam"]).strip(),
                "odds_over": pd.to_numeric(r.get("Avg>2.5"), errors="coerce"),
                "odds_under": pd.to_numeric(r.get("Avg<2.5"), errors="coerce"),
                "b365_over": pd.to_numeric(r.get("B365>2.5"), errors="coerce"),
                "b365_under": pd.to_numeric(r.get("B365<2.5"), errors="coerce"),
                "odds_h": pd.to_numeric(r.get("AvgH"), errors="coerce"),
                "odds_d": pd.to_numeric(r.get("AvgD"), errors="coerce"),
                "odds_a": pd.to_numeric(r.get("AvgA"), errors="coerce"),
                "bfe_h": pd.to_numeric(r.get("BFEH"), errors="coerce"),
                "bfe_d": pd.to_numeric(r.get("BFED"), errors="coerce"),
                "bfe_a": pd.to_numeric(r.get("BFEA"), errors="coerce"),
                "bfe_over": pd.to_numeric(r.get("BFE>2.5"), errors="coerce"),
                "bfe_under": pd.to_numeric(r.get("BFE<2.5"), errors="coerce"),
                "max_over": pd.to_numeric(r.get("Max>2.5"), errors="coerce"),
                "max_under": pd.to_numeric(r.get("Max<2.5"), errors="coerce"),
                "referee": str(r.get("Referee", "") or "").strip(),
            })
    else:
        log.warning("Main fixtures feed unavailable")

    df = read_csv(fetch(NEW_FIXTURES_URL), sep="\t")
    if df is not None and "Country" in df.columns:
        df = df.dropna(subset=["Country", "Date", "Home", "Away"])
        dates = parse_dates(df["Date"])
        for i, r in df.iterrows():
            country = str(r["Country"]).strip()
            code = EXTRA_LEAGUES.get(country)
            if code is None or pd.isna(dates[i]):
                continue
            league = str(r["League"]).strip()
            rows.append({
                "source": "extra", "code": code, "country": country, "div": f"{code}:{league}",
                "league": league, "date": dates[i], "time": str(r.get("Time", "")).strip(),
                "home": str(r["Home"]).strip(), "away": str(r["Away"]).strip(),
                "odds_over": np.nan, "odds_under": np.nan, "b365_over": np.nan, "b365_under": np.nan,
                "odds_h": pd.to_numeric(r.get("AvgH"), errors="coerce"),
                "odds_d": pd.to_numeric(r.get("AvgD"), errors="coerce"),
                "odds_a": pd.to_numeric(r.get("AvgA"), errors="coerce"),
                "bfe_h": pd.to_numeric(r.get("BFEH"), errors="coerce"),
                "bfe_d": pd.to_numeric(r.get("BFED"), errors="coerce"),
                "bfe_a": pd.to_numeric(r.get("BFEA"), errors="coerce"),
                "bfe_over": np.nan, "bfe_under": np.nan, "max_over": np.nan, "max_under": np.nan, "referee": "",
            })
    else:
        log.warning("Extra-league fixtures feed unavailable")

    fx = pd.DataFrame(rows)
    if fx.empty:
        return fx

    def kickoff(r):
        t = r["time"] if r["time"] and r["time"].lower() not in ("nan", "none", "") else "12:00"
        try:
            hh, mm = [int(x) for x in t.split(":")[:2]]
        except ValueError:
            hh, mm = 12, 0
        return datetime(r["date"].year, r["date"].month, r["date"].day, hh, mm, tzinfo=FEED_TZ).astimezone(tz)

    fx["kickoff"] = fx.apply(kickoff, axis=1)
    fx["time_known"] = fx["time"].apply(lambda t: bool(t) and t.lower() not in ("nan", "none"))
    fx["referee"] = fx["referee"].replace({"nan": "", "None": ""})
    fx = fx[fx.apply(competition_policy.allows_record, axis=1)]
    if CONFIG["LEAGUES"]:
        fx = fx[fx["code"].isin(CONFIG["LEAGUES"])]
    return fx.sort_values(["kickoff", "country", "league"]).reset_index(drop=True)


# ----------------------------------------------------------------------------- modelling
@dataclass
class DivAvg:
    mu_h: float
    mu_a: float
    n_eff: float
    o25_rate: float
    btts_rate: float


def decay_weights(dates: pd.Series, now: datetime) -> np.ndarray:
    days = (pd.Timestamp(now.date()) - dates).dt.days.clip(lower=0).to_numpy(dtype=float)
    return 0.5 ** (days / CONFIG["HALF_LIFE_DAYS"])


def compute_div_avgs(results: pd.DataFrame, now: datetime) -> dict[str, DivAvg]:
    out: dict[str, DivAvg] = {}
    if results.empty:
        return out
    w_all = decay_weights(results["date"], now)
    prior_h = wmean(results["hg"], w_all) if len(results) else 1.45
    prior_a = wmean(results["ag"], w_all) if len(results) else 1.20
    prior_h = 1.45 if math.isnan(prior_h) else prior_h
    prior_a = 1.20 if math.isnan(prior_a) else prior_a
    K = 30.0
    # A reviewed event contributes once to the global prior but is visible in
    # each provider's division-specific prior, without duplicating team samples.
    for div, g in cross_provider.division_view(results).groupby("div"):
        w = decay_weights(g["date"], now)
        n = float(w.sum())
        mu_h = wmean(g["hg"], w)
        mu_a = wmean(g["ag"], w)
        mu_h = (n * mu_h + K * prior_h) / (n + K) if not math.isnan(mu_h) else prior_h
        mu_a = (n * mu_a + K * prior_a) / (n + K) if not math.isnan(mu_a) else prior_a
        tot = g["hg"] + g["ag"]
        out[div] = DivAvg(mu_h, mu_a, n,
                          wmean((tot >= 3).astype(float), w),
                          wmean(((g["hg"] > 0) & (g["ag"] > 0)).astype(float), w))
    out["__global__"] = DivAvg(prior_h, prior_a, float(w_all.sum()), float("nan"), float("nan"))
    return out


def make_long(results: pd.DataFrame, div_avgs: dict[str, DivAvg]) -> pd.DataFrame:
    """One row per team per match (perspective table) with league-normalised goals."""
    if results.empty:
        return pd.DataFrame()
    g = div_avgs.get("__global__", DivAvg(1.45, 1.2, 0, float("nan"), float("nan")))
    mu_h = results["div"].map(lambda d: div_avgs.get(d, g).mu_h).astype(float)
    mu_a = results["div"].map(lambda d: div_avgs.get(d, g).mu_a).astype(float)
    common = {"country": results["country"], "date": results["date"], "div": results["div"],
              "league": results["league"]}
    if "_history_divs" in results:
        common["div_aliases"] = results["_history_divs"]
    if "_history_records" in results:
        common["history_sources"] = results["_history_records"].map(
            lambda recs: [r.get("_source_ref") for r in recs if isinstance(r, dict) and r.get("_source_ref")]
            if isinstance(recs, (tuple, list)) else [])
        common["history_conflicts"] = results["_history_conflicts"] if "_history_conflicts" in results else None
    hid = results["home_id"] if "home_id" in results.columns else pd.Series(None, index=results.index, dtype="object")
    aid = results["away_id"] if "away_id" in results.columns else pd.Series(None, index=results.index, dtype="object")
    col = lambda c: results[c] if c in results.columns else pd.Series(np.nan, index=results.index)  # noqa: E731
    # A missing or conflicted yellow/red count is not zero; both are required.
    cards_h = col("hy") + col("hr")
    cards_a = col("ay") + col("ar")
    eid = col("eid").astype(object).where(col("eid").notna(), None)
    common["eid"] = eid
    common["friendly"] = results["league"].astype(str).str.lower().str.contains("friendl")
    home = pd.DataFrame({**common, "team_id": hid, "opp_id": aid, "team": results["home"], "opp": results["away"], "venue": "H",
                         "gf": results["hg"], "ga": results["ag"],
                         "gf_norm": results["hg"] / mu_h, "ga_norm": results["ag"] / mu_a,
                         "xg_for": results["hxg"], "xg_against": results["axg"],
                         "sot_for": results["hst"], "sot_against": results["ast"],
                         "s_for": col("hs"), "s_against": col("as"), "c_for": col("hc"), "c_against": col("ac"),
                         "k_for": cards_h, "k_against": cards_a})
    away = pd.DataFrame({**common, "team_id": aid, "opp_id": hid, "team": results["away"], "opp": results["home"], "venue": "A",
                         "gf": results["ag"], "ga": results["hg"],
                         "gf_norm": results["ag"] / mu_a, "ga_norm": results["hg"] / mu_h,
                         "xg_for": results["axg"], "xg_against": results["hxg"],
                         "sot_for": results["ast"], "sot_against": results["hst"],
                         "s_for": col("as"), "s_against": col("hs"), "c_for": col("ac"), "c_against": col("hc"),
                         "k_for": cards_a, "k_against": cards_h})
    long = pd.concat([home, away], ignore_index=True)
    long["total"] = long["gf"] + long["ga"]
    long["o15"] = (long["total"] >= 2).astype(float)
    long["o25"] = (long["total"] >= 3).astype(float)
    long["o35"] = (long["total"] >= 4).astype(float)
    long["btts"] = ((long["gf"] > 0) & (long["ga"] > 0)).astype(float)
    long["cs"] = (long["ga"] == 0).astype(float)
    long["fts"] = (long["gf"] == 0).astype(float)
    return long.sort_values("date", ascending=False).reset_index(drop=True)


@dataclass
class TeamProfile:
    name: str
    n: int = 0
    n_eff: float = 0.0
    venue_n: int = 0
    gf: float = float("nan")
    ga: float = float("nan")
    venue_gf: float = float("nan")
    venue_ga: float = float("nan")
    att: float = 1.0
    dfc: float = 1.0
    rate_o15: float = float("nan")
    rate_o25: float = float("nan")
    rate_o35: float = float("nan")
    rate_btts: float = float("nan")
    rate_cs: float = float("nan")
    rate_fts: float = float("nan")
    last_n: int = 0
    last_o15: int = 0
    last_o25: int = 0
    last_btts: int = 0
    form5_goals: float = float("nan")
    xg_for: float = float("nan")
    xg_against: float = float("nan")
    sot_for: float = float("nan")
    sot_against: float = float("nan")
    signal_values: dict = field(default_factory=dict)
    signal_counts: dict = field(default_factory=dict)  # valid last-ten observation counts
    last5: list = field(default_factory=list)
    venue_rate_o25: float = float("nan")
    venue_rate_btts: float = float("nan")
    venue_rate_o15: float = float("nan")
    venue_last5: list = field(default_factory=list)
    # ---- evidence layer (data-first engine): raw ratings before/after each step, raw observations, opponent context
    att_raw: float = float("nan")        # all-venue time-weighted league-normalised goals for (no shrinkage)
    def_raw: float = float("nan")
    att_venue_raw: float = float("nan")  # same, this venue only
    def_venue_raw: float = float("nan")
    venue_share: float = 0.0             # weight of the venue rates in the blend
    att_blend: float = float("nan")      # after the venue blend, before shrinkage
    def_blend: float = float("nan")
    matches: list = field(default_factory=list)   # raw observations used (newest first)
    friendlies_excluded: int = 0
    opp_att: float = float("nan")        # average raw attack / defence rating of the opponents faced (information only)
    opp_def: float = float("nan")
    att_opp_adj: float = float("nan")    # raw attack / opponents' defence (information only, not a model input)
    def_opp_adj: float = float("nan")

    @property
    def ok(self) -> bool:
        return self.n_eff >= CONFIG["MIN_EFF_MATCHES"]


def _valid_id(x) -> bool:
    return isinstance(x, str) and x.strip() != ""


TEAM_HIST_CACHE: dict = {}   # (id(long), country, team, team_id) -> slice; pure lookups, cleared per run
H2H_CACHE: dict = {}         # (id(results), country, home, away, limit, home_id, away_id) -> list; cleared per run
PROFILE_CACHE: dict = {}     # (id(long), country, team, venue, id(now), team_id) -> TeamProfile; cleared per run
LONG_INDEX: dict = {}        # rating_key -> a team's perspective rows (date desc); built once per run, read-only
H2H_INDEX_SOURCE = None       # identity of indexed pool, never used for a different frame
RECENT_TEAM_CACHE: dict = {}  # per-scan team window evidence, cleared before and after analysis
H2H_INDEX: dict = {}         # (home_id, away_id) / ("n", country, home, away) -> past meetings; built once per run
ACACHE: "acache.AnalysisCache | None" = None   # the cross-run incremental cache (set in main)


def build_long_index(long: pd.DataFrame) -> None:
    """Index the perspective table by team once per run (position lists, no frame copies). Every
    later team lookup becomes an iloc slice instead of a full-frame boolean mask; positions are
    ascending, so the slice preserves the frame's (date-desc) row order exactly."""
    LONG_INDEX.clear()
    if long.empty:
        return
    if "team_id" in long.columns:
        ti = long["team_id"].to_numpy()
        for i, t in enumerate(ti):
            if _valid_id(t):
                LONG_INDEX.setdefault(("id", t), []).append(i)
    co = long["country"].to_numpy()
    te = long["team"].to_numpy()
    for i in range(len(long)):
        LONG_INDEX.setdefault(("name", co[i], te[i]), []).append(i)


def build_h2h_index(results: pd.DataFrame) -> None:
    """Index past meetings by team pair once per run (both orderings, id-based and name-based)."""
    global H2H_INDEX_SOURCE
    H2H_INDEX.clear()
    H2H_INDEX_SOURCE = id(results)
    if results.empty:
        return
    if "home_id" in results.columns and "away_id" in results.columns:
        hi = results["home_id"].to_numpy()
        ai = results["away_id"].to_numpy()
        for i in range(len(results)):
            h, a = hi[i], ai[i]
            if _valid_id(h) and _valid_id(a):
                H2H_INDEX.setdefault((h, a), []).append(i)
                H2H_INDEX.setdefault((a, h), []).append(i)
    co = results["country"].to_numpy()
    ho = results["home"].to_numpy()
    aw = results["away"].to_numpy()
    for i in range(len(results)):
        H2H_INDEX.setdefault(("n", co[i], ho[i], aw[i]), []).append(i)
        H2H_INDEX.setdefault(("n", co[i], aw[i], ho[i]), []).append(i)


def _h2h_pair_mask(results: pd.DataFrame, country: str, home: str, away: str,
                   home_id=None, away_id=None) -> pd.DataFrame:
    """The original mask-based pair lookup (kept as the exact fallback when no index is built)."""
    if _valid_id(home_id) and _valid_id(away_id) and "home_id" in results.columns:
        return results[((results["home_id"] == home_id) & (results["away_id"] == away_id)) |
                       ((results["home_id"] == away_id) & (results["away_id"] == home_id))]
    return results[(results["country"] == country) &
                   (((results["home"] == home) & (results["away"] == away)) |
                    ((results["home"] == away) & (results["away"] == home)))]


def team_history(long: pd.DataFrame, country: str, team: str, team_id=None) -> pd.DataFrame:
    """A team's perspective rows: by Livescore id when known (any competition), else by country + name."""
    key = (id(long), country, team, team_id)
    hit = TEAM_HIST_CACHE.get(key)
    if hit is not None:
        return hit
    if long.empty:
        return long
    if LONG_INDEX:
        if _valid_id(team_id) and "team_id" in long.columns:
            pos = LONG_INDEX.get(("id", team_id))
            if pos is not None:
                rows = long.iloc[pos]
                TEAM_HIST_CACHE[key] = rows
                return rows
        pos = LONG_INDEX.get(("name", country, team))
        if pos is not None:
            out = long.iloc[pos]
            TEAM_HIST_CACHE[key] = out
            return out
    if _valid_id(team_id) and "team_id" in long.columns:
        rows = long[long["team_id"] == team_id]
        if not rows.empty:
            TEAM_HIST_CACHE[key] = rows
            return rows
    out = long[(long["country"] == country) & (long["team"] == team)]
    TEAM_HIST_CACHE[key] = out
    return out


def shrink_ratings(att: float, dfc: float, n_eff: float) -> tuple[float, float]:
    """Shrink a team's attack / defence ratings towards the league average (1.00).

    Two strengths of shrinkage (validated in backtest/model_variants.py, 2026-09-28): the attack/defence *ratio*
    (how much better one team is than the other) is more persistent than the overall goal *tempo*, so the ratio is
    shrunk with SHRINK_K_STRENGTH weighted matches and the tempo with SHRINK_K. In log space:
        s = (log att - log def) * n / (n + K_s)      t = (log att + log def) * n / (n + K)
        att = exp((t + s) / 2)                       def = exp((t - s) / 2)
    """
    if math.isnan(att) or math.isnan(dfc) or n_eff <= 0:
        return 1.0, 1.0
    K, K_s = CONFIG["SHRINK_K"], CONFIG["SHRINK_K_STRENGTH"]
    la, ld = math.log(max(att, 0.05)), math.log(max(dfc, 0.05))
    s = (la - ld) * n_eff / (n_eff + K_s)
    t = (la + ld) * n_eff / (n_eff + K)
    return math.exp((t + s) / 2), math.exp((t - s) / 2)


def rating_key(country: str, team: str, team_id=None):
    return ("id", team_id) if _valid_id(team_id) else ("name", country, team)


SEASON_STARTS: dict = {}       # div -> inferred start of the current season (quality.season_starts), set once per run
RAW_RATINGS: dict = {}         # rating_key -> (raw attack, raw defence), all venues, shrunk with SHRINK_K; opponent context only


def compute_raw_ratings(long: pd.DataFrame, now: datetime) -> dict:
    """First-pass raw rating of every team in the pool (time-weighted league-normalised goals, shrunk with SHRINK_K).
    Used only to describe the strength of the opponents a team has faced — it is not an input of the match model."""
    if long.empty:
        return {}
    df = long.copy()
    df["w"] = decay_weights(df["date"], now)
    df["key"] = [rating_key(c, t, i) for c, t, i in zip(df["country"], df["team"], df["team_id"])]
    df = df.sort_values("date", ascending=False)
    df["rank"] = df.groupby("key").cumcount()
    df = df[df["rank"] < CONFIG["MAX_MATCHES_PER_TEAM"]]
    df["wa"] = df["w"] * df["gf_norm"]
    df["wd"] = df["w"] * df["ga_norm"]
    g = df.groupby("key")[["w", "wa", "wd"]].sum()
    K = CONFIG["SHRINK_K"]
    att = (g["wa"] + K) / (g["w"] + K)
    dfc = (g["wd"] + K) / (g["w"] + K)
    return {k: (float(a), float(d)) for k, a, d in zip(g.index, att, dfc)}


def build_profile(long: pd.DataFrame, country: str, team: str, venue: str, now: datetime, team_id=None) -> TeamProfile:
    key = (id(long), country, team, venue, id(now), team_id)
    hit = PROFILE_CACHE.get(key)
    if hit is not None:
        return hit
    p = TeamProfile(name=team)
    if long.empty:
        return p
    rows = team_history(long, country, team, team_id)
    if rows.empty:
        return p
    # friendlies are excluded from the core statistics once the team has enough competitive matches; otherwise they
    # stay in and are flagged in the sample composition (never silently)
    if "friendly" in rows.columns and rows["friendly"].any():
        competitive = rows[~rows["friendly"]]
        if len(competitive) >= quality.FRIENDLY_MIN_COMPETITIVE:
            p.friendlies_excluded = int(min(len(rows), CONFIG["MAX_MATCHES_PER_TEAM"]) - min(len(competitive), CONFIG["MAX_MATCHES_PER_TEAM"]))
            rows = competitive
    rows = rows.head(CONFIG["MAX_MATCHES_PER_TEAM"])
    w = decay_weights(rows["date"], now)
    p.n = len(rows)
    p.n_eff = float(w.sum())
    p.gf, p.ga = wmean(rows["gf"], w), wmean(rows["ga"], w)
    att_all, def_all = wmean(rows["gf_norm"], w), wmean(rows["ga_norm"], w)
    p.att_raw, p.def_raw = att_all, def_all
    season_start = SEASON_STARTS.get(str(rows["div"].iloc[0])) if len(rows) else None
    p.matches = [quality.match_record(r, season_start) for r in rows.itertuples()]
    # opponent context (information only): average raw rating of the opponents in the sample
    apply_opp_context(p, rows, now, att_all, def_all)

    vmask = (rows["venue"] == venue).to_numpy()
    p.venue_n = int(vmask.sum())
    if p.venue_n:
        wv = w[vmask]
        p.venue_gf = wmean(rows["gf"][vmask], wv)
        p.venue_ga = wmean(rows["ga"][vmask], wv)
        share = wv.sum() / (wv.sum() + CONFIG["VENUE_K"])
        p.venue_share = float(share)
        p.att_venue_raw, p.def_venue_raw = wmean(rows["gf_norm"][vmask], wv), wmean(rows["ga_norm"][vmask], wv)
        att = share * p.att_venue_raw + (1 - share) * att_all
        dfc = share * p.def_venue_raw + (1 - share) * def_all
        vrows = rows[vmask]
        p.venue_rate_o15 = wmean(vrows["o15"], wv)
        p.venue_rate_o25 = wmean(vrows["o25"], wv)
        p.venue_rate_btts = wmean(vrows["btts"], wv)
        p.venue_last5 = [{"date": r.date, "venue": r.venue, "opp": r.opp, "gf": int(r.gf), "ga": int(r.ga),
                          "league": r.league} for r in vrows.head(5).itertuples()]
    else:
        att, dfc = att_all, def_all

    p.att_blend, p.def_blend = att, dfc
    p.att, p.dfc = shrink_ratings(att, dfc, p.n_eff)

    p.rate_o15 = wmean(rows["o15"], w)
    p.rate_o25 = wmean(rows["o25"], w)
    p.rate_o35 = wmean(rows["o35"], w)
    p.rate_btts = wmean(rows["btts"], w)
    p.rate_cs = wmean(rows["cs"], w)
    p.rate_fts = wmean(rows["fts"], w)

    last10 = rows.head(10)
    p.last_n = len(last10)
    p.last_o15 = int(last10["o15"].sum())
    p.last_o25 = int(last10["o25"].sum())
    p.last_btts = int(last10["btts"].sum())
    p.form5_goals = float(rows.head(5)["total"].mean())
    p.xg_for = float(last10["xg_for"].mean()) if last10["xg_for"].notna().any() else float("nan")
    p.xg_against = float(last10["xg_against"].mean()) if last10["xg_against"].notna().any() else float("nan")
    p.sot_for = float(last10["sot_for"].mean()) if last10["sot_for"].notna().any() else float("nan")
    p.sot_against = float(last10["sot_against"].mean()) if last10["sot_against"].notna().any() else float("nan")
    for c in ("xg_for", "xg_against", "sot_for", "sot_against"):
        values = pd.to_numeric(last10[c], errors="coerce")
        values = values[(values >= 0) & np.isfinite(values) & (values <= (10 if c.startswith("xg") else 50))]
        p.signal_counts[c] = len(values)
        if len(values):
            p.signal_values[c] = float(values.mean())
    p.last5 = [{"date": r.date, "venue": r.venue, "opp": r.opp, "gf": int(r.gf), "ga": int(r.ga),
                "league": r.league} for r in rows.head(5).itertuples()]
    PROFILE_CACHE[key] = p
    return p


def _profile_sample_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """The exact sample build_profile consumes: the friendly-exclusion rule, then the latest MAX matches."""
    if "friendly" in rows.columns and rows["friendly"].any():
        competitive = rows[~rows["friendly"]]
        if len(competitive) >= quality.FRIENDLY_MIN_COMPETITIVE:
            rows = competitive
    return rows.head(CONFIG["MAX_MATCHES_PER_TEAM"])


def apply_opp_context(p: TeamProfile, sample: pd.DataFrame, now: datetime, att_all: float, def_all: float) -> None:
    """The opponent-context fields (information only): the average raw rating of the opponents faced.

    Cheap by design: called at the end of build_profile, and again on a cross-run cache hit with the
    current RAW_RATINGS, so the expensive profile core can be cached per-run while this context always
    reflects the current pool (opponent ratings churn as new results / statistics arrive)."""
    p.opp_att = p.opp_def = p.att_opp_adj = p.def_opp_adj = float("nan")
    if not RAW_RATINGS or sample.empty:
        return
    keys = [rating_key(r.country, r.opp, r.opp_id) for r in sample.itertuples(index=False)]
    w = decay_weights(sample["date"], now)
    oa = np.array([RAW_RATINGS.get(k, (np.nan, np.nan))[0] for k in keys], dtype=float)
    od = np.array([RAW_RATINGS.get(k, (np.nan, np.nan))[1] for k in keys], dtype=float)
    p.opp_att, p.opp_def = wmean(oa, w), wmean(od, w)
    if not math.isnan(p.opp_def) and p.opp_def > 0:
        p.att_opp_adj = att_all / p.opp_def
    if not math.isnan(p.opp_att) and p.opp_att > 0:
        p.def_opp_adj = def_all / p.opp_att


def profile_cached(long: pd.DataFrame, country: str, team: str, venue: str, now: datetime, team_id=None) -> TeamProfile:
    """build_profile with the cross-run memo (acache): when the team's own history rows, the
    season-start context and the calendar day are byte-identical to the previous run, the expensive
    profile core is reused. The light opponent context (information only, depends on opponents'
    ratings which churn as any new result / statistic lands) is refreshed on every hit, so a hit is
    still exactly what a cold build_profile would produce. Pure memoization: outputs are unchanged."""
    if ACACHE is None:
        return build_profile(long, country, team, venue, now, team_id)
    try:
        rows = team_history(long, country, team, team_id)
        if rows is None or rows.empty:
            return build_profile(long, country, team, venue, now, team_id)
        sample = _profile_sample_rows(rows)
        ss = SEASON_STARTS.get(str(sample["div"].iloc[0])) if len(sample) else None
        key = ("p2", acache.SCHEMA, now.date().isoformat(), country, team, venue, team_id,
               acache.digest_rows(rows),
               ss.strftime("%Y-%m-%d") if ss is not None else None)
        hit = ACACHE.profile_get(key)
        if hit is not None:
            apply_opp_context(hit, sample, now, hit.att_raw, hit.def_raw)
            return hit
        p = build_profile(long, country, team, venue, now, team_id)
        ACACHE.profile_put(key, p)
        return p
    except Exception:  # noqa: BLE001 — a cache hiccup must never change the model output
        pass
    return build_profile(long, country, team, venue, now, team_id)


def head_to_head(results: pd.DataFrame, country: str, home: str, away: str, limit: int = 10,
                 home_id=None, away_id=None) -> list[dict]:
    key = (id(results), country, home, away, limit, home_id, away_id)
    hit = H2H_CACHE.get(key)
    if hit is not None:
        return hit
    if results.empty:
        return []
    if H2H_INDEX:
        if _valid_id(home_id) and _valid_id(away_id) and "home_id" in results.columns:
            p1, p2 = H2H_INDEX.get((home_id, away_id)), H2H_INDEX.get((away_id, home_id))
            pos = sorted(set(p1 or ()) | set(p2 or ())) if (p1 or p2) else None
        else:
            p1, p2 = H2H_INDEX.get(("n", country, home, away)), H2H_INDEX.get(("n", country, away, home))
            pos = sorted(set(p1 or ()) | set(p2 or ())) if (p1 or p2) else None
        m = results.iloc[pos] if pos else _h2h_pair_mask(results, country, home, away, home_id, away_id)
    else:
        m = _h2h_pair_mask(results, country, home, away, home_id, away_id)
    m = m.sort_values("date", ascending=False).head(limit)
    out = [{"date": r.date, "home": r.home, "away": r.away, "hg": int(r.hg), "ag": int(r.ag),
            "league": r.league} for r in m.itertuples()]
    H2H_CACHE[key] = out
    return out


@dataclass
class MatchRow:
    fx: pd.Series
    home: TeamProfile
    away: TeamProfile
    lam_h: float          # expected goals used for every probability = the football-data model (lam == mod, kept for callers)
    lam_a: float
    mod_h: float          # model expected goals (football data only)
    mod_a: float
    mkt_h: float          # market-implied expected goals — comparison layer only, never a model input (nan without odds)
    mkt_a: float
    p_model: dict         # market -> model probability
    p_market_o25: float   # bookmaker-implied P(over 2.5) (comparison only)
    p_final: dict         # == p_model (the name is kept for the many callers; nothing else is ever blended in)
    hist: dict            # market -> average historical hit-rate of both teams (information only)
    h2h: list
    div_avg: DivAvg
    extra: markets.ExtraMarkets = field(default_factory=markets.ExtraMarkets)
    sb: dict | None = None        # Sportybet prices (main markets) or None when not matched
    sb_event: dict | None = None  # Sportybet event meta (id, names)
    sb_full: dict | None = None   # full Sportybet market list (corners / cards), dossier matches only
    fair: dict = field(default_factory=dict)   # market-implied probabilities of the shortlist markets (comparison only)
    trends: dict = field(default_factory=dict) # plain-language team / match / h2h trends (v4)
    mkt_source: str = ""          # where the market xG comes from ("reference odds" / "Sportybet")
    x12_market: dict | None = None  # de-margined bookmaker 1X2 (comparison only)
    audit: dict = field(default_factory=dict)  # evidence / quality / explanation / warnings (quality.py), filled in main()
    model_signals: dict = field(default_factory=dict)  # provisional adjustment audit
    recent_form: dict = field(default_factory=dict)  # per-fixture applied/fallback evidence
    h2h_evidence: dict = field(default_factory=dict)  # optional sample evidence, never a gate
    scores: list = field(default_factory=list)  # most likely cells of the same DC matrix

    @property
    def basis(self) -> str:
        return "model"

    @property
    def data_ok(self) -> bool:
        return self.home.ok and self.away.ok

    @property
    def label(self) -> str:
        return f"{self.fx['home']} v {self.fx['away']}"


def _recent_team(long, country, team, venue, team_id, profile, now):
    key = (id(long), country, team, venue, team_id, now.date())
    if key not in RECENT_TEAM_CACHE:
        sample = _profile_sample_rows(team_history(long, country, team, team_id))
        RECENT_TEAM_CACHE[key] = recent_form.prepare_team(profile, sample, venue, now)
    return RECENT_TEAM_CACHE[key]


def _recent_meetings(pool, fx, now):
    hid, aid = fx.get("home_id"), fx.get("away_id")
    if pool is None or not recent_form.valid_id(hid) or not recent_form.valid_id(aid) or hid == aid:
        return []
    if H2H_INDEX_SOURCE == id(pool):
        subset = pool.iloc[H2H_INDEX.get((hid, aid), [])]
    elif {"home_id", "away_id"}.issubset(pool.columns):
        subset = pool.loc[((pool["home_id"] == hid) & (pool["away_id"] == aid)) |
                          ((pool["home_id"] == aid) & (pool["away_id"] == hid))]
    else:
        return []
    return recent_form.meetings(subset, fx, now)


def analyse(fx: pd.Series, long: pd.DataFrame, results: pd.DataFrame,
            div_avgs: dict[str, DivAvg], now: datetime, h2h_pool: pd.DataFrame | None = None) -> MatchRow:
    if RECENT_FORM_ENABLED and EXPERIMENTAL_MODEL_SIGNALS:
        raise ValueError("Recent form and experimental model signals cannot be combined; disable one explicitly")
    g = div_avgs.get("__global__", DivAvg(1.45, 1.2, 0, float("nan"), float("nan")))
    da = div_avgs.get(fx["div"], g)
    hid, aid = fx.get("home_id"), fx.get("away_id")
    H = profile_cached(long, fx["country"], fx["home"], "H", now, hid)
    A = profile_cached(long, fx["country"], fx["away"], "A", now, aid)

    rho = CONFIG["DC_RHO"]
    # ---- the football-data model: league baseline x attack x opponent defence -> Dixon-Coles score matrix.
    # Bookmaker odds play no part here (data-first engine, 2026-09-28).
    mod_h = min(max(da.mu_h * H.att * A.dfc, 0.15), 4.5)
    mod_a = min(max(da.mu_a * A.att * H.dfc, 0.15), 4.5)
    recent = {"status": "disabled", "reason": "RECENT_FORM_ENABLED=0", "squad_availability": "not_used"}
    if RECENT_FORM_ENABLED:
        try:
            home_recent = _recent_team(long, fx["country"], fx["home"], "H", hid, H, now)
            away_recent = _recent_team(long, fx["country"], fx["away"], "A", aid, A, now)
            meetings = _recent_meetings(h2h_pool if h2h_pool is not None else results, fx, now)
            mod_h, mod_a, recent = recent_form.adjust(home_recent, away_recent, da, meetings)
        except ValueError as exc:
            recent = {"status": "baseline_fallback", "reason": str(exc), "squad_availability": "not_used"}
    # User-enabled experimental data-only adjustments; not yet backtested.
    # Unvalidated signals are disabled by default. Explicit research opt-in only.
    if EXPERIMENTAL_MODEL_SIGNALS:
        mod_h, sig_h = model_signals.goal_adjustment(mod_h, H, A, SIGNAL_BASELINES.get(str(fx["div"])))
        mod_a, sig_a = model_signals.goal_adjustment(mod_a, A, H, SIGNAL_BASELINES.get(str(fx["div"])))
    else:
        sig_h = {"baseline": mod_h, "adjusted": mod_h, "xg_applied": False, "sot_applied": False}
        sig_a = {"baseline": mod_a, "adjusted": mod_a, "xg_applied": False, "sot_applied": False}
    M = score_matrix(mod_h, mod_a, rho)
    p_model = probs_from_matrix(M)
    lam_h, lam_a = mod_h, mod_a
    p_final = dict(p_model)

    # ---- market layer (comparison only): implied O2.5 and market-implied expected goals from the reference odds
    oo, ou = fx["odds_over"], fx["odds_under"]
    if pd.notna(oo) and pd.notna(ou) and oo > 1 and ou > 1:
        p_mkt = (1 / oo) / (1 / oo + 1 / ou)
    else:
        p_mkt = float("nan")
    mk = market_lambdas(fx["odds_h"], fx["odds_d"], fx["odds_a"], oo, ou)
    if mk is not None:
        mkt_h, mkt_a = mk
    else:
        mkt_h = mkt_a = float("nan")
    hist = {
        "O15": float(np.nanmean([H.rate_o15, A.rate_o15])) if H.n and A.n else float("nan"),
        "O25": float(np.nanmean([H.rate_o25, A.rate_o25])) if H.n and A.n else float("nan"),
        "BTTS": float(np.nanmean([H.rate_btts, A.rate_btts])) if H.n and A.n else float("nan"),
    }
    row = MatchRow(fx, H, A, lam_h, lam_a, mod_h, mod_a, mkt_h, mkt_a, p_model, p_mkt, p_final, hist,
                   head_to_head(h2h_pool if h2h_pool is not None else results, fx["country"], fx["home"], fx["away"],
                                home_id=hid, away_id=aid), da)
    row.recent_form = recent
    if mk is not None:
        row.mkt_source = "reference odds (football-data.co.uk)"
    # ---- extra markets (v3): 1X2 / DC and team goals from the same model score matrix; corners, cards own models
    ex = row.extra
    row.scores = [[int(h), int(a), float(M[h, a])] for h, a in
                  sorted(np.ndindex(M.shape), key=lambda pos: (-M[pos], pos))[:5]]
    ex.x12 = markets.one_x_two(M)
    oh, od, oa = sharp_1x2(fx)
    if all(_ok(v) for v in (oh, od, oa)):
        mH, mD, mA = markets.power_demargin([oh, od, oa])
        row.x12_market = {"H": mH, "D": mD, "A": mA, "source": "reference odds"}
    ex.tg = markets.team_goals(M)
    row.model_signals = {"home": sig_h, "away": sig_a, "status": "experimental_unvalidated" if EXPERIMENTAL_MODEL_SIGNALS else "disabled_pending_backtest"}
    # corners / cards: main leagues from football-data; elsewhere from the archived Livescore match statistics once
    # both teams have enough matches with stats
    min_n = 0 if fx["source"] == "main" else CONFIG["WORLD_COUNT_MIN_N"]
    cm = MODELS.get("corners")
    if cm is not None:
        ex.corners = cm.expect(fx["country"], fx["home"], fx["away"], fx["div"])
        if ex.corners is not None and (ex.corners.h_n < min_n or ex.corners.a_n < min_n):
            ex.corners = None
        off = MODELS.get("shots_off")
        if EXPERIMENTAL_MODEL_SIGNALS and ex.corners is not None and off is not None:
            shot_exp = off.expect(fx["country"], fx["home"], fx["away"], fx["div"])
            if shot_exp is not None and shot_exp.h_n >= 5 and shot_exp.a_n >= 5 and str(fx["div"]) in off.div_avg:
                base_h, base_a = off._div(fx["div"])
                ex.corners.eh, ex.corners.ea, details = model_signals.corner_adjustment(
                    ex.corners.eh, ex.corners.ea, shot_exp.eh, shot_exp.ea, base_h, base_a)
                row.model_signals["corners"] = details
        ex.corner_p = markets.count_lines(ex.corners, markets.CORNERS)
    km = MODELS.get("cards")
    if km is not None:
        ex.cards = km.expect(fx["country"], fx["home"], fx["away"], fx["div"], fx.get("referee", "") or "")
        if ex.cards is not None and (ex.cards.h_n < min_n or ex.cards.a_n < min_n):
            ex.cards = None
        ex.card_p = markets.count_lines(ex.cards, markets.CARDS)
    so, su = sharp_ou(fx)
    ex.p_o25_fair = markets.fair_two_way(so, su)      # market-implied O2.5 from the reference odds (comparison only)
    return row


RECENT_FORM_ENABLED = os.getenv("RECENT_FORM_ENABLED", "1") == "1"
EXPERIMENTAL_MODEL_SIGNALS = os.getenv("EXPERIMENTAL_MODEL_SIGNALS", "0") == "1"
MODELS: dict = {}   # count models, built once per run in main()
SIGNAL_BASELINES: dict = {}


def _x12_form(matches: list[dict] | None) -> dict:
    """Recent W-D-L record, preserving the true denominator and ignoring malformed scores."""
    scores = []
    for match in (matches or [])[:rec_policy.X12_FORM_MATCHES]:
        try:
            gf, ga = match["gf"], match["ga"]
            if (isinstance(gf, bool) or isinstance(ga, bool) or not math.isfinite(float(gf))
                    or not math.isfinite(float(ga)) or int(gf) != float(gf) or int(ga) != float(ga)
                    or gf < 0 or ga < 0):
                continue
            scores.append((int(gf), int(ga)))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return {"n": len(scores), "w": sum(gf > ga for gf, ga in scores),
            "d": sum(gf == ga for gf, ga in scores), "l": sum(gf < ga for gf, ga in scores)}


def _x12_team_evidence(profile, ev: dict, venue: str) -> dict:
    composition = ev.get("composition") or {}
    share = composition.get("own_competition_share")
    if isinstance(share, bool) or not isinstance(share, (int, float)) or not math.isfinite(float(share)):
        share = None
    days = composition.get("days_since_last")
    if isinstance(days, bool) or not isinstance(days, int):
        days = None
    try:
        n_eff = float(getattr(profile, "n_eff", 0) or 0)
        n_eff = round(n_eff, 1) if math.isfinite(n_eff) else None
    except (TypeError, ValueError, OverflowError):
        n_eff = None
    friendlies = composition.get("friendlies_included")
    if isinstance(friendlies, bool) or not isinstance(friendlies, int) or friendlies < 0:
        friendlies = None
    return {
        "matches": int(getattr(profile, "n", 0) or 0),
        "effective_matches": n_eff,
        "venue": venue,
        "venue_matches": int(getattr(profile, "venue_n", 0) or 0),
        "days_since_last": days,
        "same_competition_share": round(float(share), 2) if share is not None else None,
        "friendlies_in_sample": friendlies,
        "last5": _x12_form(getattr(profile, "last5", None)),
        "venue_last5": _x12_form(getattr(profile, "venue_last5", None)),
    }


def build_x12_research(r: MatchRow, ev_h: dict, ev_a: dict, quality_data: dict) -> dict:
    """Build evidence-backed recommendation gates for the modelled 1X2 outcomes.

    Every outcome needs High data quality, complete/recent team and venue samples,
    and agreement with a complete de-margined 1X2 market. Straight wins also need
    supporting W-D-L form; draws need recent draw evidence from both teams. Raw
    probabilities remain visible as analysis even when a recommendation fails.
    """
    teams = {
        "home": _x12_team_evidence(r.home, ev_h, "home"),
        "away": _x12_team_evidence(r.away, ev_a, "away"),
    }
    common = []
    if not r.data_ok:
        common.append("match data checks did not pass")
    if (quality_data or {}).get("overall") != "High":
        common.append("overall data quality is not High")
    for side, evidence in teams.items():
        name = r.fx[side]
        if evidence["matches"] < rec_policy.X12_MIN_TEAM_MATCHES:
            common.append(f"{name}: fewer than {rec_policy.X12_MIN_TEAM_MATCHES} researched matches")
        if (evidence["effective_matches"] is None
                or evidence["effective_matches"] < rec_policy.X12_MIN_EFFECTIVE_MATCHES):
            common.append(f"{name}: insufficient time-weighted evidence")
        if evidence["venue_matches"] < rec_policy.X12_MIN_VENUE_MATCHES:
            common.append(f"{name}: fewer than {rec_policy.X12_MIN_VENUE_MATCHES} {evidence['venue']} matches")
        if (evidence["days_since_last"] is None
                or not 0 <= evidence["days_since_last"] <= rec_policy.X12_MAX_DAYS_SINCE_LAST):
            common.append(f"{name}: latest verified result is too old or unavailable")
        if (evidence["same_competition_share"] is None
                or evidence["same_competition_share"] < rec_policy.X12_MIN_COMPETITION_SHARE):
            common.append(f"{name}: insufficient evidence from this competition")
        if evidence["friendlies_in_sample"] is None:
            common.append(f"{name}: friendly count is unavailable, so friendlies are not verified absent")
        elif evidence["friendlies_in_sample"] > 0:
            common.append(f"{name}: friendlies remain in the research sample")
        if evidence["last5"]["n"] < rec_policy.X12_FORM_MATCHES:
            common.append(f"{name}: incomplete recent-results sample")
        if evidence["venue_last5"]["n"] < rec_policy.X12_FORM_MATCHES:
            common.append(f"{name}: incomplete recent {evidence['venue']} form sample")

    selections = {s.sel: s for s in safe_mod.selections(r) if s.sel in ("H", "D", "A")}
    outcomes = {}
    for code in ("H", "D", "A"):
        selection = selections.get(code)
        reasons = list(common)
        if selection is None:
            p = p_market = odds = None
            reasons.append("complete selection price data is unavailable")
        else:
            p, p_market, odds = selection.p, selection.p_sb, selection.odds
            if p < rec_policy.X12_MIN_PROBABILITY:
                reasons.append(f"model probability is below {rec_policy.X12_MIN_PROBABILITY:.0%}")
            if odds is None or not rec_policy.X12_MIN_ODDS <= odds <= rec_policy.X12_MAX_ODDS:
                reasons.append(f"SportyBet price is missing or outside {rec_policy.X12_MIN_ODDS:.2f}–{rec_policy.X12_MAX_ODDS:.2f}")
            if p_market is None:
                reasons.append("a complete de-margined 1X2 market is unavailable")
            elif abs(p - p_market) > rec_policy.X12_MAX_MARKET_GAP:
                reasons.append(f"model and de-margined market differ by more than {100 * rec_policy.X12_MAX_MARKET_GAP:.0f} percentage points")
            if odds is not None and p * odds < rec_policy.X12_MIN_MODEL_RETURN:
                reasons.append(f"model probability × price is below {rec_policy.X12_MIN_MODEL_RETURN:.2f}")

        form = None
        if code in ("H", "A"):
            own_side, opponent_side = ("home", "away") if code == "H" else ("away", "home")
            own, opponent = teams[own_side], teams[opponent_side]
            form = {"type": "win", "selected_team": {"overall": own["last5"], "venue": own["venue_last5"]},
                    "opponent": {"overall": opponent["last5"], "venue": opponent["venue_last5"]}}
            for label, own_form, opponent_form in (
                    ("recent", own["last5"], opponent["last5"]),
                    ("venue-specific recent", own["venue_last5"], opponent["venue_last5"])):
                if own_form["n"] >= rec_policy.X12_FORM_MATCHES and (
                        own_form["w"] < rec_policy.X12_FORM_MIN_WINS
                        or own_form["l"] > rec_policy.X12_FORM_MAX_LOSSES):
                    reasons.append(f"selected team lacks {label} backing ({rec_policy.X12_FORM_MIN_WINS} wins and at most {rec_policy.X12_FORM_MAX_LOSSES} loss from {rec_policy.X12_FORM_MATCHES} required)")
                if opponent_form["n"] >= rec_policy.X12_FORM_MATCHES and (
                        opponent_form["w"] > rec_policy.X12_OPPONENT_MAX_WINS):
                    reasons.append(f"opponent has too many {label} wins (at most {rec_policy.X12_OPPONENT_MAX_WINS} from {rec_policy.X12_FORM_MATCHES} required)")
        elif code == "D":
            form = {"type": "draw", "home": {"overall": teams["home"]["last5"], "venue": teams["home"]["venue_last5"]},
                    "away": {"overall": teams["away"]["last5"], "venue": teams["away"]["venue_last5"]}}
            for side in ("home", "away"):
                name = r.fx[side]
                for label, sample in (("recent", teams[side]["last5"]),
                                      ("venue-specific recent", teams[side]["venue_last5"])):
                    if (sample["n"] >= rec_policy.X12_FORM_MATCHES
                            and sample["d"] < rec_policy.X12_DRAW_MIN_DRAWS):
                        reasons.append(f"{name}: fewer than {rec_policy.X12_DRAW_MIN_DRAWS} draws in the last {rec_policy.X12_FORM_MATCHES} {label} matches")

        gap = (p - p_market) * 100 if p is not None and p_market is not None else None
        outcomes[code] = {
            "eligible": not reasons,
            "reasons": reasons,
            "model_probability": p,
            "market_probability": p_market,
            "market_gap_pp": round(gap, 1) if gap is not None else None,
            "odds": odds,
            "form": form,
        }
    return {"quality": (quality_data or {}).get("overall") or "N/A", "teams": teams,
            "outcomes": outcomes, "rules": rec_policy.X12_RULES}


def x12_research_eligible(r: MatchRow, sel: str) -> bool:
    report = getattr(r, "x12_research", None) or {}
    outcome = (report.get("outcomes") or {}).get(sel) or {}
    return outcome.get("eligible") is True


def build_audits(rows: list[MatchRow], now: datetime) -> None:
    """Fill MatchRow.audit: sample evidence of both teams, head-to-head strength, data quality, the lambda
    explanation, the market comparison layer and the automatic model-v-raw-data warnings."""
    n_fail = 0
    for r in rows:
        try:
            own_div = str(r.fx["div"])
            ev_h = quality.team_evidence(r.home, own_div, now)
            ev_a = quality.team_evidence(r.away, own_div, now)
            h2h = quality.h2h_evidence(r.h2h, now, r.recent_form)
            q = quality.data_quality(r, ev_h, ev_a, h2h, now)
            mkt = quality.market_layer(r)
            r.x12_research = build_x12_research(r, ev_h, ev_a, q)
            n_min = min(r.home.n, r.away.n)
            conf = {k: quality.confidence(r.p_model.get(k), q, n_min) for k in ("O15", "O25", "O35", "BTTS")}
            conf["X12"] = quality.confidence(r.extra.x12.get("H") if r.extra.x12 else None, q, n_min)
            conf["TG"] = quality.confidence(r.extra.tg.get("H_o05") if r.extra.tg else None, q, n_min)
            r.audit = {"evidence": {"home": ev_h, "away": ev_a}, "h2h": h2h, "quality": q, "confidence": conf,
                       "explain": quality.explanation(r, ev_h, ev_a, CONFIG), "market": mkt,
                       "warnings": quality.warnings_for(r, ev_h, ev_a, h2h, q, mkt, CONFIG)}
        except Exception as exc:  # noqa: BLE001
            n_fail += 1
            if n_fail <= 3:
                log.warning("Audit failed for %s: %s", r.label, exc)
            r.audit = {}
    if n_fail:
        log.warning("Audit failed for %d of %d matches", n_fail, len(rows))


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v)) and v > 1


def sharp_1x2(fx: pd.Series):
    """Best available reference prices for the 1X2 fair probability: Betfair Exchange, else market average."""
    if all(_ok(fx.get(c)) for c in ("bfe_h", "bfe_d", "bfe_a")):
        return fx["bfe_h"], fx["bfe_d"], fx["bfe_a"]
    return fx.get("odds_h"), fx.get("odds_d"), fx.get("odds_a")


def sharp_ou(fx: pd.Series):
    if all(_ok(fx.get(c)) for c in ("bfe_over", "bfe_under")):
        return fx["bfe_over"], fx["bfe_under"]
    return fx.get("odds_over"), fx.get("odds_under")


def attach_prices(rows: list[MatchRow], sbmap: dict, todays: pd.DataFrame) -> None:
    """Attach Sportybet prices to rows and complete the MARKET layer (comparison only).

    Nothing here touches a model probability. The market layer consists of: the de-margined Sportybet 1X2
    (x12_market), the market-implied probabilities of the shortlist markets (r.fair) and the market-implied
    expected goals (mkt_h / mkt_a) — taken from the feed's reference odds when present, else derived from the
    Sportybet 1X2 + Over/Under 2.5 prices.
    """
    for i, r in zip(todays.index, rows):
        ev = sbmap.get(i)
        if ev:
            r.sb_event = {k: ev[k] for k in ("id", "home", "away", "country", "tournament", "ko")}
            r.sb = ev["markets"]
        ex = r.extra
        sb = r.sb or {}
        sb1x2 = sb.get("1X2")
        ou = sb.get("OU", {}).get(2.5) if sb else None
        if sb1x2 and all(sb1x2):
            mH, mD, mA = markets.power_demargin(list(sb1x2))
            r.x12_market = {"H": mH, "D": mD, "A": mA, "source": "Sportybet"}
        # market-implied expected goals from Sportybet when the feed has no reference odds
        if math.isnan(r.mkt_h) and sb1x2 and all(sb1x2) and ou and ou[0] and ou[1]:
            mk = market_lambdas(sb1x2[0], sb1x2[1], sb1x2[2], ou[0], ou[1])
            if mk is not None:
                r.mkt_h, r.mkt_a = mk
                r.mkt_source = "Sportybet 1X2 + O/U 2.5"
        # market-implied probabilities of the shortlist markets (Sportybet first, else reference odds)
        fair_sb = markets.fair_two_way(ou[0], ou[1]) if ou and ou[0] and ou[1] else float("nan")
        r.fair = {"O25": fair_sb if not math.isnan(fair_sb) else ex.p_o25_fair}
        ou15 = sb.get("OU", {}).get(1.5) if sb else None
        r.fair["O15"] = markets.fair_two_way(ou15[0], ou15[1]) if ou15 and ou15[0] and ou15[1] else float("nan")
        btts = sb.get("BTTS") if sb else None
        r.fair["BTTS"] = markets.fair_two_way(btts[0], btts[1]) if btts and btts[0] and btts[1] else float("nan")


def avg_prices(fx: pd.Series) -> dict | None:
    """Illustrative reference prices only; derived DC values are not bookmaker quotes.

    Never use this for recommendation eligibility or parlay construction.
    """
    h, d, a = fx.get("odds_h"), fx.get("odds_d"), fx.get("odds_a")
    if not all(_ok(v) for v in (h, d, a)):
        return None
    dc = lambda o1, o2: 1 / (1 / o1 + 1 / o2)
    out = {"1X2": (h, d, a), "DC": {"1X": dc(h, d), "12": dc(h, a), "X2": dc(d, a)}}
    if _ok(fx.get("odds_over")) and _ok(fx.get("odds_under")):
        out["OU"] = {2.5: (fx["odds_over"], fx["odds_under"])}
    return out


def sb_price(r: MatchRow, mkt: str):
    """Sportybet price for a shortlist market (O15 / O25 / BTTS) or None."""
    if not r.sb:
        return None
    if mkt == "BTTS":
        return (r.sb.get("BTTS") or (None, None))[0]
    line = 1.5 if mkt == "O15" else 2.5
    return (r.sb.get("OU", {}).get(line) or (None, None))[0]


# ----------------------------------------------------------------------------- run schedule / parlays
def run_desc(label: str, tz: bool = False) -> str:
    """'run 07:00' / 'manual run 15:05' (+ timezone label)."""
    txt = f"manual run {label[7:]}" if str(label).startswith("manual") else f"run {label}"
    return f"{txt} {TZL}" if tz else txt


def run_schedule(now: datetime) -> tuple[str, datetime]:
    """(run label, window end). Runs close to a report hour (07/12/17) are the full-report runs and keep the
    plain 'HH:MM' label; the half-hourly refreshes in between are 'auto HH:MM'; dispatches are 'manual HH:MM'."""
    hours = CONFIG["RUN_HOURS"]
    todays = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in hours]
    event = os.getenv("GITHUB_EVENT_NAME", "")
    label = f"manual {now:%H:%M}" if event == "workflow_dispatch" or not event else f"auto {now:%H:%M}"
    # the first run within 90 min after a report hour that has not yet produced that report is the report run
    # (GitHub's cron is often 5-30 min late; a crashed run is retried by the next half-hourly one)
    done = _report_marks().get(now.strftime("%Y-%m-%d"), [])
    for t in todays:
        if -5 * 60 <= (now - t).total_seconds() <= 90 * 60 and f"{t:%H:%M}" not in done:
            label = f"{t:%H:%M}"
            break
    nxt = [t for t in todays if t > now + timedelta(minutes=20)]
    window_end = nxt[0] if nxt else (todays[0] + timedelta(days=1))
    return label, window_end


def is_report_run(label: str) -> bool:
    return not label.startswith(("auto", "manual"))


REPORT_MARKS_FILE = DATA_DIR / "report_marks.json"


def _report_marks() -> dict:
    try:
        return json.loads(REPORT_MARKS_FILE.read_text(encoding="utf-8")) if REPORT_MARKS_FILE.exists() else {}
    except Exception:
        return {}


def mark_report_run(now: datetime, label: str) -> None:
    """Remember that today's report for this hour went out (keeps the last 3 days)."""
    marks = _report_marks()
    day = now.strftime("%Y-%m-%d")
    marks.setdefault(day, [])
    if label not in marks[day]:
        marks[day].append(label)
    for k in sorted(marks)[:-3]:
        marks.pop(k, None)
    REPORT_MARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MARKS_FILE.write_text(json.dumps(marks, indent=1), encoding="utf-8")


def build_run_parlays(rows: list[MatchRow], now: datetime, window_end: datetime, sb_ok: bool) -> dict:
    """Legs from priced matches kicking off before the next run; whole window if too thin."""
    start = now + timedelta(minutes=10)
    # Feed-average odds (and synthetic double-chance prices derived from them)
    # are not actual SportyBet quotes and must not become recommended legs.
    source = "Sportybet"

    def legs_for(rs):
        legs = []
        for r in rs:
            if not r.data_ok:
                continue
            prices = r.sb if sb_ok else None
            if not prices:
                continue
            legs += [leg for leg in parlay_mod.candidate_legs(r.fx, r.extra.x12, r.p_model["O25"], prices, source)
                     if math.isfinite(leg.odds) and leg.odds >= safe_mod.MIN_ODDS]
        return legs

    short = [r for r in rows if start <= r.fx["kickoff"] <= window_end]
    legs = legs_for(short)
    extended = False
    if len({l.key for l in legs}) < CONFIG["PARLAY_MIN_MATCHES"]:
        legs = legs_for([r for r in rows if r.fx["kickoff"] >= start])
        extended = True
    lo, hi = CONFIG["PARLAY_ODDS"]
    built = parlay_mod.build_parlays(legs, lo, hi, CONFIG["PARLAYS_PER_RUN"])
    return {"parlays": built, "legs": legs, "extended": extended, "source": source,
            "n_matches": len({l.key for l in legs})}


def select_picks(rows: list[MatchRow]) -> dict[str, list[MatchRow]]:
    picks: dict[str, list[MatchRow]] = {}
    for mkt, thr in CONFIG["THRESHOLDS"].items():
        # backtest: team hit-rate floors and model-vs-market filters added nothing once the
        # probabilities were calibrated, so the rule is simply "final probability >= threshold"
        cand = [r for r in rows if r.data_ok and r.p_final[mkt] >= thr["p"]]
        cand.sort(key=lambda r: (-r.p_final[mkt], -int(h2h_evidence.row_preferred(r))))
        picks[mkt] = cand[: CONFIG["MAX_PICKS"]]
    return picks


# ----------------------------------------------------------------------------- tracker
TRACKER_COLS = ["match_date", "kickoff", "country", "div", "league", "home", "away", "market",
                "p_model", "p_market", "p_final", "odds", "status", "score", "total_goals",
                "settled_on", "report_date"]


def load_tracker() -> pd.DataFrame:
    if TRACKER_FILE.exists():
        t = pd.read_csv(TRACKER_FILE, dtype=str, keep_default_na=False)
        for c in TRACKER_COLS:
            if c not in t.columns:
                t[c] = ""
        return t[TRACKER_COLS]
    return pd.DataFrame(columns=TRACKER_COLS)


def settle_tracker(t: pd.DataFrame, results: pd.DataFrame, today: datetime) -> pd.DataFrame:
    if t.empty:
        return t
    t = t.copy()
    for i, r in t[t["status"] == "pending"].iterrows():
        mdate = pd.Timestamp(r["match_date"])
        if not results.empty:
            m = results[(results["home"] == r["home"]) & (results["away"] == r["away"]) &
                        (results["country"] == r["country"]) &
                        ((results["date"] - mdate).abs() <= pd.Timedelta(days=3))]
            if not m.empty:
                row = m.iloc[0]
                hg, ag = int(row["hg"]), int(row["ag"])
                total = hg + ag
                hit = {"O15": total >= 2, "O25": total >= 3, "BTTS": hg > 0 and ag > 0}[r["market"]]
                t.loc[i, ["status", "score", "total_goals", "settled_on"]] = [
                    "hit" if hit else "miss", f"{hg}-{ag}", str(total), today.strftime("%Y-%m-%d")]
                continue
        if (pd.Timestamp(today.date()) - mdate).days > 21:
            t.loc[i, ["status", "settled_on"]] = ["void", today.strftime("%Y-%m-%d")]
    return t


def add_picks(t: pd.DataFrame, picks: dict[str, list[MatchRow]], today: datetime) -> pd.DataFrame:
    existing = set(zip(t["match_date"], t["home"], t["away"], t["market"]))
    new = []
    for mkt, rows in picks.items():
        for r in rows:
            key = (r.fx["date"].strftime("%Y-%m-%d"), r.fx["home"], r.fx["away"], mkt)
            if key in existing:
                continue
            existing.add(key)
            # first-published price: O25 keeps its long-standing source; O15/BTTS record the
            # Sportybet price when available (presentation record only — never a model input)
            if mkt == "O25":
                odds = r.fx["odds_over"]
            else:
                sp = sb_price(r, mkt)
                odds = sp if sp is not None else float("nan")
            new.append({
                "match_date": key[0], "kickoff": r.fx["kickoff"].strftime("%Y-%m-%d %H:%M"),
                "country": r.fx["country"], "div": r.fx["div"], "league": r.fx["league"],
                "home": r.fx["home"], "away": r.fx["away"], "market": mkt,
                "p_model": f"{r.p_model[mkt]:.3f}",
                "p_market": "" if math.isnan(r.p_market_o25) or mkt != "O25" else f"{r.p_market_o25:.3f}",
                "p_final": f"{r.p_final[mkt]:.3f}",
                "odds": "" if pd.isna(odds) else f"{odds:.2f}",
                "status": "pending", "score": "", "total_goals": "", "settled_on": "",
                "report_date": today.strftime("%Y-%m-%d"),
            })
    if new:
        t = pd.concat([t, pd.DataFrame(new, columns=TRACKER_COLS)], ignore_index=True)
    return t


def tracker_summary(t: pd.DataFrame, today: datetime) -> dict:
    out = {}
    if t.empty:
        return out
    recent_cut = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    # overall live record (all tracked picks) — presentation of the tracker, no model input
    settled_all = t[t["status"].isin(["hit", "miss"])]
    wins_all = int((settled_all["status"] == "hit").sum())
    w_odds = settled_all[settled_all["odds"].astype(str).str.strip() != ""]
    odds_n = len(w_odds)
    if odds_n:
        od = pd.to_numeric(w_odds["odds"], errors="coerce").dropna()
        won = (w_odds.loc[od.index, "status"] == "hit").astype(float)
        profit_units = float((od * won).sum() - len(od))
        out["overall"] = {"settled": len(settled_all), "wins": wins_all, "losses": len(settled_all) - wins_all,
                          "pending": int((t["status"] == "pending").sum()), "void": int((t["status"] == "void").sum()),
                          "hit_rate": wins_all / len(settled_all),
                          "roi": profit_units / len(od) if len(od) else float("nan"),
                          "profit_units": profit_units, "odds_n": odds_n,
                          "first_date": str(t["report_date"].min())}
    else:
        out["overall"] = {"settled": len(settled_all), "wins": wins_all, "losses": len(settled_all) - wins_all,
                          "pending": int((t["status"] == "pending").sum()), "void": int((t["status"] == "void").sum()),
                          "hit_rate": wins_all / len(settled_all) if len(settled_all) else float("nan"),
                          "roi": float("nan"), "profit_units": 0.0, "odds_n": 0,
                          "first_date": str(t["report_date"].min())}
    # shortlist-class report card: primary = ⭐⭐⭐ tier, watchlist = ⭐⭐ tier (frozen thresholds, read-only)
    classes = {}
    for cls in ("primary", "watchlist"):
        rows = []
        for mkt, cfg in CONFIG["THRESHOLDS"].items():
            t2, t3 = cfg["tiers"]
            lo, hi = (t3, 2.0) if cls == "primary" else (t2, t3)
            s = t[(t["market"] == mkt) & (pd.to_numeric(t["p_final"], errors="coerce") >= lo) &
                  (pd.to_numeric(t["p_final"], errors="coerce") < hi)]
            rows.append(s)
        c = pd.concat(rows, ignore_index=True) if rows else t.iloc[0:0]
        c_settled = c[c["status"].isin(["hit", "miss"])]
        c_hits = int((c_settled["status"] == "hit").sum())
        c_odds = pd.to_numeric(c_settled["odds"].astype(str).str.strip().replace("", "nan"), errors="coerce").dropna()
        c_roi = None
        if len(c_odds):
            c_won = (c_settled.loc[c_odds.index, "status"] == "hit").astype(float)
            c_roi = float((c_odds * c_won).sum() - len(c_odds)) / len(c_odds)
        classes[cls] = {"n": len(c_settled),
                        "hit_rate": (c_hits / len(c_settled)) if len(c_settled) else None,
                        "expected": (float(pd.to_numeric(c_settled["p_final"], errors="coerce").mean())
                                     if len(c_settled) else None),
                        "roi": c_roi, "pending": int((c["status"] == "pending").sum())}
    out["classes"] = classes
    # most recent ledger rows (newest first) for the advisor's selection ledger
    rec = t.sort_values(["report_date", "match_date"], ascending=False).head(20)
    out["recent"] = [{"home": r["home"], "away": r["away"], "market": r["market"],
                      "odds": (None if str(r["odds"]).strip() == "" else float(r["odds"])),
                      "match_date": str(r["match_date"]), "status": r["status"],
                      "score": (str(r["score"]) if str(r["score"]).strip() not in ("", "nan") else None)}
                     for _, r in rec.iterrows()]
    for mkt in MARKETS:
        s = t[t["market"] == mkt]
        settled = s[s["status"].isin(["hit", "miss"])]
        hits = int((settled["status"] == "hit").sum())
        rec = settled[settled["match_date"] >= recent_cut]
        rec_hits = int((rec["status"] == "hit").sum())
        info = {"settled": len(settled), "hits": hits,
                "rate": hits / len(settled) if len(settled) else float("nan"),
                "recent_settled": len(rec), "recent_hits": rec_hits,
                "recent_rate": rec_hits / len(rec) if len(rec) else float("nan"),
                "pending": int((s["status"] == "pending").sum()),
                "avg_odds": float("nan"), "roi": float("nan")}
        if mkt == "O25":
            with_odds = settled[settled["odds"] != ""]
            if len(with_odds):
                odds = pd.to_numeric(with_odds["odds"], errors="coerce")
                won = (with_odds["status"] == "hit").astype(float)
                info["avg_odds"] = float(odds.mean())
                info["roi"] = float(((odds * won).sum() - len(with_odds)) / len(with_odds))
        out[mkt] = info
    return out


# ----------------------------------------------------------------------------- rendering
def ko(r: MatchRow) -> str:
    k = r.fx["kickoff"]
    return k.strftime("%a %d %b %H:%M") if r.fx["time_known"] else k.strftime("%a %d %b (time TBC)")


def comp(r: MatchRow) -> str:
    return f"{r.fx['country']} · {r.fx['league']}"


def form_str(r: MatchRow, mkt: str) -> str:
    H, A = r.home, r.away
    attr = {"O15": "last_o15", "O25": "last_o25", "BTTS": "last_btts"}[mkt]
    return f"H {getattr(H, attr)}/{H.last_n} · A {getattr(A, attr)}/{A.last_n}"


def market_str(r: MatchRow) -> str:
    if math.isnan(r.p_market_o25):
        return "–"
    return f"{fmt_odds(r.fx['odds_over'])} ({pct(r.p_market_o25)})"


def basis_str(r: MatchRow) -> str:
    """Data-quality label of the match (the probability itself is always the football-data model)."""
    q = (r.audit or {}).get("quality") or {}
    return {"High": "🟢 High", "Medium": "🟡 Medium", "Low": "🔴 Low"}.get(q.get("overall"), "–")


def market_pct(r: MatchRow, mkt: str) -> str:
    """Market-implied probability of a shortlist market (comparison only)."""
    p = (r.fair or {}).get(mkt)
    if p is None or math.isnan(p):
        return "–"
    return pct(p)


def render_pick_table(rows: list[MatchRow], mkt: str) -> list[str]:
    L = []
    if not rows:
        L.append("_No match met the criteria today._")
        return L
    if mkt == "O25":
        L.append(f"| # | Kick-off ({TZL}) | Competition | Match | Model | Rating | Market (odds) | Market implied | Data quality | Last-10 form | Model xG |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(rows, 1):
            L.append(f"| {i} | {ko(r)} | {comp(r)} | **{r.label}** | **{pct(r.p_model['O25'])}** | {stars(r.p_model['O25'], mkt)} | "
                     f"{market_str(r)} | {market_pct(r, 'O25')} | {basis_str(r)} | {form_str(r, mkt)} | "
                     f"{r.mod_h:.1f} – {r.mod_a:.1f} |")
    else:
        L.append(f"| # | Kick-off ({TZL}) | Competition | Match | Model | Rating | Market implied | Data quality | Last-10 form | Model xG |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(rows, 1):
            L.append(f"| {i} | {ko(r)} | {comp(r)} | **{r.label}** | **{pct(r.p_model[mkt])}** | "
                     f"{stars(r.p_model[mkt], mkt)} | {market_pct(r, mkt)} | {basis_str(r)} | {form_str(r, mkt)} | "
                     f"{r.mod_h:.1f} – {r.mod_a:.1f} |")
    return L


def render_tracker(summary: dict) -> list[str]:
    L = ["| Market | Settled | Hits | Hit rate | Last 30 days | Pending | Avg odds | Flat-stake return |",
         "|---|---|---|---|---|---|---|---|"]
    if not summary:
        L.append("| – | 0 | 0 | – | – | 0 | – | – |")
        return L
    for mkt, name in MARKETS.items():
        s = summary.get(mkt)
        if not s:
            continue
        recent = f"{s['recent_hits']}/{s['recent_settled']} ({pct(s['recent_rate'])})" if s["recent_settled"] else "–"
        roi = "–" if math.isnan(s["roi"]) else f"{100 * s['roi']:+.1f}%"
        L.append(f"| {name} | {s['settled']} | {s['hits']} | {pct(s['rate'])} | {recent} | {s['pending']} | "
                 f"{f2(s['avg_odds'])} | {roi} |")
    return L


def render_team_block(p: TeamProfile, venue_label: str) -> list[str]:
    L = [f"**{p.name}** ({venue_label}) — {p.n} matches used (weighted {p.n_eff:.1f}), {p.venue_n} {venue_label.lower()}",
         "", "| Stat | Value |", "|---|---|",
         f"| Goals for / against per game | {f2(p.gf)} / {f2(p.ga)} |",
         f"| {venue_label} goals for / against | {f2(p.venue_gf)} / {f2(p.venue_ga)} |",
         f"| Attack / defence strength (1.00 = league avg) | {f2(p.att)} / {f2(p.dfc)} |",
         f"| Over 1.5 / 2.5 / 3.5 rate | {pct(p.rate_o15)} / {pct(p.rate_o25)} / {pct(p.rate_o35)} |",
         f"| BTTS rate | {pct(p.rate_btts)} |",
         f"| Clean sheets / failed to score | {pct(p.rate_cs)} / {pct(p.rate_fts)} |",
         f"| Avg total goals, last 5 | {f2(p.form5_goals)} |"]
    if not math.isnan(p.xg_for):
        L.append(f"| xG for / against (last 10) | {f2(p.xg_for)} / {f2(p.xg_against)} |")
    if not math.isnan(p.sot_for):
        L.append(f"| Shots on target for / against (last 10) | {p.sot_for:.1f} / {p.sot_against:.1f} |")
    if p.last5:
        parts = []
        for m in p.last5:
            res = "W" if m["gf"] > m["ga"] else ("L" if m["gf"] < m["ga"] else "D")
            parts.append(f"{res} {m['gf']}-{m['ga']} {'v' if m['venue'] == 'H' else '@'} {m['opp']}")
        L.append(f"| Last 5 | {' · '.join(parts)} |")
    L.append("")
    return L


def render_details(r: MatchRow) -> list[str]:
    L = [f"<details><summary><b>{html.escape(r.label)}</b> — {html.escape(comp(r))}, {ko(r)} · "
         f"O2.5 {pct(r.p_final['O25'])} · BTTS {pct(r.p_final['BTTS'])}"
         f"{'' if r.data_ok else ' · ⚠️ low data'}</summary>", ""]
    q = (r.audit or {}).get("quality") or {}
    conf = (r.audit or {}).get("confidence") or {}
    L.append(f"* **Model xG {r.mod_h:.2f} – {r.mod_a:.2f}** (total {r.mod_h + r.mod_a:.2f}, football data only) · "
             f"P(O1.5) **{pct(r.p_model['O15'])}** · P(O2.5) **{pct(r.p_model['O25'])}** · P(O3.5) {pct(r.p_model['O35'])} · "
             f"P(BTTS) **{pct(r.p_model['BTTS'])}** · confidence {conf.get('O25', 'N/A')}")
    L.append(f"* Market xG: " + (f"{r.mkt_h:.2f} – {r.mkt_a:.2f} (total {r.mkt_h + r.mkt_a:.2f}, {r.mkt_source}; comparison only, not a model input)"
                                 if not math.isnan(r.mkt_h) else "N/A (no market prices)")
             + f" · Data quality **{q.get('overall', 'N/A')}** ({q.get('score', 'N/A')}) · samples {r.home.n} / {r.away.n} matches "
               f"({quality.evidence_label(r.home.n)} / {quality.evidence_label(r.away.n)})")
    for w in ((r.audit or {}).get("warnings") or [])[:6]:
        L.append(f"* {'⚠️' if w['level'] == 'warn' else 'ℹ️'} {html.escape(w['text'])}")
    sqd = getattr(r, "squad", None) or {}
    if sqd.get("home") or sqd.get("away"):
        h_, a_ = sqd.get("home") or {}, sqd.get("away") or {}
        L.append(f"* Squad value (Transfermarkt): {html.escape(r.fx['home'])} **{squads_mod.fmt_value(h_.get('value'))}**"
                 f"{' (avg age ' + str(h_.get('avg_age')) + ')' if h_.get('avg_age') else ''} · {html.escape(r.fx['away'])} "
                 f"**{squads_mod.fmt_value(a_.get('value'))}**{' (avg age ' + str(a_.get('avg_age')) + ')' if a_.get('avg_age') else ''}")
    if not math.isnan(r.p_market_o25):
        L.append(f"* Market: Over 2.5 @ {fmt_odds(r.fx['odds_over'])} / Under 2.5 @ {fmt_odds(r.fx['odds_under'])} "
                 f"(implied O2.5 {pct(r.p_market_o25)}) · 1X2 {fmt_odds(r.fx['odds_h'])} / {fmt_odds(r.fx['odds_d'])} / {fmt_odds(r.fx['odds_a'])}")
    elif pd.notna(r.fx["odds_h"]):
        L.append(f"* Market 1X2: {fmt_odds(r.fx['odds_h'])} / {fmt_odds(r.fx['odds_d'])} / {fmt_odds(r.fx['odds_a'])} (no O/U odds published in feed)")
    L.append(f"* League context: avg {r.div_avg.mu_h:.2f} home + {r.div_avg.mu_a:.2f} away goals · "
             f"O2.5 in {pct(r.div_avg.o25_rate)} · BTTS in {pct(r.div_avg.btts_rate)} of matches")
    L += render_extra_lines(r)
    L.append("")
    L += render_team_block(r.home, "Home")
    L += render_team_block(r.away, "Away")
    if r.h2h:
        parts = [f"{m['date']:%d %b %y}: {m['home']} {m['hg']}-{m['ag']} {m['away']}" for m in r.h2h]
        tot = [m["hg"] + m["ag"] for m in r.h2h]
        L.append(f"**Head-to-head** (last {len(r.h2h)}): avg {np.mean(tot):.1f} goals, "
                 f"O2.5 in {sum(t >= 3 for t in tot)}/{len(tot)}, "
                 f"BTTS in {sum(m['hg'] > 0 and m['ag'] > 0 for m in r.h2h)}/{len(tot)}  ")
        L.append("; ".join(parts))
    else:
        L.append("_No head-to-head data in the last two seasons._")
    L += ["", "</details>", ""]
    return L


def fmt_odds(o) -> str:
    return "–" if o is None or not math.isfinite(o) or o < safe_mod.MIN_ODDS else f"{o:.2f}"


def sb_line_str(d: dict | None, lines=None) -> str:
    """'O8.5 1.45/2.60 · O9.5 1.85/1.90' from a Sportybet {line: (over, under)} dict."""
    if not d:
        return "–"
    parts = []
    for line in sorted(d):
        if lines and line not in lines:
            continue
        o, u = d[line]
        parts.append(f"O{line:g} {fmt_odds(o)} / U {fmt_odds(u)}")
    return " · ".join(parts) if parts else "–"


def render_extra_lines(r: MatchRow) -> list[str]:
    ex = r.extra
    L = []
    if ex.x12:
        x = ex.x12
        L.append(f"* **1X2** (fair, {x.get('source', 'model')}): home {pct(x['H'])} · draw {pct(x['D'])} · away {pct(x['A'])} → "
                 f"fair odds {1 / x['H']:.2f} / {1 / x['D']:.2f} / {1 / x['A']:.2f} · "
                 f"**Double chance** 1X {pct(x['1X'])} · 12 {pct(x['12'])} · X2 {pct(x['X2'])}")
    if ex.tg:
        t = ex.tg
        L.append(f"* **Team goals:** {r.fx['home']} to score {pct(t['H_o05'])} (2+ {pct(t['H_o15'])}) · "
                 f"{r.fx['away']} to score {pct(t['A_o05'])} (2+ {pct(t['A_o15'])})")
    if ex.corners is not None:
        c, cp = ex.corners, ex.corner_p
        tot = " · ".join(f"O{l:g} **{pct(p)}**" for l, p in cp["total"].items())
        L.append(f"* **Corners:** expected {c.eh:.1f} (home) + {c.ea:.1f} (away) = **{c.total:.1f}** · total {tot} · "
                 f"home " + " · ".join(f"O{l:g} {pct(p)}" for l, p in cp["home"].items()) + " · away " +
                 " · ".join(f"O{l:g} {pct(p)}" for l, p in cp["away"].items()) +
                 f" _(team averages: {r.fx['home']} {c.h_for:.1f} for / {c.h_against:.1f} against over {c.h_n} games, "
                 f"{r.fx['away']} {c.a_for:.1f} / {c.a_against:.1f} over {c.a_n})_")
    if ex.cards is not None:
        k, kp = ex.cards, ex.card_p
        tot = " · ".join(f"O{l:g} **{pct(p)}**" for l, p in kp["total"].items())
        ref = ""
        if k.ref_n > 0:
            ref = f" · referee {r.fx.get('referee', '')} factor {k.ref_factor:.2f} ({k.ref_n:.0f} weighted games)"
        L.append(f"* **Cards** (yellow + red): expected {k.eh:.1f} + {k.ea:.1f} = **{k.total:.1f}** · total {tot}{ref} "
                 f"_(team averages: {r.fx['home']} {k.h_for:.1f} received / {k.h_against:.1f} opponents booked, "
                 f"{r.fx['away']} {k.a_for:.1f} / {k.a_against:.1f})_")
    if r.sb:
        sb = r.sb
        parts = []
        if sb.get("1X2") and any(sb["1X2"]):
            parts.append("1X2 " + " / ".join(fmt_odds(o) for o in sb["1X2"]))
        if sb.get("DC"):
            parts.append("DC 1X/12/X2 " + " / ".join(fmt_odds(sb["DC"].get(k)) for k in ("1X", "12", "X2")))
        if sb.get("OU"):
            parts.append("goals " + sb_line_str(sb["OU"], (1.5, 2.5, 3.5)))
        if sb.get("BTTS"):
            parts.append(f"BTTS {fmt_odds(sb['BTTS'][0])} / {fmt_odds(sb['BTTS'][1])}")
        if sb.get("TGH"):
            parts.append(f"{r.fx['home']} goals " + sb_line_str(sb["TGH"], (0.5, 1.5)))
        if sb.get("TGA"):
            parts.append(f"{r.fx['away']} goals " + sb_line_str(sb["TGA"], (0.5, 1.5)))
        L.append("* **Sportybet:** " + " · ".join(parts))
        full = r.sb_full or {}
        parts = []
        if full.get("CORN"):
            parts.append("total corners " + sb_line_str(full["CORN"], (8.5, 9.5, 10.5, 11.5)))
        if full.get("CORNH"):
            parts.append("home corners " + sb_line_str(full["CORNH"], (3.5, 4.5, 5.5)))
        if full.get("CORNA"):
            parts.append("away corners " + sb_line_str(full["CORNA"], (3.5, 4.5, 5.5)))
        if full.get("CORN1H"):
            parts.append("1st-half corners " + sb_line_str(full["CORN1H"]) + " _(no model — market only)_")
        if full.get("CARDS"):
            parts.append("total cards " + sb_line_str(full["CARDS"], (3.5, 4.5, 5.5)))
        if parts:
            L.append("* **Sportybet corners / cards:** " + " · ".join(parts))
    return L


def leg_row(l: parlay_mod.Leg) -> str:
    flag = " ⚠️ price moved vs reference — check team news" if l.ev > 0.08 else ""
    return (f"| {l.kickoff[5:]} | **{l.match}** | {l.league} | **{l.label}** | **{l.odds:.2f}** | {l.fair_odds:.2f} | "
            f"{pct(l.p)} | {100 * l.ev:+.1f}%{flag} |")


def render_parlays(ctx: dict, pr: dict, ids: list[str], psum: dict) -> list[str]:
    lo, hi = CONFIG["PARLAY_ODDS"]
    L = [f"## 🎟️ Parlays — {run_desc(ctx['run'])} · combined odds {lo:.2f}–{hi:.2f}", ""]
    src = pr["source"]
    win = f"kick-offs before the next run ({ctx['window_end']:%a %H:%M} {TZL})"
    if pr["extended"]:
        win = f"whole 24 h window (fewer than {CONFIG['PARLAY_MIN_MATCHES']} priced matches before the next run)"
    L.append(f"_Prices: **{src}**{' — Sportybet was unreachable, average market prices used' if src != 'Sportybet' else ''}. "
             f"Window: {win}. {pr['n_matches']} priced matches, {len(pr['legs'])} candidate legs. "
             f"Legs are limited to 1X2, double chance and Over/Under 2.5 — markets with real prices. "
             f"Each parlay maximises estimated return (model probability × price) inside the odds band._")
    L.append("")
    if not pr["parlays"]:
        L.append("_No parlay could be built inside the odds band for this window._")
        L.append("")
        return L
    for i, pl in enumerate(pr["parlays"], 1):
        odds, p = parlay_mod.parlay_odds(pl), parlay_mod.parlay_p(pl)
        pid = ids[i - 1] if i - 1 < len(ids) else ""
        L.append(f"### Parlay {i} — {len(pl)} legs @ **{odds:.2f}** · win probability **{pct(p)}** · "
                 f"expected return {100 * (p * odds - 1):+.1f}% · id `{pid}`")
        L.append("")
        L.append("| Kick-off | Match | Competition | Selection | Price | Fair odds | Probability | Leg edge |")
        L.append("|---|---|---|---|---|---|---|---|")
        for l in pl:
            L.append(leg_row(l))
        L.append("")
    a, d30 = psum.get("all", {}), psum.get("30d", {})
    if a.get("n"):
        L.append(f"**Parlay record:** {a['won']}/{a['n']} won ({pct(a['rate'])}, expected {pct(a['exp_rate'])}) · "
                 f"flat-stake return {100 * a['roi']:+.1f}% · last 30 days {d30.get('won', 0)}/{d30.get('n', 0)} "
                 f"({pct(d30.get('rate', float('nan')))}, {100 * d30['roi']:+.1f}%)" if d30.get("n") else
                 f"**Parlay record:** {a['won']}/{a['n']} won ({pct(a['rate'])}, expected {pct(a['exp_rate'])}) · "
                 f"flat-stake return {100 * a['roi']:+.1f}%")
    else:
        L.append(f"**Parlay record:** no settled parlays yet ({psum.get('pending', 0)} pending).")
    L.append("")
    L.append(f"> ⚠️ Honest expectation: a parlay at ~{(lo + hi) / 2:.1f} needs to win about 1 in 3 to break even. "
             "In the 2023-26 backtest this exact construction won 30-33% of the time and returned −4% to −13% "
             "per unit at average prices — the bookmaker margin compounds across legs. Treat parlays as "
             "entertainment with a known cost, not as income. Full test: `backtest/PARLAY_EXPERIMENT.md`.")
    L.append("")
    return L


def render_safest(ctx: dict) -> list[str]:
    sf = ctx.get("safe") or {}
    if not sf:
        return []
    L = [f"## 📈 High-probability selections — {run_desc(ctx['run'])}", ""]
    L.append(f"_1X2, goals and corners selections whose **football-data model** probability is at least {pct(sf['min_p'])} "
             f"(the de-margined Sportybet price is shown for comparison and only excludes a selection when it contradicts the model by "
             f"a wide margin) at a Sportybet price of {sf['min_odds']:.2f} or more, ranked by model probability. "
             f"A 75% probability still loses about one time in four. Graded automatically (`data/safe_bets.csv`)._")
    L.append("")
    groups = ctx.get("botd_groups") or []
    if groups:
        L.append(f"### ⭐ Bets of the day — {ctx['now']:%A %d %B}")
        L.append("")
        L.append(f"_1X2 ≥70% and Over 2.5 ≥55% require supporting form; Over 1.5 ≥70%, corners ≥65%. "
                 f"Sportybet price ≥ {safe_mod.MIN_ODDS:.2f}; one market per match. Probabilities are model-only; "
                 "the market view is a comparison and disagreement check._")
        L.append("")
        icon = {"hit": "✅ hit", "miss": "❌ miss", "pending": "⏳", "void": "void"}
        for g in groups:
            L.append(f"**{g['title']}** — {len(g['bets'])} pick(s)")
            L.append("")
            L.append("| Kick-off | Match | Competition | Selection | Price | Model % | Data quality | Status |")
            L.append("|---|---|---|---|---|---|---|---|")
            qmap = sf.get("quality") or {}
            for b in g["bets"]:
                q = qmap.get((b["kickoff"][:10], b.get("country"), b["home"], b["away"])) or "–"
                L.append(f"| {b['kickoff'][11:]} | **{b['home']} v {b['away']}** | {b['league']} | **{b['label']}** | "
                         f"**{b['odds']:.2f}** | {pct(b['p'])} | {q} | {icon.get(b['status'], b['status'])} |")
            L.append("")
    bets = sf.get("bets") or []
    L.append(f"### High-probability singles (model ≥70%, price ≥{safe_mod.MIN_ODDS:.2f}) — top {min(len(bets), 25)} of {len(bets)}")
    L.append("")
    if bets:
        L.append("| Kick-off | Match | Competition | Selection | Price | Model % | Market implied % | Diff (pp) | Data quality |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        qmap = sf.get("quality") or {}
        for b in bets[:25]:
            diff = None if b.p_sb is None else 100 * (b.p_model - b.p_sb)
            L.append(f"| {b.kickoff[5:]} | {b.home} v {b.away} | {b.league} | **{b.label}** | **{b.odds:.2f}** | **{pct(b.p_model)}** | "
                     f"{pct(b.p_sb) if b.p_sb is not None else '–'} | {f'{diff:+.1f}' if diff is not None else '–'} | "
                     f"{qmap.get(b.key) or '–'} |")
    else:
        L.append("_Nothing priced met the rules in this window._")
    L.append("")
    ss = ctx.get("safe_summary") or {}
    ba = (ss.get("bets") or {}).get("all") or {}
    bd = (ss.get("botd") or {}).get("all") or {}
    if ba.get("n"):
        L.append(f"_Track record — high-probability selections: {ba.get('won', 0)}/{ba.get('n', 0)} hit ({pct(ba['rate'])}, expected {pct(ba['exp_rate'])})"
                 f"{'; bets of the day: ' + str(bd.get('won', 0)) + '/' + str(bd.get('n', 0)) + ' hit' if bd.get('n') else ''}._")
        L.append("")
    return L


def render_value_check(picks: dict, sb_ok: bool) -> list[str]:
    L = ["## 💰 Sportybet price check — shortlisted picks", ""]
    if not sb_ok:
        L.append("_Sportybet prices were not available for this run._")
        L.append("")
        return L
    L.append("_Model % = football-data model. Implied % = Sportybet price with the margin removed. Difference = model − market "
             "in percentage points. EV = model % × price − 1. The market is a comparison layer only — it never feeds the "
             "model, and the backtest showed model-v-market disagreement is not a reliable value signal on its own._")
    L.append("")
    L.append("| Market | Match | Kick-off | Model % | Sportybet | Implied % | Difference | EV |")
    L.append("|---|---|---|---|---|---|---|---|")
    n = 0
    for mkt, name in MARKETS.items():
        for r in picks.get(mkt, []):
            price = sb_price(r, mkt)
            p = r.p_model[mkt]
            if price is None or not math.isfinite(price) or price < safe_mod.MIN_ODDS or p is None or math.isnan(p) or p <= 0:
                continue
            n += 1
            pm = (r.fair or {}).get(mkt)
            ev = p * price - 1
            flag = "model > market" if ev > 0.02 else ("≈ agree" if ev > -0.03 else "market > model")
            L.append(f"| {name} | **{r.label}** | {r.fx['kickoff']:%a %H:%M} | {pct(p)} | **{price:.2f}** | "
                     f"{'–' if pm is None or math.isnan(pm) else pct(pm)} | "
                     f"{'–' if pm is None or math.isnan(pm) else f'{100 * (p - pm):+.0f} pp'} | {100 * ev:+.1f}% {flag} |")
    if n == 0:
        L.append("| – | _no shortlisted pick is priced at Sportybet yet_ | | | | | |")
    L.append("")
    return L


def render_other_markets(rows: list[MatchRow]) -> list[str]:
    L = ["## 🧾 Other markets — 1X2, double chance, team goals, corners, cards", ""]
    if not rows:
        return L + ["_No fixtures._", ""]
    L.append("_Probabilities use the football-data model and count models. The new xG/shot adjustments are experimental and unvalidated; "
             "card counts do not match verified SportyBet booking rules and are not recommendations. Sportybet column = 1X2 prices._")
    L.append("")
    L.append(f"| Kick-off ({TZL}) | Match | Competition | Home / Draw / Away | 1X / X2 | Home to score / 2+ | "
             f"Away to score / 2+ | Corners exp. (O9.5 · O10.5) | Cards exp. (O3.5 · O4.5) | Sportybet 1X2 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: (r.fx["kickoff"], comp(r))):
        x, t, c, k = r.extra.x12, r.extra.tg, r.extra.corners, r.extra.cards
        cp, kp = r.extra.corner_p, r.extra.card_p
        corners = f"{c.total:.1f} ({pct(cp['total'][9.5])} · {pct(cp['total'][10.5])})" if c is not None else "–"
        cards = f"{k.total:.1f} ({pct(kp['total'][3.5])} · {pct(kp['total'][4.5])})" if k is not None else "–"
        sb = " / ".join(fmt_odds(o) for o in r.sb["1X2"]) if r.sb and r.sb.get("1X2") and any(r.sb["1X2"]) else "–"
        L.append(f"| {ko(r)} | **{r.label}** | {comp(r)} | {pct(x['H'])} / {pct(x['D'])} / {pct(x['A'])} | "
                 f"{pct(x['1X'])} / {pct(x['X2'])} | {pct(t['H_o05'])} / {pct(t['H_o15'])} | {pct(t['A_o05'])} / {pct(t['A_o15'])} | "
                 f"{corners} | {cards} | {sb} |")
    L.append("")
    return L


def render_parlay_history(psum: dict, rec: list[dict]) -> list[str]:
    L = ["### Parlay ledger", ""]
    a = psum.get("all", {})
    if not a.get("n") and not rec:
        pend = psum.get("pending", 0)
        L.append(f"_No settled parlays yet — {pend} pending (graded automatically once the results are in)._"
                 if pend else "_No parlays recorded yet._")
        L.append("")
        return L
    L.append("| Scope | Settled | Won | Hit rate | Expected | Avg odds | Flat-stake return |")
    L.append("|---|---|---|---|---|---|---|")
    for name, st in (("All time", psum.get("all", {})), ("Last 30 days", psum.get("30d", {}))):
        if st.get("n"):
            L.append(f"| {name} | {st['n']} | {st['won']} | {pct(st['rate'])} | {pct(st['exp_rate'])} | {f2(st['avg_odds'])} | {100 * st['roi']:+.1f}% |")
        else:
            L.append(f"| {name} | 0 | 0 | – | – | – | – |")
    for run, st in sorted(psum.get("by_run", {}).items()):
        if st.get("n"):
            L.append(f"| Run {run} | {st['n']} | {st['won']} | {pct(st['rate'])} | {pct(st['exp_rate'])} | {f2(st['avg_odds'])} | {100 * st['roi']:+.1f}% |")
    L.append("")
    if rec:
        L.append("| Id | Created | Run | Legs | Odds | Prob. | Status |")
        L.append("|---|---|---|---|---|---|---|")
        icon = {"won": "✅ won", "lost": "❌ lost", "pending": "⏳ pending", "void": "void"}
        for x in rec:
            legs = "; ".join(f"{l.match} — {l.label} @ {l.odds:.2f}" for l in x["legs"])
            L.append(f"| `{x['id']}` | {x['created']} | {x['run']} | {legs} | {x['odds']} | {pct(float(x['p']))} | {icon.get(x['status'], x['status'])} |")
        L.append("")
    return L


def render_report(ctx: dict, rows: list[MatchRow], picks: dict, summary: dict, notes: list[str]) -> str:
    now = ctx["now"]
    L = [f"# ⚽ PlayReport — {now:%A %d %B %Y}", ""]
    comps = {comp(r) for r in rows}
    L.append(f"**{run_desc(ctx.get('run', ''), True).capitalize()}** · scan window {ctx['start']:%a %d %b %H:%M} → {ctx['end']:%a %d %b %H:%M} · "
             f"**{len(rows)} fixtures** across **{len(comps)} competitions** · generated {now:%H:%M} {TZL} · "
             f"next run {ctx['window_end']:%a %H:%M}")
    L.append("")
    if notes:
        L.append("> " + "  \n> ".join(notes))
        L.append("")
    if ctx.get("digest"):
        L += ctx["digest"]
    L += render_safest(ctx)

    L.append("## 🎯 Shortlist")
    L.append("")
    for mkt, name in MARKETS.items():
        thr = CONFIG["THRESHOLDS"][mkt]
        L.append(f"### {name} — {len(picks.get(mkt, []))} pick(s)")
        L.append(f"_Rule: final probability ≥ {pct(thr['p'])} (⭐⭐ ≥ {pct(thr['tiers'][0])}, ⭐⭐⭐ ≥ {pct(thr['tiers'][1])}). "
                 f"Previous baseline backtest 2025/26–26/27 (not the current experimental signals): {CONFIG['BACKTEST'][mkt]}._")
        L.append("")
        L += render_pick_table(picks.get(mkt, []), mkt)
        L.append("")

    cap = CONFIG["REPORT_MAX_ROWS"]
    ranked = sorted([r for r in rows if r.data_ok], key=lambda r: r.p_final["O25"], reverse=True)
    L.append(f"## 📊 Full scan — top {min(cap, len(ranked))} of {len(rows)} fixtures by Over 2.5 probability")
    L.append("")
    if ranked:
        L.append(f"| Kick-off ({TZL}) | Competition | Match | Model xG | Market xG | O1.5 | O2.5 | BTTS | Market O2.5 (odds) | Data quality | O2.5 last-10 form |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in ranked[:cap]:
            L.append(f"| {ko(r)} | {comp(r)} | {r.label} | {r.mod_h:.1f} – {r.mod_a:.1f} | "
                     f"{'–' if math.isnan(r.mkt_h) else f'{r.mkt_h:.1f} – {r.mkt_a:.1f}'} | {pct(r.p_model['O15'])} | "
                     f"**{pct(r.p_model['O25'])}** | {pct(r.p_model['BTTS'])} | {market_str(r)} | "
                     f"{basis_str(r)} | {form_str(r, 'O25')} |")
        if len(rows) > cap:
            L.append("")
            L.append(f"_{len(rows) - cap} more fixtures (including {sum(1 for r in rows if not r.data_ok)} with too little history) are in the PlayReport app._")
    else:
        L.append("_No fixtures found in the scan window._")
    L.append("")

    L += render_value_check(picks, bool(ctx.get("sb_ok")))
    # match dossiers: bets of the day first, then the safest bets, then the ⭐⭐⭐ / ⭐⭐ shortlist picks — capped so
    # the PDF stays readable (everything else is one tap away in the app)
    key_of = lambda r: (r.fx["date"].strftime("%Y-%m-%d"), r.fx["country"], r.fx["home"], r.fx["away"])  # noqa: E731
    priority: dict[tuple, int] = {}
    for b in ctx.get("botd") or []:
        priority.setdefault((str(b.get("kickoff", ""))[:10], b.get("country"), b.get("home"), b.get("away")), 0)
    for i, b in enumerate((ctx.get("safe") or {}).get("bets") or []):
        priority.setdefault(b.key, 100 + i)
    for mkt, m in picks.items():
        for i, r in enumerate(m):
            n_stars = len(stars(r.p_final[mkt], mkt))
            priority.setdefault(key_of(r), 1000 + i - 100 * n_stars)
    focus_all = [r for r in rows if key_of(r) in priority]
    focus = sorted(focus_all, key=lambda r: priority[key_of(r)])[:CONFIG.get("DETAIL_MAX", 20)]
    L += render_other_markets([r for r in focus if r.fx["source"] == "main"] or focus[:cap])

    if focus:
        L.append(f"## 🔍 Match details — {len(focus)} key matches (bets of the day, high-probability selections, top shortlist picks)")
        L.append("")
        if len(focus_all) > len(focus):
            L.append(f"_{len(focus_all) - len(focus)} more shortlisted matches have their full analysis in the PlayReport app._")
            L.append("")
        for r in sorted(focus, key=lambda r: (r.fx["kickoff"], comp(r))):
            L += render_details(r)

    L.append("## 📈 Trackers (auto-settled from results)")
    L.append("")
    L.append("### Shortlist tracker")
    L.append("")
    L += render_tracker(summary)
    L.append("")
    L.append("_Flat-stake return is for model evaluation only: 1 unit on every Over 2.5 pick at the average market odds._")
    L.append("")

    L.append("## ℹ️ Method")
    L.append("")
    L += [
        "* **Football-data model (data-first):** every probability comes from football statistics only — goals scored and "
        "conceded over the last 40 matches (max 400 days, friendlies excluded when enough competitive matches exist), "
        f"normalised by competition averages, time-weighted (half-life {CONFIG['HALF_LIFE_DAYS']} days), venue-blended and "
        f"shrunk towards the league average (team strength K={CONFIG['SHRINK_K_STRENGTH']:g}, goal tempo K={CONFIG['SHRINK_K']:g} "
        "weighted matches). Expected goals = league venue average × attack × opponent defence; bounded experimental xG/xGA and shots adjustments are "
        + ("enabled by explicit opt-in and unvalidated" if EXPERIMENTAL_MODEL_SIGNALS else "disabled pending point-in-time validation") + "; probabilities for goal markets "
        f"come from a Dixon-Coles adjusted Poisson score matrix (ρ={CONFIG['DC_RHO']:g}).",
        "* **Market layer (separate):** bookmaker prices are de-margined and shown next to the model as implied probability, "
        "difference in percentage points and EV, and as market-implied expected goals. They never feed the model and the "
        "model is not tuned to agree with them.",
        "* **Evidence & data quality:** every statistic carries its sample size (Very small 1–4, Small 5–9, Moderate 10–19, "
        "Strong 20–39, Very strong 40+); each match has a transparent data-quality assessment (completeness, sample, recency, "
        "consistency, competition, home/away relevance, source) that drives the confidence wording, never the probability. "
        "Missing data is shown as N/A, never as zero. Historical frequency (what happened) is always labelled apart from "
        "model probability and market implied.",
        "* **Historical baseline backtest (52,000 matches, 2023-26):** describes an earlier configuration, not a point-in-time validation of this version. "
        "Experimental signals and recent history-integrity changes need an untouched, availability-verified holdout; do not assume the old calibration applies. `backtest/RESULTS.md`.",
        "* **Extra markets:** 1X2 / double chance and team goals = the same model score matrix. "
        "Corners and cards = team for/against rates, league-normalised and shrunk (K=40 / K=20), negative binomial "
        "totals; cards include a referee factor where the referee is published (UK leagues). The old count baselines were backtested "
        "(`backtest/MARKETS_RESULTS.md`); the new off-target adjustment is unvalidated. Card-count probabilities are not SportyBet booking recommendations. Half-time corners have no free data "
        "source and are shown as Sportybet prices only, without a model.",
        "* **World coverage:** senior men's domestic leagues on Livescore.com are analysed with the same "
        "team-form model from Livescore's season results (goals markets only; corners and cards need the richer "
        "football-data feed of the 22 main European leagues). Sportybet's de-margined prices are the market view there.",
        f"* **High-probability selections** = 1X2, goals, BTTS and corners selections with model probability ≥70%, "
        f"priced {safe_mod.MIN_ODDS:.2f} or better, with large model–market disagreements excluded. "
        "**Bets of the day** prioritise 1X2 (≥70%, supporting form), then Over 2.5 (≥55%, supporting form), "
        "Over 1.5 (≥70%), corners (≥65%) and BTTS (≥55%), one market per match. Historical selections remain in the record.",
        "* **Sportybet prices** never enter the probability model; they are the market view shown next to it.",
        f"* Data: football-data.co.uk, Livescore.com. All times are {TZL} ({CONFIG['TIMEZONE']}). ⚠️ marks teams with too little history "
        "— they are never shortlisted.",
        "* This is statistical information, not advice. Past hit-rates do not guarantee future results.",
    ]
    L.append("")
    return "\n".join(L)


def render_readme_block(ctx: dict, rows: list[MatchRow], picks: dict, summary: dict, report_rel: str) -> str:
    now = ctx["now"]
    L = [f"### Latest scan — {now:%A %d %B %Y} ({now:%H:%M} {TZL})", "",
         f"{len(rows)} fixtures scanned · window {ctx['start']:%a %H:%M} → {ctx['end']:%a %H:%M} {TZL} · "
         f"[open full report]({report_rel})", ""]
    for mkt, name in MARKETS.items():
        sel = picks.get(mkt, [])
        L.append(f"**{name}** — {len(sel)} pick(s)")
        L.append("")
        if sel:
            L.append("| Kick-off | Match | Competition | Final prob. | Rating |")
            L.append("|---|---|---|---|---|")
            for r in sel[:8]:
                L.append(f"| {ko(r)} | **{r.label}** | {comp(r)} | {pct(r.p_final[mkt])} | "
                         f"{stars(r.p_final[mkt], mkt)} |")
            if len(sel) > 8:
                L.append(f"| … | _{len(sel) - 8} more in the full report_ | | | |")
        else:
            L.append("_None met the criteria._")
        L.append("")
    pr = ctx.get("parlays") or {}
    if pr:
        L.append(f"**Parlays ({run_desc(ctx.get('run', ''))}, {pr['source']})** — see [dossier]({report_rel.replace('.md', '-parlays.md')})")
        L.append("")
        for i, pl in enumerate(pr["parlays"], 1):
            legs = "; ".join(f"{l.match} — {l.label} @ {l.odds:.2f}" for l in pl)
            L.append(f"{i}. @ **{parlay_mod.parlay_odds(pl):.2f}** (P {pct(parlay_mod.parlay_p(pl))}): {legs}")
        if not pr["parlays"]:
            L.append("_none possible in this window_")
        L.append("")
    L.append("**Tracker**")
    L.append("")
    L += render_tracker(summary)
    L.append("")
    L += render_parlay_history(ctx.get("parlay_summary", {}), [])
    return "\n".join(L)


def update_readme(block: str) -> None:
    start, end = "<!-- SCAN:START -->", "<!-- SCAN:END -->"
    text = README_FILE.read_text(encoding="utf-8") if README_FILE.exists() else f"# Goals Scanner\n\n{start}\n{end}\n"
    if start in text and end in text:
        pre, rest = text.split(start, 1)
        _, post = rest.split(end, 1)
        text = f"{pre}{start}\n{block}\n{end}{post}"
    else:
        text = f"{text.rstrip()}\n\n{start}\n{block}\n{end}\n"
    README_FILE.write_text(text, encoding="utf-8")


def rows_to_csv(rows: list[MatchRow], path: Path) -> None:
    recs = []
    for r in rows:
        fx = r.fx
        recs.append({
            "kickoff": fx["kickoff"].strftime("%Y-%m-%d %H:%M"), "country": fx["country"],
            "competition": fx["league"], "div": fx["div"], "home": fx["home"], "away": fx["away"],
            "xg_home_model": round(r.mod_h, 3), "xg_away_model": round(r.mod_a, 3),
            "xg_home_market": None if math.isnan(r.mkt_h) else round(r.mkt_h, 3),
            "xg_away_market": None if math.isnan(r.mkt_a) else round(r.mkt_a, 3),
            "xg_market_source": r.mkt_source or None,
            "data_quality": ((r.audit or {}).get("quality") or {}).get("overall"),
            "data_quality_score": ((r.audit or {}).get("quality") or {}).get("score"),
            "sample_home": r.home.n, "sample_away": r.away.n,
            "p_over15": round(r.p_final["O15"], 3), "p_over25": round(r.p_final["O25"], 3),
            "p_over35": round(r.p_final["O35"], 3), "p_btts": round(r.p_final["BTTS"], 3),
            "p_model_over15": round(r.p_model["O15"], 3), "p_model_over25": round(r.p_model["O25"], 3),
            "p_model_btts": round(r.p_model["BTTS"], 3),
            "odds_over25_avg": fx["odds_over"], "odds_under25_avg": fx["odds_under"],
            "odds_over25_b365": fx["b365_over"], "odds_under25_b365": fx["b365_under"],
            "p_market_over25": None if math.isnan(r.p_market_o25) else round(r.p_market_o25, 3),
            "odds_home": fx["odds_h"], "odds_draw": fx["odds_d"], "odds_away": fx["odds_a"],
            "home_matches": r.home.n, "home_gf": r.home.gf, "home_ga": r.home.ga,
            "home_att": r.home.att, "home_def": r.home.dfc, "home_o15_rate": r.home.rate_o15,
            "home_o25_rate": r.home.rate_o25, "home_btts_rate": r.home.rate_btts,
            "home_cs_rate": r.home.rate_cs, "home_fts_rate": r.home.rate_fts,
            "home_last10_o25": f"{r.home.last_o25}/{r.home.last_n}",
            "home_xg_for": r.home.xg_for, "home_xg_against": r.home.xg_against,
            "away_matches": r.away.n, "away_gf": r.away.gf, "away_ga": r.away.ga,
            "away_att": r.away.att, "away_def": r.away.dfc, "away_o15_rate": r.away.rate_o15,
            "away_o25_rate": r.away.rate_o25, "away_btts_rate": r.away.rate_btts,
            "away_cs_rate": r.away.rate_cs, "away_fts_rate": r.away.rate_fts,
            "away_last10_o25": f"{r.away.last_o25}/{r.away.last_n}",
            "away_xg_for": r.away.xg_for, "away_xg_against": r.away.xg_against,
            "league_avg_home_goals": r.div_avg.mu_h, "league_avg_away_goals": r.div_avg.mu_a,
            "league_o25_rate": r.div_avg.o25_rate, "h2h_matches": len(r.h2h),
            "h2h_avg_goals": np.mean([m["hg"] + m["ag"] for m in r.h2h]) if r.h2h else None,
            "data_ok": r.data_ok,
            "p_home": r.extra.x12.get("H"), "p_draw": r.extra.x12.get("D"), "p_away": r.extra.x12.get("A"),
            "p_home_scores": r.extra.tg.get("H_o05"), "p_away_scores": r.extra.tg.get("A_o05"),
            "exp_corners_home": r.extra.corners.eh if r.extra.corners else None,
            "exp_corners_away": r.extra.corners.ea if r.extra.corners else None,
            "p_corners_over95": r.extra.corner_p["total"][9.5] if r.extra.corner_p else None,
            "exp_cards_home": r.extra.cards.eh if r.extra.cards else None,
            "exp_cards_away": r.extra.cards.ea if r.extra.cards else None,
            "p_cards_over45": r.extra.card_p["total"][4.5] if r.extra.card_p else None,
            "sportybet_home": r.sb["1X2"][0] if r.sb and r.sb.get("1X2") else None,
            "sportybet_draw": r.sb["1X2"][1] if r.sb and r.sb.get("1X2") else None,
            "sportybet_away": r.sb["1X2"][2] if r.sb and r.sb.get("1X2") else None,
            "sportybet_over25": sb_price(r, "O25"), "sportybet_btts": sb_price(r, "BTTS"),
        })
    frame = pd.DataFrame(recs)
    rounded = frame.round(3)
    # Keep the exact bookmaker quotes so the app never rounds a sub-1.16 price into eligibility.
    for col in frame.columns:
        if col.startswith(("odds_", "sportybet_")):
            rounded[col] = frame[col]
    rounded.to_csv(path, index=False)


def render_dossier(ctx: dict, pr: dict, ids: list[str], rows_by_key: dict, headlines: dict) -> str:
    """Parlay dossier: every parlay, then the full data sheet of every match involved (+ headlines)."""
    now = ctx["now"]
    L = [f"# 🎟️ Parlay dossier — {now:%A %d %B %Y}, {run_desc(ctx['run'], True)}", ""]
    lo, hi = CONFIG["PARLAY_ODDS"]
    L.append(f"_{len(pr['parlays'])} parlay(s) · combined odds {lo:.2f}–{hi:.2f} · prices: {pr['source']} · "
             f"generated {now:%H:%M} {TZL}. Full method and the honest backtest warning are in the main report._")
    L.append("")
    if not pr["parlays"]:
        L.append("_No parlay could be built for this window._")
        return "\n".join(L)
    L.append("## Summary")
    L.append("")
    for i, pl in enumerate(pr["parlays"], 1):
        odds, p = parlay_mod.parlay_odds(pl), parlay_mod.parlay_p(pl)
        pid = ids[i - 1] if i - 1 < len(ids) else ""
        L.append(f"### Parlay {i} — {len(pl)} legs @ **{odds:.2f}** · win probability **{pct(p)}** · "
                 f"expected return {100 * (p * odds - 1):+.1f}% · id `{pid}`")
        L.append("")
        L.append("| Kick-off | Match | Competition | Selection | Price | Fair odds | Probability | Leg edge |")
        L.append("|---|---|---|---|---|---|---|---|")
        for l in pl:
            L.append(leg_row(l))
        L.append("")
    L.append("## Match data sheets")
    L.append("")
    seen = set()
    for i, pl in enumerate(pr["parlays"], 1):
        for l in pl:
            if l.key in seen:
                continue
            seen.add(l.key)
            r = rows_by_key.get(l.key)
            if r is None:
                continue
            L.append(f"### {r.label} — {comp(r)}, {ko(r)} (parlay {i}: {l.label} @ {l.odds:.2f})")
            L.append("")
            L.append(f"* Model xG **{r.mod_h:.2f} – {r.mod_a:.2f}** (football data only) · P(O1.5) {pct(r.p_final['O15'])} · "
                     f"P(O2.5) **{pct(r.p_final['O25'])}** · P(O3.5) {pct(r.p_final['O35'])} · P(BTTS) **{pct(r.p_final['BTTS'])}**"
                     + (f" · Sportybet O2.5 {fmt_odds(sb_price(r, 'O25'))} / BTTS {fmt_odds(sb_price(r, 'BTTS'))}" if r.sb else ""))
            L.append((f"* Market xG {r.mkt_h:.2f} – {r.mkt_a:.2f} (comparison only)" if not math.isnan(r.mkt_h) else "* Market xG N/A")
                     + f" · league avg {r.div_avg.mu_h:.2f} + {r.div_avg.mu_a:.2f} goals, O2.5 in {pct(r.div_avg.o25_rate)}")
            if pd.notna(r.fx.get("odds_h")):
                L.append(f"* Market average 1X2 {fmt_odds(r.fx['odds_h'])} / {fmt_odds(r.fx['odds_d'])} / {fmt_odds(r.fx['odds_a'])}"
                         + (f" · O/U 2.5 {fmt_odds(r.fx['odds_over'])} / {fmt_odds(r.fx['odds_under'])}" if pd.notna(r.fx.get("odds_over")) else "")
                         + (f" · Betfair Exchange 1X2 {fmt_odds(r.fx['bfe_h'])} / {fmt_odds(r.fx['bfe_d'])} / {fmt_odds(r.fx['bfe_a'])}" if pd.notna(r.fx.get("bfe_h")) else ""))
            L += render_extra_lines(r)
            L.append("")
            L += render_team_block(r.home, "Home")
            L += render_team_block(r.away, "Away")
            if r.h2h:
                parts = [f"{m['date']:%d %b %y}: {m['home']} {m['hg']}-{m['ag']} {m['away']}" for m in r.h2h]
                tot = [m["hg"] + m["ag"] for m in r.h2h]
                L.append(f"**Head-to-head** (last {len(r.h2h)}): avg {np.mean(tot):.1f} goals, O2.5 in {sum(t >= 3 for t in tot)}/{len(tot)}, "
                         f"BTTS in {sum(m['hg'] > 0 and m['ag'] > 0 for m in r.h2h)}/{len(tot)}  ")
                L.append("; ".join(parts))
                L.append("")
            for team in (r.fx["home"], r.fx["away"]):
                hs = headlines.get(team) or []
                L.append(f"**{team} — recent headlines** _(Google News, context only, not used by the model)_")
                L.append("")
                if hs:
                    for h in hs:
                        when = h["when"].astimezone(now.tzinfo).strftime("%d %b") if h.get("when") else ""
                        L.append(f"* {when} · {h['source']}: {h['title']}")
                else:
                    L.append("* _no recent headlines found_")
                L.append("")
    return "\n".join(L)


def weekly_digest(tracker: pd.DataFrame, ledger: pd.DataFrame, now: datetime) -> list[str]:
    """Monday digest: last 7 days + all time for the shortlists and parlays."""
    L = ["## 📅 Weekly digest", ""]
    cut = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    L.append("| Market | Last 7 days | Hit rate | All time | Hit rate | Previous baseline backtest (not current) |")
    L.append("|---|---|---|---|---|---|")
    for mkt, name in MARKETS.items():
        s = tracker[(tracker["market"] == mkt) & tracker["status"].isin(["hit", "miss"])] if not tracker.empty else tracker
        wk = s[s["match_date"] >= cut] if not s.empty else s
        h_all, h_wk = int((s["status"] == "hit").sum()) if not s.empty else 0, int((wk["status"] == "hit").sum()) if not wk.empty else 0
        L.append(f"| {name} | {h_wk}/{len(wk)} | {pct(h_wk / len(wk)) if len(wk) else '–'} | {h_all}/{len(s)} | "
                 f"{pct(h_all / len(s)) if len(s) else '–'} | {CONFIG['BACKTEST'][mkt].split(' of')[0]} |")
    ps = parlay_mod.summary(ledger, now)
    wk = ledger[(ledger["created"] >= cut)] if not ledger.empty else ledger
    wks = parlay_mod._stats(wk)
    a = ps["all"]
    L.append(f"| Parlays | {wks['won']}/{wks['n']} | {pct(wks['rate'])} | {a['won']}/{a['n']} | {pct(a['rate'])} | "
             f"30-33% wins, −4% to −13% return |")
    L.append("")
    if a["n"]:
        L.append(f"Parlay flat-stake return: last 7 days {100 * wks['roi']:+.1f}% · all time {100 * a['roi']:+.1f}% "
                 f"(avg odds {f2(a['avg_odds'])}, model expected {pct(a['exp_rate'])} wins vs actual {pct(a['rate'])}).")
        L.append("")
    return L


def digest_text(lines: list[str]) -> str:
    """Plain-text version of the digest for Telegram."""
    out = ["📅 <b>Weekly digest</b>"]
    for ln in lines:
        if ln.startswith("|") and not ln.startswith("|---"):
            cells = [c.strip().replace("**", "") for c in ln.strip("|").split("|")]
            if cells[0] == "Market":
                continue
            out.append(f"• {html.escape(cells[0])}: week {cells[1]} ({cells[2]}), all {cells[3]} ({cells[4]})")
        elif ln and not ln.startswith("#") and not ln.startswith("|"):
            out.append(html.escape(ln))
    return "\n".join(out)


def send_telegram_document(path: Path, caption: str) -> bool:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat or not path.exists():
        return False
    try:
        with open(path, "rb") as fh:
            r = SESSION.post(f"https://api.telegram.org/bot{token}/sendDocument", data={"chat_id": chat, "caption": caption[:1000]},
                             files={"document": (f"playreport-{path.name}" if not path.name.startswith("playreport") else path.name, fh, "application/pdf" if path.suffix == ".pdf" else "text/csv" if path.suffix == ".csv" else "text/plain")}, timeout=60)
        if r.status_code != 200:
            log.warning("Telegram document error %s: %s", r.status_code, r.text[:200])
            return False
        log.info("Telegram: document sent (%s, %d KB)", path.name, path.stat().st_size // 1024)
        return True
    except (requests.RequestException, OSError) as exc:
        log.warning("Telegram document failed: %s", exc)
        return False


def telegram_text(ctx: dict, rows: list[MatchRow], picks: dict, report_url: str | None) -> str:
    now = ctx["now"]
    cov = ctx.get("coverage") or {}
    L = [f"⚽ <b>PlayReport — {now:%a %d %b}, {run_desc(ctx.get('run', ''))}</b>",
         f"{len(rows)} fixtures · {cov.get('competitions', 0)} competitions · {cov.get('priced', 0)} priced by Sportybet · times in {TZL}"]
    groups = ctx.get("botd_groups") or []
    if groups:
        L.append("")
        L.append(f"⭐ <b>Bets of the day</b>")
        icon = {"hit": "✅", "miss": "❌", "pending": "", "void": "⚪"}
        for g in groups:
            L.append(f"<u>{html.escape(g['title'])}</u>")
            for b in g["bets"]:
                L.append(f"• {b['kickoff'][11:]} {html.escape(b['home'])} v {html.escape(b['away'])} — <b>{html.escape(b['label'])}</b> "
                         f"@ {b['odds']:.2f} · {pct(b['p'])} {icon.get(b['status'], '')}")
    sf = ctx.get("safe") or {}
    bets = sf.get("bets") or []
    L.append("")
    L.append(f"📈 <b>High-probability selections</b> (model ≥{pct(sf.get('min_p', 0.7))}, market not contradicting, price ≥ {sf.get('min_odds', 1.3):.2f}) — {len(bets)}")
    if not bets:
        L.append("nothing priced met the rules in this window")
    for b in bets[:12]:
        L.append(f"• {b.kickoff[5:]} {html.escape(b.home)} v {html.escape(b.away)} — <b>{html.escape(b.label)}</b> @ {b.odds:.2f} · {pct(b.p)}")
    if len(bets) > 12:
        L.append(f"… +{len(bets) - 12} more in the app")
    for mkt, name in MARKETS.items():
        sel = picks.get(mkt, [])
        L.append("")
        L.append(f"<b>{name}</b> ({len(sel)})")
        if not sel:
            L.append("none today")
        for r in sel[:6]:
            L.append(f"• {r.fx['kickoff']:%H:%M} {html.escape(r.label)} — {html.escape(r.fx['league'])} — "
                     f"<b>{pct(r.p_final[mkt])}</b> {stars(r.p_final[mkt], mkt)}")
        if len(sel) > 6:
            L.append(f"… +{len(sel) - 6} more")
    if report_url:
        L += ["", f'<a href="{report_url}">Full report</a>']
    return "\n".join(L)


def alert_text(new_bets: list, now: datetime) -> str:
    L = [f"🎯 <b>New high-probability selection{'s' if len(new_bets) > 1 else ''}</b> · {now:%a %H:%M} {TZL}"]
    for b in new_bets[:10]:
        L.append(f"• {b.kickoff[5:]} {html.escape(b.home)} v {html.escape(b.away)} ({html.escape(b.league)}) — "
                 f"<b>{html.escape(b.label)}</b> @ {b.odds:.2f} · {pct(b.p)}")
    if len(new_bets) > 10:
        L.append(f"… +{len(new_bets) - 10} more in the app")
    return "\n".join(L)


def send_telegram(text: str) -> None:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        log.info("Telegram not configured – skipping push")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3800:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    chunks.append(cur)
    for c in chunks:
        try:
            r = SESSION.post(url, json={"chat_id": chat, "text": c, "parse_mode": "HTML",
                                        "disable_web_page_preview": True}, timeout=20)
            if r.status_code != 200:
                log.warning("Telegram error %s: %s", r.status_code, r.text[:200])
            else:
                log.info("Telegram: message sent (%d chars)", len(c))
        except requests.RequestException as exc:
            log.warning("Telegram failed: %s", exc)


def strong_signal(r: MatchRow, sel: str) -> bool:
    """Evidence backing for every 1X2 outcome and Over 2.5; other day-card markets need no extra signal."""
    H, A = r.home, r.away
    if sel in ("H", "D", "A"):
        return x12_research_eligible(r, sel)
    if sel == "BTTS":
        return H.last_n >= 6 and A.last_n >= 6 and H.last_btts / H.last_n >= 0.6 and A.last_btts / A.last_n >= 0.6 \
            and (H.venue_rate_btts >= 0.5 if H.venue_rate_btts == H.venue_rate_btts else True)
    if sel in ("O25", "O35"):
        return H.last_n >= 6 and A.last_n >= 6 and H.last_o25 / H.last_n >= 0.6 and A.last_o25 / A.last_n >= 0.6 \
            and (r.lam_h + r.lam_a) >= 2.9
    return True


def promote_publication(staging: Path, live: Path, now: datetime) -> None:
    """Move a checked staging export into the live app directory (files replaced one by one; the staging copy is
    complete and valid, so a half-written publication is never picked up by the workflow's commit)."""
    live.mkdir(parents=True, exist_ok=True)
    (live / "fx").mkdir(parents=True, exist_ok=True)
    for name in ("latest.json", "meta.json", "alerts.json", "badges.json"):
        src = staging / name
        if src.exists():
            os.replace(src, live / name)
    fx_src = staging / "fx"
    if fx_src.exists():
        for f in fx_src.glob("*.json"):
            os.replace(f, live / "fx" / f.name)
    # detail files of matches older than the history window are removed from the live directory (the file names are
    # hashes, so the match date inside each file decides; file times are meaningless after a fresh checkout)
    keep = {f.name for f in fx_src.glob("*.json")} if fx_src.exists() else set()
    cutoff = (now - timedelta(days=appdata.KEEP_DETAIL_DAYS)).strftime("%Y-%m-%d")
    removed = 0
    for f in (live / "fx").glob("*.json"):
        if f.name in keep:
            continue
        try:
            with f.open("rb") as fh:
                head = fh.read(4096).decode("utf-8", "ignore")
            m = re.search(r'"date":\s*"(\d{4}-\d{2}-\d{2})"', head)
            if m is None or m.group(1) < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    if removed:
        log.info("Detail files pruned: %d older than %s", removed, cutoff)


# ----------------------------------------------------------------------------- main
def all_sels(r: MatchRow) -> list[dict]:
    """Every modelled selection of a match as plain dicts (probability views + Sportybet price), best first."""
    sels = sorted(safe_mod.selections(r), key=lambda s: (-s.p, -(s.odds or 0)))
    return [safe_mod.sel_dict(s, r.fx["home"], r.fx["away"]) for s in sels]


def top_sels(r: MatchRow) -> list[dict]:
    """The three best priced selections for day history; 1X2 requires its research gate."""
    out = [d for d in all_sels(r) if d["odds"] and d["odds"] >= safe_mod.MIN_ODDS and not d["diff"]
           and rec_policy.allowed(d["sel"])
           and (d["sel"] not in ("H", "D", "A") or x12_research_eligible(r, d["sel"]))
           and not rec_policy.outlier(d.get("p_model"), d.get("p_sb"), d["odds"])]
    return [{"sel": d["sel"], "label": d["label"], "p": d["p"], "odds": d["odds"]} for d in out[:3]]


def require_publication(ctx: dict) -> None:
    """Do not let a successful scan workflow publish stale or incomplete app data."""
    if not (ctx.get("data_check") or {}).get("ok"):
        raise RuntimeError("App publication failed; refusing to publish incomplete state")


def analyse_fixtures(fixtures, evidence, long, results, div_avgs, now, pool):
    """Analyse every fixture; H2H sample evidence is optional context only."""
    rows = []
    for i, fx in fixtures.iterrows():
        row = analyse(fx, long, results, div_avgs, now, pool)
        row.h2h_evidence = evidence.get(i, {'status': 'unavailable', 'meetings': None})
        rows.append(row)
    return rows


def filter_botd_by_current_rows(card, rows):
    """Keep sticky day-card picks in current rows; stale 1X2 picks must still pass research."""
    rows_by_key = {(r.fx["date"].strftime("%Y-%m-%d"), r.fx["country"], r.fx["home"], r.fx["away"]): r for r in rows}
    def eligible(b):
        key = (str(b.get("kickoff") or "")[:10], b.get("country"), b.get("home"), b.get("away"))
        row = rows_by_key.get(key)
        return (competition_policy.allows_record(b) and row is not None
                and (b.get("sel") not in ("H", "D", "A") or x12_research_eligible(row, b.get("sel"))))
    card["bets"] = [b for b in card.get("bets", []) if eligible(b)]
    for group in card.get("groups", []):
        group["bets"] = [b for b in group.get("bets", []) if eligible(b)]
    return card


def filter_pending_alerts(alerts, rows, now):
    """Do not re-announce old upcoming alerts outside the current analysed fixture set."""
    allowed = {appdata.fixture_id(r.fx["date"].strftime("%Y-%m-%d"), r.fx["country"],
                                  r.fx["home"], r.fx["away"]) for r in rows}
    cutoff = now.replace(tzinfo=None)
    kept = []
    for alert in alerts:
        try:
            kickoff = datetime.strptime(str(alert.get("kickoff") or ""), "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            continue
        if kickoff <= cutoff or alert.get("fixture") in allowed:
            kept.append(alert)
    return kept


def main() -> None:
    if RECENT_FORM_ENABLED and EXPERIMENTAL_MODEL_SIGNALS:
        raise ValueError("Recent form and experimental model signals cannot be combined; disable one explicitly")
    tz = ZoneInfo(CONFIG["TIMEZONE"])
    override = os.getenv("SCAN_NOW")  # e.g. "2026-09-26 07:00" for testing
    now = datetime.strptime(override, "%Y-%m-%d %H:%M").replace(tzinfo=tz) if override else datetime.now(tz)
    tz_off = int(now.utcoffset().total_seconds() // 3600)
    start = now - timedelta(minutes=5)
    end = now + timedelta(days=CONFIG["COVER_DAYS"])
    app_end = now + timedelta(hours=CONFIG["APP_WINDOW_HOURS"])
    run_label, window_end = run_schedule(now)
    report_run = is_report_run(run_label)
    ctx = {"now": now, "start": start, "end": end, "app_start": start, "app_end": app_end, "run": run_label, "window_end": window_end}
    log.info("Run %s (%s): coverage window %s -> %s (app window -> %s), state %s",
             run_label, "report" if report_run else "refresh", start, end, app_end, STATE)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    fixtures = load_fixtures(tz)
    todays = fixtures[(fixtures["kickoff"] >= start) & (fixtures["kickoff"] <= end)] if not fixtures.empty else fixtures
    log.info("football-data: %d upcoming fixtures in feed, %d inside the window", len(fixtures), len(todays))

    # ---- world spine (Livescore): every match in the window that the feeds above do not cover
    ls_events, ls_map, archive = [], {}, None
    if CONFIG["LIVESCORE"]:
        try:
            ls_events = worldfeed.fetch_window(start, end, tz_off)
            ls_events = [e for e in ls_events if competition_policy.allowed(
                e.get("country"), e.get("league"), home=e.get("home"), away=e.get("away"),
                key=f"{e.get('ccd', '')}/{e.get('scd', '')}")]
            log.info("Livescore: %d events on the window days", len(ls_events))
        except Exception as exc:  # noqa: BLE001
            log.warning("Livescore window failed: %s", exc)
    if ls_events and not todays.empty:
        try:
            ls_map = livescore.match_fixtures(todays, now, tz_off, events=ls_events)
        except Exception as exc:  # noqa: BLE001
            log.warning("Livescore matching failed: %s", exc)
    if CONFIG["WORLD"] and ls_events:
        used = {v["eid"] for v in ls_map.values()}
        world_events = [e for e in worldfeed.upcoming(ls_events, start, end) if e["eid"] not in used]
        world_fx = worldfeed.fixtures_frame(world_events, tz)
        if not world_fx.empty:
            base = todays.copy()
            base["home_id"] = None
            base["away_id"] = None
            base["eid"] = None
            todays = pd.concat([base, world_fx], ignore_index=True).sort_values(["kickoff", "country", "league"]).reset_index(drop=True)
            # rebuild the fixture-index -> livescore map on the new index
            by_eid = {e["eid"]: e for e in ls_events}
            old_eids = {}
            for i, row in base.iterrows():
                if i in ls_map:
                    old_eids[(row["kickoff"], row["country"], row["home"], row["away"])] = ls_map[i]
            ls_map = {}
            for i, row in todays.iterrows():
                if row.get("eid") and row["eid"] in by_eid:
                    ls_map[i] = worldfeed.ls_entry(by_eid[row["eid"]])
                else:
                    ev = old_eids.get((row["kickoff"], row["country"], row["home"], row["away"]))
                    if ev:
                        ls_map[i] = ev
        log.info("World spine: %d Livescore fixtures added (%d matched to feed fixtures)", len(world_fx), len(used))
        try:
            archive = worldfeed.Archive(LS_DIR)
            archive.absorb_days(ls_events, now)
            prios = worldfeed.stage_priorities(todays)
            # stage discovery, so the archive covers every in-season competition worldwide — not only
            # the ones playing inside the 24 h window: stages from the window days (yesterday included)
            # and from the day before that, plus every already-archived stage (kept fresh between
            # matchdays). Newly found stages sit at priority 0, so in-window stages always refresh first.
            for ev in ls_events:
                if ev["ccd"] and ev["scd"]:
                    k = worldfeed.stage_key(ev["ccd"], ev["scd"])
                    if k not in prios:
                        prios[k] = 0
            try:
                for ev in worldfeed.fetch_day(now - timedelta(days=2), tz_off):
                    if ev["ccd"] and ev["scd"] and competition_policy.allowed(
                            ev.get("country"), ev.get("league"), home=ev.get("home"), away=ev.get("away"),
                            key=f"{ev['ccd']}/{ev['scd']}"):
                        k = worldfeed.stage_key(ev["ccd"], ev["scd"])
                        if k not in prios:
                            prios[k] = 0
            except Exception as exc:  # noqa: BLE001
                log.warning("Stage discovery day failed: %s", exc)
            for k in worldfeed.known_stages(LS_DIR / "stages"):
                if k not in prios and competition_policy.allows_record(archive.load(k)):
                    prios[k] = 0
            for k in (s.strip() for s in str(CONFIG["SEED_STAGES"]).split(",")):
                if k and k not in prios and competition_policy.allowed(key=k):
                    prios[k] = 0
            archive.refresh(prios, now, tz_off)
            archive.backfill(prios, now, tz_off, seasons=CONFIG["BACKFILL_SEASONS"], budget_s=CONFIG["BACKFILL_BUDGET_S"])
            archive.refresh_stats(prios, now, budget_s=CONFIG["STATS_BUDGET_S"], max_n=CONFIG["STATS_MAX"])
            archive.save()
        except Exception as exc:  # noqa: BLE001
            log.warning("Livescore archive failed: %s", exc)
    elif todays.empty:
        pass

    # ---- coverage registry: per-competition status dashboard (read-only report on what the
    # scanner has; written before the league build so the browser index can carry the status)
    try:
        import coverage
        window_counts: dict[str, int] = {}
        nexts: dict[str, str] = {}
        if not todays.empty:
            for r in todays[todays["source"] == "world"].itertuples():
                k = str(r.div)[3:] if str(r.div).startswith("LS:") else None
                if not k:
                    continue
                window_counts[k] = window_counts.get(k, 0) + 1
                ko = r.kickoff.strftime("%Y-%m-%d %H:%M")
                if k not in nexts or ko < nexts[k]:
                    nexts[k] = ko
        coverage.build(LS_DIR / "stages", DATA_DIR / "app" / "leagues", now, window_counts, nexts)
    except Exception as exc:  # noqa: BLE001
        log.warning("Coverage registry failed (non-fatal): %s", exc)

    # ---- league browser: tables / results / fixtures for the app's Leagues tab (standalone;
    # reads the world archive + the coverage window already fetched above; never feeds the model)
    try:
        import leagues
        leagues.build(LS_DIR / "stages", now, DATA_DIR / "app" / "leagues", tz_hours=2, events=ls_events or None)
    except Exception as exc:  # noqa: BLE001
        log.warning("Leagues build failed (non-fatal): %s", exc)
    ls_events = None   # last use — free the ~17k window events before the analysis runs

    tracker = load_tracker()
    pending = tracker[tracker["status"] == "pending"] if not tracker.empty else tracker

    # which history files do we need? whole country systems, so promoted/relegated teams keep their history
    countries = set(todays["country"]) if not todays.empty else set()
    countries |= set(pending["country"]) if not pending.empty else set()
    main_divs = {d for d, (c, _) in MAIN_LEAGUES.items() if c in countries}
    extra_codes = {code for c, code in EXTRA_LEAGUES.items() if c in countries}

    seasons = season_codes(now)
    older = []
    y = now.year if now.month >= 7 else now.year - 1
    for k in range(2, CONFIG["H2H_SEASONS"]):
        older.append(f"{(y - k) % 100:02d}{(y - k + 1) % 100:02d}")
    since = datetime(now.year, now.month, now.day) - timedelta(days=CONFIG["MAX_HISTORY_DAYS"])
    main_all = load_main_results(main_divs, seasons + older, live_seasons=(seasons[0],))
    # The eligibility threshold uses every available archived meeting, including
    # older ones. This does not extend the 400-day model history or fetch new sources.
    extra_all = load_extra_results(extra_codes, datetime(1900, 1, 1))
    world_all = archive.results_frame(datetime(1900, 1, 1)) if archive is not None else pd.DataFrame()
    pool = pd.concat([f for f in (main_all, extra_all, world_all) if f is not None and not f.empty] or [empty_results()],
                     ignore_index=True)
    raw_pool = pool.dropna(subset=["date", "hg", "ag"]).sort_values("date", ascending=False).reset_index(drop=True)
    # Settlement must continue to see same-day results. Prediction/evidence inputs
    # have a separate conservative as-of cutoff because result availability times
    # are not recorded in the historical feeds.
    settlement_results = raw_pool[(raw_pool["date"] >= since) & (raw_pool["date"] <= pd.Timestamp(now.date()))].reset_index(drop=True)
    pool = prediction_history_as_of(raw_pool, now).reset_index(drop=True)
    pre_reconciliation = len(pool)
    pool, integrity = history_integrity.reconcile_livescore_ids(pool)
    log.info("Livescore prediction history reconciliation: %s", integrity)
    try:
        reviewed = cross_provider.load_approvals()
    except ValueError as exc:
        log.warning("%s; cross-provider merging disabled", exc)
        reviewed = {}
    pool, cross_audit, _ = cross_provider.reconcile(pool, reviewed)
    log.info("Cross-provider reconciliation (unreviewed and blocked candidates remain separate): %s", cross_audit)
    results = pool[pool["date"] >= since].reset_index(drop=True)
    log.info("History pool: %d matches for the model (%d incl. older seasons for head-to-head; %d from Livescore); "
             "%d same-day/future records excluded from predictions",
             len(results), len(pool), 0 if world_all is None or world_all.empty else len(world_all), len(raw_pool) - pre_reconciliation)
    del raw_pool

    div_avgs = compute_div_avgs(results, now)
    long = make_long(results, div_avgs)
    build_long_index(long)
    build_h2h_index(pool)
    h2h_index = h2h_gate.build_index(pool, now)
    sample_evidence = {i: h2h_evidence.assess(fx, h2h_index) for i, fx in todays.iterrows()}
    counts = {status: sum(e['status'] == status for e in sample_evidence.values())
              for status in ('sufficient', 'limited', 'unavailable')}
    ctx["h2h_evidence"] = {"minimum_meetings": h2h_evidence.MIN_MEETINGS, "counts": counts,
                           "considered": len(todays), "filter_enabled": False}
    log.info("H2H sample evidence (no eligibility filter): %s", ctx["h2h_evidence"])
    del h2h_index
    TEAM_HIST_CACHE.clear()
    H2H_CACHE.clear()
    PROFILE_CACHE.clear()
    SEASON_STARTS.clear()
    SEASON_STARTS.update(quality.season_starts(cross_provider.division_view(results), now))
    RAW_RATINGS.clear()
    RAW_RATINGS.update(compute_raw_ratings(long, now))
    global ACACHE
    ACACHE = acache.AnalysisCache(DATA_DIR / "analysis_cache.bin")
    SIGNAL_BASELINES.clear()
    SIGNAL_BASELINES.update(model_signals.sot_baselines(cross_provider.division_view(results)))
    MODELS["corners"] = markets.CountModel(results, "hc", "ac", now, markets.CORNERS)
    # Only genuine separately reported off-target counts, never HS minus HST.
    off = results.dropna(subset=["hsoff", "asoff"]) if {"hsoff", "asoff"} <= set(results) else results.iloc[:0]
    off = off[off["hsoff"].between(0, 50) & off["asoff"].between(0, 50)] if not off.empty else off
    if not off.empty:
        off_divisions = cross_provider.division_view(off)
        eligible_divs = set(off_divisions.groupby("div").size().loc[lambda n: n >= 30].index)
        if "_history_divs" in off:
            eligible = [r["div"] in eligible_divs or (isinstance(r["_history_divs"], (tuple, list)) and
                        any(d in eligible_divs for d in r["_history_divs"])) for _, r in off.iterrows()]
            off = off.loc[eligible]
        else:
            off = off[off["div"].isin(eligible_divs)]
    MODELS["shots_off"] = markets.CountModel(off, "hsoff", "asoff", now, markets.CORNERS) if not off.empty and off["hsoff"].mean() > 0 and off["asoff"].mean() > 0 else None
    cards_df = results.assign(hcards=results["hy"].fillna(0) + results["hr"].fillna(0),
                              acards=results["ay"].fillna(0) + results["ar"].fillna(0))
    cards_df.loc[results[["hy", "hr", "ay", "ar"]].isna().any(axis=1), ["hcards", "acards"]] = np.nan
    MODELS["cards"] = markets.CountModel(cards_df, "hcards", "acards", now, markets.CARDS, use_ref=True)

    # A wall-clock override does not make current feed prices historical quotes.
    if override:
        todays = without_unverified_replay_prices(todays)
        log.warning("SCAN_NOW: current prices withheld; historical quote availability is not established")
    RECENT_TEAM_CACHE.clear()
    rows = analyse_fixtures(todays, sample_evidence, long, results, div_avgs, now, pool)
    app_rows = [r for r in rows if r.fx["kickoff"] <= app_end]   # what the app publication carries
    def _signal_count(key):
        return sum(any((r.model_signals.get(side) or {}).get(key, False) for side in ("home", "away")) for r in app_rows)
    ctx["recent_form"] = {"enabled": RECENT_FORM_ENABLED, "fixtures": len(app_rows),
                          "applied": sum(r.recent_form.get("status") == "applied" for r in app_rows),
                          "baseline_fallback": sum(r.recent_form.get("status") == "baseline_fallback" for r in app_rows),
                          "h2h_applied": sum(bool(r.recent_form.get("h2h", {}).get("weight")) for r in app_rows)}
    log.info("Recent form coverage: %s", ctx["recent_form"])
    ctx["model_signals"] = {
        "status": "experimental_unvalidated" if EXPERIMENTAL_MODEL_SIGNALS else "disabled",
        "fixtures": len(app_rows), "xg_xga": _signal_count("xg_applied"),
        "shots_on_target": _signal_count("sot_applied"),
        "shots_off_target_corners": sum(bool((r.model_signals.get("corners") or {}).get("applied")) for r in app_rows),
    }
    log.info("Experimental model signal coverage: %s", ctx["model_signals"])

    # ---- Sportybet prices (their feed lists every event they have priced — currently ~33 days out,
    # so the 60-day coverage window gets priced for as far as the book has opened its lines)
    sbmap, sb_ok = {}, False
    if CONFIG["SPORTYBET"] and rows and not override:
        events = sporty.fetch_upcoming(CONFIG["COVER_DAYS"] * 24 + 6)
        sb_ok = bool(events)
        sbmap = sporty.match_fixtures(todays, events) if events else {}
    attach_prices(rows, sbmap, todays)
    ctx["sb_ok"] = sb_ok
    # full market lists (corners / cards) for the main-league matches the count models cover
    n_full = 0
    if sb_ok:
        for r in sorted(rows, key=lambda r: r.fx["kickoff"]):
            if n_full >= CONFIG["FULL_MARKETS_MAX"]:
                break
            if r.sb_event and r.sb_event.get("id") and (r.extra.corners or r.extra.cards):
                r.sb_full = sporty.fetch_event_markets(r.sb_event["id"])
                n_full += 1
    log.info("Sportybet: %d fixtures priced, %d full market lists", len(sbmap), n_full)
    picks = select_picks(rows)
    # analysis lookups are done — drop the per-team caches and the long frame before the trends pass
    # (trends works from its own frame); keeps the 60-day run inside a small runner's memory budget
    TEAM_HIST_CACHE.clear()
    PROFILE_CACHE.clear()
    RECENT_TEAM_CACHE.clear()
    H2H_CACHE.clear()
    del long

    # ---- squad market values (Transfermarkt, weekly) — context only
    try:
        sq = squads_mod.Squads(DATA_DIR / "squads.json")
        sq.refresh(set(str(d) for d in todays["div"]) if not todays.empty else set(), now)
        n_sq = 0
        for r in rows:
            r.squad = {"home": sq.lookup(r.fx["div"], r.fx["home"]), "away": sq.lookup(r.fx["div"], r.fx["away"])}
            n_sq += bool(r.squad["home"]) + bool(r.squad["away"])
        sq.save()
        log.info("Squad values: %d of %d teams matched", n_sq, 2 * len(rows))
    except Exception as exc:  # noqa: BLE001
        log.warning("Squad values failed: %s", exc)
    # ---- trends (team / match / head-to-head) — computed only for the matches the app publishes
    # (the 24 h window's detail files); nothing else ships trend text, so the far part of the
    # coverage window is pure model analysis
    trends_mod.clear_caches()
    lg_tr = None
    try:
        lg_tr = trends_mod._long(pool)
        for r in rows:
            if r.fx["kickoff"] <= app_end:
                r.trends = trends_mod.for_fixture(lg_tr, r.fx, r.h2h)
    except Exception as exc:  # noqa: BLE001
        log.warning("Trends failed: %s", exc)
    del lg_tr, pool            # the big history frames are done; keep RAM free for the day files and app export
    trends_mod.clear_caches()  # the per-team slices pin the trends frame; drop them too

    # ---- evidence / data quality / explanation / warnings (quality.py) — descriptive, never changes a probability
    build_audits(rows, now)

    # ---- day history with late scores
    days = None
    results_s = settlement_results
    try:
        days = history_mod.Days(DAYS_DIR, now)
        days.upsert(rows, comp, ls_map, top_sels)
        extra = days.fill_scores(settlement_results, archive)
        if not extra.empty:
            results_s = pd.concat([settlement_results, extra], ignore_index=True)
            log.info("History: %d late score(s) from Livescore added for settlement", len(extra))
    except Exception as exc:  # noqa: BLE001
        log.warning("Day history failed: %s", exc)

    # ---- legacy ledgers (parlays / trebles are no longer produced; pending ones are still graded)
    ledger = parlay_mod.load_ledger(PARLAY_FILE)
    if not ledger.empty and (ledger["status"] == "pending").any():
        ledger = parlay_mod.settle(ledger, results_s, now)
        ledger.to_csv(PARLAY_FILE, index=False)
    pr = {"parlays": [], "legs": [], "source": "none", "extended": False}
    ctx.update({"parlays": pr, "parlay_ids": [], "parlay_summary": parlay_mod.summary(ledger, now), "parlay_recent": []})

    # ---- high-probability selections and the day card (current app recommendation policy)
    safe_res = safe_mod.safest(rows, now, window_end, groups=safe_mod.SAFE_GROUPS, trebles=False,
                               signal=x12_research_eligible)
    safe_res["quality"] = {(r.fx["date"].strftime("%Y-%m-%d"), r.fx["country"], r.fx["home"], r.fx["away"]):
                           ((r.audit or {}).get("quality") or {}).get("overall") for r in rows if r.data_ok}
    bets_df = safe_mod.load_csv(SAFE_BETS_FILE, safe_mod.SAFE_BET_COLS)
    accas_df = safe_mod.load_csv(SAFE_ACCAS_FILE, safe_mod.ACCA_COLS)
    bets_df = safe_mod.settle_bets(bets_df, results_s, now)
    if not accas_df.empty and (accas_df["status"] == "pending").any():
        accas_df = safe_mod.settle_accas(accas_df, results_s, now)
        accas_df.to_csv(SAFE_ACCAS_FILE, index=False)
    bets_df, new_bets = safe_mod.add_bets(bets_df, safe_res["bets"], now, run_label)
    bets_df = safe_mod.pick_bets_of_the_day(bets_df, now, CONFIG["BOTD_N"],
                                            candidates=safe_mod.botd_candidates(rows, now, signal=strong_signal), run=run_label)
    bets_df.to_csv(SAFE_BETS_FILE, index=False)
    safe_res["ids"] = []
    ctx["safe"] = safe_res
    ctx["safe_summary"] = safe_mod.summary(bets_df, accas_df, now)
    botd_card = safe_mod.bets_of_the_day(bets_df, now)
    # Sticky historical card entries can predate the pause; retain the ledger but do not republish them.
    filter_botd_by_current_rows(botd_card, rows)
    ctx["botd"], ctx["botd_groups"] = botd_card["bets"], botd_card["groups"]
    log.info("Safest: %d bets (%d new), bets of the day: %d", len(safe_res["bets"]), len(new_bets), len(ctx["botd"]))

    # ---- alerts for the app (new safest bets), kept in state
    alerts_file = DATA_DIR / "app" / "alerts.json"
    try:
        alerts = json.loads(alerts_file.read_text(encoding="utf-8")) if alerts_file.exists() else []
    except (OSError, ValueError):
        alerts = []
    alerts = filter_pending_alerts(alerts, rows, now)
    for b in new_bets:
        alerts.append({"id": safe_mod.bet_id(b.key[0], b.home, b.away, b.sel), "ts": now.strftime("%Y-%m-%d %H:%M"),
                       "title": f"New high-probability selection · {b.label}", "kickoff": b.kickoff,
                       "text": f"{b.home} v {b.away} · {b.kickoff[5:]} · {b.odds:.2f} · {pct(b.p)}",
                       "fixture": appdata.fixture_id(b.key[0], b.key[1], b.home, b.away)})
    alerts = alerts[-50:]

    notes = ["H2H is optional: three available prior non-friendly meetings are a ranking tie-break only; "
             "fixtures are not excluded for missing or limited H2H history."]
    lowdata = sum(1 for r in rows if not r.data_ok)
    if lowdata:
        notes.append(f"{lowdata} fixture(s) flagged ⚠️ low data and excluded from shortlists.")
    if CONFIG["SPORTYBET"]:
        notes.append(f"Sportybet ({sporty.CC.upper()}): {len(sbmap)} of {len(rows)} fixtures priced." if sb_ok
                     else "Sportybet prices unavailable this run — average market prices shown instead.")
    coverage = {"fixtures": len(rows), "app_window": len(app_rows), "cover_days": CONFIG["COVER_DAYS"],
                "competitions": len({comp(r) for r in rows}), "priced": len(sbmap),
                "main": sum(1 for r in rows if r.fx["source"] == "main"), "extra": sum(1 for r in rows if r.fx["source"] == "extra"),
                "world": sum(1 for r in rows if r.fx["source"] == "world"), "data_ok": sum(1 for r in rows if r.data_ok)}
    ctx["coverage"] = coverage
    log.info("Coverage: %d fixtures over %d days (%d inside the app window), %d priced by Sportybet",
             len(rows), CONFIG["COVER_DAYS"], len(app_rows), len(sbmap))

    today_str = now.strftime("%Y-%m-%d")
    tracker = settle_tracker(tracker, results_s, now)
    tracker = add_picks(tracker, picks, now)
    tracker.to_csv(TRACKER_FILE, index=False)
    summary = tracker_summary(tracker, now)

    # ---- day history files + team pages for the app
    days_index = []
    if days is not None:
        try:
            days.annotate(tracker, ledger, accas_df, bets_df)
            days_index = days.summarise()
            log.info("History: %d day file(s) written", days.write())
            days.days.clear()   # on disk now — free the 60-day in-memory archive before the team-page export
        except Exception as exc:  # noqa: BLE001
            log.warning("Day history write failed: %s", exc)
    try:
        log.info("Team pages: %d division file(s)", len(teamstats.export(results, now, TEAMS_DIR, squad_lookup=sq.lookup if sq else None,
                                                                        page_cache=ACACHE)))
    except Exception as exc:  # noqa: BLE001
        log.warning("Team pages failed: %s", exc)
    try:
        ACACHE.save()   # persist this run's evidence for the next run (best effort; never fatal)
        cfile = DATA_DIR / "analysis_cache.bin"
        ctx["analysis_cache"] = {
            "profiles_hit": ACACHE.hits, "profiles_miss": ACACHE.misses,
            "pages_hit": ACACHE.page_hits, "pages_miss": ACACHE.page_misses,
            "file_mb": round(cfile.stat().st_size / 1e6, 1) if cfile.exists() else 0,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("Analysis cache save failed: %s", exc)

    digest_lines = []
    if now.weekday() == 0 and run_label == f"{CONFIG['RUN_HOURS'][0]:02d}:00":
        digest_lines = weekly_digest(tracker, ledger, now)
        ctx["digest"] = digest_lines

    report_md = render_report(ctx, rows, picks, summary, notes)
    (REPORTS_DIR / f"{today_str}.md").write_text(report_md, encoding="utf-8")
    (REPORTS_DIR / "latest.md").write_text(report_md, encoding="utf-8")
    rows_to_csv(rows, REPORTS_DIR / f"{today_str}.csv")
    # ---- per-fixture news for the app's Match Center (context only — shown for the user's
    # reference, never used by the model). Budgeted + TTL-cached across the half-hourly runs.
    try:
        ncache = news_mod.Cache(DATA_DIR / "news_cache.json", ttl_hours=CONFIG["NEWS_TTL_H"])
        budget = [CONFIG["NEWS_BUDGET"]]
        news_end = now + timedelta(hours=CONFIG["NEWS_HOURS"])
        for r in rows:
            if r.fx["kickoff"] > news_end:
                continue     # headlines for far-future fixtures are noise; keep the budget for near matches
            home, away = str(r.fx["home"]), str(r.fx["away"])
            country = str(r.fx.get("country") or "")
            r.news = {
                "home": ncache.items(f"team:{home}",
                                     lambda h=home: news_mod.team_headlines(h, country, limit=4), budget)[0],
                "away": ncache.items(f"team:{away}",
                                     lambda a=away: news_mod.team_headlines(a, country, limit=4), budget)[0],
                "match": ncache.items(f"match:{home}|{away}",
                                      lambda hh=home, aa=away: news_mod.fixture_headlines(hh, aa, country, limit=4),
                                      budget)[0],
            }
        # league-level news for the League Center's News tab (top-two teams + the competition name)
        try:
            import leagues as _lg
            _lg.add_news(DATA_DIR / "app" / "leagues",
                         league_fn=lambda league, country="": ncache.items(
                             f"q:{league}", lambda lg=league, cc=country: news_mod.team_headlines(lg, cc, limit=4), budget)[0],
                         team_fn=lambda name: ncache.items(
                             f"team:{name}", lambda t=name: news_mod.team_headlines(t, "", limit=3), budget)[0])
        except Exception as exc:  # noqa: BLE001
            log.warning("League news failed (non-fatal): %s", exc)
        ncache.save()
    except Exception as exc:  # noqa: BLE001
        log.warning("Per-fixture news failed (non-fatal): %s", exc)
    # ---- optional, source-authorized lineup pilot (context only, never a model input).
    # A real capture time, not SCAN_NOW or a supplied timestamp, prevents backdating imports.
    lineup_path = DATA_DIR / "lineup-pilot" / "archive.json"
    try:
        lineups = lineup_pilot.load(lineup_path)
        incoming = os.getenv("LINEUP_PILOT_INPUT", "").strip()
        if incoming and os.getenv("LINEUP_PILOT_RIGHTS_CONFIRMED", "").lower() == "true":
            lineups, imported = lineup_pilot.capture(lineups, json.loads(incoming), datetime.now(ZoneInfo("UTC")))
            if imported:
                lineup_pilot.save(lineup_path, lineups)
            log.info("Lineup pilot: %d new authorized snapshots", imported)
        elif incoming:
            log.warning("Lineup pilot input ignored: storage/use rights have not been confirmed")
        ctx["lineup_archive"] = lineups
        ctx["lineup_as_of"] = datetime.now(tz)
        research_path = DATA_DIR / "lineup-pilot" / "evaluation.json"
        eval_rows, n_frozen = lineup_pilot.freeze_evaluations(
            lineup_pilot.load_evaluations(research_path), app_rows, lineups, ctx["lineup_as_of"], analysis_at=now)
        if n_frozen:
            lineup_pilot.save(research_path, eval_rows)
        log.info("Lineup pilot: %d new pre-match baseline records", n_frozen)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        log.warning("Lineup pilot unavailable; model and publication continue: %s", exc)
        ctx["lineup_archive"] = []
        ctx["lineup_as_of"] = datetime.now(tz)

    # ---- structured export for the Android app: written to a staging directory, checked, then promoted.
    # The publication carries only the APP_WINDOW_HOURS window (the Matches tab is "today"); the rest of
    # the coverage window lives in the day files (browseable per day) and feeds the model / tracker.
    staging = APP_FILE.parent / "_staging"
    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        appdata.export(staging / APP_FILE.name, ctx=ctx, rows=app_rows, all_rows=rows, picks=picks, tracker_summary=summary, notes=notes, ls_map=ls_map,
                       helpers={"render_details": render_details, "stars": stars, "comp": comp, "sb_price": sb_price,
                                "selections": all_sels},
                       reports_dir=REPORTS_DIR, tz_label=TZL, thresholds=CONFIG["THRESHOLDS"],
                       backtest=CONFIG["BACKTEST"], repo=os.getenv("GITHUB_REPOSITORY", "perfectndumiso1-netizen/goals-scanner"),
                       days_index=days_index, safe_summary=ctx["safe_summary"], botd=ctx["botd"], botd_groups=ctx["botd_groups"], alerts=alerts,
                       coverage=coverage, safe_groups=safe_mod.SAFE_GROUPS,
                       extra_badges=archive.badge_map() if archive is not None else None, report_run=report_run,
                       live_dir=APP_FILE.parent)
        errors, warns = verify.check_publication(staging, APP_FILE.parent, SAFE_BETS_FILE, now, expect_fixtures=len(app_rows))
        for w in warns[:20]:
            log.warning("Data check: %s", w)
        if errors:
            for e in errors[:30]:
                log.error("Data check FAILED: %s", e)
            ctx["data_check"] = {"ok": False, "errors": errors[:30], "warnings": warns[:30]}
            log.error("Publication kept from the previous run (%d problem(s))", len(errors))
            send_telegram("⚠️ PlayReport data check failed — the app keeps the previous publication.\n" +
                          "\n".join(f"• {e}" for e in errors[:8]))
        else:
            ctx["data_check"] = {"ok": True, "warnings": warns[:30]}
            promote_publication(staging, APP_FILE.parent, now)
            log.info("App data: %s (%d checks passed, %d warning(s))", APP_FILE, 1, len(warns))
    except Exception as exc:  # noqa: BLE001 - keep the old publication if export fails
        ctx["data_check"] = {"ok": False, "errors": ["App data export failed"]}
        log.exception("App data export failed: %s", exc)
        send_telegram("⚠️ Mr 2 Odds app data export failed — the previous publication remains live.")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    # A successful workflow must mean a checked app publication is ready for the state push.
    require_publication(ctx)
    if os.getenv("README_AUTO") == "1":
        update_readme(render_readme_block(ctx, rows, picks, summary, f"reports/{today_str}.md"))

    pdf_report = None
    if report_run and CONFIG["PDF"] and pdfgen is not None:
        stamp = f"{today_str}-{now:%H%M}"
        try:
            pdf_report = pdfgen.markdown_to_pdf(report_md, PDF_DIR / f"playreport-{stamp}.pdf", "PlayReport",
                                                f"{run_desc(run_label, True).capitalize()} · full report")
        except Exception as exc:  # noqa: BLE001 - never lose the run because of the PDF
            log.warning("PDF generation failed: %s", exc)
    # keep only the newest PDFs in state
    for old_pdf in sorted(PDF_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)[12:]:
        old_pdf.unlink(missing_ok=True)

    repo = os.getenv("GITHUB_REPOSITORY")
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    report_url = f"{server}/{repo}/blob/data/reports/{today_str}.md" if repo else None
    if report_run:
        send_telegram(telegram_text(ctx, rows, picks, report_url))
        if pdf_report:
            send_telegram_document(pdf_report, f"📄 PlayReport — {now:%a %d %b}, {run_desc(run_label, True)} ({len(rows)} fixtures)")
        csv_path = REPORTS_DIR / f"{today_str}.csv"
        if csv_path.exists():
            send_telegram_document(csv_path, f"📊 PlayReport data — {now:%a %d %b}, {run_desc(run_label, True)}: every fixture with "
                                             f"probabilities, expected goals, corners, cards and Sportybet prices (CSV)")
        mark_report_run(now, run_label)
    elif new_bets:
        send_telegram(alert_text(new_bets, now))
    if digest_lines:
        send_telegram(digest_text(digest_lines))

    for mkt, name in MARKETS.items():
        log.info("%s: %d pick(s)", name, len(picks[mkt]))
    log.info("Done. Report: %s", REPORTS_DIR / f"{today_str}.md")


if __name__ == "__main__":
    main()
