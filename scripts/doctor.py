# -*- coding: utf-8 -*-
"""doctor.py — cnipa-integrated-circuit-layout-writer 环境体检(只检查、不安装、不联网)。

一条命令报告每个依赖的状态、当前选中的渲染后端,以及缺失项的具体修复建议。
渲染后端按"有序回退链"真实探测(实际转换一个临时小 docx/pdf),第一个真正可用的胜出:
    docx->pdf: soffice -> Word COM(Windows, pywin32) -> docx2pdf
    pdf->png : pdftoppm -> PyMuPDF(fitz)
(与 render_check.py 共用同一套后端顺序;可用环境变量 CPW_DOCX2PDF_ORDER / CPW_PDF2PNG_ORDER 重排。)

用法:
    python scripts/doctor.py            # 完整体检(含真实转换探测,约数秒~半分钟)
    python scripts/doctor.py --quick    # 跳过真实转换探测,只查存在性
    python scripts/doctor.py --json     # 机器可读输出
    python scripts/doctor.py --all      # 回退链中每个后端都实测(默认找到可用者即停止)
    python scripts/doctor.py --intake session_intake.json  # 开工就绪清单(转发 session_intake)

退出码:所有"必需"项未 FAIL 返回 0,否则 1。
本脚本自身只用标准库;不安装任何东西,不访问网络。
"""
import argparse
import glob
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import warnings
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"

CJK_FONT_NAMES = ["SimSun", "NSimSun", "SimHei", "Microsoft YaHei", "Noto Sans CJK SC", "Noto Sans SC",
                  "Noto Serif CJK SC", "Noto Sans CJK JP", "Source Han Sans SC", "Source Han Serif SC",
                  "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "PingFang SC", "Heiti SC", "STHeiti",
                  "STSong", "FangSong", "KaiTi", "DengXian"]

# ---------------------------------------------------------------------------
# 修复建议(按平台)
# ---------------------------------------------------------------------------


def _fix(win, linux, mac=None):
    if IS_WIN:
        return win
    if IS_MAC:
        return mac or linux
    return linux


PIP = "%s -m pip install" % ("python" if IS_WIN else "python3")
FIX = {
    "python": "安装 Python 3.8+(建议 3.10+),并确认 PATH 上的 python 不是 LibreOffice 便携版自带解释器",
    "python-docx": PIP + " python-docx",
    "matplotlib": PIP + " matplotlib",
    "Pillow": PIP + " Pillow",
    "math2docx": PIP + " math2docx   (仅 $...$ LaTeX 转 OMML 时需要)",
    "graphviz-py": PIP + " graphviz   (仅用 gen_figures_graphviz.py 时需要)",
    "dot": _fix("winget install Graphviz.Graphviz,或 https://graphviz.org/download/ 安装后把 bin 加入 PATH",
                "sudo apt-get install -y graphviz", "brew install graphviz"),
    "cjk": _fix("系统通常自带 宋体/黑体/微软雅黑(C:\\Windows\\Fonts);若缺,安装开源 Noto Sans CJK SC 后"
                "删除 matplotlib 字体缓存(%USERPROFILE%\\.matplotlib\\fontlist-*.json)",
                "sudo apt-get install -y fonts-noto-cjk,或把宋体/黑体放 ~/.fonts 后 fc-cache -f,"
                "再删 ~/.cache/matplotlib/fontlist-*.json",
                "brew install --cask font-noto-sans-cjk-sc,然后删 ~/.matplotlib/fontlist-*.json"),
    "soffice": _fix("winget install TheDocumentFoundation.LibreOffice(或用便携版,把其 program 目录加入 PATH,"
                    "或设环境变量 CPW_SOFFICE=soffice.com 的绝对路径)",
                    "sudo apt-get install -y libreoffice-writer", "brew install --cask libreoffice"),
    "word": "安装 Microsoft Word(或可注册 Word.Application 的 WPS)并 " + PIP + " pywin32",
    "word-probe": "Word.Application 已注册但实测转换失败:关闭卡住的 Word/WPS 弹窗(激活/恢复文档/更新提示)后重跑;"
                  "仍失败则改装 LibreOffice(首选后端)",
    "soffice-probe": "soffice 存在但实测转换失败:关闭正在运行的 LibreOffice 后重跑,或重装 LibreOffice",
    "docx2pdf-probe": "docx2pdf 实测失败(它依赖 Word):先确认 Word 可正常打开文档,或改装 LibreOffice",
    "docx2pdf": PIP + " docx2pdf   (Windows/macOS 上依赖已安装的 Word)",
    "pdftoppm": _fix("安装 poppler for Windows(conda install -c conda-forge poppler,或 MiKTeX 自带),"
                     "并把含 pdftoppm.exe 的 bin 目录加入 PATH",
                     "sudo apt-get install -y poppler-utils", "brew install poppler"),
    "fitz": PIP + " PyMuPDF",
}

# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _run(cmd, timeout=30):
    """运行命令,返回 (rc, 合并输出首行)。不存在/超时返回 rc=None。"""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        out = (r.stdout or b"") + b"\n" + (r.stderr or b"")
        txt = out.decode("utf-8", "replace").strip()
        first = next((ln.strip() for ln in txt.splitlines() if ln.strip()), "")
        return r.returncode, first, txt
    except FileNotFoundError:
        return None, "未找到可执行文件", ""
    except subprocess.TimeoutExpired:
        return None, "超时(%ss)" % timeout, ""
    except Exception as e:  # pragma: no cover
        return None, str(e), ""


def _import(mod):
    try:
        m = __import__(mod)
        return True, getattr(m, "__version__", "") or "", ""
    except Exception as e:
        return False, "", "%s: %s" % (type(e).__name__, e)


def _short(msg, n=90):
    msg = " ".join(str(msg).split())
    return msg if len(msg) <= n else msg[: n - 3] + "..."


def make_tiny_docx(path):
    """纯标准库生成一个最小 docx(含中文),用于真实转换探测。"""
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
          'wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="word/document.xml"/></Relationships>')
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           '<w:p><w:r><w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="SimSun"/></w:rPr>'
           '<w:t>环境体检 doctor probe 123</w:t></w:r></w:p>'
           '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
    return path


def make_tiny_pdf(path):
    """纯标准库生成一页最小 PDF(docx->pdf 全部不可用时,仍可单独探测 pdf->png)。"""
    stream = b"BT /F1 24 Tf 40 100 Td (doctor probe) Tj ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(buf.tell())
        buf.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    x = buf.tell()
    buf.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for o in offs:
        buf.write(b"%010d 00000 n \n" % o)
    buf.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x))
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return path


# ---------------------------------------------------------------------------
# 检查项
# ---------------------------------------------------------------------------


class Doctor:
    def __init__(self, quick=False, probe_all=False):
        self.quick = quick
        self.probe_all = probe_all
        self.items = []
        self.selected = {"docx2pdf": None, "pdf2png": None}
        self.tmp = tempfile.mkdtemp(prefix="cpw_doctor_")

    def add(self, cat, name, status, detail, fix="", required=False):
        self.items.append({"category": cat, "name": name, "status": status, "required": required,
                           "detail": _short(detail, 120), "fix": fix if status in (WARN, FAIL) else ""})

    # -- Python 与包 --------------------------------------------------------
    def check_python(self):
        v = sys.version_info
        ok = v >= (3, 8)
        self.add("Python", "Python 版本", PASS if ok else FAIL,
                 "%s (%s)" % (platform.python_version(), sys.executable), FIX["python"], required=True)

    def check_packages(self):
        for mod, label, req in (("docx", "python-docx", True), ("matplotlib", "matplotlib", True),
                                ("PIL", "Pillow", True), ("math2docx", "math2docx", False)):
            ok, ver, err = _import(mod)
            if ok:
                self.add("Python 包", label, PASS, "已安装 %s" % ver, required=req)
            else:
                self.add("Python 包", label + ("" if req else "(可选)"), FAIL if req else WARN,
                         err or "无法导入", FIX[label], required=req)

    def check_graphviz(self):
        ok, ver, err = _import("graphviz")
        self.add("配图", "graphviz Python 包(可选)", PASS if ok else WARN,
                 ("已安装 %s" % ver) if ok else (err or "无法导入"), FIX["graphviz-py"])
        dot = shutil.which("dot")
        if not dot:
            self.add("配图", "dot 可执行文件(可选)", WARN, "PATH 上未找到 dot", FIX["dot"])
            return
        rc, first, _ = _run([dot, "-V"])
        if rc != 0:
            self.add("配图", "dot 可执行文件(可选)", WARN, "dot -V 失败:%s" % first, FIX["dot"])
            return
        if self.quick:
            self.add("配图", "dot 可执行文件(可选)", PASS, "%s (%s)" % (first, dot))
            return
        src = os.path.join(self.tmp, "g.dot")
        png = os.path.join(self.tmp, "g.png")
        with open(src, "w", encoding="utf-8") as f:
            f.write('digraph G { a [label="开始"]; b [label="结束"]; a -> b; }\n')
        rc2, first2, _ = _run([dot, "-Tpng", "-o", png, src], timeout=60)
        if rc2 == 0 and os.path.isfile(png) and os.path.getsize(png) > 0:
            self.add("配图", "dot 可执行文件(可选)", PASS, "%s;实测出图 OK" % first)
        else:
            self.add("配图", "dot 可执行文件(可选)", WARN, "dot -V 正常但出图失败:%s" % first2, FIX["dot"])

    # -- CJK 字体 -----------------------------------------------------------
    def check_cjk(self):
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.font_manager as fm
        except Exception as e:
            self.add("字体", "matplotlib 中文字体", FAIL, "matplotlib 不可用,无法检查:%s" % e,
                     FIX["matplotlib"], required=True)
            return
        found = {}
        by_name = {}
        for f in fm.fontManager.ttflist:
            if f.name in CJK_FONT_NAMES:
                by_name.setdefault(f.name, []).append(f)
        for n in CJK_FONT_NAMES:  # 按优先级:宋体/黑体优先,常规字重优先
            if n in by_name:
                fs = sorted(by_name[n], key=lambda f: (str(f.weight) not in ("400", "normal", "regular"),
                                                       f.style != "normal", f.fname))
                found[n] = fs[0].fname
        if not found:  # 兜底:按文件名猜
            for f in fm.fontManager.ttflist:
                low = os.path.basename(f.fname).lower()
                if any(k in low for k in ("cjk", "simsun", "simhei", "msyh", "notosanssc", "wqy")):
                    found.setdefault(f.name, f.fname)
        if not found:
            self.add("字体", "matplotlib 中文字体", FAIL, "font_manager 中未发现中文字体(中文将渲染为豆腐块)",
                     FIX["cjk"], required=True)
            return
        names = list(found)
        font, path = names[0], found[names[0]]
        if self.quick:
            self.add("字体", "matplotlib 中文字体", PASS, "发现 %s 等 %d 种(--quick 未实测渲染)"
                     % (", ".join(names[:3]), len(names)), required=True)
        else:
            try:
                import matplotlib.pyplot as plt
                png = os.path.join(self.tmp, "cjk.png")
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")
                    fig = plt.figure(figsize=(2, 0.6), dpi=50)
                    fig.text(0.05, 0.3, "权利要求书 中文体检", fontfamily=font)
                    fig.savefig(png)
                    plt.close(fig)
                missing = [str(x.message) for x in w if "missing" in str(x.message).lower()]
                if missing:
                    self.add("字体", "matplotlib 中文字体", FAIL, "用 %s 实测渲染缺字形:%s" % (font, missing[0]),
                             FIX["cjk"], required=True)
                    return
                self.add("字体", "matplotlib 中文字体", PASS, "实测渲染中文 OK(%s;共发现 %d 种)"
                         % (font, len(names)), required=True)
            except Exception as e:
                self.add("字体", "matplotlib 中文字体", FAIL, "实测渲染出错:%s" % e, FIX["cjk"], required=True)
                return
        # make_figures.setup_cjk() 默认只找固定路径(偏 Linux):提示是否需显式传 font_path
        try:
            import make_figures  # noqa: 只读其候选列表
            cands = list(getattr(make_figures, "_CANDIDATES", []))
            hit = next((c for c in cands if os.path.exists(c)), None)
            if not hit:
                hit = next(iter(glob.glob("/usr/share/fonts/**/*CJK*.ttc", recursive=True)), None)
        except Exception:
            hit = "?"
        if hit is None:
            self.add("字体", "make_figures 默认字体路径", WARN, "setup_cjk() 默认候选路径均未命中",
                     "调用 setup_cjk(font_path=r\"%s\") 显式传入已发现的中文字体" % path)
        elif hit != "?":
            self.add("字体", "make_figures 默认字体路径", PASS, "setup_cjk() 默认可用:%s" % hit)

    # -- 渲染后端 -----------------------------------------------------------
    def check_render(self):
        try:
            import render_check as rc
        except Exception as e:
            self.add("渲染", "render_check.py", FAIL, "无法导入 render_check.py:%s" % e,
                     "确认 scripts/render_check.py 存在且未损坏")
            return
        docx = make_tiny_docx(os.path.join(self.tmp, "probe.docx"))
        made_pdf = None
        d_order = rc._order("CPW_DOCX2PDF_ORDER", rc.DOCX2PDF_ORDER)
        label = {"soffice": "LibreOffice soffice", "word": "Microsoft Word COM", "docx2pdf": "docx2pdf 包"}
        for i, name in enumerate(d_order, 1):
            title = "docx->pdf #%d %s" % (i, label[name])
            if self.selected["docx2pdf"] and not self.probe_all:
                self.add("渲染", title, SKIP, "已选用更靠前的后端 %s" % self.selected["docx2pdf"])
                continue
            present, where = self._docx2pdf_present(rc, name)
            if not present:
                self.add("渲染", title, WARN, where, FIX[name])
                continue
            if self.quick:
                self.add("渲染", title, PASS, "已发现 %s(--quick 未实测)" % where)
                self.selected["docx2pdf"] = self.selected["docx2pdf"] or name
                continue
            outdir = os.path.join(self.tmp, "out_" + name)
            os.makedirs(outdir, exist_ok=True)
            target = os.path.join(outdir, "probe.pdf")
            try:
                if name == "soffice":
                    pdf = rc.docx_to_pdf_soffice(docx, outdir, where, timeout=120)
                elif name == "word":
                    pdf = rc.docx_to_pdf_word(docx, target, timeout=120)
                else:
                    pdf = rc.docx_to_pdf_docx2pdf(docx, target, timeout=120)
                ok = os.path.isfile(pdf) and os.path.getsize(pdf) > 0
            except subprocess.CalledProcessError as e:
                err = (e.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [str(e)]
                self.add("渲染", title, FAIL, "实测转换失败:%s" % err[0], FIX[name + "-probe"])
                continue
            except Exception as e:
                self.add("渲染", title, FAIL, "实测转换失败:%s" % e, FIX[name + "-probe"])
                continue
            if ok:
                made_pdf = made_pdf or pdf
                self.add("渲染", title, PASS, "实测 docx->pdf OK(%s)" % where)
                self.selected["docx2pdf"] = self.selected["docx2pdf"] or name
            else:
                self.add("渲染", title, FAIL, "未生成 PDF", FIX[name + "-probe"])

        pdf = made_pdf or make_tiny_pdf(os.path.join(self.tmp, "fallback.pdf"))
        p_order = rc._order("CPW_PDF2PNG_ORDER", rc.PDF2PNG_ORDER)
        plabel = {"pdftoppm": "pdftoppm (poppler)", "fitz": "PyMuPDF (fitz)"}
        for i, name in enumerate(p_order, 1):
            title = "pdf->png #%d %s" % (i, plabel[name])
            if self.selected["pdf2png"] and not self.probe_all:
                self.add("渲染", title, SKIP, "已选用更靠前的后端 %s" % self.selected["pdf2png"])
                continue
            if name == "pdftoppm":
                exe = shutil.which("pdftoppm")
                if not exe:
                    self.add("渲染", title, WARN, "PATH 上未找到 pdftoppm", FIX[name])
                    continue
                if self.quick:
                    self.add("渲染", title, PASS, "已发现 %s(--quick 未实测)" % exe)
                    self.selected["pdf2png"] = self.selected["pdf2png"] or name
                    continue
                prefix = os.path.join(self.tmp, "pp")
                rcode, first, _ = _run([exe, "-png", "-r", "30", "-f", "1", "-l", "1", pdf, prefix], timeout=60)
                ok = rcode == 0 and bool(glob.glob(prefix + "-*.png"))
                detail = "实测 pdf->png OK(%s)" % exe if ok else "实测失败:%s" % first
            else:
                okimp, ver, err = _import("fitz")
                if not okimp:
                    self.add("渲染", title, WARN, err or "无法导入 fitz", FIX[name])
                    continue
                if self.quick:
                    self.add("渲染", title, PASS, "已安装 PyMuPDF %s(--quick 未实测)" % ver)
                    self.selected["pdf2png"] = self.selected["pdf2png"] or name
                    continue
                try:
                    pages = rc.pdf_to_png_fitz(pdf, os.path.join(self.tmp, "fz"), 30)
                    ok = bool(pages) and os.path.getsize(pages[0]) > 0
                    detail = "实测 pdf->png OK(PyMuPDF %s)" % ver
                except Exception as e:
                    ok, detail = False, "实测失败:%s" % e
            if ok:
                self.add("渲染", title, PASS, detail)
                self.selected["pdf2png"] = self.selected["pdf2png"] or name
            else:
                self.add("渲染", title, FAIL, detail, FIX[name])

        d, p = self.selected["docx2pdf"], self.selected["pdf2png"]
        if d and p:
            primary = (d == "soffice" and p == "pdftoppm")
            note = ""
            if d == "word" and "wps" in rc.word_com_server().lower():
                note = ";Word.Application 由 WPS 接管,版面可能与 Word/LibreOffice 略有差异"
            self.add("渲染", "render_check 选用后端", PASS,
                     "%s + %s%s%s" % (d, p, "(主路径)" if primary else "(回退路径,render_check 自动启用)", note))
        else:
            miss = [x for x, v in (("docx->pdf", d), ("pdf->png", p)) if not v]
            self.add("渲染", "render_check 选用后端", WARN, "无可用 %s 后端,第 7 步视觉校验无法执行" % "/".join(miss),
                     "按上方对应行的修复建议任装其一(首选 LibreOffice + poppler)")

    @staticmethod
    def _docx2pdf_present(rc, name):
        if name == "soffice":
            p = rc.find_soffice()
            return (True, p) if p else (False, "PATH/常见安装位置/CPW_SOFFICE 均未找到 soffice")
        if name == "word":
            if not IS_WIN:
                return False, "仅 Windows 可用"
            if not rc._importable("win32com"):
                return False, "未安装 pywin32(win32com)"
            if not rc.has_word_com():
                return False, "未注册 Word.Application(未装 Word)"
            srv = rc.word_com_server()
            who = "WPS 接管" if "wps" in srv.lower() else ("Microsoft Word" if "winword" in srv.lower() else "未知服务器")
            return True, "Word.Application -> %s(%s)+ pywin32" % (who, os.path.basename(srv.split(" /")[0]) or "?")
        if rc._importable("docx2pdf"):
            return True, "docx2pdf 包"
        return False, "未安装 docx2pdf 包"

    # -- 汇总 ---------------------------------------------------------------
    def run(self):
        try:
            self.check_python()
            self.check_packages()
            self.check_cjk()
            self.check_graphviz()
            self.check_render()
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)
        failed_required = [i for i in self.items if i["required"] and i["status"] == FAIL]
        return 1 if failed_required else 0


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def _w(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s, n):
    return s + " " * max(0, n - _w(s))


def print_table(doc, code):
    rows = [("状态", "类别", "检查项", "说明")]
    for i in doc.items:
        rows.append((i["status"] + ("*" if i["required"] else ""), i["category"], i["name"], i["detail"]))
    widths = [max(_w(r[k]) for r in rows) for k in range(3)]
    print("cnipa-integrated-circuit-layout-writer 环境体检(%s, Python %s%s)" % (platform.platform(terse=True),
                                                             platform.python_version(),
                                                             ", --quick" if doc.quick else ""))
    print("-" * 100)
    for n, r in enumerate(rows):
        print("  ".join(_pad(r[k], widths[k]) for k in range(3)) + "  " + r[3])
        if n == 0:
            print("-" * 100)
    print("-" * 100)
    print("(* = 必需项;WARN = 可选/降级;SKIP = 回退链中已有更靠前的可用后端)")
    fixes = [i for i in doc.items if i["fix"]]
    if fixes:
        print("\n修复建议:")
        for i in fixes:
            print("  [%s] %s:%s" % (i["status"], i["name"], i["fix"]))
    d, p = doc.selected["docx2pdf"], doc.selected["pdf2png"]
    print("\n渲染后端:docx->pdf = %s;pdf->png = %s" % (d or "无", p or "无"))
    cnt = {s: sum(1 for i in doc.items if i["status"] == s) for s in (PASS, WARN, FAIL, SKIP)}
    print("汇总:PASS %d / WARN %d / FAIL %d / SKIP %d -> %s" % (
        cnt[PASS], cnt[WARN], cnt[FAIL], cnt[SKIP], "必需项全部通过" if code == 0 else "有必需项 FAIL,请先修复"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="cnipa-integrated-circuit-layout-writer 环境体检(只检查,不安装,不联网)")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--quick", action="store_true", help="跳过真实转换/渲染探测,只查存在性")
    ap.add_argument("--all", action="store_true", help="回退链中每个后端都实测(默认找到可用者即停)")
    ap.add_argument("--intake", metavar="JSON", help="开工就绪清单(调用 session_intake.py check)")
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except Exception:
            pass
    if getattr(a, "intake", None):
        import session_intake as SI
        try:
            ready, issues = SI.check_file(a.intake)
        except Exception as e:
            print("ERROR intake:", type(e).__name__)
            return 1
        if ready:
            print("READY_FOR_LOCAL_WORK")
            return 0
        print("NOT_READY")
        for code, field, detail in issues:
            print("  %s  field=%s  %s" % (code, field, detail))
        return 2
    doc = Doctor(quick=a.quick, probe_all=a.all)
    code = doc.run()
    if a.json:
        print(json.dumps({"ok": code == 0, "exit_code": code, "quick": a.quick,
                          "platform": platform.platform(), "python": sys.executable,
                          "selected_backends": doc.selected, "items": doc.items},
                         ensure_ascii=False, indent=2))
    else:
        print_table(doc, code)
    return code


if __name__ == "__main__":
    sys.exit(main())
