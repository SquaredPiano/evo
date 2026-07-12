import type { SequenceRegion } from "./sequence";

export interface LikelihoodScore {
  position: number;
  score: number; // log likelihood under Evo 2
}

export interface MutationEffect {
  position: number;
  referenceBase: string;
  alternateBase: string;
  deltaLikelihood: number;
  // Model-likelihood label for a single-base edit (sign of the delta LL), not a
  // clinical pathogenicity call.
  predictedImpact: "more_likely" | "neutral" | "less_likely";
}

export interface PredictedProtein {
  regionStart: number;
  regionEnd: number;
  pdbData?: string; // raw PDB string for Three.js renderer
  sequenceIdentity?: number;
}

export interface AnalysisResult {
  rawSequence: string;
  regions: SequenceRegion[];
  perPositionScores: LikelihoodScore[];
  predictedProteins: PredictedProtein[];
}
