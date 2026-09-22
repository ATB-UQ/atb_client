"""``client.structures`` — structure search and RMSD alignment."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Union

from .. import _ops
from .._base import Resource, operation
from .._transport import json_of, request
from ..models import StructureMatch

DEFAULT_SEARCH_TIMEOUT = 600.0


def _matches(result: Any):
    return [StructureMatch.model_validate(m) for m in _ops.items_of(result)]


class Structures(Resource):
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
        """``POST /structures/search`` → ``list[StructureMatch]``.

        ``netcharge="*"`` matches any charge. With ``wait=False`` the call returns at
        once with a :class:`Job` whose ``.result(timeout=...)`` blocks for the matches
        (as raw dicts); a search answered immediately comes back as an already-done job.
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
        return _matches(result)

    @operation
    def rmsd(
        self,
        *,
        molids: Optional[Iterable[int]] = None,
        reference: Optional[str] = None,
        structures: Optional[Iterable[str]] = None,
        format: str = "pdb",
        matrix: bool = False,
    ):
        """``POST /structures/rmsd`` — align two structures (or molids), or with
        ``matrix=True`` all against all. Returns the server's JSON."""
        body: Dict[str, Any] = {"format": format, "matrix": matrix}
        if molids is not None:
            body["molids"] = [int(m) for m in molids]
        if reference is not None:
            body["reference"] = reference
        if structures is not None:
            body["structures"] = list(structures)
        response = yield from request(self._client, "POST", "structures/rmsd", json=body)
        return json_of(response)
