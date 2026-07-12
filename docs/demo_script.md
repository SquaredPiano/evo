# Proteus - 2:00 Demo Script

**Product name: Proteus.** Everything below is real and honest - no overclaiming.
The voiceover is the master clock (~293 words, calm ~150 wpm → lands at 2:00). Cut video under it.
Emphasis words are **bold**. `( · )` marks a deliberate micro-pause. `[ ]` are timing windows, not spoken.

---

## THE SCRIPT

**[0:00-0:11] — Hook**
A wet lab can take **weeks** to design a single gene.
( · ) Watch this.
I'm going to describe one in plain English - and Proteus is going to write it in **seconds**.

**[0:11-0:33] — Evo 2 generates, base by base**
*"Design a neuron-specific promoter for BDNF."* That's the whole prompt.
Now Evo 2 - a **forty-billion-parameter** DNA foundation model, trained on **nine-point-three trillion nucleotides** across all of life - starts writing. Base by base. **Live**, on NVIDIA.
And this stripe? ( · ) That's the model's **own confidence** in every base it just wrote. Real probabilities, streamed in real time.

**[0:33-0:49] — ESMFold structure**
From that sequence, ESMFold predicts the protein it builds - in **three dimensions**.
The color is confidence, residue by residue: blue, the model is sure; orange, less so.
Ribbons. Side chains. Hydrogen bonds. ( · ) Not a cartoon - a **structure**.

**[0:49-1:09] — The loop: regenerate a region, refold**
Now the part I love.
I select **one region** ( · ) and ask Evo 2 to regenerate just those bases.
It rewrites them, splices them back in - and the whole protein **refolds**, live.
And every new base carries its own confidence again. The model isn't guessing behind a spinner. It's **showing its work**.

**[1:09-1:38] — Helio acts, and the real paper opens**
Meet Helio - an agent that **acts**, not just chats.
I ask it to explain this region. It reads the model's signal, then pulls current research - **real papers**, from this year, retrieved and ranked live.
And here's the thing every demo is afraid to do. ( · ) I'm going to **click one**.
That's a real study - opening right now, in a real browser. ( · ) Nothing here is a mockup. **This is running.**

**[1:38-1:53] — The science underneath**
And under all of it, real science: JASPAR motif models, published CRISPR off-target scoring, melting temperature, primer design, RNA structure.
Every number **computed**. Every method **named**. ( · ) And two real folds, side by side, to compare.

**[1:53-2:00] — Close**
Proteus.
An IDE for the **code of life**.
The design half of the lab - ( · ) from weeks, to **seconds**.

> Word count: **293** words. At ~150 wpm = ~1:57 of speech; the marked micro-pauses and beat breaks carry it to a clean **2:00**.

---

## 3 ALTERNATE HOOKS (first ~10s — pick one)

1. **The dare (default above).**
   "A wet lab can take weeks to design a single gene. ( · ) Watch this. I'm going to describe one in plain English - and Proteus is going to write it in seconds."

2. **The reframe.**
   "We learned to read DNA decades ago. ( · ) We're still terrible at writing it. Proteus is an IDE for writing the code of life - and it starts with a sentence."

3. **The cold open (no setup - action first).**
   "This is a working gene, being designed from scratch, in front of you, right now. One sentence of English in - and a real, folded protein out. Let me show you how."

## 2 ALTERNATE CLOSERS (last ~7s — pick one)

1. **The tagline (default above).**
   "Proteus. ( · ) An IDE for the code of life. The design half of the lab - from weeks, to seconds."

2. **The turn.**
   "For a century, biology was something you ran. ( · ) Proteus makes it something you **write**. This is Proteus."

---

## DELIVERY + MUSIC

- **Tone:** calm, clinical, quietly certain - a scientist who already knows it works. Never a pitch. Let the screen do the wowing; your job is to point.
- **Pace:** ~150 wpm. Slow down and *lean in* on the bold words. The two turns - "Now the part I love" (0:49) and "I'm going to click one" (1:25) - get a real breath before them; don't rush the paper-opening beat, that single line is what flips a skeptic.
- **Breathe:** at every blank line between beats. Full stop, quarter-second, next beat. The `( · )` marks are shorter catches inside a line.
- **Music:** warm minimal cinematic-ambient, soft low pulse, ~90-100 BPM. Keep it under the voice (~-18 LUFS). Let it **build** quietly through the regenerate loop (0:49), hold tension under "this is running" (1:33), then **drop** slightly at 1:52 so "Proteus" lands in near-silence. Subtle UI click SFX on each action (type, generate, regenerate, select, click-paper). No swells that fight the narration.

---

## SCREEN RECORDING GUIDE (step by step)

**The core idea:** do NOT record the screen live against the audio. Record each clip separately, as long as you need. Then in iMovie you drop each clip under its audio window and speed it up or trim it. The audio is the fixed 2:00 clock; the video bends to fit.

### The generation-is-slow fix (read this first)
Generation and folding take a while. You never show them in real time. Pick ONE:
- **Speed-up (easiest):** record the whole thing once (let generation run 30-60s), then in iMovie set that clip to 400-600% speed so it collapses into ~10-15s. The bases visibly flying by looks better than real time anyway.
- **Snippet + jump-cut:** record only the first ~6-8s of streaming (bases appearing), then hard-cut straight to the finished result screen. You do not owe the viewer the full wait.
Use the same trick for the ESMFold fold: show it start, jump-cut to the finished 3D.

### Do this BEFORE you hit record (prep)
1. **Light mode on**, browser full-screen, clean (no bookmarks bar / notifications). Same window size for every clip.
2. **Pre-warm the papers for your gene.** The script says BDNF, but only BRCA1 / TP53 / CFTR are pre-loaded. Either (a) change the prompt in your recording to one of those, or (b) run this once in the backend first so BDNF papers are instant on camera:
   `python -m scripts.ingest_literature BDNF`
   The paper MUST open with zero lag - that beat is the whole demo.
3. **Do one full practice run** end-to-end so you know the flow and have a good candidate. Note: papers only appear on a region you have REGENERATED, so your regenerate step (Shot 4) must come before the explain-and-open-paper step (Shot 5) - which is the natural order below.
4. Have the guide sequence be a GENERATED one (not pasted) - that is where the per-base confidence is genuinely real.

### Record these clips, in this order
Record each generously (a few extra seconds of headroom each side). One slow, smooth zoom per clip.

**SHOT 1 - Home + prompt** (fills audio 0:00-0:11)
Screen: the Proteus home / composer (the design input). Action: type the goal, e.g. *"Design a neuron-specific promoter for BDNF"*, then click Generate. Record ~12s. Slow-zoom into the composer as you type.

**SHOT 2 - Generation streaming** (fills 0:11-0:33)
Screen: the pipeline running - DNA streaming base by base, the per-base confidence stripe filling in, retrieval chips ticking. Action: none, just let it run. Record the WHOLE thing (30-60s is fine). In iMovie: speed it 4-6x to fit the window; keep the last ~3s at 1x as it completes and lands on the overview. (Or use the snippet + jump-cut trick.)

**SHOT 3 - The 3D structure** (fills 0:33-0:49)
Screen: after it completes, open the Structure view (sidebar). Action: slowly drag to orbit the folded protein; hover one residue so its side chain + label pop. Record ~20s. If it is still folding, capture the "Folding with ESMFold" state for ~2s then jump-cut to the finished fold.

**SHOT 4 - Regenerate a region** (fills 0:49-1:09)
Screen: the Sequence view (the DNA with the colored region bars / annotation track). Action: click a region bar to select it (this opens Helio and pre-fills it), then click "Regenerate selected region" in Helio. Watch the result card + the diff, and the structure refold. Record the action + wait + result. In iMovie: speed 2x through the wait, land at 1x on the result card showing the real per-base confidence strip (labeled "real").

**SHOT 5 - Helio explains + OPEN A REAL PAPER** (fills 1:09-1:38) - the money shot, record it twice
Screen: same region, now regenerated. Action: in Helio click "Explain this region" - the plain-English card appears. Then hover that region on the track so the evidence card with paper links shows. Click a paper link - a real study opens in a new browser tab. HOLD on the open paper ~1.5-2s. Record at 1x; do not rush the click. This one clip is what convinces the judge, so do a couple takes and keep the best.

**SHOT 6 - The science, fast** (fills 1:38-1:53)
Screen: the Tools panel tabs (in the Sequence view rail). Action: click through 3-4 tabs, ~3s each, zooming to the number: CRISPR (the specificity / CFD score), Tm, Structure (RNA) (the MFE), the regulatory / motif map. Then open the Compare view (two structures side by side). Record ~20s. In iMovie: 1.5x through the tabs, end on Compare at 1x.

**SHOT 7 - Close** (fills 1:53-2:00)
Screen: the Proteus wordmark - either the landing page hero or the app header. Record ~8s, static or a very slow push-in. Let it breathe; fade the music tail.

### Then assemble (iMovie)
1. Lay the locked voiceover across the timeline. Add the music bed low underneath.
2. Drop each Shot under its window, in order. Apply the speed / jump-cut from each shot so the action fills its window (Shot 2 and 4 are the ones you speed up).
3. Add subtle UI click SFX on each action; burn in captions from THE SCRIPT above (many judges watch muted).
4. Watch it once end to end. If a beat runs long, trim the video (never the audio).

**Honesty guardrails (never say):**
- Not "Helix" (old name) - it's **Proteus**.
- Not "Helio is powered by Gemini." Helio (the agent) = gpt-4o-mini via OpenRouter. Gemini (2.5-flash) powers the literature **synthesis**.
- Not "9.3 trillion base pairs" → "**nucleotides**."
- CRISPR off-target is CFD (Doench 2016) + MIT (Hsu 2013) **against a supplied reference** - not genome-wide.
- The 4D functional/tissue/novelty numbers are **signals**, not assays - never "clinical" or "validated."
