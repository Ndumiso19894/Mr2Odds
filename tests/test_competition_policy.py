"""Pause policy across source data, cached carry-over, day cards and the browser."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

import appdata
import competition_policy as policy
import leagues
import safe
import scanner
import coverage
from zoneinfo import ZoneInfo
import verify
from test_verify_archive_fixtures import _build as build_publication

CASES = json.loads((Path(__file__).parent / 'competition_cases.json').read_text())


@pytest.mark.parametrize('case', CASES)
def test_policy_examples(case):
    assert policy.allows_record(case['record']) is case['allowed']


def test_frozen_fixture_does_not_resurrect_paused_matches():
    now = datetime(2026, 11, 4, 8)
    def fixture(fid, league):
        return {'id': fid, 'kickoff': '2026-11-04 07:30', 'country': 'England',
                'league': league, 'home': 'A', 'away': 'B'}
    prev = {'fixtures': [fixture('cup', 'FA Cup'), fixture('league', 'Premier League')],
            'tracked': ['cup', 'league'], 'safe': {'bets': [
                {'id': 'cup-bet', 'fixture': 'cup', 'sel': 'O15'}, {'id': 'league-bet', 'fixture': 'league', 'sel': 'O15'}]}}
    index, bets, tracked = [], [], set()
    assert appdata.carry_over(prev, index, bets, tracked, now) == 1
    assert [f['id'] for f in index] == ['league']
    assert [b['id'] for b in bets] == ['league-bet']
    assert tracked == {'league'}


def test_day_card_slots_ignore_paused_ledger_but_preserve_it():
    now = datetime(2026, 11, 4, 8)
    rows = [{**{c: '' for c in safe.SAFE_BET_COLS}, 'match_date': '2026-11-04', 'country': 'England',
             'league': 'FA Cup', 'home': f'Cup {i}', 'away': f'Club {i}', 'sel': 'O15',
             'status': 'pending', 'botd': 'o15', 'kind': 'botd'} for i in range(7)]
    candidate = safe.Bet(('2026-11-04', 'England', 'League Club', 'Rivals'), 'E0', 'Premier League',
                         'League Club', 'Rivals', '2026-11-04 14:00', 'O15', .8, .8, .8, 1.4)
    result = safe.pick_bets_of_the_day(pd.DataFrame(rows), now, candidates=[candidate])
    assert len(result) == 8
    assert (result.loc[result['home'] == 'League Club', 'botd'] == 'o15').all()
    assert len(result[result['league'] == 'FA Cup']) == 7


def test_league_window_filters_team_and_stage_markers():
    now = datetime(2026, 11, 4, 8)
    def ev(league, scd, home='A'):
        return {'country': 'England', 'league': league, 'ccd': 'england', 'scd': scd, 'home': home,
                'away': 'B', 'status': 'NS', 'kickoff': now + timedelta(hours=3)}
    result = leagues._window_events([ev('Premier League', 'premier-league'), ev('FA Cup', 'fa-cup'),
                                    ev('Premier League', 'premier-league', 'A U21')], now)
    assert list(result) == ['england/premier-league']
    assert len(result['england/premier-league']) == 1


def test_publication_check_rejects_paused_fixture(tmp_path):
    staging, live = build_publication(tmp_path)
    p = staging / 'latest.json'
    data = json.loads(p.read_text())
    data['fixtures'][0]['league'] = 'FA Cup'
    p.write_text(json.dumps(data))
    errors, _ = verify.check_publication(staging, live, tmp_path / 'missing', datetime(2026, 9, 30, 12), 1)
    assert any('paused competition' in e for e in errors)


def test_football_data_fixture_ingestion_filters_exclusions(monkeypatch):
    main = pd.DataFrame([{'Div': 'E0', 'Date': '04/11/2026', 'HomeTeam': 'Arsenal', 'AwayTeam': 'Rivals', 'Time': '15:00'}])
    extra = pd.DataFrame([{'Country': 'Brazil', 'League': name, 'Date': '04/11/2026',
                           'Home': 'A', 'Away': 'B', 'Time': '15:00'}
                          for name in ['Serie A', 'Copa do Brasil', 'Brasileiro Sub-20', 'Liga Feminina']])
    monkeypatch.setattr(scanner, 'fetch', lambda url: url)
    monkeypatch.setattr(scanner, 'read_csv', lambda value, **kwargs: main.copy() if value == scanner.FIXTURES_URL else extra.copy())
    monkeypatch.setitem(scanner.CONFIG, 'LEAGUES', [])
    fixtures = scanner.load_fixtures(ZoneInfo('Africa/Johannesburg'))
    assert set(fixtures['league']) == {'Premier League', 'Serie A'}


def test_coverage_omits_paused_stages_without_deleting_archive(tmp_path):
    stages = tmp_path / 'stages'
    stages.mkdir()
    for key, league in [('england/premier-league', 'Premier League'), ('england/fa-cup', 'FA Cup')]:
        data = {'key': key, 'country': 'England', 'league': league,
                'events': {'1': ['202611011500', 'a', 'A', 'b', 'B', 1, 0, None, None]}}
        (stages / (key.replace('/', '__') + '.json')).write_text(json.dumps(data))
    out = coverage.build(stages, tmp_path / 'out', datetime(2026, 11, 4))
    assert [x['competition'] for x in out['competitions'] if x['provider'] == 'livescore'] == ['Premier League']
    assert (stages / 'england__fa-cup.json').exists()
