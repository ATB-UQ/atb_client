"""``client.forcefields`` — the IFP/MTB reference files per force field."""

from __future__ import annotations

from typing import Any, Optional

from .. import _ops
from .._base import Resource, operation
from ..models import ForcefieldList


def _text_or_path(result: Any) -> Any:
    """Decode a fetched result to text unless it is a path."""
    return result.decode("utf-8") if isinstance(result, bytes) else result


class Forcefields(Resource):
    """``client.forcefields`` — the IFP/MTB reference files per force field."""

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
        version: Optional[int] = None,
        ifp_hash: Optional[str] = None,
        path: Any = None,
    ):
        """``GET /forcefields/{ff}/ifp`` → text, or the path written.

        ``format`` is ``"gxx"`` (``<ff>.ifp``) or ``"g96"`` (``IFP<ff>.dat``); left
        out, the server's default: ``g96`` while the server reads its database, ``gxx``
        once it serves the parameter library, where ``g96`` raises :class:`Retired`.
        ``version`` picks a version of the force field's parameter set (library
        servers; default its head, ``forcefields.list()`` lists them; a database
        server answers :class:`NotFound`). ``rules=True`` fetches the rules file, which
        a library server has retired (:class:`Retired`). ``ifp_hash`` selects a stored
        IFP version (its md5), as an old topology names it."""
        result = yield from _ops.fetch_file(
            self._client,
            f"forcefields/{ff}/ifp",
            target=path,
            default_name=f"{ff}.ifp",
            params={
                "format": format,
                "rules": rules or None,
                "version": version,
                "ifp_hash": ifp_hash,
            },
        )
        return _text_or_path(result)

    @operation
    def mtb(self, ff: str, *, format: Optional[str] = None, path: Any = None):
        """``GET /forcefields/{ff}/mtb`` → text, or the path written. ``format`` is
        ``"gxx"`` or ``"g96"``; left out, the server's default (``g96``, then ``gxx`` once
        the server serves the parameter library, where ``g96`` raises :class:`Retired`)."""
        result = yield from _ops.fetch_file(
            self._client,
            f"forcefields/{ff}/mtb",
            target=path,
            default_name=f"{ff}.mtb",
            params={"format": format},
        )
        return _text_or_path(result)

    @operation
    def lammps(
        self,
        ff: str,
        *,
        version: Optional[int] = None,
        ifp_hash: Optional[str] = None,
        path: Any = None,
    ):
        """``GET /forcefields/{ff}/lammps`` → text, or the path written: the GXX IFP
        converted for LAMMPS -- of ``version`` of the parameter set (library servers;
        default its head) or of a stored version by ``ifp_hash``."""
        result = yield from _ops.fetch_file(
            self._client,
            f"forcefields/{ff}/lammps",
            target=path,
            default_name=f"{ff}.lammps",
            params={"version": version, "ifp_hash": ifp_hash},
        )
        return _text_or_path(result)
