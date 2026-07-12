"use client";

import { useEffect, useRef } from "react";
import { putSession } from "@/lib/api";
import { useEvoStore } from "@/lib/store";

/**
 * Debounced, best-effort autosave of the current session snapshot.
 *
 * Fires a `PUT /api/sessions/{id}` when meaningful state changes (sequence,
 * candidate count, or chat length), keyed by `sessionId`. It is deliberately:
 *  - silent on failure (persistence is additive; Mongo may be disabled),
 *  - a no-op for blank sessions (no sessionId, or no sequence AND no candidates)
 *    so we never present an empty session as saved,
 *  - deduped: identical snapshots within a debounce window are not re-sent.
 *
 * When Mongo is off the PUT still returns 200 (a backend no-op) so this stays
 * harmless; a network failure is swallowed.
 */
export function useSessionAutosave(debounceMs = 1500): void {
  const sessionId = useEvoStore((s) => s.sessionId);
  const rawSequence = useEvoStore((s) => s.rawSequence);
  const candidateCount = useEvoStore((s) => s.candidates.length);
  const chatCount = useEvoStore((s) => s.chatMessages.length);

  const lastSavedKey = useRef<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    // Never autosave a blank session.
    if (rawSequence.length === 0 && candidateCount === 0) return;

    // Signature of the meaningful state; skip if unchanged since last save.
    const key = `${sessionId}:${rawSequence.length}:${candidateCount}:${chatCount}`;
    if (key === lastSavedKey.current) return;

    const timer = setTimeout(() => {
      const snapshot = useEvoStore.getState().snapshotFromStore();
      if (!snapshot.sessionId) return;
      putSession(snapshot)
        .then(() => {
          lastSavedKey.current = key;
        })
        .catch(() => {
          // Best-effort: ignore. A later change retries.
        });
    }, debounceMs);

    return () => clearTimeout(timer);
  }, [sessionId, rawSequence, candidateCount, chatCount, debounceMs]);
}
