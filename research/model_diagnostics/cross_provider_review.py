#!/usr/bin/env python3
"""Offline cross-provider review queue for the pinned snapshot; writes JSON to stdout.

Only cached main football-data seasons are available; extra/current feeds and
point-in-time collection timestamps are absent. No approval is created here.
"""
import collections, json, logging, sys
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import scanner, worldfeed, history_integrity, cross_provider

logging.disable(logging.CRITICAL)
root=Path(sys.argv[1])/'data'; now=datetime(2026,11,4)
scanner.fetch_cached=lambda url,name: (root/'cache'/name).read_bytes() if (root/'cache'/name).exists() else None
main=scanner.load_main_results(set(scanner.MAIN_LEAGUES), ['2223','2324','2425','2526'])
world=worldfeed.Archive(root/'ls').results_frame(now-timedelta(days=400))
main=scanner.prediction_history_as_of(main,now);world=scanner.prediction_history_as_of(world,now)
since=pd.Timestamp(now.date())-pd.Timedelta(days=400)
main=main[main.date>=since];world=world[world.date>=since]
world,world_audit=history_integrity.reconcile_livescore_ids(world)
rows=pd.concat([main,world],ignore_index=True).sort_values('date',ascending=False).reset_index(drop=True)
_, summary, entries=cross_provider.reconcile(rows,{},True)
reasons=collections.Counter(r for e in entries for r in e.get('reasons',[]))
fields=collections.Counter(k for e in entries for k in e.get('stat_conflicts',{}))
kickoffs=collections.Counter(e.get('kickoff_comparison','not_comparable') for e in entries)
comps=collections.Counter((e['football_data']['country'],e['football_data']['league'],e['livescore']['league'])
                          for e in entries if e['status']=='needs_review')
result={'method':{'cutoff':str(now),'window_start':str(since.date()),'snapshot':str(root.parent),
          'limitations':['postdated snapshot, no collection timestamps', 'cached historical main divisions only; missing live season and extra feeds',
                         'normalization finds candidates only; none is proof of identity or data correctness',
                         'kickoff clocks lack proven time zones and are flagged for review; equal clock values do not prove identity',
                         'no independent reviewed identity mapping supplied; no approvals are created']},
        'coverage':{'football_data_rows':len(main),'livescore_rows_after_id_dedupe':len(world),'livescore_id_audit':world_audit,
                    'review_summary':summary,'blocked_reasons':dict(reasons),'conflicting_stat_fields':dict(fields),'kickoff_comparison':dict(kickoffs),
                    'eligible_competitions':[{'country':c,'football_data':a,'livescore':b,'candidates':n} for (c,a,b),n in comps.most_common()]},
        'candidates':entries}
print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
