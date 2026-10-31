import io
import json
import zipfile

import pytest

from app import fielddocs
from test_field_evidence import _paused


def make_docx(paragraphs):
    body = "".join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def make_pdf(lines):
    text = " ".join(f"({l}) Tj T*" for l in lines)
    stream = f"BT /F1 12 Tf 14 TL 72 720 Td {text} ET".encode()
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
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()
    return out


CSV = b"time,ul_rssi_dbm,sinr_db\n10:00,-92.5,4.1\n10:05,-91.8,3.9\n10:10,-93.0,4.4\n"


def test_reads_csv_docx_pdf_txt():
    c = fielddocs.extract(CSV, "text/csv", "sweep.csv")
    assert c["kind"] == "csv" and c["rows"] == 3 and c["stats"][0]["column"] == "ul_rssi_dbm" and c["stats"][0]["max"] == -91.8
    d = fielddocs.extract(make_docx(["Site visit report", "Found a loose feeder connector, water in the jumper"]), "", "report.docx")
    assert d["kind"] == "docx" and "loose feeder connector" in d["text"]
    p = fielddocs.extract(make_pdf(["Spectrum analyser sweep", "Narrowband emitter at 1712 MHz east of the site"]), "application/pdf", "sweep.pdf")
    assert p["kind"] == "pdf" and p["pages"] == 1 and "emitter" in p["text"]
    t = fielddocs.extract(b"booster found in the coffee shop", "text/plain", "notes.txt")
    assert t["kind"] == "txt"


def test_rejects_unknown_empty_and_large():
    for data, mime, name in [(b"MZ...", "application/x-msdownload", "a.exe"), (b"", "text/csv", "a.csv"),
                             (b"x" * (fielddocs.MAX_BYTES + 1), "text/plain", "a.txt"), (b"not a zip", "", "a.docx")]:
        with pytest.raises(fielddocs.DocError):
            fielddocs.extract(data, mime, name)


def test_attached_files_go_into_the_field_report(sentinel):
    inc = _paused(sentinel)
    doc = sentinel.add_attachment(inc["id"], make_docx(["Spectrum analyser shows an emitter near the site"]), "", "visit.docx", "Sarah Chen")
    csvrec = sentinel.add_attachment(inc["id"], CSV, "text/csv", "sweep.csv", "Sarah Chen")
    assert doc["type"] == "document" and doc["findings"]["by"] == "rules (offline)" and "external_interference" in doc["findings"]["supports"]
    assert csvrec["facts"]["rows"] == 3 and any(e["tool"] == "field_document" for e in inc["evidence"])
    req = sentinel.provide_evidence(inc["id"], "Sarah Chen", "See attached sweep and report.")
    assert req["answer"]["documents"] == [doc["id"], csvrec["id"]]
    fr = next(e for e in inc["evidence"] if e["tool"] == "field_report")
    assert len(fr["result"]["document_findings"]) == 2


class DocModel:
    offline = False
    label = "test double"

    def __init__(self):
        self.seen = []

    def chat(self, messages, tools=None, agent="", models=None):
        self.seen.append((agent, messages[-1]["content"]))
        return {"content": json.dumps({"key_findings": ["emitter at 1712 MHz"], "values": [{"name": "UL RSSI", "value": "-92 dBm"}],
                                       "supports": ["external_interference"], "against": ["hardware_fault"],
                                       "consistent_with_diagnosis": "yes", "summary": "Sweep shows an external emitter.",
                                       "next_step": "locate it"}), "tool_calls": []}, {"model": "muse-spark-1.3"}


def test_model_reads_the_extracted_text(sentinel):
    inc = _paused(sentinel)
    sentinel.provider = DocModel()
    rec = sentinel.add_attachment(inc["id"], make_pdf(["Narrowband emitter at 1712 MHz"]), "application/pdf", "sweep.pdf", "Sarah Chen")
    agent, content = sentinel.provider.seen[-1]
    assert agent == "field_document" and "1712 MHz" in content and "FILE CONTENT" in content
    assert rec["findings"]["by"] == "muse-spark-1.3" and rec["findings"]["supports"] == ["external_interference"]
