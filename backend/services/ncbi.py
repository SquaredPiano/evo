"""NCBI gene info fetcher via E-utilities.

Prefers RefSeq mRNA / CDS for coding designs so seeds are gene identity–locked
rather than a random genomic mid-window.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

import httpx

from services.eutils import (
    EUTILS_BASE,
    eutils_client,
    eutils_params,
    get_with_retry,
    safe_json_response,
)

logger = logging.getLogger(__name__)

# Interactive design window - long enough to ground identity, short enough for NIM.
_MAX_SEED_BP = 720


@dataclass
class NCBIResult:
    gene_id: str = ""
    symbol: str = ""
    description: str = ""
    organism: str = ""
    chromosome: str = ""
    location: str = ""
    aliases: list[str] = field(default_factory=list)
    reference_accession: str = ""
    reference_sequence: str = ""
    sequence_kind: str = ""  # "cds" | "mrna_window" | "genomic_window" | ""


def _extract_id_list(search_data: dict) -> list[str]:
    payload = search_data.get("esearchresult")
    if not isinstance(payload, dict):
        return []
    if payload.get("ERROR"):
        logger.warning("NCBI esearch error: %s", payload.get("ERROR"))
    ids = payload.get("idlist")
    return [str(item) for item in ids] if isinstance(ids, list) else []


async def fetch_gene_info(
    gene: str,
    organism: str | None = None,
    *,
    prefer_cds: bool = True,
) -> NCBIResult:
    """Fetch gene summary from NCBI Gene database."""
    if not gene:
        return NCBIResult()

    try:
        async with eutils_client() as client:
            terms = [f"{gene}[gene]"]
            if organism:
                terms.insert(0, f"{gene}[gene] AND {organism}[orgn]")
                terms.append(f"{gene}[gene] AND {organism}[organism]")

            id_list: list[str] = []
            for term in terms:
                search_resp = await get_with_retry(
                    client,
                    f"{EUTILS_BASE}/esearch.fcgi",
                    params=eutils_params({
                        "db": "gene",
                        "term": term,
                        "retmax": 1,
                        "retmode": "json",
                    }),
                )
                search_data = safe_json_response(search_resp)
                id_list = _extract_id_list(search_data)
                if id_list:
                    break
            if not id_list:
                return NCBIResult(symbol=gene)

            gene_id = id_list[0]

            # Respect NCBI rate limit: max 3 req/sec without an API key.
            await asyncio.sleep(0.34)

            summary_resp = await get_with_retry(
                client,
                f"{EUTILS_BASE}/esummary.fcgi",
                params=eutils_params({
                    "db": "gene",
                    "id": gene_id,
                    "retmode": "json",
                }),
            )
            summary_data = safe_json_response(summary_resp)

            entry = summary_data.get("result", {}).get(gene_id, {})
            if not entry:
                return NCBIResult(gene_id=gene_id, symbol=gene)

            accession, reference_sequence, sequence_kind = await _fetch_reference_sequence(
                client, gene, organism, prefer_cds=prefer_cds,
            )

            return NCBIResult(
                gene_id=gene_id,
                symbol=entry.get("name", gene),
                description=entry.get("description", ""),
                organism=entry.get("organism", {}).get("scientificname", "")
                    if isinstance(entry.get("organism"), dict)
                    else str(entry.get("organism", "")),
                chromosome=entry.get("chromosome", ""),
                location=entry.get("maplocation", ""),
                aliases=entry.get("otheraliases", "").split(", ")
                    if entry.get("otheraliases")
                    else [],
                reference_accession=accession,
                reference_sequence=reference_sequence,
                sequence_kind=sequence_kind,
            )

    except Exception:
        logger.warning("NCBI gene lookup failed for gene=%s", gene, exc_info=True)
        return NCBIResult(symbol=gene)


def _clean_fasta_sequence(text: str) -> str:
    lines = [line.strip().upper() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    if lines[0].startswith(">"):
        lines = lines[1:]
    sequence = "".join(lines)
    return "".join(base for base in sequence if base in {"A", "T", "C", "G", "N"})


def _extract_cds_from_genbank(text: str) -> str | None:
    """Pull the joined CDS translation substrate (nucleotide) from GenBank text."""
    # Prefer a CDS feature with /translation= nearby - extract the location span sequence
    # via the ORIGIN block when location is simple.
    cds_match = re.search(
        r"^\s+CDS\s+(?:join\()?([0-9.,\s]+)",
        text,
        flags=re.MULTILINE,
    )
    origin_match = re.search(r"^ORIGIN\s*(.*)\n//", text, flags=re.MULTILINE | re.DOTALL)
    if not origin_match:
        return None
    origin = re.sub(r"[^atcgATCG]", "", origin_match.group(1)).upper()
    if not origin:
        return None

    if cds_match:
        coords = re.findall(r"(\d+)\.\.(\d+)", cds_match.group(1))
        if coords:
            pieces: list[str] = []
            for start_s, end_s in coords:
                start, end = int(start_s), int(end_s)
                if 1 <= start <= end <= len(origin):
                    pieces.append(origin[start - 1 : end])
            joined = "".join(pieces)
            if len(joined) >= 60 and joined.startswith("ATG"):
                return joined

    # Fallback: longest ATG…stop ORF in the mRNA origin
    return _longest_atg_orf(origin)


def _longest_atg_orf(sequence: str, min_bp: int = 90) -> str | None:
    best = ""
    stops = {"TAA", "TAG", "TGA"}
    upper = sequence.upper()
    for i in range(0, len(upper) - 2):
        if upper[i : i + 3] != "ATG":
            continue
        for j in range(i + 3, len(upper) - 2, 3):
            codon = upper[j : j + 3]
            if codon in stops:
                orf = upper[i : j + 3]
                if len(orf) > len(best):
                    best = orf
                break
    return best if len(best) >= min_bp else None


async def _fetch_fasta(client: httpx.AsyncClient, nuccore_id: str) -> tuple[str, str]:
    fasta_resp = await get_with_retry(
        client,
        f"{EUTILS_BASE}/efetch.fcgi",
        params=eutils_params({
            "db": "nuccore",
            "id": nuccore_id,
            "rettype": "fasta",
            "retmode": "text",
        }),
    )
    fasta_text = fasta_resp.text
    lines = [line.strip() for line in fasta_text.splitlines() if line.strip()]
    accession = ""
    if lines and lines[0].startswith(">"):
        accession = lines[0].split()[0].replace(">", "")
    return accession, _clean_fasta_sequence(fasta_text)


async def _fetch_genbank(client: httpx.AsyncClient, nuccore_id: str) -> str:
    resp = await get_with_retry(
        client,
        f"{EUTILS_BASE}/efetch.fcgi",
        params=eutils_params({
            "db": "nuccore",
            "id": nuccore_id,
            "rettype": "gb",
            "retmode": "text",
        }),
    )
    return resp.text


async def _search_nuccore(client: httpx.AsyncClient, terms: list[str]) -> str | None:
    for query in terms:
        search_resp = await get_with_retry(
            client,
            f"{EUTILS_BASE}/esearch.fcgi",
            params=eutils_params({
                "db": "nuccore",
                "term": query,
                "retmax": 1,
                "retmode": "json",
            }),
        )
        search_data = safe_json_response(search_resp)
        id_list = _extract_id_list(search_data)
        if id_list:
            return id_list[0]
    return None


def _window_sequence(seq: str, window: int = _MAX_SEED_BP) -> str:
    if len(seq) <= window:
        return seq
    # Prefer N-terminus / 5' for coding identity (domains often start there).
    if seq.startswith("ATG"):
        return seq[:window]
    center = len(seq) // 2
    start = max(0, center - window // 2)
    return seq[start : start + window]


async def _fetch_reference_sequence(
    client: httpx.AsyncClient,
    gene: str,
    organism: str | None = None,
    *,
    prefer_cds: bool = True,
) -> tuple[str, str, str]:
    try:
        org = organism or "Homo sapiens"
        mrna_terms = [
            f"{gene}[Gene Name] AND {org}[Organism] AND biomol_mrna[PROP] AND srcdb_refseq[PROP]",
            f"{gene}[Gene Name] AND biomol_mrna[PROP] AND srcdb_refseq[PROP]",
            f"{gene}[Gene] AND {org}[Organism] AND refseq[filter] AND mrna[filter]",
        ]
        genomic_terms = [
            f"{gene}[Gene Name] AND biomol_genomic[PROP] AND srcdb_refseq[PROP] AND {org}[Organism]",
            f"{gene}[Gene Name] AND srcdb_refseq[PROP]",
            f"{gene}[Gene Name]",
        ]

        if prefer_cds:
            nuccore_id = await _search_nuccore(client, mrna_terms)
            if nuccore_id:
                await asyncio.sleep(0.34)
                gb = await _fetch_genbank(client, nuccore_id)
                cds = _extract_cds_from_genbank(gb)
                await asyncio.sleep(0.34)
                accession, fasta = await _fetch_fasta(client, nuccore_id)
                if cds:
                    return accession or nuccore_id, _window_sequence(cds), "cds"
                if fasta:
                    orf = _longest_atg_orf(fasta)
                    if orf:
                        return accession, _window_sequence(orf), "cds"
                    return accession, _window_sequence(fasta), "mrna_window"

        nuccore_id = await _search_nuccore(client, genomic_terms if not prefer_cds else genomic_terms + mrna_terms)
        if not nuccore_id:
            return "", "", ""
        await asyncio.sleep(0.34)
        accession, seq = await _fetch_fasta(client, nuccore_id)
        if not seq:
            return accession, "", ""
        return accession, _window_sequence(seq, window=260 if not prefer_cds else _MAX_SEED_BP), "genomic_window"
    except Exception:
        logger.warning("NCBI reference sequence fetch failed for gene=%s", gene, exc_info=True)
        return "", "", ""
