"""``client.compounds`` -- compound-level reads (``/compounds/{id}/...``). A compound is
reached through its molecules: one with none visible to the key is 404, like one that
does not exist."""

from __future__ import annotations

from typing import Optional

from .. import _ops
from .._base import Resource, operation
from ..exceptions import CompoundNotFound
from ..models import CompoundConformers


class Compounds(Resource):
    """``client.compounds`` -- the conformers of a compound."""

    @operation
    def conformers(
        self,
        compound_id: int,
        *,
        max_relative_energy: Optional[float] = None,
        qm_type: Optional[str] = None,
        include_unscored: bool = True,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        """``GET /compounds/{compound_id}/conformers`` -> :class:`CompoundConformers`:
        every visible, error-free molecule of the compound with its energy relative to
        the lowest (kJ/mol), scored ones first by relative energy, optionally only those
        within ``max_relative_energy`` kJ/mol. ``qm_type`` is the method ranked by (default
        ``wB97X_631Gd_SMD_water``; also ``wB97X_321G_SMD_water`` and
        ``b3lyp_631Gd_PCM_water``). ``include_unscored`` keeps molecules with no energy yet
        (listed last). Pages of 200 (at most 1000); ``page.all()`` walks them. 404 ->
        :class:`CompoundNotFound`."""
        return (
            yield from _ops.offset_page_of(
                self._client,
                CompoundConformers,
                f"compounds/{int(compound_id)}/conformers",
                {
                    "max_relative_energy": max_relative_energy,
                    "qm_type": qm_type,
                    "include_unscored": include_unscored,
                    "limit": limit,
                    "offset": offset,
                },
                not_found=CompoundNotFound,
            )
        )
