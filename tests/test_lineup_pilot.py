from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
import lineup_pilot as lp

SAST = timezone(timedelta(hours=2))
START = datetime(2026, 9, 1, 15, tzinfo=SAST)


def players(prefix, excluded=None):
    return [{'id': f'{prefix}{i}', 'name': f'{prefix} Player {i}'} for i in range(11) if i != excluded]


def record(when, match_id, home='Home', away='Away', div='E0', country='England'):
    return {'fixture_id': f'{when:%Y-%m-%d}|{country}|{home}|{away}', 'div': div, 'country': country,
            'kickoff': when.isoformat(), 'source': 'Authorized example', 'source_match_id': match_id,
            'status': 'confirmed', 'home': {'name': home, 'id': 'team-h', 'starting': players('h')},
            'away': {'name': away, 'id': 'team-a', 'starting': players('a')}}


def fx(when, **updates):
    return {'kickoff': when, 'country': 'England', 'div': 'E0', 'home': 'Home', 'away': 'Away'} | updates


def archive_before(target):
    archive = []
    for i in range(4):
        when = target - timedelta(days=7 * (4-i))
        archive, count = lp.capture(archive, [record(when, str(i))], when + timedelta(hours=3))
        assert count == 1
    return archive


def test_confirmed_starters_only_and_timestamps_cannot_be_supplied():
    target = START + timedelta(days=28)
    a = archive_before(target)
    r = record(target, 'current')
    r['observed_at'] = '2000-01-01T00:00:00+00:00'  # ignored, never backdated
    r['home']['starting'][-1] = {'id': 'new', 'name': 'Replacement'}
    now = target - timedelta(minutes=30)
    a, count = lp.capture(a, [r], now)
    assert count == 1
    c = lp.context(fx(target), now, a)
    assert c['status'] == 'confirmed'
    assert c['observed_at'] == now.astimezone(timezone.utc).isoformat()
    assert c['home']['sample'] == 4
    assert [p['id'] for p in c['home']['not_starting']] == ['h10']
    assert not c['away']['not_starting']
    a2, count = lp.capture(a, [r], now + timedelta(minutes=5))
    assert a2 == a and count == 0  # retry does not change observation time


def test_missing_or_late_target_never_claims_absences():
    target = START + timedelta(days=28)
    a = archive_before(target)
    early = lp.context(fx(target), target-timedelta(hours=1), a)
    assert early['status'] == 'not_confirmed'
    assert early['home']['sample'] == 4 and early['home']['not_starting'] == []
    late = record(target, 'late')
    a, _ = lp.capture(a, [late], target+timedelta(minutes=20))
    assert lp.context(fx(target), target+timedelta(minutes=30), a)['status'] == 'not_confirmed'
    assert lp.context(fx(target+timedelta(days=1)), target-timedelta(hours=1), a)['status'] == 'not_confirmed'


def test_never_use_future_observations_or_unfinished_prior_games():
    target = START + timedelta(days=28)
    a = archive_before(target)
    later = record(target-timedelta(days=1), 'late-history')
    a, _ = lp.capture(a, [later], target+timedelta(hours=5))
    now = target - timedelta(minutes=30)
    c = lp.context(fx(target), now, a)
    assert c['home']['sample'] == 4  # later historical import was not known
    same_day = record(target-timedelta(hours=1), 'in-progress')
    a, _ = lp.capture(a, [same_day], target-timedelta(minutes=50))
    c = lp.context(fx(target), now, a)
    assert c['home']['sample'] == 4  # prior kickoff is still in progress


def test_incomplete_conflicting_and_out_of_scope_rejected():
    r = record(START, 'x')
    r['home']['starting'].pop()
    with pytest.raises(ValueError, match='exactly 11'):
        lp.capture([], [r], START)
    r = record(START, 'x'); r['status'] = 'predicted'
    with pytest.raises(ValueError, match='only confirmed'):
        lp.capture([], [r], START)
    r = record(START, 'x', country='England', div='cup')
    with pytest.raises(ValueError, match='outside'):
        lp.capture([], [r], START)
    r = record(START, 'x'); r['kickoff'] = '2026-09-01T15:00:00'
    with pytest.raises(ValueError, match='timezone'):
        lp.capture([], [r], START)
    r = record(START, 'x'); r['fixture_id'] = 'different'
    with pytest.raises(ValueError, match='fixture_id'):
        lp.capture([], [r], START)
    r = record(START, 'x'); r['home']['starting'][1]['id'] = r['home']['starting'][0]['id']
    with pytest.raises(ValueError, match='distinct'):
        lp.capture([], [r], START)
    assert lp.context(fx(START, div='E1'), START, []) is None


def test_ambiguous_identity_and_small_samples_are_never_confident():
    target = START + timedelta(days=28)
    a = archive_before(target)[:2]
    c = lp.context(fx(target), target-timedelta(hours=1), a)
    assert c['home']['status'] == 'collecting' and not c['home']['regulars']
    alt = record(START + timedelta(days=3), 'other')
    alt['source'] = 'Other authorized provider'
    a, _ = lp.capture(a, [alt], START+timedelta(days=4))
    c = lp.context(fx(target), target-timedelta(hours=1), a)
    assert c['home']['sample'] == 0  # no fuzzy cross-source identity guess


def test_archive_roundtrip_and_atomic_batch_validation(tmp_path):
    archive = tmp_path / 'lineup-pilot' / 'archive.json'
    a, _ = lp.capture([], [record(START, 'x')], START-timedelta(minutes=30))
    lp.save(archive, a)
    assert lp.load(archive) == a
    before = archive.read_text()
    bad = record(START, 'bad'); bad['away']['starting'] = []
    with pytest.raises(ValueError):
        lp.capture(a, [record(START+timedelta(days=1), 'y'), bad], START)
    assert archive.read_text() == before
    # A duplicate provider match id may not silently attach to another match.
    with pytest.raises(ValueError, match='conflicts'):
        lp.capture(a, [record(START+timedelta(days=7), 'x')], START)


def test_freeze_baseline_only_pre_match_and_never_overwrites():
    from types import SimpleNamespace
    target = START + timedelta(days=28)
    a = archive_before(target)
    a, _ = lp.capture(a, [record(target, 'current')], target-timedelta(minutes=30))
    row = SimpleNamespace(fx=fx(target), p_model={'O15': .8, 'O25': .6, 'O35': .4, 'BTTS': .55},
                          extra=SimpleNamespace(x12={'H': .5, 'D': .3, 'A': .2}))
    saved, count = lp.freeze_evaluations([], [row], a, target-timedelta(minutes=25), analysis_at=target-timedelta(minutes=40))
    assert count == 1
    assert saved[0]['baseline']['O15'] == .8
    assert saved[0]['analysis_at'] == (target-timedelta(minutes=40)).astimezone(timezone.utc).isoformat()
    assert saved[0]['context']['status'] == 'confirmed'
    row.p_model['O15'] = .99
    repeat, count = lp.freeze_evaluations(saved, [row], a, target-timedelta(minutes=10))
    assert count == 0 and repeat[0]['baseline']['O15'] == .8
    late, count = lp.freeze_evaluations([], [row], a, target+timedelta(seconds=1))
    assert not late and count == 0
    with pytest.raises(ValueError, match='future analysis clock'):
        lp.freeze_evaluations([], [row], a, target-timedelta(minutes=25), analysis_at=target+timedelta(days=1))


def test_cli_requires_rights_and_stamps_receipt_time(tmp_path):
    import subprocess
    import sys
    inp = tmp_path / 'input.json'
    archive = tmp_path / 'archive.json'
    inp.write_text(json.dumps([record(START, 'x')]))
    cmd = [sys.executable, str(Path(lp.__file__)), str(inp), '--archive', str(archive)]
    denied = subprocess.run(cmd, capture_output=True, text=True)
    assert denied.returncode != 0 and not archive.exists()
    before = datetime.now(timezone.utc)
    accepted = subprocess.run(cmd + ['--rights-confirmed'], capture_output=True, text=True)
    assert accepted.returncode == 0
    observed = lp._time(lp.load(archive)[0]['observed_at'])
    assert before <= observed <= datetime.now(timezone.utc)
