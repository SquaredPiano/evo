"use client";

import { useEffect, useMemo, useRef, useState } from "react";

interface ProteinViewerProps {
  pdbData?: string;
  highlightResidues?: number[];
  onResidueClick?: (residueSeq: number) => void;
  onResidueHover?: (residueSeq: number | null) => void;
  isFullscreen?: boolean;
  theme?: "dark" | "light";
  structureModel?: string | null;
}

type RenderMode = "cinematic" | "cartoon" | "sticks";

declare global {
  interface Window {
    $3Dmol?: any;
  }
}

let molScriptPromise: Promise<void> | null = null;
const DRAG_THRESHOLD_PX = 6;

function load3DMol(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (window.$3Dmol) return Promise.resolve();
  if (molScriptPromise) return molScriptPromise;

  const scriptSources = [
    "https://cdn.jsdelivr.net/npm/3dmol@2.4.2/build/3Dmol-min.js",
    "https://unpkg.com/3dmol@2.4.2/build/3Dmol-min.js",
    "https://3Dmol.org/build/3Dmol-min.js",
  ];

  molScriptPromise = (async () => {
    let lastError: Error | null = null;
    for (const src of scriptSources) {
      try {
        await new Promise<void>((resolve, reject) => {
          const existing = document.querySelector(`script[src="${src}"]`) as HTMLScriptElement | null;
          if (existing && window.$3Dmol) {
            resolve();
            return;
          }
          const script = existing ?? document.createElement("script");
          script.src = src;
          script.async = true;
          const timeout = window.setTimeout(() => reject(new Error("3Dmol script load timeout")), 7000);
          script.onload = () => {
            window.clearTimeout(timeout);
            resolve();
          };
          script.onerror = () => {
            window.clearTimeout(timeout);
            reject(new Error(`Failed loading ${src}`));
          };
          if (!existing) document.head.appendChild(script);
        });
        if (window.$3Dmol) return;
      } catch (err) {
        lastError = err instanceof Error ? err : new Error(String(err));
      }
    }
    throw lastError ?? new Error("Failed to load 3Dmol");
  })();
  return molScriptPromise;
}

function resolvePlddt(atom: any): number {
  // 3Dmol: occupancy is often on `.b` (~1.0); real B-factor/pLDDT is `.bfactor`.
  const raw = atom?.bfactor ?? atom?.tempfactor ?? atom?.b;
  const n = Number(raw);
  if (!Number.isFinite(n)) return 70;
  // Match backend: values in [0, 1.5] are treated as normalized pLDDT.
  return n <= 1.5 ? n * 100 : n;
}

function confidenceColor(atomOrScore?: any): string {
  const score =
    typeof atomOrScore === "number"
      ? atomOrScore <= 1.5
        ? atomOrScore * 100
        : atomOrScore
      : resolvePlddt(atomOrScore);
  if (score >= 90) return "#5bb5a2";
  if (score >= 70) return "#6b9fd4";
  if (score >= 50) return "#c9a855";
  return "#d47a7a";
}

function applyViewerStyle(viewer: any, mode: RenderMode) {
  if (!viewer) return;
  if (mode === "sticks") {
    viewer.setStyle({}, { stick: { radius: 0.2, colorfunc: (atom: any) => confidenceColor(atom) } });
    return;
  }
  if (mode === "cartoon") {
    viewer.setStyle({}, { cartoon: { colorfunc: (atom: any) => confidenceColor(atom), opacity: 1.0 } });
    return;
  }
  viewer.setStyle(
    {},
    {
      cartoon: { colorfunc: (atom: any) => confidenceColor(atom), opacity: 1.0 },
      stick: { radius: 0.1, opacity: 0.35, colorfunc: (atom: any) => confidenceColor(atom) },
    }
  );
}

function pdbStats(pdbText: string): { atoms: number; residues: number } {
  const residues = new Set<number>();
  let atoms = 0;
  for (const line of pdbText.split("\n")) {
    if (!line.startsWith("ATOM")) continue;
    atoms += 1;
    const resi = Number.parseInt(line.substring(22, 26).trim(), 10);
    if (!Number.isNaN(resi)) residues.add(resi);
  }
  return { atoms, residues: residues.size };
}

export const SAMPLE_PDB = `HEADER    SAMPLE PDB\nTITLE     HELIX SAMPLE\nMODEL     1\nATOM      1  N   MET A   1      12.345  23.456   5.678  1.00 92.30           N\nATOM      2  CA  MET A   1      13.100  24.200   6.100  1.00 93.10           C\nATOM      3  C   MET A   1      14.500  23.800   5.800  1.00 91.50           C\nATOM      4  O   MET A   1      14.800  22.700   5.400  1.00 89.20           O\nATOM      5  CB  MET A   1      12.900  25.700   5.900  1.00 88.70           C\nATOM      6  N   ASP A   2      15.300  24.800   6.000  1.00 90.80           N\nATOM      7  CA  ASP A   2      16.700  24.600   5.700  1.00 91.20           C\nATOM      8  C   ASP A   2      17.400  25.900   5.400  1.00 89.40           C\nATOM      9  O   ASP A   2      16.900  27.000   5.700  1.00 87.80           O\nATOM     10  CB  ASP A   2      17.300  23.600   4.700  1.00 86.40           C\nTER\nENDMDL\nEND`;

export default function ProteinViewer({
  pdbData,
  highlightResidues = [],
  onResidueClick,
  onResidueHover,
  isFullscreen = false,
  theme = "light",
  structureModel = null,
}: ProteinViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<any>(null);
  const clickHandlerRef = useRef(onResidueClick);
  const hoverHandlerRef = useRef(onResidueHover);
  const pointerDownRef = useRef<{ x: number; y: number } | null>(null);
  const draggedRef = useRef(false);
  const lastClickResidueRef = useRef<number | null>(null);
  const lastClickAtRef = useRef(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [renderMode, setRenderMode] = useState<RenderMode>("cartoon");
  const [compatibilityMode, setCompatibilityMode] = useState(false);

  const pdb = pdbData?.trim() ? pdbData : "";
  const stats = useMemo(() => pdbStats(pdb), [pdb]);
  const modelLabel =
    structureModel === "esmfold"
      ? "ESMFold"
      : structureModel === "mock"
        ? "Mock fold"
        : structureModel
          ? structureModel
          : "Structure";

  useEffect(() => {
    clickHandlerRef.current = onResidueClick;
  }, [onResidueClick]);

  useEffect(() => {
    hoverHandlerRef.current = onResidueHover;
  }, [onResidueHover]);

  // Track pointer travel so orbit-drags don't fire residue clicks.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const onDown = (e: PointerEvent) => {
      pointerDownRef.current = { x: e.clientX, y: e.clientY };
      draggedRef.current = false;
    };
    const onMove = (e: PointerEvent) => {
      const start = pointerDownRef.current;
      if (!start) return;
      const dx = e.clientX - start.x;
      const dy = e.clientY - start.y;
      if (Math.hypot(dx, dy) > DRAG_THRESHOLD_PX) draggedRef.current = true;
    };
    const onUp = () => {
      pointerDownRef.current = null;
    };

    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    return () => {
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
    };
  }, [pdb]);

  useEffect(() => {
    const handler = (event: ErrorEvent) => {
      const message = String(event.message || "");
      if (
        message.includes("OffscreenCanvas.transferToImageBitmap") ||
        (message.includes("OffscreenCanvas") && message.includes("ImageBitmap"))
      ) {
        const viewer = viewerRef.current;
        if (viewer && typeof viewer.spin === "function") {
          try {
            viewer.spin(false);
          } catch {
            /* noop */
          }
        }
        setCompatibilityMode(true);
        setLoadError("3D acceleration fallback enabled for this browser/GPU.");
      }
    };
    window.addEventListener("error", handler);
    return () => window.removeEventListener("error", handler);
  }, []);

  useEffect(() => {
    let mounted = true;
    let rafId: number | null = null;
    let retries = 0;

    async function mountViewer() {
      if (!containerRef.current) return;
      if (!pdb) {
        setIsReady(false);
        return;
      }
      setLoadError(null);
      setIsReady(false);

      try {
        await load3DMol();
        if (!mounted || !containerRef.current || !window.$3Dmol) return;

        const rect = containerRef.current.getBoundingClientRect();
        if ((rect.width < 24 || rect.height < 24) && retries < 8) {
          retries += 1;
          rafId = window.requestAnimationFrame(mountViewer);
          return;
        }

        containerRef.current.innerHTML = "";
        const viewer = window.$3Dmol.createViewer(containerRef.current, {
          backgroundColor: theme === "dark" ? "#0F0F0F" : "#FAF9F6",
        });

        viewer.addModel(pdb, "pdb");
        const effectiveMode: RenderMode = compatibilityMode ? "cartoon" : renderMode;
        applyViewerStyle(viewer, effectiveMode);

        viewer.setClickable({}, true, (atom: any) => {
          if (draggedRef.current) return;
          const residue = Number(atom?.resi);
          if (Number.isNaN(residue)) return;
          const now = Date.now();
          if (lastClickResidueRef.current === residue && now - lastClickAtRef.current < 300) {
            return;
          }
          lastClickResidueRef.current = residue;
          lastClickAtRef.current = now;
          clickHandlerRef.current?.(residue);
        });

        viewer.setHoverable(
          {},
          true,
          (atom: any) => {
            if (draggedRef.current) return;
            const residue = Number(atom?.resi);
            if (!Number.isNaN(residue)) hoverHandlerRef.current?.(residue);
          },
          () => {
            if (!draggedRef.current) hoverHandlerRef.current?.(null);
          }
        );

        viewer.zoomTo();
        viewer.zoom(1.12);
        viewer.render();

        viewerRef.current = viewer;
        if (mounted) setIsReady(true);
      } catch (err) {
        if (mounted) {
          setLoadError(err instanceof Error ? err.message : "3D viewer failed to initialize");
        }
      }
    }

    mountViewer();

    return () => {
      mounted = false;
      if (rafId !== null) window.cancelAnimationFrame(rafId);
      if (viewerRef.current && typeof viewerRef.current.spin === "function") {
        viewerRef.current.spin(false);
      }
      viewerRef.current = null;
    };
  }, [compatibilityMode, pdb, renderMode, theme]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;

    const effectiveMode: RenderMode = compatibilityMode ? "cartoon" : renderMode;
    applyViewerStyle(viewer, effectiveMode);

    if (highlightResidues.length > 0) {
      viewer.setStyle(
        { resi: highlightResidues },
        {
          stick: { radius: 0.22, color: theme === "dark" ? "#f8fafc" : "#0F0F0F" },
          sphere: { radius: 0.35, color: "#F59E0B" },
        }
      );
      // Do NOT zoomTo on highlight — that causes camera jumps that feel like phantom clicks.
    }

    viewer.render();
  }, [compatibilityMode, highlightResidues, renderMode, theme]);

  useEffect(() => {
    const onResize = () => {
      const viewer = viewerRef.current;
      if (!viewer) return;
      viewer.resize();
      viewer.render();
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const hudStyle = {
    background: theme === "dark" ? "rgba(15,15,15,0.72)" : "rgba(255,255,255,0.75)",
    color: theme === "dark" ? "#FAF9F6" : "#0F0F0F",
    border: "1px solid var(--ghost-border)",
    backdropFilter: "blur(12px)",
  } as const;

  return (
    <div className="relative w-full h-full select-none">
      <div ref={containerRef} className="absolute inset-0 touch-none" style={{ cursor: "grab" }} />

      {loadError && (
        <div className="absolute inset-0 flex items-center justify-center text-sm pointer-events-none" style={{ color: "var(--base-t)" }}>
          {loadError}
        </div>
      )}

      {!pdb && (
        <div className="absolute inset-0 flex items-center justify-center text-sm pointer-events-none" style={{ color: "var(--text-faint)" }}>
          Waiting for structure data…
        </div>
      )}

      {!isReady && !loadError && pdb && (
        <div className="absolute inset-0 flex items-center justify-center text-sm pointer-events-none" style={{ color: "var(--text-faint)" }}>
          Folding with {modelLabel === "ESMFold" ? "ESMFold" : "structure engine"}…
        </div>
      )}

      {/* HUD — pointer-events none so they never steal orbit/click */}
      <div className="absolute left-4 top-4 rounded-2xl px-3 py-2 text-[11px] font-mono pointer-events-none" style={hudStyle}>
        {stats.residues > 0 ? `${stats.residues} residues · ${stats.atoms} atoms` : "No PDB loaded"}
      </div>

      <div className="absolute right-4 top-4 rounded-2xl px-3 py-2 text-[11px] pointer-events-none" style={hudStyle}>
        {modelLabel}
        {isFullscreen ? " · Fullscreen" : ""}
      </div>

      {compatibilityMode && (
        <div
          className="absolute right-4 top-14 rounded-2xl px-3 py-2 text-[10px] pointer-events-none"
          style={{ ...hudStyle, color: "#B45309" }}
        >
          Compatibility mode
        </div>
      )}

      <div className="absolute right-4 bottom-4 flex flex-col items-end gap-2 z-10 max-w-[min(100%,280px)]">
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          {([
            { id: "cinematic", label: "Cinematic" },
            { id: "cartoon", label: "Cartoon" },
            { id: "sticks", label: "Sticks" },
          ] as const).map((mode) => (
            <button
              key={mode.id}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setRenderMode(mode.id);
              }}
              disabled={compatibilityMode}
              className="px-2.5 py-1.5 rounded-full text-[10px] font-bold uppercase tracking-wider transition-all duration-300"
              style={{
                background: renderMode === mode.id ? "var(--honey-500)" : "rgba(255,255,255,0.75)",
                color: renderMode === mode.id ? "var(--ink)" : "var(--text-muted)",
                border: "1px solid var(--ghost-border)",
                opacity: compatibilityMode ? 0.45 : 1,
                boxShadow: "var(--shadow-soft)",
              }}
            >
              {mode.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
