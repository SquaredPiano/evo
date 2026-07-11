"""Explanation layer — generates mechanistic reports for candidates via LLM streaming.

Streams through the unified OpenRouter client. Falls back to a score-based
summary when no LLM is available.
"""

from __future__ import annotations

import logging

from models.domain import DesignSpec
from services import llm
from ws.events import ExplanationChunkData, ExplanationChunkEvent
from ws.manager import WebSocketManager

logger = logging.getLogger("evo")

SYSTEM_PROMPT = """You are a genomic design analyst for Evo, a genomic design IDE. \
Given a candidate DNA sequence, its scoring results, and the researcher's design goal, \
write a concise mechanistic explanation (3-5 sentences) covering:

1. Why this candidate scores well or poorly based on its functional plausibility and tissue specificity
2. Any off-target risks or notable sequence features
3. A brief suggested next step for wet lab validation

Be specific to the actual scores and sequence properties. Do not be generic. \
Use scientific language appropriate for a molecular biology researcher."""


def _build_prompt(
    sequence: str,
    scores: dict,
    spec: DesignSpec,
) -> str:
    """Build the user prompt with candidate details."""
    parts = [f"Design goal: {spec.design_type}"]
    if spec.target_gene:
        parts.append(f"Target gene: {spec.target_gene}")
    if spec.organism:
        parts.append(f"Organism: {spec.organism}")
    if spec.tissue_specificity:
        if spec.tissue_specificity.high_expression:
            parts.append(f"Target tissues: {', '.join(spec.tissue_specificity.high_expression)}")
    if spec.therapeutic_context:
        parts.append(f"Therapeutic context: {spec.therapeutic_context}")

    parts.append(f"\nCandidate sequence ({len(sequence)} bp): {sequence[:100]}{'...' if len(sequence) > 100 else ''}")
    parts.append(f"\nScoring results:")
    parts.append(f"  Functional plausibility: {scores.get('functional', 'N/A')}")
    parts.append(f"  Tissue specificity: {scores.get('tissue_specificity', 'N/A')}")
    parts.append(f"  Off-target risk: {scores.get('off_target', 'N/A')}")
    parts.append(f"  Novelty: {scores.get('novelty', 'N/A')}")
    if "combined" in scores:
        parts.append(f"  Combined rank: {scores['combined']}")

    parts.append("\nProvide a concise mechanistic explanation of this candidate.")
    return "\n".join(parts)


def _build_score_based_fallback(scores: dict, spec: DesignSpec) -> list[str]:
    """Generate a useful explanation from actual scores when no LLM is available."""
    chunks: list[str] = []

    functional = scores.get("functional")
    tissue = scores.get("tissue_specificity")
    off_target = scores.get("off_target")
    novelty = scores.get("novelty")
    combined = scores.get("combined")

    # Overall assessment
    if combined is not None:
        if combined >= 0.7:
            chunks.append("This candidate shows strong overall potential with a high combined score.")
        elif combined >= 0.4:
            chunks.append("This candidate has moderate potential — some dimensions score well while others may need optimization.")
        else:
            chunks.append("This candidate scores below average and may require significant redesign.")

    # Functional assessment
    if functional is not None:
        if functional >= 0.7:
            chunks.append(f"Functional plausibility is high ({functional:.2f}), suggesting the sequence maintains biologically coherent patterns.")
        elif functional < 0.4:
            chunks.append(f"Functional plausibility is low ({functional:.2f}), indicating potential disruption of essential sequence motifs.")

    # Tissue specificity
    if tissue is not None:
        target = ""
        if spec.tissue_specificity and spec.tissue_specificity.high_expression:
            target = f" for {', '.join(spec.tissue_specificity.high_expression)}"
        if tissue >= 0.6:
            chunks.append(f"Tissue specificity score ({tissue:.2f}) indicates good alignment with requested expression profile{target}.")
        elif tissue < 0.3:
            chunks.append(f"Low tissue specificity ({tissue:.2f}) suggests the sequence lacks tissue-selective regulatory elements{target}.")

    # Off-target risk
    if off_target is not None:
        if off_target <= 0.2:
            chunks.append(f"Off-target risk is minimal ({off_target:.2f}), supporting sequence specificity.")
        elif off_target >= 0.5:
            chunks.append(f"Elevated off-target risk ({off_target:.2f}) warrants BLAST analysis before wet lab validation.")

    # Fallback if scores produced no useful text
    if not chunks:
        chunks.append("Scoring data is insufficient for a detailed mechanistic assessment.")

    return chunks


async def _stream_openrouter(
    prompt: str,
    candidate_id: int,
    manager: WebSocketManager,
    session_id: str,
) -> None:
    """Stream explanation chunks via OpenRouter."""
    async for text in llm.stream_text(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=512,
    ):
        await manager.send_event(
            session_id,
            ExplanationChunkEvent(
                data=ExplanationChunkData(candidate_id=candidate_id, text=text)
            ).to_json(),
        )


async def generate_explanation(
    *,
    sequence: str,
    scores: dict,
    spec: DesignSpec,
    candidate_id: int,
    manager: WebSocketManager,
    session_id: str,
) -> None:
    """Stream a mechanistic explanation for a candidate via WebSocket.

    Streams through OpenRouter when configured; otherwise emits a score-based
    summary derived from the candidate's actual scores.
    """
    prompt = _build_prompt(sequence, scores, spec)

    if llm.llm_available():
        try:
            await _stream_openrouter(prompt, candidate_id, manager, session_id)
            return
        except Exception:
            logger.warning("OpenRouter explanation failed, using score-based fallback", exc_info=True)

    logger.info("No LLM available — using score-based explanation")
    chunks = _build_score_based_fallback(scores, spec)
    for chunk in chunks:
        await manager.send_event(
            session_id,
            ExplanationChunkEvent(
                data=ExplanationChunkData(candidate_id=candidate_id, text=chunk)
            ).to_json(),
        )
