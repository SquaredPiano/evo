"use client";

/**
 * EngineStatus — honest, at-a-glance provenance of the inference backend.
 *
 * Rather than a decorative "Ready" pill, this queries /api/health and reports
 * exactly what is powering the pipeline: the real hosted Evo2 model, a local
 * GPU model, or the deterministic mock. Being upfront about real-vs-simulated
 * is a core Evo principle, so the label never overstates what's running.
 */

import { useEffect, useState } from "react";
import { checkHealth } from "@/lib/api";

type Health = { status: string; model: string; inference_mode: string };

const MODE_LABEL: Record<string, string> = {
  nim_api: "Evo 2 · hosted 40B (live)",
  local: "Evo 2 · local GPU (live)",
  mock: "Evo 2 · mock (deterministic)",
};

export default function EngineStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let active = true;
    checkHealth()
      .then((h) => active && setHealth(h))
      .catch(() => active && setUnreachable(true));
    return () => {
      active = false;
    };
  }, []);

  const isLive = health?.inference_mode === "nim_api" || health?.inference_mode === "local";
  const isMock = health?.inference_mode === "mock";
  const color = unreachable
    ? "var(--base-t)"
    : isLive
      ? "var(--accent)"
      : isMock
        ? "var(--annotation-rrna)"
        : "var(--text-faint)";

  const label = unreachable
    ? "Backend unreachable"
    : health
      ? MODE_LABEL[health.inference_mode] ?? `Evo 2 · ${health.inference_mode}`
      : "Checking engine…";

  return (
    <div className="flex items-center gap-2.5 px-3 pt-2" title={health ? `status: ${health.status}` : undefined}>
      <div className="w-2 h-2 rounded-full" style={{ background: color, boxShadow: isLive ? `0 0 6px ${color}` : "none" }} />
      <span className="label-caps" style={{ fontSize: "9px", color: "var(--text-muted)" }}>
        {label}
      </span>
    </div>
  );
}
