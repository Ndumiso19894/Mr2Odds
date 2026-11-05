# Facebook selections and results

The separate daily Bet Advisor reel and Telegram video are documented in [REEL_AUTOMATION.md](REEL_AUTOMATION.md).

All times are South African time (SAST, UTC+2):

| Time | Post |
| --- | --- |
| 07:00 | Five different eligible selections |
| 08:00 | One post with two images covering the previous day's published selection cards |
| 12:00 | Five different eligible selections |
| 17:00 | Five different eligible selections |

The selection and results images are white-background 1080 × 1920 (9:16) cards using the Mr 2 Odds logo, a small 18+ badge, and both verified club crests. Selection cards show country, league, kickoff (SAST), selection and the quoted SportyBet price. The caption says `Today's football picks - <date>`, asks about a fixture, invites viewers to follow and includes a responsible-betting reminder; hashtags are solely for teams actually pictured. Results captions invite discussion without suggesting a result was won, and the settlement logic still shows losses and pending results honestly. Five matches per selection card helps reserve distinct matches for the later slots and keeps the two-image recap legible. If fewer than five new, eligible fixtures with two real crests exist, that slot is skipped. Never fabricate fixtures, odds or crests to fill a slot. The current snapshot must be no more than 90 minutes old. Fixtures without known kickoff, country or league are skipped.

Senior men's UEFA competitions are in scope when the source explicitly identifies UEFA or the European Champions, Europa or Conference League. Other cups, non-UEFA international competitions, women's and youth competitions, and tennis remain paused. Selections still must pass the existing shortlist, probability, price-floor, quality and disagreement checks.

## Results

The recap is based on the exact selection-card manifests recorded before each Facebook upload and includes only claims whose upload step was confirmed successful. Results show every distinct recorded selection, final scores when available, and won/lost only when the required statistics are available. Missing scores or corner statistics stay pending. UEFA market outcomes remain pending when the archive cannot establish the regulation-time score, rather than guessing about extra time. Results also identify the originating posting slot. Older card manifests did not save selections or odds: those entries show the final score only and explicitly say the selection was not recorded. Where multiple older corrected pictures repeated the same unrecorded fixture, it appears once.

Both images are attached to a single Page post. If a previous upload is unconfirmed, an archive or crest is unavailable, or the results cannot fit clearly on two images, the results post fails safely instead of omitting or inventing entries. A day with no previous posts has no results post. The recap can contain pending or postponed matches; check the original bookmaker for official settlement.

## Setup

Create GitHub Actions repository secrets `FACEBOOK_PAGE_ACCESS_TOKEN` and `FACEBOOK_PAGE_ID` (numeric Page ID). Use a Page access token, or an authorized user access token that can retrieve a token for that specific Page. The user token must have the required Facebook Page listing and posting permissions. Derived Page tokens are kept only in memory. Tokens can be revoked, so monitor the workflow even if a token has no scheduled expiry.

GitHub's scheduled events may be delayed. After successful scans, the scan workflow also dispatches the Facebook workflow during the four posting hours as a fallback. A manual run within a posting hour can trigger that hour's slot. Runs outside those hours do not post. The schedule is best effort, not a guarantee of exact minute delivery.

Club badge references already published in the app are tried first. If a badge is missing or fails to load, the workflow searches Wikipedia for an unambiguous exact club name and uses a page thumbnail only if its filename identifies it as a crest or logo. It never substitutes initials, photographs or a guessed club. The operator must ensure they have the necessary rights to use and publish the selected club crests; club trademarks and image rights may apply.

## Duplicate protection and recovery

All triggers share a concurrency group. Before the Facebook upload, the workflow stores an Actions artifact containing the exact image(s) and manifest. A claim is unique to each date and slot (`facebook-post-YYYY-MM-DD-07`, `-12` or `-17`, or `facebook-results-YYYY-MM-DD`). Every previous selection claim for that day—including claims from the earlier single-post automation—is read before a new selection card is prepared; its fixtures are excluded even if the upload later failed. The claims are deliberately created **before** any Facebook write: an accepted post with a network timeout must not be automatically repeated. The previous 35 days of claims are retained.

If an upload job fails after claiming, first inspect the Page to establish whether the post appeared; the following morning's results will not silently treat an unconfirmed upload as successful. If it did not and a retry is wanted, remove the specific slot's claim from the Actions run only after checking the Page, then manually run during that slot's posting hour. Never remove a claim after an ambiguous result without verifying the Page. Failures before the claim, including missing secrets or too few eligible matches, are safe to retry. The image uses prices from the latest scan, which can change before a bet is placed.

## Measuring growth

These changes are a test, not a guarantee of follower growth. Over the next two weeks, use Meta Business Suite's Insights to compare each post's reach, engagement and follows, and each reel's watch time or retention where available. Compare the 07:00, 12:00 and 17:00 selection slots separately and note which fixtures and formats prompt real discussion. Record the period and posting dates so they can be compared fairly; reporting and available metrics may vary by Page. Nothing in this automation reads Page Insights or changes the schedule automatically. Any posting-frequency experiment should be approved by the Page owner first.
