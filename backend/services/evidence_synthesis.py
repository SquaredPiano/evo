"""Gemini-backed literature detail synthesis.

``RegionEvidence.detail`` (see docs/region_evidence_interface.md §1/§4) is
specced as a one-to-two sentence explanation that is honest about
provenance. A raw PubMed abstract is too long and noisy for a hover card, so
this module asks Gemini to condense one into that shape.

This is a different job from services/llm.py: that module is the OpenRouter
gateway for intent parsing / explanation / agent reasoning. This is a narrow,
single-purpose literature summarizer that happens to use Gemini
(``config.settings.gemini_api_key``, previously configured but unused).

Mirrors pipeline/retrieval.py's "partial success is success" — never raises.
Any failure (no key, network error, malformed response) degrades to a
truncated abstract.
"""

from __future__ import annotations

import logging
import os

import httpx

from config import settings
from services.pubmed import PubMedArticle

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_FALLBACK_ABSTRACT_CHARS = 240


def _gemini_api_key() -> str:
    return settings.gemini_api_key or os.environ.get("GEMINI_API_KEY", "")


def gemini_available() -> bool:
    """True when a Gemini API key is configured."""
    return bool(_gemini_api_key())


def _fallback_detail(article: PubMedArticle) -> str:
    """Truncated-abstract fallback — never claims more than the source does."""
    abstract = (article.abstract or "").strip()
    if not abstract:
        title = article.title.strip() or "Untitled"
        return f"{title} ({article.year or 'year unknown'}) — no abstract available."
    if len(abstract) <= _FALLBACK_ABSTRACT_CHARS:
        return abstract
    return abstract[:_FALLBACK_ABSTRACT_CHARS].rsplit(" ", 1)[0] + "…"


def _build_prompt(article: PubMedArticle, gene: str | None, label: str | None) -> str:
    focus = gene or "the region of interest"
    region_note = f" in the context of {label}" if label else ""
    return (
        "You are writing a one-to-two sentence hover-card summary of a research "
        "paper for a genomic design tool. Be concise and strictly honest about "
        "what the paper actually shows: do not assert pathogenicity, safety, or "
        "clinical significance, and do not invent a confidence level the "
        "abstract doesn't support. If the abstract is unclear or unrelated to "
        f"{focus}{region_note}, say so plainly instead of guessing.\n\n"
        f"Title: {article.title}\n"
        f"Year: {article.year or 'unknown'}\n"
        f"Journal: {article.journal or 'unknown'}\n"
        f"Abstract: {article.abstract or '(no abstract available)'}\n\n"
        f"Gene/region context: {focus}{region_note}\n\n"
        "Write only the 1-2 sentence summary, no preamble, no quotes."
    )


async def synthesize_detail(
    article: PubMedArticle,
    gene: str | None = None,
    label: str | None = None,
) -> str:
    """Concise, honest 1-2 sentence relevance summary for a PubMed hit.

    Calls Gemini to condense the abstract into a hover-card-sized explanation.
    Falls back to a truncated abstract when no key is configured, the request
    fails, or the response is malformed — this function never raises.
    """
    api_key = _gemini_api_key()
    if not api_key:
        return _fallback_detail(article)

    payload = {
        "contents": [{"parts": [{"text": _build_prompt(article, gene, label)}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 200},
    }
    url = f"{GEMINI_BASE_URL}/models/{settings.gemini_model}:generateContent"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = (text or "").strip()
        return text or _fallback_detail(article)
    except Exception:
        logger.warning("Gemini detail synthesis failed for PMID=%s", article.pmid, exc_info=True)
        return _fallback_detail(article)
