# Premier League pilot: corroboration and sensitivity

## Decision

Five Premier League candidate pairs were checked against a pinned third-party mirror of official Fantasy Premier League (FPL) fixtures and a pinned OpenFootball record. Dates, ordered teams, regulation scores and UTC kickoffs agree across those references and the football-data rows. The five Livescore records have the same teams, dates and scores, and their clocks are compatible with UTC+2. **Their original per-record timezone offsets were not retained**, however, so UTC+2 is an assumption, not a verified collection fact. The pairs remain **unapproved and unmerged**. The scanner's currently configured Johannesburg timezone supports the assumption, but does not prove how an individual older archive record was collected.

FPL and OpenFootball are separately hosted records; their complete underlying data-supply independence has not been established. The FPL data is a third-party mirror, not a direct authenticated response in this session. Neither source independently validates the Livescore event ID or the providers' match statistics. This is strong fixture corroboration, not conclusive historical provenance.

| Date | Match | Score | FPL fixture ID | Kickoff UTC | FD clock (UK convention) | LS stored clock* |
|---|---|---|---:|---|---|---|
| 2026-05-24 | Crystal Palace – Arsenal | 1–2 | 373 | 15:00 | 16:00 | 17:00 |
| 2026-05-24 | Liverpool – Brentford | 1–1 | 375 | 15:00 | 16:00 | 17:00 |
| 2026-05-18 | Arsenal – Burnley | 1–0 | 361 | 19:00 | 20:00 | 21:00 |
| 2026-05-17 | Everton – Sunderland | 1–3 | 366 | 14:00 | 15:00 | 16:00 |
| 2026-05-15 | Aston Villa – Liverpool | 4–2 | 362 | 19:00 | 20:00 | 21:00 |

\* The Livescore offset is not recorded in the historical event. Its displayed clock matches UTC+2 in each case, but that does not prove the offset. Football-data local time is converted using the repository's existing `Europe/London` feed convention; FPL and OpenFootball explicitly state their UTC times/offsets. Candidate IDs, Livescore IDs, comparison details and source hashes are in `results/premier_league_batch.json`. The two providers' comparable recorded match statistics happened to agree on these five rows, but matching definitions or truth is not established by the fixture references.

## Model and recommendation comparison

The actual approvals file still has **zero entries**. For the tested replay inputs, running the real approval gate removed zero rows and the result frame was identical; no change in probabilities or recommendations is claimed from this pilot.

For sensitivity only, the same five unapproved pairs were merged **in memory**, without changing the approval file. On seven matched archived England Premier League targets dated 2026-09-12, using identical prior-day inputs and signals off, the sample changed from 74,010 to 74,005 rows. All seven remained goal-eligible. Goal-team and H2H counts were unchanged; corner-team sample counts were also unchanged, but the contents of the capped corner samples differed for six targets.

| Market | Mean absolute change | Largest absolute change |
|---|---:|---:|
| Over 1.5 goals | 0.0012 percentage points | 0.0032 pp |
| Over 2.5 goals | 0.0017 pp | 0.0045 pp |
| BTTS | 0.0020 pp | 0.0043 pp |
| Over 9.5 corners | 0.6282 pp | 1.0400 pp |

These are a **hypothetical implementation sensitivity**, not a recommendation to approve the five pairs or evidence of improved accuracy. Seven targets are not a meaningful holdout. The historical snapshot postdates this replay date, its outcomes and statistics may have been backfilled, and the main current-season and extra feeds were unavailable. Actual historical SportyBet prices and eligible selections for the matched targets were not independently verified, so no priced recommendation count, profit or ROI comparison is reported. `results/premier_league_target_sensitivity.json` has all markets; a separate 50-target world-only scenario is in `results/premier_league_batch_sensitivity.json`.

## Sources and reproduction

* FPL fixture and team mirror pinned at [commit a8337d50698de908f92e8d1905142d968384a2ca](https://github.com/vaastav/Fantasy-Premier-League/tree/a8337d50698de908f92e8d1905142d968384a2ca/data/2025-26); its [license](https://github.com/vaastav/Fantasy-Premier-League/blob/a8337d50698de908f92e8d1905142d968384a2ca/LICENSE) says the data belongs to FPL and Understat. No full third-party fixture dataset was copied into this repository or used as a prediction feature.
* OpenFootball full fixture file pinned at [commit 1d0afcbd66d88df55e98166dd7d986d7c56d82ab](https://github.com/openfootball/football.json/blob/1d0afcbd66d88df55e98166dd7d986d7c56d82ab/2025-26/en.1-full.json).
* The existing data-branch snapshot and candidate queue are documented in `README.md` and `CROSS_PROVIDER_REVIEW.md`.

From the repository root, after recreating the pinned Mr2Odds snapshot and audit environment described in `README.md`:

```bash
mkdir -p /tmp/mr2-research
gh api 'repos/vaastav/Fantasy-Premier-League/contents/data/2025-26/fixtures.csv?ref=a8337d50698de908f92e8d1905142d968384a2ca' -H 'Accept: application/vnd.github.raw+json' > /tmp/mr2-research/fpl_fixtures_2025_26.csv
gh api 'repos/vaastav/Fantasy-Premier-League/contents/data/2025-26/teams.csv?ref=a8337d50698de908f92e8d1905142d968384a2ca' -H 'Accept: application/vnd.github.raw+json' > /tmp/mr2-research/fpl_teams_2025_26.csv
gh api 'repos/openfootball/football.json/contents/2025-26/en.1-full.json?ref=1d0afcbd66d88df55e98166dd7d986d7c56d82ab' -H 'Accept: application/vnd.github.raw+json' > /tmp/mr2-research/openfootball_2025_26_full.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/mr2-audit-env/bin/python research/model_diagnostics/verify_premier_league_batch.py /tmp/mr2-research/cross_provider_review.json /tmp/mr2-research/fpl_fixtures_2025_26.csv /tmp/mr2-research/fpl_teams_2025_26.csv /tmp/mr2-research/openfootball_2025_26_full.json > /tmp/mr2-research/premier_league_batch.json
SNAP=/tmp/mr2-research/Mr2Odds-6c63d69397aedc461150db8ddc7351082792ee1c
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/mr2-audit-env/bin/python research/model_diagnostics/cross_provider_sensitivity.py "$SNAP" /tmp/mr2-research/premier_league_batch.json 2026-09-12 > /tmp/mr2-research/premier_league_target_sensitivity.json
```

The review script verifies the pinned third-party file hashes and fails closed on nonunique matches, score or UTC kickoff disagreements. It does not write approvals. Its timezone parser explicitly handles `UTC+1` as a positive offset, avoiding the reversed-sign interpretation used by some date parsers.

## Remaining

Retrieve trustworthy event-level Livescore timezone provenance or an independently authenticated cross-provider event-ID mapping, then review the pairs again. Historical archives do not themselves supply those facts. Verified timestamped SportyBet quotes and a prospective point-in-time holdout remain prerequisites for a priced evaluation and release. No production data, schedules, social posts, deployments or publications were changed.

## Validation

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/mr2-audit-env/bin/python -m pytest -q -rs -p no:cacheprovider leagues/tests tests research/model_diagnostics/test_research.py` — **253 passed, 1 skipped** (local league archive absent). Added tests cover explicit UTC-offset signs, failing closed on score conflict, and withholding approval when archive timezone provenance is missing. `git diff --check` and the tracked-file secret check passed.
