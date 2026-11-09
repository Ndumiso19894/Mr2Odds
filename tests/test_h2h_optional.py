from datetime import datetime, timedelta
from types import SimpleNamespace
import pandas as pd
import pytest

import appdata
import h2h_evidence
import safe
import scanner

NOW = datetime(2026, 11, 4, 10)


def row(name, p=.8, odds=1.3, evidence=None):
    fx = {'date': pd.Timestamp(NOW.date()), 'kickoff': NOW + timedelta(hours=2), 'country':'England',
          'div':'E0', 'league':'Premier League', 'home':name, 'away':'Away'}
    return SimpleNamespace(data_ok=True, fx=fx, h2h_evidence=evidence or {}, p=p, odds=odds,
                           p_final={'O15':p, 'O25':p, 'BTTS':p})


STRONG = {'status':'sufficient', 'meetings':3, 'last_meeting':'2010-01-01', 'minimum_meetings':3}
LIMITED = {'status':'limited', 'meetings':2, 'last_meeting':'2010-01-01', 'minimum_meetings':3}
UNKNOWN = {'status':'unavailable', 'meetings':None, 'last_meeting':None, 'minimum_meetings':3}


def test_tiebreak_applies_only_after_probability_and_price(monkeypatch):
    monkeypatch.setattr(safe, 'selections', lambda r: [safe.Sel('O15', r.p, r.p, r.odds)])
    rows = [row('limited', evidence=LIMITED), row('enough', evidence=STRONG),
            row('higher', p=.81, evidence=UNKNOWN), row('higher price', odds=1.4, evidence=UNKNOWN),
            row('unknown', evidence=UNKNOWN)]
    bets = safe.safest(rows, NOW, NOW + timedelta(hours=4))['bets']
    assert [b.home for b in bets] == ['higher', 'higher price', 'enough', 'limited', 'unknown']
    assert [b.p for b in bets] == [.81, .8, .8, .8, .8]
    assert all(b.odds >= safe.MIN_ODDS for b in bets)
    botd = safe.botd_candidates(rows, NOW)
    assert [b.home for b in botd] == ['higher', 'higher price', 'enough', 'limited', 'unknown']


def test_probability_priority_beats_h2h_in_model_shortlist():
    rows = [row('limited', p=.90, evidence=LIMITED), row('enough', p=.90, evidence=STRONG), row('higher', p=.91, evidence=UNKNOWN)]
    assert [r.fx['home'] for r in scanner.select_picks(rows)['O15']] == ['higher','enough','limited']


def test_tiebreak_must_have_valid_available_evidence():
    assert h2h_evidence.preferred(STRONG)
    for e in (None, {}, LIMITED, UNKNOWN, {'status':'sufficient','meetings':True},
              {'status':'sufficient','meetings':'3'}, {'status':'sufficient','meetings':2}):
        assert not h2h_evidence.preferred(e)


def test_published_shortlist_prioritises_only_exact_probability_and_price_ties():
    def fixture(name, p, odds, evidence):
        return {'id':name,'date':'2026-11-04','kickoff':'2026-11-04 12:00', 'country':'England',
                'home':name,'away':'Away','league':'Premier League','q':'High','data_ok':True,
                'h2h_evidence':evidence,'sels':[['O15',p,p,p,odds,0,None,None]]}
    items = [fixture('a-limited',.8,1.3,LIMITED), fixture('z-enough',.8,1.3,STRONG),
             fixture('higher-p',.81,1.3,UNKNOWN), fixture('higher-price',.8,1.4,UNKNOWN)]
    assert [x['home'] for x in appdata.shortlist_payload(items,NOW)['primary']] == [
        'higher-p','higher-price','z-enough','a-limited']
