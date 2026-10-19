"""Rotamer jobs, the compound conformers and the Idempotency-Key header
(ROTAMER_SUBMISSION.md section 7)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from atb_client import (
    AsyncATBClient,
    CompoundNotFound,
    Conflict,
    IdempotencyKeyReused,
    PermissionDenied,
    RotamerJobExists,
    RotamerJobFailed,
    RotamerJobNotFound,
    ServiceUnavailable,
    Timeout,
    ValidationError,
)
from atb_client.cli import main
from atb_client.models import (
    CompoundConformers,
    Job,
    RotamerJob,
    RotamerJobPage,
    RotamerJobSummary,
)

from .conftest import BASE, KEY, PROBLEM_HEADERS, molecule, problem


def summary(job_id=3, state="searching", **extra):
    body = {
        "id": job_id,
        "state": state,
        "cancel_requested": False,
        "molid": 21,
        "compound_id": 7,
        "requested_as": "molid",
        "submission_budget": 20,
        "seed_budget": 500,
        "dry_run": False,
        "created_at": "2026-10-19T01:02:03Z",
        "finished_at": None,
        "settlement_reason": None,
        "coverage": {
            "selected": 0,
            "covered": 0,
            "submitted": 0,
            "existing": 0,
            "failed": 0,
            "reconcile": 0,
            "unresolved": 0,
        },
        "links": {"self": f"/api/v1/rotamer-jobs/{job_id}"},
    }
    body.update(extra)
    return body


def job(job_id=3, state="searching", **extra):
    body = summary(job_id, state)
    body.update(
        {
            "options": {"seed_source": "rotor", "window_kj": 25.0, "public": True},
            "search": {"stopped": "population", "n_minima": 4, "new_key": 1},
            "conformers": [
                {
                    "minimum_id": "m1",
                    "rank": 1,
                    "e_search_kj": 0.0,
                    "degeneracy": 2,
                    "population": 0.6,
                    "eligible": True,
                    "selected": True,
                    "outcome": "submitted",
                    "molid": 22,
                    "hidden": False,
                    "driver": {"attempts": 1, "claimed_at": "2026-10-19T02:00:00Z"},
                }
            ],
            "progress": {"settled": 0, "pending": 1, "all_settled": False},
            "advice": {
                "version": 1,
                "seed_budget": {"verdict": "unlikely", "reasons": ["a"], "metrics": {"n": 1}},
            },
        }
    )
    body.update(extra)
    return body


# ------------------------------------------------------------------ admin


def test_admin_create_sends_the_documented_body(api, client):
    route = api.post("/admin/rotamer-jobs").respond(
        201, json=job(state="queued"), headers={"Location": "/api/v1/rotamer-jobs/3"}
    )
    result = client.admin.rotamer_jobs.create(molid=21)
    assert isinstance(result, RotamerJob) and result.state == "queued"
    assert json.loads(route.calls[0].request.content) == {
        "molid": 21,
        "submission_budget": 20,
        "seed_budget": 500,
        "seed_source": "rotor",
        "window_kj": 25.0,
        "dry_run": False,
        "force": False,
    }
    assert result.conformers[0].driver.attempts == 1
    assert result.search.model_extra == {"new_key": 1}  # a field added later passes through


def test_admin_create_by_compound_with_every_option(api, client):
    route = api.post("/admin/rotamer-jobs").respond(201, json=job(requested_as="compound_id"))
    client.admin.rotamer_jobs.create(
        compound_id=7,
        submission_budget=5,
        seed_budget=100,
        seed_source="union",
        window_kj=10,
        max_qm_level=1,
        public=False,
        dry_run=True,
        force=True,
    )
    body = json.loads(route.calls[0].request.content)
    assert body["compound_id"] == 7 and "molid" not in body
    assert body["public"] is False and body["max_qm_level"] == 1 and body["dry_run"] is True


def test_admin_create_403_is_permission_denied(api, client):
    api.post("/admin/rotamer-jobs").respond(
        403, json=problem("insufficient-scope", 403), headers=PROBLEM_HEADERS
    )
    with pytest.raises(PermissionDenied):
        client.admin.rotamer_jobs.create(molid=21)


@pytest.mark.parametrize(
    "slug,status,cls",
    [
        ("target-required", 422, ValidationError),
        ("no-searchable-molecule", 422, ValidationError),
        ("private-parent", 422, ValidationError),
        ("idempotency-key-reused", 422, IdempotencyKeyReused),
        ("rotamer-job-exists", 409, RotamerJobExists),
        ("rotamer-job-finished", 409, Conflict),
        ("rotamer-job-not-found", 404, RotamerJobNotFound),
        ("compound-not-found", 404, CompoundNotFound),
        ("schema-missing", 503, ServiceUnavailable),
    ],
)
def test_new_slugs_map_to_classes(api, client, slug, status, cls):
    headers = {"Retry-After": "0"} if status == 503 else {}
    api.post("/admin/rotamer-jobs").respond(status, json=problem(slug, status), headers=headers)
    with pytest.raises(cls) as info:
        client.admin.rotamer_jobs.create(molid=21)
    assert type(info.value) is cls and info.value.slug == slug


def test_rotamer_job_exists_names_the_job(api, client):
    api.post("/admin/rotamer-jobs").respond(
        409, json=problem("rotamer-job-exists", 409, job_id=3, state="complete")
    )
    with pytest.raises(RotamerJobExists) as info:
        client.admin.rotamer_jobs.create(compound_id=7)
    assert (info.value.job_id, info.value.state) == (3, "complete")


def test_admin_cancel(api, client):
    route = api.delete("/admin/rotamer-jobs/3").respond(
        202, json=job(cancel_requested=True)
    )
    result = client.admin.rotamer_jobs.cancel(3)
    assert route.called and result.cancel_requested is True


def test_admin_cancel_finished_is_a_conflict(api, client):
    api.delete("/admin/rotamer-jobs/3").respond(409, json=problem("rotamer-job-finished", 409))
    with pytest.raises(Conflict):
        client.admin.rotamer_jobs.cancel(3)


# ------------------------------------------------------------------ read


def test_list_sends_filters_and_pages_by_offset(api, client):
    route = api.get("/rotamer-jobs")
    route.side_effect = [
        httpx.Response(
            200,
            json={"items": [summary(5), summary(4)], "total": 3, "limit": 2, "offset": 0},
        ),
        httpx.Response(
            200, json={"items": [summary(3)], "total": 3, "limit": 2, "offset": 2}
        ),
    ]
    page = client.rotamer_jobs.list(molid=21, state="searching", limit=2)
    assert isinstance(page, RotamerJobPage) and page.total == 3
    assert isinstance(page.items[0], RotamerJobSummary)
    assert dict(route.calls[0].request.url.params) == {
        "molid": "21",
        "state": "searching",
        "limit": "2",
    }
    assert [j.id for j in page.all()] == [5, 4, 3]
    assert route.calls[1].request.url.params["offset"] == "2"
    assert route.calls[1].request.url.params["molid"] == "21"


def test_list_empty_means_no_job(api, client):
    api.get("/rotamer-jobs").respond(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})
    page = client.rotamer_jobs.list(compound_id=7)
    assert page.total == 0 and not page and page.next_cursor is None


def test_get(api, client):
    api.get("/rotamer-jobs/3").respond(200, json=job())
    result = client.rotamer_jobs.get(3)
    assert result.progress.pending == 1 and result.advice.seed_budget.verdict == "unlikely"
    assert result.conformers[0].molid == 22


def test_get_unknown(api, client):
    api.get("/rotamer-jobs/9").respond(404, json=problem("rotamer-job-not-found", 404, job_id=9))
    with pytest.raises(RotamerJobNotFound) as info:
        client.rotamer_jobs.get(9)
    assert info.value.job_id == 9


# ------------------------------------------------------------------ wait


def test_wait_polls_until_submitted(api, client, clock):
    route = api.get("/rotamer-jobs/3")
    route.side_effect = [
        httpx.Response(200, json=job(state="searching")),
        httpx.Response(200, json=job(state="submitting")),
        httpx.Response(200, json=job(state="submitted")),
    ]
    assert client.rotamer_jobs.wait(3).state == "submitted"
    assert clock.sleeps == [15.0, 15.0]


def test_wait_submitted_accepts_a_later_state(api, client, clock):
    api.get("/rotamer-jobs/3").respond(200, json=job(state="complete"))
    assert client.rotamer_jobs.wait(3, until="submitted").state == "complete"
    assert clock.sleeps == []


def test_wait_complete_keeps_polling_through_submitted(api, client, clock):
    route = api.get("/rotamer-jobs/3")
    route.side_effect = [
        httpx.Response(200, json=job(state="submitted")),
        httpx.Response(200, json=job(state="complete")),
    ]
    assert client.rotamer_jobs.wait(3, until="complete", interval=5).state == "complete"
    assert clock.sleeps == [5]


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_wait_raises_on_failed_or_cancelled(api, client, state):
    api.get("/rotamer-jobs/3").respond(200, json=job(state=state, error="boom"))
    with pytest.raises(RotamerJobFailed) as info:
        client.rotamer_jobs.wait(3, until="complete")
    assert info.value.job.state == state


def test_wait_times_out(api, client, clock):
    api.get("/rotamer-jobs/3").respond(200, json=job(state="searching"))
    with pytest.raises(Timeout) as info:
        client.rotamer_jobs.wait(3, timeout=40, interval=15)
    assert info.value.rotamer_job.state == "searching"
    assert sum(clock.sleeps) == 40


def test_wait_rejects_other_targets(client):
    with pytest.raises(ValueError):
        client.rotamer_jobs.wait(3, until="searching")


def test_async_wait_and_list(api, clock):
    async def main_():
        async with AsyncATBClient(api_key=KEY, base_url=BASE) as atb:
            api.get("/rotamer-jobs/3").side_effect = [
                httpx.Response(200, json=job(state="selecting")),
                httpx.Response(200, json=job(state="complete")),
            ]
            api.get("/rotamer-jobs").respond(
                200, json={"items": [summary()], "total": 1, "limit": 100, "offset": 0}
            )
            done = await atb.rotamer_jobs.wait(3, until="complete")
            page = await atb.rotamer_jobs.list(molid=21)
            return done, [j async for j in page.all()]

    done, items = asyncio.run(main_())
    assert done.state == "complete" and [j.id for j in items] == [3]


# ------------------------------------------------------------------ compounds


def conformers_body(offset=0, items=None, total=3):
    return {
        "compound_id": 7,
        "qm_type": "wB97X_631Gd_SMD_water",
        "energy_unit": "kJ/mol",
        "e_min": -100.0,
        "total": total,
        "limit": 2,
        "offset": offset,
        "items": items
        or [
            {"molid": 21, "energy": -100.0, "relative_energy": 0.0, "qm_level": 2},
            {"molid": 22, "energy": -98.0, "relative_energy": 2.0, "rotamer_job_id": 3},
        ],
    }


def test_compound_conformers_params_and_paging(api, client):
    route = api.get("/compounds/7/conformers")
    route.side_effect = [
        httpx.Response(200, json=conformers_body()),
        httpx.Response(200, json=conformers_body(2, [{"molid": 23}])),
    ]
    page = client.compounds.conformers(
        7, max_relative_energy=5.0, qm_type="wB97X_321G_SMD_water", include_unscored=False, limit=2
    )
    assert isinstance(page, CompoundConformers) and page.e_min == -100.0
    assert dict(route.calls[0].request.url.params) == {
        "max_relative_energy": "5.0",
        "qm_type": "wB97X_321G_SMD_water",
        "include_unscored": "false",
        "limit": "2",
    }
    assert [c.molid for c in page.all()] == [21, 22, 23]
    assert route.calls[1].request.url.params["offset"] == "2"
    assert page.items[1].rotamer_job_id == 3


def test_compound_conformers_defaults(api, client):
    route = api.get("/compounds/7/conformers").respond(200, json=conformers_body(items=[], total=0))
    client.compounds.conformers(7)
    assert dict(route.calls[0].request.url.params) == {"include_unscored": "true"}


def test_compound_not_found(api, client):
    api.get("/compounds/8/conformers").respond(
        404, json=problem("compound-not-found", 404, compound_id=8)
    )
    with pytest.raises(CompoundNotFound) as info:
        client.compounds.conformers(8)
    assert info.value.compound_id == 8


# ------------------------------------------------------------------ molecules.conformations


def test_conformations_without_new_params_sends_none(api, client):
    route = api.get("/molecules/21/conformations").respond(
        200, json={"molid": 21, "compound_id": 7, "qm_type": "x", "items": [{"molid": 21}]}
    )
    assert client.molecules.conformations(21).items[0].molid == 21
    assert dict(route.calls[0].request.url.params) == {}


def test_conformations_with_filters(api, client):
    route = api.get("/molecules/21/conformations").respond(200, json={"molid": 21, "items": []})
    client.molecules.conformations(
        21, max_relative_energy=10, qm_type="b3lyp_631Gd_PCM_water", include_unscored=False
    )
    assert dict(route.calls[0].request.url.params) == {
        "max_relative_energy": "10",
        "qm_type": "b3lyp_631Gd_PCM_water",
        "include_unscored": "false",
    }


# ------------------------------------------------------------------ submit


def test_submit_sends_idempotency_key(api, client):
    route = api.post("/molecules").respond(201, json=molecule(31))
    client.molecules.submit("ATOM", netcharge=0, idempotency_key="run-42")
    request = route.calls[0].request
    assert request.headers["Idempotency-Key"] == "run-42"
    assert "idempotency" not in json.loads(request.content)


def test_submit_without_key_sends_no_header(api, client):
    route = api.post("/molecules").respond(201, json=molecule(31))
    client.molecules.submit("ATOM", netcharge=0)
    assert "Idempotency-Key" not in route.calls[0].request.headers
    assert route.calls[0].request.url.params["wait"] == "120"


def test_submit_key_reused(api, client):
    api.post("/molecules").respond(
        422, json=problem("idempotency-key-reused", 422, job_id="01J")
    )
    with pytest.raises(IdempotencyKeyReused) as info:
        client.molecules.submit("ATOM", netcharge=0, idempotency_key="k")
    assert info.value.job_id == "01J"


def test_submit_no_wait_returns_the_pending_job(api, client):
    route = api.post("/molecules").respond(
        202,
        json={"id": "01JOB", "kind": "submit", "state": "queued"},
        headers={"Location": "/api/v1/jobs/01JOB", "Idempotent-Replayed": "true"},
    )
    result = client.molecules.submit("ATOM", netcharge=0, idempotency_key="k", wait=False)
    assert isinstance(result, Job) and result.id == "01JOB" and result.state == "queued"
    assert route.calls[0].request.url.params["wait"] == "0"
    assert route.calls[0].request.headers["Idempotency-Key"] == "k"


def test_submit_no_wait_still_returns_a_molecule_on_201(api, client):
    api.post("/molecules").respond(201, json=molecule(31))
    assert client.molecules.submit("ATOM", netcharge=0, wait=False).molid == 31


def test_async_submit_with_key_and_no_wait(api):
    async def main_():
        async with AsyncATBClient(api_key=KEY, base_url=BASE) as atb:
            route = api.post("/molecules").respond(
                202, json={"id": "01JOB", "state": "queued"}, headers={"Location": "/api/v1/jobs/01JOB"}
            )
            result = await atb.molecules.submit(
                "ATOM", netcharge=0, idempotency_key="k", wait=False
            )
            return result, route.calls[0].request

    result, request = asyncio.run(main_())
    assert result.id == "01JOB" and request.headers["Idempotency-Key"] == "k"


# ------------------------------------------------------------------ CLI


@pytest.fixture
def env(monkeypatch, api):
    monkeypatch.setenv("ATB_API_KEY", KEY)
    monkeypatch.setenv("ATB_API_URL", BASE)
    return api


def out_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_cli_admin_create(env, capsys):
    route = env.post("/admin/rotamer-jobs").respond(201, json=job(state="queued"))
    assert main(["admin", "rotamer-jobs", "create", "--molid", "21", "--dry-run", "--private"]) == 0
    body = json.loads(route.calls[0].request.content)
    assert body["molid"] == 21 and body["dry_run"] is True and body["public"] is False
    assert out_json(capsys)["id"] == 3


def test_cli_admin_create_needs_exactly_one_target(env, capsys):
    assert main(["admin", "rotamer-jobs", "create"]) == 2
    assert main(["admin", "rotamer-jobs", "create", "--molid", "1", "--compound-id", "2"]) == 2


def test_cli_admin_create_forbidden_is_1(env, capsys):
    env.post("/admin/rotamer-jobs").respond(403, json=problem("insufficient-scope", 403))
    assert main(["admin", "rotamer-jobs", "create", "--compound-id", "7"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "insufficient-scope"


def test_cli_admin_cancel(env, capsys):
    env.delete("/admin/rotamer-jobs/3").respond(202, json=job(cancel_requested=True))
    assert main(["admin", "rotamer-jobs", "cancel", "3"]) == 0
    assert out_json(capsys)["cancel_requested"] is True


def test_cli_list_all(env, capsys):
    route = env.get("/rotamer-jobs")
    route.side_effect = [
        httpx.Response(200, json={"items": [summary(2)], "total": 2, "limit": 1, "offset": 0}),
        httpx.Response(200, json={"items": [summary(1)], "total": 2, "limit": 1, "offset": 1}),
    ]
    assert main(["rotamer-jobs", "list", "--molid", "21", "--limit", "1", "--all"]) == 0
    assert [j["id"] for j in out_json(capsys)] == [2, 1]


def test_cli_get_and_wait_exit_codes(env, capsys, clock):
    env.get("/rotamer-jobs/3").respond(200, json=job(state="searching"))
    assert main(["rotamer-jobs", "get", "3"]) == 0
    env.get("/rotamer-jobs/3").respond(200, json=job(state="failed"))
    assert main(["rotamer-jobs", "get", "3", "--wait", "complete"]) == 5
    env.get("/rotamer-jobs/3").respond(200, json=job(state="searching"))
    assert main(["rotamer-jobs", "get", "3", "--wait", "complete", "--wait-timeout", "1"]) == 4
    assert json.loads(capsys.readouterr().err.split("\n}\n")[-2] + "\n}")["error"] == "timeout"


def test_cli_compound_conformers(env, capsys):
    route = env.get("/compounds/7/conformers").respond(200, json=conformers_body(total=2))
    assert (
        main(
            [
                "compounds",
                "conformers",
                "7",
                "--max-relative-energy",
                "5",
                "--scored-only",
                "--all",
            ]
        )
        == 0
    )
    assert [c["molid"] for c in out_json(capsys)] == [21, 22]
    params = route.calls[0].request.url.params
    assert params["include_unscored"] == "false" and params["max_relative_energy"] == "5.0"


def test_cli_submit_idempotency_key(env, capsys, tmp_path):
    structure = tmp_path / "x.pdb"
    structure.write_text("ATOM")
    route = env.post("/molecules").respond(201, json=molecule(31))
    assert main(["submit", str(structure), "--charge", "0", "--idempotency-key", "k"]) == 0
    assert route.calls[0].request.headers["Idempotency-Key"] == "k"
