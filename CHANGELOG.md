# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[SemVer](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-09-13

### Added
- **Contract recipes.** A contract hash now travels with the recipe that produced it: a declaration states `contract_recipe`, an observation may state the recipe its `contract_hash` was computed under, the report's `summary` lists every recipe in play, and `verify` prints them for a ledger. Recipe 2 folds the declared output schema and the tool's MCP annotation hints into the contract; recipe 1 is the original four fields (`name`, `description`, `input_schema`, `permissions`).
- A `recipe_mismatch` check: an observation whose recipe differs from the declaration's is refused rather than reported as drift, because two hashes computed different ways are not evidence of change in either direction.
- `examples/rebuild_pair.py`: re-derives a committed example pair, and the per-call hashes in its capture, from the raw `tools/list` replies. No Node.js, no network.
- `NOTICE`: attribution for the Apache-2.0 licence.
- `examples/filesystem-server-declared.json` and `examples/filesystem-server-observed.json`: a declared-vs-observed pair captured from a real MCP server, `@modelcontextprotocol/server-filesystem`, declaring `2026.1.14` and observing `2026.8.31` (closes [#17](https://github.com/narko4u/mcp-evidence-validator/issues/17)).
- `examples/capture_mcp_server.py`: starts a published MCP server over stdio, records `tools/list` and real `tools/call` replies, and writes the pair. The raw replies are committed under `examples/captures/`.
- `tests/test_filesystem_example.py`: recomputes every contract hash in the pair from the raw captures, runs the pair through the validator and the CLI, and asserts the pair is exactly what the captures derive.
- Tests: legacy declarations still hash under recipe 1, recipe 2 covers an output-schema-only and an annotation-only change, recipe precedence, rejection of unknown recipes, recipe mismatch, and the recipe-1 blindness that motivated the change — pinned rather than deleted.

### Changed
- **Recipe 2 is the default for new declarations.** A declaration that states no recipe keeps hashing under recipe 1, so every ledger issued before this release still verifies and nothing already published changes meaning.
- Ledger format `0.2` → `0.3`. Additive: block shape, the chain, and the dump/load round trip are unchanged, and a `0.2` ledger still loads and still verifies.
- The filesystem example pair is hashed under recipe 2, with every contract hash re-derived from the raw captures. It reports **three** findings where it previously reported one: the `2026.8.31` release added an `openWorldHint` annotation to every tool it serves, which moved the contracts of `read_text_file` and `get_file_info` while leaving them byte-identical under recipe 1.
- README: example table gained a recipe column; the filesystem example's finding count and its cause are stated; new "Contract recipes" section; owner and related-work context.
- `docs/DESIGN.md`: new §2.2.1 on recipes and migration, a recipe-mismatch row in the check table, ledger self-description notes, and component paths corrected from the prototype layout to `src/`.

### Fixed
- The contract no longer misses a server that changes only what it returns, or only the hints it publishes about its own side effects — the gap reported in [#23](https://github.com/narko4u/mcp-evidence-validator/issues/23).

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
