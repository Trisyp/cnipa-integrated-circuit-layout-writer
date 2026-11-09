# -*- coding: utf-8 -*-
"""检查布图登记输出目录中的 ZIP/TIFF 是否符合电子申请习惯门禁。

用法：
    python check_layout_package.py DIST_DIR
    python check_layout_package.py --selftest
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from layout_gates import catalog_tiff_mismatch, zip_rules_from_namelist  # noqa: E402

TIFF_RE = re.compile(r"^\d+\.(tiff|tif)$", re.I)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_dist(dist: Path) -> dict:
    result = {"zips": [], "errors": [], "warnings": [], "hashes": {}}
    zips = sorted(dist.glob("*.zip"))
    if not zips:
        result["errors"].append("NO_ZIP: 目录下无 zip")
        return result
    for zp in zips:
        info = {"path": str(zp), "errors": []}
        result["hashes"][zp.name] = sha256(zp)
        try:
            with zipfile.ZipFile(zp) as zf:
                names = zf.namelist()
                info["names"] = names
                info["errors"] += zip_rules_from_namelist(names, max_bytes=zp.stat().st_size)
                tiffs = [n for n in names if TIFF_RE.match(Path(n).name)]
                if tiffs:
                    info["errors"] += catalog_tiff_mismatch(list(range(len(tiffs))), [Path(n).name for n in tiffs])
        except zipfile.BadZipFile:
            info["errors"].append("BAD_ZIP")
        result["zips"].append(info)
        result["errors"].extend(info["errors"])
    return result


def _selftest() -> int:
    import tempfile
    from pack_layout_zips import pack
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        try:
            from PIL import Image
            Image.new("RGB", (32, 32), (255, 255, 255)).save(td / "x.tiff", format="TIFF")
        except Exception:
            (td / "x.tiff").write_bytes(b"II*\x00" + b"\x00" * 32)
        pack({
            "base_dir": str(td),
            "packages": [{"category": "图样", "zip_name": "图样.zip",
                          "files": [{"src": "x.tiff", "dest": "1.tiff"}]}],
        }, td / "dist")
        r = check_dist(td / "dist")
        assert not r["errors"], r
        print("PASS check_layout_package selftest")
        print(json.dumps(r["hashes"], ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dist", nargs="?")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        raise SystemExit(_selftest())
    if not args.dist:
        ap.error("dist required")
    r = check_dist(Path(args.dist))
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        for z in r["zips"]:
            print(z["path"], "OK" if not z["errors"] else z["errors"])
        print("TOTAL_ERRORS", len(r["errors"]))
        for k, v in r["hashes"].items():
            print(f"SHA256 {k} {v}")
    raise SystemExit(1 if r["errors"] else 0)


if __name__ == "__main__":
    main()
