"""``client.files`` and ``molecule.files`` — list and download a molecule's outputs.

File names are the v1 vocabulary ``<format>_<atoms>[_<geometry>]`` — ``itp_aa``,
``pdb_aa_opt``, ``mtb_ua``, ``lgf``, ``qm1_log`` ... (plan §6). The v0.1 names
(``itp_allatom``, ``pdb_allatom_optimised``) are accepted by the server as aliases.

Restricted files (the QM logs, ``qm_data``, ``atb_log``) need a partner or admin
account or a service key; for anyone else they are left out of ``list()`` and
``download()`` raises :class:`PermissionDenied` (``file-restricted``).

Until the server generates on demand (WP3), downloading a topology file that is not
cached raises :class:`GenerationRequired` (409); afterwards the same call waits for
the generation job (the server's ``202``) up to ``timeout``.
"""

from __future__ import annotations

from typing import Any, Optional

from .. import _ops
from .._base import Resource, operation
from .._transport import request
from ..exceptions import MoleculeNotFound
from ..models import FileList

DEFAULT_DOWNLOAD_TIMEOUT = 300.0


def _list(client: Any, molid: int, hash: Optional[str], ff: Optional[str]):
    response = yield from request(
        client,
        "GET",
        f"molecules/{int(molid)}/files",
        params={"hash": hash, "ff": ff},
        not_found=MoleculeNotFound,
    )
    return FileList.model_validate(response.json())


def _download(
    client: Any,
    molid: int,
    name: str,
    path: Any,
    timeout: Optional[float],
    hash: Optional[str],
    ff: Optional[str],
):
    return (
        yield from _ops.download(
            client,
            f"molecules/{int(molid)}/files/{name}",
            target=path,
            default_name=name,
            params={"hash": hash, "ff": ff},
            timeout=timeout,
        )
    )


class Files(Resource):
    @operation
    def list(self, molid: int, *, hash: Optional[str] = None, ff: Optional[str] = None):
        """``GET /molecules/{molid}/files`` → :class:`FileList` (iterable over its
        :class:`FileEntry` items) for the current topology, or the one pinned by
        ``hash``, of force field ``ff`` (default: the server's)."""
        return (yield from _list(self._client, molid, hash, ff))

    @operation
    def download(
        self,
        molid: int,
        name: str,
        path: Any = None,
        *,
        timeout: Optional[float] = DEFAULT_DOWNLOAD_TIMEOUT,
        hash: Optional[str] = None,
        ff: Optional[str] = None,
    ):
        """``GET /molecules/{molid}/files/{name}``.

        With ``path`` (a file, or an existing directory to write into under the
        server's file name) the body is streamed to disk atomically and the
        :class:`~pathlib.Path` returned; without it the bytes are returned. A file
        that must be generated first is waited for (the 202/job dance) up to
        ``timeout`` seconds, then :class:`Timeout`; the WP2 server instead answers
        :class:`GenerationRequired`. A pinned ``hash`` that is no longer stored raises
        :class:`TopologyVersionGone`. A merged duplicate molid is followed to its
        canonical molecule.
        """
        return (yield from _download(self._client, molid, name, path, timeout, hash, ff))


class MoleculeFiles:
    """``molecule.files``: the :class:`Files` calls with the molid filled in."""

    def __init__(self, client: Any, molid: int) -> None:
        self._client = client
        self.molid = molid

    @operation
    def list(self, *, hash: Optional[str] = None, ff: Optional[str] = None):
        return (yield from _list(self._client, self.molid, hash, ff))

    @operation
    def download(
        self,
        name: str,
        path: Any = None,
        *,
        timeout: Optional[float] = DEFAULT_DOWNLOAD_TIMEOUT,
        hash: Optional[str] = None,
        ff: Optional[str] = None,
    ):
        """See :meth:`Files.download`."""
        return (yield from _download(self._client, self.molid, name, path, timeout, hash, ff))

    def __repr__(self) -> str:
        return f"<MoleculeFiles molid={self.molid}>"
