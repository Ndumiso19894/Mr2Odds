# Recent-form model research

This directory contains an **offline, unvalidated retrospective** of the recent-form overlay. The authorized live scanner uses the same pure maths in `recent_form.py`, preserving longer history and league averages; it does not import this research adapter. This comparison makes no provider calls and is not prospective validation.

## What it tests

The comparison baseline is the earlier signals-off Dixon–Coles goal model: league home/away averages multiplied by the existing team's attack and the opponent's defence ratings. Its profile uses up to 40 matches over 400 days with time decay, venue blending and shrinkage. Division averages themselves are shrunk towards the global prior. The challenger starts from **the same baseline, same eligible matches and same inputs**:

1. For each team, examine the most recent 5, the preceding 5 (giving a full last-10 view), and up to 5 relevant venue matches: home for the home team, away for the away team. Goals for and against are normalised to their league averages. Combine the existing rating with weights up to 20%, 10% and 10% respectively, scaled down for incomplete windows. Each window is further shrunk toward the existing rating using five prior matches. Thus at least 60% of each rating is retained directly, and in practice the prior contributes more. The venue window can overlap the last ten; these are not independent samples.
2. Count scored, failed-to-score, conceded and clean-sheet matches in each window, alongside goals for/against and actual sample sizes. Scoring-frequency evidence affects the model through a small, shrunk adjustment: the most recent five count twice, the previous five once and the relevant venue five once. For a team's implied scoring probability `p`, each of its scoring observations and its opponent's conceding observations contributes `0.10 * (weighted_successes - weighted_n * p) / (12 + weighted_n)`. The initial `p` comes from the candidate Poisson rate; the final probabilities all come from the same recalculated score matrix. These constants are research assumptions, not established statistical effects. Historical counts and model probabilities are separately labelled.
3. Use up to five recent head-to-head meetings from the same Livescore competition in the previous 1,095 days **only when event and team IDs are present and unambiguous**. Below three meetings the effect is zero. Otherwise the mean goals in each direction is blended into the candidate goal rate with weight `0.10 * n / (n + 5)`, at most 5% for five meetings. Reversed venues are oriented to the current teams; tied-date or duplicate events are excluded. This does not infer cross-provider identity from names.
4. Continue using the existing normalised score matrix and derive goals, 1X2, double chance, team goals and zero-goal probabilities from it consistently. Quotes, selection rules and price floors are untouched. The variant does not alter corners or cards.

Only valid completed-score rows strictly before the cutoff calendar day are used. Same-day history is excluded conservatively; ambiguous same-day team records in recent windows reject the challenger rather than inventing an order. Missing or invalid scores are not converted into zero. The baseline and variant both require the existing minimum effective team sample; a missing division falls back to the existing global league prior. The data frame uses the scanner's naive local-calendar date convention; this is **not** proof of an event's actual timezone or when its statistic was captured. The offline research context is single-threaded and uses scanner in-process caches; production does not use that research context. The live integration reuses its own per-run indexes and caches and falls back to the baseline on ambiguous or unusable recent history.

### Squad availability is not yet a model input

There is no validated historical feed of pre-kickoff injuries, suspensions or available squads, no reliable player impact estimates, and no authorized live source for this task. Therefore the variant explicitly reports `squad_availability.status = "not_used"`; it makes **no guessed probability adjustment**. The existing confirmed-lineup pilot is also context-only: a player not starting is not necessarily injured or unavailable. Actual squad effects require a rights-cleared, timestamped source, exact fixture/team/player identity, and an independently calibrated and validated impact model. Until then this part of your request remains open rather than fabricated.

## Reproduce

With Python dependencies from `requirements.txt` plus `scipy` and `pytest`:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m research.recent_form.demo
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/test_recent_form_research.py
```

The demo uses **invented data** and prints the separate baseline, variant, league inputs and recent evidence. No provider calls or files are created by it. For the local pinned historical archive and environment setup, see `research/model_diagnostics/README.md`. After verifying its documented SHA-256, run:

```sh
SNAP=/tmp/mr2-research/Mr2Odds-6c63d69397aedc461150db8ddc7351082792ee1c
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/mr2-audit-env/bin/python research/recent_form/compare.py "$SNAP" --start 2026-10-01 --end 2026-10-15 > /tmp/recent-form-comparison.json
```

`end` is exclusive. A compact aggregate from that run is in `results/retrospective_2026_10.json`. Baseline and variant use identical targets and identical earlier-dated, same-ID-reconciled inputs. Any inadequate team sample or ambiguous ordering is excluded from **both**. Measures include paired Brier and log loss, mean/max absolute probability changes, day-block bootstrap intervals, per-day coverage, and larger-league slices. There are no verified historical odds, recommendations, bets or ROI.

## Exploratory result—not evidence of improvement

Across 14 days, 2,770 of 3,043 eligible archived target fixtures matched both models. Of 273 excluded, 271 lacked adequate baseline team history and 2 had ambiguous same-day team records. Both teams had complete last-five windows in all 2,770; both had complete last-ten windows in 2,238 and complete venue-five windows in 2,240. The conservative H2H effect was applied in 783 fixtures. Squad availability was never used.

| Market | Mean absolute change | Maximum change | Brier baseline → variant | Log loss baseline → variant |
|---|---:|---:|---:|---:|
| Over 1.5 | 2.13 pp | 12.18 pp | 0.16608 → 0.16703 | 0.51117 → 0.51351 |
| Over 2.5 | 3.03 pp | 13.64 pp | 0.23494 → 0.23599 | 0.66189 → 0.66432 |
| Over 3.5 | 2.95 pp | 12.99 pp | 0.21900 → 0.21916 | 0.62857 → 0.62918 |
| BTTS | 2.37 pp | 11.30 pp | 0.24354 → 0.24448 | 0.68013 → 0.68226 |
| Home team scores zero | 1.96 pp | 10.82 pp | 0.16211 → 0.16185 | 0.49919 → 0.49837 |
| Away team scores zero | 2.04 pp | 12.06 pp | 0.18952 → 0.19060 | 0.56380 → 0.56631 |
| Home win | 2.38 pp | 13.16 pp | 0.22735 → 0.22743 | 0.64622 → 0.64663 |
| Draw | 0.94 pp | 5.27 pp | 0.17531 → 0.17523 | 0.53409 → 0.53382 |
| Away win | 2.16 pp | 10.78 pp | 0.20009 → 0.19955 | 0.58568 → 0.58483 |

Lower Brier/log loss is better, but this short exploratory comparison does **not** validate either model. In this sample the challenger was worse on total-goals/BTTS scores and mixed on 1X2 and team zero-goal outcomes; the implementation was not retuned after viewing it. The source archive postdates the simulated cutoff, so results and stats may be backfilled. It only includes Livescore world history, lacks the live football-data and extra feeds, may contain unresolved cross-provider identity issues, uses retrospective completed-event selection, and has no authenticated odds or source update times. The day-bootstrap intervals are conditional on these 14 dates and don't cure those limitations. It is not an untouched prospective holdout or a reason to deploy the variant.

## Live rollout and outstanding validation

Independently freeze the research formula and cohort, capture authorized timestamped pre-cutoff inputs and model outputs, and compare both models on the same genuinely future fixtures with held-out evaluation, coverage and market/league breakdowns. Separately obtain and validate squad information and player effects. Keep unverified or unavailable inputs out and report exclusions. Actual profitability requires verified executable prices, stakes and settlement; no ROI is claimed here. The user authorized the recent-form live rollout with squad effects off. Set `RECENT_FORM_ENABLED=0` to restore the baseline; `EXPERIMENTAL_MODEL_SIGNALS=1` cannot be combined with the recent-form overlay and requires explicitly disabling it. No new squad provider or automatic squad collection was authorized. A live rollout is not evidence of improved accuracy or profitability.

## Verification performed

- Full Python suite including the pinned-archive smoke test: **332 passed**, no skips (`leagues/tests`, `tests`, and `research/model_diagnostics/test_research.py`). The local environment included `imageio-ffmpeg` for optional video tests.
- All 10 existing JavaScript UI suites and Android web-asset syntax check passed; the Android APK was not built in this research task.
- A fresh two-day diagnostic reproduced the same matched predictions/metrics; secret-pattern checks and whitespace checks passed for tracked and new files.
- The retrospective itself made no live provider calls or changes to production data; integration and deployment are separate from that offline run.
