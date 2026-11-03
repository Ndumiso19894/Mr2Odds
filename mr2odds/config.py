"""Default scanning rules for the goal scanner.

Tune these thresholds to match your risk appetite and the markets you track.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ScanRules:
    # Minimum implied probability (from odds) to flag an Over/Under play
    over_under_min_implied_prob: float = 0.52
    # Minimum implied probability to flag a BTTS play
    btts_min_implied_prob: float = 0.55
    # Minimum combined recent form (home + away goals per game)
    min_combined_form: float = 2.4
    # Odds window to consider (avoid huge longs and tiny favs)
    min_odds: float = 1.40
    max_odds: float = 5.00
    # How many top opportunities to return
    top_n: int = 10


# Active ruleset. Import and override in your own config if you like.
RULES = ScanRules()