"""Goal-scanning engine.

Takes matches with goal markets, applies configurable rules, and returns a
ranked list of :class:`~mr2odds.models.Opportunity` objects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Sequence

from .config import ScanRules
from .models import Match, Market, Opportunity

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanResult:
    opportunities: tuple[Opportunity, ...]
    scanned: int
    rules: ScanRules

    @property
    def by_score(self) -> tuple[Opportunity, ...]:
        return tuple(sorted(self.opportunities, key=lambda o: o.score, reverse=True))


class GoalScanner:
    """Scans matches for goal-market betting opportunities."""

    def __init__(self, rules: ScanRules | None = None) -> None:
        self.rules = rules or ScanRules()

    # ------------------------------------------------------------------ public

    def scan(self, matches: Iterable[Match]) -> ScanResult:
        matches = list(matches)
        opportunities: list[Opportunity] = []

        for match in matches:
            opportunities.extend(self._scan_match(match))

        opportunities.sort(key=lambda o: o.score, reverse=True)
        top = opportunities[: self.rules.top_n]

        log.info(
            "Scanned %d matches, flagged %d opportunities (top %d)",
            len(matches),
            len(opportunities),
            len(top),
        )
        return ScanResult(
            opportunities=tuple(top),
            scanned=len(matches),
            rules=self.rules,
        )

    # ---------------------------------------------------------------- internals

    def _scan_match(self, match: Match) -> list[Opportunity]:
        found: list[Opportunity] = []

        # --- form prefilter -------------------------------------------------
        combined = match.combined_form
        form_ok = combined is None or combined >= self.rules.min_combined_form
        if not form_ok:
            log.debug(
                "Skipping %s v %s: combined form %.2f below %.2f",
                match.home_team,
                match.away_team,
                combined or 0.0,
                self.rules.min_combined_form,
            )
            return found

        for market in match.markets:
            if not (self.rules.min_odds <= market.odds <= self.rules.max_odds):
                continue

            name_lower = market.name.lower()
            if "over" in name_lower or "under" in name_lower:
                opp = self._scan_over_under(match, market)
            elif "btts" in name_lower or "both teams" in name_lower:
                opp = self._scan_btts(match, market)
            else:
                continue

            if opp is not None:
                found.append(opp)

        return found

    def _scan_over_under(self, match: Match, market: Market) -> Opportunity | None:
        implied = market.implied_probability
        if implied < self.rules.over_under_min_implied_prob:
            return None

        # Simple model: recent combined form nudges the fair probability.
        model_prob = implied
        if match.combined_form is not None:
            # Each 0.5 of combined form above 2.0 adds ~4% to the fair prob.
            form_nudge = min(0.12, max(0.0, (match.combined_form - 2.0) * 0.08))
            model_prob = min(0.95, implied + form_nudge)

        edge = model_prob - implied
        score = self._score(implied, edge, match.combined_form)
        reason = (
            f"{market.name} at {market.odds:.2f} (implied {implied:.1%}); "
            f"combined recent form {match.combined_form:.1f} GPG"
        )
        return Opportunity(match=match, market=market, reason=reason, score=score, edge=edge)

    def _scan_btts(self, match: Match, market: Market) -> Opportunity | None:
        implied = market.implied_probability
        if implied < self.rules.btts_min_implied_prob:
            return None

        model_prob = implied
        if match.combined_form is not None:
            form_nudge = min(0.10, max(0.0, (match.combined_form - 2.2) * 0.06))
            model_prob = min(0.95, implied + form_nudge)

        edge = model_prob - implied
        score = self._score(implied, edge, match.combined_form)
        reason = (
            f"{market.name} at {market.odds:.2f} (implied {implied:.1%}); "
            f"both sides averaging {match.combined_form:.1f} goals/game combined"
        )
        return Opportunity(match=match, market=market, reason=reason, score=score, edge=edge)

    @staticmethod
    def _score(implied: float, edge: float, combined_form: float | None) -> float:
        """0-10 opportunity score."""
        base = min(10.0, implied * 10)  # likelier outcomes score higher
        edge_bonus = min(4.0, edge * 40)  # reward positive edge
        form_bonus = min(2.0, max(0.0, (combined_form or 2.0) - 2.0)) if combined_form else 0.0
        return round(min(10.0, base + edge_bonus + form_bonus), 1)


__all__ = ["GoalScanner", "ScanResult"]