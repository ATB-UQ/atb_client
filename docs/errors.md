# Errors

Server errors are RFC 9457 problem details. Each is mapped to an exception by its `type`
slug first (the last path segment of the problem `type` URL, e.g. `duplicate-molecule`), and
by HTTP status second — so a server adding a new slug still produces the right family of
exception. Every server-side exception carries `.status` and `.problem` (the parsed body,
extra members kept).

## Hierarchy

```
ATBError
├── APIError                     (.status, .problem, .type, .slug, .title, .detail)
│   ├── ValidationError          400  validation-error, invalid-request, bad-request, ...
│   │   ├── PayloadTooLarge      413  payload-too-large, structure-too-large, batch-too-large
│   │   └── IdempotencyKeyReused 422  idempotency-key-reused      (.job_id)
│   ├── AuthenticationError      401  unauthenticated, invalid-key, key-expired, ...
│   ├── PermissionDenied         403  forbidden, insufficient-scope, not-visible, ...
│   ├── NotFound                 404  not-found, job-not-found, file-not-found, ...
│   │   ├── MoleculeNotFound     404  molecule-not-found          (.molid)
│   │   ├── CompoundNotFound     404  compound-not-found          (.compound_id)
│   │   └── RotamerJobNotFound   404  rotamer-job-not-found       (.job_id)
│   ├── MoleculeMoved            301  molecule-moved              (.molid, .canonical_molid, .location)
│   ├── Conflict                 409  conflict, generation-locked, molecule-public, ...
│   │   ├── GenerationRequired   409  generation-required         (.name)
│   │   ├── DuplicateMolecule    409  duplicate-molecule          (.molid, .compound_id, .molecule)
│   │   └── RotamerJobExists     409  rotamer-job-exists          (.job_id, .state)
│   ├── TopologyVersionGone      410  topology-version-gone, job-result-expired
│   ├── ChemistryRejected        422  chemistry-rejected, infeasible-structure, ...  (.reason)
│   │   └── RemapRefused         422  remap-refused               (.report)
│   ├── RateLimited              429  rate-limited, burst-limit-exceeded, ...  (.retry_after, .limit)
│   └── ServerError              5xx  server-error, internal-error
│       └── ServiceUnavailable   503  service-unavailable, ...    (.retry_after)
├── ConfigurationError                bad config file, unsafe URL, unknown profile
├── NetworkError                      unreachable after every retry (`__cause__` is the httpx error)
├── MoleculeFailed                    `wait()` reached stage `failed`  (.molid, .status)
├── MoleculeRejected                  `wait()` reached stage `rejected`  (.molid, .status)
├── JobFailed                         a server-side job ended `failed`  (.job)
├── RotamerJobFailed                  `rotamer_jobs.wait()` found the job failed or cancelled  (.job)
└── Timeout                           the caller's timeout elapsed  (.job, .status, .pending, .rotamer_job)
```

Rotamer-job slugs without a class of their own: `target-required`, `no-searchable-molecule` and
`private-parent` are `ValidationError` (422); `rotamer-job-finished` is `Conflict`;
`schema-missing` is `ServiceUnavailable`.

The full slug-to-exception table is `atb_client.exceptions._BY_SLUG`; see the
[exceptions reference](reference/exceptions.md) for every class's fields.

## Retrying

Transient failures — 429, 502, 503, 504, connection errors — are retried automatically with
backoff (see the [usage guide](usage.md#rate-limits-and-retries)). Everything else is raised
straight to the caller.
