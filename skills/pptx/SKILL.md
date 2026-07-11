---
name: pptx
description: >-
  Create, edit, and export PowerPoint presentations (.pptx) with the deterministic
  `ppt` CLI. Use for ANY request that produces slides, a deck, a presentation, or a
  .pptx file. Write the DeckSpec to a JSON file and run `ppt` yourself to produce the
  .pptx — never just print JSON for the user to run, and never use python-pptx, raw
  pptxgenjs, or built-in document/slide generation. The engine owns rendering; your job
  is to author the DeckSpec file and drive the CLI.
---

# Building presentations with the `ppt` engine

This project renders slides from a single JSON **DeckSpec** — the source of truth — into
a `.pptx` (and an HTML preview). Rendering is deterministic: the same DeckSpec always
produces the same deck. **You write and edit the DeckSpec file; the engine renders it.**

> **Operate the CLI yourself — don't just draft in chat.** Use your file tool to write the
> DeckSpec to a real file (e.g. `deck.json`), then use your shell to run `ppt validate` and
> `ppt export`. The deliverable is the exported **`.pptx`** (report its path) — *not* a JSON
> blob in your reply, and *not* a list of commands for the user to run. Run every `ppt`
> command yourself. Only stop to ask the user when a command needs something you genuinely
> don't have (e.g. a real image file). If you truly cannot run shell commands or write files
> in this environment, say so plainly instead of pasting a DeckSpec and stopping.

> **Do not** write `python-pptx`, raw `pptxgenjs`, OOXML/XML, or use any built-in
> slide-generation tool. Those produce inconsistent, off-theme decks with broken fonts.
> The only correct path is: write `deck.json` → `ppt validate` → `ppt export` → deliver the `.pptx`.

## The loop — you run every step

You execute each step (write files with your file tool, run commands with your shell). You do
**not** print these for the user to run:

```
ppt info + ppt patterns  →  OUTLINE the whole deck (each slide → a pattern)
   →  write deck.json (assemble the patterns; vary them; ~6–12 slides)  →  ppt validate --json
   →  fix path:message errors  →  ppt export -o deck.pptx  (→ ppt preview)  →  deliver the .pptx
```

### 1. Discover, then plan the WHOLE deck first

Don't build slide-by-slide and stop early. First see what's available, then **outline the entire
deck before writing any JSON**:

```bash
ppt info        # names: themes, archetypes, widgets
ppt patterns    # the menu of ready-made slide compositions — ALWAYS run this and compose from it
```

**Outline the deck** as a list of slides, each mapped to a pattern. A real deck has a narrative
arc and is usually **~6–12 slides with VARIED patterns** — for example:

```
1 Title cover   2 Agenda   3 Executive summary   4 Key message + chart
5 Three labeled columns   6 Stat band   7 Wide image band   8 Two-up comparison
9 Timeline   10 Big statement (close)
```

Write this outline down (in chat is fine) before authoring. **A deck of 1–2 slides, or one where
every slide is the same archetype, is a failure** — cover the user's whole topic and vary the
patterns across the deck.

Only **after** the outline, look up exact shapes — targeted, never the full `ppt schema --json`:

```bash
ppt patterns --name "Stat band"   # one pattern's ready slide — copy it and fill in real text
ppt schema --archetype Dashboard  # an archetype's regions + a fill-in example (for custom slides)
ppt schema --widget KpiCard       # one widget's exact props
ppt schema --edits                # edit ops + fields (for `ppt update`)
```

### 2. Write the DeckSpec to a file

**Assemble the file from your outline.** For each planned slide, take its pattern's slide
(`ppt patterns --name "<name>"`), give it unique `id`s, and replace the placeholder text with
real content; combine all of them into one `deck.json`. **Save it to a real file with your file
tool** (e.g. `deck.json`) — do not paste the whole spec into your reply and stop. The shape:

```jsonc
{
  "version": 1,
  "theme": "startup",          // one of ppt info themes
  "size": "16:9",              // or "4:3"
  "meta": { "title": "Q3 Review" },
  "slides": [
    {
      "id": "cover",            // unique within the deck
      "archetype": "TitleSlide",// from ppt info; defines the available regions
      "widgets": [
        { "id": "t", "type": "Title", "region": "title", "props": { "text": "Q3 Review" } }
      ]
    }
  ]
}
```

Rules:
- Every `widget.region` MUST be a region the slide's archetype declares (see `ppt schema`).
- Every `widget.type` MUST be a registered widget; its `props` MUST match that widget's schema.
- `id`s are unique within their scope (slides in the deck; widgets in a slide).
- `variant` is optional — omit it and the theme picks one.
- `notes` is optional — see *Presenter script* below.

### Presenter script (speaker notes)

`notes` is the **verbatim script the presenter reads aloud** — the actual spoken words, in full
sentences, as if talking to the audience. It is **not** a memo, an outline, or stage directions.

- Write natural spoken prose, ~2–5 sentences for a normal slide — readable word-for-word at the
  podium.
- ✅ `"Last quarter we set out to cut onboarding time in half. We didn't just hit that goal — we
  beat it, landing at forty-seven percent faster, and I'll show you exactly how the team got
  there."`
- ❌ `"Open with the problem, then mention the 47% number."` — that's a reminder, not a script.
- Spell things the way they're spoken ("forty-seven percent", "three-x", "Q3" → "the third
  quarter") so it reads naturally aloud.

It is written to PowerPoint's **Notes** pane (visible to the presenter, never on the slide) and
shown beneath the slide in `ppt preview`.

```jsonc
{
  "id": "cover",
  "archetype": "TitleSlide",
  "notes": "Good morning, everyone — thanks for being here. Before we get into the numbers, I want to start with the problem we set out to solve this quarter, because it's the reason everything else matters.",
  "widgets": [ /* ... */ ]
}
```

Set or change it later with the `setNotes` edit op (pass `""` to clear it):

```json
{ "op": "setNotes", "slideId": "cover", "notes": "Welcome, everyone. It's great to see you all here. Let me quickly introduce the team behind this work, and then we'll dive into what we found." }
```

Fastest starts (all via the CLI — no files to locate): `ppt new -a <archetype> -o deck.json`
scaffolds a valid deck for an archetype, and `ppt patterns` lists curated slide patterns (see
*Design* below). Use `ppt schema --archetype <id>` and `ppt schema --widget <type>` for exact
shapes.

### 3. Validate and fix

```bash
ppt validate deck.json --json
```

On failure you get `{ ok: false, errors: [{ path, message, code }] }`. Fix each `path` and
re-run until `{ ok: true }`. Do not export an invalid deck.

### 4. Export — this produces the deliverable

Run the export yourself, then hand the user the resulting `.pptx` (its path) — not the command:

```bash
ppt export deck.json -o deck.pptx
ppt preview deck.json -d preview/      # fast HTML look without opening PowerPoint
```

### 5. Revise with structured edits — don't rewrite the file

Apply targeted, deterministic edits instead of regenerating the whole DeckSpec:

```bash
ppt update deck.json --edit edit.json -o deck.json --export deck.pptx
```

`edit.json` is `{ "edits": [ ... ] }` with ops: `setTheme`, `setMeta`, `addSlide`,
`removeSlide`, `reorderSlide`, `addWidget`, `removeWidget`, `moveWidget`, `setProps`,
`setNotes`, `setArchetype`, `setSlideBackground`, `setVariant`. Each
edit is re-validated, so a bad edit is rejected and the deck is never left broken. Run
`ppt schema --edits` for each op's exact fields.

## Design for variety & readability

Discovery lists *what exists*; good decks come from *choosing well*. The two failure modes to
avoid are **(1) every slide is `TitleSlide` + `BulletList`** and **(2) over-correcting into a
salad of mismatched widgets**. Both look amateur. Follow the house style.

### Message-first anatomy (the default)

Every content slide is built message-first:

1. **Action title** — the `title` is a **full-sentence takeaway**, not a topic label. Test: read
   the title alone; if it still makes a claim, it's an action title.
   - ❌ `"Q3 Revenue"` (topic label)
   - ✅ `"Revenue grew 3.2x in Q3, driven by enterprise expansion"` (action title)
   - **Keep it to one line — aim for ≤ ~10 words (~60 characters), two lines absolute max.** The
     title is a headline, not a sentence of body prose. The box does **not** grow and auto-fit only
     *shrinks* text, so a too-long title wraps into the body or renders tiny.
   - ❌ `"Revenue grew 3.2x in Q3 because enterprise expansion accelerated across every region while churn fell to a record low"` (two facts crammed in — overflows)
   - **State one claim in the title; move any qualifier, cause, or evidence to the one-line lead**
     (step 2). If a title needs a comma-spliced second clause to make sense, that clause belongs in
     the lead — don't lengthen the title to hold it.
2. **One-line lead** (optional but preferred) — a `Subtitle` in the `lead` region that adds the
   "so what" in one sentence. Archetypes with a `lead` region: `HeadlineLead`, `ThreeUpLead`,
   `MediaBandTop`, `SplitMediaLeft/Right`, `InsetMediaRight`.
3. **Structured body** — labeled blocks (`Callout` columns with `title` labels), a `Chart`, a
   `StatStrip`, a `Table`, or a `Process` — **not** bare bullets. A bare `BulletList` is the
   last resort, only for genuinely list-shaped content (e.g. an agenda).

`HeadlineLead` is the default content archetype; the *Executive summary*, *Key message + chart*,
and *Three labeled columns* patterns show the anatomy filled in.

### House style (compose, don't decorate)

- **One focal point per slide.** Each slide has a single dominant element — a chart, a stat
  band, a quote, or one key sentence. Everything else only supports it.
- **At most ~2 widget *families* per slide.** A good slide is usually a heading + **one** content
  widget (optionally one small support like a `Callout` or `Image`). Do **not** combine
  `Chart` + `Table` + `Callout` + `BulletList` on one slide.
- **Be consistent across the deck.** Reuse a small set of slide patterns; repeat structure
  (sections open with `SectionDivider`; every data slide uses the same `Chart` style).
  Consistency is what reads as "designed" — varying *everything* reads as noise.
- **Don't decorate.** Per-slide `background`/accents are for section and quote slides, not every
  slide; keep content slides on the theme background.
- **Keep text large.** One idea per slide; prefer few words. Auto-fit only *shrinks* text to make
  it fit, so an overstuffed region just renders small — split the slide instead of cramming.
  Horizontal multi-column regions (`ThreeUp`, `FourUp`, `StatBand.stats`, `Dashboard.metrics`)
  are for **short** cards/stats/charts only — never long paragraphs — and keep to **≤3–4 columns**.

### Start from a pattern, then vary

List the ready-made patterns with `ppt patterns`, then fetch one with
`ppt patterns --name "<name>"`. The library covers the corporate staples (Title cover, Agenda,
Section divider, Executive summary, Key message + chart, Three labeled columns, Two-up
comparison, Stat band, KPI overview, Timeline, Process steps, Data table, Big statement) and an
image-shape set (Wide image band, Tall image split, Small image inset, Full-bleed statement,
Gallery). Pick a pattern that fits the content, fill in its text, and **vary the pattern slide
to slide** — don't free-mix widgets. Match content to widget:

| Content | Reach for |
|---|---|
| One image | pick the pattern by **image shape** — see the table under *Images* below |
| Numbers / KPIs | `Dashboard` or `StatBand` with `KpiCard` / `StatStrip` |
| Trends, series, mix | `Chart` (bar/line/pie) — not a table of numbers |
| A process or steps | `Process`, or `Timeline` for dated milestones |
| Two options / before–after | `Comparison` |
| One point to emphasize | `Callout` |
| Code or commands | `CodeBlock` |
| Screens / photos | `Image`, or `ImageGrid` for several |
| Section break / big statement | `SectionDivider`, `HeroAsymmetric`, `FullBleedQuote` |
| Plain prose | `Paragraph`, `BulletList`, `IconList` |

Run `ppt info` for the full list of archetypes and widgets; the patterns above already cover the
common, well-matched compositions.

## Fonts (important for fidelity)

A `.pptx` does not embed fonts — it only looks right where the font is installed. The themes
use OFL fonts with **Korean + Latin** coverage. Tell the user they can install them with
`ppt install-fonts`, or bundle them to ship next to the deck with
`ppt install-fonts --bundle ./deck-fonts`. For view-only audiences, exporting to PDF embeds
fonts. Keep the Korean+Latin themes when the user works in Korean.

## Images (local files, no network)

Use `Image` (or `ImageGrid` for a gallery) with a **local file path** or a `data:` URI in
`src`. Relative paths resolve against the deck file's folder, or `meta.assetsBase`, or
`ppt export --assets <dir>`. **Remote `http(s)` URLs are rejected at export** (the engine never
fetches — decks stay reproducible and offline); a missing file fails with a clear path. `Image`
also takes `fit` (`cover`/`contain`) and a `caption`. A slide may set a `background` (a color,
or a full-bleed image with `fit` + a translucent `overlay`).

**Pick the pattern by the image's shape** — match the layout to the image, not the other way
around. When generating images (e.g. with an image skill), request these sizes (~200 DPI for
the default 16:9 deck):

| Image shape | Pattern (via `ppt patterns --name`) | Rendered box | Generate at |
|---|---|---|---|
| WIDE / horizontal (landscape) | `Wide image band` | 12.9″ × 2.9″ (4.5:1) | 2580×570 px — or your widest ratio with the subject vertically centered (`cover` crops top/bottom) |
| TALL / vertical (portrait) | `Tall image split` | 5.7″ × 7.1″ (4:5) | 1080×1350 px |
| SMALL / square (logo, screenshot detail, headshot) | `Small image inset` | 3.6″ × 2.9″ (5:4) | 1000×800 px, or 1:1 with `fit: contain` |
| FULL-BLEED statement shot | `Full-bleed statement` (slide `background` + overlay) | 13.33″ × 7.5″ (exact 16:9) | 1920×1080 px or larger |
| MULTIPLE images (2–6) | `Gallery` | ~1:1 cells (3-up) | 800×800 px each |

Sizing rules:
- `fit: cover` (default) **crops from the center to fill the box** — the aspect need not be
  exact; keep the subject centered and away from edges.
- `fit: contain` **letterboxes** — use it (and match the aspect) for logos, diagrams, and
  screenshots where cropping is unacceptable.
- A `caption` on an `Image` reserves 0.32″ of the box height.

## Quick reference

| Command | Use |
|---|---|
| `ppt info` | list themes / archetypes / widget types |
| `ppt patterns [--name "<n>"]` | ready-made slide compositions — start here, compose the deck from these |
| `ppt schema --archetype <id>` | one archetype's regions + a fill-in example (for custom slides) |
| `ppt schema --widget <type>` | one widget's exact props |
| `ppt schema --edits` | the structured edit ops and their fields |
| `ppt new -t <theme> -a <archetype> -o deck.json` | scaffold a starting DeckSpec |
| `ppt validate deck.json --json` | structural + semantic validation |
| `ppt export deck.json -o deck.pptx` | render to PowerPoint |
| `ppt preview deck.json -d preview/` | render HTML preview |
| `ppt update deck.json --edit edit.json -o out.json` | structured edits |
