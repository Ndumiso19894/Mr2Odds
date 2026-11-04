"""Incremental analysis cache (across scan runs).

The scan re-fetches fresh data every 30 minutes, but the expensive per-team / per-division
computation only changes when its *inputs* change (a new result for the team, an updated squad
value, a new calendar day). This module persists that computed evidence to the state directory
(the `data` branch on GitHub) and reuses it on the next run.

This is **pure memoization**: a cache hit returns exactly the object the previous run computed
from identical inputs, so the published output is byte-identical to a cold run. Nothing here
changes what is computed — only whether the previously computed result is reused.

Safety rules (data-first engine):
  * a corrupt, foreign or stale-schema cache file is dropped and rebuilt, never fatal;
  * the cache is keyed on a digest of the exact input rows consumed, so any input change
    (new result, corrected score, new squad value, new day) forces a recompute;
  * entries not touched by the current run are pruned on save, so the file stays the size of
    one run's evidence and cannot grow unbounded;
  * every accessor is wrapped so a cache bug degrades to a cold recompute, never a broken scan.
"""
from __future__ import annotations

import hashlib
import logging
import pickle
import zlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger("acache")

SCHEMA = 2   # bump whenever a payload layout changes (the whole cache is rebuilt, nothing breaks)


def digest_rows(df: pd.DataFrame) -> str:
    """Stable digest of a frame's exact row contents (all columns, original order)."""
    h = hashlib.md5()
    for r in df.itertuples(index=False):
        h.update(repr(r).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def digest_seq(values) -> str:
    """Stable digest of a sequence of (already hashable) values."""
    h = hashlib.md5()
    for v in values:
        h.update(repr(v).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


class AnalysisCache:
    """Load / reuse / persist the computed evidence of the last scan run."""

    def __init__(self, path: Path | None):
        self.path = path
        self.profiles: dict = {}
        self.pages: dict = {}
        self._touched: set = set()
        self.hits = 0
        self.misses = 0
        self.page_hits = 0
        self.page_misses = 0
        if path is None:
            return
        try:
            if path.exists():
                obj = pickle.loads(zlib.decompress(path.read_bytes()))
                if isinstance(obj, dict) and obj.get("schema") == SCHEMA:
                    self.profiles = obj.get("profiles", {}) or {}
                    self.pages = obj.get("pages", {}) or {}
                    log.info("Analysis cache: loaded %d profile(s), %d team page(s) from %s",
                             len(self.profiles), len(self.pages), path)
            else:
                log.info("Analysis cache: cold start (no previous run file at %s)", path)
        except Exception as exc:  # noqa: BLE001 — a bad cache file must never kill a scan
            log.warning("Analysis cache: unreadable cache at %s (%s) — starting cold", path, exc)
            self.profiles, self.pages = {}, {}

    # ---- profiles (per-team match evidence) -------------------------------------------------
    def profile_get(self, key: tuple) -> "Any":
        if key not in self._touched:
            self._touched.add(key)
        hit = self.profiles.get(key)
        if hit is None:
            self.misses += 1
            return None
        self.hits += 1
        try:
            import scanner
            return scanner.TeamProfile(**hit)
        except Exception:  # noqa: BLE001
            self.profiles.pop(key, None)
            self.misses += 1
            return None

    def profile_put(self, key: tuple, profile) -> None:
        try:
            self.profiles[key] = asdict(profile)
        except Exception as exc:  # noqa: BLE001
            log.warning("Analysis cache: profile payload failed (%s) — continuing uncached", exc)

    # ---- team pages (per-division JSON) ------------------------------------------------------
    def page_get(self, key: tuple) -> tuple[str, dict] | None:
        if key not in self._touched:
            self._touched.add(key)
        hit = self.pages.get(key)
        if hit is not None:
            self.page_hits += 1
        else:
            self.page_misses += 1
        return hit

    def page_put(self, key: tuple, body: str, index_entry: list[dict]) -> None:
        self.pages[key] = (body, index_entry)

    # ---- persistence ------------------------------------------------------------------------
    def save(self, path: Path | None = None) -> None:
        path = path or self.path
        if path is None:
            return
        try:
            # prune entries this run never asked for — the file always holds exactly one run's evidence
            self.profiles = {k: v for k, v in self.profiles.items() if k in self._touched}
            self.pages = {k: v for k, v in self.pages.items() if k in self._touched}
            blob = zlib.compress(pickle.dumps(
                {"schema": SCHEMA, "profiles": self.profiles, "pages": self.pages},
                protocol=pickle.HIGHEST_PROTOCOL), 6)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(blob)
            tmp.replace(path)
            log.info("Analysis cache: saved %d profile(s), %d page(s) -> %s (%.1f MB) | profiles: %d hit / %d miss | pages: %d hit / %d miss",
                     len(self.profiles), len(self.pages), path, len(blob) / 1e6,
                     self.hits, self.misses, self.page_hits, self.page_misses)
        except Exception as exc:  # noqa: BLE001
            log.warning("Analysis cache: save failed (%s) — next run recomputes from scratch", exc)
