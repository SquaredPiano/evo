"""Durable session-snapshot store backed by MongoDB Atlas.

This is the *durable* persistence layer for resumable sessions, distinct from
the Redis hot-store (`services/session_store.py`, `SessionStore`) which binds the
live DNA to the agent. Here we persist the full frontend ``useEvoStore`` snapshot
(see ``models/sessions.py`` and ``docs/session_persistence_interface.md``) so a
session can be listed on the home screen and *resumed* (state restored) rather
than re-run.

Persistence is OPTIONAL and degrades gracefully:
- If ``MONGODB_URI`` is unset, or the ``pymongo`` async driver is not installed,
  the store is DISABLED and every method is a logged no-op (list -> [], get ->
  None, put -> summary echo, delete -> None). ``import main`` must still succeed.
- Any Mongo / network error is caught and logged; it NEVER propagates to a
  request. The app then behaves exactly as it does today (Redis-only).

The ``pymongo`` import is guarded so the module imports even when the driver is
absent (the check venv does not have it).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from config import settings
from models.sessions import SessionSnapshot, SessionSummary

logger = logging.getLogger("evo.mongo_store")

# Guarded import: the driver may be absent (e.g. the check venv). Treat a missing
# driver identically to a missing URI — the store is simply disabled.
try:  # pragma: no cover - trivial import guard
    from pymongo import AsyncMongoClient  # type: ignore
except ImportError:  # pragma: no cover
    AsyncMongoClient = None  # type: ignore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionSnapshotStore:
    """Durable snapshot store. Named ``SessionSnapshotStore`` (NOT ``SessionStore``,
    which is the Redis hot-store) to avoid a collision.

    ``enabled`` is True only when a URI is configured AND the async driver is
    importable. When disabled, every method is a safe, logged no-op.
    """

    SESSIONS_COLLECTION = "sessions"
    RUNS_COLLECTION = "design_runs"

    def __init__(
        self,
        *,
        uri: str | None = None,
        db_name: str | None = None,
        connect_timeout_ms: int | None = None,
        client: Any | None = None,
    ) -> None:
        self._uri = uri if uri is not None else settings.mongodb_uri
        self._db_name = db_name or settings.mongodb_db_name
        self._connect_timeout_ms = (
            connect_timeout_ms
            if connect_timeout_ms is not None
            else settings.mongodb_connect_timeout_ms
        )
        self._client: Any | None = None
        self._index_ready = False

        if client is not None:
            # Injected client (tests / fakes). Considered enabled.
            self._client = client
            self.enabled = True
        elif self._uri and AsyncMongoClient is not None:
            try:
                self._client = AsyncMongoClient(
                    self._uri,
                    serverSelectionTimeoutMS=self._connect_timeout_ms,
                    connectTimeoutMS=self._connect_timeout_ms,
                )
                self.enabled = True
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Mongo client init failed; persistence disabled: %s", exc)
                self._client = None
                self.enabled = False
        else:
            self.enabled = False
            if not self._uri:
                logger.info("MONGODB_URI unset; session persistence disabled (no-op).")
            elif AsyncMongoClient is None:
                logger.info("pymongo not installed; session persistence disabled (no-op).")

    # -- internals ---------------------------------------------------------

    def _db(self) -> Any:
        return self._client[self._db_name]

    def _sessions(self) -> Any:
        return self._db()[self.SESSIONS_COLLECTION]

    def _runs(self) -> Any:
        return self._db()[self.RUNS_COLLECTION]

    async def _ensure_indexes(self) -> None:
        """Best-effort index creation; failure never blocks a request."""
        if self._index_ready or not self.enabled:
            return
        try:
            await self._sessions().create_index("updatedAt")
            await self._sessions().create_index("userId")
            await self._runs().create_index("sessionId")
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Index creation skipped: %s", exc)
        finally:
            # Mark ready regardless so we don't retry on every call.
            self._index_ready = True

    @staticmethod
    def _summary_from_doc(doc: dict[str, Any]) -> SessionSummary:
        candidates = doc.get("candidates") or []
        raw = doc.get("rawSequence") or ""
        return SessionSummary(
            sessionId=doc.get("sessionId") or doc.get("_id") or "",
            title=doc.get("title"),
            kind=doc.get("kind"),
            updatedAt=doc.get("updatedAt"),
            candidateCount=len(candidates) if isinstance(candidates, list) else 0,
            length=len(raw) if isinstance(raw, str) else 0,
            userId=doc.get("userId"),
        )

    # -- public API --------------------------------------------------------

    async def list_summaries(self, user_id: str | None = None) -> list[SessionSummary]:
        if not self.enabled:
            logger.debug("list_summaries no-op (persistence disabled).")
            return []
        try:
            await self._ensure_indexes()
            query: dict[str, Any] = {}
            if user_id:
                query["userId"] = user_id
            cursor = self._sessions().find(query).sort("updatedAt", -1)
            summaries: list[SessionSummary] = []
            async for doc in cursor:
                summaries.append(self._summary_from_doc(doc))
            return summaries
        except Exception as exc:
            logger.warning("list_summaries failed; returning []: %s", exc)
            return []

    async def get(self, session_id: str) -> SessionSnapshot | None:
        if not self.enabled:
            logger.debug("get no-op (persistence disabled).")
            return None
        try:
            doc = await self._sessions().find_one({"_id": session_id})
            if not doc:
                return None
            doc.pop("_id", None)
            return SessionSnapshot(**doc)
        except Exception as exc:
            logger.warning("get(%s) failed; returning None: %s", session_id, exc)
            return None

    async def put(self, snapshot: SessionSnapshot) -> SessionSummary:
        """Upsert a snapshot keyed by ``_id = sessionId``. Stamps timestamps and
        derives summary counts. Returns the summary (echoed even when disabled so
        the caller always gets a consistent shape)."""
        data = snapshot.model_dump(exclude_none=False)
        session_id = data.get("sessionId")
        now = _now_iso()
        data["updatedAt"] = now
        if not data.get("createdAt"):
            data["createdAt"] = now

        if not self.enabled or not session_id:
            if not session_id:
                logger.debug("put no-op: snapshot missing sessionId.")
            else:
                logger.debug("put no-op (persistence disabled).")
            return self._summary_from_doc(data)

        try:
            await self._ensure_indexes()
            existing = await self._sessions().find_one(
                {"_id": session_id}, {"createdAt": 1}
            )
            if existing and existing.get("createdAt"):
                data["createdAt"] = existing["createdAt"]
            stored = dict(data)
            stored["_id"] = session_id
            await self._sessions().replace_one({"_id": session_id}, stored, upsert=True)
            return self._summary_from_doc(data)
        except Exception as exc:
            logger.warning("put(%s) failed; degraded: %s", session_id, exc)
            return self._summary_from_doc(data)

    async def delete(self, session_id: str) -> None:
        if not self.enabled:
            logger.debug("delete no-op (persistence disabled).")
            return None
        try:
            await self._sessions().delete_one({"_id": session_id})
        except Exception as exc:
            logger.warning("delete(%s) failed; ignored: %s", session_id, exc)
        return None

    # -- design-run history (additive, independent of the snapshot contract) --

    async def record_run(
        self,
        session_id: str,
        *,
        kind: str | None = None,
        summary: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or not session_id:
            logger.debug("record_run no-op (disabled or missing sessionId).")
            return None
        try:
            await self._ensure_indexes()
            await self._runs().insert_one(
                {
                    "sessionId": session_id,
                    "kind": kind,
                    "summary": summary,
                    "payload": payload or {},
                    "createdAt": _now_iso(),
                }
            )
        except Exception as exc:
            logger.warning("record_run(%s) failed; ignored: %s", session_id, exc)
        return None

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        if not self.enabled:
            logger.debug("get_history no-op (persistence disabled).")
            return []
        try:
            cursor = self._runs().find({"sessionId": session_id}).sort("createdAt", -1)
            runs: list[dict[str, Any]] = []
            async for doc in cursor:
                doc.pop("_id", None)
                runs.append(doc)
            return runs
        except Exception as exc:
            logger.warning("get_history(%s) failed; returning []: %s", session_id, exc)
            return []

    async def close(self) -> None:
        if self._client is not None:
            try:
                close = getattr(self._client, "close", None)
                if close is not None:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Mongo client close ignored: %s", exc)


# Lazily-constructed module singleton.
_store: SessionSnapshotStore | None = None


def get_snapshot_store() -> SessionSnapshotStore:
    global _store
    if _store is None:
        _store = SessionSnapshotStore()
    return _store
