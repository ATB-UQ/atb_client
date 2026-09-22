"""``client.admin`` — ``/admin/*``. Needs a key carrying the ``admin`` scope; every
call is audited server-side. Thin typed calls; the server enforces what a key may do."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Union

from .. import _ops
from .._base import Resource, operation

Id = Union[int, str]


def _drop_none(**kwargs: Any) -> Dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}


class AdminUsers(Resource):
    @operation
    def list(self, q: Optional[str] = None, *, limit: Optional[int] = None,
             cursor: Optional[str] = None):
        """``GET /admin/users?q=`` → ``Page`` of user dicts."""
        return (yield from _ops.page_of(self._client, dict, "admin/users",
                                        {"q": q, "limit": limit, "cursor": cursor}))

    @operation
    def get(self, user_id: Id):
        """``GET /admin/users/{id}``."""
        return (yield from _ops.json_call(self._client, "GET", f"admin/users/{user_id}"))

    @operation
    def update(self, user_id: Id, **fields: Any):
        """``PATCH /admin/users/{id}`` — ``class``, ``group_id``, ``expiry``, limits."""
        return (yield from _ops.json_call(self._client, "PATCH", f"admin/users/{user_id}",
                                          json=fields))

    @operation
    def create_key(self, user_id: Id, *, name: Optional[str] = None,
                   scopes: Optional[Iterable[str]] = None, expires: Any = None):
        """``POST /admin/users/{id}/keys`` (cannot grant ``admin``)."""
        body = _drop_none(name=name, scopes=list(scopes) if scopes else None, expires=expires)
        return (yield from _ops.json_call(self._client, "POST", f"admin/users/{user_id}/keys",
                                          json=body))

    @operation
    def update_key(self, user_id: Id, key_id: Id, **limits: Any):
        """``PATCH /admin/users/{id}/keys/{kid}`` — ``burst_per_min``, ``daily_limit``, ..."""
        return (yield from _ops.json_call(self._client, "PATCH",
                                          f"admin/users/{user_id}/keys/{key_id}", json=limits))

    @operation
    def revoke_key(self, user_id: Id, key_id: Id):
        """``DELETE /admin/users/{id}/keys/{kid}``."""
        return (yield from _ops.json_call(self._client, "DELETE",
                                          f"admin/users/{user_id}/keys/{key_id}"))


class AdminMolecules(Resource):
    @operation
    def update(self, molid: int, **fields: Any):
        """``PATCH /admin/molecules/{molid}`` — ``max_qm_level``, ``curation_trust``,
        ``datasets`` add/remove, ``tags``."""
        return (yield from _ops.json_call(self._client, "PATCH", f"admin/molecules/{int(molid)}",
                                          json=fields))

    @operation
    def cache_clear(self, molid: int, *, all: bool = False):
        """``POST /admin/molecules/{molid}/cache:clear`` — current version only unless ``all``."""
        return (yield from _ops.json_call(self._client, "POST",
                                          f"admin/molecules/{int(molid)}/cache:clear",
                                          json={"all": all}))

    @operation
    def invalidate(self, molid: int):
        """``POST /admin/molecules/{molid}:invalidate``."""
        return (yield from _ops.json_call(self._client, "POST",
                                          f"admin/molecules/{int(molid)}:invalidate", json={}))

    @operation
    def regenerate(self, molid: int, *, wait: bool = False, timeout: Optional[float] = None):
        """``POST /molecules/{molid}/topologies`` — regenerate now; returns the :class:`Job`,
        or with ``wait=True`` its result."""
        kind, value = yield from _ops.call_with_wait(
            self._client, "POST", f"molecules/{int(molid)}/topologies",
            deadline=_ops.Deadline(timeout), json={}, wait=None if wait else 0, follow_job=wait,
        )
        if kind == "job":
            return value.result_ if wait else value
        return value.json()

    @operation
    def request_scan(self, molid: int, **params: Any):
        """``POST /admin/molecules/{molid}/scans`` — request a dihedral scan."""
        return (yield from _ops.json_call(self._client, "POST",
                                          f"admin/molecules/{int(molid)}/scans", json=params))

    @operation
    def cancel_scan(self, molid: int, run: Id):
        """``DELETE /admin/molecules/{molid}/scans/{run}``."""
        return (yield from _ops.json_call(self._client, "DELETE",
                                          f"admin/molecules/{int(molid)}/scans/{run}"))


class Admin(Resource):
    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.users = AdminUsers(client)
        self.molecules = AdminMolecules(client)

    @operation
    def quota_requests(self, *, limit: Optional[int] = None):
        """``GET /admin/quota-requests``."""
        return (yield from _ops.page_of(self._client, dict, "admin/quota-requests",
                                        {"limit": limit}))

    @operation
    def approve_quota_request(self, request_id: Id):
        """``POST /admin/quota-requests/{id}:approve``."""
        return (yield from _ops.json_call(self._client, "POST",
                                          f"admin/quota-requests/{request_id}:approve", json={}))

    @operation
    def audit(self, **filters: Any):
        """``GET /admin/audit?…`` → ``Page`` of audit rows."""
        return (yield from _ops.page_of(self._client, dict, "admin/audit", filters))

    @operation
    def usage(self, **filters: Any):
        """``GET /admin/usage?…`` → ``Page`` of usage rows."""
        return (yield from _ops.page_of(self._client, dict, "admin/usage", filters))

    @operation
    def deletion_requests(self, *, limit: Optional[int] = None):
        """``GET /admin/deletion-requests`` — acting on them is a root operation."""
        return (yield from _ops.page_of(self._client, dict, "admin/deletion-requests",
                                        {"limit": limit}))
