import type { Base, Nucleotide, AnnotationType, SequenceRegion } from "@/types";

// Full IUPAC nucleotide alphabet: the four bases, U (RNA), and the ambiguity
// codes (R Y S W K M B D H V) plus N. Pasting a sequence that uses these is
// valid input - it must not be silently dropped.
export const IUPAC_BASES = new Set([
  "A", "C", "G", "T", "U",
  "R", "Y", "S", "W", "K", "M", "B", "D", "H", "V", "N",
]);

export function isValidSequence(seq: string): boolean {
  return seq
    .replace(/\s+/g, "")
    .split("")
    .every((ch) => IUPAC_BASES.has(ch.toUpperCase()));
}

export function normalizeSequence(raw: string): string {
  // Strip whitespace and uppercase - nothing else. Deliberately does NOT delete
  // "invalid" characters: dropping a base (e.g. an IUPAC ambiguity code like R
  // or Y) shifts every downstream coordinate silently. Anything that is not a
  // valid base is preserved here so isValidSequence can reject it LOUDLY at the
  // input boundary, rather than being erased and corrupting positions.
  return raw.replace(/\s+/g, "").toUpperCase();
}

export function parseSequence(
  raw: string,
  regions?: SequenceRegion[]
): Base[] {
  const seq = normalizeSequence(raw);
  return seq.split("").map((ch, i) => ({
    position: i,
    nucleotide: ch as Nucleotide,
    annotationType: regions
      ? getAnnotationAtPosition(i, regions)
      : undefined,
  }));
}

export function getAnnotationAtPosition(
  position: number,
  regions: SequenceRegion[]
): AnnotationType | undefined {
  const region = regions.find((r) => position >= r.start && position < r.end);
  return region?.type;
}

export function chunkSequence(seq: string, lineLength: number): string[] {
  const chunks: string[] = [];
  for (let i = 0; i < seq.length; i += lineLength) {
    chunks.push(seq.slice(i, i + lineLength));
  }
  return chunks;
}

export function formatPosition(pos: number): string {
  return pos.toLocaleString();
}

export function gcContent(seq: string): number {
  const normalized = normalizeSequence(seq);
  if (normalized.length === 0) return 0;
  const gc = normalized.split("").filter((b) => b === "G" || b === "C").length;
  return gc / normalized.length;
}

// Full IUPAC complement (mirrors backend translation.COMPLEMENT). U treated as
// the RNA form of T. Preserves ambiguity codes instead of collapsing them to N.
const IUPAC_COMPLEMENT: Record<string, string> = {
  A: "T", T: "A", U: "A", C: "G", G: "C", N: "N",
  R: "Y", Y: "R", S: "S", W: "W", K: "M", M: "K",
  B: "V", V: "B", D: "H", H: "D",
};

export function complement(base: string): string {
  return IUPAC_COMPLEMENT[base.toUpperCase()] ?? "N";
}

export function reverseComplement(seq: string): string {
  return seq
    .split("")
    .reverse()
    .map((b) => complement(b))
    .join("");
}
