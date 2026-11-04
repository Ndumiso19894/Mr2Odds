"""Regressions for app/scanner recommendation policy and preserved historical records."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import recommendation_policy as policy
import safe
import scanner

NOW = datetime(2026, 11, 4, 8)
CASES = json.loads((Path(__file__).parent / 'recommendation_cases.json').read_text())

@pytest.mark.parametrize('case', CASES)
def test_offered_families(case):
    assert policy.allowed(case['sel']) == case['allowed']


def row(home):
    ko = NOW + timedelta(hours=3)
    return SimpleNamespace(data_ok=True, fx={'kickoff': ko, 'date': ko, 'country': 'England',
                           'home': home, 'away': 'Rivals', 'div': 'E0', 'league': 'Premier League'})


def test_scanner_offers_only_current_markets_at_app_price_floor(monkeypatch):
    picks = [safe.Sel('BTTS', .9, .85, 1.16), safe.Sel('KO35', .9, .85, 1.16),
             safe.Sel('HO05', .9, .85, 1.16), safe.Sel('O15', .75, .76, 1.16)]
    monkeypatch.setattr(safe, 'selections', lambda _: picks)
    result = safe.safest([row('A')], NOW, NOW + timedelta(hours=4))
    assert [b.sel for b in result['bets']] == ['BTTS']
    assert result['min_odds'] == 1.16
    picks[:] = [safe.Sel('O15', .75, .76, 1.159)]
    assert not safe.safest([row('A')], NOW, NOW + timedelta(hours=4))['bets']


def test_day_card_priority_and_retains_legacy_records(monkeypatch):
    picks = [safe.Sel('HO05', .95, .9, 1.3), safe.Sel('O25', .56, .56, 1.8),
             safe.Sel('H', .72, .72, 1.5), safe.Sel('O15', .82, .8, 1.3)]
    monkeypatch.setattr(safe, 'selections', lambda _: picks)
    candidates = safe.botd_candidates([row('A')], NOW, signal=lambda *_: True)
    assert {b.sel for b in candidates} == {'H', 'O25', 'O15'}
    old = {**{c: '' for c in safe.SAFE_BET_COLS}, 'match_date': '2026-11-04', 'kickoff': '2026-11-04 11:00',
           'country': 'England', 'div': 'E0', 'league': 'Premier League', 'home': 'A', 'away': 'Rivals',
           'sel': 'HO05', 'status': 'pending', 'botd': 'o15', 'kind': 'botd'}
    ledger = safe.pick_bets_of_the_day(pd.DataFrame([old]), NOW, candidates=candidates)
    assert set(ledger.sel) == {'HO05', 'H'}
    assert ledger.loc[ledger.sel == 'H', 'botd'].item() == 'result'
    assert ledger.loc[ledger.sel == 'HO05', 'botd'].item() == 'o15'  # history is not deleted
    assert [b['sel'] for b in safe.bets_of_the_day(ledger, NOW)['bets']] == ['H']


def test_empty_ledger_and_disabled_btts_shortlists():
    ledger = safe.pick_bets_of_the_day(pd.DataFrame(columns=safe.SAFE_BET_COLS), NOW)
    assert list(ledger.columns) == safe.SAFE_BET_COLS
    assert scanner.select_picks([])['BTTS'] == []


def test_raw_price_outliers_are_not_issued(monkeypatch):
    monkeypatch.setattr(safe, 'selections', lambda _: [safe.Sel('O15', .90, None, 2.0)])
    assert not safe.safest([row('A')], NOW, NOW + timedelta(hours=4))['bets']
    assert not safe.botd_candidates([row('A')], NOW)


def test_publication_failure_is_not_silently_reported_as_success():
    with pytest.raises(RuntimeError, match='refusing to publish'):
        scanner.require_publication({})
    with pytest.raises(RuntimeError, match='refusing to publish'):
        scanner.require_publication({'data_check': {'ok': False}})
    scanner.require_publication({'data_check': {'ok': True}})


def test_day_history_top_selections_respect_recommendation_policy(monkeypatch):
    monkeypatch.setattr(scanner, 'all_sels', lambda _: [
        {'sel': 'BTTS', 'p': .9, 'p_model': .9, 'p_sb': .8, 'odds': 1.3, 'diff': False, 'label': 'BTTS'},
        {'sel': 'O15', 'p': .8, 'p_model': .8, 'p_sb': .8, 'odds': 1.16, 'diff': False, 'label': 'O1.5'},
        {'sel': 'O25', 'p': .9, 'p_model': .9, 'p_sb': None, 'odds': 2.0, 'diff': False, 'label': 'O2.5'},
    ])
    assert [x['sel'] for x in scanner.top_sels(None)] == ['BTTS', 'O15']
