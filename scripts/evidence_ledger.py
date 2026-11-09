# -*- coding: utf-8 -*-
"""evidence_ledger.py — 数值/效果证据台账（本地记录 + 「核心参数回填与特殊效果」草表生成器）。

目的是保证专利**完整**、数值有真实来源，而不是科研级的证据审查：
  - 台账缺行、来源偏弱（待回填 / 待实测 / 不支持）只给 **WARN** 并列出数字，**从不 FAIL、不阻断 build**；
  - 占位（如「【待用户本地回填：……】」）允许存在，只统计数量；
  - 草表只写到 reports/，特殊效果加粗；**绝不写入申请文件 docx**。
全部本地运行，仅标准库，不联网。

台账：UTF-8 TSV（首行表头，英文或中文列名均可）或 JSON 数组。列：
    id 编号 | name 参数或效果名 | location 位置 | value 数值或效果 | unit 单位 |
    source 来源类型（真实参数/计算/仿真/脱敏示例/用户提供/公知/待回填） | script 脚本或依据 |
    result_file 结果文件 | sha256 | grade 证据等级（支持/部分支持/不支持/待实测，可空） |
    special_effect 特殊效果（是/否） | core_param 核心参数（是/否） | note 备注

用法：
    python evidence_ledger.py template evidence/ledger.tsv           # 生成空台账（不覆盖已有文件）
    python evidence_ledger.py check --ledger evidence/ledger.tsv --docx 成稿.docx   # 只读 docx，WARN 列出未入账数字
    python evidence_ledger.py check --ledger L --text 有益效果=effects.txt --text 实施例=emb.txt
    python evidence_ledger.py export --ledger L --reports reports   # → reports/核心参数回填与特殊效果-YYYYMMDD.md
    python evidence_ledger.py hash 结果文件...                       # 打印 sha256，填进台账
    python evidence_ledger.py --selftest
项目 audit 也可 import：ledger_numbers / placeholder_counts / placeholder_report / verify_hashes / export_backfill。
"""
import csv
import datetime
import hashlib
import io
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

COLUMNS = ("id", "name", "location", "value", "unit", "source", "script", "result_file",
           "sha256", "grade", "special_effect", "core_param", "note")
ALIASES = {"编号": "id", "参数或效果名": "name", "名称": "name", "位置": "location", "数值或效果": "value",
           "数值": "value", "单位": "unit", "来源类型": "source", "来源": "source", "脚本或依据": "script",
           "依据": "script", "结果文件": "result_file", "证据等级": "grade", "特殊效果": "special_effect",
           "核心参数": "core_param", "备注": "note"}
SOURCES = ("真实参数", "计算", "仿真", "脱敏示例", "用户提供", "公知", "待回填")
WEAK_SOURCES = ("", "待回填")
WEAK_GRADES = ("不支持", "待实测")
YES = ("是", "yes", "y", "true", "1", "√")
NUM_PATTERN = r"[−-]?\d+\.\d+|\d+(?:\.\d+)?\s*[%％]"
PLACEHOLDER_PATTERN = r"【待[^】]{0,120}】"
BACKFILL_TITLE = "核心参数回填与特殊效果"


def _norm_num(s):
    return re.sub(r"\s+", "", (s or "").replace("％", "%").replace("−", "-"))


def _yes(v):
    return (v or "").strip().lower() in YES


def load_ledger(path):
    """读取 TSV/JSON 台账，列名统一成英文键。"""
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
            d[key] = "" if v is None else str(v).strip()
        if any(d.values()):
            out.append(d)
    return out


def ledger_numbers(texts, ledger, pattern=NUM_PATTERN):
    """texts: {节名: 文本}。返回 WARN 字符串列表（空 = 每个数字都有台账行）。

    只提示、不阻断：未入账数字、仅由弱来源（待回填/待实测/不支持/来源空）支撑的数字。
    """
    vals = [(_norm_num(r.get("value")), r) for r in ledger]
    warns = []
    for name, txt in texts.items():
        missing, weak = [], []
        for n in dict.fromkeys(_norm_num(x) for x in re.findall(pattern, txt or "")):
            rx = re.compile(r"(?<![\d.])" + re.escape(n) + r"(?!\d)")
            rows = [r for v, r in vals if n and rx.search(v)]
            if not rows:
                missing.append(n)
            elif all(r.get("source", "") in WEAK_SOURCES or r.get("grade", "") in WEAK_GRADES for r in rows):
                weak.append(f"{n}(#{rows[0].get('id') or '?'} {rows[0].get('source') or '来源空'}"
                            f"{'/' + rows[0]['grade'] if rows[0].get('grade') else ''})")
        if missing:
            warns.append(f"WARN evidence: {name} has {len(missing)} number(s) without ledger row: {', '.join(missing)}")
        if weak:
            warns.append(f"WARN evidence: {name} has {len(weak)} number(s) with weak source: {', '.join(weak)}")
    return warns


def placeholder_counts(texts, pattern=PLACEHOLDER_PATTERN):
    return {name: len(re.findall(pattern, txt or "")) for name, txt in texts.items()}


def placeholder_report(texts, pattern=PLACEHOLDER_PATTERN):
    """占位允许存在，只报告数量（INFO）。"""
    c = placeholder_counts(texts, pattern)
    total = sum(c.values())
    detail = ", ".join(f"{k} {v}" for k, v in c.items() if v)
    return [f"INFO placeholders: {total} total" + (f" ({detail})" if detail else "") + " — 待本地回填，不阻断"]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_hashes(ledger, base_dir="."):
    """台账里填了 sha256 的结果文件：缺失或哈希变化给 WARN。"""
    warns = []
    for r in ledger:
        rf, want = r.get("result_file", ""), r.get("sha256", "").lower()
        if not rf or not want:
            continue
        p = rf if os.path.isabs(rf) else os.path.join(base_dir, rf)
        if not os.path.isfile(p):
            warns.append(f"WARN evidence: #{r.get('id')} result file missing: {rf}")
        elif sha256_file(p) != want:
            warns.append(f"WARN evidence: #{r.get('id')} result file changed since recorded: {rf}")
    return warns


def _cell(s):
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def _check_reports_path(out_path):
    ap = os.path.abspath(out_path)
    if os.path.basename(os.path.dirname(ap)).lower() != "reports" or not ap.lower().endswith(".md"):
        raise ValueError("草表只能写成 reports/ 目录下的 .md（不进正式稿、不写 docx）: " + out_path)
    return ap


def default_backfill_path(reports_dir):
    day = datetime.date.today().strftime("%Y%m%d")
    base = os.path.join(reports_dir, f"{BACKFILL_TITLE}-{day}.md")
    p, i = base, 2
    while os.path.exists(p):
        p = base[:-3] + f"-{i}.md"
        i += 1
    return p


def export_backfill(ledger, out_path, ledger_name=""):
    """生成「核心参数回填与特殊效果」内部草表（Markdown，特殊效果加粗）。只允许写入 reports/*.md。"""
    ap = _check_reports_path(out_path)
    core = [r for r in ledger if _yes(r.get("core_param"))]
    special = [r for r in ledger if _yes(r.get("special_effect"))]
    pending = [r for r in ledger if r.get("source") == "待回填"]
    rest = [r for r in ledger if r not in core and r not in special and r not in pending]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [f"# {BACKFILL_TITLE}（内部文档，不进正式稿）", "",
         f"> 生成：{now}；来源台账：{ledger_name or '(未注明)'}。本文件只放 reports/，**不得插入申请文件 docx**。",
         "> 数值须来自真实参数、计算或仿真，不得凭空编造；可从真实结果中选取有代表性、效果好的一组用于实施例。", "",
         "## 一、核心参数回填", "",
         "| 编号 | 参数 | 取值 | 单位 | 来源类型 | 依据/脚本 | 位置 | 证据等级 | 备注 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in core:
        L.append(f"| {_cell(r['id'])} | **{_cell(r['name'])}** | **{_cell(r['value'])}** | {_cell(r['unit'])} | "
                 f"{_cell(r['source'])} | {_cell(r['script'])} | {_cell(r['location'])} | {_cell(r['grade'])} | {_cell(r['note'])} |")
    if not core:
        L.append("| — | （台账中无 core_param=是 的行） | | | | | | | |")
    L += ["", "## 二、特殊效果（重点标注，供新颖性/创造性论证）", "",
          "| 编号 | 效果 | 数值 | 单位 | 来源类型 | 依据/脚本 | 证据等级 | 对新颖性/创造性的作用（人工填写） |",
          "|---|---|---|---|---|---|---|---|"]
    for r in special:
        L.append(f"| {_cell(r['id'])} | **{_cell(r['name'])}** | **{_cell(r['value'])}** | {_cell(r['unit'])} | "
                 f"{_cell(r['source'])} | {_cell(r['script'])} | {_cell(r['grade'])} | {_cell(r['note'])} |")
    if not special:
        L.append("| — | （台账中无 special_effect=是 的行） | | | | | | |")
    L += ["", "## 三、待用户本地回填（占位，不代填、不猜测）", ""]
    L += [f"- **{_cell(r['name']) or _cell(r['id'])}**：{_cell(r['note']) or '取值与依据待用户本地填写'}（位置：{_cell(r['location'])}）"
          for r in pending] or ["- （无）"]
    L += ["", "## 四、其余数值溯源", "", "| 编号 | 名称 | 数值 | 来源类型 | 依据/脚本 | 位置 |", "|---|---|---|---|---|---|"]
    L += [f"| {_cell(r['id'])} | {_cell(r['name'])} | {_cell(r['value'])} | {_cell(r['source'])} | {_cell(r['script'])} | {_cell(r['location'])} |"
          for r in rest] or ["| — | | | | | |"]
    os.makedirs(os.path.dirname(ap), exist_ok=True)
    with open(ap, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    return ap


def write_template(path):
    if os.path.exists(path):
        raise FileExistsError("已存在，不覆盖: " + path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(COLUMNS) + "\n")


def _docx_texts(path):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from docx_text import read_sections, split_spec
    parts = split_spec(read_sections(path))
    return parts, {"有益效果": parts["effects"], "具体实施方式": parts["embodiments"]}


def _selftest():
    import tempfile
    ok = []
    with tempfile.TemporaryDirectory() as d:
        lp = os.path.join(d, "ledger.tsv")
        rf = os.path.join(d, "res.csv")
        with open(rf, "w", encoding="utf-8") as f:
            f.write("m,0.42\n")
        h = sha256_file(rf)
        rows = [["编号", "参数或效果名", "位置", "数值或效果", "单位", "来源类型", "脚本或依据", "结果文件", "sha256", "证据等级", "特殊效果", "核心参数", "备注"],
                ["E1", "平均偏差", "实施例1", "0.42", "", "仿真", "sim/run.py", "res.csv", h, "支持", "是", "否", "选定运行 r002"],
                ["E2", "对照偏差", "实施例1", "0.65", "", "计算", "sim/run.py", "", "", "支持", "否", "否", ""],
                ["P1", "偏差门限", "实施例1", "【待回填】", "", "待回填", "", "", "", "", "否", "是", "门限及取值依据"],
                ["E3", "响应提升", "实施例2", "12%", "", "计算", "calc.py", "", "", "待实测", "是", "否", ""]]
        with open(lp, "w", encoding="utf-8") as f:
            f.write("\n".join("\t".join(r) for r in rows) + "\n")
        L = load_ledger(lp)
        ok.append(("load chinese header", len(L) == 4 and L[0]["value"] == "0.42" and L[2]["core_param"] == "是"))
        ok.append(("covered -> no warn", ledger_numbers({"有益效果": "偏差为0.42，对照0.65。"}, L) == []))
        w = ledger_numbers({"有益效果": "偏差为0.42，降低为0.31，提升12％。"}, L)
        ok.append(("missing -> WARN lists number", any("without ledger row" in x and "0.31" in x for x in w)))
        ok.append(("weak -> WARN", any("weak source" in x and "12%" in x for x in w)))
        ok.append(("never FAIL", all(x.startswith("WARN") for x in w)))
        ok.append(("no prefix match", any("0.4" in x for x in ledger_numbers({"实施例": "取0.4。"}, L))))
        c = placeholder_counts({"实施例": "门限取【待用户本地回填：门限】，窗口【待用户本地回填：窗口】。", "权利要求": "无"})
        ok.append(("placeholder count", c == {"实施例": 2, "权利要求": 0}))
        ok.append(("placeholder INFO", placeholder_report({"a": "【待x】"})[0].startswith("INFO placeholders: 1")))
        ok.append(("hash ok", verify_hashes(L, d) == []))
        with open(rf, "a", encoding="utf-8") as f:
            f.write("tamper\n")
        ok.append(("hash changed -> WARN", any("changed" in x for x in verify_hashes(L, d))))
        out = export_backfill(L, os.path.join(d, "reports", "draft.md"), "ledger.tsv")
        md = open(out, encoding="utf-8").read()
        ok.append(("export bold special", "| **平均偏差** | **0.42** |" in md and "**偏差门限**" in md))
        ok.append(("export sections", BACKFILL_TITLE in md and "不得插入申请文件 docx" in md))
        for bad in (os.path.join(d, "draft.md"), os.path.join(d, "reports", "x.docx")):
            try:
                export_backfill(L, bad)
                ok.append(("refuse " + os.path.basename(bad), False))
            except ValueError:
                ok.append(("refuse " + os.path.basename(bad), True))
        tp = os.path.join(d, "t", "ledger.tsv")
        write_template(tp)
        try:
            write_template(tp)
            ok.append(("template no overwrite", False))
        except FileExistsError:
            ok.append(("template no overwrite", True))
    for name, r in ok:
        print(("PASS " if r else "FAIL ") + name)
    return all(r for _, r in ok)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="证据台账（本地；WARN 不阻断）")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    t = sub.add_parser("template"); t.add_argument("path")
    c = sub.add_parser("check")
    c.add_argument("--ledger", required=True)
    c.add_argument("--docx")
    c.add_argument("--text", action="append", default=[], help="节名=文本文件")
    e = sub.add_parser("export")
    e.add_argument("--ledger", required=True)
    e.add_argument("--out")
    e.add_argument("--reports", default="reports")
    hh = sub.add_parser("hash"); hh.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    if a.selftest:
        return 0 if _selftest() else 1
    if a.cmd == "template":
        write_template(a.path); print("已生成空台账:", a.path); return 0
    if a.cmd == "hash":
        for f in a.files:
            print(sha256_file(f), f)
        return 0
    if a.cmd == "check":
        L = load_ledger(a.ledger)
        texts, all_texts = {}, {}
        if a.docx:
            parts, texts = _docx_texts(a.docx)
            all_texts = {"摘要": parts["abstract"], "权利要求书": "\n".join(parts["claims"]), "说明书": parts["spec"]}
        for kv in a.text:
            k, _, p = kv.partition("=")
            texts[k] = all_texts[k] = open(p, encoding="utf-8-sig").read()
        lines = ledger_numbers(texts, L) + verify_hashes(L, os.path.dirname(os.path.abspath(a.ledger)))
        lines += placeholder_report(all_texts or texts)
        for x in lines:
            print(x)
        if not any(x.startswith("WARN") for x in lines):
            print("PASS evidence: all numbers have ledger rows")
        return 0
    if a.cmd == "export":
        L = load_ledger(a.ledger)
        out = a.out or default_backfill_path(a.reports)
        print("已写草表（仅 reports/，不进正式稿）:", export_backfill(L, out, os.path.basename(a.ledger)))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
