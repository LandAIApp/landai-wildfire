"""Smoke test against a RUNNING backend with real Earth Engine access.

    python backend/scripts/smoke_test.py [--base http://localhost:8000]
                                         [--department Tolima] [--municipality "San Luis"]
                                         [--fire-date 2026-08-05] [--end-date 2026-08-15]

Prints a summary of each endpoint. Exits non-zero on failure. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def call(method: str, url: str, body: dict | None = None, timeout: int = 900):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://localhost:8000')
    ap.add_argument('--department', default='Tolima')
    ap.add_argument('--municipality', default='San Luis')
    ap.add_argument('--fire-date', default='2026-08-05')
    ap.add_argument('--end-date', default='2026-08-15')
    a = ap.parse_args()
    body = {'department': a.department, 'municipality': a.municipality,
            'fire_date': a.fire_date, 'analysis_end': a.end_date}

    code, out = call('GET', f'{a.base}/health?check_ee=true')
    print('health        ', code, out)
    if out.get('status') != 'ok':
        print('Earth Engine is not initialized: check EE_PROJECT / credentials.')
        return 1

    code, out = call('GET', f'{a.base}/api/v1/administrative/departments')
    print('departments   ', code, len(out.get('departments', [])), 'departments')
    code, out = call('GET', f'{a.base}/api/v1/administrative/municipalities?department='
                     + urllib.parse.quote(a.department))
    print('municipalities', code, len(out.get('municipalities', [])), 'in', a.department)

    code, out = call('POST', f'{a.base}/api/v1/wildfire/preflight', body)
    print('preflight     ', code, {k: out.get(k) for k in
          ('valid', 'pre_count', 'post_count', 'history_count', 'aoi_hectares')})
    if code != 200 or not out.get('valid'):
        print('blocking:', out.get('blocking_errors'))
        return 1

    t0 = time.time()
    code, out = call('POST', f'{a.base}/api/v1/wildfire/analyze', body)
    print(f'analyze        {code} in {time.time() - t0:.0f}s')
    if code != 200:
        print(json.dumps(out, indent=2))
        return 1
    print('training      ', out['training'])
    for row in out['area_hectares']:
        print(f"  >= {row['threshold']:.2f}  {row['hectares']:>12,.1f} ha  ({row['label']})")
    print('layers        ', [l['id'] for l in out['layers']])
    print('warnings      ', [w['message'] for w in out['warnings']])
    return 0


if __name__ == '__main__':
    sys.exit(main())
