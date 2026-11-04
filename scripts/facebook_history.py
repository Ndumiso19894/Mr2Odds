"""Read Facebook posting claims from GitHub Actions, failing closed on uncertainty.

Claims are recorded before upload. They are used conservatively to avoid reusing a
match; results include only posts whose upload step GitHub reports as successful.
"""
from __future__ import annotations

import io
import json
import os
import zipfile

import requests

SLOTS = ('07', '12', '17')


def claim_names(day):
    prefix = 'facebook-post-' + day
    # The first three names are the original posting system and two approved corrections.
    return [prefix, prefix + '-retry', prefix + '-redesign'] + [prefix + '-' + s for s in SLOTS]


def _get(session, url, **kwargs):
    try:
        r = session.get(url, timeout=45, **kwargs)
        r.raise_for_status()
        return r
    except requests.RequestException:
        raise RuntimeError('Could not read Facebook posting records from GitHub; refusing to guess') from None


def _pages(session, url, key, params=None):
    for page in range(1, 101):
        r = _get(session, url, params={**(params or {}), 'per_page': 100, 'page': page})
        try:
            items = r.json()[key]
            if not isinstance(items, list):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise RuntimeError('Invalid GitHub posting records; refusing to guess') from None
        yield from items
        if len(items) < 100:
            return
    raise RuntimeError('Too many GitHub posting records; refusing to guess')


def load_claims(day, confirmed_only=False, session=None):
    token, repo = os.environ.get('GH_TOKEN', ''), os.environ.get('GITHUB_REPOSITORY', '')
    if not token or not repo:
        raise ValueError('GitHub token and repository are required to read earlier posting records')
    session = session or requests.Session()
    session.headers.update({'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'})
    base = f'https://api.github.com/repos/{repo}'
    claims = []
    for name in claim_names(day):
        arts = [a for a in _pages(session, base + '/actions/artifacts', 'artifacts', {'name': name})
                if a.get('name') == name and not a.get('expired')]
        if len(arts) > 1:
            raise RuntimeError('Duplicate Facebook claims require manual review')
        for art in arts:
            if confirmed_only:
                run_id = (art.get('workflow_run') or {}).get('id')
                if not isinstance(run_id, int):
                    raise RuntimeError('Cannot verify a Facebook posting claim')
                jobs = list(_pages(session, f'{base}/actions/runs/{run_id}/jobs', 'jobs'))
                steps = [s for j in jobs if j.get('name') == 'post' for s in j.get('steps', [])
                         if s.get('name') == 'Publish photo and caption to Facebook']
                if len(steps) != 1 or steps[0].get('conclusion') != 'success':
                    raise RuntimeError('A previous photo upload is unconfirmed; check the Page before publishing results')
            aid = art.get('id')
            if not isinstance(aid, int):
                raise RuntimeError('Invalid Facebook claim identifier')
            r = _get(session, f'{base}/actions/artifacts/{aid}/zip')
            try:
                if len(r.content) > 20_000_000:
                    raise ValueError('archive too large')
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    files = [n for n in z.namelist() if n == 'selections.json' or n.endswith('/selections.json')]
                    if len(files) != 1 or z.getinfo(files[0]).file_size > 1_000_000:
                        raise ValueError('missing manifest')
                    info = json.loads(z.read(files[0]))
                if info.get('date') != day or not isinstance(info.get('fixtures'), list):
                    raise ValueError('invalid manifest')
                claims.append({'name': name, 'manifest': info})
            except (ValueError, KeyError, zipfile.BadZipFile, UnicodeError):
                raise RuntimeError('Invalid Facebook claim manifest; refusing to guess') from None
    return claims


def match_key(item):
    """Fixture-level identity also handles old manifests that did not save an ID."""
    names = tuple(' '.join(str(item.get(k) or '').casefold().split()) for k in ('home', 'away'))
    if not all(names):
        raise ValueError('A prior claim has no usable match names')
    return names


def prior_matches(claims):
    return {match_key(item) for claim in claims for item in claim['manifest']['fixtures']}
