#!/usr/bin/env python3
"""HEXA MATRIX — CardputerZero 本体アプリ (v0.11)

CoreMatrix を CPZ のキーボードで操作する。USB は常駐の hmatrixd.py が持っていて、
このアプリは http://127.0.0.1:8090 を通して頼む。

ホーム (ハニカム) の六角形を選んで ENTER (1〜4 で直接も):
  1 ことば    : 打った文字をその場で CoreMatrix に流す (英数字・記号)
  2 ライブラリ: CPZ に置いた番組 (STUDIO の「CPZに置く」) を CPZ から流す / 本体SDへ送る
  3 本体      : CoreMatrix の中の番組を選んで流す・止める・消す
  4 設定      : 明るさ / 向き / 自動回転 / 振って次 / 省電力 / 箱庭 / 充電 / イベントAP / スマホから開くQR
  5 歩く      : Stackchan Strider (CoreMatrix + FS90R) を歩かせる (ファーム v0.12〜)。
                操作画面: ↑前 ↓後 (押している間だけ / 押したら続く) SPACE 止まる 1〜7 顔 英字キー = プログラム
                TAB 設定 / P プログラムの編集 (動き [速さ, 秒] の並び + くりかえし + キー)
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

VERSION = "0.14.0"
ACC = (255, 176, 46)                 # HEXA MATRIX の強調色 (琥珀。HEXA CLIP の緑と見分ける)
DIM = (70, 52, 20)
OKC, NGC = (47, 214, 123), (255, 110, 110)
TOP_H, BOT_H = 18, 16
CFG_PATH = os.path.join(os.path.expanduser("~"), ".config", "hexa-matrix", "app.json")

M_HOME, M_SAY, M_LIB, M_DEV, M_SET, M_WALK = range(6)
SCREENS = [M_SAY, M_LIB, M_DEV, M_SET, M_WALK]
NAMES = {M_SAY: "ことば", M_LIB: "ライブラリ", M_DEV: "本体", M_SET: "設定", M_WALK: "歩く"}
DESC = {M_SAY: "打った文字をすぐ流す", M_LIB: "CPZに置いた番組", M_DEV: "CoreMatrixの中の番組", M_SET: "向き・省電力・イベントAP",
        M_WALK: "Strider を歩かせる"}
WALK_FACES = ["おまかせ", "ふつう", "にっこり", "びっくり", "ねむい", "おこ", "キャラ"]   # キャラ = 箱庭のキャラ (ファーム v0.13〜)
# v0.13 プログラム: [速さ % (+前 / −後), 秒] を順に。キーは英字 (F/X/Z/C は方向、P は編集なので使わない)
PROG_KEYS = list("QWERTYUIOADGHJKLSVBNM")
DEFAULT_PROGS = [
    {"name": "右に回る", "key": "E", "rep": 1, "steps": [[-110, 3.0]]},     # ±110 = その場旋回 (− 右 / + 左、v0.13.6〜)
    {"name": "左に回る", "key": "Q", "rep": 1, "steps": [[110, 3.0]]},
    {"name": "ちょっと前", "key": "W", "rep": 1, "steps": [[40, 3.0]]},
    {"name": "ちょっと後ろ", "key": "S", "rep": 1, "steps": [[-40, 3.0]]},
]
SERVO_PINS = [-1, 23, 22, 24, 29, 5, 6, 7, 8, 10, 11]   # M5-Bus の GPIO (0/1 は I2C、12/13 は USB なので使わない)

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
        self.ap = None               # イベントAP の状態 (GET /api/ap)
        self.walk = {"speed": 0, "set": int(c.get("wspeed", 40)), "face": 0}   # set = ↑↓で出す速さ
        self.walk_i = 0; self.walk_sent = 0.0; self.walk_err = None
        # v0.12.3: 押している間だけ歩く (hold) / 押したら歩き続ける
        self.walk_hold = bool(c.get("whold", True))
        self.walk_hold_code = None          # 押しっぱなしで歩いている時のキー
        self.cur_code = None
        # v0.13: 操作画面 / 設定 / プログラム一覧 / プログラム編集
        self.walk_view = "ctl"
        self.pad_i = 0
        self.scan_half = int(c.get("wscanhalf", 250))
        self.progs = c.get("wprogs") or [dict(p, steps=[list(x) for x in p["steps"]]) for p in DEFAULT_PROGS]
        for p in self.progs:                 # v0.13.2: 仮の旋回 (前 1.0 + 後 0.2) を本当の旋回に置き換える
            if p.get("name") in ("右に回る(仮)", "左に回る(仮)") and len(p.get("steps", [])) == 2:
                p.update(name=p["name"][:-3], rep=1, steps=[[-110 if p["name"].startswith("右") else 110, 3.0]])
        self.prog_i = 0; self.prog_run = None; self.del_armed = False
        self.edit = None; self.edit_row = 0; self.edit_field = 0
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
                M_DEV: self.r_dev, M_SET: self.r_set, M_WALK: self.r_walk}[self.mode]()

    def r_home(self):
        img, d = self.frame(None, "方向+ENTER / 1〜5 で選ぶ  ESC 終了")
        pos = [(32, 58), (86, 58), (32, 116), (86, 116), (140, 87)]    # 5つ目 (歩く) は右の段に
        R = 26
        for i, (m, (cx, cy)) in enumerate(zip(SCREENS, pos)):
            on = i == self.sel
            d.polygon(hexpts(cx, cy, R), fill=DIM if on else (20, 22, 30))
            if on:
                glow_hex(img, cx, cy, R, ACC)
                d = ImageDraw.Draw(img)
            else:
                pts = hexpts(cx, cy, R); d.line(pts + [pts[0]], fill=(60, 64, 78), width=1)
            name = NAMES[m]
            f = self.font_s if self.font_s.getlength(name) <= 46 else self.font_t
            d.text((cx - f.getlength(name) / 2, cy - 8), name, fill=FG if on else SUB, font=f)
            d.text((cx - 3, cy + 9), str(i + 1), fill=ACC if on else (90, 94, 108), font=self.font_t)
        x0 = 174
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

    SET_KEYS = ["bright", "rot", "autorot", "shake", "psave", "hako", "chg", "hflip", "pled", "ap", "teach", "stop"]
    SET_ROWS = len(SET_KEYS)

    def set_items(self):
        dv = self.hub.st.get("dev") or {}
        cfg = dv.get("cfg") or {}
        hk = dv.get("hako") or {}
        new = "cfg" in dv                                    # ファーム v0.9.6〜
        newh = "hako" in dv                                  # ファーム v0.10〜
        onoff = lambda k: ("入" if cfg.get(k) else "切") if new else "要v0.9.6"
        learn = dv.get("learn", 0)
        rot = onoff("autorot") + (f" (覚えた向き{learn})" if new and cfg.get("autorot") else "")
        if dv.get("imu") == "none":
            rot = "IMUなし"
        ap = self.ap or {}
        hset = {"auto": "自動 (USBなしで)", "on": "いつも", "off": "使わない"}.get(hk.get("set"), "?")
        rows = {"bright": ("CoreMatrix の明るさ", f"{self.master + 1}/4"),
                "rot": ("向き", f"{dv.get('rot', '?')} (ENTERで90°)"),
                "autorot": ("自動回転", rot),
                "shake": ("振って次の番組", onoff("shake")),
                "psave": ("消灯中の省電力", onoff("psave")),
                "hako": ("箱庭", hset + (" ・いま箱庭" if dv.get("mode") == "hako" else "") if newh else "要v0.10"),
                "chg": ("充電の速さ", (f"{hk.get('chg', 180)}mA" + (" (18350×2 用)" if hk.get("chg") == 650 else "")) if newh else "要v0.10"),
                "hflip": ("箱庭の傾き 左右", ("反対" if hk.get("hflip") else "ふつう") if newh else "要v0.10"),
                "pled": ("緑の電源LED", ("点ける" if hk.get("pled", 1) else "消す") if "pled" in hk else "要v0.13.2"),
                "ap": ("イベントAP (CPZ)", "?" if not ap else ("入" if ap.get("on") else "切") if ap.get("ok") else "使えません"),
                "teach": ("APを本体に教える", "USB で ENTER"),
                "stop": ("CPZから止める", "ENTER")}
        return [rows[k] for k in self.SET_KEYS]

    def r_set(self):
        img, d = self.frame("設定", "↑↓ 項目 / ←→ ENTER 変える / ESC ホーム")
        self.list_draw(d, self.set_items(), self.set_i, 204)
        dv = self.hub.st.get("dev") or {}
        x0, y = 212, 22
        bv = dv.get("batt")
        if isinstance(bv, int) and bv > 0:
            t = f"電池 {dv.get('lvl', '?')}% {bv / 1000:.2f}V" + (" 充電中" if dv.get("chg") else "")
            d.text((x0, y), self.ellipsize(t, LCD_W - x0 - 3, self.font_t), fill=SUB, font=self.font_t); y += 12
        ap = self.ap or {}
        if ap.get("on"):
            for t, col in (("イベントAP 入", OKC), (ap.get("ssid", ""), FG), ("pw " + ap.get("pass", ""), FG)):
                d.text((x0, y), self.ellipsize(t, LCD_W - x0 - 3, self.font_t), fill=col, font=self.font_t); y += 12
        self.draw_qr_small(img, x0, y + 2)
        return img

    def refresh_ap(self):
        def done(r):
            self.ap = r; self.dirty = True
        def fn():
            try:
                self.hub.call("POST", "/api/device/ping", {}, timeout=4)    # 電池・設定を新しく
            except RuntimeError:
                pass
            try:
                return self.hub.call("GET", "/api/ap", timeout=6)
            except RuntimeError as e:
                return {"ok": False, "err": str(e)}
        self.work.do("AP", fn, done)

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
        codes = list(getattr(self.keys, "ev_codes", []) or [])
        for i, (kind, val) in enumerate(events):
            self.cur_code = codes[i] if i < len(codes) else None
            self.dirty = True
            fn = {M_HOME: self.k_home, M_SAY: self.k_say, M_LIB: self.k_lib,
                  M_DEV: self.k_dev, M_SET: self.k_set, M_WALK: self.k_walk}[self.mode]
            typing = self.mode == M_WALK and self.walk_view == "edit" and self.edit_row == 0   # 名前を打っている
            if self.mode != M_SAY and not typing:
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
        elif m == M_SET:
            self.refresh_ap()

    def k_home(self, kind, val):
        if self.confirm_quit:
            if val == "ENTER":
                return "quit"
            if val == "ESC":
                self.confirm_quit = False
            return None
        if kind == "CHAR" and val in "12345":
            self.sel = int(val) - 1; self.go(SCREENS[self.sel]); return None
        moves = {"LEFT": -1, "RIGHT": 1, "UP": -2, "DOWN": 2, "TAB": 1}
        if val in moves:
            self.sel = (self.sel + moves[val]) % len(SCREENS)
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
        self.ask("ことば", lambda: self.hub.call("POST", "/api/say", body, timeout=60),
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
            return
        if val in ("UP", "DOWN"):
            self.set_i = (self.set_i + (-1 if val == "UP" else 1)) % self.SET_ROWS
            return
        key = self.SET_KEYS[self.set_i]
        dv = self.hub.st.get("dev") or {}
        cfg = dv.get("cfg") or {}
        hk = dv.get("hako") or {}
        lr = val in ("LEFT", "RIGHT", "ENTER")
        cfgcall = lambda body, msg: self.ask("設定", lambda: self.hub.call("POST", "/api/device/config", body), lambda r: self.toast(msg, 4))
        if key == "bright" and lr:
            self.master = max(0, min(3, self.master + (-1 if val == "LEFT" else 1))) if val != "ENTER" else (self.master + 1) % 4
            v = MASTER[self.master]
            self.ask("明るさ", lambda: self.hub.call("POST", "/api/device/bright", {"value": v}))
        elif key == "rot" and val == "ENTER":
            self.ask("向き", lambda: self.hub.call("POST", "/api/device/rotate", {}),
                     lambda r: self.toast("向きを変えました (この傾きを覚えました)" if (r or {}).get("imu") == "ok" else "向きを変えました"))
        elif key in ("autorot", "shake", "psave") and lr:
            on = not cfg.get(key) if val == "ENTER" else val == "RIGHT"
            msg = {"autorot": "自動回転を入れました。いまの向きを覚えました。C長押しで直すと、その向きも覚えます" if on else "自動回転を切りました",
                   "shake": "振ると次の番組へ進みます" if on else "振っても何もしません",
                   "psave": "消灯中は Wi-Fi を省電力にします" if on else "省電力を切りました"}[key]
            cfgcall({key: on}, msg)
        elif key == "hako" and lr:
            order = ["auto", "on", "off"]
            cur = hk.get("set", "auto")
            i = order.index(cur) if cur in order else 0
            nxt = order[(i + (-1 if val == "LEFT" else 1)) % 3]
            msg = {"auto": "USB を抜くと箱庭になります (Wi-Fi は切れます。本体の A+C 長押しで抜けます)",
                   "on": "いつも箱庭にします (Wi-Fi はつながったまま・本体は眠りません)", "off": "箱庭を使いません"}[nxt]
            cfgcall({"hako": nxt}, msg)
        elif key == "chg" and lr:
            to = 180 if hk.get("chg") == 650 else 650
            cfgcall({"chg": to}, "充電を 650mA にしました (18350×2 ベースの時だけ)" if to == 650 else "充電を 180mA にしました")
        elif key == "hflip" and lr:
            cfgcall({"hflip": not hk.get("hflip")}, "箱庭で傾けた時の左右を入れ替えました")
        elif key == "pled" and lr:
            to = not hk.get("pled", 1)
            cfgcall({"pled": to}, "緑の電源LEDを点けます" if to else "緑の電源LEDを消します (電源OFF中も消えたままか見てください)")
        elif key == "ap" and lr:
            on = not (self.ap or {}).get("on") if val == "ENTER" else val == "RIGHT"
            def done(r):
                self.ap = r; self.dirty = True
                self.toast(f"イベントAP 入: {r.get('ssid')} (CPZ は家の Wi-Fi から外れます)" if r.get("on") else "イベントAP 切: 家の Wi-Fi に戻します", 5)
            self.ask("イベントAP", lambda: self.hub.call("POST", "/api/ap", {"on": on}, timeout=45), done,
                     start="切り替えています…")
        elif key == "teach" and val == "ENTER":
            self.ask("APを教える", lambda: self.hub.call("POST", "/api/ap/teach", {}, timeout=10),
                     lambda r: self.toast("本体に覚えさせました。家の Wi-Fi が無い所では15秒で CPZ につなぎます", 5))
        elif key == "stop" and val == "ENTER":
            self.stop()

    # ---- 歩く (v0.11、ファーム v0.12〜)。v0.13: 操作画面 / 設定 / プログラム に分けた
    WALK_KEYS = ["speed", "hold", "gait", "won", "woff", "face", "wchar", "walker", "servo", "strim", "sinv", "wmax",
                 "wdec", "wacc", "yawzero", "whead", "wheadth", "tcal", "thalf", "toff", "tscan", "tres1", "tres2", "pad"]

    def walk_items(self):
        w = (self.hub.st.get("dev") or {}).get("walk")
        if w is None:
            return [("歩行", "要ファーム v0.12")]
        pin = w.get("pin", -1)
        rows = {"speed": ("↑↓で出す速さ", f"{self.walk['set']}%"),
                "hold": ("↑↓の操作", "押してる間" if self.walk_hold else "押したら続く"),
                "gait": ("歩き方", ("刻む" if w.get("pon") and w.get("poff") else "なめらか") if "pon" in w else "要v0.13.4"),
                "won": ("刻む: 動く時間", f"{w['pon'] / 1000:.1f}秒" if "pon" in w else "-"),
                "woff": ("刻む: 休む時間", f"{w['poff'] / 1000:.1f}秒" if "poff" in w else "-"),
                "face": ("顔 (操作画面で 1〜7)", WALK_FACES[self.walk["face"] % len(WALK_FACES)]),
                "wchar": ("おまかせの顔", ("箱庭のキャラ" if w.get("wchar") else "スタックチャン") if "wchar" in w else "要v0.13"),
                "walker": ("歩くロボット", "入 (Grove 5V)" if w.get("walker") else "切"),
                "servo": ("サーボの GPIO", "なし" if pin < 0 else f"G{pin}"),
                "strim": ("中立の補正", f"{w.get('trim', 0):+d}µs"),
                "sinv": ("前後", "入れ替え" if w.get("inv") else "そのまま"),
                "wmax": ("速さの上限", f"{w.get('max', 60)}%"),
                "wdec": ("止まる時のゆっくり", f"{w['dec'] / 1000:.1f}秒" if "dec" in w else "要v0.13.3"),
                "wacc": ("動き出しのゆっくり", f"{w['acc'] / 1000:.1f}秒" if "acc" in w else "要v0.13.3"),
                "yawzero": ("向きを0に", "ENTER"),
                "whead": ("まっすぐ補正", (("入" + (f" 直した{w['hfixes']}回" if w.get("hfixes") else "")) if w.get("head") else "切")
                          if "head" in w else "要v0.13.6"),
                "wheadth": ("補正を始めるずれ", f"{w.get('hth', 10)}°" if "hth" in w else "-"),
                "tcal": ("旋回の自動調整", self.cal_label(w)),
                "thalf": ("旋回の片道", (f"{w.get('thalf', 350)}ms" + (f" 当たり{w['tgood']:.0f}°" if "tgood" in w else ""))
                          if "thalf" in w else "-"),
                "toff": ("左右の当たりの距離", (f"{w['toff']}ms (ENTERで消す)" if w.get("toff", -9999) > -9999 else "まだ")
                         if "toff" in w else "要v0.13.9"),
                "tscan": ("旋回スキャン 片道", self.scan_label(w)),
                "pad": ("アケコン (ENTERで設定)", self.pad_label()),
                "tres1": ("結果 1〜4 (°、+は左回り)", self.scan_res(w, 0)),
                "tres2": ("結果 5〜8", self.scan_res(w, 4))}
        return [rows[k] for k in self.WALK_KEYS]

    def pad_label(self):
        pd = self.hub.st.get("pad")
        if pd is None:
            return "要ハブ v0.13.7"
        return (pd.get("name") or "つながっている")[:14] if pd.get("connected") else "未接続"

    def cal_label(self, w):
        c = w.get("cal")
        if c is None:
            return "要v0.14"
        st = c.get("st", 0)
        if st == 1:
            sc = w.get("scan") or {}
            return f"調整中 {min(3, c.get('i', 0) + 1)}/3 ({sc.get('n', 0)}/8)"
        if not w.get("gyro", 1) or st == 4:
            return "ジャイロなし"
        return {2: "済み ENTERでやり直し", 3: "中止 ENTERでやり直し", 5: "回れる片道なし"}.get(
            st, "済み" if c.get("saved") else "未調整 ENTERで開始")

    def scan_label(self, w):
        sc = w.get("scan")
        if sc is None:
            return "要v0.13.5"
        if sc.get("st") == 1:
            return f"測定中 {sc.get('n', 0)}/8"
        return f"{self.scan_half}ms ENTERで開始"

    def scan_res(self, w, i0):
        sc = w.get("scan") or {}
        r = sc.get("r") or []
        n = sc.get("n", 0) if sc.get("st") == 1 else (8 if sc.get("st") == 2 else sc.get("n", 0))
        if not r or not n:
            return "-"
        return " ".join(f"{r[i]:+.0f}" if i < n else "…" for i in range(i0, i0 + 4))

    def r_walk(self):
        return {"ctl": self.r_walk_ctl, "set": self.r_walk_set, "prog": self.r_walk_prog,
                "edit": self.r_walk_edit, "pad": self.r_walk_pad}[self.walk_view]()

    # 操作画面: 操作だけを大きく見せる
    def r_walk_ctl(self):
        img, d = self.frame("歩く", "↑↓歩く ←→回る SPC止 英字ｷｰ TAB設定 P")
        dv = self.hub.st.get("dev") or {}
        w = dv.get("walk") or {}
        sp = self.walk["speed"]
        run = self.prog_run
        # 左: 十字 (↑ 前 / ↓ 後 / 真ん中 止)
        cx, cy = 52, 86
        def arrow(up, on):
            col = OKC if on else (64, 68, 82)
            s = -1 if up else 1
            y0 = cy + s * 18
            d.polygon([(cx, y0 + s * 30), (cx - 26, y0 + s * 6), (cx - 11, y0 + s * 6), (cx - 11, y0),
                       (cx + 11, y0), (cx + 11, y0 + s * 6), (cx + 26, y0 + s * 6)], fill=col)
        turning = bool(self.walk.get("turn")) and sp != 0
        arrow(True, sp > 0 and not turning); arrow(False, sp < 0 and not turning)
        for sx, on in ((-1, turning and sp > 0), (1, turning and sp < 0)):      # ◀ 左旋回 / ▶ 右旋回
            col = OKC if on else (64, 68, 82)
            tx = cx + sx * 40
            d.polygon([(tx + sx * 8, cy), (tx - sx * 6, cy - 12), (tx - sx * 6, cy + 12)], fill=col)
        d.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill=(120, 40, 40) if not sp else (40, 42, 52),
                  outline=(200, 90, 90) if not sp else (90, 94, 108), width=2)
        d.text((cx - self.font_t.getlength("止") / 2, cy - 6), "止", fill=FG, font=self.font_t)
        d.text((cx - 48, 140), ("押してる間" if self.walk_hold else "押したら続く") + f" {self.walk['set']}%",
               fill=SUB, font=self.font_t)
        # 真ん中: いまの速さ (本体が実際に出している % = ランプ込み) と向き
        out = w.get("out", sp) if isinstance(w.get("out"), int) else sp
        bx0, by0, bx1, by1 = 112, 26, 128, 116
        d.rectangle((bx0, by0, bx1, by1), outline=(70, 74, 88))
        mid = (by0 + by1) // 2
        d.line((bx0 - 3, mid, bx1 + 3, mid), fill=(90, 94, 108))
        if out:
            h = int((by1 - by0) / 2 * min(100, abs(out)) / 100)
            d.rectangle((bx0 + 2, mid - h if out > 0 else mid, bx1 - 2, mid if out > 0 else mid + h),
                        fill=OKC if out > 0 else ACC)
        d.text((bx0 - 2, by1 + 2), f"{out:+d}%", fill=FG, font=self.font_t)
        # 向き (ジャイロ)
        ccx, ccy, cr = 168, 60, 26
        d.ellipse((ccx - cr, ccy - cr, ccx + cr, ccy + cr), outline=(70, 74, 88), width=2)
        yaw = float(w.get("yaw", 0) or 0)
        a = math.radians(-yaw)
        d.line((ccx, ccy, ccx + (cr - 5) * math.sin(a), ccy - (cr - 5) * math.cos(a)), fill=ACC, width=3)
        d.ellipse((ccx - 3, ccy - 3, ccx + 3, ccy + 3), fill=ACC)
        d.text((ccx - 22, ccy + cr + 3), f"向き {yaw:+.0f}°", fill=SUB, font=self.font_t)
        state = (run["p"]["name"] if run else ("左へ回る" if sp > 0 else "右へ回る") if self.walk.get("turn") and sp
                 else "前進" if sp > 0 else "後退" if sp < 0 else "停止中")
        if w.get("hfix"):
            state = "向きを直し中"
        elif self.walk.get("turn") and sp and "tlock" in w:
            state += "" if w.get("tlock") else " (位相を探し中)"
        d.text((140, 112), self.ellipsize(state, 70, self.font_s), fill=FG, font=self.font_s)
        bv = dv.get("batt")
        if isinstance(bv, int) and bv > 0:
            d.text((140, 128), f"電池 {dv.get('lvl', '?')}%", fill=SUB, font=self.font_t)
        if w.get("pin", -1) < 0 or not w.get("walker"):
            d.text((140, 140), "TABで設定を", fill=NGC, font=self.font_t)
        elif "gyro" in w and not w.get("gyro"):              # v0.14.0: ジャイロが死んだ → 前後だけ
            d.text((140, 140), "ジャイロなし: 前後のみ", fill=NGC, font=self.font_t)
        # 右: プログラム (キー + 名前)。動いているものは進み具合
        x0, y = 212, 22
        d.text((x0, y), "プログラム", fill=ACC, font=self.font_t); y += 13
        for i, p in enumerate(self.progs[:8]):
            on = run is not None and run["i"] == i
            if on:
                d.rectangle((x0 - 2, y - 1, LCD_W - 2, y + 13), fill=(44, 33, 12))
            d.rounded_rectangle((x0, y, x0 + 13, y + 12), 2, fill=(52, 56, 70) if not on else ACC)
            d.text((x0 + 3, y), p["key"], fill=FG if not on else (20, 20, 20), font=self.font_t)
            d.text((x0 + 18, y), self.ellipsize(p["name"], LCD_W - x0 - 22, self.font_t), fill=FG, font=self.font_t)
            y += 15
            if on:
                frac = min(1.0, (time.time() - run["t0"]) / max(0.1, run["total"]))
                d.rectangle((x0, y - 3, x0 + int((LCD_W - 4 - x0) * frac), y - 2), fill=ACC)
        if self.walk_err:
            d.text((4, LCD_H - BOT_H - 13), self.ellipsize(self.walk_err, LCD_W - 8, self.font_t), fill=NGC, font=self.font_t)
        self.toast_draw(img)
        return img

    def r_walk_set(self):
        img, d = self.frame("歩く: 設定", "↑↓項目 ←→変更 ESC 操作画面へ")
        items = self.walk_items()
        self.list_draw(d, items, self.walk_i if len(items) > 1 else 0, LCD_W - 4, top=22, row=16)
        self.toast_draw(img)
        return img

    # プログラム一覧
    def r_walk_prog(self):
        img, d = self.frame("歩く: プログラム", "↑↓選ぶ ENTER編集 R試す N新規 BS消す ESC")
        items = [(f"{p['key']}  {p['name']}", self.prog_summary(p)) for p in self.progs] or [("(なし)", "N で作る")]
        self.list_draw(d, items, min(self.prog_i, len(items) - 1), LCD_W - 4, top=22, row=16)
        self.toast_draw(img)
        return img

    @staticmethod
    def step_word(s):
        return "左旋回" if s > 100 else "右旋回" if s < -100 else "前" if s > 0 else "後" if s < 0 else "止"

    def prog_summary(self, p):
        st = "+".join(f"{self.step_word(s)}{t:.1f}" for s, t in p["steps"])
        return (st + (f" ×{p['rep']}" if p.get("rep", 1) > 1 else ""))[:22]

    def edit_rows(self):
        p = self.edit
        rows = [("名前 (文字を打つ)", p["name"] + ("_" if self.edit_row == 0 else "")),
                ("キー", p["key"]), ("くりかえし", f"{p['rep']}回")]
        for k, (s, t) in enumerate(p["steps"]):
            sel = self.edit_row == 3 + k
            sv = self.step_word(s) if abs(s) > 100 else f"{self.step_word(s)}{abs(s)}%"
            tv = f"{t:.1f}秒"
            if sel:
                sv, tv = (f"[{sv}]", tv) if self.edit_field == 0 else (sv, f"[{tv}]")
            rows.append((f"{k + 1}. 動き", f"{sv}  {tv}"))
        rows.append(("▶ 試す", "ENTER"))
        return rows

    def r_walk_edit(self):
        r = self.edit_row
        if r == 0:
            hint = "文字を打つ BS消す ↑↓移動 ESC保存"
        elif 3 <= r < 3 + len(self.edit["steps"]):
            hint = "←→変更 ENTER速さ/時間 +足す -消す ESC保存"
        else:
            hint = "↑↓移動 ←→変更 ESC保存して戻る"
        img, d = self.frame("プログラム編集", hint)
        self.list_draw(d, self.edit_rows(), r, LCD_W - 4, top=22, row=16)
        self.toast_draw(img)
        return img

    # ---- アケコン (hub v0.13.7〜): ボタンを押して覚えさせる
    def r_walk_pad(self):
        pd = self.hub.st.get("pad") or {}
        learning = pd.get("learn")
        img, d = self.frame("アケコン", "ENTERで覚える→アケコンのボタンを押す BS消す ESC")
        head = (pd.get("name") or "未接続") + (f"  レバー:{'十字' if pd.get('lever') == 'hat' else 'スティック'}" if pd.get("lever") else "")
        d.text((4, 20), self.ellipsize(head, LCD_W - 8, self.font_t), fill=OKC if pd.get("connected") else NGC, font=self.font_t)
        mp = pd.get("map") or {}
        progs = self.progs
        items = []
        for k, a in enumerate(pd.get("actions") or []):
            label = a["label"]
            if a["id"].startswith("prog"):
                i = int(a["id"][4:]) - 1
                label += f" ({progs[i]['name']})" if i < len(progs) else " (なし)"
            v = "押して…" if learning == a["id"] else (f"ボタン {mp[a['id']]}" if a["id"] in mp else "-")
            items.append((label, v))
        if "cmd" in pd:                                  # ハブ v0.14.0: コマンド入力 (最後の行)
            items.append(("コマンド技 236波動/623昇竜", "入" if pd.get("cmd") else "切"))
        if items:
            self.list_draw(d, items, min(self.pad_i, len(items) - 1), LCD_W - 4, top=36, row=15)
        d.text((4, LCD_H - BOT_H - 13), self.ellipsize("レバー: 上下=前後 左右=その場旋回 (覚えさせ不要)", LCD_W - 8, self.font_t),
               fill=SUB, font=self.font_t)
        self.toast_draw(img)
        return img

    def k_walk_pad(self, kind, val):
        pd = self.hub.st.get("pad") or {}
        acts = [a["id"] for a in (pd.get("actions") or [])]
        if val == "ESC":
            if pd.get("learn"):
                self.ask("アケコン", lambda: self.hub.call("POST", "/api/pad/learn", {"action": None}))
            self.walk_view = "set"; return
        if not acts:
            return
        if "cmd" in pd:
            acts = acts + ["_cmd"]
        if val in ("UP", "DOWN", "TAB"):
            self.pad_i = (self.pad_i + (-1 if val == "UP" else 1)) % len(acts); return
        a = acts[self.pad_i % len(acts)]
        if a == "_cmd":
            if val in ("ENTER", "LEFT", "RIGHT"):
                on = not pd.get("cmd")
                self.ask("アケコン", lambda: self.hub.call("POST", "/api/pad/cmd", {"on": on}),
                         lambda r: self.toast("レバー↓↘→+ボタン=波動拳 / →↓↘+ボタン=昇竜拳" if on else "コマンド技を切りました", 4))
            return
        if val == "ENTER":
            if not pd.get("connected"):
                self.toast("アケコンが見つかりません (CPZ に USB で挿す)", 3, ok=False); return
            self.ask("アケコン", lambda: self.hub.call("POST", "/api/pad/learn", {"action": a}),
                     lambda r: self.toast("アケコンのボタンを押してください", 3))
        elif val == "BS":
            self.ask("アケコン", lambda: self.hub.call("POST", "/api/pad/clear", {"action": a}))

    # ---- プログラムの保存と実行
    def save_progs(self):
        c = load_cfg(); c["wprogs"] = self.progs; save_cfg(c)

    def prog_start(self, i):
        p = self.progs[i]
        total = sum(t for _, t in p["steps"]) * max(1, p.get("rep", 1))
        now = time.time()
        self.walk_hold_code = None
        self.prog_run = {"i": i, "p": p, "si": 0, "loop": 0, "t_end": now + p["steps"][0][1], "t0": now, "total": total}
        self.step_send(int(p["steps"][0][0]))

    def prog_stop(self, send=True):
        if self.prog_run is not None:
            self.prog_run = None
            if send:
                self.walk_send(0)

    def prog_tick(self, now):
        r = self.prog_run
        if r is None or now < r["t_end"]:
            return
        p = r["p"]
        r["si"] += 1
        if r["si"] >= len(p["steps"]):
            r["si"] = 0; r["loop"] += 1
            if r["loop"] >= max(1, p.get("rep", 1)):
                self.prog_stop(); self.dirty = True
                return
        s, t = p["steps"][r["si"]]
        r["t_end"] = now + t
        self.step_send(int(s)); self.dirty = True

    def step_send(self, s):
        if abs(s) > 100:
            self.walk_send(100 if s > 0 else -100, turn=True)
        else:
            self.walk_send(s)

    def walk_send(self, speed=None, turn=None):
        """hub へ速さを頼む (待たない。裏で送る)。turn=True はその場旋回 (+ 左 / − 右)"""
        if speed is not None:
            self.walk["speed"] = speed
            self.walk["turn"] = bool(turn) and speed != 0
        elif turn is not None:
            self.walk["turn"] = bool(turn)
        body = {"speed": self.walk["speed"], "face": self.walk["face"], "turn": bool(self.walk.get("turn"))}
        self.walk_sent = time.time()

        def run():
            try:
                self.hub.call("POST", "/api/walk", body, timeout=1.5)
                self.walk_err = None
            except RuntimeError as e:
                self.walk_err = str(e)
            self.dirty = True
        threading.Thread(target=run, daemon=True).start()

    def walk_stop(self):
        self.prog_stop(send=False)
        if self.walk["speed"] or time.time() - self.walk_sent < 3:
            self.walk_send(0)

    def k_walk(self, kind, val):
        return {"ctl": self.k_walk_ctl, "set": self.k_walk_set, "prog": self.k_walk_prog,
                "edit": self.k_walk_edit, "pad": self.k_walk_pad}[self.walk_view](kind, val)

    def k_walk_ctl(self, kind, val):
        if val == "ESC":
            self.walk_stop(); self.mode = M_HOME
            return
        if val in ("UP", "DOWN"):
            self.prog_stop(send=False)
            self.walk_hold_code = self.cur_code if self.walk_hold else None   # 離したら止める (run で見る)
            self.walk_send(self.walk["set"] if val == "UP" else -self.walk["set"]); return
        if val in ("LEFT", "RIGHT"):                    # v0.13.2: その場旋回 (ファーム v0.13.6〜)
            self.prog_stop(send=False)
            self.walk_hold_code = self.cur_code if self.walk_hold else None
            self.walk_send(100 if val == "LEFT" else -100, turn=True); return
        if (kind == "CHAR" and val == " ") or val == "BS":
            self.prog_stop(send=False); self.walk_hold_code = None
            self.walk_send(0); return
        if val == "TAB":
            self.walk_stop(); self.walk_view = "set"; return
        if kind == "CHAR" and val in "pP":
            self.walk_stop(); self.walk_view = "prog"; return
        if kind == "CHAR" and val in "1234567":
            self.walk["face"] = int(val) - 1; self.walk_send(); return
        if kind == "CHAR":
            for i, p in enumerate(self.progs):
                if p["key"].lower() == val.lower():
                    self.prog_start(i); return
            if val.lower() in self.FX_KEYS:               # v0.13.9: Z 波動 / X 昇竜 (プログラムに同じキーがあればそちら)
                self.fx_play(self.FX_KEYS[val.lower()]); return

    FX_KEYS = {"z": "hadou", "x": "shoryu"}

    def fx_play(self, name):
        if self.hub.st.get("fx") is None:
            self.toast("ハブを v0.13.9 以上にしてください", 3, ok=False); return
        def done(r):
            if not r.get("sound"):
                self.toast(f"音がありません: ~/.config/hexa-matrix/sounds/{name}.wav", 4, ok=False)
        threading.Thread(target=lambda: self._fx_call(name, done), daemon=True).start()

    def _fx_call(self, name, done):
        try:
            r = self.hub.call("POST", "/api/fx", {"name": name}, timeout=3)
            done(r or {})
        except Exception as e:
            self.toast(str(e), 3, ok=False)

    def k_walk_set(self, kind, val):
        if val == "ESC":
            self.walk_view = "ctl"; return
        if val in ("UP", "DOWN", "TAB"):
            n = len(self.WALK_KEYS)
            self.walk_i = (self.walk_i + (-1 if val == "UP" else 1)) % n; return
        key = self.WALK_KEYS[self.walk_i]
        w = (self.hub.st.get("dev") or {}).get("walk") or {}
        if val not in ("LEFT", "RIGHT", "ENTER"):
            return
        step = -1 if val == "LEFT" else 1
        cfgcall = lambda body, msg=None: self.ask("歩行の設定", lambda: self.hub.call("POST", "/api/device/config", body),
                                                  (lambda r: self.toast(msg, 3)) if msg else None)
        if key == "hold":
            self.walk_hold = not self.walk_hold
            c = load_cfg(); c["whold"] = self.walk_hold; save_cfg(c)
        elif key == "speed":
            self.walk["set"] = max(10, min(100, self.walk["set"] + step * 5))
            c = load_cfg(); c["wspeed"] = self.walk["set"]; save_cfg(c)
        elif key == "face":
            self.walk["face"] = (self.walk["face"] + step) % len(WALK_FACES); self.walk_send()
        elif key == "wchar":
            on = not w.get("wchar")
            cfgcall({"wchar": on}, "おまかせの顔を箱庭のキャラにしました" if on else "おまかせの顔をスタックチャンにしました")
        elif key == "walker":
            on = not w.get("walker")
            cfgcall({"walker": on}, "歩くロボットにしました (電池でも箱庭に入りません・Grove 5V 入)" if on else "歩くロボットをやめました")
        elif key == "servo":
            cur = w.get("pin", -1)
            i = SERVO_PINS.index(cur) if cur in SERVO_PINS else 0
            cfgcall({"servo": SERVO_PINS[(i + step) % len(SERVO_PINS)]})
        elif key == "strim":
            cfgcall({"strim": int(w.get("trim", 0)) + step * 5, "strimtest": True})   # 変えたら中立を2秒出して確かめる
        elif key == "sinv":
            cfgcall({"sinv": not w.get("inv")}, "前後を入れ替えました")
        elif key == "wmax":
            cfgcall({"wmax": max(10, min(100, int(w.get("max", 60)) + step * 10))})
        elif key == "gait" and "pon" in w:                # v0.13.4: なめらか ⇔ 刻む (ボタン連打と同じ動き)
            if w.get("pon") and w.get("poff"):
                c = load_cfg(); c["wpulse"] = [w["pon"], w["poff"]]; save_cfg(c)
                cfgcall({"won": 0, "woff": 0}, "なめらかに続けて歩きます")
            else:
                on, off = (load_cfg().get("wpulse") or [500, 300])
                cfgcall({"won": on, "woff": off}, f"刻んで歩きます (動く {on / 1000:.1f}秒・休む {off / 1000:.1f}秒)")
        elif key in ("won", "woff") and "pon" in w:
            cur = int(w.get("pon" if key == "won" else "poff", 0))
            cfgcall({key: max(0, min(3000, (cur + 50) // 100 * 100 + step * 100))})
        elif key in ("wdec", "wacc") and (key[1:] in w):     # v0.13.3: 0.1 秒きざみ (0〜3 秒)
            cur = int(w.get(key[1:], 0))
            cfgcall({key: max(0, min(3000, (cur + 50) // 100 * 100 + step * 100))})
        elif key == "yawzero":
            cfgcall({"yawzero": True}, "向きを 0 にしました")
        elif key == "whead" and "head" in w:             # v0.13.6: まっすぐ補正
            on = not w.get("head")
            cfgcall({"whead": on}, f"まっすぐ補正: 向きが {w.get('hth', 10)}° ずれたら止まって戻します" if on else "まっすぐ補正を切りました")
        elif key == "wheadth" and "hth" in w:
            cfgcall({"wheadth": max(3, min(60, int(w.get("hth", 10)) + step * (5 if int(w.get("hth", 10)) >= 10 else 1)))})
        elif key == "tcal" and "cal" in w and val == "ENTER":   # v0.14.0: 旋回の自動調整
            if (w.get("cal") or {}).get("st") == 1:
                cfgcall({"tcal": False}, "自動調整をやめました")
            elif not w.get("gyro", 1):
                self.toast("ジャイロが読めないので調整できません", 3, ok=False)
            else:
                cfgcall({"tcal": True}, "床に置いて約2分。片道を3通り試して、左右とも一番回れるのを選びます (歩く操作でやめる)")
        elif key == "thalf" and "thalf" in w:
            cfgcall({"thalf": max(100, min(800, int(w.get("thalf", 350)) + step * 50))})
        elif key == "pad" and val == "ENTER":
            if self.hub.st.get("pad") is None:
                self.toast("ハブを v0.13.7 以上にしてください", 3, ok=False)
            else:
                self.pad_i = 0; self.walk_view = "pad"
        elif key == "toff" and "toff" in w and val == "ENTER":   # v0.13.9: 覚えた左右の距離を消す (組み直した時)
            cfgcall({"toffclr": True}, "左右の当たりの距離を消しました (次の旋回で覚え直します)")
        elif key == "tscan" and "scan" in w:             # v0.13.5: 旋回スキャン
            if val == "ENTER":
                if (w.get("scan") or {}).get("st") == 1:
                    cfgcall({"tscan": 0}, "スキャンをやめました")
                else:
                    cfgcall({"tscan": self.scan_half}, "床に置いて約30秒。往復して回るか測ります (歩く操作でやめる)")
            else:
                self.scan_half = max(100, min(800, self.scan_half + step * 50))
                c = load_cfg(); c["wscanhalf"] = self.scan_half; save_cfg(c)

    def k_walk_prog(self, kind, val):
        n = len(self.progs)
        if val == "ESC":
            self.prog_stop(); self.walk_view = "ctl"; return
        if val in ("UP", "DOWN") and n:
            self.prog_i = (self.prog_i + (-1 if val == "UP" else 1)) % n; self.del_armed = False; return
        if kind == "CHAR" and val in "nN":
            used = {p["key"] for p in self.progs}
            free = [k for k in PROG_KEYS if k not in used]
            if not free:
                self.toast("キーが空いていません", 3, ok=False); return
            self.progs.append({"name": "", "key": free[0], "rep": 1, "steps": [[40, 1.0]]})
            self.save_progs(); self.prog_i = n
            self.edit_open(); return
        if not n:
            return
        if val == "ENTER":
            self.edit_open(); return
        if kind == "CHAR" and val in "rR":
            self.prog_start(self.prog_i); return
        if val == "BS":
            if not self.del_armed:
                self.del_armed = True; self.toast("もう一度 BS で消します", 3); return
            self.progs.pop(self.prog_i); self.save_progs()
            self.prog_i = max(0, min(self.prog_i, len(self.progs) - 1)); self.del_armed = False
            self.toast("消しました", 2)

    def edit_open(self):
        p = self.progs[self.prog_i]
        self.edit = {"name": p["name"], "key": p["key"], "rep": p.get("rep", 1), "steps": [list(s) for s in p["steps"]]}
        self.edit_row = 0; self.edit_field = 0
        self.walk_view = "edit"

    def edit_commit(self):
        self.progs[self.prog_i] = {"name": self.edit["name"] or f"prog{self.prog_i + 1}", "key": self.edit["key"],
                                   "rep": self.edit["rep"], "steps": [list(s) for s in self.edit["steps"]]}
        self.save_progs()

    def k_walk_edit(self, kind, val):
        e = self.edit
        nrow = 3 + len(e["steps"]) + 1
        r = self.edit_row
        if val == "ESC":
            self.prog_stop(); self.edit_commit(); self.walk_view = "prog"; return
        if val in ("UP", "DOWN", "TAB"):
            self.edit_row = (r + (-1 if val == "UP" else 1)) % nrow; self.edit_field = 0; return
        step = -1 if val == "LEFT" else 1 if val == "RIGHT" else 0
        if r == 0:                                        # 名前: 文字を打つ
            if kind == "CHAR" and len(e["name"]) < 16:
                e["name"] += val
            elif val == "BS":
                e["name"] = e["name"][:-1]
            return
        if r == 1 and step:                               # キー: ほかのプログラムが使っていないものだけ
            used = {p["key"] for i, p in enumerate(self.progs) if i != self.prog_i}
            free = [k for k in PROG_KEYS if k not in used]
            i = free.index(e["key"]) if e["key"] in free else 0
            e["key"] = free[(i + step) % len(free)]; return
        if r == 2 and step:
            e["rep"] = max(1, min(20, e["rep"] + step)); return
        if 3 <= r < 3 + len(e["steps"]):
            k = r - 3
            if val == "ENTER":
                self.edit_field ^= 1; return
            if kind == "CHAR" and val == "+":
                e["steps"].insert(k + 1, list(e["steps"][k])); self.edit_row += 1; return
            if kind == "CHAR" and val == "-" and len(e["steps"]) > 1:
                e["steps"].pop(k); self.edit_row = min(self.edit_row, 3 + len(e["steps"]) - 1); return
            if step and self.edit_field == 0:            # −110 右旋回 / −100〜100 歩く / 110 左旋回
                e["steps"][k][0] = max(-110, min(110, int(e["steps"][k][0]) + step * 10))
            elif step:
                e["steps"][k][1] = round(max(0.1, min(10.0, e["steps"][k][1] + step * 0.1)), 1)
            return
        if r == nrow - 1 and val == "ENTER":             # 試す (保存してから)
            self.edit_commit(); self.prog_start(self.prog_i)

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
            if self.mode == M_WALK:
                self.prog_tick(now)                    # プログラム: 次の動きへ
                if self.prog_run is not None:
                    self.dirty = True                  # 進み具合のバー
            if self.mode == M_WALK and self.walk["speed"]:
                held = getattr(self.keys, "held", None)
                if self.walk_hold_code is not None and held is not None and self.walk_hold_code not in held:
                    self.walk_hold_code = None; self.walk_send(0); self.dirty = True     # 離した → 止まる
                elif now - self.walk_sent > 0.5:
                    self.walk_send()                   # 頼み直し (hub は 1.5 秒来ないと止める)
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
        app = App(Hub(a.hub), keys, fb)
        try:
            reason = app.run()
        finally:
            if app.walk["speed"]:
                try:
                    app.hub.call("POST", "/api/walk/stop", {}, timeout=1.0)   # 終わる時は必ず止める
                except RuntimeError:
                    pass
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
