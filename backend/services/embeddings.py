"""Text embeddings for semantic (vector) search.

Two interchangeable backends sit behind one interface:

* :class:`LocalHashEmbedder` - a deterministic, dependency-free feature-hashing
  embedder. No network, no API key; the same input always maps to the same
  vector. This is the fallback that keeps vector search working offline / in a
  demo with zero configuration.
* :class:`ApiEmbedder` - calls an OpenAI-compatible embeddings endpoint
  (OpenAI, Azure OpenAI, or any gateway mirroring ``POST /embeddings``). Higher
  semantic quality; used only when an API key is configured.

:func:`create_embedder` implements the **hybrid** policy: pick the API embedder
when a key is present, otherwise fall back to the local one. Both backends emit
**L2-normalised** vectors of the SAME configured dimension, so a single MongoDB
Atlas vector index works regardless of which backend a given deployment runs.

IMPORTANT: do not mix backends within one *populated* index - the API and local
vector spaces are unrelated, so cross-backend similarity is meaningless. Pick
one embedder per deployment; if you switch, re-index.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Protocol, runtime_checkable

import numpy as np

logger = logging.getLogger("evo")

DEFAULT_EMBEDDING_DIM = 256

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@runtime_checkable
class Embedder(Protocol):
    """Anything that turns text into fixed-dimension L2-normalised vectors."""

    name: str
    dim: int

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec
    return vec / norm


def cosine_similarity(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 if either vector is zero/empty."""
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    if va.size == 0 or vb.size == 0 or va.shape != vb.shape:
        return 0.0
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


# ---------------------------------------------------------------------------
# Local deterministic embedder (the offline fallback)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lowercase word/number tokens plus adjacent bigrams (a little word order)."""
    tokens = _TOKEN_RE.findall(text.lower())
    grams: list[str] = list(tokens)
    grams.extend(f"{a} {b}" for a, b in zip(tokens, tokens[1:]))
    return grams


def _stable_hash(feature: str) -> int:
    """Deterministic 64-bit hash - unlike ``hash()``, stable across processes."""
    return int.from_bytes(hashlib.sha1(feature.encode("utf-8")).digest()[:8], "big")


class LocalHashEmbedder:
    """Deterministic feature-hashing (a.k.a. hashing-trick) embedder.

    Each token/bigram is hashed into one of ``dim`` buckets with a signed
    contribution; the accumulated vector is L2-normalised. It captures lexical
    overlap (shared vocabulary → higher cosine), which is enough for useful
    literature ranking without any model or network call. It is NOT semantic in
    the neural sense - synonyms that share no tokens won't match - but it is
    free, instant, and perfectly reproducible.
    """

    name = "local-hash"

    def __init__(self, dim: int = DEFAULT_EMBEDDING_DIM) -> None:
        if dim <= 0:
            raise ValueError("embedding dim must be positive")
        self.dim = dim

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float64)
        for feature in _tokenize(text):
            h = _stable_hash(feature)
            idx = h % self.dim
            sign = 1.0 if (h >> 32) & 1 else -1.0
            vec[idx] += sign
        return _l2_normalize(vec).tolist()


# ---------------------------------------------------------------------------
# OpenAI-compatible API embedder (the high-quality path)
# ---------------------------------------------------------------------------


class ApiEmbedder:
    """Embeddings via an OpenAI-compatible ``POST /embeddings`` endpoint.

    Works with OpenAI ``text-embedding-3-*`` (which honour the ``dimensions``
    parameter, so the returned vector matches the configured index dimension),
    or any gateway that mirrors that contract. Vectors are re-normalised locally
    because truncating dimensions denormalises them.
    """

    name = "api"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dim: int = DEFAULT_EMBEDDING_DIM,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self.dim = dim
        self._timeout = timeout

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import httpx

        payload: dict[str, object] = {"model": self._model, "input": texts}
        # text-embedding-3-* support server-side truncation to a target size,
        # keeping every deployment's vectors at EMBEDDING_DIM. Harmless to send
        # to models that ignore it (they return their native dimension, which
        # the caller's index must then match).
        if self.dim:
            payload["dimensions"] = self.dim
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/embeddings", headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()
        # Preserve request order - the API returns an "index" per item.
        items = sorted(data["data"], key=lambda d: d["index"])
        return [_l2_normalize(np.asarray(i["embedding"], dtype=np.float64)).tolist() for i in items]


# ---------------------------------------------------------------------------
# Hybrid factory
# ---------------------------------------------------------------------------


def create_embedder(settings: object) -> Embedder:
    """Pick the embedder per the hybrid policy.

    API embedder when an embedding key is configured (``EMBEDDING_API_KEY``, or
    the legacy ``OPENAI_API_KEY``); deterministic local embedder otherwise.
    """
    dim = int(getattr(settings, "embedding_dim", DEFAULT_EMBEDDING_DIM) or DEFAULT_EMBEDDING_DIM)
    api_key = (
        getattr(settings, "embedding_api_key", "")
        or getattr(settings, "openai_api_key", "")
        or os.environ.get("EMBEDDING_API_KEY", "")
    )
    if api_key:
        embedder = ApiEmbedder(
            api_key=api_key,
            base_url=getattr(settings, "embedding_base_url", "https://api.openai.com/v1"),
            model=getattr(settings, "embedding_model", "text-embedding-3-small"),
            dim=dim,
        )
        logger.info("Embeddings: using API embedder (model=%s, dim=%d).", embedder._model, dim)
        return embedder
    logger.info("Embeddings: no API key - using deterministic local embedder (dim=%d).", dim)
    return LocalHashEmbedder(dim=dim)
