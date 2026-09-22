"""Response models.

Hand-written for now, with field names taken from the v1 plan (§6, D9). Once the
server publishes ``/api/v1/openapi.json`` these are replaced by models generated with
``scripts/generate_models.sh`` into :mod:`atb_client.generated`, and this module keeps
only the behaviour (``wait()``, ``files``, pagination) layered over them.

Every model allows extra fields, so a field the server adds before the client is
regenerated is kept (``model.model_extra``) rather than dropped.
"""

from __future__ import annotations

from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generic,
    Iterator,
    List,
    Optional,
    TypeVar,
    Union,
)

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from ._base import operation, stream_operation

if TYPE_CHECKING:  # pragma: no cover
    from .resources.files import MoleculeFiles

__all__ = [
    "TERMINAL_STAGES",
    "Account",
    "ApiKey",
    "BatchItem",
    "BatchResult",
    "Change",
    "FileInfo",
    "Job",
    "Molecule",
    "MoleculeStatus",
    "Page",
    "Problem",
    "StructureMatch",
    "Usage",
]

#: D9's stages. ``terminal`` is true for the last four.
STAGES = ("queued", "qm0", "qm1", "qm2", "finished", "capped", "failed", "rejected")
TERMINAL_STAGES = ("finished", "capped", "failed", "rejected")
SUCCESS_STAGES = ("finished", "capped")
JOB_STATES = ("queued", "running", "done", "failed")


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class _Bound(_Model):
    """A model that can make further calls through the client that fetched it."""

    _client: Any = PrivateAttr(default=None)

    def _bind(self, client: Any) -> _Bound:
        self._client = client
        return self


class Problem(_Model):
    """An RFC 9457 problem body. Extra members (``molid``, ``errors``, ...) are kept."""

    type: Optional[str] = None
    title: Optional[str] = None
    status: Optional[int] = None
    detail: Optional[Any] = None  # a string; FastAPI's default 422 puts a list here
    instance: Optional[str] = None


class MoleculeStatus(_Model):
    """D9's status resource. Reading it costs no quota."""

    stage: str
    terminal: bool = False
    detail: Optional[str] = None
    since: Optional[datetime] = None
    eta_class: Optional[str] = None  # minutes | hours | days
    error: Optional[str] = None
    client_reference: Optional[str] = None
    molid: Optional[int] = None

    @property
    def succeeded(self) -> bool:
        return self.stage in SUCCESS_STAGES

    @property
    def is_terminal(self) -> bool:
        return self.terminal or self.stage in TERMINAL_STAGES


class Molecule(_Bound):
    """A molecule resource (``GET /molecules/{molid}``)."""

    molid: int
    inchi: Optional[str] = None
    inchi_key: Optional[str] = None
    smiles: Optional[str] = None
    formula: Optional[str] = None
    common_name: Optional[str] = None
    iupac: Optional[str] = None
    atoms: Optional[int] = None
    netcharge: Optional[int] = None
    owner: Optional[Any] = None
    public: Optional[bool] = None
    qm_level: Optional[int] = None
    max_qm_level: Optional[int] = None
    status: Optional[MoleculeStatus] = None
    client_reference: Optional[str] = None
    topology_hash: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    links: Optional[Dict[str, Any]] = None

    @property
    def files(self) -> MoleculeFiles:
        """This molecule's files: ``mol.files.list()``, ``mol.files.download(name, path)``."""
        from .resources.files import MoleculeFiles

        return MoleculeFiles(self._client, self.molid)

    @operation
    def refresh(self):
        """Fetch this molecule again; returns a new :class:`Molecule`."""
        from . import _ops

        return (yield from _ops.get_molecule(self._client, self.molid))

    @operation
    def wait(
        self,
        timeout: Optional[float] = None,
        *,
        poll_interval: float = 15.0,
        max_interval: float = 300.0,
    ):
        """Block until the molecule reaches a terminal stage.

        Returns the refreshed :class:`Molecule` on ``finished`` or ``capped``; raises
        :class:`~atb_client.MoleculeFailed` on ``failed``,
        :class:`~atb_client.MoleculeRejected` on ``rejected`` and
        :class:`~atb_client.Timeout` if ``timeout`` seconds pass first. Polls
        ``/status`` (which costs no quota), backing off from ``poll_interval`` to
        ``max_interval``.
        """
        from . import _ops

        return (
            yield from _ops.wait_molecule(
                self._client,
                self.molid,
                timeout=timeout,
                poll_interval=poll_interval,
                max_interval=max_interval,
            )
        )


class FileInfo(_Model):
    """One entry of ``GET /molecules/{molid}/files``."""

    name: str
    media_type: Optional[str] = None
    size: Optional[int] = None
    cached: Optional[bool] = None
    ff: Optional[str] = None
    topology_hash: Optional[str] = None


class Job(_Bound):
    """A server-side job (the D8 convention for anything that may be slow)."""

    id: Optional[str] = None
    kind: Optional[str] = None
    state: str = "queued"
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    params: Optional[Dict[str, Any]] = None
    # The wire field ``result`` is held as ``result_`` so that ``job.result(timeout=...)``
    # can be the method that waits for it.
    result_: Optional[Any] = Field(default=None, alias="result")
    error: Optional[Any] = None

    @property
    def done(self) -> bool:
        return self.state in ("done", "failed")

    @operation
    def result(self, timeout: Optional[float] = None):
        """Block until the job ends and return its ``result``.

        Raises :class:`~atb_client.JobFailed` (or the mapped problem exception) if it
        failed and :class:`~atb_client.Timeout` if ``timeout`` passes first.
        """
        from . import _ops

        job = self
        if not self.done:
            job = yield from _ops.wait_for_job(self._client, self.id, timeout=timeout)
        _ops.raise_for_job(self._client, job)
        return job.result_

    @operation
    def refresh(self):
        from . import _ops

        return (yield from _ops.get_job(self._client, self.id))

    @operation
    def cancel(self):
        from . import _ops

        return (yield from _ops.cancel_job(self._client, self.id))


T = TypeVar("T")


class Page(_Bound, Generic[T]):
    """One page of a cursor-paginated list.

    Iterating a page yields the items **of this page**; ``page.all()`` walks
    ``next_cursor`` and yields every item of every page (an async iterator on an
    :class:`~atb_client.AsyncATBClient`).
    """

    items: List[T] = []
    next_cursor: Optional[str] = None
    total: Optional[int] = None

    # Given a cursor, returns an _ops generator producing the next Page.
    _fetch: Optional[Callable[[str], Any]] = PrivateAttr(default=None)

    def __iter__(self) -> Iterator[T]:  # type: ignore[override]
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> T:
        return self.items[index]

    def __bool__(self) -> bool:
        return bool(self.items)

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None

    @stream_operation
    def all(self):
        """Every item on this page and all following pages."""
        from ._transport import Emit

        page: Page[T] = self
        while True:
            for item in page.items:
                yield Emit(item)
            if not page.next_cursor or page._fetch is None:
                return
            page = yield from page._fetch(page.next_cursor)


class Change(_Model):
    """One row of ``GET /molecules/changes``."""

    molid: int
    topology_hash: Optional[str] = None
    stage: Optional[str] = None
    changed_at: Optional[datetime] = None


class BatchItem(_Model):
    """One item of a ``POST /molecules:batch`` response."""

    index: int
    client_reference: Optional[str] = None
    molid: Optional[int] = None
    problem: Optional[Problem] = None

    @property
    def ok(self) -> bool:
        return self.molid is not None and self.problem is None

    @property
    def duplicate(self) -> bool:
        return bool(self.problem and (self.problem.type or "").endswith("duplicate-molecule"))


class BatchResult(_Model):
    items: List[BatchItem] = []

    @property
    def molids(self) -> List[int]:
        """Every molid the batch resolved to — new entries and adopted duplicates alike."""
        out: List[int] = []
        for item in self.items:
            if item.molid is not None:
                out.append(item.molid)
            elif item.duplicate and item.problem is not None:
                molid = (item.problem.model_extra or {}).get("molid")
                if molid is not None:
                    out.append(int(molid))
        return out

    @property
    def failed(self) -> List[BatchItem]:
        """Items that resolved to no molid at all (a problem other than a duplicate)."""
        return [i for i in self.items if i.molid is None and not i.duplicate]


class StructureMatch(_Model):
    molid: int
    is_identical: Optional[bool] = None
    rmsd: Optional[float] = None


class Usage(_Model):
    """``GET /me/usage``: today's counters and the key's limits (§5)."""

    burst_limit: Optional[int] = None
    burst_remaining: Optional[int] = None
    burst_reset: Optional[float] = None
    daily_limit: Optional[int] = None
    daily_used: Optional[int] = None
    daily_remaining: Optional[int] = None
    submissions_limit: Optional[int] = None
    submissions_used: Optional[int] = None
    day: Optional[str] = None


class ApiKey(_Model):
    """An API key. ``key`` (the secret) is present only in the response that created it."""

    id: Union[int, str]
    name: Optional[str] = None
    prefix: Optional[str] = None
    scopes: List[str] = []
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    key: Optional[str] = None


class Account(_Model):
    """``GET /me``."""

    id: Optional[int] = None
    email: Optional[str] = None
    name: Optional[str] = None
    user_class: Optional[int] = None
    group_id: Optional[int] = None
    scopes: List[str] = []
