<div align="center">
  <img src="frontend/public/favicon.svg" alt="Proteus Logo" width="110" style="margin-bottom: 18px;"/>

  # Proteus

  **An IDE for the code of life — from natural-language objective to editable DNA and live structure feedback.**

  [![Next.js](https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js)](https://nextjs.org/)
  [![React](https://img.shields.io/badge/React-19-149ECA?style=for-the-badge&logo=react)](https://react.dev/)
  [![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
  [![Redis](https://img.shields.io/badge/Redis-Streaming-DC382D?style=for-the-badge&logo=redis)](https://redis.io/)

  [Demo Video](https://github.com/user-attachments/assets/fb579e02-f806-487a-88be-14cb9fc5785b) · [Report Bug](https://github.com/SquaredPiano/evo/issues)
</div>

---

## 🎬 Demo

<div align="center">
  <video src="https://github.com/user-attachments/assets/fb579e02-f806-487a-88be-14cb9fc5785b" controls width="100%">
    <a href="https://github.com/user-attachments/assets/fb579e02-f806-487a-88be-14cb9fc5785b">Watch the Proteus demo video</a>
  </video>
  <p><em>From a sentence to generated DNA, live confidence, editable regions, and predicted structure.</em></p>
</div>

---

## ✨ Overview

Proteus is the **second-generation rebuild of Helix**, our AI-native genomic design IDE.

Helix proved the core idea: describe a biological objective in plain language, generate candidate DNA, score it, predict its structure, and refine it with an AI copilot. Proteus turns that prototype into a more capable, transparent, and usable workspace—without losing the speed and immediacy that made Helix compelling.

> *"Describe the biology. Generate the sequence. Edit the code of life."*

### Helix, evolved

| Helix | Proteus |
|-------|---------|
| Prototype sequence workspace | Full inline DNA editor with selection, mutation, and instant re-scoring |
| Backend-heavy research tools | Every major capability is accessible directly from the interface |
| Opaque engine state | Honest live/mock status for every model and subsystem |
| One-shot generation | Region-level regeneration, version history, comparison, and rollback |
| General retrieval context | Real papers, ClinVar evidence, motif analysis, and semantic literature search |
| Ephemeral sessions | Optional durable snapshots and design-run history with MongoDB |
| Distributed model calls | One well-behaved OpenRouter gateway for reasoning and explanation |

Proteus is not a new coat of paint on Helix. It is a deliberate revision of the same vision: **better editing, better science, better observability, and a much tighter loop between human intent and model output.**

### Features

| Feature | Description |
|---------|-------------|
| 🧬 **Evo 2 Generation** | Generate and score DNA with NVIDIA-hosted Evo 2 40B, a local engine, or deterministic mock mode. |
| ✍️ **Real Sequence Editor** | Select, overwrite, delete, reverse-complement, mutate, and re-score bases directly in the workspace. |
| 🔁 **Region Regeneration** | Ask Proteus to rewrite only a selected region, splice it back into the sequence, and refold the result. |
| 🧱 **3D Fold Studio** | Explore ESMFold predictions with confidence coloring, residue inspection, and side-by-side comparison. |
| 🤖 **Helio Agent** | A LangGraph-powered agent that explains regions, uses tools, and connects model output to evidence. |
| 📚 **Live Research Context** | Retrieve NCBI, PubMed, ClinVar, and semantically ranked literature with links to original sources. |
| 🧪 **Scientific Tooling** | JASPAR motifs, CRISPR off-target scoring, codon optimization, primer design, melting temperature, and RNA structure. |
| 🕒 **Versioned Experiments** | Track edits and follow-ups, compare versions, restore prior states, and optionally persist complete sessions. |

---

## 🔬 Real by design

Proteus runs fully offline in deterministic mock mode with no API keys. Each subsystem independently upgrades to a live engine when configured, and the interface reports the backend's actual state instead of claiming a simulated engine is live.

| Subsystem | Default | Live configuration |
|-----------|---------|--------------------|
| NCBI, PubMed, and ClinVar | Real E-utilities calls | Always live |
| Translation, ORFs, GC, motifs, and optimization | Deterministic scientific compute | Always real |
| Sequence generation and scoring | Deterministic mock engine | NVIDIA Evo 2 40B or local Evo 2 |
| Protein structure | Placeholder PDB | ESMFold API |
| Intent, explanation, and agent reasoning | Heuristic fallback | OpenRouter |

Scoring signals are transparent heuristics—not clinical predictions. Proteus labels them accordingly and includes calibration tooling to measure performance against known ClinVar variants rather than presenting unvalidated scores as ground truth.

---

## 🚀 Setup & Deployment

### Quick Start (Local)

1. **Clone and configure**
   ```bash
   git clone https://github.com/SquaredPiano/evo.git
   cd evo
   cp .env.example .env
   # Add available API keys; mock mode works without them.
   ```

2. **Backend**
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn main:app --reload --port 8000
   ```

3. **Frontend**
   ```bash
   cd frontend
   npm install
   cp .env.example .env.local
   npm run dev
   ```

4. **Open**
   - App: [http://localhost:3000](http://localhost:3000)
   - API health: [http://localhost:8000/api/health](http://localhost:8000/api/health)

### Docker (Recommended)

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: [http://localhost:3000](http://localhost:3000)
- Backend: [http://localhost:8000](http://localhost:8000)

---

## 🛠️ Architecture

Proteus keeps Helix's streaming, event-driven core and extends it with richer editing, evidence, scientific computation, and persistence:

```text
Natural-language objective
          ↓
Intent Parse → Parallel Retrieval (NCBI / PubMed / ClinVar / Literature)
          ↓
Evo 2 Generation → Scoring → ESMFold → Explanation
          ↓
Editable Workspace ↔ Region Regeneration ↔ Scientific Tools
          ↓
Redis live session + optional MongoDB snapshots and history
```

- **Frontend:** Next.js 16, React 19, TypeScript, Zustand, Framer Motion, Three.js.
- **Backend:** FastAPI, Pydantic, Redis-backed session and event flow, optional MongoDB persistence.
- **AI stack:** Evo 2, ESMFold, OpenRouter, and a LangGraph agent.
- **Scientific stack:** Biopython, DNA Chisel, Primer3, ViennaRNA, and JASPAR.
- **Transport:** REST for control plus WebSocket streaming for progressive generation and explanation.

Two edit paths keep interaction fast:

- `POST /api/edit/base` handles a single-base mutation and re-scores without rerunning the full pipeline.
- `POST /api/edit/followup` handles natural-language revisions and streams only the affected pipeline stages.

---

## 🧪 Testing

```bash
cd backend
source .venv/bin/activate
pytest -q
```

```bash
cd frontend
npm run build
```

---

## 🧭 Project Structure

```text
evo/
├── backend/
│   ├── main.py
│   ├── pipeline/
│   ├── services/
│   ├── ws/
│   └── tests/
├── frontend/
│   ├── app/
│   ├── components/
│   ├── hooks/
│   ├── lib/
│   └── public/
├── docs/
├── deploy/
├── docker-compose.yml
└── README.md
```

---

## ⚠️ Research Use Note

Proteus is a research and design platform, not a clinical decision system. Treat generated sequences, scores, structures, and explanations as hypotheses that require domain review and experimental validation.

---

## 🤝 Contributing

Contributions are welcome.

1. Fork the repository
2. Create a feature branch
3. Ensure tests and builds pass
4. Open a pull request

---

<div align="center">
  <sub>Proteus · Helix, evolved</sub>
</div>
