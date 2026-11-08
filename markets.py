"""Extra markets for the goals scanner (v3): 1X2 / double chance, team goals, corners and cards.

Everything here is backtested in backtest/markets_backtest.py (main leagues, 2023-26):
* corners  – team corner rates for/against, league-normalised, time-decayed, shrinkage K=40,
             negative binomial (size 80 for match totals, 10 for a single team). Calibrated within
             ~2 points on the 8.5-11.5 lines; beats the league-average baseline (log-loss 0.687 vs 0.693).
* cards    – team card rates (received / provoked) with a referee factor (UK leagues publish referees),
             shrinkage K=20, negative binomial size 30. Calibrated within ~2 points on 3.5-5.5 lines.
* 1X2 / DC – straight from the Dixon-Coles score matrix of the football-data model (data-first engine,
             2026-09-28: the old 10/90 blend with bookmaker prices was removed; with the two-strength
             shrinkage the model-only home/away win probabilities are calibrated within ~2 points, see
             backtest/RESULTS.md). Bookmaker 1X2 prices are de-margined with the *power* method and kept
             as a separate comparison layer.
* team goals – straight from the score matrix (calibrated within ~2 points up to 80%).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
import cross_provider

# ----------------------------------------------------------------------------- parameters (from the backtest)
CORNERS = {"K": 40.0, "KV": 20.0, "HL": 120.0, "r_total": 80.0, "r_team": 10.0, "div_K": 30.0,
           "lines_total": (8.5, 9.5, 10.5, 11.5), "lines_team": (3.5, 4.5, 5.5)}
CARDS = {"K": 20.0, "KV": 20.0, "HL": 120.0, "r_total": 30.0, "r_team": 8.0, "div_K": 30.0, "K_ref": 10.0,
         "lines_total": (3.5, 4.5, 5.5), "lines_team": (1.5, 2.5)}
MAX_N, MAX_DAYS = 40, 400


# ----------------------------------------------------------------------------- odds helpers
def power_demargin(odds) -> list[float]:
    """Fair probabilities from a set of decimal prices covering all outcomes (power method: sum p_i^k = 1).
    Falls back to proportional scaling if the prices are degenerate."""
    inv = np.array([1.0 / o for o in odds], dtype=float)
    if np.any(~np.isfinite(inv)) or inv.sum() <= 0:
        return [float("nan")] * len(inv)
    k, lo, hi = 1.0, 0.5, 3.0
    for _ in range(60):  # bisection on k: f(k) = sum inv^k - 1 is decreasing in k
        k = (lo + hi) / 2
        if (inv ** k).sum() > 1:
            lo = k
        else:
            hi = k
    p = inv ** k
    return list(p / p.sum())


def fair_two_way(o1, o2) -> float:
    """Fair probability of the first outcome of a two-way market (power method)."""
    if any(v is None or (isinstance(v, float) and math.isnan(v)) or v <= 1 for v in (o1, o2)):
        return float("nan")
    return power_demargin([o1, o2])[0]


# ----------------------------------------------------------------------------- negative binomial
def nb_pmf_vector(mu: float, r: float, kmax: int) -> np.ndarray:
    """P(X = 0..kmax) for a negative binomial with mean mu and size r (Poisson when r is inf)."""
    mu = max(float(mu), 1e-6)
    out = np.zeros(kmax + 1)
    if math.isinf(r):
        out[0] = math.exp(-mu)
        for k in range(1, kmax + 1):
            out[k] = out[k - 1] * mu / k
        return out
    q = r / (r + mu)
    out[0] = q ** r
    for k in range(1, kmax + 1):
        out[k] = out[k - 1] * (k - 1 + r) / k * (1 - q)
    return out


def nb_sf(k: int, mu: float, r: float) -> float:
    """P(X >= k)."""
    if k <= 0:
        return 1.0
    return float(max(0.0, 1.0 - nb_pmf_vector(mu, r, k - 1).sum()))


def over_line(mu: float, r: float, line: float) -> float:
    """P(X > line) for a half line, e.g. over 9.5 = P(X >= 10)."""
    return nb_sf(math.ceil(line), mu, r)


# ----------------------------------------------------------------------------- count model (corners / cards)
@dataclass
class CountExpectation:
    eh: float
    ea: float
    h_neff: float
    a_neff: float
    ref_factor: float = 1.0
    ref_n: float = 0.0
    h_for: float = float("nan")     # raw per-game averages (information)
    h_against: float = float("nan")
    a_for: float = float("nan")
    a_against: float = float("nan")
    h_n: int = 0
    a_n: int = 0

    @property
    def total(self) -> float:
        return self.eh + self.ea


class CountModel:
    """Expected home/away counts for one statistic (corners or cards), estimated at `now` from results.

    Mirrors roll_counts() in backtest/markets_backtest.py: league averages (time-decayed, shrunk towards the
    global average), team for/against rates normalised by league averages, venue blend, shrinkage K, and
    an optional referee factor."""

    def __init__(self, results: pd.DataFrame, hcol: str, acol: str, now: datetime, params: dict,
                 use_ref: bool = False):
        self.p = params
        self.use_ref = use_ref
        self.ok = False
        self.now_ord = pd.Timestamp(now.date()).toordinal()
        df = results.dropna(subset=[hcol, acol, "date"]) if not results.empty else results
        if df.empty:
            return
        ords = df["date"].map(pd.Timestamp.toordinal).to_numpy()
        keep = ords >= self.now_ord - MAX_DAYS
        df, ords = df[keep], ords[keep]
        if df.empty:
            return
        hv, av = df[hcol].to_numpy(dtype=float), df[acol].to_numpy(dtype=float)
        w = 0.5 ** ((self.now_ord - ords) / params["HL"])
        self.glob = (float((w * hv).sum() / w.sum()), float((w * av).sum() / w.sum()))
        self.div_avg: dict[str, tuple[float, float]] = {}
        # Division priors see each reviewed event under both provider keys; the
        # global prior and team samples above/below remain one row per event.
        div_df = cross_provider.division_view(df)
        div_ords = div_df["date"].map(pd.Timestamp.toordinal).to_numpy()
        div_w = 0.5 ** ((self.now_ord - div_ords) / params["HL"])
        div_hv, div_av = div_df[hcol].to_numpy(dtype=float), div_df[acol].to_numpy(dtype=float)
        div_keys = div_df["div"].to_numpy()
        for d in np.unique(div_keys):
            m = div_keys == d
            n = div_w[m].sum()
            mh, ma = (div_w[m] * div_hv[m]).sum() / n, (div_w[m] * div_av[m]).sum() / n
            dk = params["div_K"]
            self.div_avg[d] = ((n * mh + dk * self.glob[0]) / (n + dk), (n * ma + dk * self.glob[1]) / (n + dk))
        divs = df["div"].to_numpy()
        self.team: dict[tuple[str, str], list] = defaultdict(list)
        self.ref: dict[str, list] = defaultdict(list)
        countries, homes, aways = df["country"].to_numpy(), df["home"].to_numpy(), df["away"].to_numpy()
        refs = df["referee"].astype(str).to_numpy() if "referee" in df.columns else np.full(len(df), "")
        order = np.argsort(ords, kind="stable")
        for i in order:
            self.team[(countries[i], homes[i])].append((ords[i], 1, hv[i], av[i], divs[i]))
            self.team[(countries[i], aways[i])].append((ords[i], 0, av[i], hv[i], divs[i]))
            if use_ref and refs[i] and refs[i] not in ("nan", "None"):
                self.ref[refs[i]].append((ords[i], hv[i] + av[i], divs[i]))
        # referee history may need to be longer than MAX_DAYS; keep what we have (results pool is ~400 days)
        self.ok = True

    def _div(self, div: str) -> tuple[float, float]:
        return self.div_avg.get(div, self.glob)

    def _profile(self, country: str, team: str, venue: int):
        recs = self.team.get((country, team), [])[-MAX_N:]
        if not recs:
            return None
        d, HL, KV, K = self.now_ord, self.p["HL"], self.p["KV"], self.p["K"]
        sw = swa = swd = sv = sva = svd = 0.0
        raw_f = raw_a = 0.0
        for o, v, f, a, dv in recs:
            wgt = 0.5 ** ((d - o) / HL)
            mh_, ma_ = self._div(dv)
            fn, an = (f / mh_, a / ma_) if v == 1 else (f / ma_, a / mh_)
            sw += wgt
            swa += wgt * fn
            swd += wgt * an
            raw_f += wgt * f
            raw_a += wgt * a
            if v == venue:
                sv += wgt
                sva += wgt * fn
                svd += wgt * an
        att, dfc = swa / sw, swd / sw
        if sv > 0:
            sh = sv / (sv + KV)
            att = sh * (sva / sv) + (1 - sh) * att
            dfc = sh * (svd / sv) + (1 - sh) * dfc
        return ((sw * att + K) / (sw + K), (sw * dfc + K) / (sw + K), sw, raw_f / sw, raw_a / sw, len(recs))

    def _ref_factor(self, ref: str) -> tuple[float, float]:
        if not self.use_ref or not ref or ref in ("nan", "None"):
            return 1.0, 0.0
        recs = self.ref.get(ref, [])
        if not recs:
            return 1.0, 0.0
        d, HL, K_ref = self.now_ord, self.p["HL"], self.p["K_ref"]
        sw = sx = 0.0
        for o, tot, dv in recs:
            wgt = 0.5 ** ((d - o) / (2 * HL))
            mh_, ma_ = self._div(dv)
            sw += wgt
            sx += wgt * tot / (mh_ + ma_)
        return (sw * (sx / sw) + K_ref) / (sw + K_ref), sw

    def expect(self, country: str, home: str, away: str, div: str, referee: str = "") -> CountExpectation | None:
        if not self.ok:
            return None
        H, A = self._profile(country, home, 1), self._profile(country, away, 0)
        if H is None or A is None:
            return None
        mh_, ma_ = self._div(div)
        rf, rn = self._ref_factor(referee)
        return CountExpectation(mh_ * H[0] * A[1] * rf, ma_ * A[0] * H[1] * rf, H[2], A[2], rf, rn,
                                H[3], H[4], A[3], A[4], H[5], A[5])


def count_lines(exp: CountExpectation | None, params: dict) -> dict:
    """Probabilities for the standard over lines (total and per team)."""
    if exp is None:
        return {}
    out = {"total": {}, "home": {}, "away": {}}
    for line in params["lines_total"]:
        out["total"][line] = over_line(exp.total, params["r_total"], line)
    for line in params["lines_team"]:
        out["home"][line] = over_line(exp.eh, params["r_team"], line)
        out["away"][line] = over_line(exp.ea, params["r_team"], line)
    return out


# ----------------------------------------------------------------------------- 1X2 / DC / team goals
def one_x_two(M: np.ndarray) -> dict:
    """Home / draw / away and double-chance probabilities read off the model score matrix (home rows, away cols).
    Data-first engine (2026-09-28): bookmaker prices are no longer blended in here — the de-margined market 1X2 is
    kept separately (MatchRow.x12_market) for comparison only."""
    g = np.arange(M.shape[0])
    pH = float(M[g[:, None] > g[None, :]].sum())
    pA = float(M[g[:, None] < g[None, :]].sum())
    pD = max(0.0, 1.0 - pH - pA)
    return {"H": pH, "D": pD, "A": pA, "1X": pH + pD, "12": pH + pA, "X2": pD + pA, "source": "model"}


def team_goals(M: np.ndarray) -> dict:
    return {"H_o05": float(1 - M[0, :].sum()), "H_o15": float(1 - M[:2, :].sum()),
            "A_o05": float(1 - M[:, 0].sum()), "A_o15": float(1 - M[:, :2].sum())}


@dataclass
class ExtraMarkets:
    x12: dict = field(default_factory=dict)       # H D A 1X 12 X2 (+ source)
    tg: dict = field(default_factory=dict)        # team goals
    corners: CountExpectation | None = None
    corner_p: dict = field(default_factory=dict)
    cards: CountExpectation | None = None
    card_p: dict = field(default_factory=dict)
    p_o25_fair: float = float("nan")              # market-implied O2.5 from the reference odds (comparison only)
