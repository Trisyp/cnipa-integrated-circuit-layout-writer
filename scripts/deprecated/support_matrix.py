# -*- coding: utf-8 -*-
"""support_matrix.py — 权要要素 ↔ 发明内容/实施例支撑矩阵（本地；缺支撑只 WARN）。

灵感来自 K-Dense-AI/scientific-agent-skills 的 claim–evidence 矩阵思路，适配 CNIPA：
stdout / 报告只含 feature_id、位置码、support 枚举与计数，**不回显权要/摘要正文**。
输出草表只写 reports/；从不写入申请 docx。仅标准库，不联网。

台账：UTF-8 TSV（或 JSON 数组）。列：
    feature_id | claim_loc | summary_loc | embodiment_loc | support | note
support ∈ full | partial | missing | not_assessed
缺支撑（missing / 空 / not_assessed）→ WARN，从不 FAIL（完整优先）。

用法：
    python support_matrix.py template evidence/support_matrix.tsv
    python support_matrix.py check --matrix evidence/support_matrix.tsv
    python support_matrix.py check --matrix M --docx 成稿.docx   # 可选：核对位置码是否落在已解析节（不回显正文）
    python support_matrix.py report --matrix M --reports reports
    python support_matrix.py --selftest
"""
import csv
import datetime
import io
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

COLUMNS = ("feature_id", "claim_loc", "summary_loc", "embodiment_loc", "support", "note")
ALIASES = {
    "编号": "feature_id", "要素编号": "feature_id", "id": "feature_id",
    "权要位置": "claim_loc", "权利要求位置": "claim_loc",
    "发明内容位置": "summary_loc", "实施例位置": "embodiment_loc",
    "支撑": "support", "备注": "note",
}
SUPPORTS = ("full", "partial", "missing", "not_assessed")
WEAK = ("", "missing", "not_assessed")
# 位置码：claim:1 / summary / embodiment:2 / effects 等简码，禁止塞长句
_LOC_OK = re.compile(r"^(?:claim|summary|embodiment|effects|abstract|background|fig)(?::[\w.-]{1,32})?$", re.I)


def load_matrix(path):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        rows = json.loads(text)
    else:
        rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
    out = []
    for r in rows:
        d = {k: "" for k in COLUMNS}
        for k, v in r.items():
            if k is None:
                continue
            key = ALIASES.get(k.strip(), k.strip())
            if key in d:
                d[key] = "" if v is None else str(v).strip()
        if any(d.values()):
            out.append(d)
    return out


def check_rows(rows):
    """返回 WARN 字符串列表（从不 FAIL）。消息只含 ID / 枚举 / 计数。"""
    warns, seen = [], set()
    for i, r in enumerate(rows, start=1):
        fid = r.get("feature_id") or f"ROW{i}"
        if fid in seen:
            warns.append(f"WARN support: duplicate feature_id={fid}")
        seen.add(fid)
        sup = (r.get("support") or "").strip().lower()
        if sup and sup not in SUPPORTS:
            warns.append(f"WARN support: feature_id={fid} unknown support={sup!r}")
        for col in ("claim_loc", "summary_loc", "embodiment_loc"):
            loc = (r.get(col) or "").strip()
            if loc and not _LOC_OK.match(loc):
                warns.append(f"WARN support: feature_id={fid} {col} not a location code (use claim:N / summary / embodiment:N)")
        if sup in WEAK or not sup:
            warns.append(f"WARN support: feature_id={fid} support={sup or 'empty'} (missing/not_assessed; human review)")
        elif sup == "partial" and not (r.get("embodiment_loc") or "").strip():
            warns.append(f"WARN support: feature_id={fid} partial without embodiment_loc")
        elif sup == "full" and not (r.get("claim_loc") or "").strip():
            warns.append(f"WARN support: feature_id={fid} full without claim_loc")
    if not rows:
        warns.append("WARN support: matrix empty")
    return warns


def check_against_docx(rows, docx_path):
    """可选：确认 claim:N 编号不超过解析到的权利要求数；不回显正文。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from docx_text import read_sections, split_spec
    parts = split_spec(read_sections(docx_path))
    n_claims = len(parts.get("claims") or [])
    warns = []
    for r in rows:
        fid = r.get("feature_id") or "?"
        loc = (r.get("claim_loc") or "").strip()
        m = re.match(r"(?i)^claim:(\d+)$", loc)
        if m and int(m.group(1)) > n_claims:
            warns.append(f"WARN support: feature_id={fid} claim_loc={loc} > parsed claim count {n_claims}")
    return warns


def write_template(path):
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(COLUMNS) + "\n")
        f.write("F1\tclaim:1\tsummary\tembodiment:1\tfull\t\n")
        f.write("F2\tclaim:2\tsummary\t\tmissing\t\n")
    return True


def export_report(rows, out_path, matrix_name=""):
    ap = os.path.abspath(out_path)
    if os.path.basename(os.path.dirname(ap)).lower() != "reports" or not ap.lower().endswith(".md"):
        raise ValueError("报告只写 reports/*.md: " + out_path)
    warns = check_rows(rows)
    weak = sum(1 for r in rows if (r.get("support") or "").strip().lower() in WEAK or not (r.get("support") or "").strip())
    lines = [
        "# 权要要素支撑矩阵（内部文档，不进正式稿）",
        "",
        f"> 生成：{datetime.datetime.now():%Y-%m-%d %H:%M}；矩阵：{matrix_name or '(unnamed)'}；"
        f"缺支撑只 WARN，不阻断。",
        "",
        f"- 要素行数：{len(rows)}",
        f"- 弱/缺支撑行数：{weak}",
        f"- check WARN 条数：{len(warns)}",
        "",
        "| feature_id | claim_loc | summary_loc | embodiment_loc | support |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append("| " + " | ".join(
            (r.get(k) or "").replace("|", "\\|") for k in
            ("feature_id", "claim_loc", "summary_loc", "embodiment_loc", "support")) + " |")
    lines += ["", "## WARN 码（无正文）", ""]
    if warns:
        lines += [f"- {w}" for w in warns]
    else:
        lines.append("- （无）")
    os.makedirs(os.path.dirname(ap), exist_ok=True)
    with open(ap, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return ap


def _selftest():
    import tempfile
    ok = []
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "m.tsv")
        ok.append(("template", write_template(p) and not write_template(p)))
        rows = load_matrix(p)
        ok.append(("load 2 rows", len(rows) == 2))
        w = check_rows(rows)
        ok.append(("missing -> WARN with feature_id", any("feature_id=F2" in x and "missing" in x for x in w)))
        ok.append(("full row silent on weak", not any("feature_id=F1" in x and "missing" in x for x in w)))
        # bad location code (long text) -> WARN code only, no claim prose leak of that long text in "location code" message type
        bad = [{"feature_id": "F3", "claim_loc": "一种方法其特征在于包括很长的权利要求原文不应出现",
                "summary_loc": "", "embodiment_loc": "", "support": "full", "note": ""}]
        wb = check_rows(bad)
        ok.append(("long claim_loc -> location code WARN", any("not a location code" in x for x in wb)))
        ok.append(("stdout-safe: no long loc echoed", all("一种方法" not in x for x in wb)))
        ok.append(("unknown support", any("unknown support" in x for x in check_rows(
            [{"feature_id": "F9", "claim_loc": "claim:1", "summary_loc": "", "embodiment_loc": "",
              "support": "maybe", "note": ""}]))))
        ok.append(("empty matrix WARN", any("empty" in x for x in check_rows([]))))
        ok.append(("duplicate id", any("duplicate" in x for x in check_rows(rows + rows[:1]))))
        rep = os.path.join(d, "reports", "support.md")
        export_report(rows, rep, "m.tsv")
        md = open(rep, encoding="utf-8").read()
        ok.append(("report ids only", "F1" in md and "F2" in md and "一种方法" not in md))
        try:
            export_report(rows, os.path.join(d, "x.md"))
            ok.append(("refuse non-reports", False))
        except ValueError:
            ok.append(("refuse non-reports", True))
        # never FAIL API: check_rows always list of WARN strings
        ok.append(("never FAIL prefix", all(x.startswith("WARN") for x in w + wb)))
    for name, r in ok:
        print(("PASS " if r else "FAIL ") + name)
    return all(r for _, r in ok)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="权要要素支撑矩阵（WARN 不阻断；不回显正文）")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("template"); s.add_argument("path")
    s = sub.add_parser("check"); s.add_argument("--matrix", required=True); s.add_argument("--docx")
    s = sub.add_parser("report"); s.add_argument("--matrix", required=True)
    s.add_argument("--reports", default="reports"); s.add_argument("--out")
    a = ap.parse_args(argv)
    if a.selftest:
        return 0 if _selftest() else 1
    if a.cmd == "template":
        print("已生成" if write_template(a.path) else "已存在，未覆盖")
        return 0
    if a.cmd == "check":
        rows = load_matrix(a.matrix)
        warns = check_rows(rows)
        if a.docx:
            warns += check_against_docx(rows, a.docx)
        for w in warns:
            print(w)
        if not warns:
            print(f"PASS support: {len(rows)} feature(s), no weak/missing")
        # WARN 不阻断
        return 0
    if a.cmd == "report":
        rows = load_matrix(a.matrix)
        out = a.out or os.path.join(a.reports, f"支撑矩阵-{datetime.date.today():%Y%m%d}.md")
        print("已写:", export_report(rows, out, os.path.basename(a.matrix)))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
