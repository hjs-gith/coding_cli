#!/usr/bin/env python3
"""
render.py — Render HTML files (or URLs, or stdin) to image files using headless Chromium.

Requires: playwright  (pip install playwright && playwright install chromium)

Examples:
    # Basic: render an HTML file to PNG
    python render.py card.html -o card.png

    # Fixed-size card (e.g. 1080x1080 card news), retina-sharp
    python render.py card.html -o card.png --width 1080 --height 1080 --scale 2

    # Screenshot only one element (great for card decks in a single HTML)
    python render.py deck.html -o card1.png --selector "#card-1"

    # Full-page screenshot of a long report
    python render.py report.html -o report.png --full-page

    # Pipe HTML from stdin
    cat snippet.html | python render.py - -o out.png

    # Batch: render every .html in a folder
    python render.py cards/*.html --out-dir rendered/

    # JPEG with quality, or transparent PNG
    python render.py card.html -o card.jpg --quality 90
    python render.py logo.html -o logo.png --transparent
"""

import argparse
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("playwright is not installed. Run: pip install playwright && playwright install chromium")

VALID_FORMATS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}


def parse_args():
    p = argparse.ArgumentParser(description="Render HTML to image via headless Chromium.")
    p.add_argument("inputs", nargs="+",
                   help="HTML file path(s), a URL (http/https), or '-' for stdin")
    p.add_argument("-o", "--output", help="Output image path (single input only). "
                   "Extension decides format: .png / .jpg")
    p.add_argument("--out-dir", help="Output directory (used for batch input; "
                   "filenames mirror the input names)")
    p.add_argument("--width", type=int, default=1280, help="Viewport width in CSS px (default 1280)")
    p.add_argument("--height", type=int, default=800, help="Viewport height in CSS px (default 800)")
    p.add_argument("--scale", type=float, default=2.0,
                   help="Device scale factor; 2 = retina-sharp output (default 2)")
    p.add_argument("--full-page", action="store_true",
                   help="Capture the full scrollable page instead of the viewport")
    p.add_argument("--selector", help="CSS selector; screenshot only that element")
    p.add_argument("--transparent", action="store_true",
                   help="Transparent background (PNG only; page/body must not set a bg color)")
    p.add_argument("--quality", type=int, help="JPEG quality 0-100 (jpeg only)")
    p.add_argument("--wait-until", default="networkidle",
                   choices=["load", "domcontentloaded", "networkidle"],
                   help="When to consider the page ready (default networkidle)")
    p.add_argument("--delay", type=int, default=0,
                   help="Extra wait in ms after load (webfonts, JS charts, animations)")
    p.add_argument("--timeout", type=int, default=30000, help="Navigation timeout in ms")
    return p.parse_args()


def resolve_output(args, input_item, is_stdin):
    if args.output:
        return Path(args.output)
    out_dir = Path(args.out_dir or ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    if is_stdin:
        return out_dir / "output.png"
    if input_item.startswith(("http://", "https://")):
        stem = input_item.rstrip("/").split("/")[-1].split("?")[0] or "page"
        return out_dir / f"{Path(stem).stem or 'page'}.png"
    return out_dir / (Path(input_item).stem + ".png")


def render_one(page, input_item, out_path, args):
    is_stdin = input_item == "-"
    if is_stdin:
        page.set_content(sys.stdin.read(), wait_until=args.wait_until, timeout=args.timeout)
    elif input_item.startswith(("http://", "https://")):
        page.goto(input_item, wait_until=args.wait_until, timeout=args.timeout)
    else:
        path = Path(input_item).resolve()
        if not path.exists():
            raise FileNotFoundError(f"No such file: {path}")
        page.goto(path.as_uri(), wait_until=args.wait_until, timeout=args.timeout)

    if args.delay:
        time.sleep(args.delay / 1000)
    # Wait for webfonts so text renders correctly
    try:
        page.evaluate("document.fonts.ready")
    except Exception:
        pass

    fmt = VALID_FORMATS.get(out_path.suffix.lower())
    if not fmt:
        raise ValueError(f"Unsupported output extension '{out_path.suffix}'. Use .png or .jpg")

    shot_kwargs = {"path": str(out_path), "type": fmt}
    if fmt == "jpeg" and args.quality is not None:
        shot_kwargs["quality"] = args.quality
    if args.transparent and fmt == "png":
        shot_kwargs["omit_background"] = True

    if args.selector:
        el = page.wait_for_selector(args.selector, timeout=args.timeout)
        el.screenshot(**shot_kwargs)
    else:
        shot_kwargs["full_page"] = args.full_page
        page.screenshot(**shot_kwargs)


def main():
    args = parse_args()
    if args.output and len(args.inputs) > 1:
        sys.exit("Use --out-dir (not -o) when rendering multiple inputs.")

    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=args.scale,
        )
        for item in args.inputs:
            out_path = resolve_output(args, item, item == "-")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                render_one(page, item, out_path, args)
                print(f"OK  {item} -> {out_path}")
            except Exception as e:
                failures += 1
                print(f"FAIL {item}: {e}", file=sys.stderr)
        browser.close()
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()