"""Pydantic response models — serialized to JSON at the API boundary.

These must match what the frontend expects in lib/api.ts.
"""

from pydantic import BaseModel


class DesignAcceptedResponse(BaseModel):
    session_id: str
    # Durable id for this run — the client keeps it as the parent_run_id of the
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
    predicted_impact: str  # "benign" | "moderate" | "deleterious"
    updated_scores: CandidateScoresResponse
    # Fast-path additions: let the frontend update sequence + heatmap immediately
    # without waiting on (or blocking) the slow structure refold.
    sequence: str | None = None
    per_position_scores: list[dict[str, float | int]] | None = None
    # True only when the edit changes the translated coding region — i.e. when a
    # protein refold would actually differ. Lets the client skip needless folds.
    refold_recommended: bool = False


class MutationResponse(BaseModel):
    position: int
    reference_base: str
    alternate_base: str
    delta_likelihood: float
    predicted_impact: str


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
