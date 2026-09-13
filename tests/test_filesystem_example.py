"""The filesystem-server example: a real capture, and the drift inside it.

`examples/capture_mcp_server.py` starts a published MCP server over stdio, so
every contract hash in the pair tested here came out of the server itself. These
tests recompute those hashes from the raw captures in `examples/captures/`, then
run the validator over the pair.

The pair is static, so the tests need neither Node.js nor network access.
"""

import json
import os
import sys
from pathlib import Path

from mcp_evidence_validator.cli import load_json, main
from mcp_evidence_validator.fingerprint import fingerprint
from mcp_evidence_validator.validator import (
    CONTRACT_RECIPE_CURRENT,
    build_contract,
    contract_payload,
    validate_batch,
)

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
CAPTURES = EXAMPLES / "captures"
sys.path.insert(0, str(EXAMPLES))

from capture_mcp_server import build_pair  # noqa: E402

LABEL = "filesystem-server"
PACKAGE = "@modelcontextprotocol/server-filesystem"
DECLARED_VERSION = "2026.1.14"
OBSERVED_VERSION = "2026.8.31"


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def to_declared(tool, recipe=CONTRACT_RECIPE_CURRENT):
    """The mapping the capture script applies to a served tool object."""
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


def served_tools(raw, recipe=CONTRACT_RECIPE_CURRENT):
    return {tool["name"]: to_declared(tool, recipe) for tool in raw["tools"]}


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
    assert observed["server"] == calls_raw["server_info"]["name"]
    assert {tool["name"]: tool for tool in declared["tools"]} == served_tools(declared_raw)

    # The observed side derives from the manifest the *call* session served, so
    # the capture must carry it: a separate tools/list session is provenance,
    # not the declaration those calls ran under.
    call_session = served_tools(calls_raw)
    for observation, raw_call in zip(
        observed["observations"], calls_raw["calls"], strict=True
    ):
        assert observation["tool"] == raw_call["tool"]
        assert observation["observed_at"] == raw_call["observed_at"]
        assert observation["contract_hash"] == build_contract(
            call_session[raw_call["tool"]]
        )
        # Arguments are recorded relative to the server's allowed root; the raw
        # capture holds the byte-exact ones.
        assert observation["args"] == {
            key: os.path.relpath(value, calls_raw["root"])
            if isinstance(value, str) and value.startswith(calls_raw["root"])
            else value
            for key, value in raw_call["args"].items()
        }


def test_the_call_session_manifest_agrees_with_the_tools_list_session():
    """Both sessions are recorded, and this capture shows them agreeing.

    The calls were made against one session and a separate tools/list session
    listed the same version. The pair claims the call session's declaration, so
    if the two ever disagreed for a called tool, the evidence for that would
    live here rather than being averaged away.
    """
    _, observed_raw, calls_raw = captures()
    flat = {tool["name"]: to_declared(tool) for tool in observed_raw["tools"]}
    call_session = {tool["name"]: to_declared(tool) for tool in calls_raw["tools"]}

    for call in calls_raw["calls"]:
        name = call["tool"]
        assert name in flat, f"{name} was called but the tools/list session lacked it"
        assert build_contract(call_session[name]) == build_contract(flat[name])
        # The call-time hash the session recorded is the same value, so the
        # stored evidence and the derivation cannot disagree silently.
        assert call["contract_hash"] == build_contract(call_session[name])


def test_a_capture_without_its_call_session_manifest_is_refused():
    """A capture that cannot supply its own session's manifest stops the build.

    Previously the per-call manifest was taken from the tools/list session
    whatever the call session had served. A server may vary its declaration per
    session, so that could assert a contract the call never ran under; the
    fallback is now a refusal to derive, not a guess.
    """
    import pytest

    declared_raw, observed_raw, calls_raw = captures()
    stripped = {key: value for key, value in calls_raw.items() if key != "tools"}
    with pytest.raises(SystemExit, match="call-session manifests"):
        build_pair(declared_raw, observed_raw, stripped, PACKAGE, DECLARED_VERSION)


def test_the_pair_is_exactly_what_the_captures_derive():
    """The pair is a view of the captures, not a hand-maintained document.

    Both sides are regenerated here by the same function the capture script and
    `examples/rebuild_pair.py` use, so an edit made directly to a pair file
    fails this test rather than quietly becoming evidence.
    """
    declared_raw, observed_raw, calls_raw = captures()
    declared, observed = example_pair()
    assert (declared, observed) == build_pair(
        declared_raw, observed_raw, calls_raw, PACKAGE, DECLARED_VERSION
    )


def test_the_capture_is_self_describing_about_its_recipe():
    """The recipe travels next to the hashes it produced, in every artifact."""
    declared_raw, observed_raw, calls_raw = captures()
    declared, observed = example_pair()

    assert calls_raw["contract_recipe"] == CONTRACT_RECIPE_CURRENT
    assert declared["contract_recipe"] == CONTRACT_RECIPE_CURRENT
    assert observed["contract_recipe"] == CONTRACT_RECIPE_CURRENT
    for call in calls_raw["calls"]:
        assert call["contract_recipe"] == CONTRACT_RECIPE_CURRENT
    for observation in observed["observations"]:
        assert observation["contract_recipe"] == CONTRACT_RECIPE_CURRENT
    for tool in declared["tools"]:
        assert tool["contract_recipe"] == CONTRACT_RECIPE_CURRENT


def test_the_example_finds_the_real_contract_mutation():
    declared, observed = example_pair()
    findings, summary = validate_batch(declared, observed)

    assert summary["declared_tools"] == 14
    assert summary["observations"] == 3
    assert summary["findings"] == 3
    assert summary["contract_recipes"] == [CONTRACT_RECIPE_CURRENT]

    assert {f["check"] for f in findings} == {"contract_mutated"}
    assert {f["severity"] for f in findings} == {"medium"}
    assert {f["contract_recipe"] for f in findings} == {CONTRACT_RECIPE_CURRENT}
    assert [
        observed["observations"][f["observation_index"] - 1]["tool"] for f in findings
    ] == ["read_text_file", "read_media_file", "get_file_info"]

    declared_raw, observed_raw, _ = captures()
    read_media = next(
        f for f in findings
        if observed["observations"][f["observation_index"] - 1]["tool"]
        == "read_media_file"
    )
    assert read_media["declared_contract"] == build_contract(
        served_tools(declared_raw)["read_media_file"]
    )
    assert read_media["observed_contract"] == build_contract(
        served_tools(observed_raw)["read_media_file"]
    )
    assert read_media["declared_contract"] != read_media["observed_contract"]


def test_recipe_2_was_required_to_see_two_of_the_three_mutations():
    """Two of the three findings are changes recipe 1 signed off as healthy.

    The 2026.8.31 release added an ``openWorldHint`` annotation to every tool.
    That leaves ``read_text_file`` and ``get_file_info`` byte-identical under
    recipe 1 while their contracts genuinely moved - which is the argument for
    the wider recipe, made by the example rather than by description.
    """
    declared_raw, observed_raw, _ = captures()
    for name in ("read_text_file", "get_file_info"):
        old = served_tools(declared_raw)[name]
        new = served_tools(observed_raw)[name]

        assert build_contract(old, "1") == build_contract(new, "1")
        assert build_contract(old, "2") != build_contract(new, "2")
        assert old["annotations"] != new["annotations"]

    # The third changed its description and output schema too, so recipe 1 saw
    # that one - it just could not say anything about what the tool returns.
    old = served_tools(declared_raw)["read_media_file"]
    new = served_tools(observed_raw)["read_media_file"]
    assert build_contract(old, "1") != build_contract(new, "1")


def test_only_the_observed_tools_are_annotated():
    """Unannotated calls report unbound_annotation, so the pair binds all three."""
    declared, observed = example_pair()
    annotated = {annotation["tool"] for annotation in declared["annotations"]}
    assert annotated == {observation["tool"] for observation in observed["observations"]}


def test_what_moved_between_the_two_versions():
    """The input schema is identical either side; the description and the
    declared output schema both moved."""
    declared_raw, observed_raw, _ = captures()
    old = served_tools(declared_raw)["read_media_file"]
    new = served_tools(observed_raw)["read_media_file"]
    raw_old = {tool["name"]: tool for tool in declared_raw["tools"]}["read_media_file"]
    raw_new = {tool["name"]: tool for tool in observed_raw["tools"]}["read_media_file"]

    assert old["input_schema"] == new["input_schema"]
    assert old["description"] != new["description"]
    assert old["output_schema"] == raw_old["outputSchema"]
    assert new["output_schema"] == raw_new["outputSchema"]
    assert old["output_schema"] != new["output_schema"]


def test_recipe_1_was_blind_to_an_output_schema_only_change():
    """The hole issue #23 described, pinned deliberately.

    Recipe 1 folds four fields, so a server that changes only what it returns
    keeps the same contract hash and the tool reports healthy. This is the
    reason recipe 2 exists, and it stays asserted so the gap cannot quietly
    reappear as a "fix" that weakens the contract again.
    """
    declared_raw, _, _ = captures()
    old = served_tools(declared_raw)["read_media_file"]
    changed_output = dict(old, output_schema={"type": "object", "changed": True})

    assert build_contract(changed_output, "1") == build_contract(old, "1")
    assert build_contract(changed_output, "2") != build_contract(old, "2")


def test_recipe_2_hashes_the_declared_output_schema():
    declared_raw, _, _ = captures()
    old = served_tools(declared_raw)["read_media_file"]

    payload = contract_payload(old, "2")
    assert list(payload) == [
        "name",
        "description",
        "input_schema",
        "permissions",
        "output_schema",
        "annotations",
    ]
    assert payload["output_schema"] == old["output_schema"]
    assert build_contract(old, "2") == fingerprint(payload)


def test_recipe_2_hashes_the_annotation_hints():
    """A tool's annotation hints are part of its contract, not a footnote."""
    declared_raw, _, _ = captures()
    old = served_tools(declared_raw)["create_directory"]
    assert old["annotations"], "the capture should carry annotation hints"

    hinted = dict(old, annotations=dict(old["annotations"], destructiveHint=True))
    assert build_contract(hinted, "2") != build_contract(old, "2")
    assert build_contract(hinted, "1") == build_contract(old, "1")


def test_a_single_tool_can_opt_out_of_the_manifest_recipe():
    declared_raw, _, _ = captures()
    tool = served_tools(declared_raw)["read_text_file"]
    legacy = dict(tool, contract_recipe="1")
    assert build_contract(legacy) == build_contract(tool, "1")
    assert build_contract(legacy) != build_contract(tool, "2")


def test_the_pair_runs_through_the_cli(tmp_path, capsys):
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
    assert "contract_recipe" not in capsys.readouterr().err

    ledger = load_json(str(out))
    assert ledger["version"] == "0.3"
    report = ledger["blocks"][2]["record"]
    assert report["summary"]["findings"] == 3
    assert report["summary"]["contract_recipes"] == [CONTRACT_RECIPE_CURRENT]
    assert {f["check"] for f in report["findings"]} == {"contract_mutated"}

    head = ledger["blocks"][-1]["hash"]
    assert main(["verify", "--ledger", str(out), "--expected-head", head]) == 0
    assert f"contract recipes: {CONTRACT_RECIPE_CURRENT}" in capsys.readouterr().out
