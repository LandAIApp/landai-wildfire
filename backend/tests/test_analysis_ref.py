import pytest

from app.core.errors import InvalidAnalysisRefError
from app.services import analysis_ref


def test_roundtrip_and_tamper_detection():
    token = analysis_ref.issue({'kind': 'drawn', 'x': 1})
    assert analysis_ref.verify(token)['x'] == 1
    head, sig = token.split('.')
    forged = analysis_ref._b64(analysis_ref._unb64(head).replace(b'"x":1', b'"x":2')) + '.' + sig
    with pytest.raises(InvalidAnalysisRefError):
        analysis_ref.verify(forged)
    with pytest.raises(InvalidAnalysisRefError):
        analysis_ref.verify('garbage')


def test_expiry():
    token = analysis_ref.issue({'a': 1}, now=1_000)
    with pytest.raises(InvalidAnalysisRefError):
        analysis_ref.verify(token, now=1_000 + 7 * 3600)
    assert analysis_ref.verify(token, now=1_000 + 60)['a'] == 1
