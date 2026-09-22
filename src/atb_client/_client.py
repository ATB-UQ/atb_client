"""``ATBClient`` and ``AsyncATBClient``: one definition, two drivers."""

from __future__ import annotations

import platform
from typing import Any, Optional, Union

import httpx

from ._base import operation
from ._config import resolve
from ._transport import AsyncDriver, RetryPolicy, SyncDriver
from ._version import __version__
from .resources.admin import Admin
from .resources.bundles import Bundles
from .resources.files import Files
from .resources.forcefields import Forcefields
from .resources.jobs import Jobs
from .resources.me import Me
from .resources.molecules import Molecules
from .resources.pipeline import Pipeline
from .resources.reference import Dihedrals, Parameters, SiteStatistics, TautomerGroups
from .resources.structures import Structures

TimeoutTypes = Union[None, float, int, httpx.Timeout]

#: (connect, read, write, pool). A read of 30 s matches the server's synchronous
#: ceiling; anything slower is a job and is waited for by polling, not by a held read.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)

USER_AGENT = f"atb-client/{__version__} python/{platform.python_version()}"


def _timeout(value: TimeoutTypes, profile_value: Optional[float]) -> httpx.Timeout:
    if isinstance(value, httpx.Timeout):
        return value
    if value is None:
        value = profile_value
    if value is None:
        return DEFAULT_TIMEOUT
    seconds = float(value)
    return httpx.Timeout(seconds, connect=min(10.0, seconds), pool=min(10.0, seconds))


class _ClientBase:
    is_async = False

    def _setup(
        self,
        api_key: Optional[str],
        base_url: Optional[str],
        timeout: TimeoutTypes,
        profile: Optional[str],
        max_attempts: int,
        max_retry_after: float,
        headers: Optional[dict],
    ) -> dict:
        config = resolve(api_key=api_key, base_url=base_url, profile=profile)
        self.base_url = config.base_url
        self.profile = config.profile
        self._key_source = config.source
        self._has_key = config.api_key is not None
        self._retry = RetryPolicy(
            max_attempts=max(1, int(max_attempts)), max_retry_after=max_retry_after
        )
        all_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if config.api_key:
            all_headers["Authorization"] = f"Bearer {config.api_key}"
        all_headers.update(headers or {})
        return {
            "base_url": config.base_url + "/",
            "headers": all_headers,
            "timeout": _timeout(timeout, config.timeout),
            "follow_redirects": False,
        }

    def _attach_resources(self) -> None:
        self.molecules = Molecules(self)
        self.files = Files(self)
        self.bundles = Bundles(self)
        self.structures = Structures(self)
        self.forcefields = Forcefields(self)
        self.jobs = Jobs(self)
        self.me = Me(self)
        self.parameters = Parameters(self)
        self.dihedrals = Dihedrals(self)
        self.tautomers = TautomerGroups(self)
        self.statistics = SiteStatistics(self)
        self.admin = Admin(self)
        self.pipeline = Pipeline(self)

    @operation
    def health(self):
        """``GET /health`` → :class:`~atb_client.models.Health`. Needs no key; a
        ``503`` (the service is degraded) still returns the body rather than raising."""
        from ._transport import request
        from .exceptions import ServiceUnavailable
        from .models import Health

        try:
            response = yield from request(self, "GET", "health")
        except ServiceUnavailable as exc:
            if exc.response is None:
                raise
            response = exc.response
        return Health.model_validate(response.json())

    @property
    def _client(self) -> Any:  # so client-level helpers can use @operation too
        return self

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.base_url} profile={self.profile!r}>"


class ATBClient(_ClientBase):
    """Synchronous client for the ATB API v1.

    ``api_key`` and ``base_url`` default to ``ATB_API_KEY``/``ATB_API_URL`` and then to
    the ``profile`` in ``~/.config/atb/config.toml``. ``timeout`` is seconds (read and
    write; connect is capped at 10 s) or an ``httpx.Timeout``. Transient failures (429,
    502/503/504, connection errors) are retried up to ``max_attempts`` times in all.
    """

    is_async = False

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: TimeoutTypes = None,
        *,
        profile: Optional[str] = None,
        max_attempts: int = 5,
        max_retry_after: float = 60.0,
        headers: Optional[dict] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        options = self._setup(
            api_key, base_url, timeout, profile, max_attempts, max_retry_after, headers
        )
        if http_client is not None:
            http_client.headers.update(options["headers"])
        self._http = http_client or httpx.Client(**options)
        self._driver = SyncDriver(self._http)
        self._attach_resources()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ATBClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class AsyncATBClient(_ClientBase):
    """The same surface as :class:`ATBClient`, with every call a coroutine.

    Iterators (``page.all()``, ``molecules.wait_all()``) are async iterators, and
    ``DuplicateMolecule.molecule`` is awaitable.
    """

    is_async = True

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: TimeoutTypes = None,
        *,
        profile: Optional[str] = None,
        max_attempts: int = 5,
        max_retry_after: float = 60.0,
        headers: Optional[dict] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        options = self._setup(
            api_key, base_url, timeout, profile, max_attempts, max_retry_after, headers
        )
        if http_client is not None:
            http_client.headers.update(options["headers"])
        self._http = http_client or httpx.AsyncClient(**options)
        self._driver = AsyncDriver(self._http)
        self._attach_resources()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncATBClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()
