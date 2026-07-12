"use client";

/**
 * SequenceScrubber - a draggable playhead over the whole sequence.
 *
 * It scrubs `selectedPosition` (the single source of truth in the store) like a
 * timeline playhead: drag the thumb, click anywhere on the track, or use the
 * arrow keys to move it. Because it drives `selectedPosition`, it stays in
 * lock-step with the SequenceEditor caret, the LikelihoodGraph highlight and
 * the 3D residue highlight - all of which read from / write to the same value.
 *
 * Keyboard (when focused):
 *   ← / →              move by 1
 *   Shift + ← / →      jump by 10
 *   Home / End         first / last base
 */

import { useCallback, useRef } from "react";

interface Props {
  length: number;
  position: number | null;
  onChange: (position: number) => void;
}

export default function SequenceScrubber({ length, position, onChange }: Props) {
  const trackRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  const maxPos = Math.max(0, length - 1);
  const pos = position === null ? 0 : Math.max(0, Math.min(maxPos, position));
  const hasPosition = position !== null;
  const frac = maxPos > 0 ? pos / maxPos : 0;

  const posFromClientX = useCallback(
    (clientX: number): number => {
      const track = trackRef.current;
      if (!track) return pos;
      const rect = track.getBoundingClientRect();
      if (rect.width <= 0) return pos;
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      return Math.round(ratio * maxPos);
    },
    [maxPos, pos],
  );

  const handlePointerDown = (e: React.PointerEvent) => {
    if (length <= 0) return;
    draggingRef.current = true;
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    onChange(posFromClientX(e.clientX));
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!draggingRef.current) return;
    onChange(posFromClientX(e.clientX));
  };

  const endDrag = (e: React.PointerEvent) => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (length <= 0) return;
    let next: number | null = null;
    switch (e.key) {
      case "ArrowLeft":
        next = pos - (e.shiftKey ? 10 : 1);
        break;
      case "ArrowRight":
        next = pos + (e.shiftKey ? 10 : 1);
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = maxPos;
        break;
      default:
        return;
    }
    e.preventDefault();
    onChange(Math.max(0, Math.min(maxPos, next)));
  };

  if (length <= 0) return null;

  return (
    <div className="flex items-center gap-3 select-none">
      <span
        className="shrink-0 text-[10px] font-medium uppercase tracking-wider"
        style={{ color: "var(--text-faint)" }}
      >
        Playhead
      </span>
      <div
        ref={trackRef}
        role="slider"
        tabIndex={0}
        aria-label="Sequence position playhead"
        aria-valuemin={0}
        aria-valuemax={maxPos}
        aria-valuenow={pos}
        aria-valuetext={hasPosition ? `base ${pos}` : "no position selected"}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onKeyDown={handleKeyDown}
        className="relative flex-1 h-6 flex items-center cursor-pointer outline-none focus:ring-1 rounded-full"
        style={{ touchAction: "none" }}
      >
        {/* Track */}
        <div
          className="absolute left-0 right-0 h-1.5 rounded-full"
          style={{ background: "var(--wax)" }}
        />
        {/* Filled portion up to the playhead */}
        <div
          className="absolute left-0 h-1.5 rounded-full"
          style={{
            width: `${frac * 100}%`,
            background: hasPosition ? "var(--accent)" : "transparent",
            opacity: 0.55,
          }}
        />
        {/* Thumb */}
        {hasPosition && (
          <div
            className="absolute w-3 h-3 rounded-full shadow"
            style={{
              left: `calc(${frac * 100}% - 6px)`,
              background: "var(--accent)",
              border: "2px solid var(--surface-raised)",
            }}
          />
        )}
      </div>
      <span
        className="shrink-0 w-24 text-right text-[11px] font-mono tabular-nums"
        style={{ color: hasPosition ? "var(--accent)" : "var(--text-faint)" }}
      >
        {hasPosition ? `${pos} / ${maxPos}` : `– / ${maxPos}`}
      </span>
    </div>
  );
}
