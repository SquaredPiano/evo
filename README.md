# Evo — a genomic design IDE

**Cursor for DNA.** Describe a design goal in plain English, and Evo generates
candidate DNA sequences with a genomic foundation model, scores them, folds the
top ones into 3D protein structures, and hands you a real inline editor to
tweak bases and re-score in real time.

Evo is a v2 rebuild of an earlier hackathon project (Helix). The goal of this
revision was not more features — it was to make the existing ones **honest and
usable**: a real inline editor, every backend capability reachable from the UI,
a single well-behaved LLM gateway, and an interface that never claims an engine
is live when it is actually simulated.

---

## What's real vs. simulated

Evo runs fully offline in a deterministic **mock** mode with zero API keys, and
each subsystem independently upgrades to a live engine when you provide a key.
The app tells you which mode is active — the engine pill in the workspace
sidebar reflects the backend's real state, and the intake screen lists engine
status rather than hard-coding "Ready".

| Subsystem | Mock (default) | Live (with config) |
|---|---|---|
| NCBI / PubMed / ClinVar retrieval | — | **Always live** (real E-utilities calls) |
| Translation, ORF finding, GC, codon opt | **Always real** (deterministic compute) | — |
| Evo2 generation + scoring | Deterministic local model | NVIDIA-hosted Evo2 40B (`EVO2_MODE=nim_api`) |
| Protein structure | Placeholder PDB | ESMFold live API (`STRUCTURE_MODE=esmfold`) |
| Intent parsing / explanation / agent | Heuristic fallback | OpenRouter (`OPENROUTER_API_KEY`) |

Scoring is a transparent heuristic, not a clinically validated model — it is
labeled as such in the UI rather than presented as ground truth. The workspace
includes a **Validate** tab that *measures* this rather than asserting it: it
pulls known pathogenic and benign variants from ClinVar, scores each with the
active Evo2 engine, and reports a real AUROC (`POST /api/calibration`). With the
mock or hosted-NIM engines — neither of which exposes real per-sequence
log-likelihoods — an AUROC near 0.5 is the honest result; a real signal requires
`EVO2_MODE=local`. Variants whose reference base does not align to the supplied
sequence are counted and skipped rather than silently mis-scored.

---

## Architecture

```
Design goal (English)
      │
      ▼
Intent parser ── OpenRouter ──▶ structured, editable spec
      │
      ▼
Orchestrator (FastAPI) ◀── Redis (queue + cache + pub/sub) ──▶ WebSocket
      │
      ├─ NCBI ┐
      ├─ PubMed ├─ parallel retrieval
      ├─ ClinVar ┘
      ▼
Evo2 generation (streamed) ─▶ scoring (functional / tissue / off-target / novelty)
      ▼
ESMFold structure ─▶ explanation (streamed) ─▶ frontend workspace
```

**Two edit paths, two latency contracts** (the core idea, kept and extended):

- `POST /api/edit/base` — single-base edit, re-score only, target < 2s (used by
  the inline editor's "mutate + rescore").
- `POST /api/edit/followup` — natural-language follow-up, re-runs only the
  affected pipeline stages, streamed over the WebSocket.

The single LLM gateway lives in `backend/services/llm.py`; all reasoning routes
through OpenRouter's OpenAI-compatible API, so swapping models is a one-line
config change (`LLM_MODEL`).

**Durable persistence (optional).** Redis stays the hot store for a live run
(streaming, TTL'd). Set `MONGODB_URI` and each design run is *also* recorded in
MongoDB — the English **goal**, the run config, and the resulting candidates,
plus a session index and a durable mirror of experiment versions. This is what
survives a restart or TTL expiry (the prompt history a session builds on). Leave
`MONGODB_URI` blank and the app behaves exactly as before, Redis-only: every
persistence call becomes a logged no-op, never a request error. Implementation:
`backend/services/mongo_store.py`. Atlas note: the connecting host's IP must be
on the cluster's Network Access allowlist or the store stays disabled.

---

## Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Zustand, Framer Motion,
  Three.js / React Three Fiber (3D protein viewer).
- **Backend:** FastAPI, Redis (queue + cache + pub/sub), MongoDB (optional
  durable store for design-run history), Pydantic, LangGraph for the agent
  state machine.
- **Engines:** Evo2 (mock / NVIDIA NIM 40B / local), ESMFold, OpenRouter.

---

## Getting started

### 1. Configure keys (optional — mock mode needs none)

```bash
cp .env.example .env            # repo root, or backend/.env
# fill in OPENROUTER_API_KEY, NVIDIA_API_KEY, NCBI_API_KEY as available
# optional: set MONGODB_URI (+ MONGODB_DB_NAME) to persist design-run history
```

### 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

### Or with Docker

```bash
docker compose up --build
```

---

## Tests

```bash
cd backend && pytest -q     # 765 passing
cd frontend && npm run build
```

---

## In the workspace

- **Inline editor** — click to place a caret, drag to select, type A/T/C/G to
  overwrite, Backspace/Delete to remove, Shift+Arrows to extend selection,
  reverse-complement a selection, and "mutate + rescore" a single base through
  the fast edit path.
- **Research tools panel** — off-target scanning, organism-specific codon
  optimization (with one-click apply), live ClinVar variant annotation, and
  FASTA / GenBank export. All were backend-only before; now they have a UI.
- **Version history** — every edit and follow-up is versioned; revert to any
  earlier state.
- **Import** — drag in FASTA or GenBank; GenBank is parsed server-side with its
  feature table intact.
