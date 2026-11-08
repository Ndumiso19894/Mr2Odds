"""Synthetic data and a patched clock only: never contacts a provider."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from research.point_in_time import replay, snapshots

T = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
CUTOFF = T + timedelta(hours=2)
KICKOFF = T + timedelta(hours=3)
FIXTURE = {'id': 'event-a', 'competition_id': 'league-a', 'home_id': 'home-a',
           'away_id': 'away-a', 'kickoff_at': KICKOFF.isoformat()}
HISTORY = {'id': 'prior-a', 'competition_id': 'league-a', 'home_id': 'home-a',
           'away_id': 'other-a', 'kickoff_at': (T-timedelta(days=1,hours=2)).isoformat(),
           'finished_at': (T-timedelta(days=1)).isoformat(), 'status': 'FINAL',
           'score_period': 'REGULATION', 'home_goals': 2, 'away_goals': 1}
QUOTED = dict(FIXTURE, markets=[{'id': 'total_goals', 'specifier': '2.5', 'status': 'OPEN',
                                 'outcomes': [{'name': 'over', 'odds': '1.1801', 'status': 'ACTIVE'},
                                              {'name': 'under', 'odds': '3.10', 'status': 'ACTIVE'}]}])
RESULT = dict(FIXTURE, finished_at=(T+timedelta(hours=5)).isoformat(), status='FINAL',
              score_period='REGULATION', home_goals=2, away_goals=1)
QSPEC = [{'event_pointer': '/event', 'event_id_pointer': '/id', 'quotes': [
    {'market_pointer': '/markets/0', 'market_id_pointer': '/id', 'specifier_pointer': '/specifier',
     'outcome_pointer': f'/outcomes/{i}', 'outcome_name_pointer': '/name', 'odds_pointer': '/odds',
     'market_status_pointer': '/status', 'outcome_status_pointer': '/status'} for i in range(2)]}]


def make(tmp_path, monkeypatch, dataset, payload, *, at=T, specs=None, origin='synthetic', provider='synthetic'):
    times=iter([at,at+timedelta(seconds=1),at+timedelta(seconds=2)])
    monkeypatch.setattr(snapshots, '_now_utc', lambda: next(times))
    raw=json.dumps(payload, separators=(',', ':')).encode()
    return snapshots.capture(tmp_path, lambda:raw, provider=provider, dataset=dataset,
                             request_path='/toy', origin=origin, event_specs=specs)


def scenario(tmp_path, monkeypatch):
    return {'fixture':make(tmp_path,monkeypatch,'fixture',{'event':deepcopy(FIXTURE)}),
            'history':[make(tmp_path,monkeypatch,'history',{'history':[deepcopy(HISTORY)]})],
            'quotes':make(tmp_path,monkeypatch,'quotes',{'event':deepcopy(QUOTED)},specs=QSPEC),
            'cutoff':CUTOFF, 'outcome':'over', 'max_quote_age':timedelta(hours=2), 'price_policy':'final_picks'}


def test_end_to_end_synthetic_replay_and_separate_settlement(tmp_path, monkeypatch):
    args=scenario(tmp_path,monkeypatch)
    trial=replay.simulate(**args)
    assert trial.classification=='synthetic_only' and trial.odds=='1.1801'
    assert trial.observation_age==timedelta(hours=2) and trial.history_count==1
    assert {r[0] for r in trial.snapshots}=={'fixture','history','quotes'}
    result=make(tmp_path,monkeypatch,'result',{'event':deepcopy(RESULT)},at=T+timedelta(hours=5))
    with pytest.raises(replay.ReplayError,match='snapshot rejected'):
        replay.settle(trial,result=result,as_of=CUTOFF+timedelta(minutes=1))
    settled=replay.settle(trial,result=result,as_of=T+timedelta(hours=6))
    assert settled['result']=='won' and settled['classification']=='synthetic_only'
    assert 'profit' not in settled and 'roi' not in settled
    args['outcome']='under'
    assert replay.settle(replay.simulate(**args),result=result,as_of=T+timedelta(hours=6))['result']=='lost'


def test_cutoff_and_snapshot_time_gate(tmp_path,monkeypatch):
    args=scenario(tmp_path,monkeypatch)
    for t in (KICKOFF,KICKOFF+timedelta(minutes=1)):
        with pytest.raises(replay.ReplayError,match='strictly before kickoff'):
            replay.simulate(**dict(args,cutoff=t,max_quote_age=timedelta(hours=10)))
    with pytest.raises(replay.ReplayError,match='timezone-aware'):
        replay.simulate(**dict(args,cutoff=CUTOFF.replace(tzinfo=None)))
    later=make(tmp_path,monkeypatch,'history',{'history':[deepcopy(HISTORY)]},at=CUTOFF)
    with pytest.raises(replay.ReplayError,match='snapshot rejected'):
        replay.simulate(**dict(args,history=[later]))
    with pytest.raises(replay.ReplayError,match='too old'):
        replay.simulate(**dict(args,max_quote_age=timedelta(hours=2)-timedelta(microseconds=1)))
    with pytest.raises(replay.ReplayError,match='positive timedelta'):
        replay.simulate(**dict(args,max_quote_age=timedelta(0)))


@pytest.mark.parametrize('change', [
    {'id':'event-b'}, {'competition_id':'league-b'}, {'home_id':'other'}, {'away_id':'other'},
    {'kickoff_at':(KICKOFF+timedelta(minutes=1)).isoformat()}, {'kickoff_at':'2026-11-04T13:00:00'},
])
def test_event_identity_and_kickoff_are_not_inferred(tmp_path,monkeypatch,change):
    args=scenario(tmp_path,monkeypatch); quoted=dict(deepcopy(QUOTED),**change)
    args['quotes']=make(tmp_path,monkeypatch,'quotes',{'event':quoted},specs=QSPEC)
    with pytest.raises(replay.ReplayError):replay.simulate(**args)


@pytest.mark.parametrize('market,selection', [
    ({'status':'SUSPENDED'},{}), ({'specifier':'3.5'},{}), ({'id':'corners'},{}),
    ({},{'status':'SUSPENDED'}), ({},{'name':'Over'}),
])
def test_market_line_outcome_and_status_must_match_exactly(tmp_path,monkeypatch,market,selection):
    args=scenario(tmp_path,monkeypatch); quoted=deepcopy(QUOTED)
    quoted['markets'][0].update(market);quoted['markets'][0]['outcomes'][0].update(selection)
    args['quotes']=make(tmp_path,monkeypatch,'quotes',{'event':quoted},specs=QSPEC)
    with pytest.raises(replay.ReplayError):replay.simulate(**args)


def test_missing_or_ambiguous_quote_status_and_price_rejected(tmp_path,monkeypatch):
    args=scenario(tmp_path,monkeypatch)
    specs=deepcopy(QSPEC);del specs[0]['quotes'][0]['market_status_pointer']
    args['quotes']=make(tmp_path,monkeypatch,'quotes',{'event':deepcopy(QUOTED)},specs=specs)
    with pytest.raises(replay.ReplayError,match='explicitly active'):replay.simulate(**args)
    quoted=deepcopy(QUOTED);del quoted['markets'][0]['outcomes'][0]['odds']
    with pytest.raises(snapshots.SnapshotError):make(tmp_path,monkeypatch,'quotes',{'event':quoted},specs=QSPEC)
    # Two distinct pointers with the same event ID cannot silently select one.
    payload={'events':[deepcopy(QUOTED),deepcopy(QUOTED)]}
    specs=[]
    for i in range(2):
        entry=deepcopy(QSPEC[0]);entry['event_pointer']=f'/events/{i}';specs.append(entry)
    args['quotes']=make(tmp_path,monkeypatch,'quotes',payload,specs=specs)
    with pytest.raises(replay.ReplayError,match='ambiguous'):replay.simulate(**args)


@pytest.mark.parametrize('mutate', [
    {'finished_at': (CUTOFF+timedelta(minutes=1)).isoformat()},
    {'finished_at': (T+timedelta(minutes=1)).isoformat()},
    {'finished_at': None}, {'status':'IN_PROGRESS'}, {'score_period':'FULL_INCLUDING_EXTRA_TIME'},
    {'home_goals':None}, {'away_goals':True}, {'id':'event-a'},
])
def test_history_cannot_use_unfinished_unknown_or_target_data(tmp_path,monkeypatch,mutate):
    args=scenario(tmp_path,monkeypatch);row=dict(deepcopy(HISTORY),**mutate)
    args['history']=[make(tmp_path,monkeypatch,'history',{'history':[row]})]
    with pytest.raises(replay.ReplayError):replay.simulate(**args)


def test_duplicate_history_and_wrong_origin_or_dataset_rejected(tmp_path,monkeypatch):
    args=scenario(tmp_path,monkeypatch)
    with pytest.raises(replay.ReplayError,match='duplicate'):
        replay.simulate(**dict(args,history=args['history']*2))
    for origin,provider,dataset in [('file_import','synthetic','history'),('provider_response','synthetic','history'),
                                    ('synthetic','real_provider','history'),('synthetic','synthetic','fixture')]:
        path=make(tmp_path,monkeypatch,dataset,{'history':[deepcopy(HISTORY)]},origin=origin,provider=provider)
        with pytest.raises(replay.ReplayError,match='not marked'):
            replay.simulate(**dict(args,history=[path]))


@pytest.mark.parametrize('change', [
    {'id':'event-b'}, {'home_id':'wrong-team'}, {'kickoff_at': '2026-11-04T13:00:00'},
    {'finished_at':(T+timedelta(hours=5,minutes=5)).isoformat()},
    {'finished_at':None}, {'status':'POSTPONED'}, {'score_period':'EXTRA_TIME'},
    {'home_goals':None}, {'away_goals':-1},
])
def test_result_is_separate_matched_final_regulation_only(tmp_path,monkeypatch,change):
    trial=replay.simulate(**scenario(tmp_path,monkeypatch))
    result=make(tmp_path,monkeypatch,'result',{'event':dict(deepcopy(RESULT),**change)},at=T+timedelta(hours=5))
    with pytest.raises(replay.ReplayError):replay.settle(trial,result=result,as_of=T+timedelta(hours=6))


def test_tampered_snapshot_and_unsupported_market_do_not_proceed(tmp_path,monkeypatch):
    args=scenario(tmp_path,monkeypatch)
    with pytest.raises(replay.ReplayError,match='unsupported synthetic outcome'):
        replay.simulate(**dict(args,outcome='1X'))
    (args['quotes']/'payload.bin').write_bytes(b'{}')
    with pytest.raises(replay.ReplayError,match='snapshot rejected'):
        replay.simulate(**args)


def two_cases(tmp_path,monkeypatch):
    one=scenario(tmp_path,monkeypatch)
    first_result=make(tmp_path,monkeypatch,'result',{'event':deepcopy(RESULT)},at=T+timedelta(hours=5))
    event2=dict(deepcopy(FIXTURE),id='event-b')
    quote2=dict(deepcopy(QUOTED),id='event-b')
    result2=dict(deepcopy(RESULT),id='event-b',home_goals=0,away_goals=0)
    fixture2=make(tmp_path,monkeypatch,'fixture',{'event':event2})
    quotes2=make(tmp_path,monkeypatch,'quotes',{'event':quote2},specs=QSPEC)
    final2=make(tmp_path,monkeypatch,'result',{'event':result2},at=T+timedelta(hours=5))
    a=replay.ExerciseCase(CUTOFF,one['fixture'],tuple(one['history']),one['quotes'],'over',first_result,T+timedelta(hours=6))
    b=replay.ExerciseCase(CUTOFF,fixture2,tuple(one['history']),quotes2,'over',final2,T+timedelta(hours=6))
    return a,b


def test_chronological_matched_toy_scoring_and_no_result_leakage(tmp_path,monkeypatch):
    a,b=two_cases(tmp_path,monkeypatch)
    observed=[];original=replay._load
    def track(path,cutoff,dataset):
        observed.append(dataset)
        return original(path,cutoff,dataset)
    monkeypatch.setattr(replay,'_load',track)
    report=replay.run_chronological([a,b],max_quote_age=timedelta(hours=2),price_policy='final_picks')
    assert observed==['fixture','history','quotes','fixture','history','quotes','result','result']
    assert report['classification']=='synthetic_only' and report['matched_cases']==2
    assert [r['observed'] for r in report['rows']]==[1,0]
    assert [r['toy_probability'] for r in report['rows']]==pytest.approx([2/3,2/3])
    assert report['price_policy']=='final_picks' and report['max_quote_age_microseconds']==7200000000
    assert report['rows'][0]['decimal_odds']=='1.1801' and report['rows'][0]['home_goals']==2
    assert report['rows'][0]['quote_observation_age_microseconds']==7200000000
    assert report['toy_brier']==pytest.approx(5/18)
    assert report['baseline_brier']==0.25
    assert 'roi' not in report and 'profit' not in report


def test_exercise_rejects_unsorted_duplicate_and_missing_results(tmp_path,monkeypatch):
    from dataclasses import replace
    a,b=two_cases(tmp_path,monkeypatch)
    with pytest.raises(replay.ReplayError,match='duplicate target'):
        replay.run_chronological([a,a],max_quote_age=timedelta(hours=3),price_policy='final_picks')
    with pytest.raises(replay.ReplayError,match='ordered'):
        replay.run_chronological([a,replace(b,cutoff=CUTOFF-timedelta(minutes=1))],max_quote_age=timedelta(hours=3),price_policy='final_picks')
    with pytest.raises(replay.ReplayError,match='snapshot rejected'):
        replay.run_chronological([a,replace(b,settlement_as_of=CUTOFF+timedelta(minutes=1))],max_quote_age=timedelta(hours=3),price_policy='final_picks')


@pytest.mark.parametrize('policy,odds,passes', [
    ('app','1.1599',False), ('app','1.16',True), ('app','1.1799',True),
    ('final_picks','1.1799',False), ('final_picks','1.18',True), ('final_picks','1.1801',True),
])
def test_unrounded_exact_price_floors(tmp_path,monkeypatch,policy,odds,passes):
    args=scenario(tmp_path,monkeypatch);args['price_policy']=policy
    quoted=deepcopy(QUOTED);quoted['markets'][0]['outcomes'][0]['odds']=odds
    args['quotes']=make(tmp_path,monkeypatch,'quotes',{'event':quoted},specs=QSPEC)
    if passes:
        assert replay.simulate(**args).odds==odds
    else:
        with pytest.raises(replay.ReplayError,match='below the selected price floor'):
            replay.simulate(**args)


def test_unknown_price_policy_is_not_silently_defaulted(tmp_path,monkeypatch):
    args=scenario(tmp_path,monkeypatch)
    with pytest.raises(replay.ReplayError,match='explicit synthetic price policy'):
        replay.simulate(**dict(args,price_policy='unknown'))


def test_explicit_timezone_offsets_match_same_instant(tmp_path,monkeypatch):
    args=scenario(tmp_path,monkeypatch)
    fixture=deepcopy(FIXTURE)
    fixture['kickoff_at']=KICKOFF.astimezone(timezone(timedelta(hours=2))).isoformat()
    args['fixture']=make(tmp_path,monkeypatch,'fixture',{'event':fixture})
    args['cutoff']=CUTOFF.astimezone(timezone(timedelta(hours=-4)))
    assert replay.simulate(**args).kickoff==KICKOFF


def test_settlement_cannot_be_used_before_finish_or_without_final_score(tmp_path,monkeypatch):
    trial=replay.simulate(**scenario(tmp_path,monkeypatch))
    pre_finish=make(tmp_path,monkeypatch,'result',{'event':deepcopy(RESULT)},at=T+timedelta(hours=4))
    with pytest.raises(replay.ReplayError,match='not finished'):
        replay.settle(trial,result=pre_finish,as_of=T+timedelta(hours=6))
    with pytest.raises(replay.ReplayError,match='later than prediction'):
        replay.settle(trial,result=pre_finish,as_of=CUTOFF)
