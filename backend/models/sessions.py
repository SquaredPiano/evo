"""Session snapshot models - the resumable session-persistence contract.

Defined by docs/session_persistence_interface.md. A snapshot is the frontend
``useProteusStore`` state captured per session id so a session can be *resumed*
(full UI state restored) rather than re-run. The client owns the shape, so the
snapshot model is deliberately permissive (``extra="allow"``): new store fields
round-trip without a backend change. Only the summary fields are relied on here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SessionSummary(BaseModel):
    """Lightweight row for the home/resume list (no heavy payload)."""

    sessionId: str
    title: str | None = None
    kind: str | None = None
    updatedAt: str | None = None
    candidateCount: int = 0
    length: int = 0
    userId: str | None = None


class SessionSnapshot(BaseModel):
    """Full resumable snapshot. Permissive by design - unknown fields from the
    evolving frontend store are accepted and stored as-is."""

    model_config = ConfigDict(extra="allow")

    sessionId: str | None = None
    title: str | None = None
    kind: str | None = None  # "design" | "paste" | "pdb"
    createdAt: str | None = None
    updatedAt: str | None = None
    userId: str | None = None

    # Documented store fields (all optional; typed permissively so the backend
    # never rejects a snapshot when the frontend adds/renames a field).
    rawSequence: str | None = None
    candidates: list[dict[str, Any]] | None = None
    activeCandidateId: int | None = None
    analysisResult: dict[str, Any] | None = None
    scores: list[Any] | None = None
    regions: list[dict[str, Any]] | None = None
    activePdb: str | None = None
    structureModel: str | None = None
    chatMessages: list[dict[str, Any]] | None = None
    editHistory: list[dict[str, Any]] | None = None
    retrievalStatuses: list[dict[str, Any]] | None = None
    seedSource: str | None = None
    scoringNote: str | None = None
    compareLeftId: int | None = None
    compareRightId: int | None = None
    regionEvidence: list[dict[str, Any]] | None = None
