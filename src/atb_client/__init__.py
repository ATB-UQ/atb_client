"""Python client for the Automated Topology Builder (ATB) API v1.

from atb_client import ATBClient
atb = ATBClient()                       # ATB_API_KEY, or ~/.config/atb/config.toml
mol = atb.molecules.get(21)
mol.files.download("itp_aa", "ethanol.itp")
"""

from ._client import AsyncATBClient, ATBClient
from ._version import __version__
from .exceptions import (
    APIError,
    ATBError,
    AuthenticationError,
    ChemistryRejected,
    ConfigurationError,
    Conflict,
    DuplicateMolecule,
    GenerationRequired,
    JobFailed,
    MoleculeFailed,
    MoleculeMoved,
    MoleculeNotFound,
    MoleculeRejected,
    NetworkError,
    NotFound,
    PayloadTooLarge,
    PermissionDenied,
    RateLimited,
    ServerError,
    ServiceUnavailable,
    Timeout,
    TopologyVersionGone,
    ValidationError,
)

__all__ = [
    "APIError",
    "ATBClient",
    "ATBError",
    "AsyncATBClient",
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
    "ServerError",
    "ServiceUnavailable",
    "Timeout",
    "TopologyVersionGone",
    "ValidationError",
    "__version__",
]
