/** Build citation URLs from NCBI / PubMed / ClinVar retrieval payloads. */

export interface EvidenceLink {
  source: "ncbi" | "pubmed" | "clinvar";
  label: string;
  url: string;
  detail?: string;
}

type RetrievalPayload = Record<string, unknown> | null | undefined;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function pubmedUrl(pmid: string): string | null {
  const id = pmid.trim();
  if (!id || id.startsWith("DEMO-")) return null;
  return `https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(id)}/`;
}

function clinvarUrl(uid: string): string | null {
  const id = uid.trim();
  if (!id || id.startsWith("DEMO-")) return null;
  return `https://www.ncbi.nlm.nih.gov/clinvar/variation/${encodeURIComponent(id)}/`;
}

function ncbiGeneUrl(geneId: string): string | null {
  const id = geneId.trim();
  if (!id || id.startsWith("DEMO")) return null;
  return `https://www.ncbi.nlm.nih.gov/gene/${encodeURIComponent(id)}`;
}

export function buildEvidenceLinks(
  evidence: Record<string, RetrievalPayload>
): EvidenceLink[] {
  const links: EvidenceLink[] = [];

  const ncbi = asRecord(evidence.ncbi);
  if (ncbi) {
    const geneId = String(ncbi.gene_id ?? ncbi.geneId ?? "");
    const symbol = String(ncbi.symbol ?? ncbi.gene ?? "Gene");
    const accession = String(ncbi.reference_accession ?? "");
    const url = ncbiGeneUrl(geneId);
    if (url) {
      links.push({
        source: "ncbi",
        label: `${symbol} (NCBI Gene)`,
        url,
        detail: accession && accession !== "NEUTRAL_SCAFFOLD" ? accession : undefined,
      });
    } else if (accession && accession !== "NEUTRAL_SCAFFOLD" && !ncbi.fallback) {
      links.push({
        source: "ncbi",
        label: `${symbol} · ${accession}`,
        url: `https://www.ncbi.nlm.nih.gov/nuccore/${encodeURIComponent(accession)}`,
      });
    }
  }

  const pubmed = asRecord(evidence.pubmed);
  if (pubmed) {
    const papers =
      (Array.isArray(pubmed.articles) && pubmed.articles) ||
      (Array.isArray(pubmed.papers) && pubmed.papers) ||
      [];
    for (const raw of papers.slice(0, 5)) {
      const paper = asRecord(raw);
      if (!paper) continue;
      const pmid = String(paper.pmid ?? "");
      const title = String(paper.title ?? `PMID ${pmid}`);
      const url = pubmedUrl(pmid);
      if (!url) continue;
      links.push({
        source: "pubmed",
        label: title.length > 72 ? `${title.slice(0, 69)}…` : title,
        url,
        detail: pmid,
      });
    }
  }

  const clinvar = asRecord(evidence.clinvar);
  if (clinvar) {
    const variants = Array.isArray(clinvar.variants) ? clinvar.variants : [];
    for (const raw of variants.slice(0, 5)) {
      const variant = asRecord(raw);
      if (!variant) continue;
      const uid = String(variant.uid ?? "");
      const title = String(variant.title ?? `ClinVar ${uid}`);
      const significance = String(variant.clinical_significance ?? "");
      const url = clinvarUrl(uid);
      if (!url) continue;
      links.push({
        source: "clinvar",
        label: title.length > 64 ? `${title.slice(0, 61)}…` : title,
        url,
        detail: significance || uid,
      });
    }
  }

  return links;
}
