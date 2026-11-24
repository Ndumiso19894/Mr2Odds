#!/usr/bin/env python3
"""Render the three daily slips as one natural handwritten A4 sheet."""
from __future__ import annotations

import argparse
import random
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
                      "legs": [clean_selection(x) for x in legs], "odds": odds.group(1)})
    if [s["number"] for s in slips] != [1, 2, 3]:
        raise ValueError("The report must contain exactly Slip 1, Slip 2 and Slip 3 in order")
    if any(not 2 <= len(s["legs"]) <= 6 for s in slips):
        raise ValueError("A slip has an unexpected number of selections")
    return slips


def clean_selection(value: str):
    value = re.sub(r"\s+\([0-9.]+%\)\s*$", "", value).strip()
    value = re.sub(r"\bO([0-9]+(?:\.[0-9]+)?)\b", r"Over \1", value)
    value = re.sub(r"Match corners\s+Over\s+([0-9.]+)", r"Over \1 corners", value, flags=re.I)
    value = re.sub(r"([A-Za-z .'-]+) corners\s+Over\s+([0-9.]+)", r"\1 — Over \2 team corners", value)
    value = value.replace("Bristol — Over ", "Bristol City — Over ")
    return value


def handwriting_font(path: Path, size: int):
    if not path.is_file() or path.stat().st_size < 10000:
        raise ValueError("The handwriting font is missing; refusing to publish a typed-looking fallback")
    try:
        return ImageFont.truetype(str(path), size)
    except OSError as exc:
        raise ValueError("The handwriting font is invalid") from exc


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
    slips = parse_report(report_path)

    # A4 portrait canvas: the paper itself fills the image, as in the supplied reference.
    W, H = 1240, 1754
    base = Image.new("RGB", (W, H), "#F4F4F1")
    texture = Image.effect_noise((W, H), 13).convert("RGB")
    paper = Image.blend(base, texture, 0.025)
    draw = ImageDraw.Draw(paper)
    # Strong cobalt-blue ballpoint ink: clearly blue, not grey or washed-out navy.
    ink = "#123FC5"
    muted = "#123FC5"

    title_font = handwriting_font(font_path, 53)
    slip_font = handwriting_font(font_path, 76)
    subtitle_font = handwriting_font(font_path, 45)
    leg_font = handwriting_font(font_path, 49)
    total_font = handwriting_font(font_path, 57)

    # Match the reference: one simple title, blue pen, white paper and clean separators.
    draw.text((92, 34), "Mr2Odds - match notes", font=title_font, fill=ink)
    draw.line((90, 112, 635, 109), fill=ink, width=3)

    y = 132
    rng = random.Random("Mr2Odds handwritten A4 slips")
    left, right = 64, W - 65
    max_width = right - 130

    for index, slip in enumerate(slips):
        draw.text((72, y), f"SLIP {slip['number']}", font=slip_font, fill=ink)
        y += 82

        # The market-style slip title is always written directly below SLIP N and underlined.
        label_lines = wrap(draw, slip["label"], subtitle_font, max_width)
        for line in label_lines:
            draw.text((72 + rng.randint(-1, 2), y + rng.randint(-1, 2)),
                      line, font=subtitle_font, fill=muted)
            y += 49
        draw.line((68, y + 2, right, y), fill=ink, width=3)
        y += 12

        for number, selection in enumerate(slip["legs"], 1):
            lines = wrap(draw, selection, leg_font, max_width - 8)
            for line_index, line in enumerate(lines):
                prefix = f"{number}." if line_index == 0 else ""
                x = 68 if prefix else 116
                if prefix:
                    draw.text((x, y + rng.randint(-2, 2)), prefix, font=leg_font, fill=ink)
                draw.text((x + (70 if prefix else 0) + rng.randint(-2, 2),
                           y + rng.randint(-2, 2)), line, font=leg_font, fill=ink)
                y += 58
            y += 2

        y += 5
        draw.text((125, y), "Combined Odds:", font=total_font, fill=ink)
        label_width = draw.textbbox((0, 0), "Combined Odds:", font=total_font)[2]
        odds_x = 125 + label_width + 30
        draw.text((odds_x, y - 2), slip["odds"], font=total_font, fill=ink)
        odds_width = draw.textbbox((0, 0), slip["odds"], font=total_font)[2]
        draw.line((odds_x - 5, y + 67, odds_x + odds_width + 20, y + 66), fill=ink, width=3)
        y += 88

        if index < 2:
            draw.line((60, y, right, y - 1), fill=ink, width=2)
            y += 20

    if y > H - 18:
        raise ValueError("The selections do not fit legibly on one A4 page; shorten wording before publishing")

    # A very slight camera-like softness keeps the paper natural without a fake desk frame.
    paper = paper.filter(ImageFilter.GaussianBlur(0.12))
    output.parent.mkdir(parents=True, exist_ok=True)
    paper.save(output, "PNG", dpi=(150, 150), optimize=True)
    print(f"Rendered the plain handwritten A4 reference layout with {sum(len(s['legs']) for s in slips)} selections.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("reports/morning-report.md"))
    parser.add_argument("--output", type=Path, default=Path("daily-slips-a4.png"))
    parser.add_argument("--font", type=Path, default=Path("/tmp/Caveat.ttf"))
    args = parser.parse_args()
    render(args.report, args.output, args.font)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
