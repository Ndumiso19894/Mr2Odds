#!/usr/bin/env python3
"""Retrospective date-ordered WORLD-ARCHIVE-ONLY signal ablation, NOT a production replay.

Input is a pinned later data-branch snapshot; input-availability times are absent.
All historical rows (including duplicate IDs) remain unchanged.  Target rows are
not deduplicated either. We only use outcomes from calendar days strictly before
prediction day. Run with PYTHONDONTWRITEBYTECODE=1; writes JSON to stdout only.

Usage: python research/model_diagnostics/replay.py SNAPSHOT_DIR [END_EXCLUSIVE]
"""
from pathlib import Path
import collections, json, math, sys, time
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import scanner, worldfeed, model_signals, markets, competition_policy

root=Path(sys.argv[1]); start=pd.Timestamp('2026-09-25'); end=pd.Timestamp(sys.argv[2] if len(sys.argv)>2 else '2026-11-04')
a=worldfeed.Archive(root/'data/ls'); df=a.results_frame((start-pd.Timedelta(days=400)).to_pydatetime())
df=df.dropna(subset=['date','hg','ag']); df=df[df.date<end].sort_values('date',ascending=False).reset_index(drop=True)
# Date-only backtest. Source timestamps cannot establish availability at kickoff.
rows=[]; perday=[]; ts=time.time()
scanner.ACACHE=None; scanner.RAW_RATINGS.clear(); scanner.SEASON_STARTS.clear()
for day in pd.date_range(start,end-pd.Timedelta(days=1)):
    targets=df[df.date==day]
    targets=targets[[competition_policy.allowed(r.country,r.league,key=str(r.div)[3:],home=r.home,away=r.away) for r in targets.itertuples()]]
    if targets.empty:continue
    past=df[(df.date<day)&(df.date>=day-pd.Timedelta(days=400))].copy()
    assert past.empty or past.date.max()<day
    now=day.to_pydatetime(); avgs=scanner.compute_div_avgs(past,now); lg=scanner.make_long(past,avgs)
    scanner.TEAM_HIST_CACHE.clear(); scanner.PROFILE_CACHE.clear(); scanner.build_long_index(lg)
    baselines=model_signals.sot_baselines(past)
    cm=markets.CountModel(past,'hc','ac',now,markets.CORNERS)
    off=past.dropna(subset=['hsoff','asoff'])
    off=off[off.hsoff.between(0,50)&off.asoff.between(0,50)]
    if not off.empty:off=off[off.groupby('div')['div'].transform('size')>=30]
    om=markets.CountModel(off,'hsoff','asoff',now,markets.CORNERS) if not off.empty and off.hsoff.mean()>0 and off.asoff.mean()>0 else None
    for r in targets.itertuples(index=False):
        H=scanner.build_profile(lg,r.country,r.home,'H',now,r.home_id); A=scanner.build_profile(lg,r.country,r.away,'A',now,r.away_id)
        if not (H.ok and A.ok):continue
        g=avgs.get('__global__',scanner.DivAvg(1.45,1.2,0,float('nan'),float('nan'))); da=avgs.get(r.div,g)
        lh=min(max(da.mu_h*H.att*A.dfc,.15),4.5); la=min(max(da.mu_a*A.att*H.dfc,.15),4.5)
        sh,dh=model_signals.goal_adjustment(lh,H,A,baselines.get(str(r.div))); sa,da_=model_signals.goal_adjustment(la,A,H,baselines.get(str(r.div)))
        base=scanner.probs_from_matrix(scanner.score_matrix(lh,la,scanner.CONFIG['DC_RHO']))
        adjusted=scanner.probs_from_matrix(scanner.score_matrix(sh,sa,scanner.CONFIG['DC_RHO']))
        pH=markets.one_x_two(scanner.score_matrix(lh,la,scanner.CONFIG['DC_RHO']))
        pS=markets.one_x_two(scanner.score_matrix(sh,sa,scanner.CONFIG['DC_RHO']))
        hs,as_=int(r.hg),int(r.ag); y={'O15':int(hs+as_>=2),'O25':int(hs+as_>=3),'BTTS':int(hs>0 and as_>0),'H':int(hs>as_),'D':int(hs==as_),'A':int(hs<as_)}
        base.update({k:pH[k] for k in ('H','D','A')}); adjusted.update({k:pS[k] for k in ('H','D','A')})
        item={'day':str(day.date()),'eid':str(r.eid),'goals':{'base':base,'signal':adjusted,'outcome':y},
              'xg_applied':bool(dh['xg_applied'] or da_['xg_applied']),'sot_applied':bool(dh['sot_applied'] or da_['sot_applied']),'corner_applied':False}
        ex=cm.expect(r.country,r.home,r.away,r.div) if cm.ok else None
        if ex is not None and ex.h_n>=5 and ex.a_n>=5 and pd.notna(r.hc) and pd.notna(r.ac):
            eh,ea=ex.eh,ex.ea; bh,ba=eh,ea; oe=om.expect(r.country,r.home,r.away,r.div) if om and om.ok else None
            if oe is not None and oe.h_n>=5 and oe.a_n>=5 and str(r.div) in om.div_avg:
                oh,oa=om._div(r.div); eh,ea,info=model_signals.corner_adjustment(eh,ea,oe.eh,oe.ea,oh,oa)
                item['corner_applied']=bool(info['applied'])
            counts={'base':{},'signal':{},'outcome':{}}
            for line in markets.CORNERS['lines_total']:
                k='O'+str(line); counts['base'][k]=markets.over_line(bh+ba,markets.CORNERS['r_total'],line); counts['signal'][k]=markets.over_line(eh+ea,markets.CORNERS['r_total'],line);counts['outcome'][k]=int(r.hc+r.ac>line)
            for side,b,e,actual in [('H',bh,eh,r.hc),('A',ba,ea,r.ac)]:
                for line in markets.CORNERS['lines_team']:
                    k=side+'O'+str(line);counts['base'][k]=markets.over_line(b,markets.CORNERS['r_team'],line);counts['signal'][k]=markets.over_line(e,markets.CORNERS['r_team'],line);counts['outcome'][k]=int(actual>line)
            item['corners']=counts
        rows.append(item)
    perday.append({'day':str(day.date()),'target_rows':len(targets),'history_rows':len(past),'predictions':sum(x['day']==str(day.date()) for x in rows)})
    print(f'{day.date()} targets={len(targets)} predictions={perday[-1]["predictions"]} elapsed={time.time()-ts:.1f}s',file=sys.stderr,flush=True)

def measure(items,kind,market):
    out={}
    for variant in ('base','signal'):
        p=np.clip(np.array([r[kind][variant][market] for r in items],dtype=float),1e-12,1-1e-12); y=np.array([r[kind]['outcome'][market] for r in items],dtype=float)
        if not len(p):out[variant]=None;continue
        bins=[]
        for lo in np.arange(0,1,.1):
            mask=(p>=lo)&(p<lo+.1+1e-10) if lo>.899 else (p>=lo)&(p<lo+.1)
            if mask.any():bins.append({'range':f'{lo:.1f}-{lo+.1:.1f}','n':int(mask.sum()),'predicted':round(float(p[mask].mean()),6),'actual':round(float(y[mask].mean()),6)})
        out[variant]={'n':len(p),'brier':round(float(np.mean((p-y)**2)),6),'log_loss':round(float(np.mean(-y*np.log(p)-(1-y)*np.log(1-p))),6),
                      'mean_predicted':round(float(p.mean()),6),'actual':round(float(y.mean()),6),'calibration_bins':bins}
    # Paired change (signal minus baseline), resampling whole calendar days so
    # match correlations within a day do not masquerade as independent evidence.
    if items:
        y=np.asarray([r[kind]['outcome'][market] for r in items],dtype=float)
        a=np.clip(np.asarray([r[kind]['base'][market] for r in items],dtype=float),1e-12,1-1e-12)
        b=np.clip(np.asarray([r[kind]['signal'][market] for r in items],dtype=float),1e-12,1-1e-12)
        groups=collections.defaultdict(list)
        for i,r in enumerate(items):groups[r['day']].append(i)
        idx=list(groups.values()); rng=np.random.default_rng(19894)
        out['paired_delta']={}
        for metric,delta in [('brier',(b-y)**2-(a-y)**2),('log_loss',(-y*np.log(b)-(1-y)*np.log(1-b))-(-y*np.log(a)-(1-y)*np.log(1-a)))]:
            sums=np.asarray([delta[z].sum() for z in idx]); ns=np.asarray([len(z) for z in idx]); picks=rng.integers(0,len(idx),size=(2000,len(idx)))
            boot=sums[picks].sum(axis=1)/ns[picks].sum(axis=1)
            out['paired_delta'][metric]={'mean':round(float(delta.mean()),8),'day_bootstrap_95': [round(float(x),8) for x in np.quantile(boot,[.025,.975])], 'days':len(idx)}
    return out

def block(items,kind,keys):return {k:measure(items,kind,k) for k in keys}
g=[r for r in rows if r['sot_applied']]; c=[r for r in rows if r.get('corner_applied') and 'corners' in r]
result={'method':{'source':'Livescore world archive only, retrospective, not availability-time verified','start':str(start.date()),'end_exclusive':str(end.date()),'history':'strictly previous dates, max 400 days, archive rows retained exactly',
                  'goal_sample':'both goal profiles n_eff >= 4; matched to SOT applied on either side','corner_sample':'both count profiles >=5 observations, observed corner counts; matched to off-target adjustment applied',
                  'limitations':['no football-data live/extra source; global priors differ from production','no xG in Livescore archive','future snapshot data may have been collected after match day','calculated targets are world rows; no retrospective fixture identity/price/selection verification','missing-stat evaluation may be selective']},
        'coverage':{'eligible_predictions':len(rows),'sot_applied':len(g),'xg_applied':sum(x['xg_applied'] for x in rows),'corners_with_outcomes':sum('corners' in x for x in rows),'off_target_applied_with_outcome':len(c),
                    'dates':len(perday),'archive_rows_before_end':len(df)},'per_day':perday,
        'goals_sot_matched':block(g,'goals',['O15','O25','BTTS','H','D','A']),
        'corners_off_target_matched':block(c,'corners',['O8.5','O9.5','O10.5','O11.5','HO3.5','HO4.5','HO5.5','AO3.5','AO4.5','AO5.5'])}
print(json.dumps(result,indent=2,allow_nan=False))
