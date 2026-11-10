# -*- coding: utf-8 -*-
"""布图设计登记内容/包装门禁（与具体项目无关；可配置）。

每个函数返回错误字符串列表（空 = 通过）。级别由调用方标 FAIL/WARN。

    from layout_gates import (plan_as_mask, unverified_signoff_claim,
                              catalog_tiff_mismatch, term_drift,
                              secret_claim_leak, zip_rules_from_namelist)

自检：python layout_gates.py --selftest

门禁口径：
- FAIL：无签核证据却声称已完成第三方 PDK DRC/LVS/流片，或把中心线示意图说成已签核掩膜。
- 不再 FAIL：未导入 foundry GDS 的原创分层图样未写「规划/示意」二字。
- ``has_real_mask``（已导入真实源图）不等于签核证据，不能单独放行 DRC/LVS/流片声明。
"""
from __future__ import annotations
import re
import sys

PLAN_MARKERS = ("规划", "示意", "planning", "schematic-only")
# 无 has_signoff_evidence 时命中即 FAIL。不用过于宽泛的「正式版图」，以免误伤「本布图设计之图样」。
SIGNOFF_CLAIMS = (
    "正式掩膜",
    "流片版图",
    "已签核掩膜",
    "tape-out",
    "tapeout",
    "signoff layout",
    "pdk signoff",
    "foundry signoff",
    "已完成DRC",
    "已完成 DRC",
    "已通过DRC",
    "已通过 DRC",
    "已完成LVS",
    "已完成 LVS",
    "已通过LVS",
    "已通过 LVS",
    "DRC/LVS 签核",
    "DRC/LVS签核",
    "已做 DRC/LVS",
    "PDK 签核",
    "PDK签核",
    "第三方 PDK 签核",
    "流片签核",
    "已流片",
    "已签核",
)
SECRET_CLAIMS = ("已作保密", "保密处理", "保密信息已去除", "confidential areas removed")


def _blob_of(meta: dict) -> str:
    return "\n".join(meta.get("texts") or []) + "\n" + "\n".join(meta.get("filenames") or [])


def _has_token(blob: str, token: str) -> bool:
    if token.isascii():
        return token.lower() in blob.lower()
    return token in blob


def unverified_signoff_claim(meta: dict) -> list:
    """meta: {has_signoff_evidence: bool, texts: [str], filenames: [str],
              require_plan_marker: bool=False, has_real_mask: bool}

    has_real_mask 仅表示已接入真实源图，不能替代签核证据。
    require_plan_marker 仅在调用方明确选择「中心线/示意占位包」时设为 True。
    """
    errs = []
    has_evidence = bool(meta.get("has_signoff_evidence"))
    blob = _blob_of(meta)
    if not has_evidence:
        seen = set()
        for m in SIGNOFF_CLAIMS:
            if _has_token(blob, m) and m not in seen:
                seen.add(m)
                errs.append(f"PLAN_AS_MASK: 无签核证据却声称「{m}」")
    if meta.get("require_plan_marker", False):
        if not any(_has_token(blob, m) for m in PLAN_MARKERS):
            errs.append("PLAN_AS_MASK: 已选择规划示意模式，但缺少「规划/示意」标记")
    return errs


def plan_as_mask(meta: dict) -> list:
    """兼容旧名。现为「无签核证据的签核声明」门禁；默认不再要求「规划」二字。"""
    return unverified_signoff_claim(meta)


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
            print("FAIL", msg)
            fails += 1
        else:
            print("PASS", msg)

    e = plan_as_mask({
        "has_signoff_evidence": False,
        "texts": ["正式掩膜已就绪"],
        "filenames": ["1.tiff"],
    })
    check(any("PLAN_AS_MASK" in x for x in e), "detect mask/signoff claim without evidence")

    e = plan_as_mask({
        "texts": ["已完成 DRC 与已通过 LVS，并已流片"],
        "filenames": ["1.tiff"],
    })
    check(any("PLAN_AS_MASK" in x for x in e), "detect DRC/LVS/tape-out claim without evidence")

    e = plan_as_mask({
        "has_real_mask": True,
        "has_signoff_evidence": False,
        "texts": ["PDK 签核已完成"],
        "filenames": ["1.tiff"],
    })
    check(any("PLAN_AS_MASK" in x for x in e), "foundry GDS alone does not waive signoff claims")

    e = plan_as_mask({
        "has_signoff_evidence": True,
        "texts": ["已完成 DRC，已通过 LVS，流片签核见附件"],
        "filenames": ["1.tiff"],
    })
    check(e == [], "signoff claims ok when evidence present")

    e = plan_as_mask({
        "texts": ["本页为规划示意"],
        "filenames": ["1.tiff"],
    })
    check(e == [], "planning marker still ok (no signoff claim)")

    e = plan_as_mask({
        "texts": ["本布图设计之图样：金属1层（真实线宽多边形）"],
        "filenames": ["1.tiff"],
    })
    check(e == [], "original drawings without 规划 and without signoff claims pass")

    e = plan_as_mask({
        "require_plan_marker": True,
        "texts": ["本布图设计之图样"],
        "filenames": ["1.tiff"],
    })
    check(any("规划/示意" in x for x in e), "opt-in planning mode still requires marker")

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
