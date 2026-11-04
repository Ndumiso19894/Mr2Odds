"""Current recommendation eligibility shared by scanner/export paths.

This only controls new recommendations. It does not erase historical ledger entries,
change match probabilities, or stop users from viewing modelled market statistics.
"""
from __future__ import annotations

import re

PRICE_FLOOR = 1.16


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
