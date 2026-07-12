# Session Persistence Interface (for MongoDB)

Owner of storage impl: **Mohammed** (Mongo + DigitalOcean). This doc defines the
contract so persistence drops in without touching the frontend workspace or the
reprompt/evidence features already built. Nothing here is built yet — it is the
seam.

## Why
Today a "session" is two disconnected things:
- `frontend/lib/sessionHistory.ts` — localStorage list storing ONLY the prompt/sequence
  (`SessionEntry{id,kind,title,payload,createdAt}`). "Resuming" re-runs from scratch.
- `backend` `sessionId` — binds the current DNA to the agent so `/api/agent/chat` +
  `editBase` mutate the right sequence. Not listed, not persisted.

Goal: sessions that **restore full state** (candidates, chat, scores, structure),
listable on a home/summary screen, resumable instead of re-runnable, and a real
"New Chat".

## What one session must persist (the resumable snapshot)
Source of truth is `useEvoStore` (`frontend/lib/store.ts`). A session record should
capture, per session id:

| Field | Type | Notes |
|---|---|---|
| `sessionId` | string | backend agent session id (already exists in store) |
| `title` | string | design goal or short sequence label |
| `kind` | "design" \| "paste" \| "pdb" | how it started |
| `createdAt` / `updatedAt` | ISO string | |
| `rawSequence` | string | active sequence |
| `candidates` | Candidate[] | includes new `provenance` field (engine/sampled_probs) |
| `activeCandidateId` | number \| null | |
| `analysisResult` | AnalysisResult \| null | regions, predicted proteins, scores |
| `scores` | number[] | per-position |
| `regions` | SequenceRegion[] | |
| `activePdb` / `structureModel` | string \| null | structure + provenance (`user_pdb` etc.) |
| `chatMessages` | ChatMessage[] | the Helio conversation — **the thing New Chat clears** |
| `editHistory` | EditEntry[] | |
| `retrievalStatuses` | RetrievalStatus[] | NCBI/PubMed/ClinVar payloads (drives evidence + gene) |
| `seedSource` / `scoringNote` | string \| null | provenance labels |
| `compareLeftId` / `compareRightId` | number \| null | compare pins |
| `regionEvidence` | RegionEvidence[] | optional cache; recomputable from sequence+gene |

`regionEvidence` and `activePdb` are recomputable and MAY be omitted to shrink the
record (recompute on resume).

## Suggested REST contract (`backend/main.py` + a Mongo-backed store)
Frontend `frontend/lib/api.ts` has NO session endpoints today (only
`listExperiments`/`revertExperiment`, which are per-session VERSION snapshots and are
a reasonable storage precedent). Add:

- `GET  /api/sessions` → `{ sessions: SessionSummary[] }` — summaries only
  (`{sessionId,title,kind,updatedAt,candidateCount,length}`) for the home/summary list.
- `GET  /api/sessions/{sessionId}` → full session snapshot (fields above).
- `PUT  /api/sessions/{sessionId}` → upsert snapshot (debounced autosave from the client).
- `DELETE /api/sessions/{sessionId}`.

Keep it behind a small storage interface so the impl is swappable:
```python
class SessionStore(Protocol):
    async def list(self, user_id: str | None) -> list[SessionSummary]: ...
    async def get(self, session_id: str) -> SessionSnapshot | None: ...
    async def put(self, snapshot: SessionSnapshot) -> None: ...
    async def delete(self, session_id: str) -> None: ...
```
Mongo collection `sessions`, `_id = sessionId`, index on `updatedAt` (+ `userId` once
auth exists). The existing `experiment_tracker` version snapshots can live under the
session document or a sibling `versions` collection keyed by `sessionId`.

## Frontend seams to wire (after storage exists)
- `frontend/lib/store.ts` → `clearChat()` has a `// TODO(persist): session store` marker.
  New Chat = snapshot current session via `PUT`, then `clearChat()` and start fresh.
- `reset()` already PRESERVES `chatMessages` intentionally (so reprompt/redesign don't
  wipe the thread) — persistence should snapshot BEFORE a hard reset.
- `WorkspaceSidebar.onSelectSession` (currently re-prefills the composer) → change to
  `GET /api/sessions/{id}` then rehydrate the store and go to `analyze`, not `input`.
- Add an autosave effect (debounced `PUT` on meaningful store changes).
- Home/summary screen: consume `GET /api/sessions` (the app-home is `viewMode:"input"`
  today; a `"home"` view or `frontend/app/home/page.tsx` can host the summary list).

## Guarantee for the current build
The reprompt-in-chat and region-evidence features do NOT depend on this. They work
in-memory now; persistence is purely additive. Do not change the `candidate_update`
shape, the `RegionEvidence` schema, or the honest provenance fields when wiring Mongo.
