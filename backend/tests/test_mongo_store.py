"""Tests for the durable session-snapshot store (`services/mongo_store.py`).

Covers:
- the DISABLED / no-op path (no URI, or driver absent) — never errors;
- a snapshot round-trip (list / get / put / delete + history) driven by a FAKE
  in-memory async Mongo client (NO live Atlas needed);
- the moved Redis id-listing route (`GET /api/users/{user_id}/sessions`).
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import main
from models.sessions import SessionSnapshot
from services.mongo_store import SessionSnapshotStore, get_snapshot_store


# --------------------------------------------------------------------------
# A minimal in-memory fake of the pymongo AsyncMongoClient surface we use.
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction=1):
        self._docs.sort(key=lambda d: d.get(key) or "", reverse=direction < 0)
        return self

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield dict(d)

        return gen()


class _FakeCollection:
    def __init__(self):
        self._docs: dict[str, dict] = {}
        self._auto = 0

    async def create_index(self, *a, **k):
        return "idx"

    def _matches(self, doc, query):
        return all(doc.get(k) == v for k, v in query.items())

    def find(self, query=None):
        query = query or {}
        docs = [dict(d) for d in self._docs.values() if self._matches(d, query)]
        return _FakeCursor(docs)

    async def find_one(self, query, projection=None):
        for d in self._docs.values():
            if self._matches(d, query):
                return dict(d)
        return None

    async def replace_one(self, query, doc, upsert=False):
        key = doc.get("_id") or query.get("_id")
        self._docs[key] = dict(doc)

    async def insert_one(self, doc):
        self._auto += 1
        key = doc.get("_id") or f"auto-{self._auto}"
        stored = dict(doc)
        stored.setdefault("_id", key)
        self._docs[key] = stored

    async def delete_one(self, query):
        for k, d in list(self._docs.items()):
            if self._matches(d, query):
                del self._docs[k]
                return


class _FakeDB:
    def __init__(self):
        self._collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self._collections.setdefault(name, _FakeCollection())


class _FakeClient:
    def __init__(self):
        self._dbs: dict[str, _FakeDB] = {}

    def __getitem__(self, name):
        return self._dbs.setdefault(name, _FakeDB())

    def close(self):
        return None


# --------------------------------------------------------------------------
# Disabled / no-op path
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_store_is_noop():
    store = SessionSnapshotStore(uri="")  # no URI -> disabled
    assert store.enabled is False
    assert await store.list_summaries(None) == []
    assert await store.get("anything") is None
    assert await store.delete("anything") is None
    assert await store.get_history("anything") == []
    # put still returns a coherent summary without raising
    summary = await store.put(SessionSnapshot(sessionId="s1", rawSequence="ACGT"))
    assert summary.sessionId == "s1"
    assert summary.length == 4


# --------------------------------------------------------------------------
# Snapshot round-trip against the fake client
# --------------------------------------------------------------------------


@pytest.fixture
def fake_store():
    return SessionSnapshotStore(client=_FakeClient(), db_name="evo_test")


@pytest.mark.asyncio
async def test_put_get_roundtrip(fake_store):
    assert fake_store.enabled is True
    snap = SessionSnapshot(
        sessionId="sess-1",
        title="BDNF enhancer",
        kind="design",
        rawSequence="ACGTACGT",
        candidates=[{"id": 0, "sequence": "ACGT"}, {"id": 1, "sequence": "TTTT"}],
        activeCandidateId=1,
        chatMessages=[{"role": "user", "content": "hi"}],
    )
    summary = await fake_store.put(snap)
    assert summary.sessionId == "sess-1"
    assert summary.candidateCount == 2
    assert summary.length == 8
    assert summary.updatedAt is not None

    got = await fake_store.get("sess-1")
    assert got is not None
    assert got.sessionId == "sess-1"
    assert got.title == "BDNF enhancer"
    assert got.activeCandidateId == 1
    assert got.chatMessages == [{"role": "user", "content": "hi"}]
    # createdAt/updatedAt stamped
    assert got.createdAt is not None


@pytest.mark.asyncio
async def test_list_and_delete(fake_store):
    await fake_store.put(SessionSnapshot(sessionId="a", userId="u1", rawSequence="AC"))
    await fake_store.put(SessionSnapshot(sessionId="b", userId="u2", rawSequence="ACG"))

    all_summaries = await fake_store.list_summaries(None)
    ids = {s.sessionId for s in all_summaries}
    assert ids == {"a", "b"}

    filtered = await fake_store.list_summaries("u1")
    assert [s.sessionId for s in filtered] == ["a"]

    await fake_store.delete("a")
    remaining = await fake_store.list_summaries(None)
    assert {s.sessionId for s in remaining} == {"b"}


@pytest.mark.asyncio
async def test_createdat_preserved_on_update(fake_store):
    s1 = await fake_store.put(SessionSnapshot(sessionId="x", rawSequence="AC"))
    first = await fake_store.get("x")
    created = first.createdAt
    # second put should keep original createdAt
    await fake_store.put(SessionSnapshot(sessionId="x", rawSequence="ACGTACGT"))
    second = await fake_store.get("x")
    assert second.createdAt == created
    assert len(second.rawSequence) == 8


@pytest.mark.asyncio
async def test_history(fake_store):
    await fake_store.record_run("sess-h", kind="design", summary="run1")
    await fake_store.record_run("sess-h", kind="edit", summary="run2")
    history = await fake_store.get_history("sess-h")
    assert len(history) == 2
    summaries = {h["summary"] for h in history}
    assert summaries == {"run1", "run2"}


# --------------------------------------------------------------------------
# Endpoint / route tests (disabled store => safe defaults)
# --------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(main.app)


def test_moved_redis_route(client):
    """The Redis id-listing route moved to /api/users/{user_id}/sessions."""
    resp = client.get("/api/users/nobody/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "nobody"
    assert body["count"] == 0
    assert body["sessions"] == []


def test_sessions_endpoints_degrade(client):
    """With Mongo disabled (default in tests) the snapshot endpoints are safe."""
    # list -> empty
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert r.json() == {"sessions": []}

    # get missing -> 404
    r = client.get("/api/sessions/does-not-exist")
    assert r.status_code == 404

    # put -> returns a summary even when disabled
    r = client.put("/api/sessions/s-put", json={"rawSequence": "ACGT", "title": "t"})
    assert r.status_code == 200
    assert r.json()["sessionId"] == "s-put"
    assert r.json()["length"] == 4

    # delete -> ok
    r = client.delete("/api/sessions/s-put")
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    # history -> empty
    r = client.get("/api/history/s-put")
    assert r.status_code == 200
    assert r.json()["runs"] == []
