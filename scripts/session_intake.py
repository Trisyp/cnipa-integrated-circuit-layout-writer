# -*- coding: utf-8 -*-
"""session_intake.py — 开工前就绪清单（fail-closed；只校验声明，不读布图登记正文/图样）。

灵感来自 K-Dense-AI/scientific-agent-skills peer-review intake 的 fail-closed 思路。
声明为本地 JSON；stdout 只报字段名与状态码，不回显简要说明/图样目录。仅标准库，不联网。

必填声明（schema_version=1）：
    confidential_terms_path   保密词表路径（文件须存在，除非 allow_missing_terms=true）
    no_public_paste_of_body   必须为 true（禁止把正文贴公网/消费级 AI）
    claim1_locked             必须为 true（CLAIM1_STEPS / 独权落点已锁定）
    glossary_ready            必须为 true（术语表已定）
    processing_boundary       必须为 "local_only"
    human_accountable         必须为 true

可选：
    allow_missing_terms       bool，默认 false
    project_id / note         短标识（不写技术方案）

用法：
    python session_intake.py template session_intake.json
    python session_intake.py check session_intake.json
    python session_intake.py --selftest

退出码：0 = READY_FOR_LOCAL_WORK；2 = NOT_READY；1 = 用法/IO 错误。
doctor.py --intake PATH 会转发到本脚本。
"""
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

SCHEMA = "1"
REQUIRED_BOOL_TRUE = (
    "no_public_paste_of_body",
    "claim1_locked",
    "glossary_ready",
    "human_accountable",
)
TEMPLATE = {
    "schema_version": SCHEMA,
    "project_id": "local-project",
    "confidential_terms_path": "confidential_terms.txt",
    "allow_missing_terms": False,
    "no_public_paste_of_body": True,
    "claim1_locked": True,
    "glossary_ready": True,
    "processing_boundary": "local_only",
    "human_accountable": True,
    "note": "",
}


def write_template(path):
    if os.path.exists(path):
        return False
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(TEMPLATE, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return True


def validate(data):
    """返回 (ready: bool, issues: [(code, field, detail), ...])；detail 无布图登记正文/图样。"""
    issues = []
    if not isinstance(data, dict):
        return False, [("NOT_OBJECT", "root", "intake must be a JSON object")]
    if str(data.get("schema_version", "")) != SCHEMA:
        issues.append(("BAD_SCHEMA", "schema_version", f"want {SCHEMA!r}"))
    for key in REQUIRED_BOOL_TRUE:
        if data.get(key) is not True:
            issues.append(("MUST_BE_TRUE", key, f"got {data.get(key)!r}"))
    if data.get("processing_boundary") != "local_only":
        issues.append(("BAD_BOUNDARY", "processing_boundary", f"want 'local_only', got {data.get('processing_boundary')!r}"))
    terms = data.get("confidential_terms_path")
    allow_miss = data.get("allow_missing_terms") is True
    if not isinstance(terms, str) or not terms.strip():
        issues.append(("MISSING_TERMS_PATH", "confidential_terms_path", "path required"))
    elif not allow_miss and not os.path.isfile(terms):
        issues.append(("TERMS_FILE_MISSING", "confidential_terms_path", "file not found (create local confidential_terms*.txt)"))
    ready = not issues
    return ready, issues


def check_file(path):
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    # resolve terms path relative to intake file dir
    if isinstance(data, dict) and isinstance(data.get("confidential_terms_path"), str):
        tp = data["confidential_terms_path"]
        if tp and not os.path.isabs(tp):
            cand = os.path.join(os.path.dirname(os.path.abspath(path)), tp)
            if os.path.isfile(cand) or not os.path.isfile(tp):
                data = dict(data)
                data["confidential_terms_path"] = cand if os.path.isfile(cand) else tp
    return validate(data)


def _selftest():
    import tempfile
    ok = []
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "intake.json")
        ok.append(("template", write_template(p) and not write_template(p)))
        # terms missing -> NOT_READY
        ready, issues = check_file(p)
        ok.append(("missing terms -> not ready", not ready and any(c == "TERMS_FILE_MISSING" for c, _, _ in issues)))
        terms = os.path.join(d, "confidential_terms.txt")
        open(terms, "w", encoding="utf-8").write("# fictional\n示例保密词甲\n")
        data = json.load(open(p, encoding="utf-8"))
        data["confidential_terms_path"] = terms
        json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        ready, issues = check_file(p)
        ok.append(("good -> ready", ready and issues == []))
        # flip flags
        for key in REQUIRED_BOOL_TRUE:
            bad = dict(data)
            bad[key] = False
            r, iss = validate(bad)
            ok.append((f"{key} false -> block", not r and any(f == key for _, f, _ in iss)))
        bad = dict(data)
        bad["processing_boundary"] = "cloud_ok"
        r, iss = validate(bad)
        ok.append(("bad boundary", not r and any(c == "BAD_BOUNDARY" for c, _, _ in iss)))
        bad = dict(data)
        bad["allow_missing_terms"] = True
        bad["confidential_terms_path"] = os.path.join(d, "nope.txt")
        r, iss = validate(bad)
        ok.append(("allow_missing_terms", r))
        # no prose echo
        msg = " ".join(d for _, _, d in issues)
        ok.append(("no claim prose in messages", "权利要求" not in msg and "说明书" not in msg))
    for name, r in ok:
        print(("PASS " if r else "FAIL ") + name)
    return all(r for _, r in ok)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="开工前就绪清单（fail-closed；不读布图登记正文/图样）")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("template"); s.add_argument("path")
    s = sub.add_parser("check"); s.add_argument("path")
    a = ap.parse_args(argv)
    if a.selftest:
        return 0 if _selftest() else 1
    if a.cmd == "template":
        print("已生成" if write_template(a.path) else "已存在，未覆盖")
        return 0
    if a.cmd == "check":
        try:
            ready, issues = check_file(a.path)
        except (OSError, json.JSONDecodeError) as e:
            print("ERROR", type(e).__name__)
            return 1
        if ready:
            print("READY_FOR_LOCAL_WORK")
            return 0
        print("NOT_READY")
        for code, field, detail in issues:
            print(f"  {code}  field={field}  {detail}")
        return 2
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
