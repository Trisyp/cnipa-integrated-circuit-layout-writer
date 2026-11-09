# -*- coding: utf-8 -*-
"""通用专利内容门禁（与具体专利无关；词表可配置）。

项目侧 audit 直接 import 调用，每个函数返回错误字符串列表（空列表 = 通过），由项目决定 FAIL/WARN：

    from patent_gates import (internal_wording, claim1_numbers, claim_structure,
                              untraceable_numbers, figure_first_ref_order)
    errs += internal_wording({"body": body, "claims": claims_all, "abstract": abstract})
    errs += claim1_numbers(claims[0])
    errs += claim_structure(claims)
    errs += untraceable_numbers(effects_text, embodiments_text)
    errs += figure_first_ref_order(embodiments_text)
    warns = background_leak(background, invention_terms, claim1=claims[0], summary=summary)  # 建议记 WARN 人工复核
    warns += cn_appno_scan(spec_text)                                                     # 申请号校验位
    warns += overclaim({"有益效果": effects, "背景技术": background})                      # 空口号 → WARN

门禁只输出文字结论（PASS/WARN/FAIL 由调用方决定），从不改写内容。
自检：python patent_gates.py --selftest
"""
import re
import sys

# 申请文本中不应出现的内部验证用语（仿真只在内部支撑数值）。项目可增删；
# 结构化输出正反例确需「场景一/二」小标题时，从项目词表中去掉这两项。
DEFAULT_INTERNAL_WORDS = ("仿真", "合成数据", "模拟数据", "场景一", "场景二", "场景三", "单线程", "随机种子0", "个种子")
# 「种子」单独出现也拦，但先剔除技术术语用法（可配置）。
DEFAULT_SEED_ALLOW = ("共享随机种子", "随机种子生成", "按随机种子")

_CLAIM_NO = re.compile(r"^\s*(\d+)\s*[.．、]")
_REF = re.compile(r"权利要求\s*(\d+)(?:\s*(?:至|-|～|~)\s*(\d+))?")


def internal_wording(texts, words=DEFAULT_INTERNAL_WORDS, seed_allow=DEFAULT_SEED_ALLOW, seed_word="种子"):
    """texts: {名称: 文本}。返回命中的内部验证用语。"""
    errs = []
    for name, txt in texts.items():
        txt = txt or ""
        for w in words:
            if w in txt:
                errs.append(f"internal-validation wording in {name}: {w}")
        if seed_word:
            rest = txt
            for a in seed_allow:
                rest = rest.replace(a, "")
            if seed_word in rest:
                errs.append(f"internal-validation wording in {name}: {seed_word}")
    return errs


def claim1_numbers(claim1, pattern=r"(?<![A-Za-z0-9])(?:\d+\.\d+|\d+(?:\.\d+)?\s*[%％])"):
    """权1 不得带具体小数或百分数（阈值只进实施例）。步骤号、式号中的整数不拦。"""
    hits = re.findall(pattern, claim1 or "")
    return [f"claim1 carries embodiment value: {h}" for h in hits]


def claim_structure(claims, independent=(1,), system_kw="系统", medium_kw="存储介质", max_free=10):
    """检查编号连续、引用只指向在前的权利要求、方法从属只引独立权利要求、
    系统/介质权引用范围覆盖其前的全部方法权利要求。返回 (errs) ；超过 max_free 项给出提示项。"""
    errs = []
    nums = []
    for i, c in enumerate(claims, start=1):
        m = _CLAIM_NO.match(c or "")
        if not m or int(m.group(1)) != i:
            errs.append(f"claim numbering broken at {i}")
        nums.append(i)
    sys_idx = [i for i, c in enumerate(claims, start=1) if system_kw in (c or "")[:60] and "用于执行" in (c or "")]
    med_idx = [i for i, c in enumerate(claims, start=1) if medium_kw in (c or "")[:60]]
    first_other = min(sys_idx + med_idx) if (sys_idx or med_idx) else len(claims) + 1
    last_method = first_other - 1
    for i, c in enumerate(claims, start=1):
        refs = []
        for a, b in _REF.findall(c or ""):
            refs.append((int(a), int(b) if b else int(a)))
        for a, b in refs:
            if b >= i or a >= i:
                errs.append(f"claim{i} cites non-preceding claim {a}-{b}")
        if 1 < i <= last_method and i not in independent:
            if not refs:
                errs.append(f"claim{i} has no parent reference")
            elif any(not (a in independent and b in independent) for a, b in refs):
                errs.append(f"claim{i} not only dependent on independent claim(s) {independent}")
        if i in sys_idx or i in med_idx:
            if (1, last_method) not in refs:
                errs.append(f"claim{i} must cite 1至{last_method}")
    if len(claims) > max_free:
        errs.append(f"NOTICE: {len(claims)} claims > {max_free}, extra-claim fee applies (confirm with user)")
    return errs


def untraceable_numbers(effects, embodiments, pattern=r"[−-]?\d+\.\d+|\d+(?:\.\d+)?[%％]"):
    """有益效果中的数字须能在实施例中找到。"""
    out = []
    for n in sorted(set(re.findall(pattern, effects or ""))):
        if n not in (embodiments or ""):
            out.append(f"effect number not traceable to embodiments: {n}")
    return out


def figure_first_ref_order(text, pattern=r"参见图(\d+)"):
    """具体实施方式中图号首次引用须为 1、2、3…"""
    seen = []
    for m in re.finditer(pattern, text or ""):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    if seen and seen != list(range(1, len(seen) + 1)):
        return ["figure first-reference order: " + ",".join(map(str, seen))]
    return []


# ---------------- 背景禁写本发明（原则 15）：只报告，建议记 WARN 人工复核 ----------------
DEFAULT_SELF_REF = ("本发明", "本方案", "本申请", "本技术方案", "本公开", "本实施例")
# 收束句预告解法：「如何以/通过/利用〔手段〕……」
_CLOSING_SOLUTION = re.compile(r"如何(?:以|通过|利用|采用|借助|基于)")
# 两边共有时不计入重叠的套话（项目可追加）
DEFAULT_LEAK_ALLOW = ("亟待解决的技术问题", "为克服上述问题与缺陷", "其特征在于", "包括以下步骤",
                      "根据权利要求", "所述方法")
_LEAK_PUNCT = re.compile(r"[\s，。；：、,.;:（）()“”\"'《》【】\[\]！？!?—…\-]+")


def background_leak(background, invention_terms=(), claim1="", summary="", ngram=10,
                    allow=DEFAULT_LEAK_ALLOW, self_ref=DEFAULT_SELF_REF, max_spans=5):
    """背景技术疑似写入本发明：自指用语、本发明术语表词、收束句预告解法、与权1/发明内容的长片段重叠。

    invention_terms：本发明独有术语（术语表中现有技术不用的词）；allow：两边共有也不算泄漏的套话。
    返回提示列表（空 = 未发现）。这是启发式检查，建议调用方记 WARN 由人工按原则 15 判断。
    """
    bg = background or ""
    errs = []
    for w in self_ref:
        if w in bg:
            errs.append(f"background mentions the invention itself: {w}")
    for t in invention_terms or ():
        t = (t or "").strip()
        if t and t not in (allow or ()) and t in bg:
            errs.append(f"background uses invention term: {t}")
    if _CLOSING_SOLUTION.search(bg):
        errs.append("background closing sentence previews a solution: 如何以/通过……")
    if ngram and (claim1 or summary):
        def clean(x):
            x = x or ""
            for a in allow or ():
                x = x.replace(a, "\u0000")
            return _LEAK_PUNCT.sub("", x)
        grams = set()
        for src in (claim1, summary):
            c = clean(src)
            for i in range(len(c) - ngram + 1):
                g = c[i:i + ngram]
                if "\u0000" not in g:
                    grams.add(g)
        b = clean(bg)
        cover = [False] * len(b)
        for j in range(len(b) - ngram + 1):
            if b[j:j + ngram] in grams:
                for k in range(j, j + ngram):
                    cover[k] = True
        spans, j = [], 0
        while j < len(b):
            if cover[j]:
                k = j
                while k < len(b) and cover[k]:
                    k += 1
                spans.append(b[j:k])
                j = k
            else:
                j += 1
        for n, sp in enumerate(spans[:max_spans], start=1):
            # report minimization: length+index only
            errs.append(f"background shares {len(sp)}-char span with claim1/summary (span#{n})")
        if len(spans) > max_spans:
            errs.append(f"background shares {len(spans) - max_spans} more span(s) with claim1/summary")
    return errs



# ---------------- overclaim / slogans (writing-style sec.6; WARN only) ----------------
DEFAULT_OVERCLAIM = (
    "填补空白", "具有重要意义", "越来越好", "通常情况下", "一般而言",
    "显著提升", "大幅提高", "彻底解决", "完美解决", "业界领先",
    "前所未有", "革命性", "颠覆性", "巨大突破",
)
_OVERCLAIM_AS_DEVELOP = re.compile(r"随着[^，。；\n]{0,40}的发展")


def overclaim(texts, phrases=DEFAULT_OVERCLAIM, as_develop=True):
    """texts: {section: text}. Return WARN list; caller must not FAIL."""
    errs = []
    for name, txt in (texts or {}).items():
        txt = txt or ""
        for w in phrases or ():
            if w and w in txt:
                errs.append(f"overclaim slogan in {name}: {w}")
        if as_develop and _OVERCLAIM_AS_DEVELOP.search(txt):
            errs.append(f"overclaim pattern in {name}: 随着…的发展")
    return errs


# ---------------- 中国专利申请号校验位（confidentiality-and-review.md 第三节） ----------------
def cn_appno_checkdigit(digits):
    """前 12 位（或旧 8 位）按权 2–9 循环加权求和 mod 11，余 10 记 X。"""
    s = sum(int(d) * (2 + i % 8) for i, d in enumerate(digits))
    r = s % 11
    return "X" if r == 10 else str(r)


def cn_appno_check(number):
    """校验单个申请号（可带 CN/ZL 前缀、小数点与空格）。返回错误列表。"""
    raw = number or ""
    n = re.sub(r"[\s.．]", "", raw.upper())
    n = re.sub(r"^(?:CN|ZL)", "", n)
    if not re.fullmatch(r"\d{12}[0-9X]|\d{8}[0-9X]", n):
        return [f"application number malformed: {raw}"]
    exp = cn_appno_checkdigit(n[:-1])
    if n[-1] != exp:
        return [f"application number check digit wrong: {raw} (expected .{exp})"]
    return []


_APPNO_CTX = re.compile(r"申请号\s*(?:为|是|：|:)?\s*((?:CN|ZL)?\s*\d{8,12}\s*[.．]?\s*[0-9Xx])")
_APPNO_DOT = re.compile(r"(?<![\dA-Za-z])((?:CN|ZL)?\d{12}[.．][0-9Xx])(?![\dA-Za-z])")


def cn_appno_scan(text):
    """扫描文本中的申请号（「申请号为……」上下文或 12 位+点+校验位形式）并逐个校验。公开号（CN…A/B）不在此列。"""
    found = []
    for rx in (_APPNO_CTX, _APPNO_DOT):
        for m in rx.finditer(text or ""):
            v = m.group(1).strip()
            key = re.sub(r"[\s.．]", "", v.upper())
            if key not in [re.sub(r"[\s.．]", "", f.upper()) for f in found]:
                found.append(v)
    errs = []
    for v in found:
        errs += cn_appno_check(v)
    return errs


def _selftest():
    ok = []
    good = ["1.一种方法，其特征在于，包括步骤S1……超过预设门限……",
            "2.根据权利要求1所述的方法，其特征在于，……",
            "3.根据权利要求1所述的方法，其特征在于，……",
            "4.一种系统，用于执行如权利要求1至3任一项所述的方法，其特征在于，包括……",
            "5.一种计算机可读存储介质，……实现如权利要求1至3任一项所述的方法。"]
    ok.append(("structure good", claim_structure(good) == []))
    bad = list(good)
    bad[2] = "3.根据权利要求2所述的方法，其特征在于，……"
    bad[3] = bad[3].replace("1至3", "1至2")
    e = claim_structure(bad)
    ok.append(("structure bad", any("claim3 not only" in x for x in e) and any("claim4 must cite" in x for x in e)))
    ok.append(("numbering", any("numbering" in x for x in claim_structure(good[:2] + good[3:]))))
    ok.append(("fee notice", any("NOTICE" in x for x in claim_structure([f"{i}.根据权利要求1所述的方法" if i > 1 else "1.一种方法" for i in range(1, 12)]))))
    ok.append(("short list no crash", isinstance(claim_structure([]), list)))
    ok.append(("claim1 clean", claim1_numbers("步骤S410：……超过预设门限时，按式(3)……") == []))
    ok.append(("claim1 decimal", len(claim1_numbers("……门限取0.8……占80%……")) == 2))
    ok.append(("wording clean", internal_wording({"body": "由簇内共享随机种子生成。在一个具体实施例中……"}) == []))
    ok.append(("wording hit", len(internal_wording({"body": "仿真条件：场景一，种子0–9"})) >= 3))
    ok.append(("trace", untraceable_numbers("误差为0.080，降为12%", "……0.080……") == ["effect number not traceable to embodiments: 12%"]))
    ok.append(("fig order ok", figure_first_ref_order("参见图1……参见图2……参见图1") == []))
    ok.append(("fig order bad", figure_first_ref_order("参见图1……参见图3……参见图2") != []))
    # background_leak：正例（只写现有技术）与反例（自指、术语、预告解法、长片段重叠）
    c1 = "1.一种方法，其特征在于，包括：按历史稳定度确定各采集单元权重并计算加权融合值；"
    bg_ok = "现有做法采用算术平均合成读数，对个别偏离读数敏感。因此，如何区分单点偏离与整体变化，是当前亟待解决的技术问题。"
    ok.append(("leak clean", background_leak(bg_ok, ["加权融合值"], claim1=c1) == []))
    ok.append(("leak self-ref", any("itself" in x for x in background_leak("本发明采用加权方式。"))))
    ok.append(("leak term", any("invention term" in x for x in background_leak("现有做法未计算加权融合值。", ["加权融合值"]))))
    ok.append(("leak closing", any("previews" in x for x in background_leak("因此，如何以权重区分偏离，是问题。"))))
    ok.append(("leak span", any("span" in x for x in background_leak("现有做法未按历史稳定度确定各采集单元权重。", claim1=c1))))
    ok.append(("leak allow", background_leak("亟待解决的技术问题。", claim1="……亟待解决的技术问题……") == []))
    # cn_appno：正确校验位 / 错误校验位 / 格式错误 / X 校验位 / 文本扫描
    ok.append(("appno ok", cn_appno_check("200310102344.5") == []))
    ok.append(("appno bad digit", any("check digit" in x for x in cn_appno_check("200310102344.6"))))
    ok.append(("appno malformed", any("malformed" in x for x in cn_appno_check("20031010234.5"))))
    xnum = next(f"{n:012d}" for n in range(202310000000, 202310000200) if cn_appno_checkdigit(f"{n:012d}") == "X")
    ok.append(("appno X", cn_appno_check(xnum + ".X") == [] and cn_appno_check(xnum + ".0") != []))
    ok.append(("appno scan", len(cn_appno_scan("申请号为CN200310102344.6的申请；公开号为CN1234567A；另见200310102344.5")) == 1))
    ok.append(("overclaim clean", overclaim({"有益效果": "通过加权融合，平均偏差降低。"}) == []))
    ok.append(("overclaim slogan", any("填补空白" in x for x in overclaim({"有益效果": "本发明填补空白，具有重要意义。"}))))
    ok.append(("overclaim as-develop", any("随着" in x for x in overclaim({"背景技术": "随着物联网的发展，读数越来越多。"}))))
    leak_msgs = background_leak("现有做法未按历史稳定度确定各采集单元权重。", claim1=c1)
    ok.append(("leak span no prose echo", any("span#" in x for x in leak_msgs) and all("按历史稳定度确定各采集" not in x for x in leak_msgs)))
    for name, r in ok:
        print(("PASS " if r else "FAIL ") + name)
    return all(r for _, r in ok)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    print(__doc__)
