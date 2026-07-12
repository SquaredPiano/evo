"use client";

/**
 * RelatedWorkPanel - two clearly-separated zones so a judge can tell what Evo is
 * built on from what it fetched for THIS run:
 *
 *   Zone 1 "Foundational"  - static, always shown (badge: not run-specific).
 *   Zone 2 "For this run"   - live NCBI/PubMed/ClinVar records, split by role
 *                             (NCBI seeds the DNA; PubMed + ClinVar are context).
 *
 * Honesty is the point: context literature never rewrites the generated DNA.
 */

import { useEvoStore } from "@/lib/store";
import { buildEvidenceLinks } from "@/lib/evidence";
import { FOUNDATIONAL_WORK, partitionRunLiterature } from "@/lib/relatedWork";

function Badge({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "accent" }) {
  return (
    <span
      className="text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded-full whitespace-nowrap"
      style={{
        color: tone === "accent" ? "var(--accent)" : "var(--text-faint)",
        background:
          tone === "accent"
            ? "color-mix(in oklch, var(--accent), transparent 88%)"
            : "color-mix(in oklch, var(--text-faint), transparent 88%)",
      }}
    >
      {children}
    </span>
  );
}

function LinkRow({ label, sublabel, url, source }: { label: string; sublabel?: string; url: string; source?: string }) {
  return (
    <li>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="block group"
      >
        <span className="text-[12px] leading-snug group-hover:underline" style={{ color: "var(--honey-700)" }}>
          {source && (
            <span className="uppercase text-[9px] font-bold tracking-wider mr-1.5" style={{ color: "var(--text-faint)" }}>
              {source}
            </span>
          )}
          {label}
        </span>
        {sublabel && (
          <span className="block text-[10px] mt-0.5" style={{ color: "var(--text-faint)" }}>
            {sublabel}
          </span>
        )}
      </a>
    </li>
  );
}

export default function RelatedWorkPanel({ compact = false }: { compact?: boolean }) {
  const retrievalStatuses = useEvoStore((s) => s.retrievalStatuses);

  const evidenceMap = Object.fromEntries(
    retrievalStatuses.filter((r) => r.status === "complete" && r.result).map((r) => [r.source, r.result]),
  );
  const { seed, context } = partitionRunLiterature(buildEvidenceLinks(evidenceMap));
  const hasRun = seed.length > 0 || context.length > 0;

  return (
    <div className="space-y-5">
      {/* ── Zone 1: Foundational ─────────────────────────────────────── */}
      <section>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--accent)" }}>
            Foundational
          </span>
          <Badge>not run-specific</Badge>
        </div>
        <p className="text-[11px] mb-3 leading-relaxed" style={{ color: "var(--text-muted)" }}>
          The models and resources Evo is built on. Same for every design.
        </p>
        <ul className={compact ? "space-y-2.5" : "grid sm:grid-cols-2 gap-3"}>
          {FOUNDATIONAL_WORK.map((ref) => (
            <li key={ref.id}>
              <a href={ref.url} target="_blank" rel="noopener noreferrer" className="block group">
                <span className="text-[12px] font-medium leading-snug group-hover:underline block" style={{ color: "var(--honey-700)" }}>
                  {ref.title}
                </span>
              </a>
              <span className="block text-[10px] mt-0.5" style={{ color: "var(--text-faint)" }}>
                {ref.authorsShort} · {ref.year} · {ref.venue}
              </span>
              <span className="block text-[11px] mt-1 leading-relaxed" style={{ color: "var(--text-muted)" }}>
                {ref.why}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {/* ── Zone 2: Literature for this run ──────────────────────────── */}
      <section>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Literature for this run
          </span>
          <Badge tone="accent">fetched for your goal · context only</Badge>
        </div>

        {!hasRun && (
          <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-faint)" }}>
            No live records were fetched for this run.
          </p>
        )}

        {seed.length > 0 && (
          <div className="mt-2">
            <div className="text-[10px] font-medium uppercase tracking-wider mb-1.5" style={{ color: "var(--text-muted)" }}>
              DNA seed · informs generation
            </div>
            <ul className="space-y-2">
              {seed.map((l) => (
                <LinkRow key={l.url} url={l.url} label={l.label} sublabel={l.detail} source={l.source} />
              ))}
            </ul>
          </div>
        )}

        {context.length > 0 && (
          <div className="mt-3">
            <div className="text-[10px] font-medium uppercase tracking-wider mb-1.5" style={{ color: "var(--text-muted)" }}>
              Context only · does not rewrite the DNA
            </div>
            <ul className="space-y-2">
              {context.slice(0, 8).map((l) => (
                <LinkRow key={l.url} url={l.url} label={l.label} sublabel={l.detail} source={l.source} />
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}
