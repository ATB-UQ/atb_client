"""HTTP transport: effects, the two drivers, and the one ``request()`` operation.

``request()`` owns retry, backoff and error mapping. It is a generator that yields
:class:`Send` and :class:`Sleep` effects; :class:`SyncDriver` performs them with an
``httpx.Client`` and ``time.sleep``, :class:`AsyncDriver` with an ``httpx.AsyncClient``
and ``asyncio.sleep``. Only the drivers know which one they are.

Retry policy (plan §8): retried with exponential backoff and jitter on 429, 502, 503,
504 and on ``httpx.TransportError`` (connection refused/reset, timeouts), at most
``max_attempts`` attempts in all; never on any other 4xx. A ``Retry-After`` header is
honoured as the delay; one longer than ``max_retry_after`` (default 60 s — e.g. a daily
limit that resets at midnight UTC) is not slept on, and the exception is raised at
once so the caller can decide.
"""

from __future__ import annotations

import os
import random
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, Optional, Type, Union

import httpx

from . import _clock
from .exceptions import NetworkError, NotFound, error_from_response, retry_after_seconds

PathLike = Union[str, "os.PathLike[str]"]

RETRY_STATUSES = frozenset({429, 502, 503, 504})


# --------------------------------------------------------------------------- effects


@dataclass
class Send:
    """Send ``request``. With ``stream_to`` set, a 200 body is streamed to that path
    (or into that directory, named from ``Content-Disposition`` or ``default_name``)
    and ``written`` is set to the final path; any other body is read into memory."""

    request: httpx.Request
    stream_to: Optional[Path] = None
    default_name: Optional[str] = None
    written: Optional[Path] = field(default=None, init=False)


@dataclass
class Sleep:
    seconds: float


@dataclass
class Emit:
    """Yield ``value`` to the consumer of a stream operation."""

    value: Any


Op = Generator[Any, Any, Any]


# --------------------------------------------------------------------------- policy


@dataclass
class RetryPolicy:
    max_attempts: int = 5
    backoff_base: float = 0.5
    backoff_max: float = 30.0
    max_retry_after: float = 60.0

    def backoff(self, attempt: int) -> float:
        """Delay before retry number ``attempt`` (1-based): exponential, equal jitter."""
        ceiling = min(self.backoff_max, self.backoff_base * (2 ** (attempt - 1)))
        return ceiling / 2 + random.uniform(0, ceiling / 2)


# --------------------------------------------------------------------------- request op


def _clean_params(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not params:
        return None
    out: Dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        elif isinstance(value, (list, tuple, set, frozenset)):
            value = ",".join(str(v) for v in value)
        out[key] = value
    return out or None


def request(
    client: Any,
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Any = None,
    content: Optional[Union[bytes, str]] = None,
    headers: Optional[Dict[str, str]] = None,
    stream_to: Optional[Path] = None,
    default_name: Optional[str] = None,
    not_found: Type[NotFound] = NotFound,
) -> Op:
    """Send one API request with retries; return the ``httpx.Response`` (status < 400).

    Error responses raise the mapped :mod:`atb_client.exceptions` class. When the
    request streamed to a file, ``response.extensions['atb_written']`` is the path.
    """
    policy: RetryPolicy = client._retry
    cleaned = _clean_params(params)
    attempt = 0
    while True:
        attempt += 1
        req = client._http.build_request(
            method, f"{client.base_url}/{path.lstrip('/')}", params=cleaned, json=json, content=content, headers=headers
        )
        effect = Send(req, stream_to=stream_to, default_name=default_name)
        try:
            response = yield effect
        except httpx.TransportError as exc:
            if attempt >= policy.max_attempts:
                raise NetworkError(
                    f"{method} {req.url} failed after {attempt} attempts: {exc!r}"
                ) from exc
            yield Sleep(policy.backoff(attempt))
            continue

        status = response.status_code
        if status in RETRY_STATUSES and attempt < policy.max_attempts:
            delay = retry_after_seconds(response)
            if delay is None:
                delay = policy.backoff(attempt)
            if delay <= policy.max_retry_after:
                yield Sleep(delay)
                continue
        if status >= 400:
            raise error_from_response(response, not_found=not_found, client=client)
        if effect.written is not None:
            response.extensions["atb_written"] = effect.written
        return response


def json_of(response: httpx.Response) -> Any:
    if not response.content:
        return None
    return response.json()


# --------------------------------------------------------------------------- file writing

_CD_FILENAME = re.compile(r"""filename\*?=(?:UTF-8'')?"?([^";]+)"?""", re.IGNORECASE)


def _target_path(effect: Send, response: httpx.Response) -> Path:
    target = Path(effect.stream_to)  # type: ignore[arg-type]
    if target.is_dir():
        name = None
        match = _CD_FILENAME.search(response.headers.get("Content-Disposition", ""))
        if match:
            name = os.path.basename(match.group(1).strip())
        target = target / (name or effect.default_name or "download")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _open_partial(target: Path) -> Any:
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=str(target.parent))
    return os.fdopen(fd, "wb"), tmp


def _finish_partial(tmp: str, target: Path, ok: bool) -> None:
    if ok:
        os.replace(tmp, target)
    else:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# --------------------------------------------------------------------------- drivers


class SyncDriver:
    is_async = False

    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def _send(self, effect: Send) -> httpx.Response:
        if effect.stream_to is None:
            return self.http.send(effect.request)
        response = self.http.send(effect.request, stream=True)
        try:
            if response.status_code == 200:
                target = _target_path(effect, response)
                fh, tmp = _open_partial(target)
                ok = False
                try:
                    with fh:
                        for chunk in response.iter_bytes():
                            fh.write(chunk)
                    ok = True
                finally:
                    _finish_partial(tmp, target, ok)
                effect.written = target
            else:
                response.read()
        finally:
            response.close()
        return response

    def _perform(self, effect: Any) -> Any:
        if isinstance(effect, Send):
            return self._send(effect)
        if isinstance(effect, Sleep):
            _clock.sleep(effect.seconds)
            return None
        raise TypeError(f"unexpected effect {effect!r}")

    def run(self, gen: Op) -> Any:
        value: Any = None
        error: Optional[BaseException] = None
        while True:
            try:
                effect = gen.throw(error) if error is not None else gen.send(value)
            except StopIteration as stop:
                return stop.value
            value, error = None, None
            if isinstance(effect, Emit):
                raise TypeError("Emit from a non-stream operation")
            try:
                value = self._perform(effect)
            except httpx.TransportError as exc:
                error = exc

    def iterate(self, gen: Op) -> Iterable[Any]:
        value: Any = None
        error: Optional[BaseException] = None
        while True:
            try:
                effect = gen.throw(error) if error is not None else gen.send(value)
            except StopIteration:
                return
            value, error = None, None
            if isinstance(effect, Emit):
                yield effect.value
                continue
            try:
                value = self._perform(effect)
            except httpx.TransportError as exc:
                error = exc


class AsyncDriver:
    is_async = True

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def _send(self, effect: Send) -> httpx.Response:
        if effect.stream_to is None:
            return await self.http.send(effect.request)
        response = await self.http.send(effect.request, stream=True)
        try:
            if response.status_code == 200:
                target = _target_path(effect, response)
                fh, tmp = _open_partial(target)
                ok = False
                try:
                    with fh:
                        async for chunk in response.aiter_bytes():
                            fh.write(chunk)
                    ok = True
                finally:
                    _finish_partial(tmp, target, ok)
                effect.written = target
            else:
                await response.aread()
        finally:
            await response.aclose()
        return response

    async def _perform(self, effect: Any) -> Any:
        if isinstance(effect, Send):
            return await self._send(effect)
        if isinstance(effect, Sleep):
            await _clock.async_sleep(effect.seconds)
            return None
        raise TypeError(f"unexpected effect {effect!r}")

    async def run(self, gen: Op) -> Any:
        value: Any = None
        error: Optional[BaseException] = None
        while True:
            try:
                effect = gen.throw(error) if error is not None else gen.send(value)
            except StopIteration as stop:
                return stop.value
            value, error = None, None
            if isinstance(effect, Emit):
                raise TypeError("Emit from a non-stream operation")
            try:
                value = await self._perform(effect)
            except httpx.TransportError as exc:
                error = exc

    async def iterate(self, gen: Op) -> Any:
        value: Any = None
        error: Optional[BaseException] = None
        while True:
            try:
                effect = gen.throw(error) if error is not None else gen.send(value)
            except StopIteration:
                return
            value, error = None, None
            if isinstance(effect, Emit):
                yield effect.value
                continue
            try:
                value = await self._perform(effect)
            except httpx.TransportError as exc:
                error = exc
