/**
 * Numeric formatting helpers.
 */

/**
 * Format a log-likelihood delta with enough precision that the number matches
 * its impact label. Single-base deltas on the composition/model signal are often
 * tiny (near the +/-0.001 impact threshold), so rounding to 2 decimals would
 * collapse distinct values to "0.00" and make the label look arbitrary. This
 * shows 4 decimals for small magnitudes and scientific notation for extremely
 * small ones, while keeping 2 decimals for larger, clearly-nonzero deltas.
 *
 * Returns the value WITHOUT a leading "+" (callers add their own sign prefix);
 * negatives keep their "-".
 */
export function formatDelta(x: number): string {
  if (!Number.isFinite(x)) return "-";
  const a = Math.abs(x);
  if (a === 0) return "0.0000";
  if (a >= 0.1) return x.toFixed(2);
  if (a >= 0.001) return x.toFixed(4);
  return x.toExponential(2);
}
