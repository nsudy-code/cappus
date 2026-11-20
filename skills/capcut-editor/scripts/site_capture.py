#!/usr/bin/env python3
"""Capture a website for a promo video: phone screenshots, a contact sheet, and what the site says.

  site_capture.py https://example.com out_dir
  site_capture.py https://example.com/en/ out_dir --step 0.66 --max 16

Writes into out_dir:
  shot_00000.png ...   1080x1920 screenshots (a 540x960 phone at 2x), one per scroll step; the
                       number is the scroll position in CSS pixels
  sheet.jpg            every shot side by side with its number, to Read and pick the best ones
  site.json            title, description, language, headings, buttons, prices, contact details,
                       and the brand colors (background, text, accent) taken from the page itself

Needs Playwright: python -m pip install -r <skill>/requirements-web.txt, then
python -m playwright install chromium. Use only claims the site makes (site.json) in the video.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

PRICE = re.compile(r"(?:IDR|Rp\.?|USD|US\$|\$|€|£)\s?\d[\d.,]*(?:\s?(?:k|K|rb|jt|juta|million|M))?")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+?62|0)8\d[\d\s-]{7,12}\d")

# Runs in the page: text that tells what the site offers, and the colors it uses.
EXTRACT_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = el => (el.innerText || '').replace(/\s+/g, ' ').trim();
  const uniq = a => [...new Set(a.filter(Boolean))];
  const pick = sel => uniq([...document.querySelectorAll(sel)].filter(vis).map(txt)).filter(t => t.length <= 160);
  const rgb = c => { const m = (c || '').match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(',').map(Number); if (p.length > 3 && p[3] < 0.5) return null;
    return '#' + p.slice(0, 3).map(v => Math.round(v).toString(16).padStart(2, '0')).join('').toUpperCase(); };
  const buttons = [...document.querySelectorAll('a, button')].filter(vis)
    .filter(el => { const s = getComputedStyle(el); return rgb(s.backgroundColor) && txt(el).length && txt(el).length < 40; });
  const meta = n => (document.querySelector(`meta[name="${n}"], meta[property="${n}"]`) || {}).content || '';
  return {
    title: document.title, description: meta('description') || meta('og:description'),
    lang: document.documentElement.lang || '', og_image: meta('og:image'),
    h1: pick('h1'), h2: pick('h2'), h3: pick('h3'),
    buttons: uniq(buttons.map(txt)).slice(0, 20),
    paragraphs: pick('p').filter(t => t.length > 30).slice(0, 25),
    links: uniq([...document.querySelectorAll('a[href]')].map(a => a.href)).slice(0, 200),
    body_bg: rgb(getComputedStyle(document.body).backgroundColor) || rgb(getComputedStyle(document.documentElement).backgroundColor),
    body_color: rgb(getComputedStyle(document.body).color),
    button_bgs: buttons.map(el => rgb(getComputedStyle(el).backgroundColor)).filter(Boolean),
    heading_colors: [...document.querySelectorAll('h1, h2')].filter(vis).map(el => rgb(getComputedStyle(el).color)).filter(Boolean),
    full_text: (document.body.innerText || '').slice(0, 20000),
  };
}
"""


def luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def saturation(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hi, lo = max(r, g, b), min(r, g, b)
    return 0 if hi == 0 else (hi - lo) / hi


def summarize(raw: dict, url: str) -> dict:
    """Turn what the page script returned into site.json (pure function, testable without a browser)."""
    text = raw.get("full_text", "")
    bg = raw.get("body_bg") or "#FFFFFF"
    accents = Counter(c for c in raw.get("button_bgs", []) if saturation(c) > 0.35)
    accent = accents.most_common(1)[0][0] if accents else None
    heading = Counter(raw.get("heading_colors", [])).most_common(1)
    links = raw.get("links", [])
    wa = sorted({l for l in links if "wa.me" in l or "whatsapp" in l.lower()})
    socials = sorted({l for l in links if re.search(r"instagram|tiktok|facebook|youtube|linkedin|x\.com|twitter", l)})
    return {
        "url": url, "title": raw.get("title", ""), "description": raw.get("description", ""),
        "lang": raw.get("lang", ""), "og_image": raw.get("og_image", ""),
        "headings": {"h1": raw.get("h1", []), "h2": raw.get("h2", []), "h3": raw.get("h3", [])[:30]},
        "buttons": raw.get("buttons", []), "paragraphs": raw.get("paragraphs", []),
        "prices": sorted(set(m.group(0).strip() for m in PRICE.finditer(text)))[:12],
        "contact": {"emails": sorted(set(EMAIL.findall(text)))[:5],
                    "phones": sorted(set(p.strip() for p in PHONE.findall(text)))[:5],
                    "whatsapp_links": wa[:3], "socials": socials[:8]},
        "colors": {"background": bg, "text": raw.get("body_color") or ("#FFFFFF" if luminance(bg) < 0.5 else "#111111"),
                   "accent": accent, "heading": heading[0][0] if heading else None,
                   "dark": luminance(bg) < 0.5},
        "note": "Use only what the site says. colors.accent is the most used saturated button color; "
                "pass it as spec.brand.accent.",
    }


def contact_sheet(shots, out):
    from PIL import Image, ImageDraw
    thumbs = [(y, Image.open(p).convert("RGB").resize((180, 320))) for y, p in shots]
    cols = min(8, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 190 + 10, rows * 345 + 10), (60, 60, 60))
    draw = ImageDraw.Draw(sheet)
    for i, (y, t) in enumerate(thumbs):
        x0, y0 = 10 + (i % cols) * 190, 10 + (i // cols) * 345
        sheet.paste(t, (x0, y0))
        draw.text((x0, y0 + 323), f"shot_{y:05d}", fill=(255, 220, 0))
    sheet.save(out, quality=88)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--step", type=float, default=0.66, help="scroll step as a fraction of the screen height")
    ap.add_argument("--max", type=int, default=18, help="most screenshots to take")
    ap.add_argument("--dark", action="store_true", help="ask the site for its dark color scheme")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sync_playwright is None:
        print("Playwright is not installed. Run: python -m pip install -r <skill>/requirements-web.txt "
              "and then: python -m playwright install chromium", file=sys.stderr)
        return 3
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 540, "height": 960}, device_scale_factor=2, is_mobile=True,
                                has_touch=True, color_scheme="dark" if args.dark else "light")
        page.goto(args.url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1500)
        raw = page.evaluate(EXTRACT_JS)
        height = page.evaluate("document.documentElement.scrollHeight")
        step = max(200, int(960 * args.step))
        for y in list(range(0, max(1, height - 960 + 1), step))[: args.max]:
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(900)  # let reveal-on-scroll animations finish
            path = out / f"shot_{y:05d}.png"
            page.screenshot(path=str(path))
            shots.append((y, path))
        browser.close()
    contact_sheet(shots, out / "sheet.jpg")
    site = summarize(raw, args.url)
    site["shots"] = [p.name for _, p in shots]
    (out / "site.json").write_text(json.dumps(site, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"shots": len(shots), "sheet": str(out / "sheet.jpg"), "site": str(out / "site.json"),
                      "title": site["title"], "colors": site["colors"], "prices": site["prices"],
                      "contact": site["contact"]}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
