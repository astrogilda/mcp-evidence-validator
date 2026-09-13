# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[SemVer](https://semver.org/).

## [Unreleased]

### Added
- `examples/filesystem-server-declared.json` and `examples/filesystem-server-observed.json`: a declared-vs-observed pair captured from a real MCP server, `@modelcontextprotocol/server-filesystem`, declaring `2026.1.14` and observing `2026.8.31`. One finding: `read_media_file`'s contract changed between the two releases (closes [#17](https://github.com/narko4u/mcp-evidence-validator/issues/17)).
- `examples/capture_mcp_server.py`: starts a published MCP server over stdio, records `tools/list` and real `tools/call` replies, and writes the pair. The raw replies are committed under `examples/captures/`.
- `tests/test_filesystem_example.py`: recomputes every contract hash in the pair from the raw captures, runs the pair through the validator and the CLI, and pins what the contract does not cover (`outputSchema` changed in this example while `input_schema` did not).

### Changed
- README: covered server types listed with their provenance; the project-status note no longer claims every example is fictional, since one is now a real capture.

## [0.3.0] - 2026-09-13

### Fixed
- A self-describing ledger verified three forgeries clean, all of which now fail: a chain replayed over a rewritten record, a truncated chain that dropped the last block (and with it a high-severity finding), and a chain whose published `prev_hash` and `index` were falsified. `verify` now requires the head digest recorded outside the ledger and checks every published field against the chain walk. Reported by [@astrogilda](https://github.com/astrogilda) in [#20](https://github.com/narko4u/mcp-evidence-validator/issues/20); fixed in [#21](https://github.com/narko4u/mcp-evidence-validator/pull/21).

### Security
- The README claim that a changed record "invalidates every record after it" held only for a naive edit. It is replaced by the accuracy requirement: a chain read on its own proves ordering to whoever holds the file and nothing to anyone else. See the tamper-evidence note in `SECURITY.md` and `Ledger.verify(UNANCHORED)`.

### Changed
- **Breaking.** `verify` requires `--expected-head`, the head digest recorded outside the ledger. A ledger that does not reach that head is refused.
- **Breaking.** `Ledger.verify` takes `expected_head` as an argument. Pass the new `UNANCHORED` constant for chain self-consistency alone.
- `Ledger.verify` compares each block's published `prev_hash` and `index` against the chain walk and reports every disagreement, instead of recomputing both and comparing only `hash`.
- `Ledger.verify` reports every problem it finds rather than returning at the first hash mismatch.

### Added
- `Ledger.head()`, and `validate --head-out PATH` to write that digest to a separate file. `validate` also prints it to stderr.
- `tests/test_ledger_forgery.py`: a full-rewrite forgery, a tail truncation that removes a high-severity finding, and a ledger whose published `prev_hash` and `index` are falsified. Each verified clean before this change.

## [0.2.1] - 2026-08-18

### Added
- Release workflow with sigstore keyless signing (SHA256SUMS + cosign signature)
- OpenSSF baseline level 2 readiness: MAINTAINERS.md, threat assessment, DCO check, least-privilege CI permissions

## [0.2.0] - 2026-08-17

### Added
- Installable package (`pyproject.toml`, src/ layout, `mcp-ev-validate` console script)
- `validate` subcommand: compare a declared manifest against observed runtime records
- `verify` subcommand: replay the SHA-256 hash chain and report any corruption
- Test suite (pytest, 20 tests) covering fingerprinting, ledger chaining, tamper detection, and CLI entry points
- GitHub Actions CI (Python 3.10, 3.11, 3.12)
- Security policy (SECURITY.md) with private reporting and 90-day coordinated disclosure
- Contributing guide and Code of Conduct

### Security
- Ledger integrity depends on SHA-256 over canonical JSON; tampering with any
  prior record invalidates all subsequent records (verified by the test suite).
- No runtime dependencies; no secrets or credentials are stored in the ledger.

## [0.1.0] - 2026-08-01

### Added
- Prototype: declared-vs-observed evidence model (declarations, contracts, observations, findings)
- Prototype hash-chain ledger (`prototype/ledger.py`, `prototype/fingerprint.py`)
- Design document (docs/DESIGN.md)
