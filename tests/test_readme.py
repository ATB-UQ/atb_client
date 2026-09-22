"""The README quick-start, executed verbatim against mocked responses."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import httpx

from .conftest import BASE, KEY, molecule, status

README = Path(__file__).resolve().parents[1] / "README.md"


def _block(after_heading: str) -> str:
    text = README.read_text()
    section = text.split(after_heading, 1)[1]
    return re.search(r"```python\n(.*?)```", section, re.S).group(1)


def test_quick_start_runs(api, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ATB_API_KEY", KEY)
    monkeypatch.setenv("ATB_API_URL", BASE)
    (tmp_path / "lig.pdb").write_text("ATOM\n")
    (tmp_path / "ligands.sdf").write_text("x\n$$$$\n")

    api.get("/molecules/21").respond(200, json=molecule(21))
    api.get("/molecules").respond(200, json={"items": [molecule(21)], "next_cursor": None})
    api.post("/molecules").respond(201, json=molecule(3001, status=status("queued")))
    api.get("/molecules/3001/status").side_effect = [
        httpx.Response(200, json=status("qm0")),
        httpx.Response(200, json=status("capped")),
    ]
    api.get("/molecules/3001").respond(200, json=molecule(3001, status=status("capped")))
    api.get("/molecules/3001/files/itp_aa").respond(200, content=b"itp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("21/itp_aa.itp", "a")
    api.post("/bundles").respond(
        200, content=buf.getvalue(), headers={"Content-Type": "application/zip"}
    )
    api.get("/forcefields/54A7/ifp").respond(200, content=b"IFP")
    api.post("/molecules:batch").respond(
        200, json={"items": [{"index": 0, "client_reference": "a", "molid": 4001}]}
    )
    api.get("/molecules/4001/status").respond(200, json=status("finished"))
    api.get("/molecules/changes").respond(200, json={"items": [], "next_cursor": "c1"})
    api.post("/structures/search").side_effect = [
        httpx.Response(200, json={"items": [{"molid": 21, "rmsd": 0.0}]}),
        httpx.Response(202, headers={"Location": "/api/v1/jobs/S"}),
    ]
    api.get("/jobs/S").respond(200, json={"id": "S", "state": "done", "result": {"items": []}})
    api.get("/me/usage").respond(200, json={"daily_limit": 2000, "daily_used": 30})

    exec(compile(_block("## Quick start"), "README quick start", "exec"), {})

    assert (tmp_path / "lig.itp").read_bytes() == b"itp"
    assert (tmp_path / "ligs" / "21" / "itp_aa.itp").read_text() == "a"
    assert (tmp_path / "54A7.ifp").read_text() == "IFP"
    assert "4001 finished" in capsys.readouterr().out


def test_reading_what_exists_runs(api, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ATB_API_KEY", KEY)
    monkeypatch.setenv("ATB_API_URL", BASE)

    api.get("/molecules").respond(200, json={"items": [molecule(21)], "next_cursor": None})
    api.get("/molecules/21/files").respond(
        200,
        json={
            "molid": 21,
            "forcefield": "54A7",
            "topology_hash": "abc12",
            "items": [
                {
                    "name": "itp_aa",
                    "media_type": "text/plain",
                    "source": "topology",
                    "cached": True,
                    "restricted": False,
                    "url": "/x",
                }
            ],
        },
    )
    api.get("/molecules/21/topologies").respond(
        200,
        json={
            "molid": 21,
            "items": [
                {"hash": "abc12", "forcefield": "54A7", "atb_version": "3.0", "current": True}
            ],
        },
    )
    api.get("/molecules/21/qm").respond(200, json={"molid": 21, "levels": []})
    api.get("/molecules/21/validation").respond(
        200, json={"molid": 21, "emin_vac": {"rmsd_nm": 0.01}}
    )
    api.get("/molecules/21/solvation").respond(
        200, json={"molid": 21, "results": [], "experimental": []}
    )
    params = api.get("/molecules/21/parameters").respond(
        200, json={"molid": 21, "forcefield": "54A7", "topology_hash": "abc12"}
    )
    api.get("/molecules/21/tautomers").respond(200, json={"molid": 21, "members": []})
    api.get("/forcefields").respond(
        200, json={"items": [], "total": 0, "default_forcefield": "54A7"}
    )
    api.get("/forcefields/54A7/mtb").respond(200, content=b"MTB")
    api.get("/parameters/motifs").respond(
        200,
        json={"items": [{"id": 1, "key_hex": "ab", "value_median": 0.15}], "total": 1, "units": {}},
    )
    api.get("/statistics").respond(200, json={"indicators": []})
    api.post("/structures/rmsd").respond(200, json={"inputs": [], "rmsd_matrix": [], "rmsd": 0.02})
    api.get("/me").respond(
        200, json={"principal": "user", "name": "u", "scopes": ["read"], "limits": {}}
    )
    api.get("/me/usage").respond(
        200, json={"day": "2026-09-23", "weight": 3, "daily_remaining": 1997}
    )

    exec(compile(_block("### Reading what exists"), "README reading", "exec"), {})

    assert params.calls.last.request.url.params["hash"] == "abc12"
    assert (tmp_path / "54A7.mtb").read_text() == "MTB"
    out = capsys.readouterr().out
    assert "['itp_aa']" in out and "54A7" in out and "1997" in out
