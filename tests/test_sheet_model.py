"""The supplied workbook snapshot is the numerical oracle; the workbook itself stays private."""
import math
from datetime import datetime
from types import SimpleNamespace

import pytest
import sheet_model


INPUT = {'home_gf_home': 2, 'home_ga_home': 1, 'away_gf_away': .67,
         'away_ga_away': 1.17, 'lg_home': 1.14, 'lg_away': .84,
         'home_xg': 2.14, 'home_xga': .53, 'away_xg': 1., 'away_xga': 2.24,
         'home_sot': 7, 'away_sot': 2, 'home_ppg': 2.6, 'away_ppg': .6,
         'home_recent_gf': 2, 'away_recent_gf': .667}


def test_workbook_example_v1_and_v4():
    one, four = sheet_model.v1(INPUT), sheet_model.v4(INPUT)
    assert one['lambda_h'] == pytest.approx(2.053, abs=.0005)
    assert one['lambda_a'] == pytest.approx(.798, abs=.0005)
    assert dict(one['markets'])['Home Win'] == pytest.approx(.6644, abs=.0001)
    assert dict(one['markets'])['Over 2.5 Goals'] == pytest.approx(.5424, abs=.0001)
    assert four['lambda_h'] == pytest.approx(2.203, abs=.0005)
    assert four['lambda_a'] == pytest.approx(.695, abs=.0005)
    assert dict(four['markets'])['Home Win'] == pytest.approx(.7191, abs=.0001)
    assert dict(four['markets'])['Over 2.5 Goals'] == pytest.approx(.5537, abs=.0001)
    assert dict(four['markets'])['BTTS Yes'] == pytest.approx(.4456, abs=.0001)


def test_missing_or_invalid_inputs_not_replaced_with_zero():
    for value in (None, float('nan'), float('inf'), -1):
        assert sheet_model.v1(INPUT | {'lg_home': value}) is None
        assert sheet_model.v4(INPUT | {'home_xg': value}) is None
    assert sheet_model.v1(INPUT | {'home_gf_home': 0})['lambda_h'] == 0
    assert sheet_model.v4(INPUT | {'away_sot': 0}) is not None  # workbook floor is .01


def test_match_uses_actual_samples_and_refuses_incomplete_v4():
    def obs(venue, gf, ga, **extra):
        return {'venue': venue, 'gf': gf, 'ga': ga, 'div': 'E0', 'season': 'current', **extra}
    home = [obs('H', 2, 1), obs('A', 5, 0)]
    away = [obs('A', 0, 2), obs('H', 1, 1)]
    row = SimpleNamespace(fx={'date': datetime(2026, 11, 4), 'home': 'Home', 'away': 'Away', 'div': 'E0'},
                          home=SimpleNamespace(matches=home), away=SimpleNamespace(matches=away),
                          div_avg=SimpleNamespace(mu_h=1.5, mu_a=1), extra=SimpleNamespace(x12={}),
                          p_model={'O15': .8, 'O25': .5, 'O35': .3, 'BTTS': .4})
    result = sheet_model.for_match(row, 'Example')
    assert result['ok'] and not result['v4']['ok']
    assert result['inputs']['home_gf_home'] == 2
    assert result['inputs']['away_gf_away'] == 0
    assert result['model']['lambda_h'] == pytest.approx(2*2/1.5)
    assert result['model']['lambda_a'] == 0
    assert 'home_xg' in result['v4']['missing']
    assert all(math.isfinite(m['p']) for m in result['markets'])
    row.home.matches = [obs('A', 3, 2)]
    result = sheet_model.for_match(row, 'Example')
    assert result['inputs']['home_venue_n'] == 0
    assert result['inputs']['home_gf_home'] == 3  # explicit overall-sample fallback


def test_v4_uses_current_competition_sample_and_six_recent_games():
    def match(i, venue):
        return {'venue': venue, 'gf': 2, 'ga': 1, 'div': 'E0', 'season': 'current',
                'xg_for': 1.7, 'xg_against': 1.1, 'sot_for': 4}
    matches = [match(i, 'H' if i % 2 else 'A') for i in range(6)]
    row = SimpleNamespace(fx={'date': datetime(2026, 11, 4), 'home': 'H', 'away': 'A', 'div': 'E0'},
                          home=SimpleNamespace(matches=matches), away=SimpleNamespace(matches=matches),
                          div_avg=SimpleNamespace(mu_h=1.5, mu_a=1), extra=SimpleNamespace(x12={}),
                          p_model={'O15': .8, 'O25': .5, 'O35': .3, 'BTTS': .4})
    row.sb = {'1X2': [1.9, 3.0, 3.8], 'OU': None}
    data = sheet_model.for_match(row, 'Example')
    assert data['v4']['ok']
    home = data['v4']['markets'][0]
    assert home['odds'] == 1.9
    assert home['implied'] == pytest.approx(1/1.9)
    assert home['ev'] == pytest.approx(home['p'] * 1.9 - 1)
    assert home['edge'] == pytest.approx(home['p'] - 1/1.9)
    assert data['v4']['markets'][4]['value_signal'] == 'ENTER ODDS'
    assert data['inputs']['home_xg_n'] == 6
    assert data['inputs']['home_ppg'] == 3
    matches[0]['xg_for'] = None
    matches[1]['xg_for'] = None
    matches[2]['xg_for'] = None
    matches[3]['xg_for'] = None
    assert not sheet_model.for_match(row, 'Example')['v4']['ok']
