"""Small, source-neutral lineup pilot. Never supplies inputs to the prediction model.

The importer accepts only operator-supplied confirmed XIs. It makes no network calls.
The operator must verify the source permits this product's use and public-state storage.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import logging
import math
from pathlib import Path
import tempfile
import os

log = logging.getLogger('scanner')
PILOT = {'E0': 'England', 'D1': 'Germany'}
MIN_HISTORY = 3
MAX_HISTORY = 10
REGULAR_SHARE = .6


def _time(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be an ISO-8601 string with timezone')
    try:
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid ISO-8601 timestamp') from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timestamp must include timezone')
    return value.astimezone(timezone.utc)


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f'{label} must be a non-empty string of at most 200 characters')
    return value.strip()


def _team(obj):
    if not isinstance(obj, dict):
        raise ValueError('team must be an object')
    name = _text(obj.get('name'), 'team name')
    ident = _text(obj.get('id'), 'team id')
    players = obj.get('starting')
    if not isinstance(players, list) or len(players) != 11:
        raise ValueError('a confirmed starting XI must contain exactly 11 players')
    result = [{'id': _text(p.get('id'), 'player id'), 'name': _text(p.get('name'), 'player name')}
              for p in players if isinstance(p, dict)]
    if len(result) != 11 or len({p['id'] for p in result}) != 11:
        raise ValueError('a starting XI needs 11 distinct player ids')
    return {'name': name, 'id': ident, 'starting': result}


def validate(record):
    if not isinstance(record, dict) or record.get('status') != 'confirmed':
        raise ValueError('only confirmed starting XIs may be imported')
    div = _text(record.get('div'), 'division')
    country = _text(record.get('country'), 'country')
    if PILOT.get(div) != country:
        raise ValueError('fixture is outside the England Premier League / Germany Bundesliga pilot')
    home, away = _team(record.get('home')), _team(record.get('away'))
    if home['id'] == away['id']:
        raise ValueError('home and away team ids must differ')
    if set(p['id'] for p in home['starting']) & set(p['id'] for p in away['starting']):
        raise ValueError('a player cannot start for both teams')
    ko = _time(record.get('kickoff'))
    source = _text(record.get('source'), 'source')
    match_id = _text(record.get('source_match_id'), 'source match id')
    # Fixture date is local to the match's supplied kickoff timezone, matching the app's SAST date convention.
    local_date = datetime.fromisoformat(record['kickoff'].replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=2))).date().isoformat()
    fid = f"{local_date}|{country}|{home['name']}|{away['name']}"
    if record.get('fixture_id') != fid:
        raise ValueError('fixture_id must exactly match SAST date, country and both app team names')
    return {'fixture_id': fid, 'country': country, 'div': div, 'kickoff': ko.isoformat(),
            'source': source, 'source_match_id': match_id, 'status': 'confirmed', 'home': home, 'away': away}


def capture(archive, records, now):
    """Stamp the real collection time; supplied timestamps are never accepted as proof of prior knowledge."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('capture clock requires a timezone')
    if not isinstance(records, list):
        raise ValueError('input must be a JSON list of lineup records')
    normalized = [validate(r) for r in records]  # all-or-nothing: no partial import
    if len({(r['source'], r['source_match_id']) for r in normalized}) != len(normalized):
        raise ValueError('input contains duplicate source match ids')
    result = list(archive)
    count = 0
    for r in normalized:
        previous = [x for x in result if x['source'] == r['source'] and x['source_match_id'] == r['source_match_id']]
        if any(x['fixture_id'] != r['fixture_id'] or x['div'] != r['div'] for x in previous):
            raise ValueError('source match id conflicts with an archived fixture')
        if previous:
            last = max(previous, key=lambda x: _time(x['observed_at']))
            if all(last[k] == r[k] for k in ('kickoff', 'home', 'away')):
                continue  # idempotent re-import: never refresh the original observation time
        r['observed_at'] = now.astimezone(timezone.utc).isoformat()
        result.append(r)
        count += 1
    return result, count


def load(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise ValueError('lineup archive must be a list')
    out = []
    for row in data:
        cleaned = validate(row)
        observed = _time(row.get('observed_at'))
        cleaned['observed_at'] = observed.isoformat()
        out.append(cleaned)
    return out


def save(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as f:
        temp = f.name
        try:
            json.dump(rows, f, ensure_ascii=False, separators=(',', ':'))
            f.write('\n')
        except BaseException:
            os.unlink(temp)
            raise
    try:
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _fixture_time(value, now):
    if hasattr(value, 'to_pydatetime'):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=now.tzinfo)
    return value.astimezone(timezone.utc)


def context(fx, now, archive):
    """Regular starters from previously observed lineups only, using provider IDs rather than fuzzy names."""
    if PILOT.get(fx.get('div')) != fx.get('country') or now.tzinfo is None:
        return None
    ko = _fixture_time(fx.get('kickoff'), now)
    if ko is None:
        return None
    fid = f"{ko.astimezone(timezone(timedelta(hours=2))):%Y-%m-%d}|{fx['country']}|{fx['home']}|{fx['away']}"
    at = min(now.astimezone(timezone.utc), ko)
    # Only observations known by this scan; never associate a mismatched kickoff.
    visible = [r for r in archive if _time(r['observed_at']) <= at and r['div'] == fx['div']]
    targets = [r for r in visible if r['fixture_id'] == fid and abs((_time(r['kickoff'])-ko).total_seconds()) < 60]
    current = max(targets, key=lambda r: _time(r['observed_at'])) if targets else None
    # A lineup observed at/after kickoff is not a pre-match lineup signal.
    if current and _time(current['observed_at']) >= ko:
        current = None
    out = {'note': 'Context only; not a model input. Not starting does not mean injured or unavailable.',
           'source': current['source'] if current else None,
           'observed_at': current['observed_at'] if current else None, 'status': 'confirmed' if current else 'not_confirmed'}
    for side in ('home', 'away'):
        name = fx[side]
        identities = {(r['source'], t['id']) for r in visible for t in (r['home'], r['away']) if t['name'] == name}
        if current:
            identity = (current['source'], current[side]['id'])
        elif len(identities) == 1:
            identity = next(iter(identities))
        else:
            out[side] = {'status': 'collecting', 'sample': 0, 'regulars': [], 'not_starting': []}
            continue
        # Keep only the latest revision per match as of this scan, and never use another fixture
        # from the future or one that could still be in progress.
        prior = {}
        for r in visible:
            t = next((t for t in (r['home'], r['away']) if (r['source'], t['id']) == identity), None)
            when = _time(r['kickoff'])
            if t is None or r['fixture_id'] == fid or when >= ko or when + timedelta(hours=2) > at:
                continue
            key = (r['source'], r['source_match_id'])
            if key not in prior or _time(r['observed_at']) > _time(prior[key][0]['observed_at']):
                prior[key] = (r, t)
        last = sorted(prior.values(), key=lambda item: _time(item[0]['kickoff']), reverse=True)[:MAX_HISTORY]
        count = Counter(p['id'] for _, team in last for p in team['starting'])
        names = {}
        for _, team in last:
            for p in team['starting']:
                names.setdefault(p['id'], p['name'])
        regulars = [{'id': pid, 'name': names[pid], 'starts': starts} for pid, starts in count.items()
                    if len(last) >= MIN_HISTORY and starts / len(last) >= REGULAR_SHARE]
        regulars.sort(key=lambda p: (-p['starts'], p['name'], p['id']))
        starting = {p['id'] for p in current[side]['starting']} if current else set()
        out[side] = {'status': 'ok' if len(last) >= MIN_HISTORY else 'collecting', 'sample': len(last),
                     'regulars': regulars, 'not_starting': [p for p in regulars if p['id'] not in starting] if current else []}
    return out


def freeze_evaluations(existing, rows, archive, now, analysis_at=None):
    """Freeze baseline predictions and context only while the fixture is still pre-match.

    This is a research log, not a challenger model or a claimed backtest. Outcomes can be
    joined from the existing result archive once enough prospective observations exist.
    """
    if now.tzinfo is None:
        raise ValueError('evaluation clock requires timezone')
    out = list(existing)
    keys = {(r['fixture_id'], r['source'], r['lineup_observed_at']) for r in out}
    captured = now.astimezone(timezone.utc)
    if analysis_at is not None and (analysis_at.tzinfo is None or analysis_at.utcoffset() is None):
        raise ValueError('analysis clock requires timezone')
    if analysis_at is not None and analysis_at.astimezone(timezone.utc) > captured:
        raise ValueError('future analysis clock cannot be frozen')
    for row in rows:
        ko = _fixture_time(row.fx.get('kickoff'), now)
        if ko is None or captured >= ko or (analysis_at is not None and analysis_at.astimezone(timezone.utc) >= ko):
            continue
        info = context(row.fx, now, archive)
        if not info or info['status'] != 'confirmed':
            continue
        fid = f"{ko.astimezone(timezone(timedelta(hours=2))):%Y-%m-%d}|{row.fx['country']}|{row.fx['home']}|{row.fx['away']}"
        key = (fid, info['source'], info['observed_at'])
        if key in keys:
            continue
        def p(v):
            try:
                v = float(v)
                return v if math.isfinite(v) and 0 <= v <= 1 else None
            except (TypeError, ValueError):
                return None
        x12 = row.extra.x12 or {}
        baseline = {k: p(row.p_model.get(k)) for k in ('O15', 'O25', 'O35', 'BTTS')}
        baseline.update({k: p(x12.get(k)) for k in ('H', 'D', 'A')})
        out.append({'fixture_id': fid, 'kickoff': ko.isoformat(), 'source': info['source'],
                    'lineup_observed_at': info['observed_at'], 'frozen_at': captured.isoformat(),
                    'analysis_at': analysis_at.astimezone(timezone.utc).isoformat() if analysis_at else None,
                    'baseline': baseline, 'context': info})
        keys.add(key)
    return out, len(out) - len(existing)


def load_evaluations(path):
    if not path.exists():
        return []
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, list):
        raise ValueError('evaluation archive must be a list')
    # Validate identity fields before preserving or extending the log.
    for item in result:
        if not isinstance(item, dict) or not all(item.get(k) for k in ('fixture_id', 'source', 'lineup_observed_at')):
            raise ValueError('invalid evaluation archive entry')
    return result


def main():
    ap = argparse.ArgumentParser(description='Import operator-authorized confirmed lineups into the pilot archive')
    ap.add_argument('input', type=Path, help='JSON list of confirmed fixture snapshots')
    ap.add_argument('--archive', type=Path, required=True, help='state/data/lineup-pilot/archive.json')
    ap.add_argument('--rights-confirmed', action='store_true', help='confirm rights for this use and public-state storage')
    args = ap.parse_args()
    if not args.rights_confirmed:
        ap.error('confirm the source permits this use and public-state storage with --rights-confirmed')
    rows, count = capture(load(args.archive), json.loads(args.input.read_text(encoding='utf-8')), datetime.now(timezone.utc))
    save(args.archive, rows)
    print(f'Imported {count} new snapshots; archive contains {len(rows)} snapshots.')


if __name__ == '__main__':
    main()
