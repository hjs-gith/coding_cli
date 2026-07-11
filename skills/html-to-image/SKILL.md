---
name: html-to-image
description: Generate minimal, deck-ready concept diagram images (process flows, timelines, cycles, 2x2 matrices, pyramids, architecture layers, as-is/to-be comparisons) by writing HTML/CSS and rendering to transparent PNG with headless Chromium. Outputs are sized and colored to drop straight into `pptx` decks (see "For pptx decks" below). Use this skill whenever the user needs a diagram, schematic, flow, or visual explanation of an idea to embed into a presentation or document — even if they don't say "diagram", e.g. "show the process", "visualize the roadmap", "explain the architecture". Also use it to convert any .html file into an image file.
compatibility: Requires Python 3.9+, playwright, and a Chromium binary (playwright install chromium)
---

# HTML → Image: Concept Diagrams

Create diagram images by (1) authoring a self-contained HTML file from a
template, then (2) rendering it with `scripts/render.py`.

This skill produces **diagrams only** — schematic visuals that explain an
idea. It does not produce slide-like content (titles, KPI numbers, data
tables, charts); the deck template supplies those. Never add title text,
subtitles, or source lines to a diagram unless the user asks.

## Design language: minimal monochrome

All templates share `assets/style.css`. The rules that keep assets
matching any deck:

- **Grayscale only.** Ink `#1f1f1f`, gray `#6e6e6e`, light line `#b8b8b8`.
  No decorative color. Transparent + grayscale is the default because it lets
  a diagram drop onto **any** deck theme — prefer it. To color-match a specific
  pptx deck, set the single `--ink` token (in `assets/style.css`, or an inline
  `:root { --ink: #<accent>; }` override in the diagram HTML) to the deck's
  accent hex — get it from `ppt info` / the chosen theme. That recolors text,
  strong strokes, and the emphasis fill together. Keep everything else outlined
  and grayscale; still **one color only**, never a second accent. The transparent
  background already harmonizes with any theme background — leave it as is.
- **One emphasis device**: a single solid dark fill (`.emph`) on the one
  element that matters most. Everything else is outlined.
- Uniform `--stroke` (2px) line weight; subtle `--radius` (6px) corners.
- Transparent background so the PNG sits on any slide fill.

## Templates

| Template | Shape (W×H px) | Use for |
|---|---|---|
| `process-flow.html` | wide strip 1600×~160 | Left-to-right pipeline / step boxes |
| `timeline.html` | wide strip 1600×~130 | Horizontal roadmap with phase states |
| `layers.html` | wide 1000×~310 | Architecture / system stack bands |
| `comparison.html` | wide 1100×~310 | As-is → To-be transformation |
| `pyramid.html` | landscape 900×~450 | Layered hierarchy, tiered audiences |
| `matrix-2x2.html` | square 860×~660 | Strategy quadrants with axis labels |
| `cycle.html` | square 880×~790 | Circular loop with hub (4 nodes) |
| `timeline-vertical.html` | tall column 640×~410+ | Roadmap beside body text |

**Pick by placeholder shape first**, then content: full-slide-width →
wide strip; half-slide → square (matrix, cycle) or landscape (pyramid);
narrow side column → vertical timeline. Heights grow with content;
widths are set inline on `#board` and can be overridden.

**How to use:** copy a template, replace placeholder content (sample text
is Korean — write in the user's language). Freely change structure (step
count, node count, band count, direction) but keep the design language
above. If no template fits (trees, venn, hub-and-spoke, custom
schematics), design freely in the same language: outlined shapes, one
dark emphasis fill, gray thin arrows, `../assets/style.css` tokens.

## Render

```bash
python scripts/render.py diagram.html -o diagram.png \
    --selector "#board" --transparent --scale 2
```

`--transparent` → clean on any slide background. `--scale 2` → sharp when
the deck scales it; output pixels = 2× board CSS size, so size deck
placeholders accordingly. Use `--scale 1` for exact pixel dimensions.

Then **verify**: view the output; check for clipped edges, overflowing
text, wrong emphasis. Fix the HTML and re-render until clean.

## render.py quick reference

| Flag | Purpose |
|---|---|
| `--selector CSS` | Screenshot one element (use `"#board"`) |
| `--transparent` | Transparent PNG background |
| `--scale N` | Device scale factor (default 2) |
| `--width/--height` | Viewport size (mostly irrelevant with --selector) |
| `--full-page` | Whole page instead of viewport |
| `--delay MS` | Extra wait for JS-drawn content |
| `--out-dir DIR` | Batch mode: `render.py a.html b.html --out-dir out/` |
| `-` as input | Read HTML from stdin |

## For pptx decks

These diagrams are made to embed into `pptx` decks. When you do:

- **Embed with `fit: contain`, never `cover`.** Cropping a diagram cuts off
  content; `contain` scales the whole diagram to fit and letterboxes it — and
  because the PNG is transparent, those letterbox margins are invisible on the
  theme background. (See the *Images* table in the `pptx` skill for the box each
  pattern renders.)
- **Match resolution to ~200 DPI** for the default 16:9 deck — the same target
  the pptx skill states. `#board` width is set inline; `--scale` multiplies it,
  so pick `--scale` to meet the target px below. Oversizing is harmless with
  `contain`, so `--scale 2` comfortably covers full-width diagrams.
- **Pick the pattern by the diagram's proportion** (exact aspect need not match —
  `contain` + transparency handles the rest):

| Diagram template | Proportion | Best pptx pattern / region | Target output px | `#board` × scale |
|---|---|---|---|---|
| `process-flow`, `timeline` | very wide strip | `Wide image band` (4.5:1) or full content-width region | ~2580 px wide | 1600 × 2 (=3200, ample) |
| `layers`, `comparison` | wide (~3.3:1) | `Wide image band` / content region | ~2000–2580 px wide | 1000–1100 × 2 |
| `pyramid` | landscape 2:1 | half-slide / medium region | ~1800 px wide | 900 × 2 |
| `matrix-2x2`, `cycle` | square-ish | `Small image inset` (5:4) box or half-slide square | ~1000–1600 px | 860–880 × 2 |
| `timeline-vertical` | tall column | `Tall image split` (4:5) box, side column | ~1080 px wide | 640 × 2 |

## Gotchas

- **Clipped content**: element screenshots clip to `#board`'s box —
  absolutely-positioned children must stay inside it (widen the board).
- **Fonts**: script awaits `document.fonts.ready`; on closed networks
  remote fonts never load — rely on the system font stack in the tokens.
- **Animations**: captures are a single frame; templates avoid animation.

## Setup (one-time)

```bash
pip install playwright
playwright install chromium
# Closed network: point at an existing browser instead —
#   edit launch() to pw.chromium.launch(executable_path="/path/to/chrome")
```