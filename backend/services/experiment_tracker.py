"""Experiment version tracking - every design iteration gets a permanent version.

Gives researchers:
- A timeline of every edit, transform, optimisation, and generation
- Parent→child lineage chains for provenance
- Position-level diffs between any two versions
- One-click revert to any previous snapshot

Storage is backed by the existing SessionStore (get_raw / set_raw) so
it works identically in memory (tests) and Redis (production).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from services.session_store import SessionStore, SessionNotFoundError

logger = logging.getLogger("evo.experiment_tracker")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ExperimentVersion:
    """Immutable snapshot of a candidate at a point in time."""

    version_id: str
    session_id: str
    candidate_id: int
    sequence: str
    scores: dict[str, float]
    operation: str  # "initial" | "edit" | "transform" | "optimize" | "generate" | "revert"
    operation_details: dict[str, Any]
    timestamp: str  # ISO-8601
    parent_version_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentVersion:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Novel-region extraction (edit-history signal)
# ---------------------------------------------------------------------------
#
# There is no per-region novelty score to gate on: CandidateScores.novelty
# (models/domain.py) is a single whole-candidate float, not per-position, so
# it can't tell "this span is novel" from "that span is untouched". The
# session's own edit/regenerate history is used instead - it already tracks
# real per-coordinate spans for every operation that has an addressable one.


def novel_regions_from_versions(versions: list[ExperimentVersion]) -> list[tuple[int, int]]:
    """Derive the [start, end) spans a session's edit history actually touched.

    Only operations that carry a genuine coordinate span *in the current
    sequence* contribute a region:

    - A base edit (``/api/edit/base``, ``operation_details={"position": ...}``,
      no nested ``scope``) - treated as the one-base span ``[position, position+1)``.
    - An agent ``insert_bases`` tool call (``scope="insert"``) - the span the
      newly inserted bases occupy: ``[position, position+inserted_length)``.
    - An agent ``regenerate_region`` tool call (``scope="regenerate"``) - the
      regenerated span in the (possibly length-changed) new sequence:
      ``[start, new_region_end)``.

    Deliberately excluded, because neither has an addressable span in the
    *current* sequence:

    - ``scope="delete"`` - the deleted span no longer exists.
    - ``scope="transform"`` (e.g. codon optimization, "replace all X") - a
      whole-candidate change with no sub-span; gating on it would just
      re-derive the whole-candidate case this function exists to avoid.
    - The hill-climbing optimizer (``mode="hill_climb"``, no ``scope`` key -
      see ``tool_optimize`` in services/agent/tools.py) applies MULTIPLE
      independent single-base edits per call, one per round, nested in
      ``operation_details["mutations"]`` (each with its own ``"position"``).
      Every round's position contributes its own one-base span.

    Returns spans **merged**: overlapping or adjacent edits collapse into one
    span so re-editing the same region twice doesn't produce duplicate,
    overlapping literature lookups.
    """
    spans: list[tuple[int, int]] = []
    for version in versions:
        details = version.operation_details or {}
        scope = details.get("scope")
        if details.get("mode") == "hill_climb":
            for mutation in details.get("mutations") or []:
                position = mutation.get("position") if isinstance(mutation, dict) else None
                if isinstance(position, int):
                    spans.append((position, position + 1))
            continue
        start: Any = None
        end: Any = None
        if scope == "regenerate":
            start = details.get("start")
            end = details.get("new_region_end", details.get("end"))
        elif scope == "insert":
            position = details.get("position")
            length = details.get("inserted_length")
            if isinstance(position, int) and isinstance(length, int):
                start, end = position, position + length
        elif scope in ("delete", "transform"):
            continue
        elif scope is None and "position" in details:
            position = details.get("position")
            if isinstance(position, int):
                start, end = position, position + 1
        if isinstance(start, int) and isinstance(end, int) and end > start:
            spans.append((start, end))

    if not spans:
        return []
    spans.sort()
    merged: list[tuple[int, int]] = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


# ---------------------------------------------------------------------------
# Version diff
# ---------------------------------------------------------------------------


@dataclass
class VersionDiff:
    """Position-level diff between two experiment versions."""

    v1_id: str
    v2_id: str
    length_v1: int
    length_v2: int
    mutations: list[dict[str, Any]]  # [{position, ref, alt}]
    total_changes: int
    identity: float  # fraction of identical positions

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _diff_sequences(seq1: str, seq2: str) -> list[dict[str, Any]]:
    """Compute position-level mutations between two sequences."""
    mutations: list[dict[str, Any]] = []
    min_len = min(len(seq1), len(seq2))
    for i in range(min_len):
        if seq1[i] != seq2[i]:
            mutations.append({"position": i, "ref": seq1[i], "alt": seq2[i]})
    # Length differences are reported as insertions/deletions
    if len(seq2) > len(seq1):
        for i in range(min_len, len(seq2)):
            mutations.append({"position": i, "ref": "-", "alt": seq2[i]})
    elif len(seq1) > len(seq2):
        for i in range(min_len, len(seq1)):
            mutations.append({"position": i, "ref": seq1[i], "alt": "-"})
    return mutations


# ---------------------------------------------------------------------------
# Tracker service
# ---------------------------------------------------------------------------

# Storage key helpers
_INDEX_KEY = "experiment:{session_id}:index"
_VERSION_KEY = "experiment:{session_id}:version:{version_id}"
_LATEST_KEY = "experiment:{session_id}:candidate:{candidate_id}:latest"


class ExperimentVersionNotFoundError(KeyError):
    def __init__(self, session_id: str, version_id: str) -> None:
        super().__init__(f"version {version_id} not found in session {session_id}")
        self.session_id = session_id
        self.version_id = version_id


class ExperimentTracker:
    """Version-control layer for genomic design iterations.

    Redis is the primary store (fast, TTL'd). An optional ``mongo_store`` mirrors
    each recorded version durably so the timeline survives TTL expiry / restarts.
    The mirror is best-effort and never affects the Redis write path.
    """

    def __init__(self, store: SessionStore, mongo_store: Any | None = None) -> None:
        self._store = store
        self._mongo_store = mongo_store

    # -- Write operations ---------------------------------------------------

    async def record_version(
        self,
        *,
        session_id: str,
        candidate_id: int,
        sequence: str,
        scores: dict[str, float],
        operation: str,
        operation_details: dict[str, Any] | None = None,
        parent_version_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Record a new version snapshot. Returns the new version_id."""
        # Auto-resolve parent if not provided
        if parent_version_id is None:
            parent_version_id = await self._get_latest_version_id(session_id, candidate_id)

        version_id = uuid4().hex[:12]
        version = ExperimentVersion(
            version_id=version_id,
            session_id=session_id,
            candidate_id=candidate_id,
            sequence=sequence,
            scores=scores,
            operation=operation,
            operation_details=operation_details or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
            parent_version_id=parent_version_id,
            metadata=metadata or {},
        )

        # Persist the version itself
        version_key = _VERSION_KEY.format(session_id=session_id, version_id=version_id)
        await self._store.set_raw(version_key, json.dumps(version.to_dict()))

        # Append to session index
        index_key = _INDEX_KEY.format(session_id=session_id)
        raw_index = await self._store.get_raw(index_key)
        index: list[str] = json.loads(raw_index) if raw_index else []
        index.append(version_id)
        await self._store.set_raw(index_key, json.dumps(index))

        # Update latest pointer
        latest_key = _LATEST_KEY.format(session_id=session_id, candidate_id=candidate_id)
        await self._store.set_raw(latest_key, version_id)

        # Durable mirror (best-effort; no-op when Mongo is unconfigured/unreachable)
        if self._mongo_store is not None:
            await self._mongo_store.save_experiment_version(version.to_dict())

        logger.info(
            "Recorded version %s for session=%s candidate=%d op=%s",
            version_id, session_id, candidate_id, operation,
        )
        return version_id

    async def revert_to_version(
        self,
        session_id: str,
        version_id: str,
    ) -> ExperimentVersion:
        """Revert a candidate to a previous version.

        Creates a new 'revert' version pointing at the target, restores
        the sequence in the session store, and returns the new version.
        """
        target = await self.get_version(session_id, version_id)

        # Restore the sequence in the session store
        await self._store.set_candidate_sequence(
            session_id, target.candidate_id, target.sequence,
        )

        # Record the revert as a new version
        new_id = await self.record_version(
            session_id=session_id,
            candidate_id=target.candidate_id,
            sequence=target.sequence,
            scores=target.scores,
            operation="revert",
            operation_details={"reverted_to": version_id},
            parent_version_id=version_id,
        )

        return await self.get_version(session_id, new_id)

    # -- Read operations ----------------------------------------------------

    async def get_version(
        self, session_id: str, version_id: str,
    ) -> ExperimentVersion:
        """Fetch a single version by ID."""
        version_key = _VERSION_KEY.format(session_id=session_id, version_id=version_id)
        raw = await self._store.get_raw(version_key)
        if raw is None:
            raise ExperimentVersionNotFoundError(session_id, version_id)
        return ExperimentVersion.from_dict(json.loads(raw))

    async def list_versions(
        self,
        session_id: str,
        candidate_id: int | None = None,
    ) -> list[ExperimentVersion]:
        """List all versions for a session, optionally filtered by candidate."""
        index_key = _INDEX_KEY.format(session_id=session_id)
        raw_index = await self._store.get_raw(index_key)
        if not raw_index:
            return []

        version_ids: list[str] = json.loads(raw_index)
        versions: list[ExperimentVersion] = []
        for vid in version_ids:
            try:
                v = await self.get_version(session_id, vid)
                if candidate_id is None or v.candidate_id == candidate_id:
                    versions.append(v)
            except ExperimentVersionNotFoundError:
                continue  # Stale index entry
        # Sort by timestamp
        versions.sort(key=lambda v: v.timestamp)
        return versions

    async def get_lineage(
        self, session_id: str, version_id: str,
    ) -> list[ExperimentVersion]:
        """Walk the parent chain back to the root."""
        chain: list[ExperimentVersion] = []
        current_id: str | None = version_id
        seen: set[str] = set()  # guard against cycles

        while current_id and current_id not in seen:
            seen.add(current_id)
            try:
                version = await self.get_version(session_id, current_id)
                chain.append(version)
                current_id = version.parent_version_id
            except ExperimentVersionNotFoundError:
                break

        return chain  # newest → oldest

    async def diff_versions(
        self,
        session_id: str,
        v1_id: str,
        v2_id: str,
    ) -> VersionDiff:
        """Compute a position-level diff between two versions."""
        v1 = await self.get_version(session_id, v1_id)
        v2 = await self.get_version(session_id, v2_id)

        mutations = _diff_sequences(v1.sequence, v2.sequence)
        max_len = max(len(v1.sequence), len(v2.sequence))
        identity = 1.0 - (len(mutations) / max_len) if max_len > 0 else 1.0

        return VersionDiff(
            v1_id=v1_id,
            v2_id=v2_id,
            length_v1=len(v1.sequence),
            length_v2=len(v2.sequence),
            mutations=mutations,
            total_changes=len(mutations),
            identity=round(identity, 6),
        )

    # -- Internal -----------------------------------------------------------

    async def _get_latest_version_id(
        self, session_id: str, candidate_id: int,
    ) -> str | None:
        latest_key = _LATEST_KEY.format(session_id=session_id, candidate_id=candidate_id)
        return await self._store.get_raw(latest_key)
