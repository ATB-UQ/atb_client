"""The async client runs the same operations; these check the async driver end to end."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from atb_client import AsyncATBClient, DuplicateMolecule, MoleculeFailed, RateLimited
from atb_client.models import Molecule

from .conftest import BASE, KEY, molecule, problem, status


def run(coro):
    return asyncio.run(coro)


def test_async_get_and_wait(api, clock):
    async def main():
        async with AsyncATBClient(api_key=KEY, base_url=BASE) as atb:
            api.get("/molecules/7").respond(200, json=molecule(7, status=status("qm0")))
            api.get("/molecules/7/status").side_effect = [
                httpx.Response(200, json=status("qm1")),
                httpx.Response(200, json=status("capped")),
            ]
            mol = await atb.molecules.get(7)
            assert isinstance(mol, Molecule)
            return await mol.wait(timeout=600)

    done = run(main())
    assert done.molid == 7
    assert clock.sleeps == [15.0]


def test_async_retry_and_failure(api, clock):
    async def main():
        atb = AsyncATBClient(api_key=KEY, base_url=BASE)
        api.get("/molecules/8/status").side_effect = [
            httpx.Response(503),
            httpx.Response(200, json=status("failed", error="SCF did not converge")),
        ]
        try:
            await Molecule(molid=8)._bind(atb).wait()
        finally:
            await atb.aclose()

    with pytest.raises(MoleculeFailed) as info:
        run(main())
    assert "SCF" in str(info.value)
    assert len(clock.sleeps) == 1


def test_async_pagination(api):
    api.get("/molecules").side_effect = [
        httpx.Response(200, json={"items": [molecule(1)], "next_cursor": "n"}),
        httpx.Response(200, json={"items": [molecule(2)]}),
    ]

    async def main():
        async with AsyncATBClient(api_key=KEY, base_url=BASE) as atb:
            page = await atb.molecules.search(q="benz")
            return [m.molid async for m in page.all()]

    assert run(main()) == [1, 2]


def test_async_duplicate_molecule_is_awaitable(api):
    api.post("/molecules").respond(409, json=problem("duplicate-molecule", 409, molid=21))
    get = api.get("/molecules/21").respond(200, json=molecule())

    async def main():
        async with AsyncATBClient(api_key=KEY, base_url=BASE) as atb:
            try:
                await atb.molecules.submit("ATOM", netcharge=0)
            except DuplicateMolecule as dup:
                first = await dup.molecule
                return first, dup.molecule

    first, cached = run(main())
    assert first.molid == 21 and cached is first
    assert get.call_count == 1


def test_async_wait_all(api, clock):
    api.get("/molecules/1/status").respond(200, json=status("finished"))
    api.get("/molecules/2/status").side_effect = [
        httpx.Response(200, json=status("qm0")),
        httpx.Response(200, json=status("rejected")),
    ]

    async def main():
        async with AsyncATBClient(api_key=KEY, base_url=BASE) as atb:
            return [(m, s.stage) async for m, s in atb.molecules.wait_all([1, 2])]

    assert run(main()) == [(1, "finished"), (2, "rejected")]


def test_async_download(api, tmp_path):
    api.get("/molecules/21/files/itp_aa").respond(200, content=b"itp")

    async def main():
        async with AsyncATBClient(api_key=KEY, base_url=BASE) as atb:
            return await atb.files.download(21, "itp_aa", tmp_path / "a.itp")

    assert run(main()).read_bytes() == b"itp"


def test_async_rate_limited(api):
    api.get("/me/usage").respond(
        429, json=problem("rate-limited", 429), headers={"Retry-After": "3600"}
    )

    async def main():
        async with AsyncATBClient(api_key=KEY, base_url=BASE) as atb:
            await atb.me.usage()

    with pytest.raises(RateLimited) as info:
        run(main())
    assert info.value.retry_after == 3600


def test_same_surface():
    """Every public method of the sync client exists on the async one (they are the
    same classes, bound to different drivers)."""
    from atb_client import ATBClient

    sync, aio = ATBClient(api_key=KEY, base_url=BASE), AsyncATBClient(api_key=KEY, base_url=BASE)
    for name in (
        "molecules",
        "files",
        "bundles",
        "structures",
        "forcefields",
        "jobs",
        "me",
        "admin",
        "pipeline",
    ):
        assert type(getattr(sync, name)) is type(getattr(aio, name))
