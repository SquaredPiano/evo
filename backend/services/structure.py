"""ESMFold structure prediction via Meta's ESM Atlas API.

Takes a DNA sequence, translates to protein, sends to ESMFold,
returns PDB with pLDDT confidence scores.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from services.translation import find_orfs

logger = logging.getLogger(__name__)

ESMFOLD_API_URL = "https://api.esmatlas.com/foldSequence/v1/pdb/"
MIN_PROTEIN_LENGTH = 16
MAX_RETRIES = 2
PDB_RECORD_PREFIXES = {
    "HEADER",
    "TITLE",
    "MODEL",
    "ATOM",
    "HETATM",
    "TER",
    "ENDMDL",
    "END",
    "REMARK",
}


@dataclass
class StructurePrediction:
    pdb_data: str
    protein_sequence: str
    confidence: float  # mean pLDDT (0-1 scale)
    model: str = "esmfold"


def _extract_mean_plddt(pdb_text: str) -> float:
    """Extract mean pLDDT from PDB B-factor column (cols 61-66).

    pLDDT is a PER-RESIDUE confidence that ESMFold duplicates onto the B-factor
    of every atom in the residue. Averaging over all ATOM records therefore
    weights each residue by its atom count and biases the mean toward larger
    residues (Trp/Arg vs Gly). We take ONE value per residue from its CA atom,
    keyed by (chain, residue sequence number), so every residue counts once.
    Returns 0-1 scale.
    """
    per_residue: dict[tuple[str, str], float] = {}
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if line[12:16].strip() != "CA":
            continue
        try:
            b_factor = float(line[60:66].strip())
        except (ValueError, IndexError):
            continue
        chain = line[21:22]
        res_seq = line[22:26].strip()
        per_residue[(chain, res_seq)] = b_factor
    if not per_residue:
        return 0.0
    mean_b = sum(per_residue.values()) / len(per_residue)
    # Some providers return pLDDT in [0,100], others normalize to [0,1].
    return mean_b if mean_b <= 1.5 else (mean_b / 100.0)


def _extract_pdb_text(raw_text: str) -> str:
    """Normalize raw API text into valid PDB records only.

    Handles plain-PDB responses and fenced-code payloads.
    """
    text = raw_text.strip()
    if not text:
        return ""

    fenced = re.search(r"```(?:pdb)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced is not None:
        text = fenced.group(1).strip()

    lines: list[str] = []
    for line in text.splitlines():
        cleaned = line.rstrip()
        if not cleaned:
            continue
        prefix = cleaned[:6].strip().upper()
        if prefix in PDB_RECORD_PREFIXES:
            lines.append(cleaned)

    if not lines:
        return ""
    if lines[-1].strip().upper() != "END":
        lines.append("END")
    return "\n".join(lines)


def _has_backbone_atoms(pdb_text: str) -> bool:
    atom_names: set[str] = set()
    atom_count = 0
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        atom_count += 1
        atom_names.add(line[12:16].strip())
    # Require at least a minimal number of atoms plus full backbone markers.
    if atom_count < 20:
        return False
    return {"N", "CA", "C", "O"}.issubset(atom_names)


def _select_protein_for_folding(dna_sequence: str) -> str:
    """Return the protein of the longest REAL ORF, or "" if the design is non-coding.

    Folds ONLY a genuine open reading frame (ATG ... in-frame stop) discovered by
    a six-frame ORF search (3 forward + 3 reverse via ``find_orfs``). A
    regulatory / non-coding design contains no such ORF, so we return "" and the
    caller reports "no protein product" instead of folding a translational
    artifact from an arbitrary reading frame.

    N (unknown) bases are left untouched: the previous ``N``->``A`` substitution
    could fabricate spurious ATG start or stop codons out of unknown sequence.
    ``find_orfs`` never matches ATG / stop against a codon containing N, and any
    N codon inside a real ORF translates to 'X' - so we never invent codons.
    """
    seq = dna_sequence.upper()
    if len(seq) < 9:
        return ""

    orfs = find_orfs(seq, min_length=24)
    if not orfs:
        return ""
    best_orf = max(orfs, key=lambda o: len(o.protein))
    return best_orf.protein


def coding_region_changed(ref_dna: str, alt_dna: str) -> bool:
    """Would a single-base edit alter the protein we'd actually fold?

    Compares the foldable protein extracted from each sequence. Returns False for
    synonymous / non-coding edits, so callers can skip an expensive refold that
    would produce an identical structure. Cheap, string-only - safe to call on the
    hot edit path.
    """
    return _select_protein_for_folding(ref_dna) != _select_protein_for_folding(alt_dna)


async def predict_structure(
    dna_sequence: str,
    region_start: int = 0,
    region_end: int | None = None,
) -> StructurePrediction | None:
    """Predict protein structure from a DNA sequence region using ESMFold.

    Translates DNA to protein, then calls the ESM Atlas API.
    Returns None on API failure (caller handles gracefully).
    """
    region = dna_sequence[region_start:region_end]
    protein = _select_protein_for_folding(region)

    if len(protein) < MIN_PROTEIN_LENGTH:
        logger.warning(
            "Protein too short for structure prediction: %d residues (min %d)",
            len(protein),
            MIN_PROTEIN_LENGTH,
        )
        return None

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(
                    ESMFOLD_API_URL,
                    content=protein,
                    headers={"Content-Type": "text/plain"},
                )
                if resp.status_code == 429:
                    logger.warning("ESMFold rate limited (attempt %d/%d)", attempt + 1, MAX_RETRIES + 1)
                    last_error = httpx.HTTPStatusError(
                        "Rate limited", request=resp.request, response=resp
                    )
                    continue
                resp.raise_for_status()

                pdb_data = _extract_pdb_text(resp.text)
                if not pdb_data or not _has_backbone_atoms(pdb_data):
                    logger.warning("ESMFold returned invalid PDB response")
                    return None

                confidence = _extract_mean_plddt(pdb_data)

                return StructurePrediction(
                    pdb_data=pdb_data,
                    protein_sequence=protein,
                    confidence=round(confidence, 4),
                )

        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            last_error = exc
            logger.warning("ESMFold API call failed (attempt %d/%d)", attempt + 1, MAX_RETRIES + 1, exc_info=True)

    logger.error("ESMFold API exhausted all retries: %s", last_error)
    return None
