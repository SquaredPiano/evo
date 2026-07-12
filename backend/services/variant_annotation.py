"""Variant annotation service - overlays ClinVar/pathogenicity data on sequences.

Parses ClinVar variant titles (HGVS nomenclature) to extract positions,
maps them onto a user's sequence region, and returns position-level
annotations suitable for rendering on the sequence viewer.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

from services.alignment import lift_position
from services.clinvar import ClinVarVariant, lookup_variants
from services.eutils import (
    EUTILS_BASE,
    eutils_client,
    eutils_params,
    get_with_retry,
    safe_json_response,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VariantAnnotation:
    """A single variant with an explicit coordinate frame.

    IMPORTANT: a ClinVar ``c.``/``g.`` HGVS coordinate is an offset into a
    *reference* transcript/chromosome, NOT into a user's de-novo candidate. This
    record keeps the two frames separate so a reference coordinate is never
    silently painted as a candidate base position:

    - ``reference_position``: the 1-based HGVS/transcript coordinate the variant
      is actually defined on (``None`` when it could not be parsed).
    - ``coordinate_frame``: ``"candidate"`` only when ``position`` was *lifted*
      onto the candidate via alignment (``annotate_variants(reference_sequence=...)``);
      otherwise ``"reference"`` - meaning ``position`` is the reference/transcript
      0-based index and is only a valid index into the query when that query is
      itself the reference (e.g. a CDS-aligned sequence, as in calibration).

    ``position`` stays a non-optional int (0-based) so existing scoring callers
    keep working; consumers that place variants on a candidate MUST check
    ``coordinate_frame`` first (see services.region_evidence).
    """
    position: int  # 0-based index in the frame named by ``coordinate_frame``
    ref_base: str
    alt_base: str
    clinical_significance: str  # pathogenic, likely_pathogenic, benign, uncertain, etc.
    condition: str
    variant_id: str  # ClinVar UID
    variant_title: str
    variation_type: str  # single nucleotide variant, deletion, etc.
    review_stars: int  # 0-4 ClinVar review status stars
    allele_frequency: float | None  # population allele frequency if available
    reference_position: int | None = None  # 1-based HGVS/transcript coordinate
    coordinate_frame: str = "reference"    # "candidate" (lifted) | "reference"


@dataclass
class AnnotationResult:
    """Result of annotating a sequence region."""
    gene: str
    total_variants_in_gene: int
    annotations: list[VariantAnnotation] = field(default_factory=list)
    unmapped_variants: int = 0  # variants found but couldn't be mapped to positions


# ---------------------------------------------------------------------------
# HGVS parsing
# ---------------------------------------------------------------------------

# Matches patterns like:
#   c.5123C>A          coding DNA
#   c.68_69delAG       coding DNA deletion
#   c.5266dupC         coding DNA duplication
#   g.43094064G>A      genomic
_HGVS_SNV_RE = re.compile(
    r"[cg]\.(\d+)([ACGT])>([ACGT])",
    re.IGNORECASE,
)

_HGVS_POSITION_RE = re.compile(
    r"[cg]\.(\d+)",
)


def parse_hgvs_position(title: str) -> tuple[int | None, str | None, str | None]:
    """Extract position and base change from an HGVS title.

    Returns (coding_position_1based, ref_base, alt_base).
    Position is 1-based as per HGVS convention.
    Returns (None, None, None) if parsing fails.
    """
    # Try full SNV first
    m = _HGVS_SNV_RE.search(title)
    if m:
        return int(m.group(1)), m.group(2).upper(), m.group(3).upper()

    # Fall back to position only
    m = _HGVS_POSITION_RE.search(title)
    if m:
        return int(m.group(1)), None, None

    return None, None, None


# ---------------------------------------------------------------------------
# Detailed variant fetch (with review status + location data)
# ---------------------------------------------------------------------------

async def _fetch_variant_details(
    variant_ids: list[str],
) -> dict[str, dict]:
    """Fetch detailed variant info from ClinVar VCV API via efetch.

    Returns a dict mapping UID to extra fields (review_stars, location, etc.)
    """
    if not variant_ids:
        return {}

    details: dict[str, dict] = {}
    try:
        async with eutils_client(timeout=20.0) as client:
            summary_resp = await get_with_retry(
                client,
                f"{EUTILS_BASE}/esummary.fcgi",
                params=eutils_params({
                    "db": "clinvar",
                    "id": ",".join(variant_ids),
                    "retmode": "json",
                }),
            )
            data = safe_json_response(summary_resp, source="ClinVar")
            result_map = data.get("result", {})

            for uid in variant_ids:
                entry = result_map.get(uid, {})
                if not entry or uid == "uids":
                    continue

                # Review status → star rating
                review_status = ""
                clin_sig = entry.get("clinical_significance", {})
                if isinstance(clin_sig, dict):
                    review_status = clin_sig.get("review_status", "")
                stars = _review_status_to_stars(review_status)

                # Try to extract genomic location
                variation_set = entry.get("variation_set", [])
                chrom_start = None
                chrom_stop = None
                if variation_set and isinstance(variation_set, list):
                    vs = variation_set[0] if variation_set else {}
                    if isinstance(vs, dict):
                        for loc in vs.get("variation_loc", []):
                            if isinstance(loc, dict) and loc.get("assembly_name", "").startswith("GRCh"):
                                chrom_start = loc.get("start")
                                chrom_stop = loc.get("stop")
                                break

                details[uid] = {
                    "review_stars": stars,
                    "chrom_start": chrom_start,
                    "chrom_stop": chrom_stop,
                }
    except Exception:
        logger.warning("Failed to fetch variant details", exc_info=True)

    return details


def _review_status_to_stars(review_status: str) -> int:
    """Map ClinVar review status string to 0-4 star rating."""
    status = review_status.lower()
    if "practice guideline" in status:
        return 4
    if "expert panel" in status:
        return 3
    if "criteria provided, multiple submitters" in status:
        return 2
    if "criteria provided, single submitter" in status:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def annotate_variants(
    gene: str,
    sequence: str | None = None,
    max_variants: int = 25,
    significance: str = "pathogenic",
    reference_sequence: str | None = None,
) -> AnnotationResult:
    """Fetch ClinVar variants for a gene and resolve their coordinate frame.

    HGVS ``c.``/``g.`` coordinates index a reference transcript/chromosome, not a
    de-novo candidate, so they are NOT dropped onto the candidate index blindly:

    - When ``reference_sequence`` is provided, the candidate ``sequence`` is
      aligned to it (services.alignment) and each reference coordinate is
      *lifted* into the candidate frame. Only variants that land inside an
      aligned block get a candidate-frame ``position`` (``coordinate_frame ==
      "candidate"``); ones that fall in an indel/gap are counted as unmapped.
    - Without a reference, each variant keeps its reference coordinate
      (``reference_position``) with ``coordinate_frame == "reference"``. Its
      ``position`` is the 0-based reference index - a valid query index only when
      the caller's sequence is itself the reference frame (e.g. calibration's
      CDS-aligned sequence). It must NOT be painted as a candidate base; that
      gating lives in services.region_evidence.

    Args:
        gene: Gene symbol (e.g. "BRCA1")
        sequence: Optional DNA sequence (the candidate, or a reference-aligned
            sequence for calibration).
        max_variants: Maximum number of variants to fetch.
        significance: ClinVar significance filter.
        reference_sequence: Optional gene reference sequence to align the
            candidate against and lift reference coordinates through.

    Returns:
        AnnotationResult with coordinate-frame-tagged variant annotations.
    """
    if not gene:
        return AnnotationResult(gene="", total_variants_in_gene=0)

    # Fetch variants from ClinVar
    clinvar_result = await lookup_variants(
        gene, max_results=max_variants, significance=significance
    )

    if not clinvar_result.variants:
        return AnnotationResult(
            gene=gene,
            total_variants_in_gene=clinvar_result.total_count,
        )

    # Fetch additional details (review stars, locations)
    variant_ids = [v.uid for v in clinvar_result.variants]
    details = await _fetch_variant_details(variant_ids)

    annotations: list[VariantAnnotation] = []
    unmapped = 0

    seq_len = len(sequence) if sequence else 0

    for variant in clinvar_result.variants:
        position_1based, ref_base, alt_base = parse_hgvs_position(variant.title)
        detail = details.get(variant.uid, {})
        stars = detail.get("review_stars", 0)

        if position_1based is not None:
            # The HGVS coordinate is a REFERENCE coordinate. 0-based reference
            # index; frame defaults to "reference" (see VariantAnnotation).
            reference_position = position_1based
            pos_0 = position_1based - 1
            frame = "reference"

            if reference_sequence and sequence:
                # Approach (a): lift the reference coordinate into the candidate
                # frame by aligning candidate <-> reference. CONCORDANCE GUARD:
                # the HGVS reference base must match the reference sequence at
                # that coordinate, else we are in the wrong frame (a CDS-relative
                # c. offset against a genomic reference, or RefSeq version drift)
                # and must NOT paint a candidate-frame position. A global
                # alignment lifts almost any in-range index, so without this
                # check the lift "succeeds" onto a biologically wrong base.
                if (
                    not ref_base
                    or pos_0 < 0
                    or pos_0 >= len(reference_sequence)
                    or reference_sequence[pos_0].upper() != ref_base.upper()
                ):
                    unmapped += 1
                    continue
                lifted = lift_position(reference_sequence, sequence, pos_0)
                if lifted is None or not (0 <= lifted < len(sequence)):
                    unmapped += 1
                    continue
                pos_0 = lifted
                frame = "candidate"
            elif sequence and (pos_0 < 0 or pos_0 >= seq_len):
                # No reference to lift against. The reference index still has to
                # fall within the provided (reference-frame) sequence to be
                # usable; otherwise it is genuinely unmapped.
                unmapped += 1
                continue

            annotations.append(VariantAnnotation(
                position=pos_0,
                ref_base=ref_base or "",
                alt_base=alt_base or "",
                clinical_significance=variant.clinical_significance,
                condition=variant.condition,
                variant_id=variant.uid,
                variant_title=variant.title,
                variation_type=variant.variation_type,
                review_stars=stars,
                allele_frequency=None,  # ClinVar esummary doesn't provide AF
                reference_position=reference_position,
                coordinate_frame=frame,
            ))
        else:
            unmapped += 1

    # Sort by position for sequential rendering
    annotations.sort(key=lambda a: a.position)

    return AnnotationResult(
        gene=gene,
        total_variants_in_gene=clinvar_result.total_count,
        annotations=annotations,
        unmapped_variants=unmapped,
    )


async def annotate_sequence_region(
    gene: str,
    sequence: str,
    region_start: int = 0,
    region_end: int | None = None,
    max_variants: int = 25,
    reference_sequence: str | None = None,
) -> AnnotationResult:
    """Annotate a specific region of a sequence with variants.

    Filters annotations to only include those within [region_start, region_end).
    Adjusts positions to be relative to region_start. The coordinate frame of
    each annotation is preserved (see :class:`VariantAnnotation`).
    """
    if region_end is None:
        region_end = len(sequence)

    if region_start < 0 or region_end > len(sequence) or region_start >= region_end:
        raise ValueError(
            f"Invalid region [{region_start}, {region_end}) for sequence of length {len(sequence)}"
        )

    result = await annotate_variants(
        gene, sequence, max_variants=max_variants, reference_sequence=reference_sequence
    )

    # Filter to region and adjust positions
    region_annotations = []
    for ann in result.annotations:
        if region_start <= ann.position < region_end:
            region_annotations.append(VariantAnnotation(
                position=ann.position - region_start,
                ref_base=ann.ref_base,
                alt_base=ann.alt_base,
                clinical_significance=ann.clinical_significance,
                condition=ann.condition,
                variant_id=ann.variant_id,
                variant_title=ann.variant_title,
                variation_type=ann.variation_type,
                review_stars=ann.review_stars,
                allele_frequency=ann.allele_frequency,
                reference_position=ann.reference_position,
                coordinate_frame=ann.coordinate_frame,
            ))

    return AnnotationResult(
        gene=gene,
        total_variants_in_gene=result.total_variants_in_gene,
        annotations=region_annotations,
        unmapped_variants=result.unmapped_variants,
    )
