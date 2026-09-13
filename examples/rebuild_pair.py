"""Rebuild committed example pairs from the committed captures.

No Node.js, no network, no MCP server: the raw ``tools/list`` and ``tools/call``
replies under ``examples/captures/`` are the source of truth, and every contract
hash in a pair is a derivation from them. This script re-runs that derivation,
which is how a pair is migrated between contract recipes (see ``docs/DESIGN.md``,
section 2.2.1).

What it rewrites:

  examples/<label>-declared.json          the pair the validator consumes
  examples/<label>-observed.json
  examples/captures/<label>-<v>.calls.json   only the derived ``contract_hash``
                                             and ``contract_recipe`` fields

What it never touches, in any file: the server replies themselves - ``outcome``,
``args``, ``observed_at``, ``root``, tool descriptions, schemas and annotations
are copied through byte-for-byte.

Usage:

  python3 examples/rebuild_pair.py                    # current recipe
  python3 examples/rebuild_pair.py --recipe 2         # explicitly
  python3 examples/rebuild_pair.py --check            # verify, write nothing
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

from capture_mcp_server import build_pair, write_json  # noqa: E402
from mcp_evidence_validator.validator import (  # noqa: E402
    CONTRACT_RECIPE_CURRENT,
    CONTRACT_RECIPE_FIELDS,
)

#: Every committed capture pair, and the versions it was taken at.
PAIRS = [
    {
        "label": "filesystem-server",
        "package": "@modelcontextprotocol/server-filesystem",
        "declared": "2026.1.14",
        "observed": "2026.8.31",
    },
]


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def rebuild(pair, examples, recipe, check):
    label = pair["label"]
    captures = examples / "captures"
    declared_raw = load(captures / f"{label}-{pair['declared']}.tools-list.json")
    observed_raw = load(captures / f"{label}-{pair['observed']}.tools-list.json")
    calls_path = captures / f"{label}-{pair['observed']}.calls.json"
    calls_raw = load(calls_path)

    declared, observed = build_pair(
        declared_raw, observed_raw, calls_raw, pair["package"], pair["declared"], recipe
    )

    # The stored per-call hashes are derived values too, so they move with the
    # recipe. Everything else in the capture is passed through untouched.
    rebuilt_calls = dict(calls_raw)
    rebuilt_calls["contract_recipe"] = recipe
    rebuilt_calls["calls"] = []
    for record, observation in zip(calls_raw["calls"], observed["observations"]):
        updated = dict(record)
        updated["contract_hash"] = observation["contract_hash"]
        updated["contract_recipe"] = recipe
        rebuilt_calls["calls"].append(updated)

    targets = {
        examples / f"{label}-declared.json": declared,
        examples / f"{label}-observed.json": observed,
        calls_path: rebuilt_calls,
    }

    changed = []
    for path, payload in targets.items():
        current = load(path) if path.exists() else None
        if current == payload:
            continue
        changed.append(path)
        if not check:
            write_json(path, payload)

    verb = "would change" if check else "rewrote"
    if changed:
        for path in changed:
            print(f"{verb}: {path.relative_to(REPO)}")
    else:
        print(f"{label}: already consistent with the captures (recipe {recipe})")
    return changed


def main():
    parser = argparse.ArgumentParser(
        description="Rebuild committed example pairs from the committed captures."
    )
    parser.add_argument("--examples-dir", default=str(HERE))
    parser.add_argument(
        "--recipe",
        default=CONTRACT_RECIPE_CURRENT,
        choices=sorted(CONTRACT_RECIPE_FIELDS),
        help="contract recipe to rebuild under (default: current)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report differences without writing (exit 1 if any)",
    )
    args = parser.parse_args()

    examples = Path(args.examples_dir)
    changed = []
    for pair in PAIRS:
        changed += rebuild(pair, examples, args.recipe, args.check)
    if args.check and changed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
