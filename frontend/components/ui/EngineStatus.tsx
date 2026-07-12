"use client";

/**
 * EngineStatus - honest provenance for generation + structure backends.
 */

import { useEffect, useState } from "react";
import { checkHealth } from "@/lib/api";

type Health = {
  status: string;
  model: string;
  inference_mode: string;
  structure_mode?: string;
};

const MODE_LABEL: Record<string, string> = {
  nim_api: "Evo 2 · NIM live",
  local: "Evo 2 · local GPU",
  mock: "Evo 2 · mock (not live)",
};

export default function EngineStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let active = true;
    checkHealth()
      .then((h) => active && setHealth(h as Health))
      .catch(() => active && setUnreachable(true));
    return () => {
      active = false;
    };
  }, []);

  const isLive = health?.inference_mode === "nim_api" || health?.inference_mode === "local";
  const structureLive = health?.structure_mode === "esmfold";
  const color = unreachable
    ? "var(--base-t)"
    : isLive
      ? "var(--accent)"
      : "var(--text-faint)";

  const evoLabel = unreachable
    ? "Backend unreachable"
    : health
      ? MODE_LABEL[health.inference_mode] ?? `Evo 2 · ${health.inference_mode}`
      : "Checking…";

  const foldLabel = unreachable
    ? ""
    : health
      ? structureLive
        ? " · ESMFold live"
        : ` · structure ${health.structure_mode ?? "unknown"}`
      : "";

  return (
    <div className="flex items-center gap-2.5 px-3 pt-2" title={health ? `status: ${health.status}` : undefined}>
      <div className="w-2 h-2 rounded-full" style={{ background: color, boxShadow: isLive ? `0 0 6px ${color}` : "none" }} />
      <span className="label-caps" style={{ fontSize: "9px", color: "var(--text-muted)" }}>
        {evoLabel}{foldLabel}
      </span>
    </div>
  );
}
