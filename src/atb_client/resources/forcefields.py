"""``client.forcefields`` — the IFP/MTB reference files per force field."""

from __future__ import annotations

from typing import Any, Optional

from .. import _ops
from .._base import Resource, operation
from .._transport import json_of, request


def _text_or_path(result: Any) -> Any:
    return result.decode("utf-8") if isinstance(result, bytes) else result


class Forcefields(Resource):
    @operation
    def list(self):
        """``GET /forcefields``."""
        response = yield from request(self._client, "GET", "forcefields")
        return list(_ops.items_of(json_of(response)))

    @operation
    def ifp(
        self, ff: str, *, format: str = "gxx", path: Any = None, timeout: Optional[float] = 120
    ):
        """``GET /forcefields/{ff}/ifp?format=gxx|g96`` → text, or the path written."""
        result = yield from _ops.download(
            self._client,
            f"forcefields/{ff}/ifp",
            target=path,
            default_name=f"{ff}.ifp",
            params={"format": format},
            timeout=timeout,
        )
        return _text_or_path(result)

    @operation
    def mtb(self, ff: str, *, path: Any = None, timeout: Optional[float] = 120):
        """``GET /forcefields/{ff}/mtb`` → text, or the path written."""
        result = yield from _ops.download(
            self._client,
            f"forcefields/{ff}/mtb",
            target=path,
            default_name=f"{ff}.mtb",
            timeout=timeout,
        )
        return _text_or_path(result)

    @operation
    def lammps(self, ff: str, *, path: Any = None, timeout: Optional[float] = 120):
        """``GET /forcefields/{ff}/lammps`` → text, or the path written."""
        result = yield from _ops.download(
            self._client,
            f"forcefields/{ff}/lammps",
            target=path,
            default_name=f"{ff}.lammps",
            timeout=timeout,
        )
        return _text_or_path(result)
