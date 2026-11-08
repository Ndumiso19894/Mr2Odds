# Mr2Odds research diagnostics — ranks 1–3

## Scope and baseline

No production code, model settings, recommendation rules, Android behavior, workflows, live state or historical records were changed. No deployment, publication or external post was performed. The files in this directory are isolated research scripts and aggregated outputs.

- Code snapshot: `c5f36454a039aeec454252f3d0c97d81095e1f83`. Its commit timestamp is 2026-11-08; thus it cannot be assumed to be the code actually running on 2026-11-04.
- Data snapshot: data-branch commit `6c63d69397aedc461150db8ddc7351082792ee1c`, timestamp 2026-11-08 11:34 UTC, SHA-256 of the downloaded tarball `b0a10d9c238b5301856931432c651572dfe966f87b13e7faac3573121cd1a23e`.
- The data snapshot is **later than the session date supplied for this task**. The analysis therefore fixes an illustrative as-of boundary at 2026-11-04 00:00 SAST, and filters later match dates, but cannot show which statistics were available then. GitHub returned no data-branch commit at or before 2026-11-04 00:00 UTC. This is not proof that no other historical archive exists.
- Verified defaults: 120-day half-life, 400-day history, 40 matches, venue K=20, strength K=5, tempo K=40, fixed rho −0.05, and experimental adjustments enabled by default. Full fingerprints/settings/versions: `results/baseline.json`.
- 19 existing and diagnostic tests passed. The three chronology/duplicate characterization checks demonstrate the present behavior, rather than claiming it is correct.

## Confirmed duplicates and measured conflicts

The snapshot contains 88 cached football-data main-league CSVs (2022/23–2025/26) and 498 Livescore stage files. It does **not** contain a cached 2026/27 main-season CSV or the extra-league feed used by the scanner. Cross-source candidates are matched by exact normalized country, ordered team names and date, not by fuzzy aliases; the counts are therefore not an estimate for the entire production pool. No records were merged or deduplicated.

| Scope, before simulated cutoff | Main rows | Livescore rows | Cross-source candidate pairs | Full-time score conflicts |
|---|---:|---:|---:|---:|
| All available history | 30,956 | 134,325 | 4,340 (14.0% of main rows) | 0 / 4,340 |
| Last 400 days | 6,205 | 70,358 | 1,821 (29.3% of main rows) | 0 / 1,821 |

These are overlapping historical matches, not proof all would have appeared in every production scan: `scanner.py:2518–2535` chooses main divisions by countries in that scan. Exact-name matching misses legitimate aliases; this is not a full overlap census.

For the 1,752 matched pairs with both sources' statistics available, the field-level disagreements were:

| Field | Different / comparable | Rate |
|---|---:|---:|
| Home corners | 51 / 1,752 | 2.91% |
| Away corners | 41 / 1,752 | 2.34% |
| Home shots on target | 275 / 1,752 | 15.70% |
| Away shots on target | 271 / 1,752 | 15.47% |

For example, 2026-02-06 Greuther Furth v Magdeburg: football-data `fd_2526_D2.csv` reports 9 home corners; Livescore event `1540707` in `germany__2-bundesliga.json` reports 10. Augsburg v Wolfsburg, 2025-10-04: football-data reports 5 home shots on target and Livescore event `1540464` reports 6. These are provider discrepancies; the study does not establish which definition or source is correct. Individual field disagreements are not independent matches.

Within Livescore, **380 event IDs occur in two stage files** across all pre-cutoff history: 380 extra rows among 134,325 (0.28%). Within the 400-day subset there are 60 duplicated IDs, 60 extra rows among 70,358 (0.085%). All 380 groups agree on date and score; among the 60 with comparable stats, home/away corners and shots on target also agree. One example is event `1424350` (Shonan Bellmare v Tokyo Verdy, 2025-10-03) in both `japan__j-league-2025.json` and `japan__j-league.json`.

**Affected code:** `worldfeed.py:168–193, 374–413` stores and reads stage-level rows; `scanner.py:2529–2542` concatenates them with main/extra sources with no cross-source reconciliation. These confirmed duplicates can enter global priors and some team histories, but this study does **not** quantify their effect on a specific published probability.

## Confirmed chronology behavior versus risks

`scanner.py:2532–2535` filters the goal-model `results` to dates up to the scan date, but the broader `pool` is passed to H2H and trends (`scanner.py:2567, 2621–2627`). `scanner.head_to_head` and `trends.team_rows` have no as-of check (`scanner.py:959–980`; `trends.py:24–44, 54–68`).

- **Confirmed via reproduction:** using the later snapshot as input to a simulated 2026-11-04 scan, H2H for KF Tirana v Teuta Durres returns the archived 2026-11-07 result as its newest prior meeting. This is a retrospective override scenario, not evidence that a real 2026-11-04 publication contained that result.
- **Confirmed future-dated archive records:** the 2026-11-08 snapshot contains three scored events dated in 2027. One is Paris Saint-Germain v Rennes, 2027-03-06, recorded 2–2, Livescore event `1794670`. In reproduction, it is returned as PSG/Rennes H2H and appears first in Rennes trend input. The record may have an erroneous date or score; neither the real match outcome nor the record's correctness is verified. It is nevertheless future-dated relative to both the supplied session date and the snapshot timestamp.
- **Scope:** this confirms an as-of defect in H2H/trend lookup when future-dated records exist. The goal-model date filter excludes these later-dated rows. It does **not** establish that the published goal probabilities used the future record. H2H presence can affect quality-based eligibility; no specific affected recommendation was proved.
- **Potential additional risk:** the core pool uses dates rather than full availability timestamps (`worldfeed.py:399–403`; `scanner.py:2535`). A misdated same-day finished record or retrospectively backfilled statistics may be included without proving they were known at the simulated prediction time. No specific live goal-probability leak from such a record was established.

Full reproducible examples: `results/chronology.json` and `chronology.py`.

## Chronological signal study

**Design.** The retrospective study predicts dated archive outcomes from 2026-09-25 through 2026-11-03, using only archive records from strictly earlier dates and at most 400 days of history. It calls existing scanner/profile and signal/count functions, with no historical deduplication. This interval is later than the historical report ending 2026-09-24, but because the code and data snapshot are later and source-availability times are missing, it is **not a verifiably untouched point-in-time holdout**.

This is a Livescore-only approximation, not an end-to-end production replay: it omits the current/extra football-data inputs and reconstructs neither actual fixtures, prices, selections nor all-source global priors. Differences below are descriptive and cannot establish profitability or deployment readiness.

**Coverage:** 9,248 evaluated target rows with both goal profiles meeting the minimum effective sample; 3,109 had at least one applicable SOT adjustment. There were 3,056 rows with a qualifying corner model and observed corners; off-target adjustment applied for 1,742 of them. HxG/AxG are not present in the 88 cached CSVs and Livescore archived results set them missing: **zero xG-applicable cases**, so xG cannot be evaluated from these inputs. The separate current live-season feed was not archived here; this says nothing definitive about its coverage.

### Goals: paired SOT ablation, n=3,109

Lower Brier and log loss are better; calibration is mean predicted probability versus observed frequency on the same sample.

| Market | Brier baseline → SOT | Log loss baseline → SOT | Mean predicted baseline → SOT | Observed |
|---|---:|---:|---:|---:|
| Over 1.5 | 0.163695 → 0.163585 | 0.507724 → 0.507405 | 77.95% → 78.04% | 79.16% |
| Over 2.5 | 0.242791 → 0.242619 | 0.678473 → 0.678120 | 54.23% → 54.37% | 55.39% |
| BTTS | 0.245626 → 0.245589 | 0.684446 → 0.684375 | 55.31% → 55.32% | 56.19% |
| Home win | 0.232197 → 0.231910 | 0.655808 → 0.655172 | 43.87% → 43.89% | 45.16% |
| Draw | 0.183286 → 0.183252 | 0.552796 → 0.552712 | 24.68% → 24.60% | 24.28% |
| Away win | 0.196196 → 0.195883 | 0.577422 → 0.576662 | 31.45% → 31.51% | 30.56% |

For example, Over 2.5 in the signal's 50–60% bucket: n=1,467, mean prediction 54.75%, actual 54.74%; the baseline bucket has n=1,475, mean 54.69%, actual 55.05%. Bins change membership between variants and should not be treated as paired samples. All bins are in `results/signal_comparison.json`.

Calendar-day bootstrap (2,000 resamples) for SOT minus baseline gives O2.5 Brier difference −0.000172, 95% interval [−0.000347, −0.000011], and BTTS −0.000037, interval [−0.000118, +0.000045]. Multiple outcomes were examined, and these intervals cannot account for post-hoc historical data availability or model-selection bias. The observed O2.5 difference is small; **it does not validate the live adjustment**.

### Corners: paired off-target ablation, n=1,742

| Market | Brier baseline → signal | Log loss baseline → signal | Mean predicted baseline → signal | Observed |
|---|---:|---:|---:|---:|
| Over 8.5 | 0.223203 → 0.223194 | 0.637948 → 0.637927 | 63.28% → 63.28% | 65.67% |
| Over 9.5 | 0.245504 → 0.245496 | 0.684113 → 0.684099 | 51.36% → 51.36% | 55.22% |
| Over 10.5 | 0.245056 → 0.245052 | 0.683532 → 0.683528 | 39.78% → 39.78% | 43.69% |
| Over 11.5 | 0.221708 → 0.221696 | 0.635902 → 0.635878 | 29.40% → 29.40% | 33.35% |

For Over 9.5, Brier delta −0.0000077 has day-bootstrap 95% interval [−0.0000319, +0.0000191]; the change is extremely small and compatible with either direction. In the signal's 50–60% bucket, n=793, prediction 54.67%, observed 58.76%. The full file includes home/away corner markets and calibration bins.

**xG and combined signals:** no xG-applicable examples are available, so neither xG alone nor a combined xG+SOT effect can be responsibly scored. A separate point-in-time source/archive is needed. Existing tests check bounded behavior; they are not accuracy validation.

## Recommended next steps — approval required

1. **As-of safety:** design a consistent cutoff for H2H and trends and characterize handling of erroneous future-dated records. Test live and overridden scan times, including same-day fixtures. This is a proposed production correction, not applied here.
2. **Source integrity:** review canonical identity, duplicated stage IDs and provider conflicts, establish source definitions/provenance and report rates per actual scan. Only then propose a non-destructive reconciliation policy; preserve raw archives and demonstrate output differences before approval.
3. **Point-in-time validation:** preserve immutable timestamped input snapshots and pre-match predictions, including source availability. Run a genuinely untouched forward or independent chronological holdout of exact production data and rules; test xG, SOT, off-target and combinations with matched samples and league breakdowns. No coefficient or flag change is justified by this retrospective study alone.
4. **Monitoring:** independently assess calibration and proper scores with sufficient samples and matched real, time-stamped odds; assess any selection or ROI results separately from probability quality. Keep experimental labels and conservative settlement protections.

No implementation is proposed as already approved. Await explicit approval before modifying production or deploying.
