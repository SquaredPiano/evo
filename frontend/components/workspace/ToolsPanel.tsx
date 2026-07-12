"use client";

/**
 * ToolsPanel - surfaces the research-grade backend services that previously
 * had no UI: off-target scanning, codon optimization, ClinVar variant
 * annotation, and FASTA/GenBank export. Each tool operates on the active
 * candidate sequence and reports real results from the backend.
 */

import { useState } from "react";
import { useProteusStore } from "@/lib/store";
import EditingCandidateChrome from "@/components/workspace/EditingCandidateChrome";
import {
  scanOffTargets,
  optimizeCodons,
  annotateVariants,
  runCalibration,
  computeTm,
  computeProteinParams,
  designPrimers,
  foldSecondaryStructure,
  exportFasta,
  exportGenbank,
  downloadText,
  type OffTargetHit,
  type CodonOptimizationResult,
  type VariantAnnotation,
  type CalibrationReport,
  type TmResult,
  type ProteinParamsResult,
  type PrimerDesignResult,
  type SecondaryStructureResult,
} from "@/lib/api";
import {
  clinvarVariationUrl,
  ncbiGeneSearchUrl,
  clinvarGeneUrl,
  pubmedGeneUrl,
} from "@/lib/evidence";
import { ScienceTooltip } from "@/components/ui/ScienceTooltip";

type Tab = "tm" | "primers" | "structure" | "offtarget" | "codon" | "protein" | "variants" | "validate" | "export";

// Standard genetic code (frame-0) for a convenience translation of the current
// DNA into the protein whose parameters we report. Pure, deterministic.
const CODON_TABLE: Record<string, string> = {
  TTT: "F", TTC: "F", TTA: "L", TTG: "L", CTT: "L", CTC: "L", CTA: "L", CTG: "L",
  ATT: "I", ATC: "I", ATA: "I", ATG: "M", GTT: "V", GTC: "V", GTA: "V", GTG: "V",
  TCT: "S", TCC: "S", TCA: "S", TCG: "S", CCT: "P", CCC: "P", CCA: "P", CCG: "P",
  ACT: "T", ACC: "T", ACA: "T", ACG: "T", GCT: "A", GCC: "A", GCA: "A", GCG: "A",
  TAT: "Y", TAC: "Y", TAA: "*", TAG: "*", CAT: "H", CAC: "H", CAA: "Q", CAG: "Q",
  AAT: "N", AAC: "N", AAA: "K", AAG: "K", GAT: "D", GAC: "D", GAA: "E", GAG: "E",
  TGT: "C", TGC: "C", TGA: "*", TGG: "W", CGT: "R", CGC: "R", CGA: "R", CGG: "R",
  AGT: "S", AGC: "S", AGA: "R", AGG: "R", GGT: "G", GGC: "G", GGA: "G", GGG: "G",
};

function translateFrame0(dna: string): string {
  const seq = dna.toUpperCase().replace(/[^ACGT]/g, "");
  let protein = "";
  for (let i = 0; i + 3 <= seq.length; i += 3) {
    const aa = CODON_TABLE[seq.slice(i, i + 3)];
    if (!aa || aa === "*") break;
    protein += aa;
  }
  return protein;
}

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
  const rawSequence = useProteusStore((s) => s.rawSequence);
  const setEditedSequence = useProteusStore((s) => s.setEditedSequence);
  const candidates = useProteusStore((s) => s.candidates);
  const activeCandidateId = useProteusStore((s) => s.activeCandidateId);

  const [tab, setTab] = useState<Tab>("tm");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [tm, setTm] = useState<TmResult | null>(null);
  const [primers, setPrimers] = useState<PrimerDesignResult | null>(null);
  const [structure, setStructure] = useState<SecondaryStructureResult | null>(null);
  const [proteinSeq, setProteinSeq] = useState("");
  const [protein, setProtein] = useState<ProteinParamsResult | null>(null);

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

  const runTm = () => run(async () => {
    setTm(await computeTm(rawSequence));
  });

  const runPrimers = () => run(async () => {
    setPrimers(await designPrimers(rawSequence));
  });

  const runStructure = () => run(async () => {
    setStructure(await foldSecondaryStructure(rawSequence));
  });

  const runProtein = () => run(async () => {
    const seq = (proteinSeq.trim() || translateFrame0(rawSequence)).toUpperCase();
    if (!seq) throw new Error("No protein sequence (paste one or provide a coding DNA).");
    setProtein(await computeProteinParams(seq));
  });

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
    { id: "tm", label: "Tm" },
    { id: "primers", label: "Primers" },
    { id: "structure", label: "Structure (RNA)" },
    { id: "offtarget", label: "Off-target" },
    { id: "codon", label: "Codon opt" },
    { id: "protein", label: "Protein" },
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

      {tab === "tm" && (
        <div className="space-y-2">
          <button onClick={runTm} disabled={busy || !rawSequence} className={btn} style={{ background: "var(--accent)", color: "var(--ink)" }}>
            {busy ? "Computing…" : "Compute Tm"}
          </button>
          {tm && (
            <div className="text-[11px] space-y-1.5" style={{ color: "var(--text-secondary)" }}>
              <div className="flex justify-between">
                <span>Tm (nearest-neighbor)</span>
                <span className="font-mono" style={{ color: "var(--accent)" }}>
                  {tm.tm_nn_celsius == null ? "n/a" : `${tm.tm_nn_celsius.toFixed(1)} °C`}
                </span>
              </div>
              <div className="flex justify-between"><span>Tm (Wallace 2+4)</span><span className="font-mono">{tm.tm_wallace_celsius.toFixed(1)} °C</span></div>
              <div className="flex justify-between"><span>Length / GC</span><span className="font-mono">{tm.length} nt · {(tm.gc_fraction * 100).toFixed(0)}%</span></div>
              {tm.delta_h_kcal != null && tm.delta_s_cal != null && (
                <div className="flex justify-between"><span>ΔH / ΔS</span><span className="font-mono">{tm.delta_h_kcal.toFixed(1)} kcal · {tm.delta_s_cal.toFixed(1)} cal/K</span></div>
              )}
              <div className="pt-1 leading-relaxed" style={{ color: "var(--text-faint)" }}>{tm.note}</div>
            </div>
          )}
          <div className="text-[10px]" style={{ color: "var(--text-faint)" }}>
            Nearest-neighbor Tm (SantaLucia 1998) at 50 mM Na+, 0.25 µM oligo, with a Wallace-rule cross-check.
          </div>
        </div>
      )}

      {tab === "primers" && (
        <div className="space-y-2">
          <button onClick={runPrimers} disabled={busy || !rawSequence} className={btn} style={{ background: "var(--accent)", color: "var(--ink)" }}>
            {busy ? "Designing…" : "Design primers"}
          </button>
          {primers && primers.pairs.length === 0 && (
            <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>
              primer3 returned no acceptable pairs.
              {primers.explain_pair ? <span className="block font-mono text-[10px] mt-1" style={{ color: "var(--text-faint)" }}>{primers.explain_pair}</span> : null}
            </div>
          )}
          {primers && primers.pairs.length > 0 && (
            <div className="text-[11px] space-y-2.5 max-h-72 overflow-auto" style={{ color: "var(--text-secondary)" }}>
              {primers.pairs.map((p, i) => {
                const hairpinTh = Math.max(p.left.hairpin_th, p.right.hairpin_th);
                const dimerTh = Math.max(p.compl_any_th, p.compl_end_th);
                const hairpinWarn = hairpinTh >= 45;
                const dimerWarn = dimerTh >= 45;
                return (
                  <div key={i} className="rounded-xl p-2.5 space-y-1.5" style={{ border: "1px solid var(--ghost-border)", background: "color-mix(in oklch, var(--accent), transparent 96%)" }}>
                    <div className="flex justify-between">
                      <span style={{ color: "var(--accent)" }}>Pair {i + 1}</span>
                      <span className="font-mono">product {p.product_size} bp</span>
                    </div>
                    {([["Forward", p.left], ["Reverse", p.right]] as const).map(([label, pr]) => (
                      <div key={label} className="space-y-0.5">
                        <div className="flex justify-between">
                          <span style={{ color: "var(--text-muted)" }}>{label}</span>
                          <span className="font-mono">{pr.tm_celsius.toFixed(1)} °C · {pr.gc_percent.toFixed(0)}% GC</span>
                        </div>
                        <div className="font-mono text-[10px] break-all" style={{ color: "var(--text-primary)" }}>{pr.sequence}</div>
                      </div>
                    ))}
                    {(hairpinWarn || dimerWarn) && (
                      <div className="text-[10px] leading-relaxed" style={{ color: "var(--base-t)" }}>
                        {hairpinWarn ? `Hairpin structure (Tm ${hairpinTh.toFixed(0)} °C). ` : ""}
                        {dimerWarn ? `Heterodimer (Tm ${dimerTh.toFixed(0)} °C).` : ""}
                      </div>
                    )}
                    {!hairpinWarn && !dimerWarn && (
                      <div className="text-[10px]" style={{ color: "var(--text-faint)" }}>No notable hairpin or dimer (both &lt; 45 °C).</div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          <div className="text-[10px] leading-relaxed" style={{ color: "var(--text-faint)" }}>
            primer3 designs PCR/sequencing primer pairs against the active sequence. Tm, GC%, and product size are primer3 metrics; hairpin/dimer values are primer3 thermodynamic-alignment melting temperatures.
          </div>
        </div>
      )}

      {tab === "structure" && (
        <div className="space-y-2">
          <button onClick={runStructure} disabled={busy || !rawSequence} className={btn} style={{ background: "var(--accent)", color: "var(--ink)" }}>
            {busy ? "Folding…" : "Fold structure"}
          </button>
          {structure && (
            <div className="text-[11px] space-y-1.5" style={{ color: "var(--text-secondary)" }}>
              <div className="flex justify-between">
                <span>MFE (min. free energy)</span>
                <span className="font-mono" style={{ color: "var(--accent)" }}>{structure.mfe_kcal_mol.toFixed(1)} kcal/mol</span>
              </div>
              <div className="flex justify-between"><span>Length / paired</span><span className="font-mono">{structure.length} nt · {(structure.paired_fraction * 100).toFixed(0)}%</span></div>
              <div className="flex justify-between"><span>Hairpins</span><span className="font-mono">{structure.hairpin_count}</span></div>
              <div className="space-y-1 pt-1">
                <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-faint)" }}>Dot-bracket structure</span>
                <div className="rounded-xl p-2 overflow-x-auto" style={{ border: "1px solid var(--ghost-border)", background: "color-mix(in oklch, var(--accent), transparent 96%)" }}>
                  <pre className="font-mono text-[10px] leading-tight m-0" style={{ color: "var(--text-primary)" }}>{structure.sequence}
{structure.dot_bracket}</pre>
                </div>
                <span className="text-[10px] leading-relaxed block" style={{ color: "var(--text-faint)" }}>
                  Dots are unpaired bases; matching parentheses are base pairs.
                </span>
              </div>
              {structure.note && <div className="pt-1 leading-relaxed" style={{ color: "var(--text-faint)" }}>{structure.note}</div>}
            </div>
          )}
          <div className="text-[10px] leading-relaxed" style={{ color: "var(--text-faint)" }}>
            ViennaRNA MFE (RNA.fold) folds an RNA model{structure?.input_was_dna ? "; the DNA input was read as RNA (T treated as U)" : " (T treated as U)"}.
          </div>
        </div>
      )}

      {tab === "protein" && (
        <div className="space-y-2">
          <textarea
            value={proteinSeq}
            onChange={(e) => setProteinSeq(e.target.value)}
            placeholder="Protein sequence (one-letter). Leave blank to translate the current DNA in frame 0."
            rows={3}
            className="w-full text-[11px] px-3 py-2 rounded-xl bg-transparent font-mono resize-none"
            style={{ border: "1px solid var(--ghost-border)", color: "var(--text-primary)" }}
          />
          <button onClick={runProtein} disabled={busy || (!proteinSeq.trim() && !rawSequence)} className={btn} style={{ background: "var(--accent)", color: "var(--ink)" }}>
            {busy ? "Computing…" : "Compute protein params"}
          </button>
          {protein && (
            <div className="text-[11px] space-y-1.5" style={{ color: "var(--text-secondary)" }}>
              <div className="flex justify-between"><span>Length</span><span className="font-mono">{protein.length} aa</span></div>
              <div className="flex justify-between"><span>Molecular weight</span><span className="font-mono">{(protein.molecular_weight / 1000).toFixed(2)} kDa</span></div>
              <div className="flex justify-between"><span>Theoretical pI</span><span className="font-mono" style={{ color: "var(--accent)" }}>{protein.theoretical_pi.toFixed(2)}</span></div>
              <div className="flex justify-between"><span>GRAVY (Kyte-Doolittle)</span><span className="font-mono">{protein.gravy.toFixed(3)}</span></div>
              <div className="flex justify-between"><span>Aromaticity</span><span className="font-mono">{(protein.aromaticity * 100).toFixed(1)}%</span></div>
              <div className="flex justify-between"><span>Charged (+ / −)</span><span className="font-mono">{protein.positively_charged} / {protein.negatively_charged}</span></div>
              {protein.unknown_residues > 0 && (
                <div className="flex justify-between"><span>Non-standard residues</span><span className="font-mono">{protein.unknown_residues}</span></div>
              )}
              <div className="pt-1 leading-relaxed" style={{ color: "var(--text-faint)" }}>{protein.note}</div>
            </div>
          )}
          <div className="text-[10px]" style={{ color: "var(--text-faint)" }}>
            Deterministic ProtParam-style descriptors for the folded protein: MW, pI, GRAVY, aromaticity, composition.
          </div>
        </div>
      )}

      {tab === "offtarget" && (
        <div className="space-y-2">
          <button onClick={runOfftarget} disabled={busy || !rawSequence} className={btn} style={{ background: "var(--accent)", color: "var(--ink)" }}>
            {busy ? "Scanning…" : "Scan for off-targets"}
          </button>
          {offtarget && (
            <div className="text-[11px] space-y-1.5" style={{ color: "var(--text-secondary)" }}>
              <div className="flex justify-between"><span><ScienceTooltip term="repeat-fraction">Repeat fraction</ScienceTooltip></span><span className="font-mono">{(offtarget.repeat_fraction * 100).toFixed(1)}%</span></div>
              <div className="flex justify-between">
                <span><ScienceTooltip term="gc-balance-risk">GC balance risk</ScienceTooltip></span>
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
              <div className="flex justify-between"><span><ScienceTooltip term="cai">CAI</ScienceTooltip></span><span className="font-mono">{codon.original_cai.toFixed(3)} → {codon.optimized_cai.toFixed(3)}</span></div>
              <div className="flex justify-between"><span>GC content</span><span className="font-mono">{(codon.gc_content_before * 100).toFixed(0)}% → {(codon.gc_content_after * 100).toFixed(0)}%</span></div>
              <div className="flex justify-between"><span><ScienceTooltip term="codon">Codons</ScienceTooltip> changed</span><span className="font-mono">{codon.codons_changed}/{codon.total_codons}</span></div>
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
            Scores known pathogenic vs benign ClinVar variants aligned to the current sequence and reports a real AUROC - no claim, a measurement.
          </div>
          {calibration && (
            <div className="text-[11px] space-y-1.5" style={{ color: "var(--text-secondary)" }}>
              <div className="flex justify-between">
                <span><ScienceTooltip term="auroc">AUROC</ScienceTooltip></span>
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
                <div className="flex justify-between"><span>Mean Δ path / benign</span><span className="font-mono">{calibration.mean_delta_pathogenic.toFixed(3)} / {calibration.mean_delta_benign?.toFixed(3) ?? "-"}</span></div>
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
