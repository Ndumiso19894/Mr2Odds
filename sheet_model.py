"""Read-only reproduction of the supplied workbook's V1 and V4 formulae.

This is a comparison, not an input to the scanner's recommendation model.
"""
from __future__ import annotations

import math


def _num(v):
    try:
        v = float(v)
        return v if math.isfinite(v) and v >= 0 else None
    except (TypeError, ValueError):
        return None


def _mean(values):
    a = [_num(v) for v in values]
    a = [v for v in a if v is not None]
    return sum(a) / len(a) if a else None


def _poisson(n, rate):
    return math.exp(-rate) * rate ** n / math.factorial(n)


def _markets(h, a, limit):
    hs = [_poisson(i, h) for i in range(limit + 1)]
    aw = [_poisson(i, a) for i in range(limit + 1)]
    if limit == 7:  # V1's explicit 0..7 x 0..7 matrix, not renormalised
        home = sum(hs[i] * aw[j] for i in range(8) for j in range(8) if i > j)
        draw = sum(hs[i] * aw[i] for i in range(8))
        away = sum(hs[i] * aw[j] for i in range(8) for j in range(8) if i < j)
    else:  # V4: away win is the workbook's residual 1 - home - draw
        home = sum(aw[j] * (1 - sum(hs[:j + 1])) for j in range(limit + 1))
        draw = sum(hs[i] * aw[i] for i in range(limit + 1))
        away = 1 - home - draw
    total = h + a
    over = lambda rate, n: 1 - sum(_poisson(i, rate) for i in range(n + 1))
    return [('Home Win', home), ('Draw', draw), ('Away Win', away),
            ('Over 0.5 Goals', over(total, 0)), ('Over 1.5 Goals', over(total, 1)),
            ('Over 2.5 Goals', over(total, 2)), ('Over 3.5 Goals', over(total, 3)),
            ('BTTS Yes', (1-math.exp(-h))*(1-math.exp(-a))),
            ('BTTS No', 1-(1-math.exp(-h))*(1-math.exp(-a))),
            ('Home Over 0.5', over(h, 0)), ('Home Over 1.5', over(h, 1)),
            ('Away Over 0.5', over(a, 0)), ('Away Over 1.5', over(a, 1))]


def v1(inputs):
    names = ('home_gf_home', 'home_ga_home', 'away_gf_away', 'away_ga_away', 'lg_home', 'lg_away')
    v = {k: _num(inputs.get(k)) for k in names}
    if any(x is None for x in v.values()) or not v['lg_home'] or not v['lg_away']:
        return None
    ha, hd = v['home_gf_home']/v['lg_home'], v['home_ga_home']/v['lg_away']
    aa, ad = v['away_gf_away']/v['lg_away'], v['away_ga_away']/v['lg_home']
    h, a = v['lg_home']*ha*ad, v['lg_away']*aa*hd
    vals = _markets(h, a, 7)
    x12 = sum(x[1] for x in vals[:3])
    return {'home_attack': ha, 'home_defence': hd, 'away_attack': aa, 'away_defence': ad,
            'lambda_h': h, 'lambda_a': a, 'lambda_total': h+a, 'x12_sum': x12,
            'matrix_residual': max(0, 1-x12), 'markets': vals}


def v4(inputs):
    """Workbook V3_ENGINE B41:B44 and V4_ENGINE B26:B29, default weights."""
    base = v1(inputs)
    keys = ('home_xg', 'home_xga', 'away_xg', 'away_xga', 'home_sot', 'away_sot',
            'home_ppg', 'away_ppg', 'home_recent_gf', 'away_recent_gf')
    x = {k: _num(inputs.get(k)) for k in keys}
    if base is None or any(v is None for v in x.values()):
        return None
    h, a = base['lambda_h'], base['lambda_a']
    xh = (x['home_xg'] + x['away_xga'])/2
    xa = (x['away_xg'] + x['home_xga'])/2
    sh = inputs['lg_home'] * x['home_sot']/max(x['away_sot'], .01)
    sa = inputs['lg_away'] * x['away_sot']/max(x['home_sot'], .01)
    rh = .35*h + .65*x['home_recent_gf']
    ra = .35*a + .65*x['away_recent_gf']
    strength_h = max(.9, min(1.1, 1+(x['home_ppg']-x['away_ppg'])*.04))
    strength_a = max(.9, min(1.1, 1+(x['away_ppg']-x['home_ppg'])*.04))
    def blend(signals, weights):
        return math.exp(sum(w * math.log(max(v, .05)) for v, w in zip(signals, weights)))
    raw_h = blend((h, xh, rh, rh*strength_h, min(sh, 3.5), strength_h*h), (.3, .3, .15, .1, .05, .1))
    raw_a = blend((a, xa, ra, ra*strength_a, min(sa, 3), strength_a*a), (.3, .3, .15, .1, .05, .1))
    h3 = max(.05, min(4.5, .75*raw_h + .25*h))
    a3 = max(.05, min(4.5, .75*raw_a + .25*a))
    raw_h4 = blend((h3, xh, rh, rh*strength_h, min(sh, 3.5), strength_h*h3), (.35, .3, .1, .1, .05, .1))
    raw_a4 = blend((a3, xa, ra, ra*strength_a, min(sa, 3), strength_a*a3), (.35, .3, .1, .1, .05, .1))
    h4 = max(.05, min(4.5, .8*raw_h4 + .2*h3))
    a4 = max(.05, min(4.5, .8*raw_a4 + .2*a3))
    return {'lambda_h': h4, 'lambda_a': a4, 'lambda_total': h4+a4, 'markets': _markets(h4, a4, 24)}


def for_match(r, comp):
    fx = r.fx
    home = list(getattr(r.home, 'matches', None) or [])
    away = list(getattr(r.away, 'matches', None) or [])
    hv = [m for m in home if m.get('venue') == 'H']
    av = [m for m in away if m.get('venue') == 'A']
    # If no venue observations exist, use the actual overall sample, clearly labelled.
    hi, ai = hv or home, av or away
    inputs = {'competition': comp, 'date': fx['date'].strftime('%Y-%m-%d'),
              'home': fx['home'], 'away': fx['away'], 'venue': fx.get('venue') if isinstance(fx.get('venue'), str) else None,
              'home_venue_n': len(hv), 'away_venue_n': len(av),
              'home_gf_home': _mean(m.get('gf') for m in hi), 'home_ga_home': _mean(m.get('ga') for m in hi),
              'away_gf_away': _mean(m.get('gf') for m in ai), 'away_ga_away': _mean(m.get('ga') for m in ai),
              # Scanner division baselines are shrunk/time-weighted; they are not a raw workbook statistic.
              'lg_home': _num(r.div_avg.mu_h), 'lg_away': _num(r.div_avg.mu_a)}
    for side, matches in [('home', home), ('away', away)]:
        current = [m for m in matches if m.get('season') == 'current' and m.get('div') == fx.get('div')]
        inputs[side+'_current_n'] = len(current)
        for field, key in [('xg_for','xg'), ('xg_against','xga'), ('sot_for','sot')]:
            vals = [_num(m.get(field)) for m in current]
            vals = [v for v in vals if v is not None]
            inputs[side+'_'+key+'_n'] = len(vals)
            inputs[side+'_'+key] = _mean(vals) if len(vals) >= 3 else None
        inputs[side+'_ppg'] = _mean(3 if m['gf'] > m['ga'] else 1 if m['gf'] == m['ga'] else 0 for m in current) if len(current) >= 3 else None
        recent = matches[:6]
        inputs[side+'_recent_gf'] = _mean(m.get('gf') for m in recent) if len(recent) == 6 else None
        inputs[side+'_recent_ga'] = _mean(m.get('ga') for m in recent) if len(recent) == 6 else None
    one = v1(inputs)
    four = v4(inputs)
    missing = [k for k in ('home_gf_home','home_ga_home','away_gf_away','away_ga_away','lg_home','lg_away') if inputs.get(k) is None]
    missing4 = [k for k in ('home_xg','home_xga','away_xg','away_xga','home_sot','away_sot','home_ppg','away_ppg','home_recent_gf','away_recent_gf') if inputs.get(k) is None]
    compare = {'Home Win': (r.extra.x12 or {}).get('H'), 'Draw': (r.extra.x12 or {}).get('D'),
               'Away Win': (r.extra.x12 or {}).get('A'), 'Over 1.5 Goals': r.p_model.get('O15'),
               'Over 2.5 Goals': r.p_model.get('O25'), 'Over 3.5 Goals': r.p_model.get('O35'),
               'BTTS Yes': r.p_model.get('BTTS')}
    sb = getattr(r, 'sb', None) or {}
    hda = sb.get('1X2') or (None, None, None)
    btts = sb.get('BTTS') or (None, None)
    prices = {'Home Win': hda[0], 'Draw': hda[1], 'Away Win': hda[2], 'BTTS Yes': btts[0], 'BTTS No': btts[1]}
    for line in (.5, 1.5, 2.5, 3.5):
        prices[f'Over {line} Goals'] = ((sb.get('OU') or {}).get(line) or (None, None))[0]
    for label, key in [('Home', 'TGH'), ('Away', 'TGA')]:
        for line in (.5, 1.5):
            prices[f'{label} Over {line}'] = ((sb.get(key) or {}).get(line) or (None, None))[0]
    def rows(model, dashboard=False):
        output = []
        for name, p in (model or {}).get('markets', []):
            row = {'name': name, 'p': p, 'fair': 1/p if p > 0 else None, 'playreport': _num(compare.get(name))}
            if dashboard:
                odds = _num(prices.get(name))
                odds = odds if odds is not None and odds > 1 else None
                ev = p*odds-1 if odds else None
                safety = 'SAFEST' if p >= .75 else 'SAFER' if p >= .6 else 'MODERATE' if p >= .5 else 'RISKY'
                signal = 'ENTER ODDS' if odds is None else 'VALUE' if ev >= .05 else 'THIN VALUE' if ev >= 0 else 'NO VALUE'
                decision = 'SAFEST MARKETS' if p >= .75 else 'AVOID / HIGH RISK' if p < .5 else 'VALUE CANDIDATE' if ev is not None and ev >= .05 else 'WATCH'
                row.update({'odds': odds, 'implied': 1/odds if odds else None, 'edge': p-1/odds if odds else None,
                            'ev': ev, 'safety': safety, 'value_signal': signal, 'decision': decision})
            output.append(row)
        return output
    result = {'ok': one is not None, 'inputs': inputs, 'model': {k: v for k,v in (one or {}).items() if k != 'markets'},
              'markets': rows(one), 'missing': missing,
              'used': ['Unweighted venue sample (overall sample if venue empty)', 'Scanner baselines (time-weighted and shrunk; may fall back to global)'],
              'note': 'Comparison only; scanner recommendations are unchanged.',
              'v4': {'ok': four is not None, 'missing': missing4, 'model': {k:v for k,v in (four or {}).items() if k != 'markets'},
                     'markets': rows(four, dashboard=True), 'note': 'Uncalibrated; current-season statistics use available sampled matches and an inferred season, not necessarily the full season. V3/V4 formulas do not use recent conceded goals despite their labels.'}}
    return result
