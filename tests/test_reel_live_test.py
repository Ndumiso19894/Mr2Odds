"""Explicit one-time live tests are separate from the automatic morning reel."""
import json
from datetime import datetime
from unittest.mock import Mock

from scripts import facebook_post as fb
from scripts import selection_reel as reel

NOW = datetime(2026, 11, 4, 20, tzinfo=fb.SAST)


def make_reel(path):
    (path/'selection-reel.mp4').write_bytes(b'video')
    info = {'date':'2026-11-04', 'generated':'2026-11-04 19:45', 'fixtures':[
        {'home':f'Home {i}', 'away':f'Away {i}', 'kickoff':'2026-11-04 22:30'} for i in range(5)]}
    (path/'selection-reel.json').write_text(json.dumps(info))
    return info


def test_live_test_label_keeps_caption_and_only_team_hashtags(tmp_path, monkeypatch):
    info = make_reel(tmp_path)
    standard = reel.reel_caption(info)
    test = reel.reel_caption(info, test=True)
    assert test.startswith("Today's safe bets - 4 November 2026\n\nTest reel\n\n")
    assert test.splitlines()[-1] == standard.splitlines()[-1]
    assert '#Mr2Odds' not in test
    monkeypatch.setenv('REEL_TEST', 'true')
    monkeypatch.setenv('FACEBOOK_PAGE_ACCESS_TOKEN', 'fake-token')
    monkeypatch.setenv('FACEBOOK_PAGE_ID', '123456')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'fake-telegram-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '123')
    session = Mock()
    session.get.side_effect = [Mock(ok=True, json=Mock(return_value={'id':'123456'})),
        Mock(ok=True, json=Mock(return_value={'status':{'publishing_phase':{'status':'complete'}}}))]
    session.post.side_effect = [Mock(ok=True, json=Mock(return_value={'video_id':'12'})),
        Mock(ok=True, json=Mock(return_value={'success':True})),
        Mock(ok=True, json=Mock(return_value={'success':True})),
        Mock(ok=True, json=Mock(return_value={'ok':True}))]
    reel.publish_facebook(tmp_path, NOW, session, pause=lambda _:None)
    reel.publish_telegram(tmp_path, NOW, session)
    assert session.post.call_args_list[2].kwargs['data']['description'] == test
    assert session.post.call_args_list[3].kwargs['data']['caption'] == test


def test_default_caption_has_no_test_label(tmp_path, monkeypatch):
    info = make_reel(tmp_path)
    monkeypatch.delenv('REEL_TEST', raising=False)
    assert reel.reel_caption(info) == fb.caption_for(info)
    assert 'Test reel' not in reel.reel_caption(info)
