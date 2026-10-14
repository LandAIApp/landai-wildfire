"""Diagnose why Overpass rejects the request: prints HTTP status + body for several request variants.
Run once from the repo root:  python backend/scripts/diagnose_overpass.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.services import osm  # noqa: E402


def show(label: str, response: httpx.Response) -> None:
    print(f'--- {label}: HTTP {response.status_code}')
    print('   ', response.text[:400].replace('\n', ' '))


def main() -> int:
    s = Settings()
    bounds = (-75.2372, 4.4339, -75.2272, 4.4439)  # ~1 km box near Ibague
    count_q, _data_q = osm.build_queries(bounds, s)
    tiny = '[out:json][timeout:10];node(4.4339,-75.2372,4.4345,-75.2366);out count;'
    print('endpoint:', s.overpass_endpoint, '| user-agent:', s.overpass_user_agent)
    variants = [
        ('A) tiny query, UA+Accept json (as the app)', tiny, {'User-Agent': s.overpass_user_agent, 'Accept': 'application/json'}),
        ('B) tiny query, UA only', tiny, {'User-Agent': s.overpass_user_agent}),
        ('C) count query (as the app), UA only', count_q, {'User-Agent': s.overpass_user_agent}),
        ('D) count query, UA+Accept json', count_q, {'User-Agent': s.overpass_user_agent, 'Accept': 'application/json'}),
    ]
    for label, query, headers in variants:
        try:
            with httpx.Client(headers=headers, timeout=60) as client:
                show(label, client.post(s.overpass_endpoint, data={'data': query}))
        except httpx.HTTPError as exc:
            print(f'--- {label}: ERROR {type(exc).__name__}: {exc}')
    print('--- status page:')
    try:
        print('   ', httpx.get(s.overpass_endpoint.replace('/interpreter', '/status'),
                                headers={'User-Agent': s.overpass_user_agent}, timeout=20).text[:300].replace('\n', ' '))
    except httpx.HTTPError as exc:
        print('    ERROR', exc)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
