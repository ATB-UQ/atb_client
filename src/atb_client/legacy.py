"""Deprecated: the ``atb_api`` interface, on top of API v1.

For scripts written against ``from atb_api import API`` (the ``atb_api_public``
package). Change the import line and they keep running::

    from atb_client.legacy import API          # was: from atb_api import API

    api = API(api_token="<your key>")
    for molecule in api.Molecules.search(common_name="Pterostilbene", match_partial=False):
        print(molecule.inchi)
        molecule.download_file(fnme=f"{molecule.molid}.pdb", atb_format="pdb_aa")

What differs from the original, deliberately:

- The wire format is JSON; ``api_format`` is accepted and ignored (YAML and pickle
  are gone from v1). ``atb_format='yml'`` returns the file's text, not parsed YAML.
- Errors raise :mod:`atb_client.exceptions` (with the server's problem body) instead
  of ``urllib.error.HTTPError`` with the body drained.
- The token travels in an ``Authorization`` header, never the query string.

New code should use :class:`atb_client.ATBClient`. This module is named ``legacy`` so
a grep during the v0.1 sunset finds exactly the code still on the old interface.
"""

from __future__ import annotations

import json
import warnings
from typing import Any, Dict, Iterable, List, Optional, Union

from ._client import ATBClient
from .models import Molecule

__all__ = ["API", "ATB_FORMAT_TO_V1", "ATB_Mol", "v1_file_name"]

ATB_MOLID = Union[str, int]

#: ``atb_format`` values and v0.1 long file names → v1 file names (plan §6).
ATB_FORMAT_TO_V1: Dict[str, str] = {
    # the atb_api short vocabulary
    "pdb_aa": "pdb_aa_opt",
    "pdb_ua": "pdb_ua_opt",
    "mtb_aa": "mtb_aa",
    "mtb_ua": "mtb_ua",
    "itp_aa": "itp_aa",
    "itp_ua": "itp_ua",
    "lgf": "lgf",
    "yml": "yml",
    # v0.1 long names
    "pdb_allatom_optimised": "pdb_aa_opt",
    "pdb_allatom_unoptimised": "pdb_aa_unopt",
    "pdb_uniatom_optimised": "pdb_ua_opt",
    "pdb_uniatom_unoptimised": "pdb_ua_unopt",
    "g96_allatom_optimised": "g96_aa_opt",
    "g96_allatom_unoptimised": "g96_aa_unopt",
    "g96_uniatom_optimised": "g96_ua_opt",
    "g96_uniatom_unoptimised": "g96_ua_unopt",
    "graph.lgf": "lgf",
}
for _fmt in (
    "mtb",
    "mtb96",
    "top",
    "itp",
    "cns_top",
    "cns_param",
    "lammps",
    "amber_prmtop",
    "amber_crd",
    "pqr",
    "cif",
    "mol",
):
    ATB_FORMAT_TO_V1[f"{_fmt}_allatom"] = f"{_fmt}_aa"
    ATB_FORMAT_TO_V1[f"{_fmt}_uniatom"] = f"{_fmt}_ua"


def v1_file_name(name: str) -> str:
    """Map an ``atb_format`` or v0.1 file name to v1; unknown names pass through (the
    server accepts the v0.1 names as aliases)."""
    return ATB_FORMAT_TO_V1.get(name, name)


class ATB_Mol:
    """A bag of a molecule's fields with ``.download_file()``, as ``atb_api`` returned."""

    def __init__(self, api: API, molecule_dict: Dict[str, Any]) -> None:
        self.api = api
        for key, value in molecule_dict.items():
            setattr(self, key, value)

    def download_file(self, **kwargs: Any) -> Optional[str]:
        kwargs.pop("molid", None)
        return self.api.Molecules.download_file(molid=self.molid, **kwargs)

    def __repr__(self) -> str:
        fields = {k: v for k, v in self.__dict__.items() if k != "api"}
        return json.dumps(fields, indent=2, default=str)


def _as_dict(molecule: Molecule) -> Dict[str, Any]:
    return molecule.model_dump(mode="json")


class _Namespace:
    def __init__(self, api: API) -> None:
        self.api = api

    @property
    def _v1(self) -> ATBClient:
        return self.api.client


class Molecules(_Namespace):
    def search(self, **kwargs: Any) -> Any:
        """``GET /molecules`` over every page. ``return_type='molids'`` returns ints."""
        return_type = kwargs.pop("return_type", "molecules")
        match_partial = kwargs.pop("match_partial", None)
        for dropped in ("api_format", "api_token"):
            kwargs.pop(dropped, None)
        if match_partial:
            kwargs["match"] = "partial"
        molecules = list(self._v1.molecules.search(**kwargs).all())
        if return_type == "molids":
            return [m.molid for m in molecules]
        if return_type == "molecules":
            return [ATB_Mol(self.api, _as_dict(m)) for m in molecules]
        raise ValueError(f"unknown return_type: {return_type!r}")

    def molid(
        self,
        molid: Optional[ATB_MOLID] = None,
        molids: Optional[Iterable[ATB_MOLID]] = None,
        **kwargs: Any,
    ) -> Union[ATB_Mol, List[ATB_Mol]]:
        if (molid is None) == (molids is None):
            raise ValueError("provide exactly one of molid=X or molids=[X, Y]")
        if molid is not None:
            return ATB_Mol(self.api, _as_dict(self._v1.molecules.get(int(molid))))
        ids = [int(m) for m in molids]  # type: ignore[union-attr]
        found = list(self._v1.molecules.search(ids=ids).all())
        return [ATB_Mol(self.api, _as_dict(m)) for m in found]

    def molids(self, **kwargs: Any) -> List[ATB_Mol]:
        result = self.molid(**kwargs)
        return result if isinstance(result, list) else [result]

    def download_file(self, **kwargs: Any) -> Optional[str]:
        """``atb_format=`` (or v0.1 ``file=``) of ``molid=``; written to ``fnme=`` (returns
        ``None``) or returned as text. ``ffVersion`` maps to v1's ``ff``."""
        if "molid" not in kwargs:
            raise ValueError("download_file needs molid=")
        name = kwargs.get("atb_format") or kwargs.get("file")
        if not name:
            raise ValueError("download_file needs atb_format= (or file=)")
        ff = kwargs.get("ffVersion") or kwargs.get("ff_version")
        data = self._v1.files.download(
            int(kwargs["molid"]),
            v1_file_name(str(name)),
            # The old timeout was per socket read; a download may first need the
            # topology generated, so give it at least the v1 default.
            timeout=max(300.0, self.api.timeout_seconds or 0.0),
            ff=ff,
            hash=kwargs.get("hash"),
        )
        fnme = kwargs.get("fnme")
        if fnme:
            with open(str(fnme), "wb") as fh:
                fh.write(data)
            return None
        return data.decode("utf-8")

    def structure_search(self, method: str = "POST", **kwargs: Any) -> Dict[str, Any]:
        """``POST /structures/search``; returns ``{"matches": [...]}``."""
        for required in ("structure", "netcharge", "structure_format"):
            if required not in kwargs:
                raise ValueError(f"structure_search needs {required}=")
        matches = self._v1.structures.search(
            kwargs["structure"],
            format=kwargs["structure_format"],
            netcharge=kwargs["netcharge"],
            limit=kwargs.get("limit"),
            timeout=self.api.timeout_seconds,
        )
        return {"matches": [m.model_dump(mode="json") for m in matches]}

    def submit(self, request: str = "POST", **kwargs: Any) -> Dict[str, Any]:
        """``POST /molecules`` with ``pdb=`` or ``smiles=``; returns the molecule's fields.
        A duplicate raises :class:`atb_client.DuplicateMolecule` (``.molid``)."""
        given = [k for k in ("pdb", "smiles") if k in kwargs]
        if len(given) != 1:
            raise ValueError("provide exactly one of pdb= or smiles=")
        for required in ("netcharge", "public", "moltype"):
            if required not in kwargs:
                raise ValueError(f"submit needs {required}=")
        public = kwargs["public"]
        if isinstance(public, str):
            public = public.lower() in ("1", "true", "yes", "public")
        molecule = self._v1.molecules.submit(
            kwargs[given[0]],
            format=given[0],
            netcharge=int(kwargs["netcharge"]),
            public=bool(public),
            moltype=kwargs["moltype"],
            client_reference=kwargs.get("client_reference"),
        )
        return _as_dict(molecule)


def _molids_list(value: Any) -> List[int]:
    if isinstance(value, str):
        return [int(v) for v in value.split(",") if v.strip()]
    return [int(v) for v in value]


class RMSD(_Namespace):
    """v1 answers every RMSD call with the whole matrix; ``align`` and ``matrix``
    both return :class:`~atb_client.models.RMSDResult` fields as a dict (``rmsd`` is
    the two-structure value, ``rmsd_matrix`` the rest)."""

    def _call(self, kwargs: Dict[str, Any]) -> Any:
        if "molids" in kwargs:
            result = self._v1.structures.rmsd(molids=_molids_list(kwargs["molids"]))
        elif "reference_pdb" in kwargs and "pdb_0" in kwargs:
            others = [kwargs[k] for k in sorted(kwargs) if k.startswith("pdb_")]
            result = self._v1.structures.rmsd(structures=[kwargs["reference_pdb"], *others])
        else:
            raise ValueError("provide molids= or reference_pdb= and pdb_0=")
        return result.model_dump(mode="json")

    def align(self, **kwargs: Any) -> Any:
        return self._call(kwargs)

    def matrix(self, **kwargs: Any) -> Any:
        return self._call(kwargs)


class API:
    """Deprecated drop-in for ``atb_api.API``. Use :class:`atb_client.ATBClient`."""

    def __init__(
        self,
        host: str = "https://atb.uq.edu.au",
        api_token: Optional[str] = None,
        internal_token: Optional[str] = None,
        debug: bool = False,
        timeout: int = 60,
        api_format: str = "json",
        debug_stream: Any = None,
        maximum_attempts: int = 5,
    ) -> None:
        warnings.warn(
            "atb_client.legacy.API is deprecated; use atb_client.ATBClient "
            "(see the atb-client README, 'Migrating from atb_api')",
            DeprecationWarning,
            stacklevel=2,
        )
        if api_format != "json":
            warnings.warn(
                f"api_format={api_format!r} is ignored: API v1 speaks JSON only",
                DeprecationWarning,
                stacklevel=2,
            )
        host = host.rstrip("/")
        base_url = host if host.endswith("/api/v1") else host + "/api/v1"
        headers = {"X-ATB-Internal-Token": internal_token} if internal_token else None
        self.host = host
        self.api_token = api_token
        self.debug = debug
        self.timeout = timeout
        self.timeout_seconds = float(timeout) if timeout else None
        self.api_format = "json"
        self.client = ATBClient(
            api_key=api_token,
            base_url=base_url,
            timeout=timeout,
            max_attempts=maximum_attempts,
            headers=headers,
        )
        self.Molecules = Molecules(self)
        self.RMSD = RMSD(self)

    def close(self) -> None:
        self.client.close()
