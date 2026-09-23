"""``client.me`` — the caller's identity, usage, keys and molecules."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Union

from .. import _ops
from .._base import Resource, operation
from .._transport import request
from ..models import ApiKey, Molecule, QuotaRequestReceived, Usage
from ..models import Me as MeModel

_DAYS = re.compile(r"^\s*(\d+)\s*d?\s*$", re.IGNORECASE)


def days_of(value: Union[int, str, None]) -> Optional[int]:
    """``90``, ``"90"`` or ``"90d"`` → ``90``; ``None`` stays ``None``."""
    if value is None or isinstance(value, int):
        return value
    match = _DAYS.match(str(value))
    if not match:
        raise ValueError(f"expiry must be a number of days such as 90 or '90d', not {value!r}")
    return int(match.group(1))


class Keys(Resource):
    """``/me/keys``; needs a user key with the ``manage`` scope."""

    @operation
    def list(self):
        """``GET /me/keys`` → ``list[ApiKey]`` (secrets are never returned)."""
        response = yield from request(self._client, "GET", "me/keys")
        return [ApiKey.model_validate(k) for k in _ops.items_of(response.json())]

    @operation
    def create(
        self,
        name: str,
        *,
        scopes: Optional[Iterable[str]] = None,
        expires_in_days: Optional[Union[int, str]] = None,
    ):
        """``POST /me/keys`` → :class:`ApiKey` whose ``.key`` is the secret, shown once.

        ``scopes`` must be a subset of the calling key's (default: all of them);
        ``expires_in_days`` (1-3650; ``"90d"`` is accepted) defaults to the calling
        key's own expiry and can never be later than it."""
        body: Dict[str, Any] = {"name": name}
        if scopes is not None:
            body["scopes"] = list(scopes)
        days = days_of(expires_in_days)
        if days is not None:
            body["expires_in_days"] = days
        response = yield from request(self._client, "POST", "me/keys", json=body)
        return ApiKey.model_validate(response.json())

    @operation
    def revoke(self, key_id: int):
        """``DELETE /me/keys/{id}`` → ``None`` (the server answers ``204``)."""
        yield from request(self._client, "DELETE", f"me/keys/{int(key_id)}")
        return None


class Me(Resource):
    """``client.me`` — the caller's identity, usage, keys and molecules."""

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.keys = Keys(client)

    @operation
    def get(self):
        """``GET /me`` → :class:`~atb_client.models.Me`: principal, scopes, limits and,
        for a user key, the ``account``."""
        response = yield from request(self._client, "GET", "me")
        return MeModel.model_validate(response.json())

    @operation
    def usage(self):
        """``GET /me/usage`` → :class:`Usage`: today's (UTC) weighted requests and this
        key's limits. Costs no quota."""
        response = yield from request(self._client, "GET", "me/usage")
        return Usage.model_validate(response.json())

    @operation
    def molecules(
        self,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        fields: Optional[List[str]] = None,
        **filters: Any,
    ):
        """Your molecules: ``GET /molecules?owner=me`` → ``Page[Molecule]``. Takes the
        filters of :meth:`Molecules.search`. (The plan's ``GET /me/molecules``
        shorthand is not served; this is the route it would alias.)"""
        params: Dict[str, Any] = dict(
            filters, owner="me", limit=limit, cursor=cursor, fields=fields
        )
        return (yield from _ops.page_of(self._client, Molecule, "molecules", params))

    @operation
    def request_quota(
        self,
        *,
        reason: str,
        daily_limit: Optional[int] = None,
        burst_per_min: Optional[int] = None,
        key_id: Optional[int] = None,
    ):
        """``POST /me/quota-requests`` → :class:`QuotaRequestReceived`: ask an admin to
        raise a key's limits (``key_id``: default the calling key). Give
        ``daily_limit``, ``burst_per_min`` or both."""
        if daily_limit is None and burst_per_min is None:
            raise ValueError("ask for a daily_limit, a burst_per_min, or both")
        body = {
            "reason": reason,
            "daily_limit": daily_limit,
            "burst_per_min": burst_per_min,
            "key_id": key_id,
        }
        response = yield from request(
            self._client,
            "POST",
            "me/quota-requests",
            json={k: v for k, v in body.items() if v is not None},
        )
        return QuotaRequestReceived.model_validate(response.json())
