// 番組ファイルの受け取りと .hxm の読み取り (Arduino に依存しない。PC でテストできる)
#pragma once
#include <stdint.h>
#include <string.h>

/// zlib / JavaScript と同じ CRC-32 (多項式 0xEDB88320)
static inline uint32_t hxm_crc32(uint32_t crc, const uint8_t* p, uint32_t n) {
  crc = ~crc;
  while (n--) {
    crc ^= *p++;
    for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
  }
  return ~crc;
}
static inline uint32_t hxm_u32(const uint8_t* p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }
static inline uint16_t hxm_u16(const uint8_t* p) { return (uint16_t)(p[0] | (p[1] << 8)); }

/// ファイル名を「英数字 _ - .」だけにし、.hxm で終わらせる (.hxc はそのまま)。使えなければ false
static inline bool hxm_safe_name(const uint8_t* src, uint8_t n, char* out, size_t cap) {
  size_t k = 0;
  for (uint8_t i = 0; i < n && k + 1 < cap; i++) {
    char c = (char)src[i];
    bool ok = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' || c == '-' || c == '.';
    if (ok) out[k++] = c;
  }
  out[k] = 0;
  while (k && out[0] == '.') { memmove(out, out + 1, k); k--; }   // 隠しファイルにしない
  if (k == 0) return false;
  if (k >= 4 && strcmp(out + k - 4, ".hxc") == 0) return true;   // 箱庭のキャラ (v0.11) はそのまま
  if (k < 4 || strcmp(out + k - 4, ".hxm") != 0) {
    if (k + 4 >= cap) return false;
    strcpy(out + k, ".hxm");
  }
  return true;
}

/// 受け取りの帳簿。書き込みそのものは呼ぶ側でやる
struct HxmUpload {
  bool active = false;
  uint32_t size = 0, got = 0, crc = 0;
  uint16_t seq = 0;
  void begin(uint32_t sz) { active = true; size = sz; got = 0; crc = 0; seq = 0; }
  // 戻り値: 0=受け取ってよい / 1=順番違い / 2=大きすぎ / 3=始まっていない
  int data(uint16_t s, const uint8_t* p, uint32_t n) {
    if (!active) return 3;
    if (s != seq) return 1;
    if (got + n > size) return 2;
    crc = hxm_crc32(crc, p, n); got += n; seq++;
    return 0;
  }
  // 戻り値: 0=OK / 1=大きさ違い / 2=CRC違い / 3=始まっていない
  int finish(uint32_t c) {
    if (!active) return 3;
    active = false;
    if (got != size) return 1;
    if (c != crc) return 2;
    return 0;
  }
};

/// .hxm の頭 8 バイトと全体の大きさから、コマ数を返す (形式が違えば -1)
///   コマ数の最上位ビットは「1回だけ流す」の印 (v0.8〜)。ここでは外して数える
static inline int32_t hxm_check_header(const uint8_t* h, uint32_t fileSize) {
  if (h[0] != 'H' || h[1] != 'X' || h[2] != 'M' || h[3] != '1') return -1;
  uint32_t n = hxm_u32(h + 4) & 0x7FFFFFFFu;
  if (n == 0 || fileSize != 8 + 35u * n) return -1;
  return (int32_t)n;
}
static inline bool hxm_is_once(const uint8_t* h) { return (h[7] & 0x80) != 0; }
