# Cross-provider reconciliation: implementation and review queue

Work is confined to the isolated branch. No live scan, deployment, publication, provider fetch, workflow dispatch, post, production archive or schedule change was performed. This report covers **stage 1**; it does not claim that cross-provider overlap has been fully resolved.

## What is implemented

* `cross_provider.py` builds one-to-one candidate groups using normalized country, date and ordered team names. Normalization finds candidates only; it does not prove identity. Multiple rows on either side are flagged as ambiguous. Raw country, both team names and competition must match exactly, scores must agree, and Livescore event and team IDs must exist before a pair is eligible for independent review. Team/competition aliases and score conflicts remain blocked. If two kickoffs have known time zones they are compared in UTC; invalid zones and conflicting times block the pair. Unverified or absent time zones are explicitly labelled and require review, not assumed to agree.
* **No cross-provider pair is merged merely because it looks exact.** An independent reviewer must provide the candidate ID, reviewer, rationale and concrete identity evidence in `history_reconciliation_approvals.json`. The code rechecks every pair when loading it. Malformed or duplicate approvals fail closed; a changed or ambiguous identity is not merged. **The approval file is empty: zero cross-provider merges have been enabled.** The available snapshot has no independent cross-provider event-ID link or established kickoff time zones, so this branch cannot safely certify those identities itself.
* For a separately reviewed pair, the prediction pool keeps one event, its Livescore event/team IDs, both complete source records in memory, source references, division keys, reviewer metadata and conflicts. For model normalisation the football-data division is the documented priority. Statistics reported by both providers but disagreeing are missing in the merged row; consistent or singly reported values are retained with source provenance. Earlier conflicting Livescore-stage statistics stay missing. Original provider archives and the settlement pool are not changed.
* Global priors, team form, opponent history, H2H and trends use one event; division-specific goal/count priors and team-page division views can see that event under each relevant provider's division key. Competition-share evidence recognises both keys. The cache schema and division-page cache key were updated to prevent stale pre-reconciliation results. Missing/conflicted yellow or red card counts are no longer silently treated as zero in team/model/trend evidence; booking recommendations and settlement remain withheld.
* Source references and conflicting fields are included in match evidence when a reviewed pair is merged; the scanner logs summary counts. The detailed offline queue includes each candidate's source identity, stats, mismatch reasons and candidate ID. It is a large generated artifact and is not committed; regenerate it at `/tmp/mr2-research/cross_provider_review.json` using the command below. No online fetch is required if the pinned input snapshot is already available.

## Pinned snapshot review, 400-day history before 2026-11-04

The snapshot was created later than the illustrative cutoff. It includes cached football-data main divisions and the Livescore archive, **not** current live-season football-data or extra feeds. There were 6,205 football-data rows and 70,298 Livescore rows after removing 60 duplicate Livescore event-ID rows.

* **1,821 cross-provider candidate groups:** 1,380 exact-looking pairs require independent review; 441 were blocked (395 competition-name aliases, 46 team/country-name aliases). Reasons can overlap in general. No candidate in this sample had a score mismatch, but identical scores alone do not prove identity.
* All 1,821 pairs have recorded kickoff clock values whose source time zones are not established. They are **unverified**, not asserted to be conflicting instants. Do not approve a pair without independent identity evidence.
* Across 1,752 pairs with both fields present, mismatches were: home/away corners **51/41**, shots on target **275/271**, total shots **756/737**, yellows **93/99**, reds **7/9**. These are provider disagreements, not a determination of which source is correct. For a reviewed event each conflicting field is excluded rather than arbitrarily preferred. Among all candidate groups, 1,121 had at least one conflicting statistic.

The candidate matcher currently does not merge aliases even if they look plausible. It does not detect every duplicate: differing dates, reversed venues, unrecorded teams, missing sources and other spelling differences can escape candidate generation. Unreviewed/blocked rows remain separate and may still inflate samples; this is why the branch is not ready for production.

## Hypothetical sensitivity, not approved identities

`results/cross_provider_sensitivity.json` applies all 1,380 exact-looking candidates **hypothetically in memory** to measure the pipeline; it does not write approvals and is not verification. On 50 matched, eligible Livescore fixtures from the same postdated snapshot, with prior-day inputs and experimental signals off:

| Probability | Mean absolute change | Largest change |
|---|---:|---:|
| Over 1.5 goals | 0.022 percentage points | 0.205 pp |
| Over 2.5 goals | 0.037 pp | 0.382 pp |
| BTTS | 0.033 pp | 0.458 pp |
| Over 9.5 corners (16 matched) | 0.115 pp | 1.313 pp |

The unique history shrank from 76,503 to 75,123 rows in this hypothetical only. No H2H or team sample count changed among the 50 targets; that is sample-specific, not a general guarantee. Different schedules, source mixes and reviewed pairs may have different effects. The experiment does not establish accuracy, calibration, bookmaker eligibility or profitability; actual priced recommendation counts were not reconstructed.

## Independent review and reproducibility

Each proposed approval should cite independently verifiable event identity and kickoff/date context, not just a normalized name or score. Do not copy all `needs_review` entries into approvals. If an event changes identity, competition, score, ID or known kickoff metadata, its candidate ID changes and it must be reviewed again. Alias cases require a separately designed, reviewed alias migration; they cannot currently be forced through the gate.

```bash
SNAP=/tmp/mr2-research/Mr2Odds-6c63d69397aedc461150db8ddc7351082792ee1c
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/mr2-audit-env/bin/python research/model_diagnostics/cross_provider_review.py "$SNAP" > /tmp/mr2-research/cross_provider_review.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/mr2-audit-env/bin/python research/model_diagnostics/cross_provider_sensitivity.py "$SNAP" > /tmp/mr2-research/cross_provider_sensitivity.json
```

Snapshot recreation and hashes are documented in `README.md`. The candidate file contains the local snapshot path and can differ if reproduced elsewhere.

## Remaining before release

Independent event review and a safe alias/key strategy remain necessary. The partially implemented point-in-time cutoff still cannot establish when old statistics were collected. An untouched prospective holdout with timestamped results and verified prices is still needed; xG/shot experiments remain disabled. Actual bookmaker quote freshness and booking rules remain unverified. Do not deploy, publish or activate collection until explicitly approved.

## Validation run

* `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/mr2-audit-env/bin/python -m pytest -q -rs -p no:cacheprovider leagues/tests tests research/model_diagnostics/test_research.py` — **250 passed, 1 skipped** (local league archive unavailable).
* All 10 `tests/test_*_ui.js` suites passed; `git diff --check` passed.
* `python scripts/check_secrets.py` passed for tracked files. No Android APK was built; the local Java toolchain remains unavailable.
