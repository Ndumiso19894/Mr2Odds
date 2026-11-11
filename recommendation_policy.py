"""Current recommendation eligibility shared by scanner/export paths.

This only controls new recommendations. It does not erase historical ledger entries,
change match probabilities, or stop users from viewing modelled market statistics.
"""
from __future__ import annotations

import re

PRICE_FLOOR = 1.16

# 1X2 is deliberately more selective than a generic probability bar. These
# constants are shared by the scanner and app payload so a straight win is not
# promoted from model probability alone.
X12_MIN_PROBABILITY = 0.60
X12_MIN_ODDS = 1.20
X12_MAX_ODDS = 3.50
X12_MIN_MODEL_RETURN = 0.95
X12_MAX_MARKET_GAP = 0.08
X12_MIN_TEAM_MATCHES = 12
X12_MIN_EFFECTIVE_MATCHES = 8.0
X12_MIN_VENUE_MATCHES = 5
X12_MAX_DAYS_SINCE_LAST = 30
X12_MIN_COMPETITION_SHARE = 0.70
X12_FORM_MATCHES = 5
X12_FORM_MIN_WINS = 3
X12_FORM_MAX_LOSSES = 1
X12_OPPONENT_MAX_WINS = 1
X12_DRAW_MIN_DRAWS = 2

X12_RULES = {
    "min_probability": X12_MIN_PROBABILITY,
    "min_odds": X12_MIN_ODDS,
    "max_odds": X12_MAX_ODDS,
    "min_model_return": X12_MIN_MODEL_RETURN,
    "max_market_gap": X12_MAX_MARKET_GAP,
    "min_team_matches": X12_MIN_TEAM_MATCHES,
    "min_effective_matches": X12_MIN_EFFECTIVE_MATCHES,
    "min_venue_matches": X12_MIN_VENUE_MATCHES,
    "max_days_since_last": X12_MAX_DAYS_SINCE_LAST,
    "min_competition_share": X12_MIN_COMPETITION_SHARE,
    "form_matches": X12_FORM_MATCHES,
    "form_min_wins": X12_FORM_MIN_WINS,
    "form_max_losses": X12_FORM_MAX_LOSSES,
    "opponent_max_wins": X12_OPPONENT_MAX_WINS,
    "draw_min_draws": X12_DRAW_MIN_DRAWS,
}


def allowed(sel: str) -> bool:
    """Match the app's current offered markets: 1X2, BTTS yes, goals overs and corner overs; booking counts are not yet bookmaker-equivalent."""
    sel = str(sel or '')
    return sel in ('H', 'D', 'A', 'BTTS') or bool(re.fullmatch(r'O(?:15|25|35|45|55)|C(?:[HA])?O\d+', sel))


def outlier(model: float | None, market: float | None, odds: float | None) -> bool:
    if model is None or odds is None or odds <= 1:
        return False
    if market is not None and market > 0:
        return model - market >= .15
    return model - 1 / odds >= .25
