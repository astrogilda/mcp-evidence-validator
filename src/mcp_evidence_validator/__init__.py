"""MCP Evidence Validator - declared-vs-observed evidence for MCP servers.

Validates what an MCP server *declares* against what it *actually does* and
produces a tamper-evident SHA-256 hash-chain ledger for auditors.

Public API:
    fingerprint(value)          -> canonical SHA-256 fingerprint
    Ledger                      -> append-only hash chain with
                                   head() and verify(expected_head)
    validate_batch(declared, observed) -> (findings, summary)
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version

from .fingerprint import canonical_json, fingerprint, fingerprint_matches
from .ledger import GENESIS, UNANCHORED, Ledger
from .validator import validate_batch

try:  # installed distribution metadata is the single source of truth
    __version__ = _distribution_version("mcp-evidence-validator")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.4.1"
__all__ = [
    "canonical_json",
    "fingerprint",
    "fingerprint_matches",
    "GENESIS",
    "UNANCHORED",
    "Ledger",
    "validate_batch",
    "__version__",
]
