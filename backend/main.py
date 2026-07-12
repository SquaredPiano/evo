"""FastAPI entrypoint for the Proteus backend - genomic design IDE."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator as _AsyncIterator
from contextlib import asynccontextmanager as _acm
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from models.requests import (
    AnalyzeRequest,
    AgentChatRequest,
    BaseEditRequest,
    CalibrationRequest,
    CodonOptimizationRequest,
    DesignRequest,
    ExperimentDiffRequest,
    ExperimentRecordRequest,
    ExperimentRevertRequest,
    FollowupEditRequest,
    LiteratureIndexRequest,
    LiteratureSearchRequest,
    MutationRequest,
    OffTargetRequest,
    ProteinParamsRequest,
    RegionEvidenceRequest,
    SessionBootstrapRequest,
    StructureRequest,
    TmRequest,
    VariantAnnotationRequest,
)
from models.responses import (
    AnalysisResponse,
    AgentCandidateUpdateResponse,
    AgentChatResponse,
    AgentToolCallResponse,
    BaseEditResponse,
    CandidateScoresResponse,
    DesignAcceptedResponse,
    FollowupAcceptedResponse,
    HealthResponse,
    LiteratureIndexResponse,
    LiteratureSearchResponse,
    LiteratureHit,
    MutationResponse,
    ProteinParamsResponse,
    StructureResponse,
    TmResponse,
)
from models.sessions import SessionSnapshot
from config import SessionStoreMode, StructureMode, settings
from pipeline.evo2_score import rescore_mutation_detailed, score_candidate
from pipeline.orchestrator import (
    DEFAULT_SEED,
    create_session_id,
    run_followup_pipeline,
    run_generation_pipeline,
)
from services.evo2 import create_evo2_service
from services.regulatory_viz import build_regulatory_map
from services.agentic_copilot import AgenticCopilot
from services.session_store import (
    CandidateNotFoundError,
    SessionLockTimeoutError,
    SessionNotFoundError,
    create_session_store,
)
from services.structure import coding_region_changed, predict_structure
from services.translation import find_orfs
from services.experiment_tracker import (
    ExperimentTracker,
    ExperimentVersionNotFoundError,
    novel_regions_from_versions,
)
from services.mongo_store import create_mongo_store
from services.embeddings import create_embedder
from services.literature_index import LiteratureIndex, LiteratureRagProvider
from ws.manager import WebSocketManager
from ws.events import (
    CandidateStatusData,
    CandidateStatusEvent,
    RegulatoryMapReadyData,
    RegulatoryMapReadyEvent,
    StructureReadyData,
    StructureReadyEvent,
)

logger = logging.getLogger("evo")


@_acm
async def _session_errors_to_http(candidate_id: int = 0) -> _AsyncIterator[None]:
    """Convert session store exceptions to HTTP error responses."""
    try:
        yield
    except SessionLockTimeoutError as exc:
        raise HTTPException(status_code=423, detail="candidate is busy; retry shortly") from exc
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate {exc.candidate_id} not found") from exc


@_acm
async def _lifespan(app: FastAPI) -> _AsyncIterator[None]:
    """Modern lifespan handler - replaces deprecated @app.on_event."""
    # Startup
    if settings.session_store_mode == SessionStoreMode.REDIS:
        redis_ok = await session_store.ping()
        if not redis_ok:
            raise RuntimeError("Redis session store is enabled but unreachable.")
    # Durable persistence is optional - a failure here is logged and the app
    # continues Redis-only (see MongoStore.connect). Never fatal.
    await mongo_store.connect()
    # Fire-and-forget: pre-warm the literature index for known demo genes so a
    # live demo doesn't pay first-query PubMed+embedding latency. Scheduled
    # here (inside the lifespan, where a loop is guaranteed to be running)
    # rather than at bare module level, which would raise "no running event
    # loop" at import time (e.g. under pytest). Must not block startup -
    # ensure_indexed's own failures are already non-raising, so nothing here
    # can delay or fail the `yield` below.
    asyncio.create_task(_prewarm_literature_index())
    yield
    # Shutdown
    await session_store.close()
    await mongo_store.close()

app = FastAPI(title="Proteus Backend", version="1.0.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ws_manager = WebSocketManager()
evo2_service = create_evo2_service()
session_store = create_session_store(settings, DEFAULT_SEED)
copilot = AgenticCopilot(session_store=session_store, evo2_service=evo2_service)
# Durable store (MongoDB Atlas). Optional: stays disabled until connect() succeeds
# in the lifespan handler, so importing/instantiating here is always safe.
mongo_store = create_mongo_store(settings)
experiment_tracker = ExperimentTracker(session_store, mongo_store=mongo_store)
# Semantic vector search over research literature. The embedder is chosen by the
# hybrid policy (real API when a key is set, deterministic local otherwise); the
# index uses Atlas $vectorSearch when available and falls back to in-memory.
embedder = create_embedder(settings)
literature_index = LiteratureIndex(embedder=embedder, mongo_store=mongo_store)
# Adapts literature_index to the region_evidence RAG seam (RegionRagProvider) -
# feeds semantically-retrieved papers into /api/region-evidence alongside
# ClinVar + regulatory evidence.
literature_rag_provider = LiteratureRagProvider(literature_index)

# Demo genes to pre-warm the literature index for at startup (see _lifespan).
# On-demand ensure_indexed() already covers any gene a user actually queries -
# this list only exists to avoid paying first-query ingestion latency live
# during a demo. NOTE: confirm/adjust this list with the team before
# presenting; it's a placeholder default, not a confirmed demo lineup.
_LITERATURE_PREWARM_GENES = ["BRCA1", "TP53", "CFTR"]


async def _prewarm_literature_index() -> None:
    for gene in _LITERATURE_PREWARM_GENES:
        try:
            await literature_index.ensure_indexed(gene)
        except Exception:
            logger.warning("Literature pre-warm failed for gene=%s", gene, exc_info=True)


SESSION_CONTEXT: dict[str, dict[str, Any]] = {}
MAX_SESSION_CONTEXT_ENTRIES = 512



@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze(request: AnalyzeRequest) -> AnalysisResponse:
    sequence = request.sequence
    scores, per_position = await score_candidate(evo2_service, sequence)
    orfs = find_orfs(sequence, min_length=24)[:3]
    proteins: list[dict[str, object]] = []

    for idx, orf in enumerate(orfs):
        pdb_data: str | None = None
        confidence = 0.0
        # Fold the first ORF with ESMFold (or mock fallback) so Structure view is real.
        if idx == 0:
            try:
                pdb_data, confidence, model = await _predict_structure_snapshot(
                    sequence=sequence[orf.start : orf.end],
                    candidate_id=0,
                )
                if model == "unavailable" or not pdb_data:
                    pdb_data, confidence = None, 0.0
            except Exception:
                logger.warning("Structure fold during analyze failed", exc_info=True)
                pdb_data, confidence = None, 0.0
        proteins.append(
            {
                "region_start": orf.start,
                "region_end": orf.end,
                "pdb_data": pdb_data,
                "sequence_identity": float(confidence or 0.0),
                "model": "esmfold" if pdb_data else None,
            }
        )

    return AnalysisResponse(
        sequence=sequence,
        scores=[{"position": x.position, "score": x.score} for x in per_position],
        proteins=proteins,
    )


@app.post("/api/design", response_model=DesignAcceptedResponse, status_code=202)
async def design(request: DesignRequest, http_request: Request) -> DesignAcceptedResponse:
    session_id = request.session_id or create_session_id()
    run_id = uuid.uuid4().hex
    num_candidates = request.num_candidates
    # Agent memory should only live within the active chat lifecycle for this run.
    await copilot.clear_session_memory(session_id=session_id)
    await session_store.initialize_session(session_id, user_id=request.user_id)
    _set_session_context(
        session_id,
        {
            "run_profile": request.run_profile,
            "truth_mode": request.truth_mode,
            "design_type": "regulatory_element",
        },
    )

    # Durable record of the prompt + config at submit time. Best-effort: when
    # persistence is disabled this is a fast no-op and the run still proceeds.
    await mongo_store.save_design_run(
        run_id=run_id,
        session_id=session_id,
        goal=request.goal,
        user_id=request.user_id,
        parent_run_id=request.parent_run_id,
        run_profile=request.run_profile,
        truth_mode=request.truth_mode,
        num_candidates=num_candidates,
        target_length=request.target_length,
        seed_sequence=request.seed_sequence or DEFAULT_SEED,
    )

    asyncio.create_task(
        run_generation_pipeline(
            manager=ws_manager,
            service=evo2_service,
            session_id=session_id,
            goal=request.goal,
            n_candidates=num_candidates,
            run_profile=request.run_profile,
            truth_mode=request.truth_mode,
            seed_sequence=request.seed_sequence or DEFAULT_SEED,
            target_length=request.target_length,
            on_candidate_ready=lambda candidate_id, sequence: _persist_candidate_sequence(
                session_id, candidate_id, sequence
            ),
            on_spec_ready=lambda spec: _set_session_design_type(session_id, spec.design_type),
            on_pipeline_complete=lambda candidates, completed, failed: _persist_run_completion(
                run_id, session_id, candidates, completed, failed
            ),
            literature_index=literature_index,
        )
    )
    return DesignAcceptedResponse(
        session_id=session_id,
        run_id=run_id,
        ws_url=_build_ws_url(http_request, session_id),
    )


@app.post("/api/edit/base", response_model=BaseEditResponse)
async def edit_base(request: BaseEditRequest) -> BaseEditResponse:
    async with _session_errors_to_http(request.candidate_id):
        async with session_store.candidate_guard(request.session_id, request.candidate_id):
            sequence = await session_store.require_candidate_sequence(request.session_id, request.candidate_id)
            if request.position < 0 or request.position >= len(sequence):
                raise HTTPException(status_code=422, detail="position out of range")

            # Single rescore pass yields scores, delta, ref base, impact AND a
            # per-position patch - no duplicate score_mutation call needed.
            rescore = await rescore_mutation_detailed(
                evo2_service,
                sequence=sequence,
                position=request.position,
                new_base=request.new_base,
            )
            updated_scores = rescore.scores
            delta = rescore.delta_likelihood
            mutated_sequence = rescore.mutated_sequence
            # Only worth refolding if the edit actually changes the translated protein.
            refold_recommended = coding_region_changed(sequence, mutated_sequence)
            await session_store.set_candidate_sequence(request.session_id, request.candidate_id, mutated_sequence)

    # Auto-record experiment version for base edits
    try:
        await experiment_tracker.record_version(
            session_id=request.session_id,
            candidate_id=request.candidate_id,
            sequence=mutated_sequence,
            scores={
                "functional": updated_scores.functional,
                "tissue_specificity": updated_scores.tissue_specificity,
                "off_target": updated_scores.off_target,
                "novelty": updated_scores.novelty,
                "combined": updated_scores.combined or 0.0,
            },
            operation="edit",
            operation_details={
                "position": request.position,
                "ref_base": rescore.reference_base,
                "new_base": request.new_base,
                "delta_likelihood": delta,
            },
        )
    except Exception:
        logger.warning("Failed to record experiment version for base edit", exc_info=True)

    return BaseEditResponse(
        position=request.position,
        reference_base=rescore.reference_base,
        new_base=request.new_base,
        delta_likelihood=delta,
        predicted_impact=rescore.predicted_impact.value,
        updated_scores=CandidateScoresResponse(
            functional=updated_scores.functional,
            tissue_specificity=updated_scores.tissue_specificity,
            off_target=updated_scores.off_target,
            novelty=updated_scores.novelty,
            combined=updated_scores.combined,
        ),
        sequence=mutated_sequence,
        per_position_scores=[
            {"position": p.position, "score": p.score}
            for p in rescore.per_position_patch
        ],
        refold_recommended=refold_recommended,
    )


@app.post("/api/edit/followup", response_model=FollowupAcceptedResponse, status_code=202)
async def edit_followup(request: FollowupEditRequest) -> FollowupAcceptedResponse:
    steps = ["intent_parse", "constraint_refine", "evo2_scoring", "structure", "explanation"]
    candidate_id = request.candidate_id or 0
    async with _session_errors_to_http(candidate_id):
        async with session_store.candidate_guard(request.session_id, candidate_id):
            base_sequence = await session_store.require_candidate_sequence(request.session_id, candidate_id)

    context = SESSION_CONTEXT.get(request.session_id, {})
    asyncio.create_task(
        run_followup_pipeline(
            manager=ws_manager,
            service=evo2_service,
            session_id=request.session_id,
            message=request.message,
            candidate_id=candidate_id,
            base_sequence=base_sequence,
            run_profile=str(context.get("run_profile", "live")),
            truth_mode=str(context.get("truth_mode", "real_only")),
            design_type_hint=str(context.get("design_type", "regulatory_element")),
            on_candidate_ready=lambda updated_candidate_id, sequence: _persist_candidate_sequence(
                request.session_id, updated_candidate_id, sequence
            ),
            on_spec_ready=lambda spec: _set_session_design_type(request.session_id, spec.design_type),
        )
    )
    return FollowupAcceptedResponse(steps_rerunning=steps)


@app.post("/api/session/bootstrap")
async def bootstrap_session(request: SessionBootstrapRequest) -> dict[str, object]:
    """Bind a sequence to a session for agent chat / edits - no pipeline run."""
    session_id = request.session_id or str(uuid.uuid4())
    await session_store.set_candidate_sequence(session_id, request.candidate_id, request.sequence)
    return {
        "session_id": session_id,
        "candidate_id": request.candidate_id,
        "length": len(request.sequence),
    }


@app.post("/api/agent/chat", response_model=AgentChatResponse)
async def agent_chat(request: AgentChatRequest) -> AgentChatResponse:
    session_id = request.session_id

    # Keep the backend sequence aligned with what the user sees in the editor.
    if request.sequence:
        try:
            stored = await session_store.require_candidate_sequence(session_id, request.candidate_id)
            if stored != request.sequence:
                await session_store.set_candidate_sequence(session_id, request.candidate_id, request.sequence)
        except (SessionNotFoundError, CandidateNotFoundError):
            await session_store.set_candidate_sequence(session_id, request.candidate_id, request.sequence)
    else:
        try:
            await session_store.require_candidate_sequence(session_id, request.candidate_id)
        except (SessionNotFoundError, CandidateNotFoundError):
            raise HTTPException(
                status_code=404,
                detail="session not found - include 'sequence' to bootstrap",
            ) from None

    ctx = request.context.model_dump(exclude_none=True) if request.context else None

    async with _session_errors_to_http(request.candidate_id):
        async with session_store.candidate_guard(session_id, request.candidate_id):
            result = await copilot.chat(
                session_id=session_id,
                candidate_id=request.candidate_id,
                message=request.message,
                history=request.history,
                ui_context=ctx,
            )

    candidate_update = None
    if result.candidate_update is not None:
        update = result.candidate_update
        design_type = str(SESSION_CONTEXT.get(request.session_id, {}).get("design_type", "regulatory_element"))
        pdb_data = update.pdb_data
        confidence = update.confidence
        structure_model = update.structure_model
        regulatory_map = update.regulatory_map
        if pdb_data is None:
            try:
                pdb_data, confidence, structure_model = await _predict_structure_snapshot(
                    sequence=update.sequence,
                    candidate_id=update.candidate_id,
                )
                # Honest null: when ESMFold cannot fold the region there is no
                # structure. Do not persist an empty string as if it were a fold.
                if not pdb_data or structure_model == "unavailable":
                    pdb_data, confidence, structure_model = None, None, None
                update.pdb_data = pdb_data
                update.confidence = confidence
                update.structure_model = structure_model
                if pdb_data is not None:
                    await ws_manager.send_event(
                        request.session_id,
                        StructureReadyEvent(
                            data=StructureReadyData(
                                candidate_id=update.candidate_id,
                                pdb_data=pdb_data,
                                confidence=confidence,
                            )
                        ).to_json(),
                    )
                    await ws_manager.send_event(
                        request.session_id,
                        CandidateStatusEvent(
                            data=CandidateStatusData(candidate_id=update.candidate_id, status="structured")
                        ).to_json(),
                    )
            except Exception:
                logger.warning("Structure prediction failed for candidate %s", update.candidate_id, exc_info=True)
        if not _design_uses_protein_structure(design_type) and regulatory_map is None:
            try:
                regulatory_map = build_regulatory_map(update.sequence)
                update.regulatory_map = regulatory_map
                await ws_manager.send_event(
                    request.session_id,
                    RegulatoryMapReadyEvent(
                        data=RegulatoryMapReadyData(
                            candidate_id=update.candidate_id,
                            regulatory_map=regulatory_map,
                        )
                    ).to_json(),
                )
                await ws_manager.send_event(
                    request.session_id,
                    CandidateStatusEvent(
                        data=CandidateStatusData(candidate_id=update.candidate_id, status="structured")
                    ).to_json(),
                )
            except Exception:
                logger.warning("Regulatory map failed for candidate %s", update.candidate_id, exc_info=True)
        candidate_update = AgentCandidateUpdateResponse(
            candidate_id=update.candidate_id,
            sequence=update.sequence,
            scores=CandidateScoresResponse(**update.scores),
            mutation=update.mutation,
            per_position_scores=update.per_position_scores,
            pdb_data=update.pdb_data,
            confidence=update.confidence,
            structure_model=update.structure_model,
            regulatory_map=update.regulatory_map,
        )

        # Auto-record experiment version for agent mutations
        try:
            op = "transform" if update.mutation and update.mutation.get("scope") == "transform" else "edit"
            await experiment_tracker.record_version(
                session_id=request.session_id,
                candidate_id=update.candidate_id,
                sequence=update.sequence,
                scores=update.scores,
                operation=op,
                operation_details=update.mutation or {},
            )
        except Exception:
            logger.warning("Failed to record experiment version for agent chat", exc_info=True)

    return AgentChatResponse(
        assistant_message=result.assistant_message,
        tool_calls=[AgentToolCallResponse(**tool.to_dict()) for tool in result.tool_calls],
        candidate_update=candidate_update,
        comparison=result.comparison,
        iterations=result.iterations,
        reasoning_steps=result.reasoning_steps,
        region_explanation=result.region_explanation,
        tool_results=result.tool_results,
        suggested_action=result.suggested_action,
    )


@app.post("/api/mutations", response_model=MutationResponse)
async def mutations(request: MutationRequest) -> MutationResponse:
    if request.position < 0 or request.position >= len(request.sequence):
        raise HTTPException(status_code=422, detail="position out of range")
    result = await evo2_service.score_mutation(request.sequence, request.position, request.alternate_base)
    return MutationResponse(
        position=result.position,
        reference_base=result.reference_base,
        alternate_base=result.alternate_base,
        delta_likelihood=result.delta_likelihood,
        predicted_impact=result.predicted_impact.value,
    )


@app.post("/api/structure", response_model=StructureResponse)
async def structure(request: StructureRequest) -> StructureResponse:
    sequence = request.sequence
    if request.region_start < 0 or request.region_end > len(sequence) or request.region_start >= request.region_end:
        raise HTTPException(status_code=422, detail="invalid structure region")

    region = sequence[request.region_start:request.region_end]
    pdb_data, confidence, model = await _predict_structure_snapshot(sequence=region, candidate_id=0)
    if not pdb_data or model == "unavailable":
        raise HTTPException(
            status_code=503,
            detail="ESMFold could not fold this region (ORF too short or API unavailable). No mock structure returned.",
        )
    return StructureResponse(pdb_data=pdb_data, model=model, confidence=confidence)


@app.post("/api/import")
async def import_sequence(file: UploadFile) -> dict[str, object]:
    """Import sequences from FASTA or GenBank files."""
    from services.sequence_formats import parse_fasta, parse_genbank

    if file.size is not None and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    content = (await file.read()).decode("utf-8", errors="replace")
    filename = (file.filename or "").lower()

    if filename.endswith((".gb", ".gbk", ".genbank")):
        records = parse_genbank(content)
        return {
            "format": "genbank",
            "count": len(records),
            "sequences": [
                {
                    "id": rec.locus or rec.accession or f"seq_{i}",
                    "sequence": rec.sequence,
                    "length": len(rec.sequence),
                    "organism": rec.organism,
                    "definition": rec.definition,
                    "features": [
                        {"type": f.type, "start": f.start, "end": f.end, "strand": f.strand}
                        for f in rec.features
                    ],
                }
                for i, rec in enumerate(records)
            ],
        }

    # Default: FASTA (handles .fasta, .fa, .fna, .txt, or raw)
    records = parse_fasta(content)
    return {
        "format": "fasta",
        "count": len(records),
        "sequences": [
            {
                "id": rec.header,
                "sequence": rec.sequence,
                "length": len(rec.sequence),
                "description": rec.description,
            }
            for rec in records
        ],
    }


@app.post("/api/export/fasta")
async def export_fasta_endpoint(request: Request) -> PlainTextResponse:
    """Export sequences to FASTA format."""
    from services.sequence_formats import export_fasta

    body = await request.json()
    sequences = body.get("sequences", [])
    if not sequences:
        raise HTTPException(status_code=422, detail="No sequences provided")

    fasta_text = export_fasta(sequences)
    return PlainTextResponse(
        content=fasta_text,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=evo_export.fasta"},
    )


@app.post("/api/export/genbank")
async def export_genbank_endpoint(request: Request) -> PlainTextResponse:
    """Export a sequence to GenBank format."""
    from services.sequence_formats import export_genbank

    body = await request.json()
    sequence = body.get("sequence", "")
    if not sequence:
        raise HTTPException(status_code=422, detail="No sequence provided")

    gb_text = export_genbank(
        sequence=sequence,
        locus=body.get("locus", "EVO_SEQ"),
        definition=body.get("definition", "Proteus-designed sequence"),
        organism=body.get("organism", "synthetic construct"),
        features=body.get("features"),
        scores=body.get("scores"),
    )
    return PlainTextResponse(
        content=gb_text,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=evo_export.gb"},
    )


@app.post("/api/offtarget")
async def offtarget_analysis(request: OffTargetRequest) -> dict[str, object]:
    """Run off-target analysis on a sequence using local k-mer scan."""
    from services.offtarget import scan_offtargets

    result = scan_offtargets(
        sequence=request.sequence,
        k=request.k,
        max_hits=request.max_hits,
    )
    return {
        "query_length": result.query_length,
        "k": result.k,
        "total_query_kmers": result.total_query_kmers,
        "repeat_fraction": result.repeat_fraction,
        "gc_balance_risk": result.gc_balance_risk,
        "hit_count": len(result.hits),
        "hits": [
            {
                "region_name": h.region_name,
                "similarity_score": h.similarity_score,
                "shared_kmers": h.shared_kmers,
                "total_query_kmers": h.total_query_kmers,
                "category": h.category,
                "risk_level": h.risk_level,
                "description": h.description,
            }
            for h in result.hits
        ],
    }


@app.post("/api/tm", response_model=TmResponse)
async def melting_temperature(request: TmRequest) -> TmResponse:
    """Melting temperature (Tm) for a DNA oligo/duplex.

    Nearest-neighbor (SantaLucia 1998) headline value with a Wallace-rule
    cross-check. Deterministic; no external calls.
    """
    from services.tm import compute_tm

    try:
        r = compute_tm(
            request.sequence,
            na_molar=request.na_molar,
            oligo_molar=request.oligo_molar,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TmResponse(
        sequence=r.sequence,
        length=r.length,
        gc_fraction=r.gc_fraction,
        method=r.method,
        tm_celsius=r.tm_celsius,
        tm_nn_celsius=r.tm_nn_celsius,
        tm_wallace_celsius=r.tm_wallace_celsius,
        na_molar=r.na_molar,
        oligo_molar=r.oligo_molar,
        delta_h_kcal=r.delta_h_kcal,
        delta_s_cal=r.delta_s_cal,
        note=r.note,
    )


@app.post("/api/protein-params", response_model=ProteinParamsResponse)
async def protein_parameters(request: ProteinParamsRequest) -> ProteinParamsResponse:
    """Protein physicochemical descriptors (MW, pI, aromaticity, GRAVY, composition).

    Deterministic ProtParam-style arithmetic over hardcoded published tables.
    """
    from services.protein_params import compute_protein_params

    try:
        r = compute_protein_params(request.sequence)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProteinParamsResponse(
        sequence=r.sequence,
        length=r.length,
        molecular_weight=r.molecular_weight,
        theoretical_pi=r.theoretical_pi,
        aromaticity=r.aromaticity,
        gravy=r.gravy,
        positively_charged=r.positively_charged,
        negatively_charged=r.negatively_charged,
        composition=r.composition,
        unknown_residues=r.unknown_residues,
        note=r.note,
    )


@app.post("/api/optimize/codons")
async def optimize_codons_endpoint(request: CodonOptimizationRequest) -> dict[str, object]:
    """Optimize codon usage for a target organism."""
    from services.codon_optimization import optimize_codons

    try:
        result = optimize_codons(
            dna=request.sequence,
            organism=request.organism,
            preserve_motifs=request.preserve_motifs or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "original_sequence": result.original_sequence,
        "optimized_sequence": result.optimized_sequence,
        "organism": result.organism,
        "original_cai": result.original_cai,
        "optimized_cai": result.optimized_cai,
        "amino_acid_sequence": result.amino_acid_sequence,
        "codons_changed": result.codons_changed,
        "total_codons": result.total_codons,
        "gc_content_before": result.gc_content_before,
        "gc_content_after": result.gc_content_after,
        "preserved_motif_count": result.preserved_motif_count,
    }


@app.post("/api/variants")
async def variant_annotation(request: VariantAnnotationRequest) -> dict[str, object]:
    """Annotate a gene/sequence region with ClinVar pathogenic variants."""
    from services.variant_annotation import annotate_sequence_region, annotate_variants

    if request.sequence and request.region_end is not None:
        result = await annotate_sequence_region(
            gene=request.gene,
            sequence=request.sequence,
            region_start=request.region_start,
            region_end=request.region_end,
            max_variants=request.max_variants,
        )
    else:
        result = await annotate_variants(
            gene=request.gene,
            sequence=request.sequence,
            max_variants=request.max_variants,
        )

    return {
        "gene": result.gene,
        "total_variants_in_gene": result.total_variants_in_gene,
        "annotations": [
            {
                "position": a.position,
                "ref_base": a.ref_base,
                "alt_base": a.alt_base,
                "clinical_significance": a.clinical_significance,
                "condition": a.condition,
                "variant_id": a.variant_id,
                "variant_title": a.variant_title,
                "variation_type": a.variation_type,
                "review_stars": a.review_stars,
                "allele_frequency": a.allele_frequency,
            }
            for a in result.annotations
        ],
        "unmapped_variants": result.unmapped_variants,
        "count": len(result.annotations),
    }


@app.post("/api/region-evidence")
async def region_evidence(request: RegionEvidenceRequest) -> dict[str, object]:
    """Assemble coordinate-bound evidence for a sequence region.

    Binds coordinates → research/evidence from three sources: ClinVar variants
    (known variants for the GENE overlapping these coordinates - context, not a
    per-base pathogenicity claim), regulatory motifs, and semantically-retrieved
    literature (post-2025 PubMed papers, vector-searched via literature_index -
    see services.region_evidence.attach_literature_evidence).

    Literature is gated to regions Evo2 actually made novel: with a
    ``session_id``, one RegionQuery is built per edited/regenerated span from
    that candidate's experiment history (see
    services.experiment_tracker.novel_regions_from_versions) instead of one
    blanket query over the whole sequence - an untouched region correctly
    gets zero literature evidence, not generic gene-wide papers. Without a
    ``session_id`` there is no known novel region, so literature is empty.
    """
    from services.region_evidence import RegionQuery, assemble_region_evidence, attach_literature_evidence

    region_end = request.region_end if request.region_end is not None else len(request.sequence)

    # Clamp to the sequence bounds - mirrors assemble_region_evidence's own
    # clamping (region_evidence.py) so an out-of-range region_start/region_end
    # can't hand the literature provider an inverted or overflowing span.
    literature_start = max(0, min(request.region_start, len(request.sequence)))
    literature_end = max(0, min(region_end, len(request.sequence)))

    assemble_task = assemble_region_evidence(
        sequence=request.sequence,
        gene=request.gene,
        region_start=request.region_start,
        region_end=region_end,
        max_variants=request.max_variants,
        include_clinvar=request.include_clinvar,
    )

    literature_queries: list[RegionQuery] = []
    if request.include_literature and literature_start < literature_end:
        versions: list = []
        if not request.session_id:
            # Observability: distinguish "no session context, so no known
            # novel region" from a genuine fetch failure below - both
            # legitimately result in zero literature, but for different
            # reasons. Expected to be the common case until the frontend
            # caller is updated to pass session_id/candidate_id through (see
            # docs/region_evidence_interface.md §5) - debug, not warning.
            logger.debug("region-evidence: no session_id, skipping literature gating")
        else:
            try:
                versions = await experiment_tracker.list_versions(
                    request.session_id, candidate_id=request.candidate_id
                )
            except Exception:
                logger.warning(
                    "Failed to load edit history for literature gating (session=%s)",
                    request.session_id, exc_info=True,
                )
        for novel_start, novel_end in novel_regions_from_versions(versions):
            span_start = max(novel_start, literature_start)
            span_end = min(novel_end, literature_end)
            if span_start < span_end:
                literature_queries.append(
                    RegionQuery(
                        start=span_start, end=span_end,
                        sequence=request.sequence, gene=request.gene,
                    )
                )

    if literature_queries:
        # Independent I/O (ClinVar/regulatory vs. the literature RAG lookups) -
        # run concurrently rather than paying the sum of both latencies.
        items, literature_items = await asyncio.gather(
            assemble_task, attach_literature_evidence(literature_queries, literature_rag_provider)
        )
        items = sorted(items + literature_items, key=lambda e: (e.start, e.source))
    else:
        items = await assemble_task

    return {
        "gene": request.gene,
        "region_start": request.region_start,
        "region_end": region_end,
        "items": [e.to_dict() for e in items],
        "count": len(items),
    }


@app.post("/api/calibration")
async def scoring_calibration(request: CalibrationRequest) -> dict[str, object]:
    """Measure how well the active Evo2 scoring engine separates known
    pathogenic from benign ClinVar variants (real AUROC, not a claim)."""
    from services.calibration import calibrate_gene

    report = await calibrate_gene(
        service=evo2_service,
        gene=request.gene,
        sequence=request.sequence,
        max_per_class=request.max_per_class,
    )
    return {
        "gene": report.gene,
        "engine_mode": report.engine_mode,
        "auroc": report.auroc,
        "n_pathogenic": report.n_pathogenic,
        "n_benign": report.n_benign,
        "n_scored": report.n_scored,
        "n_skipped_unaligned": report.n_skipped_unaligned,
        "mean_delta_pathogenic": report.mean_delta_pathogenic,
        "mean_delta_benign": report.mean_delta_benign,
        "note": report.note,
    }


# ---------------------------------------------------------------------------
# Experiment tracking endpoints
# ---------------------------------------------------------------------------


@app.post("/api/experiments/record")
async def experiment_record(request: ExperimentRecordRequest) -> dict[str, object]:
    """Record a new experiment version snapshot."""
    version_id = await experiment_tracker.record_version(
        session_id=request.session_id,
        candidate_id=request.candidate_id,
        sequence=request.sequence,
        scores=request.scores,
        operation=request.operation,
        operation_details=dict(request.operation_details),
        parent_version_id=request.parent_version_id,
        metadata=dict(request.metadata),
    )
    return {"version_id": version_id, "session_id": request.session_id}


@app.get("/api/experiments/{session_id}")
async def experiment_list(session_id: str, candidate_id: int | None = None) -> dict[str, object]:
    """List all experiment versions for a session."""
    versions = await experiment_tracker.list_versions(session_id, candidate_id=candidate_id)
    return {
        "session_id": session_id,
        "count": len(versions),
        "versions": [v.to_dict() for v in versions],
    }


@app.get("/api/experiments/{session_id}/{version_id}")
async def experiment_get(session_id: str, version_id: str) -> dict[str, object]:
    """Get a specific experiment version."""
    try:
        version = await experiment_tracker.get_version(session_id, version_id)
    except ExperimentVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return version.to_dict()


@app.post("/api/experiments/revert")
async def experiment_revert(request: ExperimentRevertRequest) -> dict[str, object]:
    """Revert a candidate to a previous experiment version."""
    try:
        version = await experiment_tracker.revert_to_version(
            request.session_id, request.version_id,
        )
    except ExperimentVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "reverted": True,
        "new_version_id": version.version_id,
        "restored_sequence_length": len(version.sequence),
        "operation": version.operation,
    }


@app.post("/api/experiments/diff")
async def experiment_diff(request: ExperimentDiffRequest) -> dict[str, object]:
    """Compute a position-level diff between two experiment versions."""
    try:
        diff = await experiment_tracker.diff_versions(
            request.session_id, request.v1_id, request.v2_id,
        )
    except ExperimentVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return diff.to_dict()


@app.get("/api/experiments/{session_id}/{version_id}/lineage")
async def experiment_lineage(session_id: str, version_id: str) -> dict[str, object]:
    """Get the lineage chain (parent→root) for a version."""
    try:
        chain = await experiment_tracker.get_lineage(session_id, version_id)
    except ExperimentVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "session_id": session_id,
        "version_id": version_id,
        "depth": len(chain),
        "lineage": [v.to_dict() for v in chain],
    }


@app.get("/api/users/{user_id}/sessions")
async def list_user_session_ids(user_id: str) -> dict[str, object]:
    """Session IDs owned by a user, from the Redis hot store.

    Relocated from GET /api/sessions/{user_id} so the session-snapshot API can
    own the /api/sessions/{session_id} route (see docs/session_persistence_interface.md).
    """
    session_ids = await session_store.list_user_sessions(user_id)
    return {"user_id": user_id, "sessions": session_ids, "count": len(session_ids)}


# ── Resumable session snapshots (durable, MongoDB) ───────────────────────────
# Contract from docs/session_persistence_interface.md: store/restore full store
# state so a session is resumable, not just re-runnable. All four degrade to
# safe no-ops (empty list / 404 / persisted:false) when Mongo is unavailable.
@app.get("/api/sessions")
async def list_session_snapshots(user_id: str | None = None) -> dict[str, object]:
    """Session summaries for the home/resume list, newest first."""
    summaries = await mongo_store.list_session_summaries(user_id)
    return {
        "persistence_enabled": mongo_store.ready,
        "sessions": summaries,
        "count": len(summaries),
    }


@app.get("/api/sessions/{session_id}")
async def get_session_snapshot(session_id: str) -> dict[str, object]:
    """Full resumable snapshot for a session (404 if none / persistence off)."""
    snapshot = await mongo_store.get_session_snapshot(session_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="session snapshot not found")
    return snapshot


@app.put("/api/sessions/{session_id}")
async def put_session_snapshot(session_id: str, snapshot: SessionSnapshot) -> dict[str, object]:
    """Upsert a session snapshot (debounced autosave from the client)."""
    payload = snapshot.model_dump(exclude_none=True)
    payload["sessionId"] = session_id  # path id is authoritative
    persisted = await mongo_store.put_session_snapshot(payload)
    return {"session_id": session_id, "persisted": persisted}


@app.delete("/api/sessions/{session_id}")
async def delete_session_snapshot(session_id: str) -> dict[str, object]:
    """Delete a stored session snapshot."""
    deleted = await mongo_store.delete_session_snapshot(session_id)
    return {"session_id": session_id, "deleted": deleted}


@app.get("/api/history/{session_id}")
async def session_history(session_id: str) -> dict[str, object]:
    """Prompt/run history for a session, oldest first - powers the reprompt thread.

    Returns an empty list (not an error) when durable persistence is disabled or
    the session predates it, so the client can treat it as 'no history yet'.
    """
    runs = await mongo_store.get_session_runs(session_id)
    return {
        "session_id": session_id,
        "persistence_enabled": mongo_store.ready,
        "runs": runs,
        "count": len(runs),
    }


# ---------------------------------------------------------------------------
# Semantic literature search (vector search)
# ---------------------------------------------------------------------------


@app.post("/api/literature/index", response_model=LiteratureIndexResponse)
async def literature_index_endpoint(request: LiteratureIndexRequest) -> LiteratureIndexResponse:
    """Embed and index research literature for semantic search.

    Provide ``gene`` to fetch + index PubMed articles, and/or ``articles`` to
    index supplied records directly. At least one is required.
    """
    if not request.gene and not request.articles:
        raise HTTPException(status_code=422, detail="provide 'gene' and/or 'articles' to index")

    query: str | None = None
    total_available = 0

    if request.articles:
        result = await literature_index.index_articles(
            [a.model_dump() for a in request.articles], gene=request.gene
        )
        total_available = len(request.articles)

    if request.gene:
        pubmed_result, query, total_available = await literature_index.index_from_pubmed(
            gene=request.gene,
            therapeutic_context=request.therapeutic_context,
            design_type=request.design_type,
            max_results=request.max_results,
        )
        # When both sources were given, report the combined indexed count.
        indexed = (result.indexed if request.articles else 0) + pubmed_result.indexed
        persisted = pubmed_result.persisted or (request.articles and result.persisted)
        return LiteratureIndexResponse(
            indexed=indexed,
            persisted=bool(persisted),
            embedding_backend=literature_index.embedder_name,
            query=query,
            total_available=total_available,
        )

    return LiteratureIndexResponse(
        indexed=result.indexed,
        persisted=result.persisted,
        embedding_backend=literature_index.embedder_name,
        query=query,
        total_available=total_available,
    )


@app.post("/api/literature/search", response_model=LiteratureSearchResponse)
async def literature_search_endpoint(request: LiteratureSearchRequest) -> LiteratureSearchResponse:
    """Semantic search over indexed literature. Empty index → empty hit list."""
    result = await literature_index.search(request.query, k=request.k, gene=request.gene)
    return LiteratureSearchResponse(
        query=request.query,
        backend=result.backend,
        embedding_backend=literature_index.embedder_name,
        count=len(result.hits),
        hits=[LiteratureHit(**hit) for hit in result.hits],
    )


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    payload = await evo2_service.health()
    return HealthResponse(
        status=str(payload.get("status", "unknown")),
        model=str(payload.get("model", "unknown")),
        gpu_available=bool(payload.get("gpu_available", False)),
        inference_mode=str(payload.get("inference_mode", "unknown")),
    )


@app.get("/api/health/detail")
async def health_detail() -> dict[str, object]:
    """Extended health for debugging - includes structure + LLM readiness."""
    payload = await evo2_service.health()
    from services import llm as llm_service

    return {
        **payload,
        "structure_mode": settings.structure_mode.value,
        "llm_available": llm_service.llm_available(),
        "evo2_mode": settings.evo2_mode.value,
        "embedding_backend": embedder.name,
        "embedding_dim": settings.embedding_dim,
        "vector_index": settings.vector_index_name,
        "durable_persistence": mongo_store.ready,
    }


@app.websocket("/ws/pipeline/{session_id}")
async def pipeline_ws(websocket: WebSocket, session_id: str) -> None:
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)


async def _predict_structure_snapshot(*, sequence: str, candidate_id: int) -> tuple[str, float, str]:
    """Return (pdb, confidence, model). Real ESMFold or an honest "unavailable".

    There is no synthetic-PDB fallback: when ESMFold cannot fold the region we
    report ``unavailable`` and the caller fails closed rather than serving a
    fabricated structure.
    """
    result = await predict_structure(sequence)
    if result is not None:
        return result.pdb_data, result.confidence, "esmfold"
    return "", 0.0, "unavailable"


async def _set_session_design_type(session_id: str, design_type: str) -> None:
    context = SESSION_CONTEXT.setdefault(session_id, {})
    context["design_type"] = design_type


def _set_session_context(session_id: str, context: dict[str, Any]) -> None:
    # Reinsert to preserve recency ordering for bounded eviction.
    SESSION_CONTEXT.pop(session_id, None)
    SESSION_CONTEXT[session_id] = context
    while len(SESSION_CONTEXT) > MAX_SESSION_CONTEXT_ENTRIES:
        oldest_key = next(iter(SESSION_CONTEXT))
        SESSION_CONTEXT.pop(oldest_key, None)


def _design_uses_protein_structure(design_type: str | None) -> bool:
    if not design_type:
        return False
    key = design_type.lower()
    return any(token in key for token in ("coding", "protein", "peptide", "orf"))

def _build_ws_url(http_request: Request, session_id: str) -> str:
    ws_scheme = "wss" if http_request.url.scheme == "https" else "ws"
    host = http_request.headers.get("host") or http_request.url.netloc
    return f"{ws_scheme}://{host}/ws/pipeline/{session_id}"


async def _persist_candidate_sequence(session_id: str, candidate_id: int, sequence: str) -> None:
    async with session_store.candidate_guard(session_id, candidate_id):
        await session_store.set_candidate_sequence(session_id, candidate_id, sequence)


async def _persist_run_completion(
    run_id: str,
    session_id: str,
    candidates: list[dict[str, Any]],
    completed: int,
    failed: int,
) -> None:
    """Snapshot a finished run into durable storage (best-effort).

    Trims heavy fields (pdb_data / regulatory_map): the history thread only needs
    sequence + scores + confidence, and PDB strings would bloat the document.
    """
    slim = [
        {
            "id": c.get("id"),
            "status": c.get("status"),
            "sequence": c.get("sequence"),
            "scores": c.get("scores"),
            "confidence": c.get("confidence"),
            "error": c.get("error"),
        }
        for c in candidates
    ]
    design_type = SESSION_CONTEXT.get(session_id, {}).get("design_type")
    await mongo_store.complete_design_run(
        run_id,
        candidates=slim,
        completed_candidates=completed,
        failed_candidates=failed,
        design_type=design_type,
    )
