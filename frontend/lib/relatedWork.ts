/**
 * Related work for the Proteus IDE.
 *
 * Two clearly-separated kinds of "related work":
 *  1. FOUNDATIONAL_WORK - a small, hand-curated, ALWAYS-shown bibliography of the
 *     models and resources Proteus is built on. This is NOT run-specific: it is the
 *     same for every design. No DOIs/PMIDs are invented - where an exact
 *     identifier is uncertain we link the canonical project/paper page instead.
 *  2. Run literature - the live NCBI / PubMed / ClinVar records fetched for the
 *     current goal. Those come from `buildEvidenceLinks` and are split by ROLE
 *     via `partitionRunLiterature` (see below).
 */

import type { EvidenceLink } from "@/lib/evidence";

export interface FoundationalRef {
  id: string;
  title: string;
  authorsShort: string;
  year: string;
  venue: string;
  url: string;
  /** One line: why this paper/resource is load-bearing inside Proteus. */
  why: string;
}

/**
 * Curated, static bibliography. Always rendered under the "Foundational" zone
 * with a "not run-specific" badge. Identifiers are only included when they are
 * embedded in the canonical page URL; otherwise we link the project page.
 */
export const FOUNDATIONAL_WORK: FoundationalRef[] = [
  {
    id: "evo2",
    title: "Genome modeling and design across all domains of life with Evo 2",
    authorsShort: "Brixi, Durrant, Hie et al.",
    year: "2025",
    venue: "Arc Institute (genomic foundation model)",
    url: "https://arcinstitute.org/tools/evo",
    why: "The DNA language model Evo streams to generate candidate sequences - the generative engine behind every design.",
  },
  {
    id: "esmfold",
    title:
      "Evolutionary-scale prediction of atomic-level protein structure with a language model",
    authorsShort: "Lin, Akin, Rao et al.",
    year: "2023",
    venue: "Science",
    url: "https://www.science.org/doi/10.1126/science.ade2574",
    why: "ESMFold turns a candidate's amino-acid sequence into the 3D structure preview and per-residue pLDDT confidence.",
  },
  {
    id: "evo1",
    title:
      "Sequence modeling and design from molecular to genome scale with Evo",
    authorsShort: "Nguyen, Poli, Durrant et al.",
    year: "2024",
    venue: "Science / Arc Institute",
    url: "https://arcinstitute.org/tools/evo",
    why: "First-generation genomic design model - the lineage and design methodology Evo 2 extends.",
  },
  {
    id: "clinvar",
    title: "ClinVar: public archive of relationships among variants and phenotypes",
    authorsShort: "Landrum et al.",
    year: "2018",
    venue: "Nucleic Acids Research / NCBI",
    url: "https://www.ncbi.nlm.nih.gov/clinvar/",
    why: "Pathogenic/benign labels used to calibrate scores and to annotate variants - the ground-truth reference for the Validate tool.",
  },
];

export interface RunLiterature {
  /** NCBI gene/CDS records - the DNA seed that informs generation. */
  seed: EvidenceLink[];
  /** PubMed + ClinVar - context only; these do NOT rewrite the DNA. */
  context: EvidenceLink[];
}

/**
 * Split the flat evidence list (from `buildEvidenceLinks`) by the role each
 * source plays in the pipeline:
 *   - NCBI → the sequence seed ("informs generation")
 *   - PubMed + ClinVar → surrounding literature ("context only")
 */
export function partitionRunLiterature(links: EvidenceLink[]): RunLiterature {
  const seed: EvidenceLink[] = [];
  const context: EvidenceLink[] = [];
  for (const link of links) {
    if (link.source === "ncbi") seed.push(link);
    else context.push(link);
  }
  return { seed, context };
}
