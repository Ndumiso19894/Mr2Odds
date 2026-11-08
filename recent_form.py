"""Bounded recent-form overlay for the existing league-based goal model.

No provider, network or persistent state. All inputs must already have passed
scanner's prior-day history and identity-reconciliation filters. Experimental
weights are not proven to improve accuracy. Insufficient or ambiguous evidence
raises ValueError so the caller can retain the baseline rather than guess.
"""
from __future__ import annotations

from datetime import datetime
import math
import numpy as np
import pandas as pd

LAST5_WEIGHT, PREVIOUS5_WEIGHT, VENUE5_WEIGHT = 0.20, 0.10, 0.10
WINDOW_PRIOR = 5.0
FREQUENCY_WEIGHT, FREQUENCY_PRIOR = 0.10, 12.0
H2H_WEIGHT, H2H_PRIOR, H2H_MIN, H2H_DAYS = 0.10, 5.0, 3, 1095


def valid_id(value):
    return (isinstance(value, str) and value == value.strip() and value != '' and
            value.lower() not in ('none', 'nan', 'null'))


def stats(rows):
    n = len(rows)
    if not n:
        return {'n': 0, 'goals_for': None, 'goals_against': None,
                'scored': None, 'failed_to_score': None, 'conceded': None, 'clean_sheets': None}
    gf, ga = rows['gf'].to_numpy(dtype=float), rows['ga'].to_numpy(dtype=float)
    return {'n': n, 'goals_for': int(gf.sum()), 'goals_against': int(ga.sum()),
            'scored': int((gf > 0).sum()), 'failed_to_score': int((gf == 0).sum()),
            'conceded': int((ga > 0).sum()), 'clean_sheets': int((ga == 0).sum())}


def windows(rows, venue):
    return rows.head(5), rows.iloc[5:10], rows[rows['venue'] == venue].head(5)


def form_rating(profile, rows, venue):
    parts = windows(rows, venue)
    weights = [weight * len(part) / 5.0 for part, weight in zip(parts, (LAST5_WEIGHT, PREVIOUS5_WEIGHT, VENUE5_WEIGHT))]
    def blend(baseline, column):
        value = baseline * (1.0 - sum(weights))
        for part, weight in zip(parts, weights):
            if weight:
                avg = float(part[column].mean())
                shrunk = (len(part) * avg + WINDOW_PRIOR * baseline) / (len(part) + WINDOW_PRIOR)
                value += weight * shrunk
        return value
    return blend(profile.att, 'gf_norm'), blend(profile.dfc, 'ga_norm'), weights


def frequency_evidence(rows, venue, col):
    parts = windows(rows, venue)
    multiplier = (2, 1, 1)
    yes = sum(mult * int((part[col] > 0).sum()) for part, mult in zip(parts, multiplier))
    total = sum(mult * len(part) for part, mult in zip(parts, multiplier))
    return yes, total


def frequency_adjust(lam, own, other):
    p = -math.expm1(-lam)
    delta = sum(FREQUENCY_WEIGHT * (yes - total * p) / (FREQUENCY_PRIOR + total) for yes, total in (own, other))
    adjusted = min(max(p + delta, 1-math.exp(-0.15)), 1-math.exp(-4.5))
    return -math.log1p(-adjusted), delta


def prepare_team(profile, rows, venue, cutoff):
    """Create per-run team evidence once; raises on ambiguous/invalid input."""
    if not profile.ok or not isinstance(cutoff, datetime) or venue not in ('H', 'A'):
        raise ValueError('insufficient baseline team history')
    if not all(math.isfinite(x) and x > 0 for x in (profile.att, profile.dfc)):
        raise ValueError('invalid baseline team ratings')
    if rows.empty or not {'date','venue','gf','ga','gf_norm','ga_norm'}.issubset(rows.columns):
        raise ValueError('recent history unavailable')
    dates = pd.to_datetime(rows['date'], errors='coerce')
    if getattr(dates.dt, 'tz', None) is not None or dates.isna().any() or (dates.dt.normalize() >= pd.Timestamp(cutoff.date())).any():
        raise ValueError('recent history is not strictly before cutoff day')
    if not dates.is_monotonic_decreasing:
        raise ValueError('recent history is not sorted newest first')
    numbers = rows[['gf','ga','gf_norm','ga_norm']].to_numpy(dtype=float)
    if not np.isfinite(numbers).all() or (numbers < 0).any() or (numbers[:,:2] % 1 != 0).any():
        raise ValueError('invalid recent score or league-normalised history')
    relevant = pd.concat([rows.head(10), rows[rows['venue'] == venue].head(5)]).loc[lambda x: ~x.index.duplicated()]
    if pd.to_datetime(relevant['date']).dt.normalize().duplicated().any():
        raise ValueError('ambiguous same-day team history in recent windows')
    attack, defence, weight = form_rating(profile, rows, venue)
    return {'attack': attack, 'defence': defence,
            'scored_evidence': frequency_evidence(rows, venue, 'gf'),
            'conceded_evidence': frequency_evidence(rows, venue, 'ga'),
            'last5': stats(rows.head(5)), 'last10': stats(rows.head(10)),
            'venue5': stats(rows[rows['venue'] == venue].head(5)), 'window_weights': weight}


def meetings(rows, fx, cutoff):
    """Latest same-league identified meetings, oriented to the target fixture."""
    hid, aid, div = fx.get('home_id'), fx.get('away_id'), fx.get('div')
    if not valid_id(hid) or not valid_id(aid) or hid == aid:
        return []
    required = {'date','div','eid','home_id','away_id','hg','ag'}
    if rows is None or rows.empty or not required.issubset(rows.columns):
        return []
    dates = pd.to_datetime(rows['date'], errors='coerce')
    if getattr(dates.dt, 'tz', None) is not None:
        return []
    date_day = dates.dt.normalize()
    cutoff_day = pd.Timestamp(cutoff.date())
    pair = ((rows['home_id'] == hid) & (rows['away_id'] == aid)) | ((rows['home_id'] == aid) & (rows['away_id'] == hid))
    scope = (rows['div'] == div) & rows['div'].astype(str).str.startswith('LS:') & pair & \
            (date_day < cutoff_day) & (date_day >= cutoff_day - pd.Timedelta(days=H2H_DAYS)) & rows['eid'].map(valid_id)
    h = rows.loc[scope].copy()
    if h.empty:
        return []
    for c in ('hg','ag'):
        values = pd.to_numeric(h[c], errors='coerce')
        h = h.loc[values.notna() & np.isfinite(values) & (values >= 0) & (values % 1 == 0)].copy()
        h[c] = pd.to_numeric(h[c])
    h['_day'] = pd.to_datetime(h['date']).dt.normalize()
    h = h[~h['eid'].duplicated(keep=False)]
    h = h[~h['_day'].duplicated(keep=False)].sort_values('_day', ascending=False, kind='stable').head(5)
    out=[]
    for r in h.itertuples():
        home, away = (int(r.hg), int(r.ag)) if r.home_id == hid else (int(r.ag), int(r.hg))
        out.append({'event_id': r.eid, 'date': r.date.strftime('%Y-%m-%d'), 'home_goals': home, 'away_goals': away})
    return out


def adjust(home, away, league, h2h):
    """Produce bounded lambdas and audit fields; league averages stay explicit."""
    if not all(math.isfinite(x) and x > 0 for x in (league.mu_h, league.mu_a)):
        raise ValueError('invalid league averages')
    def bound(value):return min(max(float(value), 0.15), 4.5)
    h = bound(league.mu_h * home['attack'] * away['defence'])
    a = bound(league.mu_a * away['attack'] * home['defence'])
    n = len(h2h)
    weight = H2H_WEIGHT * n / (n + H2H_PRIOR) if n >= H2H_MIN else 0.0
    if weight:
        h = bound(h + weight * (np.mean([m['home_goals'] for m in h2h]) - h))
        a = bound(a + weight * (np.mean([m['away_goals'] for m in h2h]) - a))
    h, h_delta = frequency_adjust(h, home['scored_evidence'], away['conceded_evidence'])
    a, a_delta = frequency_adjust(a, away['scored_evidence'], home['conceded_evidence'])
    info = {'status':'applied', 'home': {k:home[k] for k in ('last5','last10','venue5','window_weights')},
            'away': {k:away[k] for k in ('last5','last10','venue5','window_weights')},
            'h2h': {'n':n, 'weight':weight, 'matches':h2h},
            'scoring_probability_delta': {'home':h_delta, 'away':a_delta},
            'squad_availability': 'not_used'}
    return h, a, info
