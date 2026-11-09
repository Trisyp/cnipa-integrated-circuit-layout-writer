# -*- coding: utf-8 -*-
"""sim_record.py — 本地计算/仿真运行记录（run log），并标记选入申请文件的运行（SELECTED）。

定位：帮助专利**完整**、数值有真实来源。记录每次运行的目标、参数、命令与结果；允许从真实结果中
选取有代表性、效果好的一组标为 SELECTED 用于实施例。缺 target.md / 仍为模板占位 / 缺指标或对照 / 空 metrics /
目标在运行后被修改 → 只 WARN，**从不 FAIL**；裁决标签（支持/部分支持/不支持/不可测）可选。仅标准库，不联网，只写本地目录。

目录约定：simulation/<名称>/
    target.md   运行目标（效果主张、指标与方向、基线/对照、数据构成、参数表）——init 生成模板
    runs.tsv    运行记录（本脚本追加；UTF-8 TSV）

用法：
    python sim_record.py init simulation/demo                         # 生成 target.md 模板（不覆盖）
    python sim_record.py log simulation/demo --params '{"window":10}' --metrics '{"mean_dev":0.42}' \
        --cmd "python run.py --window 10" --result out/r1.csv [--label 支持] [--note "..."]
    python sim_record.py select simulation/demo r002 [--only] [--note "最有代表性"]
    python sim_record.py unselect simulation/demo r002
    python sim_record.py list simulation/demo
    python sim_record.py report simulation/demo [--reports reports]    # → reports/仿真运行记录-<名称>-YYYYMMDD.md
    python sim_record.py to-ledger simulation/demo --ledger evidence/ledger.tsv   # 把 SELECTED 运行的指标追加进证据台账
    python sim_record.py --selftest
运行记录与报告均为内部材料：申请文本不得出现「仿真/种子/场景N」等字样（patent_gates.internal_wording 拦截）。
"""
import csv
import datetime
import hashlib
import io
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

HEADER = ("run_id", "time", "target_sha256", "target_changed", "params", "command", "result_file",
          "result_sha256", "metrics", "label", "selected", "note")
LABELS = ("支持", "部分支持", "不支持", "不可测")
TARGET_TEMPLATE = """# 运行目标（内部文档，不进正式稿）

- 效果主张：<要支撑的有益效果，一句话>
- 指标与方向：<指标名>，<越小越好/越大越好>
- 对照：<现有主流做法>；<去掉关键步骤的对照>
- 数据构成：<信号组成、规模、缺失方式、重复次数>
- 参数表：<参数名 = 取值或范围>
- 选取说明：<从真实结果中选哪一组用于实施例、为什么有代表性>

> 数值须来自真实计算或仿真，不得凭空编造。修改本文件后继续运行会被记录（WARN，不阻断）。
"""


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _clean(v):
    return str(v if v is not None else "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def read_runs(d):
    p = os.path.join(d, "runs.tsv")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8-sig") as f:
        return [dict({k: "" for k in HEADER}, **{k: (v or "") for k, v in r.items() if k})
                for r in csv.DictReader(f, delimiter="\t")]


def write_runs(d, runs):
    p = os.path.join(d, "runs.tsv")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(HEADER) + "\n")
        for r in runs:
            f.write("\t".join(_clean(r.get(k, "")) for k in HEADER) + "\n")
    os.replace(tmp, p)



def _target_predeclare_warns(target_path):
    """运行前目标预声明检查：缺文件 / 仍为模板占位 / 缺指标或对照 → WARN，不阻断。"""
    warns = []
    if not os.path.isfile(target_path):
        warns.append("WARN target.md missing (run init first); recorded without target hash")
        return warns
    raw = open(target_path, encoding="utf-8-sig").read()
    if "<要支撑" in raw or "<指标名>" in raw or "<现有主流做法>" in raw:
        warns.append("WARN target.md still has template placeholders (predeclare criteria before logging)")
    if "指标" not in raw:
        warns.append("WARN target.md missing metrics declaration (指标)")
    if "对照" not in raw:
        warns.append("WARN target.md missing controls/baseline declaration (对照)")
    return warns

def init(d):
    os.makedirs(d, exist_ok=True)
    t = os.path.join(d, "target.md")
    if os.path.exists(t):
        return False
    with open(t, "w", encoding="utf-8", newline="\n") as f:
        f.write(TARGET_TEMPLATE)
    return True


def log_run(d, params=None, metrics=None, command="", result="", label="", note=""):
    """追加一次运行；返回 (run_id, warnings)。缺目标/占位/缺指标对照/空 metrics/目标变化/未知标签/缺文件只 WARN。"""
    os.makedirs(d, exist_ok=True)
    warns = []
    runs = read_runs(d)
    t = os.path.join(d, "target.md")
    tsha = _sha(t) if os.path.isfile(t) else ""
    warns += _target_predeclare_warns(t)
    changed = ""
    if runs and tsha and runs[-1].get("target_sha256") and runs[-1]["target_sha256"] != tsha:
        changed = "yes"
        warns.append(f"WARN target.md changed since {runs[-1]['run_id']} (recorded, not blocking)")
        note = ("目标已修改；" + note) if note else "目标已修改"
    if not metrics:
        warns.append("WARN metrics empty; record metrics from the real run")
    if label and label not in LABELS:
        warns.append(f"WARN unknown label {label!r} (optional; suggested: {'/'.join(LABELS)})")
    rsha = ""
    if result:
        if os.path.isfile(result):
            rsha = _sha(result)
        else:
            warns.append(f"WARN result file not found: {result}")
    rid = "r%03d" % (len(runs) + 1)
    runs.append({"run_id": rid, "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "target_sha256": tsha, "target_changed": changed,
                 "params": json.dumps(params or {}, ensure_ascii=False, sort_keys=True),
                 "command": command, "result_file": result, "result_sha256": rsha,
                 "metrics": json.dumps(metrics or {}, ensure_ascii=False, sort_keys=True),
                 "label": label, "selected": "", "note": note})
    write_runs(d, runs)
    return rid, warns


def select(d, run_id, on=True, only=False, note=""):
    runs = read_runs(d)
    if run_id not in [r["run_id"] for r in runs]:
        raise KeyError("no such run: " + run_id)
    for r in runs:
        if r["run_id"] == run_id:
            r["selected"] = "SELECTED" if on else ""
            if note:
                r["note"] = (r["note"] + "；" if r["note"] else "") + note
        elif only and on:
            r["selected"] = ""
    write_runs(d, runs)


def report(d, out_path):
    ap = os.path.abspath(out_path)
    if os.path.basename(os.path.dirname(ap)).lower() != "reports" or not ap.lower().endswith(".md"):
        raise ValueError("报告只写 reports/*.md: " + out_path)
    runs = read_runs(d)
    t = os.path.join(d, "target.md")
    L = [f"# 仿真运行记录：{os.path.basename(os.path.abspath(d))}（内部文档，不进正式稿）", "",
         f"> 生成：{datetime.datetime.now():%Y-%m-%d %H:%M}；SELECTED = 选入实施例的运行（可选有代表性、效果好的真实结果）。", ""]
    if os.path.isfile(t):
        L += ["## 目标（target.md 当前版本）", "", open(t, encoding="utf-8-sig").read().strip(), ""]
    L += ["## 运行", "", "| 运行 | 时间 | 选入 | 参数 | 指标 | 标签 | 目标变化 | 命令 | 备注 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        sel = "**SELECTED**" if r["selected"] else ""
        m = f"**{r['metrics']}**" if r["selected"] else r["metrics"]
        L.append("| " + " | ".join(x.replace("|", "\\|") for x in (
            r["run_id"], r["time"], sel, r["params"], m, r["label"], r["target_changed"], r["command"], r["note"])) + " |")
    os.makedirs(os.path.dirname(ap), exist_ok=True)
    with open(ap, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    return ap


def to_ledger(d, ledger_path):
    """把 SELECTED 运行的每个指标追加为证据台账行（来源=仿真）。返回追加行数。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from evidence_ledger import COLUMNS
    name = os.path.basename(os.path.abspath(d))
    rows = []
    for r in read_runs(d):
        if not r["selected"]:
            continue
        for k, v in json.loads(r["metrics"] or "{}").items():
            rows.append({"id": f"sim-{name}-{r['run_id']}-{k}", "name": k, "location": "", "value": str(v), "unit": "",
                         "source": "仿真", "script": r["command"], "result_file": r["result_file"],
                         "sha256": r["result_sha256"], "grade": r["label"], "special_effect": "", "core_param": "",
                         "note": f"SELECTED {r['run_id']}"})
    new = not os.path.isfile(ledger_path)
    if new:
        os.makedirs(os.path.dirname(os.path.abspath(ledger_path)), exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("\t".join(COLUMNS) + "\n")
        for row in rows:
            f.write("\t".join(_clean(row[c]) for c in COLUMNS) + "\n")
    return len(rows)


def _selftest():
    import tempfile
    ok = []
    with tempfile.TemporaryDirectory() as root:
        d = os.path.join(root, "simulation", "demo")
        ok.append(("init", init(d) and not init(d)))
        res = os.path.join(root, "r.csv")
        open(res, "w").write("x\n")
        r0, w0 = log_run(d, {"window": 5}, {"mean_dev": 0.50}, "python run.py", res)
        ok.append(("placeholder target -> WARN", any("placeholder" in x for x in w0) and r0 == "r001"))
        d = os.path.join(root, "simulation", "demo2")
        init(d)
        with open(os.path.join(d, "target.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# 运行目标\n- 效果主张：降低平均偏差\n- 指标与方向：mean_dev，越小越好\n"
                    "- 对照：算术平均；去掉加权步骤\n- 数据构成：5 单元合成读数\n- 参数表：window=10\n- 选取说明：取代表性最优\n")
        r1, w1 = log_run(d, {"window": 10}, {"mean_dev": 0.48}, "python run.py", res, "支持")
        r2, w2 = log_run(d, {"window": 20}, {"mean_dev": 0.42}, "python run.py --w 20", res)
        ok.append(("log ids after predeclare", (r1, r2) == ("r001", "r002")))
        ok.append(("predeclare clean", w1 == [] and w2 == []))
        _, wm = log_run(d, {"window": 1}, {}, "python run.py")
        ok.append(("empty metrics -> WARN", any("metrics empty" in x for x in wm)))
        d2 = os.path.join(root, "simulation", "bare")
        os.makedirs(d2, exist_ok=True)
        _, wb = log_run(d2, metrics={"x": 1})
        ok.append(("missing target.md -> WARN", any("target.md missing" in x for x in wb)))
        with open(os.path.join(d, "target.md"), "a", encoding="utf-8") as f:
            f.write("- 追加对照说明\n")
        r3, w3 = log_run(d, {"window": 30}, {"mean_dev": 0.45}, label="随便")
        runs = read_runs(d)
        ok.append(("target change -> WARN not FAIL", any("changed" in x for x in w3) and runs[-1]["target_changed"] == "yes"))
        ok.append(("unknown label -> WARN, recorded", any("unknown label" in x for x in w3) and runs[-1]["label"] == "随便"))
        ok.append(("missing result -> WARN", any("not found" in x for x in log_run(d, metrics={"z": 1}, result=os.path.join(root, "nope"))[1])))
        select(d, "r002", note="效果最好且有代表性")
        select(d, "r001")
        select(d, "r002", only=True)
        sel = [r["run_id"] for r in read_runs(d) if r["selected"]]
        ok.append(("select only", sel == ["r002"]))
        try:
            select(d, "r999")
            ok.append(("select missing run errors", False))
        except KeyError:
            ok.append(("select missing run errors", True))
        out = report(d, os.path.join(root, "reports", "run.md"))
        md = open(out, encoding="utf-8").read()
        ok.append(("report marks SELECTED", "**SELECTED**" in md and "追加对照" in md))
        try:
            report(d, os.path.join(root, "run.md"))
            ok.append(("report refuses non-reports", False))
        except ValueError:
            ok.append(("report refuses non-reports", True))
        lp = os.path.join(root, "evidence", "ledger.tsv")
        n = to_ledger(d, lp)
        txt = open(lp, encoding="utf-8").read()
        ok.append(("to-ledger", n == 1 and "0.42" in txt and "仿真" in txt and txt.startswith("id\t")))
    for name, r in ok:
        print(("PASS " if r else "FAIL ") + name)
    return all(r for _, r in ok)

def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="本地运行记录（WARN 不阻断）")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("init"); s.add_argument("dir")
    s = sub.add_parser("log"); s.add_argument("dir")
    s.add_argument("--params", default="{}"); s.add_argument("--metrics", default="{}")
    s.add_argument("--cmd", dest="command", default=""); s.add_argument("--result", default="")
    s.add_argument("--label", default=""); s.add_argument("--note", default="")
    for name in ("select", "unselect"):
        s = sub.add_parser(name); s.add_argument("dir"); s.add_argument("run_id")
        s.add_argument("--note", default="")
        if name == "select":
            s.add_argument("--only", action="store_true", help="同时取消其他运行的 SELECTED")
    s = sub.add_parser("list"); s.add_argument("dir")
    s = sub.add_parser("report"); s.add_argument("dir"); s.add_argument("--out"); s.add_argument("--reports", default="reports")
    s = sub.add_parser("to-ledger"); s.add_argument("dir"); s.add_argument("--ledger", required=True)
    a = ap.parse_args(argv)
    if a.selftest:
        return 0 if _selftest() else 1
    if a.cmd == "init":
        print("已生成 target.md" if init(a.dir) else "target.md 已存在，未覆盖"); return 0
    if a.cmd == "log":
        rid, warns = log_run(a.dir, json.loads(a.params), json.loads(a.metrics), a.command, a.result, a.label, a.note)
        for w in warns:
            print(w)
        print("已记录", rid); return 0
    if a.cmd in ("select", "unselect"):
        try:
            select(a.dir, a.run_id, on=a.cmd == "select", only=getattr(a, "only", False), note=a.note)
        except KeyError as e:
            print("ERROR", e); return 2
        print("OK", a.cmd, a.run_id); return 0
    if a.cmd == "list":
        for r in read_runs(a.dir):
            print("\t".join([r["run_id"], r["selected"] or "-", r["metrics"], r["label"] or "-", r["target_changed"] or "-", r["note"]]))
        return 0
    if a.cmd == "report":
        name = os.path.basename(os.path.abspath(a.dir))
        out = a.out or os.path.join(a.reports, f"仿真运行记录-{name}-{datetime.date.today():%Y%m%d}.md")
        print("已写:", report(a.dir, out)); return 0
    if a.cmd == "to-ledger":
        print("已追加台账行:", to_ledger(a.dir, a.ledger)); return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
