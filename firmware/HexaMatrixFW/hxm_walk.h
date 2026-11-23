// HEXA MATRIX 歩行モード (v0.12、Stackchan Strider × CoreMatrix + FEETECH FS90R)。Arduino に依存しない
//
//   CoreMatrix の M5-Bus の GPIO から 50Hz のサーボパルスを出し、連続回転サーボ FS90R で
//   Strider (ヤンセン脚 4 本・傘歯車 1:1) を前後に歩かせる。
//
//   WALK (0x08) len=3:  int8 速さ (-100〜100 %、正=前進、0=止まる)
//                       u8   この指令の有効時間 (0.1 秒単位。0 なら 5 = 0.5 秒)
//                       u8   顔 (0=おまかせ / 1〜5 / 6=箱庭のキャラ (v0.13) / 0xFF=そのまま)
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
  uint16_t accMs = 300;  // v0.13.3: 0 → 100% にかける時間 (動き出しのつんのめり防止)
  uint16_t decMs = 900;  // v0.13.3: 100% → 0 にかける時間 (止まる時の慣性で前に倒れないように)
  uint16_t pulseOn = 0;  // v0.13.4: 刻んで歩く。動く時間 ms (0 = なめらかに続けて歩く)
  uint16_t pulseOff = 0; //          休む時間 ms (続けて回すと曲がる個体向け。ボタン連打と同じ動き)
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
  float    out = 0.f;          // v0.13.3: 実際にサーボへ出している速さ % (指令へ向けてゆっくり寄せる)
  uint32_t rampAt = 0;
  uint32_t moveAt = 0;         // v0.13.4: 動き始めた時刻 / 向きを変えた時刻 (刻みの位相の基準)

  /// 出す速さを指令へ寄せる。速くする時は accMs、遅くする・止める・逆へ回す時は decMs で 100% 分動く
  int ramp(uint32_t now, const HxmWalkCfg& c) {
    float dt = rampAt ? (float)(uint32_t)(now - rampAt) : 0.f;
    rampAt = now;
    if (dt > 200.f) dt = 200.f;
    int lim = c.maxPct > 100 ? 100 : c.maxPct;
    float tgt = moving ? (float)(spd > lim ? lim : spd < -lim ? -lim : spd) : 0.f;
    if (moving && c.pulseOn && c.pulseOff) {               // 刻む: 動く → 休む をくり返す
      uint32_t ph = (uint32_t)(now - moveAt) % ((uint32_t)c.pulseOn + c.pulseOff);
      if (ph >= c.pulseOn) tgt = 0.f;
    }
    if (out == tgt) return (int)out;
    bool speedUp = (tgt > 0 && out >= 0 && tgt > out) || (tgt < 0 && out <= 0 && tgt < out);
    uint16_t ms = speedUp ? c.accMs : c.decMs;
    float step = ms ? 100.f * dt / (float)ms : 1000.f;
    float before = out;
    if (out < tgt) { out += step; if (out > tgt) out = tgt; }
    else           { out -= step; if (out < tgt) out = tgt; }
    if (out == 0.f && before != 0.f && !moving) stopAt = now;   // 止まりきった所から中立 0.3 秒
    float a = out < 0 ? -out : out;
    return a < 0.5f ? 0 : (int)(out < 0 ? out - 0.5f : out + 0.5f);
  }
  void halt() { out = 0.f; }                                    // すぐ止める (番組へ移る時など)

  /// WALK パケット。戻り値: 動きが変わった
  bool command(int8_t s, uint8_t ttl, uint8_t f, uint32_t now) {
    cmds++;
    if (f != 0xFF) face = f;
    until = now + (uint32_t)(ttl ? ttl : 5) * 100u;
    bool was = moving;
    if (s != 0 && (!was || (s > 0) != (spd > 0))) moveAt = now;   // 動き始め・向きを変えた時から刻みを数える
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
    if (!moving && pulsing && out == 0.f && (int32_t)(now - stopAt) > 300) pulsing = false;   // 中立 0.3 秒 → パルスを止める
    return false;
  }
};

// ---------------------------------------------------------------- その場旋回 (v0.13.6)
//   クランクを前後に往復させると、往復の中心 (脚の位相) によってはその場で向きが変わる (上流の実機の結果と同じ)。
//   FS90R は位置が読めないので、ジャイロで「狙った向きに回っているか」を 2 往復ごとに見て、
//   回っていなければ片道の半分だけ前へ送って位相をずらす (逆に大きく回っていたら 1 片道ぶん送る)。
struct HxmTurn {
  int8_t   dir = 0;            // +1 左 (上から見て反時計回り) / −1 右 (時計回り) / 0 しない
  uint16_t half = 350;         // 片道 ms (v0.13.7: 実機のスキャンで 350 が強かった)
  uint32_t until = 0;          // 指令の期限
  uint8_t  ph = 0;             // 0 落ち着く / 1 往復 / 2 位相送り (大きく)
  uint16_t sendMs = 0;         // 位相送りの長さ
  int16_t  swing = 0;
  int16_t  nudge = 0;          // v0.13.7: このブロックの最初の前の片道に足す ms (± で往復の中心を少しずらす)
  int8_t   nudgeDir = 1;
  int8_t   corrDir = 1;        // つかんだ後、回る量が減った時に位相を直す向き (うまくいった向きを覚える)
  bool     corrPending = false;
  uint8_t  bad = 0;            // 続けて外れたブロック数
  uint32_t at = 0;
  float    y0 = 0.f, prevD = -1000.f;
  float    earlyDeg = 5.f;      // v0.13.8: これだけ逆へ回ったらブロックの途中でも位相を送る
  float    goodDeg = 15.f;     // 2 往復 (片道 350ms なら 1.4 秒) でこれだけ狙った向きに回れば当たり
  uint32_t blocks = 0, sends = 0, nudges = 0;

  void command(int8_t d, uint8_t ttl, uint32_t now) {
    if (d != dir) {
      dir = d; ph = 0; at = now; swing = 0; nudge = 0; bad = 0; prevD = -1000.f; locked = false; around = 0;
      int k = d > 0 ? 1 : 0;
      if (d && lockOk[k]) {                            // 覚えた所へ直接行く
        float delta = lockP[k] - P;
        float a = delta < 0 ? -delta : delta;
        if (a > 4.f * half) a = 4.f * half;
        if (a > 30.f) { ph = 2; sendDir = delta < 0 ? -1 : 1; sendMs = (uint16_t)a; jumps++; }
      }
    }
    until = now + (uint32_t)(ttl ? ttl : 5) * 100u;
  }
  bool active() const { return dir != 0; }
  uint32_t strokeMs() const { return swing == 0 ? (uint32_t)((int)half + nudge) : half; }
  bool     locked = false;     // 当たりの位相をつかんでいる
  bool     warm = false;       // 位相を送った直後は少し測らない (回り方が落ち着くまで)
  uint8_t  warmSwings = 2;     // その長さ (片道の数)
  // v0.13.9: 位相の覚え書き。旋回の間だけ「前へ回した時間 − 後へ回した時間」(ms) を数え、当たりをつかんだ所を向きごとに覚える。
  //          歩くと分からなくなるので、歩いたら forget() で忘れる。左右を続けて切り替える時は覚えた所へ直接行く
  float    P = 0.f;
  float    lockP[2] = {0.f, 0.f};
  bool     lockOk[2] = {false, false};
  uint32_t lastTick = 0;
  int      lastOut = 0;
  uint32_t jumps = 0;
  float    bestD[2] = {0.f, 0.f};
  // 左の当たりと右の当たりの間の距離 (ms)。歩いても変わらない (脚のつくりで決まる) ので forget() では忘れない。
  // 探している最中に逆向きへ大きく回ったら (= 逆の当たりにいる)、この距離だけ一気に送る
  float    offset = 0.f;       // 左 − 右
  bool     offsetOk = false;
  bool     offsetNew = false;  // 覚え直した (本体に保存してもらう合図)
  void learnOffset() {
    if (!lockOk[0] || !lockOk[1]) return;
    float o = lockP[1] - lockP[0];
    if (!offsetOk || fabsf(o - offset) > 20.f) { offset = o; offsetOk = true; offsetNew = true; }
  }
  void forget() { lockOk[0] = lockOk[1] = false; bestD[0] = bestD[1] = 0.f; }
  int8_t   sendDir = 1;        // 位相送りの向き (+ 前 / − 後)
  uint8_t  around = 0;         // つかみ損ねた所のまわりを前後に探している段 (0 = していない)
  int8_t   aroundFirst = -1;   // まわりを探す時に先に行く向き。見つかった向きを覚える (中心がずれていく向き)
  int8_t   aroundPos = 0;      // 見失った所からいまどれだけ離れたか (片道の 1/4 単位)
  /// 探す間は 1 往復ごと、つかんだら 2 往復ごとに見る
  int blockSwings() const { return locked ? 4 : 2; }
  /// 探す: 外れならすぐ位相を送る (逆に大きく回っていたら片道ぶん、そうでなければ半分)。当たればつかむ。
  /// つかんだ後: 少しずつ位相をずらして回る量が増える向きを追う (山登り)。2 回続けて外れたら探し直す
  void judge(float d) {
    blocks++;
    if (!locked) {
      if (d >= goodDeg * 0.5f) {
        if (around && aroundPos) corrDir = aroundFirst = aroundPos > 0 ? 1 : -1;   // 見つかった側を次は先に探す
        locked = true; bad = 0; around = 0; prevD = d * 2.f; nudge = 0; corrPending = false;
        { int k = dir > 0 ? 1 : 0; if (!lockOk[k] || d * 2.f > bestD[k]) { lockP[k] = P; bestD[k] = d * 2.f; } lockOk[k] = true; learnOffset(); }
        return;
      }
      ph = 2; sends++; nudge = 0;
      if (around && around <= 6) {                     // 見失った所のまわり: 先に行く向きに 1, 逆へ 1, 2, 2, 3, 3 (片道の 1/4 きざみ)
        static const int8_t pos[6] = {1, -1, 2, -2, 3, -3};
        int target = pos[around - 1] * aroundFirst;
        int m = target - aroundPos;
        aroundPos = (int8_t)target;
        sendDir = m < 0 ? -1 : 1;
        sendMs = (uint16_t)((m < 0 ? -m : m) * (half / 4));
        around++;
        return;
      }
      around = 0;
      if (d < -goodDeg && offsetOk) {                  // 逆の当たりにいる → 覚えた距離だけ一気に送る
        float delta = dir > 0 ? offset : -offset;
        float a = delta < 0 ? -delta : delta;
        if (a > 4.f * half) a = 4.f * half;
        sendDir = delta < 0 ? -1 : 1; sendMs = (uint16_t)(a < 30.f ? 30.f : a); jumps++;
        return;
      }
      sendDir = 1;
      sendMs = d < -goodDeg ? half : half / 2;
      return;
    }
    if (d > bestD[dir > 0 ? 1 : 0]) { bestD[dir > 0 ? 1 : 0] = d; lockP[dir > 0 ? 1 : 0] = P; learnOffset(); }   // いちばん回った所を覚える
    if (d < goodDeg) {
      if (++bad >= 2) {
        locked = false; bad = 0; prevD = -1000.f; nudge = 0; around = 1; aroundPos = 0; aroundFirst = corrDir;
        return;
      }
    } else bad = 0;
    // 当たりの間: 回る量が減ってきたら (中心がずれていく個体)、片道の 1/4 だけ位相を直す。
    // 直して増えればその向きを覚え、増えなければ逆へ 2 倍直す
    int16_t q = (int16_t)(half / 4);
    if (corrPending && d >= prevD) corrPending = false;            // 直した向きで良くなった
    if (prevD > -999.f && d < prevD * 0.8f) {
      if (corrPending) { corrDir = -corrDir; nudge = corrDir * 2 * q; }
      else nudge = corrDir * q;
      corrPending = true; nudges++;
    } else nudge = 0;
    if (d > prevD || nudge == 0) prevD = d;
  }
  /// 毎回。戻り値はサーボへ出す速さ % (+100 前 / −100 後 / 0)
  int tick(uint32_t now, float yaw) {
    int o = tickOut(now, yaw);
    if (lastTick) P += (float)lastOut / 100.f * (float)(uint32_t)(now - lastTick);
    lastTick = now; lastOut = o;
    return o;
  }
  int tickOut(uint32_t now, float yaw) {
    if (dir && (int32_t)(now - until) > 0) dir = 0;
    if (!dir) return 0;
    uint32_t el = now - at;
    switch (ph) {
      case 0:
        if (el < 150) return 0;
        ph = 1; swing = 0; at = now; y0 = yaw; nudge = 0;
        return 100;
      case 1:
        if (!warm && (yaw - y0) * dir < -earlyDeg) {          // v0.13.8: 逆へ大きく回り出したら待たずに位相を送る
          float d = (yaw - y0) * dir;
          y0 = yaw; swing = 0; at = now;
          if (locked) { locked = false; bad = 0; prevD = -1000.f; around = 0; }
          judge(d);
          return ph == 2 ? (sendDir > 0 ? 100 : -100) : 100;
        }
        if (el < strokeMs()) return (swing & 1) ? -100 : 100;
        swing++; at = now;
        if (warm && swing >= warmSwings) { warm = false; swing = 0; y0 = yaw; return 100; }
        if (swing >= blockSwings()) {                         // 探す間は 1 往復、つかんだら 2 往復ごとに見る
          float d = (yaw - y0) * dir;
          y0 = yaw; swing = 0;
          judge(d);
          if (ph == 2) return sendDir > 0 ? 100 : -100;
        }
        return (swing & 1) ? -100 : 100;
      default:                                                // 位相送り (前へ / 後へ)
        if (el < sendMs) return sendDir > 0 ? 100 : -100;
        ph = 1; swing = 0; at = now; y0 = yaw; nudge = 0; warm = true;
        return 100;
    }
  }
};

// ---------------------------------------------------------------- まっすぐ補正 (v0.13.8)
//   歩き始め (向きを変えた時) から 0.6 秒後の向きを覚え、ずれがしきい値を超えたら止まって旋回で戻す。
//   - ずれは 0.5 秒の平均で見る (一歩ごとの揺れで動き出さない)
//   - 戻す間は生の向きで見て、基準を越えたら (1° 手前で) やめる。逆向きに切り替えない (行ったり来たりしない)
//   - 8 秒で戻せなかったら、いまの向きを新しい基準にしてあきらめる (止まって回るのをくり返さない)
struct HxmHead {
  bool     fix = false, refOk = false;
  float    ref = 0.f, yf = 0.f;
  int8_t   fixDir = 0;
  uint32_t moveAt = 0, fixAt = 0, lastAt = 0;
  uint32_t fixes = 0, giveups = 0;
  /// 戻り値: 0 = ふつうに歩く / ±1 = この向きに旋回して戻す (+ 左 / − 右、ヨー角の + の向き)
  int8_t tick(uint32_t now, float yaw, bool on, uint8_t th, bool moving, uint32_t mvAt) {
    float dt = lastAt ? (float)(uint32_t)(now - lastAt) : 0.f;
    lastAt = now;
    if (!on || !moving) { fix = false; refOk = false; yf = yaw; return 0; }
    if (mvAt != moveAt) { moveAt = mvAt; refOk = false; fix = false; yf = yaw; }
    float k = dt / 500.f; if (k > 1.f) k = 1.f;
    yf += (yaw - yf) * k;
    if (!refOk) {
      if ((int32_t)(now - mvAt) > 600) { ref = yf; refOk = true; }
      return 0;
    }
    if (!fix) {
      float e = yf - ref;
      if (e < (float)th && e > -(float)th) return 0;
      fix = true; fixAt = now; fixDir = e > 0 ? -1 : 1; fixes++;
    }
    float e = yaw - ref;
    if (fixDir < 0 ? e <= 1.f : e >= -1.f) { fix = false; yf = yaw; return 0; }      // 戻った
    if ((int32_t)(now - fixAt) > 8000) { fix = false; ref = yaw; yf = yaw; giveups++; return 0; }
    return fixDir;
  }
};

// ---------------------------------------------------------------- 顔 (16x16、各行 MSB が左)
//   純正スタックチャン (M5Stack-Avatar) の顔を 16x16 に縮めたもの:
//   小さな黒目 2 つ (2x2、間隔 6 マス) と横一文字の口 (4 マス)。Avatar の比率 (320x240 で目 x=90/230 y=93、口 y=148) に合わせる
//   ・まばたき (3.2 秒ごと)・息 (上下 1 マス、歩くと速い)・目線 (時々左右に 1 マス)
enum : uint8_t { HXW_FACE_AUTO = 0, HXW_FACE_NORMAL = 1, HXW_FACE_SMILE = 2, HXW_FACE_WOW = 3, HXW_FACE_SLEEPY = 4, HXW_FACE_ANGRY = 5,
                 HXW_FACE_CHAR = 6,      // 箱庭のキャラ (hxm_char.h のエンジンで動かす。顔の絵はファーム側)
                 HXW_FACE_N = 7 };


/// face: 1〜5、dir: 進む向き (-1/0/1、0 以外は歩いている)、t: ms。rows に 16 行を書く
static inline void hxm_walk_face(uint16_t* rows, uint8_t face, int dir, uint32_t t) {
  for (int i = 0; i < 16; i++) rows[i] = 0;
  const bool walking = dir != 0;
  // 息: 止まっている時は 3 秒でゆっくり、歩くと 1 歩ごと (0.25 秒) に上下
  int dy = walking ? (int)((t / 250) & 1) : ((t % 3000) < 1500 ? 0 : 1);
  // 目線: 4.7 秒ごとに 0.6 秒だけ左右どちらかを見る (歩いている間は前を見る)
  int dx = 0;
  if (!walking && (t % 4700) < 600) dx = ((t / 4700) & 1) ? 1 : -1;
  const bool blink = (t % 3200) < 130 && face != HXW_FACE_SLEEPY;
  auto px = [&](int y, int x) { y += dy; if (y >= 0 && y < 16 && x >= 0 && x < 16) rows[y] |= (uint16_t)(0x8000 >> x); };
  const int EY = 5, LX = 4, RX = 10, MY = 10;     // 目の上の行 / 左目と右目の左の列 / 口の行
  // 目
  for (int e = 0; e < 2; e++) {
    int x = (e ? RX : LX) + dx;
    if (blink) { px(EY + 1, x); px(EY + 1, x + 1); continue; }               // まばたき: 横線
    switch (face) {
      case HXW_FACE_SMILE:  px(EY + 1, x - 1); px(EY, x); px(EY, x + 1); px(EY + 1, x + 2); break;   // にっこり ^
      case HXW_FACE_SLEEPY: px(EY + 1, x); px(EY + 1, x + 1); break;                                 // ねむい -
      case HXW_FACE_WOW:    px(EY - 1, x); px(EY - 1, x + 1); px(EY, x - 1); px(EY, x + 2);           // びっくり: 大きい目
                            px(EY + 1, x - 1); px(EY + 1, x + 2); px(EY + 2, x); px(EY + 2, x + 1); break;
      default:              px(EY, x); px(EY, x + 1); px(EY + 1, x); px(EY + 1, x + 1); break;         // ふつう・おこ: 黒目 2x2
    }
  }
  if (face == HXW_FACE_ANGRY && !blink) {        // おこ: 眉 (\ /)
    px(EY - 3, LX - 1); px(EY - 3, LX); px(EY - 2, LX + 1);
    px(EY - 2, RX); px(EY - 3, RX + 1); px(EY - 3, RX + 2);
  }
  // 口 (Avatar と同じ横一文字が基本)
  switch (face) {
    case HXW_FACE_SMILE:
      if (walking && ((t / 250) & 1)) {          // 歩いている間はしゃべるように口が開く
        for (int x = 6; x <= 9; x++) { px(MY - 1, x); px(MY, x); }   // Avatar の口パクと同じ、塗った四角
      } else { px(MY - 1, 5); px(MY - 1, 10); for (int x = 6; x <= 9; x++) px(MY, x); }   // 口角が上がる
      break;
    case HXW_FACE_WOW:    px(MY - 1, 7); px(MY - 1, 8); px(MY, 6); px(MY, 9); px(MY + 1, 7); px(MY + 1, 8); break;  // o
    case HXW_FACE_SLEEPY: px(MY, 7); px(MY, 8); break;
    case HXW_FACE_ANGRY:  px(MY, 5); for (int x = 6; x <= 9; x++) px(MY - 1, x); px(MY, 10); break;   // への字
    default:              for (int x = 6; x <= 9; x++) px(MY, x); break;
  }
}

/// おまかせの顔: 歩いていればにっこり、止まって 20 秒でねむい
static inline uint8_t hxm_walk_autoface(bool moving, uint32_t idleMs) {
  if (moving) return HXW_FACE_SMILE;
  return idleMs > 20000 ? HXW_FACE_SLEEPY : HXW_FACE_NORMAL;
}
