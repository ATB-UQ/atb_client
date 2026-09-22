"""Where the key and the URL come from.

Resolution order, first hit wins, for each of ``api_key`` and ``base_url``:

1. the explicit constructor argument;
2. the environment: ``ATB_API_KEY``, ``ATB_API_URL``;
3. the selected profile in the config file;
4. for ``base_url`` only, the default ``https://atb.uq.edu.au/api/v1``.

The profile is the ``profile`` argument, else ``ATB_PROFILE``, else ``default``. The
config file is ``ATB_CONFIG`` if set, else ``$XDG_CONFIG_HOME/atb/config.toml``, else
``~/.config/atb/config.toml``::

    [profiles.default]
    api_key = "atb_ab12cd34_..."

    [profiles.staging]
    api_key = "atb_..."
    base_url = "https://atb-staging.example.org/api/v1"
    timeout = 60

On Python 3.11+ the file is read with :mod:`tomllib`. On 3.9/3.10, where the package
may not depend on ``tomli``, a minimal reader handles the subset a profile needs —
``[table.headers]``, ``key = value`` with basic/literal strings, integers, floats and
booleans, and ``#`` comments — and raises :class:`ConfigurationError` on anything else
rather than guessing.

The key is never taken from a command line.
"""

from __future__ import annotations

import ipaddress
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from .exceptions import ConfigurationError

DEFAULT_BASE_URL = "https://atb.uq.edu.au/api/v1"
DEFAULT_PROFILE = "default"


def config_path() -> Path:
    explicit = os.environ.get("ATB_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "atb" / "config.toml"


# --------------------------------------------------------------------------- TOML


def _loads(text: str) -> Dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib

        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigurationError(f"invalid config file: {exc}") from exc
    return _loads_minimal(text)


_BARE_KEY = r"[A-Za-z0-9_-]+"
_KEY = rf'(?:{_BARE_KEY}|"[^"]*")'
_HEADER = re.compile(rf"^\[\s*({_KEY}(?:\s*\.\s*{_KEY})*)\s*\]$")
_ASSIGN = re.compile(rf"^({_KEY})\s*=\s*(.+)$")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _key(part: str) -> str:
    part = part.strip()
    return part[1:-1] if part.startswith('"') else part


def _strip_comment(value: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(value):
        if quote:
            if ch == quote and not (quote == '"' and value[i - 1] == "\\"):
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#":
            break
        out.append(ch)
    return "".join(out).strip()


def _value(raw: str, lineno: int) -> Any:
    raw = _strip_comment(raw)
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        body, out, i = raw[1:-1], [], 0
        while i < len(body):
            if body[i] == "\\" and i + 1 < len(body) and body[i + 1] in _ESCAPES:
                out.append(_ESCAPES[body[i + 1]])
                i += 2
            else:
                out.append(body[i])
                i += 1
        return "".join(out)
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw.replace("_", ""))
    except ValueError:
        pass
    try:
        return float(raw.replace("_", ""))
    except ValueError:
        pass
    raise ConfigurationError(
        f"config file line {lineno}: unsupported value {raw!r} (Python < 3.11 reads only "
        "strings, numbers and booleans)"
    )


def _loads_minimal(text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    table = root
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        header = _HEADER.match(_strip_comment(stripped))
        if header:
            table = root
            for part in re.findall(_KEY, header.group(1)):
                table = table.setdefault(_key(part), {})
                if not isinstance(table, dict):
                    raise ConfigurationError(f"config file line {lineno}: {part!r} is not a table")
            continue
        assign = _ASSIGN.match(stripped)
        if assign:
            table[_key(assign.group(1))] = _value(assign.group(2), lineno)
            continue
        raise ConfigurationError(f"config file line {lineno}: cannot parse {stripped!r}")
    return root


def load_config_file(path: Optional[Path] = None) -> Dict[str, Any]:
    path = path or config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigurationError(f"cannot read {path}: {exc}") from exc
    return _loads(text)


# --------------------------------------------------------------------------- resolution


@dataclass
class ResolvedConfig:
    api_key: Optional[str]
    base_url: str
    timeout: Optional[float]
    profile: str
    source: str  # where the key came from: argument | env | profile | none


def _check_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.netloc:
        raise ConfigurationError(f"base_url must be an absolute http(s) URL, got {url!r}")
    if parts.scheme == "http":
        host = parts.hostname or ""
        loopback = host == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if not loopback:
            raise ConfigurationError(
                f"refusing to send an API key over plain http to {host!r}; use https "
                "(plain http is allowed for localhost only)"
            )
    return url.rstrip("/")


def resolve(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    profile: Optional[str] = None,
    *,
    config_file: Optional[Path] = None,
) -> ResolvedConfig:
    explicit_profile = profile or os.environ.get("ATB_PROFILE")
    profile_name = explicit_profile or DEFAULT_PROFILE
    data = load_config_file(config_file)
    profiles = data.get("profiles", {}) if isinstance(data, dict) else {}
    section = profiles.get(profile_name)
    if section is None:
        if explicit_profile:
            raise ConfigurationError(
                f"profile {profile_name!r} not found in {config_file or config_path()}"
            )
        section = {}
    if not isinstance(section, dict):
        raise ConfigurationError(f"[profiles.{profile_name}] must be a table")

    if api_key:
        key, source = api_key, "argument"
    elif os.environ.get("ATB_API_KEY"):
        key, source = os.environ["ATB_API_KEY"], "env"
    elif section.get("api_key"):
        key, source = str(section["api_key"]), "profile"
    else:
        key, source = None, "none"

    url = base_url or os.environ.get("ATB_API_URL") or section.get("base_url") or DEFAULT_BASE_URL
    timeout = section.get("timeout")
    return ResolvedConfig(
        api_key=key.strip() if key else None,
        base_url=_check_url(str(url)),
        timeout=float(timeout) if timeout is not None else None,
        profile=profile_name,
        source=source,
    )
