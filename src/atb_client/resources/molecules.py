"""``client.molecules`` — search, get, submit, wait, changes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from .. import _ops
from .._base import Resource, operation, stream_operation
from .._transport import Emit, Sleep, json_of, request
from ..exceptions import MoleculeNotFound, Timeout
from ..models import BatchResult, Change, Molecule, MoleculeStatus

#: A submission's duplicate search is budgeted at ~105 s server-side; give it room.
DEFAULT_SUBMIT_TIMEOUT = 600.0


def _molecule_from_job(client: Any, result: Any):
    """A submission job's result references the molecule (``{"molid": ...}``); fetch it,
    since job results reference resources rather than inlining them (§6)."""
    molid = result.get("molid") if isinstance(result, dict) else result
    if molid is None:
        raise ValueError(f"submission job result names no molid: {result!r}")
    return (yield from _ops.get_molecule(client, int(molid)))


class Molecules(Resource):
    @operation
    def get(self, molid: int):
        """``GET /molecules/{molid}`` → :class:`Molecule`. 404 → :class:`MoleculeNotFound`."""
        return (yield from _ops.get_molecule(self._client, molid))

    @operation
    def status(self, molid: int):
        """``GET /molecules/{molid}/status`` → :class:`MoleculeStatus` (costs no quota)."""
        return (yield from _ops.get_status(self._client, molid))

    @operation
    def search(
        self,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        fields: Optional[Sequence[str]] = None,
        **filters: Any,
    ):
        """``GET /molecules`` → ``Page[Molecule]``.

        Filters are the server's (``inchi_key``, ``inchi``, ``smiles``, ``common_name``,
        ``formula``, ``iupac``, ``chembl_id``, ``pdb_hetid``, ``qm_level``,
        ``max_qm_level``, ``min_atoms``, ``max_atoms``, ``is_finished``, ``has_ti``,
        ``tag``, ``q``, ``owner``, ``ids``, ``public``, ``submitted_after``). Lists are
        sent comma-separated, booleans as ``true``/``false``. Iterate the page for its
        items; ``.all()`` walks every page.
        """
        params: Dict[str, Any] = dict(filters, limit=limit, cursor=cursor, fields=fields)
        return (yield from _ops.page_of(self._client, Molecule, "molecules", params))

    @operation
    def changes(self, since: Optional[str] = None, *, limit: Optional[int] = None):
        """``GET /molecules/changes?since=`` → ``Page[Change]`` (costs no quota).

        Keep ``page.next_cursor`` (or the last page's, after ``.all()``) as the next
        ``since``."""
        params = {"since": since, "limit": limit}
        return (yield from _ops.page_of(self._client, Change, "molecules/changes", params))

    @operation
    def submit(
        self,
        structure: str,
        *,
        format: str = "pdb",
        netcharge: int,
        public: bool = True,
        client_reference: Optional[str] = None,
        max_qm_level: Optional[int] = None,
        moltype: Optional[str] = None,
        callback_url: Optional[str] = None,
        timeout: Optional[float] = DEFAULT_SUBMIT_TIMEOUT,
    ):
        """``POST /molecules`` → the new :class:`Molecule`.

        Raises :class:`DuplicateMolecule` (``.molid``, ``.molecule``) when the structure
        already exists — the normal outcome of a re-run — and :class:`ChemistryRejected`
        when it is refused. A slow duplicate search is followed as a job, up to
        ``timeout`` seconds.
        """
        body: Dict[str, Any] = {
            "structure": structure,
            "format": format,
            "netcharge": netcharge,
            "public": public,
        }
        for key, value in (
            ("client_reference", client_reference),
            ("max_qm_level", max_qm_level),
            ("moltype", moltype),
            ("callback_url", callback_url),
        ):
            if value is not None:
                body[key] = value
        kind, value = yield from _ops.call_with_wait(
            self._client, "POST", "molecules", deadline=_ops.Deadline(timeout), json=body
        )
        if kind == "response":
            return _ops.bind(Molecule.model_validate(value.json()), self._client)
        return (yield from _molecule_from_job(self._client, value.result_))

    @operation
    def submit_batch(
        self,
        *,
        sdf: Optional[str] = None,
        structures: Optional[List[Dict[str, Any]]] = None,
        netcharge_field: Optional[str] = None,
        reference_field: Optional[str] = None,
        public: bool = True,
        netcharge: Optional[int] = None,
        timeout: Optional[float] = DEFAULT_SUBMIT_TIMEOUT,
    ):
        """``POST /molecules:batch`` (≤ 100 items) → :class:`BatchResult`.

        Give either ``sdf`` (text; per-record charge and reference read from the SD
        fields named by ``netcharge_field``/``reference_field``) or ``structures``, a
        list of ``submit()``-shaped dicts. ``result.molids`` lists every molid resolved,
        duplicates included; per-item problems are in ``result.items``.
        """
        if (sdf is None) == (structures is None):
            raise ValueError("give exactly one of sdf= or structures=")
        body: Dict[str, Any] = {"public": public}
        if sdf is not None:
            body["sdf"] = sdf
        else:
            body["structures"] = structures
        for key, value in (
            ("netcharge_field", netcharge_field),
            ("reference_field", reference_field),
            ("netcharge", netcharge),
        ):
            if value is not None:
                body[key] = value
        kind, value = yield from _ops.call_with_wait(
            self._client, "POST", "molecules:batch", deadline=_ops.Deadline(timeout), json=body
        )
        result = value.json() if kind == "response" else value.result_
        if isinstance(result, list):
            result = {"items": result}
        return BatchResult.model_validate(result)

    @stream_operation
    def wait_all(
        self,
        molids: Iterable[int],
        timeout: Optional[float] = None,
        *,
        poll_interval: float = 15.0,
        max_interval: float = 300.0,
    ):
        """Yield ``(molid, MoleculeStatus)`` as each molecule reaches a terminal stage.

        Unlike ``Molecule.wait()`` this does not raise on ``failed``/``rejected``: the
        status is yielded and the caller decides. Raises :class:`Timeout` (``.pending``
        lists what never ended) if ``timeout`` passes first. Status polls cost no quota.
        """
        pending = list(dict.fromkeys(int(m) for m in molids))
        deadline = _ops.Deadline(timeout)
        interval = poll_interval
        while pending:
            still: List[int] = []
            for molid in pending:
                status: MoleculeStatus = yield from _ops.get_status(self._client, molid)
                if status.is_terminal:
                    yield Emit((molid, status))
                else:
                    still.append(molid)
            pending = still
            if not pending:
                return
            if deadline.expired():
                raise Timeout(f"{len(pending)} molecule(s) still running", pending=pending)
            yield Sleep(deadline.clamp(interval))
            interval = min(max_interval, interval * _ops.MOLECULE_POLL_FACTOR)

    @operation
    def update(
        self, molid: int, *, public: Optional[bool] = None, user_label: Optional[str] = None
    ):
        """``PATCH /molecules/{molid}`` (owner): make public (one-way) or label it."""
        body = {k: v for k, v in (("public", public), ("user_label", user_label)) if v is not None}
        response = yield from request(
            self._client, "PATCH", f"molecules/{int(molid)}", json=body, not_found=MoleculeNotFound
        )
        return _ops.bind(Molecule.model_validate(response.json()), self._client)

    @operation
    def request_deletion(self, molid: int, *, reason: Optional[str] = None):
        """``POST /molecules/{molid}/deletion-requests`` (owner of a private molecule)."""
        response = yield from request(
            self._client,
            "POST",
            f"molecules/{int(molid)}/deletion-requests",
            json={"reason": reason} if reason else {},
            not_found=MoleculeNotFound,
        )
        return json_of(response)

    @operation
    def flag(self, molid: int, *, reason: str):
        """``POST /molecules/{molid}/flags`` — report a problem with a molecule."""
        response = yield from request(
            self._client,
            "POST",
            f"molecules/{int(molid)}/flags",
            json={"reason": reason},
            not_found=MoleculeNotFound,
        )
        return json_of(response)

    def _sub(self, molid: int, what: str, params: Optional[Dict[str, Any]] = None):
        response = yield from request(
            self._client,
            "GET",
            f"molecules/{int(molid)}/{what}",
            params=params,
            not_found=MoleculeNotFound,
        )
        return json_of(response)

    @operation
    def topologies(self, molid: int):
        """``GET /molecules/{molid}/topologies`` — topology hashes with generation dates."""
        return (yield from self._sub(molid, "topologies"))

    @operation
    def qm(self, molid: int, *, level: Optional[int] = None):
        """``GET /molecules/{molid}/qm`` — QM summary per level."""
        return (yield from self._sub(molid, "qm", {"level": level}))

    @operation
    def validation(self, molid: int):
        """``GET /molecules/{molid}/validation`` — EMinVac RMSD and check-top result."""
        return (yield from self._sub(molid, "validation"))

    @operation
    def solvation(self, molid: int):
        """``GET /molecules/{molid}/solvation`` — TI and experimental free energies."""
        return (yield from self._sub(molid, "solvation"))

    @operation
    def parameters(self, molid: int, *, hash: Optional[str] = None):
        """``GET /molecules/{molid}/parameters`` — the bonded-assignment record."""
        return (yield from self._sub(molid, "parameters", {"hash": hash}))

    @operation
    def tautomers(self, molid: int):
        """``GET /molecules/{molid}/tautomers``."""
        return (yield from self._sub(molid, "tautomers"))

    @operation
    def conformations(self, molid: int):
        """``GET /molecules/{molid}/conformations``."""
        return (yield from self._sub(molid, "conformations"))
