"""Tests for CRISPR off-target scoring (CFD Doench 2016 + MIT Hsu 2013).

Scope: scoring against a SUPPLIED reference only, not a genome-wide scan.
"""

from fastapi.testclient import TestClient
import pytest

from main import app
from services.crispr_offtarget import (
    GUIDE_LENGTH,
    analyze_offtargets,
    cfd_score,
    mit_hit_score,
)
from services.translation import reverse_complement

GUIDE = "GTCACCTCCAATGACTAGGG"  # 20 nt


def _mutate(seq: str, index0: int) -> str:
    """Return seq with a guaranteed base change at 0-based ``index0``."""
    repl = "A" if seq[index0] != "A" else "C"
    return seq[:index0] + repl + seq[index0 + 1:]


# ---------------------------------------------------------------------------
# CFD scoring
# ---------------------------------------------------------------------------

def test_perfect_match_cfd_is_one() -> None:
    # Perfect protospacer with a canonical GG PAM -> CFD 1.0 (Doench 2016).
    assert cfd_score(GUIDE, GUIDE, "AGG") == pytest.approx(1.0)
    assert cfd_score(GUIDE, GUIDE, "TGG") == pytest.approx(1.0)


def test_single_mid_mismatch_reduces_cfd() -> None:
    # A single mismatch at protospacer position 10 must reduce CFD below 1.0
    # but keep it strictly positive (a mid-protospacer mismatch is tolerated
    # more than a PAM-proximal one).
    off = _mutate(GUIDE, 9)  # 0-based index 9 == position 10
    score = cfd_score(GUIDE, off, "AGG")
    assert 0.0 < score < 1.0


def test_cfd_matches_published_weight_table() -> None:
    # The per-position mismatch weight equals the CFD factor for exactly that
    # single mismatch (PAM = GG contributes 1.0). Validate the specific
    # rG:dT at position 20 weight from the Doench 2016 table.
    from services.crispr_offtarget import _load_cfd_tables

    mm, pam = _load_cfd_tables()
    assert pam["GG"] == pytest.approx(1.0)

    # Guide base G at position 20 (index 19); off-target base whose target
    # strand base is T -> off-target protospacer base is A (complement of T).
    guide = "A" * 19 + "G"
    off = "A" * 19 + "A"  # position-20 mismatch: rG:dT
    expected = mm["rG:dT,20"]
    assert cfd_score(guide, off, "AGG") == pytest.approx(expected)


def test_cfd_pam_penalty_applies() -> None:
    # A non-canonical PAM scales CFD by the PAM weight. NAG (AG) < NGG (GG=1).
    from services.crispr_offtarget import _load_cfd_tables

    _, pam = _load_cfd_tables()
    perfect_gg = cfd_score(GUIDE, GUIDE, "AGG")
    perfect_ag = cfd_score(GUIDE, GUIDE, "AAG")
    assert perfect_ag == pytest.approx(pam["AG"])
    assert perfect_ag < perfect_gg


def test_cfd_requires_20mer() -> None:
    with pytest.raises(ValueError):
        cfd_score("ACGT", "ACGT", "AGG")


# ---------------------------------------------------------------------------
# MIT scoring
# ---------------------------------------------------------------------------

def test_mit_perfect_is_100() -> None:
    assert mit_hit_score([]) == pytest.approx(100.0)


def test_mit_single_mismatch_reduces() -> None:
    # A mismatch at a high-weight (PAM-proximal) position penalizes more than
    # a zero-weight distal position.
    proximal = mit_hit_score([14])   # weight 0.851
    distal = mit_hit_score([1])      # weight 0.0 -> no penalty from term1
    assert proximal < distal
    assert distal == pytest.approx(100.0)  # position-1 weight is 0 in Hsu table


# ---------------------------------------------------------------------------
# Search over the supplied reference
# ---------------------------------------------------------------------------

def test_perfect_ontarget_found_on_plus_strand() -> None:
    ref = "AAAA" + GUIDE + "AGG" + "TTTT"
    rep = analyze_offtargets(GUIDE, ref, pam="NGG", max_mismatches=4)
    assert rep.total_sites == 1
    site = rep.sites[0]
    assert site.strand == "+"
    assert site.position == 4
    assert site.mismatch_count == 0
    assert site.cfd_score == pytest.approx(1.0)
    # No off-targets -> perfect specificity.
    assert rep.off_target_count == 0
    assert rep.specificity_score == pytest.approx(100.0)


def test_both_strands_are_searched() -> None:
    # Embed the site only on the minus strand: put revcomp(guide+PAM) on the
    # forward reference so the guide matches when reading the reverse strand.
    site_on_minus = reverse_complement(GUIDE + "TGG")
    ref = "CCCCC" + site_on_minus + "GGGGG"
    rep = analyze_offtargets(GUIDE, ref, pam="NGG", max_mismatches=4)
    assert rep.total_sites == 1
    site = rep.sites[0]
    assert site.strand == "-"
    assert site.mismatch_count == 0
    assert site.protospacer == GUIDE
    assert site.cfd_score == pytest.approx(1.0)


def test_pam_mismatch_excludes_site() -> None:
    # Same protospacer but a non-NGG PAM (CTT) must NOT be found under NGG.
    ref = "AAAA" + GUIDE + "CTT" + "TTTT"
    rep = analyze_offtargets(GUIDE, ref, pam="NGG", max_mismatches=4)
    assert rep.total_sites == 0
    # But a permissive PAM that matches CTT via IUPAC would find it.
    rep2 = analyze_offtargets(GUIDE, ref, pam="NNN", max_mismatches=4)
    assert rep2.total_sites >= 1


def test_mismatch_tolerance_boundary() -> None:
    # 4 mismatches accepted at default tolerance; 5 excluded.
    off4 = GUIDE
    for i in (2, 6, 10, 14):
        off4 = _mutate(off4, i)
    ref4 = "AAAA" + off4 + "AGG" + "TTTT"
    assert analyze_offtargets(GUIDE, ref4, max_mismatches=4).off_target_count == 1

    off5 = _mutate(off4, 18)
    ref5 = "AAAA" + off5 + "AGG" + "TTTT"
    assert analyze_offtargets(GUIDE, ref5, max_mismatches=4).total_sites == 0
    assert analyze_offtargets(GUIDE, ref5, max_mismatches=5).off_target_count == 1


def test_offtarget_lowers_aggregate_specificity() -> None:
    # One perfect on-target plus one 1-mismatch off-target: specificity < 100.
    off = _mutate(GUIDE, 12)  # position 13, high MIT weight
    ref = "AAAA" + GUIDE + "AGG" + "CC" + off + "AGG" + "TTTT"
    rep = analyze_offtargets(GUIDE, ref, pam="NGG", max_mismatches=4)
    assert rep.off_target_count == 1
    assert 0.0 < rep.specificity_score < 100.0
    # Aggregate matches the MIT formula over the off-target hit scores.
    hit_sum = sum(s.mit_score for s in rep.sites if s.mismatch_count >= 1)
    assert rep.specificity_score == pytest.approx(round(100.0 * (100.0 / (100.0 + hit_sum)), 2))


def test_mismatch_positions_use_pam_proximal_20() -> None:
    off = _mutate(GUIDE, 19)  # last protospacer base == position 20 (PAM-proximal)
    ref = "AAAA" + off + "AGG"
    rep = analyze_offtargets(GUIDE, ref, pam="NGG", max_mismatches=4)
    assert rep.total_sites == 1
    mms = rep.sites[0].mismatches
    assert len(mms) == 1 and mms[0].position == 20


def test_invalid_guide_rejected() -> None:
    with pytest.raises(ValueError):
        analyze_offtargets("ACGT", GUIDE + "AGG", pam="NGG")  # not 20 nt
    with pytest.raises(ValueError):
        analyze_offtargets("N" * 20, GUIDE + "AGG", pam="NGG")  # ambiguous guide


def test_short_reference_returns_empty_report() -> None:
    rep = analyze_offtargets(GUIDE, "ACGT", pam="NGG")
    assert rep.total_sites == 0
    assert rep.specificity_score == pytest.approx(100.0)
    assert "supplied reference" in rep.note.lower()


def test_guide_length_constant() -> None:
    assert GUIDE_LENGTH == 20


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

def test_crispr_endpoint_happy_path() -> None:
    client = TestClient(app)
    ref = "AAAA" + GUIDE + "AGG" + "CC" + _mutate(GUIDE, 12) + "AGG" + "TTTT"
    res = client.post("/api/crispr-offtarget", json={"guide": GUIDE, "reference": ref})
    assert res.status_code == 200
    body = res.json()
    assert body["strands_searched"] == "both"
    assert body["off_target_count"] == 1
    assert 0.0 < body["specificity_score"] < 100.0
    assert "not a genome-wide scan" in body["note"].lower()
    assert "Doench 2016" in body["method"]
    # Perfect on-target ranked first (CFD 1.0).
    assert body["sites"][0]["cfd_score"] == pytest.approx(1.0)


def test_crispr_endpoint_uses_supplied_reference_only_label() -> None:
    client = TestClient(app)
    res = client.post(
        "/api/crispr-offtarget",
        json={"guide": GUIDE, "reference": GUIDE + "AGG", "pam": "NGG"},
    )
    assert res.status_code == 200
    assert "genome-wide" in res.json()["note"].lower()


def test_crispr_endpoint_rejects_bad_guide() -> None:
    client = TestClient(app)
    res = client.post("/api/crispr-offtarget", json={"guide": "ACGT", "reference": GUIDE + "AGG"})
    assert res.status_code == 422


def test_crispr_endpoint_rejects_bad_pam() -> None:
    client = TestClient(app)
    res = client.post(
        "/api/crispr-offtarget",
        json={"guide": GUIDE, "reference": GUIDE + "AGG", "pam": "XYZ"},
    )
    assert res.status_code == 422
