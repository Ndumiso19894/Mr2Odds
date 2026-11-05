"""Render and validate a factual stats-watch picture and two-teams-per-slide reel."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageOps

from scripts import facebook_post as fb
from scripts import selection_reel as reel
from scripts import stats_watch


def caption(info):
    rows = info.get('rows') or []
    if not 1 <= len(rows) <= 10:
        raise ValueError('Invalid stats-watch caption')
    tags, seen = [], set()
    import unicodedata
    for row in rows:
        for name in (row['home'], row['away']):
            tag = ''.join(c for c in unicodedata.normalize('NFKC', name) if c.isalnum() or c == '_')
            if not tag:
                raise ValueError('Invalid club name')
            if tag.casefold() not in seen:
                tags.append('#'+tag)
                seen.add(tag.casefold())
    return ('Stats Watch: unbeaten league runs ⚽\n\n'
            'These teams are in their league’s top two and unbeaten in recent league play. '
            'Which run impresses you most?\n'
            'Standings and fixtures: ESPN. Times shown in SAST.\n'
            '18+ | Bet responsibly.\n\n' + ' '.join(tags))


def validate_manifest(info, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if info.get('series') != 'stats-watch' or info.get('fixtures') != []:
        raise ValueError('Not a stats-watch manifest')
    generated = stats_watch._utc(info.get('as_of'))
    if not timedelta(minutes=-5) <= now - generated <= timedelta(minutes=90):
        raise ValueError('Stats-watch source is stale')
    if info.get('date') != now.astimezone(fb.SAST).date().isoformat():
        raise ValueError('Stats-watch source is not for today')
    rows = info.get('rows') or []
    if not 1 <= len(rows) <= 10 or len({r.get('team_id') for r in rows}) != len(rows):
        raise ValueError('Stats-watch needs distinct teams')
    for r in rows:
        code = r.get('league_code')
        if (code not in stats_watch.LEAGUES or r.get('country') != stats_watch.LEAGUES[code]
            or r.get('rank') not in (1, 2) or not isinstance(r.get('played'), int)
            or r['played'] < 6 or r['played'] > 60 or not isinstance(r.get('streak'), int) or not 6 <= r['streak'] <= r['played'] or not isinstance(r.get('losses'), int) or r['losses'] < 0 or not isinstance(r.get('wins'), int)
            or not isinstance(r.get('draws'), int) or r['wins'] + r['draws'] + r['losses'] != r['played']
            or r.get('record') != f"{r['wins']}-{r['draws']}-{r['losses']}"
            or r.get('table_url') != stats_watch.STANDINGS.format(code)
            or r.get('schedule_url') != stats_watch.SCHEDULE.format('all',r.get('team_id')) + '?fixture=true'
            or r.get('team_id') not in (r.get('home_id'), r.get('away_id'))
            or (r.get('team') != r.get('home') and r.get('team') != r.get('away'))
            or not all(str(r.get(k) or '').isdigit() for k in ('team_id','home_id','away_id','event_id'))
            or not all(isinstance(r.get(k), str) and r[k] for k in ('league','competition','home','away'))
            or stats_watch._utc(r.get('kickoff_utc')) <= now + timedelta(minutes=5)
            or not stats_watch.competition_policy.allowed(country=r['country'], league=r['competition'], home=r['home'], away=r['away'])):
            raise ValueError('Invalid or expired stats-watch evidence')
        if r.get('season') not in (generated.year, generated.year-1) or (r['season'] == generated.year-1 and generated.month >= 8):
            raise ValueError('Stats-watch season is stale')
        if min(r['wins'], r['draws']) < 0:
            raise ValueError('Negative record counts')
        proof = r.get('results_proof')
        if r['losses'] == 0:
            if r['streak'] != r['played'] or proof != []:
                raise ValueError('Invalid unbeaten-season evidence')
        else:
            if not isinstance(proof,list) or len(proof) != r['played']:
                raise ValueError('Missing result evidence')
            ids, last_date, streak = set(), None, 0
            counting = True
            counts = {'W':0,'D':0,'L':0}
            for match in proof:
                if not isinstance(match,dict) or match.get('outcome') not in counts or not str(match.get('event_id') or '').isdigit():
                    raise ValueError('Invalid result evidence')
                when = stats_watch._utc(match.get('date'))
                if when > generated or (last_date is not None and when > last_date) or match['event_id'] in ids:
                    raise ValueError('Unordered or duplicate result evidence')
                last_date = when
                ids.add(match['event_id'])
                outcome = match['outcome']
                counts[outcome] += 1
                if outcome == 'L':
                    counting = False
                elif counting:
                    streak += 1
            if (counts != {'W':r['wins'],'D':r['draws'],'L':r['losses']} or streak != r['streak']):
                raise ValueError('Result evidence does not match the league record')
    if len(caption(info)) > 1024:
        raise ValueError('Stats-watch caption exceeds Telegram limits')
    return info


def _crest(row, side, session):
    team_id = row[f'{side}_id']
    if not str(team_id).isdigit():
        return None
    return fb.image_from_url(session, f'https://a.espncdn.com/i/teamlogos/soccer/500/{team_id}.png')


def _kickoff(r):
    dt = stats_watch._utc(r['kickoff_utc']).astimezone(fb.SAST)
    return f"{dt.day} {dt.strftime('%b')} · {dt.strftime('%H:%M')} SAST"


def _paste_crest(image, crest, center, size):
    crest = ImageOps.contain(crest, (size,size), Image.Resampling.LANCZOS)
    image.paste(crest, (center[0] - crest.width//2, center[1] - crest.height//2), crest)


def render_picture(rows, now, path):
    image = Image.new('RGB', (1080,1920), 'white')
    draw = ImageDraw.Draw(image)
    logo = Image.open(fb.ROOT/'android/design/mr-2-odds-logo.png').convert('RGBA')
    logo.thumbnail((180,180), Image.Resampling.LANCZOS)
    image.paste(logo, (40,24), logo)
    draw.text((250,60), 'STATS WATCH', font=fb.font(48,True), fill='#122b3d')
    draw.text((250,130), 'TOP TWO · UNBEATEN IN THE LEAGUE', font=fb.font(23,True), fill='#35736a')
    fb.draw_age_badge(draw, (930,65,1030,125))
    start, bottom, gap = 225, 1815, 10
    height = (bottom - start - gap*(len(rows)-1)) // len(rows)
    for i,r in enumerate(rows):
        y = start+i*(height+gap)
        draw.rounded_rectangle((35,y,1045,y+height), radius=16, fill='#f3f7f6', outline='#b3c8c4', width=2)
        top = f"{r['team']}  ·  #{r['rank']} {r['country']} · {r['league']}"
        draw.text((55,y+height*.20), top, font=fb.fit(draw,top,790,25,minimum=17,bold=True), fill='#244c49',anchor='lm')
        stat = f"{r['streak']} unbeaten"
        draw.text((1020,y+height*.20),stat,font=fb.font(22,True),fill='#007f72',anchor='rm')
        _paste_crest(image,r['home_image'],(88,int(y+height*.61)),45)
        _paste_crest(image,r['away_image'],(992,int(y+height*.61)),45)
        fb.draw_team(draw,r['home'],128,y+height*.61,'lm',max_size=25,line_spacing=25)
        fb.draw_team(draw,r['away'],951,y+height*.61,'rm',max_size=25,line_spacing=25)
        draw.text((540,y+height*.61),'v',font=fb.font(22,True),fill='#52716f',anchor='mm')
        meta = 'NEXT LISTED: ' + r['competition'] + ' · ' + _kickoff(r)
        draw.text((540,y+height*.87),meta,font=fb.fit(draw,meta,850,19,minimum=14),fill='#4b716b',anchor='mm')
    footer = 'Source: ESPN  ·  league records as of ' + now.astimezone(fb.SAST).strftime('%d %b %Y %H:%M SAST')
    draw.text((540,1860),footer,font=fb.fit(draw,footer,1000,22,minimum=16),fill='#52716b',anchor='mm')
    image.save(path, 'PNG', optimize=True)


def render_slide(rows, page, count, now, path):
    image = Image.new('RGB',(1080,1920),'white')
    draw = ImageDraw.Draw(image)
    draw.text((320,155),'STATS WATCH',font=fb.font(42,True),fill='#122b3d')
    draw.text((320,225),'TOP TWO · LEAGUE FORM',font=fb.font(25,True),fill='#35736a')
    fb.draw_age_badge(draw,(874,175,968,235))
    for index,r in enumerate(rows):
        y = 360 + index*605
        draw.rounded_rectangle((80,y,1000,y+550),radius=34,fill='#f7faf9',outline='#c8dcd8',width=3)
        title = f"{r['team']}  ·  #{r['rank']}"
        draw.text((540,y+53),title,font=fb.fit(draw,title,800,37,minimum=22,bold=True),fill='#122b3d',anchor='mm')
        league = f"{r['country']} · {r['league']}"
        draw.text((540,y+105),league,font=fb.fit(draw,league,800,25,minimum=18,bold=True),fill='#476b65',anchor='mm')
        label = f"{r['streak']} LEAGUE MATCHES UNBEATEN"
        draw.text((540,y+160),label,font=fb.fit(draw,label,800,27,minimum=20,bold=True),fill='#007f72',anchor='mm')
        _paste_crest(image,r['home_image'],(265,y+285),115)
        _paste_crest(image,r['away_image'],(815,y+285),115)
        fb.draw_team(draw,r['home'],265,y+390,'mm',max_size=29,line_spacing=31)
        fb.draw_team(draw,r['away'],815,y+390,'mm',max_size=29,line_spacing=31)
        draw.text((540,y+285),'VS',font=fb.font(27,True),fill='#7a9893',anchor='mm')
        fixture = 'NEXT LISTED: ' + r['competition']
        draw.text((540,y+455),fixture,font=fb.fit(draw,fixture,800,24,minimum=17,bold=True),fill='#355b58',anchor='mm')
        draw.text((540,y+505),_kickoff(r),font=fb.font(25,True),fill='#245f56',anchor='mm')
    draw.text((540,1650),f'{page:02d} / {count:02d}',font=fb.font(24,True),fill='#52716b',anchor='mm')
    footer = 'Source: ESPN · ' + now.astimezone(fb.SAST).strftime('%d %b %Y %H:%M SAST')
    draw.text((540,1710),footer,font=fb.font(22,True),fill='#52716b',anchor='mm')
    image.save(path,'PNG')


def prepare(output, now=None, music=None, session=None, minimum=1, include_video=True, image_path=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = stats_watch.collect(now, limit=30)
    session = session or requests.Session()
    complete = []
    for row in rows:
        home, away = _crest(row,'home',session), _crest(row,'away',session)
        if home is not None and away is not None:
            complete.append({**row,'home_image':home,'away_image':away})
        if len(complete) == 10:
            break
    if len(complete) < minimum:
        raise ValueError(f'Only {len(complete)} teams could be independently verified with both crests; {minimum} required')
    output.mkdir(parents=True,exist_ok=True)
    image_path = Path(image_path) if image_path else output/'selections.png'
    if include_video and image_path != output/'selections.png':
        raise ValueError('Matched reel assets require the standard picture path')
    image_path.parent.mkdir(parents=True, exist_ok=True)
    info = {'date':now.astimezone(fb.SAST).date().isoformat(), 'as_of':now.isoformat(),
            'generated':now.astimezone(fb.SAST).strftime('%Y-%m-%d %H:%M'), 'series':'stats-watch', 'fixtures':[],
            'rows':[{k:v for k,v in row.items() if not k.endswith('_image')} for row in complete]}
    validate_manifest(info,now)
    for row in info['rows']:
        print(f"::notice::{row['team']} | {row['league']} #{row['rank']} | {row['streak']} unbeaten league matches | {row['home']} v {row['away']} | {row['kickoff_utc']}")
    with tempfile.TemporaryDirectory() as td:
        temp = Path(td)
        render_picture(complete,now,image_path)
        if include_video:
            if music is None:
                music = temp/'music.mp3'
                reel.download_music(music,session)
            slides = []
            count = (len(complete)+1)//2
            for i in range(count):
                path = temp/f'{i:02}.png'
                render_slide(complete[2*i:2*i+2],i+1,count,now,path)
                slides.append(path)
            reel.encode(slides,music,output/'selection-reel.mp4')
    image_path.with_suffix('.json').write_text(json.dumps(info,ensure_ascii=False),encoding='utf-8')
    if include_video:
        (output/'selection-reel.json').write_text(json.dumps(info,ensure_ascii=False),encoding='utf-8')
    print(f'Prepared stats-watch picture and reel with {len(complete)} verified teams.')
    return True
