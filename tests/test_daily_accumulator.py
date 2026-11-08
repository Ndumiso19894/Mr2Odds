from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import time

from mr2odds import daily_accumulator as da

NOW = datetime(2026, 11, 8, 8, tzinfo=timezone(timedelta(hours=2)))


def fixture(i, price=1.20, p=.84, market=.80, quality='High', league='Premier League'):
    name = f'Club {i}'
    return {'id': f'2026-11-08|England|{name}|Away', 'date': '2026-11-08',
            'kickoff': '2026-11-08 18:00', 'country': 'England', 'league': league,
            'home': name, 'away': 'Away', 'q': quality, 'data_ok': True,
            'sels': [['O15', p, p, market, price, 0, None, None]], 'd': f'{i:012x}'}


def shortlist(fixtures):
    return {'primary': [{'fixture': f['id'], 'sel': f['sels'][0][0]} for f in fixtures]}


def test_three_disjoint_tickets_and_six_alternatives():
    fixtures = [fixture(i) for i in range(24)]
    data = da.daily_selection(fixtures, shortlist(fixtures), NOW)
    assert data['summary']['n_accumulators'] == 3
    assert data['summary']['n_alternatives'] == 6
    ids = []
    for g in data['accumulators']:
        assert len(g['legs']) == 6  # 1.20 requires six legs to reach 2.50
        product = Decimal(1)
        for leg in g['legs']:
            assert leg['odds'] >= 1.18
            ids.append(leg['match_id'])
            product *= Decimal(str(leg['odds']))
        assert Decimal('2.50') <= product <= Decimal('3.50')
        assert g['odds'] == round(float(product), 2)
    assert len(ids) == len(set(ids))
    assert not set(ids) & {a['match_id'] for a in data['alternatives']}
    json.dumps(data, allow_nan=False)


def test_fail_closed_on_price_probability_quality_competition_and_time():
    cases = [fixture(i) for i in range(10)]
    cases[0]['sels'][0][4] = 1.17999
    cases[1]['sels'][0][1] = .79999
    cases[2]['q'] = 'Medium'
    cases[3]['sels'][0][3] = None
    cases[4]['sels'][0][3] = .759
    cases[5]['sels'][0][5] = 1
    cases[6]['league'] = 'FA Cup'
    cases[7]['kickoff'] = '2026-11-08 08:09'
    cases[8]['sels'][0][0] = 'U25'
    cases[9]['data_ok'] = False
    assert da.daily_selection(cases, shortlist(cases), NOW)['accumulators'] == []
    assert da.daily_selection(cases, shortlist(cases), NOW)['alternatives'] == []
    boundary = fixture(999, price=1.18, p=.84, market=.76)
    assert da._candidates([boundary], shortlist([boundary]), NOW)[0]['odds'] == 1.18
    assert not da._candidates([boundary], {'primary': []}, NOW)


def test_bound_and_no_fabrication():
    cases = [fixture(i, price=1.18) for i in range(400)]
    start = time.monotonic()
    result = da.daily_selection(cases, shortlist(cases), NOW)
    assert time.monotonic() - start < 5
    assert len(result['accumulators']) == 3
    impossible = [fixture(i, price=1.18) for i in range(5)]
    assert da.daily_selection(impossible, shortlist(impossible), NOW)['accumulators'] == []


def test_research_uses_existing_detail_without_network(tmp_path):
    f = fixture(1)
    key = f['d']
    (tmp_path / f'{key}.json').write_text(json.dumps({'id': f['id'], 'home': f['home'], 'away': f['away'],
      'xg': {'home': 1.4, 'away': 1.1, 'total': 2.5}, 'p': {'O25': .6},
      'teams': {'home': {'n': 12, 'last5': []}, 'away': {'n': 11, 'last5': []}},
      'news': {'home': [{'title': 'Team news', 'source': 'News'}]}}))
    x = da._candidates([f], shortlist([f]), NOW)[0]
    research = da._research(x, tmp_path)
    assert research['sample_home'] == 12
    assert research['news'][0]['title'] == 'Team news'
    assert da._research({**x, 'match_id': 'different'}, tmp_path) is None
