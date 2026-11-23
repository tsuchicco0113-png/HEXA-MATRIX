#include <cstdio>
#include <cassert>
#include <cmath>
#include "../firmware/HexaMatrixFW/hxm_walk.h"   // g++ -std=c++17 tests/walk_test.cpp && ./a.out
static void show(const uint16_t* r) {
  for (int y = 0; y < 16; y++) { for (int x = 0; x < 16; x++) putchar(r[y] & (0x8000 >> x) ? '#' : '.'); putchar('\n'); }
  putchar('\n');
}
int main() {
  HxmWalkCfg c;
  assert(hxm_walk_us(c, 0) == 1500);
  assert(hxm_walk_us(c, 50) == 1500 + 50 + 200);
  assert(hxm_walk_us(c, -50) == 1500 - 250);
  assert(hxm_walk_us(c, 100) == 1500 + 50 + 240);          // 上限 60%
  c.inv = true; assert(hxm_walk_us(c, 50) == 1250);
  c.trim = 20; assert(hxm_walk_us(c, 0) == 1520);
  c.maxPct = 100; c.trim = 0; c.inv = false; c.span = 2000; assert(hxm_walk_us(c, 100) == 2300);   // 範囲で止める
  assert(hxm_walk_duty(1500, 14) == 1228);
  assert(fabsf(hxm_yaw_rate(0, 0, 1, 0, 0, 30) - 30.f) < 1e-4f);
  assert(fabsf(hxm_yaw_rate(0, -1, 0, 5, -40, 7) - 40.f) < 1e-4f);    // 立てて置いても「床のまわり」
  HxmWalk w;
  assert(w.command(40, 5, 0, 1000) && w.moving && w.pulsing);
  assert(!w.tick(1400) && w.moving);
  assert(w.tick(1501) && !w.moving && w.spd == 0 && w.timeouts == 1);   // 0.5 秒来なければ止まる
  assert(w.pulsing); w.tick(1700); assert(w.pulsing); w.tick(1802); assert(!w.pulsing);   // 中立 0.3 秒の後パルスを止める
  w.command(-30, 2, 0xFF, 2000); assert(w.moving && w.until == 2200);
  w.command(0, 5, 3, 2100); assert(!w.moving && w.face == 3);
  {   // v0.13.3: 加速・減速のランプ
    HxmWalkCfg c2;                       // acc 300ms / dec 900ms、上限 60%
    HxmWalk v;
    v.command(60, 50, 0, 10000); v.rampAt = 10000;
    assert(v.ramp(10000, c2) == 0);
    assert(v.ramp(10090, c2) == 30);     // 90ms で 30%
    assert(v.ramp(10180, c2) == 60);     // 上限で止まる
    assert(v.ramp(10300, c2) == 60);
    v.command(0, 5, 0xFF, 10300);        // 止める指令: すぐ 0 にはしない
    assert(v.ramp(10390, c2) == 50);     // 90ms で 10% ずつ落とす
    assert(v.pulsing);
    int o = 0; uint32_t t = 10390;
    while (t < 11000) { t += 30; o = v.ramp(t, c2); v.tick(t); }
    assert(o == 0 && v.out == 0.f && v.pulsing);            // 止まりきった直後はまだ中立を出す
    v.tick(t + 400); assert(!v.pulsing);                     // 中立 0.3 秒の後にパルスを止める
    v.command(60, 50, 0, 20000); v.rampAt = 20000; v.ramp(20200, c2); v.ramp(20400, c2);   // 前へ 60%
    v.command(-60, 50, 0, 20400);        // いきなり後ろ: まず減速 (dec) してから加速 (acc)
    assert(v.ramp(20490, c2) == 50);
    t = 20490; while (v.out > 0.f) { t += 30; v.ramp(t, c2); }
    assert(v.ramp(t + 60, c2) <= -19);   // 0 を越えたら acc の速さで後ろへ
    c2.decMs = 0; v.command(0, 5, 0xFF, 30000); assert(v.ramp(30010, c2) == 0);   // dec 0 = すぐ止まる
    puts("ramp ok");
  }
  {   // v0.13.4: 刻んで歩く (動く 400ms → 休む 300ms)
    HxmWalkCfg c3; c3.accMs = 0; c3.decMs = 0; c3.pulseOn = 400; c3.pulseOff = 300;
    HxmWalk v;
    v.command(50, 50, 0, 1000); v.rampAt = 1000;
    assert(v.ramp(1100, c3) == 50);
    assert(v.ramp(1399, c3) == 50);
    assert(v.ramp(1400, c3) == 0);      // 休む
    assert(v.ramp(1699, c3) == 0);
    assert(v.ramp(1700, c3) == 50);     // また動く
    v.command(50, 50, 0, 1750);          // 同じ向きの頼み直しでは位相を戻さない
    assert(v.ramp(2100, c3) == 0);
    v.command(-50, 50, 0, 2150);         // 向きを変えたら頭から
    assert(v.ramp(2200, c3) == -50);
    c3.pulseOff = 0; assert(v.ramp(2600, c3) == -50);   // 片方 0 なら刻まない
    puts("pulse ok");
  }
  {   // v0.13.6: その場旋回。クランクの位相 (0〜1 周) によって往復で回る向きが変わる模型で、狙った向きへ回れるか
    HxmTurn t; t.half = 250;
    float crank = 0.40f;                 // いまの位相 (周)。0.6〜0.8 で往復すると左、0.1〜0.3 で右に回るとする
    float yaw = 0.f;
    auto rateAt = [](float c) {          // 往復の中心 c での回る速さ (deg/s、+ が左)
      c -= floorf(c);
      if (c > 0.6f && c < 0.8f) return 40.f;
      if (c > 0.1f && c < 0.3f) return -40.f;
      return -3.f;                       // それ以外はわずかに時計回り (この個体のくせ)
    };
    float center = crank;
    t.command(+1, 50, 0);
    uint32_t now = 0; int prev = 0;
    for (; now < 20000; now += 10) {
      if (now % 1000 == 0) t.command(+1, 50, now);
      int o = t.tick(now, yaw);
      crank += o * 0.01f * 0.004f;       // 100% で 0.4 周/秒 (= 片道 250ms で 0.1 周)
      center += (crank - center) * 0.02f;          // 往復の中心 ≒ 位相の 0.5 秒の移動平均
      prev = o;
      yaw += rateAt(center) * 0.01f;
    }
    printf("turn left: yaw %.0f deg, sends %u\n", yaw, (unsigned)t.sends);
    assert(yaw > 300.f);                 // 20 秒でしっかり左へ回る (位相を探してから)
    t.command(-1, 50, now); float y1 = yaw;
    for (uint32_t end = now + 20000; now < end; now += 10) {
      if (now % 1000 == 0) t.command(-1, 50, now);
      int o = t.tick(now, yaw);
      crank += o * 0.01f * 0.004f;
      center += (crank - center) * 0.02f;          // 往復の中心 ≒ 位相の 0.5 秒の移動平均
      prev = o;
      yaw += rateAt(center) * 0.01f;
    }
    printf("turn right: yaw %.0f deg\n", yaw - y1);
    assert(yaw - y1 < -300.f);
    t.until = now - 1; assert(t.tick(now + 10, yaw) == 0 && !t.active());   // 期限切れで止まる
    puts("turn ok");
  }
  uint16_t r[16];
  for (int f = 1; f < HXW_FACE_N; f++) { hxm_walk_face(r, f, f == 2 ? 1 : f == 3 ? -1 : 0, 500); show(r); }
  puts("walk ok");
}
