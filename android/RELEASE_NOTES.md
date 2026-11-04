## Markets and experimental model signals
- 1X2, BTTS and team corners can be shortlisted when the existing price and screening rules are met. Booking recommendations and ticket grading remain paused until card data matches the bookmaker’s booking rules.
- Experimental xG/xGA and shots adjustments are enabled where sufficient inputs exist, but are not yet backtested; missing inputs are not guessed. No improved accuracy is claimed.

## Line-up research pilot
- The Line-ups tab can show regular starters and changes from a rights-cleared, operator-supplied confirmed XI in two pilot leagues. It is context only and does not alter predictions. No automatic lineup source is configured yet.

## Spreadsheet comparison
- Compare the supplied workbook's V1 and experimental V4/V5 dashboard with Mr 2 Odds for each match when inputs are available. No recommendation model or spreadsheet file is changed.

## Recommendation and ticket reliability
- The scanner's current recommendation families and minimum price now match the app. Earlier records are retained.
- Background ticket notifications wait for a definitive outcome and use the same football selection codes as the app; existing tennis tickets can check results without resuming tennis scans.
- The guide now describes the probability model that is actually running; no unverified probability formula has been substituted.

## Competition pause
- New analysis and live lists focus on senior men’s domestic leagues; women’s and youth competitions, cups and international tournaments are paused.
- Tennis scanning and notifications are paused. Historical records and existing tickets are retained.

## Android branding, release delivery and recommendation fixes
- The launcher, splash screen and in-app logo now use the new Mr 2 Odds artwork.
- Future Android APK releases are sent to the configured Telegram chat.
- Home collections now receive the published market selections they need, including the exact model probability for the 80% filter.
- The Shortlist and Sequences now use a published, data-checked list of today's upcoming selections. The advisor displays only today's card.
- Today's high-probability signals are no longer displaced by matches weeks away. Empty collections still mean no selection met the stated rules.

## What's new in Mr 2 Odds 1.8.7 — 🧭 Back button fixed + always-current tips
- ⬅️ **Back now navigates — it only closes the app at Home** — on match, day, league, team, advisor or any other screen, the back button steps you back through the app the way you'd expect. It exits only when you're already on the home screen.
- 🕒 **You can see exactly which analysis you're looking at** — the small status line under the header shows the publication time of the data on screen, and turns amber with a warning if the publication is more than 3 hours old.
- 🔄 **Self-healing data** — if the copy stored on your phone is more than 2 hours old, the app now forces a fresh download when it opens, so the Bet Advisor's picks and the strong-markets list are never silently stuck on an older day.
- 🧊 **Model untouched** — identical input, identical numbers; this release is navigation and data freshness only.

## What's new in Mr 2 Odds 1.8 — 🐾 Full integration: offline cache, live scores, advisor, tickets
- 🐾 **Rebranded to Mr 2 Odds** — the name, the dark-green theme and the football-intelligence look you know from the shared build, now running on the new worldwide pipeline.
- 📡 **Offline resource cache** — the app now keeps a phone-side cache of every analysis file (SQLite-backed, 32 MB, conditional revalidation with ETags). It opens instantly from cache and refreshes in the background every 15 minutes, even with the app closed.
- ⚽ **Live scores & goal alerts** — tracked matches (bets of the day, high-probability selections, shortlist and your tickets) are followed live: kick-off reminders, goal notifications with the scorer, optional half-time and full-time.
- 🎟️ **Ticket settlement** — save your locked tickets on the bets screen; when a leg's match finishes the app settles it from the official score and tells you whether the ticket won or lost.
- 🧠 **Bet Advisor with a live record** — the advisor tab now carries the tracker's settled history: hit rate, flat-stake ROI, per-market record and the selection ledger, plus the day's card (strongest signals, biggest model-vs-market edges, high-confidence list) and the daily briefing.
- 📈 **Strong markets for the day** — a dedicated home section for the model's ≥78% Over 1.5 goals and total corners that carry a real Sportybet price.
- 🔔 **Notification channels** — separate channels (analysis, goals, selections, kick-offs, half/full-time, tennis, tickets, updates) with distinct sounds; each notification opens exactly where you need to be.
- 🧊 **Model untouched** — identical input, identical numbers. Everything new is data plumbing, caching and presentation.

## What's new in PlayReport 1.6.2x — 📅 60-day fixture coverage + Sportybet deep links
- 📅 **Fixtures covered up to 60 days ahead, in every league** — the scanner now discovers and analyses matches across the next 60 days worldwide (not just today), so the model gathers form, statistics and context early and every match is analysed well before kick-off. The Leagues tab's fixture lists span the same window; the Matches tab still shows today's games as before.
- 🎫 **PlayReport tickets meet Sportybet** — every priced match, slip leg and ticket leg now has an **SB** link that opens the match directly in Sportybet (their live odds and slip), and tickets can be copied to the clipboard in one tap.
- 🧾 **Sportybet booking codes** — paste any Sportybet booking code (SportyBet's daily picks, Telegram groups, tipsters) on the slip screen and PlayReport loads it straight into Sportybet for you.
- 🎯 **Bets of the day = Sportybet markets** — the card only ever contains markets Sportybet actually prices (≥ 1.30), and each bet now labels its price as Sportybet's own.
- 🧊 **Model untouched** — same input, same numbers; this is coverage, navigation and presentation.

## What's new in PlayReport 1.6.2x — 📊 Full tables, team search, sort options, zero dead-ends
- 🔎 **Search now finds teams, not just leagues** — type any club in the Leagues search and it lists matching teams worldwide (with country and competition); the Matches search box finds teams, leagues and fixtures. Tap a team to open its profile.
- 📊 **Standings are now complete** — P · W-D-L · **GF** · **GA** · GD · Pts · Form, with **sort options** (points, goal difference, goals for, name) and dedicated **Home record** and **Away record** tables under the main table. Team pages show GF/GA in the league table too.
- 🗂️ **Sort options in the Leagues tab** — browse by Country (default), Name, Next fixture, Most played or Most teams.
- 🔗 **No more "Could not load this day"** — in the League Center, results older than the on-phone day archive (the last analysed days) simply show the final score instead of opening a missing page; recent results open the Match Center or the full day archive as before.
- ✨ **Cleaner, more readable tables everywhere** — aligned tabular numerals, wide tables scroll sideways on small screens, trend windows never clip.
- 🧊 **Model untouched** — presentation and data-navigation only; same input, same numbers.

## What's new in PlayReport 1.9 — 🌍 Worldwide coverage: 300+ competitions, match news, league trends
- 🌍 **Every competition on the public feed is now tracked and labelled** — 300+ competitions across 80 countries. Each league page shows its **data-quality status** from the scanner's coverage registry: active, model-eligible, insufficient history, provider publishes no stats, finished or data error. Accuracy first — thin leagues are labelled, never forced, and never filled with guesses.
- 📋 **Match Center grew**: every match now has **Form** (both clubs' last 10, all competitions, plus each club's recent home/away run), **Table** (full standings with both clubs highlighted, and their home/away records) and **News** — recent headlines about *this fixture* and each team (previews, line-ups, injury news), from Google News with source and publication date. Tap any headline to open the original article.
- 📈 **League Center grew**: every competition now has **Trends** (average goals, Over 0.5/1.5/2.5/3.5, BTTS, home/draw/away, home & away goals, clean sheets, failed to score, corners & cards — over Last 5/10/20, Season and Previous season, with a "last 10 vs season" change line), **Teams** (tap a club for its profile) and **News** about the competition and its leading teams.
- 🔎 **Global search**: the Matches search box now also finds **leagues and clubs**, not just today's fixtures.
- ⏱️ **Team pages** add a **Trends** tab: last 5/10/20, season and previous season — points per game, goals for/against, overs, BTTS, clean sheets, failed to score, scored/conceded in N.
- ✅ **Data quality everywhere**: every trend window needs a real minimum of matches — thinner windows show **N/A**, never 0. Corners/cards use only the matches whose statistics the provider publishes. Standings are the current season's table (backfilled earlier seasons live in Results and Trends, never mixed into the table).
- 🧊 **The prediction model is frozen**: same input, same numbers — verified by hash against the pre-upgrade baseline. News is **information only**: it is shown for your reference and is never read by the model, the market comparison or the selections. One bad league or one failed news query can no longer stop the worldwide scan; all data is cached on your phone with short refresh windows.

## What's new in PlayReport 1.8 — 🏆 Leagues: worldwide tables, results & fixtures
- New **Leagues** tab (bottom bar): every football competition on the public live feed, worldwide — 270+ leagues and cups, grouped by country, with a search box for league or country.
- Open any league for **Standings** (points, goal difference, last-five form), **Results** (the last 40 finished matches with half-time scores) and **Fixtures** (the next two days), grouped by day. Cup and knockout competitions show results and fixtures — no table, because a bracket is not a table.
- The archive now covers the big leagues continuously: the Premier League, LaLiga, Serie A, Bundesliga, Ligue 1, Championship, Primeira Liga, the Süper Lig, the Scottish Premiership and 40+ other top leagues are pre-loaded with the full current season plus two earlier seasons of results — and the South Africa Premiership (Premiership) is in there too, updated on every matchday.
- Everything updates automatically with the 30-minute scan; each page shows how fresh the data is. Knockout rounds and smaller leagues appear as they play, and stay in the archive afterwards.
- Data comes only from the public live-score feed's own archive — missing pieces stay blank (N/A), never filled with guesses. The betting model, its inputs and every published probability are untouched; this is a read-only browser on top of the world data the app already collects.

## What's new in PlayReport 1.7 — bet slip for both sports, favourites, new sounds
- 🎾 **Tennis bet slip**: tap **+** next to any priced tennis selection (Selections, Strong, Model > market, and every market on a match page) to add it to the same slip as football. One leg per tennis match (the newer pick replaces the earlier one); the slip shows a "🎾 tennis" tag on each leg. Tickets follow the matches and settle automatically: winner legs from the result, game markets from the final set scores — retirements void the game legs, exactly like the tennis tracker.
- ⭐ **Tennis favourites**: star any tennis match (match row or match page). Your matches appear on the tennis home screen, a Favourites filter lives on the Matches tab, and the app alerts you in the background when a favourite finishes (with the set score) plus kick-off reminders.
- ⭐ **Bets of the day, rebuilt as six blocks**: 1 · Goals (Over 1.5 & team goals) — 2 · Over 2.5 — 3 · BTTS — 4 · 1X2 — 5 · Corners — 6 · Bookings. Each block holds at most 7 of the strongest qualifying bets; if only one or two meet the bar, only those are listed, and an empty block disappears. No forced picks — the thresholds are unchanged.
- 🎾 **Tennis Selections of the day, the same idea**: three blocks in order — Winner, Player games, Total games — max 7 each, never padded.
- 🔊 **New notification sounds**: the goal alert is now a real crowd eruption with the stadium horn; tennis results get their own "serve & bounce" sound; locked tickets get a short fanfare when they settle (won or lost). Settings → Notification sounds previews every one, plus the referee whistle.
- ✨ **Polish pass**: cleaner layout on small screens (2×2 hero numbers, compact tables), stronger number hierarchy in the slip and day card, refined buttons and spacing. The model, probabilities, selections and data are untouched.

## What's new in PlayReport 1.6 — new look: dark-first, cleaner, more readable
- A visual redesign only. The model, the probabilities, the selections, the data sources and every screen's content are exactly as before — nothing was added or removed; the app simply looks and reads better.
- Dark theme first (System / Light / Dark still under Settings → Appearance): a calm dark background, slightly lighter cards with thin borders instead of heavy shadows and gradients, one blue accent, and green / amber / red kept strictly for positive / caution / negative numbers.
- Clearer hierarchy: large key numbers with small labels, uppercase section captions, tighter and more consistent spacing, corner radius and iconography; tables and statistics laid out like an analytics terminal with subtle dividers.
- Home screen header is now a flat status strip — live status, update time and the day's key counts at a glance. The tennis section uses the same system with its green identity.
- Bottom navigation with a clear active indicator; pressed states and short, subtle screen transitions; nothing that slows the app down.
- New app icon: the roaring black panther bursting through a football / tennis ball, on the PlayReport blue. The splash screen matches the dark theme (no white flash on launch).

## What's new in PlayReport 1.6 — 🎾 Tennis on the home screen, selections of the day
- Sport switch at the top of every tab (⚽ Football 13 | 🎾 Tennis 34, with today's counts) — tennis is no longer hidden in the menu. Football screens are unchanged; the app remembers the sport you were on.
- A one-time card on the home screen points to the new placement after the update.
- Tennis is also on the football home screen itself: a "Tennis · selections of the day" strip right under the header numbers and the tennis card (grouped by market) right after Bets of the day — tap a row for the tennis match page, or "Open tennis" for the full section.
- Tennis Home: the day's selections grouped by market (Match winner / Total games / Player games / Game handicap) — one preferred market per match, ranked by model probability; strong markets; model-above-market flags; next matches; the tennis record.
- Selection rules (shown in the app): Sportybet price ≥ 1.30, model ≥ 60%, the bookmaker's margin-free probability ≥ 45% (it must not contradict the pick), data quality ≥ 60%, both players with 30+ rated matches, no low-confidence game data. STRONG = model ≥ 70% and market ≥ 50%. Not a "safe bet" list — a 70% selection loses three times in ten.
- Tennis Bets tab: selections, strong markets, model > market, all priced matches — with market filters. Live tab: ATP/WTA/Challenger scores from Livescore with set-by-set games. Matches tab with search. Days tab: every analysed day kept with results and how each selection settled.
- Match page rebuilt like the football one — Overview / Markets / Stats / Data: the selection with its reason and MODEL / FAIR / SPORTYBET / IMPLIED / EDGE; every market grouped with the preferred one flagged; side-by-side stats with sample labels (rating, last known ranking, form 5/10/20, surface form, serve & return, match profile); each player's last 10 matches with tournament, round, opponent, score and the model's pre-match expectation; head-to-head (context only); data-quality checks, player identity matching, model inputs and sources.
- Tennis tracker now grades four groups separately — selections of the day, strong markets, model-above-market flags and the rating favourite — with hit rate vs average model probability and flat-stake units. Reports and Telegram carry the same "Selections of the day" and "Strong markets" sections.

## What's new in PlayReport 1.6 — 🎾 Tennis (separate section, first release)
- New Tennis section in the menu (⋮ → 🎾 Tennis). It is completely separate from football: its own data, model, tracker and reports. Nothing in the football pages, selections or trackers has changed.
- Coverage: ATP, WTA and Challenger singles in the next 36 hours. Every match shows MODEL PROBABILITY for both players (they always add to 100%), the set-score probabilities (2-0 / 2-1, or 3-0 / 3-1 / 3-2 at Grand Slams), expected total games and a DATA QUALITY score with its 14 checks.
- Markets: match winner, total games, player games and game handicap — each with MODEL, FAIR ODDS, Sportybet ODDS, MARKET IMPLIED and EDGE. Bookmaker prices are a comparison only and never change a model probability. No tennis parlays.
- Highlights list model-above-market disagreements that pass the publication rules (price ≥ 1.30, model ≥ 55%, edge 5–20 pp, data quality ≥ 60, both players with 30+ rated matches). They are flags with evidence, not recommendations — the tennis tracker will show how they settle.
- Player evidence on every match: form (last 5 / 10 / 20 overall and on the surface), serve and return statistics with their sample size and date (marked stale when old), match profile (average games, straight-sets and deciding-set shares, tiebreaks). Missing statistics are shown as N/A, never as zero.
- Model validated on 288,000 matches (2005–2026) walk-forward with no look-ahead; details and calibration tables in tennis/BACKTEST_RESULTS.md.

## What's new in PlayReport 1.6 — results that stay, sounds you recognise
- Finished matches keep their final score, half-time score, match statistics (possession, shots, on target, corners, fouls, cards) and the goal timeline with scorers — also after they leave the live list. The Matches tab shows how many matches finished earlier today with a link to their results.
- Match statistics and goals are now collected for every competition Livescore publishes them for (before, only the big leagues playing that day were covered), so far more matches in the Days archive have full tables.
- Older matches (past 14 days) open an archive page from the day record: score, statistics, goals, the model's numbers at kick-off and how the bets settled. Nothing is lost when the detailed analysis is retired.
- Each notification type has its own short sound — goal, kick-off, half/full time, new selection, report published. Preview them under Settings → Notification sounds, or open the Android setting for any alert type from there.
- Editor card now shows Ndumiso Msani's photo.
- Small fixes: day-archive rows are always openable, "FT" shown consistently, fouls added to the statistics table.

## What's new in PlayReport 1.5 — data-first engine
- Every probability now comes from football data only. Bookmaker prices are shown next to the model as a separate comparison (implied %, difference in points, EV) and never change a model probability.
- Model xG and Market xG are shown separately on every match page — never blended.
- New Data tab on every match: data quality (High / Medium / Low with the reasons), the sample behind each team (matches, competitions, season, home/away, friendlies), home/away splits as plain historical frequencies, extreme results flagged, the raw matches used, head-to-head evidence strength, the model's own numbers ("why 1.35 goals?") and automatic checks and warnings.
- Every statistic carries its sample size: Very small (1–4), Small (5–9), Moderate (10–19), Strong (20–39), Very strong (40+). Historical frequency ("scored in 9 of 10") is always labelled apart from model probability and market implied.
- Markets tab: Model / Market / Diff / Price · EV columns; corners and cards show LOW DATA CONFIDENCE when the sample is thin.
- "Safest bets" are now called high-probability selections — a 75% probability still loses one time in four. Each one shows its data quality.
- Model update validated on 52,000 matches: team strength is shrunk less than goal tempo, which improves home/away win, Over 1.5 and Over 2.5 accuracy (details in backtest/RESULTS.md).
- CSV downloads include the data-quality assessment, the raw matches used and the model/market comparison.
