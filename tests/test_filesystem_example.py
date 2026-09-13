"""The filesystem-server example: a real capture, and the drift inside it.

`examples/capture_mcp_server.py` starts a published MCP server over stdio, so
every contract hash in the pair tested here came out of the server itself. These
tests recompute those hashes from the raw captures in `examples/captures/`, then
run the validator over the pair.

The pair is static, so the tests need neither Node.js nor network access.
"""

import json
import os
from pathlib import Path

from mcp_evidence_validator.cli import load_json, main
from mcp_evidence_validator.validator import build_contract, validate_batch

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
CAPTURES = EXAMPLES / "captures"

LABEL = "filesystem-server"
DECLARED_VERSION = "2026.1.14"
OBSERVED_VERSION = "2026.8.31"


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def to_declared(tool):
    """The mapping the capture script applies to a served tool object."""
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "input_schema": tool.get("inputSchema", {}),
        "permissions": tool.get("permissions", []),
    }


def served_tools(raw):
    return {tool["name"]: to_declared(tool) for tool in raw["tools"]}


def captures():
    declared = load(CAPTURES / f"{LABEL}-{DECLARED_VERSION}.tools-list.json")
    observed = load(CAPTURES / f"{LABEL}-{OBSERVED_VERSION}.tools-list.json")
    calls = load(CAPTURES / f"{LABEL}-{OBSERVED_VERSION}.calls.json")
    return declared, observed, calls


def example_pair():
    return (
        load(EXAMPLES / f"{LABEL}-declared.json"),
        load(EXAMPLES / f"{LABEL}-observed.json"),
    )


def test_the_pair_carries_the_captured_manifests():
    declared_raw, observed_raw, calls_raw = captures()
    declared, observed = example_pair()

    assert declared["server"] == declared_raw["server_info"]["name"]
    assert observed["server"] == observed_raw["server_info"]["name"]
    assert {tool["name"]: tool for tool in declared["tools"]} == served_tools(declared_raw)

    for observation, raw_call in zip(
        observed["observations"], calls_raw["calls"], strict=True
    ):
        assert observation["tool"] == raw_call["tool"]
        assert observation["observed_at"] == raw_call["observed_at"]
        assert observation["contract_hash"] == build_contract(
            served_tools(observed_raw)[raw_call["tool"]]
        )
        # Arguments are recorded relative to the server's allowed root; the raw
        # capture holds the byte-exact ones.
        assert observation["args"] == {
            key: os.path.relpath(value, calls_raw["root"])
            if isinstance(value, str) and value.startswith(calls_raw["root"])
            else value
            for key, value in raw_call["args"].items()
        }


def test_the_example_finds_the_real_contract_mutation():
    declared, observed = example_pair()
    findings, summary = validate_batch(declared, observed)

    assert summary["declared_tools"] == 14
    assert summary["observations"] == 3
    assert summary["findings"] == 1

    (finding,) = findings
    assert finding["check"] == "contract_mutated"
    assert finding["severity"] == "medium"
    observation = observed["observations"][finding["observation_index"] - 1]
    assert observation["tool"] == "read_media_file"

    declared_raw, observed_raw, _ = captures()
    assert finding["declared_contract"] == build_contract(
        served_tools(declared_raw)["read_media_file"]
    )
    assert finding["observed_contract"] == build_contract(
        served_tools(observed_raw)["read_media_file"]
    )
    assert finding["declared_contract"] != finding["observed_contract"]


def test_only_the_observed_tools_are_annotated():
    """Unannotated calls report unbound_annotation, so the pair binds all three."""
    declared, observed = example_pair()
    annotated = {annotation["tool"] for annotation in declared["annotations"]}
    assert annotated == {observation["tool"] for observation in observed["observations"]}


def test_the_change_is_in_the_description_and_the_output_schema():
    """What moved between the two versions, and what the fingerprint sees.

    The input schema is identical either side, so the mutation is caught by the
    description half of the contract. `outputSchema` also changed, and the
    contract does not cover it: a tool can change what it returns while keeping
    its input schema and description intact.
    """
    declared_raw, observed_raw, _ = captures()
    old = served_tools(declared_raw)["read_media_file"]
    new = served_tools(observed_raw)["read_media_file"]
    raw_old = {tool["name"]: tool for tool in declared_raw["tools"]}["read_media_file"]
    raw_new = {tool["name"]: tool for tool in observed_raw["tools"]}["read_media_file"]

    assert old["input_schema"] == new["input_schema"]
    assert old["description"] != new["description"]
    assert raw_old["outputSchema"] != raw_new["outputSchema"]
    assert "outputSchema" not in old
    assert "annotations" not in old


def test_the_pair_runs_through_the_cli(tmp_path):
    declared, observed = example_pair()
    declared_path = tmp_path / "declared.json"
    observed_path = tmp_path / "observed.json"
    out = tmp_path / "evidence.json"
    declared_path.write_text(json.dumps(declared), encoding="utf-8")
    observed_path.write_text(json.dumps(observed), encoding="utf-8")

    rc = main(
        [
            "validate",
            "--declared",
            str(declared_path),
            "--observed",
            str(observed_path),
            "--out",
            str(out),
        ]
    )
    assert rc == 0

    ledger = load_json(str(out))
    report = ledger["blocks"][2]["record"]
    assert report["summary"]["findings"] == 1
    assert report["findings"][0]["check"] == "contract_mutated"

    head = ledger["blocks"][-1]["hash"]
    assert main(["verify", "--ledger", str(out), "--expected-head", head]) == 0
