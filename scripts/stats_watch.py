#!/usr/bin/env python3
"""Verified, factual football statistics for a no-picks publication slot.

ESPN league tables prove season-to-date undefeated records; ESPN schedules supply
actual next opponents, dates and club identifiers. Never infer a result, table
position, crest, or fixture when a feed is missing or inconsistent.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import competition_policy
from scripts import facebook_post as fb

# Senior men's domestic leagues only; no cup, women's, youth or international league.
LEAGUES = {
    'eng.1':'England', 'eng.2':'England', 'eng.3':'England', 'eng.4':'England',
    'ger.1':'Germany', 'ger.2':'Germany', 'ita.1':'Italy', 'ita.2':'Italy',
    'esp.1':'Spain', 'esp.2':'Spain', 'fra.1':'France', 'fra.2':'France',
    'ned.1':'Netherlands', 'por.1':'Portugal', 'bel.1':'Belgium', 'aut.1':'Austria',
    'den.1':'Denmark', 'sco.1':'Scotland', 'gre.1':'Greece', 'tur.1':'Turkey',
    'nor.1':'Norway', 'swe.1':'Sweden', 'bra.1':'Brazil', 'mex.1':'Mexico',
    'usa.1':'United States', 'arg.1':'Argentina', 'jpn.1':'Japan', 'kor.1':'South Korea',
    'aus.1':'Australia', 'rsa.1':'South Africa', 'irl.1':'Ireland', 'pol.1':'Poland',
}
STANDINGS = 'https://site.api.espn.com/apis/v2/sports/soccer/{}/standings'
SCHEDULE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{}/teams/{}/schedule'


def _json(url):
    response = requests.get(url, timeout=12, headers={'User-Agent':'Mr2OddsStatsWatch/1.0'})
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get('code') in (400, 404, 500):
        raise ValueError('Invalid sports feed')
    return data


def _utc(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp missing timezone')
    return result.astimezone(timezone.utc)


def table_candidates(league_code, data, now):
    country = LEAGUES[league_code]
    if not data.get('children'):
        return []
    # Grouped tables can represent separate divisions or playoff phases; do not
    # present group position as league position without an unambiguous table.
    groups = [g.get('standings') for g in data['children'] if isinstance(g, dict) and g.get('standings', {}).get('entries')]
    if len(groups) != 1:
        return []
    group = groups[0]
    season = group.get('season')
    if not isinstance(season, int) or season not in (now.year, now.year - 1):
        return []
    league_name = str(data.get('name') or '').strip()
    if not league_name or not competition_policy.allowed(country=country, league=league_name):
        return []
    found = []
    for entry in group.get('entries', []):
        stats = {s.get('name'): s.get('value') for s in entry.get('stats', []) if isinstance(s, dict)}
        rank, played, losses = stats.get('rank'), stats.get('gamesPlayed'), stats.get('losses')
        wins, draws = stats.get('wins'), stats.get('ties')
        if (rank not in (1, 2) or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v == int(v) for v in (played, losses, wins, draws))
                or played < 6 or played > 60 or losses != 0 or wins + draws != played):
            continue
        team = entry.get('team') or {}
        tid, name = str(team.get('id') or ''), str(team.get('displayName') or '').strip()
        if not re.fullmatch(r'\d+', tid) or not name or not competition_policy.allowed(country=country, league=league_name, home=name):
            continue
        found.append({'team_id':tid, 'team':name, 'league_code':league_code, 'league':league_name,
                      'country':country, 'rank':int(rank), 'played':int(played), 'wins':int(wins),
                      'draws':int(draws), 'record':f'{int(wins)}-{int(draws)}-0',
                      'table_url':STANDINGS.format(league_code), 'season':season})
    return found


def next_fixture(candidate, league_schedule, all_schedule, now):
    now = now.astimezone(timezone.utc)
    # Cross-check live standings against the team's league-specific schedule.
    if str((league_schedule.get('team') or {}).get('id')) != candidate['team_id']:
        return None
    if (league_schedule.get('team') or {}).get('recordSummary') != candidate['record']:
        return None
    try:
        stamp = _utc(all_schedule['timestamp'])
        if not timedelta(minutes=-5) <= now - stamp <= timedelta(hours=6):
            return None
    except (KeyError, ValueError, TypeError):
        return None
    upcoming = []
    for event in all_schedule.get('events') or []:
        try:
            when = _utc(event['date'])
            comps = event['competitions']
            if len(comps) != 1 or not event.get('timeValid'):
                continue
            comp = comps[0]
            status = (comp.get('status') or {}).get('type') or {}
            if status.get('state') != 'pre' or status.get('name') not in ('STATUS_SCHEDULED',):
                continue
            teams = comp['competitors']
            if len(teams) != 2 or when <= now + timedelta(minutes=15):
                continue
            home = next(t for t in teams if t.get('homeAway') == 'home')
            away = next(t for t in teams if t.get('homeAway') == 'away')
            home_id, away_id = str(home.get('id') or ''), str(away.get('id') or '')
            if not re.fullmatch(r'\d+', home_id) or not re.fullmatch(r'\d+', away_id) or candidate['team_id'] not in (home_id, away_id):
                continue
            hname, aname = home['team']['displayName'], away['team']['displayName']
            name = str((event.get('season') or {}).get('displayName') or '').strip()
            if not hname or not aname or not name:
                continue
            upcoming.append((when, name, hname, aname, home_id, away_id, str(event.get('id') or '')))
        except (KeyError, TypeError, ValueError, StopIteration):
            continue
    if not upcoming:
        return None
    when, competition, home, away, home_id, away_id, event_id = min(upcoming)
    # Do not silently promote a later allowed fixture when the actual next match is paused.
    if not competition_policy.allowed(country=candidate['country'], league=competition, home=home, away=away):
        return None
    return {**candidate, 'kickoff_utc':when.isoformat(), 'competition':competition,
            'home':home, 'away':away, 'home_id':home_id, 'away_id':away_id,
            'event_id':event_id, 'schedule_url':SCHEDULE.format('all', candidate['team_id']) + '?fixture=true'}


def collect(now=None, limit=10, get=_json):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    candidates = []
    def table(code):
        try:
            return table_candidates(code, get(STANDINGS.format(code)), now)
        except (requests.RequestException, ValueError, TypeError, KeyError):
            return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for entries in pool.map(table, LEAGUES):
            candidates.extend(entries)
    def fixture(candidate):
        try:
            local = get(SCHEDULE.format(candidate['league_code'], candidate['team_id']))
            all_matches = get(SCHEDULE.format('all', candidate['team_id']) + '?fixture=true')
            return next_fixture(candidate, local, all_matches, now)
        except (requests.RequestException, ValueError, TypeError, KeyError):
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        values = [x for x in pool.map(fixture, candidates) if x]
    values.sort(key=lambda x: (-x['played'], x['league_code'], x['team']))
    return values[:limit]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    rows = collect(now)
    print(f'Found {len(rows)} verified unbeaten league leaders with upcoming fixtures.')
    for row in rows:
        print(f"::notice::{row['team']} | {row['league']} #{row['rank']} | {row['played']} league matches unbeaten | {row['home']} v {row['away']} | {row['kickoff_utc']}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'as_of':now.isoformat(), 'rows':rows}, ensure_ascii=False), encoding='utf-8')

if __name__ == '__main__':
    main()
