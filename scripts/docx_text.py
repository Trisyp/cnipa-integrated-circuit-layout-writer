# -*- coding: utf-8 -*-
"""docx_text.py — 只读解析专利 docx 的文本与分节结构（仅标准库，不改写 docx）。

供 final_check.py / evidence_ledger.py / query_guard.py 复用：
    from docx_text import read_sections, split_spec, docx_structure, all_text
    secs = read_sections("成稿.docx")        # [[段落文本...], ...] 按 sectPr 分节
    parts = split_spec(secs)                 # {"abstract","claims","spec","background","summary","effects","embodiments",...}
    st = docx_structure("成稿.docx")         # 每节页眉文字 / 页脚是否有 PAGE 域 / 页码起始值

只以 zipfile 读取，不写回、不加元数据。自检：python docx_text.py --selftest
"""
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

EXPECTED_HEADERS = ("说明书摘要", "权利要求书", "说明书", "说明书附图")
SPEC_HEADINGS = ("技术领域", "背景技术", "发明内容", "附图说明", "具体实施方式")
_WS = re.compile(r"\s+")
_CLAIM_START = re.compile(r"^\s*\d+\s*[.．、]")


def _norm(s):
    return _WS.sub("", s or "").rstrip("：:")


def _para_text(p):
    out = []
    for el in p.iter():
        if el.tag in (W + "t", M + "t"):
            out.append(el.text or "")
        elif el.tag == W + "tab":
            out.append("\t")
    return "".join(out)


def _body(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    return root.find(W + "body")


def read_sections(path):
    """按 sectPr 把正文段落分节，返回 [[段落文本, ...], ...]。表格单元格文本按行并入。"""
    secs = [[]]
    for el in _body(path):
        if el.tag == W + "p":
            secs[-1].append(_para_text(el))
            ppr = el.find(W + "pPr")
            if ppr is not None and ppr.find(W + "sectPr") is not None:
                secs.append([])
        elif el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                secs[-1].append("\t".join(_para_text(tc) for tc in tr.iter(W + "tc")))
    if len(secs) > 1 and not any(t.strip() for t in secs[-1]):
        # 末节 sectPr 在 body 末尾；若最后一个 pPr/sectPr 之后再无段落，丢弃空尾
        secs.pop()
    return secs


def split_claims(paras):
    """把权利要求书段落合并成逐条权利要求（以「N.」开头为新一条）。"""
    claims = []
    for t in paras:
        if not t.strip():
            continue
        if _CLAIM_START.match(t) or not claims:
            claims.append(t.strip())
        else:
            claims[-1] += t.strip()
    return claims


def split_spec(secs):
    """4 节时按 摘要/权利要求书/说明书/附图 取文本，并把说明书按标准标题切块。"""
    out = {"abstract": "", "claims": [], "spec": "", "drawings": "",
           "background": "", "field": "", "summary": "", "effects": "",
           "figdesc": "", "embodiments": ""}
    if len(secs) < 3:
        out["spec"] = "\n".join("\n".join(s) for s in secs)
        return out
    out["abstract"] = "\n".join(t for t in secs[0] if t.strip())
    out["claims"] = split_claims(secs[1])
    spec = secs[2]
    out["spec"] = "\n".join(t for t in spec if t.strip())
    if len(secs) > 3:
        out["drawings"] = "\n".join(t for t in secs[3] if t.strip())
    key = {"技术领域": "field", "背景技术": "background", "发明内容": "summary",
           "附图说明": "figdesc", "具体实施方式": "embodiments"}
    cur = None
    in_effects = False
    buf = {k: [] for k in key.values()}
    eff = []
    for t in spec:
        n = _norm(t)
        if n in key:
            cur = key[n]
            in_effects = False
            continue
        if re.fullmatch(r"有益效果", n):
            in_effects = True
            continue
        if cur is None or not t.strip():
            continue
        if in_effects:
            eff.append(t)
        else:
            buf[cur].append(t)
    for k, v in buf.items():
        out[k] = "\n".join(v)
    out["effects"] = "\n".join(eff)
    return out


def all_text(path):
    return "\n".join("\n".join(s) for s in read_sections(path))


def _rels(z, part):
    name = part.rsplit("/", 1)
    rel = name[0] + "/_rels/" + name[1] + ".rels"
    try:
        root = ET.fromstring(z.read(rel))
    except KeyError:
        return {}
    return {r.get("Id"): r.get("Target") for r in root.iter(PR + "Relationship")}


def _part_text_and_page(z, target):
    p = "word/" + target.lstrip("/").replace("word/", "", 1) if not target.startswith("word/") else target
    try:
        root = ET.fromstring(z.read(p))
    except KeyError:
        return "", False
    txt = "".join(_para_text(x) for x in root.iter(W + "p"))
    page = False
    for el in root.iter():
        if el.tag == W + "instrText" and "PAGE" in (el.text or "").upper():
            page = True
        if el.tag == W + "fldSimple" and "PAGE" in (el.get(W + "instr") or "").upper():
            page = True
    return txt, page


def docx_structure(path):
    """返回每节 {header, footer_page, pg_start, titlePg}；未显式挂页眉/页脚的节按 Word 规则继承前节。"""
    with zipfile.ZipFile(path) as z:
        body = ET.fromstring(z.read("word/document.xml")).find(W + "body")
        rels = _rels(z, "word/document.xml")
        sps = []
        for el in body:
            if el.tag == W + "p":
                ppr = el.find(W + "pPr")
                if ppr is not None and ppr.find(W + "sectPr") is not None:
                    sps.append(ppr.find(W + "sectPr"))
            elif el.tag == W + "sectPr":
                sps.append(el)
        out = []
        prev_h, prev_f = ("", False), ("", False)
        for sp in sps:
            h = prev_h
            f = prev_f
            for ref in sp.findall(W + "headerReference"):
                if ref.get(W + "type", "default") == "default":
                    h = _part_text_and_page(z, rels.get(ref.get(R + "id"), ""))
            for ref in sp.findall(W + "footerReference"):
                if ref.get(W + "type", "default") == "default":
                    f = _part_text_and_page(z, rels.get(ref.get(R + "id"), ""))
            pg = sp.find(W + "pgNumType")
            out.append({"header": _norm(h[0]), "footer_page": bool(f[1]),
                        "pg_start": pg.get(W + "start") if pg is not None else None,
                        "titlePg": sp.find(W + "titlePg") is not None})
            prev_h, prev_f = h, f
        return out


# ---------------- 自检：用标准库拼一个极简 4 节 docx ----------------
def make_fake_docx(path, abstract="摘要文本。", claims=("1.一种方法，包括步骤S1。",),
                   spec=(("技术领域", "本发明涉及示例领域。"),), n_sections=4,
                   restart=(2, 3), headers=EXPECTED_HEADERS):
    """仅供自检：生成最小可解析 docx（不是正式版式，不用于提交）。"""
    def p(t):
        t = t.replace("&", "&amp;").replace("<", "&lt;")
        return '<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % t

    def sect(i):
        h = '<w:headerReference w:type="default" r:id="rIdH%d"/>' % i
        f = '<w:footerReference w:type="default" r:id="rIdF%d"/>' % i
        pg = '<w:pgNumType w:start="1"/>' if i in restart else ""
        return "<w:sectPr>%s%s%s</w:sectPr>" % (h, f, pg)
    contents = [[abstract], list(claims), [x for pair in spec for x in pair], ["（附图）"]][:n_sections]
    body = []
    for i, paras in enumerate(contents, start=1):
        for t in paras[:-1]:
            body.append(p(t))
        last = paras[-1] if paras else ""
        if i < len(contents):
            body.append('<w:p><w:pPr>%s</w:pPr><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (sect(i), last))
        else:
            body.append(p(last))
            body.append(sect(i))
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
    doc = '<?xml version="1.0" encoding="UTF-8"?><w:document %s><w:body>%s</w:body></w:document>' % (ns, "".join(body))
    rels = ['<Relationship Id="rIdH%d" Type="h" Target="header%d.xml"/>' % (i, i) for i in range(1, n_sections + 1)]
    rels += ['<Relationship Id="rIdF%d" Type="f" Target="footer%d.xml"/>' % (i, i) for i in range(1, n_sections + 1)]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % "".join(rels))
        for i in range(1, n_sections + 1):
            ht = " ".join(headers[i - 1]) if i <= len(headers) else ""
            z.writestr("word/header%d.xml" % i, '<w:hdr %s>%s</w:hdr>' % (ns, p(ht)))
            fld = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGE </w:instrText></w:r>'
                   '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>') if i in (2, 3) else p("")
            z.writestr("word/footer%d.xml" % i, '<w:ftr %s>%s</w:ftr>' % (ns, fld))


def _selftest():
    import os
    import tempfile
    ok = []
    with tempfile.TemporaryDirectory() as d:
        fp = os.path.join(d, "t.docx")
        make_fake_docx(fp, claims=("1.一种方法，其特征在于，包括：", "S1，获取；", "2.根据权利要求1所述的方法。"),
                       spec=(("背景技术", "现有做法甲。"), ("发明内容", "本发明提出……"),
                             ("有益效果", "误差为0.42。"), ("具体实施方式", "参见图1，误差为0.42。")))
        secs = read_sections(fp)
        ok.append(("4 sections", len(secs) == 4))
        parts = split_spec(secs)
        ok.append(("claims merged", len(parts["claims"]) == 2 and "S1" in parts["claims"][0]))
        ok.append(("background", parts["background"] == "现有做法甲。"))
        ok.append(("effects", parts["effects"] == "误差为0.42。"))
        ok.append(("embodiments", "参见图1" in parts["embodiments"]))
        st = docx_structure(fp)
        ok.append(("headers", [s["header"] for s in st] == list(EXPECTED_HEADERS)))
        ok.append(("restart", [s["pg_start"] for s in st] == [None, "1", "1", None]))
        ok.append(("page field", [s["footer_page"] for s in st] == [False, True, True, False]))
        bad = os.path.join(d, "b.docx")
        make_fake_docx(bad, n_sections=3, restart=(2,))
        st2 = docx_structure(bad)
        ok.append(("3 sections detected (neg)", len(st2) == 3 and st2[2]["pg_start"] is None))
    for name, r in ok:
        print(("PASS " if r else "FAIL ") + name)
    return all(r for _, r in ok)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    if len(sys.argv) > 1:
        secs = read_sections(sys.argv[1])
        print("sections:", len(secs))
        for i, s in enumerate(docx_structure(sys.argv[1]), 1):
            print(i, s)
    else:
        print(__doc__)
