from __future__ import annotations

import io
import zipfile

import pytest

from atb_client import TopologyVersionGone
from atb_client.models import FileEntry, FileList

from .conftest import molecule


def test_list_files(api, client):
    api.get("/molecules/21/files").respond(
        200,
        json={
            "molid": 21,
            "forcefield": "54A7",
            "topology_hash": "abc12",
            "items": [
                {
                    "name": "itp_aa",
                    "legacy_name": "itp_allatom",
                    "media_type": "text/plain",
                    "source": "topology",
                    "cached": True,
                    "size": 1200,
                    "restricted": False,
                    "url": "/api/v1/molecules/21/files/itp_aa",
                },
                {
                    "name": "pdb_aa_opt",
                    "legacy_name": "pdb_allatom_optimised",
                    "media_type": "chemical/x-pdb",
                    "source": "topology",
                    "cached": False,
                    "size": None,
                    "restricted": False,
                    "url": "/api/v1/molecules/21/files/pdb_aa_opt",
                },
            ],
        },
    )
    files = client.files.list(21)
    assert isinstance(files, FileList)
    assert [f.name for f in files] == ["itp_aa", "pdb_aa_opt"]
    assert isinstance(files[0], FileEntry)
    assert files.topology_hash == "abc12" and files.forcefield == "54A7"
    assert [f.name for f in files.cached] == ["itp_aa"]
    assert files[0].legacy_name == "itp_allatom"


def test_download_writes_file(api, client, tmp_path):
    route = api.get("/molecules/21/files/itp_aa").respond(200, content=b"itp body")
    target = tmp_path / "sub" / "lig.itp"
    assert client.files.download(21, "itp_aa", target, ff="54A7") == target
    assert target.read_bytes() == b"itp body"
    assert route.calls.last.request.url.params["ff"] == "54A7"
    assert not list(target.parent.glob("*.part"))


def test_download_into_directory_uses_content_disposition(api, client, tmp_path):
    api.get("/molecules/21/files/pdb_aa_opt").respond(
        200, content=b"PDB", headers={"Content-Disposition": 'attachment; filename="21_aa.pdb"'}
    )
    path = client.files.download(21, "pdb_aa_opt", tmp_path)
    assert path == tmp_path / "21_aa.pdb"
    assert path.read_bytes() == b"PDB"


def test_download_returns_bytes_without_path(api, client):
    api.get("/molecules/21/files/lgf").respond(200, content=b"graph")
    assert client.files.download(21, "lgf") == b"graph"


def test_molecule_files_binding(api, client, tmp_path):
    api.get("/molecules/21").respond(200, json=molecule())
    api.get("/molecules/21/files/itp_aa").respond(200, content=b"itp")
    mol = client.molecules.get(21)
    assert mol.files.download("itp_aa", tmp_path / "x.itp", timeout=300).read_bytes() == b"itp"


def test_pinned_hash_gone(api, client, tmp_path):
    api.get("/molecules/21/files/itp_aa").respond(
        410,
        json={"type": "https://atb.uq.edu.au/api/v1/errors/topology-version-gone", "status": 410},
    )
    with pytest.raises(TopologyVersionGone):
        client.files.download(21, "itp_aa", tmp_path / "x", hash="old")
    assert not (tmp_path / "x").exists()


def test_bundle_download_extracts(api, client, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("21/itp_aa.itp", "a")
        zf.writestr("22/itp_aa.itp", "b")
    api.post("/bundles").respond(202, headers={"Location": "/api/v1/jobs/B1"})
    api.get("/jobs/B1").respond(
        200, json={"id": "B1", "state": "done", "result": {"url": "/api/v1/bundles/B1.zip"}}
    )
    api.get("/bundles/B1.zip").respond(
        200, content=buf.getvalue(), headers={"Content-Type": "application/zip"}
    )
    out = client.bundles.download(molids=[21, 22], names=["itp_aa"], into=tmp_path / "ligs")
    assert (out / "21" / "itp_aa.itp").read_text() == "a"
    assert (out / "22" / "itp_aa.itp").read_text() == "b"


def test_bundle_limit(client):
    with pytest.raises(ValueError):
        client.bundles.download(molids=range(51), names=["itp_aa"])


def test_forcefield_ifp(api, client, tmp_path):
    route = api.get("/forcefields/54A7/ifp").respond(200, content=b"TITLE\n")
    assert client.forcefields.ifp("54A7", format="gxx") == "TITLE\n"
    assert dict(route.calls.last.request.url.params) == {"format": "gxx"}  # no ?wait=
    path = client.forcefields.ifp("54A7", path=tmp_path / "54A7.ifp")
    assert path.read_text() == "TITLE\n"
    assert dict(route.calls.last.request.url.params) == {}  # the server's default format
    client.forcefields.ifp("54A7", rules=True, ifp_hash="d41d8cd9")
    assert dict(route.calls.last.request.url.params) == {"rules": "true", "ifp_hash": "d41d8cd9"}
