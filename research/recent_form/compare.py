#!/usr/bin/env python3
"""Paired, date-cutoff retrospective sensitivity; not a prospective backtest.

Reads a pinned local archive. No networking, prices, publication or settlement
inference. The archive was created after the simulated dates and does not prove
historical feature availability. Outputs aggregated JSON to stdout.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import competition_policy
import history_integrity
import worldfeed
from research.recent_form import model

MARKETS = ('O15', 'O25', 'O35', 'BTTS', 'H', 'D', 'A', 'H_zero_goal', 'A_zero_goal')


def score_summary(rows, key):
    if not rows:
        return None
    y=np.array([r['outcome'][key] for r in rows],dtype=float)
    a=np.clip(np.array([r['baseline'][key] for r in rows],dtype=float),1e-12,1-1e-12)
    b=np.clip(np.array([r['variant'][key] for r in rows],dtype=float),1e-12,1-1e-12)
    out={'n':len(rows), 'actual_frequency':float(y.mean()),
         'baseline_mean_probability':float(a.mean()),'variant_mean_probability':float(b.mean()),
         'mean_signed_change_pp':float((b-a).mean()*100),
         'mean_absolute_change_pp':float(np.abs(b-a).mean()*100),
         'max_absolute_change_pp':float(np.abs(b-a).max()*100)}
    day_groups=defaultdict(list)
    for i,row in enumerate(rows):day_groups[row['day']].append(i)
    for label,loss_a,loss_b in (
        ('brier',(a-y)**2,(b-y)**2),
        ('log_loss',-y*np.log(a)-(1-y)*np.log(1-a),-y*np.log(b)-(1-y)*np.log(1-b))):
        delta=loss_b-loss_a
        entry={'baseline':float(loss_a.mean()),'variant':float(loss_b.mean()),'paired_delta':float(delta.mean()),
               'resampled_days':len(day_groups)}
        if len(day_groups)>=2:
            groups=list(day_groups.values()); sums=np.array([delta[g].sum() for g in groups]); counts=np.array([len(g) for g in groups])
            picks=np.random.default_rng(19894).integers(0,len(groups),size=(1000,len(groups)))
            boot=sums[picks].sum(axis=1)/counts[picks].sum(axis=1)
            entry['day_bootstrap_95']=[float(v) for v in np.quantile(boot,[.025,.975])]
        out[label]=entry
    return out


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('--start',default='2026-10-01')
    parser.add_argument('--end',default='2026-10-15',help='exclusive calendar date')
    args=parser.parse_args()
    start=datetime.fromisoformat(args.start);end=datetime.fromisoformat(args.end)
    if (start.tzinfo is not None or end.tzinfo is not None or start.time() != datetime.min.time() or
            end.time() != datetime.min.time() or end<=start or (end-start).days>45):
        parser.error('start and end must be naive calendar dates at most 45 days apart')
    archive=args.snapshot/'data'/'ls'
    if not (archive/'stages').is_dir():parser.error('pinned archive stages not found')
    data=worldfeed.Archive(archive).results_frame(start-timedelta(days=model.H2H_DAYS))
    data=data.dropna(subset=['date','hg','ag'])
    data=data[data.date<pd.Timestamp(end)].sort_values('date',ascending=False,kind='stable').reset_index(drop=True)
    rows=[]; days=[]; excluded=Counter(); distributions=Counter(); t=time.time()
    for day in pd.date_range(start,end-timedelta(days=1)):
        target=data[data.date==day].copy()
        # Remove same-ID duplicate target rows and quarantine conflicts; do not
        # identify unreviewed cross-provider duplicates using team names.
        target,target_integrity=history_integrity.reconcile_livescore_ids(target)
        if target.empty:continue
        mask=[competition_policy.allowed(r.country,r.league,key=str(r.div)[3:],home=r.home,away=r.away) for r in target.itertuples()]
        target=target[mask]
        for col in ('hg', 'ag'):
            value=pd.to_numeric(target[col], errors='coerce')
            valid=value.notna() & np.isfinite(value) & (value>=0) & (value % 1==0)
            excluded['invalid target score'] += int((~valid).sum())
            target=target[valid]
        if target.empty:continue
        ctx=model.prepare(data,day.to_pydatetime())
        day_counts={'day':str(day.date()),'targets':len(target),'matched':0,
                    'target_duplicate_rows_removed':target_integrity['rows_removed'],
                    'history_rows':len(ctx.results),'same_id_rows_removed':ctx.integrity['rows_removed']}
        for r in target.itertuples(index=False):
            fx={'country':r.country,'div':r.div,'home':r.home,'away':r.away,
                'home_id':r.home_id,'away_id':r.away_id}
            try:
                pred=model.predict(ctx,fx)
            except model.ResearchError as exc:
                excluded[str(exc)]+=1;continue
            hg,ag=int(r.hg),int(r.ag)
            outcome={'O15':int(hg+ag>=2),'O25':int(hg+ag>=3),'O35':int(hg+ag>=4),
                     'BTTS':int(hg>0 and ag>0),'H':int(hg>ag),'D':int(hg==ag),'A':int(hg<ag),
                     'H_zero_goal':int(hg==0),'A_zero_goal':int(ag==0)}
            ev=pred['evidence']; distributions['h2h_applied']+=int(ev['h2h']['weight']>0)
            distributions['both_last5_full']+=int(ev['home']['last5']['n']==5 and ev['away']['last5']['n']==5)
            distributions['both_last10_full']+=int(ev['home']['last10']['n']==10 and ev['away']['last10']['n']==10)
            distributions['both_venue5_full']+=int(ev['home']['venue5']['n']==5 and ev['away']['venue5']['n']==5)
            rows.append({'day':str(day.date()),'division':str(r.div),'country':str(r.country),
                         'baseline':pred['baseline']['probabilities'],'variant':pred['recent_variant']['probabilities'],
                         'outcome':outcome})
            day_counts['matched']+=1
        days.append(day_counts)
        print(f"{day.date()} targets={len(target)} matched={day_counts['matched']} elapsed={time.time()-t:.1f}s",file=sys.stderr,flush=True)
    leagues=Counter((r['country'],r['division']) for r in rows)
    by_league=[]
    for (country,division),n in leagues.most_common():
        if n<30:continue
        subset=[r for r in rows if r['country']==country and r['division']==division]
        by_league.append({'country':country,'division':division,'n':n,
                          'O25':score_summary(subset,'O25'),'BTTS':score_summary(subset,'BTTS')})
    report={'classification':'retrospective_sensitivity_not_point_in_time_validation',
            'method':{'input':'pinned postdated Livescore archive, world-only; no verified quote or availability times',
                      'start':str(start.date()),'end_exclusive':str(end.date()),
                      'history':'strictly before prediction calendar day; same-ID duplicate reconciliation',
                      'matched':'same target, same history, same baseline model; excluded if either team lacks history or recent order is ambiguous',
                      'uncertainty':'paired bootstrap resamples dates, conditional on this retrospective and non-independent sample',
                      'limitations':['pinned snapshot postdates replay; features and outcomes may be backfilled',
                        'no football-data or extra league feeds; production priors differ',
                        'cross-provider identity and archived kickoff timezones remain unresolved',
                        'no squad availability, no actual prices, no recommendations, no profitability',
                        'exploratory fixed formula; not tuned or validated on untouched prospective data']},
            'coverage':{'days':len(days),'targets':sum(d['targets'] for d in days),'matched':len(rows),
                        'excluded':dict(excluded),'recent_feature_coverage':dict(distributions)},
            'per_day':days,'markets':{k:score_summary(rows,k) for k in MARKETS},'leagues_with_at_least_30_matched':by_league}
    print(json.dumps(report,indent=2,allow_nan=False))


if __name__=='__main__':main()
