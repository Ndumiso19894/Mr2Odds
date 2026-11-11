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
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import competition_policy
from scripts import facebook_history, facebook_post as fb

# Senior men's domestic leagues only; no cup, women's, youth or international league.
LEAGUES = {
    'eng.1':'England', 'eng.2':'England', 'eng.3':'England', 'eng.4':'England',
    'ger.1':'Germany', 'ger.2':'Germany', 'ita.1':'Italy', 'ita.2':'Italy',
    'esp.1':'Spain', 'esp.2':'Spain', 'fra.1':'France', 'fra.2':'France',
    'ned.1':'Netherlands', 'por.1':'Portugal', 'bel.1':'Belgium', 'aut.1':'Austria',
    'den.1':'Denmark', 'sco.1':'Scotland', 'gre.1':'Greece', 'tur.1':'Turkey',
    'nor.1':'Norway', 'swe.1':'Sweden',
    'irl.1':'Ireland', 'pol.1':'Poland',
}
STANDINGS = 'https://site.api.espn.com/apis/v2/sports/soccer/{}/standings'
SCHEDULE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{}/teams/{}/schedule'


def _json(url):
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=15, headers={'User-Agent':'Mr2OddsStatsWatch/1.0'})
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get('code') in (400, 404, 500):
                raise ValueError('Invalid sports feed')
            return data
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)



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
    if (not isinstance(season, int) or season not in (now.year, now.year - 1)
            or (season == now.year - 1 and now.month >= 8)):
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
                or played < 6 or played > 60 or min(losses, wins, draws) < 0 or wins + draws + losses != played):
            continue
        team = entry.get('team') or {}
        tid, name = str(team.get('id') or ''), str(team.get('displayName') or '').strip()
        if not re.fullmatch(r'\d+', tid) or not name or not competition_policy.allowed(country=country, league=league_name, home=name):
            continue
        found.append({'team_id':tid, 'team':name, 'league_code':league_code, 'league':league_name,
                      'country':country, 'rank':int(rank), 'played':int(played), 'wins':int(wins),
                      'draws':int(draws), 'losses':int(losses), 'record':f'{int(wins)}-{int(draws)}-{int(losses)}',
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
        # Reject a season that has stopped updating (e.g. an old final table).
        recent = [_utc(e['date']) for e in league_schedule.get('events') or []
                  if (e.get('league') or {}).get('slug') == candidate['league_code']
                  and (e.get('season') or {}).get('year') == candidate['season']
                  and (e.get('competitions') or [{}])[0].get('status',{}).get('type',{}).get('completed')]
        if not recent or not timedelta(0) <= now - max(recent) <= timedelta(days=21):
            return None
    except (ValueError, TypeError, KeyError, IndexError):
        return None
    # A zero-loss season record proves the run even without the full history.
    # Otherwise require every season result to match the W/D/L table and then
    # count backwards, so a partial results feed cannot conceal a recent loss.
    proof = []
    if candidate['losses'] == 0:
        streak = candidate['played']
    else:
        results = []
        for event in league_schedule.get('events') or []:
            try:
                if (event.get('league') or {}).get('slug') != candidate['league_code'] or (event.get('season') or {}).get('year') != candidate['season']:
                    continue
                comp = event['competitions'][0]
                status = comp['status']['type']
                if status.get('state') == 'in':
                    return None
                if status.get('state') != 'post' or not status.get('completed'):
                    continue
                teams = comp['competitors']
                if len(teams) != 2:
                    return None
                team = next(t for t in teams if str(t.get('id')) == candidate['team_id'])
                other = next(t for t in teams if str(t.get('id')) != candidate['team_id'])
                own, opp = team['score']['value'], other['score']['value']
                if not all(isinstance(x,(int,float)) and x >= 0 and x == int(x) for x in (own,opp)):
                    return None
                outcome = 'W' if own > opp else 'D' if own == opp else 'L'
                results.append((_utc(event['date']), str(event['id']), outcome))
            except (KeyError, TypeError, ValueError, StopIteration, IndexError):
                return None
        if (len(results) != candidate['played'] or len({x[1] for x in results}) != len(results)
            or sum(x[2] == 'W' for x in results) != candidate['wins']
            or sum(x[2] == 'D' for x in results) != candidate['draws']
            or sum(x[2] == 'L' for x in results) != candidate['losses']):
            return None
        proof = [{'date':dt.isoformat(), 'event_id':eid, 'outcome':outcome}
                 for dt, eid, outcome in sorted(results, reverse=True)]
        streak = 0
        for _, _, outcome in sorted(results, reverse=True):
            if outcome == 'L':
                break
            streak += 1
        if streak < 6:
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
            if len(comps) != 1:
                return None
            comp = comps[0]
            status = (comp.get('status') or {}).get('type') or {}
            if status.get('state') == 'in':
                return None
            if status.get('state') != 'pre' or status.get('name') not in ('STATUS_SCHEDULED',):
                continue
            teams = comp['competitors']
            if len(teams) != 2 or when <= now:
                return None
            home = next(t for t in teams if t.get('homeAway') == 'home')
            away = next(t for t in teams if t.get('homeAway') == 'away')
            home_id, away_id = str(home.get('id') or ''), str(away.get('id') or '')
            if not re.fullmatch(r'\d+', home_id) or not re.fullmatch(r'\d+', away_id) or candidate['team_id'] not in (home_id, away_id):
                continue
            hname, aname = home['team']['displayName'], away['team']['displayName']
            # A numeric ID alone is not proof that ESPN has an actual club crest.
            logo_valid = True
            for competitor, tid in ((home, home_id), (away, away_id)):
                logos = (competitor.get('team') or {}).get('logos') or []
                expected = f'https://a.espncdn.com/i/teamlogos/soccer/500/{tid}.png'
                if not any(isinstance(logo,dict) and logo.get('href') == expected for logo in logos):
                    logo_valid = False
            name = str((event.get('season') or {}).get('displayName') or '').strip()
            if not hname or not aname or not name:
                continue
            upcoming.append((when, name, hname, aname, home_id, away_id, str(event.get('id') or ''), bool(event.get('timeValid')), logo_valid))
        except (KeyError, TypeError, ValueError, StopIteration):
            continue
    if not upcoming:
        return None
    when, competition, home, away, home_id, away_id, event_id, timed, logo_valid = min(upcoming)
    # Do not silently promote a later allowed fixture when the actual next match is paused.
    if not timed or not logo_valid or when <= now + timedelta(minutes=15) or not competition_policy.allowed(country=candidate['country'], league=competition, home=home, away=away):
        return None
    return {**candidate, 'streak':streak, 'results_proof':proof, 'kickoff_utc':when.isoformat(), 'competition':competition,
            'home':home, 'away':away, 'home_id':home_id, 'away_id':away_id,
            'event_id':event_id, 'schedule_url':SCHEDULE.format('all', candidate['team_id']) + '?fixture=true'}


def collect(now=None, limit=10, get=_json, exclude_teams=(), exclude_team_ids=()):
    """Collect verified rows, avoiding repeated clubs and fixtures within and across same-day posts."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if limit <= 0:
        return []
    excluded_names = {facebook_history.team_key(x) for x in exclude_teams if facebook_history.team_key(x)}
    excluded_ids = {str(x) for x in exclude_team_ids if str(x).isdigit()}
    candidates = []
    def table(code):
        try:
            return table_candidates(code, get(STANDINGS.format(code)), now)
        except (requests.RequestException, ValueError, TypeError, KeyError):
            return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for entries in pool.map(table, LEAGUES):
            candidates.extend(entries)
    def fixture(candidate):
        try:
            local = get(SCHEDULE.format(candidate['league_code'], candidate['team_id']))
            all_matches = get(SCHEDULE.format('all', candidate['team_id']) + '?fixture=true')
            return next_fixture(candidate, local, all_matches, now)
        except (requests.RequestException, ValueError, TypeError, KeyError):
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        values = [x for x in pool.map(fixture, candidates) if x]
    values.sort(key=lambda x: (-x['streak'], x['league_code'], x['team']))
    out, used_names, used_ids, used_fixtures = [], set(), set(), set()
    for row in values:
        home_key, away_key = (facebook_history.team_key(row.get(side)) for side in ('home', 'away'))
        if not home_key or not away_key or home_key == away_key:
            continue
        names = {home_key, away_key}
        ids = {str(row.get(k)) for k in ('home_id', 'away_id') if str(row.get(k) or '').isdigit()}
        fixture_key = tuple(sorted(names))
        if (names & excluded_names or ids & excluded_ids or names & used_names
                or ids & used_ids or fixture_key in used_fixtures):
            continue
        out.append(row)
        used_names.update(names)
        used_ids.update(ids)
        used_fixtures.add(fixture_key)
        if len(out) >= limit:
            break
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    rows = collect(now)
    print(f'Found {len(rows)} verified unbeaten league leaders with upcoming fixtures.')
    for row in rows:
        print(f"::notice::{row['team']} | {row['league']} #{row['rank']} | {row['streak']} league matches unbeaten | {row['home']} v {row['away']} | {row['kickoff_utc']}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'as_of':now.isoformat(), 'rows':rows}, ensure_ascii=False), encoding='utf-8')

if __name__ == '__main__':
    main()
