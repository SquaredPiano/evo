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
from services.agent.planner import (
    deterministic_plan,
    is_default_explain_plan,
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

RESPONDER_PROMPT = """You are the Evo copilot — a sharp genomic design partner inside a research IDE.
You just ran real tools against the user's DNA sequence. You have their message, UI context
(scores, selected base, current view), tool outcomes with real numbers, and conversation history.

Write like a competent colleague:
1. Lead with what you DID (edited / optimized / compared / explained) and the concrete result.
2. Interpret numbers in plain English: functional, tissue specificity, novelty are higher=better;
   off-target is higher=worse. Quote deltas when an edit changed scores.
3. Ground every claim in the tool outcomes — never invent scores or residues.
4. End with ONE specific next action they can take in Evo (e.g. "Open Structure to inspect residue 12"
   or "Ask me to optimize for safety").
5. 3–6 sentences. Warm, precise, no markdown bullet lists unless comparing ≥2 candidates side-by-side.
6. If a tool failed, say so honestly and suggest a recovery step."""


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


class AgenticCopilot:
    """Facade for the agentic copilot — manages graph, memory, and tool dispatch."""

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
        candidate_snapshot = await self._candidate_snapshot(session_id=session_id, candidate_id=candidate_id)
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

        # 1. Deterministic fast path — reliable for demo-critical commands
        det_plan = deterministic_plan(message, memory_entries=memory_entries)
        if not is_default_explain_plan(det_plan):
            tool_names = [a["tool"] for a in det_plan]
            return {
                "actions": det_plan,
                "reasoning_steps": [
                    f"[iter {iteration}] Planning: {message[:80]}...",
                    f"[iter {iteration}] Deterministic plan: {', '.join(tool_names)}",
                ],
            }

        # 2. OpenRouter JSON planning — handles everything the fast path can't
        llm_actions = await plan_with_llm(
            message, history=history, memory_entries=memory_entries, candidate_snapshot=candidate_snapshot,
        )
        if llm_actions:
            tool_names = [a["tool"] for a in llm_actions]
            return {
                "actions": llm_actions,
                "reasoning_steps": [
                    f"[iter {iteration}] Planning: {message[:80]}...",
                    f"[iter {iteration}] OpenRouter plan: {', '.join(tool_names)}",
                ],
            }

        return {
            "actions": det_plan,
            "reasoning_steps": [
                f"[iter {iteration}] Planning: {message[:80]}...",
                f"[iter {iteration}] Fallback plan: explain_candidate",
            ],
        }

    async def _execute_node(self, state: CopilotState) -> dict[str, object]:
        session_id = str(state["session_id"])
        candidate_id = int(state["candidate_id"])
        sequence = await self._session_store.require_candidate_sequence(session_id, candidate_id)
        actions = list(state.get("actions", []))
        if not actions:
            actions = [{"tool": "explain_candidate", "args": {}}]

        tool_calls: list[dict[str, str]] = []
        execution_notes: list[str] = []
        candidate_update: AgentCandidateUpdate | None = None
        comparison: list[dict[str, object]] | None = None

        for action in actions:
            tool_name = str(action.get("tool", "")).strip()
            args = action.get("args") or {}

            result = await self._dispatch_tool(
                tool_name, args, session_id=session_id, candidate_id=candidate_id, sequence=sequence,
            )

            tool_calls.append(result.call.to_dict())
            execution_notes.append(result.note)
            if result.candidate_update is not None:
                candidate_update = merge_candidate_updates(candidate_update, result.candidate_update)
                sequence = result.candidate_update.sequence
            if result.comparison is not None:
                comparison = result.comparison

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

    async def _respond_node(self, state: CopilotState) -> dict[str, str]:
        notes = state.get("execution_notes", [])
        reasoning = state.get("reasoning_steps", [])
        iteration = state.get("iteration", 1)

        if not notes:
            return {"assistant_message": "No actions were executed."}

        # Try LLM response generation via OpenRouter
        if llm.llm_available():
            try:
                payload = json.dumps({
                    "user_message": state.get("message", ""),
                    "conversation_history": state.get("history", []),
                    "agent_memory": state.get("memory_entries", []),
                    "candidate_snapshot": state.get("candidate_snapshot", {}),
                    "tool_calls": state.get("tool_calls", []),
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
                    return {"assistant_message": f"{text}{iteration_note}"}
            except Exception:
                logger.debug("OpenRouter responder failed, using deterministic fallback", exc_info=True)

        # Deterministic fallback
        base_msg = notes[-1]
        if iteration > 1:
            base_msg = f"{base_msg} (completed in {iteration} agent iterations)"
        return {"assistant_message": base_msg}

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
            if tool_name == "edit_base":
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

    async def _candidate_snapshot(self, *, session_id: str, candidate_id: int) -> dict[str, Any]:
        try:
            sequence = await self._session_store.require_candidate_sequence(session_id, candidate_id)
        except Exception:
            return {}
        gc = (sequence.count("G") + sequence.count("C")) / max(len(sequence), 1)
        return {
            "length_bp": len(sequence),
            "gc_ratio": round(gc, 4),
            "preview": sequence[:80],
        }
