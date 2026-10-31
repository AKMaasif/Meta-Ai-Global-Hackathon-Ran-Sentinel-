from __future__ import annotations

import csv
import io
import re
import statistics
import zipfile
import xml.etree.ElementTree as ET

MAX_BYTES = 10_000_000
MAX_CHARS = 12_000
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
KINDS = {
    "text/csv": "csv", "application/vnd.ms-excel": "csv", "application/csv": "csv",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
}
EXT = {".csv": "csv", ".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".log": "txt"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocError(ValueError):
    pass


def kind_of(mime: str, name: str) -> str | None:
    if mime in KINDS:
        return KINDS[mime]
    m = re.search(r"\.[A-Za-z0-9]+$", name or "")
    return EXT.get(m.group(0).lower()) if m else None


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _num(v: str) -> float | None:
    try:
        return float(v.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def read_csv(data: bytes) -> dict:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise DocError("the CSV is empty")
    head, body = rows[0], rows[1:]
    stats = []
    for i, col in enumerate(head):
        vals = [x for x in (_num(r[i]) for r in body if i < len(r)) if x is not None]
        if len(vals) >= max(1, len(body) // 2):
            stats.append({"column": col.strip()[:60], "n": len(vals), "min": round(min(vals), 3), "max": round(max(vals), 3),
                          "mean": round(statistics.fmean(vals), 3), "last": round(vals[-1], 3)})
    sample = "\n".join(", ".join(c.strip() for c in r) for r in [head] + body[:25])
    return {"kind": "csv", "rows": len(body), "columns": [h.strip()[:60] for h in head][:40], "stats": stats[:30],
            "text": sample[:MAX_CHARS]}


def read_docx(data: bytes) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        raise DocError("this is not a readable .docx file")
    root = ET.fromstring(xml)
    lines, tables = [], 0
    for el in root.iter():
        if el.tag == W + "tbl":
            tables += 1
        if el.tag == W + "p":
            t = "".join(x.text or "" for x in el.iter(W + "t")).strip()
            if t:
                lines.append(t)
    text = "\n".join(lines)
    if not text.strip():
        raise DocError("the document has no text")
    return {"kind": "docx", "paragraphs": len(lines), "tables": tables, "text": text[:MAX_CHARS]}


def read_pdf(data: bytes) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise DocError("PDF support needs pypdf: pip install -r requirements.txt")
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "").strip() for p in reader.pages[:30]]
    except Exception as e:
        raise DocError(f"could not read the PDF ({type(e).__name__})")
    text = "\n\n".join(f"[page {i + 1}]\n{t}" for i, t in enumerate(pages) if t)
    if not text:
        raise DocError("the PDF has no text layer (a scan); photograph the pages and attach the photos instead")
    return {"kind": "pdf", "pages": len(reader.pages), "text": text[:MAX_CHARS]}


def read_txt(data: bytes) -> dict:
    text = _decode(data).strip()
    if not text:
        raise DocError("the file is empty")
    return {"kind": "txt", "text": text[:MAX_CHARS]}


def extract(data: bytes, mime: str, name: str) -> dict:
    if not data:
        raise DocError("the file is empty")
    if len(data) > MAX_BYTES:
        raise DocError("files must be under 10 MB")
    k = kind_of(mime, name)
    if not k:
        raise DocError("attach a photo (JPEG, PNG, WebP), CSV, PDF, DOCX or TXT file")
    out = {"csv": read_csv, "docx": read_docx, "pdf": read_pdf, "txt": read_txt}[k](data)
    out["truncated"] = len(out["text"]) >= MAX_CHARS
    return out
