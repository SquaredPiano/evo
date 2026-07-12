"use client";

/**
 * ExperimentHistory - exposes the backend version-tracking store that had no
 * UI. Lists every recorded version of the active candidate (each edit, score,
 * and fold) and lets the user revert to an earlier one. Only rendered once a
 * design session exists, since versions are keyed by session id.
 */

import { useCallback, useEffect, useState } from "react";
import { useProteusStore } from "@/lib/store";
import { listExperiments, revertExperiment, type ExperimentVersion } from "@/lib/api";

function formatTime(ts: number | string): string {
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function ExperimentHistory() {
  const sessionId = useProteusStore((s) => s.sessionId);
  const activeCandidateId = useProteusStore((s) => s.activeCandidateId);
  const setEditedSequence = useProteusStore((s) => s.setEditedSequence);
  const editHistory = useProteusStore((s) => s.editHistory);

  const [versions, setVersions] = useState<ExperimentVersion[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await listExperiments(sessionId, activeCandidateId ?? undefined);
      setVersions(res.versions);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load history");
    } finally {
      setBusy(false);
    }
  }, [sessionId, activeCandidateId]);

  // Reload whenever a new local edit lands (edits create backend versions).
  useEffect(() => {
    refresh();
  }, [refresh, editHistory.length]);

  const doRevert = async (v: ExperimentVersion) => {
    if (!sessionId) return;
    setBusy(true);
    setErr(null);
    try {
      await revertExperiment(sessionId, v.version_id);
      if (v.sequence) setEditedSequence(v.sequence);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Revert failed");
    } finally {
      setBusy(false);
    }
  };

  if (!sessionId) return null;

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
          Version history ({versions.length})
        </span>
        <button onClick={refresh} disabled={busy} className="text-[10px] font-medium disabled:opacity-40" style={{ color: "var(--accent)" }}>
          {busy ? "…" : "Refresh"}
        </button>
      </div>
      {err && <div className="text-[11px] mb-2" style={{ color: "var(--base-t)" }}>{err}</div>}
      {versions.length === 0 ? (
        <p className="text-xs" style={{ color: "var(--text-faint)" }}>
          No versions recorded yet. Edits and follow-ups are versioned automatically.
        </p>
      ) : (
        <div className="space-y-1.5 max-h-64 overflow-auto">
          {versions.slice().reverse().map((v, i) => (
            <div
              key={v.version_id}
              className="flex items-center justify-between gap-2 py-1 px-2 rounded"
              style={{ background: i === 0 ? "color-mix(in oklch, var(--accent), transparent 88%)" : "transparent" }}
            >
              <div className="min-w-0">
                <div className="text-[11px] font-medium truncate" style={{ color: "var(--text-secondary)" }}>
                  {v.operation}
                  {i === 0 && <span className="ml-1.5" style={{ color: "var(--accent)" }}>· current</span>}
                </div>
                <div className="text-[10px] font-mono" style={{ color: "var(--text-faint)" }}>
                  {v.sequence.length} bp · {formatTime(v.created_at)}
                </div>
              </div>
              {i !== 0 && (
                <button
                  onClick={() => doRevert(v)}
                  disabled={busy}
                  className="text-[10px] px-2 py-1 rounded shrink-0 disabled:opacity-40"
                  style={{ border: "1px solid var(--ghost-border)", color: "var(--accent)" }}
                >
                  Revert
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
