# -*- coding: utf-8 -*-
"""按类别打包布图登记电子材料 ZIP（包内无文件夹；图样连续 N.tiff）。

manifest.json 示例：
{
  "out_dir": "dist",
  "packages": [
    {
      "category": "图样",
      "zip_name": "图样.zip",
      "files": [
        {"src": "pages/overview.tiff", "dest": "1.tiff"},
        {"src": "pages/layer_poly.tiff", "dest": "2.tiff"}
      ]
    },
    {
      "category": "图样目录",
      "zip_name": "图样目录.zip",
      "files": [{"src": "catalog/1.tiff", "dest": "1.tiff"}]
    },
    {
      "category": "简要说明",
      "zip_name": "简要说明.zip",
      "files": [{"src": "brief/1.tiff", "dest": "1.tiff"}]
    }
  ]
}

用法：
    python pack_layout_zips.py --manifest manifest.json [--out DIR]
    python pack_layout_zips.py --selftest
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from layout_gates import catalog_tiff_mismatch, zip_rules_from_namelist  # noqa: E402


def pack(manifest: dict, out_dir: Path) -> list:
    out_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for pkg in manifest.get("packages", []):
        zpath = out_dir / pkg["zip_name"]
        with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            dests = []
            for f in pkg.get("files", []):
                src = Path(f["src"])
                if not src.is_file():
                    # allow relative to manifest base
                    base = Path(manifest.get("base_dir", "."))
                    src = base / f["src"]
                dest = f["dest"]
                if "/" in dest.replace("\\", "/") or dest.endswith("/"):
                    raise SystemExit(f"dest must be flat file name: {dest}")
                if not src.is_file():
                    raise SystemExit(f"missing src: {f['src']}")
                zf.write(src, arcname=dest)
                dests.append(dest)
        size = zpath.stat().st_size
        names = zipfile.ZipFile(zpath).namelist()
        errs = zip_rules_from_namelist(names, max_bytes=size)
        if pkg.get("category") == "图样":
            errs += catalog_tiff_mismatch(list(range(len(dests))), dests)
        reports.append({"zip": str(zpath), "size": size, "names": names, "errors": errs})
        print(f"wrote {zpath} ({size} bytes) names={names} errs={errs or 'OK'}")
    return reports


def _selftest() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # minimal fake tiffs (Pillow optional: write bytes with TIFF header-ish via Pillow if present)
        try:
            from PIL import Image
            for i, name in enumerate(["a.tiff", "b.tiff"], 1):
                Image.new("RGB", (64, 64), (255, 255, 255)).save(td / name, format="TIFF")
        except Exception:
            for name in ["a.tiff", "b.tiff"]:
                (td / name).write_bytes(b"II*\x00" + b"\x00" * 64)
        man = {
            "base_dir": str(td),
            "packages": [{
                "category": "图样",
                "zip_name": "图样.zip",
                "files": [
                    {"src": "a.tiff", "dest": "1.tiff"},
                    {"src": "b.tiff", "dest": "2.tiff"},
                ],
            }],
        }
        out = td / "dist"
        reps = pack(man, out)
        assert reps and not reps[0]["errors"], reps
        print("PASS pack selftest")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        raise SystemExit(_selftest())
    if not args.manifest:
        ap.error("--manifest required")
    man = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out = Path(args.out or man.get("out_dir") or "dist")
    if "base_dir" not in man:
        man["base_dir"] = str(Path(args.manifest).resolve().parent)
    reps = pack(man, out)
    bad = [r for r in reps if r["errors"]]
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
