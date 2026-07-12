/**
 * Sequence diff helper for CompareView - a lightweight, honest, git-diff-style
 * comparison between two DNA candidate sequences.
 *
 * Semantics mirror the backend primitive `_diff_sequences`
 * (backend/services/experiment_tracker.py): position-level substitutions over
 * the common prefix, then a length tail reported as insertions/deletions. This
 * is intentionally NOT a full gap-aware alignment - it matches what the backend
 * `/api/experiments/diff` endpoint reports, so the two never disagree.
 *
 * Per-position score deltas are computed ONLY when both candidates carry
 * per-position likelihood scores. When they are absent, `scoreDelta` is left
 * undefined - we never fabricate a zero delta.
 */

export type DiffKind = "snp" | "ins" | "del";

export interface DiffPosition {
  /** 0-based position in the reference (A) coordinate space. */
  position: number;
  /** Base in candidate A ("-" for an insertion in B). */
  ref: string;
  /** Base in candidate B ("-" for a deletion relative to A). */
  alt: string;
  kind: DiffKind;
  /** scoreB - scoreA at this position; undefined when scores are unavailable. */
  scoreDelta?: number;
}

export interface DiffHunk {
  /** First position shown in this hunk (context included), in A coordinates. */
  start: number;
  /** One past the last position shown (exclusive). */
  end: number;
  /** The differing positions contained in this hunk. */
  changes: DiffPosition[];
}

export interface DiffResult {
  changes: DiffPosition[];
  hunks: DiffHunk[];
  /** Fraction of identical positions over the longer sequence (0..1). */
  identity: number;
  lengthA: number;
  lengthB: number;
  /** True when the score deltas are real (both candidates had per-position scores). */
  hasScoreDeltas: boolean;
}

interface ScorePoint {
  position: number;
  score: number;
}

function scoreMap(scores?: ScorePoint[]): Map<number, number> | null {
  if (!scores || scores.length === 0) return null;
  const m = new Map<number, number>();
  for (const s of scores) m.set(s.position, s.score);
  return m;
}

/**
 * Compute the list of differing positions between two sequences.
 * `scoresA`/`scoresB` are optional per-position likelihood arrays; when both
 * are present a real `scoreDelta` (B - A) is attached to substitution rows.
 */
export function computeDiff(
  seqA: string,
  seqB: string,
  scoresA?: ScorePoint[],
  scoresB?: ScorePoint[],
): DiffPosition[] {
  const mapA = scoreMap(scoresA);
  const mapB = scoreMap(scoresB);
  const haveScores = mapA !== null && mapB !== null;

  const minLen = Math.min(seqA.length, seqB.length);
  const out: DiffPosition[] = [];

  for (let i = 0; i < minLen; i++) {
    if (seqA[i] !== seqB[i]) {
      let scoreDelta: number | undefined;
      if (haveScores) {
        const a = mapA!.get(i);
        const b = mapB!.get(i);
        if (a !== undefined && b !== undefined) scoreDelta = b - a;
      }
      out.push({ position: i, ref: seqA[i], alt: seqB[i], kind: "snp", scoreDelta });
    }
  }
  // Length tail → insertions (B longer) or deletions (A longer).
  if (seqB.length > seqA.length) {
    for (let i = minLen; i < seqB.length; i++) {
      out.push({ position: i, ref: "-", alt: seqB[i], kind: "ins" });
    }
  } else if (seqA.length > seqB.length) {
    for (let i = minLen; i < seqA.length; i++) {
      out.push({ position: i, ref: seqA[i], alt: "-", kind: "del" });
    }
  }
  return out;
}

/**
 * Group differing positions into hunks with a few bp of surrounding context,
 * collapsing long unchanged runs. Two changes closer than `2 * context` share
 * a hunk. `maxPos` bounds the context window (typically max sequence length).
 */
export function buildHunks(
  changes: DiffPosition[],
  maxPos: number,
  context = 8,
): DiffHunk[] {
  if (changes.length === 0) return [];
  const hunks: DiffHunk[] = [];
  let current: DiffPosition[] = [changes[0]];

  for (let i = 1; i < changes.length; i++) {
    const prev = changes[i - 1];
    const cur = changes[i];
    if (cur.position - prev.position <= context * 2) {
      current.push(cur);
    } else {
      hunks.push(finishHunk(current, maxPos, context));
      current = [cur];
    }
  }
  hunks.push(finishHunk(current, maxPos, context));
  return hunks;
}

function finishHunk(changes: DiffPosition[], maxPos: number, context: number): DiffHunk {
  const first = changes[0].position;
  const last = changes[changes.length - 1].position;
  return {
    start: Math.max(0, first - context),
    end: Math.min(maxPos, last + context + 1),
    changes,
  };
}

/** Full diff result including hunks and identity fraction. */
export function diffCandidates(
  seqA: string,
  seqB: string,
  scoresA?: ScorePoint[],
  scoresB?: ScorePoint[],
  context = 8,
): DiffResult {
  const changes = computeDiff(seqA, seqB, scoresA, scoresB);
  const maxLen = Math.max(seqA.length, seqB.length);
  const hunks = buildHunks(changes, maxLen, context);
  const identity = maxLen > 0 ? 1 - changes.length / maxLen : 1;
  const hasScoreDeltas = changes.some((c) => c.scoreDelta !== undefined);
  return {
    changes,
    hunks,
    identity,
    lengthA: seqA.length,
    lengthB: seqB.length,
    hasScoreDeltas,
  };
}
