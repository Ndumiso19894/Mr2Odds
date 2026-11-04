"""High-probability selections and shortlist picks may reference matches outside the published app
window (they are analysed up to 60 days ahead). The data check must accept fixture ids that exist in
the day archive, and still reject truly unknown ones."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import verify

NOW = datetime(2026, 9, 30, 12, 0)


def _build(tmp: Path) -> tuple[Path, Path]:
    staging = tmp / "app" / "_staging"
    live = tmp / "app"
    for sub in (staging / "fx", tmp / "app" / "days"):
        sub.mkdir(parents=True, exist_ok=True)
    detail = {"id": "f1", "quality": {"overall": "High"}, "xg": {"home": 1.4, "model_home": 1.4}, "sels": []}
    (staging / "fx" / "k1.json").write_text(json.dumps(detail), encoding="utf-8")
    latest = {
        "version": 3,
        "meta": {"generated": NOW.strftime("%Y-%m-%d %H:%M")},
        "fixtures": [
            {"id": "f1", "d": "k1", "kickoff": "2026-09-30 14:00", "home": "A", "away": "B",
             "sels": [], "p": {"O15": 0.8, "O25": 0.6, "BTTS": 0.5}, "x12": [0.4, 0.3, 0.3], "xg": [1.4, 1.0]},
        ],
        "shortlist": {"primary": [], "counts": {}},
        "safe": {"min_p": 0.7, "min_odds": 1.3, "bets": [
            {"id": "x|A|B|O25", "fixture": "archived-fixture-1", "home": "C", "away": "D",
             "kickoff": "2026-10-20 17:00", "sel": "Over 2.5", "label": "Over 2.5", "p": 0.75, "odds": 1.4},
        ], "today": {"bets": []}},
        "picks": {"O25": [{"fixture": "archived-fixture-1", "p": 0.62, "stars": 1, "sportybet": 1.5}]},
    }
    (staging / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    for name in ("meta.json", "alerts.json", "badges.json"):
        (staging / name).write_text(json.dumps({}), encoding="utf-8")
    (tmp / "app" / "days" / "2026-10-20.json").write_text(
        json.dumps({"date": "2026-10-20", "fixtures": [{"id": "archived-fixture-1"}]}), encoding="utf-8")
    return staging, live


def test_archive_fixtures_accepted(tmp_path):
    staging, live = _build(tmp_path)
    errors, _ = verify.check_publication(staging, live, tmp_path / "no-ledger.csv", NOW, expect_fixtures=1)
    assert not [e for e in errors if "unknown fixture" in e], errors
    assert not errors, errors


def test_truly_unknown_fixture_still_fails(tmp_path):
    staging, live = _build(tmp_path)
    d = json.loads((staging / "latest.json").read_text(encoding="utf-8"))
    d["safe"]["bets"][0]["fixture"] = "does-not-exist-anywhere"
    (staging / "latest.json").write_text(json.dumps(d), encoding="utf-8")
    errors, _ = verify.check_publication(staging, live, tmp_path / "no-ledger.csv", NOW, expect_fixtures=1)
    assert any("unknown fixture" in e for e in errors), errors
