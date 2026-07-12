"""FastAPI entrypoint for the Evo backend — genomic design IDE."""

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
    MutationRequest,
    OffTargetRequest,
    RegionEvidenceRequest,
    SessionBootstrapRequest,
    StructureRequest,
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
    MutationResponse,
    StructureResponse,
)
from config import SessionStoreMode, StructureMode, settings
from models.sessions import SessionSnapshot, SessionSummary
from services.mongo_store import get_snapshot_store
from pipeline.evo2_score import rescore_mutation_detailed, score_candidate
from pipeline.orchestrator import (
    DEFAULT_SEED,
    create_session_id,
    run_followup_pipeline,
    run_generation_pipeline,
)
from services.evo2 import create_evo2_service
from services.mock_pdb import build_mock_pdb_from_dna
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
)
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
    """Modern lifespan handler — replaces deprecated @app.on_event."""
    # Startup
    if settings.session_store_mode == SessionStoreMode.REDIS:
        redis_ok = await session_store.ping()
        if not redis_ok:
            raise RuntimeError("Redis session store is enabled but unreachable.")
    yield
    # Shutdown
    await session_store.close()
    await snapshot_store.close()

app = FastAPI(title="Evo Backend", version="1.0.0", lifespan=_lifespan)
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
experiment_tracker = ExperimentTracker(session_store)
snapshot_store = get_snapshot_store()
SESSION_CONTEXT: dict[str, dict[str, Any]] = {}
MAX_SESSION_CONTEXT_ENTRIES = 512



@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze(request: AnalyzeRequest) -> AnalysisResponse:
    sequence = request.sequence
    scores, per_position = await score_candidate(evo2_service, sequence)
    orfs = find_orfs(sequence, min_length=30)[:3]
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
    run_id = create_session_id()
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
        )
    )
    # Best-effort durable log of this design run (no-op when Mongo is disabled).
    await snapshot_store.record_run(
        session_id,
        kind="design",
        summary=request.goal,
        payload={
            "run_id": run_id,
            "num_candidates": num_candidates,
            "run_profile": request.run_profile,
            "truth_mode": request.truth_mode,
        },
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
            # per-position patch — no duplicate score_mutation call needed.
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
    """Bind a sequence to a session for agent chat / edits — no pipeline run."""
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
                detail="session not found — include 'sequence' to bootstrap",
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
                update.pdb_data = pdb_data
                update.confidence = confidence
                update.structure_model = structure_model
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
        definition=body.get("definition", "Evo-designed sequence"),
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

    Binds coordinates → research/evidence using the sources that exist today:
    ClinVar variants (known variants for the GENE overlapping these coordinates —
    context, not a per-base pathogenicity claim) + regulatory motifs. A future
    RAG (per-region papers) drops in via services.region_evidence.attach_literature_evidence.
    """
    from services.region_evidence import assemble_region_evidence

    items = await assemble_region_evidence(
        sequence=request.sequence,
        gene=request.gene,
        region_start=request.region_start,
        region_end=request.region_end,
        max_variants=request.max_variants,
        include_clinvar=request.include_clinvar,
    )
    return {
        "gene": request.gene,
        "region_start": request.region_start,
        "region_end": request.region_end if request.region_end is not None else len(request.sequence),
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
    """List all Redis hot-store session ids owned by a user.

    (Moved from ``GET /api/sessions/{user_id}`` so ``/api/sessions/{session_id}``
    can serve durable snapshots without a route collision.)
    """
    session_ids = await session_store.list_user_sessions(user_id)
    return {"user_id": user_id, "sessions": session_ids, "count": len(session_ids)}


# --- Durable session snapshots (MongoDB; degrades to no-op when disabled) ---


@app.get("/api/sessions")
async def list_session_snapshots(user_id: str | None = None) -> dict[str, object]:
    """List durable session summaries for the home/resume screen."""
    summaries = await snapshot_store.list_summaries(user_id)
    return {"sessions": [s.model_dump() for s in summaries]}


@app.get("/api/sessions/{session_id}", response_model=SessionSnapshot)
async def get_session_snapshot(session_id: str) -> SessionSnapshot:
    """Return the full resumable snapshot for a session (404 if absent)."""
    snapshot = await snapshot_store.get(session_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Session snapshot not found")
    return snapshot


@app.put("/api/sessions/{session_id}", response_model=SessionSummary)
async def put_session_snapshot(session_id: str, snapshot: SessionSnapshot) -> SessionSummary:
    """Upsert (autosave) a session snapshot. Returns the lightweight summary."""
    snapshot.sessionId = session_id
    return await snapshot_store.put(snapshot)


@app.delete("/api/sessions/{session_id}")
async def delete_session_snapshot(session_id: str) -> dict[str, object]:
    """Delete a durable session snapshot."""
    await snapshot_store.delete(session_id)
    return {"sessionId": session_id, "deleted": True}


@app.get("/api/history/{session_id}")
async def get_session_history(session_id: str) -> dict[str, object]:
    """Design-run history for a session (additive; empty when disabled)."""
    runs = await snapshot_store.get_history(session_id)
    return {"sessionId": session_id, "runs": runs, "count": len(runs)}


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
    """Extended health for debugging — includes structure + LLM readiness."""
    payload = await evo2_service.health()
    from services import llm as llm_service

    return {
        **payload,
        "structure_mode": settings.structure_mode.value,
        "llm_available": llm_service.llm_available(),
        "evo2_mode": settings.evo2_mode.value,
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
    """Return (pdb, confidence, model). Never disguises mock as ESMFold."""
    if settings.structure_mode == StructureMode.ESMFOLD:
        result = await predict_structure(sequence)
        if result is not None:
            return result.pdb_data, result.confidence, "esmfold"
        return "", 0.0, "unavailable"
    pdb, confidence = build_mock_pdb_from_dna(sequence, candidate_id=candidate_id)
    return pdb, confidence, "mock"


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
