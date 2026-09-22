"""Read-only reference data: the bonded-parameter library (``client.parameters``),
dihedral archetypes (``client.dihedrals``), tautomer groups (``client.tautomers``) and
site statistics (``client.statistics``). All need only the ``read`` scope."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .. import _ops
from .._base import Resource, operation
from ..models import (
    ArchetypeDetail,
    ArchetypePage,
    LibraryVersions,
    MotifDetail,
    MotifPage,
    Statistics,
    TautomerGroup,
)


class Parameters(Resource):
    """``/parameters/*``: the bonded-parameter (motif) library."""

    @operation
    def versions(self):
        """``GET /parameters/versions`` → :class:`LibraryVersions`: the published
        library versions (``items``) and the builds (``builds``)."""
        return (
            yield from _ops.page_of(
                self._client, None, "parameters/versions", {}, page_cls=LibraryVersions
            )
        )

    @operation
    def motifs(
        self,
        *,
        build_id: Optional[int] = None,
        kind: Optional[str] = None,
        depth: Optional[int] = None,
        element: Optional[str] = None,
        min_n: Optional[int] = None,
        max_n: Optional[int] = None,
        min_spread: Optional[float] = None,
        max_spread: Optional[float] = None,
        has_hessian: Optional[bool] = None,
        sort: Optional[str] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ):
        """``GET /parameters/motifs`` → :class:`MotifPage` (iterable over
        :class:`MotifSummary`; ``.all()`` walks every page)."""
        params: Dict[str, Any] = {
            "build_id": build_id,
            "kind": kind,
            "depth": depth,
            "element": element,
            "min_n": min_n,
            "max_n": max_n,
            "min_spread": min_spread,
            "max_spread": max_spread,
            "has_hessian": has_hessian,
            "sort": sort,
            "order": order,
            "limit": limit,
            "cursor": cursor,
        }
        return (
            yield from _ops.page_of(
                self._client, None, "parameters/motifs", params, page_cls=MotifPage
            )
        )

    @operation
    def motif(
        self,
        key: str,
        *,
        kind: Optional[str] = None,
        depth: Optional[int] = None,
        build_id: Optional[int] = None,
    ):
        """``GET /parameters/motifs/{key}`` → :class:`MotifDetail`."""
        return (
            yield from _ops.model_call(
                self._client,
                MotifDetail,
                "GET",
                f"parameters/motifs/{key}",
                params={"kind": kind, "depth": depth, "build_id": build_id},
            )
        )


class Dihedrals(Resource):
    """``/dihedrals/*``: fitted dihedral archetypes."""

    @operation
    def archetypes(
        self,
        *,
        in_ifp: Optional[bool] = None,
        fit_failed: Optional[bool] = None,
        flag: Optional[str] = None,
        molid: Optional[int] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        force_regen: Optional[bool] = None,
    ):
        """``GET /dihedrals/archetypes`` → :class:`ArchetypePage` (iterable over
        :class:`ArchetypeRow`; ``.summary`` counts the library). ``force_regen`` is
        admin-only."""
        params: Dict[str, Any] = {
            "in_ifp": in_ifp,
            "fit_failed": fit_failed,
            "flag": flag,
            "molid": molid,
            "limit": limit,
            "cursor": cursor,
            "force_regen": force_regen,
        }
        return (
            yield from _ops.page_of(
                self._client, None, "dihedrals/archetypes", params, page_cls=ArchetypePage
            )
        )

    @operation
    def archetype(self, archetype_id: str):
        """``GET /dihedrals/archetypes/{archetype_id}`` → :class:`ArchetypeDetail`."""
        return (
            yield from _ops.model_call(
                self._client, ArchetypeDetail, "GET", f"dihedrals/archetypes/{archetype_id}"
            )
        )


class TautomerGroups(Resource):
    """``/tautomers/groups/*``. A molecule's own family is ``molecules.tautomers()``."""

    @operation
    def group(self, group_id: str, *, limit: Optional[int] = None, cursor: Optional[str] = None):
        """``GET /tautomers/groups/{group_id}`` → :class:`TautomerGroup` (iterable over
        :class:`TautomerMember`; ``.all()`` walks every page)."""
        return (
            yield from _ops.page_of(
                self._client,
                None,
                f"tautomers/groups/{group_id}",
                {"limit": limit, "cursor": cursor},
                page_cls=TautomerGroup,
            )
        )


class SiteStatistics(Resource):
    """``GET /statistics``."""

    @operation
    def get(
        self,
        name: Optional[str] = None,
        *,
        include_validation_set: Optional[bool] = None,
        force_regen: Optional[bool] = None,
    ):
        """``GET /statistics`` → :class:`Statistics`: every indicator's latest value;
        with ``name``, that indicator's whole ``series`` too. ``force_regen`` is
        admin-only."""
        return (
            yield from _ops.model_call(
                self._client,
                Statistics,
                "GET",
                "statistics",
                params={
                    "name": name,
                    "include_validation_set": include_validation_set,
                    "force_regen": force_regen,
                },
            )
        )
