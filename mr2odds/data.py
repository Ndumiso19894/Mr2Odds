"""Data providers for matches and goal markets.

The built-in :class:`SampleDataProvider` lets you run the scanner immediately.
Swap in your own provider (e.g. backed by an odds API) by implementing
:class:`MatchProvider`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Iterable

from .models import Match, Market

FUTURE = datetime.utcnow() + timedelta(days=1)


class MatchProvider(ABC):
    """Abstract source of :class:`~mr2odds.models.Match` objects."""

    @abstractmethod
    def fetch(self) -> Iterable[Match]:
        """Return all matches to scan."""


class SampleDataProvider(MatchProvider):
    """Embedded sample data — useful for demos and offline runs."""

    def fetch(self) -> list[Match]:
        now = datetime.utcnow()
        base = now + timedelta(hours=3)
        matches = [
            Match(
                id="eng1",
                home_team="Liverpool",
                away_team="Arsenal",
                league="Premier League",
                kickoff=base,
                home_form=1.9,
                away_form=1.7,
                markets=(
                    Market(name="Over 2.5 Goals", odds=1.90),
                    Market(name="Under 2.5 Goals", odds=1.95),
                    Market(name="BTTS — Yes", odds=1.70),
                    Market(name="BTTS — No", odds=2.10),
                ),
            ),
            Match(
                id="ger1",
                home_team="Bayern Munich",
                away_team="Borussia Dortmund",
                league="Bundesliga",
                kickoff=base + timedelta(hours=1),
                home_form=2.4,
                away_form=1.9,
                markets=(
                    Market(name="Over 2.5 Goals", odds=1.62),
                    Market(name="Under 2.5 Goals", odds=2.30),
                    Market(name="BTTS — Yes", odds=1.55),
                    Market(name="BTTS — No", odds=2.45),
                ),
            ),
            Match(
                id="esp1",
                home_team="Barcelona",
                away_team="Atletico Madrid",
                league="La Liga",
                kickoff=base + timedelta(hours=2),
                home_form=2.1,
                away_form=1.6,
                markets=(
                    Market(name="Over 2.5 Goals", odds=2.05),
                    Market(name="Under 2.5 Goals", odds=1.78),
                    Market(name="BTTS — Yes", odds=1.90),
                    Market(name="BTTS — No", odds=1.90),
                ),
            ),
            Match(
                id="ita1",
                home_team="Inter Milan",
                away_team="Napoli",
                league="Serie A",
                kickoff=base + timedelta(hours=3),
                home_form=1.6,
                away_form=1.4,
                markets=(
                    Market(name="Over 2.5 Goals", odds=2.20),
                    Market(name="Under 2.5 Goals", odds=1.66),
                    Market(name="BTTS — Yes", odds=2.05),
                    Market(name="BTTS — No", odds=1.75),
                ),
            ),
            Match(
                id="eng2",
                home_team="Brighton",
                away_team="Brentford",
                league="Premier League",
                kickoff=base + timedelta(hours=4),
                home_form=1.8,
                away_form=1.7,
                markets=(
                    Market(name="Over 2.5 Goals", odds=2.00),
                    Market(name="Under 2.5 Goals", odds=1.82),
                    Market(name="BTTS — Yes", odds=1.85),
                    Market(name="BTTS — No", odds=1.95),
                ),
            ),
            Match(
                id="ned1",
                home_team="Ajax",
                away_team="PSV",
                league="Eredivisie",
                kickoff=base + timedelta(hours=5),
                home_form=2.3,
                away_form=2.1,
                markets=(
                    Market(name="Over 2.5 Goals", odds=1.70),
                    Market(name="Under 2.5 Goals", odds=2.15),
                    Market(name="BTTS — Yes", odds=1.50),
                    Market(name="BTTS — No", odds=2.60),
                ),
            ),
        ]
        return matches


__all__ = ["MatchProvider", "SampleDataProvider"]