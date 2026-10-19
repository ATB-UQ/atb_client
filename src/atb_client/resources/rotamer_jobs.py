"""``client.rotamer_jobs`` -- the rotamer job monitor (``/rotamer-jobs``). Open to every
``read`` key, limited by the visibility of each job's molecule. Creating and cancelling a
job is ``client.admin.rotamer_jobs``."""

from __future__ import annotations

from typing import Optional

from .. import _ops
from .._base import Resource, operation
from .._transport import Sleep, request
from ..exceptions import RotamerJobFailed, RotamerJobNotFound, Timeout
from ..models import ROTAMER_FAILED_STATES, RotamerJob, RotamerJobPage

#: ``wait(until=...)``: the states a caller can wait for.
WAIT_UNTIL = ("submitted", "complete")


class RotamerJobs(Resource):
    """``client.rotamer_jobs`` -- list, get and wait for rotamer jobs."""

    @operation
    def list(
        self,
        *,
        molid: Optional[int] = None,
        compound_id: Optional[int] = None,
        state: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        """``GET /rotamer-jobs`` -> :class:`RotamerJobPage` of ``RotamerJobSummary``,
        newest first. ``molid`` matches jobs that searched that molecule or its
        compound. ``page.total > 0`` with ``molid=`` or ``compound_id=`` means it has had
        a rotamer job. ``page.all()`` walks every page."""
        return (
            yield from _ops.offset_page_of(
                self._client,
                RotamerJobPage,
                "rotamer-jobs",
                {
                    "molid": molid,
                    "compound_id": compound_id,
                    "state": state,
                    "limit": limit,
                    "offset": offset,
                },
            )
        )

    @operation
    def get(self, job_id: int):
        """``GET /rotamer-jobs/{id}`` -> :class:`RotamerJob`. 404 ->
        :class:`RotamerJobNotFound` (also for a job whose molecule this key cannot see)."""
        return (yield from _get(self._client, job_id))

    @operation
    def wait(
        self,
        job_id: int,
        until: str = "submitted",
        timeout: Optional[float] = None,
        interval: float = 15.0,
    ):
        """Poll ``GET /rotamer-jobs/{id}`` every ``interval`` seconds until the job has
        reached ``until`` -- ``"submitted"`` (every selected minimum is in the ATB, QM
        pending) or ``"complete"`` (the covered molecules have settled) -- or any later
        state, and return it. Raises :class:`RotamerJobFailed` (``.job``) if it is
        ``failed`` or ``cancelled`` and :class:`Timeout` (``.rotamer_job``) when
        ``timeout`` seconds pass first. Each poll costs one request of quota."""
        if until not in WAIT_UNTIL:
            raise ValueError(f"until must be one of {WAIT_UNTIL}, not {until!r}")
        deadline = _ops.Deadline(timeout)
        while True:
            job = yield from _get(self._client, job_id)
            if job.state in ROTAMER_FAILED_STATES:
                raise RotamerJobFailed(job)
            if job.reached(until):
                return job
            if deadline.expired():
                raise Timeout(
                    f"rotamer job {job_id} still {job.state} after {timeout} s",
                    rotamer_job=job,
                )
            yield Sleep(deadline.clamp(interval))


def _get(client, job_id: int):
    """Fetch one rotamer job, bound to `client`."""
    response = yield from request(
        client, "GET", f"rotamer-jobs/{int(job_id)}", not_found=RotamerJobNotFound
    )
    return _ops.bind(RotamerJob.model_validate(response.json()), client)
