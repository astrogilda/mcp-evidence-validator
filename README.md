# MCP Evidence Validator

[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14122/badge)](https://www.bestpractices.dev/projects/14122)
[![OpenSSF Baseline](https://www.bestpractices.dev/projects/14122/baseline)](https://www.bestpractices.dev/projects/14122)

Validate what an MCP server *declares* against what it *actually does*, and produce a tamper-evident evidence record you can hand to an auditor.

**Status:** v0.4 (installable)  ·  **License:** Apache-2.0  ·  **Language:** Python 3.10+ (stdlib only, zero dependencies)

**Built by [Empire Labs Pty Ltd](https://empirelabs.com.au)** and published as part of the Empire Stack — the evidence layer for agent actions. Related public work:

- [witnessos](https://github.com/narko4u/witnessos) — credential-brokered enforcement and cryptographic evidence for agent actions; the evidence-grade ladder these checks descend from (E0 Declared → E1 Observed → E2 Enforced → E3 Corroborated → E4 Anchored).
- [evidence-record-spec](https://github.com/narko4u/evidence-record-spec) — portable, evidence-grade record format for agent actions.

---

## Why

Model Context Protocol (MCP) is the industry standard for connecting AI agents to tools and data. It is now governed by the Agentic AI Foundation (AAIF) under the Linux Foundation, with 97M+ monthly SDK downloads and 10,000+ active public servers.

But the protocol leaves the *evidence* problem open:

- A server declares tool schemas and permissions, but nothing verifies those declarations against observed runtime behaviour.
- An annotation can be accurate at declaration time and silently stale minutes later, when the contract it was bound to mutates underneath it.
- MCP has already seen the first malicious server (Sept 2025), CVE-2025-6514 (CVSS 9.6, RCE), and a hosting-platform breach affecting 3,000+ downstream applications.

The **declared-vs-observed gap** is the measurement finding that matters. This validator is a reference implementation for closing it.

## What it does

1. **Captures declarations** - the tool schemas, permissions, and annotations an MCP server publishes.
2. **Observes reality** - the tool invocations, argument shapes, and contract hashes seen at runtime.
3. **Checks the gap** - declared annotation still bound? Contract mutated since declaration? Privilege use inside declared scope?
4. **Produces an anchored evidence ledger** - every check result is committed to a SHA-256 hash chain, and `validate` prints the head digest of that chain. Record the head somewhere the ledger file's holder cannot edit, and `verify` refuses any ledger that does not reach it. A chain read on its own proves ordering to whoever holds the file and nothing to anyone else: an editor who can change a record can replay the chain over the change, drop the last block, or publish any `prev_hash` and `index` they like.

## Install

```bash
pip install mcp-evidence-validator      # from PyPI once published
# or from source:
git clone https://github.com/narko4u/mcp-evidence-validator.git
cd mcp-evidence-validator
pip install .
```

No dependencies — Python 3.10+ standard library only.

## Quick start

After installing from source above, run these commands from the repository root
so the bundled example files are available.

```bash
# Compare a declared manifest against observed runtime records, and write the
# head digest of the resulting ledger to a separate file
mcp-ev-validate validate --declared examples/fictional-server-declared.json --observed examples/fictional-server-observed.json --out evidence.json --head-out evidence.head

# Audit a ledger later, against the head you kept elsewhere
mcp-ev-validate verify --ledger evidence.json --expected-head "$(cat evidence.head)"
```

`--expected-head` is required. Keep the head where the ledger's holder cannot reach it: a signature, a commit in another repository, a transparency log entry, or a line in the auditor's own notes. Both files land in the current directory, so the commands run unchanged on Windows.

The `validate` command prints a JSON report. Its `summary` contains:

```json
{
  "declared_tools": 2,
  "observations": 3,
  "findings": 2,
  "contract_recipes": ["1"],
  "checks": [
    "bound_unmutated",
    "contract_mutated",
    "scope_violation",
    "recipe_mismatch"
  ]
}
```

`contract_recipes` names the recipe each contract hash was computed under — `["1"]` here because the constructed example predates the current recipe and does not state one, so `validate` also notes that on stderr. See [Contract recipes](#contract-recipes).

The report's `findings` array describes the deliberately undeclared `admin_token` argument in observation 2 and the changed contract in observation 3. Validation exits **0** when the report is produced, even when it contains findings; inspect the report to assess the observed behaviour.

Record the head somewhere the ledger file's holder cannot edit. `verify` checks the chain against that head and, for this example, exits **0** with:

```text
ledger intact: 3 blocks, chain verified against the expected head
block types: {"declaration": 1, "observation_batch": 1, "report": 1}
contract recipes: 1
```

The `contract recipes:` line is the verification being explicit about how the evidence it just checked was produced: a contract hash means nothing without the recipe that produced it.

`verify` exits **1** when the ledger does not reach the expected head, and **2** when it is invoked without one. It checks the ledger against the head you pass in, so it does not vouch for the observations being free of findings: a chain read on its own proves ordering to whoever holds the file, and nothing to anyone else.

Or run as a module: `python -m mcp_evidence_validator validate --declared ...`

Output is a machine-readable evidence record with a `chain` of hash-linked entries plus a human-readable `findings` summary. The `verify` subcommand replays the chain, checks the published `prev_hash` and `index` of every block against that walk, and compares the head it reaches to the one you pass in. Try editing `evidence.json` and re-verifying against the original head: the edit is refused.

## Covered server types

| Example | Server | Declared | Observed | Recipe | Shows |
|---------|--------|----------|----------|--------|-------|
| `examples/fictional-server-*.json` | fictional weather server | — | — | 1 (legacy) | all three checks against constructed data |
| `examples/filesystem-server-*.json` | `@modelcontextprotocol/server-filesystem` | 2026.1.14 | 2026.8.31 | 2 | three real contract mutations between two releases, two of which recipe 1 could not see |

The second pair is a real capture, not a constructed one:

```bash
mcp-ev-validate validate --declared examples/filesystem-server-declared.json --observed examples/filesystem-server-observed.json --out fs-evidence.json --head-out fs-evidence.head
```

It reports three findings, one per observed call. `read_media_file`'s contract moved between the two versions in a way that matters to a caller: the description went from "Read an image or audio file" to reading *any* file, "returned as an embedded resource" when it is neither image nor audio, and the output schema gained an `anyOf` branch whose second case is a `resource` carrying a `blob`, while the first case lost `blob` from its `type` enum. A client that bound a handler to the earlier output shape at declaration time is now holding a stale annotation; the check says so, and the two hashes it prints are the two real contracts.

The other two, `read_text_file` and `get_file_info`, are the more interesting findings: the `2026.8.31` release added an `openWorldHint` annotation to every tool it serves, and those two changed *nothing else*. Under recipe 1 they were byte-identical and reported healthy. Under recipe 2 their contracts moved, correctly, because what a tool declares about its own side effects is part of what it declares.

The three calls in the observed file were made against the running server and every `contract_hash` is the validator's own fingerprint over what that server served. The raw replies are committed in `examples/captures/` and `tests/test_filesystem_example.py` recomputes each hash from them, so the pair cannot silently drift from its evidence. To recapture:

```bash
python3 examples/capture_mcp_server.py \
    --package @modelcontextprotocol/server-filesystem \
    --declared-version 2026.1.14 --observed-version 2026.8.31 \
    --root /tmp/mcp-capture-root --label filesystem-server
```

That needs Node.js (`npx`) and registry access. The committed files are static, so neither the tests nor the validator need either.

To rebuild the pair from the committed captures — which is how a pair is migrated to a new contract recipe, with no Node.js and no network:

```bash
python3 examples/rebuild_pair.py --recipe 2     # rewrite the pair and its derived hashes
python3 examples/rebuild_pair.py --check        # report differences, write nothing
```

## Concepts

| Term | Meaning |
|------|---------|
| Declaration | What a server publishes: tool name, description, input schema, permission scope |
| Contract | A canonical, hashable form of a declaration (canonical JSON → SHA-256) |
| Contract recipe | Which declaration fields a contract hash covers. Carried in the evidence next to the hash, never assumed — see [Contract recipes](#contract-recipes) |
| Annotation | A statement binding a declaration to a contract (e.g. "this tool is scoped to read-only"). Distinct from a *tool's* MCP `annotations` hints (`readOnlyHint`, `destructiveHint`, …), which recipe 2 folds into the contract itself |
| Observation | A runtime fact: invocation record, argument values, contract hash at call time |
| Finding | A measurable gap between declaration and observation |
| Ledger | An append-only SHA-256 hash chain over every captured record |

## Contract recipes

A contract hash answers "has this declaration changed?" — which is only useful if you also know *which parts of the declaration it covers*. That field set is the recipe, and it travels with the evidence instead of being assumed:

| Recipe | Covers | Applies to |
|--------|--------|-----------|
| `1` | name, description, input schema, permissions | every ledger written before v0.4.0, and any declaration that does not state a recipe |
| `2` | recipe 1, plus the declared output schema and the tool's MCP annotation hints | the current default for new declarations |

Where it lives:

- a declaration states `contract_recipe` at the manifest level, and an individual tool can override it;
- an observation may state the `contract_recipe` its `contract_hash` was computed under, and one that states none is read as recipe 1 — the same default a silent declaration gets;
- the report's `summary` lists every recipe in play, and `verify` prints them for a ledger.

Three rules make that safe rather than decorative:

1. **No silent reinterpretation.** A declaration that states no recipe is hashed under recipe 1, exactly as before — so ledgers issued before the recipe existed still verify, and nothing already published changes meaning. New declarations opt up by stating the recipe.
2. **No guessing across recipes.** If an observation states a different recipe from the declaration's, the comparison is refused with a `recipe_mismatch` finding rather than reported as drift. Two hashes computed different ways are not evidence of change in either direction.
3. **Silence means legacy, not unknown.** An observation that states no recipe was produced before recipes existed, so it is read as recipe 1 — and a pre-v0.4.0 ledger compared against a recipe-2 declaration is therefore refused, not reported as drift. The finding says so, and states the one-line change (`contract_recipe: "1"` on the declaration) that judges that ledger under the recipe that produced it.

Migrating a pair between recipes re-derives every contract hash from the raw captures, never from a stored hash — which is why the example pair can be rebuilt offline:

```bash
python3 examples/rebuild_pair.py --recipe 2
```

The example in this repository shows what the wider recipe buys: two of its three findings are contract changes that recipe 1 reported as healthy.

## Check types

- **Bound, contract unmutated** - healthy baseline: annotation still matches the contract it was declared against.
- **Bound, contract since mutated** - finding: the annotation was accurate at declaration time but is stale because the contract moved underneath it. Pairs with a review-scheduling gate.
- **Observed outside declared scope** - finding: runtime behaviour exceeds what the declaration permits (arguments, tools, or permissions not present in the declaration).
- **Recipe mismatch** - finding: the observed contract hash was computed under a different recipe from the declaration's (including an observation that states none, and is read as recipe 1), so the comparison is refused. High severity because it means the check could not run — not because the server did anything wrong.

## Roadmap

- [x] Installable package (v0.2, `mcp-ev-validate` CLI, `verify` subcommand)
- [x] Test suite + CI (Python 3.10–3.12)
- [x] Anchored evidence ledger — `verify` refuses a ledger that does not reach the head digest recorded outside it (v0.3)
- [x] Contract recipes — a contract hash states which declaration fields it covers, and a recipe disagreement is refused rather than guessed (v0.4)
- [ ] **A2A agent-card validation** — validate A2A agent cards
      (`.well-known/agent-card.json`) against observed agent behaviour:
      declared capabilities vs runtime delegation, auth requirements honoured,
      signed-card identity checks. A2A is an AAIF-hosted project (joined
      Aug 2026); this extends the declared-vs-observed evidence ladder to the
      agent-to-agent boundary. Directly addresses the open A2A identity
      verification gap (a2aproject/A2A issue #1672).
- [ ] MCP client integration (intercept tool-call records via a lightweight proxy)
- [ ] Automated review-scheduling gate (re-validate annotations on contract change)
- [ ] Report renderers (HTML, PDF)
- [ ] Policy pack support (declare what "acceptable" means per environment)

## Project status

A reference implementation of declared-vs-observed evidence for MCP servers, built and maintained by **[Empire Labs Pty Ltd](https://empirelabs.com.au)** as the open layer of its evidence-engineering work. The enforcement and cryptographic-evidence side of that work is [witnessos](https://github.com/narko4u/witnessos); the record format is [evidence-record-spec](https://github.com/narko4u/evidence-record-spec).

It is also the implementation this project puts behind the argument when the declared-vs-observed gap comes up in standards venues — including the Agentic AI Foundation's Security & Privacy work on tamper-evident evidence for agent actions — because a gap is easier to settle with a working validator than with a slide.

The core ideas are exercised in production-grade systems elsewhere in the organisation. This repository contains no proprietary code and no client data: the fictional example is constructed to exercise the checks, and the filesystem example is a capture of a public open-source MCP reference server, committed together with the raw replies it was derived from.

## Security

See [SECURITY.md](SECURITY.md) for the vulnerability reporting policy. Security issues are handled privately — do not open a public issue.

## Verifying releases

Releases are signed with **sigstore keyless signing** (GitHub Actions
workload identity). Each release contains:

- `SHA256SUMS` — hashes of every release asset
- `SHA256SUMS.sig` — the cosign signature over `SHA256SUMS`
- `SHA256SUMS.pem` — the ephemeral signing certificate

To verify a release (requires the [cosign CLI](https://docs.sigstore.dev/cosign/installation/)):

```sh
cosign verify-blob \
  --cert SHA256SUMS.pem \
  --signature SHA256SUMS.sig \
  --certificate-identity "https://github.com/narko4u/mcp-evidence-validator/.github/workflows/release.yml@refs/tags/v0.2.1" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  SHA256SUMS
```

The expected signer identity is the repository's `release.yml` workflow
running under the release tag (GitHub Actions OIDC, issuer
`https://token.actions.githubusercontent.com`). After the signature
verifies, check the asset hashes:

```sh
sha256sum -c SHA256SUMS
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions welcome under the Apache-2.0 licence; please follow the Code of Conduct.
