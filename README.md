# HEXA MATRIX (v0.4)

CoreMatrix (16×16 白色LED) に絵を出すための一式です。

| ファイル | 役割 |
|---|---|
| `hexa-matrix-studio.html` | STUDIO。「マークを作る」と「番組を作る」の2画面。USBで実機に映す |
| `firmware/HexaMatrixFW/` | CoreMatrix 用ファーム v0.4。microSD の番組を自分で流す。USBで届いたコマも表示する |
| `cpz/` | CardputerZero 用。常駐ハブ (`hmatrixd.py`)、本体アプリ (`hmatrix_app.py`)、描画エンジンの Python 版 (`hxengine.py`) |
| `src/` `build.py` | STUDIO の元ファイル。`python3 build.py` で1枚のHTMLに組み立てる |
| `tools/mkfont.py` | ドットフォント (BDF) をSTUDIO用の表に変換する |

## はじめる

1. Arduino IDE でボード **M5CoreMatrix** を選び、`firmware/HexaMatrixFW/HexaMatrixFW.ino` を開いて書き込む
   - M5Stack ボードマネージャ 3.3.10-a 以上、ライブラリ M5Unified / M5GFX
   - ツール → USB CDC On Boot は Enabled (既定)
   - 書き込めないときは電源ボタン長押しでダウンロードモード
2. 書き込めるとハートが出る。シリアルモニタは閉じる
3. パソコンの Chrome / Edge で `hexa-matrix-studio.html` を開き、「接続」で CoreMatrix を選ぶ

## 本体だけで流す (v0.3)

番組 (.hxm) を microSD の `hexa` フォルダから読んで流します。電源を入れると、最後に流していた番組から始まります。
カードが入っていないときは本体のフラッシュに保存します。

| ボタン | 押す | 長押し (0.8秒) |
|---|---|---|
| A | 前の番組 | 番組の頭から |
| B | 一時停止 / 再生 | 全体の明るさ (4段、B1〜B4 と表示) |
| C | 次の番組 | 向きを90°回す |

- 番組を切り替えると番号が一瞬出ます。読めない番組は「E」が出ます
- 番組の入れ方は2通り
  1. STUDIO の「本体の番組」→「この番組を本体に保存」(USB)
  2. 「コマ列を書き出す」で作った .hxm を、PCで microSD の `hexa` フォルダへコピー
- 番組は名前の順に並びます。`01_`、`02_` のように番号を付けると順番を決められます。名前は英数字と `_` `-` だけにしてください
- USBでコマが届いている間 (STUDIO のプレビュー) はそちらを優先し、届かなくなって3秒で番組に戻ります
- microSD は FAT32 でフォーマットしたものを使ってください。64GB 以上のカードは出荷時 exFAT なので、そのままでは読めません
  (Mac: ディスクユーティリティで「MS-DOS (FAT)」+「マスター・ブート・レコード」、Windows: guiformat や Rufus で FAT32)
- v0.4 から、カードが読めないときは起動時やカードを入れた時に「SD」と出ます。STUDIO の「本体の番組」にも案内が出ます
  (一度 FAT32 のカードが読めると「カードが入っている」状態を覚えるので、それ以降に読めないカードを入れると知らせます)

## CardputerZero で使う (v0.4)

CPZ に CoreMatrix をUSBでつなぐと、CPZ が「頭脳」になります。

```
CoreMatrix ──USB── CardputerZero ──Wi-Fi── スマホ / PC のブラウザ (STUDIO)
                    └ 本体アプリ「HEXA MATRIX」(キーボードで操作)
```

1. CPZ で `git clone https://github.com/tsuchicco0113-png/HEXA-MATRIX ~/hexa-matrix && cd ~/hexa-matrix && sh cpz/install.sh`
2. 案内どおり `sudo reboot`
3. CPZ 左の USB-SW を **Host 側 (右/下)** にして、CoreMatrix を USB-A か USB-C1 につなぐ
4. スマホ/PCのブラウザで `http://<CPZのIP>:8090/` を開く → STUDIO が開き、自動で CPZ 経由に接続します
   (WebSerial が要らないので、スマホや Safari でも送れます)

- 常駐ハブ `hexa-matrix.service` (ポート 8090) が USB を一手に持ちます。STUDIO も本体アプリもここを通ります
- STUDIO の「保存と書き出し」に **CPZに置く** が出ます。番組を CPZ のライブラリ (`~/.local/share/hexa-matrix/library/`) に置き、
  CPZ が同じエンジン (Python版) でコマ列を作ります (STUDIO と1バイト違わないことを確認済み)
- ホーム画面の「HEXA MATRIX」アプリ (方向は F/X/Z/C、ことば画面では fn+F/X/Z/C)

| 画面 | できること |
|---|---|
| 1 ことば | 打った文字をその場で流す。動き・入り方・はやさ・明るさ・字 (16/8ドット、太字)・長さ (ずっと/1回だけ/10秒〜10分) を選べる (英数字と記号) |
| 2 ライブラリ | CPZに置いた番組を CPZ から流す (くりかえし / 1回)、本体(SD)へ送る、消す |
| 3 本体 | CoreMatrix の中の番組を選んで流す、止める、消す |
| 4 設定 | CoreMatrix の明るさ、向き、スマホから開くQR |

- ブラウザから送り始めると、CPZ からの再生は止まります (後から操作した方が優先)
- 困ったとき: `journalctl -u hexa-matrix -n 30` / アプリのログ `~/.local/share/hexa-matrix/app.log`

### ハブの API (localhost からも LAN からも)

| | |
|---|---|
| `GET /` | STUDIO |
| `GET /ws` | WebSocket。バイナリで送ったパケットをそのまま USB へ、本体の返事 (1行JSON) をテキストで返す |
| `GET /api/status` | つながり、本体の状態、CPZの再生、いま出している絵 |
| `GET/POST /api/library` | 一覧 / 置く (`{"name","program"}` か `?name=` + .hxm の中身) |
| `GET/DELETE /api/library/<名前>` | .hxm を取り出す / 消す |
| `POST /api/play` `{"name","loop"}` ・ `POST /api/stop` | CPZ から流す / 止める |
| `POST /api/say` `{"text","show","eff","speed","bri","size","bold","loop","dur"}` | ことばを流す (`dur` 秒で止める。0=ずっと) |
| `POST /api/push` `{"name","as"}` | ライブラリの番組を本体へ保存 |
| `GET /api/device/list` ・ `POST /api/device/play` `{"idx"}`/`{"pause":true}` ・ `POST /api/device/delete` `{"name"}` | 本体の番組 |
| `POST /api/device/bright` `{"value"}` ・ `POST /api/device/rotate` | 明るさ (ライブ) / 向き |

認証はありません。家のLANの中で使ってください。

## 通信の形

`A5 5A <type> <len> <payload> <crc8>` (crc8 は type, len, payload の CRC-8 / 多項式 0x07)

| type | len | 内容 |
|---|---|---|
| 0x01 FRAME | 32 | 1コマ。上の行から、各行は左8点→右8点、MSBが左、1=点灯 |
| 0x02 BRIGHT | 1 | USBで流すときの明るさ 0〜255 (16段階に丸める) |
| 0x03 PING | 0 | 状態を1行のJSONで返す |
| 0x04 ROTATE | 1 | 向き 0〜3 |
| 0x05 BENCH | 0 | 描画速度を測って返す |
| 0x10 FILE_BEGIN | 4+n | u32 大きさ + ファイル名 |
| 0x11 FILE_DATA | 2+n | u16 通し番号 + 中身 (200バイトまで)。1つごとに `{"ok":true,"ack":番号}` |
| 0x12 FILE_END | 4 | u32 CRC-32。合えば `{"ok":true,"saved":名前,"idx":番号}` |
| 0x13 LIST | 0 | 番組一覧 `{"ok":true,"list":true,"store","sd","free"(KB),"cur","paused","files":[{"n","s"}]}` |
| 0x14 DELETE | n | ファイル名 |
| 0x15 PLAY | 1 | 番組の番号 (0から)。0xFF で一時停止 |

本体からの返事は1行ずつのJSONです。v0.4 から PING と LIST の返事に `"sd"` (`ok` / `unreadable` = カードが読めない / `none`) が入ります。

## 番組を作る

シーンを上から順に流します。シーンは「素材 × 入り方 × 見せ方 × 出方」の組み合わせです。

| 項目 | 選べるもの |
|---|---|
| 素材 | 文字 (16ドット1行 / 8ドット2行まで、太字可) / マーク / コマアニメ |
| 入り方・出方 | なし、← → ↑ ↓ に流れる、ワイプ、1字ずつ、粒で、落ちて、フェード、ズーム |
| 見せ方 (文字・マーク) | 止める (長い文はページ送り)、← → 横流し、↑ 縦送り、波打ち、往復、点滅、反転点滅、ゆっくり明暗 |
| 見せ方 (コマアニメ) | くりかえし、行って戻る |

- 横流し・縦送り・波打ちは、端から入って端へ抜けるので入り方・出方は使いません
- 明るさはシーンごと。フェードとゆっくり明暗は本体の明るさ (16段階) で作ります
- 番組はブラウザに自動保存。「番組を書き出す」で JSON、「コマ列を書き出す」で本体単体再生用の `.hxm`

### ヘッダーとフッター

番組一覧のいちばん上と下にある枠です。毎周の頭と終わりに挟みます。

- 左のチェックで使う・使わないを切り替え、右で出す間隔 (毎回 / 2・3・5・10周に1回) を選びます
- 中身はふつうのシーンと同じで、文字・マーク・コマアニメのどれでも作れます
- 間隔がちがうときは、そろうまで周を重ねた形で再生・保存します (例: 2周に1回と3周に1回なら6周ぶん)。本体に保存してもこの順番どおりに流れます

### フォント

- 16ドット: 東雲フォント (Public Domain)
- 8ドット: 美咲ゴシック (商用含め自由に利用・再配布可)
- JIS第1・第2水準の漢字、ひらがな、カタカナ、半角カナ、英数記号。無い字は「?」になります

### コマ列 (.hxm)

`'HXM1'` / u32 コマ数 / コマごとに u16 表示時間ms・u8 明るさ(0〜255)・32バイトの絵 (すべてリトルエンディアン)
