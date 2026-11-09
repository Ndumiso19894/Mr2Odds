# ⚽ PlayReport

Automatic football analysis that runs **every 30 minutes** on GitHub Actions and publishes to the PlayReport
Android app and Telegram — no servers, no API keys, and it runs while your phone is in your pocket.

* **Coverage** — senior men's domestic leagues on the public live feed, worldwide (women's and youth competitions, cups and international tournaments are paused),
  priced by Sportybet South Africa; the 22 main European leagues additionally get corners, cards and referee models.
* **Data-first model** — every probability comes from football data only (goals, form, venue, league baseline →
  Dixon-Coles score matrix); bookmaker prices are a *separate comparison layer* (implied %, difference, EV, market xG)
  and never feed the model. Every statistic carries its sample size (Very small 1–4 … Very strong 40+), every match
  has a transparent data-quality assessment, the raw matches used, extreme results flagged and the model's own
  numbers ("why 1.35 goals?") in the app's **Data** tab and in `python audit.py HOME AWAY`. Missing data is N/A, never 0.
* **Goals shortlists** — Over 1.5 and Over 2.5, from the statistical model; experimental adjustments are disabled by default pending point-in-time validation.
* **High-probability selections** — singles with model probability ≥ 70 % (the de-margined Sportybet price must not
  contradict it), price ≥ 1.16, in the 1X2 / BTTS / total-goals overs / total and team corners overs markets. New ones are announced
  immediately (Telegram + app). Nothing is ever labelled "safe" or "guaranteed".
* **⭐ Bets of the day** — grouped card for 1X2, Over 1.5, Over 2.5, BTTS and corners; 1X2 and Over 2.5 require supporting form. One market per match; graded separately.
* **Trends, head-to-head and home/away form** on every match page; live scores, line-ups and match statistics for
  every match in play; squad values (Transfermarkt) for the main leagues.
* **Bet slip & tickets** in the app — build a multiple from priced selections, lock it, and PlayReport grades it from
  the scores and match statistics (private record on the phone).
* **Results archive** — every finished match on the live feed is kept with half-time score, corners, cards, shots and
  possession (`data/ls/` on the data branch), feeding the corners / cards models for every league over time.
* **Checked before publishing** — every run exports the app data to a staging directory and `verify.py` checks it
  (format, probabilities, prices, selection rules, day-card sections, detail files, evidence layer, no market
  contamination of model probabilities, ledger integrity) before it is
  promoted; a failed check keeps the previous publication and reports the problem on Telegram.
* **Season backfill** — up to two earlier seasons of every covered competition are archived from Livescore once,
  so head-to-head, form and league pages are complete outside football-data's leagues.
* **Delivery** — full report (Markdown + PDF) at 07:00 / 12:00 / 17:00 SAST on Telegram; app data on the `data`
  branch (`data/app/latest.json`, per-match files, 60-day history); a weekly performance digest on Mondays.

The code lives on `main`; all generated state (reports, ledgers, app data, the Livescore archive) lives on the
orphan `data` branch, which is force-pushed by every run so the history stays small.

Statistical information, not betting advice. 18+.

## 🎾 Tennis Scanner (paused)

Tennis scanning and Telegram reports are paused; the workflow is disabled and has no schedule. Historical data and existing tickets are retained. To resume, restore the schedule in `.github/workflows/tennis-scan.yml` and enable the workflow in GitHub Actions.

`tennis/` is an independent package built beside the football scanner — own data (`data/tennis/`, `data/app/tennis/`
on the orphan `tennis-data` branch), own model, tracker (`data/tennis/tracker.csv`), reports (`reports/tennis/`),
workflow (`.github/workflows/tennis-scan.yml`, four runs a day) and tests (`tennis/tests/`). It imports nothing from
the football model code; the only shared piece is the generic Markdown → PDF helper. See `docs/TENNIS_AUDIT.md`
(architecture, sources, limitations) and `tennis/BACKTEST_RESULTS.md` (walk-forward validation and calibration).

* **Coverage** — ATP / WTA main tours and ATP/WTA Challengers, singles only (no ITF, team events or doubles).
* **Data** — Jeff Sackmann's historical match files (tennisabstract.com, CC BY-NC-SA 4.0, June 2026 snapshot via the
  Aneeshers archive mirror; 288,040 matches 2005–2026) for ratings, form, serve/return statistics; Livescore for
  results after the snapshot (no statistics — serve/return traits from the archive are marked stale when old);
  Sportybet prices as a *comparison layer only*. Anything missing is N/A, never zero.
* **Model** — Elo (overall + surface blend, sample-size K schedule) → set probability → explicit best-of-3 / best-of-5
  match probability (2-0 / 2-1 / 3-0 / 3-1 / 3-2 each way) → Markov point/game chain for total games, player games
  and game handicap. Parameters chosen on 2012–2018, evaluated on 2019–2026 (walk-forward, no look-ahead).
* **Output** — per match: MODEL PROBABILITY, FAIR ODDS, BOOKMAKER ODDS, MARKET IMPLIED, EDGE and DATA QUALITY
  (a 14-check score of the evidence, not a win probability). Reports at 08:00 / 18:00 SAST on Telegram labelled
  "🎾 TENNIS SCANNER". No parlays, no tennis + football combinations.
* **Selections of the day** — one preferred market per match (`tennis/markets.py::select`): the highest model
  probability ≥ 60 % among Sportybet-priced markets (price ≥ 1.16) whose margin-free implied probability is ≥ 45 %
  (the market must not contradict the pick), data quality ≥ 60, both players ≥ 30 rated matches, no low-confidence
  game data, model − market ≤ 20 pp. **Strong** = model ≥ 70 % and market ≥ 50 %. Ranked by probability, never by
  edge. Grouped by market (Match winner / Total games / Player games / Game handicap) in `latest.json`
  (`selections`, `sections`, `strong`), the reports and Telegram.
* **Tracker** — `data/tennis/tracker.csv` grades four groups separately (`kind` = day / strong / highlight /
  favourite): hit rate vs average model probability and flat-stake units at the recorded price. Day files
  `data/app/tennis/days/<day>.json` keep every analysed match with its result and settlement; `days/index.json` lists them.
* **App** — sport switch (⚽ Football | 🎾 Tennis) at the top of every tab in `tennis.js`; the football views are
  wrapped, not modified. Tennis Home / Bets / Live / Matches / Days and a match page with Overview / Markets /
  Stats / Data (sample labels, last 10 matches with raw scores, H2H context and eligible model subset, quality checks, identity, inputs).
  Smoke test: `android/tennis_ui_test.py`.

### Android releases to Telegram

Each successful Android build publishes its APK on GitHub and then uploads that same APK as a document
in Telegram. Configure the existing repository Actions secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
(the same ones used for scanner reports); the bot must be able to send documents to that chat. If delivery
fails, the GitHub release is still available and the Telegram job fails visibly. After correcting the problem,
use **Re-run failed jobs** on the build workflow to retry delivery without rebuilding or republishing the release.
Telegram's hosted Bot API has a 50 MB document limit.

### Workbook comparison

The match Sheet tab reproduces the supplied workbook's V1 formulas as a separate comparison. Venue rates use the scanner's unweighted team samples (overall sample when the venue split is empty); scanner league baselines are time-weighted and shrunk and may fall back to global data. The V4/V5 comparison uses the workbook's default V3/V4 weights and dashboard rules, is uncalibrated, and requires six recent results plus at least three current-competition observations for each xG/xGA and shots-on-target input. PPG and other inputs use the available capped sample and inferred season, not necessarily a complete season. Missing inputs leave V4 unavailable. Bookmaker implied probabilities are raw 1/odds, not de-margined. The CSV exports values, not spreadsheet formulas. This comparison never changes the production recommendations or the original workbook.

### Optional head-to-head context

Fixtures are not excluded for missing or limited head-to-head history. When all existing ranking criteria tie, a fixture with at least three available, identifiable prior non-friendly meetings may be placed first; this never changes a probability, price, quality requirement or selection threshold. Meetings from any competition except friendlies count, with no age limit. Counts describe the available archive, not proof that no other matches occurred. Same-day, future, ambiguous or incomplete records are not used. Livescore uses exact team/event IDs and football-data uses exact country and team names; no unreviewed cross-provider identities are inferred.

This tie-break is separate from the model's narrower, same-competition recent-H2H adjustment. It is not evidence that such fixtures are more predictable, and its effect has not been prospectively validated. Other existing data, competition and price safeguards continue to apply.

### Recent-form goal model

The live model adds shrunk last-5, previous-5 and venue-5 form and scoring frequencies to longer-history, league-normalised ratings. Eligible same-competition meetings with exact Livescore IDs can have a small H2H effect; ambiguous team history falls back to the baseline. Squad availability is not used. The exploratory retrospective was mixed and is not prospective validation or evidence of profitability. Details: [recent-form study](research/recent_form/README.md).

Set the GitHub Actions repository variable `RECENT_FORM_ENABLED` to `0` (or set `RECENT_FORM_ENABLED=0` in a local scanner environment) to restore the baseline on the next scan. Remove it or set it to `1` to re-enable the overlay. Per-fixture method details report applied, fallback or disabled status, and app metadata reports aggregate coverage. The recent-form and experimental xG/shots modes cannot be enabled together; a conflicting configuration stops the scan before publication.

### Experimental model signals and markets

Provisional xG/xGA, shots-on-target and genuinely reported off-target-shot adjustments are **disabled by default** pending point-in-time chronological validation. `RECENT_FORM_ENABLED=0 EXPERIMENTAL_MODEL_SIGNALS=1` explicitly enables them for labelled research only. Team/total booking recommendations and grading are withheld because current card-count data is not verified as equivalent to SportyBet bookings. See [model signal and market limitations](docs/MODEL_SIGNALS.md).

### Lineup research pilot

An opt-in, source-neutral pilot compares confirmed starting XIs with recent collected lineups in England's Premier League and Germany's Bundesliga. It does not change model probabilities. No automatic provider is connected; authorized input and explicit permission for public-state storage are required. See [pilot setup and limitations](docs/LINEUP_PILOT.md).
