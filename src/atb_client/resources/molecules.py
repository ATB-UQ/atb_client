"""``client.molecules`` — search, get, status, the read-only sub-resources, changes;
and submission, batch, wait.

Served by the WP2 server: ``get``, ``status``, ``search``, ``changes``, ``topologies``,
``qm``, ``validation``, ``solvation``, ``parameters``, ``tautomers``,
``conformations``. Not yet (WP3): ``submit``, ``submit_batch``, ``update``,
``request_deletion``, ``flag``; their request shapes follow the plan (§6) and will
be checked against the server when it publishes them.

A merged duplicate molid is redirected by the server (``301``) to its canonical
molecule and the client follows it, so ``get(20)`` can return molecule 21.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from .. import _ops
from .._base import Resource, operation, stream_operation
from .._transport import Emit, Sleep, json_of, request
from ..exceptions import MoleculeNotFound, Timeout
from ..models import (
    BatchResult,
    BondedParameters,
    Change,
    Conformations,
    Molecule,
    MoleculeStatus,
    QMSummary,
    Solvation,
    Tautomers,
    Topologies,
    Validation,
)

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
        """``GET /molecules`` → ``Page[Molecule]``, in molid order.

        Filters are the server's: text ``inchi_key`` (standard), ``inchi``, ``smiles``,
        ``common_name``, ``formula``, ``iupac``, ``chembl_id``, ``pdb_hetid``, ``rnme``,
        ``moltype``, ``user_label`` (exact, or substring with ``match="partial"``);
        ``q`` (free text, always partial); lists ``ids``, ``qm_level``,
        ``max_qm_level``, ``curation_trust``; ``min_atoms``, ``max_atoms``; booleans
        ``is_finished``, ``has_error``, ``has_ti``, ``public``; ``tag``; ``owner``
        (``"me"``, or a user id for admin/service keys); ``submitted_after`` (a
        datetime). Lists are sent comma-separated, booleans as ``true``/``false``.
        ``fields`` narrows each item to the named summary fields (``molid`` always
        included). A partial match costs 10 quota units rather than 1. ``limit`` is at
        most 200 (1000 for admin and service keys). ``total`` is set only when the
        whole result is on the first page. Iterate the page for its items; ``.all()``
        walks every page.
        """
        params: Dict[str, Any] = dict(filters, limit=limit, cursor=cursor, fields=fields)
        return (yield from _ops.page_of(self._client, Molecule, "molecules", params))

    @operation
    def changes(self, since: Optional[Union[str, datetime]] = None, *, limit: Optional[int] = None):
        """``GET /molecules/changes?since=`` → ``Page[Change]``, oldest change first
        (costs no quota).

        ``since`` is a ``next_cursor`` from a previous call or a datetime; the default
        is the last 24 hours. The server returns a ``next_cursor`` on every page, empty
        ones included: keep the last one you saw as the next ``since``. ``.all()``
        stops at the first empty page."""
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

    def _sub(self, model: Any, molid: int, what: str, params: Optional[Dict[str, Any]] = None):
        return (
            yield from _ops.model_call(
                self._client,
                model,
                "GET",
                f"molecules/{int(molid)}/{what}",
                params=params,
                not_found=MoleculeNotFound,
            )
        )

    @operation
    def topologies(self, molid: int):
        """``GET /molecules/{molid}/topologies`` → :class:`Topologies`: every stored
        topology version per force field, newest first."""
        return (yield from self._sub(Topologies, molid, "topologies"))

    @operation
    def qm(self, molid: int, *, level: Optional[Union[int, str]] = None):
        """``GET /molecules/{molid}/qm`` → :class:`QMSummary`: which QM result each
        level's topology was built from. ``level`` is ``0``-``2`` or ``"qm0"``-``"qm2"``."""
        if isinstance(level, int):
            level = f"qm{level}"
        return (yield from self._sub(QMSummary, molid, "qm", {"level": level}))

    @operation
    def validation(self, molid: int):
        """``GET /molecules/{molid}/validation`` → :class:`Validation`: the vacuum
        energy-minimisation RMSD (nm), or why there is none."""
        return (yield from self._sub(Validation, molid, "validation"))

    @operation
    def solvation(self, molid: int):
        """``GET /molecules/{molid}/solvation`` → :class:`Solvation`: TI and experimental
        solvation free energies (kJ/mol)."""
        return (yield from self._sub(Solvation, molid, "solvation"))

    @operation
    def parameters(self, molid: int, *, ff: Optional[str] = None, hash: Optional[str] = None):
        """``GET /molecules/{molid}/parameters`` → :class:`BondedParameters`: the
        bonded-assignment record of the current (or ``hash``-pinned) topology for force
        field ``ff`` (default: the server's)."""
        return (
            yield from self._sub(BondedParameters, molid, "parameters", {"ff": ff, "hash": hash})
        )

    @operation
    def tautomers(self, molid: int):
        """``GET /molecules/{molid}/tautomers`` → :class:`Tautomers`: the visible
        members of the molecule's family, with energies (kJ/mol)."""
        return (yield from self._sub(Tautomers, molid, "tautomers"))

    @operation
    def conformations(self, molid: int):
        """``GET /molecules/{molid}/conformations`` → :class:`Conformations`."""
        return (yield from self._sub(Conformations, molid, "conformations"))
