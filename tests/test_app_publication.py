"""Regression tests for the scanner-to-home and shortlist payload contracts."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd

import appdata
import safe
import verify

NOW = datetime(2026, 11, 4, 8)


def fixture(name, kickoff=None, ok=True, quality='High', selections=()):
    kickoff = kickoff or NOW + timedelta(hours=2)
    return {'id': f'{kickoff:%Y-%m-%d}|England|{name}|Away', 'date': f'{kickoff:%Y-%m-%d}',
            'kickoff': f'{kickoff:%Y-%m-%d %H:%M}', 'home': name, 'away': 'Away', 'country': 'England',
            'league': 'Test', 'data_ok': ok, 'q': quality, 'sels': list(selections)}


def sel(code, p, odds=1.3, market=0.8, diff=0):
    return [code, p, p, market, odds, diff, None, None]


def test_shortlist_screening_and_1x2():
    data = [fixture('Qualified', selections=[sel('O15', .82), sel('O25', .72, 1.5, .7), sel('H', .65, 1.7, .6)]),
            fixture('Other', selections=[sel('CO95', .73, 1.4, .7)]),
            fixture('Unpriced', selections=[sel('O15', .9, None)]),
            fixture('Outlier', selections=[sel('O15', .9, 1.4, .6, 1)]),
            fixture('Low data', ok=False, selections=[sel('O15', .9)]),
            fixture('Low quality', quality='Low', selections=[sel('O15', .9)]),
            fixture('Dropped', selections=[sel('BTTS', .9), sel('HO05', .9), sel('U25', .9)]),
            fixture('Started', NOW - timedelta(hours=1), selections=[sel('O15', .9)]),
            fixture('Tomorrow', NOW + timedelta(days=1), selections=[sel('O15', .9)])]
    result = appdata.shortlist_payload(data, NOW)
    assert [(x['home'], x['sel']) for x in result['primary']] == [('Qualified', 'O15'), ('Other', 'CO95')]
    assert [(x['home'], x['sel']) for x in result['x12']] == [('Qualified', 'H')]
    assert result['counts']['analysed'] == 6


def test_probability_precision_does_not_promote_rounded_80():
    s = safe.Sel('O15', .7996, .78, 1.3)
    row = appdata._selection_rows([safe.sel_dict(s, 'Home', 'Away')])[0]
    assert row[1] == .7996


def test_export_includes_home_selections_and_shortlist(tmp_path, monkeypatch):
    fx = pd.Series({'date': NOW, 'kickoff': NOW + timedelta(hours=2), 'country': 'England',
                    'home': 'Home', 'away': 'Away', 'league': 'Test', 'div': 'X'}, name=0)
    prof = SimpleNamespace(n=12)
    extra = SimpleNamespace(x12={}, tg={}, corners=None, corner_p={}, cards=None, card_p={})
    probs = {'O15': .82, 'O25': .6, 'O35': .3, 'BTTS': .55}
    row = SimpleNamespace(fx=fx, home=prof, away=prof, extra=extra, audit={'quality': {'overall': 'High'}},
                          data_ok=True, basis='model', mod_h=1.5, mod_a=1.0, mkt_h=float('nan'), mkt_a=float('nan'),
                          p_final=probs, p_model=probs, p_market_o25=None, fair={}, x12_market=None,
                          sb={'OU': {1.5: (1.3, 3.8)}}, sb_event=None, sb_full=None, h2h=[], div_avg=SimpleNamespace(mu_h=1.5, mu_a=1, o25_rate=.5),
                          trends={}, mkt_source='')
    monkeypatch.setattr(appdata, '_profile', lambda _: {})
    rows = [safe.sel_dict(s, 'Home', 'Away') for s in safe.selections(row)]
    stage = tmp_path / 'stage'; stage.mkdir()
    appdata.export(stage / 'latest.json', ctx={'now': NOW, 'start': NOW, 'end': NOW + timedelta(days=1),
                   'window_end': NOW + timedelta(hours=4), 'run': 'test'}, rows=[row], picks={}, tracker_summary={},
                   notes=[], ls_map={}, helpers={'render_details': lambda *_: '', 'stars': lambda *_: 1,
                   'comp': lambda _: 'Test', 'sb_price': lambda *_: 1.3, 'selections': lambda _: rows},
                   reports_dir=tmp_path, tz_label='SAST', thresholds={}, backtest={}, repo=None)
    data = json.loads((stage / 'latest.json').read_text())
    detail = json.loads((stage / 'fx' / (data['fixtures'][0]['d'] + '.json')).read_text())
    assert data['fixtures'][0]['sels'] == detail['sels']
    assert data['shortlist']['primary'][0]['sel'] == 'O15'
    assert data['shortlist']['primary'][0]['fixture'] == data['fixtures'][0]['id']
    errors, _ = verify.check_publication(stage, stage, tmp_path / 'ledger.csv', NOW, 1)
    assert not errors, errors
    del data['fixtures'][0]['sels']
    (stage / 'latest.json').write_text(json.dumps(data))
    errors, _ = verify.check_publication(stage, stage, tmp_path / 'ledger.csv', NOW, 1)
    assert any('missing index selections' in e for e in errors)


def test_today_signals_not_crowded_out_by_60_day_window(monkeypatch):
    def row(name, day, p):
        return SimpleNamespace(data_ok=True, fx={'kickoff': day, 'date': day, 'country': 'England',
              'home': name, 'away': 'Away', 'div': 'X', 'league': 'Test'}, p=p)
    items = [row('Today', NOW + timedelta(hours=2), .72)]
    items += [row(f'Future{i}', NOW + timedelta(days=5), .85) for i in range(50)]
    monkeypatch.setattr(safe, 'selections', lambda r: [safe.Sel('O15', r.p, r.p, 1.4)])
    result = safe.safest(items, NOW, NOW + timedelta(hours=4))
    assert len(result['bets']) == safe.MAX_BETS
    assert result['bets'][0].home == 'Today'
    assert all(b.p >= safe.MIN_P and b.odds >= safe.MIN_ODDS for b in result['bets'])


def test_visible_signals_not_displaced_by_hidden_markets(monkeypatch):
    def row(i):
        ko = NOW + timedelta(hours=2)
        return SimpleNamespace(data_ok=True, fx={'kickoff': ko, 'date': ko, 'country': 'England',
              'home': str(i), 'away': 'Away', 'div': 'X', 'league': 'Test'}, i=i)
    rows = [row(i) for i in range(50)]
    monkeypatch.setattr(safe, 'selections', lambda r: [safe.Sel('O15' if r.i == 49 else 'HO05',
                                                                .72 if r.i == 49 else .85, .8, 1.4)])
    result = safe.safest(rows, NOW, NOW + timedelta(hours=4))
    assert result['bets'][0].sel == 'O15'
    assert len(result['bets']) == safe.MAX_BETS
