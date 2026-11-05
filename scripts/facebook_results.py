#!/usr/bin/env python3
"""Build and publish a two-image recap of verified prior Facebook posts."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import competition_policy
import safe
from scripts import facebook_history as records
from scripts import facebook_post as fb


def recap_items(claims, day_data, day):
    """Match exact recorded fixtures only; unknown data remains explicitly pending."""
    if day_data.get('date') != day or not isinstance(day_data.get('fixtures'), list):
        raise ValueError('Yesterday’s match archive is missing or invalid')
    by_id = {f['id']: f for f in day_data['fixtures'] if isinstance(f, dict) and isinstance(f.get('id'), str)}
    by_name = {}
    for f in day_data['fixtures']:
        if isinstance(f, dict) and f.get('home') and f.get('away'):
            by_name.setdefault(records.match_key(f), []).append(f)
    # Legacy corrections may repeat the same match. Keep the recorded selection variants,
    # but don't duplicate identical rows across images or infer a missing historical pick.
    items, seen = [], set()
    for claim in claims:
        for original in claim['manifest']['fixtures']:
            key = records.match_key(original)
            fid = original.get('fixture')
            found = by_id.get(fid) if fid else None
            if found and records.match_key(found) != key:
                raise ValueError('A recorded fixture does not match its archived teams')
            if not found:
                matches = [f for f in by_name.get(key, []) if f.get('kickoff') == original.get('kickoff')]
                found = matches[0] if len(matches) == 1 else None
            sel = original.get('sel') or ''
            signature = (*key, sel, original.get('selection') or '')
            if signature in seen:
                continue
            seen.add(signature)
            country = original.get('country') or (found or {}).get('country') or ''
            league = original.get('league') or (found or {}).get('league') or ''
            score = (found or {}).get('score') or {}
            status = str(score.get('status') or '')
            hg, ag = score.get('hg'), score.get('ag')
            valid_score = (status == 'FT' and isinstance(hg, int) and not isinstance(hg, bool) and hg >= 0
                           and isinstance(ag, int) and not isinstance(ag, bool) and ag >= 0)
            displayed_score = f'{hg}–{ag}' if valid_score else '–'
            verdict = 'PENDING'
            if status in ('Postp.', 'Canc.', 'Aband.'):
                verdict = 'POSTPONED' if status == 'Postp.' else 'UNAVAILABLE'
            elif not sel:
                verdict = 'SCORE ONLY' if valid_score else 'PENDING'
            elif valid_score:
                # UEFA matches may finish after extra time: the archived FT label does
                # not always distinguish 90 minutes, so never guess bookmaker settlement.
                if not competition_policy._UEFA_NAMED.search(' '.join(competition_policy._text(x) for x in (country, league, (found or {}).get('div')))) and competition_policy._text(country) not in {'europe', 'champions league', 'europa league', 'conference league', 'europa conference league'}:
                    outcome = safe.settle(sel, hg, ag, score.get('hc'), score.get('ac'))
                    if outcome is not None:
                        verdict = 'WON' if outcome else 'LOST'
            suffix = claim.get('name', '').rsplit('-', 1)[-1]
            slot = f'{suffix}:00 post' if suffix in records.SLOTS else 'Earlier post'
            items.append({**original, 'country': country, 'league': league, 'score_text': displayed_score,
                          'post_slot': slot, 'verdict': verdict, 'badges': original.get('badges') or {},
                          'selection': original.get('selection') or 'Selection not recorded'})
    if len(items) > 24:
        raise ValueError('More than 24 distinct prior picks do not fit clearly on two result images')
    return items


def render_results(items, date, outputs, badge_index, session=None):
    """Render all matches across exactly two portrait images; never substitute crests."""
    session = session or requests.Session()
    if not items:
        raise ValueError('No previous Facebook selections to recap')
    if len(outputs) != 2:
        raise ValueError('Exactly two result images are required')
    cache = {}
    for item in items:
        for side in ('home', 'away'):
            name = item[side]
            path = item['badges'].get(side) or badge_index.get(name)
            key = (name, path)
            if key not in cache:
                cache[key] = fb.badge(session, name, path)
            if cache[key] is None:
                raise ValueError('A previous match is missing a verified club crest; not posting an incomplete recap')
            item[side + '_image'] = cache[key]
    midpoint = (len(items) + 1) // 2
    groups = [items[:midpoint], items[midpoint:]]
    for part, (group, path) in enumerate(zip(groups, outputs), 1):
        im = Image.new('RGB', (1080, 1920), 'white')
        draw = ImageDraw.Draw(im)
        logo = Image.open(fb.ROOT / 'android/design/mr-2-odds-logo.png').convert('RGBA')
        logo.thumbnail((180, 180), Image.Resampling.LANCZOS)
        im.paste(logo, (35, 14), logo)
        draw.text((245, 48), 'YESTERDAY’S RESULTS', font=fb.font(38, True), fill='#122b3d')
        date_text = datetime.strptime(date, '%Y-%m-%d').strftime('%d %B %Y')
        draw.text((245, 113), f'{date_text}  ·  {part} / 2', font=fb.font(25, True), fill='#285b56')
        fb.draw_age_badge(draw, (930, 55, 1030, 115))
        if not group:
            draw.text((540, 400), 'No additional matches', font=fb.font(34, True), fill='#122b3d', anchor='mm')
        else:
            gap, start, bottom = 10, 210, 1870
            height = min(250, (bottom - start - gap * (len(group) - 1)) // len(group))
            for i, item in enumerate(group):
                y = start + i * (height + gap)
                draw.rounded_rectangle((35, y, 1045, y + height), radius=15, fill='#f3f7f6', outline='#b3c8c4', width=2)
                competition = '  ·  '.join(v for v in (item.get('country'), item.get('league')) if v) or 'Competition unavailable'
                meta = f"{item.get('post_slot', 'Earlier post')}  ·  {competition}"
                mf = fb.fit(draw, meta, 755, 23, minimum=17, bold=True)
                draw.text((55, y + 17), meta, font=mf, fill='#335a58', anchor='lm')
                time = item.get('kickoff', '')
                if len(time) >= 16:
                    draw.text((1020, y + 17), time[11:16] + ' SAST', font=fb.font(20, True), fill='#174b48', anchor='rm')
                center = y + max(56, round(height * .43))
                compact = height < 150
                crest_size = 48 if compact else 64
                for side, x in (('home_image', 56), ('away_image', 951)):
                    crest = ImageOps.contain(item[side], (crest_size, crest_size), Image.Resampling.LANCZOS)
                    im.paste(crest, (x + (64 - crest.width)//2, center - crest.height//2), crest)
                team_style = {'max_size': 26, 'line_spacing': 26} if compact else {}
                fb.draw_team(draw, item['home'], 140, center, 'lm', **team_style)
                fb.draw_team(draw, item['away'], 940, center, 'rm', **team_style)
                draw.text((540, center), item['score_text'], font=fb.font(27, True), fill='#122b3d', anchor='mm')
                lower = y + height - 24
                selection = item['selection']
                if isinstance(item.get('odds'), (int, float)):
                    selection += f"  ·  {item['odds']:.2f}"
                sf = fb.fit(draw, selection, 655, 24, minimum=17)
                draw.text((140, lower), selection, font=sf, fill='#183b42', anchor='lm')
                color = {'WON': '#007f72', 'LOST': '#a42e35'}.get(item['verdict'], '#52656c')
                draw.rounded_rectangle((815, lower - 17, 1008, lower + 17), radius=8, fill=color)
                vf = fb.fit(draw, item['verdict'], 180, 19, minimum=15, bold=True)
                draw.text((912, lower), item['verdict'], font=vf, fill='white', anchor='mm')
        path.parent.mkdir(parents=True, exist_ok=True)
        im.save(path, 'PNG', optimize=True)


def prepare(day_file, badge_file, output, now=None, claims=None, session=None):
    now = (now or datetime.now(fb.SAST)).astimezone(fb.SAST)
    day = (now.date() - timedelta(days=1)).isoformat()
    claims = records.load_claims(day, confirmed_only=True) if claims is None else claims
    if not claims:
        print('No verified selection pictures from yesterday; skipping the recap.')
        return False
    data = json.loads(day_file.read_text(encoding='utf-8'))
    items = recap_items(claims, data, day)
    if not items:
        print('No selections recorded for yesterday; skipping the recap.')
        return False
    paths = [output / 'results-1.png', output / 'results-2.png']
    render_results(items, day, paths, json.loads(badge_file.read_text(encoding='utf-8')), session=session)
    manifest = {'date': day, 'fixtures': [{'home': p['home'], 'away': p['away']} for p in items]}
    (output / 'results.json').write_text(json.dumps(manifest), encoding='utf-8')
    print(f'Prepared two result images for {len(items)} recorded selections.')
    return True


def publish(output, now=None, session=None):
    now = (now or datetime.now(fb.SAST)).astimezone(fb.SAST)
    info = json.loads((output / 'results.json').read_text(encoding='utf-8'))
    if info.get('date') != (now.date() - timedelta(days=1)).isoformat():
        raise ValueError('Results are not for yesterday')
    fixtures = info.get('fixtures') or []
    if not 1 <= len(fixtures) <= 24:
        raise ValueError('Invalid results manifest')
    # Reuse team-only hashtag handling without the selections-card count constraint.
    tags, seen = [], set()
    for item in fixtures:
        for side in ('home', 'away'):
            name = item.get(side)
            if not isinstance(name, str) or not name.strip():
                raise ValueError('Missing team in results caption')
            import unicodedata
            tag = ''.join(c for c in unicodedata.normalize('NFKC', name) if c.isalnum() or c == '_')
            if not tag:
                raise ValueError('Invalid results hashtag')
            if tag.casefold() not in seen:
                seen.add(tag.casefold()); tags.append('#' + tag)
    day = datetime.strptime(info['date'], '%Y-%m-%d')
    questions = ('Which match did you follow?', 'Did you catch any of these games?',
                 'Which result caught your eye?', 'What did you make of these matches?')
    caption = (f"Yesterday's results - {day.day} {day.strftime('%B %Y')}\n\n"
               f"{questions[day.toordinal() % len(questions)]}\n"
               'Follow Mr 2 Odds for more picks and results.\n'
               '18+ | Bet responsibly.\n\n' + ' '.join(tags))
    token, page_id = fb.credentials()
    session = session or requests.Session()
    token, _ = fb.resolve_page_token(session, token, page_id)
    try:
        ids = []
        for i in (1, 2):
            with (output / f'results-{i}.png').open('rb') as image:
                r = session.post(f'https://graph.facebook.com/v24.0/{page_id}/photos',
                                 data={'access_token': token, 'published': 'false'},
                                 files={'source': (f'results-{i}.png', image, 'image/png')}, timeout=60)
            if not r.ok:
                raise RuntimeError('Facebook rejected an unpublished result photo: ' + fb.error_summary(r))
            image_id = r.json().get('id')
            if not image_id:
                raise RuntimeError('Facebook did not confirm a result photo; check the Page before retrying')
            ids.append(str(image_id))
        data = {'access_token': token, 'message': caption}
        data.update({f'attached_media[{i}]': json.dumps({'media_fbid': image_id}) for i, image_id in enumerate(ids)})
        r = session.post(f'https://graph.facebook.com/v24.0/{page_id}/feed', data=data, timeout=60)
        if not r.ok:
            raise RuntimeError('Facebook rejected the result post: ' + fb.error_summary(r))
        if not r.json().get('id'):
            raise RuntimeError('Facebook did not confirm the result post; check the Page before retrying')
    except requests.RequestException:
        raise RuntimeError('Facebook result upload is unknown; check the Page before any retry') from None
    print('Facebook confirmed the two-image result post.')


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--day-file', type=Path, required=True)
    prep.add_argument('--badges', type=Path, required=True)
    prep.add_argument('--output', type=Path, required=True)
    pub = sub.add_parser('publish'); pub.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.cmd == 'prepare':
        ready = prepare(args.day_file, args.badges, args.output)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
                f.write(f'ready={str(ready).lower()}\n')
    else:
        publish(args.output)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print(f'::error::{exc}', file=sys.stderr)
        sys.exit(1)
