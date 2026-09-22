from __future__ import annotations

import httpx
import pytest

from atb_client import (
    ATBClient,
    NetworkError,
    NotFound,
    RateLimited,
    ServiceUnavailable,
    ValidationError,
    __version__,
)

from .conftest import BASE, KEY, PROBLEM_HEADERS, molecule, problem


def test_headers_and_default_timeouts(api, client):
    route = api.get("/molecules/21").respond(200, json=molecule())
    client.molecules.get(21)
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.headers["User-Agent"].startswith(f"atb-client/{__version__} python/")
    assert str(request.url) == f"{BASE}/molecules/21"
    timeout = client._http.timeout
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (10, 30, 30, 10)


def test_timeout_is_overridable():
    c = ATBClient(api_key=KEY, base_url=BASE, timeout=90)
    assert (c._http.timeout.connect, c._http.timeout.read) == (10, 90)
    c2 = ATBClient(api_key=KEY, base_url=BASE, timeout=httpx.Timeout(5.0))
    assert c2._http.timeout.read == 5.0


@pytest.mark.parametrize("status_code", [502, 503, 504])
def test_retries_gateway_errors_with_backoff(api, client, clock, status_code):
    route = api.get("/molecules/21")
    route.side_effect = [
        httpx.Response(status_code),
        httpx.Response(status_code),
        httpx.Response(200, json=molecule()),
    ]
    assert client.molecules.get(21).molid == 21
    assert route.call_count == 3
    assert len(clock.sleeps) == 2
    # exponential with equal jitter: attempt n sleeps in [b*2^(n-1)/2, b*2^(n-1)], b=0.5
    assert 0.25 <= clock.sleeps[0] <= 0.5
    assert 0.5 <= clock.sleeps[1] <= 1.0


def test_gives_up_after_five_attempts(api, client, clock):
    route = api.get("/molecules/21").respond(
        503, json=problem("service-unavailable", 503), headers=PROBLEM_HEADERS
    )
    with pytest.raises(ServiceUnavailable) as info:
        client.molecules.get(21)
    assert route.call_count == 5
    assert len(clock.sleeps) == 4
    assert info.value.status == 503


def test_retry_after_is_honoured(api, client, clock):
    route = api.get("/molecules/21")
    route.side_effect = [
        httpx.Response(429, json=problem("rate-limited", 429), headers={"Retry-After": "7"}),
        httpx.Response(200, json=molecule()),
    ]
    client.molecules.get(21)
    assert clock.sleeps == [7.0]


def test_retry_after_on_503_is_honoured(api, client, clock):
    route = api.get("/molecules/21")
    route.side_effect = [
        httpx.Response(503, headers={"Retry-After": "3"}),
        httpx.Response(200, json=molecule()),
    ]
    client.molecules.get(21)
    assert clock.sleeps == [3.0]


def test_long_retry_after_is_raised_not_slept(api, client, clock):
    api.get("/molecules/21").respond(
        429,
        json=problem("daily-limit-exceeded", 429, limit="daily"),
        headers={"Retry-After": "40000", **PROBLEM_HEADERS},
    )
    with pytest.raises(RateLimited) as info:
        client.molecules.get(21)
    assert clock.sleeps == []
    assert info.value.retry_after == 40000.0
    assert info.value.limit == "daily"


@pytest.mark.parametrize("status_code,exc", [(400, ValidationError), (404, NotFound)])
def test_never_retries_other_4xx(api, client, clock, status_code, exc):
    route = api.get("/jobs/x").respond(status_code, json={"title": "no"})
    with pytest.raises(exc):
        client.jobs.get("x")
    assert route.call_count == 1
    assert clock.sleeps == []


def test_transport_errors_retried_then_network_error(api, client, clock):
    route = api.get("/molecules/21").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(NetworkError) as info:
        client.molecules.get(21)
    assert route.call_count == 5
    assert isinstance(info.value.__cause__, httpx.ConnectError)


def test_transport_error_then_success(api, client, clock):
    route = api.get("/molecules/21")
    route.side_effect = [httpx.ReadTimeout("slow"), httpx.Response(200, json=molecule())]
    assert client.molecules.get(21).molid == 21
    assert len(clock.sleeps) == 1


def test_max_attempts_configurable(api, clock):
    c = ATBClient(api_key=KEY, base_url=BASE, max_attempts=1)
    route = api.get("/molecules/21").respond(503)
    with pytest.raises(ServiceUnavailable):
        c.molecules.get(21)
    assert route.call_count == 1
