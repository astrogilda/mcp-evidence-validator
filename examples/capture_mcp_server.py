"""Capture a real MCP server's declared manifest and observed tool calls.

The fictional example (`make_examples.py`) shows the three checks against made-up
data. This script produces a second example pair from a *real* server, so the
declared-vs-observed gap is a thing that actually happened between two published
versions rather than a thing we invented.

What it does:

  1. starts `<package>@<declared-version>` over stdio, asks for `tools/list`,
     and records the reply as the declared manifest;
  2. starts `<package>@<observed-version>`, asks for `tools/list`, then performs
     real `tools/call` requests for the tools given on the command line;
  3. writes the pair in the repository's format (see `docs/DESIGN.md`) plus the
     raw captures the hashes derive from.

The pair records call arguments relative to the server's allowed root, so the
committed example is portable; the raw call capture under `examples/captures/`
holds the byte-exact arguments that were sent. The declared and observed sides
never contain anything but what the server actually served.

The declared side uses the older version and the observed side the newer one, so
the contract hash of a tool that changed in between disagrees with the contract
its annotation was bound to, and the validator reports `contract_mutated`.

Usage:

  python3 examples/capture_mcp_server.py \\
      --package @modelcontextprotocol/server-filesystem \\
      --declared-version 2026.1.14 --observed-version 2026.8.31 \\
      --root /tmp/mcp-capture-root

Writes:

  examples/<label>-declared.json          the pair the validator consumes
  examples/<label>-observed.json
  examples/captures/<label>-<version>.tools-list.json    raw replies
  examples/captures/<label>-<version>.calls.json

Requires Node.js (for `npx`) and network access to the package registry. The
committed example files are static, so neither is needed to run the tests or the
validator.
"""

import argparse
import base64
import hashlib
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))

from mcp_evidence_validator.fingerprint import fingerprint  # noqa: E402
from mcp_evidence_validator.validator import (  # noqa: E402
    CONTRACT_RECIPE_CURRENT,
    CONTRACT_RECIPE_FIELDS,
    build_contract,
)

# A real 1x1 PNG, so the media tool has something genuine to read.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/AGf"
    "7t1zAAAAAElFTkSuQmCC"
)
SAMPLE_TEXT = "capture fixture\n"


def to_declared(tool, recipe=CONTRACT_RECIPE_CURRENT):
    """Map an MCP tool object onto the repository's declaration shape.

    ``recipe`` 2 also carries the tool's ``outputSchema`` and its MCP annotation
    hints, so both are inside the contract hash. ``recipe`` 1 is the legacy
    four-field shape, kept because declarations hashed under it must keep
    hashing to the same values.
    """
    declared = {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "input_schema": tool.get("inputSchema", {}),
        "permissions": tool.get("permissions", []),
    }
    if recipe == "2":
        declared["output_schema"] = tool.get("outputSchema", {})
        declared["annotations"] = tool.get("annotations", {})
    declared["contract_recipe"] = recipe
    return declared


def sha256_file(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Session:
    """A JSON-RPC 2.0 conversation with an MCP server over stdio."""

    def __init__(self, package, version, root, protocol="2025-06-18"):
        self.package = package
        self.version = version
        self.protocol = protocol
        self.proc = subprocess.Popen(
            ["npx", "-y", f"{package}@{version}", str(root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.server_info = None
        self.negotiated = None

    def send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def read_reply(self, rid, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            ready, _, _ = select.select([self.proc.stdout], [], [], 1.0)
            if not ready:
                if self.proc.poll() is not None:
                    raise RuntimeError(
                        f"{self.package}@{self.version} exited before replying to id={rid}"
                    )
                continue
            line = self.proc.stdout.readline().strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # the server logs to stdout in some versions
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(f"id={rid} failed: {msg['error']}")
                return msg.get("result", {})
        raise RuntimeError(f"no reply to id={rid} within {timeout}s")

    def start(self):
        self.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": self.protocol,
                    "capabilities": {},
                    "clientInfo": {"name": "capture_mcp_server", "version": "1.0"},
                },
            }
        )
        result = self.read_reply(1, timeout=300)
        self.server_info = result.get("serverInfo", {})
        self.negotiated = result.get("protocolVersion")
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def tools(self):
        self.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        return self.read_reply(2, timeout=120).get("tools", [])

    def call(self, rid, name, arguments):
        self.send(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        result = self.read_reply(rid, timeout=60)
        text = "".join(
            item.get("text", "")
            for item in result.get("content", [])
            if item.get("type") == "text"
        )
        return {
            "tool": name,
            "arguments": arguments,
            "isError": bool(result.get("isError", False)),
            "result_preview": text[:300],
            "content_types": sorted(
                {item.get("type", "?") for item in result.get("content", [])}
            ),
        }

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def capture_tools(package, version, root):
    session = Session(package, version, root).start()
    try:
        return {
            "package": package,
            "version": version,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "protocol_version": session.negotiated,
            "server_info": session.server_info,
            "tools": session.tools(),
        }
    finally:
        session.close()


def capture_calls(package, version, root, calls, recipe=CONTRACT_RECIPE_CURRENT):
    session = Session(package, version, root).start()
    try:
        served = {tool["name"]: tool for tool in session.tools()}
        records = []
        for index, name in enumerate(calls, start=1):
            if name not in served:
                raise SystemExit(f"{package}@{version} does not serve a tool named {name!r}")
            arguments = {"path": str(Path(root) / CALL_FILES[name])}
            outcome = session.call(100 + index, name, arguments)
            records.append(
                {
                    "index": index,
                    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "tool": name,
                    "args": arguments,
                    "rel_args": {
                        key: os.path.relpath(value, str(root))
                        if isinstance(value, str) and value.startswith(str(root))
                        else value
                        for key, value in arguments.items()
                    },
                    "contract_hash": build_contract(to_declared(served[name], recipe)),
                    "contract_recipe": recipe,
                    "outcome": outcome,
                }
            )
        return records
    finally:
        session.close()


def build_pair(
    declared_raw,
    observed_raw,
    calls_raw,
    package,
    declared_version,
    recipe=CONTRACT_RECIPE_CURRENT,
):
    """Derive the declared/observed pair from raw server captures.

    Every contract hash here is recomputed from the captured ``tools/list``
    replies, never copied from a stored value: the served manifests are the
    source of truth and the pair is a view of them. That is what lets the pair
    be rebuilt offline under a different recipe without re-running the server.
    """
    calls = [record["tool"] for record in calls_raw["calls"]]
    declared_tools = {
        tool["name"]: to_declared(tool, recipe) for tool in declared_raw["tools"]
    }
    observed_tools = {
        tool["name"]: to_declared(tool, recipe) for tool in observed_raw["tools"]
    }

    missing = [name for name in calls if name not in declared_tools]
    if missing:
        raise SystemExit(
            f"observed call(s) not declared at {declared_version}: {missing}"
        )

    declared = {
        "server": declared_raw["server_info"].get("name", package),
        "declared_at": declared_raw["captured_at"],
        "contract_recipe": recipe,
        "tools": [declared_tools[name] for name in sorted(declared_tools)],
        "annotations": [
            {
                "id": f"ann-{name}",
                "tool": name,
                "statement": (
                    "client bound to the contract declared at "
                    f"{package}@{declared_version}"
                ),
                "bound_contract": build_contract(declared_tools[name], recipe),
            }
            for name in calls
        ],
    }
    observed = {
        "server": observed_raw["server_info"].get("name", package),
        "contract_recipe": recipe,
        "observations": [
            {
                "index": record["index"],
                "observed_at": record["observed_at"],
                "tool": record["tool"],
                "args": record["rel_args"],
                "contract_hash": build_contract(
                    observed_tools[record["tool"]], recipe
                ),
                "contract_recipe": recipe,
            }
            for record in calls_raw["calls"]
        ],
    }
    return declared, observed


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sha256_file(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", required=True)
    parser.add_argument("--declared-version", required=True)
    parser.add_argument("--observed-version", required=True)
    parser.add_argument("--root", required=True, help="directory the server is allowed to serve")
    parser.add_argument("--label", default=None, help="output basename (default: package name)")
    parser.add_argument(
        "--call",
        action="append",
        default=[],
        choices=sorted(CALL_FILES),
        help="tool to call against the observed version (repeatable)",
    )
    parser.add_argument("--examples-dir", default=str(HERE))
    parser.add_argument(
        "--recipe",
        default=CONTRACT_RECIPE_CURRENT,
        choices=sorted(CONTRACT_RECIPE_FIELDS),
        help="contract recipe to hash the pair under (default: current)",
    )
    args = parser.parse_args()

    calls = args.call or ["read_text_file", "read_media_file", "get_file_info"]
    label = args.label or "mcp-server"
    examples = Path(args.examples_dir)
    captures = examples / "captures"

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "sample.txt").write_text(SAMPLE_TEXT, encoding="utf-8")
    (root / "pixel.png").write_bytes(PNG_1X1)

    print(f"capturing {args.package}@{args.declared_version} (declared) ...")
    declared_raw = capture_tools(args.package, args.declared_version, root)
    print(f"capturing {args.package}@{args.observed_version} (observed) ...")
    observed_raw = capture_tools(args.package, args.observed_version, root)
    calls_raw = capture_calls(
        args.package, args.observed_version, root, calls, args.recipe
    )

    declared, observed = build_pair(
        declared_raw,
        observed_raw,
        {"calls": calls_raw},
        args.package,
        args.declared_version,
        args.recipe,
    )

    declared_tools = {tool["name"]: to_declared(tool, args.recipe)
                      for tool in declared_raw["tools"]}
    observed_tools = {tool["name"]: to_declared(tool, args.recipe)
                      for tool in observed_raw["tools"]}

    declared_path = examples / f"{label}-declared.json"
    observed_path = examples / f"{label}-observed.json"
    declared_hash = write_json(declared_path, declared)
    observed_hash = write_json(observed_path, observed)
    raw_declared = captures / f"{label}-{args.declared_version}.tools-list.json"
    raw_observed = captures / f"{label}-{args.observed_version}.tools-list.json"
    raw_calls = captures / f"{label}-{args.observed_version}.calls.json"
    raw_declared_hash = write_json(raw_declared, declared_raw)
    raw_observed_hash = write_json(raw_observed, observed_raw)
    raw_calls_hash = write_json(raw_calls, {"package": args.package,
                                            "version": args.observed_version,
                                            "root": str(root),
                                            "contract_recipe": args.recipe,
                                            "calls": calls_raw})

    drift = sorted(
        name
        for name in observed_tools
        if name in declared_tools
        and build_contract(observed_tools[name], args.recipe)
        != build_contract(declared_tools[name], args.recipe)
    )
    print()
    print(f"declared  {args.package}@{args.declared_version}: "
          f"{len(declared_tools)} tools  ({declared_path} {declared_hash})")
    print(f"observed  {args.package}@{args.observed_version}: "
          f"{len(observed_tools)} tools, {len(calls)} calls  ({observed_path} {observed_hash})")
    print(f"raw captures: {raw_declared_hash} {raw_observed_hash} {raw_calls_hash}")
    print(f"tools whose contract changed between the two versions: "
          f"{drift or 'none (this pair would show no contract_mutated finding)'}")
    for name in calls:
        record = next(r for r in calls_raw if r["tool"] == name)
        print(f"  {name}: isError={record['outcome']['isError']} "
              f"content={record['outcome']['content_types']}")


CALL_FILES = {
    "read_text_file": "sample.txt",
    "read_media_file": "pixel.png",
    "get_file_info": "sample.txt",
    "read_file": "sample.txt",
    "list_directory": ".",
}


if __name__ == "__main__":
    main()
