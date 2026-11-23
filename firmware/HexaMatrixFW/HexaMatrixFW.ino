// HEXA MATRIX ファーム v0.12.0 — CoreMatrix を「番組を自分で流す表示機」にする
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
//
//   v0.9.6:
//   ・自動回転 (BMI270)。C 長押し / CPZ で向きを変えると、そのときの傾きを覚える。自動回転を入れた瞬間の向きも覚える
//     (画面の回転と傾きの対応は実機ごとに決め打ちしない。隣り合う2つの向きを覚えると4つとも当たる)
//   ・振ると次の番組 (2G を超える揺れが 0.8 秒に3回)
//   ・消灯中の省電力: 何も出していない状態が 10 秒続いたら Wi-Fi の省電力を入れ、何か届いたらすぐ切る。
//     消灯中は LED ドライバへの送り直しもしない
//   ・設定パケット CONFIG (0x07) "autorot=1;shake=0;psave=1"。本体に覚える。PING に imu / cfg / 電池 (batt/lvl/chg)
//   ・2つ目の Wi-Fi (wifi.txt の ssid2= / pass2=、または USB から CONFIG "ssid2=..." "pass2=...")。
//     1つ目に 15 秒つながらなければ 2つ目へ (イベントで CPZ をアクセスポイントにする時用)
//
//   v0.10.0: 箱庭 (HEXA CUBE、18350×2 ベースのキーチェーン)
//   ・USB をつないでいない (電池) 時は「箱庭」: キャラが1体住んでいて、傾き・揺れ・ひっくり返し・叩く・振るに反応する
//     (エンジンは hxm_char.h。絵1枚から まばたき・目線・歩く脚・着地・寝る・目が回る を作る)。Wi-Fi は切る
//     USB をつなぐと今までの HEXA MATRIX に戻る。CONFIG hako=on/off/auto で固定もできる (開発用)
//   ・ボタン: A なでる / C つつく (跳ねる) / B おやすみ (すぐ眠る) / B長押し 明るさ / C長押し 向き (吊るして正立に合わせる)
//             A長押し キャラを真ん中に戻す
//   ・キャラが寝てから deep 秒 (既定 90) で本体も眠る (deep sleep)。起きるのは
//       ① ボタン ② 動かした: BMI270 の any-motion → PM1 GPIO4 → G2 (極性は imuhi で切替、実機で要確認)
//       ③ 見回り: peek 秒 (既定 3) ごとに一瞬起きて BMI270 の「動いた」印を読み、動いていなければすぐ眠り直す
//     眠る前のキャラの状態は RTC メモリに残し、起きたら続きから (起きた時はびっくりする)
//   ・CONFIG chg=650 で充電 650mA (18350×2 用。既定 180)。plog=1 で microSD の /hexa/power.csv に電池の記録
//
//   v0.10.1:
//   ・hako=on (いつも箱庭: 開発・展示用) では Wi-Fi を切らず、本体も眠らない (CPZ から Wi-Fi でつながったまま戻せる)。
//     Wi-Fi を切って眠るのは、USB なしで自動的に箱庭になった時だけ (以前は on でも Wi-Fi を切り、CPZ から戻せなくなった)
//   ・A と C を同時に長押し (1.5秒) で箱庭を抜ける。on なら auto に戻し、電池でも USB を抜き差しするまでは箱庭に入らない
//
//   v0.11.0: STUDIO の「箱庭」から キャラ (.hxc、hxm_char.h の hxcParse) を受け取る
//   ・"hako.hxc" で保存 → 箱庭のキャラになる (無ければ組み込みのキャラ)。返事 {"ok":true,"saved":"hako.hxc","char":名前}
//   ・"@char" はメモリだけ (試す): その場で「試しの箱庭」に入る (Wi-Fi・USB はつながったまま、眠らない)。
//     PLAY 0xFE / 0xFF・A+C 長押しで抜ける。試しのキャラは眠りの後に残さない。返事 {"ok":true,"char":名前,"try":true}
//
//   v0.12.0: 歩行モード (Stackchan Strider × FEETECH FS90R、hxm_walk.h)
//   ・WALK (0x08) で連続回転サーボを回して歩く。0.5 秒 (指定可) 次が来なければ止まる。本体のボタンを押しても止まる
//   ・歩いている間は顔を出す (おまかせ: 歩くとにっこり・上下に揺れる、止まって 20 秒でねむい)
//   ・CONFIG walker=1 で「歩くロボット」: 電池でも箱庭に入らず Wi-Fi を保ち、Grove の 5V (サーボの電源) を入れる
//     servo=GPIO (M5-Bus の 23 など。-1 で使わない) / strim=中立の補正µs / sinv=前後を入れ替え / wmax=速さの上限%
//   ・ジャイロで向きを数える (重力のまわりの回転なので本体をどう立てても良い)。PING の "walk":{"yaw":度,"wz":度/秒}
//     yawzero=1 で 0 に戻す。その場で回る歩かせ方を探す・角度で止めるのに使う
//
//   v0.12.1: 歩行の顔を純正スタックチャン (M5Stack-Avatar) 風に。小さな黒目 2 つと横一文字の口、
//            まばたき・息 (上下)・目線、歩いている間はにっこりして口パク
//
//   v0.13.0: 歩行中に箱庭のキャラ (HEXA CUBE と同じキャラ・同じエンジン) を出せる
//   ・顔 6 = キャラ。CONFIG wchar=1 にすると「おまかせ」もキャラになる (本体に覚える)
//   ・歩いている間はキャラもその場で脚を動かして歩く (前進は右向き、後退は左向き)
//   ・本体の傾き・揺れはそのまま効く: 段差でガタッとすると跳ねる、持ち上げて振ると目が回る、
//     その場で速く回ると目が回る、止まって静かにしていると寝る (寝息)、また歩き出すと起きてびっくり
//   v0.13.1: STUDIO で箱庭のキャラを保存し直したら、歩行中のキャラもそのキャラに替わる (以前は再起動まで前のまま)
//   v0.13.2: 緑の電源 LED (M5PM1 LED_EN) を消せる設定 pled (CONFIG pled=0)。M5Unified は起動のたびに点けるので起動後に毎回反映
//   v0.13.3: 歩行の加速・減速をゆっくりに (wacc / wdec ms)。前寄りの重心で、止まる時の慣性で前に倒れるのを防ぐ
//   v0.13.4: 刻んで歩く (won / woff ms)。続けて回すと曲がる個体で、ボタン連打と同じ「動く→休む」をくり返す
//   v0.13.5: 旋回スキャン (CONFIG tscan=<片道 ms>)。クランクを前後に往復させ、位相を 1/8 ずつ送りながら 8 回、
//            ジャイロで回った角度を測る。FS90R は位置が読めないので、その場で回れる位相があるかを実機で確かめる試験
//   v0.13.6: その場旋回 (WALK の 4 バイト目 = 1)。往復させながらジャイロで位相を探して狙った向きへ回る。
//            まっすぐ補正 (whead / wheadth): 歩いている間に向きがしきい値よりずれたら、止まって旋回で戻してから歩き続ける
//   v0.13.7: 旋回の位相の探し方を直す (実機で左回りが「探し直し」をくり返した)。当たりをつかんだら動かさず、回る量が
//            減ってきた時だけ少し直す (直す向きを覚える)。見失ったら近くを前後に探す。片道の既定を 350ms に
#include <M5Unified.h>
#include <Preferences.h>
#include <SPI.h>
#include <SD.h>
#include <LittleFS.h>
#include "hxm_proto.h"
#include "hxm_xfer.h"
#include "hxm_wifi.h"
#include "hxm_orient.h"
#include "hxm_char.h"
#include "hxm_walk.h"
#include <esp_sleep.h>
#include <esp_idf_version.h>
#include <soc/soc_caps.h>
#include <Wire.h>
#if __has_include(<driver/rtc_io.h>) && SOC_RTCIO_INPUT_OUTPUT_SUPPORTED
#include <driver/rtc_io.h>
#define HXM_HAVE_RTCIO 1
#endif
#include <WiFi.h>
#include <ESPmDNS.h>

static const char* FW_VER = "0.13.7";
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
static const uint8_t IOE_GROVE_EN = 4; // IO5  PYB_GROVE_EN   Grove の 5V (歩行モードのサーボの電源)

static HxmParser usbParser, netParser;
// v0.12 歩行
static HxmWalkCfg wcfg;
static HxmWalk    walk;
static bool       cfgWalker = false;   // 歩くロボットとして使う (箱庭に入らない・Grove 5V を入れる)
static bool       walkShow = false;    // 歩行の顔を出している
static int8_t     servoPinOn = -1;     // いまパルスを出すのにつないでいる GPIO
static uint16_t   servoUs = 0;         // いま出しているパルス (0 = 出していない)
static uint32_t   walkIdleAt = 0;      // 止まった時刻 (ねむい顔)
static float      yawDeg = 0.f, yawRate = 0.f;
// v0.13.5: 旋回スキャン (往復させて回るかを位相ごとに測る)
static const int  SCAN_N = 8, SCAN_SWINGS = 10;
static uint8_t    scanSt = 0;           // 0 なし / 1 実行中 / 2 済み / 3 中止
static uint16_t   scanHalf = 250;       // 片道 ms
static int8_t     scanTrial = 0, scanPhase = 0;   // phase: 0 落ち着く / 1 往復 / 2 測る / 3 位相送り
static int16_t    scanSwing = 0;
static uint32_t   scanAt = 0;
static float      scanYaw0 = 0.f, scanRes[SCAN_N];
// v0.13.6: その場旋回とまっすぐ補正
static HxmTurn    turn;
static bool       cfgHead = false;      // まっすぐ補正
static uint8_t    cfgHeadTh = 10;       // しきい値 (°)
static bool       headFix = false;      // いま補正の旋回中
static float      headRef = 0.f;
static bool       headRefOk = false;
static uint32_t   headMoveAt = 0, headFixAt = 0;
static bool       cfgWalkChar = false; // おまかせの顔を箱庭のキャラにする
static bool       wchOn = false;       // 歩行中にキャラを動かしている
static bool       wchReady = false;    // キャラを用意した (起動してから1回)
static int8_t     wchPace = 1;         // キャラが進む向き
static uint32_t   wchTickAt = 0, wchSpinMs = 0;
static uint32_t   yawAt = 0;
static const uint8_t SERVO_BITS = 14;
static void walkStop(bool hide);
struct HxcIn; static bool hakoInput(HxcIn& in, uint32_t now); static void hakoReset();
static HxmParser* pk = &usbParser;     // いま処理しているパケット (USB か Wi-Fi か)
static Print*     out = &Serial;       // 返事を返す先 (パケットが来た側)

// 設定 (CONFIG 0x07、本体に覚える)
static bool     cfgAutoRot = false;    // 自動回転
static bool     cfgShake = false;      // 振ると次の番組
static bool     cfgPsave = true;       // 消灯中は Wi-Fi の省電力
// 向き・振り (BMI270)
static bool     imuOk = false;
static HxmOrient orient;
static HxmShake  shaker;
static float    lgx = 0, lgy = 0, lgz = 1; static bool lgInit = false;   // ならした重力
static int      rotCand = -1; static uint32_t rotCandSince = 0;
// 箱庭 (v0.10)
enum : uint8_t { HAKO_AUTO = 0, HAKO_ON = 1, HAKO_OFF = 2 };
static uint8_t  cfgHako = HAKO_AUTO;    // 自動 (USB なし=箱庭) / いつも箱庭 / 使わない
static uint16_t cfgChg = 180;           // 充電電流 mA (180 / 650)
static bool cfgPled = true;             // v0.13.2: 緑の電源 LED (M5PM1 LED_EN)
static void applyPled() { M5.Power.M5pm1.setLedEnLevel(cfgPled); }
static int8_t   cfgHflip = 1;           // 傾きの左右 (+1/-1)。キャラが逆に転がるなら hflip=1 で入れ替え
static bool     cfgImuHigh = true;      // BMI270 INT1 の極性 (true=動いたら High)
static uint16_t cfgPeek = 3;            // 本体が眠っている間、何秒ごとに見回るか
static uint16_t cfgDeep = 90;           // キャラが寝てから、さらに何秒で本体も眠るか
static uint16_t cfgAnyMg = 60;          // 「動いた」とみなす揺れ (mg)
static bool     cfgPlog = false;        // 電池の記録 (/hexa/power.csv)
static bool     hakoOn = false;
static bool     hakoPreview = false;    // STUDIO の「実機で試す」(@char) で入った試しの箱庭
static bool     hakoTemp = false;       // いまのキャラは試し (眠りの後・次の箱庭に残さない)
static bool     upRamChar = false;      // メモリへの受け取りが @char
static HxcSprite hcSp; static HxcParams hcPr; static uint16_t hcTer[16]; static char hcName[17] = "";
static bool     hcOk = false;           // hako.hxc を読めた
static const char* HAKO_CHAR = "/hexa/hako.hxc";
static void hakoStart(bool resume); static void hakoStop(); static void hakoReset(); static void hakoLoadChar();
static bool     hakoKeepNet = false;    // 箱庭の間も Wi-Fi を保つ (hako=on の時)
static bool     hakoSuppress = false;   // A+C 長押しで抜けた: USB の抜き差しまで自動では入らない
static int8_t   lastUsb = -1;
static HxcWorld hako;
static float    hakoDown0 = 90.f;       // 覚えた向きが無い時の「下」の傾き角
static uint32_t hakoTickAt = 0, hakoSleepAt = 0, hakoLogAt = 0, hakoStartMs = 0;
static uint8_t  hakoEv = 0;             // ボタンからキャラへの知らせ
static float    hlx = 0, hly = 0, hlz = 1; static uint32_t tapCool = 0;
static uint8_t  hakoLast[32];
// deep sleep を越えて残る (LP メモリ)。合言葉が合わなければ最初から
static const uint32_t HAKO_MAGIC = 0x48584331;   // 'HXC1'
RTC_DATA_ATTR static uint32_t rtcMagic = 0;
RTC_DATA_ATTR static uint8_t  rtcWorld[sizeof(HxcWorld)];
RTC_DATA_ATTR static uint8_t  rtcSleeping = 0;
RTC_DATA_ATTR static uint32_t rtcPeeks = 0, rtcSleeps = 0;
RTC_DATA_ATTR static uint16_t rtcPeekSec = 3;          // 見回りの間隔 (M5.begin の前に使うので RTC に置く)
// 省電力
static uint32_t lastActivity = 0;      // 最後に何か届いた / ボタンが押された時刻
static bool     wSleepPref = false;    // wifi.txt の sleep=on (いつも省電力)
static bool     wSleepNow = false;
// Wi-Fi
static const uint16_t NET_PORT = 7800;
static String   wSsid[2], wPass[2];    // 1つ目 / 2つ目 (v0.9.6)
static int      wIdx = 0;              // いま使っている方
static uint32_t wTryAt = 0;            // いまの方でつなぎ始めた (またはつながっていた最後の) 時刻
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
                "\"begin\":%lu,\"data\":%lu,\"end\":%lu,\"drop\":%lu,\"up\":%d,\"got\":%lu},",
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
  // v0.9.6: 向き・設定・電池・どちらの Wi-Fi か
  int16_t bv = M5.Power.getBatteryVoltage();     // mV。0=電池なし / -1=まだ分からない
  out->printf("\"imu\":\"%s\",\"learn\":%d,\"cfg\":{\"autorot\":%d,\"shake\":%d,\"psave\":%d},"
              "\"batt\":%d,\"lvl\":%ld,\"chg\":%s,\"wnet\":%d,\"wsleep\":%d,\"ssid2\":%s,",
              imuOk ? "ok" : "none", orient.known(), cfgAutoRot ? 1 : 0, cfgShake ? 1 : 0, cfgPsave ? 1 : 0,
              (int)bv, (long)(bv > 0 ? M5.Power.getBatteryLevel() : -1), (bv > 0 && M5.Power.isCharging()) ? "true" : "false",
              (wifiOn && WiFi.status() == WL_CONNECTED) ? wIdx + 1 : 0, wSleepNow ? 1 : 0,
              wSsid[1].length() ? "true" : "false");
  // v0.10: 箱庭
  out->printf("\"mode\":\"%s\",\"vbus\":%d,\"hako\":{\"set\":\"%s\",\"st\":%d,\"q\":%d,\"chg\":%u,\"hflip\":%d,"
              "\"imuhi\":%d,\"peek\":%u,\"deep\":%u,\"anymg\":%u,\"plog\":%d,\"peeks\":%lu,\"sleeps\":%lu,"
              "\"char\":\"%s\",\"try\":%s,\"pled\":%d},",
              hakoOn ? "hako" : "home", (int)M5.Power.getVBUSVoltage(),
              cfgHako == HAKO_ON ? "on" : cfgHako == HAKO_OFF ? "off" : "auto", hakoOn ? (int)hako.st : -1, (int)hako.q,
              cfgChg, cfgHflip < 0 ? 1 : 0, cfgImuHigh ? 1 : 0, cfgPeek, cfgDeep, cfgAnyMg, cfgPlog ? 1 : 0,
              (unsigned long)rtcPeeks, (unsigned long)rtcSleeps,
              hcOk ? hcName : "", hakoPreview ? "true" : "false", cfgPled ? 1 : 0);
  // v0.12: 歩行
  out->printf("\"walk\":{\"walker\":%d,\"pin\":%d,\"trim\":%d,\"inv\":%d,\"max\":%u,\"spd\":%d,\"us\":%u,"
              "\"show\":%d,\"face\":%u,\"wchar\":%d,\"cst\":%d,\"cmds\":%lu,\"tmo\":%lu,\"yaw\":%.1f,\"wz\":%.1f,"
              "\"acc\":%u,\"dec\":%u,\"out\":%d,\"pon\":%u,\"poff\":%u,"
              "\"scan\":{\"st\":%u,\"half\":%u,\"n\":%d,\"r\":[%.0f,%.0f,%.0f,%.0f,%.0f,%.0f,%.0f,%.0f]},"
              "\"turn\":%d,\"thalf\":%u,\"head\":%d,\"hth\":%u,\"hfix\":%d,\"tsend\":%lu,\"tlock\":%d}}\n",
              cfgWalker ? 1 : 0, (int)wcfg.pin, (int)wcfg.trim, wcfg.inv ? 1 : 0, wcfg.maxPct, (int)walk.spd, servoUs,
              walkShow ? 1 : 0, walk.face, cfgWalkChar ? 1 : 0, wchOn ? (int)hako.st : -1, (unsigned long)walk.cmds, (unsigned long)walk.timeouts, yawDeg, yawRate,
              wcfg.accMs, wcfg.decMs, (int)lroundf(walk.out), wcfg.pulseOn, wcfg.pulseOff,
              scanSt, scanHalf, scanTrial, scanRes[0], scanRes[1], scanRes[2], scanRes[3], scanRes[4], scanRes[5], scanRes[6], scanRes[7],
              turn.dir, turn.half, cfgHead ? 1 : 0, cfgHeadTh, headFix ? 1 : 0, (unsigned long)turn.sends, turn.locked ? 1 : 0);
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
  walkStop(true);
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
        upRamChar = (n >= 9 && memcmp(b + 4, "@char", 5) == 0);   // v0.11: 箱庭のキャラを試す
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
        if (upRamChar) {                          // v0.11: キャラを試す (保存しない)
          upRamChar = false;
          HxcSprite sp; HxcParams pr; uint16_t ter[16]; char nm[17];
          if (!hxcParse(clipBuf, up.size, sp, pr, ter, nm)) { sendErr("bad char"); return; }
          hakoPreview = true;
          if (!hakoOn) hakoStart(false);
          else hakoKeepNet = true;
          hako.init(sp, pr, esp_random()); memcpy(hako.terrain, ter, sizeof ter); hako.fit(); hakoTemp = true;
          out->printf("{\"ok\":true,\"char\":\"%s\",\"try\":true}\n", nm);
          return;
        }
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
      if (path.endsWith(".hxc")) {                // v0.11: 箱庭のキャラ (番組の一覧には入れない)
        if (path != HAKO_CHAR) { FSYS->remove(HAKO_CHAR); FSYS->rename(path, HAKO_CHAR); }
        hakoLoadChar();
        if (!hcOk) { FSYS->remove(HAKO_CHAR); sendErr("bad char"); return; }
        rtcMagic = 0;                             // 前のキャラの続きは捨てる
        if (hakoOn) { hakoReset(); if (hakoPreview) hakoTemp = false; }
        if (!hakoOn && !paused) openProgram(cur, false);   // BEGIN で閉じた番組を開き直す
        out->printf("{\"ok\":true,\"saved\":\"hako.hxc\",\"char\":\"%s\"}\n", hcName);
        return;
      }
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
      if ((b[0] == 0xFE || b[0] == 0xFF) && hakoPreview) { hakoPreview = false; if (hakoOn) hakoStop(); }   // v0.11: 試しの箱庭をやめる
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
  String ssid2 = prefs.getString("wssid2", ""), pass2 = prefs.getString("wpass2", "");
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
      if (c.hasSsid2) {                                           // ssid2= が空なら2つ目を消す
        if (!c.ssid2[0]) { ssid2 = ""; pass2 = ""; }
        else { ssid2 = c.ssid2; if (!c.pass2Masked) pass2 = c.pass2; }
      }
      if (c.sleep >= 0) prefs.putChar("wsleep", (int8_t)c.sleep);
      if (c.tx >= 0) prefs.putChar("wtx", (int8_t)c.tx);
      prefs.putString("wssid", ssid); prefs.putString("wpass", pass); prefs.putString("wname", nm);
      prefs.putString("wkey", key);
      prefs.putString("wssid2", ssid2); prefs.putString("wpass2", pass2);
      size_t m = whole ? hxm_wifi_mask(buf, n, outb, sizeof outb) : 0;
      if (m) {
        File w = SD.open(WIFI_TXT, FILE_WRITE);
        if (w) { w.write((const uint8_t*)outb, m); w.close(); }
      }
    }
  }
  strlcpy(wName, nm.length() ? nm.c_str() : "hexamatrix", sizeof wName);
  strlcpy(wKey, key.c_str(), sizeof wKey);
  wSsid[0] = ssid; wPass[0] = pass; wSsid[1] = ssid2; wPass[1] = pass2; wIdx = 0;
  if (!ssid.length()) { if (wifiOn) { WiFi.disconnect(true); WiFi.mode(WIFI_OFF); } wifiOn = false; return; }
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(wName);
  WiFi.setAutoReconnect(true);
  // v0.9.2: 省電力は既定で切る (v0.9 で入れたが、受信が遅れたり抜けたりして転送が止まる原因だった。
  //         ちらつきの本当の原因は転送失敗で1コマずつ送りになっていたこと)。wifi.txt の sleep=on で入れられる
  //  v0.9.6: sleep=on でなければ、消灯中だけ省電力にする (loop の powerTick)
  wSleepPref = prefs.getChar("wsleep", 0) != 0;
  WiFi.setSleep(wSleepPref); wSleepNow = wSleepPref;
  WiFi.begin(ssid.c_str(), pass.c_str());
  wTryAt = millis();
  WiFi.setTxPower((wifi_power_t)(prefs.getChar("wtx", 15) * 4));   // 0.25dBm 単位
  wifiOn = true;
}
static void handlePacket();
static void feedByte(HxmParser& p, Print* src, uint8_t b) {
  int r = p.feed(b);
  if (r == 1) { pk = &p; out = src; lastActivity = millis(); handlePacket(); }
  else if (r == -1) { out = src; sendErr("crc"); }
}
static void wifiSleep(bool s) {
  if (!wifiOn || s == wSleepNow) return;
  WiFi.setSleep(s); wSleepNow = s;
}
static void netTick(uint32_t now) {
  if (!wifiOn) return;
  if (WiFi.status() != WL_CONNECTED && wSsid[1].length() && (int32_t)(now - wTryAt) > 15000) {
    // v0.9.6: 15 秒つながらなければもう片方へ (家の Wi-Fi ⇔ イベント用の CPZ)
    wIdx ^= 1; wTryAt = now; wifiShown = false;
    WiFi.disconnect(false);
    WiFi.begin(wSsid[wIdx].c_str(), wPass[wIdx].c_str());
  }
  if (WiFi.status() == WL_CONNECTED) {
    wTryAt = now;
    if (!serverUp) { server.begin(); server.setNoDelay(true); serverUp = true; }
    if (!mdnsUp && MDNS.begin(wName)) { MDNS.addService("hexamatrix", "tcp", NET_PORT); mdnsUp = true; }
    if (!wifiShown) { wifiShown = true; flashText(wIdx ? "W2" : "W", 500); if (!paused) nextAt = holdUntil; }
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
      lastActivity = millis();
      if (!wSleepPref) wifiSleep(false);            // 何か届いたら省電力をすぐ切る (続きが遅れないように)
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

// ---------------------------------------------------------------- 歩行 (v0.12)
/// サーボのパルスを出す (us=0 で止める)。GPIO が変わったらつなぎ直す
static void servoWrite(uint16_t us) {
  if (wcfg.pin < 0) us = 0;
  if (servoPinOn >= 0 && servoPinOn != wcfg.pin) { ledcDetach(servoPinOn); servoPinOn = -1; }
  if (us && servoPinOn < 0) {
    if (!ledcAttach(wcfg.pin, 50, SERVO_BITS)) { servoUs = 0; return; }
    servoPinOn = wcfg.pin;
  }
  if (servoPinOn >= 0) ledcWrite(servoPinOn, us ? hxm_walk_duty(us, SERVO_BITS) : 0);
  servoUs = us;
}
static void walkOut(uint32_t now);
static void scanStop(uint8_t st) {
  if (scanSt != 1) return;
  scanSt = st;
  if (servoUs) servoWrite(hxm_walk_us(wcfg, 0));
  walk.command(0, 5, 0xFF, millis());                 // 中立 0.3 秒 → パルスを止める (いつもと同じ)
}
/// 旋回スキャン 1 歩ぶん。全力 (wmax を無視) で前後に往復させ、終わったら位相を 1/8 周送る
static void scanTick(uint32_t now) {
  if (scanSt != 1) return;
  HxmWalkCfg full = wcfg; full.maxPct = 100;
  uint32_t el = now - scanAt;
  switch (scanPhase) {
    case 0:                                            // 落ち着く (0.4 秒中立)
      if (el >= 400) { scanYaw0 = yawDeg; scanSwing = 0; scanPhase = 1; scanAt = now; servoWrite(hxm_walk_us(full, 100)); }
      break;
    case 1:                                            // 往復: 前 half → 後 half → …
      if (el >= scanHalf) {
        scanSwing++; scanAt = now;
        if (scanSwing >= SCAN_SWINGS) { servoWrite(hxm_walk_us(full, 0)); scanPhase = 2; }
        else servoWrite(hxm_walk_us(full, (scanSwing & 1) ? -100 : 100));
      }
      break;
    case 2:                                            // 止まってから測る
      if (el >= 300) {
        scanRes[scanTrial] = yawDeg - scanYaw0;
        scanTrial++;
        if (scanTrial >= SCAN_N) { scanSt = 2; walk.command(0, 5, 0xFF, now); break; }
        scanPhase = 3; scanAt = now; servoWrite(hxm_walk_us(full, 100));
      }
      break;
    case 3:                                            // 位相送り: 片道の半分 (= 往復の幅の 1/2 ≒ 1/8 周) だけ前へ
      if (el >= (uint32_t)scanHalf / 2) { servoWrite(hxm_walk_us(full, 0)); scanPhase = 0; scanAt = now; }
      break;
  }
}
static void scanStart(uint16_t half) {
  if (!cfgWalker || wcfg.pin < 0) return;
  scanHalf = half < 100 ? 100 : half > 800 ? 800 : half;
  for (int i = 0; i < SCAN_N; i++) scanRes[i] = 0.f;
  scanTrial = 0; scanPhase = 0; scanAt = millis(); scanSt = 1;
  walk.halt(); walk.pulsing = true; walk.moving = false;
  servoWrite(hxm_walk_us(wcfg, 0));
}
/// Grove の 5V (サーボの電源)。歩くロボットの時だけ入れる
static void walkPower() {
  if (M5.getBoard() != m5::board_t::board_M5CoreMatrix) return;
  ioe1Out(IOE_GROVE_EN, cfgWalker);
}
/// 止める。hide=true なら顔も消す (番組・ライブ・消灯へ移る時)
static void walkStop(bool hide) {
  scanStop(3);
  turn.command(0, 1, millis()); headFix = false;
  if (walk.moving || walk.pulsing) {
    walk.command(0, 5, 0xFF, millis());
    walk.pulsing = false;
  }
  walk.halt();
  if (servoUs) servoWrite(0);
  if (hide) { walkShow = false; wchOn = false; }
}
/// 箱庭のキャラで出すか
static bool walkCharMode() { return walk.face == HXW_FACE_CHAR || (walk.face == HXW_FACE_AUTO && cfgWalkChar); }
/// 箱庭のキャラを 60Hz で動かして描く (箱庭と同じエンジン・同じ入力 + 歩いている間の「床に沿った傾き」)
static void walkCharTick(uint32_t now) {
  if (!wchReady) {                                     // 起動して初めて: 保存してあるキャラ (無ければ組み込み)
    hakoReset(); wchReady = true;
  }
  if (!wchOn) {                                        // 出し始め: いまの立て方を「下」として覚える (覚えた向きが無い時)
    wchOn = true; wchTickAt = now;
    float ax, ay, az, a; M5.Imu.update();
    if (imuOk && M5.Imu.getAccel(&ax, &ay, &az) && hxm_tilt(ax, ay, az, &a)) hakoDown0 = a;
  }
  int n = 0;
  while ((int32_t)(now - wchTickAt) >= 16 && n < 4) {
    wchTickAt += 16; n++;
    HxcIn in;
    if (!hakoInput(in, now)) continue;
    if (walk.moving) in.run = wchPace;                // その場で歩く (脚を動かす。前進は右向き、後退は左向き)
    if (fabsf(yawRate) > 150.f) {                     // その場で速く回った (0.5 秒続いた) → 目が回る
      if (!wchSpinMs) wchSpinMs = now;
      else if ((int32_t)(now - wchSpinMs) > 500) { in.ev |= HXC_SHAKE; wchSpinMs = now + 100000; }
    } else wchSpinMs = 0;
    hako.step(in);
  }
  if ((int32_t)(now - wchTickAt) > 100) wchTickAt = now;
  uint8_t f[32]; hako.render(f);
  int bri = hako.sleeping() ? MASTER_LV[0] / 2 : MASTER_LV[masterIdx];
  if ((memcmp(f, frame, 32) || bri != outBri) && (int32_t)(now - holdUntil) >= 0) { memcpy(frame, f, 32); setOut(bri); drawFrame(); }
}
static void walkDraw(uint32_t now) {
  if (walkCharMode()) { walkCharTick(now); return; }
  wchOn = false;
  uint8_t f = walk.face ? walk.face : hxm_walk_autoface(walk.moving, now - walkIdleAt);
  if (f >= HXW_FACE_N || f == HXW_FACE_CHAR) f = HXW_FACE_NORMAL;
  int dir = walk.moving ? (walk.spd > 0 ? 1 : -1) : 0;
  uint16_t rows[16];
  hxm_walk_face(rows, f, dir, now);
  uint8_t nf[32];
  for (int y = 0; y < 16; y++) { nf[y * 2] = rows[y] >> 8; nf[y * 2 + 1] = rows[y] & 0xFF; }
  if (memcmp(nf, frame, 32)) { memcpy(frame, nf, 32); setOut(MASTER_LV[masterIdx]); drawFrame(); }
}
/// WALK (0x08)
static void handleWalk() {
  if (pk->len != 3 && pk->len != 4) { sendErr("walk len"); return; }
  uint32_t now = millis();
  scanStop(3);                                       // v0.13.5: 歩く指令が来たらスキャンはやめる
  if (!walkShow) {                                   // 番組・ライブ・一時再生は止めて顔へ
    stopProgramForExternal();
    live = false; clipMode = false; needRestore = false; holdUntil = 0;
    walkShow = true; walkIdleAt = now;
  }
  if (pk->len == 4 && pk->buf[3] == 1) {             // v0.13.6: その場旋回 (速さの符号 = 向き。+ 左 / − 右)
    int8_t sp = (int8_t)pk->buf[0];
    if (pk->buf[2] != 0xFF) walk.face = pk->buf[2];
    walk.command(0, pk->buf[1], 0xFF, now);          // 歩くのはやめる (パルスは旋回が出す)
    headFix = false;
    turn.command(sp > 0 ? 1 : sp < 0 ? -1 : 0, pk->buf[1], now);
    if (turn.active()) { walk.pulsing = true; walk.halt(); }
    walkDraw(now);
    return;
  }
  if (turn.active() && !headFix) turn.command(0, 1, now);   // 歩く指令が来たら旋回はやめる
  bool was = walk.moving;
  int8_t prevSpd = walk.spd;
  walk.command((int8_t)pk->buf[0], pk->buf[1], pk->buf[2], now);
  if (walk.moving) wchPace = walk.spd > 0 ? 1 : -1;   // 後退はキャラも逆向き
  (void)prevSpd;
  if (was && !walk.moving) walkIdleAt = now;
  walkOut(now);                                       // v0.13.3: 速さは walkOut でゆっくり寄せる
  walkDraw(now);
}
/// v0.13.3: 出す速さを指令へゆっくり寄せてサーボへ (同じ値なら書かない)
static void walkOut(uint32_t now) {
  int o = walk.ramp(now, wcfg);
  if (!walk.pulsing) return;
  uint16_t us = hxm_walk_us(wcfg, o);
  if (us != servoUs) servoWrite(us);
}
/// 毎回: 期限切れで止める・中立の後にパルスを止める・顔・ジャイロで向きを数える
static void walkTick(uint32_t now) {
  if (walkShow && (live || clipMode || !paused)) walkStop(true);   // 番組・ライブ・一時再生が始まったら顔はやめる
  if (cfgWalker && imuOk && (int32_t)(now - yawAt) >= 10) {
    float ax, ay, az, gx, gy, gz;
    M5.Imu.update();
    if (M5.Imu.getAccel(&ax, &ay, &az) && M5.Imu.getGyro(&gx, &gy, &gz)) {
      float dt = yawAt ? (now - yawAt) / 1000.f : 0.f;
      if (dt > 0.2f) dt = 0.f;
      yawRate = hxm_yaw_rate(ax, ay, az, gx, gy, gz);
      if (fabsf(yawRate) > 0.6f) yawDeg += yawRate * dt;        // 止まっている時のゆっくりしたずれは数えない
      if (yawDeg > 100000.f || yawDeg < -100000.f) yawDeg = 0.f;
    }
    yawAt = now;
  }
  if (scanSt == 1) { scanTick(now); walk.rampAt = now; return; }   // v0.13.5: スキャン中はスキャンだけ
  if (walk.tick(now)) walkIdleAt = now;               // 期限切れ: 指令を 0 に (速さは walkOut でゆっくり落とす)
  // v0.13.6: まっすぐ補正。歩き始め (向きを変えた時) から 0.6 秒後の向きを基準に、ずれたら旋回で戻す
  if (cfgHead && walk.moving && !headFix && !(turn.active())) {
    if (walk.moveAt != headMoveAt) { headMoveAt = walk.moveAt; headRefOk = false; }
    if (!headRefOk && (int32_t)(now - walk.moveAt) > 600) { headRef = yawDeg; headRefOk = true; }
    if (headRefOk && fabsf(yawDeg - headRef) > cfgHeadTh) {
      headFix = true; headFixAt = now;
      turn.command(yawDeg > headRef ? -1 : 1, 50, now); walk.halt();
    }
  }
  if (headFix) {
    float e = yawDeg - headRef;
    bool done = fabsf(e) < 2.f || (int32_t)(now - headFixAt) > 8000 || !walk.moving || !cfgHead;
    if (done) { headFix = false; turn.command(0, 1, now); walk.halt(); walk.rampAt = now; }
    else turn.command(e > 0 ? -1 : 1, 50, now);
  }
  if (turn.active()) {                                // 旋回: 全力で往復 (wmax は無視)
    HxmWalkCfg full = wcfg; full.maxPct = 100;
    int o = turn.tick(now, yawDeg);
    uint16_t us = hxm_walk_us(full, o);
    if (us != servoUs) servoWrite(us);
    walk.pulsing = true; walk.rampAt = now;
    if (!turn.active()) walk.command(0, 5, 0xFF, now);   // 期限切れ → 中立 0.3 秒でパルスを止める
    if (walkShow && (int32_t)(now - holdUntil) >= 0) {
      static uint32_t lastFaceT = 0;
      if ((int32_t)(now - lastFaceT) >= 40) { lastFaceT = now; walkDraw(now); }
    }
    return;
  }
  if (walk.pulsing) walkOut(now); else walk.rampAt = now;
  if (!walk.moving && !walk.pulsing && servoUs) servoWrite(0);
  if (walkShow && (int32_t)(now - holdUntil) >= 0) {
    static uint32_t lastFace = 0;
    if ((int32_t)(now - lastFace) >= (walkCharMode() ? 16 : 40)) { lastFace = now; walkDraw(now); }
  }
}
static void loadWalkCfg() {
  cfgWalker  = prefs.getBool("wkr", false);
  wcfg.pin   = prefs.getChar("wpin", -1);
  wcfg.trim  = prefs.getShort("wtrm", 0);
  wcfg.inv   = prefs.getBool("winv", false);
  wcfg.maxPct = prefs.getUChar("wmax", 60);
  wcfg.accMs  = prefs.getUShort("wacc", 300);
  wcfg.decMs  = prefs.getUShort("wdec", 900);
  wcfg.pulseOn  = prefs.getUShort("won", 0);
  wcfg.pulseOff = prefs.getUShort("woff", 0);
  cfgHead   = prefs.getBool("whd", false);
  cfgHeadTh = prefs.getUChar("whth", 10);
  turn.half = prefs.getUShort("thalf", 350);
  cfgWalkChar = prefs.getBool("wch", false);
}

// ---------------------------------------------------------------- 向き・振り (v0.9.6)
static void saveOrient() {
  char k[4] = "ra0";
  for (int i = 0; i < 4; i++) { k[2] = '0' + i; prefs.putFloat(k, orient.ang[i]); }
}
static void loadOrient() {
  char k[4] = "ra0";
  for (int i = 0; i < 4; i++) { k[2] = '0' + i; orient.ang[i] = prefs.getFloat(k, NAN); }
}
/// いまの向き (rot) が正しいとして、いまの傾きを覚える。立てていなければ覚えない
static bool learnRot() {
  if (!imuOk) return false;
  float ax, ay, az, a;
  M5.Imu.update();
  if (!M5.Imu.getAccel(&ax, &ay, &az) || !hxm_tilt(ax, ay, az, &a)) return false;
  orient.learn(rot, a); saveOrient();
  lgInit = false; rotCand = -1;
  return true;
}
static void setRot(uint8_t r, bool manual) {
  rot = r & 3;
  M5.Display.setRotation(rot);
  if (manual) { prefs.putUChar("rot", rot); learnRot(); }   // 自動で回した時は保存しない (フラッシュを傷めない)
}
static void nextProgram() { live = false; clipMode = false; paused = false; openProgram(cur + 1, true); }
static void imuTick(uint32_t now) {
  static uint32_t last = 0;
  if (!imuOk || !(cfgAutoRot || cfgShake) || (int32_t)(now - last) < 40) return;
  last = now;
  float ax, ay, az;
  M5.Imu.update();
  if (!M5.Imu.getAccel(&ax, &ay, &az)) return;
  float mag = sqrtf(ax * ax + ay * ay + az * az);
  if (cfgShake && !up.active && shaker.feed(mag, now)) { lastActivity = now; nextProgram(); return; }
  if (!cfgAutoRot) return;
  if (fabsf(mag - 1.f) > 0.25f) { rotCand = -1; return; }          // 動かしている間は決めない
  if (!lgInit) { lgx = ax; lgy = ay; lgz = az; lgInit = true; }
  else { lgx += 0.3f * (ax - lgx); lgy += 0.3f * (ay - lgy); lgz += 0.3f * (az - lgz); }
  float a, d;
  if (!hxm_tilt(lgx, lgy, lgz, &a)) { rotCand = -1; return; }        // 寝かせている
  int b = orient.best(a, &d);
  if (b < 0 || d > 35.f || b == rot) { rotCand = -1; return; }       // はっきりしない / 今のまま
  if (b != rotCand) { rotCand = b; rotCandSince = now; return; }
  if ((int32_t)(now - rotCandSince) >= 500) {                         // 0.5 秒そのままなら回す
    setRot((uint8_t)b, false); rotCand = -1;
    if (!needRestore) drawFrame();
  }
}

// ---------------------------------------------------------------- 設定 (CONFIG 0x07)
static void hakoReset();
static void hakoStop();
static bool cfgFlag(const char* v) { return v[0] == '1' || (v[0] == 'o' && v[1] == 'n') || v[0] == 't'; }
/// "autorot=1;shake=0;psave=1" / "rotreset=1"。"ssid2=" "pass2=" は USB からだけ、1パケットに1つ (値に ; を含めてよい)
static void handleConfig() {
  char s[HXM_MAX_PAYLOAD + 1];
  memcpy(s, pk->buf, pk->len); s[pk->len] = 0;
  if (!strncmp(s, "ssid2=", 6) || !strncmp(s, "pass2=", 6)) {
    if (out != &Serial) { sendErr("usb only"); return; }               // Wi-Fi から Wi-Fi の設定は変えさせない
    bool isSsid = s[0] == 's';
    String v = String(s + 6);
    if (isSsid) { wSsid[1] = v; prefs.putString("wssid2", v); if (!v.length()) { wPass[1] = ""; prefs.putString("wpass2", ""); } }
    else { wPass[1] = v; prefs.putString("wpass2", v); }
    sendStatus();
    return;
  }
  bool bad = false, evOnly = false;
  for (char* p = s; p && *p;) {
    char* e = strchr(p, ';'); if (e) *e = 0;
    char* eq = strchr(p, '=');
    if (eq) {
      *eq = 0; const char* k = p; const char* v = eq + 1; bool on = cfgFlag(v);
      if (!strcmp(k, "autorot")) {
        if (on && !cfgAutoRot) learnRot();                           // 入れた瞬間の向きを正しいとして覚える
        cfgAutoRot = on; prefs.putBool("car", on); rotCand = -1; lgInit = false;
      }
      else if (!strcmp(k, "shake")) { cfgShake = on; prefs.putBool("csh", on); }
      else if (!strcmp(k, "psave")) { cfgPsave = on; prefs.putBool("cps", on); }
      else if (!strcmp(k, "rotreset")) { if (on) { orient.clear(); saveOrient(); } }
      else if (!strcmp(k, "rotlearn")) { if (on && !learnRot()) bad = true; }
      // v0.10 箱庭
      else if (!strcmp(k, "hako")) {
        cfgHako = !strcmp(v, "auto") || v[0] == 'a' ? HAKO_AUTO : on ? HAKO_ON : HAKO_OFF; prefs.putUChar("hko", cfgHako);
        hakoSuppress = false;
        if (hakoOn && (cfgHako == HAKO_ON) != hakoKeepNet) { hakoStop(); }   // Wi-Fi を保つかが変わる時は入り直す (次の1秒で)
      }
      else if (!strcmp(k, "pled")) { cfgPled = on; prefs.putBool("pld", on); applyPled(); }
      else if (!strcmp(k, "chg")) { cfgChg = atoi(v) >= 650 ? 650 : 180; prefs.putUShort("chg", cfgChg); M5.Power.setChargeCurrent(cfgChg); }
      else if (!strcmp(k, "hflip")) { cfgHflip = on ? -1 : 1; prefs.putChar("hfl", cfgHflip); }
      else if (!strcmp(k, "imuhi")) { cfgImuHigh = on; prefs.putBool("ihi", on); }
      else if (!strcmp(k, "peek")) { int n = atoi(v); cfgPeek = (uint16_t)(n < 1 ? 1 : n > 60 ? 60 : n); prefs.putUShort("pek", cfgPeek); }
      else if (!strcmp(k, "deep")) { int n = atoi(v); cfgDeep = (uint16_t)(n < 10 ? 10 : n > 3600 ? 3600 : n); prefs.putUShort("dep", cfgDeep); }
      else if (!strcmp(k, "anymg")) { int n = atoi(v); cfgAnyMg = (uint16_t)(n < 20 ? 20 : n > 500 ? 500 : n); prefs.putUShort("amg", cfgAnyMg); }
      else if (!strcmp(k, "plog")) { cfgPlog = on; prefs.putBool("plg", on); }
      // v0.12 歩行
      else if (!strcmp(k, "walker")) {
        cfgWalker = on; prefs.putBool("wkr", on); walkPower();
        if (!on) walkStop(true);
        if (on && hakoOn && !hakoPreview) hakoStop();
      }
      else if (!strcmp(k, "servo")) {
        int n = atoi(v); walkStop(false);
        wcfg.pin = (int8_t)(n < 0 || n > 30 || n == 0 || n == 1 || n == 12 || n == 13 ? -1 : n);   // I2C と USB のピンは使わせない
        if (n >= 0 && wcfg.pin < 0) bad = true;
        prefs.putChar("wpin", wcfg.pin);
      }
      else if (!strcmp(k, "strim")) { int n = atoi(v); wcfg.trim = (int16_t)(n < -150 ? -150 : n > 150 ? 150 : n); prefs.putShort("wtrm", wcfg.trim);
                                       if (servoUs && !walk.moving) servoWrite(hxm_walk_us(wcfg, 0)); }
      else if (!strcmp(k, "sinv")) { wcfg.inv = on; prefs.putBool("winv", on); }
      else if (!strcmp(k, "wmax")) { int n = atoi(v); wcfg.maxPct = (uint8_t)(n < 10 ? 10 : n > 100 ? 100 : n); prefs.putUChar("wmax", wcfg.maxPct); }
      else if (!strcmp(k, "wacc")) { int n = atoi(v); wcfg.accMs = (uint16_t)(n < 0 ? 0 : n > 3000 ? 3000 : n); prefs.putUShort("wacc", wcfg.accMs); }
      else if (!strcmp(k, "whead")) { cfgHead = on; prefs.putBool("whd", on); headFix = false; }
      else if (!strcmp(k, "wheadth")) { int n = atoi(v); cfgHeadTh = (uint8_t)(n < 3 ? 3 : n > 60 ? 60 : n); prefs.putUChar("whth", cfgHeadTh); }
      else if (!strcmp(k, "thalf")) { int n = atoi(v); turn.half = (uint16_t)(n < 100 ? 100 : n > 800 ? 800 : n); prefs.putUShort("thalf", turn.half); }
      else if (!strcmp(k, "tscan")) { int n = atoi(v); if (n > 0) scanStart((uint16_t)n); else scanStop(3); }
      else if (!strcmp(k, "won"))  { int n = atoi(v); wcfg.pulseOn  = (uint16_t)(n < 0 ? 0 : n > 3000 ? 3000 : n); prefs.putUShort("won", wcfg.pulseOn); }
      else if (!strcmp(k, "woff")) { int n = atoi(v); wcfg.pulseOff = (uint16_t)(n < 0 ? 0 : n > 3000 ? 3000 : n); prefs.putUShort("woff", wcfg.pulseOff); }
      else if (!strcmp(k, "wdec")) { int n = atoi(v); wcfg.decMs = (uint16_t)(n < 0 ? 0 : n > 3000 ? 3000 : n); prefs.putUShort("wdec", wcfg.decMs); }
      else if (!strcmp(k, "yawzero")) { if (on) yawDeg = 0.f; evOnly = true; }
      else if (!strcmp(k, "wchar")) { cfgWalkChar = on; prefs.putBool("wch", on); }
      else if (!strcmp(k, "strimtest")) {                           // 中立を確かめる: いまの strim の中立を 2 秒出す
        if (on && wcfg.pin >= 0) { walk.command(0, 20, 0xFF, millis()); walk.pulsing = true; walk.stopAt = millis() + 1700; servoWrite(hxm_walk_us(wcfg, 0)); }
      }
      else if (!strcmp(k, "hakoreset")) { if (on) { rtcMagic = 0; if (hakoOn) hakoReset(); } }
      else if (!strcmp(k, "hakoev")) {                              // v0.11.1: STUDIO の 叩く/振る/なでる/つつく (1/2/4/8)・寝かせる (16)
        int n = atoi(v);
        if (hakoOn) {
          hakoEv |= (uint8_t)(n & 15);
          if (n & 16) { hako.still = hako.pr.sleepAfter + 1; hako.enter(HXC_SLEEP); }
        }
        evOnly = true;
      }
      else bad = true;
    } else if (*p) bad = true;
    p = e ? e + 1 : nullptr;
  }
  if (bad) { sendErr("bad config"); return; }
  if (evOnly) { out->printf("{\"ok\":true,\"hakoev\":%s,\"yaw\":%.1f}\n", hakoOn ? "true" : "false", yawDeg); return; }   // 毎回の状態は返さない
  sendStatus();
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
    if (pk->type != HXM_FRAME && pk->type != HXM_BRIGHT && pk->type != HXM_FILE_DATA && pk->type != HXM_WALK) sendErr("auth");  // 連続で来る物には返さない
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
      walkStop(true);                             // v0.12: 絵が届いたら歩くのはやめる
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
      if (pk->len == 1) { setRot(pk->buf[0], true); drawFrame(); sendStatus(); }
      return;
    case HXM_CONFIG: handleConfig(); return;
    case HXM_WALK:  if (!hakoOn) handleWalk(); return;   // 連続で来るので返事はしない
    case HXM_PING:  sendStatus(); return;
    case HXM_BENCH: bench(); return;
    default:
      if (pk->type >= HXM_FILE_BEGIN && pk->type <= HXM_PLAY) { handleFile(); return; }
      sendErr("unknown type");
  }
}

// ---------------------------------------------------------------- 箱庭 (v0.10)
static bool usbPower() { int16_t v = M5.Power.getVBUSVoltage(); return v > 4000; }   // -1 (読めない) は電池扱い
/// 保存してあるキャラ (hako.hxc) を読む。無い・壊れていれば組み込みのキャラ
static void hakoLoadChar() {
  hcOk = false;
  wchReady = false;                      // v0.13.1: 歩行中のキャラも次に出す時に読み直す (STUDIO で保存し直した時)
  if (!FSYS || !FSYS->exists(HAKO_CHAR)) return;
  File f = FSYS->open(HAKO_CHAR, FILE_READ);
  uint8_t b[HXC_FILE_SIZE];
  if (f && f.read(b, sizeof b) == (int)sizeof b) hcOk = hxcParse(b, sizeof b, hcSp, hcPr, hcTer, hcName);
  if (f) f.close();
}
static void hakoReset() {
  if (hcOk) { hako.init(hcSp, hcPr, esp_random()); memcpy(hako.terrain, hcTer, sizeof hcTer); hako.fit(); }
  else { HxcSprite sp; sp.parse(HXC_BUILTIN, HXC_BUILTIN_H); HxcParams pr; hako.init(sp, pr, esp_random()); memset(hako.terrain, 0, sizeof hako.terrain); }
  hakoTemp = false;
}
// BMI270 を直接 (M5Unified に無い any-motion の設定)
static const uint8_t BMI = 0x68;
static bool    bmiW(uint8_t r, uint8_t v) { return M5.In_I2C.writeRegister8(BMI, r, v, 400000); }
static uint8_t bmiR(uint8_t r) { return M5.In_I2C.readRegister8(BMI, r, 400000); }
/// 眠る前: 「動いたら INT1 を出す (ラッチ)」にして、加速度だけ低消費で動かし続ける
static void imuArmWake() {
  if (!imuOk) return;
  bmiW(0x7C, 0x00); delayMicroseconds(600);              // PWR_CONF: 設定の間は省電力を切る
  uint16_t thr = (uint16_t)((uint32_t)cfgAnyMg * 2048 / 1000); if (thr > 0x7FF) thr = 0x7FF;
  uint8_t d[4] = { 0x05, 0xE0,                              // ANYMO_1: 5 サンプル (100ms)、xyz
                   (uint8_t)(thr & 0xFF), (uint8_t)(0x80 | (0x07 << 3) | ((thr >> 8) & 0x07)) };   // ANYMO_2: 有効、出力 bit6、しきい値
  bmiW(0x2F, 1);                                          // FEAT_PAGE 1
  M5.In_I2C.writeRegister(BMI, 0x3C, d, 4, 400000);
  bmiW(0x2F, 0);
  bmiW(0x53, (uint8_t)((1 << 3) | (cfgImuHigh ? (1 << 1) : 0)));   // INT1: 出力、プッシュプル、極性
  bmiW(0x55, 0x01);                                       // INT_LATCH: 読むまで保つ
  bmiW(0x56, (uint8_t)(bmiR(0x56) | 0x40));               // INT1_MAP_FEAT: any_motion
  bmiW(0x40, 0x17);                                       // ACC_CONF: 50Hz、平均、低消費
  bmiW(0x7D, 0x04);                                       // PWR_CTRL: 加速度だけ
  (void)bmiR(0x1C);                                       // INT_STATUS_0 を読んで空にする
  bmiW(0x7C, 0x01);                                       // PWR_CONF: 省電力
}
/// PM1: キー (GPIO0〜2) と IMU (GPIO4) の割り込みを通す (GPIO3 は IRQ 出力そのものなので止める)
static void pm1ArmWake() {
  M5.Power.M5pm1.clearIRQStatus();
  M5.Power.M5pm1.setGPIOIRQMaskBits(0x08);
}
static void hakoSave() {
  if (hakoTemp) { rtcMagic = 0; return; }                 // 試しのキャラは残さない
  memcpy(rtcWorld, &hako, sizeof hako); rtcMagic = HAKO_MAGIC;
}
static void hakoDeepSleep() {
  hakoSave(); rtcSleeping = 1; rtcSleeps++; rtcPeekSec = cfgPeek;
  memset(frame, 0, sizeof frame); drawFrame();
  imuArmWake();
  pm1ArmWake();
  if (FSYS == &SD) SD.end();
  ioe1Out(IOE_TF_EN, false);                              // microSD の電源
  Serial.flush();
  M5.Power.deepSleep((uint64_t)cfgPeek * 1000000ULL, true);   // 見回りのタイマー + G2 (PM1 の IRQ)
}
static void hakoStart(bool resume) {
  hakoOn = true;
  hakoKeepNet = (cfgHako == HAKO_ON) || hakoPreview;      // いつも箱庭 (開発・展示) と 試しの箱庭 は Wi-Fi を保つ
  if (!hakoKeepNet) {
    if (wifiOn) { if (client) client.stop(); MDNS.end(); WiFi.disconnect(true); WiFi.mode(WIFI_OFF); }
    wifiOn = serverUp = mdnsUp = wifiShown = false; wSleepNow = false;
  }
  if (pf) pf.close();
  live = false; clipMode = false; paused = true;
  if (up.active) abortUpload();
  if (resume && rtcMagic == HAKO_MAGIC) { memcpy(&hako, rtcWorld, sizeof hako); hako.enter(HXC_WAKE); hako.wakeT = 40; hako.still = 0; }
  else hakoReset();
  float d;
  if (!orient.expect(rot, &d) && !learnRot()) {           // 向きを覚えていなければ、いまの傾きを「下」とする
    float ax, ay, az, a; M5.Imu.update();
    if (M5.Imu.getAccel(&ax, &ay, &az) && hxm_tilt(ax, ay, az, &a)) hakoDown0 = a;
  }
  if (imuOk && resume && rtcSleeping) {                   // 眠る前に変えた BMI270 (低消費・ジャイロ停止・INT1) を元に戻す
    bmiW(0x56, (uint8_t)(bmiR(0x56) & ~0x40)); bmiW(0x55, 0x00); (void)bmiR(0x1C);
    M5.Imu.begin(&M5.In_I2C, M5.getBoard());
  }
  rtcSleeping = 0; hakoSleepAt = 0;
  hakoTickAt = hakoStartMs = lastActivity = millis();
  memset(hakoLast, 0xFF, sizeof hakoLast);
}
static void hakoStop() {
  hakoOn = false; hakoSave();
  memset(frame, 0, sizeof frame);
  goIdle();
  setOut(MASTER_LV[masterIdx]);
  if (!wifiOn) wifiSetup();                               // 切っていた時だけつなぎ直す
  hakoKeepNet = false;
  flashText("H", 400);
}
/// IMU → 画面の向きの加速度 (mg)。叩いた・振ったも見つける
static bool hakoInput(HxcIn& in, uint32_t now) {
  if (!imuOk) { in.gx = 0; in.gy = 1000; return true; }  // IMU が無ければ下向きの重力だけ
  float ax, ay, az, wx = 0, wy = 0, wz = 0;
  M5.Imu.update();
  if (!M5.Imu.getAccel(&ax, &ay, &az)) return false;
  M5.Imu.getGyro(&wx, &wy, &wz);
  float d0;
  if (!orient.expect(rot, &d0)) d0 = hakoDown0;
  float rel = (atan2f(ay, ax) * 57.2957795f - d0) * 0.0174532925f;
  float h = sqrtf(ax * ax + ay * ay);
  auto c16 = [](float v) -> int16_t { return (int16_t)(v > 4000 ? 4000 : v < -4000 ? -4000 : v); };
  in.gy = c16(h * cosf(rel) * 1000.f);
  in.gx = c16(cfgHflip * h * sinf(rel) * 1000.f);
  in.gz = c16(az * 1000.f);
  in.wz = c16(cfgHflip * wz);
  in.ev = hakoEv; hakoEv = 0;
  float mag = sqrtf(ax * ax + ay * ay + az * az);
  float jx = ax - hlx, jy = ay - hly, jz = az - hlz;
  hlx += 0.15f * jx; hly += 0.15f * jy; hlz += 0.15f * jz;
  if (shaker.feed(mag, now)) in.ev |= HXC_SHAKE;
  else if (sqrtf(jx * jx + jy * jy + jz * jz) > 1.1f && (int32_t)(now - tapCool) >= 0) { in.ev |= HXC_TAP; tapCool = now + 400; }
  if (in.ev || fabsf(mag - 1.f) > 0.08f) lastActivity = now;
  return true;
}
static void hakoLog(uint32_t now) {
  if (!cfgPlog || FSYS != &SD || (int32_t)(now - hakoLogAt) < 60000) return;
  hakoLogAt = now;
  File f = SD.open("/hexa/power.csv", FILE_APPEND);
  if (!f) return;
  if (f.size() == 0) f.println("sec,batt_mV,lvl,state,bright,sleeps,peeks");
  f.printf("%lu,%d,%ld,%d,%d,%lu,%lu\n", (unsigned long)((now - hakoStartMs) / 1000), (int)M5.Power.getBatteryVoltage(),
           (long)M5.Power.getBatteryLevel(), (int)hako.st, outBri, (unsigned long)rtcSleeps, (unsigned long)rtcPeeks);
  f.close();
}
static void hakoLoop(uint32_t now) {
  int n = 0;
  while ((int32_t)(now - hakoTickAt) >= 16 && n < 4) {    // 60Hz (遅れたら最大4回分だけ追いかける)
    hakoTickAt += 16; n++;
    HxcIn in;
    if (hakoInput(in, now)) hako.step(in);
  }
  if ((int32_t)(now - hakoTickAt) > 100) hakoTickAt = now;
  uint8_t f[32]; hako.render(f);
  int bri = hako.sleeping() ? MASTER_LV[0] / 2 : MASTER_LV[masterIdx];   // 寝ている時は暗く
  static uint32_t lastDraw = 0;
  if ((memcmp(f, hakoLast, 32) || bri != outBri || now - lastDraw > 200) && (int32_t)(now - holdUntil) >= 0) {
    memcpy(hakoLast, f, 32); memcpy(frame, f, 32);
    setOut(bri); drawFrame(); lastDraw = now;
  }
  // キャラが寝て deep 秒たったら本体も眠る (USB につないでいる時・いつも箱庭の時は眠らない)
  if (hako.sleeping() && !usbPower() && !hakoKeepNet) {
    if (!hakoSleepAt) hakoSleepAt = now;
    else if ((int32_t)(now - hakoSleepAt) > (int32_t)cfgDeep * 1000) hakoDeepSleep();
  } else hakoSleepAt = 0;
  hakoLog(now);
}
static void hakoButtons() {
  if (M5.BtnA.isPressed() || M5.BtnB.isPressed() || M5.BtnC.isPressed()) lastActivity = millis();
  // A と C を同時に 1.5 秒押す → 箱庭を抜ける (A/C の長押しの働きより先に見る)
  static uint32_t bothSince = 0;
  if (M5.BtnA.isPressed() && M5.BtnC.isPressed()) {
    if (!bothSince) bothSince = millis();
    else if (millis() - bothSince > 1500) {
      bothSince = 0;
      if (cfgHako == HAKO_ON) { cfgHako = HAKO_AUTO; prefs.putUChar("hko", cfgHako); }
      hakoSuppress = true; hakoPreview = false;
      hakoStop();
      return;
    }
    return;                                               // 同時押しの間は他のボタンの働きをしない
  }
  bothSince = 0;
  if (M5.BtnA.wasClicked()) hakoEv |= HXC_PET;
  if (M5.BtnC.wasClicked()) hakoEv |= HXC_POKE;
  if (M5.BtnA.wasHold()) { hakoReset(); flashText("*", 300); }
  if (M5.BtnB.wasClicked()) {                              // おやすみ
    if (usbPower() || hakoKeepNet) { hako.still = hako.pr.sleepAfter + 1; hako.enter(HXC_SLEEP); }
    else hakoDeepSleep();
  }
  if (M5.BtnB.wasHold()) {
    masterIdx = (masterIdx + 1) & 3; prefs.putUChar("mst", masterIdx);
    char b[4]; snprintf(b, sizeof b, "B%d", masterIdx + 1); flashText(b, 600);
  }
  if (M5.BtnC.wasHold()) { setRot((uint8_t)(rot + 1), true); flashText("^", 500); }   // 吊るして正立に合わせる (傾きも覚える)
}
/// 見回り起床: M5.begin の前に、BMI270 の「動いた」印だけ読んで、動いていなければすぐ眠り直す
static void hakoPeek() {
  if (esp_sleep_get_wakeup_cause() != ESP_SLEEP_WAKEUP_TIMER || !rtcSleeping || rtcMagic != HAKO_MAGIC) return;
  Wire.begin(0, 1, 400000);                                // 内部 I2C (SDA=G0, SCL=G1)
  Wire.beginTransmission(BMI); Wire.write(0x1C);
  uint8_t st = 0;
  if (Wire.endTransmission(false) == 0 && Wire.requestFrom((int)BMI, 1) == 1) st = Wire.read();
  else st = 0x40;                                          // 読めなければ起きる (安全側)
  if (st & 0x40) { Wire.end(); return; }                   // 動いた → 普通に起きる (眠り中の印は setup の最後で消す)
  rtcPeeks++;
  Wire.end();
  esp_sleep_enable_timer_wakeup((uint64_t)(rtcPeekSec ? rtcPeekSec : 3) * 1000000ULL);
#ifdef HXM_HAVE_RTCIO
#if defined(ESP_IDF_VERSION_VAL) && ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 3, 0)
  esp_sleep_enable_ext1_wakeup_io(1ULL << 2, ESP_EXT1_WAKEUP_ANY_LOW);
#else
  esp_sleep_enable_ext1_wakeup(1ULL << 2, ESP_EXT1_WAKEUP_ANY_LOW);
#endif
  rtc_gpio_pullup_en(GPIO_NUM_2); rtc_gpio_pulldown_dis(GPIO_NUM_2);
#endif
  esp_deep_sleep_start();
}

// ---------------------------------------------------------------- ボタン
static void buttons() {
  if (M5.BtnA.isPressed() || M5.BtnB.isPressed() || M5.BtnC.isPressed()) lastActivity = millis();
  if (walkShow && (M5.BtnA.wasPressed() || M5.BtnB.wasPressed() || M5.BtnC.wasPressed())) {   // v0.12: 歩いていたらまず止める
    bool was = walk.moving; walkStop(false); walkIdleAt = millis();
    if (was) { flashText("II", 400); return; }
  }
  if (walkShow && walkCharMode() && !walk.moving) {         // v0.13: 止まっている時は箱庭と同じ (A なでる / C つつく)
    if (M5.BtnA.wasClicked()) { hakoEv |= HXC_PET; return; }
    if (M5.BtnC.wasClicked()) { hakoEv |= HXC_POKE; return; }
  }
  if (M5.BtnA.wasClicked()) { live = false; clipMode = false; paused = false; openProgram(cur - 1, true); }
  if (M5.BtnC.wasClicked()) nextProgram();
  if (M5.BtnA.wasHold())    { live = false; clipMode = false; paused = false; openProgram(cur, true); }
  if (M5.BtnB.wasClicked()) {
    if (live || clipMode || !paused || walkShow) { goIdle(); flashText("II", 400); }   // 何か出ていれば止めて消灯
    else { paused = false; openProgram(cur, true); }                    // 止まっていれば番組を流す
  }
  if (M5.BtnB.wasHold()) {
    masterIdx = (masterIdx + 1) & 3; prefs.putUChar("mst", masterIdx);
    char b[4]; snprintf(b, sizeof b, "B%d", masterIdx + 1); flashText(b, 600);
    if (!paused) nextAt = holdUntil;
  }
  if (M5.BtnC.wasHold()) {
    setRot((uint8_t)(rot + 1), true);              // v0.9.6: いまの傾きも覚える (自動回転の手がかり)
    flashText("^", 500);
    if (!paused) nextAt = holdUntil;
  }
}

void setup() {
  hakoPeek();                            // v0.10: 見回りで起きただけなら、ここで眠り直す (M5.begin より前)
  auto cfg = M5.config();
  cfg.serial_baudrate = 115200;
  Serial.setRxBufferSize(USB_RX_BUF);    // v0.9.5: begin より前に (UART の Serial だと begin の後では変えられない)
  M5.begin(cfg);
  prefs.begin("hexamatrix", false);
  rot       = prefs.getUChar("rot", rot) & 3;
  masterIdx = prefs.getUChar("mst", masterIdx) & 3;
  cur       = prefs.getUChar("cur", 0);
  cfgAutoRot = prefs.getBool("car", false);
  cfgShake   = prefs.getBool("csh", false);
  cfgPsave   = prefs.getBool("cps", true);
  imuOk = M5.Imu.isEnabled();
  loadOrient();
  cfgHako    = prefs.getUChar("hko", HAKO_AUTO);
  cfgChg     = prefs.getUShort("chg", 180);
  cfgHflip   = prefs.getChar("hfl", 1) < 0 ? -1 : 1;
  cfgImuHigh = prefs.getBool("ihi", true);
  cfgPeek    = prefs.getUShort("pek", 3);
  cfgDeep    = prefs.getUShort("dep", 90);
  cfgAnyMg   = prefs.getUShort("amg", 60);
  cfgPlog    = prefs.getBool("plg", false);
  loadWalkCfg();                         // v0.12
  M5.Power.setChargeCurrent(cfgChg);
  cfgPled    = prefs.getBool("pld", true);
  applyPled();                           // v0.13.2: M5.begin() が点けた緑 LED を設定どおりに
  // 眠りから起きた / 電池で起動した → 箱庭から (Wi-Fi をつながずに)
  bool wantHako = !cfgWalker && (cfgHako == HAKO_ON || (cfgHako == HAKO_AUTO && !usbPower()));   // v0.12: 歩くロボットは箱庭に入らない
  M5.BtnA.setHoldThresh(800); M5.BtnB.setHoldThresh(800); M5.BtnC.setHoldThresh(800);
  M5.Display.setColorDepth(8);
  M5.Display.setRotation(rot);
  setOut(MASTER_LV[masterIdx]);
  detIn     = prefs.getChar("detIn", -1);
  cardDet = readCardDet();
  mountStorage();
  hakoLoadChar();                        // v0.11: 保存してある箱庭のキャラ (保存先が決まってから)
  if (sdBad && !wantHako) { flashText("SD", 1500); delay(1500); }   // カードが読めない (FAT32 にしてください)
  if (wantHako) { goIdle(); hakoStart(rtcSleeping || esp_sleep_get_wakeup_cause() != ESP_SLEEP_WAKEUP_UNDEFINED); }
  else {
    wifiSetup();
    goIdle();                            // 起動時は流さない (B で再生)
  }
  rtcSleeping = 0;
  walkPower();                           // v0.12: 歩くロボットならサーボの電源 (Grove 5V)
  sendStatus();
}

void loop() {
  M5.update();
  if (hakoOn) hakoButtons(); else buttons();

  while (Serial.available() > 0) {
    feedByte(usbParser, &Serial, (uint8_t)Serial.read());
    lastByteMs = millis();
  }
  uint32_t now = millis();
  if (!usbParser.idle() && (int32_t)(now - lastByteMs) > 300) usbParser.reset();   // 途切れたパケットは捨てる
  // v0.10: USB の有無 (1秒ごと) で 箱庭 ⇔ いつもの表示機
  static uint32_t lastMode = 0;
  if ((int32_t)(now - lastMode) > 1000) {
    lastMode = now;
    bool usb = usbPower();
    if (lastUsb >= 0 && (int8_t)usb != lastUsb) hakoSuppress = false;   // USB を抜き差ししたら A+C の「抜けた」を解除
    lastUsb = (int8_t)usb;
    bool want = hakoPreview || (!cfgWalker && (cfgHako == HAKO_ON || (cfgHako == HAKO_AUTO && !usb && !hakoSuppress)));
    if (want && !hakoOn && !up.active) { walkStop(true); hakoStart(true); }
    else if (!want && hakoOn) hakoStop();
  }
  if (hakoOn) {
    if (hakoKeepNet) netTick(now);                         // いつも箱庭の間も CPZ とつながったまま
    hakoLoop(now);
    if (needRestore && (int32_t)(now - holdUntil) >= 0) needRestore = false;
    delay(hako.sleeping() ? 6 : 1);
    return;
  }
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
      cardDet = d; mountStorage(wasSd); hakoLoadChar();
      if (sdBad) { flashText("SD", 1500); delay(1500); }
      if (!paused) openProgram(cur, true);
    }
  }
  if (clipMode) clipTick(); else playTick();
  imuTick(now);
  walkTick(now);                                           // v0.12
  // v0.9.6: 何も出していない (消灯) 状態
  const bool showing = live || clipMode || !paused || up.active || walkShow;
  // LED ドライバ (TM1680) の状態を時々送り直す。電源の揺れなどで消えても 0.2 秒で戻るように
  // (v0.9.6: 消灯中は真っ暗なので送り直さない)
  static uint32_t lastKeep = 0;
  if (showing && now - lastKeep > 200 && !needRestore && (int32_t)(now - holdUntil) >= 0) {
    lastKeep = now;
    if (outBri > 0) { M5.Display.wakeup(); M5.Display.setBrightness((uint8_t)outBri); }
    drawFrame();
  }
  // 省電力: 消灯が 10 秒続いたら Wi-Fi の省電力を入れる。何か届けば netTick ですぐ切る
  if (wSleepPref) wifiSleep(true);
  else wifiSleep(cfgPsave && !showing && (int32_t)(now - lastActivity) > 10000);
  delay(showing ? 1 : 4);
}
