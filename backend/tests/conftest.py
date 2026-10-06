"""Shared fixtures: the API/service layer is tested with Earth Engine mocked out."""
from datetime import date
from unittest.mock import MagicMock

import pytest

from app.schemas.wildfire import WildfireRequest


@pytest.fixture
def req() -> WildfireRequest:
    return WildfireRequest(department='Tolima', municipality='San Luis',
                           fire_date=date(2026, 8, 5), analysis_end=date(2026, 8, 15))


@pytest.fixture
def avail_ok() -> dict:
    return {'preScenes': 12, 'postScenes': 4, 'historyScenes': 30,
            'preStart': '2026-05-07', 'preEnd': '2026-07-28',
            'postStart': '2026-08-05', 'postEnd': '2026-08-15',
            'historyStart': '2026-02-05', 'historyEnd': '2026-07-20'}


@pytest.fixture
def mock_preflight_ee(monkeypatch):
    """Patch preflight so EE is never touched. Returns a setter for evaluate results."""
    from app.services import preflight

    state = {'responses': []}

    def fake_evaluate(_obj, _what='x'):
        resp = state['responses'].pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    monkeypatch.setattr(preflight, 'ee', MagicMock())
    monkeypatch.setattr(preflight, 'evaluate', fake_evaluate)
    monkeypatch.setattr(preflight.administrative, 'select_municipality',
                        lambda d, m: MagicMock())
    monkeypatch.setattr(preflight, 'get_input_availability', lambda *a, **k: MagicMock())

    def set_responses(*responses):
        state['responses'] = list(responses)
    return set_responses
