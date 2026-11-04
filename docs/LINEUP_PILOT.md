# Lineup research pilot

This pilot is **context only**. It does not alter predictions, shortlists, odds, tickets, scans or the workbook. It adds no external requests. Its initial scope is the scanner's `E0` (English Premier League) and `D1` (German Bundesliga) divisions; all other competitions remain exactly as before. Coverage has **not yet been established**. World-feed fixtures with different division codes are not included even if their names appear similar. South African coverage is not assumed.

## Source and rights: required before enabling

The existing LiveScore app display uses an unofficial feed; its [terms](https://www.livescore.com/en/about-us/terms-and-conditions.html) prohibit data mining. The pilot does **not** collect it. Another candidate, [Highlightly](https://highlightly.net/terms/), prohibits use of its data to support betting and restricts redistribution; it is **not** connected. No source has yet been validated for this project.

Select a source and confirm its terms allow this specific betting-analysis use, collection, storage, and publication before importing anything. This repository's `data` branch is public: the raw lineup archive and frozen evaluation records would be publicly retrievable. Do not import licensed or private material that cannot be published there. Do not put provider API keys in input, Git, or repository variables; this pilot makes no API calls.

## How the pilot works

* The operator supplies complete, **confirmed** starting XIs from an authorized source. Stable source-specific team, match and player IDs are required; there is no name-based matching of players. Both teams need exactly 11 unique players. Names and fixture identifiers must match the app precisely; the operator is responsible for verifying the source and match identity.
* Every import is stamped by the system clock on receipt. An input-provided observation time is ignored. Re-imports of unchanged data do not refresh the timestamp. Corrections create additional observations. Old match lineups imported today may build history for later matches, but are never represented as having been known before their own kickoff.
* For each team, the pilot considers at most its 10 most recent collected previous matches that were already observed and are at least two hours past kickoff as of the evaluation time. It requires three distinct prior lineups. A player starting at least 60% of this sample is described as a **regular starter**; this is a descriptive rule, not a player-quality score or a forecast.
* When a confirmed lineup was captured before kickoff, it reports regulars **not starting in that captured XI**. It never infers injury, suspension, or unavailability. A lineup first captured after kickoff is not used as a pre-match target. Identity ambiguity across sources is left unresolved rather than guessed.
* For eligible pre-match observations, the scanner freezes model probabilities and the lineup context with real observation times in `data/lineup-pilot/evaluation.json`. The original snapshot archive is `data/lineup-pilot/archive.json`. Existing results can be joined later by fixture ID; this does not itself implement a challenger model, result evaluation or a claim of better accuracy.
* Lineup observations and frozen records are retained across scans. If input or archive is invalid, the pilot is unavailable for that scan; normal analysis and publication continue.

## Input format

Input is a JSON **array**, each item with these fields. This is an abbreviated illustration, **not runnable JSON**: both `starting` arrays must contain exactly 11 entries with distinct nonempty string IDs.

```json
[
  {
    "source": "Name of authorized source",
    "source_match_id": "provider-match-id",
    "fixture_id": "2026-11-14|England|Home Club|Away Club",
    "country": "England",
    "div": "E0",
    "kickoff": "2026-11-14T15:00:00+02:00",
    "status": "confirmed",
    "home": {"id": "provider-team-id-home", "name": "Home Club", "starting": [{"id": "player-id", "name": "Player Name"}]},
    "away": {"id": "provider-team-id-away", "name": "Away Club", "starting": [{"id": "player-id", "name": "Player Name"}]}
  }
]
```

`fixture_id` uses the kickoff's **SAST** date and the exact country/team names from the app (`YYYY-MM-DD|country|home|away`). `kickoff` must include a UTC offset. Use the same source name and stable provider IDs across observations. The scanner displays the snapshot only when division, fixture ID and kickoff match its fixture; it will not guess a near match. Input fields such as an existing `observed_at` never override the import time.

## Supplying a snapshot

After confirming rights, either:

1. Set GitHub Actions repository variable `LINEUP_PILOT_INPUT` to the JSON array and `LINEUP_PILOT_RIGHTS_CONFIRMED` to `true`. The next successful scan imports it using that scan's real collection time. Replace the input variable as new records arrive. Empty input or missing rights confirmation makes no requests and imports nothing. The GitHub variable has size limits; keep batches small.
2. For local use, run `python lineup_pilot.py snapshots.json --archive "$STATE_DIR/data/lineup-pilot/archive.json" --rights-confirmed` against your local state. The file is only published to the app when it is part of the state that a scanner run actually publishes.

Imports are transactional per batch: one invalid record rejects the whole batch and leaves the existing archive intact. Inspect workflow logs for the number of imported snapshots and frozen baselines. No real source, account or data are preconfigured by this change.
