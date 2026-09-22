from __future__ import annotations

import warnings

import httpx
import pytest

from atb_client import DuplicateMolecule
from atb_client.legacy import API, ATB_Mol, v1_file_name

from .conftest import BASE, molecule, problem

HOST = BASE[: -len("/api/v1")]


@pytest.fixture
def legacy_api(api):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return API(api_token="0123456789abcdef0123456789abcdef", host=HOST, api_format="yaml")


def test_construction_warns(api):
    with pytest.warns(DeprecationWarning):
        API(api_token="t", host=HOST)


@pytest.mark.parametrize(
    "atb_format,v1",
    [("pdb_aa", "pdb_aa_opt"), ("pdb_ua", "pdb_ua_opt"), ("mtb_aa", "mtb_aa"),
     ("mtb_ua", "mtb_ua"), ("itp_aa", "itp_aa"), ("itp_ua", "itp_ua"), ("lgf", "lgf"),
     ("yml", "yml"), ("pdb_allatom_optimised", "pdb_aa_opt"),
     ("pdb_uniatom_unoptimised", "pdb_ua_unopt"), ("itp_allatom", "itp_aa"),
     ("mtb96_uniatom", "mtb96_ua"), ("graph.lgf", "lgf"), ("cif_ccd", "cif_ccd")],
)
def test_format_table(atb_format, v1):
    assert v1_file_name(atb_format) == v1


def test_download_file_pdb_aa_hits_v1_path(api, legacy_api, tmp_path):
    route = api.get("/molecules/21/files/pdb_aa_opt").respond(200, content=b"ATOM 1\n")
    assert legacy_api.Molecules.download_file(atb_format="pdb_aa", molid=21) == "ATOM 1\n"
    request = route.calls.last.request
    assert request.url.path == "/api/v1/molecules/21/files/pdb_aa_opt"
    assert request.headers["Authorization"] == "Bearer 0123456789abcdef0123456789abcdef"
    assert "api_token" not in str(request.url)

    out = tmp_path / "21.pdb"
    assert legacy_api.Molecules.download_file(atb_format="pdb_aa", molid=21, fnme=str(out)) is None
    assert out.read_bytes() == b"ATOM 1\n"


def test_download_file_long_name_and_ff(api, legacy_api):
    route = api.get("/molecules/21/files/itp_aa").respond(200, content=b"itp")
    legacy_api.Molecules.download_file(molid=21, file="itp_allatom", outputType="top",
                                       ffVersion="54A7")
    assert route.calls.last.request.url.params["ff"] == "54A7"


def test_readme_example(api, legacy_api, tmp_path, monkeypatch):
    """The atb_api README example, unchanged but for the import line."""
    monkeypatch.chdir(tmp_path)
    api.get("/molecules").respond(200, json={"items": [molecule(21, common_name="Pterostilbene")]})
    api.get("/molecules/21/files/pdb_aa_opt").respond(200, content=b"ATOM\n")
    molecules = legacy_api.Molecules.search(common_name="Pterostilbene", match_partial=False)
    for mol in molecules:
        assert isinstance(mol, ATB_Mol)
        assert mol.inchi.startswith("InChI=")
        pdb_path = f"{mol.molid}.pdb"
        mol.download_file(fnme=pdb_path, atb_format="pdb_aa")
    assert (tmp_path / "21.pdb").read_text() == "ATOM\n"


def test_search_molids_and_partial(api, legacy_api):
    route = api.get("/molecules").respond(200, json={"items": [molecule(1), molecule(2)]})
    assert legacy_api.Molecules.search(common_name="eth", match_partial=True,
                                       return_type="molids") == [1, 2]
    assert dict(route.calls.last.request.url.params) == {"q": "eth"}


def test_molid_and_molids(api, legacy_api):
    api.get("/molecules/21").respond(200, json=molecule(21))
    route = api.get("/molecules").respond(200, json={"items": [molecule(1), molecule(2)]})
    assert legacy_api.Molecules.molid(molid=21).molid == 21
    assert [m.molid for m in legacy_api.Molecules.molid(molids=[1, 2])] == [1, 2]
    assert route.calls.last.request.url.params["ids"] == "1,2"


def test_structure_search(api, legacy_api):
    api.post("/structures/search").respond(200, json={"items": [{"molid": 21, "rmsd": 0.0}]})
    out = legacy_api.Molecules.structure_search(structure="ATOM", netcharge=0,
                                                structure_format="pdb")
    assert out["matches"][0]["molid"] == 21


def test_submit_duplicate_raises(api, legacy_api):
    api.post("/molecules").respond(409, json=problem("duplicate-molecule", 409, molid=21))
    with pytest.raises(DuplicateMolecule):
        legacy_api.Molecules.submit(pdb="ATOM", netcharge=0, public=True, moltype="heteromolecule")


def test_rmsd_align(api, legacy_api):
    route = api.post("/structures/rmsd").respond(200, json={"rmsd": 0.1})
    assert legacy_api.RMSD.align(molids="21,22") == {"rmsd": 0.1}
    import json

    assert json.loads(route.calls.last.request.content)["molids"] == [21, 22]


def test_internal_token_header(api):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        legacy = API(internal_token="internal", host=HOST)
    route = api.get("/molecules/21").respond(200, json=molecule())
    legacy.Molecules.molid(molid=21)
    assert route.calls.last.request.headers["X-ATB-Internal-Token"] == "internal"
    assert isinstance(route.calls.last.response, httpx.Response)
