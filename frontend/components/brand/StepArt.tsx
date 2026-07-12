/**
 * StepArt — bespoke on-brand illustrations for the landing "How it works" steps.
 * Replaces the old flat-black icon squares. Each is a self-contained inline SVG
 * (no external assets) using the app's DNA base + honey palette, so the four
 * tiles read as a cohesive illustrated set rather than placeholder boxes.
 */

type StepArtProps = { variant: "generate" | "score" | "fold" | "edit" };

const STROKE = "var(--ink)";
const HONEY = "var(--honey-500)";
const HONEY_DEEP = "var(--honey-600)";
const A = "var(--base-a)";
const T = "var(--base-t)";
const C = "var(--base-c)";
const G = "var(--base-g)";

function Generate() {
  // DNA double helix: two crossing strands with base-paired rungs.
  return (
    <svg viewBox="0 0 40 40" width="32" height="32" fill="none" aria-hidden="true">
      <path d="M13 5C27 13 13 27 27 35" stroke={STROKE} strokeWidth="2.4" strokeLinecap="round" />
      <path d="M27 5C13 13 27 27 13 35" stroke={HONEY_DEEP} strokeWidth="2.4" strokeLinecap="round" />
      <line x1="15.5" y1="11" x2="24.5" y2="11" stroke={A} strokeWidth="2.2" strokeLinecap="round" />
      <line x1="15.5" y1="20" x2="24.5" y2="20" stroke={C} strokeWidth="2.2" strokeLinecap="round" />
      <line x1="15.5" y1="29" x2="24.5" y2="29" stroke={T} strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}

function Score() {
  // Four signal bars — the four composition/motif scores.
  return (
    <svg viewBox="0 0 40 40" width="32" height="32" fill="none" aria-hidden="true">
      <line x1="6" y1="33" x2="34" y2="33" stroke="var(--ghost-border)" strokeWidth="2" strokeLinecap="round" />
      <rect x="7" y="22" width="5.5" height="10" rx="2" fill={A} />
      <rect x="15.5" y="13" width="5.5" height="19" rx="2" fill={HONEY} />
      <rect x="24" y="18" width="5.5" height="14" rx="2" fill={C} />
      <rect x="32.5" y="25" width="5.5" height="7" rx="2" fill={G} />
    </svg>
  );
}

function Fold() {
  // Folded protein backbone with residue nodes.
  return (
    <svg viewBox="0 0 40 40" width="32" height="32" fill="none" aria-hidden="true">
      <path
        d="M8 30C6 18 18 15 20 22C22 29 34 27 32 15"
        stroke={HONEY_DEEP}
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
      <circle cx="8" cy="30" r="2.6" fill={C} />
      <circle cx="20" cy="22" r="2.6" fill={G} />
      <circle cx="32" cy="15" r="2.6" fill={T} />
    </svg>
  );
}

function Edit() {
  // A base cell with a text caret — the inline editor.
  return (
    <svg viewBox="0 0 40 40" width="32" height="32" fill="none" aria-hidden="true">
      <rect x="7" y="10" width="20" height="20" rx="4" stroke={STROKE} strokeWidth="2.2" />
      {/* letter "A" — a base in the cell */}
      <path d="M13 25L17 15L21 25" stroke={A} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M14.3 21.5H19.7" stroke={A} strokeWidth="2.4" strokeLinecap="round" />
      {/* blinking text caret to the right */}
      <line x1="31" y1="11" x2="31" y2="29" stroke={HONEY_DEEP} strokeWidth="2.6" strokeLinecap="round" />
    </svg>
  );
}

export default function StepArt({ variant }: StepArtProps) {
  const art = { generate: <Generate />, score: <Score />, fold: <Fold />, edit: <Edit /> }[variant];
  return (
    <div
      className="inline-flex items-center justify-center w-16 h-16 shrink-0 rounded-2xl"
      style={{
        background: "linear-gradient(135deg, var(--honey-50), var(--surface-raised))",
        border: "1px solid var(--honey-200)",
        boxShadow: "0 6px 18px -10px rgba(217,119,6,0.45)",
      }}
    >
      {art}
    </div>
  );
}
