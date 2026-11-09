# -*- coding: utf-8 -*-
"""render_check.py — 把 docx 渲染成逐页 PNG,供"可视化校验"(结构正确≠视觉正确)。

依赖(一般需 sudo apt):
    libreoffice-writer  (提供 soffice,docx->pdf)
    poppler-utils       (提供 pdftoppm,pdf->png)
    中文字体            (fonts-noto-cjk,或把宋体/黑体放 ~/.fonts 后 fc-cache -f;否则渲染中文豆腐)

用法:
    python render_check.py 成稿.docx [输出目录] [dpi]
然后用 Read 逐页查看输出目录里的 pg-*.png,核对:
    - 四个运行页眉(说明书摘要/权利要求书/说明书/说明书附图)是否分别正确;权要/说明书页码各自从 1 重起;
    - （门禁提示）本脚本只做视觉渲染；内容一致性 audit（三处同源/禁词/式号本体/符号一名多义）
      应由项目侧 audit 脚本在 build 末尾强制跑；render_check PASS ≠ 内容 audit PASS；
    - **发明名称(黑体居中标题)逐字无豆腐块**——套模板时模板内嵌的字体子集只含原文字形,本专利的新字会变 □;
      这是最易漏的一处(别只盯配图和正文宋体),务必看清说明书首页那行黑体发明名称的每个字;
    - 正文宋体/两端对齐/首行缩进/行距;章节标题加粗;发明名称居中且仅一次;
    - 配图清晰、居中、不越右边距、中文无豆腐、图号正确;
    - 分页无标题孤行、图被截断。

后端回退(仅当主路径不可用时才启用;soffice 与 pdftoppm 都在 PATH 上时行为与旧版完全一致):
    docx->pdf: soffice(PATH) -> soffice(常见安装位置/环境变量 CPW_SOFFICE,临时可写 profile)
               -> Microsoft Word COM(Windows,需 pywin32) -> docx2pdf 包
    pdf->png : pdftoppm -> PyMuPDF(fitz)
    环境变量 CPW_DOCX2PDF_ORDER / CPW_PDF2PNG_ORDER 可重排(如 "word,soffice"、"fitz,pdftoppm");
    先跑 `python scripts/doctor.py` 看哪个后端实际可用。
"""
import os
import sys
import glob
import shutil
import subprocess
import tempfile
import pathlib

# ---------------------------------------------------------------------------
# 后端回退链(有序列表,第一个可用者胜出;重排列表即切换后端)
# ---------------------------------------------------------------------------
DOCX2PDF_ORDER = ["soffice", "word", "docx2pdf"]
PDF2PNG_ORDER = ["pdftoppm", "fitz"]


def _order(env_name, default):
    v = os.environ.get(env_name, "").strip()
    if not v:
        return list(default)
    picked = [x.strip().lower() for x in v.split(",") if x.strip().lower() in default]
    return picked + [x for x in default if x not in picked]


def find_soffice():
    """先查 PATH,再查环境变量 CPW_SOFFICE 与常见安装位置;找不到返回 None。"""
    for name in ("soffice", "soffice.com", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    cands = [os.environ.get("CPW_SOFFICE", "")]
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            cands += [os.path.join(base, "LibreOffice", "program", "soffice.com"),
                      os.path.join(base, "LibreOffice", "program", "soffice.exe")]
    else:
        cands += ["/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice",
                  "/Applications/LibreOffice.app/Contents/MacOS/soffice", "/snap/bin/libreoffice"]
        cands += sorted(glob.glob("/opt/libreoffice*/program/soffice"))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def _importable(mod):
    try:
        import importlib.util
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def has_word_com():
    """Windows + pywin32 + 注册了 Word.Application 才算候选(真正可用与否由转换结果决定)。"""
    if os.name != "nt" or not _importable("win32com"):
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"))
        return True
    except Exception:
        return False


def word_com_server():
    """返回 Word.Application 实际注册的 COM 服务器路径(可能是 WINWORD.EXE,也可能是 WPS 的 wps.exe)。"""
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID") as k:
            clsid = winreg.QueryValue(k, None)
        for sub in (r"CLSID\%s\LocalServer32", r"WOW6432Node\CLSID\%s\LocalServer32"):
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, sub % clsid) as k:
                    v = winreg.QueryValue(k, None)
                    if v:
                        return v
            except OSError:
                pass
    except Exception:
        pass
    return ""


def docx_to_pdf_soffice(docx_path, out_dir, soffice, timeout=180):
    """用独立的临时可写 profile 跑 headless 转换(避免无写权限/与已开 LibreOffice 冲突)。"""
    prof = tempfile.mkdtemp(prefix="cpw_lo_profile_")
    try:
        uri = pathlib.Path(prof).as_uri()
        subprocess.run([soffice, "-env:UserInstallation=" + uri, "--headless", "--norestore",
                        "--convert-to", "pdf", "--outdir", out_dir, docx_path],
                       check=True, capture_output=True, timeout=timeout)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    pdf = os.path.join(out_dir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
    if not os.path.isfile(pdf):
        raise RuntimeError("soffice 未生成 PDF。")
    return pdf


_WORD_SNIPPET = r"""
import sys, pythoncom, win32com.client
src, dst = sys.argv[1], sys.argv[2]
pythoncom.CoInitialize()
word = win32com.client.DispatchEx("Word.Application")  # 独立实例,不碰用户已开的 Word
try:
    word.Visible = False
    word.DisplayAlerts = 0
    doc = word.Documents.Open(src, False, True, False)  # ConfirmConversions, ReadOnly, AddToRecentFiles
    try:
        try:
            doc.ExportAsFixedFormat(dst, 17)
        except Exception:
            doc.SaveAs(dst, 17)
    finally:
        doc.Close(0)
finally:
    word.Quit()
"""


def docx_to_pdf_word(docx_path, pdf_path, timeout=180, retries=1):
    """Word COM 在子进程里跑(可超时),只关闭本次新建的 Word 实例;偶发 RPC 失败时稍等重试一次。"""
    import time
    for attempt in range(retries + 1):
        try:
            subprocess.run([sys.executable, "-c", _WORD_SNIPPET, docx_path, pdf_path],
                           check=True, capture_output=True, timeout=timeout)
            break
        except subprocess.CalledProcessError:
            if attempt >= retries:
                raise
            time.sleep(3)
    if not os.path.isfile(pdf_path):
        raise RuntimeError("Word COM 未生成 PDF。")
    return pdf_path


def docx_to_pdf_docx2pdf(docx_path, pdf_path, timeout=180):
    code = "import sys; from docx2pdf import convert; convert(sys.argv[1], sys.argv[2])"
    subprocess.run([sys.executable, "-c", code, docx_path, pdf_path],
                   check=True, capture_output=True, timeout=timeout)
    if not os.path.isfile(pdf_path):
        raise RuntimeError("docx2pdf 未生成 PDF。")
    return pdf_path


def pdf_to_png_fitz(pdf, prefix, dpi):
    """PyMuPDF 回退;文件名与 pdftoppm 一致(pg-1.png / pg-01.png ...)。"""
    import fitz  # PyMuPDF
    out = []
    with fitz.open(pdf) as doc:
        w = len(str(doc.page_count))
        for i, page in enumerate(doc, 1):
            p = "%s-%0*d.png" % (prefix, w, i)
            page.get_pixmap(dpi=dpi).save(p)
            out.append(p)
    return out


def docx2pdf_candidates():
    """按顺序返回 [(后端名, 可调用 or 路径)],仅包含"看起来装了"的后端。"""
    out = []
    for name in _order("CPW_DOCX2PDF_ORDER", DOCX2PDF_ORDER):
        if name == "soffice":
            p = find_soffice()
            if p:
                out.append(("soffice", p))
        elif name == "word" and has_word_com():
            out.append(("word", None))
        elif name == "docx2pdf" and _importable("docx2pdf"):
            out.append(("docx2pdf", None))
    return out


def pdf2png_candidates():
    out = []
    for name in _order("CPW_PDF2PNG_ORDER", PDF2PNG_ORDER):
        if name == "pdftoppm" and shutil.which("pdftoppm"):
            out.append("pdftoppm")
        elif name == "fitz" and _importable("fitz"):
            out.append("fitz")
    return out


def _render_fallback(docx_path, out_dir, dpi):
    """主路径(PATH 上的 soffice + pdftoppm)缺失时的回退实现。"""
    d2p = docx2pdf_candidates()
    p2p = pdf2png_candidates()
    if not d2p:
        raise RuntimeError("缺 docx->pdf 后端:请装 LibreOffice(soffice),或在 Windows 上装 Word + pywin32 / "
                           "docx2pdf。运行 python scripts/doctor.py 查看修复建议。")
    if not p2p:
        raise RuntimeError("缺 pdf->png 后端:请装 poppler(pdftoppm)或 pip install PyMuPDF。"
                           "运行 python scripts/doctor.py 查看修复建议。")
    pdf, errs = None, []
    target = os.path.join(out_dir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
    for name, extra in d2p:
        try:
            if name == "soffice":
                pdf = docx_to_pdf_soffice(docx_path, out_dir, extra)
            elif name == "word":
                pdf = docx_to_pdf_word(docx_path, target)
            else:
                pdf = docx_to_pdf_docx2pdf(docx_path, target)
            print("docx->pdf 后端:", name)
            break
        except Exception as e:  # 当前后端失败 -> 试下一个
            errs.append("%s: %s" % (name, e))
    if pdf is None:
        raise RuntimeError("所有 docx->pdf 后端均失败:\n  " + "\n  ".join(errs))
    prefix = os.path.join(out_dir, "pg")
    for name in p2p:
        try:
            if name == "pdftoppm":
                subprocess.run(["pdftoppm", "-png", "-r", str(dpi), pdf, prefix],
                               check=True, capture_output=True, timeout=180)
            else:
                pdf_to_png_fitz(pdf, prefix, dpi)
            print("pdf->png 后端:", name)
            break
        except Exception as e:
            errs.append("%s: %s" % (name, e))
    else:
        raise RuntimeError("所有 pdf->png 后端均失败:\n  " + "\n  ".join(errs))
    return pdf


def render(docx_path, out_dir=None, dpi=110):
    docx_path = os.path.abspath(docx_path)
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(docx_path), "_render")
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    primary = (shutil.which("soffice") and shutil.which("pdftoppm")
               and not os.environ.get("CPW_DOCX2PDF_ORDER") and not os.environ.get("CPW_PDF2PNG_ORDER"))
    if not primary:
        # 主路径不可用(或用户重排了后端顺序)-> 走有序回退链
        if shutil.which("fc-cache"):
            subprocess.run(["fc-cache", "-f"], capture_output=True)
        pdf = _render_fallback(docx_path, out_dir, dpi)
    else:
        # 刷新字体缓存(若用户刚拷入字体)
        if shutil.which("fc-cache"):
            subprocess.run(["fc-cache", "-f"], capture_output=True)
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", out_dir, docx_path],
                       check=True, capture_output=True, timeout=180)
        pdfs = glob.glob(os.path.join(out_dir, "*.pdf"))
        if not pdfs:
            raise RuntimeError("soffice 未生成 PDF。")
        pdf = pdfs[0]
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), pdf, os.path.join(out_dir, "pg")],
                       check=True, capture_output=True, timeout=180)
    pages = sorted(glob.glob(os.path.join(out_dir, "pg-*.png")))
    print("PDF:", pdf)
    print("页数:", len(pages))
    for p in pages:
        print(" ", p)
    print("\n→ 现在请用 Read 逐页查看上述 PNG,按 docstring 清单核对版式/页眉/配图/分页。")
    return pages


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    render(sys.argv[1],
           sys.argv[2] if len(sys.argv) > 2 else None,
           int(sys.argv[3]) if len(sys.argv) > 3 else 110)
