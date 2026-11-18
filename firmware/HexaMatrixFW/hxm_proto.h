// HEXA MATRIX 受信プロトコル (Arduino に依存しない。PC でもそのままテストできる)
//
//   A5 5A <type> <len> <payload ...> <crc8>
//   crc8 は type, len, payload を通した CRC-8 (多項式 0x07, 初期値 0)
//
//   type 0x01 FRAME   len=32  1コマ。上の行から、各行は左8点→右8点、MSBが左、1=点灯
//        0x02 BRIGHT  len=1   USBで流すときの明るさ 0〜255 (16段階に丸まる。0 は消灯。保存しない)
//        0x03 PING    len=0   状態を1行のJSONで返す
//        0x04 ROTATE  len=1   向き 0〜3
//        0x05 BENCH   len=0   描画速度を測って返す
//        0x06 AUTH    len=n   合言葉 (v0.9.4)。wifi.txt に key= があると、Wi-Fi では
//                             これが通るまで PING と AUTH 以外を "auth" で断る。USB は常に不要
//                             OK → {"ok":true,"auth":true} / 違う → {"ok":false,"err":"auth"} を返して切る
//                             PING の返事の "auth" が true なら、合言葉が必要 (まだ通っていない)
//        0x07 CONFIG  len=n   設定 (v0.9.6)。"autorot=1;shake=0;psave=1" のように key=値 を ; で区切る。本体に覚える
//                             autorot 自動回転 / shake 振ると次の番組 / psave 消灯中は Wi-Fi 省電力 (既定 1)
//                             rotreset=1 覚えた向きを忘れる / rotlearn=1 いまの向きを覚え直す
//                             "ssid2=名前" "pass2=パスワード" (1パケットに1つ、USB からだけ) 2つ目の Wi-Fi
//                             返事は PING と同じ (cfg / imu / learn / batt / lvl / chg / wnet / ssid2)。だめなら "bad config"
//                             v0.10 箱庭: hako=auto/on/off  chg=180/650  hflip=0/1  imuhi=0/1  peek=秒  deep=秒
//                                         anymg=mg  plog=0/1  hakoreset=1。PING に "mode" (home/hako)・"vbus"・"hako":{…}
//   ---- 単体再生 (v0.3) ----
//        0x10 FILE_BEGIN len=4+n  u32 全体の大きさ + ファイル名 (英数字 _ - . のみ)
//        0x11 FILE_DATA  len=2+n  u16 通し番号 + 中身 (n は 200 まで)
//        0x12 FILE_END   len=4    u32 CRC-32 (zlib と同じ)
//        0x13 LIST       len=0    本体の番組一覧を返す
//        0x14 DELETE     len=n    ファイル名
//        0x15 PLAY       len=1    番組の番号 (0から)。0xFF は一時停止、0xFE は一時再生をやめて番組へ (v0.6)
//   ---- 一時再生 (v0.6) ----
//        FILE_BEGIN の名前を "@live" (くりかえし) / "@once" (1回) にすると、保存せずメモリに置いて流す
//   ---- 取り合い (v0.9.4) ----
//        受け取りは同時に1つだけ。USB と Wi-Fi の片方が受け取り中に、もう片方から FILE_BEGIN が来ると
//        {"ok":false,"err":"busy"} を返す (5秒止まった受け取りは捨てられるので、その後なら通る)。
//        もう片方からの FILE_DATA / FILE_END は黙って捨てる
//   ---- まとめて送る (v0.9.5) ----
//        PING の返事の "win" (16) 個までは、DATA の返事 (ack) を待たずに先へ送ってよい。
//        "win" が無いファームは USB=1 / Wi-Fi=8 (v0.6〜) で送る
#pragma once
#include <stdint.h>

enum : uint8_t { HXM_FRAME = 0x01, HXM_BRIGHT = 0x02, HXM_PING = 0x03, HXM_ROTATE = 0x04, HXM_BENCH = 0x05, HXM_AUTH = 0x06, HXM_CONFIG = 0x07,
                 HXM_FILE_BEGIN = 0x10, HXM_FILE_DATA = 0x11, HXM_FILE_END = 0x12,
                 HXM_LIST = 0x13, HXM_DELETE = 0x14, HXM_PLAY = 0x15 };
static const uint8_t HXM_MAX_PAYLOAD = 240;

static inline uint8_t hxm_crc8(uint8_t crc, uint8_t b) {
  crc ^= b;
  for (uint8_t i = 0; i < 8; i++) crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
  return crc;
}

struct HxmParser {
  enum : uint8_t { M0, M1, TYPE, LEN, PAY, CRC };
  uint8_t st = M0, type = 0, len = 0, pos = 0, crc = 0;
  uint8_t buf[HXM_MAX_PAYLOAD];
  uint32_t ok = 0, bad = 0;

  void reset() { st = M0; }
  bool idle() const { return st == M0; }

  // 1バイト入れる。戻り値: 1=1パケットそろった (type/len/buf を読む) / -1=壊れていた / 0=途中
  int feed(uint8_t b) {
    switch (st) {
      case M0: if (b == 0xA5) st = M1; return 0;
      case M1: st = (b == 0x5A) ? TYPE : (b == 0xA5 ? M1 : M0); return 0;
      case TYPE: type = b; crc = hxm_crc8(0, b); st = LEN; return 0;
      case LEN:
        if (b > HXM_MAX_PAYLOAD) { st = M0; bad++; return -1; }
        len = b; pos = 0; crc = hxm_crc8(crc, b); st = len ? PAY : CRC; return 0;
      case PAY:
        buf[pos++] = b; crc = hxm_crc8(crc, b);
        if (pos >= len) st = CRC;
        return 0;
      default:
        st = M0;
        if (b == crc) { ok++; return 1; }
        bad++; return -1;
    }
  }
};
