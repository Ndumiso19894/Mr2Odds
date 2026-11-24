#!/usr/bin/env python3
"""Render verified daily slips as one realistic, ruled A4 handwritten page."""
from __future__ import annotations

import argparse
import random
import re
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops


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


def handwriting_font(path: Path, size: int):
    if not path.is_file() or path.stat().st_size < 10000:
        raise ValueError("The Caveat handwriting font is missing; refusing to publish a typed-looking fallback")
    try:
        return ImageFont.truetype(str(path), size)
    except OSError as exc:
        raise ValueError("The downloaded handwriting font is invalid") from exc


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

    # A4 portrait at print-quality proportions, photographed on a warm desk.
    PW, PH = 1240, 1754
    paper = Image.new("RGB", (PW, PH), "#F5F0E4")
    noise = Image.effect_noise((PW, PH), 18).convert("RGB")
    paper = Image.blend(paper, noise, 0.035)
    draw = ImageDraw.Draw(paper)
    ink, muted = "#173B5C", "#536C80"
    left, right = 112, PW - 72

    # Pale blue notebook ruling and a subtle red margin, like the reference sheet.
    for y in range(250, PH - 70, 86):
        draw.line((54, y, PW - 38, y + 1), fill="#D4DFE5", width=2)
    draw.line((132, 72, 132, PH - 78), fill="#D9A49B", width=3)

    title = handwriting_font(font_path, 48)
    date_font = handwriting_font(font_path, 34)
    slip_font = handwriting_font(font_path, 70)
    subtitle_font = handwriting_font(font_path, 42)
    leg_font = handwriting_font(font_path, 43)
    total_font = handwriting_font(font_path, 52)

    draw.text((190, 58), "Mr2Odds - match notes", font=title, fill=muted)
    draw.text((190, 112), date_label, font=date_font, fill=muted)
    draw.line((185, 178, right - 30, 177), fill=ink, width=3)

    y = 205
    content_width = right - left - 72
    rng = random.Random(date_label + str(sum(len(s["legs"]) for s in slips)))

    for idx, slip in enumerate(slips):
        draw.text((190, y), f"SLIP {slip['number']}", font=slip_font, fill=ink)
        y += 74

        for line in wrap(draw, slip["label"], subtitle_font, content_width):
            draw.text((190 + rng.randint(-2, 2), y + rng.randint(-2, 2)),
                      line, font=subtitle_font, fill=muted)
            y += 47
        draw.line((185, y + 2, right - 30, y), fill=ink, width=3)
        y += 20

        for n, leg in enumerate(slip["legs"], 1):
            lines = wrap(draw, leg, leg_font, content_width - 75)
            draw.text((190, y + rng.randint(-2, 2)), f"{n}.", font=leg_font, fill=muted)
            for line in lines:
                draw.text((260 + rng.randint(-2, 2), y + rng.randint(-2, 2)),
                          line, font=leg_font, fill=ink)
                y += 49
            y += 7

        draw.line((185, y + 1, right - 30, y), fill=ink, width=2)
        y += 10
        draw.text((190, y), f"Combined odds: {slip['odds']}",
                  font=total_font, fill=ink)
        y += 68
        if idx < 2:
            draw.line((185, y, right - 30, y - 1), fill="#8A9AA5", width=2)
            y += 24

    if y > PH - 45:
        raise ValueError("The slips do not fit legibly on one A4 page; shorten wording before publishing")

    # Add a soft, realistic page shadow and warm tabletop border.
    CW, CH = 1420, 1934
    canvas = Image.new("RGB", (CW, CH), "#B9A98E")
    desk_noise = Image.effect_noise((CW, CH), 12).convert("RGB")
    canvas = Image.blend(canvas, desk_noise, 0.035)
    shadow = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rectangle((88, 78, 1332, 1834), fill=(42, 31, 19, 115))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow)
    canvas.alpha_composite(paper.convert("RGBA"), (90, 72))
    canvas = canvas.convert("RGB")

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "PNG", dpi=(150, 150), optimize=True)
    print(f"Rendered one photographed-style A4 page with {sum(len(s['legs']) for s in slips)} selections.")


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
