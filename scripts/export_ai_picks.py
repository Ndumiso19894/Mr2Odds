#!/usr/bin/env python3
"""Create a compact, machine-readable text export from Mr2Odds latest.json."""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE = Path(sys.argv[1])
DEST = Path(sys.argv[2])
TZ = ZoneInfo("Africa/Johannesburg")
MARKETS = {
    "O15": "Match total over 1.5 goals",
    "O25": "Match total over 2.5 goals",
    "O35": "Match total over 3.5 goals",
    "BTTS": "Both teams to score",
    "H": "Home win",
    "D": "Draw",
    "A": "Away win",
    "HO05": "Home team over 0.5 goals",
    "AO05": "Away team over 0.5 goals",
    "HO15": "Home team over 1.5 goals",
    "AO15": "Away team over 1.5 goals",
    "HU15": "Home team under 1.5 goals",
    "AU15": "Away team under 1.5 goals",
    "CHO35": "Home team over 3.5 corners",
    "CAO35": "Away team over 3.5 corners",
    "CO85": "Match total over 8.5 corners",
    "CO95": "Match total over 9.5 corners",
    "CO105": "Match total over 10.5 corners",
}

doc = json.loads(SOURCE.read_text(encoding="utf-8"))
meta = doc.get("meta", {})
now = datetime.now(TZ)
fixtures = doc.get("fixtures", [])
upcoming = []
for item in fixtures:
    raw_kickoff = item.get("kickoff")
    if not raw_kickoff:
        continue
    try:
        kickoff = datetime.strptime(raw_kickoff, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except ValueError:
        continue
    if kickoff <= now:
        continue
    upcoming.append((kickoff, item))
upcoming.sort(key=lambda pair: pair[0])

lines = [
    "MR2ODDS — LATEST PICKS EXPORT",
    f"Generated from scan: {meta.get('generated', 'unknown')} SAST",
    f"Export created: {now.strftime('%Y-%m-%d %H:%M')} SAST",
    f"Upcoming fixtures in latest feed: {len(upcoming)}",
    f"Total fixtures in feed: {len(fixtures)}",
    f"Model signals status: {meta.get('model_signals', {}).get('status', 'not stated')}",
    f"Recent-form module: {'enabled' if meta.get('recent_form', {}).get('enabled') else 'not confirmed'}",
    "",
    "IMPORTANT DATA LIMITATIONS",
    "- These are scanner shortlist outputs, not independently verified betting recommendations.",
    "- Model probabilities are estimates, not guarantees; compare them with current bookmaker prices.",
    "- Experimental xG/xGA and shots signals are disabled when model_signals.status is disabled.",
    "- No bookings market is included unless an explicit bookings selection appears in the source data.",
    "- Do not treat the label 'safe' as a guarantee. It is the scanner's internal shortlist label.",
    "",
    "UPCOMING PRICED SHORTLIST",
]
count = 0
for kickoff, item in upcoming:
    pick = item.get("safe")
    if not pick or len(pick) < 3:
        continue
    code, probability, odds = pick[0], pick[1], pick[2]
    try:
        probability = float(probability)
        odds = float(odds)
    except (TypeError, ValueError):
        continue
    count += 1
    market = MARKETS.get(str(code), f"Market code: {code}")
    lines.extend([
        "",
        f"{count}. {item.get('home', '?')} vs {item.get('away', '?')}",
        f"   Kick-off: {kickoff.strftime('%a %d %b %H:%M')} SAST",
        f"   Competition: {item.get('competition', item.get('league', 'unknown'))}",
        f"   Selection: {market} [{code}]",
        f"   Model probability: {probability:.1%}",
        f"   Sportybet decimal odds: {odds:.2f}",
        f"   Data quality: {item.get('q', 'not stated')}",
        f"   Other model probabilities: O1.5={item.get('p', {}).get('O15', 'n/a')}; "
        f"O2.5={item.get('p', {}).get('O25', 'n/a')}; "
        f"BTTS={item.get('p', {}).get('BTTS', 'n/a')}",
    ])
if count == 0:
    lines.extend(["", "No upcoming fixture has a populated scanner 'safe' selection and price."])
lines.extend([
    "",
    "AI ANALYSIS INSTRUCTIONS",
    "Independently research each listed match. Do not copy the scanner market automatically.",
    "Assess recent home/away scoring and conceding form, opponent quality, team-goal alternatives,",
    "corners won/conceded and match style. Assess bookings only with reliable referee and team data.",
    "Compare fair probability with the listed price; explain uncertainty and reject weak matches.",
    "Return PASS when evidence is insufficient. Never invent statistics, odds, injuries or line-ups.",
    "",
])
DEST.parent.mkdir(parents=True, exist_ok=True)
DEST.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {DEST}: {count} priced upcoming shortlist selections from {len(upcoming)} upcoming fixtures.")
