"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { normalizeSequence, isValidSequence, gcContent } from "@/lib/sequenceUtils";
import { pushSessionEntry } from "@/lib/sessionHistory";
import { useProteusStore } from "@/lib/store";
import { validatePdbText, MAX_PDB_BYTES } from "@/lib/pdbValidate";
import type { ImportedSequence } from "@/lib/api";
import { ArrowRight, Upload, Dna, Sparkles, Clock, Box } from "lucide-react";

interface SequenceInputProps {
  onSubmit: (sequence: string) => void;
  onDesign?: (goal: string) => void;
  isLoading: boolean;
  error: string | null;
}

type InputMode = "design" | "paste" | "pdb";

const DESIGN_EXAMPLES = [
  {
    name: "BRCA1 coding fragment",
    desc: "Short human tumor-suppressor CDS seed",
    goal: "Design a short human BRCA1 coding sequence fragment for a tumor suppressor research demo",
  },
  {
    name: "BDNF enhancer",
    desc: "Regulatory element for hippocampal expression",
    goal: "Design a BDNF enhancer sequence optimized for high expression in hippocampal neurons",
  },
  {
    name: "Insulin promoter",
    desc: "Pancreatic beta-cell promoter sketch",
    goal: "Design a synthetic insulin promoter for targeted expression in pancreatic beta cells",
  },
];

const PASTE_EXAMPLES = [
  {
    name: "BRCA1 (200 bp)",
    desc: "Human coding-region sample",
    seq: "ATGGATTTATCTGCTCTTCGCGTTGAAGAAGTACAAAATGTCATTAATGCTATGCAGAAAATCTTAGAGTGTCCCATCTGTCTGGAGTTGATCAAGGAACCTGTCTCCACAAAGTGTGACCACATATTTTGCAAATTTTGCATGCTGAAACTTCTCAACCAGAAGAAAGGGCCTTCACAGTGTCCTTTATGTAAGAATGA",
  },
];

export default function SequenceInput({ onSubmit, onDesign, isLoading, error }: SequenceInputProps) {
  const [mode, setMode] = useState<InputMode>(onDesign ? "design" : "paste");
  const [input, setInput] = useState("");
  const [designGoal, setDesignGoal] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importPick, setImportPick] = useState<{
    format: "fasta" | "genbank";
    sequences: ImportedSequence[];
  } | null>(null);
  const [importNote, setImportNote] = useState<string | null>(null);
  const [pdbNote, setPdbNote] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pdbRef = useRef<HTMLInputElement>(null);
  const composerPrefill = useProteusStore((s) => s.composerPrefill);
  const setComposerPrefill = useProteusStore((s) => s.setComposerPrefill);
  const setImportSource = useProteusStore((s) => s.setImportSource);
  const setActivePdb = useProteusStore((s) => s.setActivePdb);
  const setStructureModel = useProteusStore((s) => s.setStructureModel);
  const setViewMode = useProteusStore((s) => s.setViewMode);

  useEffect(() => {
    if (!composerPrefill) return;
    if (composerPrefill.mode === "design") {
      setMode("design");
      setDesignGoal(composerPrefill.value);
      setInput("");
    } else {
      setMode("paste");
      setInput(composerPrefill.value);
      setDesignGoal("");
    }
    setValidationError(null);
    setComposerPrefill(null);
  }, [composerPrefill, setComposerPrefill]);

  const normalized = normalizeSequence(input);
  const charCount = normalized.length;
  const gc = charCount > 0 ? gcContent(normalized) : 0;

  const handlePasteSubmit = useCallback(() => {
    if (charCount === 0) {
      setValidationError("Please enter a DNA sequence");
      return;
    }
    if (!isValidSequence(normalized)) {
      setValidationError("Invalid characters. Use only A, T, C, G, N.");
      return;
    }
    if (charCount < 10) {
      setValidationError("Sequence must be at least 10 nucleotides");
      return;
    }
    setValidationError(null);
    pushSessionEntry({
      kind: "paste",
      title: `Analyze · ${charCount} bp`,
      payload: normalized,
    });
    onSubmit(normalized);
  }, [charCount, normalized, onSubmit]);

  const handleDesignSubmit = useCallback(() => {
    if (!designGoal.trim()) {
      setValidationError("Describe what you want to design");
      return;
    }
    if (designGoal.trim().length < 10) {
      setValidationError("Please provide a more detailed description");
      return;
    }
    setValidationError(null);
    const goal = designGoal.trim();
    pushSessionEntry({
      kind: "design",
      title: goal.length > 64 ? `${goal.slice(0, 64)}…` : goal,
      payload: goal,
    });
    onDesign?.(goal);
  }, [designGoal, onDesign]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        mode === "paste" ? handlePasteSubmit() : handleDesignSubmit();
      }
    },
    [mode, handlePasteSubmit, handleDesignSubmit]
  );

  // Apply one imported record: load its sequence and remember its provenance.
  const applyImported = useCallback(
    (format: "fasta" | "genbank", rec: ImportedSequence) => {
      setInput(rec.sequence);
      setMode("paste");
      setImportPick(null);
      setValidationError(null);
      setImportSource({
        format,
        id: rec.id,
        organism: rec.organism || undefined,
        definition: rec.definition || undefined,
        featureCount: rec.features?.length,
      });
      const bits = [
        `Imported from ${format === "genbank" ? "GenBank" : "FASTA"} · ${rec.id}`,
        rec.organism ? rec.organism : null,
        rec.definition ? rec.definition : null,
        rec.features?.length ? `${rec.features.length} features` : null,
      ].filter(Boolean);
      setImportNote(bits.join(" · "));
    },
    [setImportSource]
  );

  // Route ALL FASTA/GenBank uploads through the backend parser (multi-record +
  // IUPAC aware). No client-side ">"-stripping fallback - on failure we surface
  // the real error instead of mangling the flat file.
  const handleFile = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      setImportNote(null);
      setImporting(true);
      setValidationError(null);
      try {
        const { importSequenceFile } = await import("@/lib/api");
        const res = await importSequenceFile(file);
        const format = res.format === "genbank" ? "genbank" : "fasta";
        const seqs = (res.sequences ?? []).filter((s) => s.sequence);
        if (seqs.length === 0) {
          setValidationError("No sequences found in that file.");
        } else if (seqs.length === 1) {
          applyImported(format, seqs[0]);
        } else {
          // Multi-record: let the user choose which record to load.
          setImportPick({ format, sequences: seqs });
        }
      } catch {
        setValidationError(
          "Could not parse that file. Check it is valid FASTA/GenBank and the backend is reachable."
        );
      } finally {
        setImporting(false);
      }
    },
    [applyImported]
  );

  // Upload a raw PDB/ENT structure file. This is NOT a model prediction - we
  // render it plainly and label it honestly, with no DNA link or fake pLDDT.
  const handlePdbFile = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      setPdbNote(null);
      setValidationError(null);
      if (file.size > MAX_PDB_BYTES) {
        setValidationError("Structure file is too large (max 10 MB).");
        return;
      }
      const text = await file.text();
      const v = validatePdbText(text);
      if (!v.ok) {
        setValidationError(v.error ?? "That does not look like a PDB structure file.");
        return;
      }
      if (v.atomCount < 20 || !v.hasBackbone) {
        setPdbNote(
          `Loaded, but this looks sparse (${v.atomCount} atoms${v.hasBackbone ? "" : ", no full N/CA/C/O backbone"}). Rendering as-is.`
        );
      }
      setActivePdb(text);
      setStructureModel("user_pdb");
      // Uploaded structures are not tied to any imported DNA sequence.
      setImportSource(null);
      setViewMode("structure");
    },
    [setActivePdb, setStructureModel, setImportSource, setViewMode]
  );

  return (
    <div className="flex-1 overflow-auto" style={{ background: "var(--cream)" }}>
      <div className="max-w-2xl mx-auto px-6 md:px-10 py-14 md:py-20">
        <div className="mb-10 text-center">
          <h1
            className="text-[2rem] md:text-[2.5rem] font-semibold tracking-tight mb-3"
            style={{ color: "var(--ink)" }}
          >
            What do you want to design?
          </h1>
          <p className="text-[15px] leading-relaxed max-w-lg mx-auto" style={{ color: "var(--text-muted)" }}>
            Describe a genomic goal, or paste DNA. Recent runs live in the sidebar.
          </p>
        </div>

        <div className="flex justify-center mb-5">
          <div className="inline-flex rounded-full p-1" style={{ background: "var(--wax)" }}>
            {(
              [
                ...(onDesign ? [{ id: "design" as const, label: "Design" }] : []),
                { id: "paste" as const, label: "Paste DNA" },
                { id: "pdb" as const, label: "Structure" },
              ]
            ).map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => {
                  setMode(m.id);
                  setValidationError(null);
                }}
                className="px-4 py-2 text-[13px] font-medium rounded-full"
                style={{
                  background: mode === m.id ? "var(--ink)" : "transparent",
                  color: mode === m.id ? "var(--cream)" : "var(--text-muted)",
                }}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        <div
          className="rounded-3xl overflow-hidden mb-4"
          style={{
            background: "#fff",
            border: "1px solid var(--ghost-border)",
            boxShadow: "0 24px 60px -36px rgba(15,15,15,0.35)",
          }}
        >
          {mode === "pdb" ? (
            <div className="px-6 py-10 text-center">
              <input
                ref={pdbRef}
                type="file"
                accept=".pdb,.ent"
                onChange={handlePdbFile}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => pdbRef.current?.click()}
                className="inline-flex items-center gap-2 px-5 py-3 rounded-2xl text-[14px] font-medium"
                style={{ border: "1px dashed var(--ghost-border)", color: "var(--ink)", background: "rgba(250,249,246,0.85)" }}
              >
                <Box size={16} /> Choose a .pdb / .ent structure file
              </button>
              <p className="text-[12px] leading-relaxed mt-4 max-w-md mx-auto" style={{ color: "var(--text-muted)" }}>
                Renders an existing structure exactly as provided. This is an <strong>uploaded structure</strong> -
                not model-predicted and not linked to a DNA sequence. B-factor colors are not ESMFold pLDDT.
              </p>
              {pdbNote && (
                <p className="text-[12px] mt-3" style={{ color: "#B45309" }}>{pdbNote}</p>
              )}
            </div>
          ) : mode === "design" ? (
            <textarea
              value={designGoal}
              onChange={(e) => {
                setDesignGoal(e.target.value);
                setValidationError(null);
              }}
              onKeyDown={handleKeyDown}
              placeholder="Ask Proteus to design…"
              spellCheck={false}
              className="w-full min-h-[132px] px-5 py-4 text-[15px] resize-none outline-none leading-relaxed"
              style={{ background: "transparent", color: "var(--ink)" }}
            />
          ) : (
            <textarea
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                setValidationError(null);
                setImportNote(null);
              }}
              onKeyDown={handleKeyDown}
              placeholder={">my_sequence\nATGGCT…"}
              spellCheck={false}
              className="w-full min-h-[132px] px-5 py-4 text-[14px] font-mono resize-none outline-none leading-relaxed"
              style={{ background: "transparent", color: "var(--ink)" }}
            />
          )}

          {mode !== "pdb" && (
            <div
              className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
              style={{ borderTop: "1px solid var(--ghost-border)", background: "rgba(250,249,246,0.85)" }}
            >
              <div className="flex items-center gap-3 text-[12px]" style={{ color: "var(--text-muted)" }}>
                {mode === "paste" ? (
                  <>
                    <button
                      type="button"
                      onClick={() => fileRef.current?.click()}
                      disabled={importing}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full hover:bg-black/[0.04] disabled:opacity-50"
                    >
                      <Upload size={12} /> {importing ? "Importing…" : "Upload"}
                    </button>
                    <input
                      ref={fileRef}
                      type="file"
                      accept=".fasta,.fa,.fna,.txt,.gb,.gbk,.genbank"
                      onChange={handleFile}
                      className="hidden"
                    />
                    {charCount > 0 && (
                      <span className="font-mono">
                        {charCount} bp · GC {(gc * 100).toFixed(0)}%
                      </span>
                    )}
                  </>
                ) : (
                  <span className="inline-flex items-center gap-1.5">
                    <Clock size={12} /> ⌘ Enter to run
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={mode === "design" ? handleDesignSubmit : handlePasteSubmit}
                disabled={isLoading || (mode === "design" ? !designGoal.trim() : charCount === 0)}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full text-[13px] font-medium disabled:opacity-45"
                style={{
                  background: "var(--ink)",
                  color: "var(--cream)",
                }}
              >
                {isLoading ? (
                  <>
                    <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin spinner-keep" />
                    Working…
                  </>
                ) : mode === "design" ? (
                  <>
                    <Sparkles size={14} /> Start design
                  </>
                ) : (
                  <>
                    <Dna size={14} /> Analyze
                  </>
                )}
              </button>
            </div>
          )}
        </div>

        {importNote && mode === "paste" && (
          <p className="text-[12px] mb-4 text-center" style={{ color: "var(--text-muted)" }}>
            {importNote}
          </p>
        )}

        {importPick && (
          <div
            className="rounded-2xl overflow-hidden mb-4"
            style={{ border: "1px solid var(--ghost-border)", background: "#fff" }}
          >
            <div className="px-4 py-3 text-[12px] font-medium" style={{ borderBottom: "1px solid var(--ghost-border)", color: "var(--ink)" }}>
              {importPick.sequences.length} records in this {importPick.format === "genbank" ? "GenBank" : "FASTA"} file - pick one
            </div>
            <div className="max-h-[240px] overflow-auto">
              {importPick.sequences.map((rec, i) => (
                <button
                  key={`${rec.id}-${i}`}
                  type="button"
                  onClick={() => applyImported(importPick.format, rec)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-black/[0.03]"
                  style={{ borderTop: i === 0 ? "none" : "1px solid var(--ghost-border)" }}
                >
                  <div className="flex-1 min-w-0">
                    <span className="text-[13px] font-medium block truncate" style={{ color: "var(--ink)" }}>
                      {rec.id}
                    </span>
                    <span className="text-[12px]" style={{ color: "var(--text-muted)" }}>
                      {rec.length} bp{rec.definition ? ` · ${rec.definition}` : ""}
                    </span>
                  </div>
                  <ArrowRight size={14} style={{ color: "var(--text-faint)" }} />
                </button>
              ))}
            </div>
          </div>
        )}

        {(validationError ?? error) && (
          <p className="text-[13px] mb-6 text-center" style={{ color: "#B91C1C" }}>
            {validationError ?? error}
          </p>
        )}

        {mode !== "pdb" && (
        <div className="mt-10">
          <p className="text-[11px] font-semibold uppercase tracking-wider mb-3 text-center" style={{ color: "var(--text-faint)" }}>
            Try one
          </p>
          <div className="grid gap-2">
            {(mode === "design" ? DESIGN_EXAMPLES : PASTE_EXAMPLES).map((ex) => (
              <button
                key={ex.name}
                type="button"
                onClick={() => {
                  if (mode === "design" && "goal" in ex) {
                    setDesignGoal(ex.goal);
                  } else if ("seq" in ex) {
                    setInput(ex.seq);
                  }
                  setValidationError(null);
                }}
                className="flex items-center gap-3 px-4 py-3 rounded-2xl text-left transition-colors hover:bg-white"
                style={{ border: "1px solid var(--ghost-border)", background: "rgba(255,255,255,0.55)" }}
              >
                <div className="flex-1 min-w-0">
                  <span className="text-[13px] font-medium block" style={{ color: "var(--ink)" }}>
                    {ex.name}
                  </span>
                  <span className="text-[12px]" style={{ color: "var(--text-muted)" }}>
                    {ex.desc}
                  </span>
                </div>
                <ArrowRight size={14} style={{ color: "var(--text-faint)" }} />
              </button>
            ))}
          </div>
        </div>
        )}
      </div>
    </div>
  );
}
