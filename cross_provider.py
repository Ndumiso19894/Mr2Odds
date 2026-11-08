"""Review-gated cross-provider identity matching on in-memory prediction history.

An exact match is *candidate evidence*, not a provider-issued cross-ID. No pair
is merged unless explicitly reviewed, recorded in the approvals file, and still
passes all identity/ambiguity checks. Raw archives and settlement stay intact.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

APPROVALS_FILE = Path(__file__).with_name('history_reconciliation_approvals.json')
STATS = ('hth', 'hta', 'hxg', 'axg', 'hs', 'as', 'hst', 'ast', 'hsoff', 'asoff',
         'hc', 'ac', 'hy', 'ay', 'hr', 'ar', 'hposs', 'aposs', 'hf', 'af')
IDENTITY = ('country', 'div', 'league', 'date', 'home', 'away', 'home_id', 'away_id', 'eid', 'hg', 'ag', '_history_kickoff', '_history_kickoff_tz')


def _plain(value):
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, 'item'):
        return value.item()
    return value


def _str(value):
    v = _plain(value)
    return '' if v is None else str(v).strip()


def _norm(value):
    text = unicodedata.normalize('NFKD', _str(value)).encode('ascii', 'ignore').decode().casefold()
    return ' '.join(re.findall(r'[a-z0-9]+', text))


def _provider(row):
    return 'livescore' if _str(row.get('div')).startswith('LS:') else 'football_data'


def _record(row):
    fields = IDENTITY + STATS + ('referee', '_source_ref', '_history_sources', '_history_conflicts')
    return {k: _plain(row.get(k)) for k in fields if k in row.index}


def _candidate_id(fd, ls):
    # Excludes statistics (which may be corrected) but binds score, teams,
    # competition, IDs, date and any known kickoff. Changes require re-review.
    pair = [{k: _plain(row.get(k)) for k in IDENTITY} for row in (fd, ls)]
    data = json.dumps(pair, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def load_approvals(path=APPROVALS_FILE):
    """Fail closed on malformed, duplicated or unreviewed approvals."""
    try:
        obj = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(obj, dict) or obj.get('version') != 1 or not isinstance(obj.get('approvals'), list):
            raise ValueError('invalid approval file schema')
        approved = {}
        for x in obj['approvals']:
            if not isinstance(x, dict):
                raise ValueError('invalid approval entry')
            key = x.get('candidate_id')
            if (not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key) or key in approved
                    or not _str(x.get('reviewed_by')) or not _str(x.get('rationale')) or not _str(x.get('evidence'))):
                raise ValueError('approval needs unique candidate_id, reviewer, rationale and identity evidence')
            approved[key] = {'reviewed_by': x['reviewed_by'], 'rationale': x['rationale'], 'evidence': x['evidence']}
        return approved
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f'Cross-provider approvals unavailable or invalid: {exc}') from exc


def candidates(rows: pd.DataFrame):
    """Yield possible duplicates as (review entry, FD position, LS position).

    Normalized names find review candidates only. One-to-one raw exact names,
    country/competition, score and any mutually available kickoff must all agree
    for a pair to be eligible. Duplicate or missing LS IDs are not eligible.
    """
    required = {'country', 'div', 'league', 'date', 'home', 'away', 'hg', 'ag'}
    if rows.empty or not required <= set(rows):
        return
    data = rows.reset_index(drop=True)
    groups = defaultdict(lambda: [[], []])
    # itertuples is faster on the large archive and still permits absent columns.
    for i, row in enumerate(data.itertuples(index=False, name=None)):
        v = dict(zip(data.columns, row))
        date = _plain(v.get('date'))
        if not date:
            continue
        key = (_norm(v.get('country')), str(date)[:10], _norm(v.get('home')), _norm(v.get('away')))
        if not all(key):
            continue
        groups[key][1 if _provider(v) == 'livescore' else 0].append(i)
    for key, (fds, worlds) in groups.items():
        if not fds or not worlds:
            continue
        # Show all involved identities; never take a best match in a collision.
        if len(fds) != 1 or len(worlds) != 1:
            yield ({'status': 'ambiguous_multiplicity', 'key': list(key),
                    'football_data': [_record(data.iloc[i]) for i in fds],
                    'livescore': [_record(data.iloc[i]) for i in worlds]}, None, None)
            continue
        fi, li = fds[0], worlds[0]
        fd, ls = data.iloc[fi], data.iloc[li]
        reasons = []
        if any(_str(fd.get(c)) != _str(ls.get(c)) for c in ('country', 'home', 'away')):
            reasons.append('identity_alias_unverified')
        if not _str(fd.get('league')) or _str(fd.get('league')) != _str(ls.get('league')):
            reasons.append('competition_alias_unverified')
        if any(_plain(fd.get(c)) is None or _plain(fd.get(c)) != _plain(ls.get(c)) for c in ('hg', 'ag')):
            reasons.append('score_conflict_or_missing')
        if not all(_str(ls.get(c)) and _str(ls.get(c)).casefold() not in ('nan', 'none') for c in ('eid', 'home_id', 'away_id')):
            reasons.append('missing_livescore_ids')
        k1, k2 = _str(fd.get('_history_kickoff')), _str(ls.get('_history_kickoff'))
        tz1, tz2 = _str(fd.get('_history_kickoff_tz')), _str(ls.get('_history_kickoff_tz'))
        kickoff_status = 'unavailable' if not (k1 and k2) else 'unverified_timezone'
        if k1 and k2 and tz1 and tz2:
            try:
                t1 = pd.Timestamp(f"{pd.Timestamp(fd['date']).date()} {k1}").tz_localize(tz1).tz_convert('UTC')
                t2 = pd.Timestamp(f"{pd.Timestamp(ls['date']).date()} {k2}").tz_localize(tz2).tz_convert('UTC')
                kickoff_status = 'matched' if t1 == t2 else 'conflict'
                if t1 != t2:
                    reasons.append('kickoff_conflict')
            except Exception:  # malformed zone or ambiguous/nonexistent local time: fail closed
                kickoff_status = 'invalid'
                reasons.append('kickoff_timezone_invalid')
        conflicts = {c: {'football_data': _plain(fd.get(c)), 'livescore': _plain(ls.get(c))}
                     for c in STATS if c in data and _plain(fd.get(c)) is not None and _plain(ls.get(c)) is not None
                     and _plain(fd.get(c)) != _plain(ls.get(c))}
        prior_conflicts = ls.get('_history_conflicts')
        if isinstance(prior_conflicts, (tuple, list)):
            for col in prior_conflicts:
                conflicts.setdefault(col, {'football_data': _plain(fd.get(col)), 'livescore': 'conflicting stage copies'})
        entry = {'candidate_id': _candidate_id(fd, ls), 'status': 'needs_review' if not reasons else 'blocked',
                 'reasons': reasons, 'kickoff_comparison': kickoff_status,
                 'football_data': _record(fd), 'livescore': _record(ls), 'stat_conflicts': conflicts}
        yield entry, fi, li


def reconcile(rows: pd.DataFrame, approvals: dict, include_details=False):
    """Apply only reviewed, still-eligible pairs; return unique rows and audit.

    Both division keys remain available via division_view. FD is the documented
    normalisation priority; nonconflicting missing stats can come from Livescore.
    Conflicts are NaN, and both original records are retained in memory.
    """
    df = rows.reset_index(drop=True)
    drop, merged = [], []
    counts = Counter()
    details = []
    seen = set()
    for item, fi, li in candidates(df):
        counts[item['status']] += 1
        for reason in item.get('reasons', []): counts[reason] += 1
        if item.get('stat_conflicts'): counts['groups_with_stat_conflicts'] += 1
        candidate_id = item.get('candidate_id')
        if candidate_id in approvals and item['status'] == 'needs_review':
            seen.add(candidate_id)
            fd, ls = df.iloc[fi], df.iloc[li]
            out = fd.copy()
            out['eid'], out['home_id'], out['away_id'] = ls['eid'], ls['home_id'], ls['away_id']
            out['_history_divs'] = (str(fd['div']), str(ls['div']))
            out['_history_records'] = (item['football_data'], item['livescore'])
            out['_history_conflicts'] = tuple(sorted(item['stat_conflicts']))
            out['_history_review'] = approvals[candidate_id].copy()
            for col in STATS:
                if col not in df.columns: continue
                a, b = _plain(fd.get(col)), _plain(ls.get(col))
                out[col] = float('nan') if col in item['stat_conflicts'] else (a if a is not None else b)
            drop.extend([fi, li]); merged.append(out); counts['merged'] += 1
            item['status'] = 'merged_reviewed'
        if include_details: details.append(item)
    counts['unmatched_or_ineligible_approvals'] = len(set(approvals) - seen)
    result = df
    if drop:
        result = pd.concat([df.drop(index=drop), pd.DataFrame(merged)], ignore_index=True)
        result = result.sort_values('date', ascending=False, kind='stable').reset_index(drop=True)
    summary = dict(counts)
    summary['rows_removed'] = len(drop) - len(merged)
    return result, summary, details


def division_view(rows: pd.DataFrame) -> pd.DataFrame:
    """Expanded division-only view; never use for global/team/event counts."""
    if rows.empty or '_history_divs' not in rows:
        return rows
    extras = []
    for pos, values in enumerate(rows['_history_divs']):
        if isinstance(values, (list, tuple)):
            current = str(rows.iloc[pos]['div'])
            for div in sorted(set(values)):
                if div != current:
                    extras.append((pos, div))
    if not extras:
        return rows
    copies = rows.iloc[[p for p, _ in extras]].copy()
    copies['div'] = [d for _, d in extras]
    return pd.concat([rows, copies], ignore_index=True)
