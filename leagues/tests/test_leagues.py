"""Tests for leagues.py (worldwide league browser data). Run: python3 -m pytest leagues/tests -q"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import leagues


def _rec(esd, home, away, hg, ag, hth=None, hta=None):
    return [esd, "1", home, "2", away, hg, ag, hth, hta]


def _ev(esd, home, away, hg, ag, hth=None, hta=None, eid="e"):
    return leagues._evt(eid, _rec(esd, home, away, hg, ag, hth, hta))


def test_evt_parses_9_and_7_field_records():
    e = leagues._evt("1839917", ["202609261600", "4533", "A", "3279", "B", 5, 1, None, None])
    assert e["finished"] and e["hg"] == 5 and e["home"] == "A" and e["eid"] == "1839917"
    e7 = leagues._evt("1", ["202609261600", "1", "A", "2", "B", 0, 0])
    assert e7["hth"] is None and e7["hta"] is None
    assert leagues._evt("1", ["junk", "1", "A", "2", "B", 1, 0]) is None
    assert leagues._evt("1", ["202609261600", "1", "", "2", "B", 1, 0]) is None
    assert leagues._evt("1", None) is None


def test_table_sorting_tie_breaks_and_form():
    evts = [
        _ev("202609011500", "A", "B", 2, 0),   # A w
        _ev("202609011500", "C", "D", 1, 1),   # C d
        _ev("202609081500", "B", "A", 0, 1),   # A w
        _ev("202609081500", "D", "C", 0, 0),   # C d
        _ev("202609151500", "A", "C", 3, 2),   # A w (beats C)
        _ev("202609151500", "D", "B", 4, 4),   # B d
    ]
    t = leagues.compute_table(evts)
    # A: 3W (9 pts, gd +4); D: 3D (3 pts, gd 0); C: 2D 1L (2 pts, gd -1); B: 1D 2L (1 pt, gd -3)
    assert [r["team"] for r in t] == ["A", "D", "C", "B"]
    a, d, c, b = t
    assert (a["p"], a["w"], a["d"], a["l"], a["pts"]) == (3, 3, 0, 0, 9)
    assert (a["gf"], a["ga"], a["gd"]) == (6, 2, 4)
    assert a["pos"] == 1
    assert (d["pts"], d["gd"], d["gf"]) == (3, 0, 5)
    assert (c["pts"], c["gd"], c["gf"]) == (2, -1, 3)
    assert (b["pts"], b["gd"], b["gf"]) == (1, -3, 4)
    # form: oldest first, last 5
    assert a["form"] == "WWW"
    assert d["form"] == "DDD"
    # half-time kept
    e = _ev("202609011500", "A", "B", 2, 1, 1, 0)
    assert e["hth"] == 1 and e["hta"] == 0


def test_table_home_away_splits():
    evts = [
        _ev("202609011500", "A", "B", 2, 0),   # A home w
        _ev("202609081500", "B", "A", 0, 1),   # A away w
        _ev("202609151500", "A", "C", 3, 2),   # A home w
    ]
    t = {r["team"]: r for r in leagues.compute_table(evts)}
    a = t["A"]
    assert (a["p"], a["gf"], a["ga"]) == (3, 6, 2)
    assert a["h"] == {"p": 2, "w": 2, "d": 0, "l": 0, "gf": 5, "ga": 2, "pts": 6}
    assert a["a"] == {"p": 1, "w": 1, "d": 0, "l": 0, "gf": 1, "ga": 0, "pts": 3}
    assert a["h"]["p"] + a["a"]["p"] == a["p"] and a["h"]["gf"] + a["a"]["gf"] == a["gf"]
    b = t["B"]
    assert b["h"] == {"p": 1, "w": 0, "d": 0, "l": 1, "gf": 0, "ga": 1, "pts": 0}
    assert b["a"] == {"p": 1, "w": 0, "d": 0, "l": 1, "gf": 0, "ga": 2, "pts": 0}


def test_league_like_detection():
    # group format: 4 teams, round robin -> league-like
    rr = [_ev(f"2026090{1 + i}1500", *p, 1, 0) for i, p in enumerate(
        [("A", "B"), ("C", "D"), ("A", "C"), ("B", "D"), ("A", "D"), ("B", "C")])]
    assert leagues.league_like(rr)
    # knockout: every team has one opponent
    ko = [_ev("202609011500", "A", "B", 2, 1), _ev("202609021500", "C", "A", 3, 2),
          _ev("202609031500", "D", "C", 0, 1), _ev("202609041500", "A", "D", 2, 2)]
    assert not leagues.league_like(ko)
    # too few teams
    small = [_ev("202609011500", "A", "B", 1, 0), _ev("202609021500", "A", "C", 2, 1)]
    assert not leagues.league_like(small)


def test_season_label():
    assert leagues._season({"2024-2025": 553, "2025-2026": 554, "2026": -1}) == "2025-2026"
    assert leagues._season(None) is None
    assert leagues._season({"2025-2026": -1}) is None


def test_build_publishes_index_and_details(tmp_path):
    stages = tmp_path / "stages"
    stages.mkdir()
    # league stage (round robin, 4 teams, 2 seasons in backfill)
    ev = {}
    for i, (h, a, hg, ag) in enumerate([("A", "B", 2, 0), ("C", "D", 1, 1), ("A", "C", 3, 2),
                                        ("B", "D", 0, 0), ("A", "D", 1, 0), ("B", "C", 2, 2)]):
        ev[str(1000 + i)] = _rec(f"20260{8 + i // 2}1500", h, a, hg, ag)
    (stages / "england__test-league.json").write_text(json.dumps(
        {"key": "england/test-league", "country": "England", "league": "Test League",
         "fetched": "2026-09-29 08:45", "events": ev, "backfill": {"2024-2025": 6, "2025-2026": 6}}))
    # knockout stage (1 opponent per team)
    evk = {"2000": _rec("202609011500", "A", "B", 2, 1), "2001": _rec("202609021500", "C", "A", 3, 2),
           "2002": _rec("202609031500", "D", "C", 0, 1), "2003": _rec("202609041500", "A", "D", 2, 2)}
    (stages / "england__test-cup.json").write_text(json.dumps(
        {"key": "england/test-cup", "country": "England", "league": "Test Cup",
         "fetched": "2026-09-29 08:45", "events": evk, "backfill": {"2025-2026": 4}}))
    # empty stage is skipped
    (stages / "england__empty.json").write_text(json.dumps(
        {"key": "england/empty", "country": "England", "league": "Empty", "events": {}}))

    n = leagues.build(stages, datetime(2026, 9, 29, 9, 0), tmp_path / "out", tz_hours=2)
    assert n == 1
    idx = json.loads((tmp_path / "out" / "index.json").read_text())
    assert idx["count"] == 1
    by_slug = {x["slug"]: x for x in idx["leagues"]}
    assert by_slug["england__test-league.json"]["table"] is True
    assert "england__test-cup.json" not in by_slug
    assert (stages / "england__test-cup.json").exists()  # archive is preserved
    assert by_slug["england__test-league.json"]["season"] == "2025-2026"
    det = json.loads((tmp_path / "out" / "england__test-league.json").read_text())
    assert [r["team"] for r in det["table"]][:1] == ["A"]
    assert len(det["results"]) == 6 and det["results"][0]["ko"].startswith("2026-09")
    assert det["fixtures"] == []          # no day feed in the test
    assert (tmp_path / "out" / "england__empty.json").exists() is False

    # stale detail files of vanished stages are removed
    (tmp_path / "out" / "england__gone.json").write_text("{}")
    leagues.build(stages, datetime(2026, 9, 29, 9, 0), tmp_path / "out", tz_hours=2)
    assert not (tmp_path / "out" / "england__gone.json").exists()


def test_build_with_timezone_aware_now(tmp_path):
    """CI runs with a tz-aware now (Africa/Johannesburg); the feed kick-offs are naive display-time."""
    from datetime import timezone, timedelta
    stages = tmp_path / "stages"
    stages.mkdir()
    ev = {"1000": _rec("202609011500", "A", "B", 1, 0), "1001": _rec("202609021500", "C", "D", 2, 1),
          "1002": _rec("202609031500", "A", "C", 1, 1), "1003": _rec("202609041500", "B", "D", 0, 2),
          "1004": _rec("202609051500", "A", "D", 2, 0), "1005": _rec("202609061500", "B", "C", 1, 1)}
    (stages / "test__league.json").write_text(json.dumps(
        {"key": "test/league", "country": "Test", "league": "League",
         "fetched": "2026-09-29 08:00", "events": ev, "backfill": {"2024-2025": 6}}))
    now = datetime(2026, 9, 29, 9, 0, tzinfo=timezone(timedelta(hours=2)))   # aware, like CI
    n = leagues.build(stages, now, tmp_path / "out", tz_hours=2)
    assert n == 1
    idx = json.loads((tmp_path / "out" / "index.json").read_text())
    assert idx["count"] == 1 and idx["leagues"][0]["table"] is True


def test_real_archive_build_smoke(tmp_path):
    """Build against the real published archive when it is present (CI has it via the data branch)."""
    real = Path("/tmp/fb-data/data/ls/stages")
    if not real.exists():
        pytest.skip("local archive not present")
    n = leagues.build(real, datetime(2026, 9, 29, 9, 0), tmp_path / "out", tz_hours=2)
    assert n >= 200
    idx = json.loads((tmp_path / "out" / "index.json").read_text())
    with_table = [x for x in idx["leagues"] if x["table"]]
    assert len(with_table) >= 50
    # every detail file parses and its table is sorted by points
    import random
    for x in random.sample(with_table, min(10, len(with_table))):
        det = json.loads((tmp_path / "out" / x["slug"]).read_text())
        pts = [r["pts"] for r in det["table"]]
        assert pts == sorted(pts, reverse=True)
