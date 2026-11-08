#!/usr/bin/env python3
"""Verify five candidate fixtures against pinned FPL and OpenFootball snapshots.

Inputs are local copies, fetched separately; this never edits the approvals file.
FPL and OpenFootball are corroborating repositories; their upstream independence
is not proven. A Livescore local clock without recorded offset is not verified.
"""
import argparse, hashlib, json, re
from pathlib import Path
from datetime import timedelta, timezone
import pandas as pd

FIXTURES = [
    ('2026-05-24', 'Crystal Palace', 'Arsenal'),
    ('2026-05-24', 'Liverpool', 'Brentford'),
    ('2026-05-18', 'Arsenal', 'Burnley'),
    ('2026-05-17', 'Everton', 'Sunderland'),
    ('2026-05-15', 'Aston Villa', 'Liverpool'),
]
FPL_COMMIT = 'a8337d50698de908f92e8d1905142d968384a2ca'
OF_COMMIT = '1d0afcbd66d88df55e98166dd7d986d7c56d82ab'
EXPECTED_HASHES = {
    'fixtures': '2d7e3950d346df14ca486cb09e9b9ba406d37d943775244eed06cdc021ffb3a9',
    'teams': 'b29df099cb0ad25413e284e53116099b0e0496874f99743dbc0870d8241b46c5',
    'openfootball': 'cbc433be6594afec7c495a80e034578245ddda8cb0e9826743297471f188ceae',
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def openfootball_utc(date, text):
    # Some parsers interpret 'UTC+1' using POSIX's reversed-sign convention.
    match=re.fullmatch(r'(\d{2}:\d{2}) UTC([+-]\d{1,2})',text)
    if not match or abs(int(match.group(2)))>14:
        raise ValueError(f'unsupported OpenFootball time: {text}')
    offset=timezone(timedelta(hours=int(match.group(2))))
    return pd.Timestamp(f"{date} {match.group(1)}").tz_localize(offset).tz_convert('UTC')


def verify(review, fixtures, teams, openfootball):
    queue=json.loads(Path(review).read_text(encoding='utf-8'))['candidates']
    fpl=pd.read_csv(fixtures); clubs=pd.read_csv(teams).set_index('id')['name'].to_dict()
    matches=json.loads(Path(openfootball).read_text(encoding='utf-8'))
    if matches.get('name') != 'England | Premier League 2025/26':
        raise ValueError('unexpected OpenFootball competition')
    games=matches['matches']; out=[]
    for date, home, away in FIXTURES:
        c=[e for e in queue if e.get('status')=='needs_review' and e['football_data'].get('country')=='England'
           and e['football_data'].get('league')=='Premier League' and e['football_data']['date'][:10]==date
           and e['football_data']['home']==home and e['football_data']['away']==away]
        if len(c)!=1:
            raise ValueError(f'candidate not unique: {date} {home} {away}: {len(c)}')
        e=c[0];fd=e['football_data'];ls=e['livescore']
        f=fpl[(fpl.team_h.map(clubs)==home)&(fpl.team_a.map(clubs)==away)&
              (pd.to_datetime(fpl.kickoff_time,utc=True).dt.strftime('%Y-%m-%d')==date)]
        of=[x for x in games if x['date']==date and x['team1']==home and x['team2']==away]
        if len(f)!=1 or len(of)!=1:
            raise ValueError(f'external fixture not unique: {date} {home} {away}')
        r=f.iloc[0];o=of[0]
        if not (r['finished'] == True and r['finished_provisional'] == True):
            raise ValueError(f'FPL fixture not marked finished: {date} {home} {away}')
        utc=pd.Timestamp(r.kickoff_time)
        fd_utc=pd.Timestamp(f"{date} {fd['_history_kickoff']}").tz_localize('Europe/London',ambiguous='raise',nonexistent='raise').tz_convert('UTC')
        of_utc=openfootball_utc(date,o['time'])
        expected_ls=(utc+timedelta(hours=2)).strftime('%H:%M')
        score=[int(r.team_h_score),int(r.team_a_score)]
        if not (score==[int(fd['hg']),int(fd['ag'])]==[int(ls['hg']),int(ls['ag'])]==o['score']['ft']):
            raise ValueError(f'score mismatch: {date} {home} {away}')
        if not (utc==fd_utc==of_utc):
            raise ValueError(f'UTC kickoff mismatch: {date} {home} {away}')
        if ls['_history_kickoff'] != expected_ls:
            raise ValueError(f'Livescore time inconsistent with assumed UTC+2: {date} {home} {away}')
        out.append({'date':date,'home':home,'away':away,'score':score,'candidate_id':e['candidate_id'],
                    'livescore_event_id':str(ls['eid']),'fpl_fixture_id':int(r['id']),'fpl_event_code':int(r['code']),
                    'utc_kickoff':utc.isoformat(),'football_data_clock':fd['_history_kickoff'],
                    'football_data_timezone':'Europe/London (scanner feed convention)',
                    'livescore_recorded_clock':ls['_history_kickoff'],
                    'livescore_clock_check':'matches UTC+2, but record has no captured timezone: unverified',
                    'openfootball_time':o['time'],'openfootball_ground':o.get('ground'),
                    'stat_conflicts':e['stat_conflicts'],
                    'decision':'corroborated_fixture_but_not_approved: original Livescore time-zone provenance missing'})
    return {'scope':'five unique Premier League matches from a postdated model snapshot; identity/time corroboration only',
       'sources':{'fpl_fixture_url':f'https://github.com/vaastav/Fantasy-Premier-League/blob/{FPL_COMMIT}/data/2025-26/fixtures.csv',
                  'fpl_teams_url':f'https://github.com/vaastav/Fantasy-Premier-League/blob/{FPL_COMMIT}/data/2025-26/teams.csv',
                  'fpl_fixtures_sha256':sha(fixtures),'fpl_teams_sha256':sha(teams),
                  'openfootball_url':f'https://github.com/openfootball/football.json/blob/{OF_COMMIT}/2025-26/en.1-full.json',
                  'openfootball_sha256':sha(openfootball),'candidate_review_sha256':sha(review)},
       'limitations':['FPL source is a third-party mirror of official FPL data, not a direct authenticated API response',
          'OpenFootball and FPL upstream source independence is not established',
          'Livescore archive records do not preserve the requested offset; UTC+2 matches are assumptions, not verified provenance',
          'retrospective model snapshot postdates simulated cutoff and cannot establish data or quote availability',
          'third-party source data is used as evidence only, not copied into the prediction pool'],
       'approved_count':0,'records':out}


def main():
    p=argparse.ArgumentParser();p.add_argument('review');p.add_argument('fixtures');p.add_argument('teams');p.add_argument('openfootball');a=p.parse_args()
    for name in ('fixtures','teams','openfootball'):
        if sha(getattr(a,name)) != EXPECTED_HASHES[name]:
            raise ValueError(f'{name} snapshot hash mismatch')
    print(json.dumps(verify(a.review,a.fixtures,a.teams,a.openfootball),indent=2,ensure_ascii=False,allow_nan=False))

if __name__=='__main__':main()
