import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image
from scripts import facebook_history as history
from scripts import facebook_post as fb
from scripts import facebook_results as results

DAY = '2026-11-04'
NOW = datetime(2026, 11, 5, 8, tzinfo=fb.SAST)


def item(i, sel='O15'):
    return {'fixture': f'id-{i}', 'home': f'Home {i}', 'away': f'Away {i}', 'kickoff': DAY+' 21:00',
            'country': 'England', 'league': 'Championship', 'sel': sel, 'selection': 'Over 1.5 goals',
            'odds': 1.25, 'badges': {'home':'enet/1.png','away':'enet/2.png'}}


def claim(items):
    return {'name':'facebook-post-2026-11-04-07', 'manifest':{'date':DAY,'fixtures':items}}


def archive(items):
    return {'date': DAY, 'fixtures': [{**i, 'id':i['fixture'], 'score': {'status':'FT','src':'results', 'hg':2,'ag':1,'hc':6,'ac':4}} for i in items]}


def test_recap_uses_exact_published_picks_and_no_false_grading():
    picks = [item(1), item(2,'CO85'), item(3,'O25'), item(4)]
    data = archive(picks)
    data['fixtures'][1]['score'].pop('hc')  # score alone cannot settle corners
    data['fixtures'][2]['score'].update(hg=0, ag=1)
    data['fixtures'][3]['score'] = {'status':'Postp.'}
    rows = results.recap_items([claim(picks)], data, DAY)
    assert [(r['score_text'],r['verdict']) for r in rows] == [('2–1','WON'),('2–1','PENDING'),('0–1','LOST'),('–','POSTPONED')]
    # Knockout UEFA records do not prove the score is 90-minute regulation.
    picks[0]['country'] = 'Champions League'
    data['fixtures'][0]['country'] = 'Champions League'
    assert results.recap_items([claim(picks)], data, DAY)[0]['verdict'] == 'PENDING'
    data['fixtures'][0]['home'] = 'Other'
    with pytest.raises(ValueError, match='does not match'):
        results.recap_items([claim(picks)], data, DAY)


def test_legacy_posts_have_score_only_not_a_guessed_pick():
    original = item(1)
    old = {k:original[k] for k in ('home','away','kickoff')}
    rows = results.recap_items([claim([old]), claim([old])], archive([original]), DAY)
    assert len(rows) == 1
    assert rows[0]['score_text'] == '2–1' and rows[0]['verdict'] == 'SCORE ONLY'
    assert rows[0]['selection'] == 'Selection not recorded'
    assert rows[0]['country'] == 'England'


def test_two_portraits_cover_all_24_picks_without_placeholder_crests(tmp_path, monkeypatch):
    picks = [item(i) for i in range(24)]
    claims = [claim(picks[:8]), claim(picks[8:16]), claim(picks[16:])]
    data = archive(picks)
    (tmp_path/'day.json').write_text(json.dumps(data))
    (tmp_path/'badges.json').write_text('{}')
    im = Image.new('RGBA',(30,30),'teal')
    monkeypatch.setattr(fb,'badge',lambda *args:im)
    assert results.prepare(tmp_path/'day.json', tmp_path/'badges.json', tmp_path/'out', NOW, claims=claims, session=object())
    for i in (1,2):
        assert Image.open(tmp_path/f'out/results-{i}.png').size == (1080,1920)
        assert Image.open(tmp_path/f'out/results-{i}.png').getpixel((0,0)) == (255,255,255)
    assert len(json.loads((tmp_path/'out/results.json').read_text())['fixtures']) == 24
    monkeypatch.setattr(fb,'badge',lambda *args:None)
    with pytest.raises(ValueError, match='missing a verified club crest'):
        results.prepare(tmp_path/'day.json', tmp_path/'badges.json', tmp_path/'no', NOW, claims=claims, session=object())


def test_missing_results_and_capacity_are_never_fabricated():
    picks = [item(1)]
    data = {'date':DAY,'fixtures':[]}
    row = results.recap_items([claim(picks)], data, DAY)[0]
    assert row['score_text'] == '–' and row['verdict'] == 'PENDING'
    with pytest.raises(ValueError, match='More than 24'):
        results.recap_items([claim([item(i) for i in range(25)])], data, DAY)


def test_publish_two_unpublished_photos_in_one_feed_post(tmp_path, monkeypatch):
    monkeypatch.setenv('FACEBOOK_PAGE_ACCESS_TOKEN','fake-token')
    monkeypatch.setenv('FACEBOOK_PAGE_ID','123456')
    for i in (1,2): (tmp_path/f'results-{i}.png').write_bytes(b'png')
    (tmp_path/'results.json').write_text(json.dumps({'date':DAY,'fixtures':[{'home':'Home FC','away':'Away United'}]}))
    session = Mock()
    session.get.return_value = Mock(ok=True, json=Mock(return_value={'id':'123456'}))
    session.post.side_effect = [Mock(ok=True,json=Mock(return_value={'id':'101'})),
                                Mock(ok=True,json=Mock(return_value={'id':'102'})),
                                Mock(ok=True,json=Mock(return_value={'id':'postid'}))]
    results.publish(tmp_path,NOW,session)
    assert session.post.call_count == 3
    calls = session.post.call_args_list
    assert all(c.kwargs['data']['published'] == 'false' for c in calls[:2])
    assert calls[2].args[0].endswith('/123456/feed')
    data = calls[2].kwargs['data']
    assert json.loads(data['attached_media[0]']) == {'media_fbid':'101'}
    assert json.loads(data['attached_media[1]']) == {'media_fbid':'102'}
    assert data['message'] == ("Yesterday's results - 4 November 2026\n\n"
        "Which match did you follow?\nFollow Mr 2 Odds for daily picks and results.\n"
        "18+ | Bet responsibly.\n\n#HomeFC #AwayUnited")
    with pytest.raises(ValueError, match='yesterday'):
        results.publish(tmp_path, NOW.replace(day=6), session)
    assert session.post.call_count == 3


def test_results_not_retried_automatically_on_uncertain_feed_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('FACEBOOK_PAGE_ACCESS_TOKEN','fake-token')
    monkeypatch.setenv('FACEBOOK_PAGE_ID','123456')
    for i in (1,2): (tmp_path/f'results-{i}.png').write_bytes(b'png')
    (tmp_path/'results.json').write_text(json.dumps({'date':DAY,'fixtures':[{'home':'A','away':'B'}]}))
    session = Mock(); session.get.return_value = Mock(ok=True,json=Mock(return_value={'id':'123456'}))
    session.post.side_effect = [Mock(ok=True,json=Mock(return_value={'id':'1'})),Mock(ok=True,json=Mock(return_value={'id':'2'})),
                                results.requests.Timeout('timeout')]
    with pytest.raises(RuntimeError,match='check the Page'):
        results.publish(tmp_path,NOW,session)
    assert session.post.call_count == 3


def test_claim_loader_fails_closed_and_checks_success(monkeypatch):
    monkeypatch.setenv('GH_TOKEN','fake-token'); monkeypatch.setenv('GITHUB_REPOSITORY','owner/repo')
    raw = io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:
        z.writestr('selections.json', json.dumps(claim([item(1)])['manifest']))
    artifact = {'id':123,'name':'facebook-post-'+DAY+'-07','expired':False,'workflow_run':{'id':7}}
    session = Mock(); session.headers = {}
    def get(url, params=None, timeout=None):
        if url.endswith('/actions/artifacts'):
            return Mock(json=Mock(return_value={'artifacts': [artifact] if params['name'] == artifact['name'] else []}))
        if url.endswith('/actions/runs/7/jobs'):
            return Mock(json=Mock(return_value={'jobs':[{'name':'post','steps':[{'name':'Publish photo and caption to Facebook','conclusion':'success'}]}]}))
        if url.endswith('/actions/artifacts/123/zip'):
            return Mock(content=raw.getvalue())
        raise AssertionError(url)
    session.get.side_effect=get
    loaded=history.load_claims(DAY,confirmed_only=True,session=session)
    assert len(loaded)==1 and history.match_key(item(1)) in history.prior_matches(loaded)
    def failed(url, params=None, timeout=None):
        if url.endswith('/actions/runs/7/jobs'):
            return Mock(json=Mock(return_value={'jobs':[{'name':'post','steps':[{'name':'Publish photo and caption to Facebook','conclusion':'failure'}]}]}))
        return get(url,params,timeout)
    session.get.side_effect=failed
    with pytest.raises(RuntimeError,match='unconfirmed'):
        history.load_claims(DAY,confirmed_only=True,session=session)
