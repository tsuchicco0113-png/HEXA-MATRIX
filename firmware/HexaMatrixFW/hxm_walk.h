// HEXA MATRIX 歩行モード (v0.12、Stackchan Strider × CoreMatrix + FEETECH FS90R)。Arduino に依存しない
//
//   CoreMatrix の M5-Bus の GPIO から 50Hz のサーボパルスを出し、連続回転サーボ FS90R で
//   Strider (ヤンセン脚 4 本・傘歯車 1:1) を前後に歩かせる。
//
//   WALK (0x08) len=3:  int8 速さ (-100〜100 %、正=前進、0=止まる)
//                       u8   この指令の有効時間 (0.1 秒単位。0 なら 5 = 0.5 秒)
//                       u8   顔 (0=おまかせ / 1〜5 / 0xFF=そのまま)
//     返事はしない (FRAME と同じく連続で送るため)。有効時間内に次の WALK が来なければ止まる
//     (CPZ が落ちた・Wi-Fi が切れた時に歩き続けない)。状態は PING の "walk" で見る
//
//   FS90R (FEETECH 仕様書): 700〜2300µs、止まる 1500µs (±45)、不感帯 90µs、1500→700 で CW / 1500→2300 で CCW
//   止まる時は 0.3 秒だけ中立のパルスを出してから、パルスを止める (中立のずれでじわじわ回らないように)
#pragma once
#include <stdint.h>
#include <math.h>

struct HxmWalkCfg {
  int8_t   pin = -1;     // サーボ信号の GPIO (-1 = 使わない)
  int16_t  trim = 0;     // 中立の補正 µs (-150〜150)
  bool     inv = false;  // 前後を入れ替える (サーボの向き・取り付けで逆に歩く時)
  uint8_t  maxPct = 60;  // 速さの上限 % (原作のシミュレーションでは 100% だと跳ねて進みが落ちる)
  uint16_t dead = 50;    // 中立から動き出すまでの µs (FS90R の不感帯 90µs の半分 + 余裕)
  uint16_t span = 400;   // 100% のときの中立からの µs (dead を含まない)
};

/// 速さ % → パルス幅 µs。0 は中立
static inline uint16_t hxm_walk_us(const HxmWalkCfg& c, int spd) {
  if (spd > 100) spd = 100;
  if (spd < -100) spd = -100;
  int lim = c.maxPct > 100 ? 100 : c.maxPct;
  if (spd > lim) spd = lim;
  if (spd < -lim) spd = -lim;
  int mid = 1500 + c.trim;
  if (spd == 0) return (uint16_t)mid;
  int s = c.inv ? -spd : spd;
  int a = s < 0 ? -s : s;
  int off = (int)c.dead + (int)((long)c.span * a / 100);
  int us = s > 0 ? mid + off : mid - off;
  if (us < 700) us = 700;
  if (us > 2300) us = 2300;
  return (uint16_t)us;
}

/// µs → LEDC のデューティ (50Hz、bits ビット)
static inline uint32_t hxm_walk_duty(uint16_t us, uint8_t bits) {
  return (uint32_t)(((uint64_t)us << bits) / 20000u);
}

/// ヨー角速度 (deg/s): 重力の向きのまわりの回転。本体をどう立てても「床の上で向きを変えた速さ」になる
static inline float hxm_yaw_rate(float ax, float ay, float az, float gx, float gy, float gz) {
  float m = sqrtf(ax * ax + ay * ay + az * az);
  if (m < 0.3f) return 0.f;
  return (ax * gx + ay * gy + az * gz) / m;
}

/// 指令の状態 (時計は外から渡す。PC でテストできる)
struct HxmWalk {
  int8_t   spd = 0;            // いまの指令 %
  uint8_t  face = 0;           // 0=おまかせ
  uint32_t until = 0;          // 指令の期限 (ms)
  uint32_t stopAt = 0;         // 止めた時刻 (中立を出し始めた)
  bool     moving = false;
  bool     pulsing = false;    // パルスを出している
  uint32_t cmds = 0, timeouts = 0;

  /// WALK パケット。戻り値: 動きが変わった
  bool command(int8_t s, uint8_t ttl, uint8_t f, uint32_t now) {
    cmds++;
    if (f != 0xFF) face = f;
    until = now + (uint32_t)(ttl ? ttl : 5) * 100u;
    bool was = moving;
    spd = s; moving = s != 0;
    if (moving) pulsing = true;
    else if (was) stopAt = now;
    return was != moving;
  }
  /// 毎回呼ぶ。戻り値: 期限切れで止めた
  bool tick(uint32_t now) {
    if (moving && (int32_t)(now - until) > 0) {
      moving = false; spd = 0; stopAt = now; timeouts++;
      return true;
    }
    if (!moving && pulsing && (int32_t)(now - stopAt) > 300) pulsing = false;   // 中立 0.3 秒 → パルスを止める
    return false;
  }
};

// ---------------------------------------------------------------- 顔 (16x16、各行 MSB が左)
//   目は 4 行目あたり、口は 11 行目あたり。歩いている間は 0.25 秒ごとに体が上下する (1 行ずらす)
enum : uint8_t { HXW_FACE_AUTO = 0, HXW_FACE_NORMAL = 1, HXW_FACE_SMILE = 2, HXW_FACE_WOW = 3, HXW_FACE_SLEEPY = 4, HXW_FACE_ANGRY = 5,
                 HXW_FACE_N = 6 };

static inline void hxw_eye(uint16_t* r, int y, int x, uint8_t kind) {
  auto px = [&](int yy, int xx) { if (yy >= 0 && yy < 16 && xx >= 0 && xx < 16) r[yy] |= (uint16_t)(0x8000 >> xx); };
  switch (kind) {
    case 0:  for (int dy = 0; dy < 3; dy++) for (int dx = 0; dx < 2; dx++) px(y + dy, x + dx); break;   // ふつう (2x3)
    case 1:  px(y + 2, x - 1); px(y + 1, x); px(y + 1, x + 1); px(y + 2, x + 2); break;                  // にっこり (^)
    case 2:  for (int dy = 0; dy < 4; dy++) { px(y - 1 + dy, x - 1); px(y - 1 + dy, x + 2); }               // まんまる (□)
             px(y - 1, x); px(y - 1, x + 1); px(y + 2, x); px(y + 2, x + 1); break;
    case 3:  px(y + 2, x - 1); px(y + 2, x); px(y + 2, x + 1); px(y + 2, x + 2); break;                  // ねむい (-)
    case 4:  px(y, x - 1); px(y + 1, x); px(y + 1, x + 1); px(y + 2, x + 1); px(y + 2, x); break;        // おこ (\ /)
    default: px(y + 2, x); px(y + 2, x + 1); break;                                                       // まばたき
  }
}

/// face: 1〜5、dir: 進む向き (-1/0/1)、t: ms。rows に 16 行を書く
static inline void hxm_walk_face(uint16_t* rows, uint8_t face, int dir, uint32_t t) {
  for (int i = 0; i < 16; i++) rows[i] = 0;
  bool blink = (t % 3200) < 140 && face != HXW_FACE_SLEEPY;
  int bob = dir != 0 && ((t / 250) & 1) ? 1 : 0;               // 歩くと上下に揺れる
  int ey = 4 + bob;
  uint8_t ek = blink ? 9 : face == HXW_FACE_SMILE ? 1 : face == HXW_FACE_WOW ? 2 : face == HXW_FACE_SLEEPY ? 3
             : face == HXW_FACE_ANGRY ? 4 : 0;
  hxw_eye(rows, ey, 4, ek);
  if (ek == 4) {   // おこ: 右目は鏡
    uint16_t tmp[16] = {0};
    hxw_eye(tmp, ey, 4, 4);
    for (int i = 0; i < 16; i++) {
      uint16_t v = tmp[i], m = 0;
      for (int b = 0; b < 16; b++) if (v & (0x8000 >> b)) m |= (uint16_t)(0x8000 >> (15 - b));
      rows[i] |= m;
    }
  } else {
    hxw_eye(rows, ey, 10, ek);
  }
  int my = 11 + bob;
  auto px = [&](int yy, int xx) { if (yy >= 0 && yy < 16 && xx >= 0 && xx < 16) rows[yy] |= (uint16_t)(0x8000 >> xx); };
  switch (face) {
    case HXW_FACE_SMILE:  px(my - 1, 5); px(my, 6); px(my, 7); px(my, 8); px(my, 9); px(my - 1, 10); break;
    case HXW_FACE_WOW:    px(my - 1, 7); px(my - 1, 8); px(my, 6); px(my, 9); px(my + 1, 7); px(my + 1, 8); break;
    case HXW_FACE_SLEEPY: px(my, 7); px(my, 8); px(1, 13); px(1, 14); px(2, 14); px(3, 13); px(3, 14); break;   // 口 + z
    case HXW_FACE_ANGRY:  px(my, 6); px(my - 1, 7); px(my - 1, 8); px(my, 9); break;
    default:              px(my, 6); px(my, 7); px(my, 8); px(my, 9); break;
  }
  if (dir != 0) {   // 進む向きの印 (下の端に ^ か v)
    if (dir > 0) { px(15, 7); px(15, 8); px(14, 7); px(14, 8); }
    else { px(14, 7); px(14, 8); px(15, 6); px(15, 9); }
  }
}

/// おまかせの顔: 歩いていればにっこり、止まって 20 秒でねむい
static inline uint8_t hxm_walk_autoface(bool moving, uint32_t idleMs) {
  if (moving) return HXW_FACE_SMILE;
  return idleMs > 20000 ? HXW_FACE_SLEEPY : HXW_FACE_NORMAL;
}
