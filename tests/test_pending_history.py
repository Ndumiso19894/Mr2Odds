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
