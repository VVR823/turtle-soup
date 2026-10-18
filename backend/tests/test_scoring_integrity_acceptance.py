"""Acceptance: damaged persisted evidence cannot produce or mutate a score."""
from contextlib import closing
import json

import pytest

from app import baselines, db
from app.runtime import runtime_context
from .test_evaluation_snapshot import api, record, reveal, start


def persisted_game(conn, sid):
    return {
        "session": tuple(conn.execute("SELECT status,questions_asked,row_version FROM sessions WHERE id=?", (sid,)).fetchone()),
        "turns": [tuple(row) for row in conn.execute("SELECT * FROM turns WHERE session_id=? ORDER BY rowid", (sid,))],
        "messages": [tuple(row) for row in conn.execute("SELECT * FROM messages WHERE session_id=? ORDER BY id", (sid,))],
        "evaluations": [tuple(row) for row in conn.execute("SELECT * FROM evaluations WHERE session_id=?", (sid,))],
    }


@pytest.mark.parametrize("damage", [
    "unlinked_message", "turn_rule_mismatch", "legacy_non_object",
    "legacy_extra_field", "legacy_boolean_schema", "changed_host_reply",
])
def test_corrupted_evidence_refuses_scoring_and_preserves_game(api, damage):
    sid = start(api)
    owner = record(api, sid)
    with runtime_context(api[0].state.runtime), closing(db._connect()) as conn, conn:
        if damage == "unlinked_message":
            conn.execute("UPDATE messages SET turn_id=NULL WHERE turn_id=? AND role='host'", (owner.turnId,))
        elif damage == "turn_rule_mismatch":
            conn.execute("UPDATE turns SET rule_version=? WHERE id=?", ("r1:" + "0" * 64, owner.turnId))
        elif damage == "changed_host_reply":
            conn.execute("UPDATE messages SET content='Synthetic altered host reply' WHERE turn_id=? AND role='host'", (owner.turnId,))
        else:
            marker = {"schemaVersion": 1, "source": "legacy", "answerVerified": False}
            if damage == "legacy_non_object":
                marker = []
            elif damage == "legacy_extra_field":
                marker["unexpected"] = "synthetic"
            else:
                marker["schemaVersion"] = True
            conn.execute("UPDATE turns SET engine_version='legacy-unversioned',result_json=?,response_json=NULL WHERE id=?",
                         (baselines.canonical_json(marker), owner.turnId))
        before = persisted_game(conn, sid)
        assert before["session"][0] == "playing" and before["session"][1] == 1
        assert before["evaluations"] == []

    for _ in range(2):
        response = reveal(api, sid)
        assert response.status_code == 503, response.text
        body = response.json()
        assert body["code"] == "snapshot_unavailable"
        assert not {"score", "completion", "verifiedCoverage", "bottom"} & body.keys()
        assert "Synthetic altered" not in json.dumps(body)
        with runtime_context(api[0].state.runtime), closing(db._connect()) as conn:
            assert persisted_game(conn, sid) == before
