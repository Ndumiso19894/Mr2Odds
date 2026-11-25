#!/usr/bin/env python3
"""Build and email a PDF containing only Mr2Odds Shortlist and Bet Advisor picks."""
import json, os, smtplib, sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

TZ=ZoneInfo("Africa/Johannesburg")
now=datetime.now(TZ)
doc=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
dest=Path(sys.argv[2])

def dt(value):
    if not value: return None
    for fmt in ("%Y-%m-%d %H:%M","%Y-%m-%dT%H:%M:%S","%Y-%m-%d"):
        try: return datetime.strptime(str(value),fmt).replace(tzinfo=TZ)
        except ValueError: pass
    return None

def is_upcoming(x):
    stamp=x.get("kickoff") or x.get("match_date") or x.get("date")
    if not stamp:
        f=str(x.get("fixture",""))
        stamp=f[:10] if len(f)>=10 and f[4:5]=="-" else None
    # Date-only advisor records count as upcoming throughout that local calendar day.
    if stamp and len(str(stamp)) == 10:
        try:
            return datetime.strptime(str(stamp), "%Y-%m-%d").date() >= now.date()
        except ValueError:
            pass
    parsed=dt(stamp)
    return parsed is None or parsed >= now

def convert(x):
    if not isinstance(x,dict): return None
    home=x.get("home") or x.get("home_team") or "?"
    away=x.get("away") or x.get("away_team") or "?"
    p=x.get("p",x.get("probability"))
    odds=x.get("odds",x.get("sportybet"))
    try: p=f"{float(p):.1%}" if p is not None else "Not supplied"
    except (ValueError,TypeError): p=str(p)
    try: odds=f"{float(odds):.2f}" if odds is not None else "Not supplied"
    except (ValueError,TypeError): odds=str(odds)
    return [str(x.get("kickoff") or x.get("match_date") or x.get("date") or "Time not supplied"),
            str(x.get("fixture") or x.get("match") or f"{home} v {away}"),
            str(x.get("label") or x.get("market") or x.get("selection") or x.get("sel") or "Market not specified"),
            p, odds, str(x.get("quality") or x.get("q") or x.get("data_quality") or "Not stated")]

short_raw=(doc.get("shortlist") or {}).get("primary") or []
advisor=doc.get("advisor") or {}
advisor_raw=[]
for key in ("picks","shown_today"):
    v=advisor.get(key) or []
    if isinstance(v,list): advisor_raw.extend(v)
    elif isinstance(v,dict): advisor_raw.extend(v.values())
short=[convert(x) for x in short_raw if isinstance(x,dict) and is_upcoming(x)]
adv=[convert(x) for x in advisor_raw if isinstance(x,dict) and is_upcoming(x)]
short=[x for x in short if x]
adv=[x for x in adv if x]

styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name="Main",parent=styles["Title"],fontSize=19,leading=23,textColor=HexColor("#102A43"),alignment=1,spaceAfter=4))
styles.add(ParagraphStyle(name="Sub",parent=styles["Normal"],fontSize=8.5,leading=12,textColor=HexColor("#52606D"),alignment=1))
styles.add(ParagraphStyle(name="Sec",parent=styles["Heading2"],fontSize=12,leading=15,textColor=HexColor("#102A43"),spaceBefore=9,spaceAfter=5))
styles.add(ParagraphStyle(name="Cell",parent=styles["Normal"],fontSize=7.1,leading=9,textColor=HexColor("#243B53")))
styles.add(ParagraphStyle(name="Note",parent=styles["Normal"],fontSize=8,leading=11,textColor=HexColor("#52606D")))
dest.parent.mkdir(parents=True,exist_ok=True)
pdf=SimpleDocTemplate(str(dest),pagesize=A4,rightMargin=12*mm,leftMargin=12*mm,topMargin=12*mm,bottomMargin=14*mm)
story=[Paragraph("MR2ODDS — DAILY SELECTIONS",styles["Main"]),
       Paragraph(f"SHORTLIST &amp; BET ADVISOR ONLY | {now.strftime('%A, %d %B %Y')} | SAST",styles["Sub"]),
       Spacer(1,4*mm),
       Paragraph(f"Source scan generated: {(doc.get('meta') or {}).get('generated','not stated')} SAST. Only Shortlist primary and Bet Advisor picks/shown-today entries are included. No other app sections are used.",styles["Note"])]

def add_section(title,items):
    story.append(Paragraph(title,styles["Sec"]))
    if not items:
        story.append(Paragraph("No upcoming selections were available in this section in the latest feed. No substitute selections have been added.",styles["Note"]))
        return
    rows=[[Paragraph("<b>"+h+"</b>",styles["Cell"]) for h in ["Kick-off","Fixture","Market","Model","Odds","Data"]]]
    for r in sorted(items,key=lambda z:z[0]):
        rows.append([Paragraph(v.replace("&","&amp;"),styles["Cell"]) for v in r])
    t=Table(rows,colWidths=[24*mm,54*mm,49*mm,19*mm,17*mm,22*mm],repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),HexColor("#102A43")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
                           ("GRID",(0,0),(-1,-1),0.3,HexColor("#D9E2EC")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,HexColor("#F5F7FA")]),
                           ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
                           ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story.append(t)

add_section("1. SHORTLIST — PRIMARY PICKS",short)
add_section("2. BET ADVISOR",adv)
story += [Spacer(1,4*mm),Paragraph("These are app selections, not independently verified betting advice. Model probabilities are estimates, not guarantees. Verify current odds, team news and line-ups before making decisions. High estimated probability does not necessarily mean good value.",styles["Note"]),
          Paragraph(f"Shortlist entries: {len(short)} | Bet Advisor entries: {len(adv)}",styles["Note"])]

def footer(c,d):
    c.saveState(); c.setStrokeColor(HexColor("#D9E2EC")); c.line(12*mm,10*mm,A4[0]-12*mm,10*mm)
    c.setFont("Helvetica",7); c.setFillColor(HexColor("#627D98")); c.drawString(12*mm,6*mm,"Mr2Odds | data branch latest.json")
    c.drawRightString(A4[0]-12*mm,6*mm,f"Page {d.page}"); c.restoreState()
pdf.build(story,onFirstPage=footer,onLaterPages=footer)

username=os.environ["GMAIL_USERNAME"]; password=os.environ["GMAIL_APP_PASSWORD"]; recipient=os.environ["REPORT_EMAIL"]
msg=EmailMessage()
msg["Subject"]=f"Mr2Odds Daily PDF — {now.strftime('%d %B %Y')}"
msg["From"]=username; msg["To"]=recipient
msg.set_content("Your Mr2Odds daily PDF is attached. It contains only Shortlist primary picks and Bet Advisor selections. Empty sections are reported as empty; no picks are substituted from other app sections.")
msg.add_attachment(dest.read_bytes(),maintype="application",subtype="pdf",filename=f"Mr2Odds_Daily_{now.strftime('%Y-%m-%d')}.pdf")
with smtplib.SMTP("smtp.gmail.com",587,timeout=30) as s:
    s.ehlo(); s.starttls(); s.ehlo(); s.login(username,password); s.send_message(msg)
print(f"PDF created and email accepted by Gmail SMTP for {recipient}.")
