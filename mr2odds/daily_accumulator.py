"""
Daily accumulator builder for Mr 2 Odds.

Produces a focused daily selection:
  * 3 accumulators, each with combined odds in the 2.50–3.50 band
  * at least 6 alternative matches (not used in any accumulator)
  * deep research on every selected match — news headlines, odds comparison
    against the football-data model, form, head-to-head, venue context

This module only *selects* and *researches*; it never changes a model
probability. Everything here is presentation of data already computed by
scanner.py (football-data model) plus Sportybet prices (market view) and
Google News headlines (context only — never a model input).

Nothing in the existing scanner, models, ledgers or app export is deleted
or modified — this module is additive and runs beside them.
"""

from __future__ import annotations

import html
import itertools
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

try:
    import requests  # only used transitively by the news module; optional here
except Exception:  # noqa: BLE001
    requests = None


log = logging.getLogger("daily_accumulator")

# --------------------------------------------------------------------------- config

ACCUM_ODDS_LO = 2.50      # lowest combined odds for an accumulator
ACCUM_ODDS_HI = 3.50      # highest combined odds for an accumulator
ACCUM_COUNT = 3           # how many accumulators to build
ACCUM_MAX_LEGS = 4        # max legs per accumulator
ALT_MIN = 6               # minimum alternative matches to surface
MIN_LEG_ODDS = 1.30       # shortest individual leg price considered
MAX_LEG_ODDS = 2.20       # longest individual leg price considered
MIN_LEG_PROB = 0.45       # lowest model probability a leg can carry
MAX_DIFF_PP = 12          # model-vs-market disagreement cap (percentage points)
NEWS_DAYS = 7             # how far back news headlines are fetched
RESEARCH_MIN_DATA = "Moderate"  # minimum data-quality label for a selected match


# --------------------------------------------------------------------------- data classes

@dataclass
class AccaLeg:
    """One leg of an accumulator."""
    match_id: str
    home: str
    away: str
    league: str
    kickoff: str          # "YYYY-MM-DD HH:MM"
    country: str
    sel: str              # "H" / "D" / "A" / "O25"
    label: str            # human-readable selection
    odds: float           # Sportybet decimal price
    p_model: float        # football-data model probability
    p_market: float | None  # de-margined Sportybet implied probability
    diff_pp: float | None   # model − market in percentage points
    data_quality: str | None

    @property
    def ev(self) -> float:
        return self.p_model * self.odds - 1


@dataclass
class Accumulator:
    """A multi-leg accumulator."""
    legs: list[AccaLeg]
    odds: float           # combined decimal odds
    p_win: float          # combined model win probability
    ev: float             # expected return per 1 staked
    note: str             # plain-language summary

    @property
    def n_legs(self) -> int:
        return len(self.legs)


@dataclass
class Alternative:
    """A match surfaced as an alternative (not in an accumulator)."""
    match_id: str
    home: str
    away: str
    league: str
    kickoff: str
    country: str
    best_sel: str         # strongest selection code
    best_label: str
    best_odds: float
    best_p_model: float
    best_p_market: float | None
    data_quality: str | None
    research: list[str]   # deep-research bullet points


@dataclass
class MatchResearch:
    """Deep research for one selected match."""
    match_id: str
    home: str
    away: str
    league: str
    kickoff: str
    country: str
    xg_home: float
    xg_away: float
    p_o25_model: float
    p_o25_market: float | None
    sporty_o25: float | None
    sporty_1x2: tuple[float | None, float | None, float | None]
    news: list[dict]      # headlines (context only)
    form_home: list[dict]  # last 5 results
    form_away: list[dict]
    h2h: list[dict]       # head-to-head
    data_quality: str | None
    sample_home: int
    sample_away: int
    bullets: list[str]    # plain-language research summary


# --------------------------------------------------------------------------- helpers

def _pct(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{100 * x:.0f}%"


def _f2(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:.2f}"


def _label(sel: str, home: str = "Home", away: str = "Away") -> str:
    if sel == "H":
        return f"{home} to win"
    if sel == "D":
        return "Draw"
    if sel == "A":
        return f"{away} to win"
    if sel == "O25":
        return "Over 2.5 goals"
    if sel == "O15":
        return "Over 1.5 goals"
    if sel == "BTTS":
        return "Both teams to score"
    return sel


def _data_quality_label(r) -> str | None:
    q = (r.audit or {}).get("quality") or {}
    return q.get("overall")


def _news_headlines(home: str, away: str, country: str, limit: int = 3) -> list[dict]:
    """Fetch Google News headlines for both teams (context only, never a model input)."""
    try:
        import news as news_mod
    except Exception:
        log.debug("news module unavailable — skipping headlines")
        return []

    headlines: list[dict] = []
    for team in (home, away):
        try:
            items = news_mod.team_headlines(team, country=country, days=NEWS_DAYS, limit=limit)
        except Exception as exc:  # noqa: BLE001 — news must never break selection
            log.debug("news failed for %s: %s", team, exc)
            items = []
        for it in items:
            headlines.append({
                "team": team,
                "title": it.get("title", ""),
                "source": it.get("source", ""),
                "when": it.get("when"),
                "link": it.get("link", ""),
                "notes": it.get("notes", ""),
            })
    # de-duplicate by title
    seen = set()
    out = []
    for h in headlines:
        k = h["title"].lower()[:60]
        if k in seen:
            continue
        seen.add(k)
        out.append(h)
    return out


def _research_bullets(r, research: MatchResearch) -> list[str]:
    """Plain-language deep-research bullets for one match (data + reality, not AI analysis)."""
    b: list[str] = []

    # Expected goals
    b.append(
        f"Model expected goals: {research.xg_home:.2f} (home) + {research.xg_away:.2f} "
        f"(away) = {research.xg_home + research.xg_away:.2f} total — football data only."
    )

    # Market vs model on Over 2.5
    if research.p_o25_market is not None:
        gap = 100 * (research.p_o25_model - research.p_o25_market)
        direction = "above" if gap > 0 else "below"
        b.append(
            f"Over 2.5: model {_pct(research.p_o25_model)} vs Sportybet-implied "
            f"{_pct(research.p_o25_market)} — model sits {abs(gap):.0f} points {direction} the market."
        )
    else:
        b.append(
            f"Over 2.5: model {_pct(research.p_o25_model)} — no Sportybet price to compare."
        )

    # Sportybet prices
    h, d, a = research.sporty_1x2
    price_bits = []
    if h is not None:
        price_bits.append(f"home {_f2(h)}")
    if d is not None:
        price_bits.append(f"draw {_f2(d)}")
    if a is not None:
        price_bits.append(f"away {_f2(a)}")
    if price_bits:
        b.append(f"Sportybet 1X2: " + " / ".join(price_bits) + ".")

    # Data quality and samples
    b.append(
        f"Data: {research.sample_home} home matches, {research.sample_away} away matches "
        f"(quality {research.data_quality or 'N/A'})."
    )

    # Head-to-head
    if research.h2h:
        tot = [m["hg"] + m["ag"] for m in research.h2h]
        o25_h2h = sum(1 for t in tot if t >= 3)
        b.append(
            f"Head-to-head (last {len(research.h2h)}): avg {sum(tot)/len(tot):.1f} goals, "
            f"Over 2.5 in {o25_h2h}/{len(research.h2h)}."
        )

    # News headlines (context only)
    team_news: dict[str, list[str]] = {}
    for item in research.news:
        team_news.setdefault(item["team"], []).append(item["title"])
    for team, items in team_news.items():
        if items:
            joined = "; ".join(items[:2])
            b.append(
                f"News ({team}): {joined} — context only, not used by the model."
            )

    return b


# --------------------------------------------------------------------------- leg eligibility

def _leg_candidates(r) -> list[AccaLeg]:
    """All priced, eligible accumulator legs from one MatchRow."""
    legs: list[AccaLeg] = []
    sb = r.sb or {}
    if not sb:
        return legs

    fx = r.fx
    date = fx["date"].strftime("%Y-%m-%d")
    ko = fx["kickoff"].strftime("%Y-%m-%d %H:%M")
    country = str(fx.get("country") or "")
    league = str(fx.get("league") or "")
    home = str(fx.get("home") or "")
    away = str(fx.get("away") or "")
    match_id = f"{date}|{country}|{home}|{away}"

    dq = _data_quality_label(r)

    # 1X2 legs
    sb1x2 = sb.get("1X2")
    if sb1x2 and all(o and o > 1 for o in sb1x2):
        x12 = r.extra.x12 or {}
        pH, pD, pA = x12.get("H"), x12.get("D"), x12.get("A")
        m = None
        try:
            import markets as _mk
            m = _mk.power_demargin(list(sb1x2))
        except Exception:
            m = None
        p_sb = list(m) if m else None
        for code, o, pm, psb in (("H", sb1x2[0], pH, p_sb[0] if p_sb else None),
                                 ("D", sb1x2[1], pD, p_sb[1] if p_sb else None),
                                 ("A", sb1x2[2], pA, p_sb[2] if p_sb else None)):
            if not (MIN_LEG_ODDS <= o <= MAX_LEG_ODDS):
                continue
            if pm is None or not (MIN_LEG_PROB <= pm < 1):
                continue
            diff = None if psb is None else 100 * (pm - psb)
            if diff is not None and abs(diff) > MAX_DIFF_PP:
                continue
            legs.append(AccaLeg(
                match_id=match_id, home=home, away=away, league=league, kickoff=ko,
                country=country, sel=code, label=_label(code, home, away), odds=float(o),
                p_model=float(pm), p_market=psb, diff_pp=diff, data_quality=dq,
            ))

    # Over 2.5 leg
    ou = sb.get("OU", {}).get(2.5) if sb.get("OU") else None
    if ou and ou[0] and ou[1]:
        po = r.p_final.get("O25")
        if po is not None and MIN_LEG_PROB <= po < 1:
            p_sb_over = (1 / ou[0]) / (1 / ou[0] + 1 / ou[1])
            diff = 100 * (po - p_sb_over)
            if abs(diff) <= MAX_DIFF_PP:
                legs.append(AccaLeg(
                    match_id=match_id, home=home, away=away, league=league, kickoff=ko,
                    country=country, sel="O25", label=_label("O25", home, away),
                    odds=float(ou[0]), p_model=float(po), p_market=p_sb_over,
                    diff_pp=diff, data_quality=dq,
                ))

    return legs


# --------------------------------------------------------------------------- accumulator builder

def _combined_odds(legs: list[AccaLeg]) -> float:
    o = 1.0
    for l in legs:
        o *= l.odds
    return o


def _combined_prob(legs: list[AccaLeg]) -> float:
    p = 1.0
    for l in legs:
        p *= l.p_model
    return p


def build_accumulators(
    rows,
    now: datetime,
    count: int = ACCUM_COUNT,
    odds_lo: float = ACCUM_ODDS_LO,
    odds_hi: float = ACCUM_ODDS_HI,
    max_legs: int = ACCUM_MAX_LEGS,
) -> list[Accumulator]:
    """
    Build `count` accumulators inside the odds band, using disjoint matches.

    Legs are ranked by expected return (p_model × odds). Each accumulator
    maximises expected return subject to the odds band and the max-leg cap.
    Matches are never reused across accumulators.
    """
    # collect all eligible legs from today's matches
    today = now.strftime("%Y-%m-%d")
    all_legs: list[AccaLeg] = []
    for r in rows:
        if not r.data_ok:
            continue
        fx_date = r.fx["date"].strftime("%Y-%m-%d")
        if fx_date != today:
            continue
        # kickoff must be in the future (>= now + 10 min buffer)
        ko = r.fx["kickoff"]
        if ko <= now + timedelta(minutes=10):
            continue
        all_legs.extend(_leg_candidates(r))

    if not all_legs:
        return []

    # rank legs by expected return, then probability
    all_legs.sort(key=lambda l: (-l.ev, -l.p_model, -l.odds))

    chosen: list[Accumulator] = []
    used_match_ids: set[str] = set()

    for _ in range(count):
        pool = [l for l in all_legs if l.match_id not in used_match_ids]
        if not pool:
            break

        best: Optional[list[AccaLeg]] = None
        best_v = -1.0

        # try all combos of 2..max_legs legs from distinct matches
        seen_match_in_combo: set[str] = set()
        for k in range(2, max_legs + 1):
            for combo in itertools.combinations(pool, k):
                mids = {l.match_id for l in combo}
                if len(mids) < k:
                    continue  # same match twice
                odds = _combined_odds(list(combo))
                if odds < odds_lo or odds > odds_hi:
                    continue
                v = _combined_prob(list(combo)) * odds  # expected return
                if v > best_v:
                    best = list(combo)
                    best_v = v

        if best is None:
            break

        chosen.append(_finalize_accumulator(best))
        used_match_ids |= {l.match_id for l in best}

    return chosen


def _finalize_accumulator(legs: list[AccaLeg]) -> Accumulator:
    odds = _combined_odds(legs)
    p_win = _combined_prob(legs)
    ev = p_win * odds - 1
    sel_names = " + ".join(l.label for l in legs)
    note = (
        f"{len(legs)} legs ({sel_names}) — combined {_f2(odds)}, "
        f"model win {_pct(p_win)}, expected return {100 * ev:+.1f}%."
    )
    return Accumulator(legs=legs, odds=odds, p_win=p_win, ev=ev, note=note)


# --------------------------------------------------------------------------- alternatives

def build_alternatives(
    rows,
    now: datetime,
    used_match_ids: set[str],
    min_alt: int = ALT_MIN,
) -> list[Alternative]:
    """
    Surface at least `min_alt` alternative matches not used in any accumulator.

    Each alternative shows its strongest priced selection plus deep research.
    """
    today = now.strftime("%Y-%m-%d")
    alts: list[Alternative] = []

    for r in rows:
        if not r.data_ok:
            continue
        fx_date = r.fx["date"].strftime("%Y-%m-%d")
        if fx_date != today:
            continue
        ko = r.fx["kickoff"]
        if ko <= now + timedelta(minutes=10):
            continue
        match_id = f"{fx_date}|{r.fx.get('country')}|{r.fx.get('home')}|{r.fx.get('away')}"
        if match_id in used_match_ids:
            continue

        legs = _leg_candidates(r)
        if not legs:
            continue

        # strongest leg by probability × odds
        best = max(legs, key=lambda l: l.p_model * l.odds)
        dq = _data_quality_label(r)
        alts.append(Alternative(
            match_id=match_id,
            home=str(r.fx.get("home") or ""),
            away=str(r.fx.get("away") or ""),
            league=str(r.fx.get("league") or ""),
            kickoff=ko,
            country=str(r.fx.get("country") or ""),
            best_sel=best.sel,
            best_label=best.label,
            best_odds=best.odds,
            best_p_model=best.p_model,
            best_p_market=best.p_market,
            data_quality=dq,
            research=[],  # filled later by research()
        ))

    alts.sort(key=lambda a: (-a.best_p_model * a.best_odds, -a.best_p_model))
    return alts[: max(min_alt, len(alts))]


# --------------------------------------------------------------------------- deep research

def research_match(r, news_headlines: list[dict]) -> MatchResearch:
    """Build a deep-research dossier for one selected match (data + reality)."""
    fx = r.fx
    date = fx["date"].strftime("%Y-%m-%d")
    ko = fx["kickoff"].strftime("%Y-%m-%d %H:%M")
    country = str(fx.get("country") or "")
    home = str(fx.get("home") or "")
    away = str(fx.get("away") or "")
    match_id = f"{date}|{country}|{home}|{away}"

    sb = r.sb or {}
    sb1x2 = sb.get("1X2") or (None, None, None)
    ou = (sb.get("OU") or {}).get(2.5) or (None, None)

    research = MatchResearch(
        match_id=match_id, home=home, away=away, league=str(fx.get("league") or ""),
        kickoff=ko, country=country,
        xg_home=float(r.mod_h), xg_away=float(r.mod_a),
        p_o25_model=float(r.p_final.get("O25", float("nan"))),
        p_o25_market=float(r.fair.get("O25", float("nan"))) if r.fair else float("nan"),
        sporty_o25=float(ou[0]) if ou and ou[0] else None,
        sporty_1x2=(
            float(sb1x2[0]) if sb1x2[0] else None,
            float(sb1x2[1]) if sb1x2[1] else None,
            float(sb1x2[2]) if sb1x2[2] else None,
        ),
        news=news_headlines,
        form_home=list(r.home.last5) if r.home else [],
        form_away=list(r.away.last5) if r.away else [],
        h2h=list(r.h2h) if r.h2h else [],
        data_quality=_data_quality_label(r),
        sample_home=int(r.home.n) if r.home else 0,
        sample_away=int(r.away.n) if r.away else 0,
        bullets=[],
    )
    research.bullets = _research_bullets(r, research)
    return research


# --------------------------------------------------------------------------- public entry point

def daily_selection(rows, now: Optional[datetime] = None) -> dict:
    """
    Build the complete daily selection payload:
      * 3 accumulators (2.50–3.50 odds)
      * 6+ alternative matches
      * deep research for every selected match
    """
    if now is None:
        import zoneinfo
        now = datetime.now(zoneinfo.ZoneInfo("Africa/Johannesburg"))

    accumulators = build_accumulators(rows, now)
    used_ids = {l.match_id for a in accumulators for l in a.legs}
    alternatives = build_alternatives(rows, now, used_ids)

    # deep research for every accumulator leg + every alternative
    all_selected: list = []
    for a in accumulators:
        all_selected.extend(a.legs)
    for alt in alternatives:
        all_selected.append(_alt_to_leg(alt))

    # fetch news once per team (batched)
    news_cache: dict[tuple[str, str], list[dict]] = {}

    def news_for(home: str, away: str, country: str) -> list[dict]:
        key = (home, away)
        if key not in news_cache:
            news_cache[key] = _news_headlines(home, away, country)
        return news_cache[key]

    acca_research: list[MatchResearch] = []
    for a in accumulators:
        for l in a.legs:
            row = _find_row(rows, l.match_id)
            if row is None:
                continue
            acca_research.append(research_match(row, news_for(l.home, l.away, l.country)))

    alt_research: list[MatchResearch] = []
    for alt in alternatives:
        row = _find_row(rows, alt.match_id)
        if row is None:
            continue
        alt_research.append(research_match(row, news_for(alt.home, alt.away, alt.country)))

    return {
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "accumulators": [_acca_to_dict(a) for a in accumulators],
        "alternatives": [_alt_to_dict(a) for a in alternatives],
        "research": {
            "accumulators": [_research_to_dict(r) for r in acca_research],
            "alternatives": [_research_to_dict(r) for r in alt_research],
        },
        "summary": {
            "n_accumulators": len(accumulators),
            "n_alternatives": len(alternatives),
            "odds_band": [ACCUM_ODDS_LO, ACCUM_ODDS_HI],
        },
    }


# --------------------------------------------------------------------------- internal helpers

def _find_row(rows, match_id: str):
    """Find a MatchRow by its deterministic fixture id."""
    date, country, home, away = match_id.split("|", 3)
    for r in rows:
        fx = r.fx
        if (fx["date"].strftime("%Y-%m-%d") == date
                and str(fx.get("country")) == country
                and str(fx.get("home")) == home
                and str(fx.get("away")) == away):
            return r
    return None


def _alt_to_leg(alt: Alternative) -> AccaLeg:
    return AccaLeg(
        match_id=alt.match_id, home=alt.home, away=alt.away, league=alt.league,
        kickoff=alt.kickoff, country=alt.country, sel=alt.best_sel,
        label=alt.best_label, odds=alt.best_odds, p_model=alt.best_p_model,
        p_market=alt.best_p_market, diff_pp=None, data_quality=alt.data_quality,
    )


def _acca_to_dict(a: Accumulator) -> dict:
    return {
        "n_legs": a.n_legs,
        "odds": round(a.odds, 2),
        "p_win": round(a.p_win, 4),
        "ev": round(a.ev, 4),
        "note": a.note,
        "legs": [
            {
                "match": f"{l.home} v {l.away}",
                "league": l.league,
                "country": l.country,
                "kickoff": l.kickoff,
                "sel": l.sel,
                "label": l.label,
                "odds": round(l.odds, 2),
                "p_model": round(l.p_model, 3),
                "p_market": None if l.p_market is None else round(l.p_market, 3),
                "diff_pp": None if l.diff_pp is None else round(l.diff_pp, 1),
                "data_quality": l.data_quality,
            }
            for l in a.legs
        ],
    }


def _alt_to_dict(a: Alternative) -> dict:
    return {
        "match_id": a.match_id,
        "match": f"{a.home} v {a.away}",
        "league": a.league,
        "country": a.country,
        "kickoff": a.kickoff,
        "best_sel": a.best_sel,
        "best_label": a.best_label,
        "best_odds": round(a.best_odds, 2),
        "best_p_model": round(a.best_p_model, 3),
        "best_p_market": None if a.best_p_market is None else round(a.best_p_market, 3),
        "data_quality": a.data_quality,
    }


def _research_to_dict(r: MatchResearch) -> dict:
    return {
        "match_id": r.match_id,
        "match": f"{r.home} v {r.away}",
        "league": r.league,
        "kickoff": r.kickoff,
        "xg_home": round(r.xg_home, 2),
        "xg_away": round(r.xg_away, 2),
        "xg_total": round(r.xg_home + r.xg_away, 2),
        "p_o25_model": round(r.p_o25_model, 3) if r.p_o25_model == r.p_o25_model else None,
        "p_o25_market": None if r.p_o25_market is None or (isinstance(r.p_o25_market, float) and math.isnan(r.p_o25_market)) else round(r.p_o25_market, 3),
        "sporty_o25": _f2(r.sporty_o25),
        "sporty_1x2": [_f2(x) for x in r.sporty_1x2],
        "news": [
            {
                "team": n["team"],
                "title": html.escape(n["title"]),
                "source": html.escape(n["source"]),
                "when": n["when"].strftime("%d %b %H:%M") if n.get("when") else "",
                "link": n.get("link", ""),
            }
            for n in r.news
        ],
        "form_home": r.form_home,
        "form_away": r.form_away,
        "h2h": r.h2h,
        "data_quality": r.data_quality,
        "sample_home": r.sample_home,
        "sample_away": r.sample_away,
        "bullets": r.bullets,
    }


__all__ = [
    "daily_selection",
    "build_accumulators",
    "build_alternatives",
    "research_match",
    "Accumulator",
    "Alternative",
    "MatchResearch",
    "ACCUM_ODDS_LO",
    "ACCUM_ODDS_HI",
    "ACCUM_COUNT",
    "ALT_MIN",
]
