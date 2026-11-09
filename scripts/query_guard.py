# -*- coding: utf-8 -*-
"""query_guard.py — 公网检索词离线守门（原则 14：公网只用隐去核心参数的框架性描述）。

在把检索式贴进任何公网检索站/搜索引擎之前，先在本地过一遍：
  BLOCK（退出码 2）：命中保密词表；含具体数值（小数、百分数、带单位的数、数值范围）；
                    与本地内容源（权要/说明书/内容源文件）有 ≥ block-ngram 字的连续重合。
  WARN ：裸整数；步骤编排措辞（步骤S1/S2、首先…然后）；检索式过长像整句；与内容源有 ngram~block-ngram 字重合；
         未提供保密词表。
  PASS ：以上都没有。
本脚本**完全离线**：不发起任何网络请求，只读本地文件；命中内容默认打码输出（--show 才明文），
避免把保密词带进聊天或日志。它是辅助闸门，不替代人工判断。仅标准库。

保密词表 confidential_terms*.txt（放项目目录，已在 .gitignore；每行一个词，# 注释，re: 前缀写正则）。

用法：
    python query_guard.py "多源 读数 融合 异常 标记"                    # 默认读取当前目录 confidential_terms*.txt
    python query_guard.py --terms confidential_terms.txt --source content.txt --file queries.txt
    python query_guard.py "..." --log 检索日志.tsv --db "某公开专利检索系统"  # 通过后追加检索日志（被拦截的只记 [BLOCKED]）
    python query_guard.py --selftest
"""
import datetime
import glob
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

_UNITS = (r"mm|cm|nm|μm|um|km|m|ms|μs|us|ns|s|min|h|Hz|kHz|MHz|GHz|V|mV|kV|A|mA|W|kW|MW|°C|℃|°|K|Pa|kPa|MPa|"
          r"dB|dBm|ppm|mol|g|kg|mg|L|mL|bit|bps|Mbps|fps|px|"
          r"毫米|厘米|米|千米|毫秒|微秒|秒|分钟|小时|赫兹|伏|安|瓦|度|帧|像素|位|倍|次|个|层|步|组|路")
RX_DECIMAL = re.compile(r"\d+\.\d+")
RX_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*[%％‰]")
RX_UNIT = re.compile(r"\d+(?:\.\d+)?\s*(?:" + _UNITS + r")(?![A-Za-z])")
RX_RANGE = re.compile(r"\d+(?:\.\d+)?\s*(?:~|～|-|–|至|到)\s*\d+")
RX_INT = re.compile(r"(?<![\d.])\d+(?![\d.])")
RX_YEAR = re.compile(r"^(?:19|20)\d\d$")
RX_STEPS = re.compile(r"步骤\s*S?\d|(?<![A-Za-z])S\d{1,3}(?![\dA-Za-z])|首先.{0,30}然后")
_PUNCT = re.compile(r"[\s，。；：、,.;:（）()“”\"'《》【】\[\]！？!?—…\-+*/|&]+")


def mask(t, show=False):
    t = t or ""
    if show or len(t) <= 1:
        return t
    return t[0] + "*" * (len(t) - 1)


def load_terms(paths):
    terms, regexes = [], []
    for p in paths:
        with open(p, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("re:"):
                    regexes.append(re.compile(line[3:], re.I))
                else:
                    terms.append(line)
    return terms, regexes


def load_source_text(paths):
    out = []
    for p in paths:
        if p.lower().endswith(".docx"):
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from docx_text import all_text
            out.append(all_text(p))
        else:
            with open(p, encoding="utf-8-sig", errors="replace") as f:
                out.append(f.read())
    return "\n".join(out)


def check_query(q, terms=(), regexes=(), source="", allow=(), ngram=8, block_ngram=12, max_len=40,
                show=False, have_terms=True):
    """返回 (verdict, [原因...])；verdict ∈ PASS/WARN/BLOCK。"""
    block, warn = [], []
    qq = q or ""
    for a in allow:
        qq = qq.replace(a, " ")
    low = qq.lower()
    for t in terms:
        if t and t.lower() in low:
            block.append(f"confidential term: {mask(t, show)}")
    for rx in regexes:
        m = rx.search(qq)
        if m:
            block.append(f"confidential pattern: {mask(m.group(0), show)}")
    nums = set()
    for name, rx in (("decimal", RX_DECIMAL), ("percent", RX_PERCENT), ("value+unit", RX_UNIT), ("range", RX_RANGE)):
        for m in rx.finditer(qq):
            nums.add(m.group(0))
            block.append(f"specific value ({name}): {mask(m.group(0), show)}")
    for m in RX_INT.finditer(qq):
        v = m.group(0)
        if not RX_YEAR.match(v) and not any(v in n for n in nums):
            warn.append(f"bare integer (parameter?): {mask(v, show)}")
    if RX_STEPS.search(qq):
        warn.append("step-order wording (步骤S1/首先…然后) — use framework keywords instead")
    compact = _PUNCT.sub("", qq)
    if len(compact) > max_len:
        warn.append(f"query is {len(compact)} chars (> {max_len}) — looks like a sentence, not keywords")
    if source and ngram:
        src = _PUNCT.sub("", source)
        for a in allow:
            src = src.replace(_PUNCT.sub("", a), "\u0000")
        best = 0
        for i in range(len(compact)):
            lo = max(best + 1, ngram)
            while i + lo <= len(compact) and compact[i:i + lo] in src:
                best = lo
                lo += 1
        if best >= block_ngram:
            block.append(f"{best}-char verbatim overlap with local content")
        elif best >= ngram:
            warn.append(f"{best}-char overlap with local content — check it is generic wording")
    if not have_terms:
        warn.append("no confidential_terms file — only generic checks ran")
    verdict = "BLOCK" if block else ("WARN" if warn else "PASS")
    return verdict, block + warn


LOG_HEADER = ("日期", "数据源", "检索式（已过guard）", "guard结果", "命中数", "打开过的文献号", "核实状态", "备注")


def append_log(path, db, query, verdict):
    new = not os.path.isfile(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("\t".join(LOG_HEADER) + "\n")
        q = "[BLOCKED，未记录检索式]" if verdict == "BLOCK" else query.replace("\t", " ")
        f.write("\t".join([datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), db or "", q, verdict, "", "", "", ""]) + "\n")


def _selftest():
    import tempfile
    ok = []
    canary = "示例保密词甲"
    terms = [canary, "ZetaCore"]
    rx = [re.compile(r"阈值\s*[=＝]", re.I)]
    src = "步骤一：按历史稳定度确定各采集单元权重并计算加权融合值，偏差门限为示例值。"
    def v(q, **kw):
        return check_query(q, terms, rx, src, **kw)
    ok.append(("framework PASS", v("多源 读数 融合 异常 标记")[0] == "PASS"))
    ok.append(("year allowed", v("传感 融合 2020")[0] == "PASS"))
    ok.append(("canary term BLOCK", v("读数融合 示例保密词甲")[0] == "BLOCK"))
    ok.append(("case-insensitive term BLOCK", v("zetacore fusion")[0] == "BLOCK"))
    ok.append(("regex term BLOCK", v("融合 阈值=")[0] == "BLOCK"))
    ok.append(("decimal BLOCK", v("融合 权重 0.35")[0] == "BLOCK"))
    ok.append(("percent BLOCK", v("误差 降低 12%")[0] == "BLOCK"))
    ok.append(("unit BLOCK", v("窗口 10 ms 融合")[0] == "BLOCK"))
    ok.append(("range BLOCK", v("窗口 5~20 融合")[0] == "BLOCK"))
    ok.append(("verbatim overlap BLOCK", v("按历史稳定度确定各采集单元权重")[0] == "BLOCK"))
    w = v("各采集单元权重 并计算")
    ok.append(("short overlap WARN", w[0] == "WARN" and any("overlap" in x for x in w[1])))
    ok.append(("bare int WARN", v("融合 窗口 7")[0] == "WARN"))
    ok.append(("steps WARN", v("步骤S1 融合")[0] == "WARN"))
    ok.append(("long WARN", v("一种对多个来源的读数进行融合并对其中偏离较大的读数进行标记以便后续环节进一步处理与输出的方法")[0] == "WARN"))
    ok.append(("no terms WARN", check_query("多源 融合", have_terms=False)[0] == "WARN"))
    ok.append(("masked output", all(canary not in x for x in v("示例保密词甲")[1])))
    ok.append(("show reveals", any(canary in x for x in v("示例保密词甲", show=True)[1])))
    with tempfile.TemporaryDirectory() as d:
        lp = os.path.join(d, "log.tsv")
        append_log(lp, "公开库", "多源 融合", "PASS")
        append_log(lp, "公开库", "读数 示例保密词甲", "BLOCK")
        txt = open(lp, encoding="utf-8").read()
        ok.append(("log masks blocked", canary not in txt and "多源 融合" in txt and txt.startswith("日期")))
        tp = os.path.join(d, "confidential_terms.txt")
        open(tp, "w", encoding="utf-8").write("# c\n示例保密词甲\nre:秘\\d+\n")
        t2, r2 = load_terms([tp])
        ok.append(("load terms", t2 == [canary] and len(r2) == 1))
    me = open(os.path.abspath(__file__), encoding="utf-8").read()
    net = re.findall(r"^\s*(?:import|from)\s+(socket|urllib|http|requests|ftplib|smtplib|ssl)\b", me, re.M)
    ok.append(("no network imports", net == []))
    for name, r in ok:
        print(("PASS " if r else "FAIL ") + name)
    return all(r for _, r in ok)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="公网检索词离线守门（不联网）")
    ap.add_argument("query", nargs="*")
    ap.add_argument("--file", help="每行一个检索式")
    ap.add_argument("--terms", action="append", default=[], help="保密词表（默认 ./confidential_terms*.txt）")
    ap.add_argument("--source", action="append", default=[], help="本地内容源（txt/md/json/docx，只读）")
    ap.add_argument("--allow", action="append", default=[], help="允许的通用词（不计重合）")
    ap.add_argument("--ngram", type=int, default=8)
    ap.add_argument("--block-ngram", type=int, default=12)
    ap.add_argument("--max-len", type=int, default=40)
    ap.add_argument("--show", action="store_true", help="明文显示命中项（默认打码）")
    ap.add_argument("--strict", action="store_true", help="WARN 也返回非零（1）")
    ap.add_argument("--log", help="把结果追加到检索日志 TSV")
    ap.add_argument("--db", default="", help="检索日志里的数据源名称")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return 0 if _selftest() else 1
    queries = list(a.query and [" ".join(a.query)] or [])
    if a.file:
        with open(a.file, encoding="utf-8-sig") as f:
            queries += [l.strip() for l in f if l.strip() and not l.startswith("#")]
    if not queries:
        print(__doc__)
        return 0
    tpaths = a.terms or sorted(glob.glob("confidential_terms*.txt"))
    terms, regexes = load_terms(tpaths) if tpaths else ([], [])
    source = load_source_text(a.source) if a.source else ""
    worst = 0
    for q in queries:
        verdict, reasons = check_query(q, terms, regexes, source, a.allow, a.ngram, a.block_ngram, a.max_len,
                                       a.show, have_terms=bool(tpaths))
        shown = q if verdict != "BLOCK" or a.show else "[已拦截，检索式不回显]"
        print(f"{verdict}  {shown}")
        for r in reasons:
            print(f"    - {r}")
        if a.log:
            append_log(a.log, a.db, q, verdict)
        worst = max(worst, {"PASS": 0, "WARN": 1 if a.strict else 0, "BLOCK": 2}[verdict])
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
