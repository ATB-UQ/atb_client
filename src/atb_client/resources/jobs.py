"""``client.jobs`` — the D8 jobs behind anything slow. Polls cost no quota."""

from __future__ import annotations

from typing import Any, Optional

from .. import _ops
from .._base import Resource, operation
from .._transport import request
from ..models import Job


class Jobs(Resource):
    @operation
    def get(self, job_id: str):
        """``GET /jobs/{id}`` → :class:`Job`."""
        return (yield from _ops.get_job(self._client, job_id))

    @operation
    def result(self, job_id: str, *, path: Any = None):
        """``GET /jobs/{id}/result`` → a finished job's answer: the zip of a bundle or
        remap job (streamed to ``path`` if given, else returned as bytes), or for
        every other kind the parsed JSON body the originating request would have
        returned. Free: what it charges was already charged when the job was
        requested. ``409 job-not-finished`` while it is still running, ``410
        job-result-expired`` once the file has aged out of ``retention_hours``."""
        stream_to = _ops.Path(path) if path is not None else None
        response = yield from request(
            self._client,
            "GET",
            f"jobs/{job_id}/result",
            stream_to=stream_to,
            default_name=f"{job_id}.zip",
        )
        if response.headers.get("Content-Type", "").startswith("application/zip"):
            return _ops._download_result(response, stream_to)
        return response.json()

    @operation
    def list(
        self,
        *,
        state: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ):
        """``GET /jobs`` → ``Page[Job]``: the caller's jobs, newest first. ``cursor``
        is the ``next_cursor`` of a previous page. Free to poll."""
        return (
            yield from _ops.page_of(
                self._client, Job, "jobs", {"state": state, "limit": limit, "cursor": cursor}
            )
        )

    @operation
    def cancel(self, job_id: str):
        """``DELETE /jobs/{id}`` → the cancelled :class:`Job` (or ``None`` on 204)."""
        return (yield from _ops.cancel_job(self._client, job_id))

    @operation
    def wait(self, job_id: str, timeout: Optional[float] = None):
        """Block until the job ends and return its ``result`` (see :meth:`Job.result`)."""
        job = yield from _ops.wait_for_job(self._client, job_id, timeout=timeout)
        _ops.raise_for_job(self._client, job)
        return job.result_
