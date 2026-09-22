from __future__ import annotations

import httpx
import pytest

from atb_client import ChemistryRejected, DuplicateMolecule, JobFailed, Timeout
from atb_client.models import Job

from .conftest import molecule


def _accepted(job_id="01JOB"):
    return httpx.Response(202, headers={"Location": f"/api/v1/jobs/{job_id}"},
                          json={"id": job_id, "kind": "generate_topology", "state": "queued"})


def test_download_202_dance_to_completion(api, client, clock, tmp_path):
    files = api.get("/molecules/21/files/itp_aa")
    files.side_effect = [_accepted(), httpx.Response(200, content=b"[ moleculetype ]\n")]
    jobs = api.get("/jobs/01JOB")
    jobs.side_effect = [
        httpx.Response(200, json={"id": "01JOB", "state": "running"}),
        httpx.Response(200, json={"id": "01JOB", "state": "running"}),
        httpx.Response(200, json={"id": "01JOB", "state": "done",
                                  "result": {"href": "/api/v1/molecules/21/files/itp_aa"}}),
    ]
    path = client.files.download(21, "itp_aa", tmp_path / "lig.itp", timeout=300)
    assert path == tmp_path / "lig.itp"
    assert path.read_bytes() == b"[ moleculetype ]\n"
    assert jobs.call_count == 3
    assert clock.sleeps == [1.0, 2.0]  # 1 s → 30 s backoff
    assert files.calls[0].request.url.params["wait"] == "120"


def test_job_poll_backoff_caps_at_30s(api, client, clock):
    api.get("/molecules/21/files/itp_aa").mock(return_value=_accepted())
    jobs = api.get("/jobs/01JOB")
    jobs.side_effect = [httpx.Response(200, json={"id": "01JOB", "state": "running"})] * 8 + [
        httpx.Response(200, json={"id": "01JOB", "state": "done", "result": {}})]
    # the second GET (after the job) must succeed
    api.get("/molecules/21/files/itp_aa").side_effect = [_accepted(), httpx.Response(200, content=b"x")]
    assert client.files.download(21, "itp_aa", timeout=None) == b"x"
    assert clock.sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


def test_202_dance_to_timeout(api, client, clock):
    api.get("/molecules/21/files/itp_aa").mock(return_value=_accepted())
    api.get("/jobs/01JOB").respond(200, json={"id": "01JOB", "state": "running"})
    with pytest.raises(Timeout) as info:
        client.files.download(21, "itp_aa", timeout=45)
    assert info.value.job.id == "01JOB" and info.value.job.state == "running"
    assert sum(clock.sleeps) == pytest.approx(45)


def test_location_only_202(api, client):
    api.get("/molecules/21/files/lgf").side_effect = [
        httpx.Response(202, headers={"Location": "https://atb.test/api/v1/jobs/XYZ"}),
        httpx.Response(200, content=b"graph"),
    ]
    api.get("/jobs/XYZ").respond(200, json={"id": "XYZ", "state": "done"})
    assert client.files.download(21, "lgf") == b"graph"


def test_failed_job_raises_job_failed(api, client):
    api.get("/molecules/21/files/itp_aa").mock(return_value=_accepted())
    api.get("/jobs/01JOB").respond(200, json={"id": "01JOB", "state": "failed",
                                              "error": "generation crashed"})
    with pytest.raises(JobFailed) as info:
        client.files.download(21, "itp_aa")
    assert info.value.job.error == "generation crashed"


def test_failed_job_with_problem_maps_it(api, client):
    api.post("/molecules").mock(return_value=_accepted())
    api.get("/jobs/01JOB").respond(200, json={"id": "01JOB", "state": "failed", "error": {
        "type": "https://atb.uq.edu.au/api/v1/errors/duplicate-molecule", "status": 409,
        "title": "duplicate", "molid": 21}})
    api.get("/molecules/21").respond(200, json=molecule())
    with pytest.raises(DuplicateMolecule) as info:
        client.molecules.submit("ATOM", netcharge=0)
    assert info.value.molecule.molid == 21


def test_slow_submission_resolves_via_job(api, client):
    api.post("/molecules").mock(return_value=_accepted())
    api.get("/jobs/01JOB").respond(200, json={"id": "01JOB", "state": "done",
                                              "result": {"molid": 3002}})
    api.get("/molecules/3002").respond(200, json=molecule(3002))
    assert client.molecules.submit("ATOM", netcharge=0).molid == 3002


def test_structure_search_wait_false_returns_job(api, client, clock):
    route = api.post("/structures/search").mock(return_value=_accepted("S1"))
    jobs = api.get("/jobs/S1")
    jobs.side_effect = [
        httpx.Response(200, json={"id": "S1", "state": "running"}),
        httpx.Response(200, json={"id": "S1", "state": "done",
                                  "result": {"items": [{"molid": 21, "is_identical": True,
                                                        "rmsd": 0.0}]}}),
    ]
    job = client.structures.search("ATOM", netcharge="*", wait=False)
    assert isinstance(job, Job) and job.id == "S1"
    assert route.calls.last.request.url.params["wait"] == "0"
    assert jobs.call_count == 0
    assert job.result(timeout=60) == {"items": [{"molid": 21, "is_identical": True, "rmsd": 0.0}]}


def test_structure_search_blocking(api, client):
    api.post("/structures/search").respond(200, json={"items": [{"molid": 21, "rmsd": 0.01}]})
    matches = client.structures.search("ATOM", netcharge=0)
    assert matches[0].molid == 21 and matches[0].rmsd == 0.01


def test_chemistry_rejected_on_submit(api, client):
    api.post("/molecules").respond(422, json={
        "type": "https://atb.uq.edu.au/api/v1/errors/chemistry-rejected",
        "title": "Infeasible", "status": 422, "reason": "odd electron count at charge 0"})
    with pytest.raises(ChemistryRejected) as info:
        client.molecules.submit("ATOM", netcharge=0)
    assert info.value.reason == "odd electron count at charge 0"


def test_jobs_cancel(api, client):
    api.delete("/jobs/J").respond(200, json={"id": "J", "state": "failed", "error": "cancelled"})
    assert client.jobs.cancel("J").state == "failed"
