"""The exception hierarchy.

Server errors are RFC 9457 problem details. Each response is mapped to an exception
by its ``type`` slug first (the last path segment of the problem ``type`` URL, e.g.
``duplicate-molecule``) and by HTTP status second, so a server that adds a new slug
still produces the right family of exception.

Every server-side exception carries ``.status`` (the HTTP status) and ``.problem``
(the parsed problem body, a :class:`atb_client.models.Problem`); nothing is drained
or discarded before the caller sees it.
"""

from __future__ import annotations

import email.utils
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

import httpx

from .models import Problem

if TYPE_CHECKING:  # pragma: no cover
    from .models import Job, MoleculeStatus

__all__ = [
    "APIError",
    "ATBError",
    "AuthenticationError",
    "ChemistryRejected",
    "ConfigurationError",
    "Conflict",
    "DuplicateMolecule",
    "GenerationRequired",
    "JobFailed",
    "MoleculeFailed",
    "MoleculeMoved",
    "MoleculeNotFound",
    "MoleculeRejected",
    "NetworkError",
    "NotFound",
    "PayloadTooLarge",
    "PermissionDenied",
    "RateLimited",
    "RemapRefused",
    "ServerError",
    "ServiceUnavailable",
    "Timeout",
    "TopologyVersionGone",
    "ValidationError",
]


class ATBError(Exception):
    """Base class of every exception this package raises."""


# --------------------------------------------------------------------------- server


class APIError(ATBError):
    """An error response from the API. Base of every server-side exception."""

    def __init__(
        self,
        problem: Problem,
        status: int,
        response: Optional[httpx.Response] = None,
    ) -> None:
        self.problem = problem
        self.status = status
        self.response = response
        message = problem.title or f"HTTP {status}"
        if problem.detail:
            message = f"{message}: {problem.detail}"
        super().__init__(message)

    @property
    def type(self) -> Optional[str]:
        return self.problem.type

    @property
    def slug(self) -> Optional[str]:
        return problem_slug(self.problem.type)

    @property
    def title(self) -> Optional[str]:
        return self.problem.title

    @property
    def detail(self) -> Optional[str]:
        return self.problem.detail

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status}, type={self.slug!r}, {str(self)!r})"


class ValidationError(APIError):
    """400 — the request was malformed; ``.errors`` holds the field errors."""

    @property
    def errors(self) -> List[Any]:
        extra = self.problem.model_extra or {}
        if "errors" in extra:
            return list(extra["errors"])
        # FastAPI's default 422 body is {"detail": [...]}.
        raw = self.problem.detail
        return list(raw) if isinstance(raw, list) else []


class PayloadTooLarge(ValidationError):
    """413 — the structure or upload is larger than the server accepts."""


class AuthenticationError(APIError):
    """401 — no key, an unknown key, or an expired or revoked one."""


class PermissionDenied(APIError):
    """403 — the key lacks the scope, or the molecule is not visible to it."""


class NotFound(APIError):
    """404."""


class MoleculeNotFound(NotFound):
    """404 on a molecule."""

    @property
    def molid(self) -> Optional[int]:
        return (self.problem.model_extra or {}).get("molid")


class MoleculeMoved(APIError):
    """301 ``molecule-moved`` on a request the client does not follow (anything but
    ``GET``/``HEAD``): the molecule was a duplicate merged into ``.canonical_molid``.
    ``GET`` requests follow the redirect instead and never raise this."""

    @property
    def molid(self) -> Optional[int]:
        value = (self.problem.model_extra or {}).get("molid")
        return int(value) if value is not None else None

    @property
    def canonical_molid(self) -> Optional[int]:
        value = (self.problem.model_extra or {}).get("canonical_molid")
        return int(value) if value is not None else None

    @property
    def location(self) -> Optional[str]:
        return self.response.headers.get("Location") if self.response is not None else None


class Conflict(APIError):
    """409 — e.g. a topology generation lock is held elsewhere."""


class GenerationRequired(Conflict):
    """409 ``generation-required`` — what the WP2 read surface answered for an uncached
    topology file, before the server generated on demand.

    The WP3 server never sends this any more: an uncached file now generates as a job
    and the download answers ``202`` instead, which :meth:`Files.download` already
    waits through. Kept only for compatibility with anything still catching it.
    ``.name`` is the file asked for."""

    @property
    def name(self) -> Optional[str]:
        return (self.problem.model_extra or {}).get("name")


class DuplicateMolecule(Conflict):
    """409 ``duplicate-molecule`` — the submitted structure already exists.

    This is the normal outcome of re-running a submission script: adopt the existing
    entry with ``.molecule`` (fetched lazily with one ``GET`` the first time it is
    read). On an :class:`AsyncATBClient` ``.molecule`` is awaitable instead.
    """

    _client: Any = None
    _molecule: Any = None

    @property
    def molid(self) -> Optional[int]:
        value = (self.problem.model_extra or {}).get("molid")
        return int(value) if value is not None else None

    @property
    def compound_id(self) -> Optional[int]:
        return (self.problem.model_extra or {}).get("compound_id")

    @property
    def molecule(self) -> Any:
        if self._molecule is not None:
            return self._molecule
        if self._client is None or self.molid is None:
            raise ATBError("this DuplicateMolecule is not bound to a client or carries no molid")
        result = self._client.molecules.get(self.molid)
        if getattr(self._client, "is_async", False):
            return self._resolve_async(result)
        self._molecule = result
        return result

    async def _resolve_async(self, awaitable: Any) -> Any:
        self._molecule = await awaitable
        return self._molecule


class TopologyVersionGone(APIError):
    """410 — the pinned ``hash`` is no longer cached; historical topologies cannot be rebuilt."""


class ChemistryRejected(APIError):
    """422 — the structure was refused on chemical grounds (charge/multiplicity, InChI, ...)."""

    @property
    def reason(self) -> Optional[str]:
        extra = self.problem.model_extra or {}
        return extra.get("reason") or self.problem.detail


class RemapRefused(ChemistryRejected):
    """422 ``remap-refused`` — ``atom_reorder`` could not map the uploaded structure onto
    this molecule (not the same molecule, or which atom is which cannot be decided).
    ``.report`` is the complete mapping report the server attached, the same one the
    molecule page's "Match to my structure" panel reads."""

    @property
    def report(self) -> Optional[Dict[str, Any]]:
        return (self.problem.model_extra or {}).get("report")


class RateLimited(APIError):
    """429 — a burst or daily limit is exhausted. ``.retry_after`` is in seconds."""

    @property
    def retry_after(self) -> Optional[float]:
        return retry_after_seconds(self.response)

    @property
    def limit(self) -> Optional[str]:
        """Which limit was hit (``burst``, ``daily``, ``submissions``), when the server says."""
        return (self.problem.model_extra or {}).get("limit")


class ServerError(APIError):
    """5xx — the platform's fault, not the caller's."""


class ServiceUnavailable(ServerError):
    """503 — a backing service (DB, Redis, Celery, a structure service) is down."""

    @property
    def retry_after(self) -> Optional[float]:
        return retry_after_seconds(self.response)


# --------------------------------------------------------------------------- client side


class ConfigurationError(ATBError):
    """The client could not be configured (bad config file, unsafe URL, unknown profile)."""


class NetworkError(ATBError):
    """The server could not be reached after every retry; ``__cause__`` is the httpx error."""


class MoleculeFailed(ATBError):
    """``Molecule.wait()`` reached the terminal stage ``failed``."""

    def __init__(self, molid: int, status: MoleculeStatus) -> None:
        self.molid = molid
        self.status = status
        super().__init__(f"molecule {molid} failed: {status.error or status.detail or ''}".rstrip())


class MoleculeRejected(ATBError):
    """``Molecule.wait()`` reached the terminal stage ``rejected``."""

    def __init__(self, molid: int, status: MoleculeStatus) -> None:
        self.molid = molid
        self.status = status
        super().__init__(
            f"molecule {molid} rejected: {status.error or status.detail or ''}".rstrip()
        )


class JobFailed(ATBError):
    """A server-side job ended in state ``failed``. ``.job`` holds it."""

    def __init__(self, job: Job) -> None:
        self.job = job
        super().__init__(f"job {job.id} ({job.kind}) failed: {job.error}")


class Timeout(ATBError):
    """The caller's ``timeout`` elapsed before the operation finished.

    ``.job`` is set when a server job was still running, ``.status`` when a molecule
    had not reached a terminal stage, ``.pending`` for ``wait_all``.
    """

    def __init__(
        self,
        message: str,
        *,
        job: Optional[Job] = None,
        status: Optional[MoleculeStatus] = None,
        pending: Optional[List[int]] = None,
    ) -> None:
        self.job = job
        self.status = status
        self.pending = pending
        super().__init__(message)


# --------------------------------------------------------------------------- mapping

_BY_SLUG: Dict[str, Type[APIError]] = {
    "validation-error": ValidationError,
    "invalid-request": ValidationError,
    "invalid-parameter": ValidationError,
    "payload-too-large": PayloadTooLarge,
    "structure-too-large": PayloadTooLarge,
    "unauthenticated": AuthenticationError,
    "authentication-required": AuthenticationError,
    "invalid-key": AuthenticationError,
    "key-expired": AuthenticationError,
    "key-revoked": AuthenticationError,
    "forbidden": PermissionDenied,
    "permission-denied": PermissionDenied,
    "insufficient-scope": PermissionDenied,
    "not-visible": PermissionDenied,
    "not-found": NotFound,
    "job-not-found": NotFound,
    "file-not-found": NotFound,
    "molecule-not-found": MoleculeNotFound,
    "conflict": Conflict,
    "generation-locked": Conflict,
    "topology-not-ready": Conflict,
    "job-not-finished": Conflict,
    "job-finished": Conflict,
    "job-cancelled": Conflict,
    "molecule-public": Conflict,
    "duplicate-molecule": DuplicateMolecule,
    "topology-version-gone": TopologyVersionGone,
    "job-result-expired": TopologyVersionGone,
    "chemistry-rejected": ChemistryRejected,
    "infeasible-structure": ChemistryRejected,
    "invalid-structure": ChemistryRejected,
    "topology-generation-failed": ChemistryRejected,
    "remap-refused": RemapRefused,
    "netcharge-missing": ValidationError,
    "netcharge-invalid": ValidationError,
    "batch-too-large": PayloadTooLarge,
    "private-submission-not-allowed": PermissionDenied,
    "not-molecule-owner": PermissionDenied,
    "user-label-not-allowed": PermissionDenied,
    "rate-limited": RateLimited,
    "burst-limit-exceeded": RateLimited,
    "daily-limit-exceeded": RateLimited,
    "submission-limit-exceeded": RateLimited,
    "server-error": ServerError,
    "internal-error": ServerError,
    "service-unavailable": ServiceUnavailable,
    "structure-service-unavailable": ServiceUnavailable,
    # Emitted by the server's WP0/WP1 code (website/website/api_v1), 2026-09-23.
    "bad-request": ValidationError,
    "method-not-allowed": APIError,
    "account-expired": AuthenticationError,
    "account-inactive": AuthenticationError,
    "key-escalation": PermissionDenied,
    "user-key-required": PermissionDenied,
    "key-not-found": NotFound,
    "key-limit-reached": Conflict,
    "schema-missing": ServiceUnavailable,
    "database-unavailable": ServiceUnavailable,
    "audit-unavailable": ServiceUnavailable,
    # Emitted by the WP2 read surface, 2026-09-23.
    "validation": ValidationError,
    "invalid-cursor": ValidationError,
    "invalid-filter": ValidationError,
    "invalid-limit": ValidationError,
    "invalid-motif-key": ValidationError,
    "file-restricted": PermissionDenied,
    "force-regen-forbidden": PermissionDenied,
    "file-name-unknown": NotFound,
    "forcefield-not-found": NotFound,
    "ifp-version-not-found": NotFound,
    "archetype-not-found": NotFound,
    "build-not-found": NotFound,
    "motif-not-found": NotFound,
    "statistic-not-found": NotFound,
    "structure-not-available": NotFound,
    "tautomer-group-not-found": NotFound,
    "user-not-found": NotFound,
    "molecule-moved": MoleculeMoved,
    "generation-required": GenerationRequired,
    "structure-unreadable": ChemistryRejected,
    "archetypes-unavailable": ServiceUnavailable,
    "graph-keys-not-installed": ServiceUnavailable,
    "library-not-installed": ServiceUnavailable,
    # Emitted by the admin surface (website/website/api_v1/routers/admin.py), WP5.
    "escalation-refused": PermissionDenied,
    "admin-account-protected": PermissionDenied,
    "field-needs-admin": PermissionDenied,
    "class-group-mismatch": ValidationError,
    "invalid-class": ValidationError,
    "invalid-grid": ValidationError,
    "scope-not-allowed": ValidationError,
    "approval-on-site": Conflict,
    "quota-request-approved": Conflict,
    "key-not-live": Conflict,
    "scan-exists": Conflict,
    "scan-not-cancellable": Conflict,
    "group-not-found": NotFound,
    "quota-request-not-found": NotFound,
}

_BY_STATUS: Dict[int, Type[APIError]] = {
    301: MoleculeMoved,
    400: ValidationError,
    401: AuthenticationError,
    403: PermissionDenied,
    404: NotFound,
    409: Conflict,
    410: TopologyVersionGone,
    413: PayloadTooLarge,
    422: ChemistryRejected,
    429: RateLimited,
    503: ServiceUnavailable,
}


def problem_slug(type_: Optional[str]) -> Optional[str]:
    """``https://atb.uq.edu.au/api/v1/errors/duplicate-molecule`` -> ``duplicate-molecule``."""
    if not type_ or type_ == "about:blank":
        return None
    return type_.rstrip("/").rsplit("/", 1)[-1] or None


def parse_problem(response: httpx.Response) -> Problem:
    """Parse any error body into a :class:`Problem`, however un-problem-like it is."""
    body: Any = None
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        data = dict(body)
        data.setdefault("status", response.status_code)
        if "title" not in data:
            data["title"] = response.reason_phrase or None
        try:
            return Problem.model_validate(data)
        except Exception:  # a body that is JSON but not a problem at all
            pass
    text = response.text if body is None else str(body)
    return Problem(
        status=response.status_code,
        title=response.reason_phrase or f"HTTP {response.status_code}",
        detail=text[:2000] or None,
    )


def exception_class_for(
    status: int,
    slug: Optional[str],
    *,
    not_found: Type[NotFound] = NotFound,
    problem: Optional[Problem] = None,
) -> Type[APIError]:
    if slug and slug in _BY_SLUG:
        cls = _BY_SLUG[slug]
        if cls is NotFound and not_found is not NotFound:
            return not_found
        return cls
    if status == 404:
        return not_found
    if status == 422 and problem is not None and isinstance(problem.detail, list):
        return ValidationError  # FastAPI's default request-validation body
    if status in _BY_STATUS:
        return _BY_STATUS[status]
    if status >= 500:
        return ServerError
    return APIError


def error_from_response(
    response: httpx.Response,
    *,
    not_found: Type[NotFound] = NotFound,
    client: Any = None,
) -> APIError:
    problem = parse_problem(response)
    cls = exception_class_for(
        response.status_code, problem_slug(problem.type), not_found=not_found, problem=problem
    )
    exc = cls(problem, response.status_code, response)
    if isinstance(exc, DuplicateMolecule):
        exc._client = client
    return exc


def error_from_problem(data: Dict[str, Any], *, client: Any = None) -> Optional[APIError]:
    """Map a problem embedded in a job's ``error`` field; ``None`` if it is not one."""
    if not isinstance(data, dict) or not ("type" in data or "status" in data):
        return None
    problem = Problem.model_validate(data)
    status = int(problem.status or 0)
    cls = exception_class_for(status, problem_slug(problem.type), problem=problem)
    exc = cls(problem, status, None)
    if isinstance(exc, DuplicateMolecule):
        exc._client = client
    return exc


def retry_after_seconds(response: Optional[httpx.Response]) -> Optional[float]:
    """``Retry-After`` as seconds: delta-seconds or an HTTP date."""
    if response is None:
        return None
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - time.time())
