"""Compare old and new H2H eligibility using an existing local archive only."""
import argparse
from datetime import datetime
import json
import logging
from pathlib import Path

import pandas as pd
import competition_policy
import h2h_gate
import history_integrity
import worldfeed


def compare(root, day, limit=800):
    if h2h_gate.MIN_MEETINGS != 3 or h2h_gate.MAX_YEARS is not None:
        raise ValueError('this comparison requires the three-meeting, no-age-limit gate')
    root = Path(root)
    if not (root / 'stages').is_dir():
        raise ValueError('an existing Livescore archive with a stages directory is required')
    if limit < 1:
        raise ValueError('sample size must be positive')
    cutoff = datetime.strptime(day, '%Y-%m-%d')
    rows = worldfeed.Archive(root).results_frame(datetime(1900, 1, 1))
    if rows.empty:
        raise ValueError('archive has no usable results')
    prior = rows[(rows.date < pd.Timestamp(day)) & rows.hg.notna() & rows.ag.notna()].copy()
    prior, _ = history_integrity.reconcile_livescore_ids(prior)
    index = h2h_gate.build_index(prior, cutoff)
    targets = rows[rows.date == pd.Timestamp(day)].copy()
    targets = targets.drop_duplicates(subset=['eid'], keep=False).sort_values(['div', 'eid'], kind='stable')
    targets = targets[[competition_policy.allowed(r.country, r.league, home=r.home, away=r.away,
                                                   key=str(r.div)[3:]) for r in targets.itertuples()]].head(limit)
    old_count = new_count = 0
    reasons = {}
    old_cutoff = (pd.Timestamp(day) - pd.DateOffset(years=3)).date()
    for r in targets.itertuples():
        fixture = dict(source='world', home_id=r.home_id, away_id=r.away_id, home=r.home, away=r.away,
                       country=r.country, div=r.div, kickoff=cutoff)
        proof = h2h_gate.eligibility(fixture, index)
        new_count += int(proof['eligible'])
        if proof['eligible'] and proof['meetings'] >= 6 and pd.Timestamp(proof['last_meeting']).date() > old_cutoff:
            old_count += 1
        reasons[proof['reason']] = reasons.get(proof['reason'], 0) + 1
    return {'date': day, 'sample_size': len(targets), 'historical_rows': len(prior),
            'old_six_and_under_three_years': old_count, 'new_three_no_age_limit': new_count,
            'newly_eligible': new_count - old_count, 'new_gate_reasons': reasons,
            'limitations': 'Gate-only sample from a postdated results archive; no point-in-time availability or historical timezone verified; not prospective and not evidence of accuracy.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', help='Existing local Livescore archive directory (containing stages/)')
    parser.add_argument('date', help='Target day, YYYY-MM-DD')
    parser.add_argument('--limit', type=int, default=800)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    print(json.dumps(compare(args.archive, args.date, args.limit), indent=2))


if __name__ == '__main__':
    main()
