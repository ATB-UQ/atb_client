"""Offline tests added by the 2026-10 code review (wave 3).

Passing tests pin behaviour production callers rely on that had no test: the
never-retry rule of ``pipeline.qm.accept``, the job-following ``generate_topology`` /
``write_lgf`` the finish tail uses, and the fallback of the exception mapping for the
slugs the live server emits that ``exceptions._BY_SLUG`` does not list.

``xfail(strict=True)`` tests document defects found by the review (see
``WORKDIR/code_review_2026-10/atb_client.ALL.md``). Each starts to fail loudly, and
must lose its marker, when the defect is fixed.
"""

from __future__ import annotations

import httpx
import pytest

from atb_client import (
    ATBClient,
    ChemistryRejected,
    Conflict,
    NetworkError,
    RateLimited,
    ServiceUnavailable,
    TopologyVersionGone,
    ValidationError,
)

from .conftest import BASE, KEY, PROBLEM_HEADERS, problem

# --------------------------------------------------------------------------- pipeline retry rules


def test_qm_accept_is_sent_once_on_a_gateway_error(api, client, clock):
    route = api.post("/pipeline/qm/claims:accept").respond(
        503, json=problem("service-unavailable", 503), headers=PROBLEM_HEADERS
    )
    with pytest.raises(ServiceUnavailable):
        client.pipeline.qm.accept([1, 2], runner_id="r1")
    assert route.call_count == 1
    assert clock.sleeps == []


def test_qm_accept_is_sent_once_on_a_transport_error(api, client, clock):
    route = api.post("/pipeline/qm/claims:accept")
    route.side_effect = httpx.ConnectError("refused")
    with pytest.raises(NetworkError):
        client.pipeline.qm.accept([1], runner_id="r1")
    assert route.call_count == 1


def test_qm_release_is_retried_like_any_idempotent_call(api, client, clock):
    route = api.post("/pipeline/qm/claims:release")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json={"molids": [1]})]
    assert client.pipeline.qm.release([1]) == {"molids": [1]}
    assert route.call_count == 2


def test_qm_accept_sends_the_runner_and_integer_molids(api, client):
    route = api.post("/pipeline/qm/claims:accept").respond(200, json={"molids": [3]})
    assert client.pipeline.qm.accept(iter(["3"]), runner_id="abc") == {"molids": [3]}
    import json

    assert json.loads(route.calls.last.request.content) == {"molids": [3], "runner_id": "abc"}


# --------------------------------------------------------------------------- the finish tail


def _job(state, **extra):
    body = {"id": "01JOB", "kind": "generate_topology", "state": state}
    body.update(extra)
    return body


def test_generate_topology_answered_inline_returns_the_body(api, client):
    api.post("/pipeline/molecules/21/topology:generate").respond(200, json={"built": ["54A7"]})
    assert client.pipeline.molecules.generate_topology(21) == {"built": ["54A7"]}


def test_generate_topology_follows_a_202_job_to_its_result(api, client, clock):
    post = api.post("/pipeline/molecules/21/topology:generate")
    post.respond(202, json=_job("queued"), headers={"Location": "/api/v1/jobs/01JOB"})
    jobs = api.get("/jobs/01JOB")
    jobs.side_effect = [
        httpx.Response(200, json=_job("running")),
        httpx.Response(200, json=_job("done", result={"built": ["54A7"]})),
    ]
    assert client.pipeline.molecules.generate_topology(21, timeout=120) == {"built": ["54A7"]}
    assert post.calls.last.request.url.params["wait"] == "120"


def test_write_lgf_job_failure_raises_the_mapped_problem(api, client):
    api.post("/pipeline/molecules/21/lgf").respond(
        202, json=_job("queued", kind="lgf"), headers={"Location": "/api/v1/jobs/01JOB"}
    )
    api.get("/jobs/01JOB").respond(
        200,
        json=_job("failed", kind="lgf", error=problem("topology-generation-failed", 422)),
    )
    with pytest.raises(ChemistryRejected) as info:
        client.pipeline.molecules.write_lgf(21)
    assert info.value.status == 422


def test_generate_topology_times_out_when_the_job_never_ends(api, client, clock):
    from atb_client import Timeout

    api.post("/pipeline/molecules/21/topology:generate").respond(
        202, json=_job("queued"), headers={"Location": "/api/v1/jobs/01JOB"}
    )
    api.get("/jobs/01JOB").respond(200, json=_job("running"))
    with pytest.raises(Timeout) as info:
        client.pipeline.molecules.generate_topology(21, timeout=45)
    assert info.value.job is not None and info.value.job.state == "running"


# --------------------------------------------------------------------------- exception mapping

#: (slug, status) pairs the live server emits (website/website/api_v1, 2026-10-16) that
#: exceptions._BY_SLUG does not list: the status fallback must still give the right family.
UNLISTED_SERVER_SLUGS = [
    ("too-many-jobs", 429, RateLimited),
    ("submission-limit-reached", 429, RateLimited),
    ("job-interrupted", 503, ServiceUnavailable),
    ("structure-comparison-busy", 503, ServiceUnavailable),
    ("changes-window-exceeded", 410, TopologyVersionGone),
    ("molecule-claimed", 409, Conflict),
    ("deletion-blocked", 409, Conflict),
    ("callback-url-refused", 400, ValidationError),
    ("unknown-functional-group", 400, ValidationError),
    ("netcharge-mismatch", 422, ChemistryRejected),
    ("structure-timeout", 422, ChemistryRejected),
]


@pytest.mark.parametrize("slug,status,expected", UNLISTED_SERVER_SLUGS)
def test_unlisted_server_slug_falls_back_to_its_status_family(api, client, slug, status, expected):
    # 429/503 are retried: send them with a Retry-After over the cap so they raise at once.
    headers = dict(PROBLEM_HEADERS, **{"Retry-After": "3600"})
    api.get("/molecules/21/status").respond(status, json=problem(slug, status), headers=headers)
    with pytest.raises(expected) as info:
        client.molecules.status(21)
    assert info.value.slug == slug


# --------------------------------------------------------------------------- known defects (xfail)


@pytest.mark.xfail(strict=True, reason="review 2026-10 atb_client F1: page_of sends ?cursor=, "
                   "GET /molecules/changes takes ?since=, so .all() re-reads the first page")
def test_changes_all_passes_the_cursor_as_since(api, client):
    route = api.get("/molecules/changes")

    def answer(request):
        since = request.url.params.get("since")
        if since == "c1":
            return httpx.Response(200, json={"items": [{"molid": 2}], "next_cursor": "c2"})
        if since == "c2":
            return httpx.Response(200, json={"items": [], "next_cursor": "c2"})
        return httpx.Response(200, json={"items": [{"molid": 1}], "next_cursor": "c1"})

    route.side_effect = answer
    seen = []
    for change in client.molecules.changes().all():
        seen.append(change.molid)
        if len(seen) > 5:  # the defect loops for ever
            break
    assert seen == [1, 2]


@pytest.mark.xfail(strict=True, reason="review 2026-10 atb_client F2: Page.all() stops at an empty "
                   "page, but /admin/molecules/stalled scans a window and may return an empty "
                   "page that still has next_cursor")
def test_stalled_all_continues_past_an_empty_scan_window(api, client):
    route = api.get("/admin/molecules/stalled")
    route.side_effect = [
        httpx.Response(200, json={"items": [], "scanned": 2000, "next_cursor": "c1"}),
        httpx.Response(200, json={"items": [{"molid": 7, "status": {"stage": "stalled"}}],
                                  "scanned": 10, "next_cursor": None}),
    ]
    assert [item.molid for item in client.admin.molecules.stalled().all()] == [7]


@pytest.mark.xfail(strict=True, reason="review 2026-10 atb_client F3: ?wait= is sized from the "
                   "caller's deadline (up to 120 s) and ignores the client's read timeout "
                   "(default 30 s), so a request the server holds ends in ReadTimeout and a retry")
def test_wait_parameter_does_not_exceed_the_read_timeout(api):
    route = api.get("/molecules/21/files/mtb_aa").respond(200, content=b"x")
    with ATBClient(api_key=KEY, base_url=BASE) as default_client:
        default_client.files.download(21, "mtb_aa")  # timeout=300 by default
    wait = int(route.calls.last.request.url.params["wait"])
    assert wait < default_client._http.timeout.read
