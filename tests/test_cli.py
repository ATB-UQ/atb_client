from __future__ import annotations

import json
import os
import subprocess
import sys

import httpx
import pytest

from atb_client.cli import main

from .conftest import BASE, KEY, molecule, problem, status


@pytest.fixture
def env(monkeypatch, api):
    monkeypatch.setenv("ATB_API_KEY", KEY)
    monkeypatch.setenv("ATB_API_URL", BASE)
    return api


def out_json(capsys):
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(
    "stage,code", [("finished", 0), ("capped", 0), ("queued", 4), ("qm1", 4), ("failed", 5),
                   ("rejected", 5)])
def test_status_exit_codes(env, capsys, stage, code):
    env.get("/molecules/21/status").respond(200, json=status(stage))
    assert main(["status", "21"]) == code
    assert out_json(capsys)["stage"] == stage


def test_rate_limited_is_3(env, capsys):
    env.get("/molecules/21/status").respond(
        429, json=problem("rate-limited", 429), headers={"Retry-After": "86000"})
    assert main(["status", "21"]) == 3
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "rate-limited" and err["retry_after"] == 86000


def test_not_found_is_1(env, capsys):
    env.get("/molecules/99").respond(404, json=problem("molecule-not-found", 404))
    assert main(["get", "99"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "molecule-not-found"


def test_usage_errors_are_2(env, capsys):
    assert main(["status"]) == 2
    assert main(["no-such-command"]) == 2
    assert main(["submit", "x.pdb"]) == 2  # --charge is required


def test_no_key_is_2(monkeypatch, api, capsys):
    monkeypatch.setenv("ATB_API_URL", BASE)
    assert main(["get", "21"]) == 2
    assert "ATB_API_KEY" in json.loads(capsys.readouterr().err)["message"]


def test_key_is_never_an_argument(env):
    assert main(["--api-key", "x", "get", "21"]) == 2


def test_get_json_and_table(env, capsys):
    env.get("/molecules/21").respond(200, json=molecule())
    assert main(["get", "21"]) == 0
    assert out_json(capsys)["molid"] == 21
    assert main(["get", "21", "--table"]) == 0
    assert "common_name" in capsys.readouterr().out


def test_global_options_before_subcommand(env, capsys):
    env.get("/molecules/21").respond(200, json=molecule())
    assert main(["--table", "get", "21"]) == 0
    assert capsys.readouterr().out.startswith("molid")


def test_submit_duplicate_adopts(env, capsys, tmp_path):
    pdb = tmp_path / "lig.pdb"
    pdb.write_text("ATOM\n")
    env.post("/molecules").respond(409, json=problem("duplicate-molecule", 409, molid=21))
    env.get("/molecules/21").respond(200, json=molecule())
    assert main(["submit", str(pdb), "--charge", "0", "--ref", "LIG-042"]) == 0
    out = out_json(capsys)
    assert out["molid"] == 21 and out["duplicate"] is True


def test_submit_wait_failed_is_5(env, capsys, tmp_path):
    pdb = tmp_path / "lig.pdb"
    pdb.write_text("ATOM\n")
    env.post("/molecules").respond(201, json=molecule(3001, status=status("queued")))
    env.get("/molecules/3001/status").respond(200, json=status("failed"))
    assert main(["submit", str(pdb), "--charge", "0", "--wait"]) == 5


def test_submit_wait_timeout_is_4(env, capsys, tmp_path):
    pdb = tmp_path / "lig.pdb"
    pdb.write_text("ATOM\n")
    env.post("/molecules").respond(201, json=molecule(3001, status=status("queued")))
    env.get("/molecules/3001/status").respond(200, json=status("qm0"))
    assert main(["submit", str(pdb), "--charge", "0", "--wait", "--wait-timeout", "60"]) == 4


def test_submit_chemistry_rejected_is_5(env, tmp_path):
    pdb = tmp_path / "lig.pdb"
    pdb.write_text("ATOM\n")
    env.post("/molecules").respond(422, json=problem("chemistry-rejected", 422))
    assert main(["submit", str(pdb), "--charge", "1"]) == 5


def test_download(env, capsys, tmp_path):
    env.get("/molecules/21/files/itp_aa").respond(
        200, content=b"itp", headers={"Content-Disposition": 'attachment; filename="21.itp"'})
    env.get("/molecules/21/files/pdb_aa_opt").respond(200, content=b"pdb")
    assert main(["download", "21", "itp_aa", "pdb_aa_opt", "-o", str(tmp_path / "lig")]) == 0
    assert (tmp_path / "lig" / "21.itp").read_bytes() == b"itp"
    assert (tmp_path / "lig" / "pdb_aa_opt").read_bytes() == b"pdb"


def test_download_timeout_is_4(env, tmp_path):
    env.get("/molecules/21/files/itp_aa").respond(202, headers={"Location": "/api/v1/jobs/J"})
    env.get("/jobs/J").respond(200, json={"id": "J", "state": "running"})
    assert main(["download", "21", "itp_aa", "-o", str(tmp_path), "--timeout", "30"]) == 4


def test_search_all(env, capsys):
    env.get("/molecules").side_effect = [
        httpx.Response(200, json={"items": [molecule(1)], "next_cursor": "n"}),
        httpx.Response(200, json={"items": [molecule(2)]}),
    ]
    assert main(["search", "--formula", "C2H6O", "--all"]) == 0
    assert [m["molid"] for m in out_json(capsys)] == [1, 2]


def test_ifp_to_stdout(env, capsys):
    env.get("/forcefields/54A7/ifp").respond(200, content=b"TITLE\n")
    assert main(["ifp", "54A7"]) == 0
    assert capsys.readouterr().out == "TITLE\n"


def test_keys_and_usage(env, capsys):
    route = env.post("/me/keys").respond(201, json={"id": 7, "name": "nb", "scopes": ["read"],
                                                    "key": "atb_new_secret"})
    assert main(["keys", "create", "--name", "nb", "--scopes", "read", "--expires", "90d"]) == 0
    assert json.loads(route.calls.last.request.content) == {
        "name": "nb", "scopes": ["read"], "expires": "90d"}
    assert out_json(capsys)["key"] == "atb_new_secret"
    env.get("/me/keys").respond(200, json={"items": [{"id": 7, "scopes": ["read"]}]})
    assert main(["keys", "list"]) == 0
    capsys.readouterr()
    env.delete("/me/keys/7").respond(204)
    assert main(["keys", "revoke", "7"]) == 0
    capsys.readouterr()
    env.get("/me/usage").respond(200, json={"daily_limit": 2000, "daily_used": 12})
    assert main(["usage"]) == 0
    assert out_json(capsys)["daily_used"] == 12


def _run_cli(*args, env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATB_")}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", "atb_client.cli", *args],
                          capture_output=True, text=True, env=env, timeout=60)


def test_subprocess_version_and_usage(tmp_path):
    proc = _run_cli("--version")
    assert proc.returncode == 0 and "atb-client" in proc.stdout
    proc = _run_cli("status", env_extra={"ATB_CONFIG": str(tmp_path / "none.toml")})
    assert proc.returncode == 2


def test_subprocess_no_key(tmp_path):
    proc = _run_cli("status", "21", env_extra={"ATB_CONFIG": str(tmp_path / "none.toml")})
    assert proc.returncode == 2
    assert json.loads(proc.stderr)["error"] == "configuration"


def test_subprocess_unreachable_is_1(tmp_path):
    proc = _run_cli("get", "21", env_extra={
        "ATB_CONFIG": str(tmp_path / "none.toml"), "ATB_API_KEY": KEY,
        "ATB_API_URL": "http://127.0.0.1:9/api/v1"})
    assert proc.returncode == 1
    assert json.loads(proc.stderr)["error"] == "NetworkError"
