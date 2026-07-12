export type AnnotationType =
  | "exon"
  | "intron"
  | "orf"
  | "prophage"
  | "trna"
  | "rrna"
  | "intergenic"
  | "unknown";

export interface SequenceRegion {
  start: number; // 0-indexed
  end: number;
  type: AnnotationType;
  label?: string;
  score?: number; // Evo 2 likelihood score for this region
}

/** Source of a piece of coordinate-bound evidence. Mirrors the backend
 *  RegionEvidence.source union; "literature" is populated by a future RAG. */
export type RegionEvidenceSource = "clinvar" | "regulatory" | "literature";

/**
 * One piece of evidence bound to a coordinate span in the candidate's frame.
 * 0-based, half-open [start, end). Mirror of backend
 * services.region_evidence.RegionEvidence — see docs/region_evidence_interface.md.
 */
export interface RegionEvidence {
  start: number;
  end: number;
  source: RegionEvidenceSource | string;
  kind: string; // "pathogenic_variant" | "motif" | "paper" | ...
  title: string;
  detail?: string | null;
  url?: string | null; // real external link, or null. Never fabricated.
  identifier?: string | null; // PMID / ClinVar UID / accession / motif name
  score?: number | null;
  confidence?: string | null;
}

export type Nucleotide = "A" | "T" | "C" | "G" | "N";

export interface Base {
  position: number;
  nucleotide: Nucleotide;
  likelihoodScore?: number;
  annotationType?: AnnotationType;
}
