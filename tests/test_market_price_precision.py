"""Bookmaker prices must not be rounded up before the app's market floor is applied."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import appdata
import safe
import scanner


def test_exact_quote_survives_selection_and_sportybet_serialization():
    d = safe.sel_dict(safe.Sel('O15', .81, .78, 1.1599), 'Home', 'Away')
    assert d['odds'] == 1.1599
    assert appdata._selection_rows([d])[0][4] == 1.1599
    assert appdata._board([d])['O15'][1] == 1.1599
    sb = appdata._sb({'1X2': [1.1599, 1.16, None], 'OU': {2.5: [1.1599, 1.16]}})
    assert sb['1X2'] == [1.1599, 1.16, None]
    assert sb['OU']['2.5'] == [1.1599, 1.16]


def test_report_price_formatter_obeys_inclusive_floor():
    assert scanner.fmt_odds(1.1599) == '–'
    assert scanner.fmt_odds(1.16) == '1.16'
    assert scanner.fmt_odds(float('nan')) == '–'
    assert scanner.fmt_odds(None) == '–'


def test_new_parlays_never_offer_sub_floor_legs(monkeypatch):
    now = datetime(2026, 11, 4, 8)
    r = SimpleNamespace(data_ok=True, fx={'kickoff': now + timedelta(hours=1)}, sb={'price': True},
                        extra=SimpleNamespace(x12={}), p_model={'O25': .8})
    legs = [SimpleNamespace(key=('short',), odds=1.1599), SimpleNamespace(key=('floor',), odds=1.16)]
    monkeypatch.setattr(scanner.parlay_mod, 'candidate_legs', lambda *args: legs)
    monkeypatch.setattr(scanner.parlay_mod, 'build_parlays', lambda legs, *args: [])
    result = scanner.build_run_parlays([r], now, now + timedelta(hours=2), True)
    assert [leg.odds for leg in result['legs']] == [1.16]
