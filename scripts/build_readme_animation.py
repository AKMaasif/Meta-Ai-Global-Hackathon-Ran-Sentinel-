"""Build the illustrative README workflow GIF; does not call models or the app."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "ran-sentinel-workflow.gif"
BG, PANEL, MUTED, FG, TEAL = "#081622", "#112735", "#94aebc", "#f3f8fa", "#44dfc4"

def font(size, bold=False):
    base = Path("C:/Windows/Fonts")
    return ImageFont.truetype(str(base / ("segoeuib.ttf" if bold else "segoeui.ttf")), size)

steps = [
    ("01", "DETECT", "Rules + ML", "Two anomalous windows create an incident.", "KPI window  >  Anomaly event"),
    ("02", "INVESTIGATE", "Muse Spark + tools", "Read KPIs, alarms and configuration; compare causes.", "Read-only tools  >  Evidence E1, E2, E3..."),
    ("03", "VERIFY", "Evidence + facts", "Check evidence coverage and facts; ask the field if needed.", "Insufficient evidence? Pause and request field input."),
    ("04", "PLAN + CHECK", "Rules + twin", "Draft a plan and rollback; evaluate limits and simulated impact.", "Unsafe proposal? Reject with reasons and revise."),
    ("05", "REVIEW", "Engineer decision", "An engineer reviews the evidence and decides whether to proceed.", "Human approval  >  Simulated change package"),
    ("06", "MONITOR", "Recover or roll back", "Observe recovery; confirm the change or roll it back.", "Safety ledger  >  Customer-safe service updates"),
]
frames, durations = [], []
for active, (_, _, _, detail, event) in enumerate(steps):
    for sub in range(6):
        im = Image.new("RGB", (1200, 510), BG)
        d = ImageDraw.Draw(im)
        d.text((42, 25), "RAN SENTINEL", fill=FG, font=font(33, True))
        d.text((43, 73), "From network evidence to an engineer-reviewed action", fill=MUTED, font=font(21))
        d.rounded_rectangle((955, 32, 1158, 65), 12, fill=PANEL)
        d.text((975, 38), "WORKFLOW PREVIEW", fill=TEAL, font=font(16, True))
        for i, (num, label, small, _, _) in enumerate(steps):
            x, y, w = 42+i*190, 146, 166
            on, done = i == active, i < active
            color = TEAL if on or done else "#355365"
            if i < 5:
                d.line((x+w, y+53, x+190, y+53), fill=color, width=3)
                d.polygon([(x+185,y+48),(x+190,y+53),(x+185,y+58)],fill=color)
            d.rounded_rectangle((x,y,x+w,y+113), 15, fill=PANEL, outline=color, width=3 if on else 1)
            d.text((x+14,y+12), num, fill=color, font=font(19,True))
            d.text((x+14,y+45),label,fill=FG if on or done else MUTED,font=font(17,True))
            d.text((x+14,y+77),small,fill=MUTED,font=font(14))
        d.rounded_rectangle((42,294,1158,427),16,fill=PANEL)
        d.text((65,313),steps[active][1],fill=TEAL,font=font(22,True))
        d.text((65,351),detail,fill=FG,font=font(21))
        d.text((65,389),event,fill=MUTED,font=font(18))
        d.rectangle((42,447,1158,451),fill="#244253")
        d.rectangle((42,447,42+int(1116*(active*6+sub+1)/36),451),fill=TEAL)
        d.text((43,470),"Illustrative sequence • simulated network • no live model calls in this animation",fill=MUTED,font=font(16))
        frames.append(im)
        durations.append(180 if sub < 5 else 1000)
OUT.parent.mkdir(parents=True, exist_ok=True)
frames[0].save(OUT,save_all=True,append_images=frames[1:],duration=durations,loop=0,optimize=True)
print(f"Saved {OUT} ({OUT.stat().st_size:,} bytes)")
