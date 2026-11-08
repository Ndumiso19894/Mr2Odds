#!/usr/bin/env python3
"""Same-target retrospective world-only comparison, not a production/price replay."""
from datetime import datetime, timedelta
from pathlib import Path
import json, sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import scanner, worldfeed, markets, model_signals, competition_policy, history_integrity

root=Path(sys.argv[1]); now=datetime(2026,11,4,0)
df=worldfeed.Archive(root/'data/ls').results_frame(now-timedelta(days=400)).dropna(subset=['date','hg','ag']).sort_values('date',ascending=False).reset_index(drop=True)
target=df[df.date==pd.Timestamp(now.date())].drop_duplicates('eid')
target=target[[competition_policy.allowed(r.country,r.league,key=str(r.div)[3:],home=r.home,away=r.away) for r in target.itertuples()]]
old=df[(df.date>=pd.Timestamp(now.date())-pd.Timedelta(days=400)) & (df.date<=pd.Timestamp(now.date()))].copy()
new0=scanner.prediction_history_as_of(df,now)
new, integrity=history_integrity.reconcile_livescore_ids(new0)
new=new[new.date>=pd.Timestamp(now.date())-pd.Timedelta(days=400)]
scanner.ACACHE=None;scanner.RAW_RATINGS.clear();scanner.SEASON_STARTS.clear()
def calculate(hist,signals):
    scanner.TEAM_HIST_CACHE.clear();scanner.PROFILE_CACHE.clear()
    avgs=scanner.compute_div_avgs(hist,now); long=scanner.make_long(hist,avgs); scanner.build_long_index(long)
    bl=model_signals.sot_baselines(hist); out={}
    for r in target.itertuples(index=False):
        H=scanner.build_profile(long,r.country,r.home,'H',now,r.home_id); A=scanner.build_profile(long,r.country,r.away,'A',now,r.away_id)
        if not (H.ok and A.ok): continue
        da=avgs.get(r.div,avgs['__global__'])
        lh=min(max(da.mu_h*H.att*A.dfc,.15),4.5);la=min(max(da.mu_a*A.att*H.dfc,.15),4.5)
        if signals:
            lh,_=model_signals.goal_adjustment(lh,H,A,bl.get(str(r.div)));la,_=model_signals.goal_adjustment(la,A,H,bl.get(str(r.div)))
        M=scanner.score_matrix(lh,la,scanner.CONFIG['DC_RHO']);p=scanner.probs_from_matrix(M);p.update(markets.one_x_two(M))
        out[str(r.eid)]={'p':{k:p[k] for k in ('O15','O25','BTTS','H','D','A')}, 'y':{'O15':int(r.hg+r.ag>=2),'O25':int(r.hg+r.ag>=3),'BTTS':int(r.hg>0 and r.ag>0),'H':int(r.hg>r.ag),'D':int(r.hg==r.ag),'A':int(r.hg<r.ag)}}
    return out
before=calculate(old,True);after=calculate(new,False);matched=sorted(set(before)&set(after)); metrics={}
for k in ('O15','O25','BTTS','H','D','A'):
    a=np.array([before[i]['p'][k] for i in matched]);b=np.array([after[i]['p'][k] for i in matched]);y=np.array([before[i]['y'][k] for i in matched]);
    metrics[k]={'n':len(a),'mean_old':float(a.mean()),'mean_new':float(b.mean()),'mean_abs_change_pp':float(abs(a-b).mean()*100),'max_abs_change_pp':float(abs(a-b).max()*100),'old_brier':float(((a-y)**2).mean()),'new_brier':float(((b-y)**2).mean())}
print(json.dumps({'as_of':'2026-11-04 00:00 SAST','input':'postdated pinned world archive only, target IDs deduplicated, no odds or prices',
 'caveat':'retrospective; targets and features may have been backfilled; old model includes same-day scores; one day, not accuracy proof',
 'coverage':{'target_events':len(target),'old_eligible':len(before),'new_eligible':len(after),'matched':len(matched),'old_history':len(old),'new_history':len(new),'same_day_old':int((old.date==pd.Timestamp(now.date())).sum()),'integrity':integrity},
 'recommendation_counts':'not available: no verified historical SportyBet prices or published eligible selection data', 'markets':metrics},indent=2,allow_nan=False))
