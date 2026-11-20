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
  uint16_t r[16];
  for (int f = 1; f < HXW_FACE_N; f++) { hxm_walk_face(r, f, f == 2 ? 1 : f == 3 ? -1 : 0, 500); show(r); }
  puts("walk ok");
}
