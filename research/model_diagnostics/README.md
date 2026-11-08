# Reproducing the isolated model diagnostics

These scripts read the pinned data-branch snapshot and print JSON; they do not run the scanner main entrypoint, fetch live providers, update ledgers or publish reports. Source snapshots and a Python environment are placed **outside the repository**. The original baseline is preserved in the report and results; tests now also verify that the prediction input pipeline applies the corrective cutoff and event-ID reconciliation. Direct raw lookups remain unsafe without that pipeline.

Code baseline: `c5f36454a039aeec454252f3d0c97d81095e1f83`. Data snapshot: `6c63d69397aedc461150db8ddc7351082792ee1c`. The snapshot is dated 2026-11-08, later than the task's supplied 2026-11-04 session date. The replay imposes the fixed as-of cutoff `2026-11-04 00:00 SAST` and uses only strictly earlier match dates in feature calculations. It **cannot reconstruct when each match statistic was originally collected** and is not an untouched historical production publication.

## Environment and input

From the repository root:

```bash
python3 -m venv /tmp/mr2-audit-env
/tmp/mr2-audit-env/bin/pip install numpy==2.4.6 pandas==3.1.1 scipy==1.17.1 requests==2.34.2 pytest==9.2.0 reportlab
mkdir -p /tmp/mr2-research
curl -L --fail 'https://codeload.github.com/Ndumiso19894/Mr2Odds/tar.gz/6c63d69397aedc461150db8ddc7351082792ee1c' -o /tmp/mr2-research/data.tar.gz
sha256sum /tmp/mr2-research/data.tar.gz
# Expected b0a10d9c238b5301856931432c651572dfe966f87b13e7faac3573121cd1a23e
tar -xzf /tmp/mr2-research/data.tar.gz -C /tmp/mr2-research --wildcards '*/data/ls/stages/*.json' '*/data/cache/*.csv' '*/data/app/days/*.json' '*/data/app/latest.json'
SNAP=/tmp/mr2-research/Mr2Odds-6c63d69397aedc461150db8ddc7351082792ee1c
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.
/tmp/mr2-audit-env/bin/python research/model_diagnostics/inventory.py "$SNAP" > /tmp/mr2-research/inventory.json
/tmp/mr2-audit-env/bin/python research/model_diagnostics/chronology.py "$SNAP" > /tmp/mr2-research/chronology.json
/tmp/mr2-audit-env/bin/python research/model_diagnostics/replay.py "$SNAP" 2026-11-04 > /tmp/mr2-research/signal_comparison.json
/tmp/mr2-audit-env/bin/python -m pytest -q -p no:cacheprovider tests/test_model_signals.py tests/test_scanner.py tests/test_worldfeed.py research/model_diagnostics/test_research.py
```

Replay duration was approximately 4½ minutes in the audit environment. Inputs' individual file hashes and counts are in `results/inventory.json`; baseline settings and package versions are in `results/baseline.json`. The snapshot path in regenerated JSON will reflect the local path. Runtime caches are kept outside the repository. The pinned snapshot was not available as-of the simulated date; do not substitute the output for a point-in-time backtest.

## Scope

`inventory.py` identifies *candidate* football-data/Livescore overlaps using exact normalized country, ordered team names and match date; it does not use fuzzy matching or merge any records. Names that differ between sources, current live-season football-data files and extra-league files are missing, so overlap and conflict estimates are lower-bound, sample-specific observations, not global production rates. An event ID duplicated across archived Livescore stage files is a stronger identity match.

`replay.py` is an observational **world-archive-only** sensitivity study. It applies the existing scanner/profile, goals-signal and count-model functions to prior-day data; baseline and signal predictions share exactly the same eligible matches. Historical rows, including duplicate IDs, remain unmodified, and target rows are not deduplicated. It does not reconstruct football-data current-season input, extra feeds, SportyBet, prediction publications, eligibility or settlement. Global priors and provider selection therefore differ from production. `HxG`/`AxG` are unavailable in this dataset, so xG cannot be evaluated. Off-target, shots and outcome data may have been backfilled after the prediction date. Day-level bootstrap intervals quantify sampling variation in this retrospective dataset only; multiple comparisons and unverified historical data availability limit inference.

`chronology.py` demonstrates the original unbounded raw H2H and trends lookups against the later archive; its future-dated archived results are not asserted to be authentic actual results. The scanner now supplies these lookups with a filtered prediction pool. See `REPORT.md` for baseline interpretation, `IMPLEMENTATION.md` for the first implementation phase, and `CROSS_PROVIDER_REVIEW.md` for the review-gated reconciliation work and current limitations.

To reproduce the same-target, world-only implementation comparison:

```bash
/tmp/mr2-audit-env/bin/python research/model_diagnostics/compare_implementation.py "$SNAP" > /tmp/mr2-research/implementation_comparison.json
```

This compares the prior same-day-inclusive history and default-on experimental signals against the updated prior-day, event-ID-deduplicated, signals-off inputs, on the same observed targets. It does not reconstruct prices or production publications and cannot establish predictive improvement.
