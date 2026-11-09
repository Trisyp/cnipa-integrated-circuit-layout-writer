# -*- coding: utf-8 -*-
"""布图设计登记内容/包装门禁（与具体项目无关；可配置）。

每个函数返回错误字符串列表（空 = 通过）。级别由调用方标 FAIL/WARN。

    from layout_gates import (plan_as_mask, catalog_tiff_mismatch, term_drift,
                              secret_claim_leak, zip_rules_from_namelist)

自检：python layout_gates.py --selftest
"""
from __future__ import annotations
import re
import sys

PLAN_MARKERS = ("规划", "示意", "planning", "schematic-only")
MASK_CLAIMS = ("正式掩膜", "流片版图", "tape-out", "signoff layout", "正式版图")
SECRET_CLAIMS = ("已作保密", "保密处理", "保密信息已去除", "confidential areas removed")


def plan_as_mask(meta: dict) -> list:
    """meta: {has_real_mask: bool, texts: [str], filenames: [str]}"""
    errs = []
    has_real = bool(meta.get("has_real_mask"))
    blob = "\n".join(meta.get("texts") or []) + "\n" + "\n".join(meta.get("filenames") or [])
    if has_real:
        return errs
    for m in MASK_CLAIMS:
        if m.lower() in blob.lower() if m.isascii() else m in blob:
            errs.append(f"PLAN_AS_MASK: 无真实掩膜源却出现「{m}」")
    # also require at least one planning marker somewhere when not real
    if meta.get("require_plan_marker", True):
        if not any(m in blob for m in PLAN_MARKERS):
            errs.append("PLAN_AS_MASK: 规划模式缺少「规划/示意」标记")
    return errs


def catalog_tiff_mismatch(catalog_pages: list, tiff_names: list) -> list:
    """catalog_pages: ordered page labels; tiff_names: e.g. ['1.tiff','2.tiff']."""
    errs = []
    n_cat = len(catalog_pages)
    n_tif = len(tiff_names)
    if n_cat != n_tif:
        errs.append(f"CATALOG_TIFF_MISMATCH: 目录页数 {n_cat} ≠ TIFF 数 {n_tif}")
    nums = []
    for name in tiff_names:
        m = re.match(r"^(\d+)\.(tiff|tif)$", name, re.I)
        if not m:
            errs.append(f"ZIP_NAME_GAP: 非法图样名 «{name}»（需要 N.tiff/tif）")
        else:
            nums.append(int(m.group(1)))
    if nums:
        nums_sorted = sorted(nums)
        expect = list(range(1, len(nums_sorted) + 1))
        if nums_sorted != expect:
            errs.append(f"ZIP_NAME_GAP: 编号不连续 {nums_sorted}，期望 {expect}")
        if nums != nums_sorted:
            errs.append("ZIP_NAME_GAP: TIFF 列表未按编号排序")
    return errs


def term_drift(layer_table: list, *text_blobs: str) -> list:
    """layer_table: list of canonical layer names; each must appear or be aliased."""
    errs = []
    if not layer_table:
        return errs
    blob = "\n".join(text_blobs)
    for name in layer_table:
        if name and name not in blob:
            errs.append(f"TERM_DRIFT: 层表名称「{name}」未出现在目录/说明/页题文本中")
    return errs


def secret_claim_leak(claims_secret: bool, public_text: str, uncovered_hint: bool = False) -> list:
    """If claiming secrecy but public text still looks detailed or uncovered_hint."""
    errs = []
    if not claims_secret:
        return errs
    for c in SECRET_CLAIMS:
        if c in (public_text or ""):
            # claiming is ok; leak if uncovered
            break
    if uncovered_hint:
        errs.append("SECRET_CLAIM_LEAK: 声称保密但公开图样/说明仍暴露拟保密细节（人工复核）")
    return errs


def zip_rules_from_namelist(namelist: list, max_bytes: int | None = None, limit=150 * 1024 * 1024) -> list:
    """namelist: ZipFile.namelist(); max_bytes: archive size."""
    errs = []
    for n in namelist:
        if n.endswith("/") or "/" in n.replace("\\", "/").rstrip("/"):
            # directory entry or nested path
            if n.endswith("/") or "/" in n.replace("\\", "/"):
                errs.append(f"ZIP_HAS_FOLDER: ZIP 内含目录或子路径 «{n}»")
                break
    if max_bytes is not None and max_bytes > limit:
        errs.append(f"ZIP_TOO_BIG: 单包 {max_bytes} bytes > {limit}")
    return errs


def _selftest() -> int:
    fails = 0
    def check(cond, msg):
        nonlocal fails
        if not cond:
            print("FAIL", msg); fails += 1
        else:
            print("PASS", msg)

    e = plan_as_mask({"has_real_mask": False, "texts": ["正式掩膜已就绪"], "filenames": ["1.tiff"], "require_plan_marker": False})
    check(any("PLAN_AS_MASK" in x for x in e), "detect mask claim without real source")

    e = plan_as_mask({"has_real_mask": False, "texts": ["本页为规划示意"], "filenames": ["1.tiff"]})
    check(e == [], "planning marker ok")

    e = catalog_tiff_mismatch(["总图", "M1"], ["1.tiff", "3.tiff"])
    check(any("ZIP_NAME_GAP" in x or "CATALOG" in x for x in e), "gap/mismatch detected")

    e = catalog_tiff_mismatch(["总图", "POLY"], ["1.tiff", "2.tiff"])
    check(e == [], "catalog match")

    e = zip_rules_from_namelist(["figs/1.tiff"])
    check(any("ZIP_HAS_FOLDER" in x for x in e), "folder detected")

    e = zip_rules_from_namelist(["1.tiff", "2.tiff"], max_bytes=10)
    check(e == [], "flat zip ok")

    e = secret_claim_leak(True, "已作保密处理", uncovered_hint=True)
    check(any("SECRET_CLAIM_LEAK" in x for x in e), "secret leak warn")

    print("selftest failures:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("usage: python layout_gates.py --selftest")
