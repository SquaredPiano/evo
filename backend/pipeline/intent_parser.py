"""Intent parsing — decompose a natural-language design goal into a DesignSpec.

Uses the unified OpenRouter LLM client (JSON mode). When no API key is
configured, or the call fails, falls back to a deterministic keyword heuristic
so the pipeline always produces a valid spec.
"""

from __future__ import annotations

import logging

from models.domain import DesignSpec, TissueSpec
from services import llm

logger = logging.getLogger("evo")

SYSTEM_PROMPT = """You are a genomic design assistant. Decompose a researcher's \
natural-language design goal into a structured biological specification that will \
drive a DNA sequence generation pipeline.

Return ONLY a JSON object with these fields (omit fields you cannot infer):
{
  "design_type": "regulatory_element | coding_sequence | promoter | enhancer | \
genome_fragment | terminator | ribosome_binding_site | origin_of_replication",
  "target_gene": "gene symbol, e.g. BDNF (or null)",
  "organism": "common name, e.g. human, E. coli, mouse (or null)",
  "tissue_specificity": {"high_expression": ["tissue", ...], "low_expression": [...]},
  "therapeutic_context": "short phrase, e.g. Alzheimer's (or null)",
  "constraints": ["novel_sequence", "no_known_pathogenic_variants", "high_gc_content", \
"codon_optimized", ...]
}

Only populate fields clearly mentioned or strongly implied. Do not invent values."""


async def parse_intent(goal: str) -> DesignSpec:
    """Decompose a natural-language design goal into a structured DesignSpec."""
    if not llm.llm_available():
        return _heuristic_intent(goal)

    try:
        parsed = await llm.complete_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": goal},
            ],
            temperature=0.1,
        )
        if parsed:
            return _coerce_spec(parsed, goal)
    except Exception:
        logger.warning("LLM intent parsing failed, using heuristic", exc_info=True)

    return _heuristic_intent(goal)


def _coerce_spec(parsed: dict, goal: str) -> DesignSpec:
    """Validate LLM JSON into a DesignSpec, filling gaps from the heuristic."""
    fallback = _heuristic_intent(goal)
    tissue = parsed.get("tissue_specificity")
    tissue_spec: TissueSpec | None = None
    if isinstance(tissue, dict):
        high = [str(t) for t in tissue.get("high_expression", []) if t]
        low = [str(t) for t in tissue.get("low_expression", []) if t]
        if high or low:
            tissue_spec = TissueSpec(high_expression=high, low_expression=low)

    constraints = parsed.get("constraints")
    if not isinstance(constraints, list):
        constraints = fallback.constraints

    return DesignSpec(
        design_type=str(parsed.get("design_type") or fallback.design_type),
        target_gene=parsed.get("target_gene") or fallback.target_gene,
        organism=parsed.get("organism") or fallback.organism,
        tissue_specificity=tissue_spec or fallback.tissue_specificity,
        therapeutic_context=parsed.get("therapeutic_context") or fallback.therapeutic_context,
        constraints=[str(c) for c in constraints],
    )


# Common gene symbols that appear in mixed-case prose (not ALLCAPS).
_KNOWN_GENES = {
    "brca1", "brca2", "brca", "bdnf", "tp53", "egfr", "kras", "myc", "pcsk9",
    "cftr", "htt", "app", "snca", "lrk2", "park2", "ins", "glucagon",
    "insulin", "p53", "her2", "alk", "braf", "pten", "rb1", "apc",
}


def _heuristic_intent(goal: str) -> DesignSpec:
    goal_lower = goal.lower()
    design_type = "regulatory_element"
    if "promoter" in goal_lower:
        design_type = "promoter"
    elif "enhancer" in goal_lower:
        design_type = "enhancer"
    elif any(
        token in goal_lower
        for token in (
            "coding",
            "cds",
            "orf",
            "protein",
            "peptide",
            "tumor suppressor",
            "tumour suppressor",
            "tumor-suppressor",
            "tumour-suppressor",
            "enzyme",
            "kinase",
            "receptor",
        )
    ):
        design_type = "coding_sequence"
    elif any(g in goal_lower for g in ("brca1", "brca2", "brca", "tp53", "p53", "rb1", "pten")):
        # Named tumor-suppressor genes without "promoter/enhancer" → coding fragment.
        design_type = "coding_sequence"

    constraints: list[str] = []
    if "novel" in goal_lower:
        constraints.append("novel_sequence")
    if "pathogenic" in goal_lower:
        constraints.append("no_known_pathogenic_variants")
    if design_type == "coding_sequence":
        constraints.append("prefer_ncbi_cds_seed")

    return DesignSpec(
        design_type=design_type,
        target_gene=_extract_target_gene(goal),
        organism=_extract_organism(goal_lower),
        tissue_specificity=_extract_tissue(goal_lower),
        constraints=constraints,
    )


def _extract_target_gene(goal: str) -> str | None:
    goal_lower = goal.lower()
    for known in _KNOWN_GENES:
        if known in goal_lower:
            if known == "insulin":
                return "INS"
            if known == "p53":
                return "TP53"
            if known == "her2":
                return "ERBB2"
            if known == "brca":
                return "BRCA1"
            return known.upper()

    tokens = goal.replace(",", " ").replace(".", " ").replace("-", " ").split()
    for token in tokens:
        cleaned = token.strip()
        if cleaned.isalpha() and 2 <= len(cleaned) <= 8 and cleaned.upper() == cleaned:
            return cleaned
    return None


def _extract_organism(goal_lower: str) -> str | None:
    if "human" in goal_lower or "homo sapiens" in goal_lower:
        return "human"
    if "mouse" in goal_lower or "mus musculus" in goal_lower:
        return "mouse"
    if "e. coli" in goal_lower or "escherichia" in goal_lower:
        return "Escherichia coli"
    # Default organism for well-known human disease genes so NCBI prefers human CDS.
    if any(g in goal_lower for g in ("brca", "tp53", "p53", "bdnf", "cftr", "htt")):
        return "human"
    return None


def _extract_tissue(goal_lower: str) -> TissueSpec | None:
    high: list[str] = []
    if "hippocamp" in goal_lower:
        high.append("hippocampal_neurons")
    elif "neuron" in goal_lower or "brain" in goal_lower:
        high.append("neurons")
    elif "heart" in goal_lower or "cardiac" in goal_lower:
        high.append("cardiac_tissue")
    if not high:
        return None
    return TissueSpec(high_expression=high)
