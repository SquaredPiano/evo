"""Regulatory visualization payload builder for non-coding design modes.

Regulatory features are real transcription-factor binding-site matches found by
position weight matrix (PWM) scanning against curated JASPAR CORE 2024 vertebrate
matrices (see ``services.motifs``), not short-substring pattern matches. Each
feature is a PWM hit: name = TF, [start, end) = the matched window, score = the
PWM relative score in [0, 1]. A hit means the local sequence resembles that TF's
known binding preference, not that the factor binds or is active here.
"""

from __future__ import annotations

from dataclasses import dataclass

# Relative-score threshold for reporting a binding site on the regulatory map.
# Matches the default used by services.motifs.scan_sequence.
_PWM_THRESHOLD = 0.8


@dataclass(frozen=True)
class RegulatoryFeature:
    name: str
    start: int
    end: int
    score: float


@dataclass(frozen=True)
class GCWindow:
    start: int
    end: int
    gc: float


def _window_gc(sequence: str, start: int, end: int) -> float:
    window = sequence[start:end]
    if not window:
        return 0.0
    gc_count = sum(1 for base in window if base in {"G", "C"})
    return gc_count / len(window)


def build_regulatory_map(sequence: str) -> dict[str, object]:
    seq = sequence.upper()
    features: list[RegulatoryFeature] = []

    # Real PWM binding-site hits on both strands. The name is the TF, the score
    # is the PWM relative score in [0, 1]. Scanning is best-effort: if the motif
    # backend is unavailable the map still returns GC/hotspot structure.
    try:
        from services.motifs import scan_sequence

        for hit in scan_sequence(seq, threshold=_PWM_THRESHOLD):
            features.append(
                RegulatoryFeature(
                    name=hit.tf_name,
                    start=hit.start,
                    end=hit.end,
                    score=round(float(hit.relative_score), 4),
                )
            )
    except Exception:  # pragma: no cover - defensive; scanning is best-effort
        features = []

    features.sort(key=lambda f: (f.start, f.name))

    window_size = 24
    step = 6
    windows: list[GCWindow] = []
    for start in range(0, max(1, len(seq) - window_size + 1), step):
        end = min(len(seq), start + window_size)
        windows.append(GCWindow(start=start, end=end, gc=round(_window_gc(seq, start, end), 4)))

    global_gc = round(_window_gc(seq, 0, len(seq)), 4)

    # Build coarse hotspot map (0-1) for quick frontend rendering.
    hotspots: list[float] = [0.0 for _ in seq]
    for feature in features:
        for pos in range(feature.start, min(feature.end, len(hotspots))):
            hotspots[pos] = max(hotspots[pos], feature.score)

    return {
        "sequence_length": len(seq),
        "gc_content": global_gc,
        "features": [
            {
                "name": feature.name,
                "start": feature.start,
                "end": feature.end,
                "score": feature.score,
            }
            for feature in features
        ],
        "gc_windows": [
            {
                "start": window.start,
                "end": window.end,
                "gc": window.gc,
            }
            for window in windows
        ],
        "hotspots": hotspots,
    }
