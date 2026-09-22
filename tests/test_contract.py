"""The client against the server's published contract (``tests/data/openapi.json``).

Every client call is made against a mock that records the request, and the request
is checked against the schema:

- a call aimed at a route the server implements must hit an operation of that
  method and path, with the ``operationId`` expected here; send only query
  parameters the operation declares (plus the few listed in
  :data:`EXPECTED_EXTRA_PARAMS`, which the server does not take *yet*); send every
  query parameter and body field the operation requires; and send only body fields
  its request schema has;
- between them, the implemented calls must reach every public operation and be
  able to send every query parameter each declares;
- a call aimed at a route the server does not have yet must still miss the schema,
  and be listed in :data:`EXPECTED_MISSING`. When the server grows one of those
  routes this test fails, which is the prompt to move the call to
  :data:`IMPLEMENTED` and check its parameters.

Finally the hand-written response models are checked field-for-field against the
models generated from the same schema (:mod:`atb_client.generated.models`).

Refresh the schema from a checkout of the server with::

    python -c "import json; from website.api_v1.app import create_app; \\
        print(json.dumps(create_app('public', redis_client=object()).openapi(), indent=2))" \\
        > tests/data/openapi.json
    scripts/generate_models.sh tests/data/openapi.json
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set, Tuple

import httpx
import pytest
import respx
from pydantic import BaseModel

from atb_client import ATBClient, models
from atb_client._base import Resource
from atb_client.generated import models as generated

from .conftest import BASE, KEY

SCHEMA = json.loads((Path(__file__).parent / "data" / "openapi.json").read_text())
PREFIX = "/api/v1"


# --------------------------------------------------------------------------- the schema


class Operation(NamedTuple):
    method: str
    template: str  # without PREFIX
    op: Dict[str, Any]

    @property
    def operation_id(self) -> str:
        return self.op["operationId"]

    def query_params(self) -> Dict[str, bool]:
        return {
            p["name"]: bool(p.get("required"))
            for p in self.op.get("parameters", [])
            if p["in"] == "query"
        }

    def body_schema(self) -> Optional[Dict[str, Any]]:
        content = self.op.get("requestBody", {}).get("content", {})
        schema = content.get("application/json", {}).get("schema")
        return _deref(schema) if schema else None


def _deref(schema: Dict[str, Any]) -> Dict[str, Any]:
    while "$ref" in schema:
        schema = SCHEMA["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def _pattern(template: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)) + "$")


OPERATIONS: List[Operation] = [
    Operation(method.upper(), path[len(PREFIX) :], op)
    for path, methods in SCHEMA["paths"].items()
    for method, op in methods.items()
]


def find_operation(method: str, path: str) -> Optional[Operation]:
    """The operation serving ``method path``; a literal path beats a templated one,
    as the server's router order does (``/molecules/changes`` before ``/{molid}``)."""
    candidates = [o for o in OPERATIONS if o.method == method and _pattern(o.template).match(path)]
    candidates.sort(key=lambda o: o.template.count("{"))
    return candidates[0] if candidates else None


# --------------------------------------------------------------------------- recording


class Sent(NamedTuple):
    method: str
    path: str
    query: Set[str]
    body: Any


MAX_RECORDED = 3


def record(call: Callable[[ATBClient], Any]) -> List[Sent]:
    """Run ``call`` against a mock answering every request ``200 {}`` and return what
    was sent. What the client makes of ``{}`` is irrelevant here, so errors parsing it
    are ignored; the requests are what the contract is about."""
    sent: List[Sent] = []

    def responder(request: httpx.Request) -> httpx.Response:
        if len(sent) >= MAX_RECORDED:  # a poll that '{}' never satisfies
            raise httpx.ConnectError("enough recorded", request=request)
        body: Any = None
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = request.content  # a text upload (PUT .../lgf)
        path = request.url.path
        assert path.startswith(PREFIX), path
        sent.append(Sent(request.method, path[len(PREFIX) :], set(request.url.params), body))
        return httpx.Response(200, json={})

    with respx.mock(assert_all_called=False) as mock:
        mock.route().mock(side_effect=responder)
        with ATBClient(api_key=KEY, base_url=BASE, max_attempts=1) as client:
            try:
                call(client)
            except Exception:
                pass
    assert sent, "the call sent no request"
    return sent


# --------------------------------------------------------------------------- the calls

#: Every query parameter ``GET /molecules`` declares, as a search filter the client
#: forwards (``**filters``); values only need to be sendable.
SEARCH_FILTERS: Dict[str, Any] = {
    "inchi_key": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
    "inchi": "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
    "smiles": "CCO",
    "common_name": "ethanol",
    "formula": "C2H6O",
    "iupac": "ethanol",
    "chembl_id": "CHEMBL545",
    "pdb_hetid": "EOH",
    "rnme": "EOH",
    "moltype": "heteromolecule",
    "user_label": "x",
    "match": "partial",
    "q": "eth",
    "ids": [1, 2],
    "qm_level": [1, 2],
    "max_qm_level": [2],
    "curation_trust": [0],
    "min_atoms": 1,
    "max_atoms": 50,
    "is_finished": True,
    "has_error": False,
    "has_ti": True,
    "tag": "drug",
    "public": True,
    "owner": "me",
    "submitted_after": "2026-01-01T00:00:00Z",
}

Call = Callable[[ATBClient], Any]

#: Client calls whose route the server implements: id -> (call, operationId).
IMPLEMENTED: Dict[str, Tuple[Call, str]] = {
    "health": (lambda c: c.health(), "health_get"),
    "me.get": (lambda c: c.me.get(), "me_get"),
    "me.usage": (lambda c: c.me.usage(), "me_usage"),
    "me.keys.list": (lambda c: c.me.keys.list(), "me_keys_list"),
    "me.keys.create": (
        lambda c: c.me.keys.create("nb", scopes=["read"], expires_in_days=30),
        "me_keys_create",
    ),
    "me.keys.revoke": (lambda c: c.me.keys.revoke(3), "me_keys_revoke"),
    "me.request_quota": (
        lambda c: c.me.request_quota(reason="r", daily_limit=10, burst_per_min=5, key_id=3),
        "me_quota_requests_create",
    ),
    "me.molecules": (
        lambda c: c.me.molecules(limit=5, cursor="k", fields=["formula"]),
        "molecules_list",
    ),
    "molecules.search": (
        lambda c: c.molecules.search(limit=5, cursor="k", fields=["formula"], **SEARCH_FILTERS),
        "molecules_list",
    ),
    "molecules.changes": (lambda c: c.molecules.changes("k", limit=5), "molecules_changes"),
    "molecules.get": (lambda c: c.molecules.get(21), "molecules_get"),
    "molecules.status": (lambda c: c.molecules.status(21), "molecules_status"),
    "molecules.topologies": (lambda c: c.molecules.topologies(21), "molecules_topologies"),
    "molecules.qm": (lambda c: c.molecules.qm(21, level=1), "molecules_qm"),
    "molecules.validation": (lambda c: c.molecules.validation(21), "molecules_validation"),
    "molecules.solvation": (lambda c: c.molecules.solvation(21), "molecules_solvation"),
    "molecules.parameters": (
        lambda c: c.molecules.parameters(21, ff="54A7", hash="abc12"),
        "molecules_parameters",
    ),
    "molecules.tautomers": (lambda c: c.molecules.tautomers(21), "molecules_tautomers"),
    "molecules.conformations": (
        lambda c: c.molecules.conformations(21),
        "molecules_conformations",
    ),
    "files.list": (lambda c: c.files.list(21, hash="abc12", ff="54A7"), "molecules_files_list"),
    "files.download": (
        lambda c: c.files.download(21, "itp_aa", hash="abc12", ff="54A7"),
        "molecules_files_get",
    ),
    "structures.rmsd": (lambda c: c.structures.rmsd(molids=[21, 22]), "structures_rmsd"),
    "forcefields.list": (lambda c: c.forcefields.list(), "forcefields_list"),
    "forcefields.ifp": (
        lambda c: c.forcefields.ifp("54A7", format="gxx", rules=True, ifp_hash="d41d8"),
        "forcefields_ifp",
    ),
    "forcefields.mtb": (lambda c: c.forcefields.mtb("54A7", format="gxx"), "forcefields_mtb"),
    "forcefields.lammps": (
        lambda c: c.forcefields.lammps("54A7", ifp_hash="d41d8"),
        "forcefields_lammps",
    ),
    "parameters.versions": (lambda c: c.parameters.versions(), "parameters_versions_list"),
    "parameters.motifs": (
        lambda c: c.parameters.motifs(
            build_id=1,
            kind="bond",
            depth=2,
            element="C",
            min_n=1,
            max_n=9,
            min_spread=0.1,
            max_spread=0.9,
            has_hessian=True,
            sort="n",
            order="desc",
            limit=5,
            cursor="k",
        ),
        "parameters_motifs_list",
    ),
    "parameters.motif": (
        lambda c: c.parameters.motif("ab", kind="bond", depth=2, build_id=1),
        "parameters_motifs_get",
    ),
    "dihedrals.archetypes": (
        lambda c: c.dihedrals.archetypes(
            in_ifp=True,
            fit_failed=False,
            flag="x",
            molid=21,
            limit=5,
            cursor="k",
            force_regen=False,
        ),
        "dihedrals_archetypes_list",
    ),
    "dihedrals.archetype": (lambda c: c.dihedrals.archetype("a1"), "dihedrals_archetypes_get"),
    "tautomers.group": (
        lambda c: c.tautomers.group("k", limit=5, cursor="c"),
        "tautomers_groups_get",
    ),
    "statistics.get": (
        lambda c: c.statistics.get("molecules", include_validation_set=True, force_regen=False),
        "statistics_get",
    ),
}

#: Query parameters the client sends that an implemented operation does not declare
#: yet, by operationId. ``wait`` is the D8 convention: the server adds it with
#: generation-on-miss (WP3), and FastAPI ignores it until then.
EXPECTED_EXTRA_PARAMS: Dict[str, Set[str]] = {
    "molecules_files_get": {"wait"},
}

#: Client calls aimed at routes the server has not built yet (WP3, WP5, WP6):
#: id -> (call, "METHOD /path/template"). Their shapes follow the plan (§6).
UNBUILT: Dict[str, Tuple[Call, str]] = {
    "molecules.submit": (
        lambda c: c.molecules.submit("ATOM", format="pdb", netcharge=0),
        "POST /molecules",
    ),
    "molecules.submit_batch": (
        lambda c: c.molecules.submit_batch(sdf="$$$$"),
        "POST /molecules:batch",
    ),
    "molecules.update": (lambda c: c.molecules.update(21, public=True), "PATCH /molecules/{molid}"),
    "molecules.request_deletion": (
        lambda c: c.molecules.request_deletion(21),
        "POST /molecules/{molid}/deletion-requests",
    ),
    "molecules.flag": (
        lambda c: c.molecules.flag(21, reason="x"),
        "POST /molecules/{molid}/flags",
    ),
    "bundles.download": (
        lambda c: c.bundles.download(molids=[21], names=["itp_aa"]),
        "POST /bundles",
    ),
    "structures.search": (lambda c: c.structures.search("ATOM"), "POST /structures/search"),
    "jobs.get": (lambda c: c.jobs.get("j1"), "GET /jobs/{id}"),
    "jobs.list": (lambda c: c.jobs.list(state="running"), "GET /jobs"),
    "jobs.cancel": (lambda c: c.jobs.cancel("j1"), "DELETE /jobs/{id}"),
    "jobs.wait": (lambda c: c.jobs.wait("j1"), "GET /jobs/{id}"),
    "admin.users.list": (lambda c: c.admin.users.list("x"), "GET /admin/users"),
    "admin.users.get": (lambda c: c.admin.users.get(3), "GET /admin/users/{id}"),
    "admin.users.update": (
        lambda c: c.admin.users.update(3, group_id=1),
        "PATCH /admin/users/{id}",
    ),
    "admin.users.create_key": (
        lambda c: c.admin.users.create_key(3, name="k"),
        "POST /admin/users/{id}/keys",
    ),
    "admin.users.update_key": (
        lambda c: c.admin.users.update_key(3, 4, daily_limit=1),
        "PATCH /admin/users/{id}/keys/{kid}",
    ),
    "admin.users.revoke_key": (
        lambda c: c.admin.users.revoke_key(3, 4),
        "DELETE /admin/users/{id}/keys/{kid}",
    ),
    "admin.molecules.update": (
        lambda c: c.admin.molecules.update(21, max_qm_level=2),
        "PATCH /admin/molecules/{molid}",
    ),
    "admin.molecules.cache_clear": (
        lambda c: c.admin.molecules.cache_clear(21),
        "POST /admin/molecules/{molid}/cache:clear",
    ),
    "admin.molecules.invalidate": (
        lambda c: c.admin.molecules.invalidate(21),
        "POST /admin/molecules/{molid}:invalidate",
    ),
    "admin.molecules.regenerate": (
        lambda c: c.admin.molecules.regenerate(21),
        "POST /molecules/{molid}/topologies",
    ),
    "admin.molecules.request_scan": (
        lambda c: c.admin.molecules.request_scan(21),
        "POST /admin/molecules/{molid}/scans",
    ),
    "admin.molecules.cancel_scan": (
        lambda c: c.admin.molecules.cancel_scan(21, 5),
        "DELETE /admin/molecules/{molid}/scans/{run}",
    ),
    "admin.quota_requests": (
        lambda c: c.admin.quota_requests(),
        "GET /admin/quota-requests",
    ),
    "admin.approve_quota_request": (
        lambda c: c.admin.approve_quota_request(9),
        "POST /admin/quota-requests/{id}:approve",
    ),
    "admin.audit": (lambda c: c.admin.audit(), "GET /admin/audit"),
    "admin.usage": (lambda c: c.admin.usage(), "GET /admin/usage"),
    "admin.deletion_requests": (
        lambda c: c.admin.deletion_requests(),
        "GET /admin/deletion-requests",
    ),
    "pipeline.qm.claim": (
        lambda c: c.pipeline.qm.claim(level=1, runner_id="r"),
        "POST /pipeline/qm/claims",
    ),
    "pipeline.qm.claims": (
        lambda c: c.pipeline.qm.claims(runner_id="r"),
        "GET /pipeline/qm/claims",
    ),
    "pipeline.qm.release": (
        lambda c: c.pipeline.qm.release(21),
        "DELETE /pipeline/qm/claims/{molid}",
    ),
    "pipeline.qm.sync": (
        lambda c: c.pipeline.qm.sync(runner_id="r"),
        "POST /pipeline/qm/claims:sync",
    ),
    "pipeline.qm.results": (
        lambda c: c.pipeline.qm.results(molid=21, level=1, method="m", log="x"),
        "POST /pipeline/qm/results",
    ),
    "pipeline.qm.failures": (
        lambda c: c.pipeline.qm.failures(molid=21, level=1, status="ERROR"),
        "POST /pipeline/qm/failures",
    ),
    "pipeline.molecules.update": (
        lambda c: c.pipeline.molecules.update(21, cpu_time=1),
        "PATCH /pipeline/molecules/{molid}",
    ),
    "pipeline.molecules.update_compound": (
        lambda c: c.pipeline.molecules.update_compound(21, smiles="C"),
        "PATCH /pipeline/molecules/{molid}/compound",
    ),
    "pipeline.molecules.put_lgf": (
        lambda c: c.pipeline.molecules.put_lgf(21, "lgf"),
        "PUT /pipeline/molecules/{molid}/lgf",
    ),
    "pipeline.molecules.put_validation": (
        lambda c: c.pipeline.molecules.put_validation(21, "EMinVac", value=0.1),
        "PUT /pipeline/molecules/{molid}/validation/{kind}",
    ),
    "pipeline.molecules.notify": (
        lambda c: c.pipeline.molecules.notify(21),
        "POST /pipeline/molecules/{molid}/notify",
    ),
    "pipeline.callback": (
        lambda c: c.pipeline.callback(21, "finished"),
        "POST /pipeline/callbacks",
    ),
}

#: The routes the client calls that the server does not have. Checked to be exactly
#: the routes UNBUILT reaches, and each to be absent from the schema.
EXPECTED_MISSING: Set[str] = {
    "POST /molecules",
    "POST /molecules:batch",
    "PATCH /molecules/{molid}",
    "POST /molecules/{molid}/deletion-requests",
    "POST /molecules/{molid}/flags",
    "POST /molecules/{molid}/topologies",
    "POST /bundles",
    "POST /structures/search",
    "GET /jobs",
    "GET /jobs/{id}",
    "DELETE /jobs/{id}",
    "GET /admin/users",
    "GET /admin/users/{id}",
    "PATCH /admin/users/{id}",
    "POST /admin/users/{id}/keys",
    "PATCH /admin/users/{id}/keys/{kid}",
    "DELETE /admin/users/{id}/keys/{kid}",
    "PATCH /admin/molecules/{molid}",
    "POST /admin/molecules/{molid}/cache:clear",
    "POST /admin/molecules/{molid}:invalidate",
    "POST /admin/molecules/{molid}/scans",
    "DELETE /admin/molecules/{molid}/scans/{run}",
    "GET /admin/quota-requests",
    "POST /admin/quota-requests/{id}:approve",
    "GET /admin/audit",
    "GET /admin/usage",
    "GET /admin/deletion-requests",
    "POST /pipeline/qm/claims",
    "GET /pipeline/qm/claims",
    "DELETE /pipeline/qm/claims/{molid}",
    "POST /pipeline/qm/claims:sync",
    "POST /pipeline/qm/results",
    "POST /pipeline/qm/failures",
    "PATCH /pipeline/molecules/{molid}",
    "PATCH /pipeline/molecules/{molid}/compound",
    "PUT /pipeline/molecules/{molid}/lgf",
    "PUT /pipeline/molecules/{molid}/validation/{kind}",
    "POST /pipeline/molecules/{molid}/notify",
    "POST /pipeline/callbacks",
}

#: Public client methods that are not one route: they compose the ones above.
COMPOSITE = {"molecules.wait_all"}


# --------------------------------------------------------------------------- tests


def _client_methods() -> Set[str]:
    """Every public operation method reachable from a client's resources, as
    ``resource[.sub].method`` ids, plus client-level operations (``health``)."""
    found: Set[str] = set()

    def walk(prefix: str, obj: Any) -> None:
        for name, member in inspect.getmembers(type(obj)):
            if name.startswith("_"):
                continue
            if hasattr(member, "__atb_operation__"):
                found.add(f"{prefix}{name}")
        for name, value in vars(obj).items():
            if not name.startswith("_") and isinstance(value, Resource):
                walk(f"{prefix}{name}.", value)

    client = ATBClient(api_key=KEY, base_url=BASE)
    walk("", client)
    return found


def test_every_client_call_is_classified():
    classified = set(IMPLEMENTED) | set(UNBUILT) | COMPOSITE
    methods = _client_methods()
    assert methods - classified == set(), "classify these in IMPLEMENTED or UNBUILT"
    assert classified - methods == set(), "these client methods no longer exist"


@pytest.mark.parametrize("name", sorted(IMPLEMENTED))
def test_implemented_call_matches_its_operation(name):
    call, operation_id = IMPLEMENTED[name]
    first = record(call)[0]
    operation = find_operation(first.method, first.path)
    assert operation is not None, f"{first.method} {first.path} is not in the schema"
    assert operation.operation_id == operation_id

    declared = operation.query_params()
    extra = EXPECTED_EXTRA_PARAMS.get(operation_id, set())
    assert first.query - set(declared) - extra == set(), "query parameters the server ignores"
    required = {p for p, is_required in declared.items() if is_required}
    assert required - first.query == set(), "required query parameters not sent"

    schema = operation.body_schema()
    if schema is None:
        assert first.body in (None, {}), "a body the operation does not take"
    else:
        assert isinstance(first.body, dict)
        properties = set(schema.get("properties", {}))
        assert set(first.body) - properties == set(), "body fields the schema lacks"
        assert set(schema.get("required", [])) - set(first.body) == set()


def test_implemented_calls_cover_every_operation_and_parameter():
    reached: Dict[str, Set[str]] = {}
    for call, operation_id in IMPLEMENTED.values():
        first = record(call)[0]
        reached.setdefault(operation_id, set()).update(first.query)
    public = {o.operation_id: o for o in OPERATIONS}
    assert set(public) - set(reached) == set(), "server operations the client cannot call"
    for operation_id, operation in public.items():
        missing = set(operation.query_params()) - reached[operation_id]
        assert missing == set(), f"{operation_id}: parameters the client never sends"


def test_expected_extra_params_are_still_extra():
    for operation_id, params in EXPECTED_EXTRA_PARAMS.items():
        operation = next(o for o in OPERATIONS if o.operation_id == operation_id)
        assert params & set(operation.query_params()) == set(), (
            f"{operation_id} now declares {params}; drop it from EXPECTED_EXTRA_PARAMS"
        )


@pytest.mark.parametrize("name", sorted(UNBUILT))
def test_unbuilt_call_is_still_missing_from_the_server(name):
    call, route = UNBUILT[name]
    method, template = route.split(" ", 1)
    first = record(call)[0]
    assert first.method == method and _pattern(template).match(first.path), first
    assert route in EXPECTED_MISSING
    assert find_operation(first.method, first.path) is None, (
        f"the server now serves {route}: move {name} to IMPLEMENTED and check its parameters"
    )


def test_expected_missing_is_exactly_what_unbuilt_reaches():
    assert {route for _, route in UNBUILT.values()} == EXPECTED_MISSING


def test_the_client_never_targets_root_routes():
    # Root routes exist only on the internal listener (plan D6, D10).
    assert not any(o.template.startswith("/root") for o in OPERATIONS)
    assert not any(" /root" in route for route in EXPECTED_MISSING)


# --------------------------------------------------------------------------- models

#: generated response model -> the hand-written model the client returns for it.
MODEL_MAP: Dict[str, type] = {
    "Account": models.Account,
    "ArchetypeDetail": models.ArchetypeDetail,
    "ArchetypePage": models.ArchetypePage,
    "ArchetypeRow": models.ArchetypeRow,
    "BondedParameters": models.BondedParameters,
    "Change": models.Change,
    "ChangePage": models.Page,
    "Conformation": models.Conformation,
    "Conformations": models.Conformations,
    "ExperimentalValue": models.ExperimentalValue,
    "FileEntry": models.FileEntry,
    "FileList": models.FileList,
    "Forcefield": models.Forcefield,
    "ForcefieldList": models.ForcefieldList,
    "Health": models.Health,
    "Indicator": models.Indicator,
    "IndicatorSeries": models.IndicatorSeries,
    "KeyCreated": models.ApiKey,
    "KeyInfo": models.ApiKey,
    "KeyList": models.Page,  # me.keys.list() returns its items
    "KeyUsage": models.KeyUsage,
    "LibraryVersionList": models.LibraryVersions,
    "Limits": models.Limits,
    "Me": models.Me,
    "Molecule": models.Molecule,
    "MoleculePage": models.Page,
    "MoleculeStatus": models.MoleculeStatus,
    "MotifDetail": models.MotifDetail,
    "MotifPage": models.MotifPage,
    "MotifSummary": models.MotifSummary,
    "ProblemDetail": models.Problem,
    "QMLevel": models.QMLevel,
    "QMSummary": models.QMSummary,
    "QuotaRequestReceived": models.QuotaRequestReceived,
    "RMSDInput": models.RMSDInput,
    "RMSDResult": models.RMSDResult,
    "Solvation": models.Solvation,
    "SolvationResult": models.SolvationResult,
    "StatisticPoint": models.StatisticPoint,
    "Statistics": models.Statistics,
    "TautomerGroup": models.TautomerGroup,
    "Tautomers": models.Tautomers,
    "Topologies": models.Topologies,
    "TopologyVersionInfo": models.TopologyVersion,
    "Usage": models.Usage,
    "VacuumValidation": models.VacuumValidation,
    "Validation": models.Validation,
    # The server has two schemas named TautomerMember (molecules and reference);
    # FastAPI disambiguates them by module path. One client model serves both.
    "WebsiteApiV1SchemasMoleculesTautomerMember": models.TautomerMember,
    "WebsiteApiV1SchemasReferenceTautomerMember": models.TautomerMember,
}

#: Generated classes that are not responses the client parses.
NOT_RESPONSES = {
    "KeyCreate",  # request bodies: the resource methods' keyword arguments
    "QuotaRequest",
    "RMSDRequest",
    "HTTPValidationError",  # FastAPI's default 422, which the server replaces
    "ValidationError",
    "MoleculeLinks",  # Molecule.links is a dict of paths
    "ForcefieldLinks",  # Forcefield.links likewise
}


def _generated_models() -> Dict[str, type]:
    return {
        name: cls
        for name, cls in vars(generated).items()
        if isinstance(cls, type)
        and issubclass(cls, BaseModel)
        and cls.__module__ == generated.__name__
        and "root" not in cls.model_fields  # the RootModel constraint wrappers
    }


def test_every_generated_model_is_mapped():
    names = set(_generated_models())
    assert names - set(MODEL_MAP) - NOT_RESPONSES == set(), "map these in MODEL_MAP"
    assert (set(MODEL_MAP) | NOT_RESPONSES) - names == set(), "these schemas are gone"


@pytest.mark.parametrize("name", sorted(MODEL_MAP))
def test_hand_written_model_has_every_server_field(name):
    server_fields = set(_generated_models()[name].model_fields)
    ours = MODEL_MAP[name]
    client_fields = {f.alias or n for n, f in ours.model_fields.items()}
    assert server_fields - client_fields == set()
    assert ours.model_config.get("extra") == "allow"
