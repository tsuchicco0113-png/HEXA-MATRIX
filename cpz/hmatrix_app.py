#!/usr/bin/env python3
"""HEXA MATRIX — CardputerZero 本体アプリ (v0.4)

CoreMatrix を CPZ のキーボードで操作する。USB は常駐の hmatrixd.py が持っていて、
このアプリは http://127.0.0.1:8090 を通して頼む。

ホーム (ハニカム) の六角形を選んで ENTER (1〜4 で直接も):
  1 ことば    : 打った文字をその場で CoreMatrix に流す (英数字・記号)
  2 ライブラリ: CPZ に置いた番組 (STUDIO の「CPZに置く」) を CPZ から流す / 本体SDへ送る
  3 本体      : CoreMatrix の中の番組を選んで流す・止める・消す
  4 設定      : 明るさ / 向き / スマホから開くQR
右側の 16×16 は、いま CPZ から流している絵

共通: ESC = ホームへ (ホームでは終了確認)  方向キー = F(↑) X(↓) Z(←) C(→)
      ことば画面では文字を打つので、方向は fn を押しながら

usage: hmatrix-app [--no-pause] [--debug-keys] [--hub http://127.0.0.1:8090]
"""
import argparse
import json
import math
import os
import queue
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cpzui import (BG, FG, LCD_H, LCD_W, SUB, find_font, glow_hex, hexpts,  # noqa: E402
                   honeycomb_bg, nav)

VERSION = "0.9.2"
ACC = (255, 176, 46)                 # HEXA MATRIX の強調色 (琥珀。HEXA CLIP の緑と見分ける)
DIM = (70, 52, 20)
OKC, NGC = (47, 214, 123), (255, 110, 110)
TOP_H, BOT_H = 18, 16
CFG_PATH = os.path.join(os.path.expanduser("~"), ".config", "hexa-matrix", "app.json")

M_HOME, M_SAY, M_LIB, M_DEV, M_SET = range(5)
SCREENS = [M_SAY, M_LIB, M_DEV, M_SET]
NAMES = {M_SAY: "ことば", M_LIB: "ライブラリ", M_DEV: "本体", M_SET: "設定"}
DESC = {M_SAY: "打った文字をすぐ流す", M_LIB: "CPZに置いた番組", M_DEV: "CoreMatrixの中の番組", M_SET: "明るさ・向き・スマホ"}

SHOWS = [("scrollL", "横流し"), ("static", "止めて"), ("wave", "波"), ("bounce", "往復"),
         ("blink", "点滅"), ("breathe", "呼吸"), ("scrollU", "縦送り"), ("scrollR", "右流し")]
EFFS = [("none", "なし"), ("slideL", "横から"), ("slideU", "下から"), ("type", "1字ずつ"),
        ("dissolve", "粒"), ("drop", "落ちる"), ("fade", "ふわっ"), ("zoom", "ズーム")]
MASTER = [40, 100, 170, 255]
FONTS = [(16, False, "16ドット"), (16, True, "16ドット 太字"), (8, False, "8ドット (2行)"), (8, True, "8ドット 太字")]
DURS = [(0, "ずっと"), (-1, "1回だけ"), (10, "10秒"), (30, "30秒"), (60, "1分"), (180, "3分"), (600, "10分")]


# ------------------------------------------------------------------ hub との話
class Hub:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.st = {}
        self.ok = False
        self.rev = 0
        threading.Thread(target=self._poll, daemon=True).start()

    def call(self, method, path, body=None, timeout=4.0):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                j = json.loads(e.read())
            except ValueError:
                j = {}
            raise RuntimeError(j.get("err") or f"HTTP {e.code}")
        except (urllib.error.URLError, OSError):
            raise RuntimeError("hub が止まっています (sudo systemctl start hexa-matrix)")

    def _poll(self):
        while True:
            try:
                st = self.call("GET", "/api/status", timeout=1.5)
                if st != self.st:
                    self.st = st; self.rev += 1
                self.ok = True
            except RuntimeError:
                if self.ok or not self.rev:
                    self.ok = False; self.st = {}; self.rev += 1
            time.sleep(0.2)


class Worker:
    """時間のかかる頼みごと (本体へ送る等) を裏で。終わったら結果を toast に"""

    def __init__(self):
        self.q = queue.Queue()
        self.busy = None
        self.results = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def do(self, label, fn, done=None):
        if self.busy:
            return False
        self.busy = label
        self.q.put((label, fn, done))
        return True

    def _run(self):
        while True:
            label, fn, done = self.q.get()
            try:
                r = fn()
                self.results.put((True, label, r, done))
            except Exception as e:                 # noqa: BLE001  (画面に出すだけ)
                self.results.put((False, label, str(e), None))
            self.busy = None


def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cfg(c):
    try:
        os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
    except OSError:
        pass


# ------------------------------------------------------------------ アプリ
class App:
    def __init__(self, hub, keys=None, fb=None):
        self.hub, self.keys, self.fb = hub, keys, fb
        self.work = Worker()
        self.font, _ = find_font(15)
        self.font_s, _ = find_font(12)
        self.font_t, _ = find_font(10)
        self.font_b, _ = find_font(19, bold=True)
        self.font_bs, _ = find_font(11, bold=True)
        self.bg = honeycomb_bg()
        self.mode = M_HOME
        self.sel = 0
        c = load_cfg()
        self.say = {"text": c.get("text", "HELLO"), "show": c.get("show", 0), "speed": c.get("speed", 6),
                    "bri": c.get("bri", 8), "eff": c.get("eff", 0),
                    "font": c.get("font", 0 if c.get("size", 16) == 16 else 2) % len(FONTS),
                    "dur": c.get("dur", 0) % len(DURS)}
        self.say_row = 0
        self.lib = []; self.lib_i = 0; self.lib_menu = None
        self.dev = None; self.dev_i = 0; self.dev_confirm = False
        self.set_i = 0; self.master = 3
        self.msg = None; self.msg_until = 0
        self.confirm_quit = False
        self.dirty = True
        self.last_rev = -1

    # ---- 小道具
    def toast(self, text, sec=2.5, ok=True):
        self.msg = (text, ok); self.msg_until = time.time() + sec; self.dirty = True

    def ask(self, label, fn, done=None, start=None):
        if not self.work.do(label, fn, done):
            self.toast("いま " + self.work.busy + " 中です", ok=False)
            return
        if start:
            self.toast(start, 30)

    def ellipsize(self, text, w, font=None):
        font = font or self.font_s
        if font.getlength(text) <= w:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            m = (lo + hi + 1) // 2
            if font.getlength(text[:m] + "…") <= w:
                lo = m
            else:
                hi = m - 1
        return text[:lo] + "…"

    # ---- 共通の枠
    def frame(self, title=None, hint=""):
        img = self.bg.copy() if self.mode == M_HOME else Image.new("RGB", (LCD_W, LCD_H), BG)
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, LCD_W, TOP_H - 1), fill=(24, 18, 8))
        d.text((5, 1), "HEXA MATRIX", fill=ACC, font=self.font_bs)
        if title:
            d.text((92, 2), title, fill=FG, font=self.font_s)
        st = self.hub.st
        if not self.hub.ok:
            s, col = "hub 停止", NGC
        elif not st.get("connected"):
            s, col = "CoreMatrix なし", NGC
        else:
            s, col = "● " + ("Wi-Fi " if st.get("link") == "wifi" else "USB ") + "v" + st.get("dev", {}).get("fw", "?"), OKC
        d.text((LCD_W - 4 - self.font_t.getlength(s), 3), s, fill=col, font=self.font_t)
        d.rectangle((0, LCD_H - BOT_H, LCD_W, LCD_H), fill=(24, 18, 8))
        d.text((4, LCD_H - BOT_H + 1), hint, fill=(210, 210, 210), font=self.font_s)
        return img, d

    def draw_led(self, d, x0, y0, pitch=4, r=1.5):
        st = self.hub.st
        fr = st.get("frame") or ""
        bits = bytes.fromhex(fr) if len(fr) == 64 else bytes(32)
        bri = st.get("bri")
        k = 0.25 + 0.75 * min(1, (bri if bri is not None else 255) / 255)
        on = tuple(int(255 * k) for _ in range(3))
        playing = (st.get("player") or {}).get("playing")
        d.rectangle((x0 - 3, y0 - 3, x0 + pitch * 16 + 2, y0 + pitch * 16 + 2), fill=(0, 0, 0), outline=(40, 44, 54))
        for y in range(16):
            v = (bits[y * 2] << 8) | bits[y * 2 + 1]
            for x in range(16):
                cx, cy = x0 + x * pitch + pitch / 2, y0 + y * pitch + pitch / 2
                lit = playing and v & (0x8000 >> x)
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=on if lit else (28, 30, 36))

    def player_line(self):
        st = self.hub.st
        p = st.get("player") or {}
        if p.get("playing"):
            left = p.get("left")
            return ("▶ " + (f"あと{left}秒 " if left is not None else "") + p.get("name", "")), ACC
        if st.get("web"):
            return "ブラウザから送信中", OKC
        dv = st.get("dev") or {}
        if dv:
            if dv.get("clip"):
                return "本体: CPZの絵を流しています", SUB
            return ("本体: 待機中 (Bで番組)" if dv.get("paused") else f"本体の番組 {dv.get('cur', 0) + 1}/{dv.get('n', 0)}"), SUB
        return "", SUB

    # ---- 画面
    def render(self):
        return {M_HOME: self.r_home, M_SAY: self.r_say, M_LIB: self.r_lib,
                M_DEV: self.r_dev, M_SET: self.r_set}[self.mode]()

    def r_home(self):
        img, d = self.frame(None, "方向+ENTER / 1〜4 で選ぶ  ESC 終了")
        pos = [(42, 62), (100, 62), (42, 120), (100, 120)]
        for i, (m, (cx, cy)) in enumerate(zip(SCREENS, pos)):
            on = i == self.sel
            d.polygon(hexpts(cx, cy, 30), fill=DIM if on else (20, 22, 30))
            if on:
                glow_hex(img, cx, cy, 30, ACC)
                d = ImageDraw.Draw(img)
            else:
                pts = hexpts(cx, cy, 30); d.line(pts + [pts[0]], fill=(60, 64, 78), width=1)
            name = NAMES[m]
            f = self.font_s if self.font_s.getlength(name) <= 46 else self.font_t
            d.text((cx - f.getlength(name) / 2, cy - 8), name, fill=FG if on else SUB, font=f)
            d.text((cx - 3, cy + 9), str(i + 1), fill=ACC if on else (90, 94, 108), font=self.font_t)
        x0 = 150
        m = SCREENS[self.sel]
        d.text((x0, 24), NAMES[m], fill=FG, font=self.font_b)
        d.text((x0, 50), DESC[m], fill=SUB, font=self.font_t)
        self.draw_led(d, x0 + 4, 72, pitch=4, r=1.6)
        s, col = self.player_line()
        d.text((x0, 142), self.ellipsize(s, LCD_W - x0 - 4, self.font_t), fill=col, font=self.font_t)
        if self.confirm_quit:
            self.box(img, ["HEXA MATRIX を終了しますか?", "ENTER = 終了 / ESC = やめる"])
        return img

    def box(self, img, lines):
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((30, 50, LCD_W - 30, 120), 6, fill=(30, 24, 12), outline=ACC, width=2)
        for i, t in enumerate(lines):
            f = self.font if i == 0 else self.font_s
            d.text(((LCD_W - f.getlength(t)) / 2, 62 + i * 28), t, fill=FG if i == 0 else SUB, font=f)

    def r_say(self):
        img, d = self.frame("ことば", "打つ / fn+↑↓ 項目 / fn+←→ 変える / ENTER 流す")
        s = self.say
        rows = [("文字", None),
                ("動き", SHOWS[s["show"]][1]),
                ("入り", EFFS[s["eff"]][1]),
                ("はやさ", f"{s['speed']}"),
                ("明るさ", f"{s['bri']}/16"),
                ("字", FONTS[s["font"]][2]),
                ("長さ", DURS[s["dur"]][1])]
        y = 21
        for i, (k, v) in enumerate(rows):
            on = i == self.say_row
            if on:
                d.rectangle((2, y - 1, 228, y + (25 if i == 0 else 15)), fill=(44, 33, 12))
            d.text((6, y + (4 if i == 0 else 0)), k, fill=ACC if on else SUB, font=self.font_s)
            if i == 0:
                d.rectangle((48, y, 226, y + 23), fill=(0, 0, 0), outline=ACC if on else (60, 64, 78))
                t = s["text"]
                while t and self.font.getlength(t) > 168:
                    t = t[1:]
                d.text((52, y + 3), t, fill=FG, font=self.font)
                if on and int(time.time() * 2) % 2 == 0:
                    cx = 53 + self.font.getlength(t)
                    d.line((cx, y + 4, cx, y + 19), fill=ACC, width=1)
                y += 28
            else:
                arrow = ("◀ " + v + " ▶") if on else v
                d.text((60, y), arrow, fill=FG if on else (200, 200, 205), font=self.font_s)
                y += 17
        self.draw_led(d, 240, 30, pitch=4.6, r=1.8)
        s2, col = self.player_line()
        d.text((236, 112), self.ellipsize(s2, 80, self.font_t), fill=col, font=self.font_t)
        self.toast_draw(img)
        return img

    def r_lib(self):
        img, d = self.frame("ライブラリ", "↑↓ / ENTER メニュー / SPACE 止める / R 更新")
        if not self.lib:
            d.text((10, 44), "まだ番組がありません", fill=FG, font=self.font)
            d.text((10, 72), "スマホ/PCで STUDIO を開いて", fill=SUB, font=self.font_s)
            d.text((10, 90), "「CPZに置く」を押してください", fill=SUB, font=self.font_s)
            self.draw_qr_small(img, 226, 24)
        else:
            self.list_draw(d, [(it["title"], ("1回 " if it.get("once") else "") + f"{it.get('sec') or '?'}秒")
                               for it in self.lib], self.lib_i, 222)
            self.draw_led(d, 240, 30, pitch=4.6, r=1.8)
            s, col = self.player_line()
            d.text((236, 112), self.ellipsize(s, 80, self.font_t), fill=col, font=self.font_t)
        if self.lib_menu is not None:
            items = ["CPZから流す (くりかえし)", "CPZから1回だけ流す", "本体(SD)に送る", "消す"]
            d.rounded_rectangle((40, 34, 280, 40 + 22 * len(items) + 8), 6, fill=(30, 24, 12), outline=ACC, width=2)
            for i, t in enumerate(items):
                on = i == self.lib_menu
                if on:
                    d.rectangle((46, 42 + i * 22, 274, 60 + i * 22), fill=(70, 52, 20))
                d.text((54, 43 + i * 22), t, fill=FG if on else SUB, font=self.font_s)
        busy = (self.hub.st or {}).get("busy")
        if busy:
            pct = busy["done"] / max(1, busy["total"])
            d.rectangle((10, LCD_H - BOT_H - 10, LCD_W - 10, LCD_H - BOT_H - 4), outline=ACC)
            d.rectangle((10, LCD_H - BOT_H - 10, 10 + int((LCD_W - 20) * pct), LCD_H - BOT_H - 4), fill=ACC)
        self.toast_draw(img)
        return img

    def r_dev(self):
        img, d = self.frame("本体の番組", "↑↓ / ENTER 流す / SPACE 止める / D 消す / R")
        dv = self.dev
        if not self.hub.st.get("connected"):
            d.text((10, 40), "CoreMatrix がつながっていません", fill=NGC, font=self.font_s)
            d.text((10, 62), "USB: USB-SW を Host 側(右)にして", fill=SUB, font=self.font_s)
            d.text((10, 80), "      USB-A か USB-C1 へ", fill=SUB, font=self.font_s)
            d.text((10, 102), "Wi-Fi: SD の hexa/wifi.txt (v0.5〜)", fill=SUB, font=self.font_s)
        elif dv is None:
            d.text((10, 50), "読み込み中…", fill=SUB, font=self.font)
        else:
            store = {"sd": "microSD", "flash": "本体メモリ", "none": "保存先なし"}.get(dv.get("store"), "?")
            head = f"{store} ・ 空き {dv.get('free', 0) / 1024:.1f}MB"
            if dv.get("sd") == "unreadable":
                head = "SDが読めません → FAT32に"
            d.text((6, 21), head, fill=NGC if dv.get("sd") == "unreadable" else SUB, font=self.font_t)
            files = dv.get("files") or []
            if not files:
                d.text((10, 56), "番組がありません", fill=FG, font=self.font)
                d.text((10, 82), "ライブラリから「本体に送る」で入ります", fill=SUB, font=self.font_s)
            else:
                cur = dv.get("cur", -1)
                self.list_draw(d, [(("▶ " if i == cur else "   ") + f["n"], f"{f['s'] / 1024:.0f}KB")
                                   for i, f in enumerate(files)], self.dev_i, LCD_W - 6, top=36)
        if self.dev_confirm and dv and dv.get("files"):
            self.box(img, ["「" + self.ellipsize(dv["files"][self.dev_i]["n"], 200, self.font) + "」を消す?",
                           "ENTER = 消す / ESC = やめる"])
        self.toast_draw(img)
        return img

    def r_set(self):
        img, d = self.frame("設定", "↑↓ 項目 / ←→ ENTER 変える / ESC ホーム")
        dv = self.hub.st.get("dev") or {}
        rows = [("CoreMatrix の明るさ", f"{self.master + 1}/4 (ライブ)"),
                ("向き", f"{dv.get('rot', '?')} (ENTERで90°)"),
                ("CPZから止める", "ENTER")]
        y = 24
        for i, (k, v) in enumerate(rows):
            on = i == self.set_i
            if on:
                d.rectangle((2, y - 1, 196, y + 17), fill=(44, 33, 12))
            d.text((6, y), k, fill=ACC if on else SUB, font=self.font_s)
            d.text((6, y + 18), v, fill=FG, font=self.font_t)
            y += 36
        st = self.hub.st
        info = [f"ファーム v{dv.get('fw', '-')}  保存先 {dv.get('store', '-')}",
                f"USB {st.get('port') or '-'}"]
        for i, t in enumerate(info):
            d.text((6, 132 + i * 11), self.ellipsize(t, 190, self.font_t), fill=SUB, font=self.font_t)
        self.draw_qr_small(img, 210, 24)
        return img

    def url(self):
        ip = self.hub.st.get("ip") or "?"
        return f"http://{ip}:8090/"

    def draw_qr_small(self, img, x0, y0, maxw=84):
        """スマホ用QR。x0 から右端までに収める (QR・文字とも画面からはみ出さない)"""
        d = ImageDraw.Draw(img)
        right = LCD_W - 3
        maxw = min(maxw, right - x0)
        bottom = LCD_H - BOT_H - 2
        url = self.url()
        w = h = 0
        try:
            import qrcode
            qr = qrcode.QRCode(border=1, box_size=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
            qr.add_data(url); qr.make(fit=True)
            q = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            k = max(1, min(maxw, bottom - y0 - 26) // q.size[0])
            q = q.resize((q.size[0] * k, q.size[1] * k), Image.NEAREST)
            w, h = q.size
            img.paste(q, (right - w, y0))
        except Exception:                        # noqa: BLE001  qrcode が無い時は文字だけ
            pass
        cx = right - w / 2 if w else (x0 + right) / 2
        for i, (t, col) in enumerate((("スマホでSTUDIO", SUB), (url.replace("http://", "").rstrip("/"), ACC))):
            tw = self.font_t.getlength(t)
            tx = max(x0 - 30, min(cx - tw / 2, right - tw))
            d.text((tx, y0 + h + 2 + i * 12), t, fill=col, font=self.font_t)

    def list_draw(self, d, items, cur, width, top=24, row=18):
        n = max(1, (LCD_H - BOT_H - top - 2) // row)
        start = max(0, min(cur - n // 2, len(items) - n))
        for k, (a, b) in enumerate(items[start:start + n]):
            i = start + k; y = top + k * row
            on = i == cur
            if on:
                d.rectangle((2, y - 1, width, y + row - 2), fill=(44, 33, 12))
            bw = self.font_t.getlength(b)
            d.text((6, y), self.ellipsize(a, width - 14 - bw), fill=FG if on else (205, 208, 215), font=self.font_s)
            d.text((width - 3 - bw, y + 2), b, fill=SUB, font=self.font_t)

    def toast_draw(self, img):
        if self.msg and time.time() < self.msg_until:
            d = ImageDraw.Draw(img)
            t, ok = self.msg
            if self.mode == M_SAY:                  # 項目に重ならないよう右下に小さく
                d.rounded_rectangle((232, 126, LCD_W - 2, LCD_H - BOT_H - 2), 4, fill=(20, 60, 36) if ok else (90, 24, 24))
                lines, cur = [], ""
                for ch in t:
                    if self.font_t.getlength(cur + ch) > 80:
                        lines.append(cur); cur = ""
                    cur += ch
                lines.append(cur)
                for i, ln in enumerate(lines[:2]):
                    d.text((236, 128 + i * 11), ln, fill=FG, font=self.font_t)
                return
            w = min(LCD_W - 12, self.font_s.getlength(t) + 16)
            x = (LCD_W - w) / 2
            d.rounded_rectangle((x, LCD_H - BOT_H - 26, x + w, LCD_H - BOT_H - 6), 5,
                                fill=(20, 60, 36) if ok else (90, 24, 24))
            d.text((x + 8, LCD_H - BOT_H - 24), self.ellipsize(t, w - 16), fill=FG, font=self.font_s)

    # ---- 操作
    def handle(self, events):
        for kind, val in events:
            self.dirty = True
            fn = {M_HOME: self.k_home, M_SAY: self.k_say, M_LIB: self.k_lib,
                  M_DEV: self.k_dev, M_SET: self.k_set}[self.mode]
            if self.mode != M_SAY:
                kind, val = nav([(kind, val)])[0]
            if fn(kind, val) == "quit":
                return "quit"
        return None

    def go(self, m):
        self.mode = m
        if m == M_LIB:
            self.refresh_lib()
        elif m == M_DEV:
            self.refresh_dev()

    def k_home(self, kind, val):
        if self.confirm_quit:
            if val == "ENTER":
                return "quit"
            if val == "ESC":
                self.confirm_quit = False
            return None
        if kind == "CHAR" and val in "1234":
            self.sel = int(val) - 1; self.go(SCREENS[self.sel]); return None
        moves = {"LEFT": -1, "RIGHT": 1, "UP": -2, "DOWN": 2, "TAB": 1}
        if val in moves:
            self.sel = (self.sel + moves[val]) % 4
        elif val == "ENTER":
            self.go(SCREENS[self.sel])
        elif val == "ESC":
            self.confirm_quit = True
        return None

    def k_say(self, kind, val):
        s = self.say
        if val == "ESC":
            self.save(); self.mode = M_HOME; return
        if kind == "CHAR":
            if len(s["text"]) < 200:
                s["text"] += val
            self.say_row = 0
            return
        if val == "BS":
            s["text"] = s["text"][:-1]; return
        if val in ("UP", "DOWN", "TAB"):
            self.say_row = (self.say_row + (-1 if val == "UP" else 1)) % 7; return
        if val in ("LEFT", "RIGHT"):
            dlt = -1 if val == "LEFT" else 1
            r = self.say_row
            if r == 1: s["show"] = (s["show"] + dlt) % len(SHOWS)
            elif r == 2: s["eff"] = (s["eff"] + dlt) % len(EFFS)
            elif r == 3: s["speed"] = max(1, min(10, s["speed"] + dlt))
            elif r == 4: s["bri"] = max(1, min(16, s["bri"] + dlt))
            elif r == 5: s["font"] = (s["font"] + dlt) % len(FONTS)
            elif r == 6: s["dur"] = (s["dur"] + dlt) % len(DURS)
            return
        if val == "DEL":
            s["text"] = ""; return
        if val == "ENTER":
            self.send_say()

    def send_say(self):
        s = self.say
        if not s["text"].strip():
            self.toast("文字を打ってください", ok=False); return
        self.save()
        size, bold, _ = FONTS[s["font"]]
        dur = DURS[s["dur"]][0]
        body = {"text": s["text"], "show": SHOWS[s["show"]][0], "eff": EFFS[s["eff"]][0],
                "speed": s["speed"], "bri": s["bri"], "size": size, "bold": bold,
                "loop": dur != -1, "dur": max(0, dur)}
        how = {0: "くりかえし", -1: "1回だけ"}.get(dur, DURS[s["dur"]][1] + "だけ")
        self.ask("ことば", lambda: self.hub.call("POST", "/api/say", body, timeout=30),
                 lambda r: self.toast(f"流しています ({how})" + ("  ※まとめて送れず1コマずつ" if r.get("mode") == "stream" else ""),
                                      4 if r.get("mode") == "stream" else 2.5, ok=r.get("mode") != "stream"))

    def save(self):
        s = self.say
        save_cfg({"text": s["text"], "show": s["show"], "speed": s["speed"], "bri": s["bri"],
                  "eff": s["eff"], "font": s["font"], "dur": s["dur"]})

    def refresh_lib(self):
        def done(r):
            self.lib = r.get("items") or []
            self.lib_i = min(self.lib_i, max(0, len(self.lib) - 1))
        self.ask("一覧", lambda: self.hub.call("GET", "/api/library"), done)

    def k_lib(self, kind, val):
        if self.lib_menu is not None:
            if val == "ESC":
                self.lib_menu = None
            elif val in ("UP", "DOWN"):
                self.lib_menu = (self.lib_menu + (-1 if val == "UP" else 1)) % 4
            elif val == "ENTER":
                it = self.lib[self.lib_i]; m = self.lib_menu; self.lib_menu = None
                if m in (0, 1):
                    self.ask("再生", lambda: self.hub.call("POST", "/api/play", {"name": it["name"], "loop": m == 0}, timeout=120),
                             lambda r: self.toast("CPZから流しています"))
                elif m == 2:
                    self.ask("本体へ送る", lambda: self.hub.call("POST", "/api/push", {"name": it["name"]}, timeout=180),
                             lambda r: self.toast(f"本体に保存: {r.get('saved')} ({r.get('sec')}秒)"),
                             start="本体へ送っています…")
                elif m == 3:
                    self.ask("消す", lambda: self.hub.call("DELETE", "/api/library/" + urllib.parse.quote(it["name"])),
                             lambda r: (self.toast("消しました"), self.refresh_lib()))
            return
        if val == "ESC":
            self.mode = M_HOME
        elif val in ("UP", "DOWN") and self.lib:
            self.lib_i = (self.lib_i + (-1 if val == "UP" else 1)) % len(self.lib)
        elif val == "ENTER" and self.lib:
            self.lib_menu = 0
        elif kind == "CHAR" and val == " ":
            self.stop()
        elif kind == "CHAR" and val in "rR":
            self.refresh_lib()

    def stop(self):
        self.ask("停止", lambda: self.hub.call("POST", "/api/stop", {}), lambda r: self.toast("CPZからの再生を止めました (3秒で本体の番組に戻ります)"))

    def refresh_dev(self):
        def done(r):
            self.dev = r
            self.dev_i = min(max(0, r.get("cur", 0)), max(0, len(r.get("files") or []) - 1))
        self.dev = None
        self.ask("本体の一覧", lambda: self.hub.call("GET", "/api/device/list"), done)

    def k_dev(self, kind, val):
        files = (self.dev or {}).get("files") or []
        if self.dev_confirm:
            if val == "ENTER" and files:
                n = files[self.dev_i]["n"]
                self.ask("消す", lambda: self.hub.call("POST", "/api/device/delete", {"name": n}),
                         lambda r: (setattr(self, "dev", r), self.toast("本体から消しました")))
            if val in ("ENTER", "ESC"):
                self.dev_confirm = False
            return
        if val == "ESC":
            self.mode = M_HOME
        elif val in ("UP", "DOWN") and files:
            self.dev_i = (self.dev_i + (-1 if val == "UP" else 1)) % len(files)
        elif val == "ENTER" and files:
            i = self.dev_i
            self.ask("再生", lambda: self.hub.call("POST", "/api/device/play", {"idx": i}),
                     lambda r: (self.dev.__setitem__("cur", i), self.toast(f"本体で {i + 1} 番を流しています")))
        elif kind == "CHAR" and val == " ":
            self.ask("一時停止", lambda: self.hub.call("POST", "/api/device/play", {"pause": True}),
                     lambda r: self.toast("本体を止めました (本体のBで再開)"))
        elif kind == "CHAR" and val in "dD" and files:
            self.dev_confirm = True
        elif kind == "CHAR" and val in "rR":
            self.refresh_dev()

    def k_set(self, kind, val):
        if val == "ESC":
            self.mode = M_HOME
        elif val in ("UP", "DOWN"):
            self.set_i = (self.set_i + (-1 if val == "UP" else 1)) % 3
        elif self.set_i == 0 and val in ("LEFT", "RIGHT", "ENTER"):
            self.master = max(0, min(3, self.master + (-1 if val == "LEFT" else 1))) if val != "ENTER" else (self.master + 1) % 4
            v = MASTER[self.master]
            self.ask("明るさ", lambda: self.hub.call("POST", "/api/device/bright", {"value": v}))
        elif self.set_i == 1 and val == "ENTER":
            self.ask("向き", lambda: self.hub.call("POST", "/api/device/rotate", {}), lambda r: self.toast("向きを変えました"))
        elif self.set_i == 2 and val == "ENTER":
            self.stop()

    # ---- 結果を受け取る
    def drain(self):
        while not self.work.results.empty():
            ok, label, r, done = self.work.results.get()
            self.dirty = True
            if not ok:
                self.toast(f"{label}: {r}", 4, ok=False)
                if self.mode == M_DEV and self.dev is None:
                    self.dev = {}
            elif done:
                done(r)
            elif self.msg and self.msg_until - time.time() > 5:
                self.msg_until = 0

    def run(self):
        last = 0
        while True:
            ev = self.keys.poll(0.05) if self.keys else []
            if ev and self.handle(ev) == "quit":
                return "quit"
            self.drain()
            if self.hub.rev != self.last_rev:
                self.last_rev = self.hub.rev; self.dirty = True
            now = time.time()
            if self.mode == M_SAY and now - last > 0.5:
                self.dirty = True                      # カーソルの点滅
            if self.msg and now > self.msg_until and self.msg_until:
                self.msg_until = 0; self.dirty = True
            if self.dirty and now - last > 0.08:
                self.fb.show(self.render()); self.dirty = False; last = now


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default=os.environ.get("HMATRIX_URL", "http://127.0.0.1:8090"))
    ap.add_argument("--no-pause", action="store_true", help="ランチャーを一時停止しない")
    ap.add_argument("--debug-keys", action="store_true")
    a = ap.parse_args()
    from cpzui import FrameBuffer, Keys, find_keyboard, launcher_pids, signal_launcher
    fb = FrameBuffer()
    keys = Keys(find_keyboard(), a.debug_keys)
    keys.flush(0.3)
    paused = False
    if not a.no_pause and launcher_pids():
        signal_launcher(signal.SIGSTOP); paused = True
        for sg in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sg, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    reason = "?"
    try:
        reason = App(Hub(a.hub), keys, fb).run()
    except KeyboardInterrupt:
        reason = "Ctrl+C"
    except Exception:                                  # noqa: BLE001
        import traceback
        traceback.print_exc(); reason = "error"
    finally:
        print("exit:", reason, flush=True)
        keys.close(); fb.clear()
        if paused:
            signal_launcher(signal.SIGCONT)


if __name__ == "__main__":
    main()
