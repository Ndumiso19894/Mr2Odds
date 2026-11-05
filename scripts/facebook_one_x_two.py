#!/usr/bin/env python3
"""Prepare a matched 1X2 card and reel using verified, priced selections only."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import facebook_history as history
from scripts import facebook_post as fb
from scripts import selection_reel as reel

MIN_PROBABILITY = .60
MAX_PROBABILITY = .95


def one_x_two_candidates(data, now, prior_claims=()):
    # Unlike a primary shortlist, this examines each actual modelled 1X2 market.
    # Applying fb.candidates afterwards preserves all existing eligibility checks.
    refs = []
    for fixture in data.get('fixtures', []):
        if not isinstance(fixture, dict):
            continue
        for selection in fixture.get('sels') or []:
            if not isinstance(selection, list) or len(selection) < 6 or selection[0] not in ('H', 'D', 'A'):
                continue
            p = fb.number(selection[1])
            if p is not None and MIN_PROBABILITY <= p <= MAX_PROBABILITY:
                refs.append((p, str(fixture.get('id') or ''), selection[0]))
    refs.sort(key=lambda x: (-x[0], x[1], x[2]))
    picks = fb.candidates(data, now, [{'fixture': fid, 'sel': code} for _, fid, code in refs])
    excluded = history.prior_matches(prior_claims)
    ids = {str(p['livescore_id']) for c in prior_claims for p in c['manifest']['fixtures'] if p.get('livescore_id')}
    seen = set()
    result = []
    for pick in picks:
        key = history.match_key(pick)
        if key in excluded or key in seen or (pick.get('livescore_id') and str(pick['livescore_id']) in ids):
            continue
        seen.add(key)
        result.append({**pick, 'series':'1x2',
                       'selection': {'H':'Home win (1)', 'D':'Draw (X)', 'A':'Away win (2)'}[pick['sel']]})
    return result


def prepare(snapshot, output, now=None, session=None, music=None, prior_claims=()):
    now = (now or datetime.now(fb.SAST)).astimezone(fb.SAST)
    session = session or requests.Session()
    data = json.loads(Path(snapshot).read_text(encoding='utf-8'))
    candidates = one_x_two_candidates(data, now, prior_claims)
    complete = []
    for pick in candidates:
        home = fb.badge(session, pick['home'], pick['badges'].get('home'))
        away = fb.badge(session, pick['away'], pick['badges'].get('away'))
        if home is not None and away is not None:
            complete.append({**pick, 'home_image':home, 'away_image':away})
        if len(complete) == 6:
            break
    if len(complete) < 5:
        print(f'Not posting 1X2: only {len(complete)} qualifying matches have both real crests (minimum 5).')
        return False
    output.mkdir(parents=True, exist_ok=True)
    day = now.date().isoformat()
    fields = ('fixture','home','away','kickoff','country','league','sel','selection','odds','probability','badges','livescore_id','series')
    info = {'date':day, 'generated':data['meta']['generated'], 'series':'1x2',
            'fixtures':[{k:pick[k] for k in fields} for pick in complete]}
    with tempfile.TemporaryDirectory() as td:
        temp = Path(td)
        if music is None:
            music = temp/'music.mp3'
            reel.download_music(music, session)
        fb.render(complete, output/'selections.png')
        slides = []
        for i, item in enumerate(complete, 1):
            slide = temp/f'{i:02}.png'
            reel.render_slide(item, i, len(complete), day, slide)
            slides.append(slide)
        reel.encode(slides, music, output/'selection-reel.mp4')
    for name in ('selections.json', 'selection-reel.json'):
        (output/name).write_text(json.dumps(info), encoding='utf-8')
    validate(output, now)
    print(f'Prepared a 1X2 picture and reel with {len(complete)} verified selections.')
    return True


def validate(output, now=None):
    output = Path(output)
    _, info = reel.validate_prepared(output, now)
    picture_info = json.loads((output/'selections.json').read_text(encoding='utf-8'))
    if picture_info != info or not (output/'selections.png').is_file():
        raise ValueError('The 1X2 picture and reel do not have the same recorded selections')
    if info.get('series') == 'stats-watch':
        from scripts import stats_watch_assets
        return stats_watch_assets.validate_manifest(info, now)
    fixtures = info.get('fixtures') or []
    if info.get('series') != '1x2' or not 5 <= len(fixtures) <= 6:
        raise ValueError('The 1X2 publication must contain five or six matches')
    seen = set()
    for item in fixtures:
        p, odds = fb.number(item.get('probability')), fb.number(item.get('odds'))
        key = history.match_key(item)
        labels = {'H':'Home win (1)', 'D':'Draw (X)', 'A':'Away win (2)'}
        if (key in seen or item.get('series') != '1x2' or item.get('sel') not in labels
                or item.get('selection') != labels.get(item.get('sel'))
                or p is None or not MIN_PROBABILITY <= p <= MAX_PROBABILITY
                or odds is None or not fb.policy.PRICE_FLOOR <= odds <= 1.90 or p * odds < .95):
            raise ValueError('The 1X2 manifest contains an invalid or duplicate selection')
        seen.add(key)
    return info


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--snapshot', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('validate'); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.cmd == 'prepare':
        claims = history.load_claims(datetime.now(fb.SAST).date().isoformat())
        day = datetime.now(fb.SAST).date().isoformat()
        if day == '2026-11-05':
            # The user specifically requested ten unbeaten top-two teams today.
            from scripts import stats_watch_assets
            ready = stats_watch_assets.prepare(args.output, minimum=10)
        else:
            ready = prepare(args.snapshot, args.output, prior_claims=claims)
            if not ready:
                from scripts import stats_watch_assets
                ready = stats_watch_assets.prepare(args.output)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
                out.write(f'ready={str(ready).lower()}\n')
    else:
        validate(args.output)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print(f'::error::{exc}', file=sys.stderr)
        sys.exit(1)
