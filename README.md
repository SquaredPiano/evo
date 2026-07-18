<div align="center">
  <img src="frontend/public/favicon.svg" alt="Proteus Logo" width="110" style="margin-bottom: 18px;"/>

  # Proteus

  **An IDE for the code of life — from prompt to editable DNA workspace in real time.**

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

Proteus is the **better, rebuilt evolution of Helix**, our original AI-native genomic design IDE.

Helix proved that a natural-language objective could become generated DNA, scored candidates, predicted structures, and an editable workspace. Proteus takes that same vision further with a real inline sequence editor, region-level regeneration, stronger scientific tooling, live research evidence, durable experiment history, and honest visibility into which engines are running.

> *"Describe the biology. Generate the sequence. Edit the code of life."*

### Features

| Feature | Description |
|---------|-------------|
| 🧬 **Evo 2 Generation** | Generate DNA with NVIDIA-hosted Evo 2 40B, a local engine, or deterministic mock mode. |
| ✍️ **Real Sequence Editor** | Select, overwrite, reverse-complement, mutate, and re-score bases directly. |
| 🔁 **Region Regeneration** | Rewrite only a selected region, splice it back in, and refold the result. |
| 🧱 **3D Fold Studio** | Explore ESMFold predictions with confidence coloring and side-by-side comparison. |
| 🤖 **Helio Agent** | Explain regions, use scientific tools, and connect model output to real evidence. |
| 📚 **Live Research Context** | Retrieve NCBI, PubMed, ClinVar, and semantically ranked literature. |
| 🧪 **Scientific Tooling** | JASPAR motifs, CRISPR scoring, codon optimization, primer design, Tm, and RNA structure. |
| 🕒 **Versioned Experiments** | Compare edits, restore earlier states, and optionally persist complete sessions. |

---

## 🚀 Setup & Deployment

**The only requirement is Docker Desktop.**

### Quick Start

1. **Clone and configure**
   ```bash
   git clone https://github.com/SquaredPiano/evo.git
   cd evo
   cp .env.example .env
   # Add available API keys; mock mode works without them.
   ```

2. **Run**
   ```bash
   docker compose up --build
   ```

3. **Open**
   - App: [http://localhost:3000](http://localhost:3000)
   - API health: [http://localhost:8000/api/health](http://localhost:8000/api/health)

---

## 🛠️ Architecture

Proteus keeps Helix's streaming, event-driven core and extends it with richer editing, scientific computation, evidence, and persistence:

```text
Prompt -> Intent Parse -> Retrieval (NCBI / PubMed / ClinVar)
      -> Evo 2 Generation -> Scoring -> ESMFold -> Explanation
      -> Editable Workspace -> Region Regeneration
```

- **Frontend:** Next.js 16, React 19, Zustand, Framer Motion, Three.js.
- **Backend:** FastAPI, Pydantic, Redis-backed sessions and event flow.
- **AI stack:** Evo 2, ESMFold, OpenRouter, and a LangGraph agent.
- **Science:** Biopython, DNA Chisel, Primer3, ViennaRNA, and JASPAR.
- **Persistence:** Redis for live sessions with optional MongoDB snapshots and history.
- **Transport:** REST for control plus WebSocket streaming.

Proteus runs without API keys in deterministic mock mode and upgrades each subsystem independently when live engines are configured. The interface always reports the backend's actual state.

---

## ⚠️ Research Use Note

Proteus is a research and design platform, not a clinical decision system. Treat its outputs as hypotheses requiring domain review and experimental validation.

---

## 🤝 Contributing

Contributions are welcome. Please fork the repository and submit a pull request.

---

<div align="center">
  <sub>Proteus · Helix, evolved</sub>
</div>
