"""Provisional bounded statistical adjustments, not calibrated or proven to improve accuracy.

Use only genuine observations, never infer missing xG or shots off target. Baselines and team
profiles must be built from completed matches available before the analysis. These adjustments
are disabled by default and need point-in-time chronological validation.
"""
from __future__ import annotations
import math
import pandas as pd


def _usable(value, n):
    try:
        return n >= 5 and math.isfinite(float(value)) and float(value) >= 0
    except (TypeError, ValueError):
        return False


def sot_baselines(results):
    if results.empty or not {'div', 'hst', 'ast'} <= set(results):
        return {}
    df = results[['div', 'hst', 'ast']].copy()
    for c in ('hst', 'ast'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    df = df[(df.hst >= 0) & (df.ast >= 0) & (df.hst < 50) & (df.ast < 50)]
    return {str(d): float((g.hst.mean() + g.ast.mean()) / 2) for d, g in df.groupby('div')
            if len(g) >= 30 and g.hst.mean() + g.ast.mean() > 0}


def goal_adjustment(base, attack, defence, sot_baseline):
    details = {'baseline': base, 'xg_applied': False, 'sot_applied': False}
    value = base
    a_counts, d_counts = getattr(attack, 'signal_counts', {}), getattr(defence, 'signal_counts', {})
    xgf, xga = getattr(attack, 'signal_values', {}).get('xg_for'), getattr(defence, 'signal_values', {}).get('xg_against')
    if _usable(xgf, a_counts.get('xg_for', 0)) and _usable(xga, d_counts.get('xg_against', 0)):
        target = (xgf + xga) / 2
        ratio = max(.5, min(1.5, target / base))
        value *= 1 + .10 * (ratio - 1)
        details.update(xg_applied=True, xg_for=xgf, xga=xga, xg_target=target)
    sf, sa = getattr(attack, 'signal_values', {}).get('sot_for'), getattr(defence, 'signal_values', {}).get('sot_against')
    if (_usable(sf, a_counts.get('sot_for', 0)) and _usable(sa, d_counts.get('sot_against', 0))
            and sot_baseline is not None and sot_baseline > 0):
        ratio = max(.5, min(1.5, ((sf + sa) / 2) / sot_baseline))
        value *= 1 + .05 * (ratio - 1)
        details.update(sot_applied=True, sot_for=sf, sot_against=sa, sot_baseline=sot_baseline)
    value = max(.15, min(4.5, value))
    details['adjusted'] = value
    return value, details


def corner_adjustment(home, away, shots_h, shots_a, baseline_h, baseline_a):
    details = {'applied': False, 'baseline_home': home, 'baseline_away': away}
    if not all(math.isfinite(x) and x > 0 for x in (baseline_h, baseline_a)):
        return home, away, details
    def factor(x, avg):
        return 1 + .05 * (max(.5, min(1.5, x / avg)) - 1)
    adjusted_h, adjusted_a = home * factor(shots_h, baseline_h), away * factor(shots_a, baseline_a)
    details.update(applied=True, shots_off_home=shots_h, shots_off_away=shots_a,
                   shot_baseline_home=baseline_h, shot_baseline_away=baseline_a,
                   adjusted_home=adjusted_h, adjusted_away=adjusted_a)
    return adjusted_h, adjusted_a, details
