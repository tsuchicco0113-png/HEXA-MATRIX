"""CardputerZero の画面・キーボードまわり (HEXA CLIP の ocr_cam.py から持ってきた部品)

  Keys        : キーボード (tca8418) を横取りして ('CHAR','a') / ('ACT','LEFT') に変換
  FrameBuffer : /dev/fb0 (320x170) に PIL の絵を出す
  find_font   : 日本語が□にならないフォントを探す
  hexpts / honeycomb_bg / glow_hex : HEXA STAGE 風の部品
  launcher_pids / signal_launcher  : ランチャー(APPLaunch)の一時停止
"""
import fcntl
import glob
import math
import os
import select
import struct
import time

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

LCD_W, LCD_H = 320, 170
BG, FG, SUB = (14, 16, 22), (235, 238, 245), (150, 158, 175)

# ---------------------------------------------------------------- keys (Linux input codes)
EVIOCGRAB = 0x40044590
EV_FMT = "llHHi"
EV_SIZE = struct.calcsize(EV_FMT)

K_ESC, K_BS, K_TAB, K_ENTER = 1, 14, 15, 28
K_LSHIFT, K_RSHIFT, K_CAPS = 42, 54, 58
K_UP, K_LEFT, K_RIGHT, K_DOWN = 103, 105, 106, 108
K_HOME, K_END, K_DEL = 102, 107, 111

CHARS = {
    2: "1!", 3: "2@", 4: "3#", 5: "4$", 6: "5%", 7: "6^", 8: "7&", 9: "8*", 10: "9(", 11: "0)",
    12: "-_", 13: "=+", 16: "qQ", 17: "wW", 18: "eE", 19: "rR", 20: "tT", 21: "yY", 22: "uU",
    23: "iI", 24: "oO", 25: "pP", 26: "[{", 27: "]}", 30: "aA", 31: "sS", 32: "dD", 33: "fF",
    34: "gG", 35: "hH", 36: "jJ", 37: "kK", 38: "lL", 39: ";:", 40: "'\"", 41: "`~", 43: "\\|",
    44: "zZ", 45: "xX", 46: "cC", 47: "vV", 48: "bB", 49: "nN", 50: "mM", 51: ",<", 52: ".>",
    53: "/?", 57: "  ",
}
ACTIONS = {K_UP: "UP", K_DOWN: "DOWN", K_LEFT: "LEFT", K_RIGHT: "RIGHT", K_HOME: "HOME",
           K_END: "END", K_DEL: "DEL", K_BS: "BS", K_TAB: "TAB", K_ENTER: "ENTER", K_ESC: "ESC"}
KNOWN = set(CHARS) | set(ACTIONS) | {K_LSHIFT, K_RSHIFT, K_CAPS}
FN_ARROWS = {33: "UP", 45: "DOWN", 44: "LEFT", 46: "RIGHT"}     # fn + F / X / Z / C
LETTER_NAV = {"f": "UP", "x": "DOWN", "z": "LEFT", "c": "RIGHT"}


def nav(events):
    """文字入力のない画面用: F/X/Z/C 単独を方向キーとして扱う"""
    out = []
    for kind, val in events:
        if kind == "CHAR" and val.lower() in LETTER_NAV:
            out.append(("ACT", LETTER_NAV[val.lower()]))
        else:
            out.append((kind, val))
    return out


class Keys:
    """キーボードを横取りして、押下を ('CHAR', 'a') / ('ACT', 'LEFT') に変換"""

    def __init__(self, dev, debug=False, cfg=None):
        self.fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self.fd, EVIOCGRAB, 1)
        except OSError as e:
            os.close(self.fd)
            if e.errno == 16:               # EBUSY: 別のプログラムがキーボードを独占中
                raise SystemExit(
                    "すでに別のアプリがキーボードを使っています (キーボードが使用中)。\n"
                    "本体の画面で ESC を押して終了するか、次を実行してください:\n"
                    "  pkill -f hmatrix_app.py; sleep 1; sudo pkill -CONT -f APPLaunch")
            raise
        self.debug = debug
        self.held = set()
        self.ev_codes = []
        self.shift_once = False
        self.caps = False
        cfg = cfg or {}
        self.fn_codes = set(cfg.get("fn", []))
        self.fn_map = {int(k): v for k, v in cfg.get("fn_map", {}).items()}

    def _raw(self, timeout):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return []
        try:
            data = os.read(self.fd, EV_SIZE * 64)
        except BlockingIOError:
            return []
        out = []
        for i in range(0, len(data) - EV_SIZE + 1, EV_SIZE):
            _, _, etype, code, value = struct.unpack(EV_FMT, data[i:i + EV_SIZE])
            if etype == 1:
                out.append((code, value))
        return out

    def poll(self, timeout=0.0):
        events = []
        self.ev_codes = []                   # events と同じ並びで、それを出したキーのコード (押しっぱなしの判定用)
        for code, value in self._raw(timeout):
            if self.debug and value == 1:
                print("key", code, flush=True)
            if value == 0:
                self.held.discard(code)
                continue
            if value == 1:
                self.held.add(code)
            if code in (K_LSHIFT, K_RSHIFT):
                if value == 1:
                    self.shift_once = True       # 押して離すと次の1文字だけ大文字
                continue
            if code == K_CAPS:
                if value == 1:
                    self.caps = not self.caps
                continue
            if code in self.fn_codes or code not in KNOWN:
                continue                         # fn / sym など(修飾キーとして held に残す)
            # fn = 設定で指定したキー、または「知らないキー」が押されている状態
            fn = any(c in self.fn_codes or c not in KNOWN for c in self.held if c != code)
            if fn and code in self.fn_map:
                events.append(("ACT", self.fn_map[code])); self.ev_codes.append(code)
                continue
            if fn and code in FN_ARROWS:
                events.append(("ACT", FN_ARROWS[code])); self.ev_codes.append(code)
                continue
            if code in ACTIONS:
                events.append(("ACT", ACTIONS[code])); self.ev_codes.append(code)
                continue
            shift = K_LSHIFT in self.held or K_RSHIFT in self.held or self.shift_once
            if self.caps and CHARS[code][0].isalpha():
                shift = not shift                # CapsLock は英字だけに効かせる (1 → ! にしない)
            events.append(("CHAR", CHARS[code][1 if shift else 0])); self.ev_codes.append(code)
            self.shift_once = False
        return events

    def flush(self, sec=0.6):
        end = time.time() + sec
        while time.time() < end:
            self._raw(0.05)
        self.held.clear()
        self.shift_once = False

    def close(self):
        try:
            fcntl.ioctl(self.fd, EVIOCGRAB, 0)
        finally:
            os.close(self.fd)


def find_keyboard():
    name = None
    for line in open("/proc/bus/input/devices"):
        if line.startswith("N: Name="):
            name = line.strip().split("=", 1)[1].strip('"')
        elif line.startswith("H: Handlers=") and name and "tca8418" in name:
            for h in line.split("=", 1)[1].split():
                if h.startswith("event"):
                    return "/dev/input/" + h
    raise RuntimeError("keyboard (tca8418) not found")


# ---------------------------------------------------------------- display
class FrameBuffer:
    def __init__(self, dev="/dev/fb0"):
        base = f"/sys/class/graphics/{os.path.basename(dev)}"
        self.bpp = int(open(f"{base}/bits_per_pixel").read())
        try:
            self.stride = int(open(f"{base}/stride").read())
        except OSError:
            self.stride = LCD_W * self.bpp // 8
        self.f = open(dev, "r+b", buffering=0)

    def show(self, img):
        a = np.asarray(img.convert("RGB"), dtype=np.uint16)
        if self.bpp == 16:
            buf = (((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)).astype("<u2")
        else:
            buf = np.zeros((LCD_H, LCD_W, 4), np.uint8)
            buf[..., 0], buf[..., 1], buf[..., 2], buf[..., 3] = a[..., 2], a[..., 1], a[..., 0], 255
        row = LCD_W * self.bpp // 8
        raw = buf.tobytes()
        if self.stride == row:
            self.f.seek(0)
            self.f.write(raw)
        else:
            for y in range(LCD_H):
                self.f.seek(y * self.stride)
                self.f.write(raw[y * row:(y + 1) * row])

    def clear(self):
        self.show(Image.new("RGB", (LCD_W, LCD_H)))


# 画面に出す字。ここに□(豆腐)が出ないフォントだけを使う
# (中国語向けのフォントは「歴・続・設・図」など日本の字体の漢字が無いことがある)
JP_TEST = "ことば番組本体設定明るさ向き接続流送消止再生停止読取保存一覧はやさ動横縦波往復点滅呼吸件秒"
_FONT_FILE = {}


def font_covers(font, text=JP_TEST):
    """text の字がすべてフォントに入っているか (無い字は .notdef の□と同じ形になる)"""
    try:
        nd = font.getmask("\U0010FFFD")
        nd_key = (nd.size, bytes(nd))
        for ch in text:
            m = font.getmask(ch)
            if m.getbbox() is None or (m.size, bytes(m)) == nd_key:
                return False
        return True
    except Exception:
        return False


def font_candidates():
    cands = []
    for p in ["/usr/share/APPLaunch/**/*.tt[fc]", "/usr/share/APPLaunch/**/*.otf",
              "/usr/share/fonts/**/*CJK*", "/usr/share/fonts/**/*[Ii][Pp][Aa]*",
              "/usr/share/fonts/**/*[Jj][Pp]*", "/usr/share/fonts/**/*wqy*",
              "/usr/share/fonts/**/*Droid*Fallback*"]:
        cands += glob.glob(p, recursive=True)
    return sorted(set(cands))


def find_font(size, bold=False):
    """日本語フォントを探す (細すぎるウェイトは後回し)。bold=True なら太いウェイトを優先
    一度決まったファイルは覚えておき、大きさだけ変えて使う"""
    f = _FONT_FILE.get(bold)
    if f:
        return ImageFont.truetype(f, size), f

    def rank(f):
        n = os.path.basename(f).lower()
        if "serif" in n or "mono" in n:
            return 50
        order = (["bold", "85", "heavy", "75", "black", "medium", "65", "regular", "55", "light", "thin"]
                 if bold else
                 ["medium", "65", "regular", "55", "bold", "75", "black", "light", "thin"])
        for i, w in enumerate(order):
            if w in n:
                return i
        return 5
    for f in sorted(font_candidates(), key=rank):
        try:
            font = ImageFont.truetype(f, size)
        except Exception:
            continue
        if font_covers(font):
            _FONT_FILE[bold] = f
            return font, f
        print("font skipped (日本語の字が足りない):", f, flush=True)
    return ImageFont.load_default(), None


# ---------------------------------------------------------------- camera / OCR

# ---------------------------------------------------------------- HEXA STAGE 風の部品
def hexpts(cx, cy, r, rot=30):
    """六角形の頂点 (rot=30 で上下が尖る向き)"""
    return [(cx + r * math.cos(math.radians(60 * i + rot)),
             cy + r * math.sin(math.radians(60 * i + rot))) for i in range(6)]


def honeycomb_bg():
    """ホーム画面の背景 (うっすらハニカム)。起動時に1回だけ作る"""
    img = Image.new("RGB", (LCD_W, LCD_H), BG)
    d = ImageDraw.Draw(img)
    for row in range(-1, 8):
        for col in range(-1, 12):
            cx = col * 30 + (15 if row % 2 else 0)
            cy = 20 + row * 26
            d.polygon(hexpts(cx, cy, 17), outline=(20, 24, 34))
    return img


def glow_hex(img, cx, cy, r, col):
    """光る六角形の枠 (ぼかした太線 + 細線)"""
    g = Image.new("RGB", img.size, (0, 0, 0))
    pts = hexpts(cx, cy, r)
    ImageDraw.Draw(g).line(pts + [pts[0]], fill=col, width=6)
    g = g.filter(ImageFilter.GaussianBlur(3))
    img.paste(ImageChops.lighter(img, g))
    ImageDraw.Draw(img).line(pts + [pts[0]], fill=col, width=2)



def launcher_pids():
    pids = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            cmd = open(f"/proc/{d}/cmdline", "rb").read()
        except OSError:
            continue
        if b"M5CardputerZero-APPLaunch" in cmd:
            pids.append(int(d))
    return pids


def signal_launcher(sig):
    for pid in launcher_pids():
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass

