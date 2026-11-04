# Facebook daily selections

The `Facebook daily selections` Actions workflow posts one portrait PNG to the configured Facebook Page. Each card has the supplied Mr 2 Odds logo, 5–8 distinct matches, both club crests, selection and SportyBet decimal price. The post text is just a short caption and hashtags. The workflow selects the app's strict shortlist, rechecking the fixture's own latest selection and price, current competition policy, quality, disagreement, price floor and kickoff. It never fills a card with extra or unpriced selections.

## Setup

Create the GitHub Actions repository secrets `FACEBOOK_PAGE_ACCESS_TOKEN` and `FACEBOOK_PAGE_ID` (numeric Page ID). Use a Page access token, or an authorized user access token that can retrieve a token for that specific Page. The user token must have the necessary Facebook Page listing and posting permissions; the app must be in an appropriate mode. Derived Page tokens are kept only in memory. No token or Page ID is stored in the repository or printed to logs. Tokens can be revoked or invalidated, so monitor the workflow even if a token has no scheduled expiry.

The schedule is 07:00 South African time. Following successful football scans after 07:00, the scan workflow also triggers the Facebook workflow as a fallback for delayed GitHub schedules. A manual run is available under Actions → Facebook daily selections → Run workflow. The current snapshot must be no more than 90 minutes old. Only upcoming fixtures today qualify. If there are fewer than five with usable crests for both teams, nothing is posted; the next scan can try again. It produces at most one card per South African day.

Club badge references already published in the app are tried first. If a badge is missing or fails to load, the workflow searches Wikipedia for an unambiguous exact club name and uses a page thumbnail only if its file name identifies it as a crest or logo. It never substitutes initials, photographs or a guessed club. The operator must ensure they have the necessary rights to use and publish the selected club crests; club trademarks and image rights may apply.

## Duplicate protection and recovery

All triggers share a concurrency group. Before the Facebook upload, the workflow stores a `facebook-post-YYYY-MM-DD` Actions artifact containing the exact image and a manifest. Any later attempt that day sees the claim and skips posting. The claim is deliberately created **before** the external API request: if Facebook accepted a photo but the network timed out, automatic retry could otherwise duplicate the post.

If the upload job fails after claiming, first inspect the Page to establish whether the photo appeared. If it did not and a retry is wanted, delete that day's claim artifact from the Actions run and manually run the workflow again. Never remove the claim before checking the Page. Failures before the claim, including missing secrets or too few eligible matches, are safe to retry. The image uses quoted prices from the last scan, which can change before a bet is placed.
