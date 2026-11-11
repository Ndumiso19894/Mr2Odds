"""Provisional feature integration and missing-data guards (not a predictive backtest)."""
from types import SimpleNamespace
from datetime import datetime
import math
import pandas as pd
import pytest
import model_signals as ms
import safe
import scanner
import appdata
import worldfeed


def profile(xgf=2.5, xga=2.2, sf=7., sa=6., n=8):
    return SimpleNamespace(signal_values=dict(xg_for=xgf, xg_against=xga, sot_for=sf, sot_against=sa),
                           signal_counts=dict(xg_for=n, xg_against=n, sot_for=n, sot_against=n))


def test_goal_adjustments_require_real_sufficient_data_and_are_bounded():
    p, flags = ms.goal_adjustment(1.5, profile(), profile(), 4.)
    assert p > 1.5 and flags['xg_applied'] and flags['sot_applied']
    q, flags = ms.goal_adjustment(1.5, profile(n=4), profile(), 4.)
    assert q == 1.5 and not flags['xg_applied'] and not flags['sot_applied']
    broken = profile(xgf=float('nan'), sf=-1)
    assert ms.goal_adjustment(1.5, broken, profile(), 4.)[0] == 1.5
    # Extreme readings are capped and never cause extreme probabilities.
    high = profile(xgf=100, xga=100, sf=100, sa=100)
    assert ms.goal_adjustment(1.5, high, high, 4.)[0] <= 1.5 * 1.05 * 1.025


def test_shot_baselines_and_explicit_off_target_only():
    rows = pd.DataFrame({'div':['E0'] * 29, 'hst':[3]*29, 'ast':[5]*29})
    assert ms.sot_baselines(rows) == {}
    rows.loc[29] = ['E0', 3, 5]
    assert ms.sot_baselines(rows)['E0'] == 4
    h, a, details = ms.corner_adjustment(5, 4, 20, 0, 4, 4)
    assert h == pytest.approx(5 * 1.025) and a == pytest.approx(4 * .975) and details['applied']
    assert ms.corner_adjustment(5, 4, 20, 0, 0, 4)[:2] == (5, 4)


def test_world_archive_preserves_real_off_target_without_inferring_from_totals(tmp_path):
    archive = worldfeed.Archive(tmp_path)
    data = {'key':'eng/epl', 'country':'England', 'league':'Test',
            'events':{'old':['202610010900','h','H','a','A',1,0,0,0],
                      'new':['202610020900','h','H','a','A',1,0,0,0]},
            'stats':{'old':[3,4,1,1,0,0,10,11,4,5,50,50,2,3],
                     'new':[3,4,1,1,0,0,10,11,4,5,50,50,2,3,2,6]}}
    import json
    (archive.stages_dir / 'eng__epl.json').write_text(json.dumps(data))
    df = archive.results_frame(datetime(2026,1,1)).set_index('eid')
    assert math.isnan(df.loc['old','hsoff'])
    assert df.loc['new','hsoff'] == 2 and df.loc['new','asoff'] == 6


def test_team_prices_labels_and_settlement():
    extra = SimpleNamespace(x12={}, tg={}, corner_p={'home':{3.5:.7}, 'away':{3.5:.65}},
                            card_p={'total':{3.5:.72}, 'home':{1.5:.7}, 'away':{1.5:.68}})
    r = SimpleNamespace(sb={}, sb_full={'CORNH':{3.5:(1.4,2.8)}, 'CORNA':{3.5:(1.5,2.7)},
                        'CARDSH':{1.5:(1.4,2.8)}, 'CARDSA':{1.5:(1.5,2.7)}},
                        p_final={}, extra=extra)
    sels = {s.sel:s for s in safe.selections(r)}
    assert sels['CHO35'].odds == 1.4 and sels['CAO35'].odds == 1.5
    assert sels['KHO15'].odds is None and sels['KAO15'].odds is None
    assert sels['KO35'].odds is None # no total price invented
    assert safe.label('CHO35', 'One', 'Two') == 'One over 3.5 corners'
    assert safe.label('KAO15', 'One', 'Two') == 'Two over 1.5 cards'
    assert safe.settle('CHO35', 1, 0, 5, 0) is True
    assert safe.settle('CAO35', 1, 0, 5, 0) is False
    assert safe.settle('CHO35', 1, 0, 5, None) is True
    assert safe.settle('CO95', 1, 0, 5, None) is None
    assert safe.settle('KHO15', 1, 0, hcards=2) is None
    assert safe.settle('KAO15', 1, 0, hcards=2) is None
    assert safe.settle('CHO40', 1, 0, 4, 0) is None  # push, not a loss
    assert safe._cards({'hy': 2, 'hr': None}, 'h') is None


def test_requested_market_shortlists_keep_existing_filters():
    now = datetime(2026, 11, 4, 8)
    def fx(name, code, p, odds=1.5, q='High'):
        return {'id':name,'date':'2026-11-04','kickoff':'2026-11-04 10:00','data_ok':True,
                'home':name,'away':'B','country':'England','league':'Test','q':q,
                'sels':[[code,p,p,p,odds,0,None,None]]}
    result = fx('result','H',.65,1.5)
    result['x12_research'] = {'outcomes': {'H': {'eligible': True}}}
    data = [result,fx('btts','BTTS',.65,1.5),fx('teamcorners','CHO35',.65,1.5),
            fx('bookings','KHO15',.70,1.5),fx('no price','CAO35',.9,None),fx('low','KO35',.9,1.5,'Low'),
            fx('too-low','KAO15',.69,1.5), fx('disabled','HO05',.9)]
    picks = appdata.shortlist_payload(data, now)['primary']
    assert {p['home'] for p in picks} == {'result','btts','teamcorners'}


def test_analysis_uses_adjusted_lambdas_for_all_goal_markets(monkeypatch):
    H, A = scanner.TeamProfile('H'), scanner.TeamProfile('A')
    for p in (H, A):
        p.n = 10
        p.n_eff = 10
        p.rate_o15, p.rate_o25, p.rate_btts = .7, .5, .5
        p.signal_values = dict(xg_for=2.2, xg_against=2.0, sot_for=6., sot_against=6.)
        p.signal_counts = dict(xg_for=8, xg_against=8, sot_for=8, sot_against=8)
    monkeypatch.setattr(scanner, 'profile_cached', lambda long, country, name, *args: H if name == 'H' else A)
    monkeypatch.setattr(scanner, 'head_to_head', lambda *args, **kw: [])
    monkeypatch.setattr(scanner, 'market_lambdas', lambda *args: None)
    monkeypatch.setattr(scanner, 'sharp_ou', lambda *args: (None, None))
    monkeypatch.setattr(scanner, 'MODELS', {})
    monkeypatch.setattr(scanner, 'SIGNAL_BASELINES', {'E0':4.})
    monkeypatch.setattr(scanner, 'RECENT_FORM_ENABLED', False)
    monkeypatch.setattr(scanner, 'EXPERIMENTAL_MODEL_SIGNALS', True)
    fx = pd.Series(dict(div='E0', country='England', home='H', away='A', source='main',
                        odds_over=float('nan'), odds_under=float('nan'), odds_h=float('nan'),
                        odds_d=float('nan'), odds_a=float('nan')))
    avg = scanner.DivAvg(1.5, 1.2, 50, .5, .5)
    row = scanner.analyse(fx, pd.DataFrame(), pd.DataFrame(), {'E0':avg}, datetime(2026,11,4))
    assert row.lam_h > 1.5 and row.lam_a > 1.2
    assert row.model_signals['home']['xg_applied'] and row.model_signals['away']['sot_applied']
    expected = scanner.probs_from_matrix(scanner.score_matrix(row.lam_h, row.lam_a, scanner.CONFIG['DC_RHO']))
    assert row.p_final['O25'] == pytest.approx(expected['O25'])
    assert row.p_final['BTTS'] == pytest.approx(expected['BTTS'])
    assert sum(row.extra.x12[k] for k in ('H', 'D', 'A')) == pytest.approx(1.)
    matrix = scanner.score_matrix(row.lam_h, row.lam_a, scanner.CONFIG['DC_RHO'])
    assert len(row.scores) == 5
    assert all(p == pytest.approx(matrix[h, a]) for h, a, p in row.scores)
    assert [p for _, _, p in row.scores] == sorted((p for _, _, p in row.scores), reverse=True)
    assert row.p_final == row.p_model
    monkeypatch.setattr(scanner, 'EXPERIMENTAL_MODEL_SIGNALS', False)
    baseline = scanner.analyse(fx, pd.DataFrame(), pd.DataFrame(), {'E0':avg}, datetime(2026,11,4))
    assert baseline.lam_h == 1.5 and baseline.lam_a == 1.2
    assert baseline.model_signals['status'] == 'disabled_pending_backtest'


def test_booking_ledger_stays_pending_without_valid_settlement_rules():
    row = {c: '' for c in safe.SAFE_BET_COLS}
    row.update(match_date='2026-01-01', country='England', home='A', away='B', sel='KO35', status='pending')
    settled = safe.settle_bets(pd.DataFrame([row]), pd.DataFrame(), datetime(2026, 11, 4))
    assert settled.iloc[0]['status'] == 'pending'


def test_signal_configuration_defaults_to_disabled_and_requires_explicit_opt_in():
    import os
    import subprocess
    import sys
    env = dict(os.environ)
    env.pop('EXPERIMENTAL_MODEL_SIGNALS', None)
    cmd = [sys.executable, '-c', 'import scanner; print(scanner.EXPERIMENTAL_MODEL_SIGNALS)']
    assert subprocess.check_output(cmd, env=env, text=True).strip() == 'False'
    env['EXPERIMENTAL_MODEL_SIGNALS'] = '1'
    assert subprocess.check_output(cmd, env=env, text=True).strip() == 'True'


def test_analyse_corner_signal_applies_only_with_sufficient_real_data(monkeypatch):
    import markets
    H, A = scanner.TeamProfile('H'), scanner.TeamProfile('A')
    monkeypatch.setattr(scanner, 'profile_cached', lambda _l, _c, name, *args: H if name == 'H' else A)
    monkeypatch.setattr(scanner, 'head_to_head', lambda *args, **kw: [])
    monkeypatch.setattr(scanner, 'market_lambdas', lambda *args: None)
    monkeypatch.setattr(scanner, 'sharp_ou', lambda *args: (None, None))
    monkeypatch.setattr(scanner, 'SIGNAL_BASELINES', {})
    monkeypatch.setattr(scanner, 'RECENT_FORM_ENABLED', False)
    monkeypatch.setattr(scanner, 'EXPERIMENTAL_MODEL_SIGNALS', True)
    class Dummy:
        div_avg = {'E0': (4., 4.)}
        def __init__(self, home, away, n): self.home, self.away, self.n = home, away, n
        def expect(self, *args): return markets.CountExpectation(self.home, self.away, 5, 5, h_n=self.n, a_n=self.n)
        def _div(self, div): return self.div_avg[div]
    cm, off = Dummy(5., 4., 8), Dummy(8., 2., 8)
    monkeypatch.setattr(scanner, 'MODELS', {'corners':cm, 'shots_off':off})
    fx = pd.Series(dict(div='E0', country='England', home='H', away='A', source='main',
                        odds_over=float('nan'), odds_under=float('nan'), odds_h=float('nan'),
                        odds_d=float('nan'), odds_a=float('nan')))
    avg = scanner.DivAvg(1.5, 1.2, 50, .5, .5)
    def analyse(): return scanner.analyse(fx, pd.DataFrame(), pd.DataFrame(), {'E0':avg}, datetime(2026,11,4))
    row = analyse()
    assert row.extra.corners.eh == pytest.approx(5.125)
    assert row.extra.corners.ea == pytest.approx(3.9)
    assert row.model_signals['corners']['applied']
    assert row.extra.corner_p['home'][3.5] == pytest.approx(markets.over_line(5.125, markets.CORNERS['r_team'], 3.5))
    off.n = 4
    row = analyse()
    assert row.extra.corners.eh == 5 and 'corners' not in row.model_signals
