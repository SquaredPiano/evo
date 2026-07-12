/**
 * Sequence diff helper for CompareView - a lightweight, honest, git-diff-style
 * comparison between two DNA candidate sequences.
 *
 * Semantics mirror the backend primitive `_diff_sequences`
 * (backend/services/experiment_tracker.py): a Needleman-Wunsch global alignment
 * with a linear gap penalty, so an indel shifts coordinates correctly instead
 * of turning every downstream base into a spurious mismatch. The scoring
 * (match +1 / mismatch -1 / gap -2) matches the backend aligner so the two
 * never disagree on candidates of differing length.
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

// Linear alignment scoring. Chosen so a single substitution (one mismatch)
// always beats an insertion+deletion pair (two gaps): mismatch (-1) > 2*gap
// (-4). Matches services/alignment.py so the two diffs never disagree.
const MATCH = 1;
const MISMATCH = -1;
const GAP = -2;

// Guard: skip the O(n*m) alignment for very large inputs and fall back to a
// prefix/tail positional diff, mirroring the backend length guard.
const MAX_ALIGN_CELLS = 4_000_000;

type AlignCol = { a: number; b: number }; // -1 marks a gap on that side

/**
 * Needleman-Wunsch global alignment. Returns the aligned column list where each
 * column carries the 0-based index consumed from A (`a`) and B (`b`); `-1`
 * means a gap on that side.
 */
function alignGlobal(seqA: string, seqB: string): AlignCol[] {
  const n = seqA.length;
  const m = seqB.length;
  // score[i][j] flattened; ptr encodes traceback: 1 diag, 2 up (gap in B), 3 left (gap in A)
  const width = m + 1;
  const score = new Int32Array((n + 1) * width);
  const ptr = new Uint8Array((n + 1) * width);
  for (let i = 1; i <= n; i++) {
    score[i * width] = i * GAP;
    ptr[i * width] = 2;
  }
  for (let j = 1; j <= m; j++) {
    score[j] = j * GAP;
    ptr[j] = 3;
  }
  for (let i = 1; i <= n; i++) {
    const ai = seqA[i - 1];
    const rowBase = i * width;
    const prevBase = (i - 1) * width;
    for (let j = 1; j <= m; j++) {
      const diag =
        score[prevBase + j - 1] + (ai === seqB[j - 1] ? MATCH : MISMATCH);
      const up = score[prevBase + j] + GAP;
      const left = score[rowBase + j - 1] + GAP;
      let best = diag;
      let d = 1;
      if (up > best) {
        best = up;
        d = 2;
      }
      if (left > best) {
        best = left;
        d = 3;
      }
      score[rowBase + j] = best;
      ptr[rowBase + j] = d;
    }
  }
  const cols: AlignCol[] = [];
  let i = n;
  let j = m;
  while (i > 0 || j > 0) {
    const d = ptr[i * width + j];
    if (i > 0 && j > 0 && d === 1) {
      cols.push({ a: i - 1, b: j - 1 });
      i--;
      j--;
    } else if (i > 0 && (j === 0 || d === 2)) {
      cols.push({ a: i - 1, b: -1 });
      i--;
    } else {
      cols.push({ a: -1, b: j - 1 });
      j--;
    }
  }
  cols.reverse();
  return cols;
}

/**
 * Compute the list of differing positions between two sequences (gap-aware).
 * `scoresA`/`scoresB` are optional per-position likelihood arrays; when both
 * are present a real `scoreDelta` (B - A) is attached to substitution rows.
 *
 * Position semantics mirror the backend `_diff_sequences`: substitutions and
 * deletions carry the index in A; insertions carry the index in B.
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

  const out: DiffPosition[] = [];

  // Length guard: fall back to a cheap prefix/tail diff for huge inputs.
  if (seqA.length * seqB.length > MAX_ALIGN_CELLS) {
    return computeDiffPositional(seqA, seqB, mapA, mapB, haveScores);
  }

  const cols = alignGlobal(seqA, seqB);
  for (const col of cols) {
    if (col.a >= 0 && col.b >= 0) {
      if (seqA[col.a] !== seqB[col.b]) {
        let scoreDelta: number | undefined;
        if (haveScores) {
          const a = mapA!.get(col.a);
          const b = mapB!.get(col.b);
          if (a !== undefined && b !== undefined) scoreDelta = b - a;
        }
        out.push({
          position: col.a,
          ref: seqA[col.a],
          alt: seqB[col.b],
          kind: "snp",
          scoreDelta,
        });
      }
    } else if (col.a < 0) {
      // gap in A -> base present in B only -> insertion (indexed in B).
      out.push({ position: col.b, ref: "-", alt: seqB[col.b], kind: "ins" });
    } else {
      // gap in B -> base present in A only -> deletion (indexed in A).
      out.push({ position: col.a, ref: seqA[col.a], alt: "-", kind: "del" });
    }
  }
  return out;
}

/**
 * Prefix/tail positional diff. Fallback for over-long inputs only - NOT
 * gap-aware. Retained so very large sequences still produce a diff without an
 * O(n*m) alignment matrix.
 */
function computeDiffPositional(
  seqA: string,
  seqB: string,
  mapA: Map<number, number> | null,
  mapB: Map<number, number> | null,
  haveScores: boolean,
): DiffPosition[] {
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
