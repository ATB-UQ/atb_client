from __future__ import annotations

import time
from typing import List

import pytest
import respx

from atb_client import AsyncATBClient, ATBClient, _clock

BASE = "https://atb.test/api/v1"
KEY = "atb_abcd1234_" + "s" * 43


class FakeClock:
    """Replaces time.sleep / the monotonic clock / asyncio sleeping: sleeping advances
    the clock instantly and is recorded."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: List[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    async def async_sleep(self, seconds: float) -> None:
        self.sleep(seconds)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for var in ("ATB_API_KEY", "ATB_API_URL", "ATB_PROFILE", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ATB_CONFIG", str(tmp_path / "no-such-config.toml"))


@pytest.fixture(autouse=True)
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(time, "sleep", fake.sleep)
    monkeypatch.setattr(_clock, "monotonic", fake.monotonic)
    monkeypatch.setattr(_clock, "async_sleep", fake.async_sleep)
    return fake


@pytest.fixture
def api():
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def client(api) -> ATBClient:
    with ATBClient(api_key=KEY, base_url=BASE) as c:
        yield c


@pytest.fixture
def aclient(api) -> AsyncATBClient:
    return AsyncATBClient(api_key=KEY, base_url=BASE)


def problem(slug: str, status: int, **extra):
    body = {
        "type": f"https://atb.uq.edu.au/api/v1/errors/{slug}",
        "title": slug.replace("-", " "),
        "status": status,
        "detail": f"{slug} detail",
    }
    body.update(extra)
    return body


PROBLEM_HEADERS = {"Content-Type": "application/problem+json"}


def molecule(molid: int = 21, **extra):
    body = {
        "molid": molid,
        "inchi": "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
        "inchi_key": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
        "formula": "C2H6O",
        "common_name": "ethanol",
        "atoms": 9,
        "netcharge": 0,
        "public": True,
        "qm_level": 2,
        "maximum_qm_level": 2,
        "is_finished": True,
        "has_error": False,
        "submitted_at": "2026-09-01T02:03:04Z",
        "owned_by_caller": False,
        "forcefield": "54A7",
        "status": {
            "molid": molid,
            "stage": "finished",
            "terminal": True,
            "running": False,
            "detail": "The topology is complete.",
            "qm_level": 2,
            "maximum_qm_level": 2,
        },
        "topology_hash": "abc123",
        "links": {"self": f"/api/v1/molecules/{molid}"},
    }
    body.update(extra)
    return body


def status(stage: str, **extra):
    body = {"stage": stage, "terminal": stage in ("finished", "capped", "failed", "rejected")}
    body.update(extra)
    return body
