"""Original, script-free animated SVGs for the RAN Sentinel README."""
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / 'docs' / 'assets'
STYLE = '''<style>
svg{--bg:#fafbf9;--panel:#fff;--ink:#172a30;--mut:#63767c;--line:#dce5e3;--accent:#087f80;--soft:#dff2ee;--red:#c34f44;--gold:#a87520}
@media(prefers-color-scheme:dark){svg{--bg:#101b23;--panel:#172832;--ink:#edf6f5;--mut:#9eb4bc;--line:#304852;--accent:#5edac6;--soft:#213e42;--red:#f28b7e;--gold:#e5b768}}
text{font-family:'Segoe UI',Helvetica,Arial,sans-serif;fill:var(--ink)}.mut{fill:var(--mut)}.accent{fill:var(--accent)}.cap{font-size:11px;letter-spacing:1.6px;fill:var(--mut)}.wire{fill:none;stroke:var(--line);stroke-width:2}.card{fill:var(--panel);stroke:var(--line)}
@media(prefers-reduced-motion:reduce){.motion{display:none}}
</style>'''

def text(x,y,s,size=15,cls='',weight=400,anchor='start'):
    return f'<text x="{x}" y="{y}" font-size="{size}" class="{cls}" font-weight="{weight}" text-anchor="{anchor}">{escape(s)}</text>'

def box(x,y,w,h,title,sub,color='var(--line)'):
    return f'<rect class="card" x="{x}" y="{y}" width="{w}" height="{h}" rx="12" style="stroke:{color}"/>'+text(x+17,y+27,title,16,weight=600)+text(x+17,y+49,sub,12,'mut')

def path(p,dash=False):
    return f'<path d="{p}" class="wire"'+(' stroke-dasharray="5 6"' if dash else '')+'/>'

def packet(p,start,end,color='var(--accent)',duration=12):
    # Phase-local motion and visibility share a cycle; no JS, external assets or fonts.
    a,b=start/duration,end/duration
    return f'''<circle class="motion" r="5" fill="{color}" opacity="0">
<animateMotion dur="{duration}s" repeatCount="indefinite" calcMode="linear" path="{p}" keyPoints="0;0;1;1" keyTimes="0;{a:.4f};{b:.4f};1"/>
<animate attributeName="opacity" dur="{duration}s" repeatCount="indefinite" values="0;0;1;1;0;0" keyTimes="0;{max(0,a-.005):.4f};{a:.4f};{b:.4f};{min(1,b+.005):.4f};1"/></circle>'''

def pulse(x,y,r=12):
    return f'<circle class="motion" cx="{x}" cy="{y}" r="{r}" fill="none" stroke="var(--accent)" opacity=".4"><animate attributeName="r" values="{r};{r+20}" dur="3s" repeatCount="indefinite"/><animate attributeName="opacity" values=".6;0" dur="3s" repeatCount="indefinite"/></circle>'

def save(name,h,title,body):
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="{h}" viewBox="0 0 1100 {h}" role="img" aria-label="{escape(title)}"><title>{escape(title)}</title>{STYLE}<rect x="1" y="1" width="1098" height="{h-2}" rx="18" fill="var(--bg)" stroke="var(--line)"/>{body}</svg>'
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(svg,encoding='utf-8')

def hero():
    b=text(38,42,'RAN SENTINEL / AI NETWORK CO-ENGINEER',11,'cap')
    b+=text(38,107,'Network signals in.',39,weight=700)+text(38,156,'Evidence-led decisions out.',36,'accent',700)
    b+=text(38,202,'Meta agents investigate. Code checks the plan.',17,'mut')+text(38,229,'An engineer decides what happens next.',17,'mut')
    # A radio mast, three evidence streams, and a checked incident record.
    b+='<path d="M568 225 L591 135 L614 225 M578 188 H604 M572 209 H610" fill="none" stroke="var(--ink)" stroke-width="3"/>'
    b+='<circle cx="591" cy="130" r="6" fill="var(--accent)"/>'+pulse(591,130)
    for y,label in [(86,'KPIs'),(150,'ALARMS'),(214,'CONFIG')]:
        p=f'M620 150 C655 150 655 {y} 691 {y}'
        q=f'M803 {y} C845 {y} 843 150 885 150'
        b+=path(p)+path(q)
        b+=f'<rect x="691" y="{y-18}" width="112" height="36" rx="18" class="card"/>'+text(747,y+5,label,12,'mut',600,'middle')
        i=[86,150,214].index(y)
        b+=packet(p,.2+i*.7,2+i*.7)+packet(q,3+i*.6,4.8+i*.6)
    b+='<rect x="885" y="103" width="168" height="102" rx="14" class="card"/>'
    b+=text(969,132,'INCIDENT',12,'cap',anchor='middle')+text(969,157,'Evidence + plan',16,weight=600,anchor='middle')
    b+='<path d="M947 178 l8 8 16-18" stroke="var(--accent)" stroke-width="3" fill="none"/>'
    b+=text(38,285,'SIMULATED NETWORK  /  ILLUSTRATED FLOW  /  FULL WORKING DEMO BELOW',10,'cap')
    save('ran-sentinel-hero.svg',310,'Network signals become evidence-led engineering decisions',b)

def investigation():
    b=text(32,36,'INSIDE AN INVESTIGATION',11,'cap')+text(32,66,'The agent follows the evidence, not the first suspicion.',25,weight=600)
    for y,title,sub in [(110,'KPI history','Trends, load and radio quality'),(197,'Alarm history','Events and timestamps'),(284,'Running configuration','Compared with the radio plan')]:
        p=f'M264 {y+31} C307 {y+31} 302 228 350 228'
        b+=path(p)+box(32,y,232,64,title,sub)
        i=[110,197,284].index(y)
        b+=packet(p,.4+i*.6,2.6+i*.6)
    b+=box(350,187,238,83,'Muse Spark investigator','Read-only tools • evidence IDs','var(--accent)')
    for k in range(4):
        b+=f'<rect x="{371+k*47}" y="247" width="35" height="5" rx="2" fill="var(--accent)" opacity=".25"><animate attributeName="opacity" values=".2;1;.2" begin="{k*.35}s" dur="2s" repeatCount="indefinite"/></rect>'
    p='M588 228 C629 228 627 154 668 154'
    b+=path(p)+packet(p,4,5.5)+box(668,117,182,76,'Compare causes','Support + contradictions')
    q='M850 154 C883 154 872 228 905 228'
    b+=path(q)+packet(q,5.6,7)+box(905,187,164,83,'Verify facts','Evidence + playbook','var(--accent)')
    r='M986 270 C986 326 857 326 850 326'
    b+=path(r,True)+packet(r,7.2,8.5,'var(--gold)')+box(668,295,182,66,'Need more evidence?','Ask the field • then resume','var(--gold)')
    r='M668 326 C623 326 621 249 588 249'
    b+=path(r,True)+packet(r,8.6,10.4,'var(--gold)')
    b+=text(32,402,'The workflow can pause for field input. A plausible answer alone is not a verified diagnosis.',14,'mut')
    save('ran-sentinel-investigation.svg',430,'Read-only evidence retrieval, cause comparison, fact verification and field evidence loop',b)

def safety():
    b=text(32,36,'FROM PROPOSAL TO OUTCOME',11,'cap')+text(32,66,'A model proposes. An engineer approves.',27,weight=600)
    for x,title,sub in [(32,'Proposed plan','Action + rollback'),(293,'Rules + twin','Limits + what-if'),(554,'Engineer review','Approve or reject'),(815,'Monitor recovery','Confirm or roll back')]:
        b+=box(x,126,222,77,title,sub,'var(--accent)' if x==554 else 'var(--line)')
    for i in range(3):
        p=f'M{254+i*261} 164 L{293+i*261} 164'
        b+=path(p)+packet(p,.5+i*2,1.9+i*2)
    p='M404 203 C404 276 143 276 143 203'
    b+=path(p,True)+packet(p,2.4,4.2,'var(--red)')+text(273,273,'Unsafe? Reject and revise.',13,'mut',anchor='middle')
    p='M926 203 C926 320 700 320 700 358'
    b+=path(p)+packet(p,6.6,8.4)+box(570,358,260,65,'Evidence-to-Action Ledger','Record evidence, checks and decisions')
    p='M830 389 L864 389'
    b+=path(p)+packet(p,8.5,9.5)+box(864,358,205,65,'Northstar Connect','Customer-safe updates')
    b+=text(32,338,'Human control stays explicit.',20,weight=600)+text(32,366,'Changes apply to simulated radio units.',14,'mut')
    b+=text(32,390,'This illustration makes no live API calls.',14,'mut')
    save('ran-sentinel-safety.svg',455,'Safety checks, human approval, recovery monitoring and customer updates',b)

if __name__=='__main__':
    hero(); investigation(); safety()
    for p in sorted(OUT.glob('ran-sentinel-*.svg')): print(p.name,p.stat().st_size)
