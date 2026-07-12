"use client";

import type { RegionEvidence, SequenceRegion } from "@/types";

interface RegionEvidenceCardProps {
  region: SequenceRegion;
  /** Evidence items already filtered to those overlapping this region. */
  evidence: RegionEvidence[];
}

const SOURCE_BADGE: Record<string, { label: string; color: string }> = {
  clinvar: { label: "ClinVar", color: "var(--annotation-exon, #d97757)" },
  regulatory: { label: "Regulatory", color: "var(--annotation-orf, #6aa6c9)" },
  literature: { label: "Paper", color: "var(--accent, #7c9885)" },
};

function badgeFor(source: string) {
  return (
    SOURCE_BADGE[source] ?? { label: source, color: "var(--annotation-unknown, #888)" }
  );
}

/** Real external link only - never fabricate. Backend supplies url; require http(s). */
function safeUrl(url?: string | null): string | null {
  if (!url) return null;
  const u = url.trim();
  return u.startsWith("http://") || u.startsWith("https://") ? u : null;
}

export default function RegionEvidenceCard({ region, evidence }: RegionEvidenceCardProps) {
  const label = region.label ?? region.type;

  // Group by source, preserving a stable source order.
  const order = ["clinvar", "regulatory", "literature"];
  const grouped = new Map<string, RegionEvidence[]>();
  for (const item of evidence) {
    const arr = grouped.get(item.source) ?? [];
    arr.push(item);
    grouped.set(item.source, arr);
  }
  const sources = [...grouped.keys()].sort(
    (a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99)
  );

  return (
    <div
      style={{
        backgroundColor: "var(--surface-raised)",
        border: "1px solid var(--ghost-border)",
        borderRadius: "12px",
        padding: "12px 14px",
        minWidth: "268px",
        maxWidth: "360px",
        boxShadow: "var(--shadow-elevated, 0 8px 28px rgba(0,0,0,0.28))",
        fontSize: "12px",
        color: "var(--text-primary)",
      }}
    >
      <div className="flex items-center justify-between" style={{ marginBottom: "6px" }}>
        <span style={{ fontWeight: 600 }}>{label}</span>
        <span style={{ color: "var(--text-muted)", fontFamily: "monospace", fontSize: "11px" }}>
          {region.start}–{region.end}
        </span>
      </div>

      {evidence.length === 0 ? (
        <div style={{ color: "var(--text-muted)", fontStyle: "italic" }}>
          No linked evidence for this region yet.
        </div>
      ) : (
        <div className="flex flex-col" style={{ gap: "8px", maxHeight: "260px", overflowY: "auto" }}>
          {sources.map((source) => {
            const items = grouped.get(source)!;
            const badge = badgeFor(source);
            return (
              <div key={source} className="flex flex-col" style={{ gap: "4px" }}>
                <span
                  className="uppercase"
                  style={{
                    alignSelf: "flex-start",
                    fontSize: "9px",
                    fontWeight: 700,
                    letterSpacing: "0.06em",
                    padding: "1px 6px",
                    borderRadius: "3px",
                    color: badge.color,
                    backgroundColor: `color-mix(in oklch, ${badge.color}, transparent 86%)`,
                  }}
                >
                  {badge.label}
                </span>
                {items.map((item, i) => {
                  const href = safeUrl(item.url);
                  return (
                    <div key={`${source}-${i}`} style={{ paddingLeft: "2px" }}>
                      {href ? (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: "var(--accent)", textDecoration: "none", fontWeight: 500 }}
                        >
                          {item.title} ↗
                        </a>
                      ) : (
                        <span style={{ fontWeight: 500 }}>{item.title}</span>
                      )}
                      {item.detail && (
                        <div style={{ color: "var(--text-muted)", marginTop: "2px", lineHeight: 1.35 }}>
                          {item.detail}
                        </div>
                      )}
                      {item.confidence && (
                        <div style={{ color: "var(--text-faint)", fontSize: "10px", marginTop: "1px" }}>
                          {item.confidence}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
