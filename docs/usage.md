# Usage guide

## API keys and configuration

Create a key on your ATB account page (*Manage Account → API keys*), or with an existing key
via `atb keys create`. The client resolves a key in this order:

1. the `api_key=` argument,
2. the `ATB_API_KEY` environment variable,
3. a profile in `~/.config/atb/config.toml` (`ATB_CONFIG` overrides the path):

```toml
[profiles.default]
api_key = "atb_ab12cd34_..."

[profiles.staging]
api_key = "atb_..."
base_url = "https://staging.example.org/api/v1"
timeout = 60
```

Select a profile with `ATBClient(profile="staging")`, `ATB_PROFILE=staging`, or
`atb --profile staging`. `ATB_API_URL` overrides the base URL (default
`https://atb.uq.edu.au/api/v1`). The key is never accepted on the command line, and the
client refuses to send it over plain `http://` to anything but localhost. Keep the config
file private (`chmod 600`).

## Search and get

```python
mol = atb.molecules.get(21)
hits = atb.molecules.search(common_name="pterostilbene", limit=20)  # Page[Molecule]
for m in atb.molecules.search(formula="C6H6").all():                # walks every page
    print(m.molid, m.common_name)
```

A molid merged into another as a duplicate is redirected by the server (`301`) and followed,
so `atb.molecules.get(20)` may return molecule 21.

## Submit and wait

```python
from atb_client import DuplicateMolecule

try:
    mol = atb.molecules.submit(
        open("lig.pdb").read(), format="pdb", netcharge=0, public=True, client_reference="LIG-042"
    )
except DuplicateMolecule as dup:
    mol = dup.molecule  # the normal path on a re-run: adopt the existing entry

mol = mol.wait(timeout=6 * 3600)
```

`DuplicateMolecule.molecule` fetches the existing entry lazily, with one extra `GET`. `wait()`
polls `/status` (no quota cost), backing off from 15 s to 5 minutes, and returns on `finished`
or `capped`. It raises `MoleculeFailed` or `MoleculeRejected` on those terminal stages, and
`Timeout` if `timeout` elapses first.

Submit a batch from an SDF:

```python
batch = atb.molecules.submit_batch(
    sdf=open("ligands.sdf").read(), netcharge_field="charge", public=False, reference_field="_Name"
)
for molid, status in atb.molecules.wait_all(batch.molids, timeout=24 * 3600):
    print(molid, status.stage)
```

## Downloads and bundles

```python
mol.files.download("itp_aa", "lig.itp", timeout=300)   # hides the 202/job dance
atb.bundles.download(molids=[21, 22], names=["itp_aa", "pdb_aa_opt"], into="ligs/")
atb.forcefields.ifp("54A7", format="gxx", path="54A7.ifp")
```

File names follow one vocabulary: `<format>_<atoms>[_<geometry>]` — `itp_aa`, `mtb_ua`,
`pdb_aa_opt`, `pdb_ua_unopt`, `g96_aa_opt`, `top_aa`, `lgf`, plus `qm0_log`, `qm1_log`,
`qm2_log`, `qm_data`, `emin_vac`, `emin_vac_ref`. `mol.files.list()` shows what exists for the
current topology, with each name's v0.1 alias. Pin a version with `hash=`; a version no
longer stored raises `TopologyVersionGone`. QM logs, `qm_data` and `atb_log` are restricted
to partner and admin accounts and service keys.

## Jobs and `?wait`

Anything that may be slow is a job (D8): the server answers `202 Accepted` and the client
polls `GET /jobs/{id}` until it ends. Most calls hide this — `download()`, `submit()`,
`structures.search()` — and only return once the job is done, up to their own `timeout`. Call
a job-backed method with `wait=False` to get the pending `Job` back immediately instead, and
resolve it later:

```python
job = atb.structures.search(structure=open("lig.pdb").read(), wait=False)
result = job.result(timeout=600)  # blocks for this job specifically
```

Polling a job or a molecule's `/status` costs no quota.

## Rate limits and retries

Transient failures — `429`, `502`, `503`, `504`, and connection errors — are retried with
exponential backoff and jitter, up to `max_attempts` (default 5), honouring `Retry-After`
when the server sends one. A `Retry-After` longer than `max_retry_after` (default 60 s — a
daily limit resetting at midnight, say) is not slept on: `RateLimited` is raised at once with
`.retry_after` set, so the caller can decide. Tune both on the client:

```python
atb = ATBClient(max_attempts=8, max_retry_after=120)
```

`atb.me.usage()` returns today's weighted request count and limits, at no quota cost.

## Async

`AsyncATBClient` has the same surface, every call a coroutine; iterators become async
iterators and `DuplicateMolecule.molecule` is awaitable:

```python
import asyncio
from atb_client import AsyncATBClient

async def main(molids):
    async with AsyncATBClient() as atb:
        mols = await asyncio.gather(*(atb.molecules.get(m) for m in molids))
        return await asyncio.gather(*(m.wait(timeout=86400) for m in mols))
```

Both clients come from one generator-based implementation (see `atb_client._base`), so they
cannot drift apart.
