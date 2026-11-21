"""受け台 v5「ﾀﾜｰ」: 今の cm_yoke + FS90R のまま、CoreMatrix を軸の真上へ載せて重心を真ん中に。

cm_cradle (ｻｰﾎﾞの前に立てる) の代わりに、ｻｰﾎﾞにかぶせる筒(ｽﾘｰﾌﾞ)の上に棚を作り、そこへｽﾀｯｸを立てる。
- 天板の 2 つの角穴は同じ(受け台と同じｽﾅｯﾌﾟほぞで留める)。ｻｰﾎﾞを天板にﾈｼﾞ止めしてから、上からかぶせる
- 頭の受けは受け台 v4 と同じ(すきま 0.5、つぶしﾘﾌﾞ 7 本、短い側壁、貫通しない配線溝 + 溝の中のｹｰﾌﾞﾙ穴)
- 側面に窓(配線の出入りとﾄﾞﾗｲﾊﾞｰ用)
- 造形は受け台と同じく背面を下(棚・ｽﾘｰﾌﾞ・ほぞが全部ｻﾎﾟｰﾄなし)
座標は cm_variant と同じ。
"""
from __future__ import annotations

import math
import os
from functools import lru_cache

import numpy as np
from manifold3d import CrossSection, JoinType, Manifold

import design as d
import cm_variant as c
from design import box, rect

DY = float(os.environ.get("TOWER_DY", 4.0))     # ｽﾀｯｸ中心を軸から前へ(前の角穴にほぞを掛けるため少しだけ)
CLR = 0.5
WALL = 2.0
R_OUT = 6.0
IN_X = c.CM_W / 2 + CLR
IN_Y = c.CM_DEPTH / 2 + CLR
OUT_X, OUT_Y = IN_X + WALL, IN_Y + WALL
Z0 = c.PLATE_TOP                                  # 天板の上面
SERVO_TOP = c.PLATE_TOP + c.SV_EAR_HI             # 逆さｻｰﾎﾞの底(上を向く) 68.7
SHELF_T = 3.2
SHELF_BOT = SERVO_TOP + 0.6
SHELF_TOP = SHELF_BOT + SHELF_T
GROOVE_D, GROOVE_W = 1.6, 7.0
BACK_H, SIDE_H, LIP_H = 22.0, 14.0, 2.5
STACK_Y0 = -c.CM_DEPTH / 2 + DY                  # ｽﾀｯｸ背面(ﾍﾞｰｽ底)
STACK_Y1 = STACK_Y0 + c.CM_DEPTH                 # 前面(LED)


def _rr(hx, hy, r, cx=0.0, cy=0.0) -> CrossSection:
    return rect(cx - hx + r, cx + hx - r, cy - hy + r, cy + hy - r).offset(r, JoinType.Round, 2.0, 48)


def outline(inset: float = 0.0) -> CrossSection:
    return _rr(OUT_X - inset, OUT_Y - inset, R_OUT - inset, 0, DY)


@lru_cache(maxsize=None)
def tower_part() -> Manifold:
    # ｽﾘｰﾌﾞ(ｻｰﾎﾞにかぶせる筒)
    sleeve = (outline() - outline(WALL)).extrude(SHELF_BOT - Z0).translate((0, 0, Z0))
    # 側面の窓(配線・ﾄﾞﾗｲﾊﾞｰ)。下 4 mm と上 3 mm は残して筒の強さを保つ
    for sx in (1, -1):
        sleeve -= box(sx * OUT_X - 3 if sx > 0 else -OUT_X - 1, sx * OUT_X + 1 if sx > 0 else -OUT_X + 3,
                      DY - 7.0, DY + 7.0, Z0 + 4.0, SHELF_BOT - 3.0)
    # ほぞの台座(天板の角穴の上)
    pads = Manifold()
    for x, y in c.CR_TENONS:
        pads += box(x - 5.0, x + 5.0, y - c.CR_TENON_T / 2 - 1.5, y + c.CR_TENON_T / 2 + 1.5, Z0, Z0 + 4.0)
    # 棚 + 配線溝(貫通しない) + 溝の中のｹｰﾌﾞﾙ穴
    shelf = outline().extrude(SHELF_T).translate((0, 0, SHELF_BOT))
    gy1 = STACK_Y0 + c.CM_BASE_H + 0.5
    shelf -= box(-OUT_X - 1, OUT_X + 1, gy1 - GROOVE_W, gy1, SHELF_TOP - GROOVE_D, SHELF_TOP + 1)
    shelf -= box(-10.0, 10.0, gy1 - GROOVE_W + 1.0, gy1 - 1.0, SHELF_BOT - 1, SHELF_TOP + 1)
    # 頭の受け: 背板は全幅、側壁はﾍﾞｰｽの後ろ寄りだけ、前は低いﾘｯﾌﾟ
    grip = box(-OUT_X + R_OUT, OUT_X - R_OUT, DY - OUT_Y, STACK_Y0 - CLR, SHELF_TOP - 0.01, SHELF_TOP + BACK_H)
    for sx in (1, -1):
        grip += box(min(sx * IN_X, sx * OUT_X), max(sx * IN_X, sx * OUT_X), DY - OUT_Y + R_OUT,
                    STACK_Y0 + c.CM_BASE_H - 10.0, SHELF_TOP - 0.01, SHELF_TOP + SIDE_H)
    grip += box(-IN_X + 7, IN_X - 7, STACK_Y1 + CLR, DY + OUT_Y, SHELF_TOP - 0.01, SHELF_TOP + LIP_H)
    grip = grip ^ outline().extrude(BACK_H + 1).translate((0, 0, SHELF_TOP - 0.5))
    # ｽﾀｯｸ下角 R5 に沿うすみ肉(受け台と同じ)。配線溝の幅だけ切る
    sec = c._stack_section(CLR).translate((0, SHELF_TOP))
    space = d._along_y(sec, STACK_Y0 - CLR, STACK_Y1 + CLR)
    fillet = box(-IN_X, IN_X, STACK_Y0 - CLR, STACK_Y1 + CLR, SHELF_TOP - 0.01, SHELF_TOP + c.CM_R) - space
    fillet -= box(-OUT_X - 1, OUT_X + 1, gy1 - GROOVE_W, gy1, SHELF_TOP - 1, SHELF_TOP + c.CM_R + 1)
    # つぶしﾘﾌﾞ: 背板 3 本で前のﾘｯﾌﾟへ押し、側壁 2 本ずつで挟む
    gap = CLR * 2
    ribs = Manifold()
    for x in (-14.0, 0.0, 14.0):
        ribs += c._rib(x, STACK_Y0 - CLR, 0, 1, SHELF_TOP + c.CM_R, SHELF_TOP + BACK_H, gap + c.RIB_INTERF)
    for sx in (1, -1):
        for y in (STACK_Y0 + 4.0, STACK_Y0 + c.CM_BASE_H - 14.0):
            ribs += c._rib(sx * IN_X, y, -sx, 0, SHELF_TOP + c.CM_R, SHELF_TOP + SIDE_H, (gap + c.RIB_INTERF) / 2)
    part = sleeve + pads + shelf + grip + fillet + ribs
    # 天板の角穴へのｽﾅｯﾌﾟほぞ(受け台と同じ形)
    for x, y in c.CR_TENONS:
        tenon = d._snap_tenon(d.TENON_W, c.PLATE_T + 0.15, 4.5).mirror((0, 1)).translate((x, Z0 + 0.01))
        part += d._along_y(tenon, y - c.CR_TENON_T / 2, y + c.CR_TENON_T / 2)
    return part


@lru_cache(maxsize=None)
def stack_dummy() -> Manifold:
    """ﾘﾌﾞで前のﾘｯﾌﾟへ押し付けられた位置"""
    sec = c._stack_section(0.0).translate((0, SHELF_TOP))
    return d._along_y(sec, STACK_Y0 + CLR, STACK_Y1 + CLR)


def instances(theta: float):
    out = [i for i in c.instances(theta) if i.part not in ("cm_cradle", "cm_stack")]
    out += [d.Instance("cm_tower", "cm_tower", np.eye(4), "chassis"),
            d.Instance("cm_stack", "tower_stack", np.eye(4), "chassis")]
    return out


def shape_of(key: str) -> Manifold:
    if key == "cm_tower":
        return tower_part()
    if key == "tower_stack":
        return stack_dummy()
    return c.shape_of(key)


def collisions(theta: float, tol: float = 0.02):
    placed = [(i, d.apply(shape_of(i.part), i.matrix)) for i in instances(theta)]
    hits = []
    for a in range(len(placed)):
        for b_ in range(a + 1, len(placed)):
            ia, sa = placed[a]
            ib, sb = placed[b_]
            if ia.group == ib.group and ia.group != "chassis":
                continue
            if frozenset((ia.name, ib.name)) in c.EXPECTED or frozenset((ia.name, ib.name)) == frozenset(("cm_tower", "cm_stack")):
                continue
            if frozenset((ia.name, ib.name)) == frozenset(("cm_tower", "cm_yoke")):
                v = (sa ^ sb).volume()            # ほぞは天板の角穴に入る。天板と重なっていないかだけ見る
                if v > tol:
                    hits.append((ia.name, ib.name, round(v, 3)))
                continue
            bb_a, bb_b = sa.bounding_box(), sb.bounding_box()
            if not all(bb_a[k] < bb_b[k + 3] and bb_b[k] < bb_a[k + 3] for k in range(3)):
                continue
            v = (sa ^ sb).volume()
            if v > tol:
                hits.append((ia.name, ib.name, round(v, 3)))
    return hits


PRINT_POSE = (d.mat([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0]]), "背面を下")


if __name__ == "__main__":
    import json
    t = tower_part()
    bb = t.bounding_box()
    print("cm_tower", [round(bb[i + 3] - bb[i], 1) for i in range(3)], round(t.volume() / 1000, 1), "cm3",
          "pieces", len(t.decompose()))
    print("stack top z", round(SHELF_TOP + c.CM_W, 1), "stack y", round(STACK_Y0 + CLR, 2), round(STACK_Y1 + CLR, 2))
    print("rib bite", round((t ^ stack_dummy()).volume(), 2))
    hits = []
    for deg in range(0, 360, 10):
        hits += [(deg,) + h for h in collisions(math.radians(deg))]
    print(json.dumps(hits[:20], ensure_ascii=False))
