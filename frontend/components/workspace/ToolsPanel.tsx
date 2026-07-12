"use client";

/**
 * ToolsPanel — surfaces the research-grade backend services that previously
 * had no UI: off-target scanning, codon optimization, ClinVar variant
 * annotation, and FASTA/GenBank export. Each tool operates on the active
 * candidate sequence and reports real results from the backend.
 */

import { useState } from "react";
import { useEvoStore } from "@/lib/store";
import EditingCandidateChrome from "@/components/workspace/EditingCandidateChrome";
import {
  scanOffTargets,
  optimizeCodons,
  annotateVariants,
  runCalibration,
  exportFasta,
  exportGenbank,
  downloadText,
  type OffTargetHit,
  type CodonOptimizationResult,
  type VariantAnnotation,
  type CalibrationReport,
} from "@/lib/api";
import {
  clinvarVariationUrl,
  ncbiGeneSearchUrl,
  clinvarGeneUrl,
  pubmedGeneUrl,
} from "@/lib/evidence";

type Tab = "offtarget" | "codon" | "variants" | "validate" | "export";

const ORGANISMS = [
  { id: "homo_sapiens", label: "Human" },
  { id: "e_coli", label: "E. coli" },
  { id: "yeast", label: "Yeast" },
  { id: "mouse", label: "Mouse" },
  { id: "drosophila", label: "Fruit fly" },
];

const RISK_COLOR: Record<string, string> = {
  high: "var(--base-t)",
  medium: "var(--annotation-rrna)",
  low: "var(--accent)",
};

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--accent)" }}>
      {children}
    </span>
  );
}

export default function ToolsPanel() {
  const rawSequence = useEvoStore((s) => s.rawSequence);
  const setEditedSequence = useEvoStore((s) => s.setEditedSequence);
  const candidates = useEvoStore((s) => s.candidates);
  const activeCandidateId = useEvoStore((s) => s.activeCandidateId);

  const [tab, setTab] = useState<Tab>("offtarget");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [offtarget, setOfftarget] = useState<{ repeat_fraction: number; gc_balance_risk: string; hits: OffTargetHit[] } | null>(null);
  const [organism, setOrganism] = useState("homo_sapiens");
  const [codon, setCodon] = useState<CodonOptimizationResult | null>(null);
  const [gene, setGene] = useState("BRCA1");
  const [variants, setVariants] = useState<VariantAnnotation[] | null>(null);
  const [calGene, setCalGene] = useState("BRCA1");
  const [calibration, setCalibration] = useState<CalibrationReport | null>(null);

  const active = candidates.find((c) => c.id === (activeCandidateId ?? 0)) ?? candidates[0];

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  const runOfftarget = () => run(async () => {
    const res = await scanOffTargets(rawSequence, 12);
    setOfftarget({ repeat_fraction: res.repeat_fraction, gc_balance_risk: res.gc_balance_risk, hits: res.hits });
  });

  const runCodon = () => run(async () => {
    setCodon(await optimizeCodons(rawSequence, organism));
  });

  const runVariants = () => run(async () => {
    const res = await annotateVariants({ gene: gene.trim(), sequence: rawSequence || undefined });
    setVariants(res.annotations);
  });

  const runCalibrate = () => run(async () => {
    setCalibration(await runCalibration({ gene: calGene.trim(), sequence: rawSequence }));
  });

  const doExportFasta = () => run(async () => {
    const header = `evo_candidate_${active?.id ?? 0}`;
    const text = await exportFasta([{ id: header, sequence: rawSequence }]);
    downloadText(`${header}.fasta`, text);
  });

  const doExportGenbank = () => run(async () => {
    const text = await exportGenbank({
      sequence: rawSequence,
      locus: `EVO_${active?.id ?? 0}`,
      scores: active
        ? {
            functional: active.scores.functional,
            tissue_specificity: active.scores.tissue,
            off_target: active.scores.offTarget,
            novelty: active.scores.novelty,
          }
        : undefined,
    });
    downloadText(`evo_candidate_${active?.id ?? 0}.gb`, text);
  });

  const TABS: { id: Tab; label: string }[] = [
    { id: "offtarget", label: "Off-target" },
    { id: "codon", label: "Codon opt" },
    { id: "variants", label: "Variants" },
    { id: "validate", label: "Validate" },
    { id: "export", label: "Export" },
  ];

  const btn = "text-[11px] px-3 py-1.5 rounded-full font-medium transition-colors disabled:opacity-40";

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-2">
        <Label>Research tools</Label>
        <EditingCandidateChrome variant="subline" />
      </div>
      <div className="flex gap-1 mb-3 flex-wrap">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className="text-[10px] px-3 py-1.5 rounded-full transition-colors"
            style={{
              background: tab === t.id ? "color-mix(in oklch, var(--accent), transparent 85%)" : "transparent",
              color: tab === t.id ? "var(--accent)" : "var(--text-muted)",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {err && <div className="text-[11px] mb-2" style={{ color: "var(--base-t)" }}>{err}</div>}

      {tab === "offtarget" && (
        <div className="space-y-2">
          <button onClick={runOfftarget} disabled={busy || !rawSequence} className={btn} style={{ background: "var(--accent)", color: "var(--ink)" }}>
            {busy ? "Scanning…" : "Scan for off-targets"}
          </button>
          {offtarget && (
            <div className="text-[11px] space-y-1.5" style={{ color: "var(--text-secondary)" }}>
              <div className="flex justify-between"><span>Repeat fraction</span><span className="font-mono">{(offtarget.repeat_fraction * 100).toFixed(1)}%</span></div>
              <div className="flex justify-between">
                <span>GC balance risk</span>
                <span className="font-mono capitalize" style={{ color: RISK_COLOR[offtarget.gc_balance_risk] ?? "var(--text-muted)" }}>{offtarget.gc_balance_risk}</span>
              </div>
              <div className="pt-1" style={{ color: "var(--text-muted)" }}>{offtarget.hits.length} hit(s) vs known elements</div>
              {offtarget.hits.slice(0, 6).map((h, i) => (
                <div key={i} className="flex items-center justify-between gap-2 py-0.5">
                  <span className="truncate" title={h.description}>{h.region_name}</span>
                  <span className="font-mono shrink-0" style={{ color: RISK_COLOR[h.risk_level] ?? "var(--text-muted)" }}>
                    {(h.similarity_score * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "codon" && (
        <div className="space-y-2">
          <select
            value={organism}
            onChange={(e) => setOrganism(e.target.value)}
            className="w-full text-[11px] px-3 py-2 rounded-full bg-transparent"
            style={{ border: "1px solid var(--ghost-border)", color: "var(--text-primary)" }}
          >
            {ORGANISMS.map((o) => (
              <option key={o.id} value={o.id} style={{ background: "var(--surface-elevated)" }}>{o.label}</option>
            ))}
          </select>
          <button onClick={runCodon} disabled={busy || !rawSequence} className={btn} style={{ background: "var(--accent)", color: "var(--ink)" }}>
            {busy ? "Optimizing…" : "Optimize codons"}
          </button>
          {codon && (
            <div className="text-[11px] space-y-1.5" style={{ color: "var(--text-secondary)" }}>
              <div className="flex justify-between"><span>CAI</span><span className="font-mono">{codon.original_cai.toFixed(3)} → {codon.optimized_cai.toFixed(3)}</span></div>
              <div className="flex justify-between"><span>GC content</span><span className="font-mono">{(codon.gc_content_before * 100).toFixed(0)}% → {(codon.gc_content_after * 100).toFixed(0)}%</span></div>
              <div className="flex justify-between"><span>Codons changed</span><span className="font-mono">{codon.codons_changed}/{codon.total_codons}</span></div>
              <button
                onClick={() => setEditedSequence(codon.optimized_sequence)}
                className={btn}
                style={{ border: "1px solid var(--ghost-border)", color: "var(--accent)" }}
              >
                Apply optimized sequence
              </button>
            </div>
          )}
        </div>
      )}

      {tab === "variants" && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              value={gene}
              onChange={(e) => setGene(e.target.value)}
              placeholder="Gene symbol (e.g. BRCA1)"
              className="flex-1 text-[11px] px-3 py-2 rounded-full bg-transparent"
              style={{ border: "1px solid var(--ghost-border)", color: "var(--text-primary)" }}
            />
            <button onClick={runVariants} disabled={busy || !gene.trim()} className={btn} style={{ background: "var(--accent)", color: "var(--ink)" }}>
              {busy ? "…" : "Fetch"}
            </button>
          </div>
          <div className="text-[10px]" style={{ color: "var(--text-faint)" }}>Live ClinVar pathogenic variants via NCBI.</div>
          {gene.trim() && (() => {
            const geneQuickLinks = [
              { label: "NCBI Gene", url: ncbiGeneSearchUrl(gene) },
              { label: "ClinVar", url: clinvarGeneUrl(gene) },
              { label: "PubMed", url: pubmedGeneUrl(gene) },
            ].filter((l): l is { label: string; url: string } => l.url != null);
            if (geneQuickLinks.length === 0) return null;
            return (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-faint)" }}>
                  {gene.trim()} →
                </span>
                {geneQuickLinks.map((l) => (
                  <a
                    key={l.label}
                    href={l.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[10px] px-2 py-0.5 rounded-full transition-colors hover:underline"
                    style={{ color: "var(--honey-700)", background: "color-mix(in oklch, var(--accent), transparent 92%)" }}
                  >
                    {l.label}
                  </a>
                ))}
              </div>
            );
          })()}
          {variants && (
            <div className="text-[11px] space-y-1.5 max-h-52 overflow-auto" style={{ color: "var(--text-secondary)" }}>
              {variants.length === 0 && <div style={{ color: "var(--text-muted)" }}>No mapped variants.</div>}
              {variants.slice(0, 10).map((v, i) => {
                const href = clinvarVariationUrl(v.variant_id);
                const hgvs = `${v.ref_base}${v.position}${v.alt_base}`;
                return (
                  <div key={i} className="py-0.5">
                    <div className="flex justify-between gap-2">
                      {href ? (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-mono hover:underline"
                          style={{ color: "var(--honey-700)" }}
                          title={`Open ClinVar variation ${v.variant_id}`}
                        >
                          {hgvs}
                        </a>
                      ) : (
                        <span className="font-mono">{hgvs}</span>
                      )}
                      <span style={{ color: "var(--base-t)" }}>{v.clinical_significance}</span>
                    </div>
                    <div className="truncate" style={{ color: "var(--text-muted)" }} title={v.condition}>{v.condition || v.variant_title}</div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {tab === "validate" && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              value={calGene}
              onChange={(e) => setCalGene(e.target.value)}
              placeholder="Gene (e.g. BRCA1)"
              className="flex-1 text-[11px] px-3 py-2 rounded-full bg-transparent"
              style={{ border: "1px solid var(--ghost-border)", color: "var(--text-primary)" }}
            />
            <button onClick={runCalibrate} disabled={busy || !calGene.trim() || !rawSequence} className={btn} style={{ background: "var(--accent)", color: "var(--ink)" }}>
              {busy ? "…" : "Run"}
            </button>
          </div>
          <div className="text-[10px]" style={{ color: "var(--text-faint)" }}>
            Scores known pathogenic vs benign ClinVar variants aligned to the current sequence and reports a real AUROC — no claim, a measurement.
          </div>
          {calibration && (
            <div className="text-[11px] space-y-1.5" style={{ color: "var(--text-secondary)" }}>
              <div className="flex justify-between">
                <span>AUROC</span>
                <span className="font-mono" style={{ color: calibration.auroc == null ? "var(--text-muted)" : calibration.auroc >= 0.7 ? "var(--accent)" : calibration.auroc >= 0.55 ? "var(--annotation-rrna)" : "var(--base-t)" }}>
                  {calibration.auroc == null ? "n/a" : calibration.auroc.toFixed(3)}
                </span>
              </div>
              <div className="flex justify-between"><span>Engine</span><span className="font-mono">{calibration.engine_mode}</span></div>
              <div className="flex justify-between"><span>Scored (path / benign)</span><span className="font-mono">{calibration.n_pathogenic} / {calibration.n_benign}</span></div>
              {calibration.n_skipped_unaligned > 0 && (
                <div className="flex justify-between"><span>Skipped (unaligned)</span><span className="font-mono">{calibration.n_skipped_unaligned}</span></div>
              )}
              {calibration.mean_delta_pathogenic != null && (
                <div className="flex justify-between"><span>Mean Δ path / benign</span><span className="font-mono">{calibration.mean_delta_pathogenic.toFixed(3)} / {calibration.mean_delta_benign?.toFixed(3) ?? "—"}</span></div>
              )}
              <div className="pt-1 leading-relaxed" style={{ color: "var(--text-faint)" }}>{calibration.note}</div>
            </div>
          )}
        </div>
      )}

      {tab === "export" && (
        <div className="space-y-2">
          <div className="text-[10px]" style={{ color: "var(--text-faint)" }}>Download the active candidate.</div>
          <div className="flex gap-2">
            <button onClick={doExportFasta} disabled={busy || !rawSequence} className={btn} style={{ border: "1px solid var(--ghost-border)", color: "var(--text-primary)" }}>
              FASTA
            </button>
            <button onClick={doExportGenbank} disabled={busy || !rawSequence} className={btn} style={{ border: "1px solid var(--ghost-border)", color: "var(--text-primary)" }}>
              GenBank
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
