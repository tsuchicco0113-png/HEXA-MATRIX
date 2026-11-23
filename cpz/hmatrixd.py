#!/usr/bin/env python3
"""HEXA MATRIX hub — CardputerZero に常駐して CoreMatrix をまとめて受け持つ (v0.5)

  CoreMatrix ──USB── CPZ (このプログラム) ──Wi-Fi── スマホ / PC のブラウザ
                         └── 本体アプリ (hmatrix_app.py) も localhost で使う

  http://<CPZ>:8090/        STUDIO (hexa-matrix-studio.html) をそのまま配信
  ws://<CPZ>:8090/ws        STUDIO の送信をそのまま USB へ中継 (WebSerial の代わり)
  /api/...                  ライブラリ (CPZに置く番組)、CPZから流す、本体SDへ送る、ことば

USB シリアルを開くのはこのプログラムだけ。STUDIO も本体アプリもここを通る。
標準ライブラリだけで動く (シリアルは termios で直接開く)。

usage: hmatrixd.py [--port 8090] [--dev /dev/ttyACM0] [--net hexamatrix.local] [--lib DIR] [--key 合言葉]

USB が無ければ Wi-Fi の CoreMatrix (ファーム v0.5〜、microSD の hexa/wifi.txt でつなぐ) を探す。
wifi.txt に key= (合言葉、ファーム v0.9.4〜) を入れたら、ここにも --key か HMATRIX_KEY で同じものを渡す。
"""
import argparse
import base64
import glob
import hashlib
import json
import os
import re
import select
import socket
import struct
import sys
import termios
import threading
import time
import tty
import urllib.parse
import subprocess
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hxengine as H  # noqa: E402

VERSION = "0.13.6"
NET_PORT = 7800          # CoreMatrix (ファーム v0.5〜) が Wi-Fi で待ち受けるポート
HOME = os.path.expanduser("~")
DEF_LIB = os.path.join(HOME, ".local", "share", "hexa-matrix", "library")
STUDIO_CANDIDATES = [os.path.join(HERE, "..", "hexa-matrix-studio.html"),
                     os.path.join(HERE, "hexa-matrix-studio.html")]

T_FRAME, T_BRIGHT, T_PING, T_ROTATE, T_BENCH, T_AUTH, T_CONFIG = 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07
T_WALK = 0x08            # 歩行 (ファーム v0.12〜): int8 速さ% / u8 有効時間(0.1秒) / u8 顔
T_BEGIN, T_DATA, T_END, T_LIST, T_DEL, T_PLAY = 0x10, 0x11, 0x12, 0x13, 0x14, 0x15
CHUNK = 200
WIN_MAX = 16             # 返事を待たずに先へ送る DATA の数の上限 (本体が PING の "win" で教えてくれる、v0.9.5〜)
AP_CMD = ["sudo", "-n", "/usr/local/sbin/hexa-ap"]   # イベント用アクセスポイント (install.sh が置く、v0.9.6)
LEASES = "/var/lib/NetworkManager/dnsmasq-*.leases"  # AP につないできた CoreMatrix の IP (mDNS が引けない時の予備)
KEEPALIVE = 1.0          # 同じ絵が長く続くとき、本体のライブ待ち(3秒)が切れないように送り直す間隔


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class DevError(RuntimeError):
    """本体からのエラー。code に本体の err ("busy" など) を持つ"""

    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


# ------------------------------------------------------------------ パケット
def crc8(data):
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c


def packet(t, payload=b""):
    payload = bytes(payload)
    body = bytes([t, len(payload)]) + payload
    return b"\xA5\x5A" + body + bytes([crc8(body)])


def safe_name(s):
    """本体に置く名前 (英数字 _ - のみ + .hxm)。STUDIO の slug() と同じ考え方"""
    s = re.sub(r"\.hxm$", "", str(s or ""), flags=re.I)
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_")[:30]
    return (s + ".hxm") if s else ""


def pkt_types(data):
    """ブラウザから届いたバイト列に入っているパケットの type を並べる (中継の見張り用)"""
    out, i, n = [], 0, len(data)
    while i + 4 < n:
        if data[i] == 0xA5 and data[i + 1] == 0x5A:
            out.append(data[i + 2])
            i += 5 + data[i + 3]
        else:
            i += 1
    return out


def lib_name(s):
    """ライブラリの名前 (日本語OK。/ や制御文字だけ除く)"""
    s = re.sub(r"\.(hxm|json)$", "", str(s or "").strip(), flags=re.I)
    s = re.sub(r"[\x00-\x1f/\\:*?\"<>|]+", "_", s).strip(" ._")[:60]
    return s


# ------------------------------------------------------------------ USB シリアル
def find_port():
    env = os.environ.get("HMATRIX_DEV")
    if env:
        return env if os.path.exists(env) else None
    for p in sorted(glob.glob("/dev/serial/by-id/*")):
        if re.search(r"espressif|303a|m5", p, re.I):
            return os.path.realpath(p)
    for p in sorted(glob.glob("/dev/ttyACM*")):
        return p
    return None


class Link:
    """CoreMatrix との USB / Wi-Fi。抜き差しに追従し、返事 (1行JSON) を配る

    USB が見つかれば USB、無ければ Wi-Fi (hexamatrix.local:7800 など) へ TCP でつなぐ。
    Wi-Fi でつないでいる間に USB が差されたら USB に切り替える。パケットはどちらも同じ。
    """

    def __init__(self, dev=None, nets=None, key=""):
        self.fixed = dev
        self.key = key or ""
        self.auth_bad_until = 0.0     # 合言葉が違った → しばらくつなぎに行かない
        self.auth_warned = False
        self.nets = [h.strip() for h in (nets or "").split(",") if h.strip() and h.strip() != "off"]
        self.fd = None
        self.sock = None
        self.kind = None             # "usb" / "wifi"
        self.path = None
        self.last_rx = 0.0
        self.last_ping = 0.0
        self.last_usb_check = 0.0
        self.wlock = threading.Lock()
        self.waiters = []
        self.wait_lock = threading.Lock()
        self.listeners = []           # 1行ごとに呼ぶ (ws へ流す)
        self.status = {}              # 最後に来た PING の返事
        self.devlist = None
        self.rx = bytearray()
        threading.Thread(target=self._loop, daemon=True).start()

    @property
    def connected(self):
        return self.fd is not None

    def _open(self):
        p = self.fixed or find_port()
        if not p:
            return self._open_net()
        if p.startswith("tcp://"):
            return self._open_net([p[6:]])
        try:
            fd = os.open(p, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            tty.setraw(fd)
            a = termios.tcgetattr(fd)
            a[4] = a[5] = termios.B115200
            a[2] |= termios.CLOCAL | termios.CREAD
            a[2] &= ~termios.HUPCL
            termios.tcsetattr(fd, termios.TCSANOW, a)
        except OSError as e:
            log("open failed", p, e)
            return False
        self.fd, self.path, self.kind = fd, p, "usb"
        log("connected", p)
        self.last_rx = time.monotonic()
        threading.Timer(0.3, lambda: self.send(packet(T_PING))).start()
        return True

    def _lease_hosts(self):
        """CPZ がアクセスポイントの時、つないできた CoreMatrix の IP を DHCP の記録から探す (v0.9.6)"""
        names = {h.partition(":")[0].lower().removesuffix(".local") for h in self.nets}
        out = []
        for p in glob.glob(LEASES):
            try:
                with open(p) as f:
                    for ln in f:
                        v = ln.split()          # 期限 MAC IP ホスト名 ...
                        if len(v) >= 4 and v[3].lower() in names:
                            out.append(v[2])
            except OSError:
                pass
        return out

    def _open_net(self, hosts=None):
        if time.monotonic() < self.auth_bad_until:
            return False
        if hosts is None and self.nets:
            hosts = self.nets + [ip for ip in self._lease_hosts() if ip not in self.nets]
        for h in (hosts or self.nets):
            host, _, port = h.partition(":")
            try:
                sk = socket.create_connection((host, int(port or NET_PORT)), timeout=2.5)
            except (OSError, ValueError):
                continue
            sk.setblocking(False)
            sk.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sk.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            self.sock, self.fd, self.kind = sk, sk.fileno(), "wifi"
            self.path = f"wifi {host}:{port or NET_PORT}"
            log("connected", self.path)
            self.last_rx = time.monotonic()
            if self.key:                               # v0.9.4〜: 合言葉を先に通す (合言葉なしの本体は黙って OK を返す)
                self.send(packet(T_AUTH, self.key.encode()[:32]))
            self.send(packet(T_PING))
            return True
        return False

    def _close(self):
        if self.fd is not None:
            try:
                if self.sock:
                    self.sock.close()
                else:
                    os.close(self.fd)
            except OSError:
                pass
            log("disconnected", self.path)
        self.fd = None
        self.sock = None
        self.kind = None
        self.status = {}
        self.devlist = None
        with self.wait_lock:
            for w in self.waiters:
                w["err"] = "本体がつながっていません"; w["ev"].set()
            self.waiters = []

    def _loop(self):
        while True:
            if self.fd is None:
                if not self._open():
                    time.sleep(1.5)
                    continue
            if self.kind == "wifi" and self._wifi_check():
                continue
            try:
                r, _, _ = select.select([self.fd], [], [], 0.5)
                if not r:
                    continue
                data = os.read(self.fd, 4096)
                if not data:
                    raise OSError("eof")
            except OSError:
                self._close()
                time.sleep(1)
                continue
            self.last_rx = time.monotonic()
            self.rx += data
            while b"\n" in self.rx:
                line, _, rest = self.rx.partition(b"\n")
                self.rx = bytearray(rest)
                self._line(line.decode("utf-8", "replace").strip())
            if len(self.rx) > 8192:
                self.rx.clear()

    def _wifi_check(self):
        """Wi-Fi の時: USB が差されたら切り替え、返事が途絶えたらつなぎ直す。切ったら True"""
        now = time.monotonic()
        if not self.fixed and now - self.last_usb_check > 3:
            self.last_usb_check = now
            if find_port():
                log("USB が見つかったので USB に切り替えます")
                self._close(); return True
        quiet = now - self.last_rx
        if quiet > 20:
            log("Wi-Fi の返事が途絶えました")
            self._close(); time.sleep(1); return True
        if quiet > 8 and now - self.last_ping > 5:
            self.last_ping = now
            self.send(packet(T_PING))
        return False

    def _line(self, ln):
        if not ln:
            return
        try:
            j = json.loads(ln)
        except ValueError:
            j = None
        if isinstance(j, dict):
            if j.get("ok") is False and j.get("err") == "auth" and self.kind == "wifi":
                log("本体の合言葉と違います (wifi.txt の key= と --key / HMATRIX_KEY をそろえてください)。30秒待ちます")
                self.auth_bad_until = time.monotonic() + 30
            if "fw" in j:
                self.status = j
                if j.get("auth") is True and not self.auth_warned:
                    self.auth_warned = True
                    log("本体に合言葉が設定されています。--key か HMATRIX_KEY で渡してください")
            if j.get("list"):
                self.devlist = j
            with self.wait_lock:
                for w in list(self.waiters):
                    if j.get("ok") is False:
                        w["err"] = j.get("err") or "error"
                    elif not w["pred"](j):
                        continue
                    w["res"] = j; w["ev"].set(); self.waiters.remove(w)
        for fn in list(self.listeners):
            try:
                fn(ln)
            except Exception:
                pass

    def send(self, data):
        if self.fd is None:
            return False
        with self.wlock:
            try:
                mv = memoryview(data)
                end = time.time() + 2
                while mv:
                    try:
                        n = os.write(self.fd, mv)
                        mv = mv[n:]
                    except BlockingIOError:
                        if time.time() > end:
                            return False
                        select.select([], [self.fd], [], 0.1)
                return True
            except OSError:
                return False

    def expect(self, pred):
        """返事の待ちを登録する (送る前に呼ぶ。速い返事の取りこぼし対策)"""
        w = {"pred": pred, "ev": threading.Event(), "res": None, "err": None}
        with self.wait_lock:
            self.waiters.append(w)
        return w

    def forget(self, w):
        with self.wait_lock:
            if w in self.waiters:
                self.waiters.remove(w)

    def wait(self, w, timeout=3.0):
        if not w["ev"].wait(timeout):
            self.forget(w)
            raise RuntimeError("本体から返事がありません")
        if w["err"]:
            raise DevError(ERR_TEXT.get(w["err"], w["err"]), w["err"])
        return w["res"]

    def request(self, data, pred, timeout=3.0):
        """送って返事を待つ"""
        w = self.expect(pred)
        if not self.send(data):
            self.forget(w)
            raise RuntimeError("本体がつながっていません")
        return self.wait(w, timeout)

    def fw_at_least(self, *ver):
        try:
            return tuple(int(x) for x in str(self.status.get("fw", "0")).split(".")[:3]) >= ver
        except ValueError:
            return False

    def dev_win(self):
        """返事を待たずに先へ送ってよい DATA の数。v0.9.5〜 は本体が PING の "win" で教えてくれる
        (USB の受信バッファも広げてあるので USB でも使える)。それより前は Wi-Fi 8 / USB 1"""
        try:
            w = int(self.status.get("win") or 0)
        except (TypeError, ValueError):
            w = 0
        if w > 0:
            return max(1, min(WIN_MAX, w))
        return 8 if self.kind == "wifi" else 1

    def transfer(self, name, data, progress=None, win=None):
        """FILE_BEGIN / DATA / END でファイルを送る。名前が @ で始まると本体はメモリに置いて流す (v0.6〜)
        返事を待たずに数個先まで送る (往復の待ち時間で遅くならないように)。数は dev_win()。
        win を渡すと、それと dev_win() の小さい方 (やり直しで減らす時)"""
        wifi = self.kind == "wifi"
        win = min(win, self.dev_win()) if win else self.dev_win()
        tmo = 8 if wifi else 4        # Wi-Fi は無線の再送で数秒遅れることがある
        n = (len(data) + CHUNK - 1) // CHUNK
        step = "開始"
        try:
            self.request(packet(T_BEGIN, struct.pack("<I", len(data)) + name.encode()),
                         lambda j: j.get("ack") == "begin", tmo)
            pend = []
            try:
                for seq, off in enumerate(range(0, len(data), CHUNK)):
                    s = seq & 0xFFFF
                    w = self.expect(lambda j, s=s: j.get("ack") == s)
                    w["seq"] = seq
                    pend.append(w)
                    if not self.send(packet(T_DATA, struct.pack("<H", s) + data[off:off + CHUNK])):
                        raise RuntimeError("本体がつながっていません")
                    if len(pend) >= win:
                        step = f"中身 {pend[0]['seq'] + 1}/{n}"
                        self.wait(pend.pop(0), tmo)
                    if progress:
                        progress(min(len(data), off + CHUNK))
                while pend:
                    step = f"中身 {pend[0]['seq'] + 1}/{n}"
                    self.wait(pend.pop(0), tmo)
            finally:
                for w in pend:
                    self.forget(w)
            step = "終わり"
            return self.request(packet(T_END, struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF)),
                                # PING の返事にも "clip" (true/false) があるので、コマ数 (int) の時だけ
                                lambda j: "saved" in j or "char" in j or type(j.get("clip")) is int, tmo + 4)
        except RuntimeError as e:
            raise DevError(f"{e} ({step}, 窓{win})", getattr(e, "code", None)) from None

    def diag(self):
        """本体の受け取りの記録を聞いて、ログ用の1行にする (v0.9.2 以上のファーム)"""
        try:
            j = self.request(packet(T_PING), lambda j: "fw" in j, 4)
        except RuntimeError as e:
            return f"PING も返事なし: {e}"
        return f"fw {j.get('fw')} net {json.dumps(j.get('net', {}), ensure_ascii=False)}"


ERR_TEXT = {"no storage": "保存先がありません", "bad name": "ファイル名が使えません", "no space": "空きが足りません",
            "seq": "順番が乱れました", "too big": "大きさが合いません", "crc": "中身が壊れました",
            "size": "大きさが合いません", "open failed": "ファイルを作れません", "write failed": "書き込めません",
            "rename failed": "名前を付けられません", "not found": "見つかりません",
            "upload timeout": "途中で止まりました", "no memory": "本体のメモリが足りません",
            "bad clip": "コマ列の形が違います",
            "bad char": "キャラのファイルの形が違います (STUDIO の箱庭で作り直してください)",
            "bad config": "本体の設定を変えられません (ファームが古いか、立てて置いていないかもしれません)",
            "usb only": "この設定は USB でつないでいる時だけ変えられます",
            "busy": "本体が別の受け取りの最中です (USB と Wi-Fi の両方から送っていませんか)",
            "auth": "本体の合言葉と違います (wifi.txt の key= と --key / HMATRIX_KEY)",
            "unknown type": "本体のファームが古いです。v0.3.0 以上を書き込んでください"}


# ------------------------------------------------------------------ CPZから流す
class Player:
    """コマ列を USB で流す (ライブ)。ブラウザから送り始めたら止める"""

    def __init__(self, link):
        self.link = link
        self.lock = threading.Lock()
        self.job = None              # {"name","frames":[(ms,bri,32B)],"loop"}
        self.gen = 0
        self.pos = 0
        self.frame = bytes(32)       # いま出している絵 (本体アプリのプレビュー用)
        self.bri = None

    def play(self, name, frames, loop=True, dur=None, clip=False):
        """dur: 流す秒数 (くりかえしの途中でも、時間が来たら止める)。None ならずっと
        clip=True: 本体がメモリのコマ列を自分で流している (v0.6〜)。ここはプレビュー用に
        同じ時間で追いかけるだけで送らない。時間切れ・停止の時だけ本体に「番組へ戻れ」を送る"""
        if not frames:
            raise ValueError("コマがありません")
        with self.lock:
            self.gen += 1
            self.job = {"name": name, "frames": frames, "loop": loop, "total": sum(f[0] for f in frames),
                        "until": time.monotonic() + dur if dur else None, "clip": clip}
            self.pos = 0
            g = self.gen
        threading.Thread(target=self._run, args=(g,), daemon=True).start()

    def stop(self, tell_device=True):
        with self.lock:
            job = self.job
            self.gen += 1
            self.job = None
        if job and job.get("clip") and tell_device:
            self.link.send(packet(T_PLAY, [0xFE]))     # 一時再生をやめて番組へ

    def state(self):
        j = self.job
        if not j:
            return {"playing": False}
        out = {"playing": True, "name": j["name"], "loop": j["loop"], "frames": len(j["frames"]),
               "sec": round(j["total"] / 1000, 1), "pos": self.pos, "clip": bool(j.get("clip"))}
        if j.get("until"):
            out["left"] = max(0, int(j["until"] - time.monotonic() + 0.99))
        return out

    def _run(self, g):
        job = self.job
        tx = not job.get("clip")
        last_f, last_b, last_tx = None, None, 0
        t = time.monotonic()
        while self.gen == g:
            for i, (ms, bri, fb) in enumerate(job["frames"]):
                if self.gen != g:
                    return
                if job["until"] and time.monotonic() >= job["until"]:
                    break
                self.pos = i
                if tx and bri != last_b:
                    self.link.send(packet(T_BRIGHT, [bri])); last_b = bri
                if tx and fb != last_f:
                    self.link.send(packet(T_FRAME, fb)); last_f = fb; last_tx = time.monotonic()
                self.frame, self.bri = fb, bri
                t += ms / 1000
                while self.gen == g:
                    now = time.monotonic()
                    if now >= t:
                        break
                    if tx and now - last_tx >= KEEPALIVE:
                        self.link.send(packet(T_FRAME, fb)); last_tx = now
                    time.sleep(min(t - now, 0.05, max(0.001, KEEPALIVE - (now - last_tx))))
                if time.monotonic() - t > 0.5:          # 大きく遅れたら追いつこうとしない
                    t = time.monotonic()
            if not job["loop"] or (job["until"] and time.monotonic() >= job["until"]):
                break
        timed_out = bool(job["until"]) and time.monotonic() >= job["until"]
        with self.lock:
            mine = self.gen == g
            if mine:
                self.job = None
        if mine and job.get("clip") and (timed_out or job["loop"]):
            self.link.send(packet(T_PLAY, [0xFE]))     # 時間が来たので本体を番組へ戻す


# ------------------------------------------------------------------ 歩行 (v0.12)
class Walker:
    """Stackchan Strider (CoreMatrix + FS90R) を歩かせる。

    本体は WALK を 0.5 秒受け取らないと止まる。ここは 0.15 秒ごとに送り直す。
    頼んだ側 (本体アプリ / ブラウザ) も HOLD 秒ごとに頼み直す。頼み直しが途切れたら (アプリが落ちた等) 止める。"""
    PERIOD = 0.15
    HOLD = 1.5

    def __init__(self, link):
        self.link = link
        self.lock = threading.Lock()
        self.speed = 0
        self.face = 0
        self.turn = False            # v0.13.6: その場旋回 (速さの符号 = 向き。+ 左 / − 右)
        self.asked = 0.0
        self.sent_stop = True
        self.pinged = 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def _pkt(self, sp, fc, turn):
        if turn or self.link.fw_at_least(0, 13, 6):
            return packet(T_WALK, struct.pack("<bBBB", sp, 5, fc, 1 if turn else 0))
        return packet(T_WALK, struct.pack("<bBB", sp, 5, fc))

    def set(self, speed=None, face=None, turn=None):
        with self.lock:
            if turn is not None:
                if turn and not self.link.fw_at_least(0, 13, 6):
                    raise RuntimeError("本体のファームを v0.13.6 以上にしてください (その場旋回)")
                self.turn = bool(turn)
            if speed is not None:
                self.speed = max(-100, min(100, int(speed)))
            if face is not None:
                self.face = int(face) & 0xFF
            self.asked = time.monotonic()
            self.sent_stop = False
            sp, fc, tn = self.speed, self.face, self.turn
        self.link.send(self._pkt(sp, fc, tn))                            # すぐ1回 (反応を速く)
        return self.state()

    def stop(self):
        return self.set(0, turn=False)

    def state(self):
        return {"ok": True, "speed": self.speed, "face": self.face, "turn": self.turn,
                "walk": (self.link.status or {}).get("walk")}

    def _run(self):
        while True:
            time.sleep(self.PERIOD)
            send = None
            with self.lock:
                now = time.monotonic()
                if self.speed and now - self.asked > self.HOLD:
                    log("walk: 頼み直しが来ないので止めます")
                    self.speed = 0
                if not self.sent_stop:
                    send = (self.speed, self.face, self.turn)
                    if not self.speed:
                        self.sent_stop = True       # 止まれは1回送れば良い (本体は期限切れでも止まる)
                ping = now - self.asked < 3 and now - self.pinged > 0.5
                if ping:
                    self.pinged = now
            if not self.link.connected:
                continue
            if send:
                self.link.send(self._pkt(*send))
            if ping:                                  # 歩かせている間は向き (ジャイロ) を細かく見る
                self.link.send(packet(T_PING))


# ------------------------------------------------------------------ ハブ本体
class Hub:
    def __init__(self, link, libdir):
        self.link = link
        self.lib = libdir
        os.makedirs(libdir, exist_ok=True)
        self.player = Player(link)
        self.walker = Walker(link)
        self.busy = None             # 本体へ送っている最中 {"name","done","total"}
        self.busy_lock = threading.Lock()
        self.xfer_lock = threading.Lock()   # ファイル転送は同時に1つだけ (CPZ の転送とブラウザ中継の転送で共有)
        self.relay_hold = None       # ブラウザ中継の転送が xfer_lock を持っている間 {"ws": id, "t": 最後のパケットの時刻}
        self.web_last = 0.0          # ブラウザ(ws)から最後に送られた時刻
        self.last_say = None

    # ---- ライブラリ
    def lib_items(self):
        out = []
        for p in sorted(glob.glob(os.path.join(self.lib, "*.hxm"))):
            name = os.path.basename(p)[:-4]
            try:
                st = os.stat(p)
                with open(p, "rb") as f:
                    head = f.read(8)
                n = (struct.unpack_from("<I", head, 4)[0] & 0x7FFFFFFF) if head[:4] == b"HXM1" else 0
                meta = self._meta(name)
                out.append({"name": name, "size": st.st_size, "frames": n, "mtime": int(st.st_mtime),
                            "sec": meta.get("sec"), "src": os.path.exists(self._p(name, ".json")),
                            "title": meta.get("title") or name, "once": H.hxm_is_once(head)})
            except OSError:
                pass
        out.sort(key=lambda x: x["name"])
        return out

    def _p(self, name, ext):
        return os.path.join(self.lib, name + ext)

    def _meta(self, name):
        try:
            with open(self._p(name, ".meta"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def lib_save(self, name, program=None, hxm=None):
        """program (STUDIO の番組JSON) があれば CPZ で描いて .hxm にする"""
        name = lib_name(name or (program or {}).get("name"))
        if not name:
            raise ValueError("名前を付けてください")
        cycles = 1
        if program is not None:
            seq, cycles = H.program_sequence(program)
            if not seq:
                raise ValueError("シーンがありません")
            t0 = time.time()
            frames = H.render_program(seq)
            hxm = H.bake_bin(frames, once=program.get("loop") is False)
            log(f"render {name}: {len(frames)} frames {time.time() - t0:.2f}s")
        if not hxm:
            raise ValueError("中身がありません")
        fr = H.parse_hxm(hxm)
        tmp = self._p(name, ".tmp")
        with open(tmp, "wb") as f:
            f.write(hxm)
        os.replace(tmp, self._p(name, ".hxm"))
        if program is not None:
            with open(self._p(name, ".json"), "w", encoding="utf-8") as f:
                json.dump(program, f, ensure_ascii=False)
        with open(self._p(name, ".meta"), "w", encoding="utf-8") as f:
            json.dump({"title": (program or {}).get("name") or name, "cycles": cycles,
                       "sec": round(sum(x[0] for x in fr) / 1000, 1)}, f, ensure_ascii=False)
        return {"name": name, "size": len(hxm), "frames": len(fr), "cycles": cycles}

    def lib_read(self, name):
        name = lib_name(name)
        with open(self._p(name, ".hxm"), "rb") as f:
            return name, f.read()

    def lib_delete(self, name):
        name = lib_name(name)
        if self.player.job and self.player.job["name"] == name:
            self.player.stop()
        found = False
        for ext in (".hxm", ".json", ".meta"):
            try:
                os.remove(self._p(name, ext)); found = True
            except OSError:
                pass
        if not found:
            raise ValueError("見つかりません")

    # ---- 流す
    def lock_xfer(self, timeout=10):
        """CPZ からの転送の前に。ブラウザの中継転送が途中で止まったまま (8秒) なら取り上げる"""
        end = time.time() + timeout
        while True:
            if self.xfer_lock.acquire(timeout=0.25):
                return True
            h = self.relay_hold
            if h and time.time() - h["t"] > 8:
                log("ブラウザからの転送が途中で止まったので打ち切ります")
                self.relay_hold = None
                try:
                    self.xfer_lock.release()
                except RuntimeError:
                    pass
                continue
            if time.time() > end:
                return False

    def play_lib(self, name, loop=True, dur=None):
        name, data = self.lib_read(name)
        return self.play_data(name, data, loop, dur)

    def _takeover(self):
        """CPZ から流し始めたことをブラウザ (STUDIO) へ知らせる。STUDIO はプレビューの送信を止める
        (止めないと、ブラウザのプレビューと CPZ の絵が交互に出る)"""
        msg = json.dumps({"ok": True, "hub": "cpz", "takeover": True})
        for fn in list(self.link.listeners):
            try:
                fn(msg)
            except Exception:
                pass

    def play_data(self, name, data, loop=True, dur=None):
        """CPZ から流す。ファーム v0.6 以上ならコマ列をまとめて本体のメモリへ送り、本体の時計で流してもらう
        (1コマずつ送ると、特に Wi-Fi では届き方がばらついてカクつく / 本体の番組と混ざる)"""
        fr = H.parse_hxm(data)
        # v0.9.6: 本体がつながっていない (合言葉違いで切られた時も) のに「流しています」にならないように
        if not self.link.connected:
            raise RuntimeError("本体がつながっていません" + (" (合言葉が違うかもしれません)" if time.monotonic() < self.link.auth_bad_until else ""))
        if not self.link.status:                       # つないだ直後でファームの版がまだ分からない
            try:
                self.link.request(packet(T_PING), lambda j: "fw" in j, 3)
            except RuntimeError:
                pass
        self._takeover()
        if self.link.connected and self.link.fw_at_least(0, 6, 0) and len(data) <= 4 * 1024 * 1024:
            if not self.lock_xfer(10):
                raise RuntimeError("いま別の番組を送っています (ブラウザから本体へ送っている最中かもしれません)")
            try:
                self.player.stop()
                # 失敗したら少し待ってやり直す。窓を 本体の数 → 4 → 1 と減らす (最後は遅いが確実)
                # busy (本体がもう片方から受け取り中) は回線のせいではないので窓は減らさず、
                # 本体が5秒で捨てるのを待つ (busy のやり直しは2回まで)
                wins, wi, busy_left = (None, 4, 1), 0, 2
                for attempt in range(1, 6):
                    if wi >= len(wins):
                        break
                    win = wins[wi]
                    t0 = time.time()
                    try:
                        self.link.transfer("@live" if loop else "@once", data, win=win)
                    except RuntimeError as e:
                        code = getattr(e, "code", None)
                        log(f"clip try {attempt} failed via {self.link.kind}:", e)
                        if code == "auth":
                            raise
                        if code == "busy" and busy_left > 0:
                            busy_left -= 1
                            time.sleep(2.5)
                            continue
                        wi += 1
                        log("  本体:", self.link.diag())
                        time.sleep(0.5)
                        continue
                    log(f"clip {name}: {len(data)}B {time.time() - t0:.2f}s via {self.link.kind} 窓{win or self.link.dev_win()}")
                    self.player.play(name, fr, loop, dur, clip=True)
                    return {"mode": "clip", "send_sec": round(time.time() - t0, 2)}
                if self.link.kind == "wifi":
                    # v0.9.3: Wi-Fi で1コマずつ送ると届き方がばらついて点滅するので、それには落とさない
                    log("clip failed via wifi")
                    raise RuntimeError("Wi-Fi で本体に送れませんでした。もう一度押すか USB でつないでください")
                log("clip failed, stream instead")
            finally:
                self.xfer_lock.release()
        self.player.play(name, fr, loop, dur)
        return {"mode": "stream"}

    def say(self, opt):
        text = str(opt.get("text") or "").strip()
        if not text:
            raise ValueError("文字がありません")
        sc = H.say_scene(text, show=opt.get("show") or "scrollL", speed=opt.get("speed") or 6,
                         bri=opt.get("bri") or 8, size=16 if opt.get("size") != 8 else 8,
                         hold=opt.get("hold") or 2, loops=1, eff=opt.get("eff") or "none",
                         bold=bool(opt.get("bold")))
        frames = H.render_program([sc])
        data = H.bake_bin(frames)
        self.last_say = sc
        try:
            dur = float(opt.get("dur") or 0)
        except (TypeError, ValueError):
            dur = 0
        r = self.play_data("ことば: " + text[:20], data, opt.get("loop", True) and dur >= 0, dur if dur > 0 else None)
        return dict(r, frames=len(frames), sec=round(sum(f.ms for f in frames) / 1000, 1))

    # ---- 本体 (CoreMatrix) の番組
    def dev_list(self):
        return self.link.request(packet(T_LIST), lambda j: j.get("list"), 4)

    def dev_play(self, idx):
        self.player.stop()
        return self.link.request(packet(T_PLAY, [idx & 0xFF]), lambda j: "dev" in j)

    def dev_delete(self, name):
        n = safe_name(name)
        if not n:
            raise ValueError("ファイル名が使えません")
        return self.link.request(packet(T_DEL, n.encode()), lambda j: j.get("list"), 4)

    def push(self, libname, devname=None):
        """ライブラリの番組を本体 (SD / 本体メモリ) に保存する"""
        name, data = self.lib_read(libname)
        dn = safe_name(devname or "") or self._suggest(name)
        with self.busy_lock:
            if self.busy:
                raise RuntimeError("いま別の番組を送っています")
            self.busy = {"name": dn, "done": 0, "total": len(data)}
        if not self.lock_xfer(10):
            with self.busy_lock:
                self.busy = None
            raise RuntimeError("いま別の番組を送っています")
        try:
            self.player.stop()
            time.sleep(0.12)
            t0 = time.time()
            for attempt in (1, 2):
                try:
                    j = self.link.transfer(dn, data, lambda n: self.busy.__setitem__("done", n))
                    break
                except RuntimeError as e:
                    if attempt == 2 or getattr(e, "code", None) != "busy":
                        raise
                    log("push: 本体が別の受け取りの最中なので待ってやり直します")
                    time.sleep(2.5)
            log(f"pushed {dn} {len(data)}B {time.time() - t0:.1f}s 窓{self.link.dev_win()}")
            try:
                self.dev_list()
            except RuntimeError:
                pass
            return {"saved": j.get("saved"), "idx": j.get("idx"), "size": len(data),
                    "sec": round(time.time() - t0, 1)}
        finally:
            self.xfer_lock.release()
            with self.busy_lock:
                self.busy = None

    # ---- 本体の設定 (ファーム v0.9.6〜)
    CFG_KEYS = ("autorot", "shake", "psave", "rotreset", "rotlearn")
    # v0.12 歩行: servo は GPIO 番号 (-1 で使わない)、strim は µs、wmax は %、ほかは true/false
    WALK_KEYS = ("walker", "servo", "strim", "sinv", "wmax", "yawzero", "strimtest", "wchar")
    PLED_KEYS = ("pled",)          # v0.13.2: 緑の電源 LED
    RAMP_KEYS = ("wacc", "wdec")   # v0.13.3: 歩行の加速・減速 (ms)
    PULSE_KEYS = ("won", "woff")   # v0.13.4: 刻んで歩く (ms)
    SCAN_KEYS = ("tscan",)         # v0.13.5: 旋回スキャン (片道 ms、0 で中止)
    TURN_KEYS = ("whead", "wheadth", "thalf")   # v0.13.6: まっすぐ補正・旋回の片道
    TOFF_KEYS = ("toffclr",)       # v0.13.9: 覚えた左右の距離を消す
    # v0.10 箱庭: hako は "auto"/"on"/"off"、chg/peek/deep/anymg は数、ほかは true/false
    HAKO_KEYS = ("hako", "chg", "hflip", "imuhi", "peek", "deep", "anymg", "plog", "hakoreset")

    def dev_config(self, opt):
        if not self.link.fw_at_least(0, 9, 6):
            raise RuntimeError("本体のファームを v0.9.6 以上にしてください (自動回転・振って次・省電力)")
        if any(k in opt for k in self.HAKO_KEYS) and not self.link.fw_at_least(0, 10, 0):
            raise RuntimeError("本体のファームを v0.10.0 以上にしてください (箱庭)")
        if any(k in opt for k in self.WALK_KEYS) and not self.link.fw_at_least(0, 12, 0):
            raise RuntimeError("本体のファームを v0.12.0 以上にしてください (歩行)")
        if any(k in opt for k in self.PLED_KEYS) and not self.link.fw_at_least(0, 13, 2):
            raise RuntimeError("本体のファームを v0.13.2 以上にしてください (電源 LED)")
        if any(k in opt for k in self.RAMP_KEYS) and not self.link.fw_at_least(0, 13, 3):
            raise RuntimeError("本体のファームを v0.13.3 以上にしてください (加速・減速)")
        if any(k in opt for k in self.PULSE_KEYS) and not self.link.fw_at_least(0, 13, 4):
            raise RuntimeError("本体のファームを v0.13.4 以上にしてください (刻んで歩く)")
        if any(k in opt for k in self.SCAN_KEYS) and not self.link.fw_at_least(0, 13, 5):
            raise RuntimeError("本体のファームを v0.13.5 以上にしてください (旋回スキャン)")
        if any(k in opt for k in self.TURN_KEYS) and not self.link.fw_at_least(0, 13, 6):
            raise RuntimeError("本体のファームを v0.13.6 以上にしてください (旋回・まっすぐ補正)")
        if any(k in opt for k in self.TOFF_KEYS) and not self.link.fw_at_least(0, 13, 9):
            raise RuntimeError("本体のファームを v0.13.9 以上にしてください (旋回の覚え書き)")
        def val(k, v):
            if k == "hako":
                return v if v in ("auto", "on", "off") else ("on" if v is True else "off" if v is False else "auto")
            if isinstance(v, bool) or v is None:
                return "1" if v else "0"
            if isinstance(v, (int, float)):
                return str(int(v))
            raise ValueError(f"{k} の値が変です")
        items = [f"{k}={val(k, opt[k])}" for k in self.CFG_KEYS + self.HAKO_KEYS + self.WALK_KEYS + self.PLED_KEYS + self.RAMP_KEYS + self.PULSE_KEYS + self.SCAN_KEYS + self.TURN_KEYS + self.TOFF_KEYS if k in opt]
        if not items:
            raise ValueError("設定がありません")
        return self.link.request(packet(T_CONFIG, ";".join(items).encode()), lambda j: "fw" in j, 4)

    def dev_wifi2(self, ssid, pw):
        """2つ目の Wi-Fi を本体に教える (USB の時だけ。本体は Wi-Fi からは受け付けない)"""
        if self.link.kind != "usb":
            raise RuntimeError("本体に Wi-Fi を教えるのは USB でつないでいる時だけです")
        if not self.link.fw_at_least(0, 9, 6):
            raise RuntimeError("本体のファームを v0.9.6 以上にしてください")
        ssid, pw = str(ssid or ""), str(pw or "")
        if len(ssid.encode()) > 32 or len(pw.encode()) > 64:
            raise ValueError("名前は32バイト、パスワードは64バイトまでです")
        self.link.request(packet(T_CONFIG, b"ssid2=" + ssid.encode()), lambda j: "fw" in j, 4)
        return self.link.request(packet(T_CONFIG, b"pass2=" + pw.encode()), lambda j: "fw" in j, 4)

    def ap(self, cmd="status"):
        """イベント用アクセスポイント (CPZ を AP にする)。cmd: on / off / status"""
        try:
            r = subprocess.run(AP_CMD + [cmd], capture_output=True, text=True, timeout=40)
        except FileNotFoundError:
            raise RuntimeError("sudo がありません")
        except subprocess.TimeoutExpired:
            raise RuntimeError("アクセスポイントの切り替えが終わりません")
        try:
            j = json.loads((r.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            err = (r.stderr or "").strip()
            if "password" in err or "sudo" in err:
                err = "hexa-ap を使う許可がありません。sh cpz/install.sh をもう一度実行してください"
            raise RuntimeError(err or "hexa-ap が動きません (sh cpz/install.sh で入れ直してください)")
        if not j.get("ok"):
            raise RuntimeError(j.get("err") or "アクセスポイントを切り替えられません")
        if cmd != "status":
            log(f"event AP {cmd}: {j.get('ssid')} {j.get('ip')}")
        return j

    def ap_teach(self):
        """いまの AP の名前とパスワードを、USB でつないでいる本体に2つ目の Wi-Fi として教える"""
        j = self.ap("status")
        return self.dev_wifi2(j.get("ssid"), j.get("pass"))

    def _suggest(self, name):
        files = (self.link.devlist or {}).get("files") or []
        used = {f.get("n", "")[:3] for f in files}
        base = safe_name(name)[:-4] or "program"
        for i in range(1, 100):
            n = f"{i:02d}_{base}.hxm"
            if n[:3] not in used:
                return n
        return base + ".hxm"

    def status(self):
        p = self.player
        return {"ok": True, "hub": "cpz", "ver": VERSION, "connected": self.link.connected,
                "port": self.link.path, "link": self.link.kind, "dev": self.link.status, "player": p.state(),
                "frame": p.frame.hex(), "bri": p.bri, "busy": self.busy,
                "web": time.time() - self.web_last < 5, "ip": local_ip()}


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


# ------------------------------------------------------------------ WebSocket (最小限)
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WS:
    def __init__(self, rfile, wfile):
        self.r, self.w = rfile, wfile
        self.lock = threading.Lock()
        self.open = True

    def recv(self):
        """→ (opcode, bytes) / None (切れた)"""
        data = b""
        while True:
            h = self.r.read(2)
            if len(h) < 2:
                return None
            fin, op = h[0] & 0x80, h[0] & 0x0F
            masked, n = h[1] & 0x80, h[1] & 0x7F
            if n == 126:
                n = struct.unpack(">H", self.r.read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self.r.read(8))[0]
            if n > 1 << 20:
                return None
            mask = self.r.read(4) if masked else b""
            pay = self.r.read(n)
            if len(pay) < n:
                return None
            if masked:
                pay = bytes(b ^ mask[i & 3] for i, b in enumerate(pay))
            if op == 9:
                self.send(pay, 10); continue
            if op == 10:
                continue
            if op == 8:
                return None
            data += pay
            if op != 0:
                first = op
            if fin:
                return (first, data)

    def send(self, data, op=1):
        if isinstance(data, str):
            data = data.encode()
        n = len(data)
        if n < 126:
            h = bytes([0x80 | op, n])
        elif n < 65536:
            h = bytes([0x80 | op, 126]) + struct.pack(">H", n)
        else:
            h = bytes([0x80 | op, 127]) + struct.pack(">Q", n)
        with self.lock:
            try:
                self.w.write(h + data); self.w.flush()
            except OSError:
                self.open = False


# ------------------------------------------------------------------ HTTP
HUB = None


class Handler(BaseHTTPRequestHandler):
    server_version = "hmatrixd/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        pass

    # ---- 返事
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _err(self, e, code=400):
        self._send(code, {"ok": False, "err": str(e)})

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 32 * 1024 * 1024:
            raise ValueError("大きすぎます")
        return self.rfile.read(n) if n else b""

    def _json(self):
        b = self._body()
        try:
            return json.loads(b.decode("utf-8")) if b else {}
        except ValueError:
            raise ValueError("JSON が読めません")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- GET
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path, q = u.path, urllib.parse.parse_qs(u.query)
        try:
            if path in ("/", "/index.html", "/studio"):
                for p in STUDIO_CANDIDATES:
                    if os.path.exists(p):
                        with open(p, "rb") as f:
                            return self._send(200, f.read(), "text/html; charset=utf-8")
                return self._send(404, "hexa-matrix-studio.html が見つかりません", "text/plain; charset=utf-8")
            if path == "/ws":
                return self._ws()
            if path == "/api/status":
                return self._send(200, HUB.status())
            if path == "/api/library":
                return self._send(200, {"ok": True, "items": HUB.lib_items()})
            m = re.match(r"^/api/library/(.+)$", path)
            if m:
                name = urllib.parse.unquote(m.group(1))
                if name.endswith(".json"):
                    with open(HUB._p(lib_name(name), ".json"), "rb") as f:
                        return self._send(200, f.read())
                n, data = HUB.lib_read(name)
                fn = urllib.parse.quote(n + ".hxm")
                return self._send(200, data, "application/octet-stream",
                                  {"Content-Disposition": f"attachment; filename*=UTF-8''{fn}"})
            if path == "/api/device/list":
                return self._send(200, HUB.dev_list())
            if path == "/api/ap":
                return self._send(200, HUB.ap("status"))
            return self._send(404, {"ok": False, "err": "not found"})
        except FileNotFoundError:
            self._err("見つかりません", 404)
        except (ValueError, RuntimeError) as e:
            self._err(e)

    do_HEAD = do_GET

    # ---- POST / DELETE
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        path, q = u.path, urllib.parse.parse_qs(u.query)
        try:
            if path == "/api/library":
                ct = self.headers.get("Content-Type", "")
                if "json" in ct:
                    j = self._json()
                    hxm = base64.b64decode(j["hxm"]) if j.get("hxm") else None
                    return self._send(200, dict(ok=True, **HUB.lib_save(j.get("name"), j.get("program"), hxm)))
                name = (q.get("name") or [""])[0]
                return self._send(200, dict(ok=True, **HUB.lib_save(name, None, self._body())))
            j = self._json()
            if path == "/api/play":
                dur = float(j.get("dur") or 0)
                r = HUB.play_lib(j.get("name"), j.get("loop", True), dur if dur > 0 else None)
                return self._send(200, dict(HUB.status(), **r))
            if path == "/api/stop":
                HUB.player.stop()
                return self._send(200, HUB.status())
            if path == "/api/say":
                return self._send(200, dict(ok=True, **HUB.say(j)))
            if path == "/api/push":
                return self._send(200, dict(ok=True, **HUB.push(j.get("name"), j.get("as"))))
            if path == "/api/device/play":
                return self._send(200, HUB.dev_play(0xFF if j.get("pause") else int(j.get("idx", 0))))
            if path == "/api/device/delete":
                return self._send(200, HUB.dev_delete(j.get("name")))
            if path == "/api/device/bright":
                v = max(0, min(255, int(j.get("value", 128))))
                HUB.link.send(packet(T_BRIGHT, [v]))
                return self._send(200, {"ok": True, "bright": v})
            if path == "/api/device/rotate":
                rot = (int(HUB.link.status.get("rot", 1)) + 1) & 3 if j.get("rot") is None else int(j["rot"]) & 3
                return self._send(200, HUB.link.request(packet(T_ROTATE, [rot]), lambda r: "dev" in r))
            if path == "/api/device/ping":
                return self._send(200, HUB.link.request(packet(T_PING), lambda r: "dev" in r))
            if path == "/api/device/config":                 # {"autorot":true,"shake":false,"psave":true,"rotreset":true}
                return self._send(200, HUB.dev_config(j))
            if path == "/api/device/wifi2":                  # {"ssid":..,"pass":..} USB の時だけ
                return self._send(200, HUB.dev_wifi2(j.get("ssid"), j.get("pass")))
            if path == "/api/ap":                            # {"on":true|false}
                return self._send(200, HUB.ap("on" if j.get("on") else "off"))
            if path == "/api/ap/teach":
                return self._send(200, HUB.ap_teach())
            if path == "/api/walk":                          # {"speed":-100〜100, "face":0〜5} 1.5秒ごとに頼み直す
                if not HUB.link.fw_at_least(0, 12, 0):
                    raise RuntimeError("本体のファームを v0.12.0 以上にしてください (歩行)")
                if j.get("speed"):
                    HUB.player.stop()                        # CPZ から流している絵は止める (顔と混ざらない)
                return self._send(200, HUB.walker.set(j.get("speed"), j.get("face"), j.get("turn", False)))
            if path == "/api/walk/stop":
                return self._send(200, HUB.walker.stop())
            return self._send(404, {"ok": False, "err": "not found"})
        except (ValueError, RuntimeError, KeyError, FileNotFoundError) as e:
            self._err(e if not isinstance(e, FileNotFoundError) else "見つかりません")

    def do_DELETE(self):
        m = re.match(r"^/api/library/(.+)$", urllib.parse.urlparse(self.path).path)
        try:
            if not m:
                return self._send(404, {"ok": False, "err": "not found"})
            HUB.lib_delete(urllib.parse.unquote(m.group(1)))
            self._send(200, {"ok": True})
        except ValueError as e:
            self._err(e)

    # ---- WebSocket: STUDIO の送信を USB へそのまま
    def _ws(self):
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or "websocket" not in self.headers.get("Upgrade", "").lower():
            return self._send(400, {"ok": False, "err": "websocket only"})
        acc = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", acc)
        self.end_headers()
        self.close_connection = True
        ws = WS(self.rfile, self.wfile)
        hello = {"ok": True, "hub": "cpz", "ver": VERSION, "connected": HUB.link.connected, "port": HUB.link.path,
                 "link": HUB.link.kind}
        ws.send(json.dumps(hello, ensure_ascii=False))
        if HUB.link.status:
            ws.send(json.dumps(HUB.link.status))

        def fwd(ln):
            if ws.open:
                ws.send(ln)
        HUB.link.listeners.append(fwd)
        me = id(ws)
        holding = False
        def busy_reply():
            # 本体と同じ形で返す (STUDIO の返事待ちがそのまま「busy」で失敗する)
            ws.send(json.dumps({"ok": False, "err": "busy"}))
        try:
            while True:
                m = ws.recv()
                if m is None:
                    break
                op, data = m
                if op == 2 and data:
                    if HUB.player.job:
                        # ブラウザから送り始めたら CPZ の再生は止める。本体の一時再生は、
                        # ブラウザのコマが届けば本体が自分でやめるので、ここでは何も送らない
                        HUB.player.stop(tell_device=False)
                    HUB.web_last = time.time()
                    # v0.9.6: ファイル転送 (BEGIN〜END) の間は xfer_lock を持つ。本体から見ると CPZ の転送も
                    # ブラウザの転送も同じ口から来るので、ここで順番を守らないと中身が混ざる
                    ts = pkt_types(data)
                    if T_BEGIN in ts:
                        if not holding:
                            if not HUB.xfer_lock.acquire(timeout=0.5):
                                busy_reply(); continue
                            holding = True
                        HUB.relay_hold = {"ws": me, "t": time.time()}
                    elif T_DATA in ts or T_END in ts:
                        if not holding or not HUB.relay_hold or HUB.relay_hold.get("ws") != me:
                            holding = False
                            continue                 # 断った (or 取り上げられた) 転送の残りは本体へ送らない
                        HUB.relay_hold["t"] = time.time()
                    if not HUB.link.send(data):
                        ws.send(json.dumps({"ok": False, "hub": "cpz", "err": "本体がつながっていません"}, ensure_ascii=False))
                    if holding and T_END in ts:
                        holding = False
                        HUB.relay_hold = None
                        HUB.xfer_lock.release()
                elif op == 1:
                    try:
                        j = json.loads(data.decode())
                    except ValueError:
                        continue
                    if j.get("q") == "hub":
                        ws.send(json.dumps(HUB.status(), ensure_ascii=False))
        finally:
            ws.open = False
            if holding and HUB.relay_hold and HUB.relay_hold.get("ws") == me:
                HUB.relay_hold = None
                try:
                    HUB.xfer_lock.release()
                except RuntimeError:
                    pass
            if fwd in HUB.link.listeners:
                HUB.link.listeners.remove(fwd)


def main():
    global HUB
    ap = argparse.ArgumentParser(description="HEXA MATRIX hub for CardputerZero")
    ap.add_argument("--port", type=int, default=int(os.environ.get("HMATRIX_PORT", 8090)))
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--dev", default=None, help="USBシリアル (既定: 自動で探す)。tcp://host:port も可")
    ap.add_argument("--net", default=os.environ.get("HMATRIX_NET", "hexamatrix.local"),
                    help="USBが無い時につなぐ Wi-Fi の CoreMatrix (カンマ区切り、host[:port]。off で使わない)")
    ap.add_argument("--lib", default=os.environ.get("HMATRIX_LIB", DEF_LIB))
    ap.add_argument("--key", default=os.environ.get("HMATRIX_KEY", ""),
                    help="Wi-Fi の合言葉 (本体の wifi.txt の key= と同じもの。ファーム v0.9.4〜)")
    a = ap.parse_args()
    H.load_fonts()
    HUB = Hub(Link(a.dev, a.net, a.key), a.lib)
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    srv.daemon_threads = True
    log(f"HEXA MATRIX hub {VERSION}  http://{local_ip()}:{a.port}/  library: {a.lib}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
