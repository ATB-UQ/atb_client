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
    [
        ("pdb_aa", "pdb_aa_opt"),
        ("pdb_ua", "pdb_ua_opt"),
        ("mtb_aa", "mtb_aa"),
        ("mtb_ua", "mtb_ua"),
        ("itp_aa", "itp_aa"),
        ("itp_ua", "itp_ua"),
        ("lgf", "lgf"),
        ("yml", "yml"),
        ("pdb_allatom_optimised", "pdb_aa_opt"),
        ("pdb_uniatom_unoptimised", "pdb_ua_unopt"),
        ("itp_allatom", "itp_aa"),
        ("mtb96_uniatom", "mtb96_ua"),
        ("graph.lgf", "lgf"),
        ("cif_ccd", "cif_ccd"),
    ],
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
    legacy_api.Molecules.download_file(
        molid=21, file="itp_allatom", outputType="top", ffVersion="54A7"
    )
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
    assert legacy_api.Molecules.search(
        common_name="eth", match_partial=True, return_type="molids"
    ) == [1, 2]
    assert dict(route.calls.last.request.url.params) == {"common_name": "eth", "match": "partial"}


def test_molid_and_molids(api, legacy_api):
    api.get("/molecules/21").respond(200, json=molecule(21))
    route = api.get("/molecules").respond(200, json={"items": [molecule(1), molecule(2)]})
    assert legacy_api.Molecules.molid(molid=21).molid == 21
    assert [m.molid for m in legacy_api.Molecules.molid(molids=[1, 2])] == [1, 2]
    assert route.calls.last.request.url.params["ids"] == "1,2"


def test_structure_search(api, legacy_api):
    api.post("/structures/search").respond(
        200, json={"matches": [{"molid": 21, "rmsd": 0.0, "compared": True}]}
    )
    out = legacy_api.Molecules.structure_search(
        structure="ATOM", netcharge=0, structure_format="pdb"
    )
    assert out["matches"][0]["molid"] == 21


def test_submit_duplicate_raises(api, legacy_api):
    api.post("/molecules").respond(409, json=problem("duplicate-molecule", 409, molid=21))
    with pytest.raises(DuplicateMolecule):
        legacy_api.Molecules.submit(pdb="ATOM", netcharge=0, public=True, moltype="heteromolecule")


def test_rmsd_align(api, legacy_api):
    result = {
        "inputs": [
            {"index": 0, "molid": 21, "source": "pdb_allatom_optimised"},
            {"index": 1, "molid": 22, "source": "pdb_allatom_optimised"},
        ],
        "rmsd_matrix": [[0.0, 0.1], [0.1, 0.0]],
        "rmsd": 0.1,
    }
    route = api.post("/structures/rmsd").respond(200, json=result)
    assert legacy_api.RMSD.align(molids="21,22") == result
    import json

    assert json.loads(route.calls.last.request.content) == {"molids": [21, 22]}


def test_rmsd_reference_goes_first(api, legacy_api):
    route = api.post("/structures/rmsd").respond(200, json={"inputs": [], "rmsd_matrix": []})
    legacy_api.RMSD.matrix(reference_pdb="REF", pdb_1="B", pdb_0="A")
    import json

    assert json.loads(route.calls.last.request.content) == {"structures": ["REF", "A", "B"]}


def test_internal_token_header(api):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        legacy = API(internal_token="internal", host=HOST)
    route = api.get("/molecules/21").respond(200, json=molecule())
    legacy.Molecules.molid(molid=21)
    assert route.calls.last.request.headers["X-ATB-Internal-Token"] == "internal"
    assert isinstance(route.calls.last.response, httpx.Response)


# --- v0.1 search keywords, tag, generate_mol_data, download_file(ifp=) (D2, 2026-10) ---


@pytest.mark.parametrize(
    "v01, v1",
    [
        ({"InChI": "InChI=1S/x"}, {"inchi": "InChI=1S/x"}),
        ({"inchi": "i"}, {"inchi": "i"}),
        ({"pdb_hetId": "EOH"}, {"pdb_hetid": "EOH"}),
        ({"maximum_qm_level": "0,1"}, {"max_qm_level": [0, 1]}),
        ({"qm_level": "2"}, {"qm_level": [2]}),
        ({"curation_trust": [0, 1]}, {"curation_trust": [0, 1]}),
        ({"has_TI": True}, {"has_ti": True}),
        ({"any": "ethanol"}, {"q": "ethanol"}),
        ({"tag": "alcohol", "max_atoms": 20}, {"tag": "alcohol", "max_atoms": 20}),
    ],
)
def test_search_filters_to_v1(v01, v1):
    from atb_client.legacy import search_filters_to_v1

    assert search_filters_to_v1(v01) == v1


@pytest.mark.parametrize("bad", [{"has_pdb_hetId": True}, {"has_chembl_id": True}])
def test_search_unsupported_filter_raises(bad):
    from atb_client.legacy import search_filters_to_v1

    with pytest.raises(ValueError):
        search_filters_to_v1(bad)


def test_search_translates_on_the_wire(api, legacy_api):
    route = api.get("/molecules").respond(200, json={"items": [molecule(1), molecule(2)]})
    found = legacy_api.Molecules.search(
        InChI="InChI=1S/x", maximum_qm_level="2", page=1, order="asc", limit=1, return_type="molids"
    )
    assert found == [1]
    assert dict(route.calls.last.request.url.params) == {"inchi": "InChI=1S/x", "max_qm_level": "2"}


def test_atb_mol_tag_patches_admin(api, legacy_api):
    import json

    api.get("/molecules/21").respond(200, json=molecule(21))
    route = api.patch("/admin/molecules/21").respond(
        200, json={"molid": 21, "max_qm_level": None, "tags": ["alcohol"]}
    )
    mol = legacy_api.Molecules.molid(molid=21)
    assert mol.tag(tag_name="alcohol", compound_id=5) is True
    assert json.loads(route.calls.last.request.content) == {
        "tags": {"add": ["alcohol"], "remove": []}
    }
    with pytest.raises(ValueError):
        legacy_api.Molecules.tag(molid=21)


def test_generate_mol_data_force_goes_to_admin_regenerate(api, legacy_api):
    route = api.post("/molecules/21/topologies").respond(200, json={"ok": True})
    assert legacy_api.Molecules.generate_mol_data(molid=21, force_regen=True) is True
    assert route.called


def test_generate_mol_data_default_goes_to_pipeline(api, legacy_api):
    route = api.post("/pipeline/molecules/21/topology:generate").respond(200, json={"ok": True})
    assert legacy_api.Molecules.generate_mol_data(molid=21) is True
    assert route.called


def test_download_file_ifp_gxx_and_rules(api, legacy_api, tmp_path):
    route = api.get("/forcefields/54A7/ifp").respond(200, content=b"IFP TEXT\n")
    assert legacy_api.Molecules.download_file(format="GXX", ifp="54A7") == "IFP TEXT\n"
    assert dict(route.calls.last.request.url.params) == {"format": "gxx"}
    out = tmp_path / "x.ifp"
    assert (
        legacy_api.Molecules.download_file(format="GXX", ifp="54A7", rules="True", fnme=str(out))
        is None
    )
    assert out.read_text() == "IFP TEXT\n"
    assert dict(route.calls.last.request.url.params) == {"format": "gxx", "rules": "true"}
