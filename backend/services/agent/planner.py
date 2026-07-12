"""Agent planner - routes user messages to tool invocations.

Two strategies, tried in order:
1. Deterministic regex/keyword fast path (reliable for demo-critical commands)
2. OpenRouter JSON planning (handles everything the fast path can't)
"""

from __future__ import annotations

import logging
from typing import Any

from services import llm
from services.agent.memory import derive_repeat_action, derive_undo_action
from services.agent.parsing import (
    normalize_action,
    objective_from_prompt,
    parse_base_replacement,
    parse_explicit_edit,
    parse_region_regeneration,
    parse_transform_mode,
    resolve_selection_window,
)

logger = logging.getLogger("evo")

# Prompt for the OpenRouter JSON planner.
PLANNER_JSON_PROMPT = """You are the planning brain for Evo, a genomic design IDE assistant.
Return ONLY strict JSON with this exact shape:
{"actions":[{"tool":"<tool_name>","args":{...}}]}

Allowed tools:
0) explain_region - args: {"start": <int>, "end": <int>}
    Explain ONE region for a (possibly non-biologist) scientist: what it likely
    does, why it matters, and how confident the model is - using real per-position
    Evo2 signal + region evidence. Route here whenever the user asks about, or
    references, a SPECIFIC region or their current selection ("what does the
    middle do?", "is this chunk risky?", "explain the selected region", "why is
    the score high here?"). If the user has a selection and gives no numbers,
    still emit explain_region - the backend fills start/end from the selection
    (you MAY pass the selection's start/end shown in context).
1) explain_candidate - args: {}   (WHOLE-sequence summary; use only when NO region/selection is in focus)
2) edit_base - args: {"position": <int>, "new_base": "A|T|C|G"}
3) optimize_candidate - args: {"objective": "safety|tissue_specificity|functional|novelty", "rounds": <int 1-5, optional>}
4) compare_candidates - args: {}
5) transform_sequence - args: {"mode": "all_t|all_a|all_c|all_g|reverse_complement|replace_base", "from_base": "A|T|C|G (only for replace_base)", "to_base": "A|T|C|G (only for replace_base)"}
6) restore_sequence - args: {"sequence": "<ATCG...>"}
7) codon_optimize - args: {"organism": "homo_sapiens|e_coli|yeast|mouse|drosophila"}
8) offtarget_scan - args: {"k": <int 8-20, default 12>}
9) insert_bases - args: {"position": <int>, "bases": "<ATCG...>"}
10) delete_bases - args: {"start": <int>, "end": <int>}
11) restriction_sites - args: {"enzymes": ["EcoRI", ...] (optional)}
12) regenerate_region - args: {"start": <int, optional>, "end": <int, optional>, "gc_target": <float 0-1, optional>, "length_delta": <int, optional>, "avoid_motifs": ["GAATTC" or "EcoRI", ...] (optional), "temperature": <float, optional>}
    Use this for TRUE re-generation: the model actually resamples a region and splices it back
    (NOT a single-base edit). Route here for "regenerate positions 40-80", "redo/resample this
    region", "raise GC in this region", "avoid EcoRI here". If no start/end given, it regenerates
    the whole sequence. Conditioning is prefix-only; constraints are rejection-sampled.

Rules:
- If user asks for global sequence rewrite like "all Ts", use transform_sequence.
- If user asks to replace one base globally (e.g., "change all Gs to Cs"), use mode "replace_base".
- If user asks to undo/revert, use restore_sequence with the most recent previous sequence from memory.
- If user asks to compare or rank, include compare_candidates.
- If user asks specific base mutation, include edit_base.
- If user asks to optimize codons/expression for an organism, use codon_optimize.
- If user asks about off-target risk or safety scan, use offtarget_scan.
- If user asks to insert or add bases, use insert_bases.
- If user asks to delete or remove bases, use delete_bases.
- If user asks about restriction enzymes or cloning sites, use restriction_sites.
- If user asks to regenerate/resample/redo a region, raise GC in a region, or avoid a restriction site in a region, use regenerate_region.
- SELECTION: when the context shows a selected region/position, resolve "this"/"here"/"the
  selected region" to it. For "regenerate/resample this" emit regenerate_region with the
  selection's start/end; for "explain/what does this do/is this risky" emit explain_region.
- Prefer explain_region over explain_candidate whenever a region or selection is in focus.
- You may chain multiple actions in order.
- If uncertain, default to explain_candidate.
"""


def deterministic_fast_path(
    message: str,
    *,
    memory_entries: list[dict[str, Any]] | None = None,
    selected_position: int | None = None,
    selected_region: dict[str, int] | tuple[int, int] | None = None,
) -> list[dict[str, Any]] | None:
    """High-confidence, structurally-unambiguous commands that bypass the LLM.

    Returns a concrete plan ONLY for commands whose intent is explicit from
    structure (undo/redo, explicit single-base edits, deterministic transforms,
    and region regeneration with a resolvable range). Returns ``None`` for
    everything intent-like ("is this risky?", "make it safer", "why is the
    off-target score high?"), which routes to the LLM planner instead - killing
    the keyword false-positives.
    """
    text = message.lower()
    memory_entries = memory_entries or []

    # Undo / revert - explicit, structural.
    if any(token in text for token in ("undo", "revert", "roll back", "rollback")):
        undo_action = derive_undo_action(memory_entries)
        if undo_action is not None:
            actions = [undo_action]
            if "explain" in text or "impact" in text:
                actions.append({"tool": "explain_candidate", "args": {}})
            return actions

    # Repeat last action - explicit reference to a prior structural edit.
    if "again" in text or "same change" in text or "do that" in text:
        repeat_action = derive_repeat_action(memory_entries)
        if repeat_action is not None:
            actions = [repeat_action]
            if "explain" in text or "impact" in text:
                actions.append({"tool": "explain_candidate", "args": {}})
            return actions

    # Region regeneration - only fast-path when start/end are actually resolvable
    # (explicit numeric range or a live selection). Keyword-only / whole-sequence
    # regen flows to the LLM so it can reason with full context.
    regen_args = parse_region_regeneration(
        message, selected_position=selected_position, selected_region=selected_region,
    )
    if regen_args is not None and "start" in regen_args and "end" in regen_args:
        actions = [{"tool": "regenerate_region", "args": regen_args}]
        if "explain" in text or "impact" in text:
            actions.append({"tool": "explain_candidate", "args": {}})
        return actions

    # Explicit single-base edit ("position 5 to G").
    explicit = parse_explicit_edit(message)
    if explicit is not None:
        actions = [{"tool": "edit_base", "args": {"position": explicit[0], "new_base": explicit[1]}}]
        if "explain" in text or "impact" in text:
            actions.append({"tool": "explain_candidate", "args": {}})
        return actions

    # Global base replacement ("change all Gs to Cs").
    replacement = parse_base_replacement(text)
    if replacement is not None:
        from_base, to_base = replacement
        actions = [{
            "tool": "transform_sequence",
            "args": {"mode": "replace_base", "from_base": from_base, "to_base": to_base},
        }]
        if "explain" in text or "impact" in text:
            actions.append({"tool": "explain_candidate", "args": {}})
        return actions

    # Deterministic whole-sequence transform ("all Ts", "reverse complement").
    transform_mode = parse_transform_mode(text)
    if transform_mode is not None:
        return [{"tool": "transform_sequence", "args": {"mode": transform_mode}}]

    return None


def deterministic_plan(
    message: str,
    *,
    memory_entries: list[dict[str, Any]] | None = None,
    selected_position: int | None = None,
    selected_region: dict[str, int] | tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Full deterministic tool selection via regex and keyword matching.

    Used as the OFFLINE fallback when the LLM planner is unavailable (and as the
    substrate for :func:`deterministic_fast_path`). Returns a concrete plan for
    matched commands, or the default ``[explain_candidate]`` plan if nothing
    matched.
    """
    text = message.lower()
    actions: list[dict[str, Any]] = []
    memory_entries = memory_entries or []
    sel_window = resolve_selection_window(selected_position, selected_region)

    # Undo / revert
    if any(token in text for token in ("undo", "revert", "roll back", "rollback")):
        undo_action = derive_undo_action(memory_entries)
        if undo_action is not None:
            actions.append(undo_action)
            if "explain" in text or "impact" in text:
                actions.append({"tool": "explain_candidate", "args": {}})
            return actions

    # Repeat last action
    if ("again" in text or "same change" in text or "do that" in text) and not actions:
        repeat_action = derive_repeat_action(memory_entries)
        if repeat_action is not None:
            actions.append(repeat_action)
            if "explain" in text or "impact" in text:
                actions.append({"tool": "explain_candidate", "args": {}})
            return actions

    # Region regeneration - TRUE model re-invocation (regenerate/resample/redo a
    # region, raise GC in a region, avoid a restriction site here). Checked before
    # single-base edit / optimize so "regenerate positions 40-80" doesn't fall
    # through to hill-climbing.
    regen_args = parse_region_regeneration(
        message, selected_position=selected_position, selected_region=selected_region,
    )
    if regen_args is not None:
        actions.append({"tool": "regenerate_region", "args": regen_args})
        if "explain" in text or "impact" in text:
            actions.append({"tool": "explain_candidate", "args": {}})
        return actions

    # Explicit base edit (e.g., "position 5 to G")
    explicit = parse_explicit_edit(message)
    if explicit is not None:
        actions.append({"tool": "edit_base", "args": {"position": explicit[0], "new_base": explicit[1]}})
        if "explain" in text or "impact" in text:
            actions.append({"tool": "explain_candidate", "args": {}})

    # Base replacement (e.g., "change all Gs to Cs")
    replacement = parse_base_replacement(text)
    if replacement is not None:
        from_base, to_base = replacement
        actions.append({
            "tool": "transform_sequence",
            "args": {"mode": "replace_base", "from_base": from_base, "to_base": to_base},
        })
        if "explain" in text or "impact" in text:
            actions.append({"tool": "explain_candidate", "args": {}})
    else:
        transform_mode = parse_transform_mode(text)
        if transform_mode is not None:
            actions.append({"tool": "transform_sequence", "args": {"mode": transform_mode}})

    # Compare / rank
    if any(token in text for token in ("compare", "rank", "best candidate", "which candidate")):
        actions.append({"tool": "compare_candidates", "args": {}})

    explain_only = any(token in text for token in (
        "what do", "what does", "explain", "mean", "beginner", "plain english",
        "scores mean", "interpret", "why is", "how good", "what should i do",
        "for a beginner", "in plain english",
        "cite", "citation", "pubmed", "clinvar", "ncbi", "evidence", "literature", "sources",
    ))
    explicit_mutate = any(token in text for token in (
        "optim", "mutate", "mutation", "edit base", "change base",
        "make it safer", "make safer", "safer", "improve score", "boost score",
        "hill climb", "redesign", "improve the", "boost the",
    ))

    # Optimize / improve - NEVER on explain/beginner prompts (even if they say "what should I do next")
    if explicit_mutate and not explain_only:
        if any(token in text for token in (
            "tissue-specific", "tissue specific", "safer", "novel", "functional",
            "improve", "better", "boost", "increase", "optimize", "optimise",
        )) or any(token in text for token in ("mutate", "mutation", "edit base", "change base")):
            if not any(a["tool"] == "optimize_candidate" for a in actions):
                actions.append({"tool": "optimize_candidate", "args": {"objective": objective_from_prompt(text)}})
                actions.append({"tool": "explain_candidate", "args": {}})

    # Explain / interpret scores - read-only. When the user has a region/base
    # selected, explain THAT region (real per-position Evo2 signal + evidence)
    # instead of re-printing the whole-sequence summary.
    if explain_only and not any(a["tool"] in {"edit_base", "optimize_candidate", "transform_sequence"} for a in actions):
        if sel_window is not None and not any(
            a["tool"] in {"explain_region", "explain_candidate"} for a in actions
        ):
            start, end = sel_window
            actions.append({"tool": "explain_region", "args": {"start": start, "end": end}})
        elif not any(a["tool"] in {"explain_region", "explain_candidate"} for a in actions):
            actions.append({"tool": "explain_candidate", "args": {}})

    # Codon optimize
    if any(token in text for token in ("codon", "codon optim", "expression optim", "cai")):
        organism = "homo_sapiens"
        if "e. coli" in text or "e coli" in text or "ecoli" in text:
            organism = "e_coli"
        elif "yeast" in text:
            organism = "yeast"
        elif "mouse" in text:
            organism = "mouse"
        elif "drosophila" in text or "fly" in text:
            organism = "drosophila"
        actions.append({"tool": "codon_optimize", "args": {"organism": organism}})

    # Off-target scan
    if any(token in text for token in ("off-target", "off target", "offtarget", "kmer", "k-mer", "genomic risk")):
        if not any(a["tool"] == "optimize_candidate" for a in actions):
            actions.append({"tool": "offtarget_scan", "args": {}})

    # Restriction sites
    if any(token in text for token in ("restriction", "cut site", "cloning site", "restriction enzyme", "ecori", "bamhi")):
        actions.append({"tool": "restriction_sites", "args": {}})

    if not actions:
        actions.append({"tool": "explain_candidate", "args": {}})
    return actions


def is_default_explain_plan(actions: list[dict[str, Any]]) -> bool:
    return len(actions) == 1 and actions[0].get("tool") == "explain_candidate"


async def plan_with_llm(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    memory_entries: list[dict[str, Any]] | None = None,
    candidate_snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | None:
    """Plan tool actions via OpenRouter JSON mode. Returns None on any failure."""
    if not llm.llm_available():
        return None

    context = _build_planning_context(message, history, memory_entries, candidate_snapshot)
    try:
        parsed = await llm.complete_json(
            [
                {"role": "system", "content": PLANNER_JSON_PROMPT},
                {"role": "user", "content": context},
            ],
            temperature=0.1,
            max_tokens=512,
            timeout=15.0,
        )
    except Exception:
        logger.debug("OpenRouter planning failed", exc_info=True)
        return None

    actions = parsed.get("actions")
    if not isinstance(actions, list):
        return None
    normalized = [normalize_action(entry) for entry in actions]
    normalized = [entry for entry in normalized if entry is not None]
    return normalized or None


def _build_planning_context(
    message: str,
    history: list[dict[str, str]] | None,
    memory_entries: list[dict[str, Any]] | None,
    candidate_snapshot: dict[str, Any] | None,
) -> str:
    """Build a rich context string for LLM planning.

    Injects the user's SELECTION (position/region + the selected bases), the
    per-objective scores, the current view mode and any evidence links, so the
    planner can resolve "this"/"here" and emit region-scoped tools with real
    coordinates.
    """
    parts: list[str] = []

    if candidate_snapshot:
        parts.append(
            f"Current candidate: {candidate_snapshot.get('length_bp', '?')} bp, "
            f"GC ratio {candidate_snapshot.get('gc_ratio', '?')}, "
            f"preview: {candidate_snapshot.get('preview', '?')}"
        )

        scores = candidate_snapshot.get("scores")
        if isinstance(scores, dict) and scores:
            score_str = ", ".join(f"{k}={v}" for k, v in scores.items())
            parts.append(f"Current scores (functional/tissue/novelty higher=better, off_target higher=worse): {score_str}")

        view_mode = candidate_snapshot.get("view_mode")
        if view_mode:
            parts.append(f"View mode: {view_mode}")

        # SELECTION - the single most important signal for region-scoped intent.
        resolved = candidate_snapshot.get("selected_region_resolved")
        sel_region = candidate_snapshot.get("selected_region")
        sel_pos = candidate_snapshot.get("selected_position")
        sel_bases = candidate_snapshot.get("selected_bases")
        if resolved:
            parts.append(
                f"SELECTED REGION: positions [{resolved.get('start')}, {resolved.get('end')}) "
                f"(use these as start/end for region tools)."
            )
        elif sel_region:
            parts.append(f"SELECTED REGION: {sel_region}")
        elif sel_pos is not None:
            parts.append(f"SELECTED BASE: position {sel_pos}.")
        else:
            parts.append("No region is currently selected.")
        if sel_bases:
            parts.append(f"Selected bases: {sel_bases}")

        evidence_links = candidate_snapshot.get("evidence_links")
        if isinstance(evidence_links, list) and evidence_links:
            labels = [
                str(link.get("label") or link.get("source") or "source")
                for link in evidence_links if isinstance(link, dict)
            ]
            if labels:
                parts.append(f"Evidence available: {', '.join(labels[:6])}")

    if history:
        # Real conversation content - lets the planner resolve references like
        # "do that again", "the other one", "make it safer instead".
        recent = history[-6:]
        parts.append("Conversation so far:")
        for turn in recent:
            role = str(turn.get("role", "user")).capitalize()
            content = str(turn.get("content", "")).strip().replace("\n", " ")
            if content:
                parts.append(f"  {role}: {content[:200]}")

    if memory_entries:
        recent = memory_entries[-3:]
        parts.append("Recent tool activity:")
        for entry in recent:
            user_msg = entry.get("user_message", "")
            tools_used = [tc.get("tool", "?") for tc in entry.get("tool_calls", [])]
            parts.append(f"  User: {user_msg[:80]} -> Tools: {', '.join(tools_used) or 'none'}")

    parts.append(f"\nUser request: {message}")
    return "\n".join(parts)
