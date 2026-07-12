"""Pydantic request models for all API endpoints."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# Full IUPAC nucleotide alphabet: the four bases, N, and the ambiguity codes
# (R,Y,S,W,K,M,B,D,H,V). Import/translation already accept IUPAC, so the API
# layer must not reject a legitimately-ambiguous imported sequence.
VALID_BASES = frozenset("ATCGNRYSWKMBDHV")

# Unambiguous single bases for point edits/substitutions (A/C/G/T/N only): an
# edit must resolve to a concrete base, not an ambiguity code.
VALID_EDIT_BASES = frozenset("ATCGN")


def _validate_sequence(seq: str) -> str:
    seq = seq.upper().strip()
    if not seq:
        raise ValueError("Sequence must not be empty")
    bad = set(seq) - VALID_BASES
    if bad:
        raise ValueError(f"Invalid nucleotides: {bad}")
    return seq


def _validate_base(base: str) -> str:
    base = base.upper().strip()
    if base not in VALID_EDIT_BASES:
        raise ValueError(f"Invalid base: {base}")
    return base


MAX_SEQUENCE_LENGTH = 100_000

class DesignRequest(BaseModel):
    goal: str
    session_id: str | None = None
    user_id: str | None = None
    # Reprompt lineage: when a user refines a goal within an existing session,
    # the client sends the prior run's id so the new run is chained to it in the
    # durable history (design_runs.parent_run_id). None for a first/fresh run.
    parent_run_id: str | None = None
    num_candidates: int = Field(10, ge=1, le=10, description="Number of candidates to generate (1-10)")
    run_profile: Literal["demo", "live"] = "live"
    truth_mode: Literal["demo_fallback", "real_only"] = "real_only"
    target_length: int | None = Field(
        None,
        ge=100,
        le=MAX_SEQUENCE_LENGTH,
        description="Target sequence length in base pairs (100–100,000). "
        "If omitted, chosen automatically based on design type and run profile.",
    )
    seed_sequence: str | None = Field(
        None,
        description="Optional starting DNA sequence to seed generation "
        "(e.g. a pasted or imported reference). If omitted, a default scaffold is used.",
    )

    @field_validator("seed_sequence")
    @classmethod
    def validate_seed_sequence(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return _validate_sequence(v)


class AnalyzeRequest(BaseModel):
    sequence: str

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)


class BaseEditRequest(BaseModel):
    session_id: str
    candidate_id: int
    position: int
    new_base: str

    @field_validator("new_base")
    @classmethod
    def validate_new_base(cls, v: str) -> str:
        return _validate_base(v)


class FollowupEditRequest(BaseModel):
    session_id: str
    message: str
    candidate_id: int | None = None


class SessionBootstrapRequest(BaseModel):
    """Bind a DNA sequence to a session without running the full design pipeline."""
    sequence: str
    session_id: str | None = None
    candidate_id: int = Field(0, ge=0)

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)


class SelectedRegion(BaseModel):
    """A half-open [start, end) selection in the candidate's own coordinate frame."""
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)


class AgentContext(BaseModel):
    """Optional UI context so the agent can explain what the user is looking at."""
    scores: dict[str, float] | None = None
    selected_position: int | None = Field(None, ge=0)
    # The user's highlighted region. When omitted but selected_position is set,
    # the agent derives a window around that position automatically.
    selected_region: SelectedRegion | None = None
    view_mode: str | None = None
    # Gene symbol for ClinVar gene-context in region explanations (optional).
    gene: str | None = None
    # Provenance links from the design pipeline (NCBI / PubMed / ClinVar).
    evidence_links: list[dict[str, str]] | None = None
    seed_source: str | None = None
    scoring_note: str | None = None
    # Full candidate pool from the editor (id, sequence, scores, overall). The
    # backend session store only persists candidate 0 + the active one, so the
    # frontend sends the rest here to let "compare candidates" rank the real set.
    candidates: list[dict[str, object]] | None = None


class AgentChatRequest(BaseModel):
    session_id: str
    candidate_id: int = 0
    message: str
    history: list[dict[str, str]] = Field(default_factory=list)
    sequence: str | None = None  # Sync session to the sequence visible in the editor
    context: AgentContext | None = None


class MutationRequest(BaseModel):
    sequence: str
    position: int
    alternate_base: str

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)

    @field_validator("alternate_base")
    @classmethod
    def validate_alt_base(cls, v: str) -> str:
        return _validate_base(v)


class StructureRequest(BaseModel):
    sequence: str
    region_start: int
    region_end: int

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)


class VariantAnnotationRequest(BaseModel):
    gene: str = Field(..., min_length=1, description="Gene symbol (e.g. BRCA1)")
    sequence: str | None = Field(None, description="Optional sequence for position validation")
    region_start: int = Field(0, ge=0)
    region_end: int | None = None
    max_variants: int = Field(25, ge=1, le=100)

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_sequence(v)
        return v


class RegionEvidenceRequest(BaseModel):
    """Assemble coordinate-bound evidence (ClinVar + regulatory + literature) for a sequence."""
    sequence: str = Field(..., description="Candidate DNA sequence; evidence coords are in its frame")
    gene: str | None = Field(None, description="Optional gene symbol for ClinVar/literature context")
    region_start: int = Field(0, ge=0)
    region_end: int | None = None
    max_variants: int = Field(25, ge=1, le=100)
    include_clinvar: bool = Field(True, description="Set False to skip the ClinVar network fetch")
    include_literature: bool = Field(True, description="Set False to skip the literature RAG lookup")
    session_id: str | None = Field(
        None,
        description="Session id for edit-history-gated literature: without it, "
        "there is no known novel region, so literature comes back empty (honest, "
        "not a fallback to generic gene-wide papers).",
    )
    candidate_id: int = Field(0, ge=0, description="Candidate whose edit history gates literature")

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)


class CalibrationRequest(BaseModel):
    gene: str = Field(..., min_length=1, description="Gene symbol (e.g. BRCA1)")
    sequence: str = Field(..., description="CDS-aligned reference sequence to score variants against")
    max_per_class: int = Field(40, ge=2, le=100, description="Max variants to fetch per class")

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)


class CodonOptimizationRequest(BaseModel):
    sequence: str = Field(..., description="Protein-coding DNA sequence to optimize")
    organism: str = Field("homo_sapiens", description="Target organism for codon usage")
    preserve_motifs: list[str] = Field(default_factory=list, description="Motif sequences to preserve")
    # Optional constraint-based fields (added; existing callers may omit them).
    gc_min: float = Field(0.30, ge=0.0, le=1.0, description="Minimum GC fraction target")
    gc_max: float = Field(0.70, ge=0.0, le=1.0, description="Maximum GC fraction target")
    avoid_sites: list[str] = Field(
        default_factory=list,
        description="Restriction-enzyme names (e.g. EcoRI) or literal DNA patterns to avoid",
    )
    max_homopolymer: int = Field(
        6, ge=1, le=20, description="Maximum single-base run length (<=1 disables the cap)"
    )

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)

    @field_validator("gc_max")
    @classmethod
    def validate_gc_window(cls, v: float, info) -> float:
        gc_min = info.data.get("gc_min", 0.0)
        if v <= gc_min:
            raise ValueError("gc_max must be greater than gc_min")
        return v


class PrimerDesignRequest(BaseModel):
    """PCR/sequencing primer design request (primer3)."""
    sequence: str = Field(..., description="Template DNA sequence to design primers against")
    product_size_min: int = Field(100, ge=40, le=10_000, description="Minimum amplicon size (bp)")
    product_size_max: int = Field(1000, ge=50, le=20_000, description="Maximum amplicon size (bp)")
    opt_tm: float = Field(60.0, ge=40.0, le=80.0, description="Optimal primer Tm (Celsius)")
    min_tm: float = Field(57.0, ge=40.0, le=80.0, description="Minimum primer Tm (Celsius)")
    max_tm: float = Field(63.0, ge=40.0, le=80.0, description="Maximum primer Tm (Celsius)")
    num_return: int = Field(5, ge=1, le=20, description="Max number of primer pairs to return")

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)


class SecondaryStructureRequest(BaseModel):
    """RNA/DNA secondary-structure (MFE) request (ViennaRNA)."""
    sequence: str = Field(..., description="RNA or DNA sequence; DNA is folded as transcribed RNA")

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        # Accept RNA (U) in addition to the DNA IUPAC alphabet: this endpoint
        # folds RNA directly and converts DNA (T) to RNA internally.
        seq = v.upper().strip()
        if not seq:
            raise ValueError("Sequence must not be empty")
        bad = set(seq) - (VALID_BASES | {"U"})
        if bad:
            raise ValueError(f"Invalid nucleotides: {bad}")
        return seq


class OffTargetRequest(BaseModel):
    sequence: str = Field(..., description="Query sequence to check for off-target hits")
    k: int = Field(12, ge=8, le=20, description="K-mer size for local similarity search")
    max_hits: int = Field(20, ge=1, le=100)

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)


_VALID_PAM_CODES = frozenset("ATCGNRYSWKMBDHV")


class CrisprOffTargetRequest(BaseModel):
    """CRISPR off-target scoring against a SUPPLIED reference sequence.

    Scores candidate off-target sites for an SpCas9 guide with CFD (Doench 2016)
    and MIT (Hsu 2013). Searches only the supplied reference (both strands); it
    is not a genome-wide scan.
    """
    guide: str = Field(..., description="20 nt SpCas9 spacer/protospacer (A/C/G/T)")
    reference: str = Field(..., description="Reference DNA to search (both strands scanned)")
    pam: str = Field("NGG", description="IUPAC PAM located 3' of the protospacer (default NGG)")
    max_mismatches: int = Field(4, ge=0, le=6, description="Max protospacer mismatches to accept")
    max_sites: int = Field(200, ge=1, le=2000, description="Max ranked sites to return")

    @field_validator("guide")
    @classmethod
    def validate_guide(cls, v: str) -> str:
        g = v.upper().strip()
        if len(g) != 20:
            raise ValueError(f"Guide must be exactly 20 nt; got {len(g)}")
        bad = set(g) - frozenset("ACGT")
        if bad:
            raise ValueError(f"Guide must be unambiguous A/C/G/T; invalid: {sorted(bad)}")
        return g

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, v: str) -> str:
        seq = "".join(v.upper().split())
        if not seq:
            raise ValueError("Reference must not be empty")
        if len(seq) > MAX_SEQUENCE_LENGTH:
            raise ValueError(f"Reference exceeds {MAX_SEQUENCE_LENGTH} nt")
        bad = set(seq) - VALID_BASES
        if bad:
            raise ValueError(f"Invalid nucleotides in reference: {sorted(bad)}")
        return seq

    @field_validator("pam")
    @classmethod
    def validate_pam(cls, v: str) -> str:
        p = v.upper().strip()
        if not (2 <= len(p) <= 8):
            raise ValueError("PAM must be 2-8 IUPAC symbols")
        bad = set(p) - _VALID_PAM_CODES
        if bad:
            raise ValueError(f"PAM has invalid IUPAC codes: {sorted(bad)}")
        return p


class ExperimentRecordRequest(BaseModel):
    session_id: str
    candidate_id: int = 0
    sequence: str
    scores: dict[str, float] = Field(default_factory=dict)
    operation: str = Field(..., min_length=1, description="Operation type: initial, edit, transform, optimize, generate")
    operation_details: dict[str, object] = Field(default_factory=dict)
    parent_version_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)


class ExperimentDiffRequest(BaseModel):
    session_id: str
    v1_id: str = Field(..., min_length=1, description="First version ID")
    v2_id: str = Field(..., min_length=1, description="Second version ID")


class ExperimentRevertRequest(BaseModel):
    session_id: str
    version_id: str = Field(..., min_length=1, description="Version to revert to")


class LiteratureArticle(BaseModel):
    """An article to index directly (bypasses the PubMed fetch)."""
    title: str = Field(..., min_length=1)
    abstract: str = ""
    pmid: str | None = None
    year: str = ""
    journal: str = ""
    authors: list[str] = Field(default_factory=list)
    url: str | None = None
    gene: str | None = None


class LiteratureIndexRequest(BaseModel):
    """Index research literature for semantic search.

    Provide ``gene`` to fetch + index PubMed articles, and/or ``articles`` to
    index supplied records directly. At least one of the two is required.
    """
    gene: str | None = Field(None, description="Gene symbol to fetch PubMed literature for")
    therapeutic_context: str | None = None
    design_type: str | None = None
    max_results: int = Field(5, ge=1, le=50, description="Max PubMed articles to fetch")
    articles: list[LiteratureArticle] = Field(default_factory=list)


class LiteratureSearchRequest(BaseModel):
    """Semantic search over indexed research literature."""
    query: str = Field(..., min_length=1, description="Natural-language query")
    k: int = Field(5, ge=1, le=50, description="Number of results to return")
    gene: str | None = Field(None, description="Optional gene filter")


class TmRequest(BaseModel):
    """Melting-temperature request for a DNA oligo/duplex."""
    sequence: str = Field(..., description="DNA sequence (A/C/G/T; N allowed but falls back to Wallace)")
    na_molar: float = Field(0.05, gt=0, le=2.0, description="Monovalent cation [Na+] in mol/L")
    oligo_molar: float = Field(
        0.25e-6, gt=0, le=1e-2, description="Total oligo strand concentration in mol/L"
    )

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)


VALID_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")


class ProteinParamsRequest(BaseModel):
    """Protein physicochemical-parameter request."""
    sequence: str = Field(..., min_length=1, description="Protein sequence (one-letter amino acids)")

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        seq = "".join(v.upper().split())
        if not seq:
            raise ValueError("Protein sequence must not be empty")
        # Strip a trailing stop codon marker if present; keep only known residues check.
        seq = seq.replace("*", "")
        if not any(a in VALID_AMINO_ACIDS for a in seq):
            raise ValueError("Sequence contains no standard amino acids")
        return seq
