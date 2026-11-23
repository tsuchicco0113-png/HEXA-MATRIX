#include <cstdio>
#include <cassert>
#include <initializer_list>
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
  {   // v0.13.7: その場旋回。実機のスキャン結果を位相の関数にした模型で、前の方が少し速い / 遅い (往復すると中心がずれていく)
      //          場合も含めて、左右とも位相を見失わずに回り続けるか
    auto sim = [](int dir, float fwdGain, float startCrank, unsigned& sends, unsigned& nudges) {
      HxmTurn t; t.half = 350;
      float crank = startCrank, yaw = 0.f, center = crank;
      auto rateAt = [](float c) {          // 実機の旋回スキャン (片道 350ms、2026-11-23) の 8 段を、1 段 = 0.0525 周として周期的に並べたもの
        static const float r[8] = {-28, 86, 78, -86, -161, -15, 200, -33};   // 5 往復 (3.5 秒) で回った角度
        float k = c / 0.0525f;
        k -= 8.f * floorf(k / 8.f);
        int i = (int)k; float f = k - i;
        return (r[i] * (1 - f) + r[(i + 1) % 8] * f) / 3.5f;
      };
      for (uint32_t now = 0; now < 20000; now += 10) {
        if (now % 1000 == 0) t.command(dir, 50, now);
        int o = t.tick(now, yaw);
        crank += o * 0.01f * 0.003f * (o > 0 ? fwdGain : 1.f);
        center += (crank - center) * 0.05f;          // 往復の中心 ≒ 位相の 0.2 秒の移動平均
        yaw += rateAt(center) * 0.01f;
      }
      sends = t.sends; nudges = t.nudges;
      return yaw;
    };
    float sumL = 0.f, sumR = 0.f; int n = 0;
    for (float g : {1.0f, 1.04f, 0.96f}) {
      for (float c0 : {0.0f, 0.35f, 0.7f}) {
        unsigned s1, n1, s2, n2;
        float l = sim(+1, g, c0, s1, n1), r = sim(-1, g, c0, s2, n2);
        printf("gain %.2f start %.2f: left %.0f (sends %u) right %.0f (sends %u)\n", g, c0, l, s1, r, s2);
        fflush(stdout); assert(l > 0.f && r < 0.f);      // どの場合も狙った向きへは回る
        sumL += l; sumR += r; n++;
      }
    }
    printf("avg left %.0f right %.0f (20 s)\n", sumL / n, sumR / n);
    {   // v0.13.9: 左右を 5 秒ずつ切り替える。2 回目からは覚えた所へ直接行くので早く回り出す
      HxmTurn t; t.half = 350;
      float crank = 0.2f, center = 0.2f, yaw = 0.f;
      auto rate8 = [](float c) {
        static const float r[8] = {-28, 86, 78, -86, -161, -15, 200, -33};
        float k = c / 0.0525f; k -= 8.f * floorf(k / 8.f);
        int i = (int)k; float f = k - i;
        return (r[i] * (1 - f) + r[(i + 1) % 8] * f) / 3.5f;
      };
      float got[8];
      for (int seg = 0; seg < 8; seg++) {
        int d = (seg & 1) ? -1 : 1;
        float y0 = yaw;
        for (uint32_t k = 0; k < 5000; k += 10) {
          uint32_t now = seg * 5000 + k;
          if (k % 1000 == 0) t.command(d, 50, now);
          int o = t.tick(now, yaw);
          crank += o * 0.01f * 0.003f;
          center += (crank - center) * 0.05f;
          yaw += rate8(center) * 0.01f;
        }
        got[seg] = (yaw - y0) * d;
      }
      fprintf(stderr, "switch: L %.0f R %.0f L %.0f R %.0f L %.0f R %.0f L %.0f R %.0f (jumps %u)\n",
             got[0], got[1], got[2], got[3], got[4], got[5], got[6], got[7], (unsigned)t.jumps);
      for (int seg = 2; seg < 8; seg++) assert(got[seg] > 40.f);   // 2 回目からは覚えた所へ直接行く
      // 歩いて位置を忘れても、左右の距離は覚えている。右の当たりにいる時に左を頼むと一気に送って回り出す
      t.forget(); t.command(0, 1, 50000);
      assert(t.offsetOk);
      float y0 = yaw; uint32_t start = 50000;
      while (fmodf(center / 0.0525f, 8.f) < 3.2f || fmodf(center / 0.0525f, 8.f) > 4.0f) { crank += 0.0003f; center = crank; }   // 右の当たりへ歩く
      for (uint32_t k = 0; k < 5000; k += 10) {
        uint32_t now = start + k;
        if (k % 1000 == 0) t.command(1, 50, now);
        int o = t.tick(now, yaw);
        crank += o * 0.01f * 0.003f;
        center += (crank - center) * 0.05f;
        yaw += rate8(center) * 0.01f;
      }
      fprintf(stderr, "after walk, from right window: left %.0f in 5 s (jumps %u)\n", yaw - y0, (unsigned)t.jumps);
      assert(yaw - y0 > 40.f);
    }
    assert(sumL / n > 250.f && sumR / n < -250.f);
    HxmTurn t; t.command(1, 1, 0); t.until = 0; assert(t.tick(10, 0) == 0 && !t.active());   // 期限切れで止まる
    puts("turn ok");
  }
  {   // v0.13.8: まっすぐ補正。歩くと −4°/s で時計回りにずれ、一歩ごとに ±3° 揺れる機体を 40 秒歩かせる
    HxmHead h; HxmTurn t; t.half = 350;
    auto rateAt = [](float c) {
      static const float r[8] = {-28, 86, 78, -86, -161, -15, 200, -33};
      float k = c / 0.0525f; k -= 8.f * floorf(k / 8.f);
      int i = (int)k; float f = k - i;
      return (r[i] * (1 - f) + r[(i + 1) % 8] * f) / 3.5f;
    };
    float crank = 0.f, center = 0.f, base = 0.f, maxE = 0.f;
    int reversals = 0; int8_t lastDir = 0; uint32_t walkMs = 0;
    for (uint32_t now = 0; now < 40000; now += 10) {
      float wob = 3.f * sinf(now * 0.00628f);              // 1 Hz の揺れ
      float yaw = base + wob;
      int8_t hd = h.tick(now, yaw, true, 10, true, 0);
      if (hd) {
        if (lastDir && hd != lastDir) reversals++;
        if (!t.active() || t.dir != hd) t.command(hd, 50, now); else t.command(hd, 50, now);
        int o = t.tick(now, yaw);
        crank += o * 0.01f * 0.003f;
        center += (crank - center) * 0.05f;
        base += rateAt(center) * 0.01f;
      } else {
        if (t.active()) t.command(0, 1, now);
        t.forget();                                        // 歩いたら覚えた位置は忘れる (本体と同じ)
        crank += 0.6f * 0.003f;                            // 60% で歩く
        center = crank;
        base += -4.f * 0.01f;
        walkMs += 10;
      }
      if (!hd) lastDir = 0; else lastDir = hd;
      if (now > 2000) { float e = fabsf(base); if (e > maxE) maxE = e; }
    }
    printf("head: fixes %u giveups %u reversals %d max error %.0f walk %.0f%%\n", (unsigned)h.fixes, (unsigned)h.giveups,
           reversals, maxE, walkMs / 400.f);
    assert(h.giveups == 0 && reversals == 0);
    assert(maxE < 40.f);                 // しきい値 10° + 揺れ + 平均の遅れ + 位相を探す間に逆へ回る分
    assert(walkMs > 40000 * 0.5);        // 半分以上の時間は歩いている
    // 止まったら補正はしない / 歩き直すと基準を取り直す
    assert(h.tick(50000, 90.f, true, 10, false, 0) == 0 && !h.fix);
    assert(h.tick(50010, 90.f, true, 10, true, 50000) == 0);
    assert(h.tick(50700, 90.f, true, 10, true, 50000) == 0 && h.refOk && fabsf(h.ref - 90.f) < 0.5f);
    assert(h.tick(50710, 120.f, false, 10, true, 50000) == 0);   // 補正を切ったら何もしない
    puts("head ok");
  }
  {  // v0.14.0: 旋回の自動調整
    const uint16_t hv[3] = {250, 350, 450};
    float rr[3][8] = {{10, -12, 30, -9, 5, 18, -14, 3},              // 250: 左右とも弱い → 失格
                      {-28, 86, 78, -86, -161, -15, 200, -33},       // 350: 実機の値 (min 161 / 3.5 秒 = 46°/s)
                      {40, 220, 60, -50, -120, 10, 150, -30}};       // 450: 右が 120 / 4.5 秒 = 27°/s
    HxmCalPick p = hxm_cal_pick(rr, hv, 3, 10);
    assert(p.idx == 1 && fabsf(p.worst - 161.f) < 0.1f && fabsf(p.good - 12.88f) < 0.05f && p.early > 4.f && p.early < 4.5f);
    float bad[1][8] = {{0, 0, 0, 0, 0, 0, 0, 0}};
    assert(hxm_cal_pick(bad, hv, 1, 10).idx == -1);
    float big[1][8] = {{900, -900, 0, 0, 0, 0, 0, 0}};
    assert(hxm_cal_pick(big, hv, 1, 10).good == 30.f);
    puts("cal ok");
  }
  {  // v0.14.0: ジャイロの見張り
    HxmImuWatch w;
    uint32_t t = 0;
    for (; t < 3000; t += 10) assert(w.tick(t, true, 0.1f * (t % 70), 0.f, 0.f));     // 揺れている = 生きている
    for (; t < 3400; t += 10) w.tick(t, false, 0, 0, 0);
    assert(w.alive);                                                                  // 0.4 秒読めないだけなら大丈夫
    for (; t < 3600; t += 10) w.tick(t, false, 0, 0, 0);
    assert(!w.alive && w.deaths == 1);                                                // 0.5 秒超えたら死んだ
    assert(w.tick(t += 10, true, 1.f, 2.f, 3.f));                                    // 読めたら生き返る
    for (; t < 6000; t += 10) w.tick(t, true, 1.f, 2.f, 3.f);                        // 同じ値のまま 1.5 秒以上 = 固まった
    assert(!w.alive && w.deaths == 2);
    puts("imuwatch ok");
  }
  uint16_t r[16];
  for (int f = 1; f < HXW_FACE_N; f++) { hxm_walk_face(r, f, f == 2 ? 1 : f == 3 ? -1 : 0, 500); show(r); }
  puts("walk ok");
}
