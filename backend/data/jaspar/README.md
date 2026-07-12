# Bundled JASPAR motif matrices

Curated set of real transcription-factor position frequency matrices (PFMs) from
the **JASPAR CORE 2024 vertebrates** collection, used by `services.motifs` for
position weight matrix (PWM) scanning. These replace the earlier short-substring
motif matching, which matched 6-7 bp cores by chance every few kilobases and so
counted noise rather than binding-site signal.

## Format

Each `*.jaspar` file is the JASPAR `.jaspar` PFM text format (raw base counts),
read directly by Biopython (`Bio.motifs.read(fh, "jaspar")`). The file name is
the matrix ID (e.g. `MA0108.3.jaspar`). `manifest.json` lists every bundled
matrix (`matrix_id`, `tf_name`, and the query TF name).

## Source

- Collection: JASPAR CORE 2024, taxonomic group `vertebrates`.
- Downloaded from the JASPAR REST API:
  `https://jaspar.elixir.no/api/v1/matrix/{MATRIX_ID}.jaspar`
  (matrix IDs resolved to the latest CORE version per TF via
  `.../matrix/?name={TF}&tax_group=vertebrates&collection=CORE&version=latest`).

## Bundled matrices (26)

Grouped as used by `services.motifs` and the tissue scorer:

**Neuronal / neural lineage:** REST/NRSF (MA0138.3), NEUROD1 (MA1109.2),
ASCL1 (MA1100.3), OLIG2 (MA0678.1), SOX2 (MA0143.5), PAX6 (MA0069.1),
CREB1 (MA0018.5), POU2F1 (MA0785.2).

**Cardiac / muscle lineage:** MEF2A (MA0052.5), MEF2C (MA0497.2),
GATA1 (MA0035.5), GATA2 (MA0036.4), GATA3 (MA0037.5), MYOD1 (MA0499.3),
NFATC1 (MA0624.3), NFATC2 (MA0152.3), TEAD1 (MA0090.4).

**General regulatory / core promoter:** TBP/TATA (MA0108.3), SP1/GC-box
(MA0079.5), NRF1 (MA0506.3), YY1 (MA0095.4), CTCF (MA0139.2), NFKB1 (MA0105.4),
STAT3 (MA0144.3), TP53 (MA0106.3), E2F1 (MA0024.3).

## Honest labeling

A PWM hit means the local sequence resembles a transcription factor's known
binding preference above a relative-score threshold. It is a sequence-pattern
match, not a measured binding event, an occupancy call, or an expression assay.
