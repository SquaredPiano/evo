"use client";

import { useRef } from "react";
import Link from "next/link";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import { ArrowRight, Dna, Gauge, Boxes, Sparkles } from "lucide-react";
import EvoLogo from "@/components/brand/EvoLogo";

gsap.registerPlugin(ScrollTrigger);

const BASE_COLOR: Record<string, string> = {
  A: "var(--base-a)",
  T: "var(--base-t)",
  C: "var(--base-c)",
  G: "var(--base-g)",
};

const HERO_STRIP = "ATGGCTAGCTAGGCATTACGGCATGCATTAGCGGCTATTACGCATGGCTAAGCTTGCAT".split("");

const STEPS = [
  {
    icon: <Dna size={22} strokeWidth={2.5} />,
    kicker: "01 / Generate",
    title: "Design in plain English",
    body: "Describe the element you want. Evo 2 streams candidate sequences base-by-base over a live socket — no spinners, no black box.",
  },
  {
    icon: <Gauge size={22} strokeWidth={2.5} />,
    kicker: "02 / Score",
    title: "Four labeled heuristics",
    body: "Composition/motif scores for function, tissue motifs, panel off-target overlap, and novelty — clearly marked as demo metrics, not clinical predictions.",
  },
  {
    icon: <Boxes size={22} strokeWidth={2.5} />,
    kicker: "03 / Fold",
    title: "Sequence to structure",
    body: "Top candidates fold through live ESMFold into 3D protein structures, coloured by per-residue confidence, rendered right in the browser.",
  },
  {
    icon: <Sparkles size={22} strokeWidth={2.5} />,
    kicker: "04 / Edit",
    title: "Click a base, feel the delta",
    body: "Type directly into the sequence. Single-base edits re-score in under two seconds; natural-language follow-ups rerun only the stages that changed.",
  },
];

export default function Home() {
  const main = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      gsap.fromTo(
        ".rise",
        { opacity: 0, y: 24 },
        {
          opacity: 1,
          y: 0,
          duration: 0.7,
          ease: "power3.out",
          stagger: 0.08,
          scrollTrigger: { trigger: ".rise", start: "top 85%" },
        }
      );
      const intro = gsap.timeline({ defaults: { ease: "power3.out" } });
      intro
        .fromTo(".h-tag", { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.5 })
        .fromTo(".h-line", { opacity: 0, y: 30 }, { opacity: 1, y: 0, stagger: 0.12, duration: 0.7 }, "-=0.2")
        .fromTo(".h-sub", { opacity: 0 }, { opacity: 1, duration: 0.5 }, "-=0.25")
        .fromTo(".h-cta > *", { opacity: 0, y: 10 }, { opacity: 1, y: 0, stagger: 0.08, duration: 0.4 }, "-=0.2")
        .fromTo(".h-base", { opacity: 0, y: 8 }, { opacity: 1, y: 0, stagger: 0.015, duration: 0.3 }, "-=0.3");

      gsap.utils.toArray<HTMLElement>(".step-row").forEach((row) => {
        gsap.fromTo(
          row,
          { opacity: 0, y: 40 },
          {
            opacity: 1,
            y: 0,
            duration: 0.7,
            ease: "power3.out",
            scrollTrigger: { trigger: row, start: "top 80%" },
          }
        );
      });
    },
    { scope: main }
  );

  return (
    <div ref={main} className="overflow-x-hidden font-sans" style={{ background: "var(--surface-base)", color: "var(--text-primary)" }}>
      {/* ── NAV ── */}
      <nav
        className="fixed top-0 w-full z-50 flex justify-between items-center px-6 md:px-10 h-16"
        style={{ background: "color-mix(in srgb, var(--surface-base) 88%, transparent)", backdropFilter: "blur(14px)", borderBottom: "1px solid var(--ghost-border)" }}
      >
        <EvoLogo size="md" />
        <div className="flex items-center gap-2">
          <a
            href="https://github.com/evo-genomics/evo"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full hidden sm:inline-flex items-center gap-2 px-4 py-2 text-[13px] font-semibold transition-smooth"
            style={{ color: "var(--text-secondary)" }}
          >
            GitHub
          </a>
          <Link
            href="/analyze"
            className="inline-flex rounded-full items-center gap-2 px-5 py-2.5 text-[12px] font-medium tracking-tight transition-smooth"
            style={{ background: "var(--honey-500)", color: "var(--ink)", border: "none", boxShadow: "0 8px 24px -8px rgba(245,158,11,0.45)" }}
          >
            Open IDE
          </Link>
        </div>
      </nav>

      {/* ═══ HERO ═══ */}
      <section className="gridlines relative min-h-screen flex flex-col items-center justify-center px-6 pt-20 pb-16 text-center">
        <p className="h-tag chip-honey mb-8">Evo 2 · 40B params · 9.3T base pairs</p>
        <h1 className="display max-w-5xl text-[clamp(2.8rem,8vw,6.5rem)] font-normal mb-8">
          <span className="h-line block">The genomic design IDE</span>
          <span className="h-line block">
            that <span className="italic" style={{ color: "var(--accent-bright)" }}>thinks out loud.</span>
          </span>
        </h1>
        <p className="h-sub max-w-xl text-[17px] md:text-[19px] leading-relaxed mb-10" style={{ color: "var(--text-secondary)" }}>
          Paste a sequence or describe a goal. Watch Evo 2 annotate, score, and fold it live — then click any base and feel the consequence in seconds.
        </p>
        <div className="h-cta flex flex-wrap gap-3 justify-center mb-16">
          <Link
            href="/analyze"
            className="inline-flex rounded-full items-center gap-2 px-8 py-4 text-[13px] font-medium tracking-tight transition-smooth hover:-translate-x-0.5 hover:-translate-y-0.5"
            style={{ background: "var(--ink)", color: "var(--cream)", border: "none", boxShadow: "0 16px 40px -12px rgba(15,15,15,0.35)" }}
          >
            Start designing <ArrowRight size={16} />
          </Link>
          <Link
            href="/analyze?view=input"
            className="inline-flex rounded-full items-center gap-2 px-8 py-4 text-[13px] font-medium tracking-tight transition-smooth"
            style={{ background: "var(--surface-raised)", color: "var(--text-primary)", border: "1px solid var(--ghost-border)", boxShadow: "var(--shadow-soft)" }}
          >
            Paste a sequence
          </Link>
        </div>

        {/* Live DNA strip */}
        <div className="w-full max-w-3xl">
          <div className="flex items-center justify-between mb-2 px-1">
            <span className="label-caps">chr17 · 43,044,295</span>
            <span className="label-caps">likelihood heatmap</span>
          </div>
          <div
            className="flex flex-wrap justify-center gap-[3px] p-4"
            style={{ background: "var(--surface-raised)", border: "1px solid var(--ghost-border)", boxShadow: "var(--shadow-soft)" }}
          >
            {HERO_STRIP.map((b, i) => (
              <span
                key={i}
                className="h-base font-mono text-[15px] md:text-[18px] font-bold w-[20px] md:w-[24px] h-[26px] md:h-[30px] flex items-center justify-center rounded-full"
                style={{ color: BASE_COLOR[b], background: `color-mix(in srgb, ${BASE_COLOR[b]} ${8 + (i % 5) * 6}%, transparent)` }}
              >
                {b}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ STEPS (alternating editorial rows) ═══ */}
      <section className="px-6 md:px-10 py-24" style={{ background: "var(--surface-raised)", borderTop: "1px solid var(--ghost-border)", borderBottom: "1px solid var(--ghost-border)" }}>
        <div className="max-w-5xl mx-auto">
          <p className="label-caps mb-3">How it works</p>
          <h2 className="display text-[clamp(2rem,4.5vw,3.5rem)] mb-16 max-w-2xl">
            An editor, a compiler, and a lab notebook — for DNA.
          </h2>
          <div className="flex flex-col gap-5">
            {STEPS.map((s) => (
              <div
                key={s.kicker}
                className="step-row grid grid-cols-1 md:grid-cols-[auto_1fr] gap-5 md:gap-8 items-start p-7 md:p-9 hover-lift"
                style={{ background: "var(--surface-base)", border: "1px solid var(--ghost-border)", boxShadow: "var(--shadow-soft)" }}
              >
                <div
                  className="inline-flex items-center justify-center w-14 h-14 shrink-0"
                  style={{ background: "var(--ink)", color: "var(--honey-400)", border: "1px solid var(--ghost-border)" }}
                >
                  {s.icon}
                </div>
                <div>
                  <p className="label-caps mb-2" style={{ color: "var(--accent-bright)" }}>{s.kicker}</p>
                  <h3 className="text-2xl md:text-3xl font-bold tracking-tight mb-2">{s.title}</h3>
                  <p className="text-[15px] md:text-[16px] leading-relaxed max-w-2xl" style={{ color: "var(--text-secondary)" }}>{s.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ IMPACT ═══ */}
      <section className="px-6 py-32 text-center gridlines">
        <div className="rise max-w-4xl mx-auto">
          <p className="label-caps mb-6">The bottleneck</p>
          <h2 className="display text-[clamp(2.6rem,7vw,5.5rem)] leading-[0.98]">
            From weeks in a wet lab<br />
            <span className="italic" style={{ color: "var(--accent-bright)" }}>to minutes in a tab.</span>
          </h2>
        </div>
      </section>

      {/* ═══ CTA ═══ */}
      <section className="px-6 py-24" style={{ background: "var(--ink)", color: "var(--cream)" }}>
        <div className="rise max-w-3xl mx-auto text-center">
          <h2 className="display text-[clamp(2rem,4.5vw,3.4rem)] mb-4">
            The interface layer genomic design has been missing.
          </h2>
          <p className="text-[16px] mb-10" style={{ color: "var(--rail-muted)" }}>
            Evo 2 can generate DNA (NIM), ESMFold folds coding ORFs when live, NCBI/ClinVar supply context cards, and the copilot runs real tools — scores stay labeled as heuristics until a forward endpoint exists.
          </p>
          <Link
            href="/analyze"
            className="inline-flex rounded-full items-center gap-2 px-9 py-4 text-[13px] font-medium tracking-tight transition-smooth hover:-translate-x-0.5 hover:-translate-y-0.5"
            style={{ background: "var(--honey-500)", color: "var(--ink)", border: "none", boxShadow: "0 12px 30px -10px rgba(245,158,11,0.4)" }}
          >
            Open Evo IDE <ArrowRight size={18} />
          </Link>
        </div>
      </section>

      {/* ── FOOTER ── */}
      <footer className="py-10 px-8" style={{ background: "var(--surface-base)", borderTop: "1px solid var(--ghost-border)" }}>
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row justify-between items-center gap-4">
          <EvoLogo size="sm" />
          <span className="label-caps">Genomic Design IDE · Powered by Evo 2 + ESMFold</span>
        </div>
      </footer>
    </div>
  );
}
