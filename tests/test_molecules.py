from __future__ import annotations

import json

import httpx
import pytest

from atb_client import MoleculeFailed, MoleculeRejected, RemapRefused, Timeout
from atb_client.models import Change, Molecule, MoleculeStatus, Page

from .conftest import molecule, problem, status


def test_get_returns_bound_model(api, client):
    api.get("/molecules/21").respond(200, json=molecule(extra_field="kept"))
    mol = client.molecules.get(21)
    assert isinstance(mol, Molecule)
    assert mol.status.stage == "finished" and mol.status.terminal
    assert mol.model_extra["extra_field"] == "kept"
    assert mol._client is client


# ------------------------------------------------------------------ wait()


def _status_sequence(api, molid, stages):
    route = api.get(f"/molecules/{molid}/status")
    route.side_effect = [httpx.Response(200, json=status(s)) for s in stages]
    return route


@pytest.mark.parametrize("final", ["finished", "capped"])
def test_wait_returns_on_success(api, client, clock, final):
    api.get("/molecules/7").respond(200, json=molecule(7, status=status("queued")))
    polls = _status_sequence(api, 7, ["queued", "qm0", "qm1", final])
    mol = client.molecules.get(7)
    api.get("/molecules/7").respond(200, json=molecule(7, status=status(final)))
    done = mol.wait(timeout=3600)
    assert done.status.stage == final
    assert polls.call_count == 4
    # 15 s, then x1.5 each round
    assert clock.sleeps == [15.0, 22.5, 33.75]


def test_wait_backoff_caps_at_five_minutes(api, client, clock):
    _status_sequence(api, 7, ["qm1"] * 12 + ["finished"])
    api.get("/molecules/7").respond(200, json=molecule(7))
    Molecule(molid=7)._bind(client).wait()
    assert max(clock.sleeps) == 300.0
    assert clock.sleeps[-1] == 300.0


@pytest.mark.parametrize("stage,exc", [("failed", MoleculeFailed), ("rejected", MoleculeRejected)])
def test_wait_raises_on_negative_terminal(api, client, stage, exc):
    _status_sequence(api, 7, ["qm0", stage])
    with pytest.raises(exc) as info:
        Molecule(molid=7)._bind(client).wait()
    assert info.value.molid == 7
    assert info.value.status.stage == stage


def test_wait_times_out(api, client, clock):
    api.get("/molecules/7/status").respond(200, json=status("qm2"))
    with pytest.raises(Timeout) as info:
        Molecule(molid=7)._bind(client).wait(timeout=60)
    assert info.value.status.stage == "qm2"
    assert sum(clock.sleeps) == pytest.approx(60)


def test_status_is_a_model(api, client):
    api.get("/molecules/7/status").respond(
        200, json=status("qm1", eta_class="hours", client_reference="LIG-042")
    )
    st = client.molecules.status(7)
    assert isinstance(st, MoleculeStatus)
    assert (st.stage, st.terminal, st.eta_class, st.client_reference) == (
        "qm1",
        False,
        "hours",
        "LIG-042",
    )


# ------------------------------------------------------------------ search


def test_search_page_and_all(api, client):
    route = api.get("/molecules")
    route.side_effect = [
        httpx.Response(
            200, json={"items": [molecule(1), molecule(2)], "next_cursor": "c2", "total": 5}
        ),
        httpx.Response(200, json={"items": [molecule(3), molecule(4)], "next_cursor": "c3"}),
        httpx.Response(200, json={"items": [molecule(5)], "next_cursor": None}),
    ]
    page = client.molecules.search(formula="C6H6", limit=2)
    assert isinstance(page, Page)
    assert [m.molid for m in page] == [1, 2]
    assert page.total == 5 and page.has_more
    everything = list(page.all())
    assert [m.molid for m in everything] == [1, 2, 3, 4, 5]
    params = [dict(c.request.url.params) for c in route.calls]
    assert params[0] == {"formula": "C6H6", "limit": "2"}
    assert params[1] == {"formula": "C6H6", "limit": "2", "cursor": "c2"}
    assert params[2]["cursor"] == "c3"
    assert all(m._client is client for m in everything)


def test_search_encodes_lists_and_bools(api, client):
    route = api.get("/molecules").respond(200, json={"items": []})
    client.molecules.search(ids=[1, 2, 3], is_finished=True)
    assert dict(route.calls.last.request.url.params) == {"ids": "1,2,3", "is_finished": "true"}


def test_changes(api, client):
    route = api.get("/molecules/changes").respond(
        200,
        json={
            "items": [
                {
                    "molid": 21,
                    "topology_hash": "h2",
                    "stage": "finished",
                    "changed_at": "2026-09-23T01:02:03Z",
                }
            ],
            "next_cursor": "k",
        },
    )
    page = client.molecules.changes(since="abc")
    change = next(iter(page))
    assert isinstance(change, Change) and change.topology_hash == "h2"
    assert page.next_cursor == "k"
    assert route.calls.last.request.url.params["since"] == "abc"


# ------------------------------------------------------------------ submit


def test_submit_201(api, client):
    route = api.post("/molecules").respond(201, json=molecule(3001, status=status("queued")))
    mol = client.molecules.submit(
        "ATOM", format="pdb", netcharge=0, public=True, client_reference="LIG-042"
    )
    assert mol.molid == 3001
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "structure": "ATOM",
        "format": "pdb",
        "netcharge": 0,
        "public": True,
        "client_reference": "LIG-042",
    }
    assert route.calls.last.request.url.params["wait"] == "120"


def test_submit_batch(api, client):
    api.post("/molecules:batch").respond(
        200,
        json=[
            {"index": 0, "client_reference": "A", "molid": 10},
            {
                "index": 1,
                "client_reference": "B",
                "problem": {
                    "type": "https://atb.uq.edu.au/api/v1/errors/duplicate-molecule",
                    "status": 409,
                    "molid": 11,
                },
            },
            {
                "index": 2,
                "client_reference": "C",
                "problem": {
                    "type": "https://atb.uq.edu.au/api/v1/errors/chemistry-rejected",
                    "status": 422,
                },
            },
        ],
    )
    batch = client.molecules.submit_batch(
        sdf="...$$$$", netcharge_field="charge", reference_field="_Name", public=False
    )
    assert batch.molids == [10, 11]
    assert [i.client_reference for i in batch.failed] == ["C"]


def test_wait_all_yields_as_each_ends(api, client, clock):
    s1 = api.get("/molecules/1/status")
    s1.side_effect = [
        httpx.Response(200, json=status("qm1")),
        httpx.Response(200, json=status("finished")),
    ]
    api.get("/molecules/2/status").respond(200, json=status("capped"))
    s3 = api.get("/molecules/3/status")
    s3.side_effect = [
        httpx.Response(200, json=status("qm0")),
        httpx.Response(200, json=status("failed", error="SCF")),
    ]
    seen = [(m, s.stage) for m, s in client.molecules.wait_all([1, 2, 3])]
    assert seen == [(2, "capped"), (1, "finished"), (3, "failed")]
    assert clock.sleeps == [15.0]


def test_wait_all_timeout_lists_pending(api, client):
    api.get("/molecules/1/status").respond(200, json=status("finished"))
    api.get("/molecules/2/status").respond(200, json=status("qm2"))
    it = client.molecules.wait_all([1, 2], timeout=100)
    assert next(it)[0] == 1
    with pytest.raises(Timeout) as info:
        list(it)
    assert info.value.pending == [2]


# ------------------------------------------------------------------ remap


def test_remap_bytes(api, client):
    route = api.post("/molecules/21/remap").respond(
        200, content=b"PK\x03\x04zip", headers={"Content-Type": "application/zip"}
    )
    out = client.molecules.remap(21, "ATOM", format="pdb")
    assert out == b"PK\x03\x04zip"
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "structure": "ATOM",
        "names": "query",
        "coords": "query",
        "united": False,
        "format": "pdb",
    }


def test_remap_to_path(api, client, tmp_path):
    api.post("/molecules/21/remap").respond(
        200, content=b"PK\x03\x04zip", headers={"Content-Type": "application/zip"}
    )
    out = tmp_path / "remap.zip"
    path = client.molecules.remap(21, "ATOM", path=out)
    assert path == out
    assert out.read_bytes() == b"PK\x03\x04zip"


def test_remap_follows_job(api, client, clock):
    api.post("/molecules/21/remap").respond(202, headers={"Location": "/api/v1/jobs/J"})
    api.get("/jobs/J").respond(200, json={"id": "J", "state": "done", "kind": "remap"})
    api.get("/jobs/J/result").respond(
        200, content=b"PK\x03\x04zip", headers={"Content-Type": "application/zip"}
    )
    out = client.molecules.remap(21, "ATOM")
    assert out == b"PK\x03\x04zip"


def test_remap_refused_carries_report(api, client):
    api.post("/molecules/21/remap").respond(
        422,
        json=problem(
            "remap-refused", 422, molid=21, report={"mapping": {"status": "not_equivalent"}}
        ),
    )
    with pytest.raises(RemapRefused) as info:
        client.molecules.remap(21, "ATOM")
    assert info.value.report == {"mapping": {"status": "not_equivalent"}}
