"""Ledger integrity tests."""

import json

import pytest

from mcp_evidence_validator import GENESIS, UNANCHORED, Ledger


def test_genesis_constant():
    assert GENESIS == "sha256:" + "0" * 64


def test_append_chains_hashes():
    led = Ledger()
    led.append("declaration", {"a": 1})
    led.append("observation", {"b": 2})
    assert len(led) == 2
    assert led.verify(UNANCHORED) == []
    assert led._blocks[0]["prev_hash"] == GENESIS
    assert led._blocks[1]["prev_hash"] == led._blocks[0]["hash"]


def test_tamper_detected():
    led = Ledger()
    led.append("declaration", {"tool": "x"})
    led.append("report", {"findings": 0})
    assert led.verify(UNANCHORED) == []
    # Tamper with an early block
    led._blocks[0]["record"]["tool"] = "y"
    problems = led.verify(UNANCHORED)
    assert problems, "tampering must be detected"


def test_mid_chain_tamper_detected():
    led = Ledger()
    for i in range(4):
        led.append("observation", {"i": i})
    assert led.verify(UNANCHORED) == []
    led._blocks[2]["record"]["i"] = 999
    assert led.verify(UNANCHORED)


def test_roundtrip_dump_load(tmp_path):
    led = Ledger()
    led.append("declaration", {"tools": []})
    out = tmp_path / "evidence.json"
    led.dump(str(out))
    data = json.loads(out.read_text())
    assert data["ledger"] == "mcp-evidence-validator"
    # Ledger format 0.3. The chain, block shape and dump/load round trip are
    # unchanged; the bump records that the records a 0.3 validator writes carry
    # a contract recipe next to every contract hash. A 0.2 ledger still loads
    # and still verifies - nothing about the old format was reinterpreted.
    assert data["version"] == "0.3"
    loaded = Ledger.load(str(out))
    assert len(loaded) == 1
    assert loaded.verify(UNANCHORED) == []


def test_load_rejects_foreign_ledger(tmp_path):
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({"ledger": "other-thing", "blocks": []}))
    with pytest.raises(ValueError):
        Ledger.load(str(foreign))
