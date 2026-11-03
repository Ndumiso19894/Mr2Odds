"""Core domain models for the goal scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Market:
    """A single betting market on a match (e.g. 'Over 2.5 Goals')."""

    name: str
    odds: float
    implied_probability: float = field(init=False)

    def __post_init__(self) -> None:
        if self.odds <= 0:
            raise ValueError(f"odds must be positive, got {self.odds}")
        object.__setattr__(
            self, "implied_probability", 1.0 / self.odds
        )


@dataclass(frozen=True)
class Match:
    """A football match with goal-related markets and recent form."""

    id: str
    home_team: str
    away_team: str
    league: str
    kickoff: datetime
    markets: tuple[Market, ...] = ()
    home_form: Optional[float] = None  # avg goals scored/conceded per game
    away_team_form: Optional[float] = None  # kept for backward compat
    away_form: Optional[float] = None

    @property
    def combined_form(self) -> Optional[float]:
        if self.home_form is None or self.away_form is None:
            return None
        return self.home_form + self.away_form

    @property
    def market_by_name(self) -> dict[str, Market]:
        return {m.name: m for m in self.markets}


@dataclass(frozen=True)
class Opportunity:
    """A flagged goal-market opportunity with reasoning and a score."""

    match: Match
    market: Market
    reason: str
    score: float  # 0-10, higher = stronger opportunity
    edge: float  # model probability minus implied probability
