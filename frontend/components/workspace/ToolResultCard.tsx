"use client";

import { Crosshair, Scissors, ShieldAlert } from "lucide-react";
import {
  isOffTargetScan,
  isRestrictionSites,
  type ToolResult,
  type OffTargetScanResult,
  type RestrictionSitesResult,
} from "@/lib/agentTypes";

/**
 * Read-only tool result cards (offtarget_scan / restriction_sites) so the
 * agent's read-only tools visibly produce something a scientist can inspect.
 */
export default function ToolResultCard({ result }: { result: ToolResult }) {
  if (isOffTargetScan(result)) return <OffTargetScanCard r={result} />;
  if (isRestrictionSites(result)) return <RestrictionSitesCard r={result} />;
  return null;
}

function riskColor(level: string): string {
  const l = (level || "").toLowerCase();
  if (l.includes("high")) return "var(--base-t, #ef4444)";
  if (l.includes("medium") || l.includes("mod")) return "var(--honey-500, #f59e0b)";
  return "var(--accent, #7c9885)";
}

function pct(v: number): string {
  return Number.isFinite(v) ? `${Math.round(v * (v <= 1 ? 100 : 1))}%` : "–";
}

function CardShell({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{ background: "var(--surface-base)", border: "1px solid var(--ghost-border)" }}
    >
      <div
        className="flex items-center gap-2 px-3.5 py-2.5"
        style={{ borderBottom: "1px solid var(--ghost-border)" }}
      >
        {icon}
        <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-primary)" }}>
          {title}
        </span>
      </div>
      <div className="px-3.5 py-3 space-y-2.5">{children}</div>
    </div>
  );
}

function StatRow({ stats }: { stats: { label: string; value: string; color?: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10.5px]" style={{ color: "var(--text-muted)" }}>
      {stats.map((s) => (
        <span key={s.label}>
          {s.label}{" "}
          <span className="font-mono font-semibold" style={{ color: s.color ?? "var(--text-secondary)" }}>
            {s.value}
          </span>
        </span>
      ))}
    </div>
  );
}

function OffTargetScanCard({ r }: { r: OffTargetScanResult }) {
  const hits = Array.isArray(r.hits) ? r.hits : [];
  return (
    <CardShell
      icon={<Crosshair size={13} style={{ color: "var(--accent)" }} />}
      title="Off-target scan"
    >
      <StatRow
        stats={[
          { label: "query", value: `${r.query_length} bp` },
          { label: "k", value: String(r.k) },
          { label: "hits", value: String(r.total_hits) },
          { label: "high", value: String(r.high_risk), color: "var(--base-t)" },
          { label: "medium", value: String(r.medium_risk), color: "var(--honey-500, #f59e0b)" },
          { label: "repeats", value: pct(r.repeat_fraction) },
        ]}
      />
      {r.gc_balance_risk !== null && r.gc_balance_risk !== undefined && (
        <div className="text-[10px] flex items-center gap-1" style={{ color: "var(--text-faint)" }}>
          <ShieldAlert size={10} /> GC-balance risk: {String(r.gc_balance_risk)}
        </div>
      )}
      {hits.length > 0 ? (
        <div className="space-y-1.5">
          {hits.slice(0, 8).map((h, i) => {
            const color = riskColor(h.risk_level);
            return (
              <div
                key={`${h.region_name}-${i}`}
                className="rounded-lg px-2.5 py-1.5"
                style={{ background: "var(--surface-raised)", border: "1px solid var(--ghost-border)" }}
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className="uppercase"
                    style={{
                      fontSize: "8.5px",
                      fontWeight: 700,
                      letterSpacing: "0.05em",
                      padding: "1px 5px",
                      borderRadius: "3px",
                      color,
                      backgroundColor: `color-mix(in oklch, ${color}, transparent 86%)`,
                    }}
                  >
                    {h.risk_level}
                  </span>
                  <span className="text-[11px] font-medium" style={{ color: "var(--text-primary)" }}>
                    {h.region_name}
                  </span>
                  <span className="text-[9px]" style={{ color: "var(--text-faint)" }}>
                    {h.category}
                  </span>
                  <span className="flex-1" />
                  <span className="text-[9.5px] font-mono" style={{ color: "var(--text-muted)" }}>
                    sim {typeof h.similarity_score === "number" ? h.similarity_score.toFixed(2) : "–"} · {h.shared_kmers} k-mers
                  </span>
                </div>
                {h.description && (
                  <div className="text-[10px] mt-0.5 leading-snug" style={{ color: "var(--text-muted)" }}>
                    {h.description}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-[10.5px]" style={{ color: "var(--accent)" }}>
          No off-target hits found in the reference panel.
        </div>
      )}
    </CardShell>
  );
}

function RestrictionSitesCard({ r }: { r: RestrictionSitesResult }) {
  const sites = Array.isArray(r.sites) ? r.sites : [];
  return (
    <CardShell
      icon={<Scissors size={13} style={{ color: "var(--accent)" }} />}
      title="Restriction sites"
    >
      <StatRow
        stats={[
          { label: "sequence", value: `${r.sequence_length} bp` },
          { label: "enzymes", value: String(r.enzymes_checked) },
          { label: "sites", value: String(r.total_sites) },
        ]}
      />
      {sites.length > 0 ? (
        <div className="space-y-1">
          {sites.map((s, i) => (
            <div
              key={`${s.enzyme}-${i}`}
              className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px]"
              style={{ background: "var(--surface-raised)", border: "1px solid var(--ghost-border)" }}
            >
              <span className="font-semibold" style={{ color: "var(--text-primary)" }}>
                {s.enzyme}
              </span>
              <span className="font-mono text-[10px]" style={{ color: "var(--base-c, #6aa6c9)" }}>
                {s.recognition_site}
              </span>
              <span className="flex-1" />
              <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                {s.count}× · {Array.isArray(s.positions) ? s.positions.slice(0, 6).join(", ") : ""}
                {Array.isArray(s.positions) && s.positions.length > 6 ? "…" : ""}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[10.5px]" style={{ color: "var(--accent)" }}>
          No restriction sites for the checked enzymes - clean to cut.
        </div>
      )}
    </CardShell>
  );
}
