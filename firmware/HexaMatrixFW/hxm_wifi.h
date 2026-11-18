// HEXA MATRIX Wi-Fi 設定ファイル (microSD の /hexa/wifi.txt) の読み書き。Arduino に依存しない
//
//   ssid=自宅のSSID
//   pass=パスワード          ← 読み込んだら本体に覚えさせ、ファイルは pass=***** に書き換える
//   name=hexamatrix          ← 省略可。CPZ からは hexamatrix.local で見つける
//
//   # で始まる行は無視。キーの前後の空白・CRLF・先頭の BOM は気にしない
//   ssid= を空にしておくと Wi-Fi を使わない (覚えた設定も消す)
//   sleep=on    Wi-Fi の省電力を入れる (既定は off。v0.9.1 までは on。入れると受信が遅れ、転送が止まることがある)
//   tx=11       送信の強さ (dBm, 2〜20)。既定は 15。下げると電流の山が小さくなる
//   key=合言葉  (v0.9.4) Wi-Fi でつないできた相手に AUTH を求める。8文字以上を推奨 (32字まで)
//               pass と同じく本体に覚えさせて ***** に書き換える。key= を空にすると合言葉なし
#pragma once
#include <stddef.h>
#include <string.h>

struct HxmWifiCfg {
  char ssid[33];
  char pass[65];
  char name[32];
  char key[33];
  bool hasSsid;       // ssid= の行がある
  bool hasPass;       // pass= の行がある
  bool passMasked;    // pass が ***** (書き換え済み)
  bool hasKey;        // key= の行がある
  bool keyMasked;     // key が ***** (書き換え済み)
  int  sleep;         // -1=書いてない / 0=off / 1=on
  int  tx;            // -1=書いてない / dBm
};

static inline bool hxm_ws(char c) { return c == ' ' || c == '\t' || c == '\r'; }
static inline bool hxm_key_is(const char* k, size_t kn, const char* want) {
  return strlen(want) == kn && strncmp(k, want, kn) == 0;
}
static inline bool hxm_all_stars(const char* v, size_t n) {
  if (n == 0) return false;
  for (size_t i = 0; i < n; i++) if (v[i] != '*') return false;
  return true;
}

/// 1行ずつ key=value を見る。cb(key, kn, val, vn, lineStart, lineEnd)
template <typename F>
static inline void hxm_wifi_lines(const char* t, size_t n, F cb) {
  size_t p = 0;
  if (n >= 3 && (unsigned char)t[0] == 0xEF && (unsigned char)t[1] == 0xBB && (unsigned char)t[2] == 0xBF) p = 3;
  while (p < n) {
    size_t ls = p, le = p;
    while (le < n && t[le] != '\n') le++;
    size_t a = ls, b = le;
    while (a < b && hxm_ws(t[a])) a++;
    while (b > a && hxm_ws(t[b - 1])) b--;
    if (a < b && t[a] != '#') {
      size_t eq = a;
      while (eq < b && t[eq] != '=') eq++;
      if (eq < b) {
        size_t ke = eq; while (ke > a && hxm_ws(t[ke - 1])) ke--;
        size_t vs = eq + 1; while (vs < b && hxm_ws(t[vs])) vs++;
        cb(t + a, ke - a, t + vs, b - vs, ls, le, vs);
      }
    }
    p = le + 1;
  }
}

static inline bool hxm_wifi_parse(const char* t, size_t n, HxmWifiCfg* c) {
  memset(c, 0, sizeof *c);
  c->sleep = -1; c->tx = -1;
  hxm_wifi_lines(t, n, [&](const char* k, size_t kn, const char* v, size_t vn, size_t, size_t, size_t) {
    if (hxm_key_is(k, kn, "ssid")) {
      c->hasSsid = true; size_t m = vn < 32 ? vn : 32; memcpy(c->ssid, v, m); c->ssid[m] = 0;
    } else if (hxm_key_is(k, kn, "pass") || hxm_key_is(k, kn, "password")) {
      c->hasPass = true; c->passMasked = hxm_all_stars(v, vn);
      size_t m = vn < 64 ? vn : 64; memcpy(c->pass, v, m); c->pass[m] = 0;
      if (c->passMasked) c->pass[0] = 0;
    } else if (hxm_key_is(k, kn, "key")) {
      c->hasKey = true; c->keyMasked = hxm_all_stars(v, vn);
      size_t m = vn < 32 ? vn : 32; memcpy(c->key, v, m); c->key[m] = 0;
      if (c->keyMasked) c->key[0] = 0;
    } else if (hxm_key_is(k, kn, "sleep")) {
      c->sleep = (vn >= 2 && (v[0] == 'o' || v[0] == 'O') && (v[1] == 'f' || v[1] == 'F')) || (vn == 1 && v[0] == '0') ? 0 : 1;
    } else if (hxm_key_is(k, kn, "tx")) {
      int x = 0; size_t i = 0;
      for (; i < vn && v[i] >= '0' && v[i] <= '9'; i++) x = x * 10 + (v[i] - '0');
      if (i > 0) c->tx = x < 2 ? 2 : x > 20 ? 20 : x;
    } else if (hxm_key_is(k, kn, "name")) {
      size_t o = 0;                                   // ホスト名に使える字だけ (英数字と -)
      for (size_t i = 0; i < vn && o < 31; i++) {
        char ch = v[i];
        if (ch >= 'A' && ch <= 'Z') ch = ch - 'A' + 'a';
        if ((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '-') c->name[o++] = ch;
      }
      c->name[o] = 0;
    }
  });
  return c->hasSsid;
}

/// pass= と key= の値を ***** にした中身を out に作る。書き換える必要が無ければ 0 を返す
///   (それぞれ最初の1行だけ。行は前から順に見るので、範囲は前から並ぶ)
static inline size_t hxm_wifi_mask(const char* t, size_t n, char* out, size_t cap) {
  size_t vs[2], ve[2]; int cnt = 0; bool gotPass = false, gotKey = false;
  hxm_wifi_lines(t, n, [&](const char* k, size_t kn, const char* v, size_t vn, size_t, size_t, size_t vstart) {
    if (vn == 0 || hxm_all_stars(v, vn)) return;
    bool isPass = hxm_key_is(k, kn, "pass") || hxm_key_is(k, kn, "password");
    bool isKey  = hxm_key_is(k, kn, "key");
    if ((isPass && !gotPass) || (isKey && !gotKey)) {
      if (isPass) gotPass = true; else gotKey = true;
      vs[cnt] = vstart; ve[cnt] = vstart + vn; cnt++;
    }
  });
  if (cnt == 0) return 0;
  size_t total = n;
  for (int i = 0; i < cnt; i++) total = total - (ve[i] - vs[i]) + 5;
  if (total > cap) return 0;
  size_t src = 0, o = 0;
  for (int i = 0; i < cnt; i++) {
    memcpy(out + o, t + src, vs[i] - src); o += vs[i] - src;
    memcpy(out + o, "*****", 5); o += 5;
    src = ve[i];
  }
  memcpy(out + o, t + src, n - src); o += n - src;
  return o;
}
