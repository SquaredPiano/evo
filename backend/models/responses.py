"""Pydantic response models - serialized to JSON at the API boundary.

These must match what the frontend expects in lib/api.ts.
"""

from pydantic import BaseModel


class DesignAcceptedResponse(BaseModel):
    session_id: str
    # Durable id for this run - the client keeps it as the parent_run_id of the
    # next reprompt so the history thread chains correctly. Present even when
    # persistence is disabled (Mongo just won't have a matching document).
    run_id: str
    status: str = "pipeline_started"
    ws_url: str


class CandidateScoresResponse(BaseModel):
    functional: float
    tissue_specificity: float
    off_target: float
    novelty: float
    combined: float | None = None


class BaseEditResponse(BaseModel):
    position: int
    reference_base: str
    new_base: str
    delta_likelihood: float
    predicted_impact: str  # "more_likely" | "neutral" | "less_likely"
    updated_scores: CandidateScoresResponse
    # Fast-path additions: let the frontend update sequence + heatmap immediately
    # without waiting on (or blocking) the slow structure refold.
    sequence: str | None = None
    per_position_scores: list[dict[str, float | int]] | None = None
    # True only when the edit changes the translated coding region - i.e. when a
    # protein refold would actually differ. Lets the client skip needless folds.
    refold_recommended: bool = False


class MutationResponse(BaseModel):
    position: int
    reference_base: str
    alternate_base: str
    delta_likelihood: float
    predicted_impact: str  # "more_likely" | "neutral" | "less_likely"


class FollowupAcceptedResponse(BaseModel):
    status: str = "partial_rerun_started"
    steps_rerunning: list[str]


class AgentToolCallResponse(BaseModel):
    tool: str
    status: str
    summary: str


class AgentCandidateUpdateResponse(BaseModel):
    candidate_id: int
    sequence: str
    scores: CandidateScoresResponse
    mutation: dict[str, object] | None = None
    per_position_scores: list[dict[str, float | int]] | None = None
    pdb_data: str | None = None
    confidence: float | None = None
    structure_model: str | None = None
    regulatory_map: dict[str, object] | None = None


class AgentChatResponse(BaseModel):
    assistant_message: str
    tool_calls: list[AgentToolCallResponse]
    candidate_update: AgentCandidateUpdateResponse | None = None
    comparison: list[dict[str, object]] | None = None
    iterations: int = 1
    reasoning_steps: list[str] | None = None
    # Plain-English, cited, honest explanation of the selected region (or None).
    region_explanation: dict[str, object] | None = None
    # Structured payloads from read-only tools (off-target scan, restriction sites).
    tool_results: list[dict[str, object]] | None = None
    # One concrete, data-grounded next action the frontend renders as a click.
    suggested_action: dict[str, object] | None = None


class StructureResponse(BaseModel):
    pdb_data: str
    model: str = "mock"
    confidence: float = 0.0


class HealthResponse(BaseModel):
    status: str
    model: str
    gpu_available: bool
    inference_mode: str


class AnalysisResponse(BaseModel):
    sequence: str
    scores: list[dict[str, float | int]]
    proteins: list[dict[str, object]]


class LiteratureHit(BaseModel):
    doc_id: str
    title: str
    abstract: str
    score: float
    pmid: str | None = None
    gene: str | None = None
    year: str = ""
    journal: str = ""
    url: str | None = None
    source: str = "pubmed"


class LiteratureSearchResponse(BaseModel):
    query: str
    backend: str            # index backend that answered: "atlas" | "memory"
    embedding_backend: str  # "api" | "local-hash"
    count: int
    hits: list[LiteratureHit]


class LiteratureIndexResponse(BaseModel):
    indexed: int
    persisted: bool         # True only when durably stored in MongoDB
    embedding_backend: str
    query: str | None = None
    total_available: int = 0


class TmResponse(BaseModel):
    """Melting-temperature result (nearest-neighbor + Wallace cross-check)."""
    sequence: str
    length: int
    gc_fraction: float
    method: str                        # headline method: "nearest-neighbor" | "wallace"
    tm_celsius: float                  # headline Tm
    tm_nn_celsius: float | None        # nearest-neighbor Tm (None if not computable)
    tm_wallace_celsius: float          # Wallace-rule Tm
    na_molar: float
    oligo_molar: float
    delta_h_kcal: float | None         # NN total enthalpy, kcal/mol
    delta_s_cal: float | None          # NN total entropy incl. salt, cal/mol/K
    note: str


class PrimerModel(BaseModel):
    """A single primer (left or right) with primer3 metrics."""
    sequence: str
    start: int
    length: int
    tm_celsius: float
    gc_percent: float
    self_any_th: float
    self_end_th: float
    hairpin_th: float


class PrimerPairModel(BaseModel):
    """A primer pair with product size and heterodimer metrics."""
    left: PrimerModel
    right: PrimerModel
    product_size: int
    product_tm: float | None
    pair_penalty: float
    compl_any_th: float
    compl_end_th: float


class PrimerDesignResponse(BaseModel):
    """primer3 primer-design result."""
    sequence_length: int
    method: str                        # "primer3"
    pairs: list[PrimerPairModel]
    count: int
    explain_left: str
    explain_right: str
    explain_pair: str
    note: str
    settings: dict[str, object]


class HairpinModel(BaseModel):
    """A hairpin loop parsed from the dot-bracket structure."""
    stem_start: int
    stem_end: int
    loop_start: int
    loop_size: int


class SecondaryStructureResponse(BaseModel):
    """ViennaRNA minimum-free-energy secondary-structure result."""
    sequence: str                      # folded sequence (RNA alphabet)
    length: int
    method: str                        # "ViennaRNA MFE (RNA.fold)"
    mfe_kcal_mol: float
    dot_bracket: str
    paired_fraction: float
    hairpins: list[HairpinModel]
    hairpin_count: int
    input_was_dna: bool
    note: str


class ProteinParamsResponse(BaseModel):
    """Protein physicochemical descriptors (ProtParam-style, deterministic)."""
    sequence: str
    length: int
    molecular_weight: float            # Da
    theoretical_pi: float
    aromaticity: float                 # fraction F+W+Y
    gravy: float                       # grand average hydropathy (Kyte-Doolittle)
    positively_charged: int            # R + K
    negatively_charged: int            # D + E
    composition: dict[str, float]      # residue -> fraction
    unknown_residues: int
    note: str
