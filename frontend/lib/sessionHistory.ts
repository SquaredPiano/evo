/** Shared recent-session history for the workspace sidebar + composer. */

export type SessionKind = "design" | "paste";

export interface SessionEntry {
  id: string;
  kind: SessionKind;
  title: string;
  /** Full design goal or DNA sequence (not truncated). */
  payload: string;
  createdAt: number;
}

export const HISTORY_KEY = "evo.sessionHistory.v1";
export const HISTORY_CHANGED = "evo:session-history-changed";

export function loadSessionHistory(): SessionEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as SessionEntry[];
    if (!Array.isArray(parsed)) return [];
    // Migrate older shape { detail } → payload
    return parsed
      .map((entry) => {
        const anyEntry = entry as SessionEntry & { detail?: string };
        return {
          id: String(anyEntry.id ?? ""),
          kind: (anyEntry.kind === "paste" ? "paste" : "design") as SessionKind,
          title: String(anyEntry.title ?? "Untitled"),
          payload: String(anyEntry.payload ?? anyEntry.detail ?? ""),
          createdAt: Number(anyEntry.createdAt) || Date.now(),
        };
      })
      .filter((e) => e.id && e.payload)
      .slice(0, 40);
  } catch {
    return [];
  }
}

export function saveSessionHistory(entries: SessionEntry[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, 40)));
    window.dispatchEvent(new Event(HISTORY_CHANGED));
  } catch {
    // ignore quota
  }
}

export function pushSessionEntry(entry: Omit<SessionEntry, "id" | "createdAt">): SessionEntry[] {
  const next: SessionEntry = {
    ...entry,
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    createdAt: Date.now(),
  };
  const merged = [next, ...loadSessionHistory().filter((e) => e.payload !== entry.payload)].slice(0, 40);
  saveSessionHistory(merged);
  return merged;
}

export function clearSessionHistory() {
  saveSessionHistory([]);
}
