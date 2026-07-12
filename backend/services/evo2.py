"""Evo2 service layer — the core of Helix.

Three backends behind one interface:
  - Evo2LocalService:  wraps arcinstitute/evo2 on the GX10 (primary)
  - Evo2NIMService:    NVIDIA NIM API fallback (40B model)
  - Evo2MockService:   realistic mock for dev/testing

Use `create_evo2_service(settings)` to get the right one from config.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import random
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import numpy as np

if TYPE_CHECKING:
    from config import Settings

from models.domain import ForwardResult, Impact, MutationScore


# ---------------------------------------------------------------------------
# Generation provenance — the honest structured result of a generation call
# ---------------------------------------------------------------------------

@dataclass
class GenerationResult:
    """Structured, provenance-carrying result of a single generation call.

    This is the honest surface for reprompting/regeneration: it carries not just
    the generated bases but *where they came from* and *how confident the model
    was*, so a science UI can never mistake a mock fallback for real Evo2.

    Fields:
      generated:     the newly generated bases (the suffix beyond ``seed``).
      sampled_probs: per-generated-token probability from Evo2 (REAL model
                     confidence) when the engine is ``nim``; ``None`` for mock and
                     local (we never fabricate probabilities). Under nim_api a
                     failed call RAISES rather than degrading, so a mock
                     suffix is never returned as a NIM result.
      engine:        actual engine that produced these bases — one of
                     "nim" | "local" | "mock". Under nim_api a failed NIM call
                     raises; it does not silently fall back to mock.
      elapsed_ms:    wall-clock (or engine-reported) latency for the call.
      seed:          the conditioning prefix that was passed in.
      n_tokens:      number of tokens requested.
    """

    generated: str
    sampled_probs: list[float] | None = None
    engine: str = "unknown"
    elapsed_ms: float | None = None
    seed: str = ""
    n_tokens: int = 0

    @property
    def sampled_probs_are_real_model_confidence(self) -> bool:
        """True only when sampled_probs come from a real Evo2 inference (NIM)."""
        return self.engine == "nim" and self.sampled_probs is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "generated": self.generated,
            "sampled_probs": self.sampled_probs,
            "engine": self.engine,
            "elapsed_ms": self.elapsed_ms,
            "n_tokens": self.n_tokens,
            "sampled_probs_are_real_model_confidence": self.sampled_probs_are_real_model_confidence,
        }


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class Evo2Service(ABC):
    """Abstract Evo2 interface. Every downstream module depends on this."""

    # Honest engine label for provenance. NIM overrides generate_detailed entirely.
    _engine_name: str = "unknown"

    @abstractmethod
    async def forward(self, sequence: str) -> ForwardResult:
        """Run a forward pass, returning per-position log-likelihoods."""

    @abstractmethod
    async def score(self, sequence: str) -> float:
        """Return the mean log-likelihood for the full sequence."""

    @abstractmethod
    async def score_mutation(
        self, sequence: str, position: int, alt_base: str
    ) -> MutationScore:
        """Score a single-base substitution by comparing ref vs alt."""

    @abstractmethod
    async def generate(
        self, seed: str, n_tokens: int, temperature: float = 1.0
    ) -> AsyncGenerator[str, None]:
        """Autoregressively generate tokens, yielding one at a time."""

    async def generate_detailed(
        self, seed: str, n_tokens: int, temperature: float = 1.0
    ) -> GenerationResult:
        """Generate and return structured provenance (bases + engine + confidence).

        Default implementation drives the streaming ``generate`` and reports the
        engine honestly with ``sampled_probs=None`` — no probabilities are
        fabricated. NIM overrides this to capture real Evo2 ``sampled_probs`` and
        to report ``mock_fallback`` truthfully when it degrades to mock.

        NOTE: generation is autoregressive / left-to-right — it conditions on the
        ``seed`` prefix only. Callers doing region splicing must treat this as a
        prefix-only limitation (see services/regeneration.py).
        """
        started = time.perf_counter()
        tokens: list[str] = []
        async for token in self.generate(seed, n_tokens, temperature):
            tokens.append(token)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return GenerationResult(
            generated="".join(tokens),
            sampled_probs=None,
            engine=self._engine_name,
            elapsed_ms=round(elapsed_ms, 2),
            seed=seed,
            n_tokens=n_tokens,
        )

    @abstractmethod
    async def health(self) -> dict[str, object]:
        """Return service health status."""


# ---------------------------------------------------------------------------
# Mock implementation — realistic enough for TDD and frontend integration
# ---------------------------------------------------------------------------

# Dinucleotide transition probabilities (simplified Markov chain)
_TRANSITION: dict[str, dict[str, float]] = {
    "A": {"A": 0.20, "T": 0.30, "C": 0.15, "G": 0.35},
    "T": {"A": 0.25, "T": 0.20, "C": 0.35, "G": 0.20},
    "C": {"A": 0.15, "T": 0.25, "C": 0.25, "G": 0.35},
    "G": {"A": 0.30, "T": 0.15, "C": 0.30, "G": 0.25},
}

# Known regulatory motifs that boost functional scores
_MOTIFS: dict[str, float] = {
    "TATAAA": 0.08,   # TATA box
    "CCAAT": 0.05,    # CAAT box
    "GGGCGG": 0.04,   # GC box (Sp1 binding)
    "ATG": 0.03,      # start codon
    "AATAAA": 0.04,   # poly-A signal
}


def _deterministic_seed(sequence: str) -> int:
    """Derive a stable RNG seed from a sequence so results are reproducible."""
    return int(hashlib.sha256(sequence.encode()).hexdigest()[:8], 16)


def _mock_logits(sequence: str) -> list[float]:
    """Seeded-random per-position values for the OFFLINE mock engine only.

    This deliberately injects RNG noise so ``EVO2_MODE=mock`` behaves like a
    stochastic model for local development and tests. It is NOT used by any real
    engine path (nim/local): a real engine must never serve fabricated random
    numbers. For the NIM engine's per-position array, see ``_composition_logits``.
    """
    rng = np.random.default_rng(_deterministic_seed(sequence))
    seq = sequence.upper()
    n = len(seq)

    # Base: random log-likelihoods in a biologically plausible range
    logits = rng.normal(loc=-0.35, scale=0.12, size=n).tolist()

    # Boost positions inside known motifs
    for motif, boost in _MOTIFS.items():
        start = 0
        while True:
            idx = seq.find(motif, start)
            if idx == -1:
                break
            for j in range(idx, min(idx + len(motif), n)):
                logits[j] += boost
            start = idx + 1

    # Slight boost for G/C (higher stability)
    for i, base in enumerate(seq):
        if base in ("G", "C"):
            logits[i] += 0.02

    return logits


def _composition_logits(sequence: str) -> list[float]:
    """Deterministic per-position composition signal (NOT an Evo2 log-likelihood).

    This is a transparent, reproducible function of the ACTUAL sequence — no RNG.
    Each position's value is the log-odds of its base given the previous base
    under a fixed dinucleotide model (``_TRANSITION``), relative to a uniform
    0.25 baseline, plus known-motif boosts and a slight GC-stability term.

    Provenance, stated plainly: this is a composition/motif heuristic used where a
    per-position array is required for a pasted / non-generated sequence. The
    hosted NIM endpoint exposes no per-position forward pass, so real Evo2
    confidence is available ONLY as the per-generated-base ``sampled_probs``
    captured during generation. Callers must not present this array as an Evo2
    likelihood.
    """
    seq = sequence.upper()
    n = len(seq)
    if n == 0:
        return []

    logits: list[float] = []
    prev: str | None = None
    for base in seq:
        if prev is not None and prev in _TRANSITION and base in _TRANSITION[prev]:
            p = _TRANSITION[prev][base]
        else:
            p = 0.25  # first base / non-ACGT: uniform prior
        logits.append(math.log(max(p, 1e-6) / 0.25))
        prev = base

    for motif, boost in _MOTIFS.items():
        start = 0
        while True:
            idx = seq.find(motif, start)
            if idx == -1:
                break
            for j in range(idx, min(idx + len(motif), n)):
                logits[j] += boost
            start = idx + 1

    for i, base in enumerate(seq):
        if base in ("G", "C"):
            logits[i] += 0.02

    return logits


class Evo2MockService(Evo2Service):
    """Mock backend for development and testing.

    Produces deterministic, biologically-informed outputs so the
    scoring pipeline and CLI can be validated before real Evo2 is ready.
    """

    _engine_name = "mock"

    async def forward(self, sequence: str) -> ForwardResult:
        logits = _mock_logits(sequence)
        sequence_score = float(np.mean(logits)) if logits else 0.0
        return ForwardResult(
            logits=logits,
            sequence_score=sequence_score,
            embeddings=None,
        )

    async def score(self, sequence: str) -> float:
        logits = _mock_logits(sequence)
        return float(np.mean(logits)) if logits else 0.0

    async def score_mutation(
        self, sequence: str, position: int, alt_base: str
    ) -> MutationScore:
        seq = sequence.upper()
        if position < 0 or position >= len(seq):
            raise ValueError(f"Position {position} out of range [0, {len(seq)})")

        ref_base = seq[position]
        alt_base = alt_base.upper()

        # Score original
        ref_score = await self.score(seq)

        # Score mutated
        mutated = seq[:position] + alt_base + seq[position + 1 :]
        alt_score = await self.score(mutated)

        delta = alt_score - ref_score
        return MutationScore(
            position=position,
            reference_base=ref_base,
            alternate_base=alt_base,
            delta_likelihood=round(delta, 6),
            predicted_impact=Impact.from_delta(delta),
        )

    async def generate(
        self, seed: str, n_tokens: int, temperature: float = 1.0
    ) -> AsyncGenerator[str, None]:
        rng = random.Random(_deterministic_seed(seed + str(n_tokens)))
        last = seed[-1].upper() if seed else "A"
        # Scale delay by sequence length to keep wall-clock time reasonable.
        # Short (<160): visible streaming. Medium (160-5k): fast streaming. Long (>5k): minimal delay.
        if n_tokens >= 5000:
            token_delay = 0.0005
        elif n_tokens >= 160:
            token_delay = 0.004
        else:
            token_delay = 0.012

        for _ in range(n_tokens):
            weights = _TRANSITION.get(last, _TRANSITION["A"])
            bases = list(weights.keys())
            probs = list(weights.values())

            # Apply temperature
            if temperature != 1.0:
                log_probs = [math.log(p) / temperature for p in probs]
                max_lp = max(log_probs)
                exp_probs = [math.exp(lp - max_lp) for lp in log_probs]
                total = sum(exp_probs)
                probs = [ep / total for ep in exp_probs]

            chosen = rng.choices(bases, weights=probs, k=1)[0]
            last = chosen
            yield chosen
            # Simulate inference latency
            await asyncio.sleep(token_delay)

    async def health(self) -> dict[str, object]:
        return {
            "status": "healthy",
            "model": "mock",
            "gpu_available": False,
            "inference_mode": "mock",
        }


# ---------------------------------------------------------------------------
# Local inference — wraps arcinstitute/evo2 on the GX10
# ---------------------------------------------------------------------------

class Evo2LocalService(Evo2Service):
    """Wraps the Evo2 Python package for local GPU inference.

    Requires: pip install evo2 (or the arcinstitute package)
    Hardware: ASUS ASCENT GX10 with NVIDIA GPU + 128 GB LPDDRX
    """

    _engine_name = "local"

    def __init__(self, model_path: str = "arcinstitute/evo2_7b") -> None:
        self._model_path = model_path
        self._model: object | None = None

    def _load_model(self) -> object:
        if self._model is None:
            # Deferred import — only needed when actually running local
            from evo2 import Evo2  # type: ignore[import-untyped]

            self._model = Evo2(self._model_path)
        return self._model

    async def forward(self, sequence: str) -> ForwardResult:
        model = self._load_model()
        loop = asyncio.get_running_loop()
        logits, _embeddings = await loop.run_in_executor(
            None, model.forward, sequence  # type: ignore[union-attr]
        )
        logits_list = logits.tolist() if hasattr(logits, "tolist") else list(logits)
        sequence_score = float(np.mean(logits_list)) if logits_list else 0.0
        return ForwardResult(
            logits=logits_list,
            sequence_score=sequence_score,
            embeddings=None,  # skip embedding transfer for speed
        )

    async def score(self, sequence: str) -> float:
        model = self._load_model()
        loop = asyncio.get_running_loop()
        score_val = await loop.run_in_executor(
            None, model.score, sequence  # type: ignore[union-attr]
        )
        return float(score_val)

    async def score_mutation(
        self, sequence: str, position: int, alt_base: str
    ) -> MutationScore:
        seq = sequence.upper()
        if position < 0 or position >= len(seq):
            raise ValueError(f"Position {position} out of range [0, {len(seq)})")

        ref_base = seq[position]
        mutated = seq[:position] + alt_base.upper() + seq[position + 1 :]

        ref_score, alt_score = await asyncio.gather(
            self.score(seq), self.score(mutated)
        )
        delta = alt_score - ref_score
        return MutationScore(
            position=position,
            reference_base=ref_base,
            alternate_base=alt_base.upper(),
            delta_likelihood=round(delta, 6),
            predicted_impact=Impact.from_delta(delta),
        )

    async def generate(
        self, seed: str, n_tokens: int, temperature: float = 1.0
    ) -> AsyncGenerator[str, None]:
        # Evo2 local generation: extend the seed sequence token by token
        model = self._load_model()
        loop = asyncio.get_running_loop()
        current = seed

        for _ in range(n_tokens):
            # Run a forward pass on the current sequence
            logits, _ = await loop.run_in_executor(
                None, model.forward, current  # type: ignore[union-attr]
            )
            # Sample from the last position's distribution
            last_logits = logits[-1] if hasattr(logits, "__getitem__") else logits
            if hasattr(last_logits, "numpy"):
                last_logits = last_logits.numpy()
            probs = _softmax(np.array(last_logits) / temperature)
            # Map to bases (Evo2 uses ACGT ordering)
            bases = ["A", "C", "G", "T"]
            chosen = np.random.choice(bases, p=probs[:4] / probs[:4].sum())
            current += chosen
            yield chosen

    async def health(self) -> dict[str, object]:
        try:
            self._load_model()
            return {
                "status": "healthy",
                "model": self._model_path,
                "gpu_available": True,
                "inference_mode": "local",
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "model": self._model_path,
                "gpu_available": False,
                "inference_mode": "local",
                "error": str(e),
            }


# ---------------------------------------------------------------------------
# NVIDIA NIM API — fallback to the 40B model via cloud
# ---------------------------------------------------------------------------

class Evo2NIMService(Evo2Service):
    """NVIDIA NIM API client for Evo2-40B.

    Used when local GPU is unavailable or when the 40B model is needed.
    """

    _engine_name = "nim"

    def __init__(self, api_key: str, api_url: str) -> None:
        self._api_key = api_key
        self._api_url = api_url

    async def _post(self, payload: dict[str, object]) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                self._api_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _is_retryable_nim_error(exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return status in {429, 500, 502, 503, 504}
        msg = str(exc).lower()
        return "429" in msg or "too many requests" in msg or "rate limit" in msg

    async def forward(self, sequence: str) -> ForwardResult:
        # The hosted NIM endpoint exposes generation only — no per-position
        # forward pass — so there is NO real per-position Evo2 log-likelihood for
        # an arbitrary pasted sequence. Real Evo2 confidence is available only as
        # the per-generated-base sampled_probs captured during generation
        # (see generate_detailed). For scorers that need a per-position array over
        # a non-generated sequence we return a DETERMINISTIC composition/motif
        # signal derived from the actual sequence — honestly not an Evo2 LL, and
        # never seeded-random fabrication.
        logits = _composition_logits(sequence)
        return ForwardResult(
            logits=logits,
            sequence_score=float(np.mean(logits)) if logits else 0.0,
            embeddings=None,
        )

    async def score(self, sequence: str) -> float:
        result = await self.forward(sequence)
        return result.sequence_score

    async def score_mutation(
        self, sequence: str, position: int, alt_base: str
    ) -> MutationScore:
        seq = sequence.upper()
        if position < 0 or position >= len(seq):
            raise ValueError(f"Position {position} out of range [0, {len(seq)})")

        ref_base = seq[position]
        mutated = seq[:position] + alt_base.upper() + seq[position + 1 :]

        ref_score, alt_score = await asyncio.gather(
            self.score(seq), self.score(mutated)
        )
        delta = alt_score - ref_score
        return MutationScore(
            position=position,
            reference_base=ref_base,
            alternate_base=alt_base.upper(),
            delta_likelihood=round(delta, 6),
            predicted_impact=Impact.from_delta(delta),
        )

    async def generate(
        self, seed: str, n_tokens: int, temperature: float = 1.0
    ) -> AsyncGenerator[str, None]:
        # FAIL-LOUD: a NIM API failure (422, 429, 5xx, timeout) RAISES. We never
        # degrade to fabricated tokens under nim_api — a hard failure must surface
        # to the caller as an error, not silently stream fake sequence.
        clamped_temp = max(0.01, min(float(temperature), 1.0))
        data = await self._post({
            "sequence": seed,
            "num_tokens": n_tokens,
            "top_k": 4,
            "enable_sampled_probs": True,
            "temperature": clamped_temp,
        })
        generated = _extract_generated_sequence(data)
        suffix = generated[len(seed):] if generated.startswith(seed) else generated

        # NIM returns the full suffix in one shot — yield base-by-base so the
        # WebSocket client can stream into the IDE.
        for base in (suffix or "").upper():
            if base not in ("A", "T", "C", "G", "N"):
                continue
            yield base
            await asyncio.sleep(0.004)

    async def generate_detailed(
        self, seed: str, n_tokens: int, temperature: float = 1.0
    ) -> GenerationResult:
        """NIM generation with real Evo2 provenance.

        On success, returns ``engine="nim"`` plus the REAL per-generated-token
        ``sampled_probs`` from the Evo2-40B model — genuine model confidence,
        distinct from the heuristic 4D scores. FAIL-LOUD: on ANY error
        (422/429/5xx/timeout) this RAISES rather than degrading to fabricated
        output, so the caller can never present mock sequence as real NIM.

        Conditioning is prefix-only (autoregressive): generated bases see the
        ``seed`` prefix but not any downstream suffix.
        """
        started = time.perf_counter()
        clamped_temp = max(0.01, min(float(temperature), 1.0))
        data = await self._post({
            "sequence": seed,
            "num_tokens": n_tokens,
            "top_k": 4,
            "enable_sampled_probs": True,
            "temperature": clamped_temp,
        })
        generated = _extract_generated_sequence(data)
        suffix = generated[len(seed):] if generated.startswith(seed) else generated
        suffix = "".join(b for b in suffix.upper() if b in ("A", "T", "C", "G", "N"))
        probs = _extract_sampled_probs(data)
        # Keep probs aligned to the returned bases; if lengths disagree, trim
        # to the common prefix so per-base confidence never misaligns.
        if probs is not None and len(probs) != len(suffix):
            common = min(len(probs), len(suffix))
            probs = probs[:common] if common > 0 else None
        elapsed_ms = _nim_elapsed_ms(data, started)
        return GenerationResult(
            generated=suffix,
            sampled_probs=probs,
            engine="nim",
            elapsed_ms=elapsed_ms,
            seed=seed,
            n_tokens=n_tokens,
        )

    async def health(self) -> dict[str, object]:
        try:
            await self._post({
                "sequence": "ATG",
                "num_tokens": 1,
                "top_k": 1,
                "enable_sampled_probs": True,
            })
            return {
                "status": "healthy",
                "model": "evo2-40b-nim",
                "gpu_available": True,
                "inference_mode": "nim_api",
                "scoring_note": "Real Evo2-40B generation returns per-generated-base sampled_probs (genuine model confidence). The hosted endpoint has no per-position forward pass, so per-position arrays over pasted sequences are a deterministic composition/motif signal, not an Evo2 log-likelihood.",
            }
        except Exception as e:
            if self._is_retryable_nim_error(e):
                return {
                    "status": "degraded",
                    "model": "evo2-40b-nim",
                    "gpu_available": True,
                    "inference_mode": "nim_api",
                    "error": str(e),
                }
            return {
                "status": "unhealthy",
                "model": "evo2-40b-nim",
                "gpu_available": False,
                "inference_mode": "nim_api",
                "error": str(e),
            }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


def _extract_sampled_probs(data: dict[str, object]) -> list[float] | None:
    """Pull the per-generated-token sampled probabilities from a NIM response.

    These are REAL Evo2 model confidences. Returns None if absent or malformed —
    we never fabricate probabilities.
    """
    probs = data.get("sampled_probs")
    if not isinstance(probs, list) or not probs:
        return None
    out: list[float] = []
    for p in probs:
        try:
            out.append(round(float(p), 6))
        except (TypeError, ValueError):
            return None
    return out


def _nim_elapsed_ms(data: dict[str, object], started: float) -> float:
    """Prefer the engine-reported elapsed_ms; fall back to measured wall-clock."""
    reported = data.get("elapsed_ms")
    if isinstance(reported, (int, float)):
        return round(float(reported), 2)
    return round((time.perf_counter() - started) * 1000.0, 2)


def _extract_generated_sequence(data: dict[str, object]) -> str:
    generated = data.get("generated_sequence")
    if isinstance(generated, str):
        return generated
    sequence = data.get("sequence")
    if isinstance(sequence, str):
        return sequence
    tokens = data.get("tokens")
    if isinstance(tokens, list):
        return "".join(str(t) for t in tokens)
    return ""



# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_evo2_service(cfg: Settings | None = None) -> Evo2Service:
    """Instantiate the right Evo2 backend from config."""
    if cfg is None:
        from config import settings as cfg  # type: ignore[assignment]

    assert cfg is not None

    if cfg.evo2_mode == "local":
        return Evo2LocalService(model_path=cfg.evo2_model_path)
    if cfg.evo2_mode == "nim_api":
        api_key = (
            cfg.evo2_nim_api_key
            or getattr(cfg, "evo2_key", "")
            or os.environ.get("EVO2_KEY", "")
            or os.environ.get("EVO2_NIM_API_KEY", "")
            or os.environ.get("NVIDIA_API_KEY", "")
        )
        if not api_key:
            raise ValueError(
                "EVO2_NIM_API_KEY, EVO2_KEY, or NVIDIA_API_KEY required for NIM mode"
            )
        return Evo2NIMService(
            api_key=api_key, api_url=cfg.evo2_nim_api_url
        )
    return Evo2MockService()
