"""Temporary publication policy: senior men's domestic leagues and UEFA competitions.

The source exposes competition names and stage slugs but no reliable competition-type flag.
Screen known cup, international, women's and youth markers in both metadata and team names.
The policy is deliberately non-destructive: archived results and existing ledgers are retained.
"""
from __future__ import annotations

import re
import unicodedata


def _text(value) -> str:
    s = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


# Include slugs and country because feed stages often have a generic name like "Group A".
_PAUSED = re.compile(
    r'\b(?:women|womens|woman|ladies|female|feminine|feminin|femminile|femmes|femenina|femenino|feminina|feminino|'
    r'frauen|damen|damer|kvinde|kvinder|damallsvenskan|nwsl|wsl|girls|youth|junior|juniors|juvenil|'
    r'academy|cup|cups|copa|coppa|coupe|pokal|kupa|taca|trophy|shield|supercup|supercopa|supercoppa|supercoupe|recopa|'
    r'friendlies|friendly|olympics|olympic|libertadores|sudamericana)\b'
    r'|\b(?:u|under|sub)\s*(?:1[0-9]|2[0-3])\b'
    r'|\b(?:liga\s+f|we\s+league)\b'
    r'|\b(?:champions|europa|conference|nations)\s+league\b'
    r'|\b(?:world|european|african|asian|continental)\s+championship\b'
    r'|\b(?:world|european|african|asian)\s+(?:qualifiers?|qualification)\b'
)
_TEAM_PAUSED = re.compile(
    r'\b(?:women|womens|woman|ladies|female|feminine|feminin|femminile|femmes|femenina|femenino|feminina|feminino|frauen|girls|youth)\b'
    r'|\b(?:u|under|sub)\s*(?:1[0-9]|2[0-3])\b'
    r'|\(\s*w\s*\)\s*$|\s+w\s*$'
)
_CONTINENTS = {'world', 'international', 'europe', 'asia', 'africa', 'oceania',
               'north and central america', 'north central america', 'south america'}
# UEFA is an explicit exception, never an exception to the women's/youth pause.
_DEMOGRAPHIC_PAUSED = re.compile(
    r'\b(?:women|womens|woman|ladies|female|feminine|feminin|femminile|femmes|femenina|femenino|feminina|feminino|frauen|damen|damer|kvinde|kvinder|damallsvenskan|nwsl|wsl|girls|youth|junior|juniors|juvenil|academy)\b'
    r'|\b(?:u|under|sub)\s*(?:1[0-9]|2[0-3])\b|\b(?:liga\s+f|we\s+league)\b')
_UEFA_NAMED = re.compile(r'\buefa\b')
_UEFA_CLUB = re.compile(r'\b(?:champions|europa|conference)\s+league\b')


def allowed(country='', league='', div='', home='', away='', key='') -> bool:
    """Whether a fixture/stage is in scope, using all available source identifiers."""
    metadata = ' '.join(_text(v) for v in (country, league, div, key))
    if _DEMOGRAPHIC_PAUSED.search(metadata) or any(
        _TEAM_PAUSED.search(unicodedata.normalize('NFKD', str(t or '')).encode('ascii', 'ignore').decode().lower())
        for t in (home, away)
    ):
        return False
    category = _text(country)
    other_confederation = re.search(r'\b(?:afc|caf|concacaf|conmebol|ofc|fifa)\b', metadata)
    uefa = not other_confederation and (bool(_UEFA_NAMED.search(metadata)) or (
        category in {'europe', 'champions league', 'europa league', 'conference league', 'europa conference league'}
        and bool(_UEFA_CLUB.search(metadata))))
    if uefa:
        return True
    if category in _CONTINENTS or _PAUSED.search(metadata):
        return False
    return True


def allows_record(record) -> bool:
    get = record.get
    return allowed(get('country', ''), get('league', '') or get('competition', ''), get('div', ''),
                   get('home', ''), get('away', ''), get('key', ''))
