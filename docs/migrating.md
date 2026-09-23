# Migrating from atb_api

`atb_client.legacy` keeps scripts written against `from atb_api import API` running on API v1
with one changed import line:

```python
from atb_client.legacy import API          # was: from atb_api import API

api = API(api_token="<your key>")
for molecule in api.Molecules.search(common_name="Pterostilbene", match_partial=False):
    print(molecule.inchi)
    molecule.download_file(fnme=f"{molecule.molid}.pdb", atb_format="pdb_aa")
```

It covers `Molecules.search`/`molid`/`molids`/`download_file`/`structure_search`/`submit`
and `RMSD.align`/`matrix`, maps the old `atb_format` names (`pdb_aa`, `mtb_ua`, `itp_aa`,
`lgf`, `yml`, `pdb_allatom_optimised`, ...) to v1 file names, and emits a
`DeprecationWarning`. Your existing token keeps working as a v1 key.

What differs from the original, deliberately:

- the wire format is JSON only; `api_format` is accepted and ignored (YAML and pickle are
  gone). `atb_format='yml'` returns the file's text, not parsed YAML;
- errors raise `atb_client.exceptions` classes (carrying the server's problem body) instead
  of `urllib.error.HTTPError` with the body drained;
- the token travels in an `Authorization` header, never the query string.

The two packages install side by side (different import names), so migrate at your own pace
— but write new code against `ATBClient` directly.

| `atb_api` | `atb_client` |
|---|---|
| `API(api_token=...)` | `ATBClient()` (key from env/config) |
| `api.Molecules.search(...)` | `atb.molecules.search(...).all()` |
| `api.Molecules.molid(molid=21)` | `atb.molecules.get(21)` |
| `download_file(molid=21, atb_format="pdb_aa", fnme=p)` | `atb.files.download(21, "pdb_aa_opt", p)` |
| `api.Molecules.submit(pdb=..., netcharge=0, ...)` | `atb.molecules.submit(pdb_text, format="pdb", netcharge=0)` |
| `api.Molecules.structure_search(...)` | `atb.structures.search(...)` |
| `api.RMSD.align(molids=...)` | `atb.structures.rmsd(molids=...)` (always the full matrix) |

See `atb_client.legacy` in the [API reference](reference/client.md) for the complete
compatibility surface.
