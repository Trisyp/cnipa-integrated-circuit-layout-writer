# -*- coding: utf-8 -*-
"""selftest_all.py — 布图登记 skill 一键回归。

    python scripts/selftest_all.py
只用 tests/fixtures/ 虚构数据；不联网。
"""
from __future__ import annotations
import os
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIX = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

SELFTESTS = [
    "layout_gates.py",
    "pack_layout_zips.py",
    "check_layout_package.py",
    "make_planning_tiffs.py",
    "query_guard.py",
    "evidence_ledger.py",
]

RESULTS = []


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd or str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = p.returncode == 0
    RESULTS.append((ok, cmd, p.stdout[-500:], p.stderr[-500:]))
    status = "PASS" if ok else "FAIL"
    print(status, " ".join(cmd))
    if not ok:
        print(p.stdout)
        print(p.stderr)
    return ok


def main():
    fails = 0
    # compile non-deprecated scripts
    for p in HERE.glob("*.py"):
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as e:
            print("FAIL compile", p.name, e)
            fails += 1
    for name in SELFTESTS:
        path = HERE / name
        if not path.is_file():
            print("SKIP missing", name)
            continue
        # scripts with --selftest
        if not run([sys.executable, str(path), "--selftest"]):
            fails += 1
    # fixture smoke: planning -> pack -> check
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        layers = "总图,示意层A,示意层B"
        if not run([sys.executable, str(HERE / "make_planning_tiffs.py"), "--out", str(td / "pages"), "--layers", layers]):
            fails += 1
        else:
            import json
            files = []
            pages = sorted((td / "pages").glob("*.tiff"))
            for i, pg in enumerate(pages, 1):
                files.append({"src": str(pg), "dest": f"{i}.tiff"})
            man = {"base_dir": str(td), "packages": [
                {"category": "图样", "zip_name": "图样.zip", "files": files}
            ]}
            man_path = td / "manifest.json"
            man_path.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
            if not run([sys.executable, str(HERE / "pack_layout_zips.py"), "--manifest", str(man_path), "--out", str(td / "dist")]):
                fails += 1
            elif not run([sys.executable, str(HERE / "check_layout_package.py"), str(td / "dist")]):
                fails += 1
    print("==== summary fails=", fails)
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()