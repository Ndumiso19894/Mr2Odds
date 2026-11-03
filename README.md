# Mr2Odds — Goal Scanner

A goal scanner for football/soccer betting markets. It loads matches with
goal-related odds (Over/Under, Both Teams To Score), converts odds to implied
probabilities, applies scanning rules, and surfaces the best goal-market
opportunities.

## Features

- Scan match lists for Over/Under and BTTS goal opportunities
- Implied-probability and edge calculation from decimal odds
- Configurable scanning rules (probability thresholds, form filters, min odds)
- Works out of the box with embedded sample data
- Pluggable data providers (swap in your own odds API)
- Optional FastAPI/uvicorn web server (`mr2odds serve`)

## Quick start

```bash
# install (optional, only needed for the web server)
pip install -r requirements.txt

# run the scanner against sample data
python -m mr2odds scan

# run the web API
python -m mr2odds serve
```

Example output:

```
╔═══════════════════════════════════════════════════════════════════════╗
║                              GOAL SCANNER                            ║
╚═══════════════════════════════════════════════════════════════════════╝

Found 4 opportunities (scanned 12 matches)

#   Match                      Market          Odds  Implied   Edge   Score
---- ------------------------ ----------------- ----- --------- ------ ------
1   Liverpool v Arsenal        Over 2.5 Goals   1.90   52.6%    8.6%   8.7
2   Bayern v Dortmund          BTTS — Yes        1.75   57.1%   12.1%   8.4
...

Use `python -m mr2odds scan --help` for options.
```

## Repository layout

```
mr2odds/           # package: models, scanner, providers, CLI
tests/             # pytest tests
config.py          # scanning rule defaults
main.py            # CLI entry point (-m mr2odds)
requirements.txt   # optional web-server deps
```

## Config

Edit `mr2odds/config.py` to tune the scanning rules:

```python
RULES = ScanRules(
    over_under_min_implied_prob=0.52,
    btts_min_implied_prob=0.55,
    min_combined_form=2.4,        # home + away goals per game
    min_odds=1.40,
    max_odds=4.50,
)
```

> ⚠️ This is a hobby/analysis tool, not financial advice. Bet responsibly.