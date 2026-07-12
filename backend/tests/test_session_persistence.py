"""Session persistence + design-run history endpoints.

These run with MongoDB disabled (no MONGODB_URI), so they assert the
graceful-degradation contract: endpoints respond normally and report that
persistence is off rather than erroring. Live read/write behaviour is covered
separately against a real cluster.
"""

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestSessionSnapshotAPI:
    def test_list_sessions_empty_when_disabled(self, client):
        r = client.get("/api/sessions")
        assert r.status_code == 200
        body = r.json()
        assert body["sessions"] == []
        assert body["count"] == 0
        assert body["persistence_enabled"] is False

    def test_get_missing_snapshot_is_404(self, client):
        r = client.get("/api/sessions/does-not-exist")
        assert r.status_code == 404

    def test_put_snapshot_is_accepted_but_not_persisted_when_disabled(self, client):
        snapshot = {
            "sessionId": "unit-sess-1",
            "title": "Design a promoter",
            "kind": "design",
            "rawSequence": "ATGCATGC",
            "candidates": [{"id": 0, "sequence": "ATGC"}],
            "chatMessages": [{"role": "user", "content": "hi"}],
            "somethingNew": {"v": 1},  # unknown field must be tolerated
        }
        r = client.put("/api/sessions/unit-sess-1", json=snapshot)
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == "unit-sess-1"
        assert body["persisted"] is False  # Mongo disabled → no-op, no error

    def test_delete_snapshot_when_disabled(self, client):
        r = client.delete("/api/sessions/unit-sess-1")
        assert r.status_code == 200
        assert r.json()["deleted"] is False

    def test_put_rejects_malformed_body(self, client):
        # candidates must be a list; a string should fail validation (422).
        r = client.put("/api/sessions/bad", json={"candidates": "not-a-list"})
        assert r.status_code == 422


class TestDesignRunHistoryAPI:
    def test_history_empty_when_disabled(self, client):
        r = client.get("/api/history/whatever")
        assert r.status_code == 200
        body = r.json()
        assert body["runs"] == []
        assert body["count"] == 0
        assert body["persistence_enabled"] is False

    def test_design_returns_run_id(self, client):
        r = client.post("/api/design", json={"goal": "Design a BDNF enhancer", "session_id": "run-id-sess"})
        assert r.status_code == 202
        body = r.json()
        assert body["session_id"] == "run-id-sess"
        assert isinstance(body.get("run_id"), str) and body["run_id"]


class TestRelocatedUserSessionsRoute:
    def test_user_sessions_listing_still_works(self, client):
        r = client.get("/api/users/nobody/sessions")
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == "nobody"
        assert body["count"] == 0
        assert body["sessions"] == []
