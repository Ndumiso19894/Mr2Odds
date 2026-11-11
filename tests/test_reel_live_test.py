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


def test_video_captions_are_only_team_hashtags_even_in_live_test_mode(tmp_path, monkeypatch):
    info = make_reel(tmp_path)
    standard = reel.reel_caption(info)
    test = reel.reel_caption(info, test=True)
    expected = ' '.join(f'#{name.replace(" ", "")}' for i in range(5)
                        for name in (f'Home {i}', f'Away {i}'))
    assert standard == test == expected
    assert all(tag.startswith('#') for tag in test.split())
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


def test_default_video_caption_is_only_team_hashtags(tmp_path, monkeypatch):
    info = make_reel(tmp_path)
    monkeypatch.delenv('REEL_TEST', raising=False)
    caption = reel.reel_caption(info)
    assert caption == fb.caption_for(info, medium='reel')
    assert all(tag.startswith('#') for tag in caption.split())


def test_revised_live_test_has_separate_opt_in_claims():
    from pathlib import Path
    workflow = Path('.github/workflows/facebook-reel.yml').read_text()
    assert 'revised_test:' in workflow
    assert "[ \"$EVENT_NAME\" = 'workflow_dispatch' ] && [ \"$REVISED_TEST\" = 'true' ]" in workflow
    assert 'Select only one live-test option' in workflow
    assert 'prefix=test-reel-10s' in workflow and 'prefix=test-reel\n' in workflow
    assert 'prefix=daily-reel' in workflow
    assert workflow.count("startsWith(steps.claims.outputs.prefix, 'test-reel')") == 2
    assert workflow.index('Claim Facebook reel delivery') < workflow.index('Publish Facebook reel')
    assert workflow.index('Claim Telegram reel delivery') < workflow.index('Send the same video to Telegram')
