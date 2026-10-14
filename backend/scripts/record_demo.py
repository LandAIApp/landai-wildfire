"""Record a REAL wildfire + exposure result as a cached demo for the conference.

Requires a running backend with Earth Engine access and internet (Overpass / WorldPop):

    python backend/scripts/record_demo.py --base http://localhost:8000 \
        --department Tolima --municipality "San Luis" --fire-date 2026-08-05 --end-date 2026-08-15

Writes frontend/public/demo/exposure-demo.json. The file contains ONLY responses returned by the real
services at ``recorded_at`` (nothing is invented or edited) and is shown in the UI with a clear
"Recorded demo" label. Tile URLs expire, so the demo shows the exposure layers and metrics, not live tiles.
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / 'frontend' / 'public' / 'demo' / 'exposure-demo.json'


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f'{url} -> HTTP {e.code}: {e.read().decode()[:500]}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://localhost:8000')
    ap.add_argument('--department', required=True)
    ap.add_argument('--municipality', required=True)
    ap.add_argument('--fire-date', required=True)
    ap.add_argument('--end-date', required=True)
    ap.add_argument('--threshold', type=float, default=0.72)
    a = ap.parse_args()
    analysis = post(f'{a.base}/api/v1/wildfire/analyze', {
        'department': a.department, 'municipality': a.municipality,
        'fire_date': a.fire_date, 'analysis_end': a.end_date})
    exposure = post(f'{a.base}/api/v1/exposure/analyze', {'analysis_ref': analysis['analysis_ref'],
                                                            'threshold': a.threshold})
    analysis['layers'] = []          # signed tile URLs are temporary
    analysis['analysis_ref'] = None  # tokens expire and are server-specific
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        'recorded': True, 'recorded_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'recorded_from_live_services': True, 'event': f'{a.municipality}, {a.department}',
        'analysis': analysis, 'exposure': exposure}, ensure_ascii=False))
    print('written', OUT, f'({OUT.stat().st_size/1e6:.1f} MB)', '| exposure status:', exposure['status'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
