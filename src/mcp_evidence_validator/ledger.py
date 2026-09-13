"""Evidence ledger: append-only SHA-256 hash chain, verified against an
externally held head.

block_n = sha256(prev_hash + canonical_json(record_n))

A hash chain proves ordering to whoever holds the file. It proves nothing to
anyone else, because an editor who can change a record can also replay the
chain over the change, drop the last block, or write any value into the
published ``prev_hash`` and ``index`` fields. Detection therefore requires two
things the chain cannot supply on its own: a head digest committed somewhere
the editor cannot reach, and a walk that reads the fields the format
publishes. ``verify`` takes the expected head as an argument for that reason.
"""

import hashlib
import json
from typing import Any

from .fingerprint import canonical_json

GENESIS = "sha256:" + ("0" * 64)

#: Passed as ``expected_head`` by a caller that deliberately has no external
#: commitment to the head. It buys chain self-consistency and nothing more, and
#: the command-line interface has no way to produce it.
UNANCHORED = "unanchored"

#: The ledger *format* version. It is independent of ``CONTRACT_RECIPE_*``: the
#: format says how blocks are shaped, the records say how their contract hashes
#: were computed. A ledger written under 0.2 stays verifiable as-is - the chain
#: covers its own records, and those records state what they are.
LEDGER_NAME = "mcp-evidence-validator"
LEDGER_VERSION = "0.3"


class Ledger:
    def __init__(self) -> None:
        self._blocks: list[dict[str, Any]] = []

    @classmethod
    def load(cls, path: str) -> "Ledger":
        led = cls()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("ledger") != LEDGER_NAME:
            raise ValueError(
                f"not a {LEDGER_NAME} ledger (ledger field = {data.get('ledger')!r})"
            )
        led._blocks = data.get("blocks", [])
        return led

    def append(self, record_type: str, record: dict[str, Any]) -> dict[str, Any]:
        prev_hash = self._blocks[-1]["hash"] if self._blocks else GENESIS
        body = canonical_json({"type": record_type, "record": record})
        block_hash = "sha256:" + hashlib.sha256(
            (prev_hash + body).encode("utf-8")
        ).hexdigest()
        block = {
            "index": len(self._blocks),
            "prev_hash": prev_hash,
            "type": record_type,
            "record": record,
            "hash": block_hash,
        }
        self._blocks.append(block)
        return block

    def head(self) -> str:
        """Return the hash of the last block, or GENESIS for an empty ledger."""
        return self._blocks[-1]["hash"] if self._blocks else GENESIS

    def verify(self, expected_head: str) -> list[str]:
        """Return a list of problem messages (empty when the ledger is sound).

        ``expected_head`` is the head digest recorded outside this file, as
        printed by ``validate``. Pass :data:`UNANCHORED` to skip that check and
        get chain self-consistency alone.
        """
        problems = []
        prev_hash = GENESIS
        for position, block in enumerate(self._blocks):
            if block["index"] != position:
                problems.append(
                    f"block at position {position}: index field says {block['index']!r}"
                )
            if block["prev_hash"] != prev_hash:
                problems.append(
                    f"block at position {position}: prev_hash field says "
                    f"{block['prev_hash']!r}, chain walk says {prev_hash!r}"
                )
            body = canonical_json({"type": block["type"], "record": block["record"]})
            expected = "sha256:" + hashlib.sha256(
                (prev_hash + body).encode("utf-8")
            ).hexdigest()
            if block["hash"] != expected:
                problems.append(f"block at position {position}: hash mismatch")
            prev_hash = block["hash"]
        if expected_head != UNANCHORED and prev_hash != expected_head:
            problems.append(
                f"head mismatch: ledger head {prev_hash!r}, expected {expected_head!r}"
            )
        return problems

    def dump(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                {"ledger": LEDGER_NAME, "version": LEDGER_VERSION, "blocks": self._blocks},
                fh,
                indent=2,
            )

    def __len__(self) -> int:
        return len(self._blocks)

    def __iter__(self):
        return iter(self._blocks)
