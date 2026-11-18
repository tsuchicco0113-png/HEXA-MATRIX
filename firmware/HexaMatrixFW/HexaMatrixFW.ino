// HEXA MATRIX ファーム v0.9.5 — CoreMatrix を「番組を自分で流す表示機」にする
//
//   ボード      : M5CoreMatrix (M5Stack ボードマネージャ 3.3.10-a 以上)
//   ライブラリ  : M5Unified / M5GFX
//   USB CDC On Boot : Enabled (既定)
//   Partition Scheme: No OTA (2MB APP/2MB SPIFFS)   ← v0.5 から Wi-Fi が入って 1.2MB を超えるため
//                     (切り替えると本体フラッシュに保存した番組は消える。microSD の番組はそのまま)
//
//   番組 (.hxm) を microSD の /hexa/ から読んで流す。カードが無ければ本体のフラッシュを使う。
//   電源を入れても番組は流さない (消灯で待つ)。B を押すと、最後に選んでいた番組から流す。
//   CPZ / STUDIO からコマや一時再生が届いたら、番組は止めてそちらだけを出す (混ざらないように)。
//   それが終わったら消灯に戻る (番組は自動では再開しない)。
//
//   ボタン   押す            長押し
//     A      前の番組を流す  番組の頭から
//     B      再生 / 止める   全体の明るさ (4段)
//     C      次の番組を流す  向きを90°回す
//
//   USBシリアル(115200)で hxm_proto.h のパケットを受ける。
//   コマ(FRAME)が届いている間はそちらを優先し、3秒止まると番組に戻る。
//
//   Wi-Fi (v0.5): microSD の /hexa/wifi.txt に ssid= / pass= / name= を書いておくと、起動時につなぐ。
//   パスワードは本体に覚えさせて、ファイルは pass=***** に書き換える。つながると「W」が一瞬出る。
//   TCP 7800 番で USB と同じパケットを受ける (CPZ からは <name>.local で見つける)。返事は来た側へ返す。
//
//   1回だけ (v0.8): .hxm のコマ数の最上位ビットが立っている番組は、最後まで流したら消灯して止まる。
//
//   一時再生 (v0.6): ファイル名 "@live" (くりかえし) / "@once" (1回) で送ると、保存せずにメモリに置いて
//   本体の時計で流す。Wi-Fi で1コマずつ流すと届き方がばらついてカクつくため、CPZ はこちらを使う。
//   流している間は番組を止める。PLAY 0xFE / ボタン / USB のコマ で番組に戻る。
//
//   起動時やカードを入れた時に「SD」と出たら、カードが読めていない (exFAT など)。
//   FAT32 でフォーマットし直すと使える (一度読めたカードで「入っている」状態を覚える)。
//
//   v0.9.4:
//   ・受け取りは同時に1つだけ。USB と Wi-Fi が同時に送ってきても、先に始めた方を守る ("busy")
//   ・wifi.txt の key= で合言葉。Wi-Fi の相手は AUTH (0x06) を通すまで PING 以外できない
//   ・wifi.txt が 1KB を超えても、書き戻しで後ろが消えないようにした
//   ・一時再生の受け取り失敗で、流していた番組が頭に戻っていたのを直した
//   ・同じ名前で上書きするときの空き容量の判定に、古いファイルの分を入れた
//
//   v0.9.5: まとめて送る
//   ・USB の受信バッファを 256B → 4KB に広げた。ファイル転送の DATA を返事を待たずに 16 個先まで送っても溢れない
//   ・PING の返事に "win":16 (送り側が返事を待たずに先へ送ってよい DATA の数)。ハブ / STUDIO はこれを見て窓を決める
#include <M5Unified.h>
#include <Preferences.h>
#include <SPI.h>
#include <SD.h>
#include <LittleFS.h>
#include "hxm_proto.h"
#include "hxm_xfer.h"
#include "hxm_wifi.h"
#include <WiFi.h>
#include <ESPmDNS.h>

static const char* FW_VER = "0.9.5";
static const char* DIR = "/hexa";
static const char* TMP = "/hexa/upload.tmp";
static const int   MAXF = 64;
static const uint32_t LIVE_TIMEOUT_MS = 3000;
// v0.9.5: 送り側が返事を待たずに先へ送ってよい DATA の数。DATA 1つは最大 4+202+1=207B なので
//         16 個で約 3.3KB。USB の受信バッファ (USB_RX_BUF) と Wi-Fi の TCP 窓 (約 5.7KB) の両方に収まる
static const int      XFER_WIN = 16;
static const size_t   USB_RX_BUF = 4096;
static const uint8_t  MASTER_LV[4] = {40, 100, 170, 255};

// SD (CoreMatrix の資料より)
static const int SD_SCK = 25, SD_MISO = 26, SD_MOSI = 27, SD_CS = 28;
// M5IOE1 のピン番号 (M5IOE1_Class の gpio1=0 … gpio10=9 と同じ並び)
static const uint8_t IOE_TF_EN = 0;    // IO1  PYB_TF_EN      カードの電源
static const uint8_t IOE_TF_DET = 9;   // IO10 PYB_TFCARD_DET カードの有無

static HxmParser usbParser, netParser;
static HxmParser* pk = &usbParser;     // いま処理しているパケット (USB か Wi-Fi か)
static Print*     out = &Serial;       // 返事を返す先 (パケットが来た側)

// Wi-Fi
static const uint16_t NET_PORT = 7800;
static WiFiServer server(NET_PORT);
static WiFiClient client;
static char     wName[32] = "hexamatrix";
static bool     wifiOn = false, serverUp = false, mdnsUp = false, wifiShown = false;
static uint32_t lastNetByte = 0;
static char     wKey[33] = "";          // 合言葉 (空なら不要)
static bool     netAuthed = false;      // いまの Wi-Fi の相手が合言葉を通したか
static bool     netKick = false;        // 合言葉が違った → 読み終えたら切る
// Wi-Fi の受け取りの記録 (v0.9.2: 転送がうまくいかない時の切り分け用。PING の返事の "net" に出す)
static uint32_t netBytes = 0, netConns = 0, netDrop = 0, netBegin = 0, netData = 0, netEnd = 0;
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
static bool     pfOnce = false;        // この番組は1回だけ流す (.hxm の印)
static int      cur = 0;
static bool     paused = true;         // true = 番組を流していない (起動時はこちら)
static uint32_t nextAt = 0, holdUntil = 0;
static bool     needRestore = false;
static uint8_t  masterIdx = 3;
static int      outBri = -1;

// ライブ (USBで届くコマ)
static bool     live = false;
static uint32_t lastLiveMs = 0;
static uint8_t  liveBri = 128;

// 一時再生 (メモリに置いたコマ列)
static uint8_t* clipBuf = nullptr;
static uint32_t clipCap = 0, clipCount = 0, clipIdx = 0;
static bool     clipMode = false, clipLoop = true;
static const uint32_t CLIP_MAX = 4u * 1024 * 1024;

// 受け取り
static HxmUpload up;
static bool     upRam = false;         // メモリへ受け取り中 (一時再生)
static bool     upRamLoop = true;
static bool     upFromNet = false;     // Wi-Fi から受け取り中
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
static const char* wifiState() { return !wifiOn ? "off" : WiFi.status() == WL_CONNECTED ? "ok" : "connecting"; }
static void sendStatus() {
  out->printf("{\"ok\":true,\"dev\":\"corematrix\",\"fw\":\"%s\",\"bri\":%u,\"rot\":%u,"
                "\"frames\":%lu,\"rx_ok\":%lu,\"rx_bad\":%lu,\"draw_us\":%lu,"
                "\"store\":\"%s\",\"sd\":\"%s\",\"n\":%d,\"cur\":%d,\"paused\":%s,\"live\":%s,\"master\":%u,"
                "\"wifi\":\"%s\",\"ip\":\"%s\",\"name\":\"%s\",\"clip\":%s,\"auth\":%s,\"win\":%d,"
                "\"net\":{\"rssi\":%d,\"sleep\":%d,\"conn\":%lu,\"bytes\":%lu,\"ok\":%lu,\"bad\":%lu,"
                "\"begin\":%lu,\"data\":%lu,\"end\":%lu,\"drop\":%lu,\"up\":%d,\"got\":%lu}}\n",
                FW_VER, liveBri, rot, (unsigned long)frames,
                (unsigned long)(usbParser.ok + netParser.ok), (unsigned long)(usbParser.bad + netParser.bad), (unsigned long)lastDrawUs,
                store, sdState(), nfiles, cur, paused ? "true" : "false", live ? "true" : "false", masterIdx + 1,
                wifiState(), wifiOn && WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "", wName,
                clipMode ? "true" : "false",
                (out == &client && wKey[0] && !netAuthed) ? "true" : "false", XFER_WIN,
                wifiOn && WiFi.status() == WL_CONNECTED ? (int)WiFi.RSSI() : 0, (int)WiFi.getSleep(),
                (unsigned long)netConns, (unsigned long)netBytes, (unsigned long)netParser.ok, (unsigned long)netParser.bad,
                (unsigned long)netBegin, (unsigned long)netData, (unsigned long)netEnd, (unsigned long)netDrop,
                up.active ? 1 : 0, (unsigned long)up.got);
}
static void sendErr(const char* e) { out->printf("{\"ok\":false,\"err\":\"%s\"}\n", e); }
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
  out->println(s);
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
  pfCount = n; pfOnce = hxm_is_once(h);
  if (announce) { char b[4]; snprintf(b, sizeof b, "%d", cur + 1); flashText(b, 600); }
  nextAt = millis() + (announce ? 600 : 0);
  return true;
}
static void goIdle();
static void playTick() {
  if (live || paused || !pf) return;
  uint32_t now = millis();
  if ((int32_t)(now - holdUntil) < 0 || (int32_t)(now - nextAt) < 0) return;
  if (pfIdx >= pfCount) {
    if (pfOnce) { goIdle(); return; }     // 1回だけの番組は流し終えたら消灯 (B でもう一度)
    pf.seek(8); pfIdx = 0;
  }
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
  if (!upRam && FSYS && FSYS->exists(TMP)) FSYS->remove(TMP);
  up.active = false; upRam = false;
}
static bool openProgram(int i, bool announce);
static void goIdle();
/// 受け取りをやめて、流していた番組に戻る
static void failUpload(const char* e) {
  bool ram = upRam;
  abortUpload();
  if (!ram && !paused) openProgram(cur, false);     // メモリへの受け取りなら番組はそのまま
  // メモリへの受け取りで一時再生を止めていて、ほかに何も出ていなければ、止まった絵を残さず消灯
  if (ram && paused && !live && !clipMode) goIdle();
  sendErr(e);
}
/// 何も流さない状態 (消灯) にする。番組・ライブ・一時再生をすべて止める
static void goIdle() {
  paused = true; live = false; clipMode = false;
  if (pf) pf.close();
  pfCount = pfIdx = 0;
  memset(frame, 0, sizeof frame);
  if ((int32_t)(millis() - holdUntil) >= 0) drawFrame(); else needRestore = true;   // 知らせの字が出ていれば消えてから
}
/// 外から絵が来た: 番組は止める (戻ったときに勝手に再開しない)
static void stopProgramForExternal() {
  if (!paused || pf) { paused = true; if (pf) pf.close(); pfCount = pfIdx = 0; }
}
static void clipStop() { if (clipMode) goIdle(); }
static void clipTick() {
  if (!clipMode || live) return;
  uint32_t now = millis();
  if ((int32_t)(now - holdUntil) < 0 || (int32_t)(now - nextAt) < 0) return;
  if (clipIdx >= clipCount) {
    if (!clipLoop) { clipStop(); return; }
    clipIdx = 0;
  }
  const uint8_t* r = clipBuf + 8 + clipIdx * 35;
  clipIdx++;
  memcpy(frame, r + 3, 32);
  setOut(playBri(r[2]));
  drawFrame();
  needRestore = false;
  uint16_t ms = hxm_u16(r);
  nextAt += ms;
  if ((int32_t)(now - nextAt) > 500) nextAt = now + ms;
}
static void handleFile() {
  const uint8_t* b = pk->buf; uint8_t n = pk->len;
  const bool fromNet = (out == &client);
  // v0.9.4: 受け取り中に「もう片方」から来た受け取りのパケットは受け付けない (USB と Wi-Fi の取り合い)
  const bool otherBusy = up.active && fromNet != upFromNet;
  switch (pk->type) {
    case HXM_FILE_BEGIN: {
      if (fromNet) netBegin++;
      if (otherBusy) { sendErr("busy"); return; }
      abortUpload();
      if (n >= 5 && b[4] == '@') {                // 一時再生: メモリに受け取る
        uint32_t sz = hxm_u32(b);
        if (sz < 8 || sz > CLIP_MAX) { sendErr("too big"); return; }
        if (clipCap < sz) {
          clipMode = false;
          if (clipBuf) free(clipBuf);
          clipBuf = (uint8_t*)ps_malloc(sz);
          if (!clipBuf) clipBuf = (uint8_t*)malloc(sz);
          clipCap = clipBuf ? sz : 0;
          if (!clipBuf) { sendErr("no memory"); return; }
        }
        clipMode = false;                         // 書き換えるので止める
        upRam = true; upRamLoop = !(n >= 9 && memcmp(b + 4, "@once", 5) == 0);
        up.begin(sz); upLastMs = millis(); upFromNet = (out == &client);
        out->println("{\"ok\":true,\"ack\":\"begin\"}");
        return;
      }
      if (!FSYS) { sendErr("no storage"); return; }
      if (n < 5 || !hxm_safe_name(b + 4, n - 4, upName, sizeof upName)) { sendErr("bad name"); return; }
      uint32_t sz = hxm_u32(b);
      // 同じ名前があれば、それは上書きで消えるので空きに足す (v0.9.4)
      uint64_t avail = freeBytes();
      {
        String path = String(DIR) + "/" + upName;
        if (FSYS->exists(path)) { File o = FSYS->open(path, FILE_READ); if (o) { avail += o.size(); o.close(); } }
      }
      if (sz < 8 || sz > avail) { sendErr("no space"); return; }
      if (pf) pf.close();                         // 上書きに備えて手放す
      upf = FSYS->open(TMP, FILE_WRITE);
      if (!upf) { failUpload("open failed"); return; }
      up.begin(sz); upLastMs = millis(); upFromNet = (out == &client);
      out->println("{\"ok\":true,\"ack\":\"begin\"}");
      return; }
    case HXM_FILE_DATA: {
      // 受け取りが始まっていない (前の受け取りを打ち切った後に遅れて届いた残り) は黙って捨てる。
      // ここでエラーを返すと、送り側の「次の」受け取りを失敗させてしまう (v0.9.1 で修正)
      if (fromNet) netData++;
      if (!up.active || otherBusy) { if (fromNet) netDrop++; return; }
      if (n < 2) { sendErr("bad data"); return; }
      uint16_t s = hxm_u16(b);
      uint32_t off = up.got;
      int r = up.data(s, b + 2, n - 2);
      if (r) { failUpload(r == 1 ? "seq" : r == 2 ? "too big" : "not started"); return; }
      if (upRam) memcpy(clipBuf + off, b + 2, n - 2);
      else if (upf.write(b + 2, n - 2) != (size_t)(n - 2)) { failUpload("write failed"); return; }
      upLastMs = millis();
      out->printf("{\"ok\":true,\"ack\":%u}\n", s);
      return; }
    case HXM_FILE_END: {
      if (fromNet) netEnd++;
      if (!up.active || otherBusy) { if (fromNet) netDrop++; return; }   // 同上
      if (n != 4) { sendErr("bad end"); return; }
      int r = up.finish(hxm_u32(b));
      if (upRam) {
        // v0.9.4: 失敗の時は upRam を立てたまま failUpload へ (先に下ろすと「ファイルの受け取り」と
        //         見なされ、流していた番組を頭から開き直していた)
        if (r) { failUpload(r == 1 ? "size" : r == 2 ? "crc" : "not started"); return; }
        upRam = false;
        int32_t cnt = hxm_check_header(clipBuf, up.size);
        if (cnt < 0) { if (paused && !live) goIdle(); sendErr("bad clip"); return; }
        clipCount = cnt; clipIdx = 0; clipLoop = upRamLoop;
        stopProgramForExternal();
        clipMode = true; live = false; holdUntil = 0; needRestore = false; nextAt = millis();
        out->printf("{\"ok\":true,\"clip\":%lu,\"loop\":%s}\n", (unsigned long)clipCount, clipLoop ? "true" : "false");
        return;
      }
      upf.close();
      if (r) { failUpload(r == 1 ? "size" : r == 2 ? "crc" : "not started"); return; }
      String path = String(DIR) + "/" + upName;
      if (FSYS->exists(path)) FSYS->remove(path);
      if (!FSYS->rename(TMP, path)) { failUpload("rename failed"); return; }
      scanFiles();
      int idx = 0; for (int i = 0; i < nfiles; i++) if (names[i] == upName) idx = i;
      paused = false; live = false; clipMode = false;   // 保存した番組をそのまま流す (自分で保存した時だけ)
      openProgram(idx, true);
      out->printf("{\"ok\":true,\"saved\":\"%s\",\"idx\":%d}\n", upName, idx);
      return; }
    case HXM_LIST:
      // 受け取り中はカードを付け直さない (書いている途中のファイルが壊れるので)
      if (!up.active && (readCardDet() != cardDet || !FSYS)) { bool w = (FSYS == &SD); cardDet = readCardDet(); mountStorage(w); if (!paused) openProgram(cur, false); }
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
      if (!paused) openProgram(cur, false);
      if (!ok) { sendErr("not found"); return; }
      sendList();
      return; }
    case HXM_PLAY:
      if (n != 1) { sendErr("bad play"); return; }
      if (b[0] == 0xFE) { if (clipMode || live) goIdle(); }  // 一時再生をやめて消灯へ
      else if (b[0] == 0xFF) goIdle();                      // 止める (消灯)
      else { paused = false; live = false; clipMode = false; openProgram(b[0], true); }
      sendStatus();
      return;
  }
}

// ---------------------------------------------------------------- Wi-Fi
static const char* WIFI_TXT = "/hexa/wifi.txt";
/// microSD の wifi.txt を読む → 本体に覚えさせる → pass を ***** に書き換える → つなぐ
static void wifiSetup() {
  String ssid = prefs.getString("wssid", ""), pass = prefs.getString("wpass", ""), nm = prefs.getString("wname", "hexamatrix");
  String key = prefs.getString("wkey", "");
  if (FSYS == &SD && SD.exists(WIFI_TXT)) {
    static char buf[1024], outb[1024 + 16];
    File f = SD.open(WIFI_TXT, FILE_READ);
    size_t fsz = f ? f.size() : 0;
    size_t n = f ? f.read((uint8_t*)buf, sizeof buf) : 0;
    if (f) f.close();
    // v0.9.4: 1KB に入りきらない時は、途中で切れた最後の行を読まず、ファイルにも書き戻さない
    //         (以前は読んだ 1KB だけで上書きしていて、後ろの行が消えていた)
    const bool whole = (fsz <= sizeof buf);
    if (!whole) { while (n > 0 && buf[n - 1] != '\n') n--; }
    HxmWifiCfg c;
    if (hxm_wifi_parse(buf, n, &c)) {
      if (!c.ssid[0]) { ssid = ""; pass = ""; }                    // ssid= が空 → Wi-Fi を使わない
      else {
        if (!c.passMasked) pass = c.pass;                         // ***** なら覚えているものを使う
        ssid = c.ssid;
      }
      if (c.name[0]) nm = c.name;
      if (c.hasKey && !c.keyMasked) key = c.key;                  // key= が空なら合言葉なし。***** なら覚えているもの
      if (c.sleep >= 0) prefs.putChar("wsleep", (int8_t)c.sleep);
      if (c.tx >= 0) prefs.putChar("wtx", (int8_t)c.tx);
      prefs.putString("wssid", ssid); prefs.putString("wpass", pass); prefs.putString("wname", nm);
      prefs.putString("wkey", key);
      size_t m = whole ? hxm_wifi_mask(buf, n, outb, sizeof outb) : 0;
      if (m) {
        File w = SD.open(WIFI_TXT, FILE_WRITE);
        if (w) { w.write((const uint8_t*)outb, m); w.close(); }
      }
    }
  }
  strlcpy(wName, nm.length() ? nm.c_str() : "hexamatrix", sizeof wName);
  strlcpy(wKey, key.c_str(), sizeof wKey);
  if (!ssid.length()) { if (wifiOn) { WiFi.disconnect(true); WiFi.mode(WIFI_OFF); } wifiOn = false; return; }
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(wName);
  WiFi.setAutoReconnect(true);
  // v0.9.2: 省電力は既定で切る (v0.9 で入れたが、受信が遅れたり抜けたりして転送が止まる原因だった。
  //         ちらつきの本当の原因は転送失敗で1コマずつ送りになっていたこと)。wifi.txt の sleep=on で入れられる
  WiFi.setSleep(prefs.getChar("wsleep", 0) != 0);
  WiFi.begin(ssid.c_str(), pass.c_str());
  WiFi.setTxPower((wifi_power_t)(prefs.getChar("wtx", 15) * 4));   // 0.25dBm 単位
  wifiOn = true;
}
static void handlePacket();
static void feedByte(HxmParser& p, Print* src, uint8_t b) {
  int r = p.feed(b);
  if (r == 1) { pk = &p; out = src; handlePacket(); }
  else if (r == -1) { out = src; sendErr("crc"); }
}
static void netTick(uint32_t now) {
  if (!wifiOn) return;
  if (WiFi.status() == WL_CONNECTED) {
    if (!serverUp) { server.begin(); server.setNoDelay(true); serverUp = true; }
    if (!mdnsUp && MDNS.begin(wName)) { MDNS.addService("hexamatrix", "tcp", NET_PORT); mdnsUp = true; }
    if (!wifiShown) { wifiShown = true; flashText("W", 500); if (!paused) nextAt = holdUntil; }
    WiFiClient nc = server.accept();
    if (nc) {                                        // 新しくつないできた方を使う (古い方は切る)
      if (client) client.stop();
      client = nc; client.setNoDelay(true); netParser.reset(); lastNetByte = now; netConns++;
      netAuthed = (wKey[0] == 0); netKick = false;  // 合言葉が無ければ最初から通す
      if (up.active && upFromNet) abortUpload();   // つなぎ直したら前の受け取りは無効
    }
  } else if (mdnsUp) { MDNS.end(); mdnsUp = false; }
  if (client && client.connected()) {
    uint8_t b[256]; int n;
    while ((n = client.available()) > 0) {
      int r = client.read(b, n < (int)sizeof b ? n : (int)sizeof b);
      if (r <= 0) break;
      netBytes += r;
      for (int i = 0; i < r && !netKick; i++) feedByte(netParser, &client, b[i]);
      lastNetByte = millis();
      if (netKick) break;
    }
    if (netKick) {                                   // 合言葉が違った相手は切る
      netKick = false; client.stop(); netParser.reset();   // NoDelay なので返事は送られてから閉じる
      if (up.active && upFromNet) abortUpload();
      return;
    }
    // v0.9.2: TCP は途中が抜けない (遅れて必ず届く) ので、間が空いてもパケットを捨てない。
    //         以前は 0.3 秒で捨てていて、無線の再送で遅れたパケットが丸ごと消え、転送が止まっていた
    if (!netParser.idle() && millis() - lastNetByte > 10000) netParser.reset();
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
  out->printf("{\"ok\":true,\"bench_us\":%lu,\"fps_max\":%lu}\n", (unsigned long)us, (unsigned long)(us ? 1000000UL / us : 0));
  if (pf) { pf.seek(8); pfIdx = 0; nextAt = millis(); }
}

/// 合言葉の照合 (長さが違っても最後まで比べる)
static bool keyMatch(const uint8_t* p, uint8_t n) {
  size_t kl = strlen(wKey);
  uint8_t d = (n == kl) ? 0 : 1;
  for (size_t i = 0; i < kl; i++) d |= (uint8_t)(wKey[i] ^ (i < n ? p[i] : 0));
  return d == 0;
}

static void handlePacket() {
  // v0.9.4: Wi-Fi の相手は、合言葉を通すまで PING と AUTH しか受け付けない (USB は常に通す)
  if (out == &client && !netAuthed && pk->type != HXM_PING && pk->type != HXM_AUTH) {
    if (pk->type != HXM_FRAME && pk->type != HXM_BRIGHT && pk->type != HXM_FILE_DATA) sendErr("auth");  // 連続で来る物には返さない
    return;
  }
  switch (pk->type) {
    case HXM_AUTH:
      if (out != &client || !wKey[0]) { out->println("{\"ok\":true,\"auth\":true}"); return; }   // USB / 合言葉なし
      if (keyMatch(pk->buf, pk->len)) { netAuthed = true; out->println("{\"ok\":true,\"auth\":true}"); }
      else { sendErr("auth"); netKick = true; }
      return;
    case HXM_FRAME:
      if (pk->len != 32) { sendErr("frame len"); return; }
      memcpy(frame, pk->buf, 32);
      clipMode = false;                           // 1コマずつ届いたらそちらを優先
      stopProgramForExternal();
      live = true; lastLiveMs = millis(); needRestore = false; holdUntil = 0;
      setOut(liveBri);
      drawFrame(); frames++;
      return;                                     // コマごとの返事はしない (連続で流すため)
    case HXM_BRIGHT:
      if (pk->len == 1) { liveBri = pk->buf[0]; if (live) setOut(liveBri); }
      return;                                     // 再生中に毎回返事をすると USB が混むので返さない
    case HXM_ROTATE:
      if (pk->len == 1) { rot = pk->buf[0] & 3; M5.Display.setRotation(rot); prefs.putUChar("rot", rot); drawFrame(); sendStatus(); }
      return;
    case HXM_PING:  sendStatus(); return;
    case HXM_BENCH: bench(); return;
    default:
      if (pk->type >= HXM_FILE_BEGIN && pk->type <= HXM_PLAY) { handleFile(); return; }
      sendErr("unknown type");
  }
}

// ---------------------------------------------------------------- ボタン
static void buttons() {
  if (M5.BtnA.wasClicked()) { live = false; clipMode = false; paused = false; openProgram(cur - 1, true); }
  if (M5.BtnC.wasClicked()) { live = false; clipMode = false; paused = false; openProgram(cur + 1, true); }
  if (M5.BtnA.wasHold())    { live = false; clipMode = false; paused = false; openProgram(cur, true); }
  if (M5.BtnB.wasClicked()) {
    if (live || clipMode || !paused) { goIdle(); flashText("II", 400); }   // 何か出ていれば止めて消灯
    else { paused = false; openProgram(cur, true); }                    // 止まっていれば番組を流す
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
  Serial.setRxBufferSize(USB_RX_BUF);    // v0.9.5: begin より前に (UART の Serial だと begin の後では変えられない)
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
  wifiSetup();
  goIdle();                              // 起動時は流さない (B で再生)
  sendStatus();
}

void loop() {
  M5.update();
  buttons();

  while (Serial.available() > 0) {
    feedByte(usbParser, &Serial, (uint8_t)Serial.read());
    lastByteMs = millis();
  }
  uint32_t now = millis();
  if (!usbParser.idle() && (int32_t)(now - lastByteMs) > 300) usbParser.reset();   // 途切れたパケットは捨てる
  netTick(now);
  // v0.9.3: Wi-Fi で受けた分は netTick の中で millis() を記録するので、now を取り直す。
  //   以前は古い now から引き算して負 (=符号なしで巨大) になり、Wi-Fi で受けた直後に
  //   ・転送を「時間切れ」として捨てる (→ 中身がすべて捨てられ、一時再生が送れない)
  //   ・1コマ送りを「止んだ」として消灯する (→ Wi-Fi の時だけ点滅)
  //   していた。比較も符号付きにして、同じ間違いが起きないようにする
  now = millis();
  if (up.active && (int32_t)(now - upLastMs) > 5000) {      // 途中で止まった受け取りは黙って捨てる (送り側は自分で時間切れにしている)
    bool ram = upRam; abortUpload();
    if (!ram && !paused) openProgram(cur, false);
    if (ram && paused && !live && !clipMode) goIdle();     // 止めた一時再生の絵を残さない
  }
  if (live && (int32_t)(now - lastLiveMs) > (int32_t)LIVE_TIMEOUT_MS) {                  // ライブが止んだら番組へ戻る (一時再生中ならそちらへ)
    live = false;
    if (clipMode) nextAt = now; else goIdle();                     // 番組は自動で再開しない
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
      if (!paused) openProgram(cur, true);
    }
  }
  if (clipMode) clipTick(); else playTick();
  // LED ドライバ (TM1680) の状態を時々送り直す。電源の揺れなどで消えても 0.2 秒で戻るように
  static uint32_t lastKeep = 0;
  if (now - lastKeep > 200 && !needRestore && (int32_t)(now - holdUntil) >= 0) {
    lastKeep = now;
    if (outBri > 0) { M5.Display.wakeup(); M5.Display.setBrightness((uint8_t)outBri); }
    drawFrame();
  }
  delay(1);
}
