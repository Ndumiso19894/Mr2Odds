import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw
from scripts import facebook_history as history
from scripts import facebook_one_x_two as x12
from scripts import facebook_post as fb
from scripts import selection_reel as reel

NOW = datetime(2026, 11, 5, 13, tzinfo=fb.SAST)


def snapshot(n=9):
    fixtures = []
    for i in range(n):
        fixture = {'id':str(i), 'home':f'Home {i}', 'away':f'Away {i}', 'country':'England',
            'league':'Premier League', 'date':'2026-11-05', 'kickoff':'2026-11-05 17:00',
            'time_known':True, 'data_ok':True, 'q':'High', 'badges':{'home':'enet/a.png','away':'enet/b.png'},
            'livescore_id':f'event-{i}', 'sels':[
                ['O15', .85, .85, .83, 1.2, 0],
                ['H', .80, .80, .79, 1.20, 0],
                ['D', .10, .10, .12, 8.0, 0],
                ['A', .10, .10, .09, 8.0, 0],
            ]}
        fixtures.append(fixture)
    return {'meta':{'generated':'2026-11-05 12:45'}, 'fixtures':fixtures,
            'shortlist':{'primary':[{'fixture':str(i), 'sel':'O15'} for i in range(n)]}}


def test_1x2_checks_probability_price_freshness_and_existing_policy():
    data = snapshot()
    data['fixtures'][0]['sels'][1][1:5] = [.60,.60,.60,1.60]
    data['fixtures'][1]['sels'][1][1:5] = [.95,.95,.95,1.16]
    data['fixtures'][2]['sels'][1][1:5] = [.5999,.5999,.5999,1.65]
    data['fixtures'][3]['sels'][1][1:5] = [.9501,.9501,.9501,1.16]
    data['fixtures'][4]['sels'][1][4] = 1.159
    data['fixtures'][5]['sels'][1][4] = None
    data['fixtures'][6]['sels'][1][5] = 1
    data['fixtures'][7]['q'] = 'Low'
    data['fixtures'][8]['league'] = 'FA Cup'
    picks = x12.one_x_two_candidates(data, NOW)
    assert [p['fixture'] for p in picks] == ['1', '0']
    assert [p['probability'] for p in picks] == [.95, .60]
    assert all(p['sel'] == 'H' and p['selection'] == 'Home win (1)' for p in picks)
    with pytest.raises(ValueError, match='stale'):
        x12.one_x_two_candidates(data, NOW + timedelta(hours=2))


def test_draw_away_disagreement_unpriced_upcoming_and_distinct_prior():
    data = snapshot(8)
    data['fixtures'][0]['sels'] = [['A', .75, .75, .73, 1.3, 0]]
    data['fixtures'][1]['sels'] = [['D', .72, .72, .71, 1.4, 0]]
    data['fixtures'][2]['sels'][1] = ['H', .8, .8, .6, 1.3, 0] # outlier
    data['fixtures'][3]['kickoff'] = '2026-11-05 13:10'
    data['fixtures'][4]['sels'][1][4] = 1.16  # .80 * 1.16 < .95
    prior = [{'manifest':{'fixtures':[{'home':'Home 5','away':'Away 5','livescore_id':'event-5'}]}}]
    picks = x12.one_x_two_candidates(data, NOW, prior)
    assert {p['fixture'] for p in picks} == {'0','1','6','7'}
    assert {p['selection'] for p in picks} >= {'Away win (2)', 'Draw (X)'}


def test_matching_post_and_reel_use_five_to_six_real_crest_inputs(tmp_path, monkeypatch):
    source = tmp_path/'snapshot.json'; source.write_text(json.dumps(snapshot()))
    music = tmp_path/'music.mp3'; music.write_bytes(b'user music')
    crest = Image.new('RGBA', (60,60), 'teal')
    monkeypatch.setattr(fb, 'badge', lambda session, team, path: None if team.endswith('0') else crest)
    monkeypatch.setattr(reel, 'encode', lambda slides, music, output: output.write_bytes(b'video'))
    out = tmp_path/'out'
    assert x12.prepare(source, out, NOW, object(), music)
    info = x12.validate(out, NOW)
    assert len(info['fixtures']) == 6
    assert all(p['sel'] in ('H','D','A') and .60 <= p['probability'] <= .95 and p['odds'] >= 1.16 for p in info['fixtures'])
    assert all(not p['home'].endswith('0') for p in info['fixtures'])
    assert json.loads((out/'selections.json').read_text()) == json.loads((out/'selection-reel.json').read_text())
    hashtags = fb.caption_for(info)
    assert hashtags.split() and all(tag.startswith('#') for tag in hashtags.split())
    assert '#Home1' in hashtags and '#Away1' in hashtags
    bad = json.loads((out/'selection-reel.json').read_text()); bad['fixtures'][0]['probability'] = .59
    (out/'selection-reel.json').write_text(json.dumps(bad)); (out/'selections.json').write_text(json.dumps(bad))
    with pytest.raises(ValueError, match='invalid'):
        x12.validate(out, NOW)


def test_fewer_than_five_never_invents_picks_or_publishes(tmp_path, monkeypatch):
    source = tmp_path/'snapshot.json'; source.write_text(json.dumps(snapshot(4)))
    monkeypatch.setattr(fb, 'badge', lambda *args: Image.new('RGBA',(20,20),'teal'))
    assert not x12.prepare(source, tmp_path/'out', NOW, object())
    assert not (tmp_path/'out'/'selection-reel.mp4').exists()


def test_artwork_does_not_mention_model(tmp_path, monkeypatch):
    crest=Image.new('RGBA',(20,20),'teal')
    picks=x12.one_x_two_candidates(snapshot(), NOW)[:5]
    items=[{**p,'home_image':crest,'away_image':crest} for p in picks]
    texts=[]; original=ImageDraw.ImageDraw.text
    def capture(self, xy, text, *args, **kwargs):
        texts.append(text)
        return original(self, xy, text, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture)
    fb.render(items, tmp_path/'post.png')
    assert 'TODAY’S PREDICTIONS' in texts and not any('model' in t.lower() for t in texts)
    texts.clear(); reel.render_slide(items[0], 1, 5, '2026-11-05', tmp_path/'slide.png')
    assert not any('model' in t.lower() for t in texts)
    assert '18+' in texts and 'Home win (1)' in texts


def test_13_post_is_included_in_verified_daily_results():
    assert 'facebook-post-2026-11-05-13' in history.claim_names('2026-11-05')
    workflow = Path('.github/workflows/facebook-1x2.yml').read_text()
    assert "cron:" not in workflow
    assert 'if: ${{ false }}' in workflow
    assert 'facebook-1x2.yml' not in Path('.github/workflows/scan-30.yml').read_text()


def test_social_caption_contains_only_team_hashtags():
    fixtures=[{'home':f'Home {i}', 'away':f'Away {i}'} for i in range(5)]
    captions=[fb.caption_for({'date':f'2026-11-{d:02}', 'fixtures':fixtures}) for d in range(1,5)]
    expected = [f'#{name.replace(" ", "")}' for i in range(5) for name in (f'Home {i}', f'Away {i}')]
    assert all(caption.split() == expected for caption in captions)
    assert all(all(tag.startswith('#') for tag in caption.split()) for caption in captions)
