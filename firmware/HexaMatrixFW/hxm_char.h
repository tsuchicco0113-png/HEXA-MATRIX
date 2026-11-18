// HEXA MATRIX 箱庭エンジン (v0.10)。Arduino に依存しない (PC でテストできる)
//
//   16×16 の箱の中にキャラが1体いる。本体の傾き (重力) で落ちる・転がる・ぶつかる・跳ねる。
//   ・重力の向きは4方向 (下/左/上/右)。本体を回すとキャラも回って、新しい「床」に立つ
//   ・アニメは「絵1枚」から自動で作る: まばたき / 目線 / 歩く脚 / 着地でつぶれる / 跳ぶと伸びる /
//     寝る (目を閉じて息をする) / 目が回る / 起きてびっくり
//     絵の中の「目」(体の中の穴) と「脚」(いちばん下の行の点のかたまり) を自分で見つける
//   ・数はすべて整数 (固定小数点)。同じ入力なら同じ動き (STUDIO の JS 版と揃えるため)
//
//   座標: 画面の左上が (0,0)、x は右、y は下。位置と速度は 1/256 マス単位 (Q8)。1回の step = 1/60 秒
//   入力: 画面の向きに直した加速度 (mg)。gx 右が +、gy 下が + (吊るして静止で gy ≒ +1000)
#pragma once
#include <stdint.h>
#include <string.h>
#include <type_traits>

enum : uint8_t { HXC_TAP = 1, HXC_SHAKE = 2, HXC_PET = 4, HXC_POKE = 8 };      // HxcIn.ev
enum HxcState : uint8_t { HXC_IDLE, HXC_WALK, HXC_AIR, HXC_LAND, HXC_DIZZY, HXC_SLEEP, HXC_WAKE, HXC_HAPPY };

struct HxcSprite {
  uint8_t  w = 0, h = 0;
  uint16_t rows[16] = {0};       // 1行ずつ。bit x (x=0 が左) が点
  bool px(int x, int y) const { return x >= 0 && y >= 0 && x < w && y < h && ((rows[y] >> x) & 1); }
  void set(int x, int y, bool on) { if (x >= 0 && y >= 0 && x < 16 && y < 16) { if (on) rows[y] |= (1u << x); else rows[y] &= ~(1u << x); } }
  /// "..##.." のような文字列 (# か 1 が点) を上の行から
  void parse(const char* const* lines, int n) {
    memset(rows, 0, sizeof rows); h = (uint8_t)(n > 16 ? 16 : n); w = 0;
    for (int y = 0; y < h; y++)
      for (int x = 0; lines[y][x] && x < 16; x++) {
        if (lines[y][x] == '#' || lines[y][x] == '1') rows[y] |= (1u << x);
        if (x + 1 > w) w = (uint8_t)(x + 1);
      }
  }
};

struct HxcParams {                 // キャラの「性格」(STUDIO で変える)
  int16_t grav   = 26;   // 重さ: 1G のときの加速 (Q8 マス/step²)。大きいほど速く落ちる
  int16_t maxv   = 170;  // 最高速度 (Q8 マス/step)
  uint8_t bounce = 80;   // 跳ね返り (/256)。0=ベチャ、200=スーパーボール
  uint8_t fric   = 36;   // 床のすべりにくさ (/256 毎 step)
  int16_t stick  = 140;  // この傾き (mg) までは床で滑らない (吊るした時の小さな揺れで動かない)
  int16_t jump   = 235;  // 叩いた時の跳ぶ強さ (Q8 マス/step)
  uint8_t whim   = 120;  // 気まぐれ (/255)。じっとしている時に勝手に跳ねる・見回す
  uint16_t sleepAfter = 60 * 25;   // これだけ (step) 静かなら寝る
  int16_t slosh  = 0;    // 回転の慣性 (ジャイロ)。0=使わない (実機で符号と強さを決める)
};

struct HxcIn {
  int16_t gx = 0, gy = 1000, gz = 0;   // mg、画面の向き
  int16_t wz = 0;                      // 画面に垂直な軸まわりの回転 (deg/s、右回り +)。slosh 用
  uint8_t ev = 0;                      // HXC_TAP など
};

struct HxcWorld {
  // ---- 設定
  HxcSprite sp;
  HxcParams pr;
  uint16_t terrain[16] = {0};          // 地形 (bit x が壁)
  // ---- 状態 (眠る前に丸ごと保存すれば、起きた時に続きから)
  int32_t  x = 0, y = 0, vx = 0, vy = 0;   // 体の箱の左上 (Q8)
  uint8_t  q = 0, qCand = 0; uint8_t qT = 0;   // 重力の向き 0=下 1=左 2=上 3=右
  HxcState st = HXC_IDLE;
  uint16_t stT = 0;                    // いまの状態の経過 (step)
  uint16_t still = 0;                  // 静かな時間 (step)
  uint16_t blinkT = 0, whimT = 0;
  int8_t   lookX = 0, lookY = 0;       // 目線 (-1/0/+1)
  int8_t   face = 1;                   // 向き (+1 右 / -1 左)
  uint8_t  walkPh = 0, walkT = 0;
  uint8_t  dizzyT = 0, landT = 0, wakeT = 0, happyT = 0;
  bool     grounded = false;
  int16_t  lgx = 0, lgy = 1000, lgz = 0;   // ならした加速度 (静かさの判定)
  int16_t  lastWz = 0;
  uint32_t rng = 1;
  uint32_t ticks = 0;
  // ---- 絵から見つけたもの
  int8_t eyeX[2] = {-1, -1}, eyeY[2] = {-1, -1};
  uint8_t legN = 0, legX0[6] = {0}, legX1[6] = {0};
  uint8_t midRow = 0;                  // つぶす・伸ばす時に消す/増やす行 (胴の真ん中)

  // ---------------------------------------------------------------- 準備
  void init(const HxcSprite& s, const HxcParams& p, uint32_t seed) {
    sp = s; pr = p; rng = seed ? seed : 1;
    analyze();
    q = qCand = 0; qT = 0;
    x = ((16 - sp.w) << 8) / 2; y = (16 - sp.h) << 8; vx = vy = 0;
    st = HXC_IDLE; stT = still = 0; blinkT = 120 + rnd(180); whimT = 240 + rnd(240);
    face = 1; ticks = 0;
  }
  /// 目 = 体の中の穴 (上下左右を体に囲まれた空き)。脚 = いちばん下の行の点のかたまり
  void analyze() {
    int ne = 0;
    eyeX[0] = eyeX[1] = eyeY[0] = eyeY[1] = -1;          // 前のキャラの目を残さない
    for (int yy = 1; yy < sp.h - 1 && ne < 2; yy++)
      for (int xx = 1; xx < sp.w - 1 && ne < 2; xx++)
        if (!sp.px(xx, yy) && sp.px(xx - 1, yy) && sp.px(xx + 1, yy) && sp.px(xx, yy - 1) && sp.px(xx, yy + 1)) {
          // 脚のすき間 (下の方) は目ではない: 目は体の上半分
          if (yy < sp.h / 2 + 1) { eyeX[ne] = (int8_t)xx; eyeY[ne] = (int8_t)yy; ne++; }
        }
    legN = 0;
    int last = sp.h - 1;
    for (int xx = 0; xx < sp.w && legN < 6; ) {
      if (sp.px(xx, last)) { int x0 = xx; while (xx < sp.w && sp.px(xx, last)) xx++; legX0[legN] = (uint8_t)x0; legX1[legN] = (uint8_t)(xx - 1); legN++; }
      else xx++;
    }
    // 胴の真ん中: 脚が始まる行 (下の行と同じ形になる最初の行) より上の真ん中
    int legTop = last;
    while (legTop > 0 && sp.rows[legTop - 1] == sp.rows[last]) legTop--;
    midRow = (uint8_t)(legTop > 2 ? legTop / 2 : sp.h / 2);
  }
  uint32_t rnd(uint32_t n) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return n ? rng % n : rng; }

  // ---------------------------------------------------------------- 向き
  int bw() const { return (q & 1) ? sp.h : sp.w; }      // 画面の上での箱の幅・高さ
  int bh() const { return (q & 1) ? sp.w : sp.h; }
  static void gdir(uint8_t qq, int& dx, int& dy) {        // 重力の向き (画面)
    dx = qq == 1 ? -1 : qq == 3 ? 1 : 0; dy = qq == 0 ? 1 : qq == 2 ? -1 : 0;
  }
  static void tdir(uint8_t qq, int& dx, int& dy) {        // キャラの「右」(画面)。render の回し方と同じ
    dx = qq == 0 ? 1 : qq == 2 ? -1 : 0; dy = qq == 1 ? 1 : qq == 3 ? -1 : 0;
  }

  // ---------------------------------------------------------------- 当たり
  bool solid(int px, int py, int w, int h) const {
    if (px < 0 || py < 0 || px + w > 16 || py + h > 16) return true;
    for (int yy = py; yy < py + h; yy++) {
      uint16_t m = (uint16_t)(((1u << w) - 1) << px);
      if (terrain[yy] & m) return true;
    }
    return false;
  }
  /// 1つの軸を動かす。ぶつかったら止めて跳ね返す。ぶつかった時の速さを返す (0=ぶつからない)
  int32_t moveAxis(bool isX) {
    int32_t& p = isX ? x : y; int32_t& v = isX ? vx : vy;
    int w = bw(), h = bh();
    int32_t np = p + v;
    int from = (int)(p >> 8), to = (int)(np >> 8);
    int step = to > from ? 1 : -1;
    for (int c = from; c != to; c += step) {
      int n = c + step;
      if (isX ? solid(n, (int)(y >> 8), w, h) : solid((int)(x >> 8), n, w, h)) {
        p = step > 0 ? ((int32_t)c << 8) + 255 : ((int32_t)c << 8);
        int32_t hit = v < 0 ? -v : v;
        v = -(v * pr.bounce) / 256;
        if ((v < 0 ? -v : v) < 24) v = 0;
        return hit;
      }
    }
    p = np;
    if (p < 0) p = 0;
    return 0;
  }
  bool onFloor() const {
    int dx, dy; gdir(q, dx, dy);
    return solid((int)(x >> 8) + dx, (int)(y >> 8) + dy, bw(), bh());
  }

  /// 重力の向きが変わった: 箱の縦横を入れ替える (真ん中を保って、はみ出たら押し戻す)
  // (nx,ny) の近くで、地形にも箱の外にもかからない場所を探して置く。無ければ false (v0.11.2)
  bool place(int nx, int ny) {
    const int w = bw(), h = bh();
    if (w > 16 || h > 16) return false;
    if (nx < 0) nx = 0; if (ny < 0) ny = 0;
    if (nx + w > 16) nx = 16 - w; if (ny + h > 16) ny = 16 - h;
    int dx, dy; gdir(q, dx, dy);
    for (int d = 0; d <= 30; d++) {
      for (int a = -d; a <= d; a++) {                  // 重力と逆向き (-dx,-dy) を先に試す
        const int b = d - (a < 0 ? -a : a);
        for (int sgn = -1; sgn <= 1; sgn += 2) {
          if (b == 0 && sgn > 0) break;
          // 重力の軸を o1、それと直角を o2
          const int o1 = -sgn * b, o2 = a;
          const int px = nx + (dx ? o1 * dx : o2), py = ny + (dy ? o1 * dy : o2);
          if (!solid(px, py, w, h)) { x = (int32_t)px << 8; y = (int32_t)py << 8; return true; }
        }
      }
    }
    return false;
  }
  void fit() { place((int)(x >> 8), (int)(y >> 8)); }   // 地形を入れた後、埋まっていたら近くへ逃がす

  bool setQ(uint8_t nq) {
    int cx = (int)(x >> 8) * 2 + bw(), cy = (int)(y >> 8) * 2 + bh();   // 中心 ×2
    const uint8_t oq = q; const int32_t ox = x, oy = y;
    q = nq;
    if (!place((cx - bw()) / 2, (cy - bh()) / 2)) { q = oq; x = ox; y = oy; return false; }   // 入らない向きには回らない
    vx = vy = 0;
    return true;
  }

  void enter(HxcState s) { if (st != s) { st = s; stT = 0; } }

  // ---------------------------------------------------------------- 1 step
  void step(const HxcIn& in) {
    ticks++;
    // 静かさ: ならした値からのずれ
    int dmove = abs16(in.gx - lgx) + abs16(in.gy - lgy) + abs16(in.gz - lgz);
    lgx += (in.gx - lgx) / 8; lgy += (in.gy - lgy) / 8; lgz += (in.gz - lgz) / 8;
    bool moving = dmove > 90 || in.ev;
    if (moving) still = 0; else if (still < 0xFFFF) still++;

    // 重力の向き (4方向)。はっきり傾いて 0.3 秒続いたら変える
    int ax = in.gx, ay = in.gy;
    int mag = abs16(ax) > abs16(ay) ? abs16(ax) : abs16(ay);
    uint8_t want = q;
    if (mag > 450) {
      if (abs16(ay) * 10 > abs16(ax) * 13) want = ay > 0 ? 0 : 2;
      else if (abs16(ax) * 10 > abs16(ay) * 13) want = ax < 0 ? 1 : 3;
    }
    if (want != q) { if (want == qCand) { if (++qT >= 18) { qT = 0; if (setQ(want)) enter(HXC_AIR); } } else { qCand = want; qT = 0; } }
    else qT = 0;

    // 寝ている: 動かされたら起きる
    if (st == HXC_SLEEP) {
      if (moving) { enter(HXC_WAKE); wakeT = 30; kick(-pr.jump * 2 / 3, 0); }
      else { stT++; animTick(); return; }
    }

    // 力
    int gdx, gdy; gdir(q, gdx, gdy);
    int tdx, tdy; tdir(q, tdx, tdy);
    grounded = onFloor();
    int32_t vn0 = vx * gdx + vy * gdy;                 // このステップで力を足す前の、床へ向かう速さ
    int32_t ax8 = (int32_t)ax * pr.grav / 1000, ay8 = (int32_t)ay * pr.grav / 1000;
    if (pr.slosh) {                    // 回転の慣性: 回し始めると中身が置いていかれる
      int32_t dw = in.wz - lastWz;
      int32_t rx = (x >> 8) + bw() / 2 - 8, ry = (y >> 8) + bh() / 2 - 8;
      ax8 += (int32_t)pr.slosh * dw * ry / 2048;
      ay8 -= (int32_t)pr.slosh * dw * rx / 2048;
    }
    lastWz = in.wz;
    int32_t at = ax8 * tdx + ay8 * tdy;                 // 床に沿った力
    int32_t aTmg = (int32_t)ax * tdx + (int32_t)ay * tdy;
    if (grounded && abs32(aTmg) < pr.stick) {          // 少しの傾きでは滑らない (静止摩擦)
      ax8 -= at * tdx; ay8 -= at * tdy;
    }
    vx += ax8; vy += ay8;
    if (grounded) {                                     // 床の摩擦 (床に沿った速さだけ減らす)
      int32_t vt = vx * tdx + vy * tdy;
      int32_t dec = vt * pr.fric / 256;
      vx -= dec * tdx; vy -= dec * tdy;
    } else { vx -= vx / 128; vy -= vy / 128; }          // 空気
    vx = clamp32(vx, -pr.maxv, pr.maxv); vy = clamp32(vy, -pr.maxv * 2, pr.maxv * 2);

    // イベント
    if (in.ev & HXC_SHAKE) { dizzyT = 120; enter(HXC_DIZZY); }
    if ((in.ev & (HXC_TAP | HXC_POKE)) && grounded) kick(-pr.jump, (int32_t)(rnd(3)) - 1);
    if (in.ev & HXC_PET) { happyT = 40; if (grounded) kick(-pr.jump / 2, 0); }

    // 気まぐれ: 静かに立っている時、ときどき跳ねる・見回す
    if (grounded && st != HXC_DIZZY && still > 120 && pr.whim) {
      if (whimT) whimT--;
      else {
        uint32_t r = rnd(256);
        if (r < pr.whim / 2) {
          int32_t k = (int32_t)rnd(3), t = (int32_t)rnd(3);   // 乱数を引く順番を決めておく (引数の中で引くと順番が決まらない)
          kick(-pr.jump * (2 + k) / 5, t - 1);
        }
        else { lookX = (int8_t)((int)rnd(3) - 1); lookY = (int8_t)((int)rnd(3) - 1); }
        whimT = (uint16_t)(150 + rnd(300) * (256 - pr.whim) / 128);
      }
    }

    // 動かす
    int32_t hitX = moveAxis(true), hitY = moveAxis(false);
    int32_t hitN = gdx ? hitX : hitY;                   // 床/天井にぶつかった速さ
    grounded = onFloor();
    // 床に落ちた: 力を足す前から床へ向かって動いていて (止まっているだけではなく)、強くぶつかった
    // (重い設定だと、止まっていても1ステップ分の重力だけで hitN が大きくなり、ずっと「着地」になっていた)
    if (vn0 > 40 && grounded && hitN > 60) { landT = hitN > 160 ? 10 : 6; }

    // 状態
    int32_t vt = vx * tdx + vy * tdy, vn = vx * gdx + vy * gdy;
    if (abs32(vt) > 20) face = vt > 0 ? 1 : -1;
    if (dizzyT) { dizzyT--; enter(HXC_DIZZY); }
    else if (wakeT) { wakeT--; enter(HXC_WAKE); }
    else if (landT) { landT--; enter(HXC_LAND); }
    else if (!grounded) enter(HXC_AIR);
    else if (happyT) { happyT--; enter(HXC_HAPPY); }
    else if (abs32(vt) > 18) enter(HXC_WALK);
    else if (still > pr.sleepAfter) enter(HXC_SLEEP);
    else enter(HXC_IDLE);
    (void)vn;
    stT++;
    animTick();
  }
  /// 跳ばす (n: 重力と逆向きの速さ、t: 横に -1/0/+1)
  void kick(int32_t n, int32_t t) {
    int gdx, gdy, tdx, tdy; gdir(q, gdx, gdy); tdir(q, tdx, tdy);
    vx += n * gdx + t * 60 * tdx; vy += n * gdy + t * 60 * tdy;
  }
  void animTick() {
    if (blinkT) blinkT--; else blinkT = (uint16_t)(150 + rnd(240));
    if (st == HXC_WALK) { if (++walkT >= 7) { walkT = 0; walkPh ^= 1; } }
    else walkPh = 0;
    if (st != HXC_IDLE && st != HXC_SLEEP && !(st == HXC_IDLE && still > 120)) {   // 動いている方を見る
      int tdx, tdy, gdx, gdy; tdir(q, tdx, tdy); gdir(q, gdx, gdy);
      int32_t vt = vx * tdx + vy * tdy, vn = vx * gdx + vy * gdy;
      lookX = (int8_t)(vt > 30 ? 1 : vt < -30 ? -1 : 0);
      lookY = (int8_t)(vn > 40 ? 1 : vn < -40 ? -1 : 0);
    }
  }

  // ---------------------------------------------------------------- 描画
  /// いまの絵 (体の向きのまま、足が下)。dh = 縦の伸び縮み (-1/0/+1)
  void pose(HxcSprite& o, int& dh, int& sway) const {
    o = sp; dh = 0; sway = 0;
    bool closed = false;
    int ex = lookX, ey = lookY;
    switch (st) {
      case HXC_LAND: dh = -1; break;
      case HXC_AIR: { int gdx, gdy; gdir(q, gdx, gdy); int32_t vn = vx * gdx + vy * gdy; dh = vn < -90 ? 1 : 0; break; }
      case HXC_WAKE: dh = (stT / 4) & 1 ? 1 : 0; ey = -1; break;
      case HXC_SLEEP: closed = true; dh = ((stT / 50) & 1) ? -1 : 0; ex = ey = 0; break;   // 寝息
      case HXC_DIZZY: ex = (int)((ticks / 5) % 3) - 1; ey = (int)((ticks / 7) % 3) - 1; sway = ((ticks / 6) & 1) ? 1 : -1; break;
      case HXC_HAPPY: closed = (stT / 6) & 1; break;
      default: break;
    }
    if (st == HXC_IDLE && blinkT < 7) closed = true;
    // 目: 元の穴を埋めて、目線の分ずらした所に開ける (体の外や輪郭には開けない)
    for (int i = 0; i < 2; i++) {
      if (eyeX[i] < 0) continue;
      o.set(eyeX[i], eyeY[i], true);
    }
    if (!closed)
      for (int i = 0; i < 2; i++) {
        if (eyeX[i] < 0) continue;
        int nx = eyeX[i] + ex * face, ny = eyeY[i] + ey;
        bool ok = sp.px(nx - 1, ny) && sp.px(nx + 1, ny) && sp.px(nx, ny - 1) && sp.px(nx, ny + 1) && sp.px(nx, ny);
        if (!ok) { nx = eyeX[i]; ny = eyeY[i]; }
        o.set(nx, ny, false);
      }
    // 歩く: 脚を交互に持ち上げる (いちばん下の行を消す)
    if (st == HXC_WALK)
      for (int k = 0; k < legN; k++)
        if ((k & 1) == walkPh)
          for (int xx = legX0[k]; xx <= legX1[k]; xx++) o.set(xx, sp.h - 1, false);
    // 伸び縮み: 胴の真ん中の行を消す / 増やす
    if (dh) {
      HxcSprite t = o; int j = 0;
      memset(o.rows, 0, sizeof o.rows);
      for (int yy = 0; yy < sp.h; yy++) {
        if (dh < 0 && yy == midRow) continue;
        if (j < 16) o.rows[j++] = t.rows[yy];
        if (dh > 0 && yy == midRow && j < 16) o.rows[j++] = t.rows[yy];
      }
      o.h = (uint8_t)j;
    }
  }
  /// 16×16 のコマ (上の行から、各行 左8点→右8点、MSB が左) に描く
  void render(uint8_t out[32]) const {
    memset(out, 0, 32);
    for (int yy = 0; yy < 16; yy++)
      for (int xx = 0; xx < 16; xx++)
        if ((terrain[yy] >> xx) & 1) dot(out, xx, yy);
    HxcSprite o; int dh, sway;
    pose(o, dh, sway);
    int bx = (int)(x >> 8), by = (int)(y >> 8), w = sp.w, h = sp.h;
    int tdx, tdy; tdir(q, tdx, tdy);
    for (int v = 0; v < o.h; v++)
      for (int u = 0; u < o.w; u++) {
        if (!o.px(u, v)) continue;
        int uu = face < 0 ? w - 1 - u : u;
        int vb = v - dh;                                // 足をそろえる (伸びたら上に、縮んだら下に寄る)
        int sx, sy;
        switch (q) {
          case 0: sx = uu; sy = vb; break;
          case 2: sx = w - 1 - uu; sy = h - 1 - vb; break;
          case 1: sx = h - 1 - vb; sy = uu; break;
          default: sx = vb; sy = w - 1 - uu; break;
        }
        dot(out, bx + sx + sway * tdx, by + sy + sway * tdy);
      }
  }
  static void dot(uint8_t* out, int px, int py) {
    if (px < 0 || py < 0 || px > 15 || py > 15) return;
    out[py * 2 + (px >> 3)] |= (uint8_t)(0x80 >> (px & 7));
  }
  bool sleeping() const { return st == HXC_SLEEP; }

  static int abs16(int v) { return v < 0 ? -v : v; }
  static int32_t abs32(int32_t v) { return v < 0 ? -v : v; }
  static int32_t clamp32(int32_t v, int32_t lo, int32_t hi) { return v < lo ? lo : v > hi ? hi : v; }
};

// ---------------------------------------------------------------- .hxc (キャラのファイル、v0.11)
//   STUDIO の「箱庭」で作って本体へ送る。リトルエンディアン、101 バイト
//     0  'HXC1'
//     4  u8 w, u8 h                 絵の幅・高さ (1〜16)
//     6  u16 rows[16]               絵 (bit x が点、x=0 が左)
//    38  i16 grav, i16 maxv, u8 bounce, u8 fric, i16 stick, i16 jump, u8 whim, u16 sleepAfter, i16 slosh   (15)
//    53  u16 terrain[16]            地形 (bit x が壁)
//    85  char name[16]              名前 (ASCII、0 埋め)
static const int HXC_FILE_SIZE = 101;
static inline uint16_t hxc_u16(const uint8_t* p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static inline void hxc_w16(uint8_t* p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
/// 読む。形が違えば false (中身は変えない)
static inline bool hxcParse(const uint8_t* b, uint32_t n, HxcSprite& sp, HxcParams& pr, uint16_t terrain[16], char name[17]) {
  if (n < (uint32_t)HXC_FILE_SIZE || b[0] != 'H' || b[1] != 'X' || b[2] != 'C' || b[3] != '1') return false;
  uint8_t w = b[4], h = b[5];
  if (w < 1 || w > 16 || h < 1 || h > 16) return false;
  HxcSprite s; s.w = w; s.h = h;
  uint16_t mask = (uint16_t)((1u << w) - 1);
  int dots = 0;
  for (int y = 0; y < 16; y++) { s.rows[y] = y < h ? (uint16_t)(hxc_u16(b + 6 + y * 2) & mask) : 0; dots += __builtin_popcount(s.rows[y]); }
  if (!dots) return false;
  const uint8_t* q = b + 38;
  HxcParams p;
  p.grav = (int16_t)hxc_u16(q); p.maxv = (int16_t)hxc_u16(q + 2); p.bounce = q[4]; p.fric = q[5];
  p.stick = (int16_t)hxc_u16(q + 6); p.jump = (int16_t)hxc_u16(q + 8); p.whim = q[10];
  p.sleepAfter = hxc_u16(q + 11); p.slosh = (int16_t)hxc_u16(q + 13);
  // 壊れた値で暴れないように丸める
  if (p.grav < 1) p.grav = 1; if (p.grav > 400) p.grav = 400;
  if (p.maxv < 16) p.maxv = 16; if (p.maxv > 255) p.maxv = 255;
  if (p.jump < 0) p.jump = 0; if (p.jump > 600) p.jump = 600;
  if (p.sleepAfter < 60) p.sleepAfter = 60;
  sp = s; pr = p;
  for (int y = 0; y < 16; y++) terrain[y] = hxc_u16(b + 53 + y * 2);
  for (int i = 0; i < 16; i++) { char c = (char)b[85 + i]; name[i] = (c >= 0x20 && c < 0x7F) ? c : 0; if (!c) break; }
  name[16] = 0;
  return true;
}
/// 書く (PC のテスト・組み込みキャラの書き出し用)
static inline void hxcBake(uint8_t* b, const HxcSprite& sp, const HxcParams& p, const uint16_t terrain[16], const char* name) {
  memset(b, 0, HXC_FILE_SIZE);
  b[0] = 'H'; b[1] = 'X'; b[2] = 'C'; b[3] = '1'; b[4] = sp.w; b[5] = sp.h;
  for (int y = 0; y < 16; y++) hxc_w16(b + 6 + y * 2, sp.rows[y]);
  uint8_t* q = b + 38;
  hxc_w16(q, (uint16_t)p.grav); hxc_w16(q + 2, (uint16_t)p.maxv); q[4] = p.bounce; q[5] = p.fric;
  hxc_w16(q + 6, (uint16_t)p.stick); hxc_w16(q + 8, (uint16_t)p.jump); q[10] = p.whim;
  hxc_w16(q + 11, p.sleepAfter); hxc_w16(q + 13, (uint16_t)p.slosh);
  for (int y = 0; y < 16; y++) hxc_w16(b + 53 + y * 2, terrain ? terrain[y] : 0);
  for (int i = 0; name && name[i] && i < 16; i++) b[85 + i] = (uint8_t)name[i];
}

// 眠る前に RTC メモリへ memcpy で丸ごと写すので、ポインタや仮想関数を持たせないこと
static_assert(std::is_trivially_copyable<HxcWorld>::value, "HxcWorld must be trivially copyable");

/// 組み込みのキャラ (動画から読み取った 14×10)
static const char* const HXC_BUILTIN[] = {
  "..##########..",
  ".############.",
  ".##.#########.",
  "##########.###",
  "##############",
  ".#############",
  ".############.",
  ".##.##..##.##.",
  ".##.##..##.##.",
  "..#.##..##.##.",
};
static const int HXC_BUILTIN_H = 10;
