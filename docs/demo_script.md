# Proteus - 2:00 Demo Script (v2)

Exactly 120 seconds. Audio is the master clock; video is sped/trimmed to fit each beat (see the SPEED column). Product name is **Proteus** (not Helix). Everything claimed here is real and honest - do not overclaim.

---

## The approach (read first)

- **Audio is the master.** Record the voiceover to the cadence below (about 145 words per minute, calm and confident). It will land near 2:00. Lock it, then cut video under it.
- **Video is elastic.** Real actions take variable time (generation streams for 15 to 40s, ESMFold folds for 10 to 90s). Record each action generously with Cursorful, then in iMovie SPEED UP or JUMP-CUT the slow parts to fit the narration window. The SPEED column tells you the factor per beat.
- **One honey accent, dark-free UI.** The app is light mode; the 3D scene is dark (that is a scientific-viz convention, fine). Keep zooms smooth and slow.
- **Burn in captions.** The old video had none; many judges watch muted. Add clean subtitles from this script.

Music: warm minimal / cinematic-ambient electronic with a soft low pulse, roughly 90 to 100 BPM, that builds subtly and drops slightly at 1:52 for the close. Keep it low, about -18 LUFS under the voice. Add subtle UI click SFX on each action (type, generate, regenerate, select).

---

## Beat sheet (Time | Voiceover | On-screen action (Cursorful) | Edit / SPEED | Proof on screen)

| Time | Voiceover (say this) | Cursorful action | Edit / SPEED | Proof beat |
|---|---|---|---|---|
| 0:00-0:10 | "Designing a gene the old way takes a wet lab weeks. Proteus drafts one in seconds. I just describe what I want, in plain English." | Land on the clean home page. Type a real goal, e.g. "Design a neuron-specific promoter for BDNF." Hit generate. | 1x. Slow zoom into the composer as you type. | Clean home UI; a concrete, real design goal. |
| 0:10-0:30 | "Evo 2, a forty-billion-parameter DNA foundation model, running live on NVIDIA, writes the sequence base by base. This stripe is the model's own confidence for every base it generated, streamed in real time." | The pipeline streams: retrieval chips, then DNA generating base-by-base with the per-base confidence stripe filling in. | Real generation may take 20 to 40s. SPEED 2x to 3x so streaming visibly fills within the 20s window. Keep the last 3s at 1x. | The "Evo 2 - NIM live" engine pill. The confidence stripe = real sampled probabilities. |
| 0:30-0:48 | "For the protein it encodes, ESMFold predicts the three-dimensional fold. Color is per-residue confidence: blue is sure, orange is uncertain. Ribbons, side chains, hydrogen bonds - the real structure, not a bead on a string." | Cut to the Structure view. Slow-orbit the folded protein. Hover a residue to show the side chain + label. | Folding can take 30 to 90s. JUMP-CUT: show the fold starting, hard cut to the finished 3D scene. Then 1x slow orbit. | Mol*-grade viewer: cartoon + pLDDT gradient + side chains + pLDDT legend. |
| 0:48-1:10 | "Now the point. I select a region and ask Evo 2 to regenerate it. It rewrites just those bases, splices them back in, and refolds. The confidence here is genuine Evo 2 model confidence for the bases it just wrote." | In the Sequence view, select a region (click a region bar). In Helio, click "Regenerate selected region." Watch the diff + refold. | Regen + refold take time. SPEED 2x through the wait; land 1x on the result card + diff. | The regen result card: real per-base Evo 2 confidence strip (indigo, labeled "real"), engine = NIM. |
| 1:10-1:33 | "Helio is an agent - it doesn't just answer, it acts. I ask it to explain this region. It reads the model's own signal, and pulls current research, retrieved and ranked live, so every claim is grounded in a real paper you can open." | Click "Explain this region." The RegionExplanationCard appears. Hover the region on the track: the evidence card shows real paper links. Click one - a real PubMed/paper page opens briefly. | 1x for the explanation card. Quick 1.5x on the hover-to-paper. The opened paper is your hard proof - hold it 1.5s. | Plain-English region card + clickable real research links (RAG). Opening a real paper = undeniable proof. |
| 1:33-1:52 | "Underneath is real science: JASPAR motif models, ESMFold, published CRISPR off-target scoring, melting temperature, primer design, pairwise alignment. Every number is computed, honest, and labeled for what it is." | Fast, smooth montage across the Tools tabs: PWM/regulatory map, CRISPR (CFD score), Primers (Tm), Structure (RNA MFE). Then the Compare view side-by-side. | 1.5x montage, ~3s per tab, smooth zoom to each number. End on Compare at 1x. | Each tab shows a real computed number with an honest method label. Compare = two real ESMFold structures. |
| 1:52-2:00 | "Proteus. An IDE for designing life's code. The design half of the lab - from weeks, to seconds." | Cut to the Proteus wordmark / a clean hero frame. Fade music tail. | 1x. Let it breathe. | The name. Calm confidence. |

Total narration is about 290 words over 120s (~145 wpm) - leaves room for the pauses marked by the beat breaks. Breathe at every row boundary.

---

## Cadence notes (delivery)

- Calm, clinical, confident. Not hype. Let the product do the wowing.
- Emphasize these words: "seconds", "base by base", "real time", "regenerate", "acts", "real paper", "computed", "honest".
- Micro-pause (0.4s) before "Now the point." (0:48) and before "Proteus." (1:52) - those are the two turns.
- Do not rush the paper-opening beat (1:25ish). That single real link is what flips a skeptical judge.

## What blows a judge's mind (make sure these land)

1. Real generation, base-by-base, from a 40B model - visible, not a spinner.
2. Regenerate a *region* and it refolds - the closed loop.
3. Real Evo 2 confidence on the bases it just wrote (labeled "real").
4. An agent that *acts* + grounds its answer in a **real paper you can open**.
5. The rigor montage: published methods (JASPAR, CFD, ESMFold), each labeled honestly.

## Honesty guardrails (never say)

- Do NOT say "Helio is powered by Gemini." Helio (the agent) = gpt-4o-mini via OpenRouter. Gemini powers the literature synthesis. If you name the stack: "Evo 2 via NVIDIA NIM for DNA, ESMFold for structure, Gemini for literature synthesis, an OpenRouter agent for Helio."
- Do NOT call the 4D functional/tissue/off-target/novelty scores clinical or validated. They are composition and motif heuristics (tissue now uses real JASPAR PWMs). Say "signals", not "assays".
- Do NOT say "9.3 trillion base pairs." Say "9.3 trillion nucleotides."
- Do NOT imply the CRISPR off-target is genome-wide. It is CFD/MIT against the supplied reference.
- The per-base confidence is genuinely real for GENERATED / regenerated bases (sampled probabilities). For pasted, un-regenerated sequence the per-position value is a composition signal - so demo the flow on GENERATED sequence, which is honest and strongest.

## Recording workflow

1. Record the voiceover first, to the cadence above. Lock it as the master track.
2. Screen-record each beat's action with Cursorful (generous length, smooth zooms). Do a clean run of: generate, fold, select region, regenerate, explain-region, hover-to-paper (open one), the tools montage, compare.
3. In iMovie: lay the voiceover on top, drop each clip under its beat, apply the SPEED factor / jump cuts from the table so each action fills its window. Add the music bed low, UI click SFX on actions, and burnt-in captions from this script.
4. Pre-warm the literature index for your demo gene beforehand (BRCA1 / TP53 / CFTR are pre-loaded; for any other gene run the ingest once) so the papers appear instantly on camera.
