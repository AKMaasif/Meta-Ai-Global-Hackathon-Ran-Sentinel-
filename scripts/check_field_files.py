# py scripts/check_field_files.py
# py scripts/check_field_files.py --file "D:\reports\site visit.pdf" --file sweep.csv
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import agents, fielddocs  # noqa: E402
from app.agents import AgentContext  # noqa: E402
from app.config import settings  # noqa: E402
from app.providers import MetaProvider, ProviderError  # noqa: E402
from check_meta import test_png  # noqa: E402

FACTS = {"cell": "SEA-RAN-001", "area": "Downtown", "diagnosis": "external_interference",
         "open_request": "Sweep the uplink with a spectrum analyser near the site and look for repeaters or boosters."}


def sample_docx() -> bytes:
    paras = ["Site visit report SEA-RAN-001, 31 Oct 2026", "Spectrum analyser sweep on the roof, 10:00-10:20.",
             "Narrowband emitter at 1712.4 MHz, about -88 dBm, strongest towards the east.",
             "Found an unlicensed cellular booster in the coffee shop across the street. Antennas and feeders look fine."]
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def sample_pdf() -> bytes:
    lines = ["Uplink interference sweep - SEA-RAN-001", "Noise floor east sector: -92 dBm (normal -105 dBm)",
             "Peak at 1712.4 MHz, narrowband, continuous", "VSWR at radio unit 1.2 (normal)"]
    stream = ("BT /F1 12 Tf 14 TL 72 720 Td " + " ".join(f"({l}) Tj T*" for l in lines) + " ET").encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()


SAMPLES = [
    ("uplink_sweep.csv", "text/csv", ("time,ul_rssi_dbm,sinr_db,prb_util\n" + "\n".join(
        f"10:{m:02d},{-92 + (m % 3) * 0.4:.1f},{4 + (m % 2) * 0.3:.1f},{55 + m % 5}" for m in range(0, 20, 2))).encode()),
    ("site_visit.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", sample_docx()),
    ("sweep_report.pdf", "application/pdf", sample_pdf()),
    ("notes.txt", "text/plain", b"Booster found in the coffee shop east of the site. Switched off at 10:25, RSSI back to -104 dBm."),
]
MIME = {".csv": "text/csv", ".pdf": "application/pdf", ".txt": "text/plain", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def ctx_for(provider):
    return AgentContext(provider, None, {"id": "CHECK", "cell_id": FACTS["cell"]}, lambda *a: "", lambda *a: None, 0)


def check_doc(provider, name, mime, data) -> int:
    t0 = time.time()
    try:
        doc = fielddocs.extract(data, mime, name)
    except fielddocs.DocError as e:
        print(f"  FAIL {name:22s} read: {e}")
        return 1
    what = {k: v for k, v in doc.items() if k in ("rows", "pages", "paragraphs")}
    try:
        f = agents.document_findings(ctx_for(provider), name, doc, FACTS, [settings.primary_model, settings.fallback_model])
    except (ProviderError, agents.AgentOutputError) as e:
        print(f"  FAIL {name:22s} read OK {what}, model: {e}")
        return 1
    print(f"  PASS {name:22s} {time.time() - t0:5.1f}s  {doc['kind'].upper()} {what} -> {f['by']}, fits diagnosis: "
          f"{f['consistent_with_diagnosis']}, supports {f['supports'] or '-'}\n       {f['summary'][:150]}")
    return 0


def check_photo(provider, name, mime, data) -> int:
    t0 = time.time()
    url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    try:
        f = agents.photo_findings(ctx_for(provider), url, [], FACTS, [settings.vision_model, settings.fallback_model])
    except (ProviderError, agents.AgentOutputError) as e:
        print(f"  FAIL {name:22s} vision: {e}")
        return 1
    print(f"  PASS {name:22s} {time.time() - t0:5.1f}s  IMAGE -> {f['by']}: {f['summary'][:120]}")
    return 0


def probe_native_pdf(provider) -> None:
    pdf = "data:application/pdf;base64," + base64.b64encode(sample_pdf()).decode()
    tries = [("Responses API input_file", "/responses", {"model": settings.primary_model, "input": [{"type": "message", "role": "user", "content": [
                 {"type": "input_text", "text": "What is the peak frequency in this report? One line."},
                 {"type": "input_file", "filename": "sweep_report.pdf", "file_data": pdf}]}]}),
             ("Chat Completions file part", "/chat/completions", {"model": settings.primary_model, "max_tokens": 400, "messages": [
                 {"role": "user", "content": [{"type": "text", "text": "What is the peak frequency in this report? One line."},
                                              {"type": "file", "file": {"filename": "sweep_report.pdf", "file_data": pdf}}]}]})]
    for label, path, body in tries:
        try:
            provider._post("file_probe", settings.primary_model, path, json=body)
            print(f"  accepted  {label}")
        except ProviderError as e:
            print(f"  rejected  {label}: {str(e)[:110]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Check that Muse Spark can read every field-evidence file type")
    ap.add_argument("--file", action="append", type=Path, default=[], help="your own file to test (repeatable)")
    a = ap.parse_args()
    if not settings.api_key:
        print("No MODEL_API_KEY in .env")
        return 1
    provider = MetaProvider(settings)
    print(f"Endpoint {settings.base_url} (key ends ...{settings.api_key[-4:]}), model {settings.primary_model}\n")
    fails = 0
    print("Sample files (text is extracted in the app, then Muse Spark reads it):")
    for name, mime, data in SAMPLES:
        fails += check_doc(provider, name, mime, data)
    fails += check_photo(provider, "site_photo.png", "image/png", test_png())
    if a.file:
        print("\nYour files:")
        for p in a.file:
            mime = MIME.get(p.suffix.lower(), "")
            data = p.read_bytes()
            fails += (check_photo if mime.startswith("image/") else check_doc)(provider, p.name, mime, data)
    print("\nDoes the API also take a PDF directly? (information only; the app does not need it)")
    probe_native_pdf(provider)
    print("\nAll file types readable." if not fails else f"\n{fails} check(s) failed.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
