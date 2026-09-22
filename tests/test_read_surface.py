"""The WP2 read surface, with response bodies shaped as the server's schema declares
them (tests/data/openapi.json)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from atb_client import MoleculeNotFound, NotFound
from atb_client.models import (
    ArchetypeDetail,
    ArchetypePage,
    BondedParameters,
    Conformations,
    ForcefieldList,
    Health,
    LibraryVersions,
    Me,
    MotifDetail,
    MotifPage,
    QMSummary,
    QuotaRequestReceived,
    RMSDResult,
    Solvation,
    Statistics,
    TautomerGroup,
    Tautomers,
    Topologies,
    Usage,
    Validation,
)

from .conftest import PROBLEM_HEADERS, molecule, problem

UTC = timezone.utc


def test_molecule_timestamps_are_aware_utc(api, client):
    api.get("/molecules/21").respond(
        200, json=molecule(21, finished_at="2026-09-02T03:04:05Z", maximum_qm_level=1)
    )
    mol = client.molecules.get(21)
    assert mol.submitted_at == datetime(2026, 9, 1, 2, 3, 4, tzinfo=UTC)
    assert mol.finished_at.tzinfo is not None and mol.finished_at.utcoffset().total_seconds() == 0
    assert mol.maximum_qm_level == 1
    assert mol.status.running is False and mol.status.qm_level == 2
    assert mol.links["self"] == "/api/v1/molecules/21"


def test_search_projection_parses(api, client):
    route = api.get("/molecules").respond(
        200, json={"items": [{"molid": 1, "formula": "CH4"}], "next_cursor": None, "total": 1}
    )
    page = client.molecules.search(
        common_name="meth", match="partial", fields=["formula"], owner="me"
    )
    assert page[0].formula == "CH4" and page[0].status is None
    assert page.total == 1
    assert dict(route.calls.last.request.url.params) == {
        "common_name": "meth",
        "match": "partial",
        "fields": "formula",
        "owner": "me",
    }


def test_search_sends_datetimes_as_iso(api, client):
    route = api.get("/molecules").respond(200, json={"items": []})
    client.molecules.search(submitted_after=datetime(2026, 9, 1, tzinfo=UTC))
    assert route.calls.last.request.url.params["submitted_after"] == "2026-09-01T00:00:00+00:00"


def test_changes_all_stops_at_an_empty_page(api, client):
    route = api.get("/molecules/changes")
    route.side_effect = [
        _json({"items": [{"molid": 1, "stage": "qm0", "changed_at": None}], "next_cursor": "c1"}),
        _json({"items": [], "next_cursor": "c2"}),
    ]
    assert [c.molid for c in client.molecules.changes().all()] == [1]
    assert route.call_count == 2
    assert route.calls.last.request.url.params["cursor"] == "c1"


def _json(body, status=200):
    import httpx

    return httpx.Response(status, json=body)


def test_topologies(api, client):
    api.get("/molecules/21/topologies").respond(
        200,
        json={
            "molid": 21,
            "items": [
                {
                    "hash": "abc12",
                    "forcefield": "54A7",
                    "generated_at": "2026-09-01T00:00:00Z",
                    "atb_version": "3.0",
                    "current": True,
                },
                {
                    "hash": "old01",
                    "forcefield": "54A7",
                    "generated_at": None,
                    "atb_version": "2.2",
                    "current": False,
                },
            ],
        },
    )
    topologies = client.molecules.topologies(21)
    assert isinstance(topologies, Topologies)
    assert [t.hash for t in topologies] == ["abc12", "old01"]
    assert [t.hash for t in topologies.current] == ["abc12"]


@pytest.mark.parametrize("level,sent", [(1, "qm1"), ("qm2", "qm2"), (None, None)])
def test_qm_level_is_sent_as_qmN(api, client, level, sent):
    route = api.get("/molecules/21/qm").respond(
        200,
        json={
            "molid": 21,
            "levels": [
                {
                    "level": "qm1",
                    "qm_type": "B3LYP_631Gd_SMD_water",
                    "charge_method": "MK",
                    "volume": 81.5,
                    "n_atoms": 9,
                    "energy": -405123.4,
                    "contents": ["charge", "hessian"],
                }
            ],
        },
    )
    qm = client.molecules.qm(21, level=level)
    assert isinstance(qm, QMSummary) and qm.levels[0].energy == -405123.4
    assert route.calls.last.request.url.params.get("level") == sent


def test_validation_solvation_parameters_tautomers_conformations(api, client):
    api.get("/molecules/21/validation").respond(
        200,
        json={
            "molid": 21,
            "emin_vac": {
                "rmsd_nm": 0.012,
                "completed_at": "2026-09-01T00:00:00Z",
                "superposition": {"minimised": "/api/v1/molecules/21/files/emin_vac"},
            },
        },
    )
    api.get("/molecules/21/solvation").respond(
        200,
        json={
            "molid": 21,
            "results": [
                {
                    "id": 5,
                    "solvent": "H2O",
                    "value": -21.3,
                    "current": True,
                    "experimental": {"value": -20.9, "doi": "10.1/x"},
                }
            ],
            "experimental": [{"value": -20.9, "solvent": "H2O"}],
        },
    )
    params = api.get("/molecules/21/parameters").respond(
        200, json={"molid": 21, "forcefield": "54A7", "topology_hash": "abc12", "record": {}}
    )
    api.get("/molecules/21/tautomers").respond(
        200,
        json={
            "molid": 21,
            "grouping": "skeleton_key",
            "group": "k",
            "members": [{"molid": 21, "energies": {"wB97X_631Gd_SMD_water": -1.5}}],
        },
    )
    api.get("/molecules/21/conformations").respond(
        200,
        json={
            "molid": 21,
            "compound_id": 15,
            "qm_type": "wB97X_631Gd_SMD_water",
            "items": [{"molid": 21, "energy": None}],
        },
    )
    validation = client.molecules.validation(21)
    assert isinstance(validation, Validation) and validation.emin_vac.rmsd_nm == 0.012
    solvation = client.molecules.solvation(21)
    assert isinstance(solvation, Solvation)
    assert solvation.results[0].experimental.value == -20.9
    assert isinstance(client.molecules.parameters(21, ff="54A7", hash="abc12"), BondedParameters)
    assert dict(params.calls.last.request.url.params)["ff"] == "54A7"
    assert dict(params.calls.last.request.url.params)["hash"] == "abc12"
    tautomers = client.molecules.tautomers(21)
    assert isinstance(tautomers, Tautomers)
    assert tautomers.members[0].energies["wB97X_631Gd_SMD_water"] == -1.5
    assert isinstance(client.molecules.conformations(21), Conformations)


def test_sub_resource_404_is_molecule_not_found(api, client):
    api.get("/molecules/9/qm").respond(
        404, json=problem("molecule-not-found", 404, molid=9), headers=PROBLEM_HEADERS
    )
    with pytest.raises(MoleculeNotFound) as info:
        client.molecules.qm(9)
    assert info.value.molid == 9


def test_topology_version_gone_on_a_pinned_hash(api, client):
    from atb_client import TopologyVersionGone

    api.get("/molecules/21/parameters").respond(
        410, json=problem("topology-version-gone", 410), headers=PROBLEM_HEADERS
    )
    with pytest.raises(TopologyVersionGone):
        client.molecules.parameters(21, hash="gone1")


# --------------------------------------------------------------------------- reference data


def test_forcefields_list(api, client):
    api.get("/forcefields").respond(
        200,
        json={
            "items": [
                {
                    "name": "54A7",
                    "ifp_formats": ["g96", "gxx"],
                    "mtb_formats": ["g96", "gxx"],
                    "available": True,
                    "default": True,
                    "links": {"ifp": {"g96": "/api/v1/forcefields/54A7/ifp"}, "mtb": {}},
                }
            ],
            "total": 1,
            "default_forcefield": "54A7",
        },
    )
    forcefields = client.forcefields.list()
    assert isinstance(forcefields, ForcefieldList)
    assert forcefields.default_forcefield == "54A7"
    assert [f.name for f in forcefields] == ["54A7"]


def test_forcefield_not_found(api, client):
    api.get("/forcefields/99X9/mtb").respond(
        404, json=problem("forcefield-not-found", 404), headers=PROBLEM_HEADERS
    )
    with pytest.raises(NotFound):
        client.forcefields.mtb("99X9")


def test_parameters_library(api, client):
    api.get("/parameters/versions").respond(
        200, json={"items": [{"version": 1}], "total": 1, "builds": [{"id": 3}]}
    )
    motifs = api.get("/parameters/motifs").respond(
        200,
        json={
            "items": [{"id": 1, "key_hex": "ab", "kind": "bond", "depth": 2, "build_id": 3}],
            "next_cursor": None,
            "total": 1,
            "build_id": 3,
            "units": {"value_median": "nm"},
        },
    )
    api.get("/parameters/motifs/ab").respond(
        200,
        json={
            "id": 1,
            "key_hex": "ab",
            "kind": "bond",
            "depth": 2,
            "build_id": 3,
            "ladder": {"2": [{"id": 1}]},
            "versions_holding": [],
        },
    )
    versions = client.parameters.versions()
    assert isinstance(versions, LibraryVersions) and versions.builds == [{"id": 3}]
    page = client.parameters.motifs(kind="bond", has_hessian=True, limit=5)
    assert isinstance(page, MotifPage) and page.units == {"value_median": "nm"}
    assert dict(motifs.calls.last.request.url.params) == {
        "kind": "bond",
        "has_hessian": "true",
        "limit": "5",
    }
    detail = client.parameters.motif("ab", kind="bond")
    assert isinstance(detail, MotifDetail) and detail.ladder["2"] == [{"id": 1}]


def test_dihedral_archetypes(api, client):
    api.get("/dihedrals/archetypes").respond(
        200,
        json={
            "items": [
                {
                    "id": "a1",
                    "molid": 21,
                    "run_id": 4,
                    "fit_failed": False,
                    "auto_exclude": False,
                    "in_ifp": True,
                }
            ],
            "total": 1,
            "summary": {"in_ifp": 1},
        },
    )
    api.get("/dihedrals/archetypes/a1").respond(
        200,
        json={
            "id": "a1",
            "molid": 21,
            "run_id": 4,
            "metadata": {},
            "graph": {},
            "flags": [],
            "flag_descriptions": [],
            "fit_metrics": {},
            "rmsd_units": "kJ/mol",
            "e_window_kj": 20.0,
            "fit_failed": False,
            "auto_exclude": False,
            "manual_include": False,
            "in_ifp": True,
            "term_ids": [],
            "ifp_terms": [],
            "energies": {},
        },
    )
    page = client.dihedrals.archetypes(in_ifp=True)
    assert isinstance(page, ArchetypePage) and page.summary == {"in_ifp": 1}
    assert isinstance(client.dihedrals.archetype("a1"), ArchetypeDetail)


def test_tautomer_group_pages(api, client):
    route = api.get("/tautomers/groups/k")
    route.side_effect = [
        _json(
            {
                "group_id": "k",
                "grouping": "skeleton_key",
                "items": [{"molid": 1, "compound_id": 2, "energies": {}}],
                "next_cursor": "n",
                "total": 2,
            }
        ),
        _json(
            {
                "group_id": "k",
                "grouping": "skeleton_key",
                "items": [{"molid": 3, "compound_id": 4, "energies": {}}],
                "next_cursor": None,
                "total": 2,
            }
        ),
    ]
    group = client.tautomers.group("k", limit=1)
    assert isinstance(group, TautomerGroup) and group.grouping == "skeleton_key"
    assert [m.molid for m in group.all()] == [1, 3]


def test_statistics(api, client):
    route = api.get("/statistics").respond(
        200,
        json={
            "indicators": [{"name": "molecules", "latest": {"date": "2026-09-22", "value": 1.0}}],
            "series": {"name": "molecules", "points": [{"date": "2026-09-22", "value": 1.0}]},
        },
    )
    stats = client.statistics.get("molecules", include_validation_set=False)
    assert isinstance(stats, Statistics)
    assert stats.indicators[0].latest.date == date(2026, 9, 22)
    assert dict(route.calls.last.request.url.params) == {
        "name": "molecules",
        "include_validation_set": "false",
    }


def test_rmsd(api, client):
    route = api.post("/structures/rmsd").respond(
        200,
        json={
            "inputs": [
                {"index": 0, "molid": 21, "source": "pdb_allatom_optimised"},
                {"index": 1, "molid": None, "source": "uploaded"},
            ],
            "rmsd_matrix": [[0.0, None], [None, 0.0]],
            "rmsd": None,
        },
    )
    result = client.structures.rmsd(molids=[21], structures=["ATOM ..."])
    assert isinstance(result, RMSDResult) and result.rmsd_matrix[0][1] is None
    assert json.loads(route.calls.last.request.content) == {
        "molids": [21],
        "structures": ["ATOM ..."],
    }
    with pytest.raises(ValueError):
        client.structures.rmsd(molids=[21])


def test_health_returns_a_degraded_body(api, client):
    api.get("/health").respond(
        503,
        json={
            "status": "degraded",
            "role": "public",
            "database": False,
            "redis": True,
            "schema_present": True,
            "tables": {},
        },
    )
    health = client.health()
    assert isinstance(health, Health) and health.status == "degraded"


# --------------------------------------------------------------------------- me


def test_me_and_usage(api, client):
    api.get("/me").respond(
        200,
        json={
            "principal": "user",
            "name": "someone@example.org",
            "key_id": 7,
            "key_prefix": "atb_ab12cd34",
            "key_expires_at": "2027-01-01T00:00:00Z",
            "scopes": ["manage", "read"],
            "limits": {"burst_per_min": 60, "daily_limit": 2000},
            "account": {"id": 3, "email": "someone@example.org", "user_class": 1},
        },
    )
    api.get("/me/usage").respond(
        200, json={"day": "2026-09-23", "weight": 4, "daily_limit": 2000, "keys": []}
    )
    me = client.me.get()
    assert isinstance(me, Me) and me.account.user_class == 1 and me.limits.daily_limit == 2000
    assert me.key_expires_at == datetime(2027, 1, 1, tzinfo=UTC)
    usage = client.me.usage()
    assert isinstance(usage, Usage) and usage.day == date(2026, 9, 23) and usage.weight == 4


def test_me_molecules_is_owner_me(api, client):
    route = api.get("/molecules").respond(200, json={"items": [molecule(5)]})
    page = client.me.molecules(limit=10, is_finished=False)
    assert page[0].molid == 5
    assert dict(route.calls.last.request.url.params) == {
        "owner": "me",
        "limit": "10",
        "is_finished": "false",
    }


def test_keys_create_and_revoke(api, client):
    created = api.post("/me/keys").respond(
        201,
        json={
            "id": 8,
            "prefix": "atb_ffff0000",
            "principal": "user",
            "format": "v1",
            "scopes": ["read"],
            "created_at": "2026-09-23T00:00:00Z",
            "key": "atb_ffff0000_secret",
        },
    )
    key = client.me.keys.create("laptop", scopes=["read"], expires_in_days="30d")
    assert key.key == "atb_ffff0000_secret" and key.created_at.tzinfo is not None
    assert json.loads(created.calls.last.request.content) == {
        "name": "laptop",
        "scopes": ["read"],
        "expires_in_days": 30,
    }
    api.delete("/me/keys/8").respond(204)
    assert client.me.keys.revoke(8) is None


def test_quota_request(api, client):
    route = api.post("/me/quota-requests").respond(202, json={"status": "received", "key_id": 7})
    received = client.me.request_quota(reason="screening", daily_limit=10000, key_id=7)
    assert isinstance(received, QuotaRequestReceived) and received.key_id == 7
    assert json.loads(route.calls.last.request.content) == {
        "reason": "screening",
        "daily_limit": 10000,
        "key_id": 7,
    }
    with pytest.raises(ValueError):
        client.me.request_quota(reason="nothing asked")
