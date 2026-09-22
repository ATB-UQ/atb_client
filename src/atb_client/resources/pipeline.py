"""``client.pipeline`` — ``/pipeline/*``, the service-key-only surface the ATB's own
workers use (plan §6, §7). Present, not hidden: the server refuses a key without the
``pipeline:*`` scopes. These rename the ``qm_calculations/*`` and molecule write paths;
their claim/resolve semantics are the QM drivers' and do not change here."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from .. import _ops
from .._base import Resource, operation


def _drop_none(**kwargs: Any) -> Dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}


class PipelineQM(Resource):
    @operation
    def claim(self, *, level: int, n: int = 1, runner_id: str, group: Optional[str] = None):
        """``POST /pipeline/qm/claims`` → the claimed molecules with their decks/inputs."""
        body = _drop_none(level=level, n=n, runner_id=runner_id, group=group)
        return (yield from _ops.json_call(self._client, "POST", "pipeline/qm/claims", json=body))

    @operation
    def claims(self, *, runner_id: str, changed_since: Optional[str] = None):
        """``GET /pipeline/qm/claims?runner_id=&changed_since=`` — which of my running
        molecules changed."""
        return (yield from _ops.json_call(
            self._client, "GET", "pipeline/qm/claims",
            params={"runner_id": runner_id, "changed_since": changed_since}))

    @operation
    def release(self, molid: int, *, reason: Optional[str] = None):
        """``DELETE /pipeline/qm/claims/{molid}``."""
        return (yield from _ops.json_call(
            self._client, "DELETE", f"pipeline/qm/claims/{int(molid)}",
            params={"reason": reason}))

    @operation
    def sync(self, *, runner_id: str, molids: Any = None, **extra: Any):
        """``POST /pipeline/qm/claims:sync`` — reconcile a runner's view with the ledger."""
        body = _drop_none(runner_id=runner_id, molids=list(molids) if molids else None, **extra)
        return (yield from _ops.json_call(self._client, "POST", "pipeline/qm/claims:sync",
                                          json=body))

    @operation
    def results(
        self,
        *,
        molid: int,
        level: int,
        method: str,
        qm_data: Optional[Union[str, Dict[str, Any]]] = None,
        log: Optional[str] = None,
        geometry: Optional[str] = None,
    ):
        """``POST /pipeline/qm/results`` — store a finished calculation."""
        body = _drop_none(molid=molid, level=level, method=method, qm_data=qm_data, log=log,
                          geometry=geometry)
        return (yield from _ops.json_call(self._client, "POST", "pipeline/qm/results", json=body))

    @operation
    def failures(self, *, molid: int, level: int, status: str, reason: Optional[str] = None,
                 method: Optional[str] = None):
        """``POST /pipeline/qm/failures`` — report a failed calculation."""
        body = _drop_none(molid=molid, level=level, status=status, reason=reason, method=method)
        return (yield from _ops.json_call(self._client, "POST", "pipeline/qm/failures",
                                          json=body))


class PipelineMolecules(Resource):
    @operation
    def update(self, molid: int, **fields: Any):
        """``PATCH /pipeline/molecules/{molid}`` — ``cpu_time``, ``max_qm_level``, ``iupac``."""
        return (yield from _ops.json_call(self._client, "PATCH",
                                          f"pipeline/molecules/{int(molid)}", json=fields))

    @operation
    def update_compound(self, molid: int, **fields: Any):
        """``PATCH /pipeline/molecules/{molid}/compound`` — the ``compounds/set`` field set."""
        return (yield from _ops.json_call(self._client, "PATCH",
                                          f"pipeline/molecules/{int(molid)}/compound",
                                          json=fields))

    @operation
    def put_lgf(self, molid: int, lgf: str):
        """``PUT /pipeline/molecules/{molid}/lgf``."""
        return (yield from _ops.json_call(self._client, "PUT",
                                          f"pipeline/molecules/{int(molid)}/lgf",
                                          content=lgf.encode("utf-8"),
                                          headers={"Content-Type": "text/plain"}))

    @operation
    def put_validation(self, molid: int, kind: str, **payload: Any):
        """``PUT /pipeline/molecules/{molid}/validation/{kind}`` (rows + EMinVac files)."""
        return (yield from _ops.json_call(self._client, "PUT",
                                          f"pipeline/molecules/{int(molid)}/validation/{kind}",
                                          json=payload))

    @operation
    def notify(self, molid: int, **payload: Any):
        """``POST /pipeline/molecules/{molid}/notify`` — the submitter email."""
        return (yield from _ops.json_call(self._client, "POST",
                                          f"pipeline/molecules/{int(molid)}/notify",
                                          json=payload))


class Pipeline(Resource):
    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.qm = PipelineQM(client)
        self.molecules = PipelineMolecules(client)

    @operation
    def callback(self, molid: int, event: str):
        """``POST /pipeline/callbacks`` — fan an event out to stored ``callback_url``s."""
        return (yield from _ops.json_call(self._client, "POST", "pipeline/callbacks",
                                          json={"molid": molid, "event": event}))
