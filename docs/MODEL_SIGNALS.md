# Provisional model signals and restored markets

**Enabled by default at the user’s request; not yet validated.** Set `EXPERIMENTAL_MODEL_SIGNALS=0` to restore the baseline. The additions below are small, heuristic experimental
adjustments; their weights are not fitted, and there is no chronological holdout result for
them. Previous backtest accuracy and ROI figures describe earlier model configurations and
must not be attributed to this version. A comparison with the unchanged baseline on strictly
past-only, appropriately licensed historical data is still needed.
Unit tests verify behavior, not predictive skill.

The existing goals baseline uses league rates and team attack/defence. For each team, if both
its last-ten xG-for and its opponent's xG-against have at least five valid observations, the
average of those two measures provides a target. Its ratio to the baseline is capped at 0.5–1.5
and contributes 10% of the difference. With five valid observations of each team's shots on
target for/against and at least 30 paired league observations, the relative shots-on-target
ratio is capped at 0.5–1.5 and contributes 5% of the difference. These adjustments are
sequential, data-only, and bounded; missing inputs leave the baseline unchanged. Opponent xG
is xGA, not a separate guessed value. Historical samples can contain matches in other
competitions; they follow the scanner's existing profile/friendly-selection rules.

For corners, only explicitly reported shots **off target** (`Shof`) are used, not total shots
minus on-target shots (that difference can include blocked shots). With at least 30 paired
league observations and five for each team, a separate count model estimates off-target shots;
the ratio to the league rate is capped at 0.5–1.5 and contributes 5% of the difference to each
team's corner expectation. Old archive vectors have no off-target value: the signal will only
accumulate as new statistics are fetched, unless an appropriately authorized historical dataset
is provided. Main football-data feeds may lack xG or explicit off-target shots, so coverage may
be low. Missing information never becomes zero.

The shortlist can now include 1X2, BTTS yes, and team/total corner overs. Team/total booking recommendations are withheld until the historical data and bookmaker rules are reconciled.
It still requires data quality, the actual Sportybet price between 1.16 and 1.90, no model/market
disagreement or outlier, and `probability × odds >= 0.95`; one selection per fixture. Bars are
55% for 1X2/BTTS/O2.5, 65% for corners and 70% for other goal overs. The separate day
card has its own stricter section and form rules. Team corner markets use only the exact team/line
price, never a total or other team's price. Double chance, team goals, unders and O0.5 remain
excluded from recommendations. Existing paused competitions remain paused.

The card model counts provider-reported yellow plus red cards. SportyBet's published rules
for other country sites count a red as two bookings and exclude the second yellow leading to a
red; verify the precise ZA market and player's/bench treatment. The existing source aggregates
do not prove those distinctions, so pricing card-count probabilities as booking markets would
be misleading. Booking prices are therefore not attached to these model selections, they cannot
be shortlisted, and booking ticket grading stays pending. Native background grading also defers
these tickets. Previously stored results and tickets are not deleted. See the provider's
[football market rules](https://sportybetng.zendesk.com/hc/en-us/articles/360006289097-Football-Markets).
