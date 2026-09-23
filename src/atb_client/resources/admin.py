"""``client.admin`` — ``/admin/*``. Needs a key carrying the ``admin`` scope; every
call is audited server-side. Thin typed calls; the server enforces what a key may do.

``AdminMolecules.update``'s ``max_qm_level`` is the one field a ``pipeline:write``
service key may also send (no ``admin`` scope needed for that field alone); every
other field and every other call here needs ``admin``."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Union

from .. import _ops
from .._base import Resource, operation
from .._transport import request
from ..models import (
    AdminUser,
    AdminUserDetail,
    ApiKey,
    AuditRow,
    CacheCleared,
    CurationResult,
    DeletionRequestPage,
    QuotaApproved,
    QuotaRequestItem,
    ScanCancelled,
    ScanQueued,
    StalledItem,
    StalledPage,
    UsagePage,
)

Id = Union[int, str]


def _drop_none(**kwargs: Any) -> Dict[str, Any]:
    """Drop keyword arguments whose value is ``None``."""
    return {k: v for k, v in kwargs.items() if v is not None}


class AdminUsers(Resource):
    """``client.admin.users`` — account listing, updates and key management."""

    @operation
    def list(
        self, q: Optional[str] = None, *, limit: Optional[int] = None, cursor: Optional[str] = None
    ):
        """``GET /admin/users?q=`` → ``Page[AdminUser]``. ``q`` matches part of an
        email, name or institute."""
        return (
            yield from _ops.page_of(
                self._client, AdminUser, "admin/users", {"q": q, "limit": limit, "cursor": cursor}
            )
        )

    @operation
    def get(self, user_id: Id):
        """``GET /admin/users/{id}`` → :class:`~atb_client.models.AdminUserDetail`."""
        response = yield from request(self._client, "GET", f"admin/users/{user_id}")
        return AdminUserDetail.model_validate(response.json())

    @operation
    def update(
        self,
        user_id: Id,
        *,
        user_class: Optional[int] = None,
        group_id: Optional[int] = None,
        expiry: Any = None,
        burst_per_min: Optional[int] = None,
        daily_limit: Optional[int] = None,
    ):
        """``PATCH /admin/users/{id}`` → the updated :class:`AdminUserDetail`.

        ``user_class`` is 1, 2, 3, 4 or 6 (class 5 is reached only through a root
        key); a class-1 account's approval is ``approval-on-site`` here -- it is done
        on the admin page instead, which issues and emails its password. ``expiry``
        and the limits go on every live key of the account; either can be sent as
        ``None`` explicitly to clear/reset it -- pass it with ``**{"expiry": None}``
        if the plain keyword would otherwise be omitted."""
        body = _drop_none(
            user_class=user_class,
            group_id=group_id,
            expiry=expiry,
            burst_per_min=burst_per_min,
            daily_limit=daily_limit,
        )
        response = yield from request(self._client, "PATCH", f"admin/users/{user_id}", json=body)
        return AdminUserDetail.model_validate(response.json())

    @operation
    def create_key(
        self,
        user_id: Id,
        *,
        name: str,
        scopes: Optional[Iterable[str]] = None,
        expires_in_days: Optional[int] = None,
        burst_per_min: Optional[int] = None,
        daily_limit: Optional[int] = None,
    ):
        """``POST /admin/users/{id}/keys`` → :class:`ApiKey` whose ``.key`` is the
        secret, shown once; hand it over out of band. Cannot grant ``admin`` (root's
        to do, ``POST /root/keys`` or ``PATCH /root/keys/{id}``)."""
        body = _drop_none(
            name=name,
            scopes=list(scopes) if scopes is not None else None,
            expires_in_days=expires_in_days,
            burst_per_min=burst_per_min,
            daily_limit=daily_limit,
        )
        response = yield from request(
            self._client, "POST", f"admin/users/{user_id}/keys", json=body
        )
        return ApiKey.model_validate(response.json())

    @operation
    def update_key(
        self,
        user_id: Id,
        key_id: Id,
        *,
        burst_per_min: Optional[int] = None,
        daily_limit: Optional[int] = None,
    ):
        """``PATCH /admin/users/{id}/keys/{kid}`` → the updated :class:`ApiKey`.
        Omitted: unchanged. ``None``: back to the class default. A key holding
        ``admin`` cannot be raised this way -- that is root's."""
        body = _drop_none(burst_per_min=burst_per_min, daily_limit=daily_limit)
        response = yield from request(
            self._client, "PATCH", f"admin/users/{user_id}/keys/{key_id}", json=body
        )
        return ApiKey.model_validate(response.json())

    @operation
    def revoke_key(self, user_id: Id, key_id: Id):
        """``DELETE /admin/users/{id}/keys/{kid}`` → ``None`` (``204``). Allowed on an
        administrator's own keys too: taking access away is never an escalation."""
        yield from request(self._client, "DELETE", f"admin/users/{user_id}/keys/{key_id}")
        return None


class AdminMolecules(Resource):
    """``client.admin.molecules`` — curation, cache and scan operations on one molecule."""

    @operation
    def update(
        self,
        molid: int,
        *,
        max_qm_level: Optional[int] = None,
        curation_trust: Optional[int] = None,
        datasets_add: Optional[Iterable[str]] = None,
        datasets_remove: Optional[Iterable[str]] = None,
        tags_add: Optional[Iterable[str]] = None,
        tags_remove: Optional[Iterable[str]] = None,
    ):
        """``PATCH /admin/molecules/{molid}`` → :class:`CurationResult`.

        ``max_qm_level`` re-enters the QM pipeline (v0.1 ``update_maximum_qm_level``)
        and is the one field a ``pipeline:write`` service key may also send; every
        other field needs the ``admin`` scope. ``curation_trust`` and the dataset/tag
        adds and removes are otherwise independent -- send any subset."""
        body: Dict[str, Any] = _drop_none(max_qm_level=max_qm_level, curation_trust=curation_trust)
        if datasets_add is not None or datasets_remove is not None:
            body["datasets"] = {
                "add": list(datasets_add or []),
                "remove": list(datasets_remove or []),
            }
        if tags_add is not None or tags_remove is not None:
            body["tags"] = {"add": list(tags_add or []), "remove": list(tags_remove or [])}
        response = yield from request(
            self._client, "PATCH", f"admin/molecules/{int(molid)}", json=body
        )
        return CurationResult.model_validate(response.json())

    @operation
    def cache_clear(self, molid: int, *, all: bool = False):
        """``POST /admin/molecules/{molid}/cache:clear`` → :class:`CacheCleared`.
        Current topology version only, unless ``all`` (v0.1 ``clear_cache``)."""
        response = yield from request(
            self._client, "POST", f"admin/molecules/{int(molid)}/cache:clear", json={"all": all}
        )
        return CacheCleared.model_validate(response.json())

    @operation
    def cache_invalidate(self, molid: int, *, wait: bool = True, timeout: Optional[float] = None):
        """``POST /admin/molecules/{molid}/cache:invalidate`` — rebuild the topology for
        every force field (v0.1 ``invalidate_cache``). A D8 job: the result within
        ``wait``, else the pending :class:`Job` (``wait=False``). The rebuilt version
        becomes current; older versions stay servable."""
        kind, value = yield from _ops.call_with_wait(
            self._client,
            "POST",
            f"admin/molecules/{int(molid)}/cache:invalidate",
            deadline=_ops.Deadline(timeout),
            wait=0 if not wait else None,
            follow_job=wait,
        )
        if kind == "job":
            return value.result_ if wait else value
        return value.json()

    @operation
    def regenerate(
        self,
        molid: int,
        *,
        forcefield: Optional[str] = None,
        wait: bool = True,
        timeout: Optional[float] = None,
    ):
        """``POST /molecules/{molid}/topologies`` — regenerate now, forced, for one
        force field or (default) every force field. A D8 job: the result within
        ``wait``, else the pending :class:`Job`."""
        kind, value = yield from _ops.call_with_wait(
            self._client,
            "POST",
            f"molecules/{int(molid)}/topologies",
            deadline=_ops.Deadline(timeout),
            json=_drop_none(forcefield=forcefield),
            wait=0 if not wait else None,
            follow_job=wait,
        )
        if kind == "job":
            return value.result_ if wait else value
        return value.json()

    @operation
    def request_scan(
        self,
        molid: int,
        *,
        dihedral_atoms: Iterable[int],
        method: str,
        mode: str = "partial",
        execution: Optional[str] = None,
        dihedral_label: Optional[str] = None,
        priority: int = 0,
        grid_start: float = -165.0,
        grid_stop: float = 180.0,
        grid_increment: float = 15.0,
    ):
        """``POST /admin/molecules/{molid}/scans`` → :class:`ScanQueued`: queue a QM
        torsion scan (cluster spend, hence admin-only). ``dihedral_atoms`` is four
        distinct 1-indexed PDB serials."""
        body = {
            "dihedral_atoms": list(dihedral_atoms),
            "method": method,
            "mode": mode,
            "priority": priority,
            "grid_start": grid_start,
            "grid_stop": grid_stop,
            "grid_increment": grid_increment,
            **_drop_none(execution=execution, dihedral_label=dihedral_label),
        }
        response = yield from request(
            self._client, "POST", f"admin/molecules/{int(molid)}/scans", json=body
        )
        return ScanQueued.model_validate(response.json())

    @operation
    def cancel_scan(self, molid: int, scan_request_id: Id):
        """``DELETE /admin/molecules/{molid}/scans/{scan_request_id}`` →
        :class:`ScanCancelled`. Only a queued or running scan can be cancelled."""
        response = yield from request(
            self._client, "DELETE", f"admin/molecules/{int(molid)}/scans/{scan_request_id}"
        )
        return ScanCancelled.model_validate(response.json())

    @operation
    def stalled(self, *, scan: Optional[int] = None, cursor: Optional[str] = None):
        """``GET /admin/molecules/stalled`` → a page of :class:`StalledItem` (plan D9
        ``stalled``): molecules no QM driver will pick up. ``scan`` candidates are
        examined per page, so a page can hold fewer items than it examined --
        ``next_cursor`` continues the scan, ``page.scanned`` is how many it looked at."""
        return (
            yield from _ops.page_of(
                self._client,
                StalledItem,
                "admin/molecules/stalled",
                _drop_none(scan=scan, cursor=cursor),
                page_cls=StalledPage,
            )
        )


class Admin(Resource):
    """``client.admin`` — account, quota, audit and deletion-request operations."""

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.users = AdminUsers(client)
        self.molecules = AdminMolecules(client)

    @operation
    def quota_requests(
        self, *, status: str = "pending", limit: Optional[int] = None, cursor: Optional[str] = None
    ):
        """``GET /admin/quota-requests`` → ``Page[QuotaRequestItem]``. ``status`` is
        ``pending`` (default), ``approved`` or ``all``."""
        return (
            yield from _ops.page_of(
                self._client,
                QuotaRequestItem,
                "admin/quota-requests",
                {"status": status, "limit": limit, "cursor": cursor},
            )
        )

    @operation
    def approve_quota_request(
        self,
        request_id: Id,
        *,
        burst_per_min: Optional[int] = None,
        daily_limit: Optional[int] = None,
        note: Optional[str] = None,
    ):
        """``POST /admin/quota-requests/{id}:approve`` → :class:`QuotaApproved`.
        Omitted limits: apply what the request asked for. A key holding ``admin`` is
        root's to raise, not this call's."""
        body = _drop_none(burst_per_min=burst_per_min, daily_limit=daily_limit, note=note)
        response = yield from request(
            self._client, "POST", f"admin/quota-requests/{request_id}:approve", json=body or None
        )
        return QuotaApproved.model_validate(response.json())

    @operation
    def audit(self, **filters: Any):
        """``GET /admin/audit`` → ``Page[AuditRow]``: every admin, service and root
        write, and every denial. Filters: ``key_id``, ``principal`` (``user``,
        ``service``, ``root``, ``anonymous``), ``user_email``, ``target_type``,
        ``target_id``, ``outcome`` (``ok``, ``denied``, ``error``), ``since``,
        ``until``, ``limit``, ``cursor``."""
        return (yield from _ops.page_of(self._client, AuditRow, "admin/audit", filters))

    @operation
    def usage(self, *, day: Any = None, user_id: Optional[int] = None, limit: Optional[int] = None):
        """``GET /admin/usage`` → :class:`UsagePage`: weighted usage per key for one
        UTC day (default today), heaviest first. Services are counted, not limited."""
        params = _drop_none(day=day, user_id=user_id, limit=limit)
        response = yield from request(self._client, "GET", "admin/usage", params=params)
        return UsagePage.model_validate(response.json())

    @operation
    def deletion_requests(self):
        """``GET /admin/deletion-requests`` → :class:`DeletionRequestPage`: every
        molecule flagged for deletion, with what would block it. Acting on it is a
        root operation (``POST /root/deletion-requests:process``)."""
        response = yield from request(self._client, "GET", "admin/deletion-requests")
        return DeletionRequestPage.model_validate(response.json())
