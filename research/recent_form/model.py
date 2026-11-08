"""Experimental recent-form overlay on the existing Dixon--Coles model.

Offline comparison adapter: not imported by the production scanner, not a selection engine,
not an availability-time-verified replay. Constants are exploratory, not tuned
or validated. The caller must provide local result rows; no provider is called.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

import numpy as np
import pandas as pd

import history_integrity
import markets
import scanner
import recent_form as core

# Shared with the production overlay so the researched and live formula cannot drift.
LAST5_WEIGHT, PREVIOUS5_WEIGHT, VENUE5_WEIGHT = core.LAST5_WEIGHT, core.PREVIOUS5_WEIGHT, core.VENUE5_WEIGHT
WINDOW_PRIOR = core.WINDOW_PRIOR
FREQUENCY_WEIGHT, FREQUENCY_PRIOR = core.FREQUENCY_WEIGHT, core.FREQUENCY_PRIOR
H2H_WEIGHT, H2H_PRIOR, H2H_MIN, H2H_DAYS = core.H2H_WEIGHT, core.H2H_PRIOR, core.H2H_MIN, core.H2H_DAYS


class ResearchError(ValueError):
    """The offline research inputs are invalid or no baseline is available."""


@dataclass
class Context:
    cutoff: datetime
    history: pd.DataFrame
    results: pd.DataFrame
    long: pd.DataFrame
    averages: dict
    integrity: dict
    h2h_index: dict


def prepare(history: pd.DataFrame, cutoff: datetime) -> Context:
    """Build same-day-excluded production baseline inputs, in memory only.

    Dates alone cannot establish when an archived statistic became available.
    The returned context is single-threaded: scanner's in-process indexes and
    caches are shared; activate this context before calling predict.
    """
    if not isinstance(cutoff, datetime):
        raise ResearchError('cutoff must be a datetime')
    required = {'date', 'country', 'div', 'league', 'home', 'away', 'hg', 'ag'}
    if not isinstance(history, pd.DataFrame) or not required.issubset(history.columns):
        raise ResearchError('history is missing required result columns')
    h = history.copy()
    h['date'] = pd.to_datetime(h['date'], errors='coerce')
    if getattr(h['date'].dt, 'tz', None) is not None:
        raise ResearchError('history dates must use the same naive local calendar convention as the scanner')
    h['date'] = h['date'].dt.normalize()
    h = scanner.prediction_history_as_of(h, cutoff).dropna(subset=['date', 'hg', 'ag']).copy()
    for col in scanner.NUM_RESULT_COLS:
        if col not in h:
            h[col] = np.nan
    for col in ('home_id', 'away_id', 'referee'):
        if col not in h:
            h[col] = None
    # Corrupt goals must not become zero or a failed-to-score observation.
    for col in ('hg', 'ag'):
        values = pd.to_numeric(h[col], errors='coerce')
        h = h.loc[values.notna() & np.isfinite(values) & (values >= 0) & (values % 1 == 0)].copy()
        h[col] = pd.to_numeric(h[col])
    h, audit = history_integrity.reconcile_livescore_ids(h)
    h = h.sort_values('date', ascending=False, kind='stable').reset_index(drop=True)
    current = h[h['date'] >= pd.Timestamp(cutoff.date()) - pd.Timedelta(days=scanner.CONFIG['MAX_HISTORY_DAYS'])].copy()
    if current.empty:
        raise ResearchError('no valid earlier history')
    averages = scanner.compute_div_avgs(current, cutoff)
    long = scanner.make_long(current, averages)
    index = {}
    if {'home_id', 'away_id', 'eid'}.issubset(h.columns):
        scope = h[h['div'].astype(str).str.startswith('LS:') &
                  (h['date'] >= pd.Timestamp(cutoff.date()) - pd.Timedelta(days=H2H_DAYS))]
        for r in scope.itertuples():
            if _valid_id(r.home_id) and _valid_id(r.away_id) and r.home_id != r.away_id and _valid_id(r.eid):
                pair = tuple(sorted((r.home_id, r.away_id)))
                index.setdefault((r.div, pair), []).append(r.Index)
    return Context(cutoff, h, current, long, averages, audit, index)


_ACTIVE_CONTEXT = None


def _activate(ctx: Context):
    # Offline-only isolation from previous research calls. Never invoke scanner
    # main, fetch prices, load a persistent cache, or mutate source archives.
    # Like scanner's own indexes, this research context is not thread-safe.
    global _ACTIVE_CONTEXT
    if _ACTIVE_CONTEXT is ctx:
        return
    scanner.ACACHE = None
    scanner.PROFILE_CACHE.clear()
    scanner.TEAM_HIST_CACHE.clear()
    scanner.RAW_RATINGS.clear()
    scanner.SEASON_STARTS.clear()
    scanner.build_long_index(ctx.long)
    _ACTIVE_CONTEXT = ctx


_stats = core.stats
_windows = core.windows
_form_rating = core.form_rating
_frequency_evidence = core.frequency_evidence
_frequency_adjust = core.frequency_adjust
_valid_id = core.valid_id


def _h2h(ctx, fx):
    hid, aid = fx.get('home_id'), fx.get('away_id')
    if not (_valid_id(hid) and _valid_id(aid)) or hid == aid:
        return [], 'team IDs unavailable or ambiguous'
    positions = ctx.h2h_index.get((fx['div'], tuple(sorted((hid, aid)))), [])
    return core.meetings(ctx.history.iloc[positions], fx, ctx.cutoff), 'same-competition, identified meetings only'


def predict(ctx: Context, fx: dict) -> dict:
    """Compute baseline and variant on identical history; no outcomes/prices read."""
    if not isinstance(ctx, Context) or not isinstance(fx, dict):
        raise ResearchError('context and fixture mapping are required')
    if any(not isinstance(fx.get(k), str) or not fx[k].strip() for k in ('country','div','home','away')):
        raise ResearchError('fixture identity is incomplete')
    if fx['home'] == fx['away']:
        raise ResearchError('fixture teams must differ')
    _activate(ctx)
    hid, aid = fx.get('home_id'), fx.get('away_id')
    hp = scanner.build_profile(ctx.long, fx['country'], fx['home'], 'H', ctx.cutoff, hid)
    ap = scanner.build_profile(ctx.long, fx['country'], fx['away'], 'A', ctx.cutoff, aid)
    if not hp.ok or not ap.ok:
        raise ResearchError('insufficient existing baseline team history')
    def rows(team, team_id):
        sample = scanner.team_history(ctx.long, fx['country'], team, team_id)
        return scanner._profile_sample_rows(sample)
    home, away = rows(fx['home'], hid), rows(fx['away'], aid)
    league = ctx.averages.get(fx['div'], ctx.averages['__global__'])
    if not all(math.isfinite(x) and x > 0 for x in (league.mu_h, league.mu_a, hp.att, hp.dfc, ap.att, ap.dfc)):
        raise ResearchError('invalid league averages or baseline team ratings')
    def bound(value): return min(max(float(value), 0.15), 4.5)
    base_h, base_a = bound(league.mu_h * hp.att * ap.dfc), bound(league.mu_a * ap.att * hp.dfc)
    try:
        hteam = core.prepare_team(hp, home, 'H', ctx.cutoff)
        ateam = core.prepare_team(ap, away, 'A', ctx.cutoff)
        meetings, h2h_reason = _h2h(ctx, fx)
        recent_h, recent_a, info = core.adjust(hteam, ateam, league, meetings)
    except ValueError as exc:
        raise ResearchError(str(exc)) from exc
    info['h2h']['scope'] = h2h_reason
    info['squad_availability'] = {'status': 'not_used', 'reason': 'no validated historical pre-kickoff availability and effect estimates'}
    def output(lh, la):
        matrix = scanner.score_matrix(lh, la, scanner.CONFIG['DC_RHO'])
        probabilities = {**scanner.probs_from_matrix(matrix), **markets.one_x_two(matrix), **markets.team_goals(matrix),
                         'H_zero_goal': float(matrix[0, :].sum()), 'A_zero_goal': float(matrix[:, 0].sum())}
        return {'lambda_home': lh, 'lambda_away': la, 'probabilities': probabilities, 'matrix': matrix.tolist()}
    return {'classification': 'offline_research_unvalidated', 'baseline': output(base_h, base_a),
            'recent_variant': output(recent_h, recent_a),
            'league': {'source': 'division' if fx['div'] in ctx.averages else 'global_fallback',
                       'home_mean': league.mu_h, 'away_mean': league.mu_a, 'effective_matches': league.n_eff},
            'evidence': {k: info[k] for k in ('home', 'away', 'h2h', 'scoring_probability_delta', 'squad_availability')}}
