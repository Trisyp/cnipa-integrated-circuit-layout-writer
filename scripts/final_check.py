# NOTE: 布图登记主验收请优先用 check_layout_package.py / layout_gates.py。
# 本脚本保留用于简要说明 docx 的只读验收；发明专利四节逻辑已降级。
# -*- coding: utf-8 -*-
"""final_check.py — 终稿一次性验收：结构 + 内容门禁 + 证据台账 + 渲染，写验收快照与 build-manifest。

**只读终稿**：docx 只被读取与（复制到临时目录后）渲染，绝不写回、不加元数据/批注/高亮/表格；
运行前后比对 docx 的 sha256，变化即 FAIL。所有输出只写 reports/（默认 <docx 所在目录>/reports）：
    reports/acceptance-YYYYMMDD-HHMMSS.txt    验收快照（含 docx sha256；docx 一改即“过期”）
    reports/build-manifest-YYYYMMDD-HHMMSS.json  技能 commit、脚本/模板/内容源/台账/终稿哈希
    reports/_render_final/                    渲染页（render_check 会清空该目录，勿放其他文件）
    reports/核心参数回填与特殊效果-YYYYMMDD.md     （给 --ledger 且加 --export-backfill 时）

判定：
    FAIL（验收不通过）：非 4 节 / 4 页眉不对 / 权要书与说明书页码未从 1 重起或无 PAGE 域；内部验证用语
        （仿真/种子/场景N…）；权1 带小数或百分数；权利要求编号/引用错误；公式空角标 ❑；终稿在检查中被改动。
    WARN（人工复核，不影响通过）：证据台账缺行/来源偏弱、有益效果数字在实施例找不到、背景疑似写入本发明、
        申请号校验位、附图首次引用顺序、摘要超 300 字、未渲染、过度宣称口号、支撑矩阵缺行。
    INFO：占位数量（允许占位，待本地回填）、超 10 项附加费提示、摘要/附图节页码情况。
门禁只报告，从不改写内容。仅标准库（渲染沿用 render_check.py 的后端回退）。不联网。

用法：
    python final_check.py 成稿.docx [--reports DIR] [--ledger evidence/ledger.tsv] [--glossary 术语表.txt]
                          [--template 模板.docx] [--source content.py ...] [--matrix support.tsv] [--export-backfill] [--no-render] [--dpi 110]
    python final_check.py --verify reports/acceptance-xxx.txt [成稿.docx]   # 快照是否仍对应当前终稿
    python final_check.py --selftest
"""
import contextlib
import datetime
import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from docx_text import EXPECTED_HEADERS, docx_structure, read_sections, split_spec  # noqa: E402
import patent_gates as G  # noqa: E402
import evidence_ledger as EL  # noqa: E402


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _lines(path):
    if not path:
        return []
    with open(path, encoding="utf-8-sig") as f:
        return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]


def check_docx(docx, glossary=(), ledger_path=None, matrix_path=None):
    """返回 [(level, category, message)]；level ∈ PASS/WARN/FAIL/INFO。只读。"""
    R = []
    add = lambda lv, cat, msg: R.append((lv, cat, msg))
    st = docx_structure(docx)
    n = len(st)
    add("PASS" if n == 4 else "FAIL", "结构", f"{n} 个分节（应为 4）")
    heads = [s["header"] for s in st]
    add("PASS" if heads == list(EXPECTED_HEADERS) else "FAIL", "结构", "页眉: " + " / ".join(h or "(空)" for h in heads))
    for i, name in ((1, "权利要求书"), (2, "说明书")):
        if i < n:
            good = st[i]["pg_start"] == "1" and st[i]["footer_page"]
            add("PASS" if good else "FAIL", "结构",
                f"{name}节页码从 1 重起且有 PAGE 域: start={st[i]['pg_start']}, PAGE={st[i]['footer_page']}")
    for i, name in ((0, "说明书摘要"), (3, "说明书附图")):
        if i < n:
            add("INFO", "结构", f"{name}节: PAGE={st[i]['footer_page']}, start={st[i]['pg_start']}（按模板实测为准）")

    parts = split_spec(read_sections(docx))
    claims = parts["claims"]
    if not claims:
        add("FAIL", "权要", "未解析到权利要求")
    texts = {"摘要": parts["abstract"], "权利要求书": "\n".join(claims), "说明书": parts["spec"],
             "说明书附图": parts["drawings"]}
    e = G.internal_wording(texts)
    add("FAIL" if e else "PASS", "用语", "; ".join(e) or "申请文本无内部验证用语")
    if claims:
        e = G.claim1_numbers(claims[0])
        add("FAIL" if e else "PASS", "权要", "; ".join(e) or "权1 无小数/百分数")
        e = G.claim_structure(claims)
        hard = [x for x in e if not x.startswith("NOTICE")]
        add("FAIL" if hard else "PASS", "权要", "; ".join(hard) or f"{len(claims)} 项权利要求编号与引用正确")
        for x in e:
            if x.startswith("NOTICE"):
                add("INFO", "权要", x)
    e = G.untraceable_numbers(parts["effects"], parts["embodiments"])
    add("WARN" if e else "PASS", "效果", "; ".join(e) or "有益效果数字均可在实施例找到")
    e = G.figure_first_ref_order(parts["embodiments"])
    add("WARN" if e else "PASS", "附图", "; ".join(e) or "附图首次引用顺序正确")
    if not parts["background"].strip():
        add("WARN", "背景", "未找到背景技术段（标题应为「背景技术」）")
    else:
        e = G.background_leak(parts["background"], glossary, claim1=claims[0] if claims else "", summary=parts["summary"])
        add("WARN" if e else "PASS", "背景", "; ".join(e) or "背景未发现本发明手段/效果措辞")
    e = G.cn_appno_scan(parts["spec"])
    add("WARN" if e else "PASS", "引用", "; ".join(e) or "申请号校验位无误（或未引用申请号）")
    alen = len(re.sub(r"\s", "", parts["abstract"]))
    add("WARN" if alen > 300 else "PASS", "摘要", f"摘要 {alen} 字（≤300）")
    add("INFO", "占位", EL.placeholder_report(texts)[0][5:])
    if ledger_path:
        L = EL.load_ledger(ledger_path)
        w = EL.ledger_numbers({"有益效果": parts["effects"], "具体实施方式": parts["embodiments"]}, L)
        w += EL.verify_hashes(L, os.path.dirname(os.path.abspath(ledger_path)))
        for x in w:
            add("WARN", "证据", x[5:] if x.startswith("WARN ") else x)
        if not w:
            add("PASS", "证据", f"台账 {len(L)} 行，有益效果/实施例数字均已入账")
    else:
        add("INFO", "证据", "未提供证据台账（--ledger），跳过数值溯源提示")
    e = G.overclaim({"有益效果": parts["effects"], "背景技术": parts["background"], "摘要": parts["abstract"]})
    add("WARN" if e else "PASS", "表述", "; ".join(e) or "未发现 writing-style 空口号/过度宣称启发式")
    if matrix_path:
        import support_matrix as SM
        rows = SM.load_matrix(matrix_path)
        w = SM.check_rows(rows)
        w += SM.check_against_docx(rows, docx)
        for x in w:
            add("WARN", "支撑", x[5:] if x.startswith("WARN ") else x)
        if not w:
            add("PASS", "支撑", f"矩阵 {len(rows)} 行，无缺支撑 WARN")
    else:
        add("INFO", "支撑", "未提供支撑矩阵（--matrix），跳过要素支撑提示")
    return R


def render_step(docx, reports_dir, dpi=110):
    """把终稿复制到临时目录后渲染（原文件不被任何后端打开）；返回 [(level, cat, msg)], info。"""
    R, info = [], {}
    try:
        import render_check
    except Exception as ex:  # pragma: no cover
        return [("WARN", "渲染", f"render_check 不可用: {ex}")], info
    tmp = tempfile.mkdtemp(prefix="cpw_final_")
    try:
        copy = os.path.join(tmp, os.path.basename(docx))
        shutil.copy2(docx, copy)
        out_dir = os.path.join(reports_dir, "_render_final")
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                pages = render_check.render(copy, out_dir, dpi)
        except Exception as ex:
            return [("WARN", "渲染", f"未能渲染（须人工在 Word/WPS 逐页看）: {' | '.join(l.strip() for l in str(ex).splitlines() if l.strip())[:400]}")], info
        log = buf.getvalue()
        backends = [l.strip() for l in log.splitlines() if "后端" in l] or ["soffice + pdftoppm（主路径）"]
        info = {"pages": len(pages), "out_dir": out_dir, "backends": backends}
        R.append(("PASS" if pages else "WARN", "渲染", f"{len(pages)} 页 → {out_dir}；{'; '.join(backends)}；请逐页查看 PNG"))
        pdfs = glob.glob(os.path.join(out_dir, "*.pdf"))
        pt = shutil.which("pdftotext")
        if pdfs and pt:
            txt = os.path.join(tmp, "t.txt")
            subprocess.run([pt, "-enc", "UTF-8", pdfs[0], txt], capture_output=True, timeout=120)
            s = open(txt, encoding="utf-8", errors="replace").read() if os.path.isfile(txt) else ""
            n1, n2 = s.count("❑"), s.count("□")
            R.append(("FAIL" if n1 else "PASS", "公式", f"PDF 文本中 ❑ = {n1}"))
            if n2:
                R.append(("WARN", "字形", f"PDF 文本中 □ = {n2}（核对是否豆腐块）"))
        else:
            R.append(("INFO", "公式", "无 pdftotext，❑ 计数跳过；请看公式页"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return R, info


def _git_commit(d):
    try:
        r = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        c = r.stdout.strip() if r.returncode == 0 else ""
        dirty = subprocess.run(["git", "-C", d, "status", "--porcelain"], capture_output=True, text=True, timeout=10)
        return c, bool(dirty.stdout.strip()) if dirty.returncode == 0 else None
    except Exception:
        return "", None


def write_manifest(path, docx, docx_sha, template=None, sources=(), ledger=None, render_info=None):
    skill_dir = os.path.dirname(HERE)
    commit, dirty = _git_commit(skill_dir)
    m = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
         "docx": {"path": os.path.abspath(docx), "sha256": docx_sha, "size": os.path.getsize(docx)},
         "skill": {"dir": skill_dir, "git_commit": commit, "dirty": dirty,
                   "scripts": {os.path.basename(p): sha256_file(p) for p in sorted(glob.glob(os.path.join(HERE, "*.py")))}},
         "template": {"path": os.path.abspath(template), "sha256": sha256_file(template)} if template else None,
         "sources": [{"path": os.path.abspath(s), "sha256": sha256_file(s)} for s in sources],
         "ledger": {"path": os.path.abspath(ledger), "sha256": sha256_file(ledger)} if ledger else None,
         "render": render_info or None}
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    return path


def run(docx, reports=None, ledger=None, glossary=None, template=None, sources=(), export_backfill=False,
        render=True, dpi=110, quiet=False, matrix=None):
    docx = os.path.abspath(docx)
    reports = os.path.abspath(reports or os.path.join(os.path.dirname(docx), "reports"))
    if os.path.basename(reports).lower() != "reports":
        raise ValueError("输出目录须名为 reports: " + reports)
    os.makedirs(reports, exist_ok=True)
    before = sha256_file(docx)
    R = check_docx(docx, _lines(glossary), ledger, matrix)
    rinfo = {}
    if render:
        rr, rinfo = render_step(docx, reports, dpi)
        R += rr
    else:
        R.append(("WARN", "渲染", "--no-render：未做视觉校验，交付前须渲染逐页查看"))
    if export_backfill and ledger:
        p = EL.export_backfill(EL.load_ledger(ledger), EL.default_backfill_path(reports), os.path.basename(ledger))
        R.append(("INFO", "证据", "已写「核心参数回填与特殊效果」草表（仅 reports/）: " + os.path.basename(p)))
    after = sha256_file(docx)
    R.append(("PASS" if after == before else "FAIL", "只读", "检查前后终稿 sha256 一致" if after == before else "终稿在检查中被改动！"))
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base, i = stamp, 2
    while glob.glob(os.path.join(reports, f"*-{stamp}.*")):
        stamp, i = f"{base}-{i}", i + 1
    man = write_manifest(os.path.join(reports, f"build-manifest-{stamp}.json"), docx, after, template, sources, ledger, rinfo)
    cnt = {k: sum(1 for r in R if r[0] == k) for k in ("PASS", "WARN", "FAIL", "INFO")}
    verdict = "ACCEPT" if cnt["FAIL"] == 0 else "REJECT"
    lines = ["# cnipa-patent-writer 终稿验收快照（内部文档，不进正式稿）",
             f"time: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
             f"docx: {docx}", f"docx_sha256: {after}", f"manifest: {os.path.basename(man)}", ""]
    lines += [f"{lv:<5} [{cat}] {msg}" for lv, cat, msg in R]
    lines += ["", f"summary: PASS {cnt['PASS']} / WARN {cnt['WARN']} / FAIL {cnt['FAIL']} / INFO {cnt['INFO']}",
              f"verdict: {verdict}" + ("（WARN 为人工复核项，不影响通过）" if verdict == "ACCEPT" and cnt["WARN"] else ""),
              "note: 终稿再改动即本快照过期（python final_check.py --verify 本文件）；验收 PASS ≠ 创造性够硬。"]
    acc = os.path.join(reports, f"acceptance-{stamp}.txt")
    with open(acc, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    if not quiet:
        print("\n".join(lines[5:]))
        print("验收快照:", acc)
    return verdict, acc, R


def verify(acc_path, docx=None):
    txt = open(acc_path, encoding="utf-8").read()
    want = re.search(r"^docx_sha256: (\w+)", txt, re.M)
    path = docx or (re.search(r"^docx: (.+)$", txt, re.M) or [None, None])[1]
    if not want or not path or not os.path.isfile(path):
        print("STALE 无法核对（快照或终稿缺失）")
        return 1
    if sha256_file(path) == want.group(1):
        print("CURRENT 快照对应当前终稿")
        return 0
    print("STALE 终稿已改动，需重新运行 final_check.py")
    return 1


def _selftest():
    from docx_text import make_fake_docx
    ok = []
    claims = ("1.一种方法，其特征在于，包括：S1，获取读数；S2，当偏差超过预设门限时标记异常。",
              "2.根据权利要求1所述的方法，其特征在于，所述门限按历史数据确定。",
              "3.一种系统，用于执行如权利要求1至2任一项所述的方法，其特征在于，包括获取模块。")
    spec = (("技术领域", "本发明涉及数据处理领域。"), ("背景技术", "现有做法采用算术平均，对偏离读数敏感。"),
            ("发明内容", "本发明提出一种方法。"), ("有益效果", "平均偏差为0.42。"),
            ("附图说明", "图1为流程示意图。"), ("具体实施方式", "参见图1，门限取【待用户本地回填：门限】，平均偏差为0.42。"))
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.docx")
        make_fake_docx(good, claims=claims, spec=spec)
        rep = os.path.join(d, "reports")
        v, acc, R = run(good, rep, render=False, quiet=True)
        ok.append(("good -> ACCEPT", v == "ACCEPT"))
        ok.append(("acceptance written", os.path.isfile(acc) and glob.glob(os.path.join(rep, "build-manifest-*.json")) != []))
        ok.append(("placeholder INFO", any(r[0] == "INFO" and "placeholders: 1" in r[2] for r in R)))
        ok.append(("verify current", verify(acc) == 0))
        lp = os.path.join(d, "ledger.tsv")
        open(lp, "w", encoding="utf-8").write("id\tvalue\tsource\nE1\t0.10\t仿真\n")
        v2, _, R2 = run(good, rep, ledger=lp, render=False, quiet=True)
        ok.append(("ledger gap -> WARN, still ACCEPT", v2 == "ACCEPT" and any(r[0] == "WARN" and r[1] == "证据" and "0.42" in r[2] for r in R2)))
        cases = {
            "3 sections -> REJECT": dict(n_sections=3),
            "no page restart -> REJECT": dict(restart=(2,)),
            "wrong header -> REJECT": dict(headers=("说明书摘要", "权利要求书", "说明书", "附图")),
            "claim1 decimal -> REJECT": dict(claims=("1.一种方法，门限取0.8。",) + claims[1:]),
            "internal wording -> REJECT": dict(spec=spec[:-1] + (("具体实施方式", "仿真条件：场景一，平均偏差为0.42。"),)),
            "bad claim ref -> REJECT": dict(claims=claims[:1] + ("2.根据权利要求3所述的方法。",) + claims[2:]),
        }
        for name, kw in cases.items():
            p = os.path.join(d, "bad.docx")
            args = dict(claims=claims, spec=spec)
            args.update(kw)
            make_fake_docx(p, **args)
            ok.append((name, run(p, rep, render=False, quiet=True)[0] == "REJECT"))
        leak = os.path.join(d, "leak.docx")
        make_fake_docx(leak, claims=claims, spec=(spec[0], ("背景技术", "本发明当偏差超过预设门限时标记异常。")) + spec[2:])
        v3, _, R3 = run(leak, rep, render=False, quiet=True)
        ok.append(("background leak -> WARN only", v3 == "ACCEPT" and any(r[0] == "WARN" and r[1] == "背景" for r in R3)))
        oc = os.path.join(d, "oc.docx")
        make_fake_docx(oc, claims=claims, spec=(spec[0], spec[1], spec[2], ("有益效果", "本发明填补空白，具有重要意义。"), spec[4], spec[5]))
        v4, _, R4 = run(oc, rep, render=False, quiet=True)
        ok.append(("overclaim -> WARN only", v4 == "ACCEPT" and any(r[0] == "WARN" and r[1] == "表述" for r in R4)))
        with open(good, "ab") as f:
            f.write(b"\0")
        ok.append(("verify stale", verify(acc) == 1))
        try:
            run(good, os.path.join(d, "out"), render=False, quiet=True)
            ok.append(("refuse non-reports dir", False))
        except ValueError:
            ok.append(("refuse non-reports dir", True))
    me = open(os.path.abspath(__file__), encoding="utf-8").read()
    ok.append(("never opens docx for writing", re.search(r"open\(\s*docx\s*,\s*['\"][wa]", me) is None))
    for name, r in ok:
        print(("PASS " if r else "FAIL ") + name)
    return all(r for _, r in ok)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="终稿只读验收（输出只写 reports/）")
    ap.add_argument("docx", nargs="?")
    ap.add_argument("--reports")
    ap.add_argument("--ledger")
    ap.add_argument("--matrix", help="权要要素支撑矩阵 TSV/JSON（缺支撑只 WARN）")
    ap.add_argument("--glossary", help="本发明独有术语，每行一个（背景泄漏检查用）")
    ap.add_argument("--template")
    ap.add_argument("--source", action="append", default=[])
    ap.add_argument("--export-backfill", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--verify", metavar="ACCEPTANCE_TXT")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return 0 if _selftest() else 1
    if a.verify:
        return verify(a.verify, a.docx)
    if not a.docx:
        print(__doc__)
        return 0
    v, _, _ = run(a.docx, a.reports, a.ledger, a.glossary, a.template, a.source, a.export_backfill,
                  not a.no_render, a.dpi, matrix=a.matrix)
    return 0 if v == "ACCEPT" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
