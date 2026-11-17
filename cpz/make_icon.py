#!/usr/bin/env python3
"""HEXA MATRIX のランチャー用アイコン (琥珀の六角形 + 点のハート)

usage: python3 make_icon.py OUT.png [SIZE | REFERENCE.png]
"""
import math
import sys

from PIL import Image, ImageDraw, ImageFilter

HEART = [0x0000, 0x1E78, 0x3FFC, 0x7FFE, 0x7FFE, 0x7FFE, 0x7FFE, 0x3FFC,
         0x1FF8, 0x0FF0, 0x0FF0, 0x07E0, 0x03C0, 0x0180, 0x0000, 0x0000]


def hexpts(cx, cy, r):
    return [(cx + r * math.cos(math.radians(60 * i + 30)), cy + r * math.sin(math.radians(60 * i + 30)))
            for i in range(6)]


def make(size):
    s = size * 4
    u = s / 100
    amber = (255, 176, 46, 255)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    pts = hexpts(50 * u, 50 * u, 44 * u)
    ImageDraw.Draw(glow).line(pts + [pts[0]], fill=(255, 176, 46, 200), width=int(10 * u))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(4 * u)))
    d = ImageDraw.Draw(img)
    d.polygon(pts, fill=(16, 18, 24, 255))
    d.line(pts + [pts[0]], fill=amber, width=int(4 * u), joint="curve")
    pitch, r = 2.9 * u, 1.0 * u
    x0 = y0 = 50 * u - pitch * 8 + pitch / 2
    for y in range(16):
        for x in range(16):
            cx, cy = x0 + x * pitch, y0 + y * pitch + 2 * u
            on = HEART[y] & (0x8000 >> x)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 240, 220, 255) if on else (40, 36, 30, 255))
    return img.resize((size, size), Image.LANCZOS)


def main():
    out, size = sys.argv[1], 64
    if len(sys.argv) > 2:
        a = sys.argv[2]
        if a.lower().endswith(".png"):
            try:
                size = Image.open(a).size[0]
            except OSError:
                pass
        else:
            size = int(a)
    make(size).save(out)
    print(f"icon {size}x{size} -> {out}")


if __name__ == "__main__":
    main()
