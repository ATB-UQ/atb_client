# atb-client

Python client and command-line tool for the [Automated Topology Builder](https://atb.uq.edu.au)
(ATB) API v1: submit a structure, wait for its topology, download it in the format your
simulation engine wants, and search what already exists — from a script, with one API key.

- one package, sync and async (`ATBClient`, `AsyncATBClient`), Python 3.9+
- dependencies: `httpx` and `pydantic` 2 only
- retries with backoff on rate limits and transient server errors, honouring `Retry-After`
- typed exceptions carrying the server's problem body
- an `atb` CLI whose exit codes a workflow engine can branch on

> **Status: 0.1.0.dev0.** The v1 server is being built alongside this package. Everything
> that *reads* — molecules, their files and sub-resources, reference data, your account and
> keys — matches the server's published OpenAPI document (work packages 0–2) and is checked
> against it by `tests/test_contract.py`. Submission, batches, bundles, structure search, jobs,
> the admin and pipeline surfaces are written to the API design and are not served yet; see
> [What the server serves today](#what-the-server-serves-today).

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

### Reading what exists

```python
from atb_client import ATBClient

atb = ATBClient()
mine = atb.me.molecules(is_finished=False)          # GET /molecules?owner=me
for m in atb.molecules.search(q="stilbene", fields=["formula", "common_name"]).all():
    print(m.molid, m.formula)                       # a partial match costs 10 units, not 1

files = atb.files.list(21)                          # FileList: .topology_hash, .forcefield
print([f.name for f in files.cached])               # what can be downloaded right now
old = atb.molecules.topologies(21)                  # every stored version, newest first
print(atb.molecules.qm(21, level=2).levels)         # energies in kJ/mol
print(atb.molecules.validation(21).emin_vac.rmsd_nm)
print(atb.molecules.solvation(21).results)          # TI free energies, kJ/mol
record = atb.molecules.parameters(21, hash=old.items[0].hash)   # the bonded-assignment record
family = atb.molecules.tautomers(21)

print(atb.forcefields.list().default_forcefield)
atb.forcefields.mtb("54A7", format="gxx", path="54A7.mtb")
for motif in atb.parameters.motifs(kind="bond", limit=50):
    print(motif.key_hex, motif.value_median)
print(atb.statistics.get().indicators)
print(atb.structures.rmsd(molids=[21, 22]).rmsd)    # nm, after optimal alignment
print(atb.me.get().scopes, atb.me.usage().daily_remaining)
```

Timestamps are timezone-aware UTC `datetime`s. A molid that was merged into another as a
duplicate is redirected by the server (`301`) and followed, so `atb.molecules.get(20)` may
return molecule 21; the key is sent on only while the redirect stays on the same host.

### What the server serves today

These calls are written to the API design (plan §6) but the server does not have their routes
yet, so they currently fail with `NotFound` (or `APIError` 405): `molecules.submit`,
`molecules.submit_batch`, `molecules.update`, `molecules.request_deletion`, `molecules.flag`,
`bundles.download`, `structures.search`, `jobs.*`, `admin.*`, `admin.molecules.regenerate`
and `pipeline.*`. Until topology generation runs as a server-side job, downloading a file
that is not cached raises `GenerationRequired` (409); afterwards the same call waits for the
job. `tests/test_contract.py` keeps this list honest: it fails as soon as the server's schema
gains one of these routes.

### Molecule stages

`mol.status.stage` is one of `queued`, `qm0`, `qm1`, `qm2` (in progress) or `finished`,
`capped`, `failed`, `rejected` (terminal). `capped` is a real end state, not "still running":
the molecule reached the highest QM level its size allows (for anything over ~50 atoms that is
qm0) and has its topology. `wait()` returns on `finished` and `capped` and raises on the other
two.

### File names

One vocabulary everywhere: `<format>_<atoms>[_<geometry>]`, e.g. `itp_aa`, `mtb_ua`,
`pdb_aa_opt`, `pdb_ua_unopt`, `g96_aa_opt`, `top_aa`, `lgf`, plus `qm0_log`, `qm1_log`,
`qm2_log`, `qm_data`, `emin_vac`, `emin_vac_ref`. `mol.files.list()` shows what exists for
the current topology, with each name's v0.1 alias (`legacy_name`), which the server also
accepts. Pin a topology version with `hash=`; a version no longer stored raises
`TopologyVersionGone`. QM logs, `qm_data` and `atb_log` are restricted to partner and admin
accounts and service keys: they are left out of the listing for anyone else, and downloading
one raises `PermissionDenied`.

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
| `Conflict` (`DuplicateMolecule`, `GenerationRequired`) | 409; a duplicate has `.molid` and `.molecule`; `GenerationRequired` is an uncached file (`.name`) |
| `MoleculeMoved` | 301 on a non-GET call: merged into `.canonical_molid` (GETs follow it) |
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
atb keys create --name laptop --scopes read,submit --expires 90d
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
| `api.RMSD.align(molids=...)` | `atb.structures.rmsd(molids=...)` (always the full matrix) |

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q                     # respx-mocked; no network
ATB_LIVE_TESTS=1 ATB_API_KEY=... python -m pytest -q -m live   # read-only smoke test
ruff check src tests && ruff format --check src tests
scripts/generate_models.sh tests/data/openapi.json               # regenerate models
```

### The server's schema and the models

`tests/data/openapi.json` is the server's OpenAPI document, checked in.
`src/atb_client/generated/models.py` is generated from it by `scripts/generate_models.sh`
with `datamodel-code-generator==0.26.5` (the last release that can target Python 3.9;
`uvx --from "datamodel-code-generator[http]==0.26.5" datamodel-codegen` works if you would
rather not install it). CI regenerates it and fails on any difference, and — once v1 is
deployed — diffs against the live `/api/v1/openapi.json`.

The models the client returns are the hand-written ones in `atb_client.models`, not the
generated classes, and do not subclass them:

- the generated classes require fields exactly as the server declares them, but
  `GET /molecules?fields=` returns projections, and an older client must survive a newer
  server dropping a field — so only identity fields are required here;
- the server's schema types its timestamps as strings (a custom serialiser hides the
  `date-time` format); here they are aware UTC `datetime`s;
- the hand-written classes carry behaviour (`wait()`, `files`, `Page.all()`), and allow
  extra fields, so a field the server adds reaches `model.model_extra` before the client is
  regenerated.

`tests/test_contract.py` holds the two together: every field of every generated response
model must exist on its hand-written counterpart, every client call to a served route must
match an operation's method, path, `operationId` and parameters, and the calls to routes not
served yet are listed and checked to still be missing.

`stage` (a molecule's) and `state` (a job's) stay plain strings in the hand-written models,
never an `Enum` or `Literal`, so that a stage the server adds does not stop an older client
from parsing a status; `atb_client.models.STAGES` documents the current set. The generator
keeps `--enum-field-as-literal all`, which only affects the generated reference classes (and
is a no-op today: the server declares these fields as plain strings too).

To refresh the schema from a server checkout (no server needs to run):

```bash
cd website && python -c "import json; from website.api_v1.app import create_app; \
    print(json.dumps(create_app('public', redis_client=object()).openapi(), indent=2))" \
    > ../atb_client/tests/data/openapi.json
cd ../atb_client && scripts/generate_models.sh tests/data/openapi.json && python -m pytest -q
```

Always the `public` app: the internal one adds only the root routes, which the client never
calls.

Releases are cut by pushing a `v<version>` tag matching `src/atb_client/_version.py`; GitHub
Actions builds and publishes to PyPI by trusted publishing.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
