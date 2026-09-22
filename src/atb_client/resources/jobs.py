"""``client.jobs`` — the D8 jobs behind anything slow. Polls cost no quota."""

from __future__ import annotations

from typing import Optional

from .. import _ops
from .._base import Resource, operation
from ..models import Job


class Jobs(Resource):
    @operation
    def get(self, job_id: str):
        """``GET /jobs/{id}`` → :class:`Job`."""
        return (yield from _ops.get_job(self._client, job_id))

    @operation
    def list(self, *, state: Optional[str] = None, limit: Optional[int] = None):
        """``GET /jobs?state=`` → ``Page[Job]``."""
        return (yield from _ops.page_of(self._client, Job, "jobs", {"state": state, "limit": limit}))

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
