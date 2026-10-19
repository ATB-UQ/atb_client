# Admin

`client.admin.*` (`/admin/*`) is the administrator's surface: user accounts and their keys,
quota-request approval, molecule curation (`max_qm_level`, `curation_trust`, dataset/tag
flags), cache clearing and forced regeneration, dihedral scan requests, the audit log,
per-key usage, deletion requests, the `stalled` molecule list, and rotamer searches.

Every call needs an API key carrying the `admin` scope, and every call — reads included —
is audited server-side. The one exception is
`client.admin.molecules.update(molid, max_qm_level=...)`: a `pipeline:write` service key may
also send that one field without `admin`.

```python
atb.admin.users.list("acme.edu")
atb.admin.molecules.update(21, max_qm_level=2)
atb.admin.audit(target_type="molecule", target_id=21)
```

## Rotamer jobs

`client.admin.rotamer_jobs` requests and cancels conformer searches. Both need a key carrying
the `admin` scope (cluster time); a key without it gets `PermissionDenied`. Reading them is
open to every `read` key through `client.rotamer_jobs` and `client.compounds`.

```python
job = atb.admin.rotamer_jobs.create(compound_id=7, submission_budget=20, dry_run=True)
job = atb.rotamer_jobs.wait(job.id, until="complete")     # raises RotamerJobFailed
atb.admin.rotamer_jobs.create(compound_id=7, force=True)  # another job for a finished one
atb.admin.rotamer_jobs.cancel(job.id)                     # 202; the state follows shortly
```

Give exactly one of `molid` and `compound_id` (otherwise `ValidationError`, slug
`target-required`). A compound has one live job: a second request raises `RotamerJobExists`
(`.job_id`, `.state`), and so does one for a compound with a finished job unless `force=True`.
`public=True` on a private molecule is refused (`private-parent`); a compound with nothing to
search is `no-searchable-molecule`. Cancelling a finished job is a `Conflict`
(`rotamer-job-finished`).

Root operations — promoting an admin, deleting a molecule or an account, granting `admin` on
a key — are **not** part of this client. They exist only on the server's internal listener,
driven by its own `atb-api root` CLI, never over the public API.
