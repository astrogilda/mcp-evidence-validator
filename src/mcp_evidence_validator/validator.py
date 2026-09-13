"""Core validation logic: declared vs observed MCP server state.

Produces findings for the declared-vs-observed gap and a human-readable
summary. The caller is responsible for ledger bookkeeping.

Contract recipes
----------------

A contract hash answers "has this declaration changed?". Which fields of the
declaration are folded into that hash is the *recipe*, and a hash is only
meaningful together with it. Recipe is carried in the evidence rather than
assumed:

* a declaration states ``contract_recipe`` (manifest level, overridable per
  tool),
* an observation may state the ``contract_recipe`` its ``contract_hash`` was
  computed under.

A declaration that states no recipe is recipe 1 - the four-field contract that
every ledger issued before 0.4.0 carries. Legacy declarations must keep hashing
to the values already committed in those ledgers, so the default is the legacy
recipe and new declarations opt up explicitly. Comparing a hash from one recipe
against a re-derivation under another would be a false verdict in either
direction, so the two are never mixed: a recipe disagreement is reported as its
own finding and the mutation comparison is skipped.
"""

from typing import Any

from .fingerprint import fingerprint

#: Recipe used for new declarations.
CONTRACT_RECIPE_CURRENT = "2"

#: Recipe assumed for a declaration that does not state one.
CONTRACT_RECIPE_LEGACY = "1"

#: Which declaration fields each recipe folds into the contract hash.
CONTRACT_RECIPE_FIELDS: dict[str, tuple[str, ...]] = {
    "1": ("name", "description", "input_schema", "permissions"),
    "2": (
        "name",
        "description",
        "input_schema",
        "permissions",
        "output_schema",
        "annotations",
    ),
}

#: Fallback for a field the declaration does not carry. These reproduce the
#: reads recipe 1 has always performed, so its hashes are unchanged by the
#: introduction of recipe 2.
_FIELD_DEFAULTS: dict[str, Any] = {
    "description": "",
    "input_schema": {},
    "permissions": [],
    "output_schema": {},
    "annotations": {},
}

#: What each recipe covers, for reports and documentation.
CONTRACT_RECIPE_NOTES: dict[str, str] = {
    "1": "name, description, input schema, permissions",
    "2": (
        "recipe 1 plus the tool's declared output schema and its MCP "
        "annotation hints (readOnlyHint, destructiveHint, idempotentHint, "
        "openWorldHint)"
    ),
}


def check_recipe(recipe: str) -> str:
    """Return ``recipe`` unchanged, or raise if it is not a known recipe."""
    if recipe not in CONTRACT_RECIPE_FIELDS:
        raise ValueError(
            f"unknown contract recipe {recipe!r}; "
            f"known recipes: {sorted(CONTRACT_RECIPE_FIELDS)}"
        )
    return recipe


def contract_recipe(tool: dict[str, Any]) -> str:
    """The recipe a tool declaration is hashed under, defaulting to legacy."""
    return check_recipe(tool.get("contract_recipe") or CONTRACT_RECIPE_LEGACY)


def contract_payload(tool: dict[str, Any], recipe: str | None = None) -> dict[str, Any]:
    """The fields a recipe folds into the contract hash, and their values."""
    recipe = check_recipe(recipe) if recipe else contract_recipe(tool)
    payload: dict[str, Any] = {}
    for field in CONTRACT_RECIPE_FIELDS[recipe]:
        if field == "name":
            payload[field] = tool["name"]
        else:
            payload[field] = tool.get(field, _FIELD_DEFAULTS[field])
    return payload


def build_contract(tool: dict[str, Any], recipe: str | None = None) -> str:
    """Canonical fingerprint of a tool declaration under a named recipe.

    ``recipe`` defaults to the declaration's own ``contract_recipe`` field, and
    to the legacy recipe when it states none.
    """
    return fingerprint(contract_payload(tool, recipe))


def validate_batch(
    declared: dict[str, Any],
    observed: dict[str, Any],
    recipe: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compare a declared manifest against an observed runtime batch.

    Returns (findings, summary). Findings are dicts with keys:
    observation_index, check, severity, detail, and check-specific extras.

    ``recipe`` overrides the manifest-level ``contract_recipe``; per-tool
    declarations take precedence over both.
    """
    tools = {t["name"]: t for t in declared.get("tools", [])}
    manifest_recipe = check_recipe(
        recipe or declared.get("contract_recipe") or CONTRACT_RECIPE_LEGACY
    )
    annotations = declared.get("annotations", [])
    ann_by_tool: dict[str, list[dict[str, Any]]] = {}
    for ann in annotations:
        ann_by_tool.setdefault(ann.get("tool"), []).append(ann)

    findings: list[dict[str, Any]] = []
    obs_list = observed.get("observations", [])
    recipes_in_use = {manifest_recipe}

    for obs in obs_list:
        tool_name = obs.get("tool")
        decl = tools.get(tool_name)
        if decl is None:
            findings.append(
                {
                    "observation_index": obs.get("index", 0),
                    "check": "unknown_tool",
                    "severity": "high",
                    "detail": f"tool '{tool_name}' observed but not declared",
                }
            )
            continue

        tool_recipe = check_recipe(decl.get("contract_recipe") or manifest_recipe)
        recipes_in_use.add(tool_recipe)
        current = build_contract(decl, tool_recipe)
        observed_hash = obs.get("contract_hash")
        observed_recipe = obs.get("contract_recipe")
        anns = ann_by_tool.get(tool_name, [])
        bound = any(a.get("bound_contract") == current for a in anns)

        comparable = True
        if observed_recipe is not None and check_recipe(observed_recipe) != tool_recipe:
            # The two sides were hashed under different recipes, so a
            # comparison would report drift that is really a recipe change.
            # Refuse the verdict instead of guessing which side is right.
            findings.append(
                {
                    "observation_index": obs.get("index", 0),
                    "check": "recipe_mismatch",
                    "severity": "high",
                    "detail": (
                        f"observed contract hash was computed under recipe "
                        f"{observed_recipe}, the declaration is recipe "
                        f"{tool_recipe}; the two are not comparable"
                    ),
                    "declared_recipe": tool_recipe,
                    "observed_recipe": observed_recipe,
                }
            )
            comparable = False

        # Check 1: bound and unmutated (healthy baseline - no finding emitted)
        # Check 2: contract mutated since declaration (stale annotation)
        if comparable and observed_hash is not None and observed_hash != current:
            findings.append(
                {
                    "observation_index": obs.get("index", 0),
                    "check": "contract_mutated",
                    "severity": "medium",
                    "detail": (
                        "annotation bound to contract that has changed "
                        "since declaration"
                    ),
                    "contract_recipe": tool_recipe,
                    "declared_contract": current,
                    "observed_contract": observed_hash,
                }
            )
        elif comparable and not bound and observed_hash == current:
            findings.append(
                {
                    "observation_index": obs.get("index", 0),
                    "check": "unbound_annotation",
                    "severity": "low",
                    "detail": (
                        f"tool '{tool_name}' observed with no annotation "
                        "bound to the current contract"
                    ),
                    "contract_recipe": tool_recipe,
                }
            )

        # Check 3: observed arguments outside declared input schema
        allowed = set((decl.get("input_schema") or {}).get("properties", {}).keys())
        actual = set((obs.get("args") or {}).keys())
        extra = actual - allowed
        if extra:
            findings.append(
                {
                    "observation_index": obs.get("index", 0),
                    "check": "scope_violation",
                    "severity": "high",
                    "detail": f"arguments outside declared schema: {sorted(extra)}",
                }
            )

    summary = {
        "declared_tools": len(tools),
        "observations": len(obs_list),
        "findings": len(findings),
        "contract_recipes": sorted(recipes_in_use),
        "checks": [
            "bound_unmutated",
            "contract_mutated",
            "scope_violation",
            "recipe_mismatch",
        ],
    }
    return findings, summary
