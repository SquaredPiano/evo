"""LangGraph state machine for the agentic copilot.

Graph: plan → execute → reflect →(continue|finish)→ respond
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from pipeline.evo2_score import score_candidate
from services import llm
from services.agent.memory import AgentMemory
from services.agent.parsing import resolve_selection_window
from services.agent.planner import (
    deterministic_fast_path,
    deterministic_plan,
    plan_with_llm,
)
from services.agent.state import (
    MAX_AGENT_ITERATIONS,
    AgentCandidateUpdate,
    AgentChatResult,
    AgentToolCall,
    CopilotState,
    ToolExecution,
    merge_candidate_updates,
    trim_history,
)
from services.agent import tools as agent_tools
from services.evo2 import Evo2MockService, Evo2Service
from services.session_store import SessionStore

logger = logging.getLogger(__name__)

RESPONDER_PROMPT = """You are the Evo copilot - a sharp genomic design partner inside a research IDE.
You just ran real tools against the user's DNA sequence. You have their message, UI context
(scores, selected base, current view), tool outcomes with real numbers, evidence links
(NCBI / PubMed / ClinVar when present), and conversation history.

Format for a chat bubble - scannable, never a wall of text:
1. First line: what you DID + the headline result (one short sentence).
2. Then 2–4 short lines, each starting with a label like "Functional:" / "Off-target:" /
   "Evidence:" - one idea per line. Prefer line breaks over long paragraphs.
3. Interpret numbers in plain English: functional, tissue specificity, novelty are higher=better;
   off-target is higher=worse. Quote real deltas when an edit changed scores.
4. When evidence_links or retrieval notes are present, cite them with full URLs on their own lines
   (PubMed, ClinVar, NCBI Gene). Never invent PMIDs or accessions.
5. Ground every claim in tool outcomes - never invent scores or residues.
6. End with ONE specific next action in Evo.
7. Hard limit: ~80 words unless comparing ≥2 candidates. No markdown tables.
8. If a tool failed, say so honestly and suggest a recovery step.

REGION FOCUS (when a `region_explanation` is present in the payload):
- Explain THIS region for a non-biologist: in one plain line, what it likely does
  (use the bound evidence - regulatory motifs, ClinVar gene context) and why it
  matters. Then a line on WHERE the model is least confident (cite the region's
  weakest per-position position from signal_summary).
- CONFIDENCE HONESTY: `model_confidence.sampled_probs` are REAL Evo2 model
  confidence ONLY when `is_real_model_confidence` is true (engine=nim, i.e. after
  a regeneration) - cite them as "model confidence" then. Otherwise say the
  per-position numbers are heuristic proxies, not real Evo2 log-likelihoods.
  Never fabricate a probability.
- ClinVar is gene-locus CONTEXT, never a pathogenicity verdict on generated bases.
- If a `suggested_action` is present, phrase its `label` as the closing next action."""


def _weakest_objective(scores: dict[str, Any]) -> str:
    """Pick the optimization objective that most needs work from a score dict.

    Scores are 0–1; off_target is inverted (higher = worse). Returns one of the
    objectives understood by tool_optimize.
    """
    candidates: dict[str, float] = {}
    if "functional" in scores:
        candidates["functional"] = float(scores["functional"])
    if "tissue_specificity" in scores:
        candidates["tissue_specificity"] = float(scores["tissue_specificity"])
    if "novelty" in scores:
        candidates["novelty"] = float(scores["novelty"])
    if "off_target" in scores:
        # Invert so it competes on the same "headroom" scale.
        candidates["safety"] = 1.0 - float(scores["off_target"])
    if not candidates:
        return "functional"
    return min(candidates, key=candidates.get)


_OBJECTIVE_LABELS = {
    "safety": "off-target safety",
    "tissue_specificity": "tissue specificity",
    "functional": "functional plausibility",
    "novelty": "novelty",
}
_OBJECTIVE_SCORE_KEY = {
    "safety": "off_target",
    "tissue_specificity": "tissue_specificity",
    "functional": "functional",
    "novelty": "novelty",
}


def _regeneration_signal(candidate_update: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract real regeneration confidence from a candidate_update, or None.

    Returns the region span, engine, per-base ``sampled_probs`` (REAL Evo2
    confidence only when engine=nim), and the constraint report - or None when
    the last op was not a region regeneration.
    """
    if not candidate_update:
        return None
    mutation = candidate_update.get("mutation") or {}
    if mutation.get("scope") != "regenerate":
        return None
    return {
        "start": mutation.get("start"),
        "end": mutation.get("end"),
        "new_region_end": mutation.get("new_region_end"),
        "engine": mutation.get("engine"),
        "sampled_probs": mutation.get("sampled_probs"),
        "sampled_probs_are_real_model_confidence": mutation.get(
            "sampled_probs_are_real_model_confidence"
        ),
        "constraint_report": mutation.get("constraint_report"),
    }


def _weakest_window(
    per_position: list[dict[str, Any]] | None, width: int = 40
) -> tuple[int, int] | None:
    """Find the [start, end) window of lowest mean per-position score.

    Uses real per-position Evo2 log-likelihoods (or their heuristic proxy). This
    is what turns "the model is least sure here" into concrete coordinates for a
    suggested regeneration.
    """
    if not per_position:
        return None
    rows = [
        (int(p["position"]), float(p["score"]))
        for p in per_position
        if isinstance(p, dict) and "position" in p and "score" in p
    ]
    if len(rows) < 2:
        return None
    rows.sort(key=lambda r: r[0])
    positions = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    n = len(vals)
    w = min(width, n)
    best_i, best_mean = 0, float("inf")
    for i in range(0, n - w + 1):
        m = sum(vals[i : i + w]) / w
        if m < best_mean:
            best_mean, best_i = m, i
    return positions[best_i], positions[min(best_i + w - 1, n - 1)] + 1


def _derive_suggested_action(state: CopilotState) -> dict[str, Any] | None:
    """Propose ONE concrete, data-grounded next action for the frontend.

    Grounds the suggestion in the weakest objective (:func:`_weakest_objective`)
    and, when available, the lowest-confidence region window - e.g. "tissue score
    is weakest and positions 40-80 have low model confidence → regenerate that
    region?". Returns a structured suggested-action or None.
    """
    candidate_update = state.get("candidate_update") or {}
    scores = dict(candidate_update.get("scores") or {})
    if not scores:
        snap = state.get("candidate_snapshot") or {}
        raw = snap.get("scores")
        if isinstance(raw, dict):
            scores = dict(raw)
    if not scores:
        return None

    objective = _weakest_objective(scores)
    label = _OBJECTIVE_LABELS.get(objective, objective)
    raw_val = scores.get(_OBJECTIVE_SCORE_KEY.get(objective, objective))
    val_str = f" ({float(raw_val):.2f})" if isinstance(raw_val, (int, float)) else ""

    weak_region: tuple[int, int] | None = None
    region_explanation = state.get("region_explanation") or {}
    summary = region_explanation.get("signal_summary") if isinstance(region_explanation, dict) else None
    region = region_explanation.get("region") if isinstance(region_explanation, dict) else None
    if summary and summary.get("low_confidence_positions") and isinstance(region, dict):
        weak_region = (int(region["start"]), int(region["end"]))
    else:
        weak_region = _weakest_window(candidate_update.get("per_position_scores"))

    if weak_region and weak_region[0] is not None:
        s, e = int(weak_region[0]), int(weak_region[1])
        return {
            "label": f"Regenerate positions {s}–{e} to lift {label}",
            "tool": "regenerate_region",
            "args": {"start": s, "end": e},
            "objective": objective,
            "rationale": (
                f"{label} is the weakest objective{val_str} and positions {s}–{e} show the "
                f"lowest per-position model confidence."
            ),
        }
    return {
        "label": f"Optimize for {label}",
        "tool": "optimize_candidate",
        "args": {"objective": objective, "rounds": 3},
        "objective": objective,
        "rationale": f"{label} is the weakest objective{val_str}; a targeted hill-climb can improve it.",
    }


class AgenticCopilot:
    """Facade for the agentic copilot - manages graph, memory, and tool dispatch."""

    def __init__(self, *, session_store: SessionStore, evo2_service: Evo2Service) -> None:
        self._session_store = session_store
        self._service = evo2_service
        self._memory = AgentMemory(session_store)
        self._graph = self._build_graph()

    async def clear_session_memory(self, *, session_id: str) -> None:
        await self._memory.clear_session(session_id)

    async def chat(
        self,
        *,
        session_id: str,
        candidate_id: int,
        message: str,
        history: list[dict[str, str]] | None = None,
        ui_context: dict[str, Any] | None = None,
    ) -> AgentChatResult:
        memory_entries = await self._memory.snapshot(session_id, candidate_id)
        candidate_snapshot = await self._candidate_snapshot(
            session_id=session_id, candidate_id=candidate_id, ui_context=ui_context,
        )
        if ui_context:
            candidate_snapshot = {**candidate_snapshot, **ui_context}
        state: CopilotState = {
            "session_id": session_id,
            "candidate_id": candidate_id,
            "message": message.strip(),
            "history": trim_history(history or []),
            "actions": [],
            "tool_calls": [],
            "candidate_update": None,
            "comparison": None,
            "region_explanation": None,
            "tool_results": [],
            "suggested_action": None,
            "execution_notes": [],
            "assistant_message": "",
            "iteration": 0,
            "should_continue": True,
            "reasoning_steps": [],
            "memory_entries": memory_entries,
            "candidate_snapshot": candidate_snapshot,
        }
        final = await self._graph.ainvoke(state)

        candidate_update = None
        if final.get("candidate_update"):
            update_payload = final["candidate_update"]
            candidate_update = AgentCandidateUpdate(
                candidate_id=int(update_payload["candidate_id"]),
                sequence=str(update_payload["sequence"]),
                scores=dict(update_payload["scores"]),
                mutation=update_payload.get("mutation"),
                per_position_scores=update_payload.get("per_position_scores"),
                pdb_data=update_payload.get("pdb_data"),
                confidence=update_payload.get("confidence"),
                structure_model=update_payload.get("structure_model"),
                regulatory_map=update_payload.get("regulatory_map"),
            )

        result = AgentChatResult(
            assistant_message=str(final.get("assistant_message") or "I could not produce a response."),
            tool_calls=[AgentToolCall(**entry) for entry in final.get("tool_calls", [])],
            candidate_update=candidate_update,
            comparison=final.get("comparison"),
            iterations=int(final.get("iteration", 1)),
            reasoning_steps=final.get("reasoning_steps"),
            region_explanation=final.get("region_explanation"),
            tool_results=final.get("tool_results") or None,
            suggested_action=final.get("suggested_action"),
        )
        await self._memory.remember_turn(
            session_id=session_id,
            candidate_id=candidate_id,
            user_message=message.strip(),
            candidate_update=candidate_update,
            tool_calls=[call.to_dict() for call in result.tool_calls],
            assistant_message=result.assistant_message,
        )
        return result

    # -------------------------------------------------------------------------
    # Graph construction
    # -------------------------------------------------------------------------

    def _build_graph(self):
        graph = StateGraph(CopilotState)
        graph.add_node("plan", self._plan_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("reflect", self._reflect_node)
        graph.add_node("respond", self._respond_node)
        graph.add_edge(START, "plan")
        graph.add_edge("plan", "execute")
        graph.add_edge("execute", "reflect")
        graph.add_conditional_edges(
            "reflect",
            self._should_continue,
            {"continue": "plan", "finish": "respond"},
        )
        graph.add_edge("respond", END)
        return graph.compile()

    @staticmethod
    def _should_continue(state: CopilotState) -> str:
        if state.get("should_continue") and state.get("iteration", 0) < MAX_AGENT_ITERATIONS:
            return "continue"
        return "finish"

    # -------------------------------------------------------------------------
    # Graph nodes
    # -------------------------------------------------------------------------

    async def _plan_node(self, state: CopilotState) -> dict[str, object]:
        iteration = state.get("iteration", 0)
        message = state.get("message", "")
        history = state.get("history", [])
        memory_entries = state.get("memory_entries", [])
        candidate_snapshot = state.get("candidate_snapshot", {})

        # 0. Forced plan injected by the reflect node (e.g. auto-optimize).
        forced = state.get("forced_plan")
        if forced:
            tool_names = [a.get("tool", "?") for a in forced]
            return {
                "actions": list(forced),
                "forced_plan": None,
                "reasoning_steps": [f"[iter {iteration}] Forced plan from reflection: {', '.join(tool_names)}"],
            }

        if not message:
            return {
                "actions": [{"tool": "explain_candidate", "args": {}}],
                "iteration": iteration,
                "reasoning_steps": [f"[iter {iteration}] No message provided, defaulting to explain_candidate"],
            }

        selected_position = candidate_snapshot.get("selected_position")
        resolved = candidate_snapshot.get("selected_region_resolved")
        selected_region = resolved or candidate_snapshot.get("selected_region")

        # 1. High-confidence deterministic fast path - ONLY structurally
        # unambiguous commands (explicit edits, undo/redo, deterministic
        # transforms, resolvable-range regen). Keeps these fast + reliable even
        # when the LLM is up, and returns None for anything intent-like.
        fast_plan = deterministic_fast_path(
            message,
            memory_entries=memory_entries,
            selected_position=selected_position,
            selected_region=selected_region,
        )
        if fast_plan is not None:
            tool_names = [a["tool"] for a in fast_plan]
            return {
                "actions": fast_plan,
                "reasoning_steps": [
                    f"[iter {iteration}] Planning: {message[:80]}...",
                    f"[iter {iteration}] Deterministic fast-path: {', '.join(tool_names)}",
                ],
            }

        # 2. LLM-FIRST planning - the primary router for all free-text intent
        # ("is this chunk risky?", "what does the middle do?", "make it safer").
        # This kills the brittle-keyword false positives.
        if llm.llm_available():
            llm_actions = await plan_with_llm(
                message, history=history, memory_entries=memory_entries, candidate_snapshot=candidate_snapshot,
            )
            if llm_actions:
                tool_names = [a["tool"] for a in llm_actions]
                return {
                    "actions": llm_actions,
                    "reasoning_steps": [
                        f"[iter {iteration}] Planning: {message[:80]}...",
                        f"[iter {iteration}] LLM plan: {', '.join(tool_names)}",
                    ],
                }

        # 3. OFFLINE fallback - full deterministic keyword planner (used when the
        # LLM is unavailable or returned nothing).
        det_plan = deterministic_plan(
            message,
            memory_entries=memory_entries,
            selected_position=selected_position,
            selected_region=selected_region,
        )
        tool_names = [a["tool"] for a in det_plan]
        return {
            "actions": det_plan,
            "reasoning_steps": [
                f"[iter {iteration}] Planning: {message[:80]}...",
                f"[iter {iteration}] Offline deterministic plan: {', '.join(tool_names)}",
            ],
        }

    async def _execute_node(self, state: CopilotState) -> dict[str, object]:
        session_id = str(state["session_id"])
        candidate_id = int(state["candidate_id"])
        sequence = await self._session_store.require_candidate_sequence(session_id, candidate_id)
        actions = list(state.get("actions", []))
        if not actions:
            actions = [{"tool": "explain_candidate", "args": {}}]

        snapshot = state.get("candidate_snapshot", {}) or {}
        gene = snapshot.get("gene") or snapshot.get("target_gene")

        tool_calls: list[dict[str, str]] = []
        execution_notes: list[str] = []
        candidate_update: AgentCandidateUpdate | None = None
        comparison: list[dict[str, object]] | None = None
        region_explanation: dict[str, object] | None = None
        tool_results: list[dict[str, object]] = []

        for action in actions:
            tool_name = str(action.get("tool", "")).strip()
            args = action.get("args") or {}

            result = await self._dispatch_tool(
                tool_name, args, session_id=session_id, candidate_id=candidate_id,
                sequence=sequence, gene=gene,
            )

            tool_calls.append(result.call.to_dict())
            execution_notes.append(result.note)
            if result.candidate_update is not None:
                candidate_update = merge_candidate_updates(candidate_update, result.candidate_update)
                sequence = result.candidate_update.sequence
            if result.comparison is not None:
                comparison = result.comparison
            if result.region_explanation is not None:
                region_explanation = result.region_explanation
            if result.structured_result is not None:
                tool_results.append(result.structured_result)

            # On failure, fall back to scoring so the response always has useful data
            if result.call.status == "failed":
                fallback = await self._fallback_score(candidate_id, sequence)
                tool_calls.append(fallback.call.to_dict())
                execution_notes.append(f"Recovered via fallback scoring after {tool_name} failure. {fallback.note}")
                if fallback.candidate_update is not None:
                    candidate_update = merge_candidate_updates(candidate_update, fallback.candidate_update)
                    sequence = fallback.candidate_update.sequence

        return {
            "tool_calls": tool_calls,
            "execution_notes": execution_notes,
            "candidate_update": candidate_update.to_dict() if candidate_update else None,
            "comparison": comparison,
            "region_explanation": region_explanation,
            "tool_results": tool_results,
        }

    async def _reflect_node(self, state: CopilotState) -> dict[str, object]:
        iteration = state.get("iteration", 0) + 1
        tool_calls = state.get("tool_calls", [])

        failed_tools = [tc for tc in tool_calls if tc.get("status") == "failed"]
        has_failures = len(failed_tools) > 0

        update = state.get("candidate_update")
        combined_score = None
        scores: dict[str, Any] = {}
        if update and isinstance(update, dict):
            scores = update.get("scores", {}) or {}
            combined_score = scores.get("combined")

        should_continue = False
        forced_plan: list[dict[str, Any]] | None = None
        new_steps: list[str] = []

        already_optimized = any(
            tc.get("tool") == "optimize_candidate" for tc in tool_calls
        )
        message_lc = (state.get("message") or "").lower()
        explicit_transform = any(
            phrase in message_lc
            for phrase in (
                "all t", "all ts", "all a", "all c", "all g",
                "transform", "replace all", "reverse complement", "for the fun",
            )
        )
        wants_optimization = any(
            kw in message_lc
            for kw in (
                "optim", "mutate", "make it safer", "make safer", "safer",
                "boost score", "improve score", "redesign", "improve the",
            )
        )
        explain_only = any(
            kw in message_lc
            for kw in ("explain", "plain english", "beginner", "what does", "scores mean", "what should i do")
        )

        if has_failures and iteration < MAX_AGENT_ITERATIONS:
            new_steps.append(
                f"[reflect iter {iteration}] {len(failed_tools)} tool(s) failed. Re-planning to recover."
            )
            should_continue = True
        elif (
            combined_score is not None
            and combined_score < 0.45
            and iteration < MAX_AGENT_ITERATIONS
            and not already_optimized
            and wants_optimization
            and not explicit_transform
            and not explain_only
        ):
            objective = _weakest_objective(scores)
            new_steps.append(
                f"[reflect iter {iteration}] Combined score {combined_score:.3f} is weak (<0.45). "
                f"Auto-optimizing for '{objective}'."
            )
            should_continue = True
            forced_plan = [
                {"tool": "optimize_candidate", "args": {"objective": objective, "rounds": 3}},
                {"tool": "explain_candidate", "args": {}},
            ]
        else:
            new_steps.append(
                f"[reflect iter {iteration}] "
                + (f"Score {combined_score:.3f}. " if combined_score is not None else "")
                + f"Satisfied after {iteration} iteration(s)."
            )

        return {
            "iteration": iteration,
            "should_continue": should_continue,
            "forced_plan": forced_plan,
            "reasoning_steps": new_steps,
        }

    async def _respond_node(self, state: CopilotState) -> dict[str, object]:
        notes = state.get("execution_notes", [])
        reasoning = state.get("reasoning_steps", [])
        iteration = state.get("iteration", 1)

        if not notes:
            return {"assistant_message": "No actions were executed."}

        candidate_update = state.get("candidate_update")
        regen = _regeneration_signal(candidate_update)

        # Region focus for the responder: the rich explain_region payload if one
        # was produced, else a lightweight focus derived from a regeneration.
        region_explanation = state.get("region_explanation")
        region_focus = dict(region_explanation) if isinstance(region_explanation, dict) else None
        if region_focus is None and regen and regen.get("start") is not None:
            s = int(regen["start"])
            e = int(regen.get("new_region_end") or regen.get("end") or s)
            per_position = (candidate_update or {}).get("per_position_scores") or []
            region_focus = {
                "region": {"start": s, "end": e, "length": e - s},
                "per_position_scores": [
                    p for p in per_position
                    if isinstance(p, dict) and s <= p.get("position", -1) < e
                ],
            }

        # Fold REAL Evo2 model confidence (sampled_probs) into the focus when a
        # regeneration produced it - kept honest via the is_real flag.
        if region_focus is not None and regen:
            probs = regen.get("sampled_probs") or []
            mean_prob = (sum(probs) / len(probs)) if probs else None
            region_focus["model_confidence"] = {
                "engine": regen.get("engine"),
                "is_real_model_confidence": bool(regen.get("sampled_probs_are_real_model_confidence")),
                "mean_sampled_prob": round(mean_prob, 4) if mean_prob is not None else None,
                "sampled_probs": probs or None,
            }
            region_focus["constraint_report"] = regen.get("constraint_report")

        suggested_action = _derive_suggested_action(state)
        # region_focus feeds suggested-action derivation too; recompute once the
        # focus (with sampled_probs) exists so the rationale can cite it.
        extra: dict[str, object] = {"suggested_action": suggested_action}
        if region_focus is not None:
            extra["region_explanation"] = region_focus

        # Try LLM response generation via OpenRouter
        if llm.llm_available():
            try:
                payload = json.dumps({
                    "user_message": state.get("message", ""),
                    "conversation_history": state.get("history", []),
                    "agent_memory": state.get("memory_entries", []),
                    "candidate_snapshot": state.get("candidate_snapshot", {}),
                    "tool_calls": state.get("tool_calls", []),
                    "tool_results": state.get("tool_results", []),
                    "region_explanation": region_focus,
                    "suggested_action": suggested_action,
                    "execution_notes": notes,
                    "iterations": iteration,
                    "reasoning_trace": reasoning,
                }, indent=2)
                text = (await asyncio.wait_for(
                    llm.complete_text(
                        [
                            {"role": "system", "content": RESPONDER_PROMPT},
                            {"role": "user", "content": payload},
                        ],
                        temperature=0.2,
                        max_tokens=400,
                    ),
                    timeout=15.0,
                )).strip()
                if text:
                    iteration_note = f" [{iteration} iteration(s)]" if iteration > 1 else ""
                    return {"assistant_message": f"{text}{iteration_note}", **extra}
            except Exception:
                logger.debug("OpenRouter responder failed, using deterministic fallback", exc_info=True)

        # Deterministic fallback - keep line breaks so the chat UI stays scannable.
        base_msg = notes[-1]
        snapshot = state.get("candidate_snapshot") or {}
        evidence = snapshot.get("evidence_links") or []
        if evidence and "pubmed.ncbi.nlm.nih.gov" not in base_msg and "clinvar" not in base_msg.lower():
            cite_lines = []
            for link in evidence[:4]:
                if not isinstance(link, dict):
                    continue
                label = str(link.get("label") or link.get("source") or "Source")
                url = str(link.get("url") or "")
                if url:
                    cite_lines.append(f"{label}: {url}")
            if cite_lines:
                base_msg = f"{base_msg}\nEvidence:\n" + "\n".join(cite_lines)
        if iteration > 1:
            base_msg = f"{base_msg}\n(completed in {iteration} agent iterations)"
        suggested = extra.get("suggested_action")
        if isinstance(suggested, dict) and suggested.get("label"):
            base_msg = f"{base_msg}\nSuggested next: {suggested['label']}"
        return {"assistant_message": base_msg, **extra}

    # -------------------------------------------------------------------------
    # Tool dispatch
    # -------------------------------------------------------------------------

    async def _dispatch_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        session_id: str,
        candidate_id: int,
        sequence: str,
        gene: str | None = None,
    ) -> ToolExecution:
        """Dispatch a tool by name. Returns ToolExecution (never raises)."""
        common = {
            "service": self._service,
            "store": self._session_store,
            "session_id": session_id,
            "candidate_id": candidate_id,
            "sequence": sequence,
        }

        try:
            if tool_name == "explain_region":
                start_raw = args.get("start")
                end_raw = args.get("end")
                return await agent_tools.tool_explain_region(
                    service=self._service,
                    candidate_id=candidate_id,
                    sequence=sequence,
                    start=int(start_raw) if start_raw is not None else None,
                    end=int(end_raw) if end_raw is not None else None,
                    gene=gene,
                )
            elif tool_name == "edit_base":
                return await agent_tools.tool_edit_base(
                    **common,
                    position=int(args.get("position")),
                    new_base=str(args.get("new_base", "")).upper(),
                )
            elif tool_name == "optimize_candidate":
                rounds_raw = args.get("rounds")
                return await agent_tools.tool_optimize(
                    **common,
                    objective=str(args.get("objective", "tissue_specificity")),
                    rounds=int(rounds_raw) if rounds_raw is not None else None,
                )
            elif tool_name == "compare_candidates":
                return await agent_tools.tool_compare(**common)
            elif tool_name == "transform_sequence":
                return await agent_tools.tool_transform(
                    **common,
                    mode=str(args.get("mode", "all_t")),
                    from_base=str(args.get("from_base", "")).upper() or None,
                    to_base=str(args.get("to_base", "")).upper() or None,
                )
            elif tool_name == "restore_sequence":
                return await agent_tools.tool_restore(
                    **common,
                    restore_to=str(args.get("sequence", "")).upper(),
                )
            elif tool_name == "codon_optimize":
                return await agent_tools.tool_codon_optimize(
                    **common,
                    organism=str(args.get("organism", "homo_sapiens")),
                )
            elif tool_name == "offtarget_scan":
                return await agent_tools.tool_offtarget_scan(
                    service=self._service,
                    candidate_id=candidate_id,
                    sequence=sequence,
                    k=int(args.get("k", 12)),
                )
            elif tool_name == "insert_bases":
                return await agent_tools.tool_insert_bases(
                    **common,
                    position=int(args.get("position", 0)),
                    bases=str(args.get("bases", "")),
                )
            elif tool_name == "delete_bases":
                return await agent_tools.tool_delete_bases(
                    **common,
                    start=int(args.get("start", 0)),
                    end=int(args.get("end", 0)),
                )
            elif tool_name == "restriction_sites":
                return await agent_tools.tool_restriction_sites(
                    candidate_id=candidate_id,
                    sequence=sequence,
                    enzymes=args.get("enzymes"),
                )
            elif tool_name == "regenerate_region":
                start_raw = args.get("start")
                end_raw = args.get("end")
                gc_raw = args.get("gc_target")
                temp_raw = args.get("temperature")
                return await agent_tools.tool_regenerate_region(
                    **common,
                    start=int(start_raw) if start_raw is not None else None,
                    end=int(end_raw) if end_raw is not None else None,
                    gc_target=float(gc_raw) if gc_raw is not None else None,
                    length_delta=int(args.get("length_delta", 0) or 0),
                    avoid_motifs=args.get("avoid_motifs"),
                    temperature=float(temp_raw) if temp_raw is not None else None,
                )
            else:
                return await agent_tools.tool_explain(**common)
        except Exception as exc:
            return ToolExecution(
                call=AgentToolCall(tool=tool_name or "unknown_tool", status="failed", summary=str(exc)),
                note=f"Tool {tool_name or 'unknown_tool'} failed: {exc}",
            )

    async def _fallback_score(self, candidate_id: int, sequence: str) -> ToolExecution:
        """Score the candidate as a recovery path when a tool fails."""
        try:
            return await agent_tools.tool_explain(
                service=self._service, candidate_id=candidate_id, sequence=sequence,
            )
        except Exception:
            try:
                scores, per_position = await score_candidate(self._service, sequence)
            except Exception:
                scores, per_position = await score_candidate(Evo2MockService(), sequence)
            score_dict = scores.to_dict()
            return ToolExecution(
                call=AgentToolCall(
                    tool="explain_candidate", status="ok",
                    summary="Recovered by re-scoring the active candidate.",
                ),
                note=(
                    f"Recovered with fallback scoring. Candidate #{candidate_id} combined "
                    f"{score_dict['combined']:.3f}, functional {score_dict['functional']:.3f}, "
                    f"tissue {score_dict['tissue_specificity']:.3f}, off-target {score_dict['off_target']:.3f}."
                ),
                candidate_update=AgentCandidateUpdate(
                    candidate_id=candidate_id,
                    sequence=sequence,
                    scores=score_dict,
                    per_position_scores=[{"position": x.position, "score": x.score} for x in per_position],
                ),
            )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    async def _candidate_snapshot(
        self,
        *,
        session_id: str,
        candidate_id: int,
        ui_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            sequence = await self._session_store.require_candidate_sequence(session_id, candidate_id)
        except Exception:
            return {}
        gc = (sequence.count("G") + sequence.count("C")) / max(len(sequence), 1)
        snapshot: dict[str, Any] = {
            "length_bp": len(sequence),
            "gc_ratio": round(gc, 4),
            "preview": sequence[:80],
        }

        # Make the SELECTED region's actual bases visible to the planner/responder
        # (not just the first 80 bp) so region reasoning works anywhere in the seq.
        if ui_context:
            window = resolve_selection_window(
                ui_context.get("selected_position"),
                ui_context.get("selected_region"),
            )
            if window is not None:
                start = max(0, min(window[0], len(sequence)))
                end = max(start, min(window[1], len(sequence)))
                if end > start:
                    snapshot["selected_region_resolved"] = {"start": start, "end": end}
                    snapshot["selected_bases"] = sequence[start:end]
        return snapshot
