"""Pydantic request models for all API endpoints."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


VALID_BASES = frozenset("ATCGN")


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
    if base not in VALID_BASES:
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
    num_candidates: int = Field(4, ge=1, le=10, description="Number of candidates to generate (1–10)")
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


class AgentContext(BaseModel):
    """Optional UI context so the agent can explain what the user is looking at."""
    scores: dict[str, float] | None = None
    selected_position: int | None = Field(None, ge=0)
    view_mode: str | None = None
    # Provenance links from the design pipeline (NCBI / PubMed / ClinVar).
    evidence_links: list[dict[str, str]] | None = None
    seed_source: str | None = None
    scoring_note: str | None = None


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
    """Assemble coordinate-bound evidence (ClinVar + regulatory) for a sequence."""
    sequence: str = Field(..., description="Candidate DNA sequence; evidence coords are in its frame")
    gene: str | None = Field(None, description="Optional gene symbol for ClinVar context")
    region_start: int = Field(0, ge=0)
    region_end: int | None = None
    max_variants: int = Field(25, ge=1, le=100)
    include_clinvar: bool = Field(True, description="Set False to skip the ClinVar network fetch")

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

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)


class OffTargetRequest(BaseModel):
    sequence: str = Field(..., description="Query sequence to check for off-target hits")
    k: int = Field(12, ge=8, le=20, description="K-mer size for local similarity search")
    max_hits: int = Field(20, ge=1, le=100)

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: str) -> str:
        return _validate_sequence(v)


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
