#!/usr/bin/env python3
"""Offline, non-mutating inventory of a pinned data-branch snapshot.

Usage: PYTHONDONTWRITEBYTECODE=1 python research/model_diagnostics/inventory.py SNAPSHOT_DIR
SNAPSHOT_DIR must contain data/cache and data/ls/stages. Output is JSON to stdout.
Candidate cross-provider matches use exact country/date and normalized *ordered* team names;
they are not canonical identities and are never merged. The 400-day subset uses
2026-11-04 00:00 SAST as an illustrative fixed cutoff. Main 2026/27 live and extra
football-data files are not present in this snapshot, so denominators are partial.
"""
import collections, hashlib, json, re, sys, unicodedata
from pathlib import Path
import pandas as pd

root = Path(sys.argv[1]); cut = pd.Timestamp('2026-11-04'); start = cut - pd.Timedelta(days=400)

def norm(x):
    x = unicodedata.normalize('NFKD',str(x)).encode('ascii','ignore').decode().lower()
    return ' '.join(re.findall(r'[a-z0-9]+',x))

def filehash(p): return hashlib.sha256(p.read_bytes()).hexdigest()

# Names from current production mapping, not fuzzy similarity.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import scanner
main=[]; files=sorted((root/'data/cache').glob('fd_*.csv'))
for p in files:
    m=re.fullmatch(r'fd_(\d{4})_(.+)\.csv',p.name)
    if not m or m[2] not in scanner.MAIN_LEAGUES: continue
    d=pd.read_csv(p,low_memory=False)
    if not {'Date','HomeTeam','AwayTeam','FTHG','FTAG'}<=set(d): continue
    dates=scanner.parse_dates(d.Date)
    for i in range(len(d)):
        row=d.iloc[i]; dt=dates.iloc[i]
        if pd.isna(dt) or dt>=cut or pd.isna(row.FTHG) or pd.isna(row.FTAG): continue
        main.append({'country':scanner.MAIN_LEAGUES[m[2]][0], 'div':m[2], 'date':dt.strftime('%Y-%m-%d'),
         'home':str(row.HomeTeam),'away':str(row.AwayTeam),'hg':int(row.FTHG),'ag':int(row.FTAG),
         'hc':None if pd.isna(row.get('HC')) else int(row['HC']),'ac':None if pd.isna(row.get('AC')) else int(row['AC']),
         'hst':None if pd.isna(row.get('HST')) else int(row['HST']),'ast':None if pd.isna(row.get('AST')) else int(row['AST']), 'source':p.name})
world=[]
for p in sorted((root/'data/ls/stages').glob('*.json')):
    d=json.loads(p.read_text(encoding='utf-8')); sts=d.get('stats') or {}
    for eid,v in (d.get('events') or {}).items():
        if len(v)!=9: continue
        es,hid,h,aid,a,hg,ag,*_=v
        if hg is None or ag is None or str(es)[:8] >= '20261104':continue
        st=sts.get(eid) or []; val=lambda i: st[i] if len(st)>i else None
        world.append({'country':d.get('country') or '', 'div':d.get('key') or p.stem,
          'date':f'{str(es)[:4]}-{str(es)[4:6]}-{str(es)[6:8]}', 'home':h,'away':a,'hg':int(hg),'ag':int(ag),
          'hc':val(0),'ac':val(1),'hst':val(8),'ast':val(9),'eid':str(eid),'file':p.name})

def key(r):return (norm(r['country']),r['date'],norm(r['home']),norm(r['away']))
def matches(m,w):
    idx=collections.defaultdict(list)
    for x in w:idx[key(x)].append(x)
    pairs=[(x,y) for x in m for y in idx.get(key(x),[])]
    # Unique identity candidates, while preserving all underlying rows for denominators.
    field={}
    for f in ('score','hc','ac','hst','ast'):
        comparable=[(a,b) for a,b in pairs if (f=='score' or (a[f] is not None and b[f] is not None))]
        dif=[(a,b) for a,b in comparable if ((a['hg'],a['ag'])!=(b['hg'],b['ag']) if f=='score' else a[f]!=b[f])]
        field[f]={'comparable_pairs':len(comparable),'conflicting_pairs':len(dif),'fraction':round(len(dif)/len(comparable),6) if comparable else None,
          'examples':[{'date':a['date'],'match':a['home']+' v '+a['away'],'field':f,'football_data':([a['hg'],a['ag']] if f=='score' else a[f]),'livescore':([b['hg'],b['ag']] if f=='score' else b[f]),'fd_file':a['source'],'ls_file':b['file'],'eid':b['eid']} for a,b in dif[:8]]}
    return {'main_rows':len(m),'world_rows':len(w),'candidate_pairs':len(pairs),'unique_main_candidate_rows':len({id(a) for a,b in pairs}),
       'unique_world_candidate_rows':len({id(b) for a,b in pairs}),'unique_keys':len({key(a) for a,b in pairs}), 'fields':field,
       'examples':[{'date':a['date'],'match':a['home']+' v '+a['away'],'country':a['country'],'football_data':a['source'],'livescore':b['file'],'eid':b['eid']} for a,b in pairs[:8]]}

def eid_analysis(w):
    by=collections.defaultdict(list)
    for r in w:by[r['eid']].append(r)
    groups=[v for v in by.values() if len(v)>1]
    conflicts=[v for v in groups if len({(r['date'],r['hg'],r['ag']) for r in v})>1]
    stats={}
    for field in ('hc','ac','hst','ast'):
        comparable=[v for v in groups if sum(r[field] is not None for r in v)>=2]
        bad=[v for v in comparable if len({r[field] for r in v if r[field] is not None})>1]
        stats[field]={'comparable_groups':len(comparable),'conflicting_groups':len(bad),
                      'examples':[{'eid':v[0]['eid'],'values':[{'file':r['file'],'value':r[field]} for r in v]} for v in bad[:3]]}
    return {'rows':len(w),'unique_ids':len(by),'duplicate_id_groups':len(groups),'extra_rows':sum(len(v)-1 for v in groups),
            'id_groups_with_date_or_score_conflict':len(conflicts),'duplicate_id_stat_conflicts':stats,
            'examples':[{'eid':v[0]['eid'],'entries':[{k:r[k] for k in ('date','home','away','hg','ag','div','file')} for r in v]} for v in (conflicts[:5] or groups[:5])]}
wm=[r for r in world if r['date']>=start.strftime('%Y-%m-%d')]; mm=[r for r in main if r['date']>=start.strftime('%Y-%m-%d')]
columns=collections.Counter(); nrow=0
for p in files:
    d=pd.read_csv(p,low_memory=False);nrow+=len(d)
    for c in ('HxG','AxG','HST','AST','HC','AC'):
        if c in d:columns[c]+=int(d[c].notna().sum())
future=[]
for p in sorted((root/'data/ls/stages').glob('*.json')):
    d=json.loads(p.read_text(encoding='utf-8'))
    for eid,v in (d.get('events') or {}).items():
        if len(v)==9 and str(v[0])[:8]>='20261104':
            future.append({'eid':eid,'kickoff':v[0],'home':v[2],'away':v[4],'score':[v[5],v[6]],'stage':d.get('key')})
print(json.dumps({'snapshot':str(root),'cutoff':'2026-11-04 00:00 SAST','window_start':start.strftime('%Y-%m-%d'),'cache_files':len(files),'cache_rows_all':nrow,'cache_nonnull_columns':dict(columns),
 'cache_sha256':{p.name:filehash(p) for p in files},'stage_sha256':{p.name:filehash(p) for p in sorted((root/'data/ls/stages').glob('*.json'))},
 'all_pre_cut':matches(main,world),'last_400_days':matches(mm,wm),'world_eids_all_pre_cut':eid_analysis(world),'world_eids_last_400_days':eid_analysis(wm),
 'future_events_in_snapshot':len(future),'future_scored_events':sum(x['score'][0] is not None and x['score'][1] is not None for x in future),'future_examples':future[:8]},indent=2))
