"""Tests for async pipeline orchestrator event flow."""

import pytest

import pipeline.orchestrator as orchestrator
from pipeline.orchestrator import (
    _filter_relevant_literature_hits,
    run_followup_pipeline,
    run_generation_pipeline,
)
from config import StructureMode
from pipeline.retrieval import RetrievalResult
from services.evo2 import Evo2MockService
from services.literature_index import SearchResult
from services.pubmed import PubMedArticle, PubMedResult
from ws.manager import WebSocketManager


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def accept(self) -> None:
        return

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)


_STUB_PDB = (
    "HEADER    ESMFOLD TEST STUB\n"
    "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 90.00           N\n"
    "ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00 90.00           C\n"
    "ATOM      3  C   ALA A   1       2.009   1.420   0.000  1.00 90.00           C\n"
    "ATOM      4  O   ALA A   1       3.222   1.601   0.000  1.00 90.00           O\n"
    "END\n"
)


@pytest.fixture(autouse=True)
def _stub_esmfold(monkeypatch: pytest.MonkeyPatch):
    """Stub the ESMFold network call at its boundary so pipeline event-flow tests
    are deterministic and offline. This returns a REAL StructurePrediction shape
    (as a successful ESMFold call would); it is not a mock PDB fallback inside the
    pipeline. Tests that exercise structure-unavailable behavior re-patch
    ``predict_structure`` in their body, which overrides this fixture."""
    from services.structure import StructurePrediction

    async def _ok(*_args, **_kwargs) -> StructurePrediction:
        return StructurePrediction(pdb_data=_STUB_PDB, protein_sequence="A", confidence=0.9)

    monkeypatch.setattr(orchestrator, "predict_structure", _ok)


@pytest.mark.asyncio
async def test_generation_pipeline_emits_key_events() -> None:
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-gen")

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-gen",
        goal="Design a regulatory element for BDNF in hippocampal neurons",
        n_tokens=5,
    )

    events = [e["event"] for e in ws.sent]
    assert events[0] == "pipeline_manifest"
    assert "intent_parsed" in events
    assert "stage_status" in events
    assert "retrieval_progress" in events
    assert "candidate_status" in events
    assert "generation_token" in events
    assert "candidate_scored" in events
    assert "structure_ready" in events
    assert "explanation_chunk" in events
    assert events[-1] == "pipeline_complete"


@pytest.mark.asyncio
async def test_demo_profile_retrieval_reports_failure_without_fabricating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even under the demo profile, failed sources are reported as failed — no
    fabricated demo payloads are ever backfilled (real_only is now the behavior)."""
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-retrieval-fallback")

    async def _missing_retrieval(*_args, **_kwargs):
        return None

    monkeypatch.setattr(orchestrator, "retrieve_context", _missing_retrieval)

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-retrieval-fallback",
        goal="Design promoter",
        n_tokens=2,
        run_profile="demo",
        truth_mode="demo_fallback",
    )

    retrieval_events = [event for event in ws.sent if event["event"] == "retrieval_progress"]
    assert len(retrieval_events) == 3
    assert all(event["data"]["status"] == "failed" for event in retrieval_events)
    assert all(event["data"]["result"] == {} for event in retrieval_events)


@pytest.mark.asyncio
async def test_real_only_retrieval_reports_failure_when_sources_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-retrieval-real-only")

    async def _missing_retrieval(*_args, **_kwargs):
        return None

    monkeypatch.setattr(orchestrator, "retrieve_context", _missing_retrieval)

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-retrieval-real-only",
        goal="Design promoter",
        n_tokens=2,
        run_profile="demo",
        truth_mode="real_only",
    )

    retrieval_events = [event for event in ws.sent if event["event"] == "retrieval_progress"]
    assert len(retrieval_events) == 3
    assert all(event["data"]["status"] == "failed" for event in retrieval_events)


class _FakeLiteratureIndex:
    """Duck-types LiteratureIndex.search()/ensure_indexed() without touching
    the real module (owned by a concurrently-modified teammate file)."""

    def __init__(self, hits: list[dict[str, object]]) -> None:
        self._hits = hits
        self.calls: list[dict[str, object]] = []
        self.ensure_indexed_calls: list[dict[str, object]] = []

    async def ensure_indexed(
        self, gene: str | None, therapeutic_context: str | None = None, design_type: str | None = None
    ) -> None:
        self.ensure_indexed_calls.append(
            {"gene": gene, "therapeutic_context": therapeutic_context, "design_type": design_type}
        )

    async def search(self, query: str, *, k: int = 5, gene: str | None = None) -> SearchResult:
        self.calls.append({"query": query, "k": k, "gene": gene})
        return SearchResult(hits=self._hits, backend="memory")


def _retrieval_with_pubmed(existing_articles: list[PubMedArticle]) -> RetrievalResult:
    return RetrievalResult(
        ncbi=None,
        pubmed=PubMedResult(query="BRCA1", articles=list(existing_articles), total_count=len(existing_articles)),
        clinvar=None,
    )


class TestFilterRelevantLiteratureHits:
    """Pure unit tests for the relevance filter, using the real observed score
    ranges from the local-hash embedder (see the constants' comments)."""

    def test_empty_hits_returns_empty(self):
        assert _filter_relevant_literature_hits([]) == []

    def test_strong_top_hit_keeps_hits_within_relative_cutoff(self):
        hits = [{"score": 0.669}, {"score": 0.624}, {"score": 0.583}, {"score": 0.20}]
        kept = _filter_relevant_literature_hits(hits)
        # top=0.669, cutoff=0.669*0.7=0.468 -> first three pass, last does not.
        assert [h["score"] for h in kept] == [0.669, 0.624, 0.583]

    def test_weak_top_hit_excludes_everything(self):
        """Real observed case: an off-topic query, still gene-filtered, whose
        best hit only reaches ~0.49 — below the absolute floor, so nothing
        should be cited even though the relative gap between hits is small."""
        hits = [{"score": 0.4923}, {"score": 0.4917}, {"score": 0.4751}]
        assert _filter_relevant_literature_hits(hits) == []

    def test_floor_boundary_is_inclusive_just_above_and_exclusive_just_below(self):
        assert _filter_relevant_literature_hits([{"score": 0.55}]) == [{"score": 0.55}]
        assert _filter_relevant_literature_hits([{"score": 0.549}]) == []


@pytest.mark.asyncio
async def test_retrieval_merges_relevant_literature_hits_into_pubmed_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-lit-merge")

    async def _fake_retrieve_context(spec):
        return _retrieval_with_pubmed([
            PubMedArticle(pmid="1", title="Existing keyword hit", authors=[], abstract="a", year="2025", journal="J"),
        ])

    monkeypatch.setattr(orchestrator, "retrieve_context", _fake_retrieve_context)

    fake_index = _FakeLiteratureIndex(hits=[
        {"pmid": "1", "title": "Duplicate of the keyword hit", "abstract": "dup", "score": 0.66, "year": "2025", "journal": "J"},
        {"pmid": "2", "title": "New vector hit", "abstract": "new", "score": 0.62, "year": "2025", "journal": "J"},
    ])

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-lit-merge",
        goal="Design a regulatory element for BRCA1",
        n_tokens=2,
        literature_index=fake_index,
    )

    assert fake_index.calls, "literature_index.search() was never called"
    assert fake_index.ensure_indexed_calls[0]["gene"] == "BRCA1"
    assert fake_index.calls[0]["gene"] == "BRCA1"
    assert fake_index.calls[0]["k"] == 5
    retrieval_events = [e for e in ws.sent if e["event"] == "retrieval_progress"]
    pubmed_event = next(e for e in retrieval_events if e["data"]["source"] == "pubmed")
    pmids = [a["pmid"] for a in pubmed_event["data"]["result"]["articles"]]
    # pmid "1" appears once (deduped against the existing keyword hit); "2" is new.
    assert pmids == ["1", "2"]


@pytest.mark.asyncio
async def test_retrieval_merges_literature_when_keyword_pubmed_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The keyword PubMed sub-fetch can fail/timeout independently (result.pubmed
    is None) while NCBI/ClinVar still succeed — literature hits must still
    surface via a freshly-built PubMedResult, not silently disappear."""
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-lit-no-keyword-pubmed")

    async def _fake_retrieve_context(spec):
        return RetrievalResult(ncbi=None, pubmed=None, clinvar=None)

    monkeypatch.setattr(orchestrator, "retrieve_context", _fake_retrieve_context)

    fake_index = _FakeLiteratureIndex(hits=[
        {"pmid": "3", "title": "Vector-only hit", "abstract": "v", "score": 0.66, "year": "2025", "journal": "J"},
    ])

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-lit-no-keyword-pubmed",
        goal="Design a regulatory element for BRCA1",
        n_tokens=2,
        literature_index=fake_index,
    )

    retrieval_events = [e for e in ws.sent if e["event"] == "retrieval_progress"]
    pubmed_event = next(e for e in retrieval_events if e["data"]["source"] == "pubmed")
    assert pubmed_event["data"]["status"] == "complete"
    assert [a["pmid"] for a in pubmed_event["data"]["result"]["articles"]] == ["3"]


@pytest.mark.asyncio
async def test_retrieval_excludes_weak_literature_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """A query with no genuinely relevant literature must not cite the
    closest-but-still-weak match — the whole point of the relevance filter."""
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-lit-weak")

    async def _fake_retrieve_context(spec):
        return _retrieval_with_pubmed([])

    monkeypatch.setattr(orchestrator, "retrieve_context", _fake_retrieve_context)

    fake_index = _FakeLiteratureIndex(hits=[
        {"pmid": "9", "title": "Weak, off-topic match", "abstract": "x", "score": 0.49, "year": "2025", "journal": "J"},
    ])

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-lit-weak",
        goal="Design a regulatory element for BRCA1",
        n_tokens=2,
        literature_index=fake_index,
    )

    retrieval_events = [e for e in ws.sent if e["event"] == "retrieval_progress"]
    pubmed_event = next(e for e in retrieval_events if e["data"]["source"] == "pubmed")
    assert pubmed_event["data"]["result"]["articles"] == []


@pytest.mark.asyncio
async def test_retrieval_without_literature_index_is_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backward compatibility: literature_index defaults to None, so existing
    callers (e.g. run_followup_pipeline, which never passes it) see no change."""
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-lit-none")

    async def _fake_retrieve_context(spec):
        return _retrieval_with_pubmed([
            PubMedArticle(pmid="1", title="Keyword hit only", authors=[], abstract="a", year="2025", journal="J"),
        ])

    monkeypatch.setattr(orchestrator, "retrieve_context", _fake_retrieve_context)

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-lit-none",
        goal="Design a regulatory element for BRCA1",
        n_tokens=2,
    )

    retrieval_events = [e for e in ws.sent if e["event"] == "retrieval_progress"]
    pubmed_event = next(e for e in retrieval_events if e["data"]["source"] == "pubmed")
    assert [a["pmid"] for a in pubmed_event["data"]["result"]["articles"]] == ["1"]


@pytest.mark.asyncio
async def test_generation_pipeline_uses_custom_seed() -> None:
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-custom-seed")

    custom_seed = "ATGCGT"
    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-custom-seed",
        goal="Design promoter",
        n_tokens=2,
        seed_sequence=custom_seed,
    )

    complete = ws.sent[-1]
    assert complete["event"] == "pipeline_complete"
    assert complete["data"]["requested_candidates"] == 1
    generated_sequence = complete["data"]["candidates"][0]["sequence"]
    assert generated_sequence.startswith(custom_seed)
    assert len(generated_sequence) == len(custom_seed) + 2


@pytest.mark.asyncio
async def test_generation_pipeline_requested_candidates_are_all_present() -> None:
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-multi")

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-multi",
        goal="Design promoter",
        n_tokens=2,
        n_candidates=5,
        run_profile="demo",
    )

    complete = ws.sent[-1]
    assert complete["event"] == "pipeline_complete"
    assert complete["data"]["requested_candidates"] == 5
    ids = [candidate["id"] for candidate in complete["data"]["candidates"]]
    assert ids == [0, 1, 2, 3, 4]

    manifest = ws.sent[0]
    assert manifest["event"] == "pipeline_manifest"
    assert manifest["data"]["truth_mode"] == "demo_fallback"
    seeded_events = [event for event in ws.sent if event["event"] == "candidate_seeded"]
    assert sorted(event["data"]["candidate_id"] for event in seeded_events) == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_followup_pipeline_returns_steps_and_emits_complete() -> None:
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-follow")

    steps = await run_followup_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-follow",
        message="make this more tissue-specific",
        candidate_id=0,
    )

    assert steps == ["intent_parse", "constraint_refine", "evo2_scoring", "structure", "explanation"]
    events = [e["event"] for e in ws.sent]
    assert "structure_ready" in events
    assert ws.sent[-1]["event"] == "pipeline_complete"
    assert ws.sent[-1]["data"]["candidates"][0]["status"] == "structured"


@pytest.mark.asyncio
async def test_followup_pipeline_uses_provided_base_sequence() -> None:
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-follow-base")

    base_sequence = "ATGCCGATGCCGATGCCG"
    await run_followup_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-follow-base",
        message="make this more tissue-specific",
        candidate_id=0,
        base_sequence=base_sequence,
    )

    complete = ws.sent[-1]
    assert complete["event"] == "pipeline_complete"
    candidate_sequence = complete["data"]["candidates"][0]["sequence"]
    assert len(candidate_sequence) == len(base_sequence)


@pytest.mark.asyncio
async def test_followup_pipeline_fails_closed_when_structure_prediction_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAIL-LOUD: when ESMFold raises there is no synthetic fold; the candidate
    fails honestly with a null structure."""
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-follow-structure-fail")

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("esmfold unavailable")

    monkeypatch.setattr(orchestrator, "predict_structure", _boom)

    await run_followup_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-follow-structure-fail",
        message="make this more tissue-specific",
        candidate_id=0,
        base_sequence="ATGCCGATGCCGATGCCG",
        run_profile="demo",
    )

    complete = ws.sent[-1]
    assert complete["event"] == "pipeline_complete"
    assert complete["data"]["failed_candidates"] == 1
    assert complete["data"]["candidates"][0]["status"] == "failed"
    assert complete["data"]["candidates"][0]["pdb_data"] is None


@pytest.mark.asyncio
async def test_generation_pipeline_invokes_candidate_callback() -> None:
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-cb")

    seen: dict[str, object] = {}

    async def capture(candidate_id: int, sequence: str) -> None:
        seen["candidate_id"] = candidate_id
        seen["sequence"] = sequence

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-cb",
        goal="Design promoter",
        n_tokens=3,
        on_candidate_ready=capture,
    )

    assert seen["candidate_id"] == 0
    assert isinstance(seen["sequence"], str)
    assert len(str(seen["sequence"])) > 0


@pytest.mark.asyncio
async def test_generation_pipeline_caps_requested_candidates_at_ten() -> None:
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-max-ten")

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-max-ten",
        goal="Design promoter",
        n_tokens=1,
        n_candidates=42,
    )

    complete = ws.sent[-1]
    assert complete["event"] == "pipeline_complete"
    assert complete["data"]["requested_candidates"] == 10
    assert len(complete["data"]["candidates"]) == 10


@pytest.mark.asyncio
async def test_stage_status_never_regresses() -> None:
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-stages")

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-stages",
        goal="Design promoter",
        n_tokens=3,
    )

    rank = {"pending": 0, "active": 1, "done": 2, "failed": 2}
    seen: dict[str, int] = {}
    for event in ws.sent:
        if event["event"] != "stage_status":
            continue
        stage = event["data"]["stage"]
        status = event["data"]["status"]
        value = rank[status]
        previous = seen.get(stage, -1)
        assert value >= previous
        seen[stage] = value


@pytest.mark.asyncio
async def test_demo_profile_fails_closed_when_structure_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAIL-LOUD: demo profile no longer backfills a mock structure. When ESMFold
    returns nothing, the candidate fails honestly with a null structure."""
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-demo-fallback")

    async def _no_structure(*_args, **_kwargs):
        return None

    monkeypatch.setattr(orchestrator, "predict_structure", _no_structure)

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-demo-fallback",
        goal="Design promoter",
        n_tokens=2,
        run_profile="demo",
    )

    complete = ws.sent[-1]
    assert complete["event"] == "pipeline_complete"
    assert complete["data"]["failed_candidates"] == 1
    assert complete["data"]["candidates"][0]["status"] == "failed"
    assert complete["data"]["candidates"][0]["pdb_data"] is None


@pytest.mark.asyncio
async def test_live_profile_fails_closed_when_structure_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAIL-LOUD: live profile also fails closed with no synthetic structure."""
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-live-fail")

    async def _no_structure(*_args, **_kwargs):
        return None

    monkeypatch.setattr(orchestrator, "predict_structure", _no_structure)

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-live-fail",
        goal="Design promoter",
        n_tokens=2,
        run_profile="live",
    )

    complete = ws.sent[-1]
    assert complete["event"] == "pipeline_complete"
    assert complete["data"]["failed_candidates"] == 1
    assert complete["data"]["candidates"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_followup_pipeline_invokes_candidate_callback() -> None:
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-follow-cb")

    seen: dict[str, object] = {}

    def capture(candidate_id: int, sequence: str) -> None:
        seen["candidate_id"] = candidate_id
        seen["sequence"] = sequence

    await run_followup_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-follow-cb",
        message="make this more tissue-specific",
        candidate_id=2,
        base_sequence="ATGCCGATGCCGATGCCG",
        on_candidate_ready=capture,
    )

    assert seen["candidate_id"] == 2
    assert isinstance(seen["sequence"], str)


@pytest.mark.asyncio
async def test_ten_candidates_all_complete_in_demo_mode() -> None:
    """All 10 candidates must reach structured status in demo mode with mock services."""
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-ten")

    await run_generation_pipeline(
        manager=manager,
        service=Evo2MockService(),
        session_id="session-ten",
        goal="Design a regulatory element for BDNF in hippocampal neurons",
        n_tokens=5,
        n_candidates=10,
        run_profile="demo",
    )

    complete = ws.sent[-1]
    assert complete["event"] == "pipeline_complete"
    data = complete["data"]
    assert data["requested_candidates"] == 10
    assert data["completed_candidates"] == 10
    assert data["failed_candidates"] == 0
    assert len(data["candidates"]) == 10
    for candidate in data["candidates"]:
        assert candidate["status"] == "structured"
        assert candidate["pdb_data"]
        assert candidate["sequence"]


@pytest.mark.asyncio
async def test_demo_profile_fails_closed_when_generation_service_raises() -> None:
    """FAIL-LOUD: when generation raises before producing any real bases, the
    candidate fails honestly — no fabricated demo tokens are streamed."""

    class _FailingGenerateService(Evo2MockService):
        async def generate(self, seed: str, n_tokens: int, temperature: float = 1.0):
            raise RuntimeError("simulated generation failure")
            yield  # pragma: no cover

    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-demo-recover-generate")

    await run_generation_pipeline(
        manager=manager,
        service=_FailingGenerateService(),
        session_id="session-demo-recover-generate",
        goal="Design promoter",
        n_tokens=4,
        n_candidates=10,
        run_profile="demo",
    )

    complete = ws.sent[-1]
    assert complete["event"] == "pipeline_complete"
    assert complete["data"]["requested_candidates"] == 10
    assert complete["data"]["failed_candidates"] == 10
    assert all(c["status"] == "failed" for c in complete["data"]["candidates"])
    assert len(complete["data"]["candidates"]) == 10


@pytest.mark.asyncio
async def test_candidate_temperature_stays_within_api_bounds() -> None:
    """Temperature for all 10 candidates must stay in [0.0, 1.0] for NIM API compatibility."""
    manager = WebSocketManager()
    ws = _FakeWebSocket()
    await manager.connect(ws, "session-temp")

    captured_temps: list[float] = []
    original_generate = Evo2MockService.generate

    async def tracking_generate(self, seed, n_tokens=50, temperature=1.0):
        captured_temps.append(temperature)
        async for token in original_generate(self, seed, n_tokens=n_tokens, temperature=temperature):
            yield token

    Evo2MockService.generate = tracking_generate  # type: ignore[assignment]
    try:
        await run_generation_pipeline(
            manager=manager,
            service=Evo2MockService(),
            session_id="session-temp",
            goal="Design promoter",
            n_tokens=2,
            n_candidates=10,
            run_profile="demo",
        )
    finally:
        Evo2MockService.generate = original_generate  # type: ignore[assignment]

    assert len(captured_temps) == 10
    for temp in captured_temps:
        assert 0.0 <= temp <= 1.0, f"Temperature {temp} exceeds API safe range [0.0, 1.0]"
