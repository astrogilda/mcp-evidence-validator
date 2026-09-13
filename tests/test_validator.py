"""Validator end-to-end tests (declared vs observed)."""

import json

from mcp_evidence_validator import validate_batch
from mcp_evidence_validator.cli import main
from mcp_evidence_validator.fingerprint import fingerprint
from mcp_evidence_validator.validator import build_contract, contract_payload

DECLARED = {
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
                    "days": {"type": "integer", "minimum": 1, "maximum": 7},
                },
                "required": ["city"],
            },
            "permissions": ["read:weather"],
        }
    ],
    "annotations": [
        {
            "tool": "get_forecast",
            "statement": "read-only forecast access",
            "bound_contract": None,  # filled below via helper
        }
    ],
}


def with_bound_annotation(contract: str) -> dict:
    d = json.loads(json.dumps(DECLARED))
    d["annotations"][0]["bound_contract"] = contract
    return d


def make_observed(entries) -> dict:
    return {"server": "fictional-weather", "observations": entries}


def test_clean_batch_no_findings():
    from mcp_evidence_validator.validator import build_contract

    decl = with_bound_annotation(build_contract(DECLARED["tools"][0]))
    obs = make_observed(
        [
            {
                "index": 1,
                "observed_at": "2026-08-02T12:00:00Z",
                "tool": "get_forecast",
                "args": {"city": "Townsville", "days": 3},
                "contract_hash": build_contract(DECLARED["tools"][0]),
            }
        ]
    )
    findings, summary = validate_batch(decl, obs)
    assert findings == []
    assert summary["declared_tools"] == 1
    assert summary["observations"] == 1


def test_unknown_tool_finding():
    obs = make_observed(
        [
            {
                "index": 1,
                "observed_at": "2026-08-02T12:00:00Z",
                "tool": "delete_everything",
                "args": {},
            }
        ]
    )
    findings, _ = validate_batch(DECLARED, obs)
    assert findings[0]["check"] == "unknown_tool"
    assert findings[0]["severity"] == "high"


def test_scope_violation_finding():
    obs = make_observed(
        [
            {
                "index": 2,
                "observed_at": "2026-08-02T12:05:00Z",
                "tool": "get_forecast",
                "args": {"city": "Townsville", "admin_token": "redacted"},
            }
        ]
    )
    findings, _ = validate_batch(DECLARED, obs)
    assert any(f["check"] == "scope_violation" for f in findings)


def test_contract_mutated_finding():
    obs = make_observed(
        [
            {
                "index": 3,
                "observed_at": "2026-08-02T12:10:00Z",
                "tool": "get_forecast",
                "args": {"city": "Townsville"},
                "contract_hash": "sha256:" + "1" * 64,
            }
        ]
    )
    findings, _ = validate_batch(DECLARED, obs)
    assert any(f["check"] == "contract_mutated" for f in findings)


def test_cli_validate_and_verify(tmp_path):
    declared = tmp_path / "declared.json"
    observed = tmp_path / "observed.json"
    out = tmp_path / "evidence.json"
    declared.write_text(json.dumps(DECLARED))
    observed.write_text(json.dumps(make_observed([])))

    rc = main(
        ["validate", "--declared", str(declared), "--observed", str(observed), "--out", str(out)]
    )
    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["ledger"] == "mcp-evidence-validator"

    head = json.loads(out.read_text())["blocks"][-1]["hash"]
    rc = main(["verify", "--ledger", str(out), "--expected-head", head])
    assert rc == 0


def test_cli_verify_detects_tamper(tmp_path):
    from mcp_evidence_validator.cli import load_json

    declared = tmp_path / "declared.json"
    observed = tmp_path / "observed.json"
    out = tmp_path / "evidence.json"
    declared.write_text(json.dumps(DECLARED))
    observed.write_text(json.dumps(make_observed([])))
    main(["validate", "--declared", str(declared), "--observed", str(observed), "--out", str(out)])

    head = load_json(str(out))["blocks"][-1]["hash"]
    data = load_json(str(out))
    data["blocks"][0]["record"]["server"] = "tampered"
    out.write_text(json.dumps(data))

    rc = main(["verify", "--ledger", str(out), "--expected-head", head])
    assert rc != 0


def test_cli_version():
    try:
        rc = main(["--version"])
        assert rc in (0, 2)  # argparse exits via SystemExit(0) normally
    except SystemExit as exc:
        assert exc.code == 0


def test_a_declaration_that_states_no_recipe_is_recipe_1():
    """Legacy declarations keep hashing exactly as they did before 0.4.0.

    Every ledger issued before the recipe existed carries four-field contract
    hashes, and those ledgers still have to verify. So the default is the legacy
    recipe, not the current one - new declarations opt up by stating it.
    """
    tool = DECLARED["tools"][0]
    payload = contract_payload(tool)
    assert list(payload) == ["name", "description", "input_schema", "permissions"]
    assert build_contract(tool) == build_contract(tool, "1") == fingerprint(payload)


def test_recipe_2_covers_what_recipe_1_could_not():
    tool = dict(DECLARED["tools"][0], contract_recipe="2")
    payload = contract_payload(tool)
    assert list(payload) == [
        "name",
        "description",
        "input_schema",
        "permissions",
        "output_schema",
        "annotations",
    ]

    only_output_changed = dict(tool, output_schema={"type": "string"})
    assert build_contract(only_output_changed, "1") == build_contract(tool, "1")
    assert build_contract(only_output_changed, "2") != build_contract(tool, "2")

    only_hint_changed = dict(tool, annotations={"destructiveHint": True})
    assert build_contract(only_hint_changed, "1") == build_contract(tool, "1")
    assert build_contract(only_hint_changed, "2") != build_contract(tool, "2")


def test_an_unknown_recipe_is_rejected_rather_than_guessed():
    import pytest

    obs = make_observed([])
    with pytest.raises(ValueError, match="unknown contract recipe"):
        validate_batch(dict(DECLARED, contract_recipe="3"), obs)
    with pytest.raises(ValueError, match="unknown contract recipe"):
        build_contract(DECLARED["tools"][0], "9")


def test_a_recipe_mismatch_is_reported_not_guessed():
    """Two different recipes make a comparison meaningless, so it is refused.

    Reporting drift here would be a false verdict: the hashes differ because
    they were computed differently, not because the server changed.
    """
    tool = dict(DECLARED["tools"][0], contract_recipe="2")
    decl = {
        "server": DECLARED["server"],
        "declared_at": DECLARED["declared_at"],
        "contract_recipe": "2",
        "tools": [tool],
        "annotations": [
            {
                "tool": "get_forecast",
                "statement": "read-only forecast access",
                "bound_contract": build_contract(tool, "2"),
            }
        ],
    }
    obs = {
        "server": DECLARED["server"],
        "contract_recipe": "1",
        "observations": [
            {
                "index": 1,
                "observed_at": "2026-08-02T12:00:00Z",
                "tool": "get_forecast",
                "args": {"city": "Townsville"},
                # Recorded under the legacy recipe, as a pre-0.4.0 observer would.
                "contract_hash": build_contract(tool, "1"),
                "contract_recipe": "1",
            }
        ],
    }

    findings, summary = validate_batch(decl, obs)
    assert [f["check"] for f in findings] == ["recipe_mismatch"]
    assert findings[0]["severity"] == "high"
    assert findings[0]["declared_recipe"] == "2"
    assert findings[0]["observed_recipe"] == "1"
    assert summary["contract_recipes"] == ["2"]


def test_cli_reports_the_recipe_the_evidence_carries(tmp_path, capsys):
    tool = dict(DECLARED["tools"][0], contract_recipe="2")
    declared = {
        "server": DECLARED["server"],
        "declared_at": DECLARED["declared_at"],
        "contract_recipe": "2",
        "tools": [tool],
        "annotations": [
            {
                "tool": "get_forecast",
                "statement": "read-only forecast access",
                "bound_contract": build_contract(tool, "2"),
            }
        ],
    }
    observed = {
        "server": DECLARED["server"],
        "contract_recipe": "2",
        "observations": [
            {
                "index": 1,
                "observed_at": "2026-08-02T12:00:00Z",
                "tool": "get_forecast",
                "args": {"city": "Townsville"},
                "contract_hash": build_contract(tool, "2"),
                "contract_recipe": "2",
            }
        ],
    }

    declared_path = tmp_path / "declared.json"
    observed_path = tmp_path / "observed.json"
    out = tmp_path / "evidence.json"
    declared_path.write_text(json.dumps(declared))
    observed_path.write_text(json.dumps(observed))

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
    report_out = capsys.readouterr().out
    assert '"contract_recipes"' in report_out
    assert "contract_recipes" not in capsys.readouterr().err

    ledger = json.loads(out.read_text())
    assert ledger["blocks"][2]["record"]["summary"]["contract_recipes"] == ["2"]

    head = ledger["blocks"][-1]["hash"]
    assert main(["verify", "--ledger", str(out), "--expected-head", head]) == 0
    assert "contract recipes: 2" in capsys.readouterr().out


def test_cli_warns_when_a_declaration_states_no_recipe(tmp_path, capsys):
    declared = tmp_path / "declared.json"
    observed = tmp_path / "observed.json"
    out = tmp_path / "evidence.json"
    declared.write_text(json.dumps(DECLARED))
    observed.write_text(json.dumps(make_observed([])))

    main(["validate", "--declared", str(declared), "--observed", str(observed), "--out", str(out)])
    captured = capsys.readouterr()
    assert "states no contract_recipe" in captured.err
    assert "recipe 1" in captured.err
