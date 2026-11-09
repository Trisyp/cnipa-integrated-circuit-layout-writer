# -*- coding: utf-8 -*-
"""生成虚构的「规划/示意」分层 TIFF（非正式掩膜）。

仅用示意矩形/文字，不模仿任何参考示例几何。输出页均带「规划/示意」水印。

用法：
    python make_planning_tiffs.py --out DIR --layers 总图,有源,多晶,金属1
    python make_planning_tiffs.py --selftest
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

def render_pages(out: Path, layers: list[str], size=(2480, 3508)):
    """A4 ~300dpi default; requires Pillow."""
    from PIL import Image, ImageDraw, ImageFont
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, name in enumerate(layers, 1):
        img = Image.new("RGB", size, (255, 255, 255))
        dr = ImageDraw.Draw(img)
        # margin box
        dr.rectangle([80, 80, size[0]-80, size[1]-80], outline=(0, 0, 0), width=3)
        title = f"{i}. {name}（规划/示意）"
        dr.text((120, 120), title, fill=(0, 0, 0))
        dr.text((120, 200), "PLANNING / SCHEMATIC ONLY — NOT A FORMAL MASK", fill=(0, 0, 0))
        # fictional blocks
        y = 400
        for k in range(3):
            dr.rectangle([200, y, size[0]-200, y+180], outline=(0, 0, 0), width=2)
            dr.text((220, y+70), f"MODULE_{k+1}", fill=(0, 0, 0))
            y += 260
        dest = out / f"{i}.tiff"
        img.save(dest, format="TIFF")
        paths.append(dest)
    # catalog text
    cat = out / "catalog.txt"
    lines = [f"{i}\t{name}\t规划/示意" for i, name in enumerate(layers, 1)]
    cat.write_text("页码\t图层名称\t备注\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return paths, cat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="planning_out")
    ap.add_argument("--layers", default="总图,示意层A,示意层B")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    layers = [x.strip() for x in args.layers.split(",") if x.strip()]
    if args.selftest:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            paths, cat = render_pages(Path(td), ["总图", "层A"])
            assert paths[0].is_file() and "规划" in cat.read_text(encoding="utf-8")
            print("PASS make_planning_tiffs selftest")
        return 0
    paths, cat = render_pages(Path(args.out), layers)
    print("wrote", len(paths), "tiff +", cat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
