# Design: MCP Evidence Validator (draft v0.1)

## 1. Goal

Provide a repeatable, machine-checkable way to answer the question an auditor asks:

> "How do I know this MCP server is still doing what it said it would do?"

The answer is an **evidence record**: a hash-chained ledger of declarations, observations, and the checks between them, produced automatically and verifiable by anyone with the ledger.

## 2. Core model

### 2.1 Declarations

A declaration is what a server publishes about itself. Minimum viable shape:

```json
{
  "server": "fictional-weather",
  "declared_at": "2026-08-01T00:00:00Z",
  "tools": [
    {
      "name": "get_forecast",
      "description": "Return forecast for a city",
      "input_schema": {
        "type": "object",
        "properties": {
          "city": {"type": "string"},
          "days": {"type": "integer", "minimum": 1, "maximum": 7}
        },
        "required": ["city"]
      },
      "permissions": ["read:weather"]
    }
  ],
  "annotations": [
    {
      "id": "ann-001",
      "tool": "get_forecast",
      "statement": "read-only access to public weather data",
      "bound_contract": "sha256:abc123..."
    }
  ]
}
```

### 2.2 Contracts

A contract is the canonical, hashable form of a declaration. We fingerprint the canonical JSON (sorted keys, stable serialization) with SHA-256. The contract hash is what annotations bind to, and what we re-derive on every observation.

If the re-derived hash differs from the bound hash, **the contract has mutated**.

### 2.2.1 Contract recipes and migration

A hash answers "has this declaration changed?" only together with the set of declaration fields that went into it. That set is the **recipe**, and a contract hash is meaningless without it: the same declaration hashes two different ways under two recipes, and neither is wrong.

The recipe is therefore carried in the evidence, not assumed:

| Recipe | Fields folded into the hash |
|--------|-----------------------------|
| `1` | `name`, `description`, `input_schema`, `permissions` |
| `2` | recipe 1, plus `output_schema` and the tool's MCP `annotations` hints |

Why recipe 2 exists: recipe 1 could not see a server that changed only what it returns, or only the hints it publishes about its own side effects (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`). A tool whose input schema and description are stable while its output schema widens — or while it starts declaring itself destructive — reported healthy. That is issue #23, and it is pinned as a test rather than fixed quietly.

Four rules keep the migration honest:

1. **Legacy keeps its meaning.** A declaration that states no recipe is hashed under recipe 1, exactly as it was before recipes existed. Every ledger issued before v0.4.0 still verifies and nothing already published changes meaning; new declarations opt up by stating `contract_recipe`.
2. **Recipes are never mixed.** If an observation states a different recipe from the declaration's, the comparison is refused with a `recipe_mismatch` finding instead of reported as drift. Two hashes computed different ways are not evidence of change in either direction, and quietly re-deriving one side to force a verdict would be worse than the gap it closes.
3. **Silence is legacy, not unknown — where a hash exists to interpret.** An observation that carries a `contract_hash` but states no recipe is read as recipe 1, the same default a silent declaration gets: that is what every artifact written before recipes existed carries. Reading that silence as "unknown recipe" left rule 2 unarmed, so an intact pre-0.4.0 ledger compared against a recipe-2 declaration came back as `contract_mutated` — drift reported where nothing had drifted. The `recipe_mismatch` finding now names the declaration change that judges such a ledger under the recipe that produced it. The inference stops at the hash: an observation that carries no `contract_hash` (scope-only) makes no recipe claim, so none is inferred for it and no finding asserts a hash the evidence does not hold. Its arguments are still checked against the declared input schema.
4. **A stated recipe is read wherever it appears.** An observation for a tool the declaration does not carry is still passed through `check_recipe` and counted in the summary, so a ledger cannot be described as holding one recipe while its evidence also holds a hash made under another — and an unknown recipe cannot escape validation by sitting on a tool that was never declared.

Precedence: an explicit argument to `build_contract`, then the tool's own `contract_recipe`, then the manifest's, then recipe 1.

Contract hashes in the committed example pair were migrated by re-deriving them from the raw `tools/list` captures (`examples/rebuild_pair.py`), never by copying stored values. That is the general migration path: raw captures are the source of truth, pairs are a view of them, and a pair that disagrees with its captures fails the test suite.

The manifest a call is judged under is the one its **own session** served, and that session's manifest is persisted beside the calls (`calls.json` carries `tools`). A separate `tools/list` session is provenance, not the source: a server may vary its declaration per session, and deriving a per-call hash from another session would assert a contract the call never ran under. A capture that cannot supply its own session's manifest stops the derivation rather than borrowing another session's declaration.

### 2.3 Observations

An observation is a runtime fact captured at or around a tool call:

```json
{
  "observed_at": "2026-08-02T12:00:00Z",
  "server": "fictional-weather",
  "tool": "get_forecast",
  "args": {"city": "Townsville", "days": 3},
  "contract_hash": "sha256:abc123...",
  "result": {"status": "ok"}
}
```

The observer (proxy, gateway, or client wrapper) records the contract hash *at call time*, capturing whether the declaration the agent believed it was calling still holds.

### 2.4 Findings

A finding is a measured gap. Three prototype checks:

| Check | Condition | Verdict |
|-------|-----------|---------|
| Bound and unmutated | annotation exists AND observed contract hash == bound hash | **healthy baseline** |
| Bound, contract mutated | annotation exists BUT observed contract hash != bound hash | **finding: stale annotation** |
| Observed outside declared scope | tool call uses tools/args/permissions not in the declaration | **finding: scope violation** |
| Recipe mismatch | observation states a recipe other than the declaration's, or states none and is therefore read as recipe 1 | **finding: check could not run** |

A finding is never an accusation. It is a signal to schedule review: if an annotation is stale, re-verify it; if a scope is violated, decide whether the declaration or the runtime is wrong.

### 2.5 Ledger (tamper-evident chain)

Every record (declaration, observation, finding) is appended to a SHA-256 hash chain:

```
block_n = sha256(prev_hash + canonical_json(record_n))
```

Properties:

- Any mutation to a past record changes its hash and therefore every later block.
- Verification is O(n) and requires only the ledger file.
- The ledger can be anchored externally (published hash, timestamped) for non-repudiation.
- Records carry how their own hashes were produced: a declaration states its `contract_recipe`, and observations may state the recipe their `contract_hash` was computed under. An observation that carries a hash but states none is read as recipe 1, the same default a silent declaration gets; one that carries no hash states no recipe either way, and none is inferred for it. A recipe stated on an observation for a tool that was never declared is still validated and still counted, so the summary describes the recipes the evidence actually holds. A ledger therefore says what its contract hashes mean, rather than leaving that to whoever reads it later.
- Format version `0.3` (was `0.2`). The bump is additive: block shape, the chain, and the dump/load round trip are unchanged, and a ledger written under `0.2` still loads and still verifies. The separate assertion a `0.2` ledger makes — that its records state no recipe and were therefore hashed under recipe 1 — is preserved by that default.

## 3. Architecture

```
+----------------+      +----------------+      +----------------+
|  Declarations  |      |  Observations  |      |  Findings      |
|  (manifest)    |      |  (runtime)     |      |  (checks)      |
+----------------+      +----------------+      +----------------+
        |                       |                       |
        +-----------+-----------+-----------------------+
                    |
                    v
          +------------------+
          | Evidence Ledger  |
          | (hash chain)     |
          +------------------+
                    |
                    v
          +------------------+
          | Report (JSON/UI) |
          +------------------+
```

Components:

- `src/mcp_evidence_validator/cli.py` - CLI entry point; runs checks and emits the ledger.
- `src/mcp_evidence_validator/validator.py` - declared-vs-observed checks, contract recipes.
- `src/mcp_evidence_validator/ledger.py` - hash-chain append and verify.
- `src/mcp_evidence_validator/fingerprint.py` - canonical JSON fingerprinting.
- `examples/capture_mcp_server.py` - starts a real MCP server, captures its replies, derives an example pair.
- `examples/rebuild_pair.py` - re-derives a committed pair from its captures, e.g. when migrating recipes.
- (Roadmap) a lightweight MCP client wrapper that records observations from a live call path.

## 4. Security model

- The validator does **not** trust server self-reports. Observations come from the call path (client/gateway side), not from the server.
- The ledger is append-only; verification is independent of the validator binary (documented algorithm).
- Contract fingerprinting is deterministic: same declaration always yields the same hash.
- No secrets are stored. The ledger contains hashes and metadata, never credentials or payload contents (observation records store argument *shape* optionally, with a redaction flag).

## 5. Scope (explicit non-goals)

- Identity and delegated authorization (SPIFFE/SVID, RFC 8693, UCAN capability tokens) are handled by the AAIF Identity & Trust WG, not here.
- This is not a runtime sandbox or an enforcement engine. It measures and records; policy engines can consume the ledger.
- It does not replace threat modeling; it operationalizes one part of it (evidence of ongoing compliance).

## 6. Compatibility

- Language: Python 3.10+, standard library only (prototype).
- Output: JSON (machine) and console (human).
- Works with any MCP server whose tool calls can be observed; protocol version agnostic at the ledger level.

## 7. Reference context

- AAIF Security & Privacy WG Best Practices Guide (draft v0.1): post-incident forensics domain.
- OWASP MCP Governance and Risk Framework: automated evidence collection and enforcement appendix (PR in review).
- Observed industry data: 90% of deployed agents hold ~10x more privilege than a single task requires (Obsidian Security 2025); first malicious MCP server Sept 2025; CVE-2025-6514 (CVSS 9.6).
