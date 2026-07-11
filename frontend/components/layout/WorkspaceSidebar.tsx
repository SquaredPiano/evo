"use client";

import { memo, useCallback, useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Dna, Home, HelpCircle, Plus, CircleDashed } from "lucide-react";
import EngineStatus from "@/components/ui/EngineStatus";
import {
  clearSessionHistory,
  HISTORY_CHANGED,
  loadSessionHistory,
  type SessionEntry,
} from "@/lib/sessionHistory";

export interface SidebarNavItem {
  icon: LucideIcon;
  label: string;
  viewMode: string;
}

interface WorkspaceSidebarProps {
  viewMode: string;
  analysisResult: unknown;
  sidebarOpen: boolean;
  onNavigate: (view: string) => void;
  onCloseMobile: () => void;
  onShowTutorial: () => void;
  onSelectSession: (session: SessionEntry) => void;
  onNewDesign: () => void;
  wsStatus: string;
  navItems: SidebarNavItem[];
}

function WorkspaceSidebar({
  viewMode,
  analysisResult,
  sidebarOpen,
  onNavigate,
  onCloseMobile,
  onShowTutorial,
  onSelectSession,
  onNewDesign,
  wsStatus,
  navItems,
}: WorkspaceSidebarProps) {
  const [sessions, setSessions] = useState<SessionEntry[]>([]);
  const [showAllSessions, setShowAllSessions] = useState(false);

  const refreshSessions = useCallback(() => {
    setSessions(loadSessionHistory());
  }, []);

  useEffect(() => {
    refreshSessions();
    const onChange = () => refreshSessions();
    window.addEventListener(HISTORY_CHANGED, onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(HISTORY_CHANGED, onChange);
      window.removeEventListener("storage", onChange);
    };
  }, [refreshSessions]);

  const hasWorkspace = Boolean(analysisResult);
  const isHome = viewMode === "input" || viewMode === "pipeline";

  const go = (target: string) => {
    if (target === "input") {
      onNewDesign();
      onCloseMobile();
      return;
    }
    if (!hasWorkspace) {
      // Workspace views need a finished run — send people to compose, don't pretend we navigated.
      onNavigate("input");
      onCloseMobile();
      return;
    }
    onNavigate(target);
    onCloseMobile();
  };

  const visibleSessions = showAllSessions ? sessions : sessions.slice(0, 8);

  return (
    <aside
      className={`w-[248px] shrink-0 flex flex-col h-full fixed lg:relative z-50 lg:z-auto transition-transform duration-200 lg:translate-x-0 ${
        sidebarOpen ? "translate-x-0" : "-translate-x-full"
      }`}
      style={{
        background: "#FFFFFF",
        borderRight: "1px solid var(--ghost-border)",
      }}
      aria-label="Main navigation"
      role="navigation"
    >
      {/* Brand + new design */}
      <div className="px-3 pt-5 pb-3 space-y-3" style={{ borderBottom: "1px solid var(--ghost-border)" }}>
        <button
          type="button"
          onClick={() => {
            onNewDesign();
            onCloseMobile();
          }}
          className="flex items-center gap-2.5 w-full px-2 py-1.5 rounded-xl text-left hover:bg-black/[0.03] transition-colors"
        >
          <span
            className="inline-flex items-center justify-center w-8 h-8 rounded-full shrink-0"
            style={{ background: "var(--honey-500)", color: "var(--ink)" }}
          >
            <Dna size={16} strokeWidth={2.5} />
          </span>
          <div className="min-w-0">
            <span className="text-[14px] font-semibold tracking-tight block" style={{ color: "var(--ink)" }}>
              Evo
            </span>
            <span className="text-[10px] block" style={{ color: "var(--text-faint)" }}>
              Workspace
            </span>
          </div>
        </button>

        <button
          type="button"
          onClick={() => {
            onNewDesign();
            onCloseMobile();
          }}
          className="flex items-center justify-center gap-2 w-full px-3 py-2.5 rounded-xl text-[13px] font-medium transition-colors"
          style={{
            background: "var(--ink)",
            color: "var(--cream)",
          }}
        >
          <Plus size={15} strokeWidth={2.25} />
          New design
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-3">
        {/* Primary nav */}
        <div className="space-y-0.5 mb-5">
          <button
            type="button"
            onClick={() => go("input")}
            className="flex items-center gap-3 w-full px-3 py-2 rounded-xl transition-colors"
            style={{
              background: isHome ? "rgba(0,0,0,0.05)" : "transparent",
              color: isHome ? "var(--ink)" : "var(--text-secondary)",
            }}
          >
            <Home size={16} strokeWidth={2} style={{ opacity: isHome ? 1 : 0.55 }} />
            <span className="text-[13px] font-medium">Home</span>
          </button>

          {navItems.map(({ icon: Icon, label, viewMode: target }) => {
            const isActive = viewMode === target;
            const disabled = !hasWorkspace;
            return (
              <button
                key={target}
                type="button"
                disabled={disabled}
                title={disabled ? "Run a design first" : label}
                onClick={() => go(target)}
                className="flex items-center gap-3 w-full px-3 py-2 rounded-xl transition-colors disabled:opacity-35 disabled:cursor-not-allowed hover:bg-black/[0.03] disabled:hover:bg-transparent"
                style={{
                  background: isActive && !disabled ? "rgba(0,0,0,0.05)" : "transparent",
                  color: isActive && !disabled ? "var(--ink)" : "var(--text-secondary)",
                }}
              >
                <Icon size={16} strokeWidth={2} style={{ opacity: isActive ? 1 : 0.55 }} />
                <span className="text-[13px] font-medium">{label}</span>
              </button>
            );
          })}
        </div>

        {/* Recent sessions — v0-inspired, not a copy */}
        <div className="px-2 mb-2 flex items-center justify-between">
          <p className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-faint)" }}>
            Recent
          </p>
          {sessions.length > 0 && (
            <button
              type="button"
              onClick={() => {
                clearSessionHistory();
                refreshSessions();
              }}
              className="text-[10px] font-medium px-1.5 py-0.5 rounded-md hover:bg-black/[0.04]"
              style={{ color: "var(--text-faint)" }}
            >
              Clear
            </button>
          )}
        </div>

        <div className="space-y-0.5">
          {sessions.length === 0 ? (
            <p className="px-3 py-2 text-[12px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
              Designs you run will show up here.
            </p>
          ) : (
            visibleSessions.map((session) => (
              <button
                key={session.id}
                type="button"
                onClick={() => {
                  onSelectSession(session);
                  onCloseMobile();
                }}
                className="flex items-start gap-2.5 w-full px-3 py-2 rounded-xl text-left transition-colors hover:bg-black/[0.04]"
              >
                <CircleDashed size={14} className="mt-0.5 shrink-0" style={{ color: "var(--text-faint)" }} />
                <span className="min-w-0 flex-1">
                  <span className="block text-[12.5px] font-medium truncate leading-snug" style={{ color: "var(--ink)" }}>
                    {session.title}
                  </span>
                  <span className="block text-[10px] mt-0.5 truncate" style={{ color: "var(--text-faint)" }}>
                    {session.kind === "design" ? "Design" : "Analyze"} ·{" "}
                    {new Date(session.createdAt).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                </span>
              </button>
            ))
          )}

          {sessions.length > 8 && (
            <button
              type="button"
              onClick={() => setShowAllSessions((v) => !v)}
              className="w-full text-left px-3 py-2 text-[12px] font-medium rounded-xl hover:bg-black/[0.04]"
              style={{ color: "var(--text-muted)" }}
            >
              {showAllSessions ? "Show less" : `More (${sessions.length - 8})`}
            </button>
          )}
        </div>
      </div>

      <div className="px-3 py-3 space-y-1" style={{ borderTop: "1px solid var(--ghost-border)" }}>
        <button
          type="button"
          onClick={onShowTutorial}
          className="flex items-center gap-2.5 w-full px-3 py-2 rounded-xl hover:bg-black/[0.03] transition-colors text-[12px] font-medium"
          style={{ color: "var(--text-muted)" }}
        >
          <HelpCircle size={14} /> Tutorial
        </button>
        <div className="px-2 pt-1 opacity-80">
          <EngineStatus />
        </div>
        {wsStatus !== "disconnected" && (
          <div className="flex items-center gap-2 px-3 pt-1">
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: wsStatus === "connected" ? "#16A34A" : "var(--honey-400)" }}
            />
            <span className="text-[10px] font-medium" style={{ color: "var(--text-faint)" }}>
              {wsStatus === "connected" ? "Live" : "Connecting…"}
            </span>
          </div>
        )}
      </div>
    </aside>
  );
}

export default memo(WorkspaceSidebar);
