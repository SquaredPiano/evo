/**
 * candidateDisplay — single source of truth for how the "active edit target"
 * candidate is named across the UI.
 *
 * There are two numbers floating around the product and they were used
 * inconsistently:
 *   - rank    → 1-based index of the candidate in the (already sorted) list.
 *               This is the USER-FACING number ("candidate #1").
 *   - id      → the raw candidate id, e.g. 3 → "Candidate_003". This is an
 *               internal handle; only ever shown as a secondary/tooltip label.
 *
 * `activeCandidateId` in the store is the edit target. Every edit surface
 * (mutation panel, tools, chat, sequence toolbar) should show the SAME
 * "Editing candidate #N" label derived from here.
 */

export interface CandidateDisplayInput {
  id: number;
}

export interface CandidateDisplay {
  /** 1-based rank in the sorted candidate list, or null when there are none. */
  rank: number | null;
  /** Raw candidate id, or null when there are none. */
  id: number | null;
  /** User-facing label, e.g. "Editing candidate #1". */
  label: string;
  /** Secondary/tooltip label, e.g. "Candidate_003". */
  subtitle: string;
  /** True when a concrete candidate resolved (safe to render chrome). */
  hasCandidate: boolean;
}

/** Format a raw candidate id the way the product does everywhere else. */
export function candidateIdLabel(id: number): string {
  return `Candidate_${id.toString().padStart(3, "0")}`;
}

/**
 * Resolve the display metadata for the candidate edits currently apply to.
 *
 * Candidates are assumed already sorted (the store keeps them ranked by
 * overall score). The active candidate is `activeCandidateId`; if that id is
 * missing or not found we fall back to the top-ranked candidate, matching the
 * store's own `activeCandidateId ?? candidates[0]` edit-target logic.
 */
export function getCandidateDisplay(
  candidates: CandidateDisplayInput[],
  activeCandidateId: number | null,
): CandidateDisplay {
  const empty: CandidateDisplay = {
    rank: null,
    id: null,
    label: "No candidate selected",
    subtitle: "",
    hasCandidate: false,
  };

  if (!candidates || candidates.length === 0) return empty;

  const foundIdx = candidates.findIndex((c) => c.id === activeCandidateId);
  const idx = foundIdx >= 0 ? foundIdx : 0;
  const candidate = candidates[idx];
  if (!candidate) return empty;

  const rank = idx + 1;
  return {
    rank,
    id: candidate.id,
    label: `Editing candidate #${rank}`,
    subtitle: candidateIdLabel(candidate.id),
    hasCandidate: true,
  };
}
