#!/usr/bin/env python3
"""Render the three verified Mr2Odds slips as one A4 handwritten-style page."""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter


def parse_report(path: Path):
    text = path.read_text(encoding="utf-8")
    slips = []
    for section in re.split(r"(?=^### SLIP [1-3] — )", text, flags=re.M):
        head = re.search(r"^### SLIP ([1-3]) — (.+)$", section, re.M)
        if not head:
            continue
        legs = re.findall(r"^•\s*(.+?)\s*$", section, re.M)
        odds = re.search(r"^\*\*Combined odds\s+([0-9]+(?:\.[0-9]+)?)\*\*", section, re.M)
        if not legs or not odds:
            raise ValueError(f"Slip {head.group(1)} is missing selections or combined odds")
        slips.append({"number": int(head.group(1)), "label": head.group(2).strip(),
                      "legs": legs, "odds": odds.group(1)})
    if [s["number"] for s in slips] != [1, 2, 3]:
        raise ValueError("The report must contain exactly Slip 1, Slip 2 and Slip 3 in order")
    if any(not 2 <= len(s["legs"]) <= 6 for s in slips):
        raise ValueError("A slip has an unexpected number of selections")
    return text, slips


def load_font(path, size, fallback):
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.truetype(fallback, size)


def wrap(draw, text, font, max_width):
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = (line + " " + word).strip()
        if line and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if any(draw.textbbox((0, 0), line, font=font)[2] > max_width for line in lines):
        raise ValueError("A selection is too long to fit on the A4 page")
    return lines


def render(report_path: Path, output: Path, font_path: Path):
    report_text, slips = parse_report(report_path)
    date_match = re.search(r"^# Mr2Odds Daily Research — (.+)$", report_text, re.M)
    date_label = date_match.group(1).strip() if date_match else datetime.now().strftime("%d %B %Y")

    W, H = 1240, 1754
    # Warm white paper, subtle natural grain, dark blue pen.
    paper = Image.new("RGB", (W, H), "#F8F6EF")
    grain = Image.effect_noise((W, H), 7).convert("RGB")
    paper = Image.blend(paper, grain, 0.025)
    draw = ImageDraw.Draw(paper)
    ink, muted, rule = "#173B61", "#47627A", "#B8C9D6"
    margin = 92

    title = load_font(font_path, 58, "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf")
    date_font = load_font(font_path, 38, "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf")
    slip_font = load_font(font_path, 62, "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf")
    subtitle_font = load_font(font_path, 39, "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf")
    leg_font = load_font(font_path, 36, "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf")
    total_font = load_font(font_path, 43, "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf")

    # Slightly irregular ruling and margin, like a real sheet of paper.
    draw.line((margin, 66, margin, H - 72), fill="#D7A49A", width=2)
    draw.text((margin + 36, 48), "Mr2Odds - daily selections", font=title, fill=ink)
    draw.text((margin + 38, 112), date_label, font=date_font, fill=muted)
    draw.line((margin + 35, 168, W - margin, 166), fill=ink, width=3)

    y = 194
    content_width = W - margin * 2 - 90
    for idx, slip in enumerate(slips):
        draw.text((margin + 35, y), f"SLIP {slip['number']}", font=slip_font, fill=ink)
        y += 68
        label_lines = wrap(draw, slip["label"], subtitle_font, content_width)
        for line in label_lines:
            draw.text((margin + 38, y), line, font=subtitle_font, fill=muted)
            y += 43
        draw.line((margin + 35, y + 3, W - margin, y + 1), fill=ink, width=2)
        y += 20

        for n, leg in enumerate(slip["legs"], 1):
            lines = wrap(draw, leg, leg_font, content_width - 70)
            draw.text((margin + 42, y), f"{n}.", font=leg_font, fill=muted)
            for line_index, line in enumerate(lines):
                draw.text((margin + 105, y), line, font=leg_font, fill=ink)
                y += 43
            y += 8

        y += 2
        draw.text((margin + 45, y), f"Combined odds: {slip['odds']}", font=total_font, fill=ink)
        y += 60
        if idx < 2:
            draw.line((margin + 30, y, W - margin, y - 2), fill=ink, width=2)
            y += 24

    if y > H - 55:
        raise ValueError("The slips do not fit legibly on one A4 page; shorten the wording before publishing")

    output.parent.mkdir(parents=True, exist_ok=True)
    paper.save(output, "PNG", dpi=(150, 150), optimize=True)
    print(f"Rendered one A4 page with {sum(len(s['legs']) for s in slips)} selections.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("reports/morning-report.md"))
    parser.add_argument("--output", type=Path, default=Path("mr2odds-daily-slips.png"))
    parser.add_argument("--font", type=Path, default=Path("/tmp/Caveat.ttf"))
    args = parser.parse_args()
    render(args.report, args.output, args.font)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
