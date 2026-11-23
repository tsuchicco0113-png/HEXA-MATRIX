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
]
SPEEDS = [40, 60, 80, 100]
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
    def __init__(self, walker, before_walk=None, log=print, finder=find_pads):
        self.walker = walker
        self.before_walk = before_walk          # 歩く前に呼ぶ (CPZ から流している絵を止める)
        self.log = log
        self.finder = finder
        self.cfg = _load(PAD_CFG)
        self.map = {k: int(v) for k, v in (self.cfg.get("map") or {}).items() if isinstance(v, int)}
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
                    "actions": [{"id": a, "label": l} for a, l in ACTIONS]}

    def set_learn(self, action):
        with self.lock:
            if action is not None and action not in dict(ACTIONS):
                raise RuntimeError("その動きはありません")
            self.learn = action
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

    def tick(self, now):
        if self.prog:
            self._prog_tick(now)
        fb, lr = self.lever()
        if fb or lr:
            self.prog = None                    # レバーを入れたらプログラムはやめる
        if self.prog:
            return
        want = (fb, 0) if fb else (0, -lr)      # 斜めは前後を優先。旋回は + が左 (レバー左 = lr −1)
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
