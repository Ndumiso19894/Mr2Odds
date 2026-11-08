from datetime import datetime, timedelta
import math

import numpy as np
import pandas as pd
import pytest

import markets
import scanner
from research.recent_form import model

NOW = datetime(2026, 10, 10, 12)
FX = {'country':'Test', 'div':'LS:test/league', 'home':'Alpha', 'away':'Beta', 'home_id':'a', 'away_id':'b'}


def record(date, home, away, hid, aid, hg, ag, eid, div='LS:test/league'):
    return {'date': pd.Timestamp(date), 'country':'Test', 'league':'League', 'div':div,
            'home':home, 'away':away, 'home_id':hid, 'away_id':aid, 'hg':hg, 'ag':ag, 'eid':eid}


def sample():
    rows=[]
    # Alternating venue, different dates for each team, so each recent window
    # is unambiguous even though only calendar dates are available.
    for i in range(12):
        d=NOW-timedelta(days=2*i+1)
        goals=[0,1,2,0,3,1,1,2,1,0,2,1][i]
        against=[1,0,1,2,0,1,2,2,0,1,0,0][i]
        if i%2==0: rows.append(record(d,'Alpha',f'X{i}','a',f'x{i}',goals,against,f'a{i}'))
        else: rows.append(record(d,f'X{i}','Alpha',f'x{i}','a',against,goals,f'a{i}'))
        d2=NOW-timedelta(days=2*i+2)
        if i%2==0: rows.append(record(d2,f'Y{i}','Beta',f'y{i}','b',against,goals,f'b{i}'))
        else: rows.append(record(d2,'Beta',f'Y{i}','b',f'y{i}',goals,against,f'b{i}'))
    # Three older, exact-ID meetings with both venue orientations.
    rows += [record(NOW-timedelta(days=80),'Alpha','Beta','a','b',3,1,'h1'),
             record(NOW-timedelta(days=160),'Beta','Alpha','b','a',2,0,'h2'),
             record(NOW-timedelta(days=240),'Alpha','Beta','a','b',1,1,'h3')]
    return pd.DataFrame(rows)


def test_recent_windows_scored_failed_conceded_and_venue():
    result=model.predict(model.prepare(sample(),NOW),FX)
    home=result['evidence']['home']
    assert home['last5']=={'n':5,'goals_for':6,'goals_against':4,'scored':3,'failed_to_score':2,'conceded':3,'clean_sheets':2}
    assert home['last10']['n']==10 and home['last10']['scored']==7 and home['last10']['failed_to_score']==3
    assert home['venue5']['n']==5 and home['venue5']['goals_for']==7
    assert home['window_weights']==pytest.approx([.2,.1,.1])
    assert result['evidence']['squad_availability']['status']=='not_used'
    assert result['classification']=='offline_research_unvalidated'


def test_h2h_only_last_five_exact_ids_same_league_prior_day_oriented():
    df=sample()
    # Later result is never a past meeting, even if the score is huge.
    df.loc[len(df)] = record(NOW,'Alpha','Beta','a','b',20,20,'future')
    df.loc[len(df)] = record(NOW-timedelta(days=60),'Alpha','Beta','a','b',20,20,'other','LS:test/cup')
    res=model.predict(model.prepare(df,NOW),FX)
    h=res['evidence']['h2h']
    assert h['n']==3 and [x['event_id'] for x in h['matches']]==['h1','h2','h3']
    assert [(x['home_goals'],x['away_goals']) for x in h['matches']]==[(3,1),(0,2),(1,1)]
    assert h['weight']==pytest.approx(.1*3/8)
    assert res['league']['source']=='division'


def test_no_fictitious_h2h_without_event_and_team_ids():
    df=sample(); df.loc[df['eid']=='h1','eid']=None
    res=model.predict(model.prepare(df,NOW),FX)
    assert res['evidence']['h2h']['n']==2 and res['evidence']['h2h']['weight']==0
    res=model.predict(model.prepare(sample(),NOW),dict(FX,home_id=None,away_id=None))
    assert res['evidence']['h2h']['n']==0 and res['evidence']['h2h']['weight']==0


def test_model_retains_baseline_league_averages_and_probability_coherence():
    ctx=model.prepare(sample(),NOW);r=model.predict(ctx,FX)
    hp=scanner.build_profile(ctx.long,'Test','Alpha','H',NOW,'a')
    ap=scanner.build_profile(ctx.long,'Test','Beta','A',NOW,'b')
    league=ctx.averages[FX['div']]
    assert r['baseline']['lambda_home']==pytest.approx(min(max(league.mu_h*hp.att*ap.dfc,.15),4.5))
    assert r['baseline']['lambda_away']==pytest.approx(min(max(league.mu_a*ap.att*hp.dfc,.15),4.5))
    for name in ('baseline','recent_variant'):
        mat=np.array(r[name]['matrix']); p=r[name]['probabilities']; x=markets.one_x_two(mat)
        assert mat.shape==(11,11) and np.isfinite(mat).all() and (mat>=0).all()
        assert mat.sum()==pytest.approx(1)
        assert p['H']+p['D']+p['A']==pytest.approx(1)
        assert p['O15']>=p['O25']>=p['O35']
        assert p['BTTS']==pytest.approx(mat[1:,1:].sum())
        assert p['H']==pytest.approx(x['H'])
        assert p['1X']==pytest.approx(1-p['A'])
        assert p['H_zero_goal']==pytest.approx(1-p['H_o05'])
        assert p['A_zero_goal']==pytest.approx(1-p['A_o05'])


def test_recent_form_increases_influence_without_removing_older_history():
    from types import SimpleNamespace
    p=SimpleNamespace(att=1.0,dfc=1.0)
    data=pd.DataFrame({'venue':['H','A']*5,'gf_norm':[2]*5+[1]*5,'ga_norm':[1]*10})
    att,defence,w=model._form_rating(p,data,'H')
    assert 1 < att < 1.4 and defence==pytest.approx(1)
    assert sum(w)==pytest.approx(.4)
    shorter=data.head(1)
    _,_,few=model._form_rating(p,shorter,'H')
    assert sum(few)<sum(w) and 1-sum(few)>.9
    older=data.copy();older.loc[5:9,'gf_norm']=0
    older_att,_,_=model._form_rating(p,older,'H')
    assert older_att<att


def test_scoring_and_failure_frequencies_change_score_probability():
    baseline=1.5
    many,plus=model._frequency_adjust(baseline,(20,20),(20,20))
    none,minus=model._frequency_adjust(baseline,(0,20),(0,20))
    missing,delta=model._frequency_adjust(baseline,(0,0),(0,0))
    assert many>baseline>none and plus>0>minus
    assert missing==pytest.approx(baseline) and delta==0
    assert abs(plus)<=.2 and abs(minus)<=.2


def test_same_day_future_and_fixture_outcome_cannot_leak():
    data=sample(); old=model.predict(model.prepare(data,NOW),FX)
    data.loc[len(data)]=record(NOW,'Alpha','Beta','a','b',80,70,'today')
    data.loc[len(data)]=record(NOW+timedelta(days=1),'Alpha','Beta','a','b',90,90,'future')
    new=model.predict(model.prepare(data,NOW),dict(FX,hg=99,ag=99,odds_over=100))
    assert new['baseline']==old['baseline'] and new['recent_variant']==old['recent_variant']
    assert new['evidence']==old['evidence']


def test_unknown_negative_and_nan_scores_never_become_zero():
    data=sample();data.loc[len(data)]=record(NOW-timedelta(days=1),'Alpha','Odd','a','odd',None,1,'null')
    data.loc[len(data)]=record(NOW-timedelta(days=2),'Beta','Odd','b','odd',-1,0,'negative')
    ctx=model.prepare(data,NOW); assert 'null' not in set(ctx.history['eid']) and 'negative' not in set(ctx.history['eid'])
    assert model._stats(pd.DataFrame(columns=['gf','ga']))['failed_to_score'] is None


def test_ambiguous_same_day_team_records_fail_closed():
    data=sample();data.loc[len(data)]=record(NOW-timedelta(days=1),'Alpha','Other','a','other',1,1,'different')
    with pytest.raises(model.ResearchError,match='ambiguous same-day'):
        model.predict(model.prepare(data,NOW),FX)


def test_insufficient_or_incomplete_inputs_fail_closed():
    with pytest.raises(model.ResearchError,match='required result'):
        model.prepare(pd.DataFrame(),NOW)
    with pytest.raises(model.ResearchError,match='no valid earlier history'):
        model.prepare(sample(),NOW-timedelta(days=1000))
    with pytest.raises(model.ResearchError,match='fixture identity'):
        model.predict(model.prepare(sample(),NOW),dict(FX,home=''))
    with pytest.raises(model.ResearchError,match='insufficient'):
        model.predict(model.prepare(sample(),NOW),dict(FX,away='New',away_id='new'))


def test_context_switch_isolation():
    first=model.prepare(sample(),NOW);a=model.predict(first,FX)
    other=sample();other.loc[0,'hg']=9
    b=model.predict(model.prepare(other,NOW),FX)
    c=model.predict(first,FX)
    assert a['recent_variant']==c['recent_variant'] and b['recent_variant']!=a['recent_variant']


def test_h2h_last_five_and_ambiguous_date_not_double_counted():
    data=sample()
    data.loc[len(data)]=record(NOW-timedelta(days=300),'Beta','Alpha','b','a',2,2,'h4')
    data.loc[len(data)]=record(NOW-timedelta(days=360),'Alpha','Beta','a','b',0,0,'h5')
    data.loc[len(data)]=record(NOW-timedelta(days=420),'Alpha','Beta','a','b',5,0,'h6')
    r=model.predict(model.prepare(data,NOW),FX)
    assert [m['event_id'] for m in r['evidence']['h2h']['matches']]==['h1','h2','h3','h4','h5']
    # Two different IDs on one date cannot be ordered or trusted as distinct meetings.
    data.loc[len(data)]=record(NOW-timedelta(days=80),'Alpha','Beta','a','b',9,9,'duplicate-date')
    # This ambiguity is older than all recent team windows, but H2H omits both.
    r=model.predict(model.prepare(data,NOW),FX)
    assert 'h1' not in [m['event_id'] for m in r['evidence']['h2h']['matches']]
    assert 'duplicate-date' not in [m['event_id'] for m in r['evidence']['h2h']['matches']]


def test_historical_probabilities_are_separate_from_recent_counts():
    result=model.predict(model.prepare(sample(),NOW),FX)
    raw=result['evidence']['home']['last5']
    p=result['recent_variant']['probabilities']
    assert raw['failed_to_score']==2 and raw['n']==5
    assert 0 <= p['H_zero_goal'] <= 1 and not math.isclose(p['H_zero_goal'],2/5)


def test_timezone_aware_input_history_not_silently_reinterpreted():
    data=sample();data['date']=pd.to_datetime(data['date'],utc=True)
    with pytest.raises(model.ResearchError,match='naive local calendar'):
        model.prepare(data,NOW)


def test_log_loss_and_matched_delta_summary():
    from research.recent_form.compare import score_summary
    rows=[{'day':'2026-01-01','baseline':{'O15':.8},'variant':{'O15':.6},'outcome':{'O15':1}},
          {'day':'2026-01-02','baseline':{'O15':.8},'variant':{'O15':.6},'outcome':{'O15':0}}]
    s=score_summary(rows,'O15')
    assert s['n']==2 and s['brier']['baseline']==pytest.approx(.34)
    assert s['brier']['variant']==pytest.approx(.26)
    assert s['brier']['paired_delta']==pytest.approx(-.08)
    assert s['brier']['resampled_days']==2 and len(s['brier']['day_bootstrap_95'])==2


def test_league_averages_anchor_both_models_and_missing_division_is_labelled():
    data=sample();old=model.predict(model.prepare(data,NOW),FX)
    extra=[record(NOW-timedelta(days=40+i),f'L{i}',f'R{i}',f'l{i}',f'r{i}',5,0,f'lge{i}') for i in range(20)]
    new=model.predict(model.prepare(pd.concat([data,pd.DataFrame(extra)],ignore_index=True),NOW),FX)
    assert new['league']['home_mean']>old['league']['home_mean']
    assert new['baseline']['lambda_home']!=old['baseline']['lambda_home']
    assert new['recent_variant']['lambda_home']!=old['recent_variant']['lambda_home']
    fallback=model.predict(model.prepare(data,NOW),dict(FX,div='LS:other/league'))
    assert fallback['league']['source']=='global_fallback' and fallback['evidence']['h2h']['n']==0


def test_same_goal_average_different_scoring_consistency_is_not_ignored():
    mixed=pd.DataFrame({'gf':[0,2,0,2,1,1,1,1,1,1], 'venue':['H','A']*5})
    consistent=mixed.copy();consistent['gf']=1
    assert mixed['gf'].mean()==consistent['gf'].mean()
    mixed_evidence=model._frequency_evidence(mixed,'H','gf')
    consistent_evidence=model._frequency_evidence(consistent,'H','gf')
    assert consistent_evidence[0]>mixed_evidence[0] and consistent_evidence[1]==mixed_evidence[1]
    assert model._frequency_adjust(1.5,consistent_evidence,(0,0))[0]>model._frequency_adjust(1.5,mixed_evidence,(0,0))[0]
