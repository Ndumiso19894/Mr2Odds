from datetime import datetime, timedelta
from unittest.mock import Mock

from zoneinfo import ZoneInfo
import history
import worldfeed


def test_late_corner_stats_are_retried_after_previous_three_probes(tmp_path, monkeypatch):
    now = datetime(2026,11,7,7,tzinfo=ZoneInfo('Africa/Johannesburg'))
    days=history.Days(tmp_path,now)
    sc={'status':'FT','hg':2,'ag':1,'stp':3,'inc':[]}
    fixture={'kickoff':'2026-11-06 19:00','livescore_id':'123','score':sc}
    days.days={'2026-11-06':{'fixtures':[fixture]}}
    archive=Mock();archive.event_for.return_value=None;archive.stats_for.return_value=None
    fetch=Mock(return_value=[]);monkeypatch.setattr(worldfeed,'fetch_stats',fetch)
    days._enrich(archive)
    assert fetch.call_count == 1 and sc['stp']==4 and sc.get('hc') is None
    days._enrich(archive)
    assert fetch.call_count == 1  # bounded backoff, not on every scan
    days.now=now+timedelta(hours=7)
    fetch.return_value=[7,4]
    days._enrich(archive)
    assert fetch.call_count==2 and (sc['hc'],sc['ac'])==(7,4)


def test_partial_archived_statistics_still_trigger_corner_refresh(tmp_path,monkeypatch):
    now=datetime(2026,11,7,7,tzinfo=ZoneInfo('Africa/Johannesburg'))
    days=history.Days(tmp_path,now);sc={'status':'FT','hg':1,'ag':0,'inc':[]}
    days.days={'2026-11-06':{'fixtures':[{'kickoff':'2026-11-06 18:00','livescore_id':'123','score':sc}]}}
    archive=Mock();archive.event_for.return_value=None;archive.stats_for.return_value=[None,None,1,2]
    fetch=Mock(return_value=[3,5]);monkeypatch.setattr(worldfeed,'fetch_stats',fetch)
    days._enrich(archive)
    assert fetch.call_count==1 and sc['hc']==3 and sc['ac']==5


def test_scores_preserve_extra_time_and_verify_regulation(monkeypatch,tmp_path):
    import pandas as pd
    import livescore
    now=datetime(2026,11,7,7,tzinfo=ZoneInfo('Africa/Johannesburg'))
    d=history.Days(tmp_path,now)
    def fixture(eid):
        return {'kickoff':'2026-11-06 20:00','livescore_id':eid,'country':'England','league':'Example',
                'div':'X','home':f'H{eid}','away':f'A{eid}','score':None}
    d.days={'2026-11-06':{'fixtures':[fixture('1'),fixture('2'),{**fixture('3'),'score':{'hg':2,'ag':1,'status':'FT'}},fixture('4')]}}
    events=[{'eid':'1','status':'FT','hg':2,'ag':1}, {'eid':'2','status':'AET','hg':2,'ag':1},
            {'eid':'3','status':'FT','hg':2,'ag':1}, {'eid':'4','status':'Postp.','hg':None,'ag':None}]
    monkeypatch.setattr(livescore,'fetch_day',lambda *args:events)
    extra=d.fill_scores(pd.DataFrame())
    a,b,c,postponed=d.days['2026-11-06']['fixtures']
    assert a['score']['regulation_confirmed'] is True and b['score']['status']=='AET'
    assert b['score']['regulation_confirmed'] is False and c['score']['regulation_confirmed'] is True
    assert postponed['score']['status']=='Postp.' and postponed['score']['hg'] is None
    assert set(extra['home'])=={'H1'}
