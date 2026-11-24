"""Shared caption for every Mr2Odds social post."""

CAPTION = "Today's slips selections, GOOD LUCK!"
HASHTAGS = (
    "#Mr2Odds #FootballPredictions #FootballTips "
    "#SoccerPredictions #FootballAnalysis #BetResponsibly"
)


def social_caption(*, test=False):
    prefix = "TEST POST — " if test else ""
    return f"{prefix}{CAPTION}\n\n{HASHTAGS}"
