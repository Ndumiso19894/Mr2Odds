"""Conservative in-memory history reconciliation; raw source archives are untouched."""
from __future__ import annotations
import logging
import pandas as pd

log = logging.getLogger('scanner')


def reconcile_livescore_ids(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Collapse only repeated Livescore event IDs with consistent identity and scores.

    Preserve contributing stage codes on each resulting row. A numeric statistic
    is filled from another copy only if all nonmissing values agree; conflicting
    values become missing, not an arbitrary provider choice. Identity/score
    conflicts quarantine the entire ID from prediction history. Settlement and
    the persisted archive are not changed. Cross-provider candidates without a
    shared ID are deliberately not merged: their competition/team mappings and
    statistic definitions are not proven.
    """
    report = {'duplicate_groups': 0, 'rows_removed': 0, 'quarantined_groups': 0,
              'stat_conflicts': 0, 'unmerged_cross_provider': True}
    if rows.empty or 'eid' not in rows or 'div' not in rows:
        return rows.copy(), report
    world = rows['div'].astype(str).str.startswith('LS:') & rows['eid'].notna()
    duplicate = world & rows.loc[:, 'eid'].astype(str).duplicated(keep=False)
    if not duplicate.any():
        return rows.copy(), report
    indices_to_drop = []
    replacements = []
    identity = ('country', 'league', 'date', 'home', 'away', 'home_id', 'away_id', 'hg', 'ag')
    statistics = ('hth','hta','hxg','axg','hs','as','hst','ast','hsoff','asoff',
                  'hc','ac','hy','ay','hr','ar','hposs','aposs','hf','af')
    # Work with unique positional indices even when callers passed repeated labels.
    result = rows.reset_index(drop=True)
    duplicate = duplicate.reset_index(drop=True)
    for eid, group in result.loc[duplicate].groupby('eid', sort=False):
        if len(group) < 2:
            continue
        report['duplicate_groups'] += 1
        indices_to_drop.extend(group.index.tolist())
        if any(c not in group or group[c].isna().any() or group[c].astype(str).nunique() != 1 for c in identity):
            report['quarantined_groups'] += 1
            log.warning('Quarantined conflicting Livescore event %s from prediction history', eid)
            continue
        # Prefer the unsuffixed/shortest stage deterministically; retain all stage
        # codes so the choice is inspectable rather than a loss of provenance.
        ix = min(group.index, key=lambda i: (len(str(group.at[i, 'div'])), str(group.at[i, 'div'])))
        merged = group.loc[ix].copy()
        merged['_history_sources'] = tuple(sorted(group['div'].astype(str).unique()))
        conflicts = []
        for col in statistics:
            if col not in group:
                continue
            vals = group[col].dropna().unique()
            if len(vals) > 1:
                merged[col] = float('nan')
                conflicts.append(col)
            elif len(vals) == 1:
                merged[col] = vals[0]
        merged['_history_conflicts'] = tuple(conflicts)
        report['stat_conflicts'] += len(conflicts)
        if conflicts:
            log.warning('Conflicting Livescore statistics for event %s: %s', eid, ', '.join(conflicts))
        replacements.append(merged)
    if not indices_to_drop:
        return result, report
    report['rows_removed'] = len(indices_to_drop) - len(replacements)
    result = pd.concat([result.drop(index=indices_to_drop), pd.DataFrame(replacements)], ignore_index=True)
    return result.sort_values('date', ascending=False, kind='stable').reset_index(drop=True), report
