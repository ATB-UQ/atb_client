"""The sync/async seam.

Every API operation in this package is written **once**, as a generator that yields
effects (:class:`~atb_client._transport.Send`, :class:`~atb_client._transport.Sleep`,
:class:`~atb_client._transport.Emit`) and receives their results. The two decorators
here turn such a generator function into a public method whose behaviour depends on
the client it is bound to:

- on an :class:`~atb_client.ATBClient`, calling it runs the generator to completion
  and returns the value;
- on an :class:`~atb_client.AsyncATBClient`, calling it returns a coroutine that does
  the same with ``await``.

``stream_operation`` is the iterator counterpart: a plain iterator on the sync client,
an async iterator on the async one. So there is exactly one implementation of retry,
backoff, error mapping, the 202/job dance, ``wait()`` and pagination, and
``AsyncATBClient`` cannot drift from ``ATBClient``.
"""

from __future__ import annotations

import functools
from typing import Any, Callable


def _driver_of(obj: Any) -> Any:
    """Return the driver of the client `obj` is bound to."""
    client = getattr(obj, "_client", None)
    if client is None:
        raise RuntimeError(
            f"{type(obj).__name__} is not bound to a client; fetch it through an "
            "ATBClient or AsyncATBClient"
        )
    return client._driver


def operation(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run the generator ``fn`` on the bound client's driver (sync value or coroutine)."""

    @functools.wraps(fn)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        """Run the bound generator on its client's driver."""
        return _driver_of(self).run(fn(self, *args, **kwargs))

    wrapper.__atb_operation__ = fn  # type: ignore[attr-defined]
    return wrapper


def stream_operation(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run the generator ``fn`` as an iterator (sync) or async iterator (async)."""

    @functools.wraps(fn)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        """Iterate the bound generator on its client's driver."""
        return _driver_of(self).iterate(fn(self, *args, **kwargs))

    wrapper.__atb_operation__ = fn  # type: ignore[attr-defined]
    return wrapper


class Resource:
    """Base of every resource namespace (``client.molecules``, ``client.me``, ...)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def __repr__(self) -> str:
        return f"<{type(self).__name__} of {self._client!r}>"
