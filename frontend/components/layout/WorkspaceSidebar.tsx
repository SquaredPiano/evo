"use client";

import { memo } from "react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { Dna, Home, HelpCircle, LogOut, Sun, Moon } from "lucide-react";
import EngineStatus from "@/components/ui/EngineStatus";

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
  user: { name: string; email: string } | null;
  onSignIn: () => void;
  theme: string;
  onToggleTheme: () => void;
  onShowTutorial: () => void;
  wsStatus: string;
  navItems: SidebarNavItem[];
}

function WorkspaceSidebar({
  viewMode,
  analysisResult,
  sidebarOpen,
  onNavigate,
  onCloseMobile,
  user,
  onSignIn,
  theme,
  onToggleTheme,
  onShowTutorial,
  wsStatus,
  navItems,
}: WorkspaceSidebarProps) {
  const go = (target: string) => {
    if (analysisResult || target === "structure") onNavigate(target);
    else onNavigate("input");
    onCloseMobile();
  };

  const isHome = viewMode === "input" || viewMode === "pipeline";

  return (
    <aside
      className={`w-[248px] shrink-0 flex flex-col h-full fixed lg:relative z-50 lg:z-auto transition-transform duration-200 lg:translate-x-0 ${
        sidebarOpen ? "translate-x-0" : "-translate-x-full"
      }`}
      style={{
        background: "rgba(255,255,255,0.92)",
        backdropFilter: "blur(12px)",
        borderRight: "1px solid var(--ghost-border)",
      }}
      aria-label="Main navigation"
      role="navigation"
    >
      <div className="px-5 py-7" style={{ borderBottom: "1px solid var(--ghost-border)" }}>
        <Link href="/" className="flex items-center gap-3 group">
          <span
            className="inline-flex items-center justify-center w-9 h-9 rounded-full transition-shadow duration-500"
            style={{
              background: "var(--honey-500)",
              color: "var(--ink)",
              boxShadow: "0 8px 20px -6px rgba(245, 158, 11, 0.45)",
            }}
          >
            <Dna size={18} strokeWidth={2.5} />
          </span>
          <div>
            <span className="text-[15px] font-semibold tracking-tight block" style={{ color: "var(--ink)" }}>
              Evo
            </span>
            <span className="text-[10px] font-medium" style={{ color: "var(--text-faint)" }}>
              Design workspace
            </span>
          </div>
        </Link>
      </div>

      <nav className="flex-1 px-3 py-5 space-y-1" aria-label="Workspace views">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] px-3 mb-3" style={{ color: "var(--text-faint)" }}>
          Navigate
        </p>

        <button
          onClick={() => {
            onNavigate("input");
            onCloseMobile();
          }}
          className="group flex items-center gap-3 w-full px-3.5 py-2.5 rounded-full transition-all duration-300"
          style={{
            background: isHome ? "var(--honey-500)" : "transparent",
            color: isHome ? "var(--ink)" : "var(--text-secondary)",
            boxShadow: isHome ? "0 8px 20px -6px rgba(245, 158, 11, 0.35)" : "none",
          }}
        >
          <Home size={16} strokeWidth={2} style={{ opacity: isHome ? 1 : 0.55 }} />
          <span className="text-[13px] font-medium">Home</span>
        </button>

        {navItems.map(({ icon: Icon, label, viewMode: target }) => {
          const isActive = viewMode === target || (target === "ide" && viewMode === "compare");
          return (
            <button
              key={target}
              onClick={() => go(target)}
              className="group flex items-center gap-3 w-full px-3.5 py-2.5 rounded-full transition-all duration-300 hover:bg-black/[0.03]"
              style={{
                background: isActive ? "var(--honey-500)" : "transparent",
                color: isActive ? "var(--ink)" : "var(--text-secondary)",
                boxShadow: isActive ? "0 8px 20px -6px rgba(245, 158, 11, 0.35)" : "none",
              }}
            >
              <Icon size={16} strokeWidth={2} style={{ opacity: isActive ? 1 : 0.55 }} />
              <span className="text-[13px] font-medium">{label}</span>
            </button>
          );
        })}
      </nav>

      <div className="px-3 py-4 space-y-0.5" style={{ borderTop: "1px solid var(--ghost-border)" }}>
        {user ? (
          <div className="flex items-center gap-3 px-3 py-2 mb-1">
            <div
              className="w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-semibold"
              style={{ background: "var(--honey-100)", color: "var(--honey-700)" }}
            >
              {user.name.charAt(0)}
            </div>
            <div className="min-w-0">
              <span className="text-[12px] font-medium block truncate" style={{ color: "var(--ink)" }}>
                {user.name}
              </span>
              <span className="text-[10px] block truncate" style={{ color: "var(--text-faint)" }}>
                {user.email}
              </span>
            </div>
          </div>
        ) : (
          <button
            onClick={onSignIn}
            className="w-full text-left px-3.5 py-2 text-[12px] font-medium rounded-full hover:bg-black/[0.03]"
            style={{ color: "var(--honey-600)" }}
          >
            Sign in
          </button>
        )}

        <button
          onClick={onShowTutorial}
          className="flex items-center gap-2.5 w-full px-3.5 py-2 rounded-full hover:bg-black/[0.03] transition-colors text-[12px] font-medium"
          style={{ color: "var(--text-muted)" }}
        >
          <HelpCircle size={14} /> Tutorial
        </button>
        <button
          onClick={onToggleTheme}
          className="flex items-center gap-2.5 w-full px-3.5 py-2 rounded-full hover:bg-black/[0.03] transition-colors text-[12px] font-medium"
          style={{ color: "var(--text-muted)" }}
        >
          {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
          {theme === "dark" ? "Light mode" : "Dark mode"}
        </button>
        <Link
          href="/"
          className="flex items-center gap-2.5 w-full px-3.5 py-2 rounded-full hover:bg-black/[0.03] transition-colors text-[12px] font-medium"
          style={{ color: "var(--text-muted)" }}
        >
          <LogOut size={14} /> Exit
        </Link>

        <div className="px-3 pt-2 opacity-80">
          <EngineStatus />
        </div>
        {wsStatus !== "disconnected" && (
          <div className="flex items-center gap-2 px-3.5 pt-1">
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
