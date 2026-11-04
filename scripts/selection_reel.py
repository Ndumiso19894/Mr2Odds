#!/usr/bin/env python3
"""Create a morning 9:16 shortlist reel and deliver it without unsafe retries."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import facebook_post as fb

# Digest of the supplied track. The Drive file ID is configured separately as an
# Actions secret, not embedded in this public repository.
MUSIC_SHA256 = 'ec242d687e52716fda5ff0a0cd9877ddaff45052251cdc27f36db57cd4b2c4b8'
MAX_MUSIC_BYTES = 20 * 1024 * 1024
MAX_VIDEO_BYTES = 49 * 1024 * 1024  # below Telegram's hosted Bot API limit
SLIDE_SECONDS = 7
FPS = 25


def download_music(path, session=None):
    file_id = os.environ.get('REEL_MUSIC_FILE_ID', '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,200}', file_id):
        raise ValueError('Configure the REEL_MUSIC_FILE_ID Actions secret with the supplied music file ID')
    session = session or requests.Session()
    try:
        response = session.get('https://drive.google.com/uc', params={'export':'download', 'id':file_id},
                               stream=True, timeout=60, allow_redirects=True)
        response.raise_for_status()
        size, digest = 0, hashlib.sha256()
        with path.open('wb') as out:
            for block in response.iter_content(65536):
                size += len(block)
                if size > MAX_MUSIC_BYTES:
                    raise ValueError('The music file exceeds the size limit')
                digest.update(block)
                out.write(block)
        if not size or digest.hexdigest() != MUSIC_SHA256:
            raise ValueError('The music download is unavailable or does not match the supplied track')
    except requests.RequestException:
        raise RuntimeError('Could not download the music; check its Drive link access') from None


def make_logo_disc(logo_path=fb.ROOT / 'android/design/mr-2-odds-logo.png', size=180):
    """Crop the supplied circular artwork, with transparent corners for rotation."""
    logo = Image.open(logo_path).convert('RGBA')
    # The supplied logo contains a centered disc surrounded by a dark square.
    width, height = logo.size
    disc = logo.crop((round(width * .145), round(height * .145),
                      round(width * .855), round(height * .855)))
    disc = ImageOps.fit(disc, (size * 3, size * 3), Image.Resampling.LANCZOS)
    mask = Image.new('L', disc.size, 0)
    ImageDraw.Draw(mask).ellipse((1, 1, disc.width - 2, disc.height - 2), fill=255)
    from PIL import ImageChops
    disc.putalpha(ImageChops.multiply(disc.getchannel('A'), mask))
    return disc.resize((size, size), Image.Resampling.LANCZOS)


def draw_centered_team(draw, name, x, center_y):
    """Fit a complete club name in one or two lines below its crest."""
    words = name.split()
    splits = [(name,)] + [(' '.join(words[:i]), ' '.join(words[i:])) for i in range(1, len(words))]
    for size in range(38, 21, -1):
        font = fb.font(size, True)
        options = [lines for lines in splits if all(draw.textbbox((0, 0), t, font=font)[2] <= 365 for t in lines)]
        if options:
            lines = min(options, key=lambda v: (len(v), max(draw.textbbox((0, 0), t, font=font)[2] for t in v)))
            for i, text in enumerate(lines):
                y = center_y + (i - (len(lines) - 1) / 2) * 43
                draw.text((x, y), text, font=font, fill='#152c3d', anchor='mm')
            return
    raise ValueError('A team name is too long to display safely')


def render_slide(item, index, count, day, out):
    # Keep all useful content inside the central 9:16 safe area for social overlays.
    image = Image.new('RGB', (1080, 1920), '#ffffff')
    draw = ImageDraw.Draw(image)
    # The animated logo is overlaid during encoding; this ring anchors its position.
    draw.ellipse((95, 135, 285, 325), fill='#eff6f4', outline='#c2ddd7', width=3)
    draw.text((310, 180), 'BET ADVISOR', font=fb.font(45, True), fill='#102c3f')
    draw.text((312, 250), 'TODAY’S SELECTIONS', font=fb.font(26, True), fill='#35736a')
    draw.rounded_rectangle((874, 175, 968, 235), radius=18, fill='#ffffff', outline='#8faca8', width=3)
    draw.text((921, 205), '18+', font=fb.font(27, True), fill='#274c49', anchor='mm')

    # Gentle shadow and a high-contrast, uncluttered white match card.
    draw.rounded_rectangle((99, 378, 991, 1568), radius=35, fill='#edf3f1')
    draw.rounded_rectangle((90, 365, 990, 1555), radius=35, fill='#fafcfb', outline='#c8dcd8', width=3)
    competition = item['country'] + '  ·  ' + item['league']
    cf = fb.fit(draw, competition, 805, 30, minimum=21, bold=True)
    draw.text((540, 430), competition, font=cf, fill='#355b58', anchor='mm')
    kick = datetime.strptime(item['kickoff'], '%Y-%m-%d %H:%M').strftime('%H:%M')
    draw.rounded_rectangle((433, 480, 647, 532), radius=20, fill='#e8f2ef')
    draw.text((540, 506), kick + ' SAST', font=fb.font(25, True), fill='#235c53', anchor='mm')
    for side, cx in (('home_image', 300), ('away_image', 780)):
        draw.ellipse((cx - 135, 600, cx + 135, 870), fill='#ffffff', outline='#d5e4e1', width=3)
        crest = ImageOps.contain(item[side], (208, 208), Image.Resampling.LANCZOS)
        image.paste(crest, (cx - crest.width // 2, 735 - crest.height // 2), crest)
    draw_centered_team(draw, item['home'], 300, 937)
    draw_centered_team(draw, item['away'], 780, 937)
    draw.text((540, 735), 'VS', font=fb.font(28, True), fill='#7a9893', anchor='mm')
    draw.line((150, 1018, 930, 1018), fill='#d4e4df', width=3)
    draw.text((540, 1090), 'SELECTION', font=fb.font(24, True), fill='#48736c', anchor='mm')
    sf = fb.fit(draw, item['selection'], 785, 43, minimum=25, bold=True)
    draw.text((540, 1170), item['selection'], font=sf, fill='#102c3f', anchor='mm')
    draw.rounded_rectangle((395, 1255, 685, 1355), radius=22, fill='#008878')
    draw.text((540, 1305), f"{item['odds']:.2f}", font=fb.font(48, True), fill='white', anchor='mm')
    draw.text((540, 1468), f'{index:02d}  /  {count:02d}', font=fb.font(25, True), fill='#52716b', anchor='mm')
    date = datetime.strptime(day, '%Y-%m-%d')
    draw.text((540, 1645), f'{date.day} {date.strftime("%B %Y")}', font=fb.font(26, True), fill='#52716b', anchor='mm')
    image.save(out, 'PNG')


def encode(slides, music, output):
    """H.264/AAC, 25 fps, 9:16, with a continuously rotating brand disc."""
    import imageio_ffmpeg
    if not slides or not music.is_file():
        raise ValueError('Missing reel slides or music')
    with tempfile.TemporaryDirectory() as td:
        listing = Path(td)/'slides.txt'
        # All slide names are generated by this script, not supplied externally.
        lines = []
        for slide in slides:
            lines.extend([f"file '{str(slide.resolve()).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'", f'duration {SLIDE_SECONDS}'])
        lines.append(f"file '{str(slides[-1].resolve()).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'")
        listing.write_text('\n'.join(lines)+'\n', encoding='utf-8')
        duration = SLIDE_SECONDS * len(slides)
        logo = Path(td) / 'brand-disc.png'
        make_logo_disc().save(logo)
        # Only the brand disc rotates. The match card and both club crests remain
        # visible and stationary for the entire slide, with no transition blackout.
        filters = (f'[0:v]fps={FPS},format=yuv420p[base];'
                   '[2:v]format=rgba,rotate=angle=2*PI*t/10:ow=iw:oh=ih:c=none[disc];'
                   '[base][disc]overlay=100:140:shortest=1,format=yuv420p[video]')
        args = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y',
                '-f','concat','-safe','0','-i',str(listing), '-stream_loop','-1','-i',str(music),
                '-loop','1','-framerate',str(FPS),'-i',str(logo),
                '-t',str(duration),'-filter_complex',filters,'-map','[video]','-map','1:a:0',
                '-af',f'afade=t=in:st=0:d=1,afade=t=out:st={duration-1}:d=1',
                '-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p',
                '-r',str(FPS),'-c:a','aac','-b:a','128k','-ar','48000','-movflags','+faststart',str(output)]
        try:
            subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=600)
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError('Could not render the selection reel') from None
    if not output.is_file() or not 0 < output.stat().st_size <= MAX_VIDEO_BYTES:
        raise ValueError('Rendered reel is empty or too large for Telegram')


def prepare(snapshot, output, now=None, session=None, music=None):
    now = (now or datetime.now(fb.SAST)).astimezone(fb.SAST)
    session = session or requests.Session()
    picks = fb.candidates(json.loads(snapshot.read_text(encoding='utf-8')), now)
    complete = []
    for item in picks:
        home = fb.badge(session, item['home'], item['badges'].get('home'))
        away = fb.badge(session, item['away'], item['badges'].get('away'))
        if home is not None and away is not None:
            complete.append({**item, 'home_image':home, 'away_image':away})
        if len(complete) == 8:
            break
    if len(complete) < 5:
        print(f'Not creating a reel: only {len(complete)} qualifying matches have both crests (minimum 5).')
        return False
    output.mkdir(parents=True, exist_ok=True)
    day = now.date().isoformat()
    info = {'date':day, 'generated':json.loads(snapshot.read_text(encoding='utf-8'))['meta']['generated'],
            'fixtures':[{k:p[k] for k in ('fixture','home','away','kickoff','country','league','sel','selection','odds','badges')}
                        for p in complete]}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        if music is None:
            music = td/'music.mp3'
            download_music(music, session)
        slides = []
        for i,item in enumerate(complete, 1):
            slide = td/f'{i:02}.png'
            render_slide(item, i, len(complete), day, slide)
            slides.append(slide)
        encode(slides, music, output/'selection-reel.mp4')
    (output/'selection-reel.json').write_text(json.dumps(info),encoding='utf-8')
    print(f'Prepared a reel with {len(complete)} verified selections and supplied music.')
    return True


def reel_caption(info, test=False):
    caption = fb.caption_for(info)
    if test:
        caption = caption.replace('\n\n', '\n\nTest reel\n\n', 1)
    return caption


def validate_prepared(output, now=None):
    now = (now or datetime.now(fb.SAST)).astimezone(fb.SAST)
    video = output/'selection-reel.mp4'
    info = json.loads((output/'selection-reel.json').read_text(encoding='utf-8'))
    if info.get('date') != now.date().isoformat():
        raise ValueError('Reel selections are not for today')
    generated = datetime.strptime(info['generated'], '%Y-%m-%d %H:%M').replace(tzinfo=fb.SAST)
    if not timedelta(minutes=-5) <= now-generated <= timedelta(minutes=90):
        raise ValueError('Reel selections are based on a stale snapshot')
    if not 5 <= len(info.get('fixtures', [])) <= 8 or any(
        datetime.strptime(f['kickoff'], '%Y-%m-%d %H:%M').replace(tzinfo=fb.SAST) <= now+timedelta(minutes=5)
        for f in info['fixtures']):
        raise ValueError('Reel contains an expired or invalid selection')
    if not video.is_file() or not 0 < video.stat().st_size <= MAX_VIDEO_BYTES:
        raise ValueError('Reel is missing or exceeds the upload size limit')
    # Reserve space for the test label even before a delivery claim is written.
    if len(reel_caption(info, test=True)) > 1024:
        raise ValueError('The reel caption is too long for Telegram')
    return video, info


def publish_facebook(output, now=None, session=None, pause=time.sleep):
    video, info = validate_prepared(output, now)
    token, page_id = fb.credentials()
    session = session or requests.Session()
    token, _ = fb.resolve_page_token(session, token, page_id)
    endpoint = f'https://graph.facebook.com/v24.0/{page_id}/video_reels'
    try:
        r = session.post(endpoint, data={'access_token':token,'upload_phase':'start'}, timeout=60)
        if not r.ok:
            raise RuntimeError('Facebook rejected reel initialization: ' + fb.error_summary(r))
        video_id = str(r.json().get('video_id') or '')
        if not re.fullmatch(r'\d+', video_id):
            raise RuntimeError('Facebook did not return a valid reel ID')
        # Do not follow an arbitrary URL from a response while carrying a token.
        with video.open('rb') as src:
            r = session.post(f'https://rupload.facebook.com/video-upload/v24.0/{video_id}', data=src,
                             headers={'Authorization':'OAuth '+token, 'offset':'0', 'file_size':str(video.stat().st_size),
                                      'Content-Type':'application/octet-stream'}, timeout=180)
        if not r.ok or r.json().get('success') is not True:
            raise RuntimeError('Facebook rejected the reel video upload: ' + fb.error_summary(r))
        # This write can be ambiguous. Never retry automatically after claiming.
        r = session.post(endpoint, data={'access_token':token,'upload_phase':'finish', 'video_id':video_id,
                         'video_state':'PUBLISHED', 'description':reel_caption(info, os.environ.get('REEL_TEST') == 'true')}, timeout=60)
        if not r.ok or r.json().get('success') is not True:
            raise RuntimeError('Facebook did not confirm reel publication; check the Page before retrying')
        for attempt in range(12):
            r = session.get(f'https://graph.facebook.com/v24.0/{video_id}', params={'fields':'status'},
                            headers={'Authorization':'Bearer '+token}, timeout=30)
            if not r.ok:
                raise RuntimeError('Facebook accepted the reel but its status is unknown; check the Page before retrying')
            status = r.json().get('status') or {}
            phases = [status.get(k) or {} for k in ('uploading_phase','processing_phase','publishing_phase')]
            if any(p.get('error') or p.get('status') in ('error','failed') for p in phases):
                raise RuntimeError('Facebook reported a reel processing error; check the Page before retrying')
            if (status.get('publishing_phase') or {}).get('status') == 'complete':
                print('Facebook confirmed the reel is published.')
                return
            if attempt < 11:
                pause(10)
        raise RuntimeError('Facebook accepted the reel but processing is still pending; check the Page before retrying')
    except (requests.RequestException, ValueError):
        raise RuntimeError('Facebook reel upload or status is uncertain; check the Page before retrying') from None


def publish_telegram(output, now=None, session=None):
    video, info = validate_prepared(output, now)
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat:
        raise ValueError('Telegram delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID')
    session = session or requests.Session()
    try:
        with video.open('rb') as src:
            r = session.post(f'https://api.telegram.org/bot{token}/sendVideo',
                data={'chat_id':chat, 'caption':reel_caption(info, os.environ.get('REEL_TEST') == 'true'), 'supports_streaming':'true'},
                files={'video':('selection-reel.mp4',src,'video/mp4')}, timeout=180)
        if not r.ok or r.json().get('ok') is not True:
            raise RuntimeError('Telegram did not confirm video delivery; check the chat before retrying')
    except (requests.RequestException, ValueError):
        raise RuntimeError('Telegram video delivery is uncertain; check the chat before retrying') from None
    print('Telegram confirmed video delivery.')


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('prepare');p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for cmd in ('facebook','telegram','validate'):
        p=sub.add_parser(cmd);p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.cmd == 'prepare':
        ready=prepare(args.snapshot,args.output)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as out:
                out.write(f'ready={str(ready).lower()}\n')
    elif args.cmd == 'facebook': publish_facebook(args.output)
    elif args.cmd == 'telegram': publish_telegram(args.output)
    else: validate_prepared(args.output)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print(f'::error::{exc}', file=sys.stderr)
        sys.exit(1)
