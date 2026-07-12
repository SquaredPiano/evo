"use client";

/**
 * Proteus Brand Mark + Wordmark
 *
 * The mark is a single-stroke arc: a smooth curve from thick to thin,
 * suggesting a genomic turn and a precision measurement instrument.
 * An interface glyph, not a literal DNA double helix.
 *
 * Usage:
 *   <ProteusLogo />                    - mark + wordmark (nav default)
 *   <ProteusLogo variant="mark" />     - mark only (favicon, app icon, collapsed nav)
 *   <ProteusLogo variant="wordmark" /> - wordmark only (footer, docs)
 *   <ProteusLogo size="lg" />          - larger (hero, splash)
 *
 * Color: uses currentColor. Set the parent's text color.
 */

interface ProteusLogoProps {
  variant?: "full" | "mark" | "wordmark";
  size?: "sm" | "md" | "lg";
  className?: string;
}

const SIZES = {
  sm: { mark: 18, text: "text-[14px]", gap: "gap-1.5" },
  md: { mark: 22, text: "text-[17px]", gap: "gap-2" },
  lg: { mark: 32, text: "text-[26px]", gap: "gap-3" },
};

function Mark({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* The arc: a single smooth curve, thick to thin, suggesting a genomic turn */}
      <path
        d="M6 26C6 26 8 8 16 8C24 8 26 20 16 20C10 20 10 14 16 12"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Small dot at the end: the edit cursor / active position */}
      <circle cx="16" cy="12" r="1.5" fill="currentColor" />
    </svg>
  );
}

function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={`font-semibold tracking-[-0.03em] select-none ${className ?? ""}`}
      style={{ fontFamily: "var(--font-sans), system-ui, sans-serif" }}
    >
      Proteus
    </span>
  );
}

export default function ProteusLogo({
  variant = "full",
  size = "md",
  className = "",
}: ProteusLogoProps) {
  const s = SIZES[size];

  if (variant === "mark") {
    return (
      <span className={`inline-flex items-center ${className}`}>
        <Mark size={s.mark} />
      </span>
    );
  }

  if (variant === "wordmark") {
    return <Wordmark className={`${s.text} ${className}`} />;
  }

  return (
    <span className={`inline-flex items-center ${s.gap} ${className}`}>
      <Mark size={s.mark} />
      <Wordmark className={s.text} />
    </span>
  );
}
