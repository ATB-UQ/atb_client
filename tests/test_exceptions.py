from __future__ import annotations

import httpx
import pytest

from atb_client import (
    APIError,
    AuthenticationError,
    ChemistryRejected,
    Conflict,
    DuplicateMolecule,
    MoleculeNotFound,
    NotFound,
    PayloadTooLarge,
    PermissionDenied,
    RateLimited,
    ServerError,
    ServiceUnavailable,
    TopologyVersionGone,
    ValidationError,
)
from atb_client.models import Molecule

from .conftest import PROBLEM_HEADERS, molecule, problem


@pytest.mark.parametrize(
    "slug,status_code,exc",
    [
        ("validation-error", 400, ValidationError),
        ("structure-too-large", 413, PayloadTooLarge),
        ("invalid-key", 401, AuthenticationError),
        ("insufficient-scope", 403, PermissionDenied),
        ("not-found", 404, NotFound),
        ("molecule-not-found", 404, MoleculeNotFound),
        ("duplicate-molecule", 409, DuplicateMolecule),
        ("generation-locked", 409, Conflict),
        ("topology-version-gone", 410, TopologyVersionGone),
        ("chemistry-rejected", 422, ChemistryRejected),
        ("rate-limited", 429, RateLimited),
        ("internal-error", 500, ServerError),
        ("service-unavailable", 503, ServiceUnavailable),
    ],
)
def test_slug_maps_to_exception(api, client, slug, status_code, exc):
    body = problem(slug, status_code, molid=5)
    api.get("/jobs/j").respond(status_code, json=body, headers=PROBLEM_HEADERS)
    with pytest.raises(exc) as info:
        client.jobs.get("j")
    err = info.value
    assert type(err) is exc
    assert err.status == status_code
    assert err.problem.type == body["type"]
    assert err.problem.detail == f"{slug} detail"
    assert err.slug == slug
    assert err.problem.model_extra["molid"] == 5


def test_slug_wins_over_status(api, client):
    # a 400 whose slug says "chemistry-rejected" is ChemistryRejected, not ValidationError
    api.get("/jobs/j").respond(400, json=problem("chemistry-rejected", 400))
    with pytest.raises(ChemistryRejected):
        client.jobs.get("j")


@pytest.mark.parametrize(
    "status_code,exc",
    [
        (400, ValidationError),
        (401, AuthenticationError),
        (403, PermissionDenied),
        (404, NotFound),
        (409, Conflict),
        (410, TopologyVersionGone),
        (413, PayloadTooLarge),
        (422, ChemistryRejected),
        (500, ServerError),
        (418, APIError),
    ],
)
def test_status_fallback(api, client, status_code, exc):
    api.get("/jobs/j").respond(status_code, json={"title": "something", "type": "about:blank"})
    with pytest.raises(exc) as info:
        client.jobs.get("j")
    assert type(info.value) is exc


def test_fastapi_default_422_is_validation(api, client):
    api.get("/jobs/j").respond(422, json={"detail": [{"loc": ["query", "limit"], "msg": "bad"}]})
    with pytest.raises(ValidationError) as info:
        client.jobs.get("j")
    assert info.value.errors == [{"loc": ["query", "limit"], "msg": "bad"}]


def test_non_json_error_body(api, client):
    api.get("/jobs/j").respond(500, text="<html>Internal Server Error</html>")
    with pytest.raises(ServerError) as info:
        client.jobs.get("j")
    assert "Internal Server Error" in info.value.problem.detail
    assert info.value.status == 500


def test_molecule_404_is_molecule_not_found(api, client):
    api.get("/molecules/99").respond(404, json={"title": "Not Found"})
    with pytest.raises(MoleculeNotFound):
        client.molecules.get(99)


def test_duplicate_molecule_lazy_fetch(api, client):
    api.post("/molecules").respond(
        409, json=problem("duplicate-molecule", 409, molid=21, compound_id=15),
        headers=PROBLEM_HEADERS,
    )
    get = api.get("/molecules/21").respond(200, json=molecule())
    with pytest.raises(DuplicateMolecule) as info:
        client.molecules.submit("ATOM ...", format="pdb", netcharge=0)
    dup = info.value
    assert dup.molid == 21 and dup.compound_id == 15
    assert get.call_count == 0  # lazy
    mol = dup.molecule
    assert isinstance(mol, Molecule) and mol.molid == 21
    assert dup.molecule is mol
    assert get.call_count == 1  # fetched once, then cached


def test_http_date_retry_after(api, client):
    api.get("/jobs/j").respond(
        503, headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"}
    )
    with pytest.raises(ServiceUnavailable) as info:
        client.jobs.get("j")
    assert info.value.retry_after > 60


def test_errors_carry_response(api, client):
    api.get("/jobs/j").respond(403, json=problem("forbidden", 403))
    with pytest.raises(PermissionDenied) as info:
        client.jobs.get("j")
    assert isinstance(info.value.response, httpx.Response)
