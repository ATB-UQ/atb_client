"""Response models.

Hand-written, and checked field by field against the models generated from the
server's OpenAPI document (:mod:`atb_client.generated.models`, by
``tests/test_contract.py``): every field the server declares has a field of the same
name here. They are not subclasses of the generated classes, deliberately:

- **Tolerance.** The generated classes mark fields required exactly as the server
  declares them. ``GET /molecules?fields=`` returns projections of a molecule, and a
  client older than the server must keep working when a field is dropped, so here
  only identity (``molid``, ``stage``, ``name``, ...) is required and everything else
  defaults. Every model also allows extra fields, so a field the server adds before
  the client is regenerated is kept (``model.model_extra``) rather than dropped.
- **Types.** The server serialises its timestamps through a custom serialiser, so its
  schema calls them plain strings; here they are :class:`~datetime.datetime`, parsed
  from the RFC 3339 UTC form the server sends (``...Z``) into aware UTC values.
  Site tables stamped in the server's local time are converted to UTC server-side.
- **Open vocabularies stay strings.** ``stage`` (D9) and a job's ``state`` are plain
  ``str``, never an enum or ``Literal``: a stage the server adds must not make an older
  client fail to parse a status. :data:`STAGES` and :data:`TERMINAL_STAGES` document
  the current set.
- **Behaviour.** ``Molecule.wait()``, ``Molecule.files``, ``Page.all()`` and
  ``Job.result()`` live on these classes, bound to the client that fetched them.

Units are the server's: energies in kJ/mol (``qm_energies`` as stored), RMSDs in nm,
volumes in cubic angstroms.
"""

from __future__ import annotations

from datetime import date, datetime
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
)

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from ._base import operation, stream_operation

if TYPE_CHECKING:  # pragma: no cover
    from .resources.files import MoleculeFiles

__all__ = [
    "TERMINAL_STAGES",
    "Account",
    "AdminUsageRow",
    "AdminUser",
    "AdminUserDetail",
    "ApiKey",
    "ArchetypeDetail",
    "ArchetypePage",
    "ArchetypeRow",
    "AuditRow",
    "BatchItem",
    "BatchResult",
    "BondedParameters",
    "BundleResult",
    "CacheCleared",
    "Change",
    "Conformation",
    "Conformations",
    "CurationResult",
    "DeletionRequestItem",
    "DeletionRequestPage",
    "DeletionRequestResult",
    "ExperimentalValue",
    "FileEntry",
    "FileInfo",
    "FileList",
    "FlagResult",
    "Forcefield",
    "ForcefieldList",
    "Health",
    "Indicator",
    "IndicatorSeries",
    "Job",
    "KeyUsage",
    "LibraryVersions",
    "Limits",
    "Me",
    "Molecule",
    "MoleculeStatus",
    "MotifDetail",
    "MotifPage",
    "MotifSummary",
    "Page",
    "Problem",
    "QMLevel",
    "QMSummary",
    "QuotaApproved",
    "QuotaRequestItem",
    "QuotaRequestReceived",
    "RMSDInput",
    "RMSDResult",
    "RemapResult",
    "ScanCancelled",
    "ScanQueued",
    "Solvation",
    "SolvationResult",
    "StalledItem",
    "StalledPage",
    "StatisticPoint",
    "Statistics",
    "StructureMatch",
    "StructureSearchResult",
    "SubmissionResult",
    "TautomerGroup",
    "TautomerMember",
    "Tautomers",
    "Topologies",
    "TopologyVersion",
    "Usage",
    "UsagePage",
    "VacuumValidation",
    "Validation",
]

#: D9's stages. ``terminal`` is true for the last four.
STAGES = ("queued", "qm0", "qm1", "qm2", "finished", "capped", "failed", "rejected")
TERMINAL_STAGES = ("finished", "capped", "failed", "rejected")
SUCCESS_STAGES = ("finished", "capped")
JOB_STATES = ("queued", "running", "done", "failed")


class _Model(BaseModel):
    """Base of every response model: extra fields kept, alias/name both accepted."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class _Bound(_Model):
    """A model that can make further calls through the client that fetched it."""

    _client: Any = PrivateAttr(default=None)

    def _bind(self, client: Any) -> _Bound:
        """Attach the client this instance can make further calls through."""
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
    """D9's status resource (``GET /molecules/{molid}/status``). Reading it costs no quota.

    ``stage`` is one of :data:`STAGES`; ``running`` is true while a ``qm<N>`` stage's
    calculation holds a claim; ``qm_level`` is the highest level completed (-1 for
    none) and ``next_level`` the one being run or waited for.
    """

    stage: str
    molid: Optional[int] = None
    terminal: bool = False
    running: Optional[bool] = None
    detail: Optional[str] = None
    since: Optional[datetime] = None
    eta_class: Optional[str] = None  # minutes | hours | days
    next_level: Optional[int] = None
    qm_level: Optional[int] = None
    maximum_qm_level: Optional[int] = None
    error: Optional[str] = None
    client_reference: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        """True on a successful terminal stage (``finished`` or ``capped``)."""
        return self.stage in SUCCESS_STAGES

    @property
    def is_terminal(self) -> bool:
        """True once the molecule has reached any terminal stage."""
        return self.terminal or self.stage in TERMINAL_STAGES


class Molecule(_Bound):
    """A molecule (``GET /molecules/{molid}``, or an item of ``GET /molecules``).

    Search results carry the summary fields only (narrowed further by ``fields=``);
    the detail fields (``inchi``, ``smiles``, ``owner``, ``status``, ``links``, ...)
    are ``None`` on them. ``inchi_key`` is the standard InChIKey,
    ``internal_inchi_key`` the non-standard (FixedH) one the ATB keys tautomers by.
    ``owner`` is shown only to the owner, admins and services.
    """

    molid: int
    # summary
    inchi_key: Optional[str] = None
    common_name: Optional[str] = None
    iupac: Optional[str] = None
    formula: Optional[str] = None
    atoms: Optional[int] = None
    netcharge: Optional[int] = None
    moltype: Optional[str] = None
    rnme: Optional[str] = None
    compound_id: Optional[int] = None
    chembl_id: Optional[str] = None
    pdb_hetid: Optional[str] = None
    public: Optional[bool] = None
    scheduled_for_deletion: Optional[bool] = None
    qm_level: Optional[int] = None
    maximum_qm_level: Optional[int] = None
    curation_trust: Optional[int] = None
    is_finished: Optional[bool] = None
    has_error: Optional[bool] = None
    submitted_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    # detail
    inchi: Optional[str] = None
    internal_inchi_key: Optional[str] = None
    smiles: Optional[str] = None
    chemspider_id: Optional[int] = None
    tautomer_group_id: Optional[int] = None
    user_label: Optional[str] = None
    pH: Optional[float] = None
    warning: Optional[str] = None
    error: Optional[str] = None
    owner: Optional[str] = None
    owned_by_caller: Optional[bool] = None
    tags: List[str] = []
    has_ti: Optional[bool] = None
    started_at: Optional[datetime] = None
    topology_generated_at: Optional[datetime] = None
    topology_updated_at: Optional[datetime] = None
    topology_hash: Optional[str] = None
    forcefield: Optional[str] = None
    status: Optional[MoleculeStatus] = None
    client_reference: Optional[str] = None
    links: Optional[Dict[str, str]] = None

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


class FileEntry(_Model):
    """One file of ``GET /molecules/{molid}/files``.

    ``name`` is the v1 name, ``legacy_name`` the v0.1 one it aliases; ``cached`` says
    whether it exists now; ``restricted`` files (QM logs, ``qm_data``, ``atb_log``)
    are listed only to keys that may read them; ``url`` is the download path.
    """

    name: str
    legacy_name: Optional[str] = None
    media_type: Optional[str] = None
    source: Optional[str] = None
    cached: Optional[bool] = None
    size: Optional[int] = None
    restricted: Optional[bool] = None
    url: Optional[str] = None


#: The pre-WP2 name of :class:`FileEntry`.
FileInfo = FileEntry


class FileList(_Model):
    """``GET /molecules/{molid}/files``: the files of one topology version and force
    field. Iterating it yields the :class:`FileEntry` items."""

    molid: Optional[int] = None
    forcefield: Optional[str] = None
    topology_hash: Optional[str] = None
    items: List[FileEntry] = []

    def __iter__(self) -> Iterator[FileEntry]:  # type: ignore[override]
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> FileEntry:
        return self.items[index]

    @property
    def names(self) -> List[str]:
        """The file names of every item."""
        return [item.name for item in self.items]

    @property
    def cached(self) -> List[FileEntry]:
        """The files that exist now."""
        return [item for item in self.items if item.cached]


class Job(_Bound):
    """A server-side job (the D8 convention for anything that may be slow).

    Not served yet: ``/jobs`` arrives with WP3, so its shape follows the plan (§6)."""

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
    result_status: Optional[int] = Field(
        None, description="The HTTP status the originating request would have had."
    )
    error: Optional[Any] = None
    links: Dict[str, str] = {}

    @property
    def done(self) -> bool:
        """True once the job has reached ``done`` or ``failed``."""
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
        """Fetch this job again; returns a new :class:`Job`."""
        from . import _ops

        return (yield from _ops.get_job(self._client, self.id))

    @operation
    def cancel(self):
        """Cancel this job; returns the updated :class:`Job`, if the server sends one."""
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
        """True when a `next_cursor` is available."""
        return self.next_cursor is not None

    @stream_operation
    def all(self):
        """Every item on this page and all following pages.

        Stops at a page with no ``next_cursor`` or with no items: ``GET
        /molecules/changes`` returns a cursor even on an empty page, so that the caller
        can resume from it later."""
        from ._transport import Emit

        page: Page[T] = self
        while True:
            for item in page.items:
                yield Emit(item)
            if not page.next_cursor or not page.items or page._fetch is None:
                return
            page = yield from page._fetch(page.next_cursor)


class Change(_Model):
    """One row of ``GET /molecules/changes``."""

    molid: int
    stage: Optional[str] = None
    topology_hash: Optional[str] = None
    changed_at: Optional[datetime] = None


# --------------------------------------------------------------------------- molecule sub-resources


class TopologyVersion(_Model):
    """One stored topology version (``GET /molecules/{molid}/topologies``). A version
    is servable while it is stored; none can be regenerated once gone."""

    hash: str
    forcefield: Optional[str] = None
    generated_at: Optional[datetime] = None
    atb_version: Optional[str] = None
    current: Optional[bool] = None


class Topologies(_Model):
    """``GET /molecules/{molid}/topologies``: every stored version, newest first."""

    molid: Optional[int] = None
    items: List[TopologyVersion] = []

    def __iter__(self) -> Iterator[TopologyVersion]:  # type: ignore[override]
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def current(self) -> List[TopologyVersion]:
        """The current version of each force field."""
        return [item for item in self.items if item.current]


class QMLevel(_Model):
    """The QM result one level's topology was built from. ``energy`` in kJ/mol,
    ``volume`` in cubic angstroms; ``contents`` lists what the (restricted)
    ``qm_data`` record holds."""

    level: str
    qm_type: Optional[str] = None
    charge_method: Optional[str] = None
    volume: Optional[float] = None
    n_atoms: Optional[int] = None
    energy: Optional[float] = None
    contents: List[str] = []


class QMSummary(_Model):
    """``GET /molecules/{molid}/qm``."""

    molid: Optional[int] = None
    levels: List[QMLevel] = []


class VacuumValidation(_Model):
    """The vacuum energy-minimisation check: ``rmsd_nm`` between the QM geometry and
    the minimised one, or ``failure``/``note`` saying why there is none.
    ``superposition`` links the two structures (``minimised``, ``reference``)."""

    rmsd_nm: Optional[float] = None
    failure: Optional[str] = None
    note: Optional[str] = None
    topology_hash: Optional[str] = None
    completed_at: Optional[datetime] = None
    superposition: Optional[Dict[str, str]] = None


class Validation(_Model):
    """``GET /molecules/{molid}/validation``."""

    molid: Optional[int] = None
    emin_vac: Optional[VacuumValidation] = None


class ExperimentalValue(_Model):
    """An experimental solvation free energy (kJ/mol)."""

    value: Optional[float] = None
    uncertainty: Optional[float] = None
    solvent: Optional[str] = None
    doi: Optional[str] = None


class SolvationResult(_Model):
    """One TI solvation free energy (kJ/mol). ``current`` marks the newest result per
    solvent and method."""

    id: int
    solvent: Optional[str] = None
    method: Optional[str] = None
    value: Optional[float] = None
    uncertainty: Optional[float] = None
    target_uncertainty: Optional[float] = None
    completed_at: Optional[datetime] = None
    topology_hash: Optional[str] = None
    current: Optional[bool] = None
    experimental: Optional[ExperimentalValue] = None


class Solvation(_Model):
    """``GET /molecules/{molid}/solvation``."""

    molid: Optional[int] = None
    results: List[SolvationResult] = []
    experimental: List[ExperimentalValue] = []
    note: Optional[str] = None


class BondedParameters(_Model):
    """``GET /molecules/{molid}/parameters``: the topology's bonded-assignment record
    (``None`` for a topology built before the bonded library, with ``note`` saying so)."""

    molid: Optional[int] = None
    forcefield: Optional[str] = None
    topology_hash: Optional[str] = None
    record: Optional[Dict[str, Any]] = None
    angle_constraints: Optional[Dict[str, Any]] = None
    note: Optional[str] = None


class TautomerMember(_Model):
    """A member of a tautomer family. ``energies`` is the lowest energy per qm_type,
    in kJ/mol."""

    molid: int
    compound_id: Optional[int] = None
    inchi_key: Optional[str] = None
    formula: Optional[str] = None
    netcharge: Optional[int] = None
    qm_level: Optional[int] = None
    energies: Dict[str, float] = {}


class Tautomers(_Model):
    """``GET /molecules/{molid}/tautomers``. ``grouping`` is ``skeleton_key``,
    ``tautomer_group_id`` or ``None`` (the molecule is in no group); a skeleton-key
    family spans formulas and charges, so compare energies within one
    (``formula``, ``netcharge``)."""

    molid: Optional[int] = None
    grouping: Optional[str] = None
    group: Optional[str] = None
    members: List[TautomerMember] = []


class Conformation(_Model):
    """One item of :class:`Conformations`: another molecule of the same compound."""

    molid: int
    energy: Optional[float] = None  # kJ/mol


class Conformations(_Model):
    """``GET /molecules/{molid}/conformations``: the compound's other molecules with
    their ``qm_type`` energies (kJ/mol)."""

    molid: Optional[int] = None
    compound_id: Optional[int] = None
    qm_type: Optional[str] = None
    items: List[Conformation] = []


# --------------------------------------------------------------------------- reference data


class Forcefield(_Model):
    """One entry of ``GET /forcefields``."""

    name: str
    ifp_formats: List[str] = []
    mtb_formats: List[str] = []
    available: Optional[bool] = None
    default: Optional[bool] = None
    links: Optional[Dict[str, Any]] = None


class ForcefieldList(Page[Forcefield]):
    """``GET /forcefields``; iterating yields :class:`Forcefield`."""

    default_forcefield: Optional[str] = None


class MotifSummary(_Model):
    """A bonded-library motif, as listed."""

    id: int
    key_hex: Optional[str] = None
    kind: Optional[str] = None
    depth: Optional[int] = None
    fragment: Optional[str] = None
    parent_id: Optional[int] = None
    n: Optional[int] = None
    n_k: Optional[int] = None
    n_by_level: Optional[Any] = None
    value_median: Optional[float] = None
    value_iqr: Optional[float] = None
    value_p001: Optional[float] = None
    value_p999: Optional[float] = None
    k_median: Optional[float] = None
    k_iqr: Optional[float] = None
    r_max: Optional[float] = None
    r_min: Optional[float] = None
    linear: Optional[bool] = None
    residual_iqr_max: Optional[float] = None
    build_id: Optional[int] = None
    first_seen: Optional[Any] = None


class MotifDetail(MotifSummary):
    """``GET /parameters/motifs/{key}``."""

    bond_order_hist: Optional[Any] = None
    terms: Optional[Any] = None
    residual_profile: Optional[Any] = None
    sin_allowed: Optional[Any] = None
    stereo: Optional[Any] = None
    ladder: Dict[str, List[Dict[str, Any]]] = {}
    versions_holding: List[Dict[str, Any]] = []


class MotifPage(Page[MotifSummary]):
    """``GET /parameters/motifs``; ``units`` names the unit of each value column."""

    build_id: Optional[int] = None
    units: Dict[str, str] = {}


class LibraryVersions(Page[Dict[str, Any]]):
    """``GET /parameters/versions``: published library versions, and the builds."""

    builds: List[Dict[str, Any]] = []
    default_build_id: Optional[int] = None


class ArchetypeRow(_Model):
    """A dihedral archetype, as listed. Energies in kJ/mol."""

    id: str
    molid: Optional[int] = None
    run_id: Optional[int] = None
    rnme: Optional[str] = None
    n_atoms: Optional[int] = None
    dihedral_names: List[str] = []
    dof_elements: Optional[str] = None
    fit: Optional[Any] = None
    n_terms: Optional[int] = None
    rmsd: Optional[float] = None
    rmsd_full: Optional[float] = None
    rmsd_units: Optional[str] = None
    disc_error: Optional[float] = None
    n_minima_qm: Optional[int] = None
    n_minima_fit: Optional[int] = None
    minima_match: Optional[bool] = None
    rest_energy_kj: Optional[float] = None
    fit_failed: Optional[bool] = None
    auto_exclude: Optional[bool] = None
    flags: List[str] = []
    term_ids: List[Any] = []
    in_ifp: Optional[bool] = None
    update_date: Optional[str] = None


class ArchetypePage(Page[ArchetypeRow]):
    """``GET /dihedrals/archetypes``; ``summary`` counts the whole library."""

    summary: Dict[str, Any] = {}


class ArchetypeDetail(_Model):
    """``GET /dihedrals/archetypes/{id}``: one fitted archetype (degrees, kJ/mol)."""

    id: str
    molid: Optional[int] = None
    run_id: Optional[int] = None
    metadata: Dict[str, Any] = {}
    graph: Dict[str, Any] = {}
    flags: List[str] = []
    flag_descriptions: List[Dict[str, Any]] = []
    fit_metrics: Dict[str, Any] = {}
    rmsd_units: Optional[str] = None
    e_window_kj: Optional[float] = None
    fit_failed: Optional[bool] = None
    auto_exclude: Optional[bool] = None
    manual_include: Optional[bool] = None
    in_ifp: Optional[bool] = None
    term_ids: List[Any] = []
    ifp_terms: List[Dict[str, Any]] = []
    energies: Dict[str, Any] = {}


class TautomerGroup(Page[TautomerMember]):
    """``GET /tautomers/groups/{group_id}``; iterating yields :class:`TautomerMember`."""

    group_id: Optional[str] = None
    grouping: Optional[str] = None


class StatisticPoint(_Model):
    """One dated value of a site indicator."""

    date: date
    value: Optional[float] = None
    sample_size: Optional[int] = None


class Indicator(_Model):
    """A site indicator's latest value."""

    name: str
    unit: Optional[str] = None
    latest: Optional[StatisticPoint] = None


class IndicatorSeries(_Model):
    """A site indicator's full history of :class:`StatisticPoint`."""

    name: str
    unit: Optional[str] = None
    points: List[StatisticPoint] = []


class Statistics(_Model):
    """``GET /statistics``: every indicator's latest value, one indicator's ``series``
    when asked for by ``name``, and the validation-set summary."""

    indicators: List[Indicator] = []
    series: Optional[IndicatorSeries] = None
    validation_set: Optional[Dict[str, Any]] = None


class RMSDInput(_Model):
    """One structure of an :class:`RMSDResult`'s ``inputs``, in matrix order."""

    index: int
    molid: Optional[int] = None
    source: Optional[str] = None  # uploaded | pdb_allatom_optimised | pdb_normalised


class RMSDResult(_Model):
    """``POST /structures/rmsd``: pairwise RMSDs in nm after optimal alignment, in the
    order molids first, then uploaded structures. ``None`` where two molecular graphs
    do not match (a different tautomer included). ``rmsd`` is ``rmsd_matrix[0][1]``."""

    inputs: List[RMSDInput] = []
    rmsd_matrix: List[List[Optional[float]]] = []
    rmsd: Optional[float] = None


class Health(_Model):
    """``GET /health`` (unauthenticated)."""

    status: str
    role: Optional[str] = None
    version: Optional[str] = None
    database: Optional[bool] = None
    redis: Optional[bool] = None
    broker: Optional[bool] = None
    schema_present: Optional[bool] = None
    tables: Dict[str, bool] = {}


# --------------------------------------------------------------------------- account


class KeyUsage(_Model):
    """One key's contribution to a rate limit shared across several keys."""

    key_id: int
    prefix: Optional[str] = None
    weight: int = 0


class Usage(_Model):
    """``GET /me/usage``: this UTC ``day``'s weighted requests for the calling key
    (``weight``) and each of the account's keys (``keys``), with the key's limits
    (``None``: not limited)."""

    day: Optional[date] = None
    key_id: Optional[int] = None
    weight: int = 0
    daily_limit: Optional[int] = None
    daily_remaining: Optional[int] = None
    burst_per_min: Optional[int] = None
    keys: List[KeyUsage] = []


class ApiKey(_Model):
    """An API key (``GET /me/keys`` items; ``POST /me/keys``). ``key`` (the secret) is
    present only in the response that created it. ``burst_per_min``/``daily_limit``
    ``None`` means the account class's default."""

    id: int
    prefix: Optional[str] = None
    principal: Optional[str] = None
    name: Optional[str] = None
    format: Optional[str] = None
    scopes: List[str] = []
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_by_key_id: Optional[int] = None
    burst_per_min: Optional[int] = None
    daily_limit: Optional[int] = None
    key: Optional[str] = None


class Limits(_Model):
    """A key's limits; ``None`` is not limited."""

    burst_per_min: Optional[int] = None
    daily_limit: Optional[int] = None


class Account(_Model):
    """The user account behind a user key."""

    id: int
    email: Optional[str] = None
    user_class: Optional[int] = None
    group_id: Optional[int] = None


class Me(_Model):
    """``GET /me``: who the key is (``principal``: ``user``, ``service`` or ``root``)
    and what it may do. ``account`` is set for user keys only."""

    principal: str
    name: Optional[str] = None
    key_id: Optional[int] = None
    key_prefix: Optional[str] = None
    key_expires_at: Optional[datetime] = None
    scopes: List[str] = []
    limits: Limits = Limits()
    account: Optional[Account] = None


class QuotaRequestReceived(_Model):
    """``POST /me/quota-requests`` → ``202``: an admin will review it."""

    status: str = "received"
    key_id: Optional[int] = None


# --------------------------------------------------------------------------- submission


class SubmissionResult(_Model):
    """``POST /molecules`` with ``dry_run=True`` (``200``): what would have been
    submitted, without inserting anything — ``molid``/``compound_id`` are ``None``."""

    molid: Optional[int] = None
    compound_id: Optional[int] = None
    client_reference: Optional[str] = None
    dry_run: bool = False


class RemapResult(_Model):
    """The ``report.json`` inside a successful ``molecules.remap()`` zip, or the report
    carried by a :class:`~atb_client.exceptions.RemapRefused` (422)."""

    mapping: Optional[Dict[str, Any]] = None


class DeletionRequestResult(_Model):
    """``POST /molecules/{molid}/deletion-requests`` (``201``)."""

    molid: int
    scheduled_for_deletion: bool = False


class FlagResult(_Model):
    """``POST /molecules/{molid}/flags`` (``201``)."""

    molid: int
    flagged: bool = False


class BundleResult(_Model):
    """``POST /bundles`` (``200``): the built zip's location, or (when the caller
    asked for it as a job) the job that will build it."""

    job_id: Optional[str] = None
    download_url: Optional[str] = None
    size: Optional[int] = None
    forcefield: Optional[str] = None
    files: Optional[int] = None
    missing: List[Dict[str, Any]] = []
    retention_hours: Optional[int] = None


class BatchItem(_Model):
    """One item of a ``POST /molecules:batch`` response, in input order."""

    index: int
    client_reference: Optional[str] = None
    molid: Optional[int] = None
    compound_id: Optional[int] = None
    problem: Optional[Dict[str, Any]] = Field(
        None, description="Why this item was not submitted (RFC 9457 body)."
    )

    @property
    def ok(self) -> bool:
        """True when this item was submitted (or adopted a duplicate) without error."""
        return self.molid is not None and self.problem is None

    @property
    def duplicate(self) -> bool:
        """True when this item was refused because it already exists."""
        type_ = str(self.problem.get("type") or "") if self.problem else ""
        return type_.endswith("duplicate-molecule")


class BatchResult(_Model):
    """``POST /molecules:batch``'s response: one :class:`BatchItem` per input record."""

    items: List[BatchItem] = []
    submitted: int = 0
    refused: int = 0
    dry_run: bool = False
    submissions_remaining: Optional[int] = Field(
        None, description="Of today's submission cap; null: uncapped."
    )

    @property
    def molids(self) -> List[int]:
        """Every molid the batch resolved to — new entries and adopted duplicates alike.

        A duplicate item carries no top-level ``molid`` (the server sets it only on a
        submitted item); the existing molecule's id is in ``.problem['molid']``.
        """
        out: List[int] = []
        for item in self.items:
            if item.molid is not None:
                out.append(item.molid)
            elif item.duplicate and item.problem is not None:
                molid = item.problem.get("molid")
                if molid is not None:
                    out.append(int(molid))
        return out

    @property
    def failed(self) -> List[BatchItem]:
        """Items that resolved to no molid at all (a problem other than a duplicate)."""
        return [i for i in self.items if i.molid is None and not i.duplicate]


class StructureMatch(_Model):
    """One candidate of a ``structures.search()`` result."""

    molid: int
    rmsd: Optional[float] = Field(
        None,
        description="Blind-RMSD in nm after optimal alignment; null when the search "
        "budget ran out before this candidate was aligned.",
    )
    is_identical: Optional[bool] = None
    compared: bool = True


class StructureSearchResult(_Model):
    """``POST /structures/search`` → public molecules matching a structure, closest
    first. ``complete=False`` means the ~105 s search budget ran out before every
    candidate was aligned; those are still listed, with ``compared=False``."""

    search_molecule: Dict[str, Optional[str]] = {}
    matches: List[StructureMatch] = []
    total_matches: int = 0
    uncompared: int = 0
    complete: bool = True


# --------------------------------------------------------------------------- admin (WP5)


class AdminUser(_Model):
    """One row of ``GET /admin/users`` and the body of ``GET/PATCH /admin/users/{id}``."""

    id: int
    email: Optional[str] = None
    fullname: Optional[str] = None
    institute: Optional[str] = None
    user_class: Optional[int] = None
    group_id: Optional[int] = None
    expiry: Optional[date] = None


class AdminUserDetail(AdminUser):
    """``GET/PATCH /admin/users/{id}``: the account plus its keys and molecule count."""

    keys: List[ApiKey] = []
    molecules: int = 0


class AuditRow(_Model):
    """One row of ``GET /admin/audit``: an admin, service or root write, or a denial."""

    id: int
    at: Optional[datetime] = None
    key_id: Optional[int] = None
    principal: Optional[str] = None
    user_email: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    outcome: Optional[str] = None
    status: Optional[int] = None
    detail: Optional[Any] = None
    ip: Optional[str] = None


class CurationResult(_Model):
    """``PATCH /admin/molecules/{molid}`` (or a ``pipeline:write`` service key raising
    ``max_qm_level`` alone)."""

    molid: int
    changed: Dict[str, Any] = {}
    qm_level: Optional[int] = None
    max_qm_level: Optional[int] = None
    curation_trust: Optional[int] = None
    datasets: List[str] = []
    tags: List[str] = []
    stage: Optional[str] = None


class CacheCleared(_Model):
    """``POST /admin/molecules/{molid}/cache:clear``."""

    molid: int
    all: bool = False
    removed: List[str] = []
    kept: List[Dict[str, Any]] = []


class ScanQueued(_Model):
    """``POST /admin/molecules/{molid}/scans``."""

    scan_request_id: int
    dihedral_run_id: Optional[int] = None
    molid: int
    dihedral_atoms: Optional[str] = None
    method: Optional[str] = None
    mode: Optional[str] = None
    execution: Optional[str] = None
    status: str = "queued"


class ScanCancelled(_Model):
    """``DELETE /admin/molecules/{molid}/scans/{scan_request_id}``."""

    scan_request_id: int
    molid: int
    status: str = "cancelled"


class QuotaRequestItem(_Model):
    """One row of ``GET /admin/quota-requests``."""

    id: int
    at: Optional[datetime] = None
    key_id: Optional[int] = None
    user_email: Optional[str] = None
    burst_per_min: Optional[int] = None
    daily_limit: Optional[int] = None
    reason: Optional[str] = None
    status: str = "pending"
    approval: Optional[Dict[str, Any]] = None


class QuotaApproved(_Model):
    """``POST /admin/quota-requests/{id}:approve``."""

    request_id: int
    approval_id: Optional[int] = None
    key: Optional[ApiKey] = None


class DeletionRequestItem(_Model):
    """One row of ``GET /admin/deletion-requests``. Acting on it is a root operation."""

    molid: int
    owner: Optional[str] = None
    public: bool = False
    request_time: Optional[Any] = None
    deletable: bool = False
    blockers: List[Dict[str, Any]] = []


class DeletionRequestPage(_Model):
    """``GET /admin/deletion-requests`` — not cursor-paginated (up to 1000 rows)."""

    items: List[DeletionRequestItem] = []

    def __iter__(self) -> Iterator[DeletionRequestItem]:  # type: ignore[override]
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


class StalledItem(_Model):
    """One row of ``GET /admin/molecules/stalled`` (plan D9 ``stalled``)."""

    molid: int
    atoms: Optional[int] = None
    owner: Optional[str] = None
    status: Optional[MoleculeStatus] = None


class StalledPage(Page[StalledItem]):
    """``GET /admin/molecules/stalled``: a scan-and-filter page, so it can hold fewer
    items than it examined (``scanned``); ``next_cursor`` continues the scan."""

    scanned: int = 0


class AdminUsageRow(_Model):
    """One row of ``GET /admin/usage``: weighted usage for one key on one UTC day."""

    key_id: int
    prefix: Optional[str] = None
    principal: Optional[str] = None
    name: Optional[str] = None
    user_email: Optional[str] = None
    weight: int = 0


class UsagePage(_Model):
    """``GET /admin/usage``: every key's weighted usage for one UTC day, heaviest first."""

    day: Optional[date] = None
    items: List[AdminUsageRow] = []
    total_weight: int = 0

    def __iter__(self) -> Iterator[AdminUsageRow]:  # type: ignore[override]
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)
