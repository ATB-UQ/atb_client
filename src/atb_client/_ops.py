"""Operations shared by several resources and models (written once; see ``_base``).

The D8 ``wait`` convention lives here: :func:`call_with_wait` issues a request with
``?wait=`` and, on ``202 Accepted``, polls ``GET /jobs/{id}`` (backing off 1 s → 30 s,
which costs no quota) until the job is ``done`` or ``failed`` or the caller's
``timeout`` runs out.
"""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type

import httpx

from . import _clock
from ._transport import Op, Sleep, json_of, request
from .exceptions import (
    JobFailed,
    MoleculeFailed,
    MoleculeNotFound,
    MoleculeRejected,
    NotFound,
    Timeout,
    error_from_problem,
)
from .models import Job, Molecule, MoleculeStatus, Page

#: The server caps ``?wait=`` at 120 s (D8); its default is 30 s.
SERVER_MAX_WAIT = 120
SERVER_DEFAULT_WAIT = 30
JOB_POLL_START = 1.0
JOB_POLL_MAX = 30.0
JOB_POLL_FACTOR = 2.0
MOLECULE_POLL_FACTOR = 1.5


def bind(model: Any, client: Any) -> Any:
    if hasattr(model, "_bind"):
        model._bind(client)
    return model


class Deadline:
    """``timeout`` seconds from now; ``None`` means no deadline."""

    def __init__(self, timeout: Optional[float]) -> None:
        self.timeout = timeout
        self.at = None if timeout is None else _clock.monotonic() + timeout

    def remaining(self) -> Optional[float]:
        if self.at is None:
            return None
        return self.at - _clock.monotonic()

    def expired(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0

    def clamp(self, delay: float) -> float:
        remaining = self.remaining()
        return delay if remaining is None else max(0.0, min(delay, remaining))


# --------------------------------------------------------------------------- molecules


def get_molecule(client: Any, molid: int) -> Op:
    response = yield from request(
        client, "GET", f"molecules/{int(molid)}", not_found=MoleculeNotFound
    )
    return bind(Molecule.model_validate(response.json()), client)


def get_status(client: Any, molid: int) -> Op:
    response = yield from request(
        client, "GET", f"molecules/{int(molid)}/status", not_found=MoleculeNotFound
    )
    return MoleculeStatus.model_validate(response.json())


def check_terminal(molid: int, status: MoleculeStatus) -> bool:
    """True on a successful terminal stage; raise on a negative one; False otherwise."""
    if status.stage == "failed":
        raise MoleculeFailed(molid, status)
    if status.stage == "rejected":
        raise MoleculeRejected(molid, status)
    return status.is_terminal


def wait_molecule(
    client: Any,
    molid: int,
    *,
    timeout: Optional[float],
    poll_interval: float = 15.0,
    max_interval: float = 300.0,
) -> Op:
    deadline = Deadline(timeout)
    interval = poll_interval
    while True:
        status = yield from get_status(client, molid)
        if check_terminal(molid, status):
            return (yield from get_molecule(client, molid))
        if deadline.expired():
            raise Timeout(
                f"molecule {molid} still at stage {status.stage!r} after {timeout} s",
                status=status,
            )
        yield Sleep(deadline.clamp(interval))
        interval = min(max_interval, interval * MOLECULE_POLL_FACTOR)


# --------------------------------------------------------------------------- jobs


def get_job(client: Any, job_id: str) -> Op:
    response = yield from request(client, "GET", f"jobs/{job_id}")
    return bind(Job.model_validate(response.json()), client)


def cancel_job(client: Any, job_id: str) -> Op:
    response = yield from request(client, "DELETE", f"jobs/{job_id}")
    body = json_of(response)
    return bind(Job.model_validate(body), client) if isinstance(body, dict) else None


def raise_for_job(client: Any, job: Job) -> None:
    """Raise if ``job`` failed: the mapped problem exception if its error is a problem
    body (e.g. a duplicate found by a slow submission), else :class:`JobFailed`."""
    if job.state != "failed":
        return
    if isinstance(job.error, dict):
        exc = error_from_problem(job.error, client=client)
        if exc is not None:
            raise exc
    raise JobFailed(job)


def wait_for_job(
    client: Any,
    job_id: Optional[str],
    *,
    timeout: Optional[float] = None,
    deadline: Optional[Deadline] = None,
) -> Op:
    """Poll ``GET /jobs/{id}`` until the job ends; return it (not raising on failure)."""
    if job_id is None:
        raise ValueError("job has no id")
    deadline = deadline or Deadline(timeout)
    interval = JOB_POLL_START
    while True:
        job = yield from get_job(client, job_id)
        if job.done:
            return job
        if deadline.expired():
            raise Timeout(f"job {job_id} still {job.state} at the deadline", job=job)
        yield Sleep(deadline.clamp(interval))
        interval = min(JOB_POLL_MAX, interval * JOB_POLL_FACTOR)


def job_from_accepted(client: Any, response: httpx.Response) -> Job:
    """The job a ``202 Accepted`` refers to: its body if it is a job, else ``Location``."""
    body: Any = None
    try:
        body = json_of(response)
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("id"):
        return bind(Job.model_validate(body), client)
    location = response.headers.get("Location", "")
    if "/jobs/" not in location:
        raise ValueError(f"202 Accepted without a job reference (Location: {location!r})")
    job_id = location.split("/jobs/", 1)[1].split("?", 1)[0].strip("/")
    return bind(Job(id=job_id, state="queued"), client)


def server_wait(deadline: Deadline, wait: Optional[float] = None) -> int:
    """The ``?wait=`` to ask for: the caller's remaining time, clamped to the server's cap."""
    if wait is not None:
        return int(max(0, min(SERVER_MAX_WAIT, wait)))
    remaining = deadline.remaining()
    if remaining is None:
        return SERVER_DEFAULT_WAIT
    return int(max(0, min(SERVER_MAX_WAIT, remaining)))


def call_with_wait(
    client: Any,
    method: str,
    path: str,
    *,
    deadline: Deadline,
    params: Optional[Dict[str, Any]] = None,
    json: Any = None,
    content: Any = None,
    headers: Optional[Dict[str, str]] = None,
    stream_to: Optional[Path] = None,
    default_name: Optional[str] = None,
    not_found: Type[NotFound] = NotFound,
    wait: Optional[float] = None,
    follow_job: bool = True,
) -> Op:
    """Issue a maybe-slow request (D8). Returns ``("response", httpx.Response)`` when the
    server answered within ``wait``, or ``("job", Job)`` — the finished job when
    ``follow_job``, the pending one otherwise. A failed job raises."""
    query = dict(params or {})
    query["wait"] = server_wait(deadline, wait)
    response = yield from request(
        client,
        method,
        path,
        params=query,
        json=json,
        content=content,
        headers=headers,
        stream_to=stream_to,
        default_name=default_name,
        not_found=not_found,
    )
    if response.status_code != 202:
        return ("response", response)
    job = job_from_accepted(client, response)
    if not follow_job:
        return ("job", job)
    if not job.done:
        job = yield from wait_for_job(client, job.id, deadline=deadline)
    raise_for_job(client, job)
    return ("job", job)


# --------------------------------------------------------------------------- files


def download(
    client: Any,
    path: str,
    *,
    target: Optional[Any],
    default_name: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    not_found: Type[NotFound] = NotFound,
) -> Op:
    """GET a file that may need generating first. With ``target`` (a file or a
    directory) stream it there and return the :class:`~pathlib.Path`; without, return
    the bytes."""
    deadline = Deadline(timeout)
    stream_to = Path(target) if target is not None else None
    for _ in range(3):
        kind, value = yield from call_with_wait(
            client,
            "GET",
            path,
            deadline=deadline,
            params=params,
            stream_to=stream_to,
            default_name=default_name,
            not_found=not_found,
        )
        if kind == "response":
            return _download_result(value, stream_to)
        # The job generated the file; it is cached now, so fetch it.
        if deadline.expired():
            raise Timeout(f"{path}: generated, but no time left to download it", job=value)
    raise Timeout(f"{path}: the server kept answering 202 after its job finished")


def fetch_file(
    client: Any,
    path: str,
    *,
    target: Optional[Any],
    default_name: str,
    params: Optional[Dict[str, Any]] = None,
    not_found: Type[NotFound] = NotFound,
) -> Op:
    """GET a file that is never generated on demand (reference data): no ``?wait=``,
    no job. With ``target`` stream it there and return the path; else the bytes."""
    stream_to = Path(target) if target is not None else None
    response = yield from request(
        client,
        "GET",
        path,
        params=params,
        stream_to=stream_to,
        default_name=default_name,
        not_found=not_found,
    )
    return _download_result(response, stream_to)


def model_call(
    client: Any,
    model: Type[Any],
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Any = None,
    not_found: Type[NotFound] = NotFound,
) -> Op:
    """A plain call whose JSON body is parsed into ``model``."""
    response = yield from request(
        client, method, path, params=params, json=json, not_found=not_found
    )
    return bind(model.model_validate(response.json()), client)


def _download_result(response: httpx.Response, stream_to: Optional[Path]) -> Any:
    if stream_to is None:
        return response.content
    written = response.extensions.get("atb_written")
    if written is None:  # a 2xx that was not 200 — write what came back
        target = stream_to / "download" if stream_to.is_dir() else stream_to
        target.write_bytes(response.content)
        return target
    return written


def page_of(
    client: Any,
    model: Type[Any],
    path: str,
    params: Dict[str, Any],
    *,
    method: str = "GET",
    page_cls: Optional[Type[Any]] = None,
    not_found: Type[NotFound] = NotFound,
) -> Op:
    """Fetch one page and wire its ``.all()`` to fetch the next. ``page_cls`` is a
    :class:`Page` subclass for lists that carry more than ``items``/``next_cursor``/
    ``total``; the default is ``Page[model]``."""
    response = yield from request(client, method, path, params=params, not_found=not_found)
    body = response.json()
    if isinstance(body, builtins.list):  # a bare list is one complete page
        body = {"items": body}
    cls = page_cls or Page[model]  # type: ignore[valid-type]
    page = cls.model_validate(body)
    for item in page.items:
        bind(item, client)
    bind(page, client)

    def fetch(cursor: str) -> Op:
        return page_of(
            client,
            model,
            path,
            {**params, "cursor": cursor},
            method=method,
            page_cls=page_cls,
            not_found=not_found,
        )

    page._fetch = fetch
    return page


def items_of(body: Any) -> Tuple[Any, ...]:
    if isinstance(body, dict) and "items" in body:
        return tuple(body["items"])
    if isinstance(body, builtins.list):
        return tuple(body)
    return (body,)


def json_call(
    client: Any,
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Any = None,
    content: Any = None,
    headers: Optional[Dict[str, str]] = None,
) -> Op:
    """A plain synchronous call whose JSON body (or ``None``) is the result."""
    if isinstance(json, dict):
        json = {k: v for k, v in json.items() if v is not None}
    response = yield from request(
        client, method, path, params=params, json=json, content=content, headers=headers
    )
    try:
        return json_of(response)
    except ValueError:
        return response.text
