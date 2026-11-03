"""Command-line interface for the goal scanner."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .config import ScanRules
from .data import SampleDataProvider
from .models import Match
from .scanner import GoalScanner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mr2odds",
        description="Mr2Odds goal scanner — surface goal-market opportunities.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="Scan matches and print opportunities")
    scan_p.add_argument(
        "--top", type=int, default=None, help="Max opportunities to show"
    )
    scan_p.add_argument(
        "--min-implied",
        type=float,
        default=None,
        help="Min implied probability for Over/Under plays",
    )
    scan_p.add_argument(
        "--min-btts",
        type=float,
        default=None,
        help="Min implied probability for BTTS plays",
    )
    scan_p.add_argument(
        "--min-form", type=float, default=None, help="Min combined goals per game"
    )
    scan_p.add_argument(
        "--no-table", action="store_true", help="Print one line per opportunity"
    )

    sub.add_parser("serve", help="Run the web API (requires fastapi + uvicorn)")

    return parser


def _rules_from_args(args: argparse.Namespace) -> ScanRules:
    return ScanRules(
        over_under_min_implied_prob=args.min_implied
        if args.min_implied is not None
        else ScanRules.over_under_min_implied_prob,
        btts_min_implied_prob=args.min_btts
        if args.min_btts is not None
        else ScanRules.btts_min_implied_prob,
        min_combined_form=args.min_form
        if args.min_form is not None
        else ScanRules.min_combined_form,
        top_n=args.top if args.top is not None else ScanRules.top_n,
    )


def format_table(result) -> str:
    if not result.opportunities:
        return "No opportunities found."
    lines = [
        f"Scanned {result.scanned} matches — {len(result.opportunities)} opportunities",
        "",
    ]
    header = (
        f"#{'':<3} {'Match':<26} {'Market':<20} {'Odds':>6} {'Implied':>9} "
        f"{'Edge':>7} {'Score':>6}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for i, opp in enumerate(result.by_score, 1):
        match = opp.match
        lines.append(
            f"{i:<3} {match.home_team} v {match.away_team:<20} "
            f"{opp.market.name:<20} {opp.market.odds:>6.2f} "
            f"{opp.market.implied_probability:>8.1%} {opp.edge:>6.1%} {opp.score:>5.1f}"
        )
    lines.append("")
    for i, opp in enumerate(result.by_score, 1):
        lines.append(f"  {i}. {opp.reason}")
    return "\n".join(lines)


def format_list(result) -> str:
    lines = [f"{len(result.opportunities)} opportunities from {result.scanned} matches:"]
    for i, opp in enumerate(result.by_score, 1):
        lines.append(f"  {i}. [{opp.market.name}] {opp.match.home_team} v {opp.match.away_team} — {opp.reason}")
    return "\n".join(lines)


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        try:
            from .server import app  # noqa: F401
        except ImportError as exc:
            print(
                "The 'serve' command requires fastapi and uvicorn. "
                "Install them with: pip install -r requirements.txt",
                file=sys.stderr,
            )
            return 2
        import uvicorn

        uvicorn.run("mr2odds.server:app", host="0.0.0.0", port=8000, reload=True)
        return 0

    rules = _rules_from_args(args)
    scanner = GoalScanner(rules=rules)
    matches = SampleDataProvider().fetch()
    if not isinstance(matches, list):
        matches = list(matches)
    result = scanner.scan(matches)

    print(format_table(result) if not args.no_table else format_list(result))
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()