# Admin

`client.admin.*` (`/admin/*`) is the administrator's surface: user accounts and their keys,
quota-request approval, molecule curation (`max_qm_level`, `curation_trust`, dataset/tag
flags), cache clearing and forced regeneration, dihedral scan requests, the audit log,
per-key usage, deletion requests, and the `stalled` molecule list.

Every call needs an API key carrying the `admin` scope, and every call — reads included —
is audited server-side. The one exception is
`client.admin.molecules.update(molid, max_qm_level=...)`: a `pipeline:write` service key may
also send that one field without `admin`.

```python
atb.admin.users.list("acme.edu")
atb.admin.molecules.update(21, max_qm_level=2)
atb.admin.audit(target_type="molecule", target_id=21)
```

Root operations — promoting an admin, deleting a molecule or an account, granting `admin` on
a key — are **not** part of this client. They exist only on the server's internal listener,
driven by its own `atb-api root` CLI, never over the public API.
