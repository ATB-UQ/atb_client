"""``atb`` — the command-line client.

JSON on stdout by default (``--table`` for humans), errors as JSON on stderr, and exit
codes that are a contract a workflow engine can branch on:

====  ==========================================================================
0     done (for ``status``: the molecule is ``finished`` or ``capped``)
1     error (anything not listed below)
2     usage (bad arguments, no API key configured)
3     rate-limited (retry after the ``retry_after`` in the error body)
4     still running (``status`` not terminal; a ``--wait``/download timeout)
5     failed or rejected (the molecule, the job, or the chemistry)
====  ==========================================================================

The API key is never accepted on the command line: it comes from ``ATB_API_KEY`` or
the config-file profile (``--profile``).

``atb status <molid>`` is the poll-once step for Nextflow/Snakemake on an HPC login
node: a short-lived process, no held connection, branch on the exit code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence

from pydantic import BaseModel

from ._client import ATBClient
from ._version import __version__
from .exceptions import (
    APIError,
    ATBError,
    ChemistryRejected,
    ConfigurationError,
    DuplicateMolecule,
    JobFailed,
    MoleculeFailed,
    MoleculeRejected,
    RateLimited,
    Timeout,
)
from .resources.me import days_of

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_RATE_LIMITED = 3
EXIT_RUNNING = 4
EXIT_FAILED = 5

_FORMAT_BY_SUFFIX = {
    ".pdb": "pdb",
    ".sdf": "sdf",
    ".mol": "sdf",
    ".mol2": "mol2",
    ".smi": "smiles",
    ".smiles": "smiles",
}


class UsageError(Exception):
    pass


# --------------------------------------------------------------------------- output


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _table(value: Any) -> str:
    value = _jsonable(value)
    if isinstance(value, dict):
        width = max((len(k) for k in value), default=0)
        return "\n".join(
            f"{k.ljust(width)}  {json.dumps(v) if isinstance(v, (dict, list)) else v}"
            for k, v in value.items()
        )
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        columns: List[str] = []
        for row in value:
            columns.extend(c for c in row if c not in columns)
        cells = [[_cell(row.get(c)) for c in columns] for row in value]
        widths = [max(len(c), *(len(r[i]) for r in cells)) for i, c in enumerate(columns)]
        lines = ["  ".join(c.ljust(w) for c, w in zip(columns, widths))]
        lines += ["  ".join(v.ljust(w) for v, w in zip(r, widths)) for r in cells]
        return "\n".join(line.rstrip() for line in lines)
    if isinstance(value, list):
        return "\n".join(_cell(v) for v in value)
    return _cell(value)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _emit(args: argparse.Namespace, value: Any) -> None:
    if getattr(args, "table", False):
        print(_table(value))
    else:
        print(json.dumps(_jsonable(value), indent=2))


def _emit_error(kind: str, message: str, **extra: Any) -> None:
    body = {"error": kind, "message": message}
    body.update({k: v for k, v in extra.items() if v is not None})
    print(json.dumps(_jsonable(body), indent=2), file=sys.stderr)


# --------------------------------------------------------------------------- commands


def _status_exit(stage: str, terminal: bool) -> int:
    if stage in ("failed", "rejected"):
        return EXIT_FAILED
    if stage in ("finished", "capped"):
        return EXIT_OK
    return EXIT_OK if terminal else EXIT_RUNNING


def cmd_get(atb: ATBClient, args: argparse.Namespace) -> int:
    _emit(args, atb.molecules.get(args.molid))
    return EXIT_OK


def cmd_status(atb: ATBClient, args: argparse.Namespace) -> int:
    status = atb.molecules.status(args.molid)
    _emit(args, status)
    return _status_exit(status.stage, status.terminal)


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).read_text()
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc}") from exc


def cmd_submit(atb: ATBClient, args: argparse.Namespace) -> int:
    fmt = args.format or _FORMAT_BY_SUFFIX.get(Path(args.file).suffix.lower())
    if fmt is None:
        raise UsageError("cannot tell the structure format from the file name; pass --format")
    duplicate = False
    try:
        molecule = atb.molecules.submit(
            _read(args.file),
            format=fmt,
            netcharge=args.charge,
            public=args.public,
            client_reference=args.ref,
            max_qm_level=args.max_qm_level,
            moltype=args.moltype,
            timeout=args.timeout,
        )
    except DuplicateMolecule as dup:
        duplicate = True
        molecule = dup.molecule
    if args.wait:
        molecule = molecule.wait(timeout=args.wait_timeout)
    out = _jsonable(molecule)
    out["duplicate"] = duplicate
    _emit(args, out)
    return EXIT_OK


def cmd_submit_batch(atb: ATBClient, args: argparse.Namespace) -> int:
    result = atb.molecules.submit_batch(
        sdf=_read(args.file),
        netcharge_field=args.charge_field,
        reference_field=args.ref_field,
        netcharge=args.charge,
        public=args.public,
        timeout=args.timeout,
    )
    _emit(args, result.items if args.table else result)
    return EXIT_OK


def cmd_download(atb: ATBClient, args: argparse.Namespace) -> int:
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in args.names:
        path = atb.files.download(
            args.molid, name, out_dir, timeout=args.timeout, hash=args.hash, ff=args.ff
        )
        written.append({"name": name, "path": str(path)})
    _emit(args, written)
    return EXIT_OK


def cmd_bundle(atb: ATBClient, args: argparse.Namespace) -> int:
    molids: List[int] = []
    if args.molids:
        molids += [int(m) for m in args.molids.split(",") if m.strip()]
    if args.molids_from:
        text = _read(args.molids_from)
        molids += [int(tok) for tok in text.replace(",", " ").split() if tok.strip()]
    if not molids:
        raise UsageError("give --molids or --molids-from")
    target = atb.bundles.download(molids, args.names, into=args.output, timeout=args.timeout)
    _emit(args, {"into": str(target), "molids": molids, "names": args.names})
    return EXIT_OK


def cmd_search(atb: ATBClient, args: argparse.Namespace) -> int:
    filters = {
        "inchi_key": args.inchi_key,
        "inchi": args.inchi,
        "smiles": args.smiles,
        "common_name": args.common_name,
        "formula": args.formula,
        "q": args.q,
    }
    for item in args.filter or []:
        if "=" not in item:
            raise UsageError(f"--filter takes key=value, got {item!r}")
        key, value = item.split("=", 1)
        filters[key] = value
    filters = {k: v for k, v in filters.items() if v is not None}
    page = atb.molecules.search(limit=args.limit, **filters)
    if args.all:
        _emit(args, list(page.all()))
    elif args.table:
        _emit(args, page.items)
    else:
        _emit(args, page)
    return EXIT_OK


def cmd_ifp(atb: ATBClient, args: argparse.Namespace) -> int:
    result = atb.forcefields.ifp(args.ff, format=args.format, path=args.output)
    if args.output:
        _emit(args, {"path": str(result)})
    else:
        sys.stdout.write(result)
    return EXIT_OK


def cmd_keys_create(atb: ATBClient, args: argparse.Namespace) -> int:
    scopes = [s for s in args.scopes.split(",") if s] if args.scopes else None
    try:
        days = days_of(args.expires)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    key = atb.me.keys.create(args.name or "atb cli", scopes=scopes, expires_in_days=days)
    _emit(args, key)
    if key.key:
        print(
            "The key is shown once. Store it now, e.g. in ~/.config/atb/config.toml.",
            file=sys.stderr,
        )
    return EXIT_OK


def cmd_keys_list(atb: ATBClient, args: argparse.Namespace) -> int:
    _emit(args, atb.me.keys.list())
    return EXIT_OK


def cmd_keys_revoke(atb: ATBClient, args: argparse.Namespace) -> int:
    result = atb.me.keys.revoke(args.id)
    _emit(args, result if result is not None else {"revoked": args.id})
    return EXIT_OK


def cmd_usage(atb: ATBClient, args: argparse.Namespace) -> int:
    _emit(args, atb.me.usage())
    return EXIT_OK


# --------------------------------------------------------------------------- parser


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        _emit_error("usage", message)
        raise SystemExit(EXIT_USAGE)


def _common(suppress: bool) -> argparse.ArgumentParser:
    """Global options, accepted before or after the subcommand. On subparsers their
    defaults are suppressed so they do not overwrite a value given before it."""
    kw: dict = {"default": argparse.SUPPRESS} if suppress else {}
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--profile", help="config-file profile (default: ATB_PROFILE or 'default')", **kw
    )
    common.add_argument(
        "--base-url", help="API base URL (default: ATB_API_URL or the profile)", **kw
    )
    common.add_argument("--table", action="store_true", help="human-readable output", **kw)
    return common


def build_parser() -> argparse.ArgumentParser:
    top = _common(suppress=False)
    common = _common(suppress=True)

    parser = _Parser(
        prog="atb",
        description="Command-line client for the ATB API v1. The API key comes from "
        "ATB_API_KEY or ~/.config/atb/config.toml, never from the command line.",
        parents=[top],
        epilog="exit codes: 0 done, 1 error, 2 usage, 3 rate-limited, 4 still running, "
        "5 failed/rejected",
    )
    parser.add_argument("--version", action="version", version=f"atb-client {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", parser_class=_Parser)
    sub.required = True

    def add(name: str, func: Any, help: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help, parents=[common])
        p.set_defaults(func=func)
        return p

    p = add("get", cmd_get, "a molecule's metadata")
    p.add_argument("molid", type=int)

    p = add("status", cmd_status, "poll a molecule once; exit 0 done, 4 running, 5 failed")
    p.add_argument("molid", type=int)

    p = add("submit", cmd_submit, "submit a structure (a duplicate adopts the existing entry)")
    p.add_argument("file", help="structure file, or - for stdin")
    p.add_argument("--charge", type=int, required=True, help="net charge")
    p.add_argument("--format", choices=["pdb", "sdf", "mol2", "smiles"])
    vis = p.add_mutually_exclusive_group()
    vis.add_argument("--public", dest="public", action="store_true", default=True)
    vis.add_argument("--private", dest="public", action="store_false")
    p.add_argument("--ref", help="client_reference echoed on the molecule and its status")
    p.add_argument("--max-qm-level", type=int)
    p.add_argument("--moltype")
    p.add_argument("--timeout", type=float, default=600.0, help="for the submission itself")
    p.add_argument(
        "--wait",
        action="store_true",
        help="block until the molecule is done (interactive use; not the HPC idiom)",
    )
    p.add_argument("--wait-timeout", type=float, default=None)

    p = add("submit-batch", cmd_submit_batch, "submit up to 100 structures from an SDF")
    p.add_argument("file", help="SDF file, or - for stdin")
    p.add_argument("--charge-field", help="SD field holding each record's net charge")
    p.add_argument("--ref-field", default="_Name", help="SD field used as client_reference")
    p.add_argument("--charge", type=int, help="net charge for records without --charge-field")
    vis = p.add_mutually_exclusive_group()
    vis.add_argument("--public", dest="public", action="store_true", default=True)
    vis.add_argument("--private", dest="public", action="store_false")
    p.add_argument("--timeout", type=float, default=600.0)

    p = add("download", cmd_download, "download files of one molecule")
    p.add_argument("molid", type=int)
    p.add_argument("names", nargs="+", help="file names, e.g. itp_aa pdb_aa_opt")
    p.add_argument("-o", "--output", default=".", help="directory (default: .)")
    p.add_argument("--hash", help="pin a topology version")
    p.add_argument("--ff", help="force field, e.g. 54A7")
    p.add_argument("--timeout", type=float, default=300.0)

    p = add("bundle", cmd_bundle, "download files of many molecules as one bundle")
    p.add_argument("names", nargs="+")
    p.add_argument("--molids", help="comma-separated molids")
    p.add_argument("--molids-from", help="file of molids (whitespace/comma separated)")
    p.add_argument("-o", "--output", default=".", help="directory to extract into")
    p.add_argument("--timeout", type=float, default=1800.0)

    p = add("search", cmd_search, "search molecules")
    p.add_argument("--inchi-key")
    p.add_argument("--inchi")
    p.add_argument("--smiles")
    p.add_argument("--common-name")
    p.add_argument("--formula")
    p.add_argument("--q", help="free text")
    p.add_argument("--filter", action="append", metavar="KEY=VALUE", help="any server filter")
    p.add_argument("--limit", type=int)
    p.add_argument("--all", action="store_true", help="walk every page")

    p = add("ifp", cmd_ifp, "a force field's interaction parameter file")
    p.add_argument("ff", help="e.g. 54A7")
    p.add_argument("--format", choices=["gxx", "g96"], help="default: the server's (g96)")
    p.add_argument("-o", "--output", help="write here instead of stdout")

    keys = sub.add_parser("keys", help="manage your API keys", parents=[common])
    keys_sub = keys.add_subparsers(dest="keys_command", metavar="ACTION", parser_class=_Parser)
    keys_sub.required = True
    p = keys_sub.add_parser("create", help="mint a key (shown once)", parents=[common])
    p.set_defaults(func=cmd_keys_create)
    p.add_argument("--name", help='a label for the key (default "atb cli")')
    p.add_argument("--scopes", help="comma-separated subset of your key's scopes")
    p.add_argument("--expires", help="days until it expires, e.g. 90 or 90d")
    p = keys_sub.add_parser("list", help="list keys", parents=[common])
    p.set_defaults(func=cmd_keys_list)
    p = keys_sub.add_parser("revoke", help="revoke a key", parents=[common])
    p.set_defaults(func=cmd_keys_revoke)
    p.add_argument("id")

    add("usage", cmd_usage, "today's counters and limits")
    return parser


# --------------------------------------------------------------------------- main


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help/--version exit 0; errors exit 2
        return int(exc.code or 0)

    try:
        atb = ATBClient(base_url=args.base_url, profile=args.profile)
    except ConfigurationError as exc:
        _emit_error("configuration", str(exc))
        return EXIT_USAGE
    if not atb._has_key:
        _emit_error(
            "configuration",
            "no API key: set ATB_API_KEY or add api_key to a profile in "
            "~/.config/atb/config.toml (it is never accepted on the command line)",
        )
        return EXIT_USAGE

    try:
        with atb:
            return int(args.func(atb, args))
    except UsageError as exc:
        _emit_error("usage", str(exc))
        return EXIT_USAGE
    except RateLimited as exc:
        _emit_error("rate-limited", str(exc), retry_after=exc.retry_after, problem=exc.problem)
        return EXIT_RATE_LIMITED
    except Timeout as exc:
        _emit_error("timeout", str(exc), job=exc.job, status=exc.status, pending=exc.pending)
        return EXIT_RUNNING
    except (MoleculeFailed, MoleculeRejected) as exc:
        _emit_error(
            "failed" if isinstance(exc, MoleculeFailed) else "rejected",
            str(exc),
            molid=exc.molid,
            status=exc.status,
        )
        return EXIT_FAILED
    except JobFailed as exc:
        _emit_error("job-failed", str(exc), job=exc.job)
        return EXIT_FAILED
    except ChemistryRejected as exc:
        _emit_error("rejected", str(exc), problem=exc.problem)
        return EXIT_FAILED
    except APIError as exc:
        _emit_error(
            exc.slug or f"http-{exc.status}", str(exc), status=exc.status, problem=exc.problem
        )
        return EXIT_ERROR
    except ATBError as exc:
        _emit_error(type(exc).__name__, str(exc))
        return EXIT_ERROR
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
