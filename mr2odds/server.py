"""Optional FastAPI web API for the goal scanner.

Run with:  python -m mr2odds serve
Requires:  pip install fastapi uvicorn
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from .cli import run
from .config import ScanRules
from .data import SampleDataProvider
from .models import Match
from .scanner import GoalScanner

app = FastAPI(title="Mr2Odds Goal Scanner", version="0.1.0")


@app.get("/")
def root():
    return {"name": "Mr2Odds Goal Scanner", "version": "0.1.0"}


@app.get("/scan")
def scan(
    top: Optional[int] = Query(None, ge=1, le=100),
    min_implied: Optional[float] = Query(None, ge=0, le=1),
    min_btts: Optional[float] = Query(None, ge=0, le=1),
    min_form: Optional[float] = Query(None, ge=0),
):
    rules = ScanRules(
        over_under_min_implied_prob=min_implied if min_implied is not None else ScanRules.over_under_min_implied_prob,
        btts_min_implied_prob=min_btts if min_btts is not None else ScanRules.btts_min_implied_prob,
        min_combined_form=min_form if min_form is not None else ScanRules.min_combined_form,
        top_n=top if top is not None else ScanRules.top_n,
    )
    result = GoalScanner(rules=rules).scan(SampleDataProvider().fetch())
    return JSONResponse(
        {
            "scanned": result.scanned,
            "returned": len(result.opportunities),
            "opportunities": [
                {
                    "match": {
                        "id": o.match.id,
                        "home_team": o.match.home_team,
                        "away_team": o.match.away_team,
                        "league": o.match.league,
                        "kickoff": o.match.kickoff.isoformat(),
                        "combined_form": o.match.combined_form,
                    },
                    "market": {
                        "name": o.market.name,
                        "odds": o.market.odds,
                        "implied_probability": o.market.implied_probability,
                    },
                    "reason": o.reason,
                    "score": o.score,
                    "edge": o.edge,
                }
                for o in result.by_score
            ],
        }
    )