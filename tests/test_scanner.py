"""Tests for the goal scanner."""

from datetime import datetime, timedelta

import pytest

from mr2odds.config import ScanRules
from mr2odds.data import SampleDataProvider
from mr2odds.models import Match, Market
from mr2odds.scanner import GoalScanner


def _match(mid, home, away, home_form, away_form, over_odds, btts_odds):
    now = datetime.utcnow()
    return Match(
        id=mid,
        home_team=home,
        away_team=away,
        league="Test League",
        kickoff=now + timedelta(days=1),
        home_form=home_form,
        away_form=away_form,
        markets=(
            Market(name="Over 2.5 Goals", odds=over_odds),
            Market(name="Under 2.5 Goals", odds=2.0),
            Market(name="BTTS — Yes", odds=btts_odds),
            Market(name="BTTS — No", odds=1.8),
        ),
    )


def test_scanner_flags_strong_over_play():
    matches = [
        _match("m1", "A", "B", 2.2, 2.0, 1.70, 1.50),  # strong
        _match("m2", "C", "D", 1.0, 1.0, 3.50, 2.50),  # weak form
    ]
    result = GoalScanner().scan(matches)
    assert result.scanned == 2
    assert len(result.opportunities) >= 1
    top = result.by_score[0]
    assert top.match.id == "m1"
    assert top.score > 0


def test_scanner_respects_implied_prob_floor():
    rules = ScanRules(
        over_under_min_implied_prob=0.90,  # very high bar
        btts_min_implied_prob=0.90,
        min_combined_form=0.0,
        top_n=10,
    )
    matches = [
        _match("m1", "A", "B", 3.0, 3.0, 1.10, 1.10),  # ~91% implied -> may pass
        _match("m2", "C", "D", 3.0, 3.0, 2.00, 2.00),   # 50% implied -> filtered
    ]
    result = GoalScanner(rules=rules).scan(matches)
    ids = {o.match.id for o in result.opportunities}
    assert "m2" not in ids


def test_sample_provider_returns_matches():
    matches = SampleDataProvider().fetch()
    assert len(matches) == 6
    assert all(isinstance(m, Match) for m in matches)


def test_opportunity_sorted_by_score():
    matches = [
        _match("m1", "A", "B", 1.0, 1.0, 4.00, 4.00),
        _match("m2", "C", "D", 3.0, 3.0, 1.40, 1.40),
    ]
    result = GoalScanner().scan(matches)
    scores = [o.score for o in result.by_score]
    assert scores == sorted(scores, reverse=True)