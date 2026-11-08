"""Offline-only tests of immutable observations; no provider or network access."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import pytest
from research.point_in_time import snapshots as s

NOW=datetime(2026,11,4,10,15,tzinfo=timezone.utc)
RAW=b'{"data":{"events":[{"eventId":"123", "markets":[{"id":"18", "specifier":"total=1.5", "status":0, "outcomes":[{"desc":"Over", "odds":1.1599, "isActive":1},{"desc":"Under", "odds":"4.50", "isActive":0}]}]}]}}'
EVENTS=[{'event_pointer':'/data/events/0', 'event_id_pointer':'/eventId', 'quotes':[
    {'market_pointer':'/markets/0', 'market_id_pointer':'/id', 'outcome_pointer':'/outcomes/0',
     'outcome_name_pointer':'/desc', 'odds_pointer':'/odds', 'specifier_pointer':'/specifier',
     'market_status_pointer':'/status', 'outcome_status_pointer':'/isActive'},
    {'market_pointer':'/markets/0', 'market_id_pointer':'/id', 'outcome_pointer':'/outcomes/1',
     'outcome_name_pointer':'/desc', 'odds_pointer':'/odds', 'specifier_pointer':'/specifier',
     'outcome_status_pointer':'/isActive'}]}]


def make(tmp_path,monkeypatch,origin='synthetic',raw=RAW,specs=EVENTS):
    now=iter([NOW,NOW+timedelta(seconds=3),NOW+timedelta(seconds=4)])
    monkeypatch.setattr(s,'_now_utc',lambda:next(now))
    return s.capture(tmp_path,lambda:raw,provider='sportybet',dataset='upcoming',request_path='/factsCenter/events',
                     origin=origin,source_timezone='Africa/Johannesburg',requested_offset_minutes=120,event_specs=specs)


def test_capture_preserves_raw_hash_exact_odds_status_and_timezone(tmp_path,monkeypatch):
    monkeypatch.setenv('SCAN_NOW','2020-01-01 00:00')
    path=make(tmp_path,monkeypatch)
    d=s.load_as_of(path,NOW+timedelta(seconds=4),allow_non_provider=True)
    assert d['availability']['available_at_utc']=='2026-11-04T10:15:04.000000Z'
    assert d['payload']==RAW and d['metadata']['captured_at_utc']=='2026-11-04T10:15:03.000000Z'
    assert d['metadata']['capture_started_at_utc']=='2026-11-04T10:15:00.000000Z'
    assert d['metadata']['context']['requested_offset_minutes']==120
    assert d['metadata']['context']['source_timezone_declared']=='Africa/Johannesburg'
    e=d['claims']['events'][0]
    assert e['event_id']=='123' and e['quotes'][0]['decimal_odds']=='1.1599'
    assert e['quotes'][1]['decimal_odds']=='4.50' and e['quotes'][1]['outcome_status']==0
    assert e['quotes'][0]['market_status']==0 and e['quotes'][0]['specifier']=='total=1.5'
    assert (path/'payload.bin').stat().st_mode & 0o777 == 0o600
    with pytest.raises(s.SnapshotError,match='non-provider'):
        s.load_as_of(path,NOW+timedelta(days=1))


def test_cutoff_excludes_later_capture_even_same_day(tmp_path,monkeypatch):
    path=make(tmp_path,monkeypatch,origin='provider_response')
    with pytest.raises(s.SnapshotError,match='not yet available'):
        s.load_as_of(path,NOW+timedelta(seconds=3))
    assert s.load_as_of(path,(NOW+timedelta(seconds=4)).astimezone(ZoneInfo('Africa/Johannesburg')))['payload']==RAW
    with pytest.raises(s.SnapshotError,match='timezone-aware'):
        s.load_as_of(path,datetime(2026,11,4,23))


def test_local_import_is_not_a_historical_provider_observation(tmp_path,monkeypatch):
    path=make(tmp_path,monkeypatch,origin='file_import')
    with pytest.raises(s.SnapshotError,match='non-provider'):
        s.load_as_of(path,NOW+timedelta(days=1))
    assert s.load_as_of(path,NOW+timedelta(days=1),allow_non_provider=True)['metadata']['context']['origin']=='file_import'


@pytest.mark.parametrize('file', ['payload.bin','claims.json','manifest.json','receipt.json'])
def test_tampering_is_detected(tmp_path,monkeypatch,file):
    path=make(tmp_path,monkeypatch,origin='provider_response')
    p=path/file
    p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(s.SnapshotError):s.load_as_of(path,NOW+timedelta(days=1))


def test_claims_rechecked_against_original_even_if_hashes_rewritten(tmp_path,monkeypatch):
    path=make(tmp_path,monkeypatch,origin='provider_response')
    claims=json.loads((path/'claims.json').read_text());claims['events'][0]['quotes'][0]['decimal_odds']='1.16'
    contents=s._json_bytes(claims);(path/'claims.json').write_bytes(contents)
    manifest=json.loads((path/'manifest.json').read_text());meta=manifest['metadata']
    meta['claims'].update(bytes=len(contents),sha256=s._sha(contents));manifest['metadata_sha256']=s._sha(s._json_bytes(meta))
    modified=s._json_bytes(manifest);(path/'manifest.json').write_bytes(modified)
    receipt=json.loads((path/'receipt.json').read_text());receipt['witness']['manifest_sha256']=s._sha(modified)
    receipt['witness_sha256']=s._sha(s._json_bytes(receipt['witness']));(path/'receipt.json').write_bytes(s._json_bytes(receipt))
    with pytest.raises(s.SnapshotError,match='claims do not match'):
        s.load_as_of(path,NOW+timedelta(days=1))


def test_missing_fields_and_prices_fail_without_zero_or_fabrication(tmp_path,monkeypatch):
    for bad in (b'null',b'0',b'1',b'NaN',b'"nan"',b'"1.0"'):
        raw=RAW.replace(b'1.1599',bad)
        with pytest.raises(s.SnapshotError):make(tmp_path,monkeypatch,raw=raw)
    broken=[{'event_pointer':'/data/events/9','event_id_pointer':'/eventId','quotes':[]}]
    with pytest.raises(s.SnapshotError,match='does not resolve'):make(tmp_path,monkeypatch,specs=broken)
    assert not list(tmp_path.iterdir())


def test_pointers_cannot_cross_event_market_or_outcome():
    spec=[dict(EVENTS[0],quotes=[dict(EVENTS[0]['quotes'][0],outcome_pointer='/markets/1/outcomes/0')])]
    with pytest.raises(s.SnapshotError,match='does not resolve'):s.extract_claims(RAW,spec)
    with pytest.raises(s.SnapshotError,match='duplicate JSON key'):
        s.extract_claims(b'{"x":1,"x":2}',EVENTS)
    with pytest.raises(s.SnapshotError):s._pointer({'a/b':1},'/a~2b')
    assert s._pointer({'a/b':{'~x':3}},'/a~1b/~0x')==3


def test_incomplete_and_colliding_snapshots_never_replace_data(tmp_path,monkeypatch):
    monkeypatch.setattr(s.uuid,'uuid4',lambda:SimpleNamespace(hex='a'*32))
    path=make(tmp_path,monkeypatch); original=(path/'payload.bin').read_bytes()
    with pytest.raises(FileExistsError):make(tmp_path,monkeypatch,raw=b'{"other":true}',specs=[])
    assert (path/'payload.bin').read_bytes()==original
    (path/'manifest.json').unlink()
    with pytest.raises(s.SnapshotError):s.load_as_of(path,NOW+timedelta(days=1),allow_non_provider=True)


def test_capture_failure_never_commits_a_snapshot(tmp_path,monkeypatch):
    original=s._write_exclusive
    def fail(path,data):
        if path.name=='claims.json':raise OSError('simulated disk failure')
        return original(path,data)
    monkeypatch.setattr(s,'_write_exclusive',fail)
    with pytest.raises(OSError):make(tmp_path,monkeypatch)
    partial=next(tmp_path.iterdir())
    assert not (partial/'manifest.json').exists()
    with pytest.raises(s.SnapshotError):s.load_as_of(partial,NOW+timedelta(days=1),allow_non_provider=True)


def test_bad_context_clock_and_callback_fail_closed(tmp_path,monkeypatch):
    with pytest.raises(s.SnapshotError,match='query'):
        s.capture(tmp_path,lambda:RAW,provider='sportybet',dataset='feed',request_path='/feed?token=secret',origin='synthetic')
    with pytest.raises(s.SnapshotError,match='timezone'):
        s.capture(tmp_path,lambda:RAW,provider='sportybet',dataset='feed',request_path='/feed',origin='synthetic',source_timezone='Unknown/Zone')
    with pytest.raises(s.SnapshotError,match='offset'):
        s.capture(tmp_path,lambda:RAW,provider='sportybet',dataset='feed',request_path='/feed',origin='synthetic',requested_offset_minutes=1000)
    times=iter([NOW,NOW-timedelta(seconds=1)]);monkeypatch.setattr(s,'_now_utc',lambda:next(times))
    with pytest.raises(s.SnapshotError,match='backwards'):
        s.capture(tmp_path,lambda:RAW,provider='sportybet',dataset='feed',request_path='/feed',origin='synthetic')
    assert not list(tmp_path.iterdir())


def test_csv_raw_snapshot_has_no_invented_event_or_price(tmp_path,monkeypatch):
    path=make(tmp_path,monkeypatch,raw=b'date,home\n2026-10-01,A\n',specs=[])
    d=s.load_as_of(path,NOW+timedelta(days=1),allow_non_provider=True)
    assert d['claims']=={'events':[]} and d['payload'].startswith(b'date')


def test_external_anchor_and_untrusted_rehash(tmp_path,monkeypatch):
    path=make(tmp_path,monkeypatch,origin='provider_response')
    first=s.load_as_of(path,NOW+timedelta(days=1)); anchor=first['receipt_sha256']
    assert len(anchor)==64
    assert s.load_as_of(path,NOW+timedelta(days=1),expected_receipt_sha256=anchor)['payload']==RAW
    with pytest.raises(s.SnapshotError,match='externally anchored'):
        s.load_as_of(path,NOW+timedelta(days=1),expected_receipt_sha256='0'*64)
    (path/'receipt.json').unlink()
    with pytest.raises(s.SnapshotError):s.load_as_of(path,NOW+timedelta(days=1))


def test_one_callback_and_omitted_unknown_fields(tmp_path,monkeypatch):
    readings=iter([NOW,NOW+timedelta(seconds=1),NOW+timedelta(seconds=2)])
    monkeypatch.setattr(s,'_now_utc',lambda:next(readings))
    calls=[]
    def read():
        calls.append(1)
        return RAW
    path=s.capture(tmp_path,read,provider='test',dataset='feed',request_path='/feed',origin='synthetic')
    assert len(calls)==1
    d=s.load_as_of(path,NOW+timedelta(days=1),allow_non_provider=True)
    assert d['metadata']['context']['source_timezone_declared'] is None
    assert d['metadata']['context']['requested_offset_minutes'] is None
    assert d['claims']['events']==[]


def test_bad_spec_type_and_backwards_availability(tmp_path,monkeypatch):
    with pytest.raises(s.SnapshotError,match='event specs'):
        make(tmp_path,monkeypatch,specs={})
    readings=iter([NOW,NOW+timedelta(seconds=2),NOW+timedelta(seconds=1)])
    monkeypatch.setattr(s,'_now_utc',lambda:next(readings))
    with pytest.raises(s.SnapshotError,match='backwards before availability'):
        s.capture(tmp_path,lambda:RAW,provider='test',dataset='feed',request_path='/feed',origin='synthetic')
    partial=next(tmp_path.iterdir())
    with pytest.raises(s.SnapshotError):s.load_as_of(partial,NOW+timedelta(days=1),allow_non_provider=True)
