#!/usr/bin/env python3
"""Rebuild today's confirmed 07:00 picture from freshly checked selections."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import facebook_history as history
from scripts import facebook_post as fb


def prepare(snapshot, output, claims, now=None, session=None):
    now = (now or datetime.now(fb.SAST)).astimezone(fb.SAST)
    name = f"facebook-post-{now.date().isoformat()}-07"
    matches = [claim['manifest'] for claim in claims if claim['name'] == name]
    if len(matches) != 1:
        raise ValueError('A single confirmed 07:00 picture is required for the repost')
    original = matches[0]
    if original.get('series') == 'stats-watch':
        raise ValueError('The morning picture is Stats Watch, not priced betting selections; manual review required')
    fixtures = original.get('fixtures') or []
    if not 5 <= len(fixtures) <= 8:
        raise ValueError('The morning picture has no complete set of selection records')
    data = json.loads(Path(snapshot).read_text(encoding='utf-8'))
    refs = [{'fixture':f.get('fixture'), 'sel':f.get('sel')} for f in fixtures]
    fresh = fb.candidates(data, now, refs)
    if len(fresh) != len(fixtures):
        raise ValueError('At least one morning selection is no longer eligible or has no current quote; not reposting')
    session = session or requests.Session()
    complete = []
    for old, pick in zip(fixtures, fresh):
        if (old.get('fixture') != pick['fixture'] or old.get('sel') != pick['sel']
                or history.match_key(old) != history.match_key(pick)):
            raise ValueError('A morning fixture no longer matches the current source')
        home = fb.badge(session, pick['home'], pick['badges'].get('home'))
        away = fb.badge(session, pick['away'], pick['badges'].get('away'))
        if home is None or away is None:
            raise ValueError('A morning fixture is missing a verified club crest')
        complete.append({**pick, 'home_image':home, 'away_image':away})
    fields = ('fixture','kickoff','country','league','home','away','sel','selection','odds','livescore_id','badges')
    info = {'date':now.date().isoformat(), 'generated':data['meta']['generated'],
            'fixtures':[{k:row[k] for k in fields} for row in complete]}
    output = Path(output)
    fb.render(complete,output)
    output.with_suffix('.json').write_text(json.dumps(info,ensure_ascii=False),encoding='utf-8')
    for row in info['fixtures']:
        print(f"::notice::{row['home']} v {row['away']} | {row['selection']} @ {row['odds']:.2f} | {row['kickoff']} SAST")
    print('Prepared the morning picture using current verified SportyBet quotes.')
    return info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    day = datetime.now(fb.SAST).date().isoformat()
    claims = history.load_claims(day, confirmed_only=True)
    prepare(args.snapshot, args.output, claims)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print(f'::error::{exc}', file=sys.stderr)
        sys.exit(1)
