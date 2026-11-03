"""Tests for the incremental analysis cache (acache) and its teamstats integration."""

import json
import pickle
import zlib
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

import acache
import teamstats


# ---------------------------------------------------------------- digests
def _frame(rows):
    return pd.DataFrame(rows)


def _row(date="2026-10-30", gf=2, ga=1, **kw):
    base = dict(date=pd.Timestamp(date), country="X", div="Div0", league="L", team="A", opp="B",
                venue="H", gf=gf, ga=ga, total=gf + ga, friendly=False, team_id=None, opp_id=None)
    base.update(kw)
    return base


def test_digest_rows_identical_frames_match():
    f1 = _frame([_row(), _row(date="2026-10-28", gf=0, ga=3)])
    f2 = _frame([_row(), _row(date="2026-10-28", gf=0, ga=3)])
    assert acache.digest_rows(f1) == acache.digest_rows(f2)


def test_digest_rows_sensitive_to_any_cell():
    f1 = _frame([_row(), _row(date="2026-10-28", gf=0, ga=3)])
    f2 = _frame([_row(), _row(date="2026-10-28", gf=0, ga=2)])   # one goal different
    f3 = _frame([_row(date="2026-10-29"), _row(date="2026-10-28", gf=0, ga=3)])   # date shifted
    d1 = acache.digest_rows(f1)
    assert acache.digest_rows(f2) != d1
    assert acache.digest_rows(f3) != d1


# ---------------------------------------------------------------- profiles
def _profile():
    import scanner
    p = scanner.TeamProfile(name="Test FC")
    p.n = 12
    p.n_eff = 8.5
    p.att, p.dfc = 1.42, 0.97
    p.rate_o15 = 0.75
    p.matches = [{"date": "2026-10-30", "venue": "H", "opp": "B", "gf": 2, "ga": 1,
                  "league": "L", "div": "Div0", "friendly": False, "season": "current",
                  "outlier": None, "xg_for": None}]
    p.last5 = [{"date": "2026-10-30", "venue": "H", "opp": "B", "gf": 2, "ga": 1, "league": "L"}]
    return p


def test_profile_roundtrip(tmp_path):
    c = acache.AnalysisCache(tmp_path / "c.bin")
    key = ("p", acache.SCHEMA, "2026-11-03", "X", "Test FC", "H", None, "abc", "def", None)
    p = _profile()
    assert c.profile_get(key) is None
    c.profile_put(key, p)
    c.save()
    c2 = acache.AnalysisCache(tmp_path / "c.bin")
    got = c2.profile_get(key)
    assert got is not None
    assert type(got) is type(p)
    assert got.name == p.name and got.att == p.att and got.matches == p.matches and got.last5 == p.last5
    assert c2.hits == 1


def test_profile_miss_after_input_change(tmp_path):
    c = acache.AnalysisCache(tmp_path / "c.bin")
    k1 = ("p", acache.SCHEMA, "2026-11-03", "X", "Test FC", "H", None, "digest-a", "def", None)
    k2 = ("p", acache.SCHEMA, "2026-11-03", "X", "Test FC", "H", None, "digest-b", "def", None)
    assert c.profile_get(k1) is None    # cold miss (marks the key as used this run)
    c.profile_put(k1, _profile())
    c.save()
    c2 = acache.AnalysisCache(tmp_path / "c.bin")
    assert c2.profile_get(k1) is not None
    assert c2.profile_get(k2) is None


def test_prune_untouched_entries(tmp_path):
    c = acache.AnalysisCache(tmp_path / "c.bin")
    keep = ("p", acache.SCHEMA, "2026-11-03", "X", "Keep", "H", None, "a", "b", None)
    drop = ("p", acache.SCHEMA, "2026-11-03", "X", "Drop", "H", None, "c", "d", None)
    c.profile_put(keep, _profile())
    c.profile_put(drop, _profile())
    c.profile_get(keep)          # touched
    c.save()
    c2 = acache.AnalysisCache(tmp_path / "c.bin")
    assert c2.profile_get(keep) is not None
    assert c2.profile_get(drop) is None


def test_corrupt_cache_starts_cold(tmp_path):
    path = tmp_path / "c.bin"
    path.write_bytes(b"this is not a cache file at all")
    c = acache.AnalysisCache(path)
    assert c.profiles == {} and c.pages == {}
    k = ("p", acache.SCHEMA, "2026-11-03", "X", "T", "H", None, "a", "b", None)
    assert c.profile_get(k) is None
    c.save()   # must not raise


def test_schema_mismatch_starts_cold(tmp_path):
    path = tmp_path / "c.bin"
    blob = zlib.compress(pickle.dumps({"schema": acache.SCHEMA + 1, "profiles": {"x": 1}, "pages": {}}))
    path.write_bytes(blob)
    c = acache.AnalysisCache(path)
    assert c.profiles == {}


# ---------------------------------------------------------------- team pages
NOW = datetime(2026, 11, 3, 12, 0)


def _results(extra=0):
    rows = []
    for d in ["2026-10-30", "2026-10-28", "2026-10-25"]:
        rows.append(dict(date=pd.Timestamp(d), country="X", div="Div0", league="L",
                         home="Alpha FC", away="Beta FC", hg=2, ag=1, home_id=None, away_id=None,
                         hxg=None, axg=None, hst=None, ast=None, hc=None, ac=None,
                         hy=None, hr=None, ay=None, ar=None))
    for i in range(extra):
        rows.append(dict(date=pd.Timestamp(f"2026-10-{20 - i:02d}"), country="X", div="Div0",
                         league="L", home="Alpha FC", away="Beta FC", hg=3, ag=0,
                         home_id=None, away_id=None, hxg=None, axg=None, hst=None, ast=None,
                         hc=None, ac=None, hy=None, hr=None, ay=None, ar=None))
    return pd.DataFrame(rows)


def _pages(tmp_path):
    out = tmp_path / "app" / "teams"
    c = acache.AnalysisCache(tmp_path / "c.bin")
    teamstats.export(_results(), NOW, out, page_cache=c)
    c.save()
    return out


def test_team_pages_cache_hit_reuses_identical_output(tmp_path):
    # file present + inputs unchanged: the page is reused as-is (no recompute, file untouched)
    out = _pages(tmp_path)
    bodies = {f.name: f.read_text() for f in out.iterdir()}
    c2 = acache.AnalysisCache(tmp_path / "c.bin")
    teamstats.export(_results(), NOW, out, page_cache=c2)
    assert c2.hits >= 1 and c2.misses == 0
    for name, body in bodies.items():
        assert (out / name).read_text() == body, name


def test_team_pages_hit_without_file_recomputes_identically(tmp_path):
    # inputs unchanged but the page file is gone (fresh bootstrap): recomputed, byte-identical
    out = _pages(tmp_path)
    bodies = {f.name: f.read_text() for f in out.iterdir()}
    for f in out.iterdir():
        f.unlink()
    c2 = acache.AnalysisCache(tmp_path / "c.bin")
    teamstats.export(_results(), NOW, out, page_cache=c2)
    assert c2.hits >= 1
    for name, body in bodies.items():
        assert (out / name).read_text() == body, name


def test_team_pages_cache_invalidates_on_new_result(tmp_path):
    out = _pages(tmp_path)
    old = (out / "Div0.json").read_text()
    for f in out.iterdir():
        f.unlink()
    c2 = acache.AnalysisCache(tmp_path / "c.bin")
    teamstats.export(_results(extra=1), NOW, out, page_cache=c2)   # one more result played
    assert c2.misses >= 1                                           # the division was recomputed
    new = json.loads((out / "Div0.json").read_text())
    assert new["matches"] == json.loads(old)["matches"] + 1


def test_team_pages_without_cache_still_works(tmp_path):
    out = tmp_path / "app" / "teams"
    n = teamstats.export(_results(), NOW, out)
    assert n == ["Div0"]
    assert (out / "Div0.json").exists()
