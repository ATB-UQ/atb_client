"""``client.forcefields`` — the IFP/MTB reference files per force field."""

from __future__ import annotations

from typing import Any, Optional

from .. import _ops
from .._base import Resource, operation
from ..models import ForcefieldList


def _text_or_path(result: Any) -> Any:
    return result.decode("utf-8") if isinstance(result, bytes) else result


class Forcefields(Resource):
    @operation
    def list(self):
        """``GET /forcefields`` → :class:`ForcefieldList` (iterable over
        :class:`Forcefield`; ``.default_forcefield``)."""
        return (
            yield from _ops.page_of(self._client, None, "forcefields", {}, page_cls=ForcefieldList)
        )

    @operation
    def ifp(
        self,
        ff: str,
        *,
        format: Optional[str] = None,
        rules: bool = False,
        ifp_hash: Optional[str] = None,
        path: Any = None,
    ):
        """``GET /forcefields/{ff}/ifp`` → text, or the path written.

        ``format`` is ``"g96"`` (the server's default, ``IFP<ff>.dat``) or ``"gxx"``
        (``<ff>.ifp``); ``rules=True`` fetches the rules file instead; ``ifp_hash``
        selects a stored IFP version (its md5) instead of the current one."""
        result = yield from _ops.fetch_file(
            self._client,
            f"forcefields/{ff}/ifp",
            target=path,
            default_name=f"{ff}.ifp",
            params={"format": format, "rules": rules or None, "ifp_hash": ifp_hash},
        )
        return _text_or_path(result)

    @operation
    def mtb(self, ff: str, *, format: Optional[str] = None, path: Any = None):
        """``GET /forcefields/{ff}/mtb`` → text, or the path written. ``format`` is
        ``"g96"`` (default) or ``"gxx"``."""
        result = yield from _ops.fetch_file(
            self._client,
            f"forcefields/{ff}/mtb",
            target=path,
            default_name=f"{ff}.mtb",
            params={"format": format},
        )
        return _text_or_path(result)

    @operation
    def lammps(self, ff: str, *, ifp_hash: Optional[str] = None, path: Any = None):
        """``GET /forcefields/{ff}/lammps`` → text, or the path written: the GXX IFP
        (``ifp_hash``: a stored version) converted for LAMMPS."""
        result = yield from _ops.fetch_file(
            self._client,
            f"forcefields/{ff}/lammps",
            target=path,
            default_name=f"{ff}.lammps",
            params={"ifp_hash": ifp_hash},
        )
        return _text_or_path(result)
