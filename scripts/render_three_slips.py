#!/usr/bin/env python3
"""Render exactly three phone-readable handwritten betting notes on textured paper."""
from __future__ import annotations
import argparse, math, random, re, sys
from datetime import date
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

INK=(25,43,82); MUTED=(47,66,108); PAPER=(247,243,233)

def wrap(draw,text,font,max_width):
    lines=[]; line=""
    for word in text.split():
        trial=(line+" "+word).strip()
        if line and draw.textbbox((0,0),trial,font=font)[2]>max_width:
            lines.append(line); line=word
        else: line=trial
    if line: lines.append(line)
    if any(draw.textbbox((0,0),x,font=font)[2]>max_width for x in lines):
        raise ValueError("Text does not fit: "+text)
    return lines

def parse_report(path):
    text=path.read_text(encoding="utf-8"); slips=[]
    for section in re.split(r"(?=^### SLIP [1-3] — )",text,flags=re.M):
        head=re.search(r"^### SLIP ([1-3]) — (.+)$",section,re.M)
        if not head: continue
        legs=re.findall(r"^•\s*(.+?)\s*$",section,re.M)
        odds=re.search(r"^\*\*Combined odds ([0-9]+(?:\.[0-9]+)?)\*\*",section,re.M)
        if not legs or not odds: raise ValueError(f"Slip {head.group(1)} missing legs or odds")
        parsed=[]
        for leg in legs:
            m=re.match(r"(.+?)\s+—\s+(.+?)\s+@([0-9]+(?:\.[0-9]+)?)\s+\(([\d.]+%)\)$",leg)
            if not m: raise ValueError("Selection format not recognized: "+leg)
            parsed.append({"fixture":m.group(1).strip(),"market":m.group(2).strip(),"odds":float(m.group(3)),"prob":m.group(4)})
        total=math.prod(x["odds"] for x in parsed)
        if abs(total-float(odds.group(1)))>0.006: raise ValueError(f"Slip {head.group(1)} odds mismatch: {total:.4f}")
        if not 2.50<=total<=3.00: raise ValueError(f"Slip {head.group(1)} outside odds target: {total:.4f}")
        slips.append({"number":int(head.group(1)),"label":head.group(2).strip(),"legs":parsed,"odds":float(odds.group(1))})
    if [s["number"] for s in slips]!=[1,2,3]: raise ValueError("Exactly three slips in order are required")
    fixtures=[leg["fixture"].casefold() for slip in slips for leg in slip["legs"]]
    if len(fixtures)!=len(set(fixtures)): raise ValueError("A fixture is repeated across slips")
    if any(not 2<=len(s["legs"])<=6 for s in slips): raise ValueError("Unexpected leg count")
    return slips

def desk(w,h,seed):
    im=Image.new("RGB",(w,h),(207,184,151))
    im=Image.blend(im,Image.effect_noise((w,h),20).convert("RGB"),.035)
    d=ImageDraw.Draw(im,"RGBA"); rng=random.Random(seed)
    for y in range(0,h,24): d.line((0,y,w,y+rng.randint(-2,2)),fill=(97,70,47,rng.randint(5,12)),width=1)
    for _ in range(160):
        x=rng.randrange(w); y=rng.randrange(h); d.line((x,y,min(w,x+rng.randrange(60,300)),y),fill=(112,83,54,rng.randint(3,8)),width=1)
    return im

def paper(w,h,seed):
    p=Image.blend(Image.new("RGB",(w,h),PAPER),Image.effect_noise((w,h),13).convert("RGB"),.022)
    d=ImageDraw.Draw(p,"RGBA"); rng=random.Random(seed)
    for _ in range(600): d.point((rng.randrange(w),rng.randrange(h)),fill=(120,100,70,rng.randint(3,9)))
    d.line((w*.66,35,w*.66,h-45),fill=(135,117,92,9),width=2)
    d.line((35,h*.34,w-30,h*.34),fill=(135,117,92,6),width=1)
    d.line((42,42,w-42,42),fill=(255,255,255,55),width=2)
    return p

def render(s,date_str,font_path,out,snapshot_time):
    W,H=1080,1560; pw,ph=920,1400; x0,y0=(W-pw)//2,70
    base=desk(W,H,s["number"]).convert("RGBA")
    shadow=Image.new("RGBA",(W,H),(0,0,0,0)); sd=ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x0+16,y0+22,x0+pw+18,y0+ph+24),radius=18,fill=(30,24,18,100))
    base=Image.alpha_composite(base,shadow.filter(ImageFilter.GaussianBlur(26)))
    sheet=paper(pw,ph,s["number"]+100).convert("RGBA")
    ImageDraw.Draw(sheet).rounded_rectangle((2,2,pw-4,ph-4),radius=7,outline=(130,117,91,38),width=2)
    base.alpha_composite(sheet.rotate(-.22,expand=False,resample=Image.Resampling.BICUBIC),(x0,y0))
    im=base.convert("RGB"); d=ImageDraw.Draw(im)
    title=ImageFont.truetype(str(font_path),52); head=ImageFont.truetype(str(font_path),86)
    sub=ImageFont.truetype(str(font_path),45); match=ImageFont.truetype(str(font_path),44)
    market=ImageFont.truetype(str(font_path),39); total=ImageFont.truetype(str(font_path),67)
    small=ImageFont.truetype(str(font_path),33); rng=random.Random("handwriting"+str(s["number"]))
    left=x0+72; right=x0+pw-72; maxw=right-left; y=y0+64
    d.text((left,y),"Mr2Odds • daily notes",font=title,fill=INK); y+=78
    d.line((left+4,y,right-110,y-3),fill=INK,width=3); y+=32
    d.text((left,y),f"SLIP {s['number']}",font=head,fill=INK); y+=90
    for line in wrap(d,s["label"].replace(" — "," / ").replace("-"," "),sub,maxw):
        d.text((left+rng.randint(-1,2),y+rng.randint(-1,2)),line,font=sub,fill=MUTED); y+=56
    d.line((left,y+4,right,y),fill=INK,width=3); y+=26
    for i,leg in enumerate(s["legs"],1):
        d.text((left+2,y),f"{i}.",font=match,fill=INK); mx=left+74
        for line in wrap(d,leg["fixture"],match,maxw-78):
            d.text((mx+rng.randint(-1,2),y+rng.randint(-1,2)),line,font=match,fill=INK); y+=52
        text=f"{leg['market']}  •  @{leg['odds']:.2f}  •  {leg['prob']} model"
        for line in wrap(d,text,market,maxw-120):
            d.text((mx,y+rng.randint(-1,2)),line,font=market,fill=MUTED); y+=47
        # Hand-drawn blue checkmark; avoids missing-glyph boxes in Caveat.
        d.line((right-49,y-33,right-34,y-17),fill=INK,width=4)
        d.line((right-34,y-17,right-7,y-48),fill=INK,width=4)
        y+=18
    y+=12; label="COMBINED ODDS"; odds_text=f"{s['odds']:.2f}"
    box_x=left+10; box_y=y-3; box_w=d.textbbox((0,0),label,font=sub)[2]+total.getbbox(odds_text)[2]+150
    d.rounded_rectangle((box_x,box_y,box_x+box_w,box_y+100),radius=14,outline=INK,width=4)
    d.text((box_x+24,box_y+18),label,font=sub,fill=INK)
    lw=d.textbbox((0,0),label,font=sub)[2]
    d.text((box_x+lw+82,box_y+8),odds_text,font=total,fill=INK)
    d.line((box_x+lw+75,box_y+78,box_x+lw+total.getbbox(odds_text)[2]+105,box_y+77),fill=INK,width=3)
    d.text((left,y0+ph-88),f"SportyBet ZA prices • {snapshot_time} SAST • {date_str}",font=small,fill=(78,88,103))
    if y>H-165: raise ValueError(f"Slip {s['number']} text overflows: y={y}")
    out.parent.mkdir(parents=True,exist_ok=True); im.save(out,"PNG",optimize=True,dpi=(150,150))
    print(f"Rendered {out} ({out.stat().st_size} bytes)")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--report",type=Path,default=Path("reports/morning-report.md"))
    ap.add_argument("--font",type=Path,default=Path("/tmp/Caveat.ttf")); ap.add_argument("--date",default=None)
    ap.add_argument("--out-dir",type=Path,default=Path("reports")); a=ap.parse_args()
    if not a.font.is_file() or a.font.stat().st_size<10000: raise ValueError("Caveat handwriting font is missing; refusing a typed fallback")
    day=a.date or date.today().isoformat()
    report_text=a.report.read_text(encoding="utf-8")
    snapshot=re.search(r"Odds snapshot:.*?(\\d{2}:\\d{2}) SAST",report_text)
    snapshot_time=snapshot.group(1) if snapshot else "time unavailable"
    for s in parse_report(a.report): render(s,day,a.font,a.out_dir/f"slip-{day}-{s['number']}.png",snapshot_time)
if __name__=="__main__":
    try: main()
    except (OSError,ValueError) as e: print("ERROR:",e,file=sys.stderr); raise SystemExit(1)
