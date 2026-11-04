import hashlib
import json
import math
import struct
import subprocess
import wave
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image
from scripts import selection_reel as reel
from scripts import facebook_post as fb

NOW = datetime(2026, 11, 4, 7, 10, tzinfo=fb.SAST)


def data():
    fixtures, primary = [], []
    for i in range(10):
        f = {'id':str(i), 'home':f'Home {i}', 'away':f'Away {i}', 'country':'England',
             'league':'Championship', 'date':'2026-11-04', 'kickoff':'2026-11-04 15:00', 'time_known':True,
             'data_ok':True, 'q':'High', 'badges':{'home':'enet/1.png','away':'enet/2.png'},
             'sels':[['O15',.82,.82,.8,1.20,0]]}
        fixtures.append(f); primary.append({'fixture':str(i),'sel':'O15'})
    return {'meta':{'generated':'2026-11-04 07:00'},'fixtures':fixtures,'shortlist':{'primary':primary}}


def prepared(tmp_path, count=5):
    (tmp_path/'selection-reel.mp4').write_bytes(b'fake-video')
    info = {'date':'2026-11-04','generated':'2026-11-04 07:00',
            'fixtures':[{'home':f'Home {i}', 'away':f'Away {i}', 'kickoff':'2026-11-04 15:00'} for i in range(count)]}
    (tmp_path/'selection-reel.json').write_text(json.dumps(info))
    return info


def test_preparation_uses_only_current_eligible_selections_and_real_crests(tmp_path, monkeypatch):
    source=tmp_path/'snapshot.json'; source.write_text(json.dumps(data()))
    music=tmp_path/'music.mp3'; music.write_bytes(b'music')
    image=Image.new('RGBA',(15,15),'teal')
    monkeypatch.setattr(fb,'badge',lambda session, team, path: None if team.endswith('0') else image)
    monkeypatch.setattr(reel,'encode',lambda slides, music, out: out.write_bytes(b'video'))
    output=tmp_path/'out'
    assert reel.prepare(source,output,NOW,object(),music)
    manifest=json.loads((output/'selection-reel.json').read_text())
    assert len(manifest['fixtures'])==8
    assert all(x['sel']=='O15' and x['selection']=='Over 1.5 goals' and x['odds']==1.2 for x in manifest['fixtures'])
    assert all(not x['home'].endswith('0') for x in manifest['fixtures'])
    reel.validate_prepared(output,NOW)
    monkeypatch.setattr(fb,'badge',lambda *args:None)
    assert not reel.prepare(source,tmp_path/'empty',NOW,object(),music)
    assert not (tmp_path/'empty'/'selection-reel.mp4').exists()


def test_validate_rejects_stale_started_or_unpriced_manifest(tmp_path):
    info=prepared(tmp_path)
    with pytest.raises(ValueError,match='stale'):
        reel.validate_prepared(tmp_path,NOW+timedelta(hours=2))
    info['fixtures'][0]['kickoff']='2026-11-04 07:15'
    (tmp_path/'selection-reel.json').write_text(json.dumps(info))
    with pytest.raises(ValueError,match='expired'):
        reel.validate_prepared(tmp_path,NOW)
    info['fixtures']=info['fixtures'][:4]
    (tmp_path/'selection-reel.json').write_text(json.dumps(info))
    with pytest.raises(ValueError,match='invalid'):
        reel.validate_prepared(tmp_path,NOW)


def test_music_download_checks_content_hash_and_size(tmp_path, monkeypatch):
    monkeypatch.setenv('REEL_MUSIC_FILE_ID','fake-file-id-123')
    content=b'user-selected-audio'
    monkeypatch.setattr(reel,'MUSIC_SHA256',hashlib.sha256(content).hexdigest())
    session=Mock(); session.get.return_value=Mock(iter_content=Mock(return_value=[content]))
    reel.download_music(tmp_path/'track.mp3',session)
    assert (tmp_path/'track.mp3').read_bytes()==content
    monkeypatch.setattr(reel,'MUSIC_SHA256','wrong')
    with pytest.raises(ValueError,match='does not match'):
        reel.download_music(tmp_path/'wrong.mp3',session)


def test_facebook_uses_real_reels_api_and_confirms_publication(tmp_path, monkeypatch, capsys):
    prepared(tmp_path)
    monkeypatch.setenv('FACEBOOK_PAGE_ACCESS_TOKEN','fake-user-token')
    monkeypatch.setenv('FACEBOOK_PAGE_ID','123456')
    session=Mock()
    session.get.side_effect=[Mock(ok=True,json=Mock(return_value={'id':'123456'})),
                             Mock(ok=True,json=Mock(return_value={'status':{'publishing_phase':{'status':'complete'}}}))]
    session.post.side_effect=[Mock(ok=True,json=Mock(return_value={'video_id':'9988','upload_url':'https://attacker.invalid'})),
                              Mock(ok=True,json=Mock(return_value={'success':True})),
                              Mock(ok=True,json=Mock(return_value={'success':True}))]
    reel.publish_facebook(tmp_path,NOW,session,pause=lambda _:None)
    start, upload, finish=session.post.call_args_list
    assert start.args[0].endswith('/123456/video_reels') and start.kwargs['data']['upload_phase']=='start'
    assert upload.args[0]=='https://rupload.facebook.com/video-upload/v24.0/9988'
    assert upload.kwargs['headers']['Authorization']=='OAuth fake-user-token'
    assert finish.kwargs['data']['video_state']=='PUBLISHED'
    assert finish.kwargs['data']['description'].startswith("Today's safe bets - 4 November 2026\n\n#Home0 #Away0")
    assert 'fake-user-token' not in capsys.readouterr().out


def test_facebook_processing_unknown_is_not_claimed_as_success(tmp_path, monkeypatch):
    prepared(tmp_path)
    monkeypatch.setenv('FACEBOOK_PAGE_ACCESS_TOKEN','fake-token');monkeypatch.setenv('FACEBOOK_PAGE_ID','123456')
    session=Mock()
    session.get.side_effect=[Mock(ok=True,json=Mock(return_value={'id':'123456'}))]+[Mock(ok=True,json=Mock(return_value={'status':{'publishing_phase':{'status':'in_progress'}}})) for _ in range(12)]
    session.post.side_effect=[Mock(ok=True,json=Mock(return_value={'video_id':'98'})),Mock(ok=True,json=Mock(return_value={'success':True})),Mock(ok=True,json=Mock(return_value={'success':True}))]
    with pytest.raises(RuntimeError,match='still pending'):
        reel.publish_facebook(tmp_path,NOW,session,pause=lambda _:None)
    assert session.post.call_count==3  # no automatic second publish


def test_telegram_gets_same_video_and_team_only_hashtags(tmp_path, monkeypatch, capsys):
    prepared(tmp_path)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','fake-secret');monkeypatch.setenv('TELEGRAM_CHAT_ID','123')
    session=Mock();session.post.return_value=Mock(ok=True,json=Mock(return_value={'ok':True}))
    reel.publish_telegram(tmp_path,NOW,session)
    call=session.post.call_args
    assert call.args[0].endswith('/sendVideo')
    assert call.kwargs['files']['video'][0]=='selection-reel.mp4'
    assert '#Home0' in call.kwargs['data']['caption'] and '#Mr2Odds' not in call.kwargs['data']['caption']
    assert 'fake-secret' not in capsys.readouterr().out
    session.post.side_effect=reel.requests.Timeout('uncertain')
    with pytest.raises(RuntimeError,match='check the chat'):
        reel.publish_telegram(tmp_path,NOW,session)
    assert session.post.call_count==2


def test_actual_encoded_video_is_vertical_with_audio(tmp_path):
    imageio=pytest.importorskip('imageio_ffmpeg')
    img=tmp_path/'slide.png'; Image.new('RGB',(1080,1920),'white').save(img)
    audio=tmp_path/'tone.wav'
    with wave.open(str(audio),'wb') as w:
        w.setparams((1,2,44100,0,'NONE','not compressed'))
        w.writeframes(b''.join(struct.pack('<h', int(5000*math.sin(2*math.pi*440*i/44100))) for i in range(44100)))
    video=tmp_path/'reel.mp4'
    reel.encode([img],audio,video)
    p=subprocess.run([imageio.get_ffmpeg_exe(),'-i',str(video)],capture_output=True,text=True)
    assert '1080x1920' in p.stderr and 'Video: h264' in p.stderr and 'Audio: aac' in p.stderr
    assert '00:00:04.00' in p.stderr


def test_reel_workflow_claims_before_each_platform_and_preserves_existing_schedule():
    text=Path('.github/workflows/facebook-reel.yml').read_text()
    scan=Path('.github/workflows/scan-30.yml').read_text()
    assert "cron: '0 5 * * *'" in text
    assert text.index('Claim Facebook reel delivery') < text.index('Publish Facebook reel')
    assert text.index('Claim Telegram reel delivery') < text.index('Send the same video to Telegram')
    assert 'steps.facebook-claim.outcome' in text and 'steps.telegram-claim.outcome' in text
    assert 'prefix=daily-reel' in text and 'prefix=test-reel' in text
    assert "[ \"$EVENT_NAME\" = 'workflow_dispatch' ] && [ \"$LIVE_TEST\" = 'true' ]" in text
    assert 'name: ${{ steps.claims.outputs.prefix }}-source-${{ steps.claims.outputs.date }}' in text
    assert 'name: ${{ steps.claims.outputs.prefix }}-facebook-${{ steps.claims.outputs.date }}' in text
    assert 'name: ${{ steps.claims.outputs.prefix }}-telegram-${{ steps.claims.outputs.date }}' in text
    assert 'facebook-reel.yml' in scan and 'facebook-daily.yml' in scan
