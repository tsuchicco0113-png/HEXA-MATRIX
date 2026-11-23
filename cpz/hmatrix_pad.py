"""HEXA MATRIX hub: アケコン / ゲームパッドで歩かせる (hub v0.13.7〜)

CPZ に USB で挿したアケコン (Linux の joystick。例: Brook P5 mini = "ZEROPLUS P3 Wired Gamepad") を読み、
今の WALK (hub の Walker) に変えて送る。アプリを開いていなくても動く。

- レバー上 / 下 = 前進 / 後退 (倒している間だけ)、左 / 右 = その場で左 / 右に旋回。斜めは前後を優先
  レバーは十字キー (HAT) でもスティック (X/Y 軸) でもよい
- ボタンは機種ごとに番号が違うので、CPZ アプリ (歩く → 設定 → アケコン) で「押して覚えさせる」
  割り当ては ~/.config/hexa-matrix/pad.json に保存
- プログラム 1〜4 は CPZ アプリで作ったプログラム (app.json の wprogs) の上から 1〜4 番目
- 抜いたら止める。2 秒ごとに挿し直しを探す
"""
from __future__ import annotations

import fcntl
import json
import os
import select
import struct
import threading
import time

EV_FMT = "llHHi"
EV_SIZE = struct.calcsize(EV_FMT)
EV_KEY, EV_ABS = 1, 3
ABS_X, ABS_Y, ABS_HAT0X, ABS_HAT0Y = 0, 1, 16, 17

CFG_DIR = os.path.join(os.path.expanduser("~"), ".config", "hexa-matrix")
PAD_CFG = os.path.join(CFG_DIR, "pad.json")
APP_CFG = os.path.join(CFG_DIR, "app.json")

ACTIONS = [
    ("prog1", "プログラム 1"), ("prog2", "プログラム 2"), ("prog3", "プログラム 3"), ("prog4", "プログラム 4"),
    ("face_next", "顔 次へ"), ("face_prev", "顔 前へ"), ("speed", "速さ 切り替え"), ("stop", "止める"),
    ("say", "ことば 流す"),                                                    # v0.14.1 ハブ: CPZ の「ことば」で作った文字
    ("dev1", "本体 1番"), ("dev2", "本体 2番"), ("dev3", "本体 3番"), ("dev4", "本体 4番"),   # 本体に保存した番組
]
# 技 (波動拳・昇竜拳・竜巻旋風脚) はボタン割り当てではなくコマンド入力で出す (COMMANDS)
SPEEDS = [40, 60, 80, 100]
# v0.14.0 ハブ: コマンド入力 (テンキー表記、右向き)。ボタンを押した瞬間に、直前のレバーの動きを見る。
#   623 は 236 を含みやすいので先に見る。どのボタンでも出る (割り当てた動きより優先)
COMMANDS = [("shoryu", (6, 2, 3)), ("hadou", (2, 3, 6)), ("tatsumaki", (2, 1, 4))]
CMD_WINDOW = 0.6        # レバーを入れ始めてからボタンまで (秒)
SPIN_SEC = 2.0          # 竜巻旋風脚: その場で右に回る秒数 (pad.json の "spin" で変えられる、0 で回らない)
CMD_DELAY = 0.12        # コマンド入力を使う時は、レバーを入れてこれだけ続いてから歩き出す (入力中にピクッと動かない)
N_FACES = 7          # アプリの WALK_FACES と同じ (0 = おまかせ … 6 = 箱庭のキャラ)


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def find_pads(devices="/proc/bus/input/devices"):
    """joystick (js) を持つ入力デバイスの [(名前, /dev/input/eventN)]"""
    out = []
    try:
        text = open(devices, encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    for block in text.split("\n\n"):
        name, handlers = "", ""
        for ln in block.splitlines():
            if ln.startswith("N: Name="):
                name = ln.split("=", 1)[1].strip().strip('"')
            elif ln.startswith("H: Handlers="):
                handlers = ln.split("=", 1)[1]
        hs = handlers.split()
        ev = [h for h in hs if h.startswith("event")]
        if ev and any(h.startswith("js") for h in hs):
            out.append((name, "/dev/input/" + ev[0]))
    return out


def eviocgabs(code):
    return 0x80184540 + code          # _IOR('E', 0x40 + code, struct input_absinfo (6 x int32))


class Pad:
    def __init__(self, walker, before_walk=None, log=print, finder=find_pads, fx=None, say=None, dev_play=None):
        self.walker = walker
        self.say = say                          # v0.14.1: say(opt) CPZ から文字を流す
        self.dev_play = dev_play                # v0.14.1: dev_play(番号 0〜) 本体の番組を流す
        self.fx = fx                            # v0.13.9: fx(name) で音と絵を出す
        self.before_walk = before_walk          # 歩く前に呼ぶ (CPZ から流している絵を止める)
        self.log = log
        self.finder = finder
        self.cfg = _load(PAD_CFG)
        acts = dict(ACTIONS)
        self.map = {k: int(v) for k, v in (self.cfg.get("map") or {}).items() if isinstance(v, int) and k in acts}
        app = _load(APP_CFG)
        self.speed = int(self.cfg.get("speed") or app.get("wspeed") or 60)
        self.face = 0
        self.fd = None
        self.name = ""
        self.path = ""
        self.lever_kind = ""                    # "hat" / "stick"
        self.hx = self.hy = 0                   # 十字キー (−1 / 0 / 1)
        self.ax = {}                            # スティック: code -> (値, min, max)
        self.dir = (0, 0)                       # いま出している (前後, 旋回)
        self.sent = 0.0
        self.learn = None                       # 覚えさせ中の動き
        self.last_btn = None                    # 最後に押されたボタン (表示用)
        self.prog = None                        # 動いているプログラム
        self.err = None
        self.cmd = bool(self.cfg.get("cmd", True))   # コマンド入力 (236 / 623)
        self.hist = []                          # [(時刻, テンキー)] レバーの動き
        self.pend = None                        # (動き, 入れ始めた時刻) 歩き出し待ち
        self.cmd_lock = False                   # 技を出した後、レバーを戻すまで歩かない
        self.cmd_last = None
        self.spin_until = 0.0                   # 竜巻旋風脚で回っている間 (この時刻まで)
        self.lock = threading.Lock()
        self.stop_flag = False
        self.th = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.th.start()
        return self

    # ---- 状態 (hub の /api/status に載せる)
    def status(self):
        with self.lock:
            return {"connected": self.fd is not None, "name": self.name, "lever": self.lever_kind,
                    "map": dict(self.map), "learn": self.learn, "speed": self.speed, "face": self.face,
                    "last": self.last_btn, "running": (self.prog or {}).get("name"), "err": self.err,
                    "cmd": self.cmd, "cmd_last": self.cmd_last, "spin": self.spin_sec(),
                    "actions": [{"id": a, "label": l} for a, l in ACTIONS]}

    def set_learn(self, action):
        with self.lock:
            if action is not None and action not in dict(ACTIONS):
                raise RuntimeError("その動きはありません")
            self.learn = action
        return self.status()

    def spin_sec(self):
        try:
            return max(0.0, min(5.0, float(self.cfg.get("spin", SPIN_SEC))))
        except (TypeError, ValueError):
            return SPIN_SEC

    def set_spin(self, sec):
        with self.lock:
            self.cfg["spin"] = round(max(0.0, min(5.0, float(sec))) * 2) / 2   # 0〜5 秒、0.5 秒きざみ
            self._save()
        return self.status()

    def set_cmd(self, on):
        with self.lock:
            self.cmd = bool(on)
            self._save()
        return self.status()

    def clear(self, action):
        with self.lock:
            self.map.pop(action, None)
            self._save()
        return self.status()

    def _save(self):
        os.makedirs(CFG_DIR, exist_ok=True)
        self.cfg["map"] = self.map
        self.cfg["speed"] = self.speed
        self.cfg["cmd"] = self.cmd
        tmp = PAD_CFG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, ensure_ascii=False, indent=1)
        os.replace(tmp, PAD_CFG)

    # ---- 読む
    def _open(self):
        pads = self.finder()
        if not pads:
            return False
        name, path = pads[0]
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            self.err = f"{path} を開けません ({e.strerror})"
            return False
        self.fd, self.name, self.path, self.err = fd, name, path, None
        self.ax = {}
        for code in (ABS_X, ABS_Y):
            try:
                buf = bytearray(24)
                fcntl.ioctl(fd, eviocgabs(code), buf)
                val, mn, mx = struct.unpack_from("<iii", buf)
                if mx > mn:
                    self.ax[code] = [val, mn, mx]
            except OSError:
                pass
        self.log(f"pad: {name} ({path})")
        return True

    def _close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = None
        self.hx = self.hy = 0
        if self.dir != (0, 0) or self.prog:
            self.prog = None
            self._go(0, 0)                      # 抜けた → 止める

    def run(self):
        last_try = 0.0
        while not self.stop_flag:
            if self.fd is None:
                if time.time() - last_try > 2.0:
                    last_try = time.time()
                    self._open()
                if self.fd is None:
                    time.sleep(0.2)
                    continue
            try:
                r, _, _ = select.select([self.fd], [], [], 0.05)
                if r:
                    data = os.read(self.fd, EV_SIZE * 64)
                    if not data:
                        raise OSError("eof")
                    for i in range(0, len(data) - EV_SIZE + 1, EV_SIZE):
                        _, _, et, code, val = struct.unpack(EV_FMT, data[i:i + EV_SIZE])
                        self.event(et, code, val)
            except OSError:
                self.log("pad: 抜けました")
                self._close()
                continue
            self.tick(time.time())

    # ---- 入力 → 動き
    def event(self, et, code, val):
        if et == EV_ABS:
            if code == ABS_HAT0X:
                self.hx = (val > 0) - (val < 0); self.lever_kind = "hat"
            elif code == ABS_HAT0Y:
                self.hy = (val > 0) - (val < 0); self.lever_kind = "hat"
            elif code in self.ax:
                self.ax[code][0] = val
            return
        if et != EV_KEY or val != 1:
            return
        if self.learn is None and self.cmd and self.fx:      # コマンド技が入っていればそちらを出す
            now = time.time()
            self._rec(now, *self.lever())           # レバーと同時に押した時も入れる
            name = self.motion(now)
            if name:
                self.cmd_last = name
                self.hist = []; self.pend = None; self.cmd_lock = True; self.prog = None; self.spin_until = 0.0
                spin = self.spin_sec()
                if name == "tatsumaki" and spin > 0:
                    self.spin_until = now + spin
                    self._go(0, -1)                 # 右回り (旋回は + が左)
                elif self.dir != (0, 0):
                    self._go(0, 0)
                try:
                    self.fx(name)
                except Exception as e:
                    self.err = str(e)
                return
        with self.lock:
            self.last_btn = code
            if self.learn:
                for a, c in list(self.map.items()):     # 同じボタンは 1 つの動きにだけ
                    if c == code:
                        self.map.pop(a)
                self.map[self.learn] = code
                self.learn = None
                self._save()
                return
            act = next((a for a, c in self.map.items() if c == code), None)
        if act:
            self.do(act)

    def lever(self):
        """(前後 −1/0/1, 左右 −1/0/1)。上が前 (y は下向きが +)"""
        x, y = self.hx, self.hy
        if not x and not y:
            for code, (v, mn, mx) in self.ax.items():
                mid, half = (mn + mx) / 2, (mx - mn) / 2
                n = (v - mid) / half if half else 0
                if abs(n) > 0.5:
                    self.lever_kind = self.lever_kind or "stick"
                    if code == ABS_X:
                        x = 1 if n > 0 else -1
                    else:
                        y = 1 if n > 0 else -1
        return (-y, x)

    @staticmethod
    def numpad(fb, lr):
        """テンキー表記 (右向き): 8 上 / 2 下 / 6 右 / 4 左 / 5 中立"""
        return (1 if fb < 0 else 4 if fb == 0 else 7) + lr + 1

    def _rec(self, now, fb, lr):
        n = self.numpad(fb, lr)
        if not self.hist or self.hist[-1][1] != n:
            self.hist.append((now, n))
        while self.hist and now - self.hist[0][0] > 1.5:
            self.hist.pop(0)

    def motion(self, now):
        """直前 CMD_WINDOW 秒のレバーの動きから技を探す。無ければ None"""
        seq = [n for t, n in self.hist if now - t <= CMD_WINDOW]
        for name, pat in COMMANDS:
            i = 0
            for n in seq:
                if n == pat[i]:
                    i += 1
                    if i == len(pat):
                        return name
        return None

    def tick(self, now):
        if self.prog:
            self._prog_tick(now)
        fb, lr = self.lever()
        self._rec(now, fb, lr)
        if self.spin_until:                     # 竜巻旋風脚: 決めた時間だけ右に回る (レバーは見ない)
            if now >= self.spin_until:
                self.spin_until = 0.0
                self._go(0, 0)
            elif now - self.sent > 0.5:
                self._go(0, -1)
            return
        if fb or lr:
            self.prog = None                    # レバーを入れたらプログラムはやめる
        if self.prog:
            return
        want = (fb, 0) if fb else (0, -lr)      # 斜めは前後を優先。旋回は + が左 (レバー左 = lr −1)
        if self.cmd_lock:                       # 技の後: レバーを中立に戻すまで歩かない
            if want != (0, 0):
                return
            self.cmd_lock = False
        if self.cmd and self.fx and want != (0, 0) and want != self.dir:
            if not self.pend or self.pend[0] != want:
                self.pend = (want, now)         # 入れたばかり: 少し待つ (コマンド入力の途中かも)
            if now - self.pend[1] < CMD_DELAY:
                if self.dir != (0, 0):
                    self._go(0, 0)              # 前の動きは止める
                return
        self.pend = None
        if want != self.dir or (want != (0, 0) and now - self.sent > 0.5):
            self._go(*want)

    def _go(self, fb, turn):
        try:
            if fb:
                if self.before_walk:
                    self.before_walk()
                self.walker.set(self.speed * fb, self.face, turn=False)
            elif turn:
                if self.before_walk:
                    self.before_walk()
                self.walker.set(100 * turn, self.face, turn=True)
            elif self.dir != (0, 0) or self.prog is None:
                self.walker.stop()
            self.err = None
        except RuntimeError as e:
            self.err = str(e)
        self.dir = (fb, turn)
        self.sent = time.time()

    def do(self, act):
        if act == "say" or act.startswith("dev"):
            self.prog = None
            if self.dir != (0, 0):
                self._go(0, 0)                  # 歩いていたら止めてから (絵が届くと本体は顔をやめる)
            try:
                if act == "say":
                    opt = _load(APP_CFG).get("say_body")
                    if not opt or not str(opt.get("text") or "").strip():
                        raise RuntimeError("ことばがありません (CPZ アプリの「ことば」で一度流してください)")
                    if self.say:
                        self.say(opt)
                elif self.dev_play:
                    self.dev_play(int(act[3:]) - 1)
                self.err = None
            except Exception as e:
                self.err = str(e)
            return
        if act == "stop":
            self.prog = None
            self._go(0, 0)
        elif act == "speed":
            i = SPEEDS.index(self.speed) if self.speed in SPEEDS else 0
            self.speed = SPEEDS[(i + 1) % len(SPEEDS)]
            with self.lock:
                self._save()
        elif act in ("face_next", "face_prev"):
            self.face = (self.face + (1 if act == "face_next" else -1)) % N_FACES
            try:
                self.walker.set(None, self.face)
            except RuntimeError as e:
                self.err = str(e)
        elif act.startswith("prog"):
            progs = _load(APP_CFG).get("wprogs") or []
            i = int(act[4:]) - 1
            if i < len(progs) and progs[i].get("steps"):
                p = progs[i]
                self.prog = {"name": p.get("name") or act, "steps": p["steps"], "rep": max(1, int(p.get("rep", 1))),
                             "si": -1, "loop": 0, "t_end": 0.0}
                self._prog_tick(time.time())
            else:
                self.err = f"プログラム {i + 1} がありません (CPZ アプリで作ってください)"

    def _prog_tick(self, now):
        p = self.prog
        if now < p["t_end"]:
            if now - self.sent > 0.5:
                self._step(p["steps"][p["si"]][0])
            return
        p["si"] += 1
        if p["si"] >= len(p["steps"]):
            p["si"] = 0
            p["loop"] += 1
            if p["loop"] >= p["rep"]:
                self.prog = None
                self._go(0, 0)
                return
        s, t = p["steps"][p["si"]]
        p["t_end"] = now + float(t)
        self._step(s)

    def _step(self, s):
        s = int(s)
        if abs(s) > 100:                        # ±110 = その場旋回 (アプリと同じ)
            self._go(0, 1 if s > 0 else -1)
        elif s:
            try:
                if self.before_walk:
                    self.before_walk()
                self.walker.set(s, self.face, turn=False)
            except RuntimeError as e:
                self.err = str(e)
            self.dir = (1 if s > 0 else -1, 0)
            self.sent = time.time()
        else:
            self.walker.stop()
            self.dir = (0, 0)
            self.sent = time.time()
