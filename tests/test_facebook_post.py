"""Daily Facebook card: no fabricated prices, crests, fixtures or duplicate-prone retries."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from scripts import facebook_post as fb

NOW = datetime(2026, 11, 4, 8, tzinfo=fb.SAST)


def snapshot():
    fixtures, primary = [], []
    for i in range(10):
        f = {'id': str(i), 'home': f'Home {i}', 'away': f'Away {i}', 'country': 'England',
             'league': 'Championship', 'date': NOW.date().isoformat(), 'kickoff': '2026-11-04 12:00',
             'data_ok': True, 'q': 'High', 'badges': {'home': f'enet/{i}.png', 'away': f'enet/{i+10}.png'},
             'sels': [['O15', .82, .82, .8, 1.20, 0, None, None]]}
        fixtures.append(f); primary.append({'fixture': str(i), 'sel': 'O15', 'odds': 2.5, 'label': 'wrong'})
    return {'meta': {'generated': '2026-11-04 07:45'}, 'fixtures': fixtures, 'shortlist': {'primary': primary}}


def test_exact_current_selection_and_freshness():
    data = snapshot()
    picks = fb.candidates(data, NOW)
    assert len(picks) == 10
    assert picks[0]['odds'] == 1.2 and picks[0]['selection'] == 'Over 1.5 goals'
    data['meta']['generated'] = '2026-11-04 06:00'
    with pytest.raises(ValueError, match='stale'):
        fb.candidates(data, NOW)


def test_filters_paused_missing_started_duplicates_and_low_odds():
    data = snapshot()
    data['fixtures'][0]['sels'][0][4] = 1.159
    data['fixtures'][1]['sels'][0][4] = None
    data['fixtures'][2]['league'] = 'FA Cup'
    data['fixtures'][3]['kickoff'] = '2026-11-04 08:00'
    data['fixtures'][4]['sels'][0][0] = 'KO35'
    data['fixtures'][5]['q'] = 'Low'
    data['fixtures'][6]['sels'][0][5] = 1
    data['shortlist']['primary'].append(data['shortlist']['primary'][7])
    assert [p['fixture'] for p in fb.candidates(data, NOW)] == ['7', '8', '9']


def test_minimum_exact_floor_and_too_many_are_not_fabricated():
    data = snapshot()
    data['fixtures'][0]['sels'][0] = ['O15', .84, .84, .82, 1.16, 0]
    data['fixtures'][1]['sels'][0] = ['O15', .9, .9, .8, 1.159, 0]
    picks = fb.candidates(data, NOW)
    assert picks[0]['odds'] == 1.16
    assert not any(p['fixture'] == '1' for p in picks)


def test_prepare_requires_two_crests_and_maximum_eight(tmp_path, monkeypatch):
    source = tmp_path/'data.json'; source.write_text(json.dumps(snapshot()))
    output = tmp_path/'selections.png'
    im = Image.new('RGBA', (20,20), 'teal')
    monkeypatch.setattr(fb, 'badge', lambda session, team, path: None if team.endswith('0') else im)
    assert fb.prepare(source, output, NOW, session=object())
    assert Image.open(output).size == (1080, 1920)
    manifest = json.loads(output.with_suffix('.json').read_text())
    assert len(manifest['fixtures']) == 8
    assert all(not f['home'].endswith('0') for f in manifest['fixtures'])
    monkeypatch.setattr(fb, 'badge', lambda *args: None)
    other = tmp_path/'other.png'
    assert not fb.prepare(source, other, NOW, session=object())
    assert not other.exists()


def test_image_requires_five_to_eight_with_no_placeholder(tmp_path):
    with pytest.raises(ValueError, match='5 to 8'):
        fb.render([], tmp_path/'no.png')


def test_publish_uses_photo_endpoint_and_secret_without_logging(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('FACEBOOK_PAGE_ACCESS_TOKEN', 'example_test_secret_not_real')
    monkeypatch.setenv('FACEBOOK_PAGE_ID', '123456')
    path = tmp_path/'selections.png'; path.write_bytes(b'png')
    path.with_suffix('.json').write_text(json.dumps({'date':'2026-11-04', 'generated':'2026-11-04 07:45',
        'fixtures':[{'kickoff':'2026-11-04 12:00','home':'Home FC','away':'Away United'}]*5}))
    response = Mock(); response.json.return_value={'id':'123_456'}
    session = Mock(); session.post.return_value = response
    session.get.return_value = Mock(ok=True, json=Mock(return_value={'id': '123456'}))
    fb.publish(path, NOW, session=session)
    assert session.post.call_count == 1
    args, kwargs = session.post.call_args
    assert args[0] == 'https://graph.facebook.com/v24.0/123456/photos'
    assert kwargs['data']['message'] == "Today's safe bets - 4 November 2026\n\n#HomeFC #AwayUnited"
    assert 'example_test_secret_not_real' not in capsys.readouterr().out
    with pytest.raises(ValueError): fb.publish(path, NOW + timedelta(hours=4), session=session)
    assert session.post.call_count == 1


def test_workflow_claim_precedes_publish_and_never_retries():
    workflow = Path('.github/workflows/facebook-daily.yml').read_text()
    assert workflow.index('Record the daily posting claim') < workflow.index('Publish photo and caption')
    assert "group: facebook-daily-selections" in workflow
    assert 'FACEBOOK_PAGE_ACCESS_TOKEN' in workflow and 'FACEBOOK_PAGE_ID' in workflow
    assert 'actions/artifacts?per_page=100&name=$CLAIM_NAME' in workflow
    assert 'cron:' in workflow


def test_diagnose_is_read_only_and_sanitizes_facebook_errors(monkeypatch, capsys):
    monkeypatch.setenv('FACEBOOK_PAGE_ACCESS_TOKEN', 'example_token_not_real')
    monkeypatch.setenv('FACEBOOK_PAGE_ID', '123456')
    response = Mock(ok=True); response.json.return_value = {'id': '123456'}
    session = Mock(); session.get.return_value = response
    fb.diagnose(session)
    assert session.get.call_count == 1 and not session.post.called
    assert 'configured Page' in capsys.readouterr().out
    response.json.side_effect = [{'id': '98765'}, {'data': [{'id': '123456', 'access_token': 'example_page_token'}]}]
    fb.diagnose(session)
    assert 'authorized user token' in capsys.readouterr().out
    response.json.side_effect = [{'id': '98765'}, {'data': [{'id': '123456'}]}]
    with pytest.raises(RuntimeError, match='did not provide'):
        fb.diagnose(session)
    response.json.side_effect = [{'id': '98765'}, {'data': []}]
    with pytest.raises(RuntimeError, match='configured Page was not found'):
        fb.diagnose(session)
    response.json.side_effect = None
    response.ok = False; response.status_code = 400
    response.json.return_value = {'error': {'code': 190, 'error_subcode': 463, 'message': 'example_token_not_real'}}
    with pytest.raises(RuntimeError) as exc:
        fb.diagnose(session)
    assert 'HTTP 400' in str(exc.value) and 'Facebook code 190' in str(exc.value)
    assert 'example_token_not_real' not in str(exc.value)


def test_publish_error_reports_numeric_code_without_token(tmp_path, monkeypatch):
    monkeypatch.setenv('FACEBOOK_PAGE_ACCESS_TOKEN', 'example_test_secret_not_real')
    monkeypatch.setenv('FACEBOOK_PAGE_ID', '123456')
    path = tmp_path/'selections.png'; path.write_bytes(b'png')
    path.with_suffix('.json').write_text(json.dumps({'date':'2026-11-04', 'generated':'2026-11-04 07:45',
        'fixtures':[{'kickoff':'2026-11-04 12:00','home':'Home FC','away':'Away United'}]*5}))
    response = Mock(ok=False, status_code=403)
    response.json.return_value = {'error': {'code': 200, 'message': 'example_test_secret_not_real'}}
    session = Mock(); session.post.return_value = response
    session.get.return_value = Mock(ok=True, json=Mock(return_value={'id': '123456'}))
    with pytest.raises(RuntimeError) as exc:
        fb.publish(path, NOW, session=session)
    assert 'HTTP 403' in str(exc.value) and 'Facebook code 200' in str(exc.value)
    assert 'example_test_secret_not_real' not in str(exc.value)
    assert session.post.call_count == 1


def test_publish_derives_only_configured_page_token_in_memory(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('FACEBOOK_PAGE_ACCESS_TOKEN', 'example_user_token')
    monkeypatch.setenv('FACEBOOK_PAGE_ID', '123456')
    path = tmp_path/'card.png'; path.write_bytes(b'png')
    path.with_suffix('.json').write_text(json.dumps({'date':'2026-11-04', 'generated':'2026-11-04 07:45',
        'fixtures':[{'kickoff':'2026-11-04 12:00','home':'Home FC','away':'Away United'}]*5}))
    session = Mock()
    session.get.side_effect = [Mock(ok=True, json=Mock(return_value={'id':'99'})),
                               Mock(ok=True, json=Mock(return_value={'data':[{'id':'123456','access_token':'example_derived_page_token'}]}))]
    session.post.return_value = Mock(ok=True, json=Mock(return_value={'id':'published'}))
    fb.publish(path, NOW, session=session)
    assert session.post.call_args.kwargs['data']['access_token'] == 'example_derived_page_token'
    assert 'example_derived_page_token' not in capsys.readouterr().out
    assert 'example_derived_page_token' not in path.with_suffix('.json').read_text()


def test_caption_has_only_the_teams_on_the_picture():
    info = {'date': '2026-11-04', 'fixtures': [
        {'home': 'St. John’s FC', 'away': 'AS Étoile'},
        {'home': 'Manchester United', 'away': 'Away United'},
        {'home': 'Home Club', 'away': 'Away Club'},
        {'home': 'Home 4', 'away': 'Away 4'},
        {'home': 'Home 5', 'away': 'Away 5'},
    ]}
    caption = fb.caption_for(info)
    assert caption.startswith("Today's safe bets - 4 November 2026\n\n")
    assert caption.splitlines()[2].split() == ['#StJohnsFC', '#ASÉtoile', '#ManchesterUnited', '#AwayUnited',
                                                '#HomeClub', '#AwayClub', '#Home4', '#Away4', '#Home5', '#Away5']
    assert '#Mr2Odds' not in caption and '#BettingTips' not in caption
    info['fixtures'][4]['away'] = 'Away United'  # repeated clubs appear only once
    assert fb.caption_for(info).count('#AwayUnited') == 1


def test_portrait_fits_long_team_names_without_colliding():
    from PIL import ImageDraw
    draw = ImageDraw.Draw(Image.new('RGB', (1080,1920)))
    fb.draw_team(draw, 'A very long football club name', 158, 300, 'lm')
    fb.draw_team(draw, 'Another very long away team name', 922, 300, 'rm')


def test_workflow_corrected_retry_is_explicit_and_separate():
    workflow = Path('.github/workflows/facebook-daily.yml').read_text()
    assert 'retry_today:' in workflow
    assert "[ \"$EVENT_NAME\" = 'workflow_dispatch' ] && [ \"$RETRY_TODAY\" = 'true' ]" in workflow
    assert 'claim="$claim-retry"' in workflow
    assert 'corrected retry requires an existing claim' in workflow
    assert 'name: ${{ steps.day.outputs.claim }}' in workflow
