# atb-client

Python client and command-line tool for the [Automated Topology Builder](https://atb.uq.edu.au)
(ATB) API v1. Submit a structure, wait for its topology, download it in the format your
simulation engine wants, and search what already exists — from a script, with one API key.

- one package, sync and async (`ATBClient`, `AsyncATBClient`), Python 3.9+
- dependencies: `httpx` and `pydantic` 2 only
- retries with backoff on rate limits and transient server errors
- typed exceptions carrying the server's problem body
- an `atb` CLI whose exit codes a workflow engine can branch on

See the server's own [API guide](https://atb.uq.edu.au/api/v1/docs) for the wire protocol
this client wraps.

## Install

```bash
pip install atb-client
```

## Quick start

```python
from atb_client import ATBClient, DuplicateMolecule

atb = ATBClient()  # key from ATB_API_KEY, or a profile in ~/.config/atb/config.toml

try:
    mol = atb.molecules.submit(open("lig.pdb").read(), format="pdb", netcharge=0, public=True)
except DuplicateMolecule as dup:
    mol = dup.molecule  # a re-run adopts the existing entry

mol = mol.wait(timeout=6 * 3600)
mol.files.download("itp_aa", "lig.itp")
```

Next: the [usage guide](usage.md) covers keys, search, submission and downloads in full.
