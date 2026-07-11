"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { Dna, Home, HelpCircle, LogOut, Sun, Moon } from "lucide-react";
import EngineStatus from "@/components/ui/EngineStatus";
import { springTransition } from "@/lib/motion";

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

export default function WorkspaceSidebar({
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
    <motion.aside
      className={`w-[260px] shrink-0 flex flex-col h-full fixed lg:relative z-50 lg:z-auto transition-transform lg:translate-x-0 ${
        sidebarOpen ? "translate-x-0" : "-translate-x-full"
      }`}
      style={{
        background: "var(--rail-bg)",
        color: "var(--rail-text)",
        borderRight: "1px solid var(--rail-border)",
        boxShadow: "20px 0 60px -15px rgba(0,0,0,0.45)",
      }}
      initial={{ x: -260, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ ...springTransition, delay: 0.08 }}
      aria-label="Main navigation"
      role="navigation"
    >
      <div className="px-6 py-8" style={{ borderBottom: "1px solid var(--rail-border)" }}>
        <Link href="/" className="flex items-center gap-3 group">
          <span
            className="inline-flex items-center justify-center w-10 h-10 rounded-2xl transition-shadow duration-500"
            style={{
              background: "var(--honey-500)",
              color: "var(--ink)",
              boxShadow: "0 8px 20px -4px rgba(245, 158, 11, 0.45)",
            }}
          >
            <Dna size={20} strokeWidth={2.5} />
          </span>
          <div>
            <span className="wordmark text-[15px] block text-white">Evo</span>
            <span className="text-[9px] font-bold uppercase tracking-[0.28em]" style={{ color: "var(--rail-muted)" }}>
              Design IDE
            </span>
          </div>
        </Link>
      </div>

      <nav className="flex-1 px-4 py-6 space-y-1.5" aria-label="Workspace views">
        <p className="text-[9px] font-bold uppercase tracking-[0.3em] px-3 mb-4" style={{ color: "var(--rail-muted)" }}>
          Workspace
        </p>

        <button
          onClick={() => {
            onNavigate("input");
            onCloseMobile();
          }}
          className="group flex items-center justify-between w-full px-4 py-3.5 rounded-2xl transition-all duration-500"
          style={{
            background: isHome ? "var(--honey-500)" : "transparent",
            color: isHome ? "var(--ink)" : "var(--rail-muted)",
            boxShadow: isHome ? "0 8px 20px -4px rgba(245, 158, 11, 0.35)" : "none",
          }}
        >
          <div className="flex items-center gap-3">
            <Home size={18} strokeWidth={2} style={{ opacity: isHome ? 1 : 0.55 }} />
            <span className="text-[11px] font-bold uppercase tracking-widest">Home</span>
          </div>
        </button>

        {navItems.map(({ icon: Icon, label, viewMode: target }) => {
          const isActive = viewMode === target || (target === "ide" && viewMode === "compare");
          return (
            <button
              key={target}
              onClick={() => go(target)}
              className="group flex items-center justify-between w-full px-4 py-3.5 rounded-2xl transition-all duration-500 hover:bg-white/5"
              style={{
                background: isActive ? "var(--honey-500)" : "transparent",
                color: isActive ? "var(--ink)" : "var(--rail-muted)",
                boxShadow: isActive ? "0 8px 20px -4px rgba(245, 158, 11, 0.35)" : "none",
              }}
            >
              <div className="flex items-center gap-3">
                <Icon size={18} strokeWidth={2} style={{ opacity: isActive ? 1 : 0.55 }} />
                <span className="text-[11px] font-bold uppercase tracking-widest">{label}</span>
              </div>
            </button>
          );
        })}
      </nav>

      <div className="px-4 py-5 space-y-1" style={{ borderTop: "1px solid var(--rail-border)" }}>
        {user ? (
          <div className="flex items-center gap-3 px-3 py-2 mb-2">
            <div
              className="w-8 h-8 rounded-xl flex items-center justify-center text-[11px] font-bold"
              style={{ background: "rgba(245,158,11,0.15)", color: "var(--honey-400)" }}
            >
              {user.name.charAt(0)}
            </div>
            <div className="min-w-0">
              <span className="text-[12px] font-semibold block truncate text-white">{user.name}</span>
              <span className="text-[10px] block truncate" style={{ color: "var(--rail-muted)" }}>
                {user.email}
              </span>
            </div>
          </div>
        ) : (
          <button
            onClick={onSignIn}
            className="w-full text-left px-3 py-2 text-[11px] font-bold uppercase tracking-wider"
            style={{ color: "var(--honey-400)" }}
          >
            Sign in
          </button>
        )}

        <button
          onClick={onShowTutorial}
          className="flex items-center gap-2.5 w-full px-3 py-2 rounded-xl hover:bg-white/5 transition-colors text-[10px] font-bold uppercase tracking-wider"
          style={{ color: "var(--rail-muted)" }}
        >
          <HelpCircle size={14} /> Tutorial
        </button>
        <button
          onClick={onToggleTheme}
          className="flex items-center gap-2.5 w-full px-3 py-2 rounded-xl hover:bg-white/5 transition-colors text-[10px] font-bold uppercase tracking-wider"
          style={{ color: "var(--rail-muted)" }}
        >
          {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
          {theme === "dark" ? "Light mode" : "Dark mode"}
        </button>
        <Link
          href="/"
          className="flex items-center gap-2.5 w-full px-3 py-2 rounded-xl hover:bg-white/5 transition-colors text-[10px] font-bold uppercase tracking-wider"
          style={{ color: "var(--rail-muted)" }}
        >
          <LogOut size={14} /> Exit
        </Link>

        <div className="px-3 pt-2 opacity-80">
          <EngineStatus />
        </div>
        {wsStatus !== "disconnected" && (
          <div className="flex items-center gap-2 px-3 pt-1">
            <span
              className="w-2 h-2 rounded-full"
              style={{ background: wsStatus === "connected" ? "var(--honey-400)" : "var(--honey-200)" }}
            />
            <span className="text-[9px] font-bold uppercase tracking-wider" style={{ color: "var(--rail-muted)" }}>
              WS · {wsStatus === "connected" ? "Live" : "Connecting"}
            </span>
          </div>
        )}
      </div>
    </motion.aside>
  );
}
