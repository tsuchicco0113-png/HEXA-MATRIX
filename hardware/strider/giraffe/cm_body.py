"""案1「ﾌｸﾛｳ首」: CoreMatrix + 18350x2 ﾍﾞｰｽ + FS90R を 1 つの体ﾓｼﾞｭｰﾙにまとめる(ﾗﾌ設計)。

体 (cm_body)   : 下半分 = FS90R を軸下向きに吊るﾍﾞｲ、上半分 = CoreMatrix ｽﾀｯｸを立てて載せる受け。
                 底からはｻｰﾎﾞのｹｰｽ先端とﾎｰﾝだけが出る。配線は全部体の中。
ﾄﾞｯｸ (dock_yoke): 歩行台側。cm_yoke から天板を取り、ｶﾗｰの上に受けﾘﾝｸﾞと回り止めﾋﾟﾝ 2 本。
                 体を載せるとﾋﾟﾝで体が止まり、ﾎｰﾝが horn_hub を回す → 歩く。
台座 (desk_stand): 机用。中心にﾎｰﾝを固定するﾎﾟｹｯﾄ、外周に体が滑るﾘﾝｸﾞ。ﾎｰﾝが止まるので体が回る → 自転。

座標は design.py / cm_variant.py と同じ(歩行台に載せた状態)。
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from manifold3d import CrossSection, JoinType, Manifold

import design as d
import cm_variant as c
from design import box, circle, cyl, rect

# ---------------------------------------------------------------- 体
FLOOR_BOT = c.PLATE_BOT          # 46.5  体の底面(= 旧 cm_yoke 天板の下面)
FLOOR_TOP = c.PLATE_TOP          # 49.5  ｻｰﾎﾞの耳が載る面
SERVO_TOP = FLOOR_TOP + c.SV_EAR_HI   # 68.7 逆さｻｰﾎﾞの底(上を向く)
WALL = 2.0
CLR = 0.3
IN_X = c.CM_W / 2 + CLR          # 内のり半幅(X)
DEPTH = c.CM_DEPTH               # 38.3 ｽﾀｯｸの奥行き
IN_Y = DEPTH / 2 + CLR           # 内のり半幅(Y)。ｽﾀｯｸは回転軸の真上に中心を置く
OUT_X, OUT_Y = IN_X + WALL, IN_Y + WALL
BODY_R = 6.0                     # 外形の角 R
SHELF_T = 2.4
SHELF_BOT = SERVO_TOP + 0.6
SHELF_TOP = SHELF_BOT + SHELF_T  # ｽﾀｯｸの載る面
STACK_Y0, STACK_Y1 = -DEPTH / 2, DEPTH / 2      # 背面(ﾍﾞｰｽ底) / 前面(LED)
GRIP_H = 12.0                    # ｽﾀｯｸ下端をつかむ壁の高さ
GRIP_SIDE_Y1 = STACK_Y0 + c.CM_BASE_H - 1.0     # 側壁はﾍﾞｰｽ部分だけ(CoreMatrix 側面のﾎﾟｰﾄを塞がない)
PIN_XY = [(22.0, -14.0), (-22.0, -14.0)]        # 回り止めﾋﾟﾝ(前後非対称 → 顔の向きが 1 通りに決まる)
PIN_R, PIN_H = 2.0, 2.6

# ---------------------------------------------------------------- ﾄﾞｯｸ
DOCK_T = 3.0
DOCK_TOP = FLOOR_BOT
DOCK_BOT = DOCK_TOP - DOCK_T
DOCK_HOLE_R = 18.6               # ｻｰﾎﾞのｹｰｽ先端(角まで r 17.5)が通る穴

# ---------------------------------------------------------------- 机用台座(台座ﾛｰｶﾙ: 底 z=0)
ST_H = 16.0                      # 体の底面が載る高さ
ST_R0, ST_R1 = 37.0, 31.0        # 下と上の半径(ゆるいﾃｰﾊﾟｰ)
ST_RIM = (23.0, 28.0)            # 体が滑るﾘﾝｸﾞ(0.6 mm 盛り上げ)
ST_DZ = ST_H + 0.6 - FLOOR_BOT   # 体の座標(歩行台基準) → 台座ﾛｰｶﾙへのずらし


def _rrect(hx: float, hy: float, r: float) -> CrossSection:
    return rect(-hx + r, hx - r, -hy + r, hy - r).offset(r, JoinType.Round, 2.0, 48)


@lru_cache(maxsize=None)
def body_part() -> Manifold:
    outer = _rrect(OUT_X, OUT_Y, BODY_R)
    inner = _rrect(IN_X, IN_Y, BODY_R - WALL)
    # ﾍﾞｲ(床 + 4 周の壁) ― 上は開いていて、ｻｰﾎﾞは上から棚の窓ごしに入れる
    bay = outer.extrude(SHELF_BOT - FLOOR_BOT).translate((0, 0, FLOOR_BOT))
    bay -= inner.extrude(SHELF_BOT - FLOOR_TOP + 1).translate((0, 0, FLOOR_TOP))
    bay -= c.servo_cutout().extrude(FLOOR_TOP - FLOOR_BOT + 2).translate((0, 0, FLOOR_BOT - 1))
    bx = c.servo_body_x()
    for sx in (1, -1):
        bay -= cyl(c.SV_SCREW_PILOT, FLOOR_BOT - 1, FLOOR_TOP + 1, 24).translate((bx + sx * c.SV_EAR_PITCH / 2, 0, 0))
    for x, y in PIN_XY:   # ﾄﾞｯｸのﾋﾟﾝ穴
        bay -= cyl(PIN_R + 0.25, FLOOR_BOT - 1, FLOOR_BOT + PIN_H + 0.4, 32).translate((x, y, 0))
    # 棚(ｽﾀｯｸを受ける)。中央にｻｰﾎﾞが通る窓、後ろにｹｰﾌﾞﾙ穴
    shelf = outer.extrude(SHELF_T).translate((0, 0, SHELF_BOT))
    win = rect(bx - c.SV_EAR_SPAN / 2 - 0.8, bx + c.SV_EAR_SPAN / 2 + 0.8, -c.SV_W / 2 - 0.8, c.SV_W / 2 + 0.8)
    shelf -= win.extrude(SHELF_T + 2).translate((0, 0, SHELF_BOT - 1))
    shelf -= box(12.0, 22.0, STACK_Y0 + 1.0, STACK_Y0 + 9.0, SHELF_BOT - 1, SHELF_TOP + 1)
    # ｽﾀｯｸ下端をつかむ壁: 背面は全幅、側面はﾍﾞｰｽ部分だけ、前は低いﾘｯﾌﾟ
    grip = Manifold()
    grip += box(-OUT_X + BODY_R, OUT_X - BODY_R, -OUT_Y, STACK_Y0 - CLR, SHELF_TOP - 0.01, SHELF_TOP + GRIP_H)
    for sx in (1, -1):
        x_in, x_out = sx * IN_X, sx * OUT_X
        grip += box(min(x_in, x_out), max(x_in, x_out), -OUT_Y + BODY_R, GRIP_SIDE_Y1, SHELF_TOP - 0.01, SHELF_TOP + GRIP_H)
    grip += box(-IN_X + 7, IN_X - 7, STACK_Y1 + CLR, OUT_Y, SHELF_TOP - 0.01, SHELF_TOP + 2.5)
    # 背面の角は外形の R に合わせて丸める
    grip = grip ^ outer.extrude(GRIP_H + 1).translate((0, 0, SHELF_TOP - 0.5))
    return bay + shelf + grip


@lru_cache(maxsize=None)
def dock_part() -> Manifold:
    """cm_yoke の天板を外し、ｶﾗｰの上に体の受けﾘﾝｸﾞと回り止めﾋﾟﾝを付けたもの。"""
    yoke = c._collar_profile().revolve(128)
    outline = circle(d.COLLAR_R_OUT, seg=128)
    outside = CrossSection.circle(80, 96) - CrossSection.circle(d.COLLAR_R_IN, 128)
    columns, cuts = Manifold(), Manifold()
    for cx, cy in c._lugs():
        lug = rect(cx - d.PLATE_T / 2 - 2.6, cx + d.PLATE_T / 2 + 2.6, cy - 6.2, cy + 6.2)
        foot = lug ^ outside
        outline += foot
        columns += foot.extrude(DOCK_BOT - d.COLLAR_Z0 + 0.01).translate((0, 0, d.COLLAR_Z0))
        slot = rect(cx - d.PLATE_T / 2 - 0.2, cx + d.PLATE_T / 2 + 0.2, cy - d.TENON_W / 2 - 0.2, cy + d.TENON_W / 2 + 0.2)
        cuts += slot.extrude(DOCK_TOP - d.COLLAR_Z0 + 2).translate((0, 0, d.COLLAR_Z0 - 1))
        relief = rect(cx - d.PLATE_T / 2 - 0.2, cx + d.PLATE_T / 2 + 0.2,
                      cy - d.TENON_W / 2 - d.SNAP_BARB - 0.4, cy + d.TENON_W / 2 + d.SNAP_BARB + 0.4)
        cuts += relief.extrude(3.4).translate((0, 0, d.COLLAR_Z0 + d.COLLAR_LUG_T))
    ring = (outline - circle(DOCK_HOLE_R, seg=96)).extrude(DOCK_T).translate((0, 0, DOCK_BOT))
    body = yoke + columns + ring
    for x, y in PIN_XY:
        body += cyl(PIN_R, DOCK_TOP - 0.01, DOCK_TOP + PIN_H, 32).translate((x, y, 0))
    return body - cuts


@lru_cache(maxsize=None)
def stand_part() -> Manifold:
    """机用台座(台座ﾛｰｶﾙ座標、底 z=0)。ﾎｰﾝを固定し、体はﾘﾝｸﾞの上を回る。"""
    prof = CrossSection([[(0, 0), (ST_R0, 0), (ST_R0, 2.0), (ST_R1, ST_H), (0, ST_H)]])
    base = prof.revolve(128)
    base += (circle(ST_RIM[1], seg=128) - circle(ST_RIM[0], seg=128)).extrude(0.6).translate((0, 0, ST_H - 0.01))
    horn_face = c.HORN_FACE_Z + ST_DZ
    pocket_floor = horn_face - 1.5
    base -= cyl(DOCK_HOLE_R, horn_face + c.HORN_ARM_T + 0.6, ST_H + 1, 96)       # ｻｰﾎﾞのｹｰｽ先端が回る空間
    half = c.HORN_W / 2 + c.HORN_CLR
    slot = d.hull2(circle(half, -(c.HORN_L / 2 - c.HORN_W / 2)), circle(half, c.HORN_L / 2 - c.HORN_W / 2))
    pocket = slot.extrude(ST_H - pocket_floor + 1).translate((0, 0, pocket_floor))
    base -= pocket
    base -= d.apply(pocket, d.rot_z(math.pi / 2))
    base -= cyl(3.0, pocket_floor - 2.0, pocket_floor + 0.1)
    base -= cyl(c.HORN_BOSS_R + 0.6, pocket_floor, ST_H + 1, 48)
    return base


# ---------------------------------------------------------------- ﾀﾞﾐｰ(体の座標)
@lru_cache(maxsize=None)
def stack_dummy() -> Manifold:
    sec = c._stack_section(0.0).translate((0, SHELF_TOP))
    return d._along_y(sec, STACK_Y0, STACK_Y1)


BODY_GROUP = ("cm_body", "fs90r", "horn", "stack")   # 体ﾓｼﾞｭｰﾙとして一緒に動くもの


def body_shapes():
    return {"cm_body": body_part(), "fs90r": c.fs90r_dummy(), "horn": c.horn_dummy(), "stack": stack_dummy()}


def walker_instances(theta: float):
    """歩行台(原作から yoke/socket_frame/ｽﾀｯｸﾁｬﾝを外し、horn_hub と dock を足したもの)。"""
    out = [i for i in d.instances(theta, with_stackchan=False) if i.part not in ("yoke", "socket_frame")]
    out += [d.Instance("horn_hub", "horn_hub", d.rot_z(-theta), "table"),
            d.Instance("dock_yoke", "dock_yoke", np.eye(4), "chassis")]
    return out


def shape_of(key: str) -> Manifold:
    if key == "horn_hub":
        return c.horn_hub_part()
    if key == "dock_yoke":
        return dock_part()
    if key == "desk_stand":
        return stand_part()
    if key in body_shapes():
        return body_shapes()[key]
    return d.part_shape(key)


def check():
    """体を載せた歩行 1 周の干渉、台座での回転 1 周の干渉を調べる。"""
    hits = []
    body = {k: v for k, v in body_shapes().items()}
    for deg in range(0, 360, 10):
        th = math.radians(deg)
        for inst in walker_instances(th):
            s = d.apply(shape_of(inst.part), inst.matrix)
            for k, b in body.items():
                if k == "horn":
                    continue
                v = (s ^ b).volume()
                if v > 0.02:
                    hits.append(("walk", deg, inst.name, k, round(v, 3)))
        # ﾎｰﾝは horn_hub と一緒に回る
        hv = (d.apply(c.horn_dummy(), d.rot_z(-th)) ^ d.apply(c.horn_hub_part(), d.rot_z(-th))).volume()
        if hv > 0.02:
            hits.append(("walk", deg, "horn_hub", "horn", round(hv, 3)))
    st = stand_part()
    for deg in range(0, 360, 15):
        M = d.translation(0, 0, ST_DZ) @ d.rot_z(math.radians(deg))
        for k, b in body.items():
            if k == "horn":
                continue
            v = (st ^ d.apply(b, M)).volume()
            if v > 0.02:
                hits.append(("stand", deg, "desk_stand", k, round(v, 3)))
    hv = (st ^ d.apply(c.horn_dummy(), d.translation(0, 0, ST_DZ))).volume()
    if hv > 0.02:
        hits.append(("stand", 0, "desk_stand", "horn", round(hv, 3)))
    return hits


if __name__ == "__main__":
    import json
    for k, f in (("cm_body", body_part), ("dock_yoke", dock_part), ("desk_stand", stand_part)):
        s = f()
        bb = s.bounding_box()
        print(k, [round(bb[i + 3] - bb[i], 1) for i in range(3)], round(s.volume() / 1000, 1), "cm3", s.status())
    print("stack top z", round(SHELF_TOP + c.CM_W, 1), " body floor", FLOOR_BOT)
    print(json.dumps(check(), ensure_ascii=False))
