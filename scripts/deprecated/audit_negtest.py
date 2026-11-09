# -*- coding: utf-8 -*-
"""audit_negtest.py — 反测注入模板（与具体专利无关）。

目的：避免「注入串已不在正文里，反测却假 PASS」。每案先确认探针子串仍在源文件中，
再跑 audit 期望非零；全部反测结束后清空注入，再跑一次干净 audit 期望为零。

库用法（项目 audit 或独立 runner）::

    from audit_negtest import NegCase, run_env_suite, run_suite, replace_once

    cases = [
        NegCase("medium", probes=[("content_p7.py", "1至10")], description="介质引用范围写错"),
        NegCase("c10", probes=[("content_p7.py", "有效时间裕度")]),
    ]
    rep = run_env_suite(
        audit_cmd=[sys.executable, "audit_consistency.py"],
        cases=cases,
        cwd=项目根,
        env_key="AUDIT_NEG",
    )
    sys.exit(0 if rep.ok else 1)

项目 audit_consistency.py 顶部按环境变量改内存中的 CLAIMS/BODY（与 patent7 相同）；
本工具负责编排、探针失效检测与干净轮次。

也可纯回调（单进程，适合自检与不方便子进程的场景）::

    def apply():
        return replace_once(box, "old", "new")  # True=确实改到
    def audit():
        return 1 if "bad" in box["t"] else 0
    run_suite([NegCase("x", apply=apply)], run_audit=audit, restore=lambda: box.__setitem__("t", orig))

CLI::

    python audit_negtest.py --selftest
    python audit_negtest.py --cwd DIR --audit "python audit_consistency.py" --cases cases.json

cases.json 每项: {"id", "probes": [["rel/path", "substring"], ...], "env_value"?, "description"?}

不联网。仅标准库。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple


@dataclass
class NegCase:
    """一条反测。

    - probes: 跑前必须全部命中的 (路径, 子串)。路径相对 cwd 或绝对路径。缺一即 STALE。
    - apply: 可选；返回 True 表示内存注入确实改到了目标（回调模式）。
    - env_value: 子进程模式写入环境变量的值，默认等于 id。
    """
    id: str
    probes: Sequence[Tuple[str, str]] = field(default_factory=tuple)
    apply: Optional[Callable[[], bool]] = None
    env_value: Optional[str] = None
    description: str = ""

    def env(self) -> str:
        return self.env_value if self.env_value is not None else self.id


@dataclass
class CaseResult:
    id: str
    status: str  # PASS | FAIL | STALE
    detail: str = ""


@dataclass
class NegReport:
    results: List[CaseResult]
    clean_ok: Optional[bool] = None
    clean_detail: str = ""

    @property
    def ok(self) -> bool:
        if any(r.status != "PASS" for r in self.results):
            return False
        if self.clean_ok is False:
            return False
        return True

    def summary_lines(self) -> List[str]:
        lines = []
        for r in self.results:
            lines.append(f"{r.status}  neg:{r.id}" + (f"  ({r.detail})" if r.detail else ""))
        if self.clean_ok is not None:
            tag = "PASS" if self.clean_ok else "FAIL"
            lines.append(f"{tag}  clean-audit" + (f"  ({self.clean_detail})" if self.clean_detail else ""))
        lines.append(f"audit_negtest: {'PASS' if self.ok else 'FAIL'}  ({sum(1 for r in self.results if r.status=='PASS')}/{len(self.results)} cases)")
        return lines


def replace_once(container: dict, key: str, old: str, new: str) -> bool:
    """就地替换 container[key] 中第一个 old→new；old 不存在返回 False。"""
    text = container.get(key) or ""
    if old not in text:
        return False
    container[key] = text.replace(old, new, 1)
    return True


def check_probes(probes: Sequence[Tuple[str, str]], cwd: Path) -> Optional[str]:
    """全部命中返回 None，否则返回失败说明。"""
    missing = []
    for rel, needle in probes:
        path = Path(rel)
        if not path.is_absolute():
            path = cwd / path
        if not path.is_file():
            missing.append(f"missing file {path}")
            continue
        try:
            txt = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            txt = path.read_text(encoding="utf-8-sig")
        if needle not in txt:
            missing.append(f"{path.name!s}: probe not found: {needle[:60]!r}")
    if missing:
        return "; ".join(missing)
    return None


def run_suite(
    cases: Sequence[NegCase],
    run_audit: Callable[[], int],
    restore: Callable[[], None],
    *,
    require_clean_pass: bool = True,
    cwd: Optional[Path] = None,
) -> NegReport:
    """回调模式：每案 apply（须返回 True）→ audit 非 0 → restore；最后可选干净 audit 为 0。

    若 case.probes 非空，先按 cwd（默认 cwd=.）做探针检查。
    """
    root = Path(cwd) if cwd else Path.cwd()
    results: List[CaseResult] = []
    for case in cases:
        if case.probes:
            stale = check_probes(case.probes, root)
            if stale:
                results.append(CaseResult(case.id, "STALE", stale))
                continue
        if case.apply is None:
            results.append(CaseResult(case.id, "FAIL", "no apply() in callback mode"))
            continue
        try:
            applied = bool(case.apply())
        except Exception as e:  # noqa: BLE001 — 报告给调用方
            restore()
            results.append(CaseResult(case.id, "FAIL", f"apply raised: {e}"))
            continue
        if not applied:
            restore()
            results.append(CaseResult(case.id, "STALE", "apply() returned False (旧串不在目标中)"))
            continue
        code = int(run_audit())
        restore()
        if code == 0:
            results.append(CaseResult(case.id, "FAIL", "audit returned 0 after injection (门禁未触发)"))
        else:
            results.append(CaseResult(case.id, "PASS", f"audit exit={code}"))

    clean_ok = None
    clean_detail = ""
    if require_clean_pass:
        restore()
        code = int(run_audit())
        clean_ok = code == 0
        clean_detail = f"exit={code}"
    return NegReport(results=results, clean_ok=clean_ok, clean_detail=clean_detail)


def run_env_suite(
    *,
    audit_cmd: Sequence[str],
    cases: Sequence[NegCase],
    cwd: Path | str,
    env_key: str = "AUDIT_NEG",
    clean_env_value: str = "",
    require_clean_pass: bool = True,
    timeout: Optional[float] = None,
) -> NegReport:
    """子进程模式：每案设置环境变量 env_key=case.env()，期望非零；最后清空再跑干净轮。"""
    root = Path(cwd)
    results: List[CaseResult] = []

    def _run(val: str) -> Tuple[int, str]:
        env = dict(os.environ)
        if val:
            env[env_key] = val
        else:
            env.pop(env_key, None)
            # 兼容空字符串显式清空
            env[env_key] = clean_env_value
            if clean_env_value == "":
                env.pop(env_key, None)
        r = subprocess.run(
            list(audit_cmd),
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        tail = (r.stdout or "")[-300:] + (r.stderr or "")[-200:]
        return r.returncode, tail.strip()

    for case in cases:
        stale = check_probes(case.probes, root) if case.probes else None
        if stale:
            results.append(CaseResult(case.id, "STALE", stale))
            continue
        code, tail = _run(case.env())
        if code == 0:
            results.append(CaseResult(case.id, "FAIL", "audit returned 0 after injection; " + tail[:180]))
        else:
            results.append(CaseResult(case.id, "PASS", f"audit exit={code}"))

    clean_ok = None
    clean_detail = ""
    if require_clean_pass:
        code, tail = _run(clean_env_value)
        # ensure key cleared
        if clean_env_value == "":
            code, tail = _run("")
        clean_ok = code == 0
        clean_detail = f"exit={code}" + (f"; {tail[:120]}" if not clean_ok and tail else "")
    return NegReport(results=results, clean_ok=clean_ok, clean_detail=clean_detail)


def load_cases_json(path: Path) -> List[NegCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for item in data:
        probes = [tuple(p) for p in item.get("probes") or []]
        out.append(
            NegCase(
                id=item["id"],
                probes=probes,
                env_value=item.get("env_value"),
                description=item.get("description") or "",
            )
        )
    return out


def _selftest() -> bool:
    ok = []

    # 1) replace_once
    box = {"t": "权利要求1至10任一项"}
    ok.append(("replace_once hit", replace_once(box, "t", "1至10", "1至8") and "1至8" in box["t"]))
    ok.append(("replace_once miss", replace_once(box, "t", "1至10", "x") is False))

    # 2) probes
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        f = root / "content.py"
        f.write_text("有效时间裕度 = 1\n1至10\n", encoding="utf-8")
        ok.append(("probes ok", check_probes([("content.py", "有效时间裕度")], root) is None))
        ok.append(("probes stale", check_probes([("content.py", "不存在的串")], root) is not None))

        # 3) callback suite: injection must fail audit; clean pass
        state = {"claims": "……有效时间裕度……", "bad": False}

        def apply_c10():
            return replace_once(state, "claims", "有效时间裕度", "裕度")

        def restore():
            state["claims"] = "……有效时间裕度……"
            state["bad"] = False

        def audit():
            # 缺关键词则 FAIL(1)；干净文本 PASS(0)
            return 0 if "有效时间裕度" in state["claims"] else 1

        rep = run_suite(
            [NegCase("c10", probes=[("content.py", "有效时间裕度")], apply=apply_c10)],
            run_audit=audit,
            restore=restore,
            cwd=root,
        )
        ok.append(("suite inject FAIL→PASS", rep.results[0].status == "PASS" and rep.clean_ok is True))

        # 4) stale apply
        def apply_stale():
            return replace_once(state, "claims", "早已删掉的词", "x")

        restore()
        rep2 = run_suite(
            [NegCase("stale", apply=apply_stale)],
            run_audit=audit,
            restore=restore,
            require_clean_pass=False,
            cwd=root,
        )
        ok.append(("suite stale", rep2.results[0].status == "STALE"))

        # 5) gate not triggered (audit always 0)
        def apply_ok():
            return replace_once(state, "claims", "有效时间裕度", "裕度")

        def audit_blind():
            return 0

        restore()
        rep3 = run_suite(
            [NegCase("blind", probes=[("content.py", "有效时间裕度")], apply=apply_ok)],
            run_audit=audit_blind,
            restore=restore,
            require_clean_pass=False,
            cwd=root,
        )
        ok.append(("suite blind FAIL", rep3.results[0].status == "FAIL"))

        # 6) env suite with tiny fake audit script
        audit_py = root / "fake_audit.py"
        audit_py.write_text(
            "import os,sys\n"
            "v=os.environ.get('AUDIT_NEG','')\n"
            "sys.exit(1 if v else 0)\n",
            encoding="utf-8",
        )
        cases = [
            NegCase("medium", probes=[("content.py", "1至10")]),
            NegCase("c10", probes=[("content.py", "有效时间裕度")]),
        ]
        rep4 = run_env_suite(
            audit_cmd=[sys.executable, str(audit_py)],
            cases=cases,
            cwd=root,
            env_key="AUDIT_NEG",
        )
        ok.append(("env suite", rep4.ok and all(r.status == "PASS" for r in rep4.results) and rep4.clean_ok))

        # 7) env suite catches stale probe
        rep5 = run_env_suite(
            audit_cmd=[sys.executable, str(audit_py)],
            cases=[NegCase("gone", probes=[("content.py", "早就没了")])],
            cwd=root,
            require_clean_pass=False,
        )
        ok.append(("env stale", rep5.results[0].status == "STALE" and not rep5.ok))

        # 8) load json
        jp = root / "cases.json"
        jp.write_text(
            json.dumps([{"id": "medium", "probes": [["content.py", "1至10"]], "description": "x"}], ensure_ascii=False),
            encoding="utf-8",
        )
        loaded = load_cases_json(jp)
        ok.append(("load json", loaded[0].id == "medium" and loaded[0].probes[0][1] == "1至10"))

    me = Path(__file__).read_text(encoding="utf-8")
    import re as _re
    net = _re.findall(r"^\s*(?:import|from)\s+(socket|urllib|http|requests)\b", me, _re.M)
    ok.append(("no network imports", net == []))

    for name, r in ok:
        print(("PASS " if r else "FAIL ") + name)
    return all(r for _, r in ok)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="专利 audit 反测注入模板（探针失效检测 + 干净轮次）")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--cwd", default=".", help="项目根（探针相对路径基准）")
    ap.add_argument("--audit", nargs="+", help="audit 命令 argv，如: python audit_consistency.py")
    ap.add_argument("--cases", help="cases.json 路径")
    ap.add_argument("--env-key", default="AUDIT_NEG")
    ap.add_argument("--timeout", type=float, default=None)
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.selftest:
        return 0 if _selftest() else 1
    if not a.audit or not a.cases:
        print(__doc__)
        return 0
    cases = load_cases_json(Path(a.cases))
    rep = run_env_suite(
        audit_cmd=a.audit,
        cases=cases,
        cwd=Path(a.cwd),
        env_key=a.env_key,
        timeout=a.timeout,
    )
    for line in rep.summary_lines():
        print(line)
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
