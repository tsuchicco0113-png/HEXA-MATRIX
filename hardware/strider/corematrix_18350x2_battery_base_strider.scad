// =====================================================================
//  HEXA STAGE  -  CoreMatrix 18350 x2 (並列) バッテリーベース  (スタックチャン/Strider 仕様つき)
//  CoreMatrix(54x54x11.6 / R5) の背面にスタックするﾄﾚｲ型ｹｰｽ
//  ・外形はCoreMatrix本体ﾌﾚｰﾑと同形状(54x54 R5ｽﾄﾚｰﾄ)をそのまま延長
//  ・上面(CoreMatrix背面と接する面)は開放 → 本体背面がﾌﾀになる
//  ・CoreMatrix背面の 4-M3 (44mmﾋﾟｯﾁ) と同軸の貫通ﾎﾞｽ
//    → 純正ﾈｼﾞを長いM3に交換して底面から共締め
//  ・端子は秋月 18650電池ﾎﾞｯｸｽのばね端子/平端子を抜いて再利用
//    (端子板の寸法は個体差あり → 実測して下のﾊﾟﾗﾒｰﾀを修正)
//
//
//  ｽﾀｯｸﾁｬﾝ仕様 (strider = true):
//  ・CoreMatrix の背面ﾌﾟﾚｰﾄ(ｼｰﾙの板)を外して使う。外すと基板の M5-Bus (2x15 ﾒｽﾍｯﾀﾞ) が出る
//    → ｻｰﾎﾞの信号線を M5-Bus 21番 (G23) に挿す
//  ・ｾﾙの上に bus_gap の「配線ｷﾞｬﾗﾘｰ」を足し、挿したﾋﾟﾝと線の逃げにする (ﾍﾞｰｽが bus_gap だけ厚くなる)
//  ・ｷﾞｬﾗﾘｰの側面に線の出口 (ﾍｯﾀﾞ側)。Grove の線は本体側面の PORT.A から外を回すので穴は要らない
//  ・ﾈｼﾞは背面ﾌﾟﾚｰﾄを固定していた純正の位置 (枠の真鍮ｲﾝｻｰﾄ) にそのまま締める
//
//  座標: 中心原点, Z=0 が底面, Z=H がCoreMatrix背面との合わせ面
//        +Y = CoreMatrix の A/B/C ﾎﾞﾀﾝ側 (正面から見て上)
//        +X = 正面から見て右 (背面図で電池ｺﾈｸﾀ MX1.25-2P がある側)
// =====================================================================

// 出力するﾊﾟｰﾂ
part = "base"; // [base:本体, terminal_test:端子ﾃｽﾄ片, assembly_check:CoreMatrix重ね確認]

/* [CoreMatrix 本体] */
// 外形
body_w = 54.0; // [50:0.1:60]
// 角R (図面 4-R5 / STL実測 R5.0)
body_r = 5.0; // [0:0.1:10]
// 底面ｴｯｼﾞの面取り (本体前面ｴｯｼﾞと揃える)
edge_round = 0.6; // [0:0.1:2]
// 4-M3 ﾋﾟｯﾁ
screw_pitch = 44.0; // [40:0.1:50]

/* [18350 セル] */
// 直径 (KEEPPOWER 18350 保護付 18.5±0.1 の最大値)
cell_d = 18.6; // [17:0.05:19.5]
// 全長 (KEEPPOWER 38.9±0.5 公称。±0.5はばねで吸収)
cell_len = 38.9; // [33:0.1:42]
// 直径方向ｸﾘｱﾗﾝｽ (最大径に対して)
cell_clr = 0.3; // [0:0.05:1.5]
// ｾﾙ間ﾘﾌﾞ厚
cell_rib = 0.8; // [0.4:0.1:3]

/* [再利用端子 (秋月18650ﾎﾞｯｸｽ)] */
// 端子板の幅 (実測 13.2)
plate_w = 13.2; // [6:0.1:16]
// 端子板の板厚 ← 要実測
plate_t = 0.5; // [0.1:0.05:1.5]
// 端子板(金具)の高さ (実測 18.6)
plate_h = 18.6; // [8:0.1:22]
// 端子板上端とCoreMatrix背面のｽｷﾏ
plate_top_clr = 0.3; // [0:0.05:1]
// 端子下の配線逃げ高さ (板を左右の段で浮かせ、下に配線/はんだを通す)
wire_gap = 1.2; // [0:0.1:5]
// 配線逃げ部分だけ底板を掘り下げる深さ (底板の残り = floor_t - これ)
wire_pocket = 0.8; // [0:0.1:1.2]
// 配線逃げの幅 (板の下端ほぼ全幅。左右 ledge 幅の段で板を受ける)
wire_w = 11.7; // [2:0.1:13]
// 溝ｸﾘｱﾗﾝｽ (片側)
plate_clr = 0.25; // [0:0.05:1]
// 端子板の左右を押さえる爪幅
lip = 1.2; // [0.4:0.1:3]
// 板ばねの自由高さ (板の表面から。実測 4.4 / ＋－同形状)
spring_free = 4.4; // [0:0.1:10]
// 板ばねの使用時の高さ (公称ｾﾙ長で挿入したとき。両側同じだけ縮む)
spring_work = 2.4; // [0.5:0.1:8]
// 板ばね接点の位置 (板の中心からの上下ｵﾌｾｯﾄ。上が＋) ← 要実測
contact_dz = 0.0; // [-8:0.1:8]
// 長手方向の追加ｸﾘｱﾗﾝｽ
len_clr = 0.2; // [0:0.05:2]
// はんだﾀﾌﾞ逃げ窓の幅
tab_w = 4.5; // [1:0.1:10]
// 端子壁: ｾﾙ側の爪の厚み
lip_t = 0.8; // [0.4:0.1:3]
// 端子壁: 端子板の背当て厚み
back_t = 0.8; // [0.4:0.1:3]
// 配線ﾉｯﾁ深さ (端子壁上端から)
notch_d = 3.0; // [0:0.1:8]

/* [スタックチャン仕様 (Strider)] */
// ｽﾀｯｸﾁｬﾝ仕様にする (背面ﾌﾟﾚｰﾄを外し、M5-Bus への配線ｷﾞｬﾗﾘｰと出口を足す)
strider = true;
// 配線ｷﾞｬﾗﾘｰの高さ (ﾍｯﾀﾞに挿したﾋﾟﾝ + 線を寝かせる分。ﾋﾟﾝを曲げて 4〜5mm)
bus_gap = 5.0; // [2:0.5:12]
// 信号線の出口の面 (+1: 右側面 = M5-Bus ﾍｯﾀﾞ側 / -1: 左側面 = USB-C側)
exit_side = 1; // [-1:左側面 USB-C側, 1:右側面 ﾍｯﾀﾞ側]
// 出口の位置 Y (+ が ABC ﾎﾞﾀﾝ側。21番ﾋﾟﾝはﾍｯﾀﾞの上から11段目 ≒ 下寄り)
exit_y = -8.0; // [-20:0.5:20]
// 出口の幅 (Y)
exit_w = 9.0; // [3:0.5:20]
// 出口の深さ (上面から。bus_gap 以下)
exit_h = 4.0; // [1:0.5:12]
// ｹｰﾌﾞﾙ用の 2つ目の出口 (反対側の面、Grove の線をまとめたい時など)
exit2 = false;

/* [筐体] */
// 外壁 (左右)
wall = 1.6; // [0.8:0.1:4]
// 外壁 (端子側の前後) ※長さ方向が詰まるため薄め
end_wall = 1.2; // [0.8:0.1:4]
// 端子背面の配線ﾀﾞｸﾄ最小幅
min_duct = 1.2; // [0:0.1:5]
// 底板
floor_t = 1.6; // [0.8:0.1:4]
// ｾﾙ上端と本体背面のｽｷﾏ (小さいほど電池が上下に動かない)
top_clr = 0.3; // [0:0.05:3]

/* [ネジ] */
// M3 貫通穴径
m3_hole = 3.4; // [3:0.05:4]
// ﾈｼﾞﾎﾞｽ外径
boss_d = 7.6; // [5:0.1:10]
// 座ぐり径 (M3ﾎﾞﾀﾝ頭5.7 / ｷｬｯﾌﾟ頭5.5)
head_d = 6.2; // [5:0.1:8]
// 頭の高さ (M3ﾎﾞﾀﾝ1.65 / ｷｬｯﾌﾟ3.0 / ﾄﾗｽ1.6)
head_h = 1.65; // [0.5:0.05:4]
// 頭を底面から沈める余裕
head_margin = 0.3; // [0:0.05:2]
// 純正ﾈｼﾞ頭がCoreMatrix背面から沈んでいる深さ (面一なら0)
stock_recess = 0.0; // [0:0.05:5]
// 純正M3ﾈｼﾞの長さ (実測 M3x3)
stock_screw = 3; // [2:0.5:20]
// 交換する長ﾈｼﾞ (市販規格長)
new_screw = 20; // [6, 8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 30, 35]

/* [キーチェーン穴] */
// 側面に2穴を開けて内部でU字につなぐｽﾄﾗｯﾌﾟﾄﾝﾈﾙ
keyring = true;
// 取り付け面 (正面から見て)
key_side = -1; // [-1:左側面 USB-C側, 1:右側面]
// 穴の幅 (Y)
key_hole_w = 3.4; // [1.5:0.1:6]
// 穴の高さ (Z)
key_hole_h = 4.0; // [1.5:0.1:8]
// 2穴の中心間隔
key_pitch = 8.0; // [5:0.1:16]
// 穴の間に残る梁の厚み (外面から)
key_bar_t = 2.8; // [1.2:0.1:5]
// 内部連結ﾁｬﾝﾈﾙ幅 (X)
key_ch_w = 2.2; // [1:0.1:4]
// 穴中心の高さ
key_z = 6.5; // [3:0.1:15]

/* [刻印] */
// 刻印する
engrave = true;
// 底面の文字とﾏｰｸ(HEXA STAGE / 18350 x2 / ABC矢印)
engrave_bottom = false;
// 刻印深さ
engr_d = 0.4; // [0.2:0.05:1]

/* [Hidden] */
$fn = 64;
eps = 0.01;

// ---------- 派生寸法 ----------
cradle_d   = cell_d + cell_clr;
// 電池部分の高さ: ｾﾙ基準と端子板基準の大きい方
Hc         = max(floor_t + cradle_d + top_clr, floor_t + wire_gap + plate_h + plate_top_clr);
// ﾍﾞｰｽ全体の高さ (ｽﾀｯｸﾁｬﾝ仕様は配線ｷﾞｬﾗﾘｰの分だけ高い)
H          = Hc + (strider ? bus_gap : 0);
// ｾﾙ軸高さ: ｸﾚｰﾄﾞﾙ底を持ち上げ、ｾﾙ上端を本体背面ぎりぎりに寄せる
//  → 上下ｶﾞﾀ防止 + 板ばね(板中心)と軸を揃える
cell_z     = Hc - top_clr - cradle_d/2;
cell_px    = cradle_d/2 + cell_rib/2;               // ｾﾙ中心X (±)
// 端子間の空間: 突起/ばねは端子壁のｾﾙ側窓(lip_t厚)を通り抜けて出る
cav_len    = cell_len + 2*(spring_work - lip_t) + len_clr;
cell_y0    = -cell_len/2;                           // ｾﾙの－端Y (－側=-Y)
slot_w     = plate_w + 2*plate_clr;
slot_t     = plate_t + 2*plate_clr;
term_wall  = lip_t + slot_t + back_t;
duct_w     = body_w/2 - end_wall - (cav_len/2 + term_wall);
// 先端が純正ﾈｼﾞと同じ深さで止まるように座ぐりを決める
cb_depth   = H - (new_screw - stock_screw) + stock_recess;
inner_half = body_w/2 - wall;
term_y     = cav_len/2 + term_wall/2;

echo(str("== ベース高さ H = ", H, " mm  (電池部 ", Hc, (strider ? str(" + 配線ｷﾞｬﾗﾘｰ ", bus_gap) : ""), " / CoreMatrix込み総厚 ", H+11.6, " mm)"));
if (strider) echo("== ｽﾀｯｸﾁｬﾝ仕様: CoreMatrix の背面ﾌﾟﾚｰﾄを外して取り付ける (M5-Bus 21番 = G23 にｻｰﾎﾞの信号線)");
assert(!strider || exit_h <= bus_gap + 0.01, "出口の深さ exit_h は bus_gap 以下にしてください");
echo(str("== 端子間空間 = ", cav_len, " mm / 端子壁外面 Y=±", term_y+term_wall/2));
echo(str("== 座ぐり深さ = ", cb_depth, " mm  (M3x", new_screw, " 使用時)"));
assert(cb_depth >= head_h + head_margin,
       "ﾈｼﾞ頭が底面からはみ出す: new_screw を短くしてください");
assert(cb_depth <= H - 3,
       "座ぐりが深すぎ(ﾎﾞｽが薄い): new_screw を長くしてください");
// 使える市販長の一覧
for (L=[16,18,20,22,25,28,30,35]) {
    cb = H - (L - stock_screw) + stock_recess;
    echo(str("   M3x", L, " → 座ぐり ", cb, " mm ",
             (cb >= head_h + head_margin && cb <= H - 3) ? "OK" : "NG"));
}
echo(str("== 端子背面の配線ﾀﾞｸﾄ幅 = ", duct_w, " mm"));
echo(str("== 端子板の下端 Z=", floor_t + wire_gap, " / 上端 Z=", floor_t + wire_gap + plate_h,
         " (電池部上面 ", Hc, ") / 板中心 ", floor_t + wire_gap + plate_h/2, " vs ｾﾙ軸 ", cell_z));
assert(floor_t + wire_gap + plate_h <= Hc + 0.01,
       "端子板が上面からはみ出す: wire_gap を減らすか plate_h を確認");
assert(wire_w <= slot_w - 2*0.8, "配線逃げが広すぎて板を受ける段がなくなる");
assert(duct_w >= min_duct,
       "配線ﾀﾞｸﾄが狭すぎ: cell_len / spring_work / 端子壁を確認");
// ｾﾙ長の±0.5 は両側の板ばねで半分ずつ吸収
echo(str("== 板ばね高さ(片側): 公称 ", spring_work, " mm / ｾﾙ+0.5で ", spring_work-0.25,
         " / ｾﾙ-0.5で ", spring_work+0.25, " (自由 ", spring_free, ")"));
echo(str("== ｾﾙ軸 Z=", cell_z, " / 板ばね接点 Z=", floor_t + wire_gap + plate_h/2 + contact_dz,
         " → ずれ ", floor_t + wire_gap + plate_h/2 + contact_dz - cell_z, " mm"));
assert(spring_work - 0.25 > 0.6, "ｾﾙ最長時に板ばねが縮み切る");
assert(spring_work + 0.25 < spring_free, "ｾﾙ最短時に板ばねが届かない");

// ---------------------------------------------------------------------
module rsq(w, r, h) {               // 角丸正方形の押し出し
    linear_extrude(h) offset(r) square(w - 2*r, center=true);
}

module outer_shell() {              // 外形(底ｴｯｼﾞのみ面取り)
    hull() {
        translate([0,0,edge_round]) rsq(body_w, body_r, H - edge_round);
        rsq(body_w - 2*edge_round, body_r - edge_round, edge_round + eps);
    }
}

module screw_pos() {
    for (sx=[-1,1], sy=[-1,1])
        translate([sx*screw_pitch/2, sy*screw_pitch/2, 0]) children();
}

module cell_cut() {                 // ｾﾙ収納 (半円ｸﾚｰﾄﾞﾙ+上方開放)
    for (sx=[-1,1]) translate([sx*cell_px, 0, cell_z]) {
        rotate([90,0,0]) cylinder(d=cradle_d, h=cav_len, center=true);
        translate([-cradle_d/2, -cav_len/2, 0]) cube([cradle_d, cav_len, H]);
    }
}

// 端子壁 1枚 (s=+1:+Y側, -1:-Y側)
module term_wall(s) {
    span = 2*cell_px + cradle_d + 2.0;
    difference() {
        translate([-span/2, s*term_y - term_wall/2, 0])
            cube([span, term_wall, Hc]);
        for (sx=[-1,1]) translate([sx*cell_px, s*term_y, 0]) {
            // 端子板が差し込まれる溝(上から差し込み、左右の段で止まる)
            translate([-slot_w/2, s>0 ? -term_wall/2 + lip_t : term_wall/2 - lip_t - slot_t, floor_t + wire_gap])
                cube([slot_w, slot_t, H]);
            // 端子下の配線逃げ: 板の下を壁の厚み方向に貫通 → 外側ﾀﾞｸﾄへ
            translate([-wire_w/2, -term_wall/2 - eps, floor_t - wire_pocket])
                cube([wire_w, term_wall + 2*eps, wire_pocket + wire_gap + slot_t]);
            // ｾﾙ側の窓 (左右 lip で板を保持)
            translate([-(slot_w/2 - lip), s>0 ? -term_wall/2 - eps : term_wall/2 - lip_t - slot_t/2, floor_t])
                cube([slot_w - 2*lip, lip_t + slot_t/2 + eps, H]);
            // 外側(配線ｷﾞｬﾗﾘｰ側) はんだﾀﾌﾞ逃げ
            translate([-tab_w/2, s>0 ? term_wall/2 - back_t - slot_t/2 : -term_wall/2 - eps, floor_t])
                cube([tab_w, back_t + slot_t/2 + eps, H]);
        }
        // 配線ﾉｯﾁ: 端子壁の両端上部。ｷﾞｬﾗﾘｰ→ｾﾙ上の空間→側面ｷﾞｬﾗﾘｰへ
        // (角はM3ﾎﾞｽで塞がるため、壁の上を越えて回す)
        for (sx=[-1,1]) {
            nx0 = cell_px + slot_w/2 + 0.6;
            translate([sx>0 ? nx0 : -span/2 - 1, s*term_y - term_wall/2 - eps, Hc - notch_d])
                cube([span/2 + 1 - nx0, term_wall + 2*eps, notch_d + eps]);
        }
    }
}

// ｾﾙ下のﾍﾞｯﾄﾞ (ｸﾚｰﾄﾞﾙを形成する実体)
module cradle_bed() {
    span = 2*cell_px + cradle_d + 2.0;
    translate([-span/2, -cav_len/2 - eps, 0])
        cube([span, cav_len + 2*eps, cell_z]);
    // ｾﾙ間ﾘﾌﾞ(上部まで)
    translate([-cell_rib/2 - 0.4, -cav_len/2, 0])
        cube([cell_rib + 0.8, cav_len, Hc - 3]);
}

module base() {
    difference() {
        union() {
            difference() {
                outer_shell();
                // 内部ﾎﾟｹｯﾄ
                translate([0,0,floor_t]) linear_extrude(H)
                    offset(body_r - wall) square([body_w - 2*wall - 2*(body_r-wall), body_w - 2*end_wall - 2*(body_r-wall)], center=true);
            }
            screw_pos() cylinder(d=boss_d, h=H);
            cradle_bed();
            term_wall(+1);
            term_wall(-1);
            if (keyring) keyring_block();
        }
        cell_cut();
        // M3 貫通 + 底面座ぐり
        screw_pos() {
            translate([0,0,-eps]) cylinder(d=m3_hole, h=H + 2*eps);
            translate([0,0,-eps]) cylinder(d=head_d, h=cb_depth + eps);
        }
        if (keyring) keyring_cut();
        if (engrave) engravings();
        if (strider) strider_exits();
    }
}

// ---------- スタックチャン仕様: 配線ｷﾞｬﾗﾘｰの出口 ----------
// 上面から exit_h の切り欠き。CoreMatrix の枠が上からﾌﾀをするので、線は穴を通る形になる
module strider_exits() {
    for (side = exit2 ? [exit_side, -exit_side] : [exit_side]) {
        x0 = side > 0 ? body_w/2 - wall - 2 : -body_w/2 - 2;
        translate([x0, exit_y - exit_w/2, H - exit_h])
            hull() {   // 下の角は R1 (線を傷めない)、上は CoreMatrix の枠でﾌﾀ
                for (y = [1, exit_w - 1]) translate([0, y, 1]) rotate([0, 90, 0]) cylinder(r=1, h=wall + 4, $fn=24);
                translate([0, 0, exit_h - eps]) cube([wall + 4, exit_w, 1]);
            }
    }
}

module engravings() {
    // 底面刻印 (鏡像で底から読める向き)
    // 文字の「上」はｷｰﾁｪｰﾝ側に向ける → 吊るした状態で正立して読める
    if (engrave_bottom) translate([0,0,-eps]) linear_extrude(engr_d + eps) mirror([1,0,0]) {
        rotate([0,0, keyring ? (key_side < 0 ? -90 : 90) : 0]) {
            translate([0,  2.5]) text("HEXA STAGE", size=3.6, halign="center", valign="center",
                                      font="Liberation Sans:style=Bold");
            translate([0, -3.5]) text("18350 x2  1S2P", size=2.8, halign="center", valign="center",
                                      font="Liberation Sans");
        }
        // ABCﾎﾞﾀﾝ側を示す矢印 (組立時の向き合わせ用)
        if (keyring) {
            translate([0, 19]) polygon([[-2.5,0],[2.5,0],[0,3.5]]);
        } else {
            translate([0, 14]) polygon([[-3,0],[3,0],[0,4]]);
            translate([0, 9.5]) text("ABC", size=3, halign="center", valign="center",
                                     font="Liberation Sans:style=Bold");
        }
    }
    // 端子壁の上面中央: 極性 (+Y=プラス / -Y=マイナス。並列なので各端で共通)
    for (sy=[-1,1])
        translate([0, sy*term_y, Hc - engr_d])
            linear_extrude(1) text(sy > 0 ? "+" : "-", size=2.4, halign="center", valign="center",
                                   font="Liberation Sans:style=Bold");
}

// ---------- キーチェーン用ストラップトンネル ----------
key_blk_y = key_pitch + key_hole_w + 4;     // ﾌﾞﾛｯｸ長さ(Y)
key_blk_x = key_bar_t + key_ch_w + 1.2;     // 外面からのﾌﾞﾛｯｸ奥行き(X)
module keyring_block() {
    mirror([key_side > 0 ? 1 : 0, 0, 0])
        translate([-body_w/2 + 0.5, -key_blk_y/2, 0])
            cube([key_blk_x - 0.5, key_blk_y, H]);
}
module keyring_cut() {
    mirror([key_side > 0 ? 1 : 0, 0, 0]) {
        // 外から入る2つの穴
        for (sy=[-1,1])
            translate([-body_w/2 - 1, sy*key_pitch/2 - key_hole_w/2, key_z - key_hole_h/2])
                cube([1 + key_bar_t + key_ch_w, key_hole_w, key_hole_h]);
        // 内部で2穴をつなぐﾁｬﾝﾈﾙ
        translate([-body_w/2 + key_bar_t, -key_pitch/2 - key_hole_w/2, key_z - key_hole_h/2])
            cube([key_ch_w, key_pitch + key_hole_w, key_hole_h]);
    }
}

// 端子の差し込み確認用ｸｰﾎﾟﾝ (端子壁1枚分だけ)
module terminal_test() {
    span = 2*cell_px + cradle_d + 2.0;
    intersection() {
        base();
        translate([-span/2 - 1, term_y - term_wall/2 - 4, 0])
            cube([span + 2, term_wall + 8, H]);
    }
}

// CoreMatrix STL と重ねて確認 (同じﾌｫﾙﾀﾞに CoreMatrix.stl を置く)
module assembly_check() {
    base();
    %translate([-27, -27.871, H + 11.6]) import("CoreMatrix.stl");
}

if      (part == "base")           base();
else if (part == "terminal_test")  terminal_test();
else if (part == "assembly_check") assembly_check();
