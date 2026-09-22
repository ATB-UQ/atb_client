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
