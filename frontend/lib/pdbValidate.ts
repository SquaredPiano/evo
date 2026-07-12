/**
 * Client-side validation for user-uploaded PDB structure files.
 *
 * A user-uploaded PDB is NOT a model prediction - we render it plainly and
 * label it honestly. This helper only sanity-checks that the file looks like
 * a real coordinate file before we hand it to the 3D viewer.
 */

export const MAX_PDB_BYTES = 10 * 1024 * 1024; // ~10 MB

export interface PdbValidation {
  ok: boolean;
  error?: string;
  atomCount: number;
  residueCount: number;
  hasBackbone: boolean;
}

const BACKBONE_ATOMS = new Set(["N", "CA", "C", "O"]);

/**
 * Validate raw PDB text. Rules:
 * - non-empty
 * - at least 1 ATOM record (required)
 * - strong signal: >= 20 atoms with backbone N/CA/C/O present (advisory)
 */
export function validatePdbText(text: string): PdbValidation {
  const result: PdbValidation = {
    ok: false,
    atomCount: 0,
    residueCount: 0,
    hasBackbone: false,
  };

  if (!text || !text.trim()) {
    result.error = "File is empty.";
    return result;
  }

  const residues = new Set<string>();
  const backboneSeen = new Set<string>();
  let atomCount = 0;

  for (const line of text.split(/\r?\n/)) {
    if (!line.startsWith("ATOM")) continue;
    atomCount += 1;
    const atomName = line.substring(12, 16).trim();
    const resKey = `${line.substring(21, 22)}:${line.substring(22, 26).trim()}`;
    residues.add(resKey);
    if (BACKBONE_ATOMS.has(atomName)) backboneSeen.add(atomName);
  }

  result.atomCount = atomCount;
  result.residueCount = residues.size;
  result.hasBackbone = BACKBONE_ATOMS.size === backboneSeen.size;

  if (atomCount < 1) {
    result.error = "No ATOM records found - this does not look like a PDB structure file.";
    return result;
  }

  result.ok = true;
  return result;
}
