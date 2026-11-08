"""Fixture review validates timezones and never writes approvals."""
import json
import pandas as pd
import pytest
from research.model_diagnostics import verify_premier_league_batch as review


def test_explicit_utc_offset_sign_and_dst():
    assert review.openfootball_utc('2026-05-24','16:00 UTC+1') == pd.Timestamp('2026-05-24T15:00:00Z')
    assert review.openfootball_utc('2026-01-04','12:00 UTC-2') == pd.Timestamp('2026-01-04T14:00:00Z')
    with pytest.raises(ValueError):review.openfootball_utc('2026-01-04','12:00 UTC+25')


def make_data(tmp_path,monkeypatch):
    monkeypatch.setattr(review,'FIXTURES',[('2026-05-24','A','B')])
    q=tmp_path/'queue.json';f=tmp_path/'fpl.csv';t=tmp_path/'teams.csv';o=tmp_path/'other.json'
    fd={'country':'England','league':'Premier League','date':'2026-05-24T00:00:00','home':'A','away':'B','hg':1,'ag':2,'_history_kickoff':'16:00'}
    ls={'home':'A','away':'B','hg':1,'ag':2,'eid':'42','_history_kickoff':'17:00'}
    q.write_text(json.dumps({'candidates':[{'status':'needs_review','candidate_id':'a'*64,'football_data':fd,'livescore':ls,'stat_conflicts':{}}]}))
    pd.DataFrame([{'id':1,'code':555,'team_h':10,'team_a':20,'kickoff_time':'2026-05-24T15:00:00Z',
                   'team_h_score':1,'team_a_score':2,'finished':True,'finished_provisional':True}]).to_csv(f,index=False)
    pd.DataFrame([{'id':10,'name':'A'},{'id':20,'name':'B'}]).to_csv(t,index=False)
    o.write_text(json.dumps({'name':'England | Premier League 2025/26','matches':[{'date':'2026-05-24','team1':'A','team2':'B',
                  'time':'16:00 UTC+1','score':{'ft':[1,2]}}]}))
    return q,f,t,o


def test_independent_corroboration_does_not_approve_unproven_offset(tmp_path,monkeypatch):
    paths=make_data(tmp_path,monkeypatch)
    out=review.verify(*paths)
    assert out['approved_count']==0
    assert out['records'][0]['utc_kickoff']=='2026-05-24T15:00:00+00:00'
    assert 'unverified' in out['records'][0]['livescore_clock_check']
    assert not (tmp_path/'history_reconciliation_approvals.json').exists()


def test_score_disagreement_is_not_accepted(tmp_path,monkeypatch):
    q,f,t,o=make_data(tmp_path,monkeypatch)
    d=json.loads(o.read_text());d['matches'][0]['score']['ft']=[1,3];o.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='score mismatch'):review.verify(q,f,t,o)
