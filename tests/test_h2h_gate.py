from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import appdata
import h2h_gate
import scanner

NOW = datetime(2026, 11, 4, 10)


def fixture(**overrides):
    return {'source':'world', 'home_id':'1', 'away_id':'2', 'home':'A', 'away':'B',
            'country':'England', 'div':'LS:england/league', 'league':'Premier League',
            'kickoff':datetime(2026,11,5,12), 'date':pd.Timestamp('2026-11-05'), **overrides}


def records(n=6, source='world'):
    out=[]
    for i in range(n):
        reverse=i % 2 == 1
        out.append({'date':pd.Timestamp(NOW-timedelta(days=20+i*100)),
                    'div':'LS:england/cup' if source=='world' else 'E0',
                    'league':'FA Cup' if source=='world' else 'Premier League',
                    'country':'England', 'home':'B' if reverse else 'A', 'away':'A' if reverse else 'B',
                    'home_id':'2' if reverse else '1', 'away_id':'1' if reverse else '2',
                    'eid':f'event-{i}' if source=='world' else None, 'hg':1, 'ag':0})
    return pd.DataFrame(out)


def check(df, fx=None):
    return h2h_gate.eligibility(fx or fixture(), h2h_gate.build_index(df, NOW))


@pytest.mark.parametrize('n',[0,1,2])
def test_fewer_than_three_are_limited_evidence(n):
    result=check(records(n))
    assert not result['eligible'] and result['meetings']==n


@pytest.mark.parametrize('n',[3,4,5,6])
def test_three_or_more_are_eligible_including_reverse_and_cup(n):
    df=records(n)
    df.loc[n-1,'date']=pd.Timestamp('2010-01-01')
    result=check(df)
    assert result['eligible'] and result['meetings']==n
    assert result['last_meeting']=='2026-10-15'
    assert check(df,fixture(home_id='2',away_id='1',home='B',away='A'))['eligible']


def test_no_age_limit_and_earlier_than_fixture_date():
    df=records(3)
    df['date']=pd.to_datetime(['1980-01-01','1981-01-01','1982-01-01'])
    proof=check(df)
    assert proof['eligible'] and proof['last_meeting']=='1982-01-01'
    assert h2h_gate.valid_proof(proof,fixture()['kickoff'])
    # An as-of index can never establish a meeting on or after a fixture date.
    older_fixture = fixture(kickoff=datetime(1981,1,1))
    assert check(df,older_fixture)['meetings']==1
    assert not check(df,older_fixture)['eligible']


def test_friendlies_and_missing_invalid_scores_not_counted():
    df=records(7)
    df.loc[3,'league']='Club Friendlies'
    df.loc[4,'div']='LS:world/club-friendly'
    df.loc[5,'hg']=np.nan
    df.loc[6,'ag']=-1
    assert check(df)['meetings']==3 and check(df)['eligible']
    df.loc[0,'league']=None
    assert check(df)['reason']=='insufficient_meetings'


def test_same_day_future_duplicate_event_and_pair_date_fail_closed():
    df=records(7)
    df.loc[6,'date']=pd.Timestamp(NOW) # not available before cutoff
    assert check(df)['meetings']==6
    df.loc[6,'date']=pd.Timestamp(NOW+timedelta(days=1))
    assert check(df)['meetings']==6
    df.loc[6,'date']=df.loc[0,'date'];df.loc[6,'eid']='different-id'
    assert check(df)['meetings']==5  # both records on ambiguous day are excluded
    df.loc[6,'date']=pd.Timestamp('2025-01-01');df.loc[6,'eid']=df.loc[0,'eid']
    assert check(df)['meetings']==5  # duplicated IDs excluded even across dates


def test_invalid_ids_not_name_matched_and_no_cross_provider_combining():
    df=records(5)
    fd=records(2,'fd')
    combined=pd.concat([df,fd],ignore_index=True)
    assert check(combined)['meetings']==5
    assert check(combined,fixture(source='main',home_id=None,away_id=None))['meetings']==2
    assert check(combined,fixture(home_id=None))['reason']=='identity_unavailable'
    assert check(combined,fixture(home_id=' 1'))['reason']=='identity_unavailable'
    assert check(combined,fixture(home_id='2'))['reason']=='identity_unavailable'
    df=records(6);df.loc[0,'eid']='nan'
    assert check(df)['meetings']==5


def test_football_data_exact_names_and_country_across_competitions():
    df=records(6,'fd');df.loc[0,'div']='E1';df.loc[0,'league']='Championship'
    fx=fixture(source='main',home_id=None,away_id=None)
    assert check(df,fx)['eligible']
    assert check(df,dict(fx,home=' A'))['reason']=='identity_unavailable'
    assert not check(df,dict(fx,home='A FC'))['eligible']
    assert not check(df,dict(fx,country='Wales'))['eligible']


def test_missing_kickoff_and_unknown_source_fail_closed():
    df=records()
    assert check(df,fixture(kickoff=None))['reason']=='kickoff_unavailable'
    assert check(df,fixture(source='other'))['reason']=='identity_unavailable'


def test_all_fixtures_reach_predictor_regardless_of_h2h(monkeypatch):
    import h2h_evidence
    fixture_rows=pd.DataFrame([fixture(),fixture(home_id='3'),fixture(home_id=None)],index=[5,8,11])
    index=h2h_gate.build_index(records(3),NOW)
    evidence={i: h2h_evidence.assess(fx,index) for i,fx in fixture_rows.iterrows()}
    seen=[]
    def predict(fx,*args):
        seen.append(fx.name)
        return SimpleNamespace(fx=fx)
    monkeypatch.setattr(scanner,'analyse',predict)
    rows=scanner.analyse_fixtures(fixture_rows,evidence,None,None,{},NOW,None)
    assert seen==[5,8,11]
    assert [r.h2h_evidence['status'] for r in rows]==['sufficient','limited','unavailable']
    assert rows[1].h2h_evidence['meetings']==0
    assert rows[2].h2h_evidence['meetings'] is None
    index=h2h_gate.build_index(records(2),NOW)
    evidence={i: h2h_evidence.assess(fx,index) for i,fx in fixture_rows.iterrows()}
    assert len(scanner.analyse_fixtures(fixture_rows,evidence,None,None,{},NOW,None))==3
    assert seen==[5,8,11,5,8,11]


def test_sticky_bets_and_frozen_history_preserved_without_h2h_requirement():
    f=fixture()
    row=SimpleNamespace(fx=pd.Series(f))
    good={'kickoff':'2026-11-05 12:00','country':'England','home':'A','away':'B','league':'Premier League'}
    bad={**good,'home':'C'}
    old_result={**good,'sel':'H'}  # sticky legacy result has no research report and is hidden, not deleted
    card={'bets':[good,bad,old_result],'groups':[{'bets':[good,bad,old_result]}]}
    scanner.filter_botd_by_current_rows(card,[row])
    assert card['bets']==[good] and card['groups'][0]['bets']==[good]
    old={'id':'old','kickoff':'2026-11-04 09:00','country':'England','league':'Premier League','home':'A','away':'B'}
    proven={**old,'id':'proven','h2h_gate':{'eligible':True,'reason':'eligible','meetings':6,'last_meeting':'2026-10-15','identity':'Livescore team and event IDs'}}
    prev={'fixtures':[old,proven], 'safe':{'bets':[]}}
    index=[]
    assert appdata.carry_over(prev,index,[],set(),NOW)==2
    assert {x['id'] for x in index}=={'old','proven'}
    assert prev['fixtures'][0] == old  # input and historical records unchanged


def test_proof_validation_cannot_be_forged_by_missing_fields():
    proof=check(records())
    assert h2h_gate.valid_proof(proof,fixture()['kickoff'])
    assert not h2h_gate.valid_proof(dict(proof,meetings=2),fixture()['kickoff'])
    assert not h2h_gate.valid_proof(dict(proof,meetings=True),fixture()['kickoff'])
    assert h2h_gate.valid_proof(dict(proof,meetings=3,last_meeting='1980-01-01'),fixture()['kickoff'])
    assert not h2h_gate.valid_proof(dict(proof,last_meeting=None),fixture()['kickoff'])
    assert not h2h_gate.valid_proof(dict(proof,last_meeting='2026-11-05'),fixture()['kickoff'])
    assert not h2h_gate.valid_proof(dict(proof,identity='unknown'),fixture()['kickoff'])
    assert not h2h_gate.valid_proof({},fixture()['kickoff'])


def test_duplicate_id_with_an_invalid_score_does_not_validate_other_copy():
    df=records(7)
    df.loc[6,'eid']=df.loc[0,'eid'];df.loc[6,'hg']=np.nan
    assert check(df)['meetings']==5


def test_preexisting_future_alerts_are_filtered_but_past_records_preserved():
    row=SimpleNamespace(fx=pd.Series(fixture()))
    good={'fixture':'2026-11-05|England|A|B','kickoff':'2026-11-05 12:00'}
    bad={'fixture':'2026-11-05|England|C|B','kickoff':'2026-11-05 12:00'}
    past={'fixture':'old','kickoff':'2026-11-04 09:00'}
    invalid={'fixture':'other','kickoff':None}
    assert scanner.filter_pending_alerts([bad,good,past,invalid],[row],NOW)==[good,past]
