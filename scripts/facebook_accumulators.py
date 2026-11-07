#!/usr/bin/env python3
"""Three conservative morning accumulators, one album and one matching reel."""
from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import requests
import safe
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import facebook_post as fb
from scripts import selection_reel as reel


def _corner(code):
    return bool(re.fullmatch(r'C(?:[HA])?O\d+', str(code or '')))


def total(items):
    value = Decimal('1')
    for item in items:
        value *= Decimal(str(item['odds']))
    return value


def _find_group(pool, with_corner):
    # Selection order favours stronger checked probabilities. Search a bounded
    # number of candidates, avoiding correlated markets from the same match.
    goals = [x for x in pool if x['sel'] == 'O15'][:32]
    corners = [x for x in pool if _corner(x['sel'])][:8]
    starts = [[x] for x in corners] if with_corner else [[]]
    for start in starts:
        for count in range(1 if start else 2, 8 - len(start) + 1):
            for group in itertools.combinations(goals, count):
                picks = start + list(group)
                if len(picks) > 8 or sum(x['sel'] == 'O15' for x in picks) <= len(picks) / 2:
                    continue
                if len({x['fixture'] for x in picks}) != len(picks):
                    continue
                price = total(picks)
                if Decimal('2.50') <= price <= Decimal('3.00'):
                    return picks
    return None


def choose_groups(picks):
    remaining = list(picks)
    result = []
    for _ in range(3):
        group = _find_group(remaining, True) or _find_group(remaining, False)
        if not group:
            return []
        result.append(group)
        used = {x['fixture'] for x in group}
        remaining = [x for x in remaining if x['fixture'] not in used]
    return result


def _picture_path(output, index):
    return Path(output) / f'accumulator-{index}.png'


def _slide(picture, index, output):
    # Leave space for the rotating brand disc and social overlays.
    im = Image.new('RGB', (1080, 1920), 'white')
    draw = ImageDraw.Draw(im)
    draw.ellipse((95,135,285,325),fill='#eff6f4',outline='#c2ddd7',width=3)
    draw.text((320,180),f'ACCUMULATOR {index}',font=fb.font(37,True),fill='#102c3f')
    draw.text((320,245),'TODAY’S PREDICTIONS',font=fb.font(24,True),fill='#35736a')
    fb.draw_age_badge(draw,(874,175,968,235))
    card = Image.open(picture).convert('RGB').resize((864,1536), Image.Resampling.LANCZOS)
    im.paste(card,(108,330))
    im.save(output,'PNG')


def render_accumulator(items, path, index):
    # Render with the common picture layout, allowing smaller groups than the
    # old single-card minimum. Total is computed from the exact quoted prices.
    fb.render(items, path, minimum=2, heading=f'ACCUMULATOR {index}',
              subheading=f"TOTAL ODDS {total(items):.2f}")


def validate(info, now=None):
    now = (now or datetime.now(fb.SAST)).astimezone(fb.SAST)
    if info.get('series') != 'accumulators' or info.get('date') != now.date().isoformat():
        raise ValueError('Not today’s accumulator manifest')
    generated = datetime.strptime(info['generated'], '%Y-%m-%d %H:%M').replace(tzinfo=fb.SAST)
    if not timedelta(minutes=-5) <= now-generated <= timedelta(minutes=90):
        raise ValueError('Accumulator prices are stale')
    groups = info.get('accumulators') or []
    if len(groups) != 3:
        raise ValueError('Exactly three accumulators are required')
    flat = []
    for group in groups:
        items = group.get('fixtures') or []
        if not 2 <= len(items) <= 8 or sum(x.get('sel') == 'O15' for x in items) <= len(items)/2:
            raise ValueError('Each accumulator must mostly contain over 1.5 goals')
        if any(x.get('sel') != 'O15' and not _corner(x.get('sel')) for x in items):
            raise ValueError('Unexpected accumulator market')
        for x in items:
            odds, probability = fb.number(x.get('odds')), fb.number(x.get('probability'))
            floor = .70 if x.get('sel') == 'O15' else .65
            if (odds is None or not fb.policy.PRICE_FLOOR <= odds <= 1.90 or probability is None or not floor <= probability < 1 or probability * odds < .95 or
                x.get('selection') != safe.label(x.get('sel'),x.get('home'),x.get('away')) or
                not fb.competition_policy.allowed(country=x.get('country'),league=x.get('league'),home=x.get('home'),away=x.get('away')) or
                datetime.strptime(x['kickoff'], '%Y-%m-%d %H:%M').replace(tzinfo=fb.SAST) <= now+timedelta(minutes=5)):
                raise ValueError('Invalid or expired accumulator selection')
        price = total(items)
        if not Decimal('2.50') <= price <= Decimal('3.00') or group.get('total_odds') != f'{price:.2f}':
            raise ValueError('Accumulator total must be between 2.50 and 3.00')
        flat.extend(items)
    if len({x['fixture'] for x in flat}) != len(flat) or info.get('fixtures') != flat:
        raise ValueError('Duplicate or inconsistent accumulator selections')
    return info


def caption(info):
    if info.get('series') == 'stats-watch':
        from scripts import stats_watch_assets
        return stats_watch_assets.caption(info)
    fixtures = info['fixtures']
    tags, seen = [], set()
    import unicodedata
    for item in fixtures:
        for name in (item['home'], item['away']):
            tag = ''.join(c for c in unicodedata.normalize('NFKC',name) if c.isalnum() or c == '_')
            if tag and tag.casefold() not in seen:
                tags.append('#'+tag); seen.add(tag.casefold())
    day = datetime.strptime(info['date'],'%Y-%m-%d')
    text = (f"Morning predictions · {day.day} {day.strftime('%B %Y')} ⚽\n\n"
            "Three accumulators: mostly over 1.5 goals, with corners where available.\n"
            "Which one are you following?\nOdds from SportyBet; odds can change.\n"
            "18+ | Bet responsibly.\n\n" + ' '.join(tags))
    if len(text) > 1000:
        raise ValueError('Caption too long for Telegram')
    return text


def prepare(snapshot, output, now=None, music=None):
    now = (now or datetime.now(fb.SAST)).astimezone(fb.SAST)
    data = json.loads(Path(snapshot).read_text(encoding='utf-8'))
    refs = []
    for fixture in data.get('fixtures', []):
        if not isinstance(fixture,dict): continue
        sels = fixture.get('sels') or []
        for code in sorted({s[0] for s in sels if isinstance(s,list) and s and (s[0]=='O15' or _corner(s[0]))},key=lambda c: (c!='O15', c)):
            refs.append({'fixture':fixture.get('id'),'sel':code})
    candidates = fb.candidates(data, now, refs)
    # Give the album and reel enough time to render and publish before kickoff.
    candidates = [x for x in candidates if datetime.strptime(x['kickoff'],'%Y-%m-%d %H:%M').replace(tzinfo=fb.SAST)>now+timedelta(minutes=45)]
    candidates.sort(key=lambda x: (-x['probability'], x['kickoff'], x['fixture']))
    candidates = [x for x in candidates if x['sel']=='O15'][:40] + [x for x in candidates if _corner(x['sel'])][:10]
    def with_crests(item):
        with requests.Session() as session:
            home=fb.badge(session,item['home'],item['badges'].get('home'))
            away=fb.badge(session,item['away'],item['badges'].get('away'))
        return {**item,'home_image':home,'away_image':away} if home is not None and away is not None else None
    with ThreadPoolExecutor(max_workers=6) as executor:
        complete = [x for x in executor.map(with_crests, candidates) if x is not None]
    groups = choose_groups(complete)
    if not groups:
        print('Fewer than three qualifying accumulators: preparing a verified Stats Watch instead.')
        from scripts import stats_watch_assets
        return stats_watch_assets.prepare(Path(output),now=now,music=music)
    output = Path(output); output.mkdir(parents=True,exist_ok=True)
    fields = ('fixture','kickoff','country','league','home','away','sel','selection','odds','probability','livescore_id','badges')
    accs = [{'total_odds':f'{total(group):.2f}','fixtures':[{k:item[k] for k in fields} for item in group]} for group in groups]
    info = {'date':now.date().isoformat(),'generated':data['meta']['generated'],'series':'accumulators',
            'accumulators':accs,'fixtures':[x for g in accs for x in g['fixtures']]}
    validate(info,now); caption(info)
    with tempfile.TemporaryDirectory() as td:
        temp = Path(td); slides=[]
        for i, group in enumerate(groups,1):
            picture = _picture_path(output,i); render_accumulator(group,picture,i)
            slide = temp/f'slide-{i}.png'; _slide(picture,i,slide); slides.append(slide)
        if music is None:
            music=temp/'music.mp3'; reel.download_music(music)
        reel.encode(slides,music,output/'selection-reel.mp4')
    for name in ('selections.json','selection-reel.json'):
        (output/name).write_text(json.dumps(info,ensure_ascii=False),encoding='utf-8')
    for i,group in enumerate(accs,1):
        print(f"::notice::Accumulator {i}: {len(group['fixtures'])} selections, total odds {group['total_odds']}")
    print('Prepared three accumulator pictures and one matching reel.')
    return True


def publish(output, now=None, session=None):
    output=Path(output); info=json.loads((output/'selections.json').read_text(encoding='utf-8'))
    if info.get('series') == 'stats-watch':
        from scripts import stats_watch_assets
        stats_watch_assets.validate_manifest(info, now)
        pictures=[output/'selections.png']
    else:
        validate(info,now); pictures=[_picture_path(output,i) for i in (1,2,3)]
    text=caption(info)
    token,page_id=fb.credentials();session=session or requests.Session();token,_=fb.resolve_page_token(session,token,page_id)
    try:
        ids=[]
        for picture in pictures:
            with picture.open('rb') as image:
                response=session.post(f'https://graph.facebook.com/v24.0/{page_id}/photos',data={'access_token':token,'published':'false'},files={'source':(picture.name,image,'image/png')},timeout=60)
            if not response.ok: raise RuntimeError('Facebook rejected an unpublished picture: '+fb.error_summary(response))
            pid=response.json().get('id')
            if not pid: raise RuntimeError('Unconfirmed picture upload; check Page before recovery')
            ids.append(str(pid))
        data={'access_token':token,'message':text}
        data.update({f'attached_media[{i}]':json.dumps({'media_fbid':pid}) for i,pid in enumerate(ids)})
        response=session.post(f'https://graph.facebook.com/v24.0/{page_id}/feed',data=data,timeout=60)
        if not response.ok: raise RuntimeError('Facebook rejected the album: '+fb.error_summary(response))
        if not response.json().get('id'): raise RuntimeError('Unconfirmed album post; check Page before recovery')
    except requests.RequestException:
        raise RuntimeError('Album upload result unknown; check Page before recovery') from None
    print('Facebook confirmed the morning picture post.')


def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--snapshot',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    pub=sub.add_parser('publish');pub.add_argument('--output',type=Path,required=True)
    val=sub.add_parser('validate');val.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.cmd=='prepare':
        ready=prepare(a.snapshot,a.output)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as out:out.write(f'ready={str(ready).lower()}\n')
    elif a.cmd=='publish': publish(a.output)
    else:
        _, info = reel.validate_prepared(a.output)
        if json.loads((a.output/'selections.json').read_text(encoding='utf-8')) != info:
            raise ValueError('Picture and reel selections do not match')
        pictures = [a.output/'selections.png'] if info.get('series') == 'stats-watch' else [_picture_path(a.output,i) for i in (1,2,3)]
        if any(not path.is_file() or not path.stat().st_size for path in pictures):
            raise ValueError('A picture is missing')
        caption(info)

if __name__=='__main__':
    try: main()
    except (ValueError,OSError,RuntimeError) as exc:
        print(f'::error::{exc}',file=sys.stderr);sys.exit(1)
