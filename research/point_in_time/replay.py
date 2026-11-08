"""Synthetic-only, fail-closed point-in-time replay exercise.

This is not a production eligibility engine, a provider adapter or a backtest.
The hard-coded toy schema and rules are intentionally not bookmaker definitions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from math import log
from pathlib import Path

from . import snapshots


class ReplayError(ValueError):
    """The synthetic exercise lacks required, internally consistent evidence."""


def _time(value, name):
    if not isinstance(value, str):
        raise ReplayError(f'{name} timestamp is missing or invalid')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ReplayError(f'{name} timestamp is missing or invalid') from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ReplayError(f'{name} timestamp must have an explicit offset')
    return result.astimezone(timezone.utc)


def _aware(value, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReplayError(f'{name} must be timezone-aware')
    return value.astimezone(timezone.utc)


def _load(path, cutoff, dataset):
    try:
        result = snapshots.load_as_of(path, cutoff, allow_non_provider=True)
    except (snapshots.SnapshotError, OSError, TypeError) as exc:
        raise ReplayError(f'{dataset} snapshot rejected: {exc}') from exc
    ctx = result['metadata']['context']
    if ctx['origin'] != 'synthetic' or ctx['provider'] != 'synthetic' or ctx['dataset'] != dataset:
        raise ReplayError(f'{dataset} snapshot is not marked for the synthetic exercise')
    if ctx['content_type'] != 'application/json':
        raise ReplayError(f'{dataset} snapshot must be JSON')
    try:
        raw = snapshots._decode(result['payload'])
    except snapshots.SnapshotError as exc:
        raise ReplayError(f'{dataset} payload is invalid JSON') from exc
    if not isinstance(raw, dict):
        raise ReplayError(f'{dataset} payload must be an object')
    return result, raw


def _id(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 128:
        raise ReplayError(f'{name} must be a nonempty exact string ID')
    return value


def _event(event):
    if not isinstance(event, dict):
        raise ReplayError('event must be an object')
    ident = tuple(_id(event.get(k), k) for k in ('id', 'competition_id', 'home_id', 'away_id'))
    if ident[2] == ident[3]:
        raise ReplayError('home and away must differ')
    return ident, _time(event.get('kickoff_at'), 'kickoff')


def _goals(value, name):
    if type(value) is not int or not 0 <= value <= 99:
        raise ReplayError(f'{name} must be a non-negative regulation score')
    return value


@dataclass(frozen=True)
class Simulation:
    """An explicitly hypothetical result, not a real eligibility decision."""
    cutoff: datetime
    kickoff: datetime
    identity: tuple[str, str, str, str]
    outcome: str
    odds: str
    price_policy: str
    observation_age: timedelta
    history_count: int
    history_over_count: int
    # Snapshot IDs and hashes permit audit of the exact in-memory exercise.
    snapshots: tuple[tuple[str, str, str], ...]
    classification: str = 'synthetic_only'

    @property
    def toy_probability(self) -> Fraction:
        """Fixed Laplace-smoothed synthetic history frequency, not Mr2Odds."""
        over = Fraction(self.history_over_count + 1, self.history_count + 2)
        return over if self.outcome == 'over' else 1 - over


def simulate(*, cutoff: datetime, fixture: Path, history: list[Path], quotes: Path,
             outcome: str, max_quote_age: timedelta, price_policy: str) -> Simulation:
    """Validate one toy total-goals selection from synthetic-only snapshots.

    All inputs are checked at the *same* cutoff, which must be before kickoff.
    The toy market is exactly total_goals/2.5 with outcome over or under; OPEN
    and ACTIVE are toy statuses. No production provider meaning is assumed.
    """
    cutoff = _aware(cutoff, 'cutoff')
    if not isinstance(history, list) or not history or len(history) > 100:
        raise ReplayError('at least one bounded history snapshot is required')
    if outcome not in ('over', 'under') or not isinstance(outcome, str):
        raise ReplayError('unsupported synthetic outcome')
    if price_policy not in ('app', 'final_picks') or not isinstance(price_policy, str):
        raise ReplayError('an explicit synthetic price policy is required')
    if not isinstance(max_quote_age, timedelta) or max_quote_age <= timedelta(0):
        raise ReplayError('max_quote_age must be a positive timedelta')
    f, fraw = _load(fixture, cutoff, 'fixture')
    ident, kickoff = _event(fraw.get('event'))
    if cutoff >= kickoff:
        raise ReplayError('cutoff must be strictly before kickoff')
    references = [('fixture', f['metadata']['snapshot_id'], f['receipt_sha256'])]
    history_count, history_over_count, seen = 0, 0, set()
    for path in history:
        h, hraw = _load(path, cutoff, 'history')
        rows = hraw.get('history')
        if not isinstance(rows, list) or not rows or len(rows) > 10000:
            raise ReplayError('history must contain a bounded nonempty list')
        captured = _time(h['metadata']['captured_at_utc'], 'history capture')
        for row in rows:
            rid, rkickoff = _event(row)
            finished = _time(row.get('finished_at'), 'history finish')
            if rkickoff >= finished or finished >= cutoff or finished > captured:
                raise ReplayError('history event not demonstrably finished before cutoff and capture')
            if rid[0] == ident[0] or rid[0] in seen:
                raise ReplayError('target or duplicate event ID in history')
            seen.add(rid[0])
            if row.get('status') != 'FINAL' or row.get('score_period') != 'REGULATION':
                raise ReplayError('history result is not a synthetic regulation final')
            home = _goals(row.get('home_goals'), 'home goals')
            away = _goals(row.get('away_goals'), 'away goals')
            history_count += 1
            history_over_count += int(home + away > 2)
        references.append(('history', h['metadata']['snapshot_id'], h['receipt_sha256']))
    q, qraw = _load(quotes, cutoff, 'quotes')
    observations = [e for e in q['claims']['events'] if e['event_id'] == ident[0]]
    if len(observations) != 1:
        raise ReplayError('target quote event missing or ambiguous')
    event_claim = observations[0]
    try:
        quote_event = snapshots._pointer(qraw, event_claim['event_pointer'])
    except snapshots.SnapshotError as exc:
        raise ReplayError('quote event pointer invalid') from exc
    quote_ident, quote_kickoff = _event(quote_event)
    if quote_ident != ident or quote_kickoff != kickoff:
        raise ReplayError('fixture and quote event identities or kickoff differ')
    matching = [v for v in event_claim['quotes'] if v['market_id'] == 'total_goals'
                and v['specifier'] == '2.5' and v['outcome'] == outcome]
    if len(matching) != 1:
        raise ReplayError('exact synthetic market, line and outcome missing or ambiguous')
    quote = matching[0]
    floor = Decimal('1.16') if price_policy == 'app' else Decimal('1.18')
    if Decimal(quote['decimal_odds']) < floor:
        raise ReplayError('exact synthetic quote is below the selected price floor')
    if quote['market_status'] != 'OPEN' or quote['outcome_status'] != 'ACTIVE':
        raise ReplayError('synthetic market and outcome are not both explicitly active')
    # Local capture start is a conservative observation-age bound. It does not
    # establish provider update time, freshness, or execution at this price.
    age = cutoff - _time(q['metadata']['capture_started_at_utc'], 'quote capture start')
    if age > max_quote_age:
        raise ReplayError('local quote observation is too old')
    references.append(('quotes', q['metadata']['snapshot_id'], q['receipt_sha256']))
    return Simulation(cutoff, kickoff, ident, outcome, quote['decimal_odds'], price_policy, age, history_count,
                      history_over_count, tuple(references))


def settle(simulation: Simulation, *, result: Path, as_of: datetime) -> dict:
    """Settle the toy market against a separate, subsequent synthetic result.

    No return on investment, bookmaker settlement, or actual execution is implied.
    """
    if not isinstance(simulation, Simulation) or simulation.classification != 'synthetic_only':
        raise ReplayError('synthetic simulation required')
    as_of = _aware(as_of, 'settlement as_of')
    if as_of <= simulation.cutoff:
        raise ReplayError('settlement as_of must be later than prediction cutoff')
    snap, raw = _load(result, as_of, 'result')
    event = raw.get('event')
    identity, kickoff = _event(event)
    finished = _time(event.get('finished_at'), 'result finish')
    captured = _time(snap['metadata']['captured_at_utc'], 'result capture')
    if identity != simulation.identity or kickoff != simulation.kickoff:
        raise ReplayError('result event identity or kickoff differs')
    if finished <= kickoff or finished > captured or finished > as_of:
        raise ReplayError('result not finished by capture and settlement as_of')
    if event.get('status') != 'FINAL' or event.get('score_period') != 'REGULATION':
        raise ReplayError('result is not a synthetic regulation final')
    home, away = _goals(event.get('home_goals'), 'home goals'), _goals(event.get('away_goals'), 'away goals')
    over = home + away > 2
    won = over if simulation.outcome == 'over' else not over
    return {'classification': 'synthetic_only', 'result': 'won' if won else 'lost',
            'home_goals': home, 'away_goals': away,
            'result_snapshot_id': snap['metadata']['snapshot_id'], 'result_receipt_sha256': snap['receipt_sha256']}


@dataclass(frozen=True)
class ExerciseCase:
    """Caller-selected synthetic fixture; not proof of prospective selection."""
    cutoff: datetime
    fixture: Path
    history: tuple[Path, ...]
    quotes: Path
    outcome: str
    result: Path
    settlement_as_of: datetime


def run_chronological(cases: list[ExerciseCase], *, max_quote_age: timedelta, price_policy: str) -> dict:
    """Run a fixed toy model on matched synthetic cases, then settle them.

    Predictions for *all* cases are created before any result snapshot is read.
    This illustrates separation of phases but cannot prove caller selection or
    model design was registered in advance. Failure yields no partial metrics.
    """
    if not isinstance(cases, list) or not cases or len(cases) > 1000:
        raise ReplayError('a bounded nonempty case list is required')
    predictions = []
    previous = None
    seen = set()
    for case in cases:
        if not isinstance(case, ExerciseCase) or not isinstance(case.history, tuple):
            raise ReplayError('invalid synthetic exercise case')
        cutoff = _aware(case.cutoff, 'cutoff')
        if previous is not None and cutoff < previous:
            raise ReplayError('cases must be ordered by cutoff')
        previous = cutoff
        prediction = simulate(cutoff=cutoff, fixture=case.fixture, history=list(case.history),
                              quotes=case.quotes, outcome=case.outcome, max_quote_age=max_quote_age,
                              price_policy=price_policy)
        if prediction.identity[0] in seen:
            raise ReplayError('duplicate target event ID')
        seen.add(prediction.identity[0])
        predictions.append(prediction)
    rows = []
    for case, prediction in zip(cases, predictions):
        result = settle(prediction, result=case.result, as_of=case.settlement_as_of)
        label = int(result['result'] == 'won')
        probability = float(prediction.toy_probability)
        rows.append({'event_id': prediction.identity[0], 'competition_id': prediction.identity[1],
                     'home_id': prediction.identity[2], 'away_id': prediction.identity[3],
                     'cutoff': prediction.cutoff.isoformat(), 'kickoff': prediction.kickoff.isoformat(),
                     'outcome': prediction.outcome, 'decimal_odds': prediction.odds,
                     'quote_observation_age_microseconds': prediction.observation_age // timedelta(microseconds=1),
                     'history_count': prediction.history_count, 'history_over_count': prediction.history_over_count,
                     'toy_probability': probability, 'observed': label,
                     'home_goals': result['home_goals'], 'away_goals': result['away_goals'],
                     'settlement_as_of': _aware(case.settlement_as_of, 'settlement as_of').isoformat(),
                     'input_snapshots': prediction.snapshots, 'result_snapshot_id': result['result_snapshot_id'],
                     'result_receipt_sha256': result['result_receipt_sha256']})
    n = len(rows)
    return {'classification': 'synthetic_only', 'model': 'fixed_laplace_history_frequency',
            'baseline': 'fixed_0.5', 'price_policy': price_policy,
            'max_quote_age_microseconds': max_quote_age // timedelta(microseconds=1),
            'matched_cases': n, 'rows': rows,
            'toy_brier': sum((r['toy_probability'] - r['observed'])**2 for r in rows) / n,
            'baseline_brier': sum((0.5-r['observed'])**2 for r in rows) / n,
            'toy_log_loss': sum(-log(r['toy_probability'] if r['observed'] else 1-r['toy_probability']) for r in rows) / n,
            'baseline_log_loss': -log(0.5)}
