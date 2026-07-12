"""Durable persistence backend (MongoDB Atlas).

Redis remains the *hot* store for a live pipeline run (fast, TTL'd, pub/sub).
MongoDB is the *durable* store: it records each design run — critically the
**prompt/goal** that produced it, which Redis never kept — so a session and its
prompt history survive process restarts and TTL expiry. That durable history is
what the "reprompt" feature builds on: a new goal can be chained to a prior run.

Design contract: persistence is **optional and best-effort**. If no URI is
configured, or Atlas is unreachable (e.g. the connecting IP is not on the
cluster's Network Access allowlist), the store reports itself disabled, every
call becomes a logged no-op, and the rest of the app behaves exactly as it did
before (Redis-only). A persistence failure must NEVER turn into a request error.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pymongo import AsyncMongoClient, ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import PyMongoError

logger = logging.getLogger("evo")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MongoStore:
    """Best-effort durable store. All ops degrade to no-ops when unavailable."""

    def __init__(self, *, uri: str, db_name: str, connect_timeout_ms: int = 5000) -> None:
        self._uri = uri
        self._db_name = db_name
        self._connect_timeout_ms = connect_timeout_ms
        # Configured means a URI is present; ready means we actually connected.
        self.configured = bool(uri)
        self._ready = False
        self._client: AsyncMongoClient | None = None
        self._db: Any = None

    # ── lifecycle ──────────────────────────────────────────────────────────
    async def connect(self) -> bool:
        """Attempt a connection. Returns True only if Atlas answered a ping.

        Never raises — a failure here just leaves the store disabled so the app
        keeps running on Redis alone.
        """
        if not self.configured:
            logger.info("MongoDB persistence disabled (no MONGODB_URI configured).")
            return False
        try:
            self._client = AsyncMongoClient(
                self._uri,
                serverSelectionTimeoutMS=self._connect_timeout_ms,
                connectTimeoutMS=self._connect_timeout_ms,
                appname="evo-backend",
            )
            await self._client.admin.command("ping")
            self._db = self._client[self._db_name]
            await self._ensure_indexes()
            self._ready = True
            logger.info("MongoDB persistence connected (db=%s).", self._db_name)
            return True
        except PyMongoError as exc:
            self._ready = False
            logger.warning(
                "MongoDB unreachable — running Redis-only, persistence is a no-op. "
                "If using Atlas, add this host's IP to Network Access. Detail: %s",
                exc,
            )
            return False
        except Exception:  # defensive: DNS/SSL/etc. must not crash startup
            self._ready = False
            logger.warning("MongoDB connection failed unexpectedly — persistence disabled.", exc_info=True)
            return False

    async def _ensure_indexes(self) -> None:
        await self._db.design_runs.create_index([("session_id", ASCENDING), ("created_at", ASCENDING)])
        await self._db.design_runs.create_index([("parent_run_id", ASCENDING)])
        await self._db.design_runs.create_index([("user_id", ASCENDING)])
        await self._db.sessions.create_index([("user_id", ASCENDING)])
        await self._db.experiment_versions.create_index(
            [("session_id", ASCENDING), ("candidate_id", ASCENDING)]
        )
        await self._db.experiment_versions.create_index([("version_id", ASCENDING)], unique=True)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:  # noqa: BLE001 - shutdown best-effort
                pass

    @property
    def ready(self) -> bool:
        return self._ready

    async def ping(self) -> bool:
        if not self._ready or self._client is None:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:  # noqa: BLE001
            return False

    # ── design runs (the reprompt history spine) ────────────────────────────
    async def save_design_run(
        self,
        *,
        run_id: str,
        session_id: str,
        goal: str,
        user_id: str | None = None,
        parent_run_id: str | None = None,
        run_profile: str = "live",
        truth_mode: str = "real_only",
        num_candidates: int = 0,
        target_length: int | None = None,
        seed_sequence: str | None = None,
    ) -> None:
        """Record a run at submit time (status='running'). Idempotent by run_id."""
        if not self._ready:
            return
        doc = {
            "_id": run_id,
            "run_id": run_id,
            "session_id": session_id,
            "user_id": user_id,
            "goal": goal,
            "parent_run_id": parent_run_id,
            "run_profile": run_profile,
            "truth_mode": truth_mode,
            "num_candidates": num_candidates,
            "target_length": target_length,
            "seed_sequence": seed_sequence,
            "design_type": None,
            "status": "running",
            "candidates": [],
            "completed_candidates": 0,
            "failed_candidates": 0,
            "created_at": _utcnow_iso(),
            "completed_at": None,
        }
        try:
            await self._db.design_runs.replace_one({"_id": run_id}, doc, upsert=True)
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.save_design_run failed for %s", run_id, exc_info=True)

    async def update_design_run(self, run_id: str, patch: dict[str, Any]) -> None:
        if not self._ready or not patch:
            return
        try:
            await self._db.design_runs.update_one({"_id": run_id}, {"$set": patch})
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.update_design_run failed for %s", run_id, exc_info=True)

    async def complete_design_run(
        self,
        run_id: str,
        *,
        candidates: list[dict[str, Any]],
        completed_candidates: int,
        failed_candidates: int,
        design_type: str | None = None,
    ) -> None:
        patch: dict[str, Any] = {
            "status": "complete",
            "candidates": candidates,
            "completed_candidates": completed_candidates,
            "failed_candidates": failed_candidates,
            "completed_at": _utcnow_iso(),
        }
        if design_type is not None:
            patch["design_type"] = design_type
        await self.update_design_run(run_id, patch)

    async def get_session_runs(self, session_id: str) -> list[dict[str, Any]]:
        """Return the run thread for a session, oldest first (empty when disabled)."""
        if not self._ready:
            return []
        try:
            cursor = self._db.design_runs.find(
                {"session_id": session_id},
                projection={"seed_sequence": 0},
            ).sort("created_at", ASCENDING)
            runs = [self._clean(doc) async for doc in cursor]
            return runs
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.get_session_runs failed for %s", session_id, exc_info=True)
            return []

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        if not self._ready:
            return None
        try:
            doc = await self._db.design_runs.find_one({"_id": run_id})
            return self._clean(doc) if doc else None
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.get_run failed for %s", run_id, exc_info=True)
            return None

    # ── sessions index ──────────────────────────────────────────────────────
    async def upsert_session(self, *, session_id: str, user_id: str | None, goal: str) -> None:
        if not self._ready:
            return
        now = _utcnow_iso()
        try:
            await self._db.sessions.find_one_and_update(
                {"_id": session_id},
                {
                    "$set": {"user_id": user_id, "last_goal": goal, "last_run_at": now},
                    "$setOnInsert": {"session_id": session_id, "created_at": now},
                    "$inc": {"run_count": 1},
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.upsert_session failed for %s", session_id, exc_info=True)

    async def list_user_sessions(self, user_id: str) -> list[dict[str, Any]]:
        if not self._ready:
            return []
        try:
            cursor = self._db.sessions.find({"user_id": user_id}).sort("last_run_at", DESCENDING)
            return [self._clean(doc) async for doc in cursor]
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.list_user_sessions failed for %s", user_id, exc_info=True)
            return []

    # ── experiment versions (durable mirror of the Redis tracker) ────────────
    async def save_experiment_version(self, version: dict[str, Any]) -> None:
        if not self._ready:
            return
        version_id = version.get("version_id")
        if not version_id:
            return
        try:
            await self._db.experiment_versions.replace_one(
                {"version_id": version_id}, version, upsert=True
            )
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.save_experiment_version failed for %s", version_id, exc_info=True)

    # ── cleanup (used by the maintenance script / admin) ─────────────────────
    async def delete_session_data(self, session_id: str) -> dict[str, int]:
        if not self._ready:
            return {"design_runs": 0, "experiment_versions": 0, "sessions": 0}
        try:
            r1 = await self._db.design_runs.delete_many({"session_id": session_id})
            r2 = await self._db.experiment_versions.delete_many({"session_id": session_id})
            r3 = await self._db.sessions.delete_one({"_id": session_id})
            return {
                "design_runs": r1.deleted_count,
                "experiment_versions": r2.deleted_count,
                "sessions": r3.deleted_count,
            }
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.delete_session_data failed for %s", session_id, exc_info=True)
            return {"design_runs": 0, "experiment_versions": 0, "sessions": 0}

    @staticmethod
    def _clean(doc: dict[str, Any] | None) -> dict[str, Any]:
        """Drop the Mongo _id (we mirror it as run_id/session_id) for clean JSON."""
        if not doc:
            return {}
        doc.pop("_id", None)
        return doc


def create_mongo_store(settings: Any) -> MongoStore:
    return MongoStore(
        uri=settings.mongodb_uri,
        db_name=settings.mongodb_db_name,
        connect_timeout_ms=settings.mongodb_connect_timeout_ms,
    )
