"""``client.bundles`` — many molecules' files as one zip (``POST /bundles``, ≤ 50)."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .. import _ops
from .._base import Resource, operation
from .._transport import request

DEFAULT_BUNDLE_TIMEOUT = 1800.0
MAX_BUNDLE = 50


def _link_of(result: Any) -> str:
    """Pull the download link out of a job result or plain string."""
    if isinstance(result, dict):
        for key in ("url", "href", "download_url", "location"):
            if result.get(key):
                return str(result[key])
        links = result.get("links")
        if isinstance(links, dict) and links.get("download"):
            return str(links["download"])
    if isinstance(result, str):
        return result
    raise ValueError(f"bundle job result carries no download link: {result!r}")


def _relative(link: str, base_url: str) -> str:
    """Make a server link relative to ``base_url`` (``/api/v1/x`` → ``x``)."""
    if link.startswith(base_url):
        return link[len(base_url) :].lstrip("/")
    prefix = "/" + base_url.split("://", 1)[-1].split("/", 1)[-1].strip("/") + "/"
    if link.startswith(prefix):
        return link[len(prefix) :]
    return link.lstrip("/")


class Bundles(Resource):
    """``client.bundles`` — many molecules' files as one zip."""

    @operation
    def download(
        self,
        molids: Iterable[int],
        names: Iterable[str],
        *,
        into: Any = None,
        path: Any = None,
        hash: Optional[Dict[int, str]] = None,
        timeout: Optional[float] = DEFAULT_BUNDLE_TIMEOUT,
    ):
        """Build one zip of ``names`` for each of ``molids`` and fetch it.

        ``into``: extract into this directory (one sub-directory per molecule) and
        return it. ``path``: keep the zip at this path and return it. Neither: return
        the zip's bytes. ``hash`` pins topology versions per molid.
        """
        molid_list: List[int] = [int(m) for m in molids]
        if not 0 < len(molid_list) <= MAX_BUNDLE:
            raise ValueError(f"a bundle holds 1 to {MAX_BUNDLE} molecules; split larger sets")
        body: Dict[str, Any] = {"molids": molid_list, "names": list(names)}
        if hash:
            body["hash"] = {str(k): v for k, v in hash.items()}

        deadline = _ops.Deadline(timeout)
        tmp_dir = None
        if path is not None:
            zip_path: Optional[Path] = Path(path)
        elif into is not None:
            tmp_dir = tempfile.mkdtemp(prefix="atb-bundle-")
            zip_path = Path(tmp_dir) / "bundle.zip"
        else:
            zip_path = None

        # The POST is not streamed: its answer is normally a job or a link, and a
        # bundle small enough to be built within ``wait`` is small enough to hold.
        kind, value = yield from _ops.call_with_wait(
            self._client, "POST", "bundles", deadline=deadline, json=body
        )
        if kind == "response" and value.headers.get("Content-Type", "").startswith(
            "application/zip"
        ):
            payload = _ops._download_result(value, None)
            if zip_path is not None:
                zip_path.parent.mkdir(parents=True, exist_ok=True)
                zip_path.write_bytes(payload)
                payload = zip_path
        else:
            result = value.json() if kind == "response" else value.result_
            link = _relative(_link_of(result), self._client.base_url)
            response = yield from request(
                self._client, "GET", link, stream_to=zip_path, default_name="bundle.zip"
            )
            payload = _ops._download_result(response, zip_path)

        if into is None:
            return payload
        target = Path(into)
        target.mkdir(parents=True, exist_ok=True)
        source = io.BytesIO(payload) if isinstance(payload, bytes) else payload
        with zipfile.ZipFile(source) as archive:
            for member in archive.namelist():
                resolved = (target / member).resolve()
                if not str(resolved).startswith(str(target.resolve())):
                    raise ValueError(f"refusing to extract {member!r} outside {target}")
            archive.extractall(target)
        if tmp_dir is not None:
            Path(payload).unlink()
            try:
                Path(tmp_dir).rmdir()
            except OSError:
                pass
        return target
