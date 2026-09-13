"""Command-line interface for the MCP Evidence Validator.

Subcommands:
    validate  --declared manifest.json --observed observed.json --out evidence.json
              [--head-out head.txt]
    verify    --ledger evidence.json --expected-head sha256:...

``validate`` prints the head digest of the ledger it wrote. Record that digest
somewhere the ledger file's holder cannot edit, and pass it back to ``verify``.
Without it the chain is self-describing, and a self-describing chain can be
replayed over an edit, truncated, or issued with any published prev_hash and
index its author likes.
"""

import argparse
import json
import sys
from typing import Any

from . import __version__
from .ledger import UNANCHORED, Ledger
from .validator import (
    CONTRACT_RECIPE_CURRENT,
    CONTRACT_RECIPE_LEGACY,
    CONTRACT_RECIPE_NOTES,
    validate_batch,
)


def load_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cmd_validate(args: argparse.Namespace) -> int:
    declared = load_json(args.declared)
    observed = load_json(args.observed)

    if declared.get("contract_recipe") is None:
        print(
            f"note: declaration states no contract_recipe; hashing under recipe "
            f"{CONTRACT_RECIPE_LEGACY} ({CONTRACT_RECIPE_NOTES[CONTRACT_RECIPE_LEGACY]}). "
            f"New declarations should state {CONTRACT_RECIPE_CURRENT!r}.",
            file=sys.stderr,
        )

    led = Ledger()
    led.append("declaration", declared)
    led.append("observation_batch", observed)

    findings, summary = validate_batch(declared, observed)
    report = {"summary": summary, "findings": findings}
    led.append("report", report)

    # The ledger was built in this process, so there is no external head to
    # check it against yet. This call is the self-consistency half only.
    problems = led.verify(UNANCHORED)
    if problems:
        print("LEDGER CORRUPT:", problems, file=sys.stderr)
        return 1

    led.dump(args.out)
    head = led.head()
    if args.head_out:
        with open(args.head_out, "w", encoding="utf-8") as fh:
            fh.write(head + "\n")
    print(f"evidence head: {head}", file=sys.stderr)
    print(
        "record that digest outside this file; verify needs it back",
        file=sys.stderr,
    )
    print(json.dumps(report, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        led = Ledger.load(args.ledger)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"verify failed: {exc}", file=sys.stderr)
        return 2

    problems = led.verify(args.expected_head)
    if problems:
        print(f"LEDGER NOT VERIFIED ({len(led)} blocks):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    types = {}
    recipes = set()
    for block in led:
        types[block["type"]] = types.get(block["type"], 0) + 1
        record = block.get("record")
        if isinstance(record, dict):
            if record.get("contract_recipe"):
                recipes.add(record["contract_recipe"])
            summary = record.get("summary")
            if isinstance(summary, dict):
                recipes.update(summary.get("contract_recipes") or [])
    print(f"ledger intact: {len(led)} blocks, chain verified against the expected head")
    print("block types:", json.dumps(types, sort_keys=True))
    if recipes:
        # The recipe is what makes a contract hash interpretable, so it is
        # reported as part of verifying the evidence rather than left implicit.
        print("contract recipes:", ", ".join(sorted(recipes)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-ev-validate",
        description="MCP Evidence Validator - declared-vs-observed checks with "
        "a tamper-evident SHA-256 evidence ledger.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="compare declarations to observations")
    p_validate.add_argument("--declared", required=True, help="declared manifest JSON")
    p_validate.add_argument("--observed", required=True, help="observed runtime JSON")
    p_validate.add_argument("--out", required=True, help="output evidence ledger JSON")
    p_validate.add_argument(
        "--head-out",
        help="write the ledger head digest to this path, for storage outside the ledger",
    )
    p_validate.set_defaults(func=cmd_validate)

    p_verify = sub.add_parser("verify", help="verify a ledger's hash chain integrity")
    p_verify.add_argument("--ledger", required=True, help="evidence ledger JSON")
    p_verify.add_argument(
        "--expected-head",
        required=True,
        help="the head digest recorded outside the ledger, as printed by validate",
    )
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
