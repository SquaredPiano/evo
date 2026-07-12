"""Durable persistence backend (MongoDB Atlas).

Redis remains the *hot* store for a live pipeline run (fast, TTL'd, pub/sub).
MongoDB is the *durable* store: it records each design run - critically the
**prompt/goal** that produced it, which Redis never kept - so a session and its
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
from typing import Any, Protocol

import certifi
from pymongo import AsyncMongoClient, ASCENDING, DESCENDING
from pymongo.errors import PyMongoError

logger = logging.getLogger("evo")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_cert_verify_failure(exc: Exception) -> bool:
    return "CERTIFICATE_VERIFY_FAILED" in str(exc)


class SessionSnapshotStore(Protocol):
    """Swappable storage seam for resumable session snapshots.

    Defined by docs/session_persistence_interface.md (the MongoDB hand-off).
    ``MongoStore`` is the default implementation; an in-memory impl could be
    dropped in for tests. Named ``SessionSnapshotStore`` to avoid confusion with
    the Redis hot-store ``SessionStore`` in services/session_store.py, which is a
    different concern (live pipeline/edit state, not durable snapshots).
    """

    async def put_session_snapshot(self, snapshot: dict[str, Any]) -> bool: ...
    async def get_session_snapshot(self, session_id: str) -> dict[str, Any] | None: ...
    async def list_session_summaries(self, user_id: str | None = None) -> list[dict[str, Any]]: ...
    async def delete_session_snapshot(self, session_id: str) -> bool: ...


class MongoStore:
    """Best-effort durable store. All ops degrade to no-ops when unavailable."""

    def __init__(
        self,
        *,
        uri: str,
        db_name: str,
        connect_timeout_ms: int = 5000,
        vector_index_name: str = "literature_vector_index",
        vector_dim: int = 256,
    ) -> None:
        self._uri = uri
        self._db_name = db_name
        self._connect_timeout_ms = connect_timeout_ms
        self._vector_index_name = vector_index_name
        self._vector_dim = vector_dim
        # Configured means a URI is present; ready means we actually connected.
        self.configured = bool(uri)
        self._ready = False
        self._client: AsyncMongoClient | None = None
        self._db: Any = None

    # ── lifecycle ──────────────────────────────────────────────────────────
    async def connect(self) -> bool:
        """Attempt a connection. Returns True only if Atlas answered a ping.

        Never raises - a failure here just leaves the store disabled so the app
        keeps running on Redis alone.
        """
        if not self.configured:
            logger.info("MongoDB persistence disabled (no MONGODB_URI configured).")
            return False
        try:
            await self._connect_once(tls_ca_file=None)
            return True
        except PyMongoError as exc:
            if _is_cert_verify_failure(exc):
                # Some Python builds (notably macOS python.org/Homebrew
                # installs) don't wire up the system trust store for the ssl
                # module, which surfaces as CERTIFICATE_VERIFY_FAILED against
                # Atlas's TLS endpoints even though the URI/allowlist are
                # correct. Retry once with an explicit CA bundle - ONLY on
                # this specific failure: passing tlsCAFile unconditionally
                # would implicitly force TLS on and break non-TLS/self-hosted
                # deployments that connect fine without it.
                logger.info(
                    "MongoDB TLS handshake failed against the system trust store - "
                    "retrying once with certifi's CA bundle."
                )
                try:
                    await self._connect_once(tls_ca_file=certifi.where())
                    return True
                except Exception:
                    pass
            self._ready = False
            logger.warning(
                "MongoDB unreachable - running Redis-only, persistence is a no-op. "
                "If using Atlas, add this host's IP to Network Access. Detail: %s",
                exc,
            )
            return False
        except Exception:  # defensive: DNS/SSL/etc. must not crash startup
            self._ready = False
            logger.warning("MongoDB connection failed unexpectedly - persistence disabled.", exc_info=True)
            return False

    async def _connect_once(self, *, tls_ca_file: str | None) -> None:
        kwargs: dict[str, Any] = {
            "serverSelectionTimeoutMS": self._connect_timeout_ms,
            "connectTimeoutMS": self._connect_timeout_ms,
            "appname": "evo-backend",
        }
        if tls_ca_file is not None:
            kwargs["tlsCAFile"] = tls_ca_file
        client = AsyncMongoClient(self._uri, **kwargs)
        try:
            await client.admin.command("ping")
        except Exception:
            await client.close()
            raise
        self._client = client
        self._db = self._client[self._db_name]
        await self._ensure_indexes()
        self._ready = True
        logger.info("MongoDB persistence connected (db=%s).", self._db_name)

    async def _ensure_indexes(self) -> None:
        await self._db.design_runs.create_index([("session_id", ASCENDING), ("created_at", ASCENDING)])
        await self._db.design_runs.create_index([("parent_run_id", ASCENDING)])
        await self._db.design_runs.create_index([("user_id", ASCENDING)])
        # `sessions` holds resumable snapshots (frontend-native camelCase fields).
        await self._db.sessions.create_index([("updatedAt", DESCENDING)])
        await self._db.sessions.create_index([("userId", ASCENDING)])
        await self._db.experiment_versions.create_index(
            [("session_id", ASCENDING), ("candidate_id", ASCENDING)]
        )
        await self._db.experiment_versions.create_index([("version_id", ASCENDING)], unique=True)
        # `literature` holds embedded research articles for semantic search.
        await self._db.literature.create_index([("gene", ASCENDING)])
        await self._db.literature.create_index([("pmid", ASCENDING)])
        # Best-effort Atlas Vector Search index (Atlas only; a no-op elsewhere).
        await self._ensure_vector_index()

    async def _ensure_vector_index(self) -> None:
        """Create the literature vector-search index on Atlas if missing.

        Fully best-effort and self-contained: Atlas Search index management is
        unsupported on self-hosted / local MongoDB and on older servers, so
        EVERY failure is swallowed here. Without this index, ``$vectorSearch``
        simply errors at query time and the caller falls back to in-memory
        cosine similarity - the feature still works, just not at Atlas scale.
        """
        try:
            from pymongo.operations import SearchIndexModel

            cursor = await self._db.literature.list_search_indexes()
            existing = [ix["name"] async for ix in cursor]
            if self._vector_index_name in existing:
                return
            model = SearchIndexModel(
                definition={
                    "fields": [
                        {
                            "type": "vector",
                            "path": "embedding",
                            "numDimensions": self._vector_dim,
                            "similarity": "cosine",
                        },
                        {"type": "filter", "path": "gene"},
                    ]
                },
                name=self._vector_index_name,
                type="vectorSearch",
            )
            await self._db.literature.create_search_index(model)
            logger.info("Created Atlas vector index '%s' on literature.", self._vector_index_name)
        except Exception:  # noqa: BLE001 - non-Atlas / old server / perms: fall back silently
            logger.info(
                "Atlas vector index unavailable - literature search will use in-memory cosine "
                "fallback. (Provision '%s' on Atlas to enable $vectorSearch.)",
                self._vector_index_name,
            )

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

    # ── session snapshots (the resumable-state store - interface-doc contract) ─
    async def put_session_snapshot(self, snapshot: dict[str, Any]) -> bool:
        """Upsert a full session snapshot (debounced client autosave).

        The snapshot is the frontend ``useProteusStore`` state; the client owns its
        shape, so we round-trip it verbatim and only derive cheap summary fields
        (candidateCount / length / updatedAt) for the listing endpoint. Returns
        True when it was actually stored (False when persistence is disabled).
        """
        if not self._ready:
            return False
        session_id = snapshot.get("sessionId")
        if not session_id:
            return False
        now = _utcnow_iso()
        # _id and createdAt are managed here - keep them out of $set to avoid
        # Mongo's immutable-_id error and a $set/$setOnInsert path conflict.
        doc = {k: v for k, v in snapshot.items() if k not in ("_id", "createdAt")}
        doc["sessionId"] = session_id
        doc["updatedAt"] = snapshot.get("updatedAt") or now
        doc["candidateCount"] = len(snapshot.get("candidates") or [])
        doc["length"] = len(snapshot.get("rawSequence") or "")
        try:
            await self._db.sessions.update_one(
                {"_id": session_id},
                {"$set": doc, "$setOnInsert": {"createdAt": snapshot.get("createdAt") or now}},
                upsert=True,
            )
            return True
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.put_session_snapshot failed for %s", session_id, exc_info=True)
            return False

    async def get_session_snapshot(self, session_id: str) -> dict[str, Any] | None:
        if not self._ready:
            return None
        try:
            doc = await self._db.sessions.find_one({"_id": session_id})
            return self._clean(doc) if doc else None
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.get_session_snapshot failed for %s", session_id, exc_info=True)
            return None

    async def list_session_summaries(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Session summaries for the home/resume list, newest first."""
        if not self._ready:
            return []
        query = {"userId": user_id} if user_id else {}
        projection = {
            "sessionId": 1, "title": 1, "kind": 1, "updatedAt": 1,
            "candidateCount": 1, "length": 1, "userId": 1,
        }
        try:
            cursor = self._db.sessions.find(query, projection=projection).sort("updatedAt", DESCENDING)
            return [self._clean(doc) async for doc in cursor]
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.list_session_summaries failed", exc_info=True)
            return []

    async def delete_session_snapshot(self, session_id: str) -> bool:
        if not self._ready:
            return False
        try:
            result = await self._db.sessions.delete_one({"_id": session_id})
            return result.deleted_count > 0
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.delete_session_snapshot failed for %s", session_id, exc_info=True)
            return False

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

    # ── research literature (semantic vector search) ─────────────────────────
    async def save_literature_docs(self, docs: list[dict[str, Any]]) -> bool:
        """Upsert embedded literature docs (idempotent by doc_id). Best-effort."""
        if not self._ready or not docs:
            return False
        try:
            from pymongo import ReplaceOne

            ops = [
                ReplaceOne({"_id": d["doc_id"]}, {**d, "_id": d["doc_id"]}, upsert=True)
                for d in docs
                if d.get("doc_id")
            ]
            if not ops:
                return False
            await self._db.literature.bulk_write(ops, ordered=False)
            return True
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.save_literature_docs failed (%d docs)", len(docs), exc_info=True)
            return False

    async def vector_search_literature(
        self,
        query_vector: list[float],
        *,
        k: int = 5,
        gene: str | None = None,
        num_candidates: int | None = None,
    ) -> list[dict[str, Any]] | None:
        """Atlas ``$vectorSearch`` over the literature collection.

        Returns a list of matching docs (each with a ``score``), or ``None`` to
        signal the caller to fall back to in-memory search - which is what
        happens whenever the vector index isn't provisioned (the aggregation
        errors) or the query otherwise fails. Never raises.
        """
        if not self._ready:
            return None
        search_stage: dict[str, Any] = {
            "index": self._vector_index_name,
            "path": "embedding",
            "queryVector": query_vector,
            "numCandidates": num_candidates or max(50, k * 10),
            "limit": k,
        }
        if gene:
            search_stage["filter"] = {"gene": gene}
        pipeline = [
            {"$vectorSearch": search_stage},
            {"$set": {"score": {"$meta": "vectorSearchScore"}}},
            {"$project": {"embedding": 0}},
        ]
        try:
            cursor = await self._db.literature.aggregate(pipeline)
            return [self._clean(doc) async for doc in cursor]
        except Exception:  # noqa: BLE001 - no index / unsupported → in-memory fallback
            logger.info("Atlas $vectorSearch unavailable - using in-memory literature search.")
            return None

    async def list_literature_docs(
        self, *, gene: str | None = None, limit: int = 2000
    ) -> list[dict[str, Any]]:
        """Load literature docs (keeping embeddings) for the in-memory fallback."""
        if not self._ready:
            return []
        query = {"gene": gene} if gene else {}
        try:
            cursor = self._db.literature.find(query).limit(limit)
            return [self._clean(doc) async for doc in cursor]
        except Exception:  # noqa: BLE001
            logger.warning("MongoStore.list_literature_docs failed", exc_info=True)
            return []

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
        vector_index_name=getattr(settings, "vector_index_name", "literature_vector_index"),
        vector_dim=getattr(settings, "embedding_dim", 256),
    )
