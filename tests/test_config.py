from __future__ import annotations

import pytest

from atb_client import ATBClient, ConfigurationError
from atb_client._config import DEFAULT_BASE_URL, _loads_minimal, resolve

CONFIG = """
# ATB client configuration
[profiles.default]
api_key = "atb_default_key"   # the everyday key

[profiles.staging]
api_key = 'atb_staging_key'
base_url = "https://staging.example.org/api/v1"
timeout = 60
"""


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    monkeypatch.setenv("ATB_CONFIG", str(path))
    return path


def test_defaults_without_anything():
    cfg = resolve()
    assert cfg.api_key is None and cfg.base_url == DEFAULT_BASE_URL and cfg.source == "none"


def test_default_profile(config_file):
    cfg = resolve()
    assert (cfg.api_key, cfg.source, cfg.profile) == ("atb_default_key", "profile", "default")


def test_named_profile(config_file):
    cfg = resolve(profile="staging")
    assert cfg.api_key == "atb_staging_key"
    assert cfg.base_url == "https://staging.example.org/api/v1"
    assert cfg.timeout == 60


def test_profile_from_env(config_file, monkeypatch):
    monkeypatch.setenv("ATB_PROFILE", "staging")
    assert resolve().api_key == "atb_staging_key"


def test_env_beats_profile_and_argument_beats_env(config_file, monkeypatch):
    monkeypatch.setenv("ATB_API_KEY", "atb_env_key")
    monkeypatch.setenv("ATB_API_URL", "https://env.example.org/api/v1/")
    cfg = resolve()
    assert (cfg.api_key, cfg.source) == ("atb_env_key", "env")
    assert cfg.base_url == "https://env.example.org/api/v1"
    cfg = resolve(api_key="atb_arg", base_url="https://arg.example.org/api/v1")
    assert (cfg.api_key, cfg.base_url) == ("atb_arg", "https://arg.example.org/api/v1")


def test_unknown_explicit_profile(config_file):
    with pytest.raises(ConfigurationError):
        resolve(profile="nope")


def test_plain_http_refused_except_loopback():
    with pytest.raises(ConfigurationError):
        resolve(api_key="k", base_url="http://atb.uq.edu.au/api/v1")
    assert resolve(base_url="http://127.0.0.1:8001/api/v1").base_url.startswith("http://127")
    assert resolve(base_url="http://localhost:8001/api/v1").base_url.startswith("http://local")


def test_client_uses_profile(config_file):
    atb = ATBClient(profile="staging")
    assert atb.base_url == "https://staging.example.org/api/v1"
    assert atb._http.headers["Authorization"] == "Bearer atb_staging_key"
    assert atb._http.timeout.read == 60


def test_minimal_parser_matches_tomllib():
    """The 3.9/3.10 fallback reads the documented subset exactly as tomllib does."""
    parsed = _loads_minimal(CONFIG)
    assert parsed == {"profiles": {
        "default": {"api_key": "atb_default_key"},
        "staging": {"api_key": "atb_staging_key",
                    "base_url": "https://staging.example.org/api/v1", "timeout": 60},
    }}
    try:
        import tomllib
    except ImportError:  # pragma: no cover - 3.9/3.10
        return
    assert parsed == tomllib.loads(CONFIG)


def test_minimal_parser_edge_cases():
    parsed = _loads_minimal('[profiles."odd name"]\nflag = true\nx = 1.5\ns = "a#b\\"c"\n')
    assert parsed == {"profiles": {"odd name": {"flag": True, "x": 1.5, "s": 'a#b"c'}}}
    with pytest.raises(ConfigurationError):
        _loads_minimal("[profiles.a]\nkeys = [1, 2]\n")
    with pytest.raises(ConfigurationError):
        _loads_minimal("not toml at all\n")
