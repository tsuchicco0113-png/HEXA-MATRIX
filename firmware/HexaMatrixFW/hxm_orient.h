// HEXA MATRIX 向きと振り (v0.9.6)。Arduino に依存しない (PC でテストできる)
//
//   画面の回転 (rotation 0〜3) と、そのときの傾き (重力を画面の面に落とした向き、度) の組を覚える。
//   ・C 長押しや CPZ から向きを変えたとき、そのときの傾きを「この向きならこの回転」として覚える
//   ・自動回転を入れた瞬間も、いまの向きを正しいとして覚える
//   ・覚えていない回転は、覚えた回転から 90° ずつずらして予想する。回り方 (右回り/左回り) は
//     隣り合う2つの向きを覚えると決まる。1つしか覚えていない時は右回りと仮定する
//     (逆さま=180° は1つでも当たる)
//   M5Unified が CoreMatrix の BMI270 の軸を基板に合わせてくれるが、画面の回転との対応は
//   実機でしか分からないので、決め打ちせずに覚えさせる
#pragma once
#include <math.h>
#include <stdint.h>

static inline float hxm_wrap180(float a) {
  while (a > 180.f) a -= 360.f;
  while (a <= -180.f) a += 360.f;
  return a;
}

/// 立てて置いているときの傾きの角 (度)。寝かせている (画面が上/下を向いている) 時は false
static inline bool hxm_tilt(float ax, float ay, float az, float* ang) {
  float h = sqrtf(ax * ax + ay * ay);
  if (h < 0.55f || fabsf(az) > 0.8f) return false;
  *ang = atan2f(ay, ax) * 57.2957795f;
  return true;
}

struct HxmOrient {
  float ang[4];                 // 回転ごとの傾き。覚えていなければ NAN

  void clear() { for (int i = 0; i < 4; i++) ang[i] = NAN; }
  int known() const { int k = 0; for (int i = 0; i < 4; i++) if (!isnan(ang[i])) k++; return k; }

  /// r の回転のときの傾き (覚えていなければ予想)。何も覚えていなければ false
  bool expect(int r, float* out) const {
    r &= 3;
    if (!isnan(ang[r])) { *out = ang[r]; return true; }
    int k0 = -1;
    for (int i = 0; i < 4; i++) if (!isnan(ang[i])) { k0 = i; break; }
    if (k0 < 0) return false;
    float dir = 1.f;
    for (int k = 0; k < 4; k++) {           // 隣り合う (90° 違う) 2つから回り方を決める
      if (k == k0 || isnan(ang[k]) || !((k - k0) & 1)) continue;
      int dr = (k - k0 + 4) & 3;
      float d = hxm_wrap180(ang[k] - ang[k0]);
      float e = hxm_wrap180(90.f * dr);
      dir = fabsf(hxm_wrap180(d - e)) <= fabsf(hxm_wrap180(d + e)) ? 1.f : -1.f;
      break;
    }
    int dr = (r - k0 + 4) & 3;
    *out = hxm_wrap180(ang[k0] + dir * 90.f * dr);
    return true;
  }

  /// いまの傾き a にいちばん合う回転。diff にずれ (度)。何も覚えていなければ -1
  int best(float a, float* diff) const {
    int b = -1; float bd = 1e9f;
    for (int r = 0; r < 4; r++) {
      float e;
      if (!expect(r, &e)) return -1;
      float d = fabsf(hxm_wrap180(a - e));
      if (d < bd) { bd = d; b = r; }
    }
    if (diff) *diff = bd;
    return b;
  }

  /// 回転 r のときの傾きは a。同じ傾き (45° 以内) で覚えていた別の回転は忘れる (言い直し)
  void learn(int r, float a) {
    r &= 3;
    for (int k = 0; k < 4; k++)
      if (k != r && !isnan(ang[k]) && fabsf(hxm_wrap180(ang[k] - a)) < 45.f) ang[k] = NAN;
    ang[r] = hxm_wrap180(a);
  }
};

/// 振ったのを見つける: 2G を超える揺れが 0.8 秒の間に3回 → true。そのあと 1.5 秒は見ない
struct HxmShake {
  uint32_t last = 0, first = 0, cool = 0;
  int n = 0;
  bool feed(float mag, uint32_t now) {
    if ((int32_t)(now - cool) < 0) return false;
    if (mag > 2.0f && (int32_t)(now - last) > 120) {
      if (n == 0 || (int32_t)(now - first) > 800) { n = 0; first = now; }
      n++; last = now;
      if (n >= 3) { n = 0; cool = now + 1500; return true; }
    }
    return false;
  }
};
