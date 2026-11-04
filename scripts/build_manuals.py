"""Maintain the original PDF designs; do not reflow these manuals from Markdown.

Requires the optional maintainer packages pymupdf and pypdf. Pass the reviewed
original PDFs with --user-source and --technical-source. The application and its
installation requirements do not depend on this authoring utility.
"""
import re
import sys
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader


class OriginalFont:
    def __init__(self, reader, xref):
        from pypdf.generic import IndirectObject
        self.xref = xref
        font = IndirectObject(xref, 0, reader).get_object()
        self.subtype = str(font['/Subtype'])
        self.scale = abs(float(font.get('/FontMatrix',[.001])[0])) if self.subtype == '/Type3' else .001
        raw = font['/ToUnicode'].get_object().get_data().decode('latin1')
        self.chars = {}
        for block in re.findall(r'beginbfchar(.*?)endbfchar', raw, re.S):
            for a,b in re.findall(r'<([0-9a-f]+)>\s*<([0-9a-f]+)>', block, re.I):
                value = bytes.fromhex(b).decode('utf-16-be')
                if value != ' ' or value not in self.chars:
                    self.chars[value] = bytes.fromhex(a)
        for block in re.findall(r'beginbfrange(.*?)endbfrange', raw, re.S):
            for a,b,c in re.findall(r'<([0-9a-f]+)>\s*<([0-9a-f]+)>\s*<([0-9a-f]+)>', block, re.I):
                start,end,target = int(a,16),int(b,16),int(c,16)
                for code in range(start,end+1):
                    self.chars[chr(target+code-start)] = code.to_bytes(len(a)//2,'big')
        self.widths = {}
        self.default_width = 500
        if '/Widths' in font:
            self.widths = {int(font.get('/FirstChar',0))+i:float(width) for i,width in enumerate(font['/Widths'])}
        else:
            desc = font['/DescendantFonts'][0].get_object()
            self.default_width = float(desc.get('/DW',1000))
            values = desc.get('/W', [])
            index = 0
            while index < len(values):
                start = int(values[index]); next_value = values[index+1]; index += 2
                if isinstance(next_value,list):
                    for offset,width in enumerate(next_value): self.widths[start+offset] = float(width)
                else:
                    end = int(next_value); width = float(values[index]); index += 1
                    for code in range(start,end+1): self.widths[code] = width
        self.flipped = self.subtype == '/Type3' and float(font['/FontMatrix'][3]) < 0
        base = str(font.get('/BaseFont',''))
        self.space_adjust = 600 if 'Mono' in base else 250
        if ' ' in self.chars:
            self.space_adjust = self.widths.get(int.from_bytes(self.chars[' '],'big'), self.space_adjust) * self.scale * 1000

    def width(self, text, size):
        result = 0
        for ch in text:
            if ch == ' ': result += self.space_adjust * size / 1000; continue
            if ch not in self.chars: raise ValueError(f'font {self.xref} has no {ch!r}')
            result += self.widths.get(int.from_bytes(self.chars[ch],'big'), self.default_width) * size * self.scale
        return result

    def command(self,text,x,y,size,color,height):
        parts = []
        for word in re.split('( )',text):
            if not word: continue
            if word == ' ': parts.append(str(-self.space_adjust))
            else: parts.append('<'+b''.join(self.chars[c] for c in word).hex()+'>')
        r,g,b = color
        return f'q {r:.5f} {g:.5f} {b:.5f} rg BT /RS{self.xref} {size:.4f} Tf 1 0 0 1 {x:.4f} {height-y:.4f} Tm ['+' '.join(parts)+'] TJ ET Q\n'


def append(page, data):
    doc=page.parent
    xref=doc.get_new_xref();doc.update_object(xref,'<<>>')
    doc.update_stream(xref,page.read_contents()+b'\n'+data.encode('ascii'))
    page.set_contents(xref)


def register(page,font):
    doc=page.parent
    doc.xref_set_key(page.xref, 'Resources/Font/RS'+str(font.xref), f'{font.xref} 0 R')


import json
import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs'
AUDIT = None
WHITE = (1,1,1)
INK = (23/255,35/255,38/255)
TEAL = (13/255,82/255,87/255)
ORANGE = (194/255,65/255,12/255)


class Runs(HTMLParser):
    def __init__(self,text):
        super().__init__();self.style='body';self.items=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        if tag in ('b','code'):self.style=tag
        if tag=='br':self.items.append(('\n','body'))
    def handle_endtag(self,tag):self.style='body'
    def handle_data(self,data):self.items.extend((word,self.style) for word in re.split(r'(\s+)',data) if word)


class FullMono:
    native=True
    def __init__(self):
        self.path=ROOT/'docs/assets/fonts/IBMPlexMono-Regular.ttf'
        self.font=fitz.Font(fontfile=str(self.path))
    def width(self,text,size):return self.font.text_length(text,fontsize=size)


class CompositeFont:
    def __init__(self,fonts):self.fonts=fonts
    def pick(self,ch):
        return next((f for f in self.fonts if ch==' ' or ch in f.chars),None)
    def width(self,text,size):
        total=0
        for ch in text:
            f=self.pick(ch)
            if f is None:raise ValueError(f'No matching embedded glyph for {ch!r}')
            total+=f.width(ch,size)
        return total
    def command(self,text,x,y,size,color,height):
        commands=[]
        for ch in text:
            font=self.pick(ch);commands.append(font.command(ch,x,y,size,color,height));x+=font.width(ch,size)
        return ''.join(commands)


class Editor:
    def __init__(self,path,tag):
        self.tag=tag;self.doc=fitz.open(path);self.reader=PdfReader(path)
        self.original_blocks={i+1:p.get_text('dict',flags=0)['blocks'] for i,p in enumerate(self.doc)}
        self.fonts={};self.masks={};self.log=[]
        if tag=='user':self.roles={'body':338,'b':237,'head':167,'code':162}
        else:self.roles={'body':9,'b':150,'head':245,'code':531,'technical':1467,'technical_b':1472,'technical_head':1462,'technical_code':1499}
        if tag=='technical':
            names={f[3]:f[0] for p in self.doc for f in p.get_fonts() if f[3]}
            self.roles['technical_code']=names['EAAAAA+AnthropicMonoPrint-Regular']
            self.roles['code']=names['ABAAAA+IBMPlexMono-Regular']

    def font(self,role):
        if self.tag=='user' and role=='code':
            if 'mono' not in self.fonts:self.fonts['mono']=FullMono()
            return self.fonts['mono']
        xref=self.roles.get(role,role)
        if self.tag=='technical' and xref in (9,150,245):
            key=f'combined-{xref}'
            if key not in self.fonts:
                others=[65] if xref==9 else [245,129,65]
                self.fonts[key]=CompositeFont([OriginalFont(self.reader,ref) for ref in dict.fromkeys([xref]+others)])
            return self.fonts[key]
        if xref not in self.fonts:self.fonts[xref]=OriginalFont(self.reader,xref)
        return self.fonts[xref]

    def erase(self,n,rect,bg=WHITE,graphics=0):
        page=self.doc[n-1];rect=fitz.Rect(rect)
        page.add_redact_annot(rect,fill=False,cross_out=False)
        page.apply_redactions(images=0,graphics=graphics,text=0)
        if bg is not None:page.draw_rect(rect,color=None,fill=bg,overlay=True)
        self.masks.setdefault(n,[]).append(list(rect))

    def box(self,n,rect,text,size=9.4,role='body',color=INK,bg=WHITE,leading=None):
        rect=fitz.Rect(rect);leading=leading or size*1.54
        self.erase(n,rect,bg)
        page=self.doc[n-1];x,y=rect.x0,rect.y0+size*.80
        commands=[];last_space=False
        for word,style in Runs(text).items:
            if word=='\n':x=rect.x0;y+=leading;last_space=False;continue
            if word.isspace():
                space_role=role
                space_size=size
                if style=='code':space_role='technical_code' if role=='technical' else 'code';space_size=size*.85
                if x>rect.x0 and not last_space:x+=self.font(space_role).width(' ',space_size)
                last_space=True;continue
            chosen=role
            token_size=size
            if style=='b':chosen='technical_b' if role=='technical' else 'b'
            if style=='code':chosen='technical_code' if role=='technical' else 'code';token_size=size*.85
            font=self.font(chosen)
            width=font.width(word,token_size)
            if x+width>rect.x1+.1:
                x=rect.x0;y+=leading
            if y+size*.23>rect.y1+.2:
                raise ValueError(f'OVERFLOW {self.tag} p{n} {tuple(rect)} at {word!r}; {text}')
            if isinstance(font,CompositeFont):
                for member in font.fonts:register(page,member)
            elif not getattr(font,'native',False):register(page,font)
            if style=='code':
                chip=fitz.Rect(x-.7,y-token_size*.93,x+width+.7,y+token_size*.2)
                page.draw_rect(chip,color=(.83,.87,.87),fill=(.95,.97,.97),width=.25)
            if getattr(font,'native',False):
                page.insert_text((x,y),word,fontname='RSFullMono',fontfile=str(font.path),fontsize=token_size,color=color)
            else:commands.append(font.command(word,x,y,token_size,color,page.rect.height))
            x+=width;last_space=False
        append(page,''.join(commands));self.log.append({'page':n,'rect':list(rect),'text':text})

    def blocks(self,n,first,last,text,**kwargs):
        bs=self.original_blocks[n][first:last+1]
        rect=fitz.Rect(bs[0]['bbox'])
        for b in bs[1:]:rect|=fitz.Rect(b['bbox'])
        # Paragraphs use the existing text column, not the last short line's width.
        if kwargs.pop('column',True):rect.x0=45 if self.tag=='user' else 46.1;rect.x1=550
        rect.y0-=1;rect.y1+=2
        if 'color' not in kwargs:
            spans=[s for b in bs for l in b.get('lines',[]) for s in l['spans']]
            if spans:
                value=spans[0]['color'];kwargs['color']=((value>>16&255)/255,(value>>8&255)/255,(value&255)/255)
        self.box(n,rect,text,**kwargs)

    def token(self,n,old,new):
        page=self.doc[n-1]
        matches=page.search_for(old)
        if not matches:raise ValueError(f'Cannot find {old!r} on {self.tag} {n}')
        for rect in matches:
            spans=[s for b in self.original_blocks[n] for l in b.get('lines',[]) for s in l['spans'] if fitz.Rect(s['bbox']).intersects(rect)]
            span=spans[0];name=span['font'];match=re.search(r'Type3 \((\d+)',name)
            if 'Mono' in name and self.tag=='user':role='code'
            elif match:role=int(match.group(1))
            else:
                fonts=self.doc[n-1].get_fonts()
                role=next(f[0] for f in fonts if name in f[3] or f[3].split('+')[-1].startswith(name))
            size=span['size'];r=fitz.Rect(rect.x0-.2,rect.y0-.5,rect.x1+.3,rect.y1+1)
            c=span['color'];color=((c>>16&255)/255,(c>>8&255)/255,(c&255)/255)
            self.box(n,r,new,size=size,role=role,color=color,leading=size*1.2)

    def save(self,path):
        metadata=dict(self.doc.metadata);metadata['modDate']='D:20261104';self.doc.set_metadata(metadata)
        self.doc.save(path,garbage=3,deflate=True)
        if AUDIT is not None:
            (AUDIT/(self.tag+'-changes.json')).write_text(json.dumps({'masks':self.masks,'edits':self.log},indent=2),encoding='utf-8')


def user_updates(e):
    e.box(1,(51,782,165,797),'4 November 2026',size=7.8,color=(.235,.29,.31))
    e.box(1,(176.3,782,290,797),'main + local demo/voice update',size=7.8,color=(.235,.29,.31))
    # Change only the version digit in the letter-spaced cover label.
    raw=e.doc[0].get_text('rawdict')
    zero=[c for b in raw['blocks'] for l in b.get('lines',[]) for s in l['spans'] for c in s['chars'] if c['c']=='0' and 140<c['bbox'][1]<160]
    if zero:
        r=fitz.Rect(zero[-1]['bbox']);e.box(1,(r.x0-.2,r.y0-.1,r.x1+.5,r.y1+1),'1',size=8.4,role='body',color=(.66,.83,.85),bg=None,leading=10)
    e.box(2,(182.8,201,540,215),'1.1, local submission update',size=8.3)
    e.box(2,(182.8,222.5,540,236),'4 November 2026',size=8.3)
    e.box(2,(182.8,243.8,540,259),'RAN Sentinel, main with local no-login, speech and conversation-memory updates',size=8.3)
    e.blocks(2,15,20,'Sections A and B explain what the system is and how it is built. Section C takes you from an empty folder to a running application, and every command is labelled with its folder. Section D is the user guide, one feature at a time. Section E is a visual walkthrough: the original screenshots are from 1 November, with entry and voice captures updated on 4 November; numbered markers match the notes. Section F describes the automated tests and the results actually produced. Section G is a timed demonstration script for judges, and Section H collects known problems and their fixes.')
    e.box(2,(51.8,673,76,698),'1.1',size=8.3)
    e.box(2,(84,673,117,699),'4 Nov<br>2026',size=8.3,leading=11)
    e.box(2,(130,673,540,700),'Updates the existing manual: open demo entry, local device speech, session memory and current verification. Original design and explanations retained.',size=8.3,leading=11.8)
    # Existing contents and figure list retain their page-number columns.
    e.box(3,(58,410,430,424),'C7 First run and demo entry',size=8.6)
    e.box(3,(58,481,430,495),'D1 Opening the operations console',size=8.6)
    e.box(3,(58,578,500,592),'D7 Customer app: demo entry, home, network and reports',size=8.6)
    e.box(4,(45,371.8,264,383),'Figure 1. Operations console demo entry.',size=7.4)
    e.box(4,(45,587.5,264,599),'Figure 14. Customer demo entry.',size=7.4)
    # Architecture: edit text inside the existing boxes; retain all shapes and arrows.
    e.box(7,(208,89,389,112),'main.py<br>routes, demo entry, sessions, security headers',size=7.79,leading=10.3,bg=(.94,.97,.97))
    e.box(7,(457.5,154.5,533,167.5),'Local OS voice',size=7.79,role='head',bg=(.96,.98,.98))
    e.box(7,(457.5,167,533,181),'spoken answers',size=7.05,bg=(.96,.98,.98))
    e.box(7,(457.5,181,533,192),'No speech API key',size=6.67,color=(.36,.41,.44),bg=(.96,.98,.98))
    e.box(7,(197.4,402.8,544,417),'HTTP routes, no-login demo sessions, optional private login, security headers and the tick loop.',size=7.9,leading=10)
    e.box(7,(197.4,523.8,544,538),'Customer tools; voice_memory.py holds session context, proposals, outcomes and retries.',size=7.9,leading=10)
    e.box(8,(161.6,75.5,403,100),'seq (integer key), id (CS-100001 and up), owner (session identity), status, category, priority, created,',size=7.9,leading=11)
    e.blocks(8,11,15,'Diagram 2 follows a request from the contact form to the care team and back. The server validates every field, takes ownership from the session rather than the request body, then stores the ticket and first message together. The desk marks new messages; replies and status notes are stored and flagged unread. Open customer threads refresh every five seconds. This local demo shares one fictional customer identity, while voice conversations and pending approvals are separate per session.')
    e.blocks(9,4,9,'Choose <b>Explore engineer demo</b> or <b>Explore customer demo</b>. <code>POST /api/demo/start</code> creates an HttpOnly, SameSite=Lax role-scoped cookie: <code>rs_ops</code> or <code>rs_connect</code>. No email, password, access code or outside account is required. A customer cookie cannot authorize an engineer API, even if copied into the other cookie name. Both roles are intentionally open for local sample-data evaluation; they are not production identities. Customer confirmation and engineer approval still apply.')
    e.blocks(9,10,16,'Support ownership is taken from the server session, never a client-supplied owner. Staff routes alone change status or priority. All local visitors share the fictional customer account and its sample records; do not enter private information. Voice histories and pending proposals are separated per demo session. Text is length-limited, cleaned of control characters and escaped on display. Sessions live in RAM and end on logout or restart. Production would require a real identity provider, private roles and persistent sessions (Section H).')
    e.box(9,(51.8,622.5,218,648),'Installed local English voice',size=8.3,leading=12)
    e.box(9,(225,622.5,270,648),'Optional',size=8.3)
    e.box(9,(276.8,622.5,543,648),'Reads replies on this device; no speech key or cloud TTS. Text only remains available.',size=8.3,leading=12)
    e.blocks(10,7,10,'Double-click <code>start.bat</code> in the project folder. It creates <code>.venv</code> if needed, checks requirements on every run and creates <code>.env</code> only when missing. It starts the server and prints both portal URLs; open them yourself. Keep the terminal open while using the app. Press Ctrl+C to stop. Existing private configuration is preserved.')
    e.box(10,(54.5,376,283,440),'py -3 -m venv .venv<br>$py = ".\\.venv\\Scripts\\python.exe"<br>&amp; $py -m pip install -r requirements.txt<br>if (!(Test-Path .env)) { cp .env.example .env }<br>&amp; $py run.py',size=7.35,role='code',color=(.91,.94,.94),bg=(.063,.17,.18),leading=12.1)
    e.box(10,(312,376,541,440),'python3 -m venv .venv<br>.venv/bin/python -m pip install -r requirements.txt<br>[ -f .env ] || cp .env.example .env<br>.venv/bin/python run.py',size=7.35,role='code',color=(.91,.94,.94),bg=(.063,.17,.18),leading=12.1)
    e.blocks(10,25,26,'Python 3.14 matches the verified installation series. These commands call the environment directly; activation is unnecessary. On Ubuntu/Debian, install <code>python3-venv</code> if venv creation fails, then repeat setup.')
    for rect,text in [((50,583,194,610),'Engineer demo'),((200,583,324,610),'No login'),((332,583,544,610),'Choose Explore engineer demo. Both roles use fictional local sample data.'),((50,613,194,640),'Customer demo'),((200,613,324,640),'No login'),((332,613,544,640),'Choose Explore customer demo. No outside account or API key is needed.'),((50,673,194,688),'Speech output'),((200,673,324,688),'Local device'),((332,673,544,688),'Installed English voice; or Text only.')]:
        e.box(10,rect,text,size=7.9,leading=11)
    e.blocks(11,5,5,'C7 First run and demo entry',size=12,role='head')
    e.blocks(11,6,8,'Open <code>http://127.0.0.1:8000/ops/</code> and <code>http://127.0.0.1:8000/connect/</code>. Choose each portal\'s Explore demo button; no credentials are needed. Both can remain open in different tabs. The console labels the active engine as Offline rules engine or Meta Model API.')
    e.blocks(11,10,13,'<b>Meta models.</b> Set <code>MODEL_API_KEY</code> privately in <code>.env</code> and restart for live reasoning, microphone transcription and image analysis. Without it, use typed offline conversations. <b>Speech.</b> Select an installed local English voice or Text only; no cloud TTS is called. <b>Maveric.</b> Follow <code>docs/MAVERIC_TWIN.md</code>. <b>Browser checks.</b> Install Playwright as described in Section F.')
    e.box(11,(53.5,406.5,542,420),'Run in: the project folder, using the environment Python',size=7.2,role=772,color=(.9,.94,.94),bg=TEAL)
    e.box(11,(54.5,428,541,467),'.\\.venv\\Scripts\\python.exe -m pytest -q<br># With an isolated server running, in a second terminal:<br>node scripts/check_support_ui.js',size=7.9,role='code',color=(.91,.94,.94),bg=(.063,.17,.18),leading=12.1)
    e.blocks(11,19,20,'Current local verification: <code>206 passed</code> in the Python suite and 101 browser checks passed across speech, navigation, voice, memory, support and refresh scripts. Section F separates tested behavior from physical-device checks.')
    e.blocks(11,25,25,'D1 Opening the operations console',size=12,role='head')
    e.blocks(11,26,29,'Open <code>http://127.0.0.1:8000/ops/</code> and choose <b>Explore engineer demo</b> (Figure 1). It opens the sample shift without an account or password. The customer app has a separate Explore button and role-scoped session. Both are deliberately open local demos; approvals are still required for simulated network changes.')
    e.box(12,(117,137.5,287,152),'Engineers, approvers, care agents',size=7.9,bg=(.95,.98,.98))
    e.box(12,(340,137.5,541,152),'/ops/ - Explore engineer demo',size=7.9,bg=(.95,.98,.98))
    e.box(12,(117,158.5,287,174),'No credentials; sample data',size=7.9,bg=(.95,.98,.98))
    e.box(12,(117,179.8,542,205),'If entry fails, check that the local server is running, then reload. A server restart clears sessions; choose Explore again.',size=7.9,leading=11,bg=(.95,.98,.98))
    e.blocks(13,35,35,'D7 Customer app: demo entry, home, network and reports',size=12,role='head')
    e.blocks(13,36,38,'Open <code>http://127.0.0.1:8000/connect/</code> and choose <b>Explore customer demo</b> (Figure 14). No account or key is needed for the fictional customer and offline tools. The app stays phone-width on larger screens. Home, Network, Account, Bill and Help are the main tabs; the bell opens notifications and Ask opens the assistant.')
    e.blocks(14,14,21,'The Assistant page answers questions about places, bills and settings (Figure 18). Type or choose a suggestion. Changes appear as review cards; nothing changes until the customer confirms. "How I answered" shows the steps and whether Meta or offline rules answered.<br>Ask opens the voice agent (Figure 19). Meta handles live transcription and broader reasoning; typed input also works offline. Replies use an installed local voice or Text only. Memory holds 12 recent messages, brief older notes and one pending proposal. It resolves "report that", corrections and read-back. Review the draft, then confirm in a later turn or cancel. Refresh restores context; New conversation or 30 idle minutes clears it. Tap the orb to interrupt speech.',size=9.4,leading=14.5)
    e.blocks(16,1,4,'Screenshots were captured from the running offline app. The original 1 November walkthrough is retained; demo-entry and voice screenshots were refreshed on 4 November 2026. Console captures are 1440 by 900 and customer captures 390 by 844. Orange outlines and numbers still match the notes under each picture.',size=10.6,leading=16.5)
    e.box(16,(75,500.8,514,514),'Figure 1. Operations console demo entry.',size=7.9)
    e.box(16,(81,516.5,514,542),'1. Sample network notice     2. Explore engineer demo<br>3. Link to the customer app',size=7.9,color=ORANGE,leading=12.5)
    e.box(23,(45,338,165,351),'Figure 14. Customer demo entry.',size=7.1)
    e.box(23,(48,352,164,387),'1. Sample-data explanation<br>2. Explore customer demo<br>3. Link to the engineer app',size=6.9,color=ORANGE,leading=11.5)
    e.box(23,(176.5,716.5,290,750),'1. Local reply voice<br>2. Draft and Confirm / Cancel<br>3. New conversation',size=6.9,color=ORANGE,leading=11.5)
    e.box(26,(53.5,546.5,542,560),'Run in: the project folder (Windows PowerShell)',size=7.2,role=772,color=(.9,.94,.94),bg=TEAL)
    e.box(26,(54.5,568,541,595),'.\\.venv\\Scripts\\python.exe -m pytest -q<br>.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_support.py',size=7.9,role='code',color=(.91,.94,.94),bg=(.063,.17,.18),leading=12.1)
    e.blocks(26,15,17,'Set <code>BASE_URL</code> to select another local port. The browser scripts open the no-login demo and modify fictional sample data. Use an isolated offline server rather than a demo whose state you want to preserve. Voice and speech scripts add memory, interruption, local-only voice selection and navigation regression checks.')
    e.box(27,(438,99.5,459,113),'206',size=7.9)
    e.box(27,(463,99.5,541,113),'206 passed',size=7.9,color=(.114,.478,.275))
    e.box(27,(45,249,550,281),'Windows, Python 3.14.7, offline, 4 Nov 2026: 206 tests passed (375.73 s; 3 SQLite warnings). Also 101 browser checks: 8 speech, 2 navigation, 12 voice, 14 memory, 53 support, 12 refresh. No-key startup passed on Windows and Ubuntu/WSL.',size=7.99,leading=10.8)
    e.box(29,(50,76.5,160,90),'Safari and Firefox',size=7.9)
    e.box(29,(181,76.5,396,90),'Earlier native Safari passed; rerun this revision.',size=7.7)
    e.box(29,(403,76.5,543,90),'Repeat Section G in each browser.',size=7.7)
    e.blocks(29,10,11,'Use this eight-minute no-key walkthrough or its five-minute shortcut. The separate three-minute submission video must show actual live Meta calls, demo entry and local speech.',size=10.6,leading=16.5)
    e.blocks(29,13,16,'Start the app (Section C3 or C4), then open the engineer and customer URLs side by side. Choose Explore engineer demo and Explore customer demo; no credentials are needed. Narrow the customer window to phone width. For a clean support desk, stop the server before removing its demo database. Find Demo controls before beginning.')
    e.blocks(30,9,10,'If the entry page reappears after a server restart, choose Explore again. Sessions live in memory; no password is needed.')
    # Update only obsolete troubleshooting rows, keeping the same table grid.
    for rect,text in [((50,467,158,503),'Venv setup fails'),((165,467,284,503),'Wrong interpreter or missing venv support'),((292,467,543,503),'Use the environment Python directly (Section C4). Ubuntu may need python3-venv.'),((50,568,158,605),'No spoken reply'),((165,568,284,605),'No installed local English voice, or Text only selected'),((292,568,543,605),'Choose a local voice in Ask, check device volume, or keep reading the full written answer.'),((50,609,158,625),'Microphone cannot transcribe'),((165,609,284,625),'Meta access or permission'),((292,609,543,625),'Allow the microphone; use typed input without Meta access.'),((50,628,158,654),'Returned to demo entry'),((292,628,543,654),'Choose Explore again. No credentials are required.')]:
        e.box(30,rect,text,size=7.6,leading=10.5)
    e.blocks(31,10,11,'Can visitors see sample requests? Yes: the open local demo shares one fictional account. It is not a private customer deployment. Voice histories and pending voice approvals remain separate per session.')
    e.blocks(31,16,18,'Is it ready for production? Not as is. Replace open demo access with real identity and roles; add persistent sessions, HTTPS, a suitable server database and tested multi-customer isolation. The current approval, validation and history mechanisms are a prototype foundation, not proof of production readiness.')
    # Replace only the test count within the existing folder-tree line.
    e.token(32,'177','206')
    # The header already uses a metrically compatible sans face at tiny size.
    for n in range(2,33):
        e.erase(n,(439,13.5,563,22))
        e.doc[n-1].insert_text((443,19.5),'Version 1.1 - 4 November 2026',fontname='helv',fontsize=4.88,color=(.36,.41,.44))


def technical_updates(e):
    e.blocks(1,1,4,'This edition opens with an industry chapter (Part A). It explains which problems in mobile network operations RAN Sentinel addresses, how large the market for this kind of software is, what an operator could gain, and how the system would move from a prototype to production. The technical manual follows as Part B, updated for no-login demo access, local speech and conversation memory.',size=10.6,leading=16.5)
    e.box(1,(307.8,586.8,537,601),'Part B - Technical manual (updated 4 Nov 2026)',size=8.8,role='b')
    e.box(1,(535,587,549,601),'23',size=8.8,color=TEAL)
    sample=e.doc[0].get_pixmap(clip=fitz.Rect(520,200,521,201),alpha=False).pixel(0,0)
    hero_bg=tuple(v/255 for v in sample)
    e.box(1,(74,197,537,222),'Technical documentation - updated 4 November 2026 - AKMaasif (QuanTell) - MIT licence<br>github.com/AKMaasif/Meta-Ai-Global-Hackathon-Ran-Sentinel-',size=8.59,leading=12,color=(.84,.9,.9),bg=hero_bg)
    e.box(3,(189,633,456,670),'Customer app with confirmed updates, reports and a Muse Spark concierge. Session memory supports voice follow-ups and draft review; replies use local device speech.',size=8.29,leading=11.5)
    e.box(20,(343,463.8,542,487.2),'Open sample-data roles, portal-scoped sessions, upload hardening and security headers',size=8.1,leading=11.2)
    e.box(22,(48,646.5,544,663),'Current checks (4 Nov): 206 Python tests and 101 browser checks passed. Market and benchmark dates are unchanged.',size=8.2,leading=11.2)
    e.box(23,(53,98,400,116),'4 November 2026 - AKMaasif (QuanTell)',size=9.74,role='technical',color=(.32,.32,.32))
    # Expand the existing customer-care paragraph in its own space, without adding pages.
    e.box(36,(62.8,291.2,549,384),'Ask us uses published updates and scoped tools. Meta handles live transcription and broader reasoning; typed input works offline. Replies use local speech or Text only. Memory holds 12 messages, older notes, the issue and one proposal. Follow-ups revise the draft; confirm in a later turn or cancel. Refresh restores context; New conversation clears it. Customer text filters hide internal network details.',size=11.98,role='technical',leading=17.7)
    e.blocks(37,8,11,'<b>Quick start on Windows:</b> double-click <code>start.bat</code> in the cloned project folder. It creates the environment if needed, checks requirements and preserves an existing <code>.env</code>. It starts the server and prints the two portal URLs. Open them yourself and keep the terminal running.',size=11.98,role='technical',leading=17.8)
    e.box(37,(54.8,525,541,654),'py -3 -m venv .venv<br>.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt<br>.\\.venv\\Scripts\\python.exe run.py<br>macOS / Linux:<br>python3 -m venv .venv<br>.venv/bin/python -m pip install -r requirements.txt<br>.venv/bin/python run.py',size=10.48,role='technical_code',color=(.22,.23,.2),bg=(.965,.961,.94),leading=15.7)
    e.blocks(37,14,14,'Open http://127.0.0.1:8000/ops/ or /connect/ and choose Explore demo. No credentials are needed; both roles show open, fictional sample data.',size=11.98,role='technical',leading=17.8)
    e.box(38,(51,327,294,364),'Demo access and speech',size=11.26,role='technical')
    e.box(38,(304,329,541,362),'Open sample data; installed local voices. No login or TTS key.',size=11.26,role='technical',leading=16.4)
    e.blocks(38,0,0,'<b>Tests:</b> <code>python -m pytest -q</code> passed 206 tests locally (4 Nov). They cover:',size=11.98,role='technical',leading=17.5)
    e.box(38,(62.8,548.8,549,584.8),'Meta media request formats, customer tools, voice memory, draft corrections and confirmation guards;',size=11.98,role='technical',leading=17.7)
    e.box(38,(62.8,608.8,549,627),'alarms, support, no-login entry and session boundaries.',size=11.98,role='technical')
    e.box(39,(365.8,200,541,282),'Earlier live transcription passed. Recheck the physical microphone and installed voice on this revision. Recognition accuracy is not benchmarked.',size=11.26,role='technical',leading=16.4)
    e.box(39,(214,200,355,282),'Meta transcription verified previously; revised hardware check pending.',size=11.26,role='technical',leading=16.4)
    e.box(39,(365.8,392,541,426),'206 application tests; 101 browser checks passed locally.',size=11.26,role='technical',leading=16.4)
    e.box(39,(62.8,681.4,549,718),'<b>Twin.</b> Maveric optionally predicts RF coverage; otherwise the labelled simulator twin is used. Neither is a live network measurement.',size=11.98,role='technical',leading=17.6)
    e.box(41,(54.4,222.5,167,256),'Nov 3-4',size=11.26,role='technical')
    e.box(41,(184,222.5,540,256),'Memory, open demo entry and local speech updated; local tests passed. Owner listening check and new Meta demo video pending.',size=10.8,role='technical',leading=15.4)


def update_screenshots(e):
    assets=ROOT/'docs/assets'
    specs=[(16,2000,1250,'manual-engineer-entry.png'),(23,780,1688,'manual-customer-entry.png'),(23,780,1688,'manual-voice-draft.png')]
    for n,w,h,name in specs:
        page=e.doc[n-1]
        info=[i for i in page.get_image_info(xrefs=True) if i['width']==w and i['height']==h]
        old=info[-1] if 'voice' in name else info[0]
        rect=fitz.Rect(old['bbox']);page.replace_image(old['xref'],filename=str(assets/name))
        e.erase(n,rect,bg=None,graphics=2)
        # Keep original screenshot dimensions, rounded frame and orange callout style.
        if 'engineer' in name:
            boxes=[(24,418,416,454),(24,479,416,516),(24,539,416,573)];dims=(1440,900)
        elif 'customer' in name:
            boxes=[(23,393,367,427),(23,451,367,496),(23,517,367,567)];dims=(390,844)
        else:
            boxes=[(30,530,360,570),(15,703,374,790),(263,265,310,310)];dims=(390,844)
        sx,sy=rect.width/dims[0],rect.height/dims[1]
        for index,(x0,y0,x1,y1) in enumerate(boxes,1):
            mark=fitz.Rect(rect.x0+x0*sx,rect.y0+y0*sy,rect.x0+x1*sx,rect.y0+y1*sy)
            page.draw_rect(mark,color=ORANGE,width=.7)
            radius=4.5 if n==16 else 3.9
            center=fitz.Point(mark.x0+radius,mark.y0)
            page.draw_circle(center,radius,color=ORANGE,fill=ORANGE)
            page.insert_text((center.x-radius*.43,center.y+radius*.45),str(index),fontsize=radius*1.5,fontname='hebo',color=WHITE)


def main():
    import argparse
    import hashlib
    global OUT, AUDIT
    parser=argparse.ArgumentParser(description="Update content in the original PDF layouts without rebuilding from Markdown.")
    parser.add_argument('--user-source',type=Path,required=True,help="Original 32-page user manual")
    parser.add_argument('--technical-source',type=Path,required=True,help="Original 41-page technical document")
    parser.add_argument('--output-dir',type=Path,default=ROOT/'docs')
    parser.add_argument('--audit-dir',type=Path)
    args=parser.parse_args()
    for source,expected in ((args.user_source,'b303d35a9cf53f09383588a0c8e7fefff99380f37ca4c25f5f0ef506aa404d8a'),(args.technical_source,'7efb7cfc075b7395cfdc9ae31e0ca62395d26cc76dbb73ad6cdbe00abd8afda5')):
        if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
            raise ValueError("This updater needs the reviewed original template; source differs: "+str(source))
    OUT=args.output_dir.resolve();OUT.mkdir(parents=True,exist_ok=True)
    AUDIT=args.audit_dir
    if AUDIT is not None:AUDIT.mkdir(parents=True,exist_ok=True)
    for source,name in ((args.user_source,'PROJECT_COMPLETE_USER_MANUAL.pdf'),(args.technical_source,'RAN_Sentinel_Technical_Documentation.pdf')):
        if source.resolve()==(OUT/name).resolve():raise ValueError("Keep the original source separate from the output")
    user=Editor(args.user_source,'user')
    user_updates(user);update_screenshots(user)
    user.save(OUT/'PROJECT_COMPLETE_USER_MANUAL.pdf')
    tech=Editor(args.technical_source,'technical')
    technical_updates(tech);tech.save(OUT/'RAN_Sentinel_Technical_Documentation.pdf')
    assert len(user.doc)==32 and len(tech.doc)==41
    print('Updated content; original layouts retained: 32 and 41 pages.')


if __name__=='__main__':main()
