"""CoreMatrix + FEETECH FS90R 版の Stackchan Strider(HEXA STAGE 改造)。

原作の「スタックチャンの首サーボで土台を回す」しくみを、次の 3 部品に置き換える。
脚・側板・デッキ・歯車・ピニオン・シャフト・クランク・クリップは原作のまま使う。

  horn_hub   : ソケット枠の代わり。ターンテーブル歯車に同じツメで載り、上面のポケットに FS90R のホーンが入る
  cm_yoke    : ヨークの代わり。カラー(浮き止め)はそのまま、上を天板でふさいで FS90R を軸下向きに吊る
  cm_cradle  : 天板の前半分に載る受け台。CoreMatrix + 18350x2 ベースを立てて(顔を前に)入れる

座標は design.py と同じ(X = 右, Y = 前, Z = 上, 原点 = ヨー軸とクランク軸の交点)。
使い方: python walker/cm_variant.py   → out/cm/ に STL・干渉チェック結果・プレビュー画像
"""
from __future__ import annotations

import json
import math
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from manifold3d import CrossSection, JoinType, Manifold

import design as d
from design import box, circle, cyl, polygon, rect

# ---------------------------------------------------------------- FS90R(FEETECH 仕様書 2020-12 の図面)
SV_L = 22.5          # 本体の長さ
SV_W = 12.1          # 本体の幅
SV_CASE_TOP = 27.7   # 底面からケース上面(出力軸の根元)
SV_SHAFT_TOP = 30.7  # 底面から出力軸の先端
SV_EAR_LO = 16.7     # 底面から取付耳の下面
SV_EAR_HI = 19.2     # 底面から取付耳の上面(天板に当たる面)
SV_EAR_SPAN = 32.3   # 耳の全長
SV_EAR_PITCH = 27.7  # 耳穴ピッチ ← 図面から推定。実測して直す
SV_HOLE_TO_SHAFT = 8.7  # 耳穴から出力軸の中心まで
SV_SHAFT_D = 4.86    # 21T スプライン
SV_SHAFT_OFF = SV_EAR_PITCH / 2 - SV_HOLE_TO_SHAFT  # 本体中心から出力軸までのずれ(約 5.15)
SV_CLR = 0.3         # 天板の角穴と本体のすきま(片側)
SV_SCREW_PILOT = 0.85  # 付属タッピングネジ(M2 相当)の下穴半径

# 付属の「一文字ホーン(両側)」27.5 x 7
HORN_L, HORN_W = 27.5, 7.0
HORN_ARM_T = 1.6     # 腕の厚み(推定)。ポケットが深いので多少違っても入る
HORN_BOSS_R = 3.5
HORN_CLR = 0.3       # ポケットとホーンのすきま(片側)

# ---------------------------------------------------------------- 高さの決め方
# 出力軸の先端の高さを決め、そこから天板とホーンの位置を出す
TIP_Z = 38.0                                 # 出力軸の先端(下向き)
HORN_FACE_Z = TIP_Z - 0.3                    # ホーンの外側の面(下面)
PLATE_T = 3.0
PLATE_TOP = TIP_Z + (SV_SHAFT_TOP - SV_EAR_HI)  # 耳の当たり面 = 天板上面
PLATE_BOT = PLATE_TOP - PLATE_T
HUB_TOP = d.FRAME_Z1                         # ハブ上面(原作のソケット枠の上面と同じ。カラーの返しがここを押さえる)
POCKET_FLOOR = HORN_FACE_Z - 1.5             # ポケットの底(ホーンの下に 1.5 mm の逃げ)

# ---------------------------------------------------------------- CoreMatrix + 18350x2 ベース
CM_W = 54.0
CM_R = 5.0
CM_BASE_H = 26.7         # 18350x2 ベースの高さ (.scad の echo。スタックチャン仕様 = 電池部 21.7 + 配線ギャラリー 5)
CM_DEPTH = CM_BASE_H + 11.6   # + CoreMatrix 厚み (背面プレートを外すと 1mm ほど薄いが、前の縁で押さえる)
CM_CLR = 0.3
CR_FLOOR_T = 2.4
CR_WALL = 2.0
CR_BACK_Y = SV_W / 2 + SV_CLR + 1.0          # 受け台の背板の背面(サーボの前)
CM_Y0 = CR_BACK_Y + CR_WALL + CM_CLR         # スタックの背面(ベース底面)
CM_Y1 = CM_Y0 + CM_DEPTH                     # スタックの前面(LED)
CR_SIDE_H = 14.0
CR_BACK_H = 22.0
CR_LIP_H = 2.5
CR_SIDE_Y1 = CM_Y0 + CM_BASE_H - 1.0         # 側壁はベース部分だけ(CoreMatrix 側面の USB-C・Grove・ボタンを塞がない)
CR_TENONS = [(-20.0, 26.0), (20.0, 26.0)]    # 受け台を天板に留めるスナップほぞ(天板の下で返しが掛かる)
CR_TENON_T = 4.0                              # ほぞの厚み(Y)


def servo_body_x() -> float:
    """サーボ本体中心の X(出力軸 = 原点、本体は -X 側へ伸ばす)。"""
    return -SV_SHAFT_OFF


def servo_local_to_world() -> np.ndarray:
    """サーボのローカル(底面 z=0、軸先端 z=30.7、出力軸 = 原点)→ ワールド(軸下向き)。"""
    flip = d.mat([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0]])
    return d.translation(0, 0, PLATE_TOP + SV_EAR_HI) @ flip


# ---------------------------------------------------------------- 印刷部品
@lru_cache(maxsize=None)
def horn_hub_part() -> Manifold:
    """ソケット枠の代わりのハブ(ターンテーブル歯車と一緒に回る)。"""
    chamfer = 2.0
    profile = polygon([(30.0, d.TABLE_Z1), (d.TABLE_R, d.TABLE_Z1), (d.TABLE_R, HUB_TOP - chamfer),
                       (d.TABLE_R - chamfer, HUB_TOP), (30.0, HUB_TOP)])
    ring = profile.revolve(128)
    center = cyl(18.0, d.TABLE_Z1, HUB_TOP, 96)
    spokes = Manifold()
    for ang in (45, 135, 225, 315):
        spoke = box(0, 31.0, -4.0, 4.0, d.TABLE_Z1, HUB_TOP)
        spokes += d.apply(spoke, d.rot_z(math.radians(ang)))
    hub = ring + center + spokes
    # ツメ(原作のソケット枠と同じ位置・寸法。歯車側の角穴に入って回り止め)
    for x, y in d.FRAME_TABS:
        hub += box(x - d.TAB_L / 2, x + d.TAB_L / 2, y - d.TAB_W / 2, y + d.TAB_W / 2, d.TABLE_Z0 + 0.2, d.TABLE_Z1 + 0.01)
    # 一文字ホーンのポケット(腕が壁に当たって回る)と、中心のネジ頭の逃げ
    half = HORN_W / 2 + HORN_CLR
    slot = d.hull2(circle(half, -(HORN_L / 2 - HORN_W / 2)), circle(half, HORN_L / 2 - HORN_W / 2))
    hub -= slot.extrude(HUB_TOP - POCKET_FLOOR + 1).translate((0, 0, POCKET_FLOOR))
    # 十字ホーンでも入るよう、直交方向にも同じ溝(32 x 4 の腕は 7 幅の溝に収まる)
    hub -= d.apply(slot.extrude(HUB_TOP - POCKET_FLOOR + 1).translate((0, 0, POCKET_FLOOR)), d.rot_z(math.pi / 2))
    hub -= cyl(3.0, POCKET_FLOOR - 2.0, POCKET_FLOOR + 0.1)
    return hub


def _collar_profile() -> CrossSection:
    lip_r = d.TABLE_R - 2.0 + 0.6
    lip_z = d.FRAME_Z1 - 2.0 - (d.COLLAR_R_IN - d.TABLE_R) + 0.6
    return polygon([
        (d.COLLAR_R_IN, d.COLLAR_Z0),
        (d.COLLAR_R_OUT, d.COLLAR_Z0),
        (d.COLLAR_R_OUT, PLATE_BOT + 0.01),
        (lip_r, PLATE_BOT + 0.01),
        (lip_r, lip_z + (d.COLLAR_R_IN - lip_r)),
        (d.COLLAR_R_IN, lip_z),
    ])


def _lugs():
    """側板のツノを受ける耳 (x 中心, y 中心)。"""
    for sx in (1, -1):
        for sy in (1, -1):
            yield sx * (d.PLATE_IN + d.PLATE_T / 2), sy * d.HORN_Y


def servo_cutout() -> CrossSection:
    bx = servo_body_x()
    return rect(bx - SV_L / 2 - SV_CLR, bx + SV_L / 2 + SV_CLR, -SV_W / 2 - SV_CLR, SV_W / 2 + SV_CLR)


@lru_cache(maxsize=None)
def cm_yoke_part() -> Manifold:
    """カラー + 天板 + サーボ取付。造形は天板を下にして逆さに置く。"""
    yoke = _collar_profile().revolve(128)
    outline = circle(d.COLLAR_R_OUT, seg=128)
    outside = CrossSection.circle(80, 96) - CrossSection.circle(d.COLLAR_R_IN, 128)
    columns = Manifold()
    cuts = Manifold()
    for cx, cy in _lugs():
        lug = rect(cx - d.PLATE_T / 2 - 2.6, cx + d.PLATE_T / 2 + 2.6, cy - 6.2, cy + 6.2)
        foot = lug ^ outside
        outline += foot
        # 耳を天板まで柱にする(逆さ造形で宙に浮かせない)
        columns += foot.extrude(PLATE_BOT - d.COLLAR_Z0 + 0.01).translate((0, 0, d.COLLAR_Z0))
        slot = rect(cx - d.PLATE_T / 2 - 0.2, cx + d.PLATE_T / 2 + 0.2, cy - d.TENON_W / 2 - 0.2, cy + d.TENON_W / 2 + 0.2)
        cuts += slot.extrude(PLATE_TOP - d.COLLAR_Z0 + 2).translate((0, 0, d.COLLAR_Z0 - 1))
        # ほぞの返しが開く逃げ(返しの高さ 2.8 mm)
        relief = rect(cx - d.PLATE_T / 2 - 0.2, cx + d.PLATE_T / 2 + 0.2,
                      cy - d.TENON_W / 2 - d.SNAP_BARB - 0.4, cy + d.TENON_W / 2 + d.SNAP_BARB + 0.4)
        cuts += relief.extrude(3.4).translate((0, 0, d.COLLAR_Z0 + d.COLLAR_LUG_T))
    plate = outline.extrude(PLATE_T).translate((0, 0, PLATE_BOT))
    body = yoke + columns + plate
    # サーボの角穴と耳のネジ下穴
    body -= servo_cutout().extrude(PLATE_T + 2).translate((0, 0, PLATE_BOT - 1))
    bx = servo_body_x()
    for sx in (1, -1):
        body -= cyl(SV_SCREW_PILOT, PLATE_BOT - 1, PLATE_TOP + 1, 24).translate((bx + sx * SV_EAR_PITCH / 2, 0, 0))
    # 受け台のほぞ穴
    for x, y in CR_TENONS:
        body -= box(x - d.TENON_W / 2 - 0.2, x + d.TENON_W / 2 + 0.2, y - CR_TENON_T / 2 - 0.2, y + CR_TENON_T / 2 + 0.2,
                    PLATE_BOT - 1, PLATE_TOP + 1)
    # 後ろ半分の肉抜き(サーボと柱を避ける)
    for sx in (1, -1):
        win = d.hull2(circle(5.0, sx * 12.0, -20.0), circle(5.0, sx * 24.0, -20.0), circle(5.0, sx * 12.0, -30.0))
        body -= win.extrude(PLATE_T + 2).translate((0, 0, PLATE_BOT - 1))
    body -= d.hull2(circle(4.0, -4.0, -16.0), circle(4.0, 4.0, -16.0), circle(4.0, 0, -34.0)).extrude(PLATE_T + 2).translate((0, 0, PLATE_BOT - 1))
    return body - cuts


def _stack_section(clr: float) -> CrossSection:
    """スタックの正面形(x, z)= 54 角 R5。"""
    half = CM_W / 2 + clr
    r = CM_R + clr
    return rect(-half + r, half - r, r, 2 * half - r).offset(r, JoinType.Round, 2.0, 48)


@lru_cache(maxsize=None)
def cm_cradle_part() -> Manifold:
    """CoreMatrix + バッテリーベースを立てて入れる受け台。床の下の 2 本のスナップほぞを天板の角穴に押し込んで留める。"""
    z0 = PLATE_TOP
    fz = z0 + CR_FLOOR_T
    x_out = CM_W / 2 + CM_CLR + CR_WALL
    y_back, y_front = CR_BACK_Y, CM_Y1 + CM_CLR + 1.6
    floor = box(-x_out, x_out, y_back, y_front, z0, fz)
    back = box(-x_out, x_out, y_back, CR_BACK_Y + CR_WALL, fz - 0.01, fz + CR_BACK_H)
    sides = Manifold()
    for sx in (1, -1):
        x_in = sx * (CM_W / 2 + CM_CLR)
        sides += box(min(x_in, sx * x_out), max(x_in, sx * x_out), y_back, CR_SIDE_Y1, fz - 0.01, fz + CR_SIDE_H)
    lip = box(-CM_W / 2 + 6, CM_W / 2 - 6, CM_Y1 + CM_CLR, y_front, fz - 0.01, fz + CR_LIP_H)
    cradle = floor + back + sides + lip
    # スタックの下角 R5 に沿わせた床のすみ肉(座りを良くする)
    section = _stack_section(CM_CLR).translate((0, fz))
    stack_space = d._along_y(section, CM_Y0 - CM_CLR, CM_Y1 + CM_CLR)
    fillet = box(-CM_W / 2 - CM_CLR, CM_W / 2 + CM_CLR, CM_Y0 - CM_CLR, CM_Y1 + CM_CLR, fz - 0.01, fz + CM_R)
    cradle += fillet - stack_space
    # 背板の配線穴(サーボのケーブルを前へ回す場合)と、側壁の指掛け
    cradle -= box(-30.0, -18.0, y_back - 1, CR_BACK_Y + CR_WALL + 1, fz + 3.0, fz + 9.0)
    # 床下のスナップほぞ(下向き)。断面は X-Z 面にあり、造形時(背板が下)はベッドと平行になる
    for x, y in CR_TENONS:
        tenon = d._snap_tenon(d.TENON_W, PLATE_T + 0.15, 4.5).mirror((0, 1)).translate((x, z0 + 0.01))
        cradle += d._along_y(tenon, y - CR_TENON_T / 2, y + CR_TENON_T / 2)
    return cradle


# ---------------------------------------------------------------- 表示・干渉確認用(印刷しない)
@lru_cache(maxsize=None)
def fs90r_dummy() -> Manifold:
    bx = servo_body_x()
    body = box(bx - SV_L / 2, bx + SV_L / 2, -SV_W / 2, SV_W / 2, 0, SV_CASE_TOP)
    ears = box(bx - SV_EAR_SPAN / 2, bx + SV_EAR_SPAN / 2, -SV_W / 2, SV_W / 2, SV_EAR_LO, SV_EAR_HI)
    for sx in (1, -1):
        ears -= cyl(1.1, SV_EAR_LO - 1, SV_EAR_HI + 1, 24).translate((bx + sx * SV_EAR_PITCH / 2, 0, 0))
    shaft = cyl(SV_SHAFT_D / 2, SV_CASE_TOP - 0.01, SV_SHAFT_TOP)
    return d.apply(body + ears + shaft, servo_local_to_world())


@lru_cache(maxsize=None)
def horn_dummy() -> Manifold:
    arm = d.hull2(circle(HORN_W / 2, -(HORN_L / 2 - HORN_W / 2)), circle(HORN_W / 2, HORN_L / 2 - HORN_W / 2))
    horn = arm.extrude(HORN_ARM_T).translate((0, 0, HORN_FACE_Z))
    boss_top = TIP_Z + (SV_SHAFT_TOP - SV_CASE_TOP) - 0.4
    horn += cyl(HORN_BOSS_R, HORN_FACE_Z, boss_top)
    return horn - cyl(SV_SHAFT_D / 2, HORN_FACE_Z + 0.6, boss_top + 1)  # 出力軸の入る穴


@lru_cache(maxsize=None)
def cm_stack_dummy() -> Manifold:
    fz = PLATE_TOP + CR_FLOOR_T
    return d._along_y(_stack_section(0.0).translate((0, fz)), CM_Y0, CM_Y1)


PARTS = {
    "horn_hub": (horn_hub_part, "ハブ(ソケット枠の代わり)", d.COLORS["chassis"], 1, True),
    "cm_yoke": (cm_yoke_part, "ヨーク(サーボ天板)", d.COLORS["accent"], 1, True),
    "cm_cradle": (cm_cradle_part, "CoreMatrix 受け台", d.COLORS["chassis"], 1, True),
    "fs90r": (fs90r_dummy, "FS90R", "#2a2a2a", 1, False),
    "horn": (horn_dummy, "ホーン", "#f0f0f0", 1, False),
    "cm_stack": (cm_stack_dummy, "CoreMatrix + 18350 ベース", "#151515", 1, False),
}


def instances(theta: float):
    """原作の配置から、ヨーク・ソケット枠・スタックチャンを外し、改造部品を足す。"""
    out = [i for i in d.instances(theta, with_stackchan=False) if i.part not in ("yoke", "socket_frame")]
    table = d.rot_z(-theta)
    eye = np.eye(4)
    out += [
        d.Instance("horn_hub", "horn_hub", table, "table"),
        d.Instance("horn", "horn", table, "table"),
        d.Instance("cm_yoke", "cm_yoke", eye, "chassis"),
        d.Instance("fs90r", "fs90r", eye, "chassis"),
        d.Instance("cm_cradle", "cm_cradle", eye, "chassis"),
        d.Instance("cm_stack", "cm_stack", eye, "chassis"),
    ]
    return out


def shape_of(key: str) -> Manifold:
    if key in PARTS:
        return PARTS[key][0]()
    return d.part_shape(key)


# 意図して重ねている組(ホーンは軸に、サーボの耳はネジで天板に、受け台の床は天板の上)
EXPECTED = {frozenset(p) for p in [("fs90r", "horn"), ("cm_stack", "cm_cradle")]}


def collisions(theta: float, tol: float = 0.02):
    placed = []
    for inst in instances(theta):
        s = d.apply(shape_of(inst.part), inst.matrix)
        placed.append((inst, s, s.bounding_box()))
    hits = []
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            ia, sa, ba = placed[i]
            ib, sb, bb = placed[j]
            if ia.group == ib.group and ia.group != "chassis":
                continue
            if frozenset((ia.name, ib.name)) in EXPECTED:
                continue
            if not all(ba[k] < bb[k + 3] and bb[k] < ba[k + 3] for k in range(3)):
                continue
            v = (sa ^ sb).volume()
            if v > tol:
                hits.append((ia.name, ib.name, round(v, 3)))
    return hits


def min_gaps(theta: float, pairs):
    shapes = {i.name: d.apply(shape_of(i.part), i.matrix) for i in instances(theta)}
    return {f"{a}-{b}": round(shapes[a].min_gap(shapes[b], 6.0), 2) for a, b in pairs}


PRINT_POSE = {
    "horn_hub": (d.mat([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0]]), "上面(ポケット側)を下、ツメを上"),
    "cm_yoke": (d.mat([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0]]), "天板を下、カラーを上"),
    "cm_cradle": (d.mat([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0]]), "背板を下(床とほぞは横に寝る)"),
}


def main() -> int:
    import trimesh

    out = d.ROOT / "out" / "cm"
    (out / "stl").mkdir(parents=True, exist_ok=True)
    report = {"dims": {
        "TIP_Z": TIP_Z, "PLATE_TOP": round(PLATE_TOP, 2), "HUB_TOP": round(HUB_TOP, 2),
        "POCKET_FLOOR": round(POCKET_FLOOR, 2), "CM_Y0": round(CM_Y0, 2), "CM_Y1": round(CM_Y1, 2),
        "servo_shaft_offset": round(SV_SHAFT_OFF, 2),
    }}
    for key, pose in PRINT_POSE.items():
        shape = d.apply(shape_of(key), pose[0])
        low = shape.bounding_box()[:3]
        shape = shape.translate((-low[0], -low[1], -low[2]))
        mesh = d.to_trimesh(shape)
        mesh.export(out / "stl" / f"{key}_x1.stl")
        bb = shape.bounding_box()
        report.setdefault("parts", {})[key] = {
            "size_mm": [round(bb[3], 1), round(bb[4], 1), round(bb[5], 1)],
            "volume_cm3": round(shape.volume() / 1000, 1), "pose": pose[1],
        }
    # 歩行 1 周で干渉チェック
    worst = []
    for deg in range(0, 360, 6):
        for a, b, v in collisions(math.radians(deg)):
            worst.append((deg, a, b, v))
    report["collisions"] = worst
    report["gaps_deg0"] = min_gaps(0.0, [("horn_hub", "cm_yoke"), ("horn", "horn_hub"), ("fs90r", "horn_hub"),
                                         ("fs90r", "cm_yoke"), ("horn_hub", "gear_table")])
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
