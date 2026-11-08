"""Offline point-in-time capture prototype, NOT a live provider integration.

Capture exact bytes returned by a caller-supplied function. UTC timestamps come
from this process's wall clock, never SCAN_NOW or a caller-supplied timestamp.
SHA-256 detects accidental modification but is not a signature or proof of
provider freshness. No network requests, scheduling, selections or publication.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VERSION = 1
MAX_PAYLOAD_BYTES = 25 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
NAME = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$')
PATH = re.compile(r'^/[a-zA-Z0-9_./-]{1,255}$')


class SnapshotError(ValueError):
    """Invalid capture, unavailable snapshot, or failed integrity check."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SnapshotError('timezone-aware datetime required')
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _parse_stamp(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z', value):
        raise SnapshotError('invalid UTC timestamp')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise SnapshotError('invalid UTC timestamp') from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(obj) -> bytes:
    try:
        return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise SnapshotError('invalid canonical JSON') from exc


def _pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise SnapshotError('duplicate JSON key')
        out[k] = v
    return out


def _bad_constant(_):
    raise SnapshotError('non-finite JSON number')


def _decode(raw: bytes):
    try:
        return json.loads(raw.decode('utf-8'), parse_float=Decimal, object_pairs_hook=_pairs, parse_constant=_bad_constant)
    except SnapshotError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise SnapshotError('invalid or ambiguous JSON') from exc


def _pointer(obj, pointer: str):
    """Strict RFC 6901 JSON pointer; no traversal outside the given event."""
    if not isinstance(pointer, str) or (pointer and not pointer.startswith('/')) or len(pointer) > 1024:
        raise SnapshotError('invalid JSON pointer')
    current = obj
    for part in pointer.split('/')[1:] if pointer else ():
        if re.search(r'~(?![01])', part):
            raise SnapshotError('invalid JSON pointer escape')
        key = part.replace('~1', '/').replace('~0', '~')
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and re.fullmatch(r'0|[1-9]\d*', key) and int(key) < len(current):
            current = current[int(key)]
        else:
            raise SnapshotError('JSON pointer does not resolve')
    return current


def _scalar(value, what):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SnapshotError(f'{what} must be a string or integer present in the payload')
    text = str(value)
    if not text.strip() or len(text) > 256 or any(ord(c) < 32 for c in text):
        raise SnapshotError(f'invalid {what}')
    return text


def _status_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if value is None or isinstance(value, (str, int, bool)):
        if isinstance(value, str) and len(value) > 256:
            raise SnapshotError('status value too long')
        return value
    raise SnapshotError('status and update values must be scalar')


def _odds(value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal, str)):
        raise SnapshotError('odds must be a number or numeric string present in the payload')
    try:
        n = Decimal(str(value))
    except InvalidOperation as exc:
        raise SnapshotError('invalid decimal odds') from exc
    if not n.is_finite() or n <= 1 or len(str(value)) > 64:
        raise SnapshotError('decimal odds must be finite and greater than one')
    # Do not round or turn an absent quote into zero. This is a raw observation,
    # not proof that the outcome is active, tradable, current or eligible.
    return str(value)


def extract_claims(raw: bytes, event_specs: list[dict]) -> dict:
    """Extract event IDs and odds using explicit pointers into source JSON.

    Market, outcome and odds are resolved inside their parent event, market and
    outcome objects. Pointers are stored with values for review; the code does
    not infer provider schemas or verify that a quoted outcome is active.
    """
    if not isinstance(event_specs, list) or len(event_specs) > 10000:
        raise SnapshotError('event specs must be a bounded list')
    if not event_specs:
        return {'events': []}
    payload = _decode(raw)
    output, event_pointers = [], set()
    for spec in event_specs:
        if not isinstance(spec, dict) or set(spec) != {'event_pointer', 'event_id_pointer', 'quotes'}:
            raise SnapshotError('invalid event spec')
        event_pointer, id_pointer, quotes = spec['event_pointer'], spec['event_id_pointer'], spec['quotes']
        if not isinstance(event_pointer, str):
            raise SnapshotError('invalid event pointer')
        if event_pointer in event_pointers:
            raise SnapshotError('duplicate event pointer')
        event_pointers.add(event_pointer)
        event = _pointer(payload, event_pointer)
        if not isinstance(event, dict):
            raise SnapshotError('event pointer must resolve to an object')
        event_id = _scalar(_pointer(event, id_pointer), 'event ID')
        if not isinstance(quotes, list) or len(quotes) > 10000:
            raise SnapshotError('quotes must be a bounded list')
        out_quotes, seen = [], set()
        for q in quotes:
            required = {'market_pointer', 'market_id_pointer', 'outcome_pointer', 'outcome_name_pointer', 'odds_pointer'}
            optional = {'specifier_pointer', 'market_status_pointer', 'outcome_status_pointer', 'provider_updated_at_pointer'}
            if not isinstance(q, dict) or not required <= set(q) or set(q) - (required | optional):
                raise SnapshotError('invalid quote spec')
            market = _pointer(event, q['market_pointer'])
            if not isinstance(market, dict):
                raise SnapshotError('market pointer must resolve to an object')
            selection = _pointer(market, q['outcome_pointer'])
            if not isinstance(selection, dict):
                raise SnapshotError('outcome pointer must resolve to an object')
            mid = _scalar(_pointer(market, q['market_id_pointer']), 'market ID')
            outcome = _scalar(_pointer(selection, q['outcome_name_pointer']), 'outcome')
            price = _odds(_pointer(selection, q['odds_pointer']))
            specifier = _scalar(_pointer(market, q['specifier_pointer']), 'specifier') if 'specifier_pointer' in q else None
            key = (mid, outcome, specifier)
            if key in seen:
                raise SnapshotError('ambiguous duplicate market outcome')
            seen.add(key)
            out_quotes.append({'market_id': mid, 'outcome': outcome, 'specifier': specifier,
                               'decimal_odds': price,
                               'market_status': _status_value(_pointer(market, q['market_status_pointer'])) if 'market_status_pointer' in q else None,
                               'outcome_status': _status_value(_pointer(selection, q['outcome_status_pointer'])) if 'outcome_status_pointer' in q else None,
                               'provider_updated_at': _status_value(_pointer(selection, q['provider_updated_at_pointer'])) if 'provider_updated_at_pointer' in q else None,
                               'pointers': dict(q)})
        output.append({'event_id': event_id, 'event_pointer': event_pointer,
                       'event_id_pointer': id_pointer, 'quotes': out_quotes})
    return {'events': output}


def _context(provider, dataset, request_path, origin, source_timezone, requested_offset_minutes, content_type):
    if not isinstance(provider, str) or not NAME.fullmatch(provider) or not isinstance(dataset, str) or not NAME.fullmatch(dataset):
        raise SnapshotError('provider and dataset must be simple nonsecret identifiers')
    if not isinstance(request_path, str) or not PATH.fullmatch(request_path) or '..' in request_path.split('/'):
        raise SnapshotError('request path must be a path only, without query, credentials, or fragment')
    if origin not in ('synthetic', 'file_import', 'provider_response'):
        raise SnapshotError('invalid capture origin')
    if source_timezone is not None:
        if not isinstance(source_timezone, str) or len(source_timezone) > 64:
            raise SnapshotError('invalid source timezone')
        try:
            ZoneInfo(source_timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise SnapshotError('invalid source timezone') from exc
    if requested_offset_minutes is not None and (isinstance(requested_offset_minutes, bool) or not isinstance(requested_offset_minutes, int) or not -840 <= requested_offset_minutes <= 840):
        raise SnapshotError('requested offset must be whole minutes between -840 and 840')
    if not isinstance(content_type, str) or not re.fullmatch(r'[a-z0-9.+-]+/[a-z0-9.+-]+', content_type) or len(content_type) > 80:
        raise SnapshotError('invalid content type')
    return {'provider': provider, 'dataset': dataset, 'request_path': request_path, 'origin': origin,
            'source_timezone_declared': source_timezone, 'requested_offset_minutes': requested_offset_minutes,
            'content_type': content_type}


def _write_exclusive(path: Path, data: bytes):
    # O_EXCL prevents an existing snapshot file from being replaced.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def capture(root: Path, read_payload: Callable[[], bytes], *, provider: str, dataset: str,
            request_path: str, origin: str, source_timezone: str | None = None,
            requested_offset_minutes: int | None = None, content_type: str = 'application/json',
            event_specs: list[dict] | None = None) -> Path:
    """Capture an observed payload exactly once; no network is performed here.

    The callback is invoked once. Start/end wall-clock readings surround it; if
    the callback reads an old file, these are import times, not provider fetch or
    historical availability times. Invalid captures never create a committed
    manifest. A crash may leave an incomplete directory, which the reader rejects.
    """
    context = _context(provider, dataset, request_path, origin, source_timezone, requested_offset_minutes, content_type)
    if not callable(read_payload):
        raise SnapshotError('read_payload must be callable')
    start = _now_utc()
    raw = read_payload()
    end = _now_utc()
    started, captured = _stamp(start), _stamp(end)
    if end < start:
        raise SnapshotError('system wall clock moved backwards during capture')
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_PAYLOAD_BYTES:
        raise SnapshotError('payload must be nonempty bounded bytes')
    if event_specs is None:
        event_specs = []
    if not isinstance(event_specs, list):
        raise SnapshotError('event specs must be a bounded list')
    if event_specs and content_type != 'application/json':
        raise SnapshotError('JSON event pointers require application/json')
    claims = extract_claims(raw, event_specs)
    claims_raw = _json_bytes(claims)
    if len(claims_raw) > MAX_METADATA_BYTES:
        raise SnapshotError('extracted claims are too large')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    ident = uuid.uuid4().hex
    dest = root / ident
    dest.mkdir(mode=0o700)  # exclusive; an existing directory is never replaced
    meta = {'version': VERSION, 'snapshot_id': ident, 'capture_started_at_utc': started,
            'captured_at_utc': captured, 'context': context,
            'payload': {'file': 'payload.bin', 'sha256': _sha(raw), 'bytes': len(raw)},
            'claims': {'file': 'claims.json', 'sha256': _sha(claims_raw), 'bytes': len(claims_raw)}}
    manifest = _json_bytes({'metadata': meta, 'metadata_sha256': _sha(_json_bytes(meta))})
    _write_exclusive(dest / 'payload.bin', raw)
    _write_exclusive(dest / 'claims.json', claims_raw)
    _write_exclusive(dest / 'manifest.pending', manifest)
    # Atomic publication of the manifest, with exclusive creation. Directory
    # remains incomplete and unusable if any preceding write fails.
    os.link(dest / 'manifest.pending', dest / 'manifest.json')
    (dest / 'manifest.pending').unlink()
    # Observe the clock only after payload, claims and manifest are materialized.
    # This is the earliest admissible as-of time; collection completion alone
    # may precede extraction and persistence by an arbitrary duration.
    observed = _now_utc()
    if observed < end:
        raise SnapshotError('system wall clock moved backwards before availability witness')
    witness = {'version': VERSION, 'snapshot_id': ident, 'manifest_sha256': _sha(manifest),
               'available_at_utc': _stamp(observed)}
    receipt = _json_bytes({'witness': witness, 'witness_sha256': _sha(_json_bytes(witness))})
    _write_exclusive(dest / 'receipt.pending', receipt)
    os.link(dest / 'receipt.pending', dest / 'receipt.json')
    (dest / 'receipt.pending').unlink()
    return dest


def _read_bounded(path: Path, limit: int) -> bytes:
    try:
        # NOFOLLOW protects the final component where the OS supports it. It
        # does not protect parent paths or against a hostile concurrent writer.
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise SnapshotError('unsafe snapshot file')
            raw = f.read(limit + 1)
        if len(raw) > limit:
            raise SnapshotError('oversized snapshot file')
        return raw
    except OSError as exc:
        raise SnapshotError('snapshot file unreadable') from exc


def load_as_of(path: Path, cutoff: datetime, *, allow_non_provider: bool = False,
               expected_receipt_sha256: str | None = None) -> dict:
    """Verify and load a committed snapshot observed no later than cutoff.

    By default synthetic/file imports cannot be used as provider captures. The
    origin label is caller-supplied and is not cryptographic proof; replay code
    still needs a trusted adapter, secure clock and independently held hashes.
    """
    if type(allow_non_provider) is not bool:
        raise SnapshotError('allow_non_provider must be a boolean')
    if not isinstance(cutoff, datetime) or cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise SnapshotError('cutoff must be a timezone-aware datetime')
    path = Path(path)
    if path.is_symlink() or not path.is_dir() or not re.fullmatch(r'[0-9a-f]{32}', path.name):
        raise SnapshotError('invalid snapshot directory')
    manifest_raw = _read_bounded(path / 'manifest.json', MAX_METADATA_BYTES)
    doc = _decode(manifest_raw)
    if _json_bytes(doc) != manifest_raw:
        raise SnapshotError('manifest is not canonical')
    if not isinstance(doc, dict) or set(doc) != {'metadata', 'metadata_sha256'} or not isinstance(doc['metadata'], dict):
        raise SnapshotError('invalid manifest')
    meta = doc['metadata']
    if _sha(_json_bytes(meta)) != doc['metadata_sha256']:
        raise SnapshotError('metadata integrity check failed')
    if set(meta) != {'version', 'snapshot_id', 'capture_started_at_utc', 'captured_at_utc', 'context', 'payload', 'claims'}:
        raise SnapshotError('invalid metadata fields')
    if type(meta.get('version')) is not int or meta.get('version') != VERSION or meta.get('snapshot_id') != path.name:
        raise SnapshotError('snapshot schema or ID mismatch')
    started, captured = _parse_stamp(meta.get('capture_started_at_utc')), _parse_stamp(meta.get('captured_at_utc'))
    if captured < started:
        raise SnapshotError('capture timestamp ordering invalid')
    receipt_raw = _read_bounded(path / 'receipt.json', MAX_METADATA_BYTES)
    receipt_hash = _sha(receipt_raw)
    if expected_receipt_sha256 is not None:
        if not isinstance(expected_receipt_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_receipt_sha256):
            raise SnapshotError('invalid external receipt hash')
        if receipt_hash != expected_receipt_sha256:
            raise SnapshotError('externally anchored receipt hash mismatch')
    receipt = _decode(receipt_raw)
    if _json_bytes(receipt) != receipt_raw or not isinstance(receipt, dict) or set(receipt) != {'witness', 'witness_sha256'}:
        raise SnapshotError('invalid availability receipt')
    witness = receipt['witness']
    if not isinstance(witness, dict) or set(witness) != {'version', 'snapshot_id', 'manifest_sha256', 'available_at_utc'}:
        raise SnapshotError('invalid availability witness')
    if (_sha(_json_bytes(witness)) != receipt['witness_sha256'] or type(witness['version']) is not int or
            witness['version'] != VERSION or witness['snapshot_id'] != path.name or witness['manifest_sha256'] != _sha(manifest_raw)):
        raise SnapshotError('availability witness integrity failed')
    available = _parse_stamp(witness['available_at_utc'])
    if available < captured:
        raise SnapshotError('availability precedes response capture')
    if available > cutoff.astimezone(timezone.utc):
        raise SnapshotError('snapshot was not yet available at cutoff')
    context = meta.get('context')
    if not isinstance(context, dict):
        raise SnapshotError('invalid capture context')
    checked = _context(context.get('provider'), context.get('dataset'), context.get('request_path'), context.get('origin'),
                       context.get('source_timezone_declared'), context.get('requested_offset_minutes'), context.get('content_type'))
    if context != checked:
        raise SnapshotError('invalid capture context fields')
    if context['origin'] != 'provider_response' and not allow_non_provider:
        raise SnapshotError('non-provider import is not eligible for provider replay')
    data = {}
    for key, fname, limit in (('payload','payload.bin',MAX_PAYLOAD_BYTES),('claims','claims.json',MAX_METADATA_BYTES)):
        record = meta.get(key)
        if not isinstance(record, dict) or set(record) != {'file', 'sha256', 'bytes'} or record['file'] != fname:
            raise SnapshotError('invalid file metadata')
        raw = _read_bounded(path / fname, limit)
        if type(record['bytes']) is not int or not raw or record['bytes'] != len(raw) or _sha(raw) != record['sha256']:
            raise SnapshotError(f'{key} integrity check failed')
        data[key] = raw
    claims = _decode(data['claims'])
    if not isinstance(claims, dict) or set(claims) != {'events'} or not isinstance(claims['events'], list):
        raise SnapshotError('invalid claims')
    # Re-resolve every claim from the source payload; this catches accidental
    # extraction/serialization drift as well as a modified derived claims file.
    specs = []
    for event in claims['events']:
        if not isinstance(event, dict) or not isinstance(event.get('quotes'), list):
            raise SnapshotError('invalid event claims')
        try:
            specs.append({'event_pointer': event['event_pointer'], 'event_id_pointer': event['event_id_pointer'],
                          'quotes': [q['pointers'] for q in event['quotes']]})
        except (KeyError, TypeError) as exc:
            raise SnapshotError('invalid event claim pointers') from exc
    if extract_claims(data['payload'], specs) != claims:
        raise SnapshotError('claims do not match payload')
    return {'metadata': meta, 'availability': witness, 'payload': data['payload'], 'claims': claims,
            'receipt_sha256': receipt_hash}
