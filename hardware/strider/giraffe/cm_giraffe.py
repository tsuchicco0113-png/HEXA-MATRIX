"""ｷﾘﾝ版の体ﾓｼﾞｭｰﾙ(案1 ﾌｸﾛｳ首の発展)。ﾎﾞﾃﾞｨ 2 部品。

giraffe_bay  : 胴(ｻｰﾎﾞﾍﾞｲ)。FS90R を軸下向きに吊る。底面・ﾋﾟﾝ穴・ﾎｰﾝ位置は cm_body と同じなので
               歩行台の dock_yoke と机用台座にそのまま載る。上は開いていて、ｻｰﾎﾞを上から入れてﾈｼﾞ止め。
giraffe_neck : 首 + 頭の受け。下のｽｶｰﾄを胴に差し込み、横から M2 ﾀｯﾋﾟﾝｸﾞ 2 本で留める。
               首は前上がりに傾き、頭(CoreMatrix + 18350x2)を前へ HEAD_DY、上へ NECK_RISE ずらす。
座標は cm_variant / cm_body と同じ(歩行台に載せた状態、Y = 前)。
"""
from __future__ import annotations

import math
import os
from functools import lru_cache

from manifold3d import CrossSection, JoinType, Manifold

import design as d
import cm_variant as c
import cm_body as b
from design import box, cyl, rect

NECK_RISE = float(os.environ.get("GIRAFFE_RISE", 30.0))   # 頭を上げる量(前の体ﾓｼﾞｭｰﾙ比)
HEAD_DY = float(os.environ.get("GIRAFFE_DY", 18.0))       # 頭を前へ出す量

# ---------------------------------------------------------------- 胴
WALL = 2.0
BAY_HX, BAY_HY, BAY_R = 28.0, 17.0, 7.0          # 胴の外形(半幅)
FLOOR_BOT, FLOOR_TOP = b.FLOOR_BOT, b.FLOOR_TOP  # 46.5 / 49.5
BAY_TOP = b.SERVO_TOP + 1.8                      # 70.5 ｻｰﾎﾞの上に 1.8 mm
SKIRT_H = 6.0                                    # 首のｽｶｰﾄの差し込み深さ
SKIRT_T = 2.4
FIT = 0.2                                        # ｽｶｰﾄと胴の内壁のすきま(片側)
SCREW_Z = BAY_TOP - SKIRT_H / 2
LID_T = 2.0

# ---------------------------------------------------------------- 首と頭
SHELF_T = 2.4
SHELF_BOT = b.SHELF_BOT + NECK_RISE
SHELF_TOP = SHELF_BOT + SHELF_T
FLARE_H = 9.0                                    # 首から頭の受けへ広がる部分
NECK_HX, NECK_HY = 13.0, 9.5                     # 首の外形(半幅)
NECK_IN = 2.2                                    # 首の肉厚
STACK_Y0 = -b.DEPTH / 2 + HEAD_DY
STACK_Y1 = b.DEPTH / 2 + HEAD_DY
GRIP_H = 12.0

b.PIN_XY[:] = [(20.0, -10.0), (-20.0, -10.0)]    # 胴が細くなったのでﾄﾞｯｸのﾋﾟﾝを内側へ


def _rr(hx, hy, r, cx=0.0, cy=0.0) -> CrossSection:
    r = min(r, hx - 0.01, hy - 0.01)
    return rect(cx - hx + r, cx + hx - r, cy - hy + r, cy + hy - r).offset(r, JoinType.Round, 2.0, 48)


def _slab(sec: CrossSection, z: float, t: float = 0.01) -> Manifold:
    return sec.extrude(t).translate((0, 0, z))


def _loft(sec0, z0, sec1, z1) -> Manifold:
    return Manifold.batch_hull([_slab(sec0, z0), _slab(sec1, z1 - 0.01)])


@lru_cache(maxsize=None)
def bay_part() -> Manifold:
    outer = _rr(BAY_HX, BAY_HY, BAY_R)
    inner = _rr(BAY_HX - WALL, BAY_HY - WALL, BAY_R - WALL)
    bay = outer.extrude(BAY_TOP - FLOOR_BOT).translate((0, 0, FLOOR_BOT))
    bay -= inner.extrude(BAY_TOP - FLOOR_TOP + 1).translate((0, 0, FLOOR_TOP))
    bay -= c.servo_cutout().extrude(FLOOR_TOP - FLOOR_BOT + 2).translate((0, 0, FLOOR_BOT - 1))
    bx = c.servo_body_x()
    for sx in (1, -1):
        bay -= cyl(c.SV_SCREW_PILOT, FLOOR_BOT - 1, FLOOR_TOP + 1, 24).translate((bx + sx * c.SV_EAR_PITCH / 2, 0, 0))
        # 首を留める M2 の通し穴(横から)
        bay -= d.cyl_x(1.15, sx * (BAY_HX - WALL - 0.5), sx * (BAY_HX + 1), 0.0, SCREW_Z, 24) if sx > 0 else \
            d.cyl_x(1.15, -(BAY_HX + 1), -(BAY_HX - WALL - 0.5), 0.0, SCREW_Z, 24)
    for x, y in b.PIN_XY:
        bay -= cyl(b.PIN_R + 0.25, FLOOR_BOT - 1, FLOOR_BOT + b.PIN_H + 0.4, 32).translate((x, y, 0))
    return bay


@lru_cache(maxsize=None)
def neck_part() -> Manifold:
    # ｽｶｰﾄ(胴の内側に差さる)とﾌﾀ
    s_out = _rr(BAY_HX - WALL - FIT, BAY_HY - WALL - FIT, BAY_R - WALL - FIT)
    s_in = _rr(BAY_HX - WALL - FIT - SKIRT_T, BAY_HY - WALL - FIT - SKIRT_T, max(BAY_R - WALL - FIT - SKIRT_T, 1.0))
    skirt = (s_out - s_in).extrude(SKIRT_H).translate((0, 0, BAY_TOP - SKIRT_H))
    lid = _rr(BAY_HX, BAY_HY, BAY_R).extrude(LID_T).translate((0, 0, BAY_TOP))
    # ﾈｼﾞが効く厚みのﾎﾞｽ
    for sx in (1, -1):
        x0 = sx * (BAY_HX - WALL - FIT)
        skirt += box(min(x0, x0 - sx * 5.0), max(x0, x0 - sx * 5.0), -4.0, 4.0, BAY_TOP - SKIRT_H, BAY_TOP)
    # 首: ﾌﾀの上 → 頭の受けの下まで、前上がりに傾いた角筒
    z0 = BAY_TOP + LID_T - 0.5
    zf = SHELF_BOT - FLARE_H
    neck_top_y = HEAD_DY
    neck = _loft(_rr(NECK_HX + 2, NECK_HY + 2, 8), z0, _rr(NECK_HX, NECK_HY, 7, 0, neck_top_y), zf)
    # 頭の受けへ広がる部分(ﾌﾚｱ)
    shelf_sec = _rr(b.OUT_X, b.OUT_Y, b.BODY_R, 0, HEAD_DY)
    neck += _loft(_rr(NECK_HX, NECK_HY, 7, 0, neck_top_y), zf - 0.01, shelf_sec, SHELF_BOT + 0.01)
    # 中空(ｹｰﾌﾞﾙ通し)
    hollow = _loft(_rr(NECK_HX + 2 - NECK_IN, NECK_HY + 2 - NECK_IN, 6), z0 - LID_T - 1.0,
                   _rr(NECK_HX - NECK_IN, NECK_HY - NECK_IN, 5, 0, neck_top_y), zf)
    hollow += _loft(_rr(NECK_HX - NECK_IN, NECK_HY - NECK_IN, 5, 0, neck_top_y), zf - 0.01,
                    _rr(b.OUT_X - 6, b.OUT_Y - 6, 4, 0, HEAD_DY), SHELF_BOT - 0.01)
    # 頭の受け(棚 + 背面の壁 + 側壁はﾍﾞｰｽ部分だけ + 前のﾘｯﾌﾟ)
    shelf = shelf_sec.extrude(SHELF_T).translate((0, 0, SHELF_BOT))
    shelf -= box(-14.0, -2.0, STACK_Y0 + 1.0, STACK_Y0 + 9.0, SHELF_BOT - 1, SHELF_TOP + 1)   # ｹｰﾌﾞﾙ穴(ﾍﾞｰｽの配線口側)
    grip = box(-b.OUT_X + b.BODY_R, b.OUT_X - b.BODY_R, HEAD_DY - b.OUT_Y, STACK_Y0 - b.CLR, SHELF_TOP - 0.01, SHELF_TOP + GRIP_H)
    for sx in (1, -1):
        x_in, x_out = sx * b.IN_X, sx * b.OUT_X
        grip += box(min(x_in, x_out), max(x_in, x_out), HEAD_DY - b.OUT_Y + b.BODY_R, STACK_Y0 + c.CM_BASE_H - 1.0,
                    SHELF_TOP - 0.01, SHELF_TOP + GRIP_H)
    grip += box(-b.IN_X + 7, b.IN_X - 7, STACK_Y1 + b.CLR, HEAD_DY + b.OUT_Y, SHELF_TOP - 0.01, SHELF_TOP + 2.5)
    grip = grip ^ shelf_sec.extrude(GRIP_H + 1).translate((0, 0, SHELF_TOP - 0.5))
    part = skirt + lid + neck + shelf + grip
    part -= hollow
    part -= _rr(NECK_HX + 2 - NECK_IN, NECK_HY + 2 - NECK_IN, 6).extrude(LID_T + 2).translate((0, 0, BAY_TOP - 1))
    # ﾎﾞｽの M2 下穴
    part -= d.cyl_x(0.8, -(BAY_HX + 1), BAY_HX + 1, 0.0, SCREW_Z, 24)
    return part


@lru_cache(maxsize=None)
def stack_dummy() -> Manifold:
    sec = c._stack_section(0.0).translate((0, SHELF_TOP))
    return d._along_y(sec, STACK_Y0, STACK_Y1)


def body_shapes():
    return {"giraffe_bay": bay_part(), "giraffe_neck": neck_part(), "fs90r": c.fs90r_dummy(),
            "horn": c.horn_dummy(), "stack": stack_dummy()}


def check():
    hits = []
    shapes = body_shapes()
    # 部品どうし(ﾈｼﾞ止め面以外で重なっていないか)
    for a, bb_ in (("giraffe_bay", "giraffe_neck"), ("giraffe_bay", "fs90r"), ("giraffe_neck", "fs90r"),
                   ("giraffe_neck", "stack"), ("giraffe_bay", "stack")):
        v = (shapes[a] ^ shapes[bb_]).volume()
        if v > 0.02:
            hits.append(("body", a, bb_, round(v, 3)))
    for deg in range(0, 360, 10):
        th = math.radians(deg)
        for inst in b.walker_instances(th):
            s = d.apply(b.shape_of(inst.part), inst.matrix)
            for k, m in shapes.items():
                if k == "horn":
                    continue
                v = (s ^ m).volume()
                if v > 0.02:
                    hits.append(("walk", deg, inst.name, k, round(v, 3)))
    st = b.stand_part()
    for deg in range(0, 360, 15):
        M = d.translation(0, 0, b.ST_DZ) @ d.rot_z(math.radians(deg))
        for k, m in shapes.items():
            if k == "horn":
                continue
            v = (st ^ d.apply(m, M)).volume()
            if v > 0.02:
                hits.append(("stand", deg, k, round(v, 3)))
    return hits


if __name__ == "__main__":
    import json
    for k, f in (("giraffe_bay", bay_part), ("giraffe_neck", neck_part)):
        s = f()
        bb = s.bounding_box()
        print(k, [round(bb[i + 3] - bb[i], 1) for i in range(3)], round(s.volume() / 1000, 1), "cm3", s.status(),
              "genus", s.genus())
    print("head top z", round(SHELF_TOP + c.CM_W, 1), "stack y", round(STACK_Y0, 1), round(STACK_Y1, 1))
    print(json.dumps(check(), ensure_ascii=False))
