// HEXA MATRIX ファーム v0.4.0 — CoreMatrix を「番組を自分で流す表示機」にする
//
//   ボード      : M5CoreMatrix (M5Stack ボードマネージャ 3.3.10-a 以上)
//   ライブラリ  : M5Unified / M5GFX
//   USB CDC On Boot : Enabled (既定)
//
//   番組 (.hxm) を microSD の /hexa/ から読んで流す。カードが無ければ本体のフラッシュを使う。
//   電源を入れると、最後に流していた番組から始める。
//
//   ボタン   押す            長押し
//     A      前の番組        番組の頭から
//     B      一時停止/再生   全体の明るさ (4段)
//     C      次の番組        向きを90°回す
//
//   USBシリアル(115200)で hxm_proto.h のパケットを受ける。
//   コマ(FRAME)が届いている間はそちらを優先し、3秒止まると番組に戻る。
//
//   起動時やカードを入れた時に「SD」と出たら、カードが読めていない (exFAT など)。
//   FAT32 でフォーマットし直すと使える (一度読めたカードで「入っている」状態を覚える)。
#include <M5Unified.h>
#include <Preferences.h>
#include <SPI.h>
#include <SD.h>
#include <LittleFS.h>
#include "hxm_proto.h"
#include "hxm_xfer.h"

static const char* FW_VER = "0.4.0";
static const char* DIR = "/hexa";
static const char* TMP = "/hexa/upload.tmp";
static const int   MAXF = 64;
static const uint32_t LIVE_TIMEOUT_MS = 3000;
static const uint8_t  MASTER_LV[4] = {40, 100, 170, 255};

// SD (CoreMatrix の資料より)
static const int SD_SCK = 25, SD_MISO = 26, SD_MOSI = 27, SD_CS = 28;
// M5IOE1 のピン番号 (M5IOE1_Class の gpio1=0 … gpio10=9 と同じ並び)
static const uint8_t IOE_TF_EN = 0;    // IO1  PYB_TF_EN      カードの電源
static const uint8_t IOE_TF_DET = 9;   // IO10 PYB_TFCARD_DET カードの有無

static HxmParser parser;
static Preferences prefs;
static uint8_t  frame[32];
static uint8_t  rot = 1;
static uint32_t lastByteMs = 0, lastDrawUs = 0, frames = 0;

// 保存先
static fs::FS*  FSYS = nullptr;
static const char* store = "none";
static String   names[MAXF];
static uint32_t sizes[MAXF];
static int      nfiles = 0;
static int      cardDet = -1;
static bool     sdBad = false;        // カードは入っているのに読めない (exFAT など)
static int      detIn = -1;           // SD が読めた時の検出ピンの値 (覚えておいて「入っている」の判定に使う)

// 再生
static File     pf;
static int32_t  pfCount = 0, pfIdx = 0;
static int      cur = 0;
static bool     paused = false;
static uint32_t nextAt = 0, holdUntil = 0;
static bool     needRestore = false;
static uint8_t  masterIdx = 3;
static int      outBri = -1;

// ライブ (USBで届くコマ)
static bool     live = false;
static uint32_t lastLiveMs = 0;
static uint8_t  liveBri = 128;

// 受け取り
static HxmUpload up;
static File     upf;
static char     upName[48];
static uint32_t upLastMs = 0;

static const uint16_t HEART[16] = {
  0x0000, 0x1E78, 0x3FFC, 0x7FFE, 0x7FFE, 0x7FFE, 0x7FFE, 0x3FFC,
  0x1FF8, 0x0FF0, 0x0FF0, 0x07E0, 0x03C0, 0x0180, 0x0000, 0x0000 };

// ---------------------------------------------------------------- 表示
static void setOut(int b) {
  if (b == outBri) return;
  outBri = b;
  M5.Display.setBrightness((uint8_t)b);
}
static void drawFrame() {
  uint32_t t0 = micros();
  M5.Display.startWrite();
  M5.Display.fillScreen(TFT_BLACK);
  for (int y = 0; y < 16; y++) {
    uint16_t w = ((uint16_t)frame[y * 2] << 8) | frame[y * 2 + 1];
    for (int x = 0; x < 16; x++)
      if (w & (0x8000 >> x)) M5.Display.drawPixel(x, y, TFT_WHITE);
  }
  M5.Display.endWrite();
  M5.Display.display();
  lastDrawUs = micros() - t0;
}
static void rowsToFrame(const uint16_t* rows) {
  for (int y = 0; y < 16; y++) { frame[y * 2] = rows[y] >> 8; frame[y * 2 + 1] = rows[y] & 0xFF; }
}
/// 小さい字で一瞬だけ知らせる (番組の番号など)。時間が来たら元の絵に戻す
static void flashText(const char* s, uint32_t ms) {
  M5.Display.startWrite();
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setFont(&fonts::Font0);
  M5.Display.setTextColor(TFT_WHITE);
  M5.Display.setTextDatum(middle_center);
  M5.Display.drawString(s, 8, 8);
  M5.Display.endWrite();
  M5.Display.display();
  setOut(MASTER_LV[masterIdx]);
  holdUntil = millis() + ms;
  needRestore = true;
}
static uint8_t playBri(uint8_t b) { return (uint8_t)((uint16_t)b * MASTER_LV[masterIdx] / 255); }

// ---------------------------------------------------------------- 返事
static const char* sdState() { return FSYS == &SD ? "ok" : sdBad ? "unreadable" : "none"; }
static void sendStatus() {
  Serial.printf("{\"ok\":true,\"dev\":\"corematrix\",\"fw\":\"%s\",\"bri\":%u,\"rot\":%u,"
                "\"frames\":%lu,\"rx_ok\":%lu,\"rx_bad\":%lu,\"draw_us\":%lu,"
                "\"store\":\"%s\",\"sd\":\"%s\",\"n\":%d,\"cur\":%d,\"paused\":%s,\"live\":%s,\"master\":%u}\n",
                FW_VER, liveBri, rot, (unsigned long)frames,
                (unsigned long)parser.ok, (unsigned long)parser.bad, (unsigned long)lastDrawUs,
                store, sdState(), nfiles, cur, paused ? "true" : "false", live ? "true" : "false", masterIdx + 1);
}
static void sendErr(const char* e) { Serial.printf("{\"ok\":false,\"err\":\"%s\"}\n", e); }
static uint64_t freeBytes() {
  if (FSYS == &SD) return SD.totalBytes() - SD.usedBytes();
  if (FSYS == &LittleFS) return LittleFS.totalBytes() - LittleFS.usedBytes();
  return 0;
}
static void sendList() {
  String s = "{\"ok\":true,\"list\":true,\"store\":\"";
  s += store; s += "\",\"sd\":\""; s += sdState(); s += "\",\"free\":"; s += String((unsigned long)(freeBytes() / 1024));
  s += ",\"cur\":"; s += cur; s += ",\"paused\":"; s += paused ? "true" : "false";
  s += ",\"files\":[";
  for (int i = 0; i < nfiles; i++) {
    if (i) s += ",";
    s += "{\"n\":\""; s += names[i]; s += "\",\"s\":"; s += sizes[i]; s += "}";
  }
  s += "]}";
  Serial.println(s);
}

// ---------------------------------------------------------------- 保存先
static void ioe1Out(uint8_t pin, bool v) {
  auto& io = M5.getIOExpander(0);
  io.setHighImpedance(pin, false);
  io.setDirection(pin, true);
  io.digitalWrite(pin, v);
}
static int readCardDet() {
  if (M5.getBoard() != m5::board_t::board_M5CoreMatrix) return -1;
  auto& io = M5.getIOExpander(0);
  io.setDirection(IOE_TF_DET, false);
  return io.digitalRead(IOE_TF_DET) ? 1 : 0;
}
static void scanFiles() {
  nfiles = 0;
  if (!FSYS) return;
  File d = FSYS->open(DIR);
  if (!d || !d.isDirectory()) return;
  for (File f = d.openNextFile(); f && nfiles < MAXF; f = d.openNextFile()) {
    String n = f.name();
    int sl = n.lastIndexOf('/'); if (sl >= 0) n = n.substring(sl + 1);
    if (!f.isDirectory() && n.endsWith(".hxm") && !n.startsWith(".")) { names[nfiles] = n; sizes[nfiles] = f.size(); nfiles++; }
    f.close();
  }
  d.close();
  // 名前順 (先頭に 01_ などを付ければ並びを決められる)
  for (int i = 1; i < nfiles; i++)
    for (int j = i; j > 0 && names[j] < names[j - 1]; j--) {
      String t = names[j]; names[j] = names[j - 1]; names[j - 1] = t;
      uint32_t z = sizes[j]; sizes[j] = sizes[j - 1]; sizes[j - 1] = z;
    }
}
/// wasSd: 直前まで SD を使っていたか (抜いた時に「読めない」と言わないため)
static void mountStorage(bool wasSd = false) {
  if (pf) pf.close();
  FSYS = nullptr; store = "none"; sdBad = false;
  if (M5.getBoard() == m5::board_t::board_M5CoreMatrix) {
    ioe1Out(IOE_TF_EN, true);          // PYB_TF_EN: カードの電源
    delay(30);
  }
  SD.end();
  SPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
  if (SD.begin(SD_CS, SPI, 20000000)) {
    FSYS = &SD; store = "sd";
    if (cardDet >= 0 && cardDet != detIn) { detIn = cardDet; prefs.putChar("detIn", (int8_t)detIn); }
  } else {
    // 検出ピンが「入っている」側なのに読めない → FAT32 ではないカードの可能性
    sdBad = !wasSd && detIn >= 0 && cardDet == detIn;
    if (LittleFS.begin(true)) { FSYS = &LittleFS; store = "flash"; }
  }
  if (FSYS && !FSYS->exists(DIR)) FSYS->mkdir(DIR);
  scanFiles();
}

// ---------------------------------------------------------------- 再生
static bool openProgram(int i, bool announce) {
  if (pf) pf.close();
  pfCount = pfIdx = 0;
  if (!FSYS || nfiles == 0) { rowsToFrame(HEART); drawFrame(); setOut(MASTER_LV[masterIdx]); return false; }
  cur = ((i % nfiles) + nfiles) % nfiles;
  prefs.putUChar("cur", (uint8_t)cur);
  pf = FSYS->open(String(DIR) + "/" + names[cur], FILE_READ);
  uint8_t h[8];
  int32_t n = (pf && pf.read(h, 8) == 8) ? hxm_check_header(h, pf.size()) : -1;
  if (n < 0) { if (pf) pf.close(); flashText("E", 800); return false; }
  pfCount = n;
  if (announce) { char b[4]; snprintf(b, sizeof b, "%d", cur + 1); flashText(b, 600); }
  nextAt = millis() + (announce ? 600 : 0);
  return true;
}
static void playTick() {
  if (live || paused || !pf) return;
  uint32_t now = millis();
  if ((int32_t)(now - holdUntil) < 0 || (int32_t)(now - nextAt) < 0) return;
  if (pfIdx >= pfCount) { pf.seek(8); pfIdx = 0; }
  uint8_t r[35];
  if (pf.read(r, 35) != 35) { pf.seek(8); pfIdx = 0; return; }
  pfIdx++;
  memcpy(frame, r + 3, 32);
  setOut(playBri(r[2]));
  drawFrame();
  needRestore = false;
  uint16_t ms = hxm_u16(r);
  nextAt += ms;
  if ((int32_t)(now - nextAt) > 500) nextAt = now + ms;   // 大きく遅れたら追いつこうとしない
}

// ---------------------------------------------------------------- 受け取り
static void abortUpload() {
  if (upf) upf.close();
  if (FSYS && FSYS->exists(TMP)) FSYS->remove(TMP);
  up.active = false;
}
static bool openProgram(int i, bool announce);
/// 受け取りをやめて、流していた番組に戻る
static void failUpload(const char* e) { abortUpload(); openProgram(cur, false); sendErr(e); }
static void handleFile() {
  const uint8_t* b = parser.buf; uint8_t n = parser.len;
  switch (parser.type) {
    case HXM_FILE_BEGIN: {
      abortUpload();
      if (!FSYS) { sendErr("no storage"); return; }
      if (n < 5 || !hxm_safe_name(b + 4, n - 4, upName, sizeof upName)) { sendErr("bad name"); return; }
      uint32_t sz = hxm_u32(b);
      if (sz < 8 || sz > freeBytes()) { sendErr("no space"); return; }
      if (pf) pf.close();                         // 上書きに備えて手放す
      upf = FSYS->open(TMP, FILE_WRITE);
      if (!upf) { failUpload("open failed"); return; }
      up.begin(sz); upLastMs = millis();
      Serial.println("{\"ok\":true,\"ack\":\"begin\"}");
      return; }
    case HXM_FILE_DATA: {
      if (n < 2) { sendErr("bad data"); return; }
      uint16_t s = hxm_u16(b);
      int r = up.data(s, b + 2, n - 2);
      if (r) { failUpload(r == 1 ? "seq" : r == 2 ? "too big" : "not started"); return; }
      if (upf.write(b + 2, n - 2) != (size_t)(n - 2)) { failUpload("write failed"); return; }
      upLastMs = millis();
      Serial.printf("{\"ok\":true,\"ack\":%u}\n", s);
      return; }
    case HXM_FILE_END: {
      if (n != 4) { sendErr("bad end"); return; }
      int r = up.finish(hxm_u32(b));
      upf.close();
      if (r) { failUpload(r == 1 ? "size" : r == 2 ? "crc" : "not started"); return; }
      String path = String(DIR) + "/" + upName;
      if (FSYS->exists(path)) FSYS->remove(path);
      if (!FSYS->rename(TMP, path)) { failUpload("rename failed"); return; }
      scanFiles();
      int idx = 0; for (int i = 0; i < nfiles; i++) if (names[i] == upName) idx = i;
      paused = false; live = false;
      openProgram(idx, true);
      Serial.printf("{\"ok\":true,\"saved\":\"%s\",\"idx\":%d}\n", upName, idx);
      return; }
    case HXM_LIST:
      if (readCardDet() != cardDet || !FSYS) { bool w = (FSYS == &SD); cardDet = readCardDet(); mountStorage(w); openProgram(cur, false); }
      sendList();
      return;
    case HXM_DELETE: {
      char nm[48];
      if (!FSYS || !hxm_safe_name(b, n, nm, sizeof nm)) { sendErr("bad name"); return; }
      if (pf) pf.close();
      String path = String(DIR) + "/" + nm;
      bool ok = FSYS->exists(path) && FSYS->remove(path);
      scanFiles();
      if (cur >= nfiles) cur = nfiles ? nfiles - 1 : 0;
      openProgram(cur, false);
      if (!ok) { sendErr("not found"); return; }
      sendList();
      return; }
    case HXM_PLAY:
      if (n != 1) { sendErr("bad play"); return; }
      if (b[0] == 0xFF) paused = true;
      else { paused = false; live = false; openProgram(b[0], true); }
      sendStatus();
      return;
  }
}

// ---------------------------------------------------------------- 速度計測
static void bench() {
  uint32_t t0 = micros();
  const int n = 120;
  for (int i = 0; i < n; i++) {
    for (int y = 0; y < 16; y++) { uint16_t w = 0x8000 >> (i & 15); frame[y * 2] = w >> 8; frame[y * 2 + 1] = w & 0xFF; }
    drawFrame();
  }
  uint32_t us = (micros() - t0) / n;
  Serial.printf("{\"ok\":true,\"bench_us\":%lu,\"fps_max\":%lu}\n", (unsigned long)us, (unsigned long)(us ? 1000000UL / us : 0));
  if (pf) { pf.seek(8); pfIdx = 0; nextAt = millis(); }
}

static void handlePacket() {
  switch (parser.type) {
    case HXM_FRAME:
      if (parser.len != 32) { sendErr("frame len"); return; }
      memcpy(frame, parser.buf, 32);
      live = true; lastLiveMs = millis(); needRestore = false; holdUntil = 0;
      setOut(liveBri);
      drawFrame(); frames++;
      return;                                     // コマごとの返事はしない (連続で流すため)
    case HXM_BRIGHT:
      if (parser.len == 1) { liveBri = parser.buf[0]; if (live) setOut(liveBri); }
      return;                                     // 再生中に毎回返事をすると USB が混むので返さない
    case HXM_ROTATE:
      if (parser.len == 1) { rot = parser.buf[0] & 3; M5.Display.setRotation(rot); prefs.putUChar("rot", rot); drawFrame(); sendStatus(); }
      return;
    case HXM_PING:  sendStatus(); return;
    case HXM_BENCH: bench(); return;
    default:
      if (parser.type >= HXM_FILE_BEGIN && parser.type <= HXM_PLAY) { handleFile(); return; }
      sendErr("unknown type");
  }
}

// ---------------------------------------------------------------- ボタン
static void buttons() {
  if (M5.BtnA.wasClicked()) { paused = false; live = false; openProgram(cur - 1, true); }
  if (M5.BtnC.wasClicked()) { paused = false; live = false; openProgram(cur + 1, true); }
  if (M5.BtnA.wasHold())    { paused = false; live = false; openProgram(cur, true); }
  if (M5.BtnB.wasClicked()) {
    if (live) { live = false; openProgram(cur, true); paused = false; }
    else { paused = !paused; flashText(paused ? "II" : ">", 400); if (!paused) nextAt = holdUntil; }
  }
  if (M5.BtnB.wasHold()) {
    masterIdx = (masterIdx + 1) & 3; prefs.putUChar("mst", masterIdx);
    char b[4]; snprintf(b, sizeof b, "B%d", masterIdx + 1); flashText(b, 600);
    if (!paused) nextAt = holdUntil;
  }
  if (M5.BtnC.wasHold()) {
    rot = (rot + 1) & 3; prefs.putUChar("rot", rot);
    M5.Display.setRotation(rot); flashText("^", 500);
    if (!paused) nextAt = holdUntil;
  }
}

void setup() {
  auto cfg = M5.config();
  cfg.serial_baudrate = 115200;
  M5.begin(cfg);
  prefs.begin("hexamatrix", false);
  rot       = prefs.getUChar("rot", rot) & 3;
  masterIdx = prefs.getUChar("mst", masterIdx) & 3;
  cur       = prefs.getUChar("cur", 0);
  M5.BtnA.setHoldThresh(800); M5.BtnB.setHoldThresh(800); M5.BtnC.setHoldThresh(800);
  M5.Display.setColorDepth(8);
  M5.Display.setRotation(rot);
  setOut(MASTER_LV[masterIdx]);
  detIn     = prefs.getChar("detIn", -1);
  cardDet = readCardDet();
  mountStorage();
  if (sdBad) { flashText("SD", 1500); delay(1500); }   // カードが読めない (FAT32 にしてください)
  openProgram(cur, true);
  sendStatus();
}

void loop() {
  M5.update();
  buttons();

  while (Serial.available() > 0) {
    int r = parser.feed((uint8_t)Serial.read());
    lastByteMs = millis();
    if (r == 1) handlePacket();
    else if (r == -1) sendErr("crc");
  }
  uint32_t now = millis();
  if (!parser.idle() && now - lastByteMs > 300) parser.reset();     // 途切れたパケットは捨てる
  if (up.active && now - upLastMs > 5000) failUpload("upload timeout");
  if (live && now - lastLiveMs > LIVE_TIMEOUT_MS) {                  // ライブが止んだら番組へ戻る
    live = false;
    if (pf) nextAt = now; else openProgram(cur, false);
  }
  if (needRestore && (int32_t)(now - holdUntil) >= 0 && (paused || !pf)) {   // 知らせの字を消して元の絵へ
    needRestore = false; drawFrame();
  }
  // カードの抜き差し (1秒ごとに見る)
  static uint32_t lastDet = 0;
  if (!up.active && now - lastDet > 1000) {
    lastDet = now;
    int d = readCardDet();
    if (d >= 0 && d != cardDet) {
      bool wasSd = (FSYS == &SD);
      cardDet = d; mountStorage(wasSd);
      if (sdBad) { flashText("SD", 1500); delay(1500); }
      openProgram(cur, true);
    }
  }
  playTick();
  delay(1);
}
