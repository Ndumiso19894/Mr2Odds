#!/usr/bin/env python3
"""Reproduce as-of problems from a pinned, read-only Livescore archive snapshot."""
from pathlib import Path
from datetime import datetime
import json,sys
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import scanner,trends,worldfeed
root=Path(sys.argv[1]); archive=worldfeed.Archive(root/'data/ls')
pool=archive.results_frame(datetime(2022,1,1)).dropna(subset=['date','hg','ag']).sort_values('date',ascending=False).reset_index(drop=True)
scanner.build_h2h_index(pool)
f=pool[(pool.home=='KF Tirana') & (pool.away=='Teuta Durres') & (pool.date==pd.Timestamp('2026-11-07'))].iloc[0]
h2h=scanner.head_to_head(pool,f.country,f.home,f.away,home_id=f.home_id,away_id=f.away_id)
lg=trends._long(pool); recent=trends.team_rows(lg,'France','Rennes')
rr=recent.head(4)
future_2027=pool[pool.date>=pd.Timestamp('2027-01-01')]
print(json.dumps({'simulated_scan_time':'2026-11-04 00:00 SAST', 'later_snapshot_only':True,
  'future_fixture_example':{'eid':f.eid,'home':f.home,'away':f.away,'date':str(f.date.date()),'score':[int(f.hg),int(f.ag)],
  'h2h_returned':[{'date':str(x['date'].date()),'home':x['home'],'away':x['away'],'score':[x['hg'],x['ag']]} for x in h2h[:4]]},
  'psg_rennes_h2h':[{'date':str(x['date'].date()),'home':x['home'],'away':x['away'],'score':[x['hg'],x['ag']]} for x in scanner.head_to_head(pool,'France','Paris Saint-Germain','Rennes')[:3]],
  'rennes_trend_input':[{'date':str(x.date.date()),'team':x.team,'opponent':x.opp,'score':[int(x.gf),int(x.ga)]} for x in rr.itertuples()],
  'archive_records_dated_2027':[{'date':str(x.date.date()),'home':x.home,'away':x.away,'score':[int(x.hg),int(x.ag)],'eid':x.eid} for x in future_2027.itertuples()],
  'model_result_filter':'scanner.main filters goal-model rows to date <= scan date; H2H and trends receive unbounded older pool',
  'note':'Archived future-dated scores may be erroneous records; their truth has not been verified.'},indent=2))
