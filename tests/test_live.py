"""Smoke test against the deployed API. Skipped unless ATB_LIVE_TESTS=1 and a key is
configured (ATB_API_KEY or a profile). Read-only."""

from __future__ import annotations

import os

import pytest

# Captured at import, before conftest's autouse fixture scrubs the environment.
_ORIGINAL_ENV = {k: v for k, v in os.environ.items() if k.startswith("ATB_")}

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("ATB_LIVE_TESTS") != "1", reason="ATB_LIVE_TESTS != 1"),
]


@pytest.fixture
def live(monkeypatch):
    # conftest points ATB_CONFIG at nothing and clears the env; restore the real one.
    monkeypatch.delenv("ATB_CONFIG", raising=False)
    for var, value in _ORIGINAL_ENV.items():
        monkeypatch.setenv(var, value)
    from atb_client import ATBClient

    with ATBClient() as atb:
        yield atb


def test_ethanol(live):
    mol = live.molecules.get(21)
    assert mol.molid == 21
    status = live.molecules.status(21)
    assert status.stage
    names = {f.name for f in live.files.list(21)}
    assert "itp_aa" in names
