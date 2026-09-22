"""``client.me`` — the caller's account, usage and keys."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Union

from .. import _ops
from .._base import Resource, operation
from .._transport import json_of, request
from ..models import Account, ApiKey, Molecule, Usage


class Keys(Resource):
    @operation
    def list(self):
        """``GET /me/keys`` → ``list[ApiKey]`` (secrets are never returned)."""
        response = yield from request(self._client, "GET", "me/keys")
        return [ApiKey.model_validate(k) for k in _ops.items_of(response.json())]

    @operation
    def create(
        self,
        *,
        name: Optional[str] = None,
        scopes: Optional[Iterable[str]] = None,
        expires: Optional[Union[str, int]] = None,
    ):
        """``POST /me/keys`` → :class:`ApiKey` whose ``.key`` is the secret, shown once.

        ``scopes`` must be a subset of the calling key's; ``expires`` is an RFC 3339
        time, a day count, or a duration such as ``"90d"``."""
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if scopes is not None:
            body["scopes"] = list(scopes)
        if expires is not None:
            body["expires"] = expires
        response = yield from request(self._client, "POST", "me/keys", json=body)
        return ApiKey.model_validate(response.json())

    @operation
    def revoke(self, key_id: Union[int, str]):
        """``DELETE /me/keys/{id}``."""
        response = yield from request(self._client, "DELETE", f"me/keys/{key_id}")
        return json_of(response)


class Me(Resource):
    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.keys = Keys(client)

    @operation
    def get(self):
        """``GET /me`` → :class:`Account`."""
        response = yield from request(self._client, "GET", "me")
        return Account.model_validate(response.json())

    @operation
    def usage(self):
        """``GET /me/usage`` → :class:`Usage`: today's counters and this key's limits."""
        response = yield from request(self._client, "GET", "me/usage")
        return Usage.model_validate(response.json())

    @operation
    def molecules(self, *, limit: Optional[int] = None):
        """``GET /me/molecules`` → ``Page[Molecule]``."""
        return (yield from _ops.page_of(self._client, Molecule, "me/molecules", {"limit": limit}))

    @operation
    def request_quota(self, *, reason: str, daily_limit: Optional[int] = None,
                      burst_per_min: Optional[int] = None):
        """``POST /me/quota-requests`` — ask an admin to raise this key's limits."""
        body = {"reason": reason, "daily_limit": daily_limit, "burst_per_min": burst_per_min}
        response = yield from request(
            self._client, "POST", "me/quota-requests",
            json={k: v for k, v in body.items() if v is not None},
        )
        return json_of(response)
