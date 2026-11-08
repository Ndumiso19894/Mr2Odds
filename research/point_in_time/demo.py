"""Reproducible synthetic demonstration; no network, real data, or persistent files."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from . import snapshots
from .replay import ExerciseCase, run_chronological


def main():
    # The patched clock exists ONLY in this synthetic demonstration. It does not
    # establish real-world observation or historic availability of anything.
    base = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    cutoff = base + timedelta(hours=2)
    kickoff = base + timedelta(hours=3)
    finish = base + timedelta(hours=5)
    hist = {'id': 'toy-history', 'competition_id': 'toy-league', 'home_id': 'toy-home',
            'away_id': 'toy-third', 'kickoff_at': (base-timedelta(days=1,hours=2)).isoformat(),
            'finished_at': (base-timedelta(days=1)).isoformat(), 'status': 'FINAL',
            'score_period': 'REGULATION', 'home_goals': 2, 'away_goals': 1}
    quote_spec = [{'event_pointer': '/event', 'event_id_pointer': '/id', 'quotes': [{
        'market_pointer': '/markets/0', 'market_id_pointer': '/id', 'specifier_pointer': '/specifier',
        'outcome_pointer': '/outcomes/0', 'outcome_name_pointer': '/name', 'odds_pointer': '/odds',
        'market_status_pointer': '/status', 'outcome_status_pointer': '/status'}]}]
    with TemporaryDirectory() as directory:
        root = Path(directory)
        def capture(dataset, payload, *, at=base, specs=None):
            raw = json.dumps(payload, separators=(',', ':')).encode()
            clock = iter([at, at+timedelta(seconds=1), at+timedelta(seconds=2)])
            with patch.object(snapshots, '_now_utc', side_effect=lambda: next(clock)):
                return snapshots.capture(root, lambda: raw, provider='synthetic', dataset=dataset,
                                         request_path='/toy', origin='synthetic', event_specs=specs)
        history = capture('history', {'history': [hist]})
        cases = []
        for number, score in ((1, (2, 1)), (2, (0, 0))):
            event = {'id': f'toy-event-{number}', 'competition_id': 'toy-league',
                     'home_id': f'toy-home-{number}', 'away_id': f'toy-away-{number}',
                     'kickoff_at': kickoff.isoformat()}
            fixture = capture('fixture', {'event': event})
            quoted = dict(event, markets=[{'id': 'total_goals', 'specifier': '2.5', 'status': 'OPEN',
                                           'outcomes': [{'name': 'over', 'odds': '1.50', 'status': 'ACTIVE'}]}])
            quotes = capture('quotes', {'event': quoted}, specs=quote_spec)
            final = dict(event, finished_at=finish.isoformat(), status='FINAL', score_period='REGULATION',
                         home_goals=score[0], away_goals=score[1])
            result = capture('result', {'event': final}, at=finish)
            cases.append(ExerciseCase(cutoff, fixture, (history,), quotes, 'over', result, finish+timedelta(minutes=1)))
        report = run_chronological(cases, max_quote_age=timedelta(hours=2), price_policy='final_picks')
        # IDs and receipts are deliberately not exported; temp files are removed.
        keys = ('classification', 'model', 'baseline', 'price_policy', 'matched_cases', 'toy_brier',
                'baseline_brier', 'toy_log_loss', 'baseline_log_loss')
        print(json.dumps({key: report[key] for key in keys}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
