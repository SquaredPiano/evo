"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { RotateCcw, Orbit, Camera, Maximize2, Minimize2, Atom } from "lucide-react";

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

// Performance guards. Heavy per-atom rendering (all side chains) and contact
// analysis (neighbor side chains + hydrogen bonds) are capped by atom count so
// large structures stay at a smooth cartoon + pLDDT baseline.
const SIDECHAIN_ALL_ATOM_LIMIT = 16000;
const DECORATION_ATOM_LIMIT = 40000;
const NEIGHBOR_RADIUS = 5.0;
const NEIGHBOR_RADIUS_SQ = NEIGHBOR_RADIUS * NEIGHBOR_RADIUS;
const MAX_NEIGHBOR_RESIDUES = 32;
const HBOND_MIN_DIST = 2.4;
const HBOND_MAX_DIST = 3.5;
const HBOND_MIN_DIST_SQ = HBOND_MIN_DIST * HBOND_MIN_DIST;
const HBOND_MAX_DIST_SQ = HBOND_MAX_DIST * HBOND_MAX_DIST;
const MAX_HBONDS = 18;

const BACKBONE_ATOMS = ["N", "CA", "C", "O", "OXT"];

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

// AlphaFold / ESMFold standard pLDDT color scale, interpolated for a smooth
// gradient: very low (<50) orange, low (50-70) yellow, confident (70-90) light
// blue, very high (>90) blue. These anchors also drive the legend colorbar so
// the scene and legend read as one scale.
const PLDDT_STOPS: Array<{ v: number; c: [number, number, number] }> = [
  { v: 0, c: [255, 125, 69] }, // #FF7D45 very low
  { v: 50, c: [255, 219, 19] }, // #FFDB13 low
  { v: 70, c: [101, 203, 243] }, // #65CBF3 confident
  { v: 90, c: [0, 83, 214] }, // #0053D6 very high
  { v: 100, c: [0, 83, 214] },
];

function toHex(c: [number, number, number]): string {
  return "#" + c.map((n) => Math.round(n).toString(16).padStart(2, "0")).join("");
}

function plddtColorFromScore(score: number): string {
  const s = Math.max(0, Math.min(100, score));
  for (let i = 0; i < PLDDT_STOPS.length - 1; i++) {
    const a = PLDDT_STOPS[i];
    const b = PLDDT_STOPS[i + 1];
    if (s >= a.v && s <= b.v) {
      const span = b.v - a.v || 1;
      const t = (s - a.v) / span;
      return toHex([
        a.c[0] + (b.c[0] - a.c[0]) * t,
        a.c[1] + (b.c[1] - a.c[1]) * t,
        a.c[2] + (b.c[2] - a.c[2]) * t,
      ]);
    }
  }
  return toHex(PLDDT_STOPS[PLDDT_STOPS.length - 1].c);
}

function confidenceColor(atomOrScore?: any): string {
  const score =
    typeof atomOrScore === "number"
      ? atomOrScore <= 1.5
        ? atomOrScore * 100
        : atomOrScore
      : resolvePlddt(atomOrScore);
  return plddtColorFromScore(score);
}

// CSS gradient (bottom = 0, top = 100) matching PLDDT_STOPS, for the legend.
const PLDDT_LEGEND_GRADIENT =
  "linear-gradient(to top, #FF7D45 0%, #FFDB13 50%, #65CBF3 70%, #0053D6 90%, #0053D6 100%)";

// Flat, honest color for structures whose B-factors are NOT pLDDT confidence
// (e.g. a user-uploaded PDB). Never render these through the pLDDT gradient —
// that would imply model confidence the file does not carry.
const NEUTRAL_COLOR = "#8a94a6";

const HIGHLIGHT_COLOR = "#ff4fa3";
const HBOND_COLOR = "#a5d8ff";

type RenderParams = {
  mode: RenderMode;
  neutral: boolean;
  showAllSidechains: boolean;
  highlightResidues: number[];
  atomCount: number;
  theme: "dark" | "light";
};

function elementOf(atom: any): string {
  const e = (atom?.elem ?? "").toString().trim();
  if (e) return e.toUpperCase();
  const name = (atom?.atom ?? "").toString().trim();
  return name ? name[0].toUpperCase() : "";
}

function isPolar(atom: any): boolean {
  const e = elementOf(atom);
  return e === "N" || e === "O";
}

function dist2(a: any, b: any): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const dz = a.z - b.z;
  return dx * dx + dy * dy + dz * dz;
}

// Full scene render: cartoon + pLDDT base, optional all-atom side chains, and
// selection decorations (ball-and-stick side chains, neighbor context, dashed
// hydrogen-bond contacts, and a residue label). Called on mount and whenever
// the selection or options change. Advanced calls are wrapped so a missing
// 3Dmol API degrades to cartoon + pLDDT rather than crashing.
function renderStructure(viewer: any, params: RenderParams) {
  if (!viewer) return;
  const { mode, neutral, showAllSidechains, highlightResidues, atomCount, theme } = params;

  try {
    viewer.removeAllShapes?.();
    viewer.removeAllLabels?.();
  } catch {
    /* noop */
  }

  const colorfunc = neutral ? () => NEUTRAL_COLOR : (atom: any) => confidenceColor(atom);

  // Base representation.
  try {
    if (mode === "sticks") {
      viewer.setStyle({}, { stick: { radius: 0.18, colorfunc } });
    } else {
      viewer.setStyle(
        {},
        {
          cartoon: { colorfunc, thickness: 0.42, arrows: true, opacity: 1.0 },
        }
      );
      if (mode === "cinematic") {
        viewer.addStyle({}, { stick: { radius: 0.1, opacity: 0.35, colorfunc } });
      }
    }
  } catch {
    // Last-resort minimal style so something always renders.
    try {
      viewer.setStyle({}, { cartoon: { colorfunc } });
    } catch {
      /* noop */
    }
  }

  // Optional: all side chains (element / CPK colored sticks). Guarded by atom count.
  if (showAllSidechains && mode !== "sticks" && atomCount <= SIDECHAIN_ALL_ATOM_LIMIT) {
    try {
      viewer.addStyle(
        { atom: BACKBONE_ATOMS, invert: true },
        { stick: { radius: 0.13 } }
      );
    } catch {
      /* advanced selection unsupported — skip */
    }
  }

  // Selection decorations.
  if (highlightResidues.length > 0) {
    const highlightSet = new Set(highlightResidues);
    let allAtoms: any[] = [];
    try {
      const model = viewer.getModel?.();
      allAtoms = model?.selectedAtoms?.({}) ?? [];
    } catch {
      allAtoms = [];
    }

    const selAtoms = allAtoms.filter((a) => highlightSet.has(Number(a?.resi)));

    // Ball-and-stick on the selected residues (element colors) plus a soft
    // magenta halo + label so the active residue reads clearly, matching the
    // reference "A | ARG 177" HUD.
    for (const resi of highlightResidues) {
      const residueAtoms = selAtoms.filter((a) => Number(a?.resi) === resi);
      try {
        viewer.addStyle(
          { resi },
          { stick: { radius: 0.2 }, sphere: { scale: 0.28 } }
        );
        viewer.addStyle({ resi }, { sphere: { scale: 0.55, color: HIGHLIGHT_COLOR, opacity: 0.16 } });
      } catch {
        /* noop */
      }

      if (residueAtoms.length > 0) {
        const anchor =
          residueAtoms.find((a) => (a?.atom ?? "").toString().trim() === "CA") ?? residueAtoms[0];
        const resn = (anchor?.resn ?? "").toString().trim() || "RES";
        const chain = (anchor?.chain ?? "").toString().trim() || "?";
        try {
          viewer.addLabel(`${chain} | ${resn} ${resi}`, {
            position: { x: anchor.x, y: anchor.y, z: anchor.z },
            backgroundColor: theme === "dark" ? "rgba(8,10,16,0.86)" : "rgba(15,15,15,0.82)",
            backgroundOpacity: 0.86,
            fontColor: "#ffffff",
            fontSize: 12,
            borderColor: HIGHLIGHT_COLOR,
            borderThickness: 1.4,
            inFront: true,
            alignment: "bottomCenter",
          });
        } catch {
          /* labels unsupported — skip */
        }
      }
    }

    // Contacts (neighbor side chains + dashed hydrogen bonds) only when the
    // structure is small enough to analyze cheaply.
    if (allAtoms.length > 0 && allAtoms.length <= DECORATION_ATOM_LIMIT && selAtoms.length > 0) {
      // Neighbor residues within NEIGHBOR_RADIUS of any selected atom.
      const neighborResis = new Set<number>();
      for (const a of allAtoms) {
        const r = Number(a?.resi);
        if (highlightSet.has(r) || neighborResis.has(r)) continue;
        for (const s of selAtoms) {
          if (dist2(a, s) <= NEIGHBOR_RADIUS_SQ) {
            neighborResis.add(r);
            break;
          }
        }
        if (neighborResis.size >= MAX_NEIGHBOR_RESIDUES) break;
      }
      if (neighborResis.size > 0) {
        try {
          viewer.addStyle({ resi: Array.from(neighborResis) }, { stick: { radius: 0.11 } });
        } catch {
          /* noop */
        }
      }

      // Approximate hydrogen bonds: N/O of a selected residue within ~3.5A of
      // an N/O on a different residue. Dashed cylinder (or dashed line fallback).
      const selPolar = selAtoms.filter(isPolar);
      const allPolar = allAtoms.filter(isPolar);
      let drawn = 0;
      const seen = new Set<string>();
      for (const p of selPolar) {
        if (drawn >= MAX_HBONDS) break;
        for (const q of allPolar) {
          if (drawn >= MAX_HBONDS) break;
          if (Number(p?.resi) === Number(q?.resi)) continue;
          const d = dist2(p, q);
          if (d < HBOND_MIN_DIST_SQ || d > HBOND_MAX_DIST_SQ) continue;
          const pk = String(p?.serial ?? `${p.x},${p.y},${p.z}`);
          const qk = String(q?.serial ?? `${q.x},${q.y},${q.z}`);
          const key = pk < qk ? `${pk}-${qk}` : `${qk}-${pk}`;
          if (seen.has(key)) continue;
          seen.add(key);
          const start = { x: p.x, y: p.y, z: p.z };
          const end = { x: q.x, y: q.y, z: q.z };
          try {
            viewer.addCylinder({
              start,
              end,
              radius: 0.032,
              dashed: true,
              dashLength: 0.28,
              gapLength: 0.22,
              fromCap: 1,
              toCap: 1,
              color: HBOND_COLOR,
            });
          } catch {
            try {
              viewer.addLine({ start, end, dashed: true, color: HBOND_COLOR });
            } catch {
              /* contacts unsupported — skip */
            }
          }
          drawn += 1;
        }
      }
    }
  }

  try {
    viewer.render();
  } catch {
    /* noop */
  }
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

export default function ProteinViewer({
  pdbData,
  highlightResidues = [],
  onResidueClick,
  onResidueHover,
  isFullscreen = false,
  theme = "light",
  structureModel = null,
}: ProteinViewerProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
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
  const [spinning, setSpinning] = useState(false);
  const [showAllSidechains, setShowAllSidechains] = useState(false);
  const [nativeFullscreen, setNativeFullscreen] = useState(false);

  const pdb = pdbData?.trim() ? pdbData : "";
  const stats = useMemo(() => pdbStats(pdb), [pdb]);
  const isUserPdb = structureModel === "user_pdb";
  const inFullscreen = isFullscreen || nativeFullscreen;
  const sceneBg = inFullscreen
    ? "#06080C"
    : theme === "dark"
      ? "#0B0E14"
      : "#F4F2EC";
  const canShowAllSidechains = stats.atoms > 0 && stats.atoms <= SIDECHAIN_ALL_ATOM_LIMIT;

  const modelLabel =
    structureModel === "esmfold"
      ? "ESMFold"
      : isUserPdb
        ? "Uploaded"
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

  // Reflect native (browser) fullscreen state so the icon + background follow.
  useEffect(() => {
    const onChange = () => {
      const active = document.fullscreenElement === wrapperRef.current;
      setNativeFullscreen(active);
      const viewer = viewerRef.current;
      if (viewer) {
        window.setTimeout(() => {
          try {
            viewer.resize();
            viewer.render();
          } catch {
            /* noop */
          }
        }, 60);
      }
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

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
        setSpinning(false);
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
          backgroundColor: sceneBg,
          antialias: true,
        });

        // Subtle depth outline for a defined, structural-biology look. Degrades
        // silently on builds that lack the API.
        try {
          viewer.setViewStyle?.({ style: "outline", width: 0.04, color: "#04060a" });
        } catch {
          /* noop */
        }

        viewer.addModel(pdb, "pdb");
        const effectiveMode: RenderMode = compatibilityMode ? "cartoon" : renderMode;
        renderStructure(viewer, {
          mode: effectiveMode,
          neutral: isUserPdb,
          showAllSidechains: showAllSidechains && canShowAllSidechains,
          highlightResidues,
          atomCount: stats.atoms,
          theme,
        });

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
        try {
          viewerRef.current.spin(false);
        } catch {
          /* noop */
        }
      }
      viewerRef.current = null;
    };
    // Selection / option changes are handled by the lighter update effect below,
    // so they are intentionally excluded here to avoid full remounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compatibilityMode, pdb, theme, isUserPdb]);

  // Keep the scene background in sync with fullscreen without a remount.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    try {
      viewer.setBackgroundColor?.(sceneBg);
      viewer.render();
    } catch {
      /* noop */
    }
  }, [sceneBg]);

  // Re-render representation + decorations when the selection or options change.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const effectiveMode: RenderMode = compatibilityMode ? "cartoon" : renderMode;
    renderStructure(viewer, {
      mode: effectiveMode,
      neutral: isUserPdb,
      showAllSidechains: showAllSidechains && canShowAllSidechains,
      highlightResidues,
      atomCount: stats.atoms,
      theme,
    });
    // Do NOT zoomTo on selection change — that causes camera jumps that feel
    // like phantom clicks.
  }, [
    compatibilityMode,
    renderMode,
    showAllSidechains,
    canShowAllSidechains,
    highlightResidues,
    isUserPdb,
    stats.atoms,
    theme,
    isReady,
  ]);

  useEffect(() => {
    const onResize = () => {
      const viewer = viewerRef.current;
      if (!viewer) return;
      try {
        viewer.resize();
        viewer.render();
      } catch {
        /* noop */
      }
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const handleReset = () => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    try {
      viewer.zoomTo();
      viewer.zoom(1.12);
      viewer.render();
    } catch {
      /* noop */
    }
  };

  const handleToggleSpin = () => {
    const viewer = viewerRef.current;
    if (!viewer || compatibilityMode) return;
    const next = !spinning;
    setSpinning(next);
    try {
      viewer.spin(next ? "y" : false, next ? 1 : 0);
    } catch {
      setSpinning(false);
    }
  };

  const handleScreenshot = () => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    try {
      viewer.render();
      const uri: string | undefined = viewer.pngURI?.();
      if (!uri) return;
      const link = document.createElement("a");
      link.href = uri;
      link.download = `${modelLabel.toLowerCase().replace(/\s+/g, "-")}-structure.png`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch {
      /* noop */
    }
  };

  const handleToggleFullscreen = () => {
    const el = wrapperRef.current;
    if (!el) return;
    try {
      if (document.fullscreenElement === el) {
        document.exitFullscreen?.();
      } else {
        el.requestFullscreen?.();
      }
    } catch {
      /* noop */
    }
  };

  const hudStyle = {
    background: inFullscreen || theme === "dark" ? "rgba(10,12,18,0.66)" : "rgba(255,255,255,0.75)",
    color: inFullscreen || theme === "dark" ? "#FAF9F6" : "#0F0F0F",
    border: "1px solid rgba(255,255,255,0.10)",
    backdropFilter: "blur(12px)",
  } as const;

  const controlButtonStyle = {
    background: "rgba(12,14,20,0.62)",
    color: "#EDEDED",
    border: "1px solid rgba(255,255,255,0.12)",
    backdropFilter: "blur(10px)",
  } as const;

  const showLegend = pdb && isReady && !isUserPdb;

  return (
    <div
      ref={wrapperRef}
      className="relative w-full h-full select-none overflow-hidden"
      style={{ background: sceneBg }}
    >
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

      {/* Floating action controls — side chains, spin, reset, screenshot, fullscreen */}
      <div className="absolute right-4 top-4 flex items-center gap-1.5 z-20">
        <span className="mr-1 rounded-2xl px-3 py-2 text-[11px] pointer-events-none" style={hudStyle}>
          {modelLabel}
        </span>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setShowAllSidechains((v) => !v);
          }}
          disabled={!canShowAllSidechains}
          title={canShowAllSidechains ? "Toggle all side chains" : "Structure too large for all side chains"}
          className="w-8 h-8 rounded-full flex items-center justify-center transition-all"
          style={{
            ...controlButtonStyle,
            background: showAllSidechains ? "var(--honey-500)" : controlButtonStyle.background,
            color: showAllSidechains ? "#0F0F0F" : controlButtonStyle.color,
            opacity: canShowAllSidechains ? 1 : 0.4,
          }}
        >
          <Atom size={14} />
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            handleToggleSpin();
          }}
          disabled={compatibilityMode}
          title="Toggle auto-rotate"
          className="w-8 h-8 rounded-full flex items-center justify-center transition-all"
          style={{
            ...controlButtonStyle,
            background: spinning ? "var(--honey-500)" : controlButtonStyle.background,
            color: spinning ? "#0F0F0F" : controlButtonStyle.color,
            opacity: compatibilityMode ? 0.4 : 1,
          }}
        >
          <Orbit size={14} />
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            handleReset();
          }}
          title="Reset view"
          className="w-8 h-8 rounded-full flex items-center justify-center transition-all"
          style={controlButtonStyle}
        >
          <RotateCcw size={14} />
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            handleScreenshot();
          }}
          title="Save PNG screenshot"
          className="w-8 h-8 rounded-full flex items-center justify-center transition-all"
          style={controlButtonStyle}
        >
          <Camera size={14} />
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            handleToggleFullscreen();
          }}
          title={nativeFullscreen ? "Exit fullscreen" : "Fullscreen"}
          className="w-8 h-8 rounded-full flex items-center justify-center transition-all"
          style={controlButtonStyle}
        >
          {nativeFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
      </div>

      {compatibilityMode && (
        <div
          className="absolute right-4 top-14 rounded-2xl px-3 py-2 text-[10px] pointer-events-none z-10"
          style={{ ...hudStyle, color: "#F59E0B" }}
        >
          Compatibility mode
        </div>
      )}

      {/* Vertical pLDDT color scale — the model confidence legend. Hidden for
          uploaded PDBs whose B-factors are not pLDDT. */}
      {showLegend && (
        <div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-stretch gap-2 pointer-events-none z-10">
          <div className="flex flex-col justify-between py-0.5 text-[9px] font-mono text-right" style={{ color: "#E5E7EB" }}>
            <span>100</span>
            <span>90</span>
            <span>70</span>
            <span>50</span>
            <span>0</span>
          </div>
          <div className="flex flex-col items-center gap-1.5">
            <div
              className="w-2.5 rounded-full"
              style={{
                height: 168,
                background: PLDDT_LEGEND_GRADIENT,
                border: "1px solid rgba(255,255,255,0.18)",
                boxShadow: "0 1px 6px rgba(0,0,0,0.35)",
              }}
            />
          </div>
          <div className="flex items-center">
            <span
              className="text-[9px] font-medium uppercase tracking-wider whitespace-nowrap"
              style={{ color: "#E5E7EB", writingMode: "vertical-rl", transform: "rotate(180deg)" }}
            >
              Prediction Score (pLDDT)
            </span>
          </div>
        </div>
      )}

      {/* Representation selector — subtle segmented control */}
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
                background: renderMode === mode.id ? "var(--honey-500)" : "rgba(12,14,20,0.62)",
                color: renderMode === mode.id ? "#0F0F0F" : "#EDEDED",
                border: "1px solid rgba(255,255,255,0.12)",
                backdropFilter: "blur(10px)",
                opacity: compatibilityMode ? 0.45 : 1,
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
