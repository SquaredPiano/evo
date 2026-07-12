"use client";

/**
 * SequenceEditor — a real inline DNA editor.
 *
 * Unlike the read-only SequenceViewer, this supports the interactions a
 * biologist expects from an editor:
 *   - Click to place a caret; click-drag to select a range
 *   - Type A/T/C/G to overwrite bases at the caret (advances automatically)
 *   - Backspace / Delete to remove the base or selection
 *   - Arrow keys to move the caret; Shift+Arrows to extend a selection
 *   - A floating toolbar over any selection: copy, reverse-complement, delete,
 *     and "mutate + rescore" for a single base (the < 2s instant path)
 *
 * Local edits (typing, insert, delete) are applied optimistically through
 * `onSequenceChange`. A single-base "mutate + rescore" routes through
 * `onRescoreBase` so it hits the backend instant-rescore contract.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Base, SequenceRegion } from "@/types";

interface SequenceEditorProps {
  sequence: string;
  regions?: SequenceRegion[];
  perPositionScores?: Array<{ position: number; score: number }>;
  onSequenceChange: (next: string) => void;
  onRescoreBase?: (position: number, base: string) => void;
  onSelectPosition?: (position: number | null) => void;
  /** Store playhead. When it changes externally (graph, scrubber, 3D residue
   *  click) the editor moves its caret there and scrolls the base into view. */
  selectedPosition?: number | null;
  /** Sequences longer than this are windowed for rendering performance. */
  maxRender?: number;
}

const BASES_PER_LINE = 60;
const BASES_PER_BLOCK = 10;
const VALID = new Set(["A", "T", "C", "G", "N"]);
const COMPLEMENT: Record<string, string> = { A: "T", T: "A", C: "G", G: "C", N: "N" };

const BASE_COLOR: Record<string, string> = {
  A: "var(--base-a)",
  T: "var(--base-t)",
  C: "var(--base-c)",
  G: "var(--base-g)",
  N: "var(--base-n)",
};

function heatFor(score: number | undefined): string {
  if (typeof score !== "number") return "transparent";
  const normalized = Math.max(0, Math.min(1, (score + 3) / 6));
  if (normalized >= 0.5) {
    const alpha = 0.04 + (normalized - 0.5) * 0.18;
    return `rgba(91, 181, 162, ${alpha.toFixed(3)})`;
  }
  const alpha = 0.04 + (0.5 - normalized) * 0.2;
  return `rgba(212, 122, 122, ${alpha.toFixed(3)})`;
}

function reverseComplement(seq: string): string {
  return seq
    .split("")
    .reverse()
    .map((b) => COMPLEMENT[b] ?? "N")
    .join("");
}

export default function SequenceEditor({
  sequence,
  perPositionScores,
  onSequenceChange,
  onRescoreBase,
  onSelectPosition,
  selectedPosition = null,
  maxRender = 6000,
}: SequenceEditorProps) {
  const [caret, setCaret] = useState(0);
  const [selection, setSelection] = useState<{ anchor: number; focus: number } | null>(null);
  const draggingRef = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const scoreByPos = useMemo(() => {
    const map = new Map<number, number>();
    (perPositionScores ?? []).forEach((s) => map.set(s.position, s.score));
    return map;
  }, [perPositionScores]);

  const len = sequence.length;
  const truncated = len > maxRender;
  const renderLen = truncated ? maxRender : len;

  const selRange = useMemo(() => {
    if (!selection) return null;
    const start = Math.min(selection.anchor, selection.focus);
    const end = Math.max(selection.anchor, selection.focus) + 1;
    return { start, end };
  }, [selection]);

  useEffect(() => {
    if (caret > len) setCaret(len);
  }, [len, caret]);

  // Follow the store playhead when it moves *externally* (LikelihoodGraph,
  // scrubber, 3D residue click). We key off the incoming prop value — not the
  // local caret — so ordinary typing/arrow edits never get yanked backwards.
  const prevSelectedRef = useRef<number | null>(selectedPosition);
  useEffect(() => {
    if (selectedPosition === null) {
      prevSelectedRef.current = null;
      return;
    }
    if (selectedPosition === prevSelectedRef.current) return;
    prevSelectedRef.current = selectedPosition;
    const clamped = Math.max(0, Math.min(len - 1, selectedPosition));
    setCaret(clamped);
    const el = containerRef.current?.querySelector<HTMLElement>(`[data-pos="${clamped}"]`);
    el?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [selectedPosition, len]);

  const emitSelect = useCallback(
    (pos: number | null) => {
      onSelectPosition?.(pos);
    },
    [onSelectPosition]
  );

  // --- Mouse selection ---
  const posFromEvent = (e: React.MouseEvent): number | null => {
    const el = (e.target as HTMLElement).closest("[data-pos]");
    if (!el) return null;
    const pos = Number((el as HTMLElement).dataset.pos);
    return Number.isNaN(pos) ? null : pos;
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    const pos = posFromEvent(e);
    if (pos === null) return;
    draggingRef.current = true;
    setSelection({ anchor: pos, focus: pos });
    setCaret(pos);
    emitSelect(pos);
    containerRef.current?.focus();
  };

  const handleMouseEnter = (e: React.MouseEvent) => {
    if (!draggingRef.current) return;
    const pos = posFromEvent(e);
    if (pos === null) return;
    setSelection((sel) => (sel ? { ...sel, focus: pos } : { anchor: pos, focus: pos }));
    setCaret(pos);
  };

  useEffect(() => {
    const up = () => {
      draggingRef.current = false;
    };
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  // --- Edit operations ---
  const overwriteAt = useCallback(
    (pos: number, base: string) => {
      if (pos < 0 || pos >= sequence.length) return;
      const next = sequence.slice(0, pos) + base + sequence.slice(pos + 1);
      onSequenceChange(next);
    },
    [sequence, onSequenceChange]
  );

  const deleteRange = useCallback(
    (start: number, end: number) => {
      const next = sequence.slice(0, start) + sequence.slice(end);
      onSequenceChange(next);
      setSelection(null);
      setCaret(Math.max(0, start));
      emitSelect(null);
    },
    [sequence, onSequenceChange, emitSelect]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    const key = e.key;
    const upper = key.toUpperCase();

    // Type a base
    if (VALID.has(upper) && key.length === 1) {
      e.preventDefault();
      if (selRange && selRange.end - selRange.start > 1) {
        // Replace whole selection with the typed base
        const next = sequence.slice(0, selRange.start) + upper + sequence.slice(selRange.end);
        onSequenceChange(next);
        setSelection(null);
        setCaret(selRange.start + 1);
        emitSelect(null);
      } else {
        overwriteAt(caret, upper);
        setCaret((c) => Math.min(c + 1, sequence.length - 1));
      }
      return;
    }

    if (key === "Backspace") {
      e.preventDefault();
      if (selRange) deleteRange(selRange.start, selRange.end);
      else if (caret > 0) deleteRange(caret - 1, caret);
      return;
    }
    if (key === "Delete") {
      e.preventDefault();
      if (selRange) deleteRange(selRange.start, selRange.end);
      else if (caret < len) deleteRange(caret, caret + 1);
      return;
    }

    if (key === "ArrowRight" || key === "ArrowLeft") {
      e.preventDefault();
      const delta = key === "ArrowRight" ? 1 : -1;
      const next = Math.max(0, Math.min(len - 1, caret + delta));
      setCaret(next);
      if (e.shiftKey) {
        setSelection((sel) => ({ anchor: sel?.anchor ?? caret, focus: next }));
      } else {
        setSelection(null);
        emitSelect(next);
      }
      return;
    }
    if (key === "ArrowDown" || key === "ArrowUp") {
      e.preventDefault();
      const delta = key === "ArrowDown" ? BASES_PER_LINE : -BASES_PER_LINE;
      const next = Math.max(0, Math.min(len - 1, caret + delta));
      setCaret(next);
      if (e.shiftKey) setSelection((sel) => ({ anchor: sel?.anchor ?? caret, focus: next }));
      else {
        setSelection(null);
        emitSelect(next);
      }
      return;
    }
    if (key === "Escape") {
      setSelection(null);
      emitSelect(null);
    }
  };

  // --- Selection toolbar actions ---
  const selectedText = selRange ? sequence.slice(selRange.start, selRange.end) : "";
  const copySelection = () => {
    if (selectedText && typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(selectedText).catch(() => {});
    }
  };
  const revcompSelection = () => {
    if (!selRange) return;
    const rc = reverseComplement(sequence.slice(selRange.start, selRange.end));
    onSequenceChange(sequence.slice(0, selRange.start) + rc + sequence.slice(selRange.end));
  };
  const mutateAndRescore = () => {
    if (!selRange || selRange.end - selRange.start !== 1 || !onRescoreBase) return;
    const pos = selRange.start;
    const current = sequence[pos];
    // Cycle to the next base so the action always changes something meaningful.
    const cycle: Record<string, string> = { A: "G", G: "A", C: "T", T: "C", N: "A" };
    onRescoreBase(pos, cycle[current] ?? "A");
  };

  // --- Render ---
  const lines: number[] = [];
  for (let i = 0; i < renderLen; i += BASES_PER_LINE) lines.push(i);

  if (len === 0) {
    return (
      <div className="flex items-center justify-center h-full" style={{ color: "var(--text-faint)" }}>
        <span style={{ fontSize: "13px" }}>No sequence loaded</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {selRange && (
        <div
          className="flex items-center gap-2 px-3 py-1.5 rounded-full text-[11px] sticky top-0 z-10"
          style={{ background: "var(--surface-elevated)", color: "var(--text-secondary)" }}
        >
          <span style={{ color: "var(--accent)" }}>
            {selRange.start}–{selRange.end - 1}
          </span>
          <span>({selRange.end - selRange.start} bp selected)</span>
          <div className="flex-1" />
          <button onClick={copySelection} className="px-2 py-0.5 rounded-full hover:bg-white/[0.06]" style={{ color: "var(--text-muted)" }}>
            Copy
          </button>
          <button onClick={revcompSelection} className="px-2 py-0.5 rounded-full hover:bg-white/[0.06]" style={{ color: "var(--text-muted)" }}>
            Rev-comp
          </button>
          {onRescoreBase && selRange.end - selRange.start === 1 && (
            <button onClick={mutateAndRescore} className="px-2 py-0.5 rounded-full" style={{ background: "var(--accent)", color: "var(--ink)" }}>
              Mutate + rescore
            </button>
          )}
          <button onClick={() => deleteRange(selRange.start, selRange.end)} className="px-2 py-0.5 rounded-full hover:bg-white/[0.06]" style={{ color: "var(--base-t)" }}>
            Delete
          </button>
        </div>
      )}

      <div
        ref={containerRef}
        tabIndex={0}
        role="textbox"
        aria-label="Editable DNA sequence"
        aria-multiline="true"
        className="font-mono outline-none focus:ring-1 rounded-sm"
        style={{ fontSize: "13px", lineHeight: "22px" }}
        onKeyDown={handleKeyDown}
        onMouseDown={handleMouseDown}
      >
        {lines.map((lineStart) => {
          const lineBases: number[] = [];
          for (let i = lineStart; i < Math.min(lineStart + BASES_PER_LINE, renderLen); i++) lineBases.push(i);
          return (
            <div key={lineStart} className="flex items-start gap-3" style={{ paddingLeft: 8, paddingRight: 8 }}>
              <span
                className="select-none shrink-0 text-right tabular-nums"
                style={{ width: 48, color: "var(--text-faint)", fontSize: 11, lineHeight: "22px" }}
              >
                {lineStart}
              </span>
              <div className="flex-1 flex flex-wrap">
                {lineBases.map((pos) => {
                  const nt = sequence[pos];
                  const inSel = selRange ? pos >= selRange.start && pos < selRange.end : false;
                  const isCaret = pos === caret && !inSel;
                  const bg = inSel ? "rgba(91,181,162,0.22)" : heatFor(scoreByPos.get(pos));
                  return (
                    <span
                      key={pos}
                      data-pos={pos}
                      onMouseEnter={handleMouseEnter}
                      className="inline-block w-[1ch] text-center cursor-text select-none"
                      style={{
                        marginLeft: pos > lineStart && (pos - lineStart) % BASES_PER_BLOCK === 0 ? 6 : 0,
                        color: BASE_COLOR[nt] ?? "var(--base-n)",
                        backgroundColor: bg,
                        borderLeft: isCaret ? "2px solid var(--accent)" : "2px solid transparent",
                        lineHeight: "22px",
                      }}
                    >
                      {nt}
                    </span>
                  );
                })}
              </div>
            </div>
          );
        })}
        {truncated && (
          <div className="px-3 py-2 text-[11px]" style={{ color: "var(--text-faint)" }}>
            Showing first {maxRender.toLocaleString()} of {len.toLocaleString()} bp. Use natural-language edits in the copilot for whole-sequence operations.
          </div>
        )}
      </div>

      <div className="px-2 text-[10px]" style={{ color: "var(--text-faint)" }}>
        Click to place caret · drag to select · type A/T/C/G to overwrite · Backspace/Delete to remove · Shift+Arrows to extend
      </div>
    </div>
  );
}
