"""Daily accumulator candidates from the same stricter Final Picks as the app.

No prices or matches are created here. These are rolling pre-match selections,
not a frozen daily record; the app revalidates them against each publication.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import competition_policy
import recommendation_policy as policy
import safe

ODDS_LOW, ODDS_HIGH = Decimal('2.50'), Decimal('3.50')
MIN_PRICE, MAX_PRICE = 1.18, 1.90
MAX_LEGS, MAX_POOL, MAX_ALTERNATIVES = 8, 36, 12


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _candidates(index, shortlist, now):
    by_id = {f.get('id'): f for f in index if f.get('id')}
    seen, result = set(), []
    current = now.replace(tzinfo=None)
    for row in (shortlist or {}).get('primary', []):
        f = by_id.get(row.get('fixture'))
        if not f or f['id'] in seen or f.get('q') != 'High' or not f.get('data_ok'):
            continue
        if not competition_policy.allowed(f.get('country'), f.get('league'), f.get('div'), f.get('home'), f.get('away')):
            continue
        try:
            kickoff = datetime.strptime(f['kickoff'], '%Y-%m-%d %H:%M')
        except (ValueError, KeyError, TypeError):
            continue
        if f.get('date') != current.date().isoformat() or kickoff.date() != current.date() or kickoff <= current + timedelta(minutes=10):
            continue
        sel = next((s for s in f.get('sels', []) if len(s) >= 6 and s[0] == row.get('sel')), None)
        if not sel:
            continue
        code, p, model, market, odds, diff = sel[:6]
        if (not policy.allowed(code) or not all(_number(x) for x in (p, model, market, odds)) or
                not .80 <= p < 1 or not 0 < model < 1 or not 0 < market < 1 or
                not MIN_PRICE <= odds <= MAX_PRICE or p * odds < .98 or
                abs(model-market) > .08 + 1e-12 or diff or policy.outlier(model, market, odds)):
            continue
        seen.add(f['id'])
        result.append({'match_id': f['id'], 'match': f"{f['home']} v {f['away']}",
                       'home': f['home'], 'away': f['away'], 'league': f.get('league') or '',
                       'country': f.get('country') or '', 'kickoff': f['kickoff'], 'sel': code,
                       'label': safe.label(code, f['home'], f['away']), 'odds': odds,
                       'p_model': p, 'p_market': market, 'data_quality': 'High', 'detail_key': f.get('d')})
    return sorted(result, key=lambda x: (-x['p_model'], -x['odds'], x['match_id']))


def _find_group(pool):
    """Find a short, high-ranked valid group; bounded search with price pruning.

    The 36-candidate bound and the upper-bound pruning protect the live scan
    from the previous unbounded combinations of hundreds of markets.
    """
    pool = pool[:MAX_POOL]
    prices = [Decimal(str(x['odds'])) for x in pool]
    n = len(pool)
    # Maximum product obtainable from a suffix using exactly k selections.
    maximum = [[Decimal(0)] * (MAX_LEGS + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        maximum[i][0] = Decimal(1)
    for i in range(n - 1, -1, -1):
        for k in range(1, MAX_LEGS + 1):
            maximum[i][k] = max(maximum[i + 1][k], prices[i] * maximum[i + 1][k - 1])

    def find(start, left, product, selected):
        if left == 0:
            return selected if ODDS_LOW <= product <= ODDS_HIGH else None
        if n - start < left or product > ODDS_HIGH or product * maximum[start][left] < ODDS_LOW:
            return None
        for i in range(start, n - left + 1):
            found = find(i + 1, left - 1, product * prices[i], selected + [pool[i]])
            if found:
                return found
        return None

    for k in range(2, min(MAX_LEGS, n) + 1):
        found = find(0, k, Decimal(1), [])
        if found:
            return found
    return None


def _research(item, details_path):
    """Use already-collected fixture detail; never make unbudgeted news requests."""
    key = item.get('detail_key') or ''
    if not details_path or not all(c in '0123456789abcdef' for c in key) or len(key) != 12:
        return None
    try:
        detail = json.loads((Path(details_path) / f'{key}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if detail.get('id') != item['match_id'] or detail.get('home') != item['home'] or detail.get('away') != item['away']:
        return None
    xg = detail.get('xg') or {}
    teams = detail.get('teams') or {}
    news = detail.get('news') or {}
    headlines = []
    for side in ('home', 'away'):
        for h in (news.get(side) or [])[:3]:
            if isinstance(h, dict) and h.get('title'):
                headlines.append({'team': item[side], 'title': str(h['title']), 'source': str(h.get('source') or ''), 'when': str(h.get('when') or '')})
    raw_1x2 = (detail.get('sportybet') or {}).get('1X2')
    prices = [value if _number(value) and value >= MIN_PRICE else None for value in raw_1x2] if isinstance(raw_1x2, list) else None
    return {'match_id': item['match_id'], 'match': item['match'], 'league': item['league'],
            'country': item['country'], 'kickoff': item['kickoff'], 'data_quality': 'High',
            'xg_home': xg.get('home'), 'xg_away': xg.get('away'), 'xg_total': xg.get('total'),
            'p_o25_model': (detail.get('p') or {}).get('O25'), 'p_o25_market': (detail.get('p') or {}).get('market_O25'),
            'sporty_1x2': prices,
            'sample_home': (teams.get('home') or {}).get('n'), 'sample_away': (teams.get('away') or {}).get('n'),
            'form_home': (teams.get('home') or {}).get('last5') or [], 'form_away': (teams.get('away') or {}).get('last5') or [],
            'h2h': detail.get('h2h') or [], 'news': headlines, 'bullets': []}


def daily_selection(index, shortlist, now, details_path=None):
    """Build up to three disjoint accumulators and available alternatives."""
    candidates = _candidates(index, shortlist, now)
    unused, groups = list(candidates), []
    for _ in range(3):
        group = _find_group(unused)
        if not group:
            break
        used = {x['match_id'] for x in group}
        unused = [x for x in unused if x['match_id'] not in used]
        total = math.prod(x['odds'] for x in group)
        groups.append({'n_legs': len(group), 'odds': round(total, 2), 'legs': group})
    alternatives = [{'match_id': x['match_id'], 'match': x['match'], 'country': x['country'],
                     'league': x['league'], 'kickoff': x['kickoff'], 'best_sel': x['sel'],
                     'best_label': x['label'], 'best_odds': x['odds'], 'best_p_model': x['p_model'],
                     'best_p_market': x['p_market'], 'data_quality': x['data_quality']} for x in unused[:MAX_ALTERNATIVES]]
    acca_research = [_research(x, details_path) for g in groups for x in g['legs']]
    alt_ids = {x['match_id'] for x in alternatives}
    alt_research = [_research(x, details_path) for x in unused if x['match_id'] in alt_ids]
    return {'generated': now.strftime('%Y-%m-%d %H:%M'), 'date': now.strftime('%Y-%m-%d'),
            'accumulators': groups, 'alternatives': alternatives,
            'research': {'accumulators': [x for x in acca_research if x], 'alternatives': [x for x in alt_research if x]},
            'summary': {'n_accumulators': len(groups), 'n_alternatives': len(alternatives), 'odds_band': [2.50, 3.50]}}
