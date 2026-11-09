"""Legacy H2H archive index and sample-assessment helpers.

These helpers assess available history; they must not filter predictions.
No network calls, cross-provider name matching or fabricated identities.
"""
from collections import Counter, defaultdict
from datetime import datetime
import math

import pandas as pd

import recent_form

MIN_MEETINGS = 3
MAX_YEARS = None  # no recency cutoff; meetings must still precede the fixture


def _name(value):
    return (isinstance(value, str) and bool(value) and value == value.strip()
            and value.lower() not in ('nan', 'none', 'null'))


def _score(value):
    try:
        n = float(value)
        return math.isfinite(n) and n >= 0 and n.is_integer()
    except (TypeError, ValueError):
        return False


def _not_friendly(league, div, country):
    # A competition type must be identifiable. Do not use team names here:
    # a club's name could contain a word resembling a competition marker.
    if not _name(league) or not _name(div):
        return False
    metadata = ' '.join(v for v in (league, div, country) if isinstance(v, str)).lower()
    return not any(marker in metadata for marker in ('friendl', 'amistos', 'amical', 'freundschaft', 'vriendschappelijk'))


def _pair(a, b):
    return tuple(sorted((a, b)))


def build_index(history: pd.DataFrame, as_of: datetime) -> dict:
    """Index only earlier-day completed, identifiable non-friendly records.

    Livescore identities require exact provider team and event IDs. Football-data
    has no team IDs, so its records are matched only within that provider using
    exact country and team strings; no fuzzy or cross-provider inference.
    A still-duplicated event ID or same-day pair is excluded conservatively.
    """
    required = {'date', 'div', 'league', 'country', 'home', 'away', 'hg', 'ag'}
    if history is None or history.empty or not required.issubset(history.columns):
        return {}
    groups = defaultdict(list)
    event_counts = Counter()
    columns = ['date', 'div', 'league', 'country', 'home', 'away', 'hg', 'ag', 'home_id', 'away_id', 'eid']
    selected = history.reindex(columns=columns)
    for record in selected.itertuples(index=False, name=None):
        values = dict(zip(columns, record))
        div, league = values.get('div'), values.get('league')
        try:
            date = pd.Timestamp(values.get('date'))
            if pd.isna(date) or date.tzinfo is not None or date.date() >= as_of.date():
                continue
            day = date.date()
        except (TypeError, ValueError, OverflowError):
            continue
        if isinstance(div, str) and div.startswith('LS:') and recent_form.valid_id(values.get('eid')):
            event_counts[values['eid']] += 1
        if not _not_friendly(league, div, values.get('country')) or not _score(values.get('hg')) or not _score(values.get('ag')):
            continue
        if div.startswith('LS:'):
            hid, aid, eid = values.get('home_id'), values.get('away_id'), values.get('eid')
            if not all(recent_form.valid_id(x) for x in (hid, aid, eid)) or hid == aid:
                continue
            groups[('ls', *_pair(hid, aid))].append((day, eid))
        else:
            country, home, away = values.get('country'), values.get('home'), values.get('away')
            if not all(_name(x) for x in (country, home, away)) or home == away:
                continue
            groups[('fd', country, *_pair(home, away))].append((day, None))
    out = {}
    for key, entries in groups.items():
        entries = [(day, eid) for day, eid in entries if eid is None or event_counts[eid] == 1]
        counts = Counter(day for day, _ in entries)
        out[key] = sorted((day for day, _ in entries if counts[day] == 1), reverse=True)
    return out


def eligibility(fx, index: dict) -> dict:
    """Require at least three distinct earlier-day non-friendly meetings, with no age limit."""
    source = fx.get('source')
    if source == 'world':
        a, b = fx.get('home_id'), fx.get('away_id')
        key = ('ls', *_pair(a, b)) if recent_form.valid_id(a) and recent_form.valid_id(b) and a != b else None
        identity = 'Livescore team and event IDs'
    elif source in ('main', 'extra'):
        country, a, b = fx.get('country'), fx.get('home'), fx.get('away')
        key = ('fd', country, *_pair(a, b)) if all(_name(x) for x in (country, a, b)) and a != b else None
        identity = 'exact football-data country and team names'
    else:
        key, identity = None, None
    if key is None:
        return {'eligible': False, 'reason': 'identity_unavailable', 'meetings': 0, 'last_meeting': None, 'identity': identity}
    try:
        kickoff = pd.Timestamp(fx.get('kickoff'))
        if pd.isna(kickoff):
            raise ValueError('missing kickoff')
    except (TypeError, ValueError, OverflowError):
        return {'eligible': False, 'reason': 'kickoff_unavailable', 'meetings': 0, 'last_meeting': None, 'identity': identity}
    # The index is as-of the scan. Do not count a meeting on or after this
    # fixture's date even when evaluating an older fixture against a later index.
    days = [day for day in index.get(key, []) if day < kickoff.date()]
    latest = days[0] if days else None
    reason = 'insufficient_meetings' if len(days) < MIN_MEETINGS else 'eligible'
    return {'eligible': reason == 'eligible', 'reason': reason, 'meetings': len(days),
            'last_meeting': latest.isoformat() if latest else None, 'identity': identity}


def valid_proof(proof, kickoff):
    """Validate the exported gate evidence without manufacturing missing values."""
    if not isinstance(proof, dict) or proof.get('eligible') is not True or proof.get('reason') != 'eligible':
        return False
    count = proof.get('meetings')
    if not isinstance(count, int) or isinstance(count, bool) or count < MIN_MEETINGS:
        return False
    if proof.get('identity') not in ('Livescore team and event IDs', 'exact football-data country and team names'):
        return False
    try:
        target = pd.Timestamp(kickoff)
        last = pd.Timestamp(proof.get('last_meeting'))
        if pd.isna(target) or pd.isna(last) or last.tzinfo is not None:
            return False
        return last.date() < target.date()
    except (TypeError, ValueError, OverflowError):
        return False
