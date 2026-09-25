"""``client.structures`` — structure search and RMSD alignment."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Union

from .. import _ops
from .._base import Resource, operation
from ..models import RMSDResult, StructureSearchResult

DEFAULT_SEARCH_TIMEOUT = 600.0


class Structures(Resource):
    """``client.structures`` — structure search and RMSD alignment."""

    @operation
    def search(
        self,
        structure: str,
        *,
        format: str = "pdb",
        netcharge: Union[int, str] = "*",
        limit: Optional[int] = None,
        wait: bool = True,
        timeout: Optional[float] = DEFAULT_SEARCH_TIMEOUT,
    ):
        """``POST /structures/search`` → :class:`StructureSearchResult`: public
        molecules of the same formula and net charge, aligned by Blind-RMSD, closest
        first. ``is_identical`` is the submission duplicate threshold.

        ``netcharge="*"`` matches any charge. The search is budgeted (~105 s
        server-side): ``.complete`` is ``False`` when some candidates were not aligned
        in time (listed with ``compared=False``). ``422`` if the structure could not
        be read or built, or if a SMILES's own formal charge is not ``netcharge``
        (``netcharge-mismatch``).

        With ``wait=False`` the call returns at once with a :class:`Job` whose
        ``.result(timeout=...)`` blocks for the same shape (as a raw dict); a search
        answered immediately comes back as an already-done job.
        """
        body: Dict[str, Any] = {"structure": structure, "format": format, "netcharge": netcharge}
        if limit is not None:
            body["limit"] = limit
        kind, value = yield from _ops.call_with_wait(
            self._client,
            "POST",
            "structures/search",
            deadline=_ops.Deadline(timeout),
            json=body,
            wait=0 if not wait else None,
            follow_job=wait,
        )
        if not wait:
            if kind == "job":
                return value
            from ..models import Job

            return _ops.bind(
                Job(state="done", kind="structure_search", result=value.json()), self._client
            )
        result = value.json() if kind == "response" else value.result_
        return StructureSearchResult.model_validate(result)

    @operation
    def rmsd(
        self,
        *,
        molids: Optional[Iterable[int]] = None,
        structures: Optional[Iterable[str]] = None,
        timeout: Optional[float] = DEFAULT_SEARCH_TIMEOUT,
    ):
        """``POST /structures/rmsd`` → :class:`RMSDResult`.

        Aligns 2 to 10 inputs in all: ``molids`` (each molecule's optimised all-atom
        structure, else its normalised submitted one) first, then ``structures`` (PDB
        texts), and returns the pairwise RMSD matrix in nm; ``.rmsd`` is the
        two-input answer. A pair whose molecular graphs differ has ``None``. A merged
        duplicate molid is resolved to its canonical molecule by the server.

        Two small structures are compared inline; more, or larger ones, run as a
        server job, which this call waits for up to ``timeout`` seconds."""
        body: Dict[str, List[Any]] = {}
        if molids is not None:
            body["molids"] = [int(m) for m in molids]
        if structures is not None:
            body["structures"] = list(structures)
        if not 2 <= sum(len(v) for v in body.values()) <= 10:
            raise ValueError("give between 2 and 10 molids and structures in total")
        kind, value = yield from _ops.call_with_wait(
            self._client,
            "POST",
            "structures/rmsd",
            deadline=_ops.Deadline(timeout),
            json=body,
        )
        result = value.json() if kind == "response" else value.result_
        return RMSDResult.model_validate(result)
