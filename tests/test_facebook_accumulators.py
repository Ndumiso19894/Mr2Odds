from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json
from unittest.mock import Mock

import pytest
from PIL import Image
from scripts import facebook_accumulators as acc, facebook_post as fb, selection_reel

NOW = datetime(2026,11,7,7,0,tzinfo=fb.SAST)


def pick(i, sel='O15', odds=1.30):
    return {'fixture':str(i),'home':f'Home {i}','away':f'Away {i}','country':'England','league':'Premier League',
            'kickoff':'2026-11-07 15:00','sel':sel,'selection': 'Over 1.5 goals' if sel == 'O15' else 'Home '+str(i)+' over 3.5 corners',
            'odds':odds,'probability':.85,'badges':{'home':'enet/1.png','away':'enet/2.png'},'livescore_id':str(i)}


def make_info():
    groups=[]
    for g in range(3):
        items=[pick(g*4+i) for i in range(4)]
        groups.append({'fixtures':items,'total_odds':f'{acc.total(items):.2f}'})
    return {'series':'accumulators','date':'2026-11-07','generated':'2026-11-07 06:55','accumulators':groups,
            'fixtures':[i for g in groups for i in g['fixtures']]}


def test_builds_three_disjoint_majority_goals_accumulators():
    pool=[pick(i) for i in range(20)]
    groups=acc.choose_groups(pool)
    assert len(groups)==3
    assert len({x['fixture'] for group in groups for x in group})==sum(len(group) for group in groups)
    assert all(Decimal('2.50')<=acc.total(group)<=Decimal('3.00') for group in groups)
    assert not acc.choose_groups(pool[:5])


def test_validate_market_total_expiry_and_flat_list():
    info=make_info();acc.validate(info,NOW)
    assert 'Odds from SportyBet' in acc.caption(info) and 'model' not in acc.caption(info).lower()
    for change in ('market','total','kickoff','duplicate','price'):
        bad=deepcopy(info)
        if change=='market': bad['accumulators'][0]['fixtures'][0]['sel']='H'
        if change=='total': bad['accumulators'][0]['total_odds']='3.01'
        if change=='kickoff': bad['accumulators'][0]['fixtures'][0]['kickoff']='2026-11-07 07:01'
        if change=='duplicate': bad['accumulators'][0]['fixtures'][0]['fixture']=bad['accumulators'][0]['fixtures'][1]['fixture']
        if change=='price': bad['accumulators'][0]['fixtures'][0]['odds']=1.01
        with pytest.raises(ValueError):acc.validate(bad,NOW)


def test_album_uploads_three_images_as_one_post(tmp_path,monkeypatch):
    info=make_info()
    (tmp_path/'selections.json').write_text(json.dumps(info))
    for i in range(1,4):(tmp_path/f'accumulator-{i}.png').write_bytes(b'png')
    monkeypatch.setenv('FACEBOOK_PAGE_ACCESS_TOKEN','fake')
    monkeypatch.setenv('FACEBOOK_PAGE_ID','123')
    session=Mock();session.get.return_value=Mock(ok=True,json=Mock(return_value={'id':'123'}))
    session.post.side_effect=[Mock(ok=True,json=Mock(return_value={'id':str(i)})) for i in (1,2,3,4)]
    acc.publish(tmp_path,NOW,session)
    assert session.post.call_count==4
    assert all(c.kwargs['data']['published']=='false' for c in session.post.call_args_list[:3])
    feed=session.post.call_args_list[-1]
    assert feed.args[0].endswith('/feed') and len([x for x in feed.kwargs['data'] if x.startswith('attached_media[')])==3
    assert 'Odds from SportyBet' in feed.kwargs['data']['message']


def test_picture_and_reel_share_prediction_manifest(tmp_path):
    info=make_info();acc.validate(info,NOW)
    (tmp_path/'selection-reel.mp4').write_bytes(b'fake')
    (tmp_path/'selection-reel.json').write_text(json.dumps(info))
    video,got=selection_reel.validate_prepared(tmp_path,NOW)
    assert got==info and video.is_file()
    crest=Image.new('RGBA',(30,30),'teal')
    rows=[{**p,'home_image':crest,'away_image':crest} for p in info['accumulators'][0]['fixtures']]
    acc.render_accumulator(rows,tmp_path/'photo.png',1)
    assert Image.open(tmp_path/'photo.png').size==(1080,1920)
    acc._slide(tmp_path/'photo.png',1,tmp_path/'slide.png','2.85')
    assert Image.open(tmp_path/'slide.png').size==(1080,1920)


def test_end_to_end_prepares_three_cards_and_one_shared_reel(tmp_path, monkeypatch):
    fixtures=[]
    for i in range(16):
        x=pick(i)
        fixtures.append({'id':x['fixture'],'home':x['home'],'away':x['away'],'country':x['country'],'league':x['league'],
                         'date':'2026-11-07','kickoff':x['kickoff'],'time_known':True,'data_ok':True,'q':'High',
                         'badges':x['badges'],'sels':[['O15',.85,.85,.85,1.30,0]]})
    source=tmp_path/'data.json';source.write_text(json.dumps({'meta':{'generated':'2026-11-07 06:55'},'fixtures':fixtures}))
    monkeypatch.setattr(fb,'badge',lambda *args:Image.new('RGBA',(30,30),'teal'))
    def encode(slides,music,output):
        assert len(slides)==3
        assert all(Image.open(x).size == (1080,1920) for x in slides)
        output.write_bytes(b'video')
    monkeypatch.setattr(selection_reel,'encode',encode)
    track=tmp_path/'music.mp3';track.write_bytes(b'music')
    output=tmp_path/'output';assert acc.prepare(source,output,NOW,music=track)
    info=json.loads((output/'selections.json').read_text());assert info==json.loads((output/'selection-reel.json').read_text())
    assert len(info['accumulators'])==3 and len(info['fixtures'])==12
    assert all((output/f'accumulator-{i}.png').is_file() for i in (1,2,3))
    selection_reel.validate_prepared(output,NOW)
