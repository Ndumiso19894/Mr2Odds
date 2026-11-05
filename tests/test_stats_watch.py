from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from PIL import Image
from scripts import stats_watch as sw
from scripts import stats_watch_assets as assets
from scripts import facebook_post as fb
from scripts import selection_reel as reel
from scripts import facebook_one_x_two as one_x_two

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)


def table(losses=0, season=2026):
    stats = {'rank':1, 'gamesPlayed':8, 'wins':5, 'ties':3-losses, 'losses':losses}
    return {'name':'German Bundesliga', 'children':[{'standings':{'season':season, 'entries':[
        {'team':{'id':'132','displayName':'Bayern Munich'},
         'stats':[{'name':k,'value':v} for k,v in stats.items()]}]}}]}


def event(dt, home='132', away='2950', name='German Bundesliga', slug='ger.1', status='STATUS_SCHEDULED', home_score=0, away_score=0, event_id='100'):
    teams = [ {'id':home, 'homeAway':'home','team':{'displayName':'Bayern Munich' if home=='132' else 'Mainz'}, 'score':{'value':home_score}},
              {'id':away, 'homeAway':'away','team':{'displayName':'Bayern Munich' if away=='132' else 'Mainz'}, 'score':{'value':away_score}} ]
    for team in teams:
        team['team']['logos'] = [{'href': f"https://a.espncdn.com/i/teamlogos/soccer/500/{team['id']}.png"}]
    completed = status == 'STATUS_FULL_TIME'
    return {'id':event_id, 'date':dt.isoformat(), 'timeValid':True,
            'season':{'year':2026, 'displayName':name}, 'league':{'slug':slug},
            'competitions':[{'competitors':teams,'status':{'type':{'name':status, 'state':'post' if completed else 'pre', 'completed':completed}}}]}


def feeds(losses=0):
    c=sw.table_candidates('ger.1',table(losses),NOW)[0]
    results=[]
    for i in range(8):
        # Chronologically first result is a defeat if requested.
        outcome = 0 if losses and i == 0 else 1 if i < 5 + losses else 2
        score = (0,1) if outcome == 0 else (1,0) if outcome == 1 else (0,0)
        results.append(event(NOW-timedelta(days=14-i), status='STATUS_FULL_TIME',
                             home_score=score[0],away_score=score[1],event_id=str(200+i)))
    local = {'team':{'id':'132','recordSummary':c['record']},'events':results}
    upcoming = {'timestamp':NOW.isoformat(),'events':[event(NOW+timedelta(days=2))]}
    return c, local, upcoming


def test_standings_eligibility_and_stale_tables():
    assert sw.table_candidates('ger.1',table(),NOW)[0]['played'] == 8
    assert sw.table_candidates('ger.1',table(season=2025),NOW) == []
    bad=table(); bad['children'][0]['standings']['entries'][0]['stats'][0]['value']=3
    assert sw.table_candidates('ger.1',bad,NOW) == []
    bad=table(); bad['children'].append(deepcopy(bad['children'][0]))
    assert sw.table_candidates('ger.1',bad,NOW) == []


def test_next_fixture_not_a_later_allowed_game():
    c, local, future = feeds()
    row = sw.next_fixture(c,local,future,NOW)
    assert row['streak']==8 and row['home']=='Bayern Munich'
    future['events'].insert(0,event(NOW+timedelta(days=1),name='German Cup',slug='ger.dfb_pokal',event_id='101'))
    assert sw.next_fixture(c,local,future,NOW) is None
    future['events'][0]['timeValid']=False
    assert sw.next_fixture(c,local,future,NOW) is None


def test_recent_run_after_loss_needs_complete_consistent_results():
    c, local, future = feeds(1)
    row = sw.next_fixture(c,local,future,NOW)
    assert row['streak'] == 7
    local['events'].pop(0)
    assert sw.next_fixture(c,local,future,NOW) is None
    c, local, future = feeds(1)
    local['events'][-1]['competitions'][0]['competitors'][0]['score']['value']=0
    local['events'][-1]['competitions'][0]['competitors'][1]['score']['value']=1
    assert sw.next_fixture(c,local,future,NOW) is None


def test_stale_source_and_inconsistent_record_fail():
    c, local, future = feeds()
    local['team']['recordSummary']='4-4-0'
    assert sw.next_fixture(c,local,future,NOW) is None
    c, local, future = feeds()
    future['timestamp']=(NOW-timedelta(hours=7)).isoformat()
    assert sw.next_fixture(c,local,future,NOW) is None
    c, local, future = feeds()
    for e in local['events']:
        e['date']=(NOW-timedelta(days=40)).isoformat()
    assert sw.next_fixture(c,local,future,NOW) is None


def test_stat_manifest_caption_and_recap_isolation(tmp_path):
    c, local, future = feeds(); row=sw.next_fixture(c,local,future,NOW)
    info={'series':'stats-watch','date':'2026-11-05','as_of':NOW.isoformat(),
          'generated':'2026-11-05 12:00','fixtures':[],'rows':[row]}
    assets.validate_manifest(info,NOW)
    assert '#BayernMunich' in fb.caption_for(info) and 'picks' not in fb.caption_for(info)
    bad=deepcopy(info); bad['rows'][0]['streak']=2
    with pytest.raises(ValueError): assets.validate_manifest(bad,NOW)
    assert assets.validate_manifest(info,NOW)['fixtures'] == []
    from scripts.facebook_results import recap_items
    assert recap_items([{'manifest':info}],{'date':'2026-11-05','fixtures':[]},'2026-11-05') == []
    bad=deepcopy(info);bad['as_of']=(NOW-timedelta(hours=3)).isoformat()
    with pytest.raises(ValueError): assets.validate_manifest(bad,NOW)


def test_visuals_render_without_real_team_logos(tmp_path):
    c, local, future = feeds(); row=sw.next_fixture(c,local,future,NOW)
    row.update(home_image=Image.new('RGBA',(60,60),'blue'),away_image=Image.new('RGBA',(60,60),'red'))
    assets.render_picture([row],NOW,tmp_path/'picture.png')
    assets.render_slide([row],1,1,NOW,tmp_path/'slide.png')
    assert Image.open(tmp_path/'picture.png').size == (1080,1920)
    assert Image.open(tmp_path/'slide.png').size == (1080,1920)


def test_club_crest_and_earliest_scheduled_match_are_required():
    c, local, future = feeds()
    future['events'][0]['competitions'][0]['competitors'][0]['team']['logos'] = []
    assert sw.next_fixture(c,local,future,NOW) is None
    c, local, future = feeds()
    earlier = event(NOW-timedelta(minutes=2),event_id='101')
    future['events'].insert(0,earlier)
    assert sw.next_fixture(c,local,future,NOW) is None
    c, local, future = feeds()
    later = event(NOW+timedelta(days=10),event_id='102')
    later['timeValid'] = False
    future['events'].append(later)
    assert sw.next_fixture(c,local,future,NOW)['event_id'] == '100'


def test_loss_run_proof_is_auditable_and_tampering_rejected():
    c, local, future = feeds(1)
    row = sw.next_fixture(c,local,future,NOW)
    info = {'series':'stats-watch','date':'2026-11-05','as_of':NOW.isoformat(),
            'generated':'2026-11-05 12:00','fixtures':[],'rows':[row]}
    assets.validate_manifest(info,NOW)
    bad = deepcopy(info)
    bad['rows'][0]['results_proof'][0]['outcome'] = 'L'
    with pytest.raises(ValueError):
        assets.validate_manifest(bad,NOW)
    bad = deepcopy(info)
    bad['rows'][0]['results_proof'][0]['event_id'] = bad['rows'][0]['results_proof'][1]['event_id']
    with pytest.raises(ValueError):
        assets.validate_manifest(bad,NOW)
