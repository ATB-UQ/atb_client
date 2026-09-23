"""``client.pipeline`` — ``/pipeline/*``, the service-key-only surface the ATB's own
workers use (plan §6, §7, WP6). Present, not hidden: the server refuses any key that is
not a service key holding ``pipeline:qm`` / ``pipeline:write``.

These are the v0.1 ``qm_calculations/*`` and molecule write paths, reshaped to the
callers that exist (WP6 dossier §2.6): one molecule per job hand-out, keyed by
``qm_calculation_type``; claims accepted and released as an all-or-nothing batch; no
upload for the LGF (the server writes its own topology's). Every method returns the
server's JSON as plain ``dict``/``list`` -- the shapes v0.1 returned -- because the
callers are adapters that hand them on to code written against v0.1.

Retries: the idempotent calls retry like any other (a re-sent result overwrites the
store and the ledger row; a late failure report is a no-op). ``qm.accept`` does **not**
retry: a retried accept whose first attempt had succeeded would be refused as "already
locked", and the caller could not tell the two apart.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .. import _ops
from .._base import Resource, operation

DEFAULT_GENERATION_TIMEOUT = 900.0


def _drop_none(**kwargs: Any) -> Dict[str, Any]:
    """Drop keyword arguments whose value is ``None``."""
    return {k: v for k, v in kwargs.items() if v is not None}


def _ids(molids: Iterable[int]) -> List[int]:
    return [int(molid) for molid in molids]


class PipelineQM(Resource):
    """``client.pipeline.qm`` — claim, poll and resolve QM calculations."""

    @operation
    def local_job(self, molid: int, calculation_type: str, *, rerun: bool = False):
        """``POST /pipeline/qm/local-jobs`` (v0.1 ``get_local``) → ``{molid,
        qm_calculation_type, starting_from, net_charge, files: {"input.pdb": ...}}``.
        ``Conflict`` (``already-run``) without ``rerun``."""
        body = {"molid": int(molid), "calculation_type": calculation_type, "rerun": bool(rerun)}
        return (
            yield from _ops.json_call(self._client, "POST", "pipeline/qm/local-jobs", json=body)
        )

    @operation
    def gamess_job(
        self,
        molid: int,
        calculation_type: str,
        *,
        starting_from: Optional[str] = None,
        rerun: bool = False,
    ):
        """``POST /pipeline/qm/jobs`` (v0.1 ``get_specific``) → ``{molid,
        qm_calculation_type, starting_from, files: {"qm_input.inp": ...}}``."""
        body = _drop_none(
            molid=int(molid),
            calculation_type=calculation_type,
            starting_from=starting_from,
            rerun=bool(rerun),
        )
        return (yield from _ops.json_call(self._client, "POST", "pipeline/qm/jobs", json=body))

    @operation
    def offer(
        self,
        *,
        group: int,
        n: int = 10,
        qm_levels: Sequence[int] = (1,),
        min_atoms: Optional[int] = None,
        max_atoms: Optional[int] = None,
        sort: str = "id",
        order: str = "ASC",
    ):
        """``POST /pipeline/qm/jobs:offer`` (v0.1 ``get``) → ``{jobs: [job | None]}``.
        Claims nothing: claim with :meth:`accept`."""
        body = _drop_none(
            group=int(group),
            n=int(n),
            qm_levels=_ids(qm_levels),
            min_atoms=min_atoms,
            max_atoms=max_atoms,
            sort=sort,
            order=order,
        )
        return (
            yield from _ops.json_call(self._client, "POST", "pipeline/qm/jobs:offer", json=body)
        )

    @operation
    def accept(self, molids: Iterable[int], *, runner_id: str):
        """``POST /pipeline/qm/claims:accept`` (v0.1 ``accept``) → ``{molids}``: all
        claimed, or ``Conflict`` (``claims-refused``, ``.problem`` names them) and none.
        Never retried."""
        body = {"molids": _ids(molids), "runner_id": runner_id}
        return (
            yield from _ops.json_call(
                self._client, "POST", "pipeline/qm/claims:accept", json=body, retry=False
            )
        )

    @operation
    def release(self, molids: Iterable[int]):
        """``POST /pipeline/qm/claims:release`` (v0.1 ``release``) → ``{molids}``; all or none."""
        body = {"molids": _ids(molids)}
        return (
            yield from _ops.json_call(self._client, "POST", "pipeline/qm/claims:release", json=body)
        )

    @operation
    def sync(
        self,
        *,
        runner_id: str,
        running_molids: Iterable[int] = (),
        failed_molids: Iterable[int] = (),
    ):
        """``POST /pipeline/qm/claims:sync`` (v0.1 ``sync``) → ``{running, unknown,
        failed, lost}``."""
        body = {
            "runner_id": runner_id,
            "running_molids": _ids(running_molids),
            "failed_molids": _ids(failed_molids),
        }
        return (
            yield from _ops.json_call(self._client, "POST", "pipeline/qm/claims:sync", json=body)
        )

    @operation
    def local_result(
        self,
        molid: int,
        qm_calculation_type: str,
        qm_data: Dict[str, Any],
        *,
        geometry_pdb: str = "",
        starting_geometry_pdb: str = "",
    ):
        """``POST /pipeline/qm/local-results`` (v0.1 ``store_qm_data``) → ``{accepted,
        reason, ...}``. A rejection is ``accepted: False``, not an exception.
        ``qm_data`` is the dict itself, not its JSON text."""
        body = {
            "molid": int(molid),
            "qm_calculation_type": qm_calculation_type,
            "qm_data": qm_data,
            "geometry_pdb": geometry_pdb or "",
            "starting_geometry_pdb": starting_geometry_pdb or "",
        }
        return (
            yield from _ops.json_call(self._client, "POST", "pipeline/qm/local-results", json=body)
        )

    @operation
    def local_failure(self, molid: int, qm_calculation_type: str, status: str, *, reason: str = ""):
        """``POST /pipeline/qm/local-failures`` (v0.1 ``report_local_failure``) →
        ``{molid, qm_calculation_type, status, recorded}``. ``status`` is ``ERROR`` or
        ``NOT_CONVERGED``."""
        body = {
            "molid": int(molid),
            "qm_calculation_type": qm_calculation_type,
            "status": status,
            "reason": reason or "",
        }
        return (
            yield from _ops.json_call(self._client, "POST", "pipeline/qm/local-failures", json=body)
        )

    @operation
    def logs(self, items: Iterable[Tuple[int, str, str]], *, can_update_db: bool = True):
        """``POST /pipeline/qm/logs`` (v0.1 ``finished``) with ``(molid,
        qm_calculation_type, log)`` triples (at most 8) → ``{accepted_molids,
        verdicts}``. Decode a bytes log as UTF-8 with ``errors="replace"``."""
        body = {
            "items": [
                {"molid": int(molid), "qm_calculation_type": qm_type, "log": log}
                for (molid, qm_type, log) in items
            ],
            "can_update_db": bool(can_update_db),
        }
        return (yield from _ops.json_call(self._client, "POST", "pipeline/qm/logs", json=body))


class PipelineMolecules(Resource):
    """``client.pipeline.molecules`` — worker writes to a molecule's own fields."""

    @operation
    def remap_compound(self, molid: int, *, pdb: Optional[str] = None):
        """``POST /pipeline/molecules/{molid}/compound:remap`` (v0.1
        ``update_compound_id``) → ``{changed, old_compound_id, new_compound_id,
        created, message, ...}``."""
        return (
            yield from _ops.json_call(
                self._client,
                "POST",
                f"pipeline/molecules/{int(molid)}/compound:remap",
                json=_drop_none(pdb=pdb),
            )
        )

    @operation
    def update_compound(self, molid: int, *, overwrite: bool = False, **fields: Any):
        """``PATCH /pipeline/molecules/{molid}/compound`` (v0.1 ``compounds/set``,
        addressed by molecule). Without ``overwrite`` nothing is written unless every
        field sent is NULL on the compound: send only the missing ones."""
        body = dict(fields)
        body["overwrite"] = bool(overwrite)
        return (
            yield from _ops.json_call(
                self._client, "PATCH", f"pipeline/molecules/{int(molid)}/compound", json=body
            )
        )

    @operation
    def recompute_cpu_time(self, molid: int):
        """``POST /pipeline/molecules/{molid}/cpu-time:recompute`` (v0.1
        ``update_cpu_time``) → ``{molid, cpu_minutes}``."""
        return (
            yield from _ops.json_call(
                self._client, "POST", f"pipeline/molecules/{int(molid)}/cpu-time:recompute"
            )
        )

    def _job(self, molid: int, what: str, timeout: Optional[float]):
        kind, value = yield from _ops.call_with_wait(
            self._client,
            "POST",
            f"pipeline/molecules/{int(molid)}/{what}",
            deadline=_ops.Deadline(timeout),
        )
        return value.json() if kind == "response" else value.result_

    @operation
    def generate_topology(
        self, molid: int, *, timeout: Optional[float] = DEFAULT_GENERATION_TIMEOUT
    ):
        """``POST /pipeline/molecules/{molid}/topology:generate`` (v0.1
        ``generate_mol_data``): build every force field's topology where the cache
        says it must; follows the job up to ``timeout`` seconds."""
        return (yield from self._job(molid, "topology:generate", timeout))

    @operation
    def write_lgf(self, molid: int, *, timeout: Optional[float] = DEFAULT_GENERATION_TIMEOUT):
        """``POST /pipeline/molecules/{molid}/lgf`` (v0.1 ``write_LGF``) → ``{already,
        written_to, went_to_graphs_dir, message, topology_hash}``. Nothing is uploaded:
        the server writes its own topology's graph.lgf."""
        return (yield from self._job(molid, "lgf", timeout))

    @operation
    def put_validation(
        self,
        molid: int,
        kind: str,
        *,
        files: Optional[Dict[str, str]] = None,
        row: Optional[Dict[str, Any]] = None,
        overwrite: bool = True,
    ):
        """``PUT /pipeline/molecules/{molid}/validation/{kind}``: the result's files
        (EMinVac: ``EMinVac.pdb``, ``EMinVac_ref.pdb``, ``EMinVac.log``) and then,
        optionally, its row (``qm_level``, ``value``, ``uncertainty``,
        ``topology_hash``, ``completed``, ``overwrite``) -- written last."""
        body: Dict[str, Any] = {"files": dict(files or {}), "overwrite": bool(overwrite)}
        if row is not None:
            body["row"] = dict(row)
        return (
            yield from _ops.json_call(
                self._client,
                "PUT",
                f"pipeline/molecules/{int(molid)}/validation/{kind}",
                json=body,
            )
        )

    @operation
    def notify(self, molid: int, type: int, *, email: Optional[str] = None):
        """``POST /pipeline/molecules/{molid}/notify`` (v0.1 ``users/send_job_email``):
        email type 1 partial, 2 complete, 3 error → ``{sent, skipped_reason}``."""
        body = _drop_none(type=int(type), email=email)
        return (
            yield from _ops.json_call(
                self._client, "POST", f"pipeline/molecules/{int(molid)}/notify", json=body
            )
        )


class Pipeline(Resource):
    """``client.pipeline`` — the service-key-only worker surface."""

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.qm = PipelineQM(client)
        self.molecules = PipelineMolecules(client)
