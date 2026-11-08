# Offline synthetic replay and prospective-study checklist

## What is implemented

`replay.py` exercises the point-in-time snapshot reader end to end **only with invented synthetic data**. It is not connected to Mr2Odds' live scanner or existing production backtests, does not execute the production model, and is not a bookmaker eligibility or settlement engine. It cannot authenticate its caller, so labelling real or imported data as synthetic does not make that data valid for a study.

Run the fully self-contained demonstration:

```sh
PYTHONPATH=. python -m research.point_in_time.demo
PYTHONPATH=. python -m pytest -q tests/test_point_in_time_snapshots.py tests/test_synthetic_snapshot_replay.py
```

The demonstration generates two invented fixtures and their snapshots in a temporary directory, patches the clock **only inside the demo**, scores a fixed toy model, prints a synthetic-only report, and deletes the temporary files. The times in that demonstration do not prove real historical availability. With two deliberately constructed examples the toy Brier score is 0.2778 versus 0.2500 for the matched constant-0.5 baseline; these numbers have **no accuracy or business meaning**.

### Snapshot and replay gates

The synthetic convention uses `provider="synthetic"`, `origin="synthetic"`, and datasets `fixture`, `history`, `quotes`, and `result`. Real/provider-response and file-import labels are rejected. Each snapshot passes the snapshot reader's hash, schema, re-extraction and as-of checks. The local `available_at` witness must be no later than the same prediction cutoff. **Unanchored hashes remain rewritable**, and the local clock is not independently certified; the simulation is not valid provenance for real data.

- The cutoff is offset-aware and strictly before the fixture's explicit, offset-aware kickoff. The fixture and quote event must agree exactly on string event ID, competition ID, ordered home and away IDs, and kickoff instant; no name matching, inferred timezone, aliases, or cross-provider mapping is performed.
- History is a nonempty list of synthetic final regulation results. Each event's kickoff must precede its explicit finish, and finish must precede cutoff and be no later than its snapshot's callback-return timestamp. Missing or unparseable times/scores, duplicate event IDs, the target event in history, extra-time scores, or nonfinal records fail closed. This is a toy schema, not proof that real providers' result timestamps or periods are reliable.
- The one supported **invented** market is `total_goals`, specifier `2.5`, outcome `over` or `under`. Its market/outcome statuses must explicitly be toy strings `OPEN`/`ACTIVE`. The exact unrounded quote must meet an explicitly selected test policy: `app` 1.16 or `final_picks` 1.18. A missing quote, line, status or event is rejected; no synthetic double-chance prices are invented. These toy strings and market IDs are **not** asserted to be SportyBet semantics.
- The caller must specify a positive maximum local quote-observation age. The age is measured conservatively from the callback **start** to the prediction cutoff. This limits local observation age only; it does not establish provider update time, price freshness, availability, or execution. Arbitrarily old cached content could still be returned by a callback. Status in a response is also not proof of execution at a requested stake.
- Settlement is a separate snapshot, read only after prediction. It must match fixture identity and kickoff, contain an explicit finish after kickoff, be captured after that finish, and contain a final regulation score. Unknown, abandoned, postponed, invalid, or extra-time-only results do not become wins or losses. The toy result is `won` or `lost`, not actual execution, profit, settlement by a bookmaker, or ROI.

### Matched chronological toy evaluation

`run_chronological` accepts an ordered list of `ExerciseCase` objects and one explicit price policy and age limit for the run. Cutoff ties are allowed, but out-of-order cutoffs or duplicate target IDs fail. It constructs **all** predictions before reading any settlement snapshot; any invalid or unavailable case aborts the run rather than silently changing the sample. It then scores the same cases for both models using Brier and log loss. Each result includes snapshot IDs and receipt hashes for inspection. No bet, execution, yield or ROI is produced.

The fixed toy model is Laplace-smoothed historical over-2.5 frequency: `(number of over results + 1) / (number of history results + 2)`. Under uses its complement. The baseline is exactly 0.5. Neither is Mr2Odds' model; no parameters are fitted or selected here. **Caller-provided case selection, timestamps, code and rules are not independently preregistered or authenticated**. The demonstration is a software-flow test, not a prospective holdout or evidence for model quality. Results should not be interpreted beyond that purpose.

## What still needs to happen for a real evaluation

These are prerequisites, not actions performed by this prototype:

1. **Source and authorization.** Separately approve provider access and verify usage rights. Define trustworthy event IDs, competition and ordered teams, kickoff offsets, market/line/outcome mappings, status meanings, response-cache behavior, quote update timestamps, cancellation and regulation/extra-time settlement rules. Record and investigate disagreements; never assume an alias or inferred local timezone is proof.
2. **Secure capture.** Separately authorize an adapter, access-controlled storage, retention/redaction, clock monitoring and a durable external hash/signature anchor recorded at capture. Preserve raw source bytes and extraction versions. Verify the full data lineage and audit malformed, delayed and missing captures. The prototype's caller assertions, same-directory hashes and `origin` label are not source authentication.
3. **Freeze the prospective protocol before observing results.** Record model code revision, parameters, market definitions, competition universe, data source precedence, sample eligibility rules, prediction time and maximum observation age, comparison baselines, metrics, exclusions, and handling of voids or late corrections. Freeze a chronologically later holdout and prevent tuning or picking favorable cases after outcomes are known. A fixed calibration phase must precede that untouched holdout.
4. **Capture all inputs at decision time.** Reconstruct features, evidence and actual quoted prices strictly from verified snapshots available before each decision and before kickoff. Identify individual historical matches and ensure their final results and statistic definitions were available then; snapshot capture alone does not prove the provider's internal update time. Record unavailable inputs explicitly. A visible price or response status alone is not proof of freshness, executability or accepted stake.
5. **Evaluate on matched events.** Compare the actual frozen Mr2Odds version with clearly defined baselines on the identical eligible events, separated by market and league. Report selection and settlement coverage, exclusions and missingness; use proper scores such as Brier/log loss, calibration and uncertainty appropriate to dependent matches/time. Avoid treating a selected retrospective test period as an untouched holdout. Keep the 1.16 app and 1.18 Final Picks floors, with unrounded comparisons.
6. **Keep results independent.** Link later final regulation outcomes by verified identity, report voids and unresolved results, and retain corrections with their observation times. Do not turn missing or ambiguous outcomes into losses or wins. Only calculate financially meaningful ROI after separately establishing accepted/executable prices, stakes, settlement rules, fees and void treatment; otherwise report no ROI.

The existing five-match Premier League review and historical archive remain insufficient to establish historical source-time provenance or actual SportyBet prices. No live call, collection schedule, archive mutation, deployment or publication was performed here. Any such operational step still requires approval.
