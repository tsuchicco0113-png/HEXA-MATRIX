"""エフェクト (v0.13.9 ハブ / ファーム v0.14.1〜): ボタン 1 つで「音 + CoreMatrix の 16x16 の絵」を出す。

  - 絵: ここで点を打って作る (オリジナルの気弾・突き上げ・HIT の絵)。ファームの FX (0x09) で送ると、
        歩いている顔の上に一瞬だけ重ねて出し、終わったら元の顔に戻る (歩くのは止めない)
  - 音: ~/.config/hexa-matrix/sounds/<名前>.wav (または .mp3) があれば CPZ のスピーカーで鳴らす。
        音のファイルはリポジトリに入れない (各自で置く)。wav は aplay、mp3 は mpg123 / ffplay があれば使う

名前: hadou (気弾)、shoryu (突き上げ)、tatsumaki (うず)。音のファイル名も同じ (hadou.wav / shoryu.wav / tatsumaki.wav)
"""
import math
import os
import shutil
import subprocess
import threading
import time

SOUND_DIR = os.path.expanduser("~/.config/hexa-matrix/sounds")
T_FX = 0x09

# ---------------------------------------------------------------- 16x16 の絵を作る道具
class Grid:
    def __init__(self):
        self.p = [[0] * 16 for _ in range(16)]

    def dot(self, x, y):
        x, y = int(round(x)), int(round(y))
        if 0 <= x < 16 and 0 <= y < 16:
            self.p[y][x] = 1

    def disc(self, cx, cy, r):
        for y in range(16):
            for x in range(16):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r + 0.3:
                    self.p[y][x] = 1

    def ring(self, cx, cy, r, w=0.6):
        for y in range(16):
            for x in range(16):
                d = math.hypot(x - cx, y - cy)
                if abs(d - r) <= w:
                    self.p[y][x] = 1

    def clear_disc(self, cx, cy, r):
        for y in range(16):
            for x in range(16):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r + 0.3:
                    self.p[y][x] = 0

    def line(self, x0, y0, x1, y1):
        n = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
        for i in range(n + 1):
            t = i / n
            self.dot(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)

    def rays(self, cx, cy, r0, r1, n, rot=0.0):
        for i in range(n):
            a = rot + i * 2 * math.pi / n
            self.line(cx + r0 * math.cos(a), cy + r0 * math.sin(a), cx + r1 * math.cos(a), cy + r1 * math.sin(a))

    def text(self, s, x, y):
        for ch in s:
            g = FONT3x5[ch]
            for j, row in enumerate(g):
                for i, c in enumerate(row):
                    if c == "#":
                        self.dot(x + i, y + j)
            x += len(g[0]) + 1

    def bytes(self):
        out = bytearray()
        for row in self.p:
            w = 0
            for x, v in enumerate(row):
                if v:
                    w |= 0x8000 >> x
            out += bytes((w >> 8, w & 0xFF))
        return bytes(out)


FONT3x5 = {"H": ["#.#", "#.#", "###", "#.#", "#.#"],
           "I": ["###", ".#.", ".#.", ".#.", "###"],
           "T": ["###", ".#.", ".#.", ".#.", ".#."],
           "!": ["#", "#", "#", ".", "#"]}


def _hit(burst=True):
    """HIT の決めゴマ: 真ん中に HIT、まわりに飛び散る線"""
    g = Grid()
    g.text("HIT!", 1, 6)
    if burst:
        for (x0, y0, x1, y1) in ((0, 0, 3, 3), (15, 0, 12, 3), (0, 15, 3, 12), (15, 15, 12, 12),
                                 (7.5, 0, 7.5, 3), (7.5, 15, 7.5, 12)):
            g.line(x0, y0, x1, y1)
    return g


def _hadou():
    """気弾: 手元でためる → 大きくなりながら右へ飛ぶ → 当たって弾ける → HIT"""
    fr = []
    g = Grid(); g.ring(3, 8, 1.6, 0.5); g.dot(3, 8); fr.append(g)                          # ためる
    g = Grid(); g.disc(4, 8, 2); g.rays(4, 8, 3, 4.2, 6, 0.3); fr.append(g)
    g = Grid(); g.disc(7, 8, 2.6); g.clear_disc(7.5, 8, 1); g.line(0, 7, 3, 7); g.line(1, 9, 4, 9); fr.append(g)   # 飛ぶ (尾)
    g = Grid(); g.disc(11, 8, 3); g.clear_disc(11.5, 8, 1.2); g.line(2, 6, 7, 7); g.line(1, 8, 7, 8); g.line(2, 10, 7, 9); fr.append(g)
    g = Grid(); g.disc(14, 8, 3.2); g.rays(14, 8, 3.5, 6, 8, 0.2); fr.append(g)            # 当たる
    g = Grid(); g.rays(8, 8, 2, 8, 12, 0.1); g.disc(8, 8, 1.5); fr.append(g)               # 弾ける
    fr.append(_hit())
    return fr


def _shoryu():
    """突き上げ: 下から弧を描いて上へ → てっぺんで当たる → HIT"""
    fr = []
    g = Grid(); g.disc(7, 13, 1.5); g.line(6, 15, 7, 13); fr.append(g)                     # 低く構える
    g = Grid(); g.disc(8, 9, 1.8)                                                           # 上がる (弧の尾)
    for i, (x, y) in enumerate(((5, 15), (6, 13), (7, 11))): g.dot(x, y); g.dot(x - 1, y)
    fr.append(g)
    g = Grid(); g.disc(9, 5, 2)
    for t in range(12):
        a = math.pi * (0.55 + 0.35 * t / 11)
        g.dot(9 + 7 * math.cos(a) + 3, 15 - 10 * math.sin(a))
        g.dot(9 + 6 * math.cos(a) + 3, 15 - 10 * math.sin(a))
    fr.append(g)
    g = Grid(); g.disc(9, 2, 2); g.rays(9, 2, 3, 6, 7, 0.4)                                # てっぺんで当たる
    for t in range(10):
        a = math.pi * (0.5 + 0.4 * t / 9)
        g.dot(10 + 6 * math.cos(a), 16 - 13 * math.sin(a))
    fr.append(g)
    g = Grid(); g.rays(8, 4, 1.5, 9, 14, 0.0); g.disc(8, 4, 1.2); fr.append(g)            # 大きく弾ける
    fr.append(_hit())
    return fr


def _tatsumaki():
    """竜巻: 弧 (蹴りの軌跡) が回りながら広がる → HIT"""
    fr = []
    for r, rot in ((3, 0.0), (4.5, 1.2), (6, 2.4), (7, 3.6), (7.5, 4.8)):
        g = Grid()
        for ring, rr, span, off in ((0, r, 2.4, 0.0), (1, r * 0.55, 1.8, math.pi)):
            for t in range(24):                         # 外と内の 2 本の弧 (向きを逆に)
                a = rot * (1 if ring == 0 else -1.3) + off + span * t / 23
                g.dot(7.5 + rr * math.cos(a), 7.5 + rr * math.sin(a) * 0.75)
        fr.append(g)
    fr.append(_hit())
    return fr


# name: (表示名, コマ, 1コマの ms, 最後のコマを残す ms)
EFFECTS = {"hadou": ("波動拳", _hadou(), 70, 700),
           "shoryu": ("昇竜拳", _shoryu(), 70, 700),
           "tatsumaki": ("竜巻旋風脚", _tatsumaki(), 90, 700)}


def fx_payload(name):
    label, frames, ms, hold = EFFECTS[name]
    frames = frames[:7]                                  # 1 パケット 240 バイトまで: 2 + 7×32 = 226
    return bytes((max(1, ms // 10), min(255, hold // 10))) + b"".join(f.bytes() for f in frames)


# ---------------------------------------------------------------- 音
def sound_path(name):
    for ext in (".wav", ".mp3"):
        p = os.path.join(SOUND_DIR, name + ext)
        if os.path.isfile(p):
            return p
    return None


def _player(path):
    # CPZ は PipeWire がスピーカー (ES8389) を掴んでいるので、aplay で直接は開けない (busy / 既定は HDMI で 524)。
    # PipeWire 経由 (pw-play / paplay) を先に使う。HMATRIX_SOUND_CMD="aplay -D plughw:1,0" のように指定もできる
    cmd = os.environ.get("HMATRIX_SOUND_CMD")
    if cmd:
        return cmd.split() + [path]
    if shutil.which("pw-play"):
        return ["pw-play", path]
    if shutil.which("paplay"):
        return ["paplay", path]
    if path.endswith(".wav") and shutil.which("aplay"):
        return ["aplay", "-q", path]
    if shutil.which("mpg123"):
        return ["mpg123", "-q", path]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
    if shutil.which("aplay"):
        return ["aplay", "-q", path]
    return None


def _sound_env():
    """サービス (systemd) から動かすと XDG_RUNTIME_DIR が無く、ログイン中の PipeWire に届かない → 足す"""
    env = dict(os.environ)
    if not env.get("XDG_RUNTIME_DIR"):
        d = f"/run/user/{os.getuid()}"
        if os.path.isdir(d):
            env["XDG_RUNTIME_DIR"] = d
    return env


class Fx:
    """音と絵を出す。send(payload) は本体へ FX を送る関数 (無ければ絵は出さない)"""

    def __init__(self, send, can_fx, log=print):
        self.send, self.can_fx, self.log = send, can_fx, log
        self.proc = None
        self.count = 0
        self.last = None
        self.lock = threading.Lock()

    def status(self):
        return {"list": [{"id": k, "label": v[0], "sound": bool(sound_path(k))} for k, v in EFFECTS.items()],
                "dir": SOUND_DIR, "count": self.count, "last": self.last}

    def play(self, name):
        if name not in EFFECTS:
            raise ValueError(f"エフェクト {name} はありません")
        self.count += 1; self.last = name
        pic = False
        if self.can_fx():
            try:
                self.send(fx_payload(name)); pic = True
            except Exception as e:                       # 本体とつながっていない時も音は鳴らす
                self.log(f"fx: 絵を送れません: {e}")
        snd = sound_path(name)
        if snd:
            cmd = _player(snd)
            if cmd:
                with self.lock:
                    if self.proc and self.proc.poll() is None:      # 前の音は切って新しい音を (連打で重ならない)
                        self.proc.kill()
                    try:
                        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=_sound_env())
                    except OSError as e:
                        self.log(f"fx: 音を鳴らせません: {e}")
                        snd = None
            else:
                self.log("fx: aplay / mpg123 / ffplay が見つかりません"); snd = None
        return {"name": name, "pic": pic, "sound": bool(snd)}


if __name__ == "__main__":                                # python3 hmatrix_fx.py → コマを文字で見る
    for k, (label, frames, ms, hold) in EFFECTS.items():
        print(label)
        for j in range(16):
            print("  ".join("".join("#" if v else "." for v in f.p[j]) for f in frames))
        print()
