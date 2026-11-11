#!/usr/bin/env python3
"""Prepare and publish one branded Facebook selection card.

The published app snapshot is the only source of selections and quoted prices. No
passwords, page identifiers or tokens are ever written into the image or logs.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import competition_policy
import recommendation_policy as policy
import safe
from scripts import facebook_history

ROOT = Path(__file__).resolve().parents[1]
SAST = ZoneInfo('Africa/Johannesburg')
BADGE_BASE = 'https://lsm-static-prod.livescore.com/medium/'
WIKI = 'https://en.wikipedia.org/w/api.php'
HEADERS = {'User-Agent': 'Mr2OddsSelections/1.0 (football club badge lookup)'}
MAX_IMAGE_BYTES = 3 * 1024 * 1024


def number(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def candidates(data, now, picks=None):
    """Revalidate selections and current quotes against the app's strict policy.

    The default source is the primary shortlist. A caller may provide market-specific
    fixture/selection references, but every reference passes the same checks below.
    """
    now = now.astimezone(SAST)
    try:
        generated = datetime.strptime(data['meta']['generated'], '%Y-%m-%d %H:%M').replace(tzinfo=SAST)
    except (KeyError, TypeError, ValueError):
        raise ValueError('Snapshot publication time is missing or invalid') from None
    if not timedelta(minutes=-5) <= now - generated <= timedelta(minutes=90):
        raise ValueError('Snapshot is stale or dated in the future')
    fixtures = {f.get('id'): f for f in data.get('fixtures', []) if isinstance(f, dict)}
    result, seen = [], set()
    if picks is None:
        picks = (data.get('shortlist') or {}).get('primary', [])
    for pick in picks:
        f = fixtures.get(pick.get('fixture'))
        if not f or f.get('id') in seen or not competition_policy.allows_record(f) or not f.get('data_ok') or f.get('q') == 'Low':
            continue
        if f.get('date') != now.date().isoformat() or f.get('time_known') is not True:
            continue
        country, league = f.get('country'), f.get('league')
        if not isinstance(country, str) or not country.strip() or not isinstance(league, str) or not league.strip():
            continue
        country, league = country.strip(), league.strip()
        try:
            kickoff = datetime.strptime(f['kickoff'], '%Y-%m-%d %H:%M').replace(tzinfo=SAST)
        except (KeyError, TypeError, ValueError):
            continue
        # Leave time to retrieve crests and publish before kick-off.
        if kickoff <= now + timedelta(minutes=15):
            continue
        code = pick.get('sel')
        if not policy.allowed(code):
            continue
        matches = [s for s in (f.get('sels') or []) if isinstance(s, list) and len(s) >= 6 and s[0] == code]
        if len(matches) != 1:
            continue
        s = matches[0]
        p, model, market, odds = map(number, s[1:5])
        bar = .55 if code in ('H', 'D', 'A', 'O25', 'BTTS') else .65 if code.startswith('C') else .70
        if (p is None or not bar <= p < 1 or odds is None or not policy.PRICE_FLOOR <= odds <= 1.90
                or p * odds < .95 or s[5] or policy.outlier(model, market, odds)):
            continue
        home, away = str(f.get('home') or '').strip(), str(f.get('away') or '').strip()
        if not home or not away:
            continue
        seen.add(f['id'])
        result.append({'fixture': f['id'], 'home': home, 'away': away, 'selection': safe.label(code, home, away), 'sel': code,
                       'country': country, 'league': league, 'odds': odds, 'probability': p, 'kickoff': f['kickoff'],
                       'livescore_id': f.get('livescore_id'), 'badges': f.get('badges') or {}})
    return result


def image_from_url(session, url):
    try:
        response = session.get(url, timeout=15, headers=HEADERS, stream=True, allow_redirects=True)
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                return None
            chunks.append(chunk)
        image = Image.open(io.BytesIO(b''.join(chunks)))
        if image.width * image.height > 16_000_000:
            return None
        image.load()
        return image.convert('RGBA')
    except (requests.RequestException, OSError, ValueError, UnidentifiedImageError):
        return None


def normal_name(name):
    text = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    words = re.findall(r'[a-z0-9]+', text)
    return ' '.join(w for w in words if w not in {'fc', 'afc', 'cf', 'sc', 'football', 'club'})


def wiki_badge(session, team):
    """Conservative web fallback: only a precisely matching club article's logo.

    Skip uncertain names rather than assign another club's crest.
    """
    try:
        query = session.get(WIKI, params={'action':'query', 'list':'search', 'srsearch': team + ' football club',
                            'srlimit':8, 'format':'json'}, timeout=15, headers=HEADERS)
        query.raise_for_status()
        matches = [hit.get('title', '') for hit in query.json().get('query', {}).get('search', [])
                   if normal_name(hit.get('title', '')) == normal_name(team)]
        if len(matches) != 1:
            return None
        for title in matches:
            response = session.get(WIKI, params={'action':'query','prop':'pageimages','titles':title,
                'pithumbsize':250, 'format':'json'}, timeout=15, headers=HEADERS)
            response.raise_for_status()
            for page in response.json().get('query', {}).get('pages', {}).values():
                source = (page.get('thumbnail') or {}).get('source', '')
                # Only Wikimedia image URLs, not arbitrary URLs from a feed.
                if re.match(r'^https://upload\.wikimedia\.org/', source) and re.search(r'(?:crest|logo|badge|emblem|escut|shield|coat.of.arms)', source, re.I):
                    image = image_from_url(session, source)
                    if image:
                        return image
    except (requests.RequestException, ValueError, TypeError):
        pass
    return None


def badge(session, team, path):
    if isinstance(path, str) and re.fullmatch(r'(?:enet|teambadge)/[A-Za-z0-9_.-]+', path):
        image = image_from_url(session, BADGE_BASE + path)
        if image:
            return image
    return wiki_badge(session, team)


def font(size, bold=False):
    name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    for base in ('/usr/share/fonts/truetype/dejavu', '/usr/share/fonts/truetype/dejavu-sans'):
        try:
            return ImageFont.truetype(str(Path(base) / name), size)
        except OSError:
            pass
    return ImageFont.load_default()


def fit(draw, text, max_width, size, minimum=18, bold=False):
    while size > minimum and draw.textbbox((0, 0), text, font=font(size, bold))[2] > max_width:
        size -= 1
    f = font(size, bold)
    if draw.textbbox((0, 0), text, font=f)[2] > max_width:
        raise ValueError('A team name or selection is too long to fit safely')
    return f


def draw_team(draw, name, x, center_y, anchor, max_size=32, line_spacing=33):
    """Keep each complete club name within its own half, wrapping before shrinking."""
    max_width = 320
    words = name.split()
    splits = [(name,)] + [(' '.join(words[:i]), ' '.join(words[i:])) for i in range(1, len(words))]
    for size in range(max_size, 20, -1):
        f = font(size, True)
        choices = [lines for lines in splits if all(draw.textbbox((0, 0), line, font=f)[2] <= max_width for line in lines)]
        if choices:
            lines = min(choices, key=lambda v: (len(v), max(draw.textbbox((0, 0), t, font=f)[2] for t in v)))
            for i, line in enumerate(lines):
                draw.text((x, center_y + (i - (len(lines) - 1) / 2) * line_spacing), line, font=f, fill='#122b3d', anchor=anchor)
            return
    raise ValueError('A team name is too long to display safely')


def draw_age_badge(draw, box):
    """Small, unobtrusive age reminder that fits in a card's header."""
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=16, fill='#ffffff', outline='#8faca8', width=3)
    draw.text(((x1 + x2) // 2, (y1 + y2) // 2), '18+',
              font=font(25, True), fill='#274c49', anchor='mm')


def render(selections, path, logo_path=ROOT / 'android/design/mr-2-odds-logo.png', *, minimum=5, heading=None, subheading=None):
    if not minimum <= len(selections) <= 8:
        raise ValueError(f'An image requires {minimum} to 8 complete selections')
    # 1080 x 1920 is exactly 9:16. Each match owns a separate spacious card.
    image = Image.new('RGB', (1080, 1920), '#ffffff')
    draw = ImageDraw.Draw(image)
    logo = Image.open(logo_path).convert('RGBA')
    logo.thumbnail((210, 210), Image.Resampling.LANCZOS)
    image.paste(logo, (35, 12), logo)
    heading = heading or ('TODAY’S PREDICTIONS' if selections[0].get('series') == '1x2' else 'TODAY’S FOOTBALL PICKS')
    draw.text((260, 72), heading,
              font=fit(draw, heading, 640, 42, minimum=30, bold=True), fill='#122b3d')
    if subheading:
        draw.text((260, 142), subheading, font=font(25, True), fill='#007f72')
    else:
        draw.rounded_rectangle((260, 138, 532, 144), radius=3, fill='#008f80')
    draw_age_badge(draw, (930, 70, 1030, 130))
    # A clean bet-slip layout: selection and quoted price first, then the
    # complete fixture, followed by league and kickoff. No sportsbook UI is copied.
    gap, start, bottom = 12, 230, 1855
    height = (bottom - start - gap * (len(selections) - 1)) // len(selections)
    for i, item in enumerate(selections):
        y = start + i * (height + gap)
        draw.rounded_rectangle((35, y, 1045, y + height), radius=18, fill='#f3f7f6', outline='#b3c8c4', width=2)
        pick = f"{item['selection']}  @ {item['odds']:.2f}"
        draw.text((75, y + height*.19), pick, font=fit(draw,pick,900,34,minimum=21,bold=True), fill='#122b3d', anchor='lm')
        match_y = y + height*.54
        for side, x in (('home_image', 78), ('away_image', 1002)):
            crest = ImageOps.contain(item[side], (58,58), Image.Resampling.LANCZOS)
            image.paste(crest, (x - crest.width//2, round(match_y - crest.height//2)), crest)
        match = f"{item['home']}  vs  {item['away']}"
        draw.text((540,match_y),match,font=fit(draw,match,790,29,minimum=18,bold=True),fill='#122b3d',anchor='mm')
        kickoff = datetime.strptime(item['kickoff'], '%Y-%m-%d %H:%M').strftime('%d/%m %H:%M SAST')
        competition = f"{item['country']} · {item['league']}"
        draw.text((75,y + height*.82),competition,font=fit(draw,competition,610,22,minimum=16),fill='#486a66',anchor='lm')
        draw.text((1005,y + height*.82),kickoff,font=font(22,True),fill='#008f70',anchor='rm')
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, 'PNG', optimize=True)


def caption_for(manifest, *, medium='photo'):
    """Return only the hashtags for teams shown on the post or video."""
    if manifest.get("series") == "accumulators":
        from scripts import facebook_accumulators
        return facebook_accumulators.caption(manifest)
    if manifest.get("series") == "stats-watch":
        from scripts import stats_watch_assets
        return stats_watch_assets.caption(manifest)
    try:
        fixtures = manifest['fixtures']
    except (KeyError, TypeError):
        raise ValueError('Invalid hashtag data') from None
    if not isinstance(fixtures, list) or not 5 <= len(fixtures) <= 8:
        raise ValueError('Hashtags require the same 5 to 8 matches as the image')
    tags, seen = [], set()
    for item in fixtures:
        for side in ('home', 'away'):
            name = item.get(side)
            if not isinstance(name, str) or not name.strip():
                raise ValueError('Missing team name in hashtag data')
            tag = ''.join(c for c in unicodedata.normalize('NFKC', name) if c.isalnum() or c == '_')
            if not tag:
                raise ValueError('Cannot make a hashtag from the team name')
            if tag.casefold() not in seen:
                seen.add(tag.casefold())
                tags.append('#' + tag)
    return ' '.join(tags)


def prepare(snapshot, output, now=None, session=None, prior_claims=None):
    now = now or datetime.now(SAST)
    excluded = facebook_history.prior_matches(prior_claims or [])
    excluded_ids = facebook_history.prior_livescore_ids(prior_claims or [])
    picks = [p for p in candidates(json.loads(Path(snapshot).read_text(encoding='utf-8')), now)
             if facebook_history.match_key(p) not in excluded
             and (not str(p.get('livescore_id') or '').strip()
                  or str(p['livescore_id']).strip() not in excluded_ids)]
    session = session or requests.Session()
    complete = []
    for item in picks:
        home = badge(session, item['home'], item['badges'].get('home'))
        away = badge(session, item['away'], item['badges'].get('away'))
        if home is not None and away is not None:
            complete.append({**item, 'home_image': home, 'away_image': away})
        # Five per slot leaves more distinct fixtures for later cards and keeps the
        # following morning's two-image recap readable without dropping results.
        if len(complete) == 5:
            break
    if len(complete) < 5:
        print(f'Not posting: only {len(complete)} eligible matches have both crests (minimum 5).')
        return False
    render(complete, output)
    manifest = {'date': now.astimezone(SAST).date().isoformat(), 'generated': json.loads(Path(snapshot).read_text())['meta']['generated'],
                'fixtures': [{k: p[k] for k in ('fixture', 'kickoff', 'country', 'league', 'home', 'away',
                                                  'sel', 'selection', 'odds', 'livescore_id', 'badges')} for p in complete]}
    output.with_suffix('.json').write_text(json.dumps(manifest), encoding='utf-8')
    print(f'Prepared {len(complete)} selections with both club crests.')
    return True


def credentials():
    token = os.environ.get('FACEBOOK_PAGE_ACCESS_TOKEN', '').strip()
    page_id = os.environ.get('FACEBOOK_PAGE_ID', '').strip()
    if not token or not re.fullmatch(r'\d+', page_id):
        raise ValueError('FACEBOOK_PAGE_ACCESS_TOKEN and numeric FACEBOOK_PAGE_ID must be configured as Actions secrets')
    return token, page_id


def error_summary(response):
    """Report only numeric Graph codes; never print responses, URLs or secrets."""
    try:
        err = response.json().get('error', {})
        code, subcode = err.get('code'), err.get('error_subcode')
        fields = [f'HTTP {int(response.status_code)}']
        if isinstance(code, int) and not isinstance(code, bool):
            fields.append(f'Facebook code {code}')
        if isinstance(subcode, int) and not isinstance(subcode, bool):
            fields.append(f'subcode {subcode}')
        return ', '.join(fields)
    except (ValueError, TypeError, AttributeError):
        return f'HTTP {int(response.status_code)}'


def resolve_page_token(session, token, page_id):
    """Use a Page token directly, or retrieve this Page's token from an authorized user token.

    Derived tokens remain in memory; responses, names, IDs and credentials are never logged.
    """
    try:
        headers = {'Authorization': 'Bearer ' + token}
        response = session.get('https://graph.facebook.com/v24.0/me', params={'fields': 'id'}, headers=headers, timeout=30)
        if not response.ok:
            raise RuntimeError('Facebook token check rejected: ' + error_summary(response))
        identity = response.json().get('id')
        if not identity:
            raise RuntimeError('Facebook token check returned no identity')
        if str(identity) == page_id:
            return token, False
        params = {'fields': 'id,access_token', 'limit': 100}
        for _ in range(10):
            accounts = session.get('https://graph.facebook.com/v24.0/me/accounts', params=params, headers=headers, timeout=30)
            if not accounts.ok:
                raise RuntimeError('Page access check rejected: ' + error_summary(accounts))
            body = accounts.json()
            for entry in body.get('data', []):
                if isinstance(entry, dict) and str(entry.get('id', '')) == page_id:
                    page_token = entry.get('access_token')
                    if not isinstance(page_token, str) or not page_token.strip():
                        raise RuntimeError('Facebook did not provide a Page access token; check Page permissions')
                    return page_token.strip(), True
            paging = body.get('paging') or {}
            cursor = (paging.get('cursors') or {}).get('after') if paging.get('next') else None
            if not cursor:
                break
            params = {'fields': 'id,access_token', 'limit': 100, 'after': cursor}
        raise RuntimeError('The configured Page was not found among the token’s accessible Pages')
    except requests.RequestException:
        raise RuntimeError('Could not reach Facebook for the read-only token check') from None


def diagnose(session=None):
    """Read-only token check; no photo is posted and no identifiers are logged."""
    token, page_id = credentials()
    _, derived = resolve_page_token(session or requests.Session(), token, page_id)
    detail = 'using an authorized user token' if derived else 'using the Page token'
    print(f'::notice::Facebook confirmed access to the configured Page {detail}.')


def publish(image_path, now=None, session=None):
    token, page_id = credentials()
    now = now or datetime.now(SAST)
    info = json.loads(image_path.with_suffix('.json').read_text(encoding='utf-8'))
    if info['date'] != now.astimezone(SAST).date().isoformat():
        raise ValueError('Prepared card is not for today')
    if info.get('series') == 'stats-watch':
        from scripts import stats_watch_assets
        stats_watch_assets.validate_manifest(info, now)
    else:
        generated = datetime.strptime(info['generated'], '%Y-%m-%d %H:%M').replace(tzinfo=SAST)
        if not timedelta(minutes=-5) <= now - generated <= timedelta(minutes=90):
            raise ValueError('Prepared card is based on a stale snapshot')
        if not 5 <= len(info['fixtures']) <= 8 or any(datetime.strptime(x['kickoff'], '%Y-%m-%d %H:%M').replace(tzinfo=SAST) <= now + timedelta(minutes=5) for x in info['fixtures']):
            raise ValueError('At least one fixture has started or is about to start; not posting')
    session = session or requests.Session()
    token, _ = resolve_page_token(session, token, page_id)
    try:
        with image_path.open('rb') as image:
            response = session.post(f'https://graph.facebook.com/v24.0/{page_id}/photos',
                data={'access_token': token, 'message': caption_for(info)}, files={'source': ('selections.png', image, 'image/png')}, timeout=60)
        if not response.ok:
            raise RuntimeError('Facebook rejected the photo: ' + error_summary(response))
        payload = response.json()
        if not payload.get('id'):
            raise ValueError('Facebook did not confirm the photo ID; check the Page before retrying')
    except requests.RequestException:
        # A timeout can mean Facebook accepted the photo. Never print the token or retry automatically.
        raise RuntimeError('Facebook upload failed or its result is unknown; check the Page before any retry') from None
    print('Facebook confirmed the photo post.')


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--snapshot', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--exclude-claimed', action='store_true', help='exclude every match claimed earlier today')
    p = sub.add_parser('publish'); p.add_argument('--image', type=Path, required=True)
    sub.add_parser('diagnose')
    args = parser.parse_args()
    if args.cmd == 'prepare':
        prior = facebook_history.load_claims(datetime.now(SAST).date().isoformat()) if args.exclude_claimed else []
        ready = prepare(args.snapshot, args.output, prior_claims=prior)
        if not ready:
            from scripts import stats_watch_assets
            ready = stats_watch_assets.prepare(args.output.parent, include_video=False, image_path=args.output,
                                               prior_claims=prior)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
                out.write(f'ready={str(ready).lower()}\n')
    elif args.cmd == 'diagnose':
        diagnose()
    else:
        publish(args.image)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print(f'::error::{exc}', file=sys.stderr)
        sys.exit(1)
