"""Tests for constrained region regeneration (services/regeneration.py).

Covers: splice math, length_delta, GC scoring, motif avoidance, the deterministic
mock path (no fabricated probabilities), and generate_detailed provenance.
"""

from __future__ import annotations

import pytest

from services.evo2 import Evo2MockService, GenerationResult
from services.regeneration import (
    RegenerationResult,
    gc_fraction,
    motifs_present,
    normalize_avoid_motifs,
    parse_generation_constraints,
    regenerate_region,
)


# ---------------------------------------------------------------------------
# Pure constraint helpers
# ---------------------------------------------------------------------------

class TestConstraintHelpers:
    def test_gc_fraction_basic(self) -> None:
        assert gc_fraction("GGCC") == 1.0
        assert gc_fraction("ATAT") == 0.0
        assert gc_fraction("ATGC") == 0.5

    def test_gc_fraction_empty(self) -> None:
        assert gc_fraction("") == 0.0

    def test_motifs_present(self) -> None:
        assert motifs_present("AAGAATTCAA", ["GAATTC"]) == ["GAATTC"]
        assert motifs_present("AAAAAA", ["GAATTC"]) == []

    def test_motifs_present_case_insensitive(self) -> None:
        assert motifs_present("aagaattcaa", ["gaattc"]) == ["gaattc"]

    def test_normalize_avoid_motifs_enzyme_names(self) -> None:
        assert normalize_avoid_motifs(["EcoRI"]) == ["GAATTC"]
        assert normalize_avoid_motifs(["ecori", "BamHI"]) == ["GAATTC", "GGATCC"]

    def test_normalize_avoid_motifs_raw_sites(self) -> None:
        assert normalize_avoid_motifs(["GAATTC"]) == ["GAATTC"]

    def test_normalize_avoid_motifs_dedup_and_unknown(self) -> None:
        assert normalize_avoid_motifs(["EcoRI", "GAATTC", "NotAnEnzyme"]) == ["GAATTC"]

    def test_parse_generation_constraints_gc(self) -> None:
        assert parse_generation_constraints(["high_gc_content"])["gc_target"] == 0.62
        assert parse_generation_constraints(["low_gc"])["gc_target"] == 0.38

    def test_parse_generation_constraints_avoid(self) -> None:
        parsed = parse_generation_constraints(["avoid_ecori"])
        # Enzyme name is resolvable to its site via normalize_avoid_motifs.
        assert normalize_avoid_motifs(parsed["avoid_motifs"]) == ["GAATTC"]

    def test_parse_generation_constraints_empty(self) -> None:
        assert parse_generation_constraints([]) == {}
        assert parse_generation_constraints(["novel_sequence"]) == {}


# ---------------------------------------------------------------------------
# Splice math + length_delta
# ---------------------------------------------------------------------------

SEQ = "ATGCATGCATGCATGCATGCATGCATGCATGC"  # 32 bp


@pytest.mark.asyncio
class TestSpliceMath:
    async def test_middle_region_splice(self) -> None:
        svc = Evo2MockService()
        result = await regenerate_region(svc, SEQ, 8, 16, {})
        # prefix preserved
        assert result.spliced_sequence.startswith(SEQ[:8])
        # suffix preserved
        assert result.spliced_sequence.endswith(SEQ[16:])
        # regenerated region length equals region length (no length_delta)
        assert len(result.regenerated) == 8
        assert result.region_start == 8
        assert result.region_end == 16
        assert result.new_region_end == 16
        # full reconstruction
        assert result.spliced_sequence == SEQ[:8] + result.regenerated + SEQ[16:]

    async def test_tail_regeneration(self) -> None:
        svc = Evo2MockService()
        result = await regenerate_region(svc, SEQ, 24, len(SEQ), {})
        assert result.spliced_sequence.startswith(SEQ[:24])
        assert len(result.regenerated) == len(SEQ) - 24
        # No suffix beyond the region.
        assert result.spliced_sequence == SEQ[:24] + result.regenerated

    async def test_length_delta_grows_region(self) -> None:
        svc = Evo2MockService()
        result = await regenerate_region(svc, SEQ, 8, 16, {"length_delta": 5})
        assert len(result.regenerated) == 8 + 5
        assert result.new_region_end == 8 + 13
        # suffix still preserved after the longer region
        assert result.spliced_sequence.endswith(SEQ[16:])
        assert len(result.spliced_sequence) == len(SEQ) + 5

    async def test_length_delta_shrinks_region(self) -> None:
        svc = Evo2MockService()
        result = await regenerate_region(svc, SEQ, 8, 16, {"length_delta": -3})
        assert len(result.regenerated) == 8 - 3
        assert len(result.spliced_sequence) == len(SEQ) - 3

    async def test_length_delta_clamped_to_min_one(self) -> None:
        svc = Evo2MockService()
        # region length 8, delta -100 → clamp to 1 token
        result = await regenerate_region(svc, SEQ, 8, 16, {"length_delta": -100})
        assert len(result.regenerated) == 1

    async def test_out_of_bounds_clamped(self) -> None:
        svc = Evo2MockService()
        result = await regenerate_region(svc, SEQ, -5, 999, {})
        assert result.region_start == 0
        assert result.region_end == len(SEQ)


# ---------------------------------------------------------------------------
# Mock determinism + no fabricated probabilities
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMockPath:
    async def test_mock_is_deterministic(self) -> None:
        svc = Evo2MockService()
        r1 = await regenerate_region(svc, SEQ, 8, 16, {"gc_target": 0.6})
        r2 = await regenerate_region(svc, SEQ, 8, 16, {"gc_target": 0.6})
        assert r1.spliced_sequence == r2.spliced_sequence
        assert r1.regenerated == r2.regenerated

    async def test_mock_never_fabricates_probs(self) -> None:
        svc = Evo2MockService()
        result = await regenerate_region(svc, SEQ, 8, 16, {})
        assert result.sampled_probs is None
        assert result.engine == "mock"
        assert result.sampled_probs_are_real_model_confidence is False

    async def test_prefix_only_flag_always_set(self) -> None:
        svc = Evo2MockService()
        result = await regenerate_region(svc, SEQ, 8, 16, {})
        assert result.prefix_only_conditioning is True
        assert result.method == "rejection_sampling_sample_k"

    async def test_regenerated_bases_are_valid(self) -> None:
        svc = Evo2MockService()
        result = await regenerate_region(svc, SEQ, 8, 16, {})
        assert set(result.regenerated) <= set("ATCGN")


# ---------------------------------------------------------------------------
# GC scoring + motif avoidance (rejection sampling behaviour)
# ---------------------------------------------------------------------------

class _FakeService(Evo2MockService):
    """Mock that returns scripted candidates so we can assert best-pick logic."""

    def __init__(self, candidates: list[str]) -> None:
        self._candidates = candidates
        self._i = 0

    async def generate_detailed(  # type: ignore[override]
        self, seed: str, n_tokens: int, temperature: float = 1.0
    ) -> GenerationResult:
        region = self._candidates[self._i % len(self._candidates)]
        self._i += 1
        return GenerationResult(
            generated=region,
            sampled_probs=None,
            engine="mock",
            elapsed_ms=0.0,
            seed=seed,
            n_tokens=n_tokens,
        )


@pytest.mark.asyncio
class TestConstraintSatisfaction:
    async def test_gc_target_picks_closest(self) -> None:
        # candidate #2 (GGGG) is closest to gc_target=1.0
        svc = _FakeService(["ATAT", "AAAA", "GGGG", "ATGC"])
        result = await regenerate_region(
            svc, "AAAAAAAA" + "XXXX", 8, 12, {"gc_target": 1.0}, sample_k=4,
        )
        assert result.regenerated == "GGGG"
        assert result.constraint_report["achieved_gc"] == 1.0
        assert result.constraint_report["gc_within_tolerance"] is True

    async def test_avoid_motif_prefers_clean_candidate(self) -> None:
        # Only the last candidate lacks the EcoRI site GAATTC.
        svc = _FakeService(["GAATTC", "GAATTC", "CCCCCC"])
        result = await regenerate_region(
            svc, "AAAAAAAA" + "XXXXXX", 8, 14, {"avoid_motifs": ["EcoRI"]}, sample_k=3,
        )
        assert "GAATTC" not in result.regenerated
        assert result.constraint_report["avoid_motifs_still_present"] == []
        assert result.constraint_report["satisfied"] is True

    async def test_avoid_motif_reports_when_unavoidable(self) -> None:
        # Every candidate contains the motif — report it honestly, don't crash.
        svc = _FakeService(["GAATTC", "GAATTC"])
        result = await regenerate_region(
            svc, "AAAAAAAA" + "XXXXXX", 8, 14, {"avoid_motifs": ["GAATTC"]}, sample_k=2,
        )
        assert result.constraint_report["avoid_motifs_still_present"] == ["GAATTC"]
        assert result.constraint_report["satisfied"] is False


# ---------------------------------------------------------------------------
# generate_detailed provenance (engine-level)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGenerateDetailed:
    async def test_mock_provenance(self) -> None:
        svc = Evo2MockService()
        result = await svc.generate_detailed("ATGC", 10)
        assert isinstance(result, GenerationResult)
        assert result.engine == "mock"
        assert result.sampled_probs is None
        assert len(result.generated) == 10
        assert result.elapsed_ms is not None

    async def test_mock_generate_detailed_matches_generate(self) -> None:
        svc = Evo2MockService()
        detailed = await svc.generate_detailed("ATGC", 8, temperature=1.0)
        streamed = "".join([t async for t in svc.generate("ATGC", 8, temperature=1.0)])
        assert detailed.generated == streamed


# ---------------------------------------------------------------------------
# Planner routing → regenerate_region tool
# ---------------------------------------------------------------------------

class TestPlannerRouting:
    def test_explicit_range_routes(self) -> None:
        from services.agent.planner import deterministic_plan

        plan = deterministic_plan("regenerate positions 40-80")
        assert plan[0]["tool"] == "regenerate_region"
        assert plan[0]["args"] == {"start": 40, "end": 80}

    def test_redo_region_routes(self) -> None:
        from services.agent.planner import deterministic_plan

        assert deterministic_plan("redo this region")[0]["tool"] == "regenerate_region"

    def test_raise_gc_routes_with_target(self) -> None:
        from services.agent.planner import deterministic_plan

        plan = deterministic_plan("raise GC in this region")
        assert plan[0]["tool"] == "regenerate_region"
        assert plan[0]["args"]["gc_target"] == 0.62

    def test_avoid_enzyme_routes_with_motif(self) -> None:
        from services.agent.planner import deterministic_plan

        plan = deterministic_plan("avoid EcoRI here")
        assert plan[0]["tool"] == "regenerate_region"
        assert plan[0]["args"]["avoid_motifs"] == ["GAATTC"]

    def test_non_regen_message_does_not_route(self) -> None:
        from services.agent.planner import deterministic_plan

        assert deterministic_plan("make this more tissue-specific")[0]["tool"] != "regenerate_region"
        assert deterministic_plan("change position 5 to G")[0]["tool"] == "edit_base"


# ---------------------------------------------------------------------------
# End-to-end tool: persists sequence + carries provenance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRegenerateTool:
    async def test_tool_persists_and_carries_provenance(self) -> None:
        from services.agent.tools import tool_regenerate_region
        from services.session_store import MemorySessionStore

        store = MemorySessionStore(default_seed="ATGC")
        await store.set_candidate_sequence("s1", 0, SEQ)
        result = await tool_regenerate_region(
            service=Evo2MockService(),
            store=store,
            session_id="s1",
            candidate_id=0,
            sequence=SEQ,
            start=8,
            end=16,
        )
        assert result.call.tool == "regenerate_region"
        assert result.call.status == "ok"
        update = result.candidate_update
        assert update is not None
        # Sequence was persisted to the store.
        persisted = await store.require_candidate_sequence("s1", 0)
        assert persisted == update.sequence
        # Provenance is carried honestly.
        mut = update.mutation
        assert mut["engine"] == "mock"
        assert mut["sampled_probs"] is None
        assert mut["sampled_probs_are_real_model_confidence"] is False
        assert mut["prefix_only_conditioning"] is True
        assert mut["constraint_report"]["note"]
