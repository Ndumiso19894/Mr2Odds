"""Evidence gate regressions for 1X2 recommendations and the app payload."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import appdata
import safe
import scanner

NOW = datetime(2026, 11, 10, 8)


def form(results):
    return [{'gf': gf, 'ga': ga} for gf, ga in results]


WIN_FORM = form([(2, 0), (1, 0), (3, 1), (2, 0), (1, 0)])
WEAK_FORM = form([(0, 1), (1, 1), (0, 2), (0, 0), (1, 2)])
DRAW_FORM = form([(0, 0), (1, 1), (2, 1), (1, 1), (0, 1)])
LOW_DRAW_FORM = form([(0, 1), (1, 0), (0, 2), (1, 1), (0, 1)])


def research_row(selected='H', *, p_override=None, odds_override=None):
    probs = {'H': .66, 'D': .18, 'A': .16} if selected == 'H' else {'H': .18, 'D': .66, 'A': .16}
    if p_override is not None:
        probs.update(p_override)
    odds = tuple((odds_override or {}).get(code, 1 / probs[code]) for code in ('H', 'D', 'A'))
    home_form, away_form = (WIN_FORM, WEAK_FORM) if selected == 'H' else (DRAW_FORM, DRAW_FORM)
    home = SimpleNamespace(n=20, n_eff=16.0, venue_n=7, last5=home_form, venue_last5=home_form)
    away = SimpleNamespace(n=18, n_eff=14.5, venue_n=6, last5=away_form, venue_last5=away_form)
    extra = SimpleNamespace(x12=probs, tg={}, corner_p={}, card_p={})
    return SimpleNamespace(
        fx={'home': 'Home FC', 'away': 'Away United', 'date': NOW + timedelta(days=1),
            'kickoff': NOW + timedelta(days=1), 'country': 'England', 'league': 'Premier League', 'div': 'E0'},
        home=home, away=away, data_ok=True, extra=extra,
        p_final={'O15': None, 'O25': None, 'BTTS': None},
        sb={'1X2': odds}, sb_full=None,
    )


def team_evidence():
    composition = {'own_competition_share': .82, 'days_since_last': 8, 'friendlies_included': 0}
    return {'composition': dict(composition)}, {'composition': dict(composition)}


def report_for(row, quality='High'):
    home, away = team_evidence()
    return scanner.build_x12_research(row, home, away, {'overall': quality})


def test_win_recommendation_requires_and_reports_strong_form():
    row = research_row('H')
    report = report_for(row)
    assert report['outcomes']['H']['eligible'] is True
    assert report['outcomes']['H']['market_gap_pp'] == 0
    assert report['outcomes']['H']['form']['selected_team']['overall'] == {'n': 5, 'w': 5, 'd': 0, 'l': 0}
    assert report['outcomes']['A']['eligible'] is False
    assert any('selected team lacks recent backing' in reason for reason in report['outcomes']['A']['reasons'])
    assert scanner.x12_research_eligible(row, 'H') is False  # not attached until the audit stores it
    row.x12_research = report
    assert scanner.x12_research_eligible(row, 'H') is True
    assert scanner.strong_signal(row, 'H') is True
    assert scanner.strong_signal(row, 'D') is False


def test_draw_recommendation_needs_recent_draws_from_both_teams():
    row = research_row('D')
    report = report_for(row)
    assert report['outcomes']['D']['eligible'] is True
    row.home.last5 = LOW_DRAW_FORM
    row.home.venue_last5 = LOW_DRAW_FORM
    report = report_for(row)
    assert report['outcomes']['D']['eligible'] is False
    assert any('Home FC: fewer than 2 draws in the last 5 recent matches' in reason
               for reason in report['outcomes']['D']['reasons'])
    assert any('Home FC: fewer than 2 draws in the last 5 venue-specific recent matches' in reason
               for reason in report['outcomes']['D']['reasons'])


def test_missing_or_weak_evidence_and_market_disagreement_fail_closed():
    row = research_row('H')
    home, away = team_evidence()
    home['composition']['days_since_last'] = None
    assert not scanner.build_x12_research(row, home, away, {'overall': 'High'})['outcomes']['H']['eligible']
    home, away = team_evidence()
    home['composition'].pop('friendlies_included')
    report = scanner.build_x12_research(row, home, away, {'overall': 'High'})
    assert report['teams']['home']['friendlies_in_sample'] is None
    assert not report['outcomes']['H']['eligible']
    assert any('friendly count is unavailable' in reason for reason in report['outcomes']['H']['reasons'])
    home, away = team_evidence()
    home['composition']['friendlies_included'] = True
    report = scanner.build_x12_research(row, home, away, {'overall': 'High'})
    assert report['teams']['home']['friendlies_in_sample'] is None
    assert not report['outcomes']['H']['eligible']
    home, away = team_evidence()
    assert not scanner.build_x12_research(row, home, away, {'overall': 'Medium'})['outcomes']['H']['eligible']
    row = research_row('H', p_override={'H': .75, 'D': .15, 'A': .10},
                       odds_override={'H': 1 / .66, 'D': 1 / .18, 'A': 1 / .16})
    report = report_for(row)
    assert report['outcomes']['H']['eligible'] is False
    assert any('differ by more than 8 percentage points' in reason for reason in report['outcomes']['H']['reasons'])
    row = research_row('H', odds_override={'H': 1.40})
    report = report_for(row)
    assert any('probability × price is below 0.95' in reason for reason in report['outcomes']['H']['reasons'])
    row.sb = {}
    report = report_for(row)
    assert any('SportyBet price is missing' in reason for reason in report['outcomes']['H']['reasons'])
    assert any('complete de-margined 1X2 market is unavailable' in reason
               for reason in report['outcomes']['H']['reasons'])


def test_app_x12_shortlist_only_contains_gate_passed_rows_and_explains_them():
    row = research_row('H')
    report = report_for(row)
    fx = {'id': 'one-match', 'date': NOW.strftime('%Y-%m-%d'),
          'kickoff': (NOW + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M'), 'home': 'Home FC', 'away': 'Away United',
          'country': 'England', 'league': 'Premier League', 'data_ok': True, 'q': 'High', 'x12_confidence': 'High',
          'x12': [.66, .18, .16], 'x12_research': report,
          'sels': [['H', .66, .66, .66, 1 / .66, 0, None, None],
                   ['D', .18, .18, .18, 1 / .18, 0, None, None],
                   ['A', .16, .16, .16, 1 / .16, 0, None, None]]}
    shortlist = appdata.shortlist_payload([fx], NOW)
    assert [(x['sel'], x['confidence']) for x in shortlist['x12']] == [('H', 'High')]
    assert shortlist['x12'][0]['research']['outcomes']['H']['eligible'] is True
    assert shortlist['rules']['x12']['max_market_gap'] == .08
    assert fx['x12'] == [.66, .18, .16]  # contextual probabilities are preserved


def test_scanner_safe_result_recommendations_fail_closed_without_gate_callback():
    row = research_row('H')
    row.fx['kickoff'] = NOW + timedelta(hours=2)
    row.fx['date'] = NOW
    row.extra.x12['H'] = .72  # clear the Bets-of-the-Day 70% bar as well as the research gate
    row.x12_research = report_for(row)
    assert not safe.safest([row], NOW, NOW + timedelta(hours=4))['bets']
    result = safe.safest([row], NOW, NOW + timedelta(hours=4), signal=scanner.x12_research_eligible)
    assert [bet.sel for bet in result['bets']] == ['H']
