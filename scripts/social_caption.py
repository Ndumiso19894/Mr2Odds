"""One exact caption format with hashtags made only from the teams in that post."""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPTION = "Today's slips selections, GOOD LUCK!"


def _slug(team: str) -> str:
    normalized = unicodedata.normalize("NFKD", team)
    ascii_name = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^A-Za-z0-9]", "", ascii_name)


def _fixtures(info=None):
    if isinstance(info, dict):
        fixtures = info.get("fixtures")
        if isinstance(fixtures, list):
            return fixtures
        # Some multi-slip manifests keep fixtures inside each accumulator.
        groups = info.get("accumulators")
        if isinstance(groups, list):
            return [fixture for group in groups if isinstance(group, dict)
                    for fixture in group.get("fixtures", []) if isinstance(fixture, dict)]
        return []

    report = ROOT / "reports" / "morning-report.md"
    if not report.is_file():
        return []
    text = report.read_text(encoding="utf-8")
    section = re.search(r"(?ms)^## Final tickets.*$", text)
    if not section:
        return []
    rows = re.findall(r"(?m)^•\s*(.+?)\s+—\s+.+$", section.group(0))
    result = []
    for row in rows:
        if " v " in row:
            home, away = row.split(" v ", 1)
            result.append({"home": home.strip(), "away": away.strip()})
    return result


def social_caption(info=None, *, test=False):
    teams = []
    seen = set()
    for fixture in _fixtures(info):
        if not isinstance(fixture, dict):
            continue
        for side in ("home", "away"):
            team = fixture.get(side)
            if not isinstance(team, str) or not team.strip():
                continue
            tag = _slug(team.strip())
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                teams.append("#" + tag)
    prefix = "TEST POST — " if test else ""
    hashtags = " ".join(teams)
    return f"{prefix}{CAPTION}" + (f"\n\n{hashtags}" if hashtags else "")


if __name__ == "__main__":
    print(social_caption())
