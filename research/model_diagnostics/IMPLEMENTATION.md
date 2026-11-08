# Implementation and remaining validation — isolated branch

This report records the first implementation phase. For the later review-gated cross-provider work, current tests and unresolved identity risks, see `CROSS_PROVIDER_REVIEW.md`.

No deployment, publishing, workflow runs, live scan, posts, archive updates, or schedule changes were performed. Original code/data baseline and retrospective signal study are retained in `REPORT.md` and `results/`. Nothing here establishes improved live accuracy or profitability.

## Implemented

* All scanner prediction inputs now share a strict **before scan calendar day** cutoff, based on `now` including `SCAN_NOW`: team and venue profiles, league averages, opponent ratings, xG/shots, corners/cards, H2H and trends. With date-only result records, even an apparently earlier same-day result is excluded. Same-day results remain in a separate settlement input. Future fixtures are analysed using scan-time history, not later data. This is conservative, but the lack of collection timestamps means old data could still have been backfilled after the cutoff.
* Repeated Livescore event IDs with matching competition, teams, IDs, date and score are collapsed in memory for predictions. The shortest stage code is selected deterministically and every contributing stage code remains in `_history_sources`. Conflicting statistics are set to missing and logged; conflicting identity or score quarantines that event from prediction history. Raw archives and the settlement pool are unchanged. Stage/division attribution of a duplicated event changes to the selected stage, which can affect division averages. Dedupe diagnostics are logged per scan.
* Experimental xG, shots-on-target and off-target-corners adjustments default **off**; `EXPERIMENTAL_MODEL_SIGNALS=1` deliberately opts into labelled, unvalidated research. Model architecture, parameters, thresholds, bookmaker price floors and competition policy were not changed.
* `SCAN_NOW` scans withhold current reference and SportyBet prices because those quotes cannot be authenticated as of the overridden time. A normal scan still fetches current prices, but source publication/update timestamps are not proven. Legacy run parlays no longer use feed-average prices or mathematically derived double-chance prices as actual bookmaker quotes when SportyBet is unavailable.
* Top five correct-score probabilities now come directly from the existing normalised score matrix and are exported in the Android detail contract. The guide's outdated BTTS and unsupported card-settlement descriptions were corrected. Match data warnings now describe date and source-overlap limitations.
* Added targeted cutoff, same-ID reconciliation/conflict, market-matrix, missing-price, scoreline and policy tests. Existing history, price-floor, Final Picks and UI tests still run.

## Same-target implementation comparison

`results/implementation_comparison.json` is reproducible with `compare_implementation.py`. It uses the identical pinned **postdated** world-only archive and the same 51 allowed unique-ID targets dated 2026-11-04. Before: 70,410 historical rows, including 52 same-day records; after: 70,298, after removing those 52 and collapsing 60 repeated-ID rows. Fifty targets had sufficient samples in both variants. Baseline uses same-day-inclusive history and default-on signals; updated uses prior-day history, ID deduplication and signals off. It is not a full production replay and does not isolate effects of each individual change.

| Market | Mean old | Mean new | Mean absolute change (pp) | Max change (pp) | Brier old → new |
|---|---:|---:|---:|---:|---:|
| O1.5 | 79.46% | 79.08% | 1.50 | 7.58 | 0.1690 → 0.1776 |
| O2.5 | 57.17% | 56.53% | 2.26 | 8.96 | 0.1932 → 0.2084 |
| BTTS | 55.20% | 55.28% | 1.81 | 5.97 | 0.2279 → 0.2395 |
| Home win | 45.91% | 46.22% | 5.32 | 30.44 | 0.1773 → 0.2268 |

These one-day Brier numbers are **not evidence the old model was better**: it could use same-day target results, and the snapshot and statistics postdate the replay. They show material probability changes, making further validation important. Full 1X2 results and unrounded values are in the JSON. No valid comparable recommendation counts or ROI can be calculated from this archive because verified historical SportyBet prices, selection eligibility and settlements were not reconstructed; the absence of odds is not treated as a zero price or zero selections.

## Numerical and price checks

Regression tests check 0–10 Dixon–Coles matrix normalisation, nonnegative cells and goal/BTTS/1X2/double-chance/team-goal consistency over low, asymmetric and capped extreme rates; negative-binomial corner/card half-line tails are bounded and monotone. At λ=4.5, the unadjusted single-team Poisson mass above 10 is approximately 0.00667; the existing truncated score matrix is renormalised, so that tail is not represented explicitly. The current ρ and other parameters were not altered. No calibrated predictive or profitability claim follows from these numerical checks.

Prices are not inputs to model probabilities. `safe._two_way` uses proportional de-margining, while `markets.fair_two_way` uses power de-margining; these comparison methods can differ and are not silently treated as identical. Expected return for an ordinary win/loss leg is model probability × actual decimal price − 1. Zero/missing or sub-floor quotes are not eligible. Quote source/update timestamps and staleness are not fully verified for normal scans; no historical price or card settlement has been invented. The legacy draw-no-bet market is not implemented as a recommended selection; its push and quote handling would need explicit validation before adding one.

## Outstanding; not ready for production approval

1. Cross-provider duplicates are **not** automatically reconciled. Equal dates/names/scores are candidate evidence, not proof of identity or compatible statistic definitions; football-data and Livescore use different team and division keys, which affect division priors and count profiles. These duplicates can still inflate samples, evaluation or contextual H2H. A reviewed event/competition alias map, ambiguity handling, source conflict diagnostics and cross-key migration tests are required before safe reconciliation.
2. Strict point-in-time replay requires immutable timestamped historical provider snapshots, including when each statistic and quote was collected. Date-only filtering cannot reconstruct them. No untouched prospective holdout, competition/market breakdown with sufficient coverage, robust chronological validation of xG, or complete priced baseline-versus-updated recommendation count is currently possible from the available snapshot. Existing retrospective signal results include uncertainty and calibration in `results/signal_comparison.json` but are not proof of live benefit. New decisions should wait for these inputs and an independently reserved period.
3. Genuine quote freshness and SportyBet booking/card settlement rules remain unverified; bookings remain ineligible and existing booking tickets pending. As-of override mode withholding prices does not itself make the other historical inputs point-in-time correct.
4. Full Android APK build and real remote workflow execution were not run here. No Java toolchain is installed locally. Workflow-equivalent Python and JavaScript tests were run without dispatching jobs. The skipped league integration test requires a local archive not present in this checkout.

## Validation run

* `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/mr2-audit-env/bin/python -m pytest -q -rs -p no:cacheprovider leagues/tests tests research/model_diagnostics/test_research.py` — **235 passed, 1 skipped** (local league archive unavailable).
* All 10 `tests/test_*_ui.js` suites — passed; `node --check android/app/src/main/assets/www/pages.js` passed.
* `python scripts/check_secrets.py` — passed on tracked files; `git diff --check` passed.
