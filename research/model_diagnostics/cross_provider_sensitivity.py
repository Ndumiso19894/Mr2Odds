#!/usr/bin/env python3
"""Hypothetical bulk cross-provider merge sensitivity, NEVER an approval list.

Uses the pinned postdated snapshot and same November 4 target rows in both runs;
matching candidates are NOT independently verified. Prints JSON to stdout.
"""
import hashlib, json, logging, sys
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import scanner, worldfeed, history_integrity, cross_provider, markets, competition_policy
logging.disable(logging.CRITICAL)
root=Path(sys.argv[1])/'data'
now=datetime.strptime(sys.argv[3],'%Y-%m-%d') if len(sys.argv)>3 else datetime(2026,11,4)
since=pd.Timestamp(now.date())-pd.Timedelta(days=400)
scanner.fetch_cached=lambda url,name:(root/'cache'/name).read_bytes() if (root/'cache'/name).exists() else None
main=scanner.load_main_results(set(scanner.MAIN_LEAGUES),['2223','2324','2425','2526'])
world=worldfeed.Archive(root/'ls').results_frame(now-timedelta(days=400))
target=world[world.date==pd.Timestamp(now.date())].drop_duplicates('eid')
target=target[[competition_policy.allowed(r.country,r.league,key=str(r.div)[3:],home=r.home,away=r.away) for r in target.itertuples()]]
if len(sys.argv)>3:
    target=target[(target.country=='England')&(target.league=='Premier League')]
main=scanner.prediction_history_as_of(main,now);world=scanner.prediction_history_as_of(world,now)
main=main[main.date>=since];world=world[world.date>=since]
world,_=history_integrity.reconcile_livescore_ids(world)
before=pd.concat([main,world],ignore_index=True).sort_values('date',ascending=False).reset_index(drop=True)
# Deliberately hypothetical: this does NOT review or approve identities.
entries=[item for item,_,_ in cross_provider.candidates(before) if item['status']=='needs_review']
if len(sys.argv)>2:
    requested={r['candidate_id'] for r in json.loads(Path(sys.argv[2]).read_text())['records']}
    entries=[e for e in entries if e['candidate_id'] in requested]
    if {e['candidate_id'] for e in entries} != requested:
        raise ValueError('batch candidates no longer uniquely eligible; refusing sensitivity run')
hypothetical={e['candidate_id']:{'reviewed_by':'HYPOTHETICAL - NOT AN APPROVAL','rationale':'sensitivity only','evidence':'none'} for e in entries}
actual_approvals=cross_provider.load_approvals()
actual, actual_audit, _=cross_provider.reconcile(before,actual_approvals)
actual_inputs_equal=before.equals(actual)
after, audit, _=cross_provider.reconcile(before,hypothetical)
scanner.ACACHE=None;scanner.RAW_RATINGS.clear();scanner.SEASON_STARTS.clear()
def calculate(hist):
    scanner.TEAM_HIST_CACHE.clear();scanner.PROFILE_CACHE.clear();scanner.H2H_CACHE.clear()
    avgs=scanner.compute_div_avgs(hist,now);long=scanner.make_long(hist,avgs)
    scanner.build_long_index(long);scanner.build_h2h_index(hist)
    cm=markets.CountModel(hist,'hc','ac',now,markets.CORNERS);out={}
    for r in target.itertuples(index=False):
        H=scanner.build_profile(long,r.country,r.home,'H',now,r.home_id);A=scanner.build_profile(long,r.country,r.away,'A',now,r.away_id)
        if not(H.ok and A.ok):continue
        d=avgs.get(r.div,avgs['__global__'])
        h=min(max(d.mu_h*H.att*A.dfc,.15),4.5);a=min(max(d.mu_a*A.att*H.dfc,.15),4.5)
        mat=scanner.score_matrix(h,a,scanner.CONFIG['DC_RHO']);p=scanner.probs_from_matrix(mat);p.update(markets.one_x_two(mat))
        out[str(r.eid)]={'p':{k:p[k] for k in ('O15','O25','BTTS','H','D','A')},'h_n':H.n,'a_n':A.n,
            'h2h_n':len(scanner.head_to_head(hist,r.country,r.home,r.away,home_id=r.home_id,away_id=r.away_id))}
        c=cm.expect(r.country,r.home,r.away,r.div) if cm.ok else None
        if c is not None:
            out[str(r.eid)]['corner_n']=[c.h_n,c.a_n]
            out[str(r.eid)]['corner_sample_digest']=[hashlib.sha256(repr(cm.team.get((r.country, team), [])[-markets.MAX_N:]).encode()).hexdigest() for team in (r.home,r.away)]
            if c.h_n>=5 and c.a_n>=5:
                out[str(r.eid)]['corner_o95']=markets.over_line(c.total,markets.CORNERS['r_total'],9.5)
    return out
old=calculate(before);new=calculate(after);matched=sorted(set(old)&set(new)); markets_out={}
for k in ('O15','O25','BTTS','H','D','A'):
    x=np.array([old[i]['p'][k] for i in matched]);y=np.array([new[i]['p'][k] for i in matched])
    markets_out[k]={'n':len(matched),'old_mean':float(x.mean()),'new_mean':float(y.mean()),
                    'mean_absolute_change_pp':float(abs(x-y).mean()*100),'max_absolute_change_pp':float(abs(x-y).max()*100)}
corner=[i for i in matched if 'corner_o95' in old[i] and 'corner_o95' in new[i]]
if corner:
    x=np.array([old[i]['corner_o95'] for i in corner]);y=np.array([new[i]['corner_o95'] for i in corner]);
    markets_out['corner_o95']={'n':len(corner),'old_mean':float(x.mean()),'new_mean':float(y.mean()),'mean_absolute_change_pp':float(abs(x-y).mean()*100),'max_absolute_change_pp':float(abs(x-y).max()*100)}
print(json.dumps({'warning':'HYPOTHETICAL UNREVIEWED MERGES. Never use this experiment as an approval or proof of identity or predictive improvement.',
 'scope':f'World targets on {now.date()}; {"England Premier League targets only; " if len(sys.argv)>3 else ""}cached historical main leagues plus world; same prior-day cutoff and signals off; no verified prices; postdated archive',
 'coverage':{'actual_approval_count':len(actual_approvals),'actual_rows_removed':actual_audit['rows_removed'],
 'actual_input_identical_to_before':actual_inputs_equal,
 'hypothetical_candidate_count':len(entries),'targets':len(target),'old_eligible':len(old),'hypothetical_eligible':len(new),'matched':len(matched),'old_rows':len(before),'hypothetical_rows':len(after),'audit':audit,
 'h2h_changed':sum(old[i]['h2h_n']!=new[i]['h2h_n'] for i in matched),
 'goal_team_sample_changed':sum(old[i]['h_n']!=new[i]['h_n'] or old[i]['a_n']!=new[i]['a_n'] for i in matched),
 'corner_team_sample_count_changed':sum(old[i].get('corner_n')!=new[i].get('corner_n') for i in matched),
 'corner_team_sample_content_changed':sum(old[i].get('corner_sample_digest')!=new[i].get('corner_sample_digest') for i in matched)},'markets':markets_out},indent=2,allow_nan=False))
