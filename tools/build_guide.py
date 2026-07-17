"""Build USER_GUIDE.docx (python-docx, images embedded) + USER_GUIDE.html
(self-contained base64) from USER_GUIDE.md, then sync md/docx/html + images/ to dist/.

    python tools/build_guide.py            (run from the repo root)

Needs: pip install python-docx Pillow
"""
import base64, html, os, re, mimetypes, shutil
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from PIL import Image  # noqa: F401 (ensures Pillow present for docx image sizing)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(ROOT, "USER_GUIDE.md")
DOCX = os.path.join(ROOT, "USER_GUIDE.docx")
HTM = os.path.join(ROOT, "USER_GUIDE.html")
DIST = os.path.join(ROOT, "dist")
lines = open(MD, encoding="utf-8").read().splitlines()

IMG_RE = re.compile(r'^!\[(?P<alt>.*?)\]\((?P<src>.*?)\)\s*$')
INLINE_RE = re.compile(r'(\*\*.+?\*\*|`.+?`|\*.+?\*)')


def blocks(lines):
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]; s = ln.strip()
        if not s:
            i += 1; continue
        if s == "---":
            yield ("hr", None); i += 1; continue
        m = IMG_RE.match(ln)
        if m:
            yield ("img", (m.group("alt"), m.group("src"))); i += 1; continue
        if s.startswith("#"):
            h = len(s) - len(s.lstrip("#"))
            yield ("h%d" % min(h, 3), s[h:].strip()); i += 1; continue
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip()); i += 1
            yield ("quote", " ".join(x for x in buf if x)); continue
        if s.startswith("|"):
            buf = []
            while i < n and lines[i].strip().startswith("|"):
                buf.append(lines[i].strip()); i += 1
            yield ("table", buf); continue
        if re.match(r'^([-*]|\d+\.)\s+', s):
            buf = []
            while i < n and re.match(r'^([-*]|\d+\.)\s+', lines[i].strip()):
                ordered = bool(re.match(r'^\d+\.', lines[i].strip()))
                txt = re.sub(r'^([-*]|\d+\.)\s+', '', lines[i].strip()); i += 1
                while (i < n and lines[i].strip() and lines[i].startswith(" ")
                       and not re.match(r'^([-*]|\d+\.)\s+', lines[i].strip())
                       and not lines[i].strip().startswith(("#", ">", "|"))
                       and not IMG_RE.match(lines[i]) and lines[i].strip() != "---"):
                    txt += " " + lines[i].strip(); i += 1
                buf.append((ordered, txt))
            yield ("list", buf); continue
        buf = []
        while (i < n and lines[i].strip()
               and not lines[i].strip().startswith(("#", ">", "|"))
               and not IMG_RE.match(lines[i]) and lines[i].strip() != "---"
               and not re.match(r'^([-*]|\d+\.)\s+', lines[i].strip())):
            buf.append(lines[i].strip()); i += 1
        yield ("p", " ".join(buf))


def split_cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def inline_runs(text):
    out = []
    for part in INLINE_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            out.append((part[2:-2], True, False, False))
        elif part.startswith("`") and part.endswith("`"):
            out.append((part[1:-1], False, False, True))
        elif part.startswith("*") and part.endswith("*"):
            out.append((part[1:-1], False, True, False))
        else:
            out.append((part, False, False, False))
    return out


# ------- DOCX -------
doc = Document()
doc.styles["Normal"].font.name = "Calibri"
doc.styles["Normal"].font.size = Pt(10.5)


def add_runs(p, text):
    for t, b, it, code in inline_runs(text):
        r = p.add_run(t)
        r.bold = b or None; r.italic = it or None
        if code:
            r.font.name = "Consolas"; r.font.color.rgb = RGBColor(0x33, 0x33, 0x33)


for kind, payload in blocks(lines):
    if kind == "h1":
        doc.add_heading(payload, 0)
    elif kind == "h2":
        doc.add_heading(payload, 1)
    elif kind == "h3":
        doc.add_heading(payload, 2)
    elif kind == "p":
        add_runs(doc.add_paragraph(), payload)
    elif kind == "quote":
        add_runs(doc.add_paragraph(style="Intense Quote"), payload)
    elif kind == "hr":
        doc.add_paragraph()
    elif kind == "list":
        for ordered, txt in payload:
            add_runs(doc.add_paragraph(style="List Number" if ordered else "List Bullet"), txt)
    elif kind == "img":
        alt, src = payload
        path = os.path.join(ROOT, src.replace("/", os.sep))
        if os.path.exists(path):
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(path, width=Inches(6.3))
            cap = doc.add_paragraph(); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cr = cap.add_run(alt); cr.italic = True; cr.font.size = Pt(8.5)
            cr.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        else:
            print("  !! missing image:", path)
    elif kind == "table":
        rows = [split_cells(r) for r in payload]
        header, body = rows[0], rows[2:]
        t = doc.add_table(rows=1, cols=len(header)); t.style = "Light Grid Accent 1"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, cell in enumerate(header):
            c = t.rows[0].cells[j].paragraphs[0]; add_runs(c, cell)
            for run in c.runs:
                run.bold = True
        for row in body:
            cells = t.add_row().cells
            for j, cell in enumerate(row[:len(header)]):
                add_runs(cells[j].paragraphs[0], cell)
doc.save(DOCX)
print("wrote", os.path.basename(DOCX), os.path.getsize(DOCX), "bytes")

# ------- HTML -------
def h_inline(text):
    out = []
    for t, b, it, code in inline_runs(text):
        e = html.escape(t)
        if b: e = "<strong>%s</strong>" % e
        if it: e = "<em>%s</em>" % e
        if code: e = "<code>%s</code>" % e
        out.append(e)
    return "".join(out)


def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    return "data:%s;base64,%s" % (mime, base64.b64encode(open(path, "rb").read()).decode())


parts = ["""<!doctype html><html><head><meta charset="utf-8">
<title>BYTEPLUS for Maya - User Guide</title><style>
body{font-family:Segoe UI,Helvetica,Arial,sans-serif;max-width:860px;margin:0 auto;padding:32px;color:#1d1d1d;line-height:1.55;}
h1{font-size:30px;border-bottom:3px solid #2E8BE6;padding-bottom:8px;}
h2{font-size:22px;margin-top:34px;border-bottom:1px solid #ddd;padding-bottom:4px;}
h3{font-size:17px;margin-top:24px;}
img{max-width:100%;border:1px solid #ddd;border-radius:6px;display:block;margin:12px auto;}
figcaption{text-align:center;color:#888;font-size:12px;font-style:italic;margin-bottom:16px;}
blockquote{border-left:4px solid #2E8BE6;background:#f2f8fe;margin:14px 0;padding:10px 16px;color:#333;}
code{background:#eef1f4;padding:1px 5px;border-radius:4px;font-family:Consolas,monospace;font-size:90%;}
table{border-collapse:collapse;width:100%;margin:16px 0;}
th,td{border:1px solid #ccc;padding:7px 10px;text-align:left;font-size:14px;}
th{background:#2E8BE6;color:#fff;} tr:nth-child(even){background:#f6f8fa;}
hr{border:none;border-top:1px solid #ddd;margin:28px 0;}
</style></head><body>"""]
for kind, payload in blocks(lines):
    if kind in ("h1", "h2", "h3"):
        parts.append("<%s>%s</%s>" % (kind, h_inline(payload), kind))
    elif kind == "p":
        parts.append("<p>%s</p>" % h_inline(payload))
    elif kind == "quote":
        parts.append("<blockquote>%s</blockquote>" % h_inline(payload))
    elif kind == "hr":
        parts.append("<hr>")
    elif kind == "list":
        tag = "ol" if payload and payload[0][0] else "ul"
        parts.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % h_inline(t) for _, t in payload), tag))
    elif kind == "img":
        alt, src = payload
        path = os.path.join(ROOT, src.replace("/", os.sep))
        if os.path.exists(path):
            parts.append('<figure><img alt="%s" src="%s"><figcaption>%s</figcaption></figure>'
                         % (html.escape(alt), data_uri(path), html.escape(alt)))
    elif kind == "table":
        rows = [split_cells(r) for r in payload]
        thead = "".join("<th>%s</th>" % h_inline(c) for c in rows[0])
        tbody = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % h_inline(c) for c in r) for r in rows[2:])
        parts.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (thead, tbody))
parts.append("</body></html>")
open(HTM, "w", encoding="utf-8").write("\n".join(parts))
print("wrote", os.path.basename(HTM), os.path.getsize(HTM), "bytes")

# ------- sync dist -------
for f in ("USER_GUIDE.md", "USER_GUIDE.docx", "USER_GUIDE.html"):
    shutil.copyfile(os.path.join(ROOT, f), os.path.join(DIST, f))
dst = os.path.join(DIST, "images")
if os.path.isdir(dst):
    shutil.rmtree(dst)
shutil.copytree(os.path.join(ROOT, "images"), dst)
nimg = sum(1 for k, _ in blocks(lines) if k == "img")
print("synced -> dist/  (%d img refs, %d files in dist/images)"
      % (nimg, len([x for x in os.listdir(dst) if not x.startswith(".")])))
