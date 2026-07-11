"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { normalizeSequence, isValidSequence, gcContent } from "@/lib/sequenceUtils";
import { pushSessionEntry } from "@/lib/sessionHistory";
import { useEvoStore } from "@/lib/store";
import { ArrowRight, Upload, Dna, Sparkles, Clock } from "lucide-react";

interface SequenceInputProps {
  onSubmit: (sequence: string) => void;
  onDesign?: (goal: string) => void;
  isLoading: boolean;
  error: string | null;
}

type InputMode = "design" | "paste";

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
  const fileRef = useRef<HTMLInputElement>(null);
  const composerPrefill = useEvoStore((s) => s.composerPrefill);
  const setComposerPrefill = useEvoStore((s) => s.setComposerPrefill);

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

  const handleFile = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const name = file.name.toLowerCase();
    const isGenBank = name.endsWith(".gb") || name.endsWith(".gbk") || name.endsWith(".genbank");
    if (isGenBank) {
      try {
        const { importSequenceFile } = await import("@/lib/api");
        const res = await importSequenceFile(file);
        if (res.sequences[0]?.sequence) {
          setInput(res.sequences[0].sequence);
          setMode("paste");
          setValidationError(null);
          return;
        }
      } catch {
        setValidationError("Could not parse GenBank file (backend unreachable?)");
      }
    }
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      const cleaned = text
        .split("\n")
        .filter((l) => !l.startsWith(">"))
        .join("");
      setInput(cleaned);
      setMode("paste");
      setValidationError(null);
    };
    reader.readAsText(file);
  }, []);

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

        {onDesign && (
          <div className="flex justify-center mb-5">
            <div className="inline-flex rounded-full p-1" style={{ background: "var(--wax)" }}>
              <button
                type="button"
                onClick={() => {
                  setMode("design");
                  setValidationError(null);
                }}
                className="px-4 py-2 text-[13px] font-medium rounded-full"
                style={{
                  background: mode === "design" ? "var(--ink)" : "transparent",
                  color: mode === "design" ? "var(--cream)" : "var(--text-muted)",
                }}
              >
                Design
              </button>
              <button
                type="button"
                onClick={() => {
                  setMode("paste");
                  setValidationError(null);
                }}
                className="px-4 py-2 text-[13px] font-medium rounded-full"
                style={{
                  background: mode === "paste" ? "var(--ink)" : "transparent",
                  color: mode === "paste" ? "var(--cream)" : "var(--text-muted)",
                }}
              >
                Paste DNA
              </button>
            </div>
          </div>
        )}

        <div
          className="rounded-3xl overflow-hidden mb-4"
          style={{
            background: "#fff",
            border: "1px solid var(--ghost-border)",
            boxShadow: "0 24px 60px -36px rgba(15,15,15,0.35)",
          }}
        >
          {mode === "design" ? (
            <textarea
              value={designGoal}
              onChange={(e) => {
                setDesignGoal(e.target.value);
                setValidationError(null);
              }}
              onKeyDown={handleKeyDown}
              placeholder="Ask Evo to design…"
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
              }}
              onKeyDown={handleKeyDown}
              placeholder={">my_sequence\nATGGCT…"}
              spellCheck={false}
              className="w-full min-h-[132px] px-5 py-4 text-[14px] font-mono resize-none outline-none leading-relaxed"
              style={{ background: "transparent", color: "var(--ink)" }}
            />
          )}

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
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full hover:bg-black/[0.04]"
                  >
                    <Upload size={12} /> Upload
                  </button>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".fasta,.fa,.txt,.gb,.gbk,.genbank"
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
                  <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
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
        </div>

        {(validationError ?? error) && (
          <p className="text-[13px] mb-6 text-center" style={{ color: "#B91C1C" }}>
            {validationError ?? error}
          </p>
        )}

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
      </div>
    </div>
  );
}
