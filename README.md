# atb-client

Python client and command-line tool for the [Automated Topology Builder](https://atb.uq.edu.au)
(ATB) API v1: submit a structure, wait for its topology, download it in the format your
simulation engine wants, and search what already exists — from a script, with one API key.

- one package, sync and async (`ATBClient`, `AsyncATBClient`), Python 3.9+
- dependencies: `httpx` and `pydantic` 2 only
- retries with backoff on rate limits and transient server errors, honouring `Retry-After`
- typed exceptions carrying the server's problem body
- an `atb` CLI whose exit codes a workflow engine can branch on

> **Status: 0.1.0.dev0.** The v1 server is being built alongside this package; the response
> models here are hand-written from the API design and will be regenerated from the server's
> published OpenAPI document before 1.0.

## Install

```bash
pip install atb-client
```

## Your API key

Create a key on your ATB account page (*Manage Account → API keys*), or with an existing key
via `atb keys create`. The client reads it from, in order:

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

Select a profile with `ATBClient(profile="staging")`, `ATB_PROFILE=staging` or
`atb --profile staging`. `ATB_API_URL` overrides the base URL (default
`https://atb.uq.edu.au/api/v1`). The key is never accepted on the command line, and the client
refuses to send it over plain `http://` to anything but localhost. Keep the config file private
(`chmod 600`).

## Quick start

```python
from atb_client import ATBClient, DuplicateMolecule, MoleculeNotFound, RateLimited

atb = ATBClient()                      # ATB_API_KEY from env, or ~/.config/atb/config.toml

mol = atb.molecules.get(21)            # Molecule (pydantic model); mol.status.stage, mol.status.terminal
hits = atb.molecules.search(common_name="pterostilbene", limit=20)   # Page[Molecule], iterable
for m in atb.molecules.search(formula="C6H6").all():                 # walks every page
    print(m.molid, m.common_name)

try:
    new = atb.molecules.submit(structure=open("lig.pdb").read(), format="pdb", netcharge=0,
                               public=True, client_reference="LIG-042")
except DuplicateMolecule as dup:       # the normal path on a re-run: adopt the existing entry
    new = dup.molecule                 # fetched lazily, one extra GET

new = new.wait(timeout=6 * 3600)       # returns on finished/capped; raises MoleculeFailed /
                                       # MoleculeRejected; Timeout otherwise. Polls back off
                                       # 15 s -> 5 min and cost no quota.
new.files.download("itp_aa", "lig.itp", timeout=300)    # hides the 202/job dance
atb.bundles.download(molids=[21, 22], names=["itp_aa", "pdb_aa_opt"], into="ligs/")
atb.forcefields.ifp("54A7", format="gxx", path="54A7.ifp")

batch = atb.molecules.submit_batch(sdf=open("ligands.sdf").read(), netcharge_field="charge",
                                   public=False, reference_field="_Name")
for molid, status in atb.molecules.wait_all(batch.molids, timeout=24 * 3600):
    print(molid, status.stage)         # yielded as each one ends

changes = atb.molecules.changes(since=None)       # keep changes.next_cursor for next time
match = atb.structures.search(structure=open("lig.pdb").read(), format="pdb", netcharge="*")
job = atb.structures.search(structure=open("lig.pdb").read(), wait=False)
matches = job.result(timeout=600)                  # blocks for the job

print(atb.me.usage())                  # today's counters and limits
```

### Molecule stages

`mol.status.stage` is one of `queued`, `qm0`, `qm1`, `qm2` (in progress) or `finished`,
`capped`, `failed`, `rejected` (terminal). `capped` is a real end state, not "still running":
the molecule reached the highest QM level its size allows (for anything over ~50 atoms that is
qm0) and has its topology. `wait()` returns on `finished` and `capped` and raises on the other
two.

### File names

One vocabulary everywhere: `<format>_<atoms>[_<geometry>]`, e.g. `itp_aa`, `mtb_ua`,
`pdb_aa_opt`, `pdb_ua_unopt`, `g96_aa_opt`, `top_aa`, `lgf`, plus `qm0_log`, `qm1_log`,
`qm2_log`, `qm_data`. `mol.files.list()` shows what exists. Pin a topology version with
`hash=`; a version no longer cached raises `TopologyVersionGone`.

### Async

`AsyncATBClient` has the same surface with every call a coroutine; iterators become async
iterators and `DuplicateMolecule.molecule` is awaitable:

```python
import asyncio
from atb_client import AsyncATBClient

async def main(molids):
    async with AsyncATBClient() as atb:
        mols = await asyncio.gather(*(atb.molecules.get(m) for m in molids))
        return await asyncio.gather(*(m.wait(timeout=86400) for m in mols))
```

Both clients are built from one definition, so they cannot drift apart.

### Errors

Every server error is an `APIError` with `.status` and `.problem` (the RFC 9457 body, extra
members kept):

| exception | when |
|---|---|
| `ValidationError` (`PayloadTooLarge`) | 400 (413): malformed request; `.errors` |
| `AuthenticationError` | 401: no key, unknown, expired or revoked |
| `PermissionDenied` | 403: missing scope, or not visible to you |
| `NotFound` (`MoleculeNotFound`) | 404 |
| `Conflict` (`DuplicateMolecule`) | 409; a duplicate has `.molid` and `.molecule` |
| `TopologyVersionGone` | 410: the pinned `hash` is no longer cached |
| `ChemistryRejected` | 422: refused on chemical grounds; `.reason` |
| `RateLimited` | 429; `.retry_after` (s), `.limit` |
| `ServerError` (`ServiceUnavailable`) | 5xx (503; `.retry_after`) |

Client-side: `MoleculeFailed`, `MoleculeRejected`, `JobFailed`, `Timeout` (with `.job`,
`.status` or `.pending`), `NetworkError` (unreachable after retries), `ConfigurationError`.
All derive from `ATBError`.

Transient failures — 429, 502, 503, 504 and connection errors — are retried up to 5 attempts
with exponential backoff and jitter, sleeping for `Retry-After` when the server gives one. A
`Retry-After` longer than a minute (a daily limit, say) is not slept on: `RateLimited` is
raised at once with `.retry_after` set. Tune with `ATBClient(max_attempts=..., max_retry_after=...)`.

## Command line

```bash
atb get 21
atb status 21                                   # poll once; see exit codes
atb submit lig.pdb --charge 0 --public --ref LIG-042
atb submit-batch ligands.sdf --charge-field charge
atb download 21 itp_aa pdb_aa_opt -o lig/
atb bundle --molids-from molids.txt itp_aa pdb_aa_opt -o ligs/
atb search --inchi-key LFQSCWFLJHTTHZ-UHFFFAOYSA-N
atb ifp 54A7 -o 54A7.ifp
atb keys create --scopes read,submit --expires 90d
atb keys list
atb usage
```

Output is JSON on stdout (`--table` for humans); errors are JSON on stderr.

### Exit codes

| code | meaning |
|---|---|
| 0 | done — for `status`, the molecule is `finished` or `capped` |
| 1 | error |
| 2 | usage — bad arguments, or no API key configured |
| 3 | rate-limited — see `retry_after` in the error body |
| 4 | still running — `status` not terminal, or a `--wait`/download timeout |
| 5 | failed or rejected — the molecule, its job, or its chemistry |

### On an HPC login node: poll once, do not hold a connection

The intended shape for Nextflow, Snakemake or a cron loop is a short-lived `atb status`
per check, branching on the exit code — nothing sits on the login node waiting:

```bash
# submit once (a re-run adopts the existing entry: exit 0 with "duplicate": true)
molid=$(atb submit lig.pdb --charge 0 --ref LIG-042 | python -c 'import json,sys;print(json.load(sys.stdin)["molid"])')

# each time the workflow re-evaluates the rule:
atb status "$molid"
case $? in
  0) atb download "$molid" itp_aa pdb_aa_opt -o "lig_$molid/" ;;
  4) echo "still running; check again later" ;;
  5) echo "failed or rejected"; exit 1 ;;
  3) echo "rate-limited; back off" ;;
  *) echo "error"; exit 1 ;;
esac
```

Status reads cost no quota. `atb submit --wait` exists for interactive use; it is not the HPC
idiom.

## Migrating from `atb_api`

`atb_client.legacy` keeps scripts written against `from atb_api import API` running on v1 with
one changed line:

```python
from atb_client.legacy import API          # was: from atb_api import API

api = API(api_token="<your key>")
molecules = api.Molecules.search(common_name="Pterostilbene", match_partial=False)
for molecule in molecules:
    print(molecule.inchi)
    molecule.download_file(fnme=f"{molecule.molid}.pdb", atb_format="pdb_aa")
```

It covers `Molecules.search/molid/molids/download_file/structure_search/submit` and
`RMSD.align/matrix`, maps the old `atb_format` names (`pdb_aa`, `mtb_ua`, `itp_aa`, `lgf`, `yml`,
`pdb_allatom_optimised`, …) to v1 file names, and emits a `DeprecationWarning`. Your existing
token keeps working as a v1 key. Differences: JSON only (`api_format` is ignored, `yml` comes
back as text), errors are `atb_client` exceptions, and the token is sent in a header rather
than the URL.

The two packages install side by side (`atb_api` and `atb_client` are different import
names), so migrate at your own pace — but move new code straight to `ATBClient`:

| `atb_api` | `atb_client` |
|---|---|
| `API(api_token=...)` | `ATBClient()` (key from env/config) |
| `api.Molecules.search(...)` | `atb.molecules.search(...).all()` |
| `api.Molecules.molid(molid=21)` | `atb.molecules.get(21)` |
| `download_file(molid=21, atb_format="pdb_aa", fnme=p)` | `atb.files.download(21, "pdb_aa_opt", p)` |
| `api.Molecules.submit(pdb=..., netcharge=0, ...)` | `atb.molecules.submit(pdb_text, format="pdb", netcharge=0)` |
| `api.Molecules.structure_search(...)` | `atb.structures.search(...)` |
| `api.RMSD.align(molids=...)` | `atb.structures.rmsd(molids=...)` |

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q                     # respx-mocked; no network
ATB_LIVE_TESTS=1 ATB_API_KEY=... python -m pytest -q -m live   # read-only smoke test
ruff check src tests && ruff format --check src tests
scripts/generate_models.sh [openapi.json URL or file]            # regenerate models
```

Releases are cut by pushing a `v<version>` tag matching `src/atb_client/_version.py`; GitHub
Actions builds and publishes to PyPI by trusted publishing.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
