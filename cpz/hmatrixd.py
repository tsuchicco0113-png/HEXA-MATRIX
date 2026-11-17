#!/usr/bin/env python3
"""HEXA MATRIX hub — CardputerZero に常駐して CoreMatrix をまとめて受け持つ (v0.4)

  CoreMatrix ──USB── CPZ (このプログラム) ──Wi-Fi── スマホ / PC のブラウザ
                         └── 本体アプリ (hmatrix_app.py) も localhost で使う

  http://<CPZ>:8090/        STUDIO (hexa-matrix-studio.html) をそのまま配信
  ws://<CPZ>:8090/ws        STUDIO の送信をそのまま USB へ中継 (WebSerial の代わり)
  /api/...                  ライブラリ (CPZに置く番組)、CPZから流す、本体SDへ送る、ことば

USB シリアルを開くのはこのプログラムだけ。STUDIO も本体アプリもここを通る。
標準ライブラリだけで動く (シリアルは termios で直接開く)。

usage: hmatrixd.py [--port 8090] [--dev /dev/ttyACM0] [--lib DIR]
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
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hxengine as H  # noqa: E402

VERSION = "0.4.0"
HOME = os.path.expanduser("~")
DEF_LIB = os.path.join(HOME, ".local", "share", "hexa-matrix", "library")
STUDIO_CANDIDATES = [os.path.join(HERE, "..", "hexa-matrix-studio.html"),
                     os.path.join(HERE, "hexa-matrix-studio.html")]

T_FRAME, T_BRIGHT, T_PING, T_ROTATE, T_BENCH = 0x01, 0x02, 0x03, 0x04, 0x05
T_BEGIN, T_DATA, T_END, T_LIST, T_DEL, T_PLAY = 0x10, 0x11, 0x12, 0x13, 0x14, 0x15
CHUNK = 200
KEEPALIVE = 1.0          # 同じ絵が長く続くとき、本体のライブ待ち(3秒)が切れないように送り直す間隔


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


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
    """CoreMatrix との USB。抜き差しに追従し、返事 (1行JSON) を配る"""

    def __init__(self, dev=None):
        self.fixed = dev
        self.fd = None
        self.path = None
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
            return False
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
        self.fd, self.path = fd, p
        log("connected", p)
        threading.Timer(0.3, lambda: self.send(packet(T_PING))).start()
        return True

    def _close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            log("disconnected", self.path)
        self.fd = None
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
            self.rx += data
            while b"\n" in self.rx:
                line, _, rest = self.rx.partition(b"\n")
                self.rx = bytearray(rest)
                self._line(line.decode("utf-8", "replace").strip())
            if len(self.rx) > 8192:
                self.rx.clear()

    def _line(self, ln):
        if not ln:
            return
        try:
            j = json.loads(ln)
        except ValueError:
            j = None
        if isinstance(j, dict):
            if "fw" in j:
                self.status = j
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

    def request(self, data, pred, timeout=3.0):
        """返事を待つ。待ちは送る前に登録する (速い返事の取りこぼし対策)"""
        w = {"pred": pred, "ev": threading.Event(), "res": None, "err": None}
        with self.wait_lock:
            self.waiters.append(w)
        if not self.send(data):
            with self.wait_lock:
                if w in self.waiters:
                    self.waiters.remove(w)
            raise RuntimeError("本体がつながっていません")
        if not w["ev"].wait(timeout):
            with self.wait_lock:
                if w in self.waiters:
                    self.waiters.remove(w)
            raise RuntimeError("本体から返事がありません")
        if w["err"]:
            raise RuntimeError(ERR_TEXT.get(w["err"], w["err"]))
        return w["res"]


ERR_TEXT = {"no storage": "保存先がありません", "bad name": "ファイル名が使えません", "no space": "空きが足りません",
            "seq": "順番が乱れました", "too big": "大きさが合いません", "crc": "中身が壊れました",
            "size": "大きさが合いません", "open failed": "ファイルを作れません", "write failed": "書き込めません",
            "rename failed": "名前を付けられません", "not found": "見つかりません",
            "upload timeout": "途中で止まりました",
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

    def play(self, name, frames, loop=True):
        if not frames:
            raise ValueError("コマがありません")
        with self.lock:
            self.gen += 1
            self.job = {"name": name, "frames": frames, "loop": loop, "total": sum(f[0] for f in frames)}
            self.pos = 0
            g = self.gen
        threading.Thread(target=self._run, args=(g,), daemon=True).start()

    def stop(self):
        with self.lock:
            self.gen += 1
            self.job = None

    def state(self):
        j = self.job
        if not j:
            return {"playing": False}
        return {"playing": True, "name": j["name"], "loop": j["loop"], "frames": len(j["frames"]),
                "sec": round(j["total"] / 1000, 1), "pos": self.pos}

    def _run(self, g):
        job = self.job
        last_f, last_b, last_tx = None, None, 0
        t = time.monotonic()
        while self.gen == g:
            for i, (ms, bri, fb) in enumerate(job["frames"]):
                if self.gen != g:
                    return
                self.pos = i
                if bri != last_b:
                    self.link.send(packet(T_BRIGHT, [bri])); last_b = bri
                if fb != last_f:
                    self.link.send(packet(T_FRAME, fb)); last_f = fb; last_tx = time.monotonic()
                self.frame, self.bri = fb, bri
                t += ms / 1000
                while self.gen == g:
                    now = time.monotonic()
                    if now >= t:
                        break
                    if now - last_tx >= KEEPALIVE:
                        self.link.send(packet(T_FRAME, fb)); last_tx = now
                    time.sleep(min(t - now, 0.05, max(0.001, KEEPALIVE - (now - last_tx))))
                if time.monotonic() - t > 0.5:          # 大きく遅れたら追いつこうとしない
                    t = time.monotonic()
            if not job["loop"]:
                break
        with self.lock:
            if self.gen == g:
                self.job = None


# ------------------------------------------------------------------ ハブ本体
class Hub:
    def __init__(self, link, libdir):
        self.link = link
        self.lib = libdir
        os.makedirs(libdir, exist_ok=True)
        self.player = Player(link)
        self.busy = None             # 本体へ送っている最中 {"name","done","total"}
        self.busy_lock = threading.Lock()
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
                n = struct.unpack_from("<I", head, 4)[0] if head[:4] == b"HXM1" else 0
                meta = self._meta(name)
                out.append({"name": name, "size": st.st_size, "frames": n, "mtime": int(st.st_mtime),
                            "sec": meta.get("sec"), "src": os.path.exists(self._p(name, ".json")),
                            "title": meta.get("title") or name})
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
            hxm = H.bake_bin(frames)
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
    def play_lib(self, name, loop=True):
        name, data = self.lib_read(name)
        self.player.play(name, H.parse_hxm(data), loop)

    def say(self, opt):
        text = str(opt.get("text") or "").strip()
        if not text:
            raise ValueError("文字がありません")
        sc = H.say_scene(text, show=opt.get("show") or "scrollL", speed=opt.get("speed") or 6,
                         bri=opt.get("bri") or 8, size=16 if opt.get("size") != 8 else 8,
                         hold=opt.get("hold") or 2, loops=1, eff=opt.get("eff") or "none",
                         bold=bool(opt.get("bold")))
        frames = H.render_program([sc])
        fr = [(f.ms, f.bri, H.to_bytes(f.b)) for f in frames]
        self.last_say = sc
        self.player.play("ことば: " + text[:20], fr, opt.get("loop", True))
        return {"frames": len(fr), "sec": round(sum(x[0] for x in fr) / 1000, 1)}

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
        try:
            self.player.stop()
            time.sleep(0.12)
            L = self.link
            t0 = time.time()
            L.request(packet(T_BEGIN, struct.pack("<I", len(data)) + dn.encode()),
                      lambda j: j.get("ack") == "begin", 4)
            for seq, off in enumerate(range(0, len(data), CHUNK)):
                s = seq & 0xFFFF
                L.request(packet(T_DATA, struct.pack("<H", s) + data[off:off + CHUNK]),
                          lambda j, s=s: j.get("ack") == s, 4)
                self.busy["done"] = min(len(data), off + CHUNK)
            j = L.request(packet(T_END, struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF)),
                          lambda j: "saved" in j, 8)
            log(f"pushed {dn} {len(data)}B {time.time() - t0:.1f}s")
            try:
                self.dev_list()
            except RuntimeError:
                pass
            return {"saved": j.get("saved"), "idx": j.get("idx"), "size": len(data),
                    "sec": round(time.time() - t0, 1)}
        finally:
            with self.busy_lock:
                self.busy = None

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
                "port": self.link.path, "dev": self.link.status, "player": p.state(),
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
                HUB.play_lib(j.get("name"), j.get("loop", True))
                return self._send(200, HUB.status())
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
        hello = {"ok": True, "hub": "cpz", "ver": VERSION, "connected": HUB.link.connected, "port": HUB.link.path}
        ws.send(json.dumps(hello, ensure_ascii=False))
        if HUB.link.status:
            ws.send(json.dumps(HUB.link.status))

        def fwd(ln):
            if ws.open:
                ws.send(ln)
        HUB.link.listeners.append(fwd)
        try:
            while True:
                m = ws.recv()
                if m is None:
                    break
                op, data = m
                if op == 2 and data:
                    if HUB.player.job:
                        HUB.player.stop()            # ブラウザから送り始めたら CPZ の再生は止める
                    HUB.web_last = time.time()
                    if not HUB.link.send(data):
                        ws.send(json.dumps({"ok": False, "hub": "cpz", "err": "本体がつながっていません"}, ensure_ascii=False))
                elif op == 1:
                    try:
                        j = json.loads(data.decode())
                    except ValueError:
                        continue
                    if j.get("q") == "hub":
                        ws.send(json.dumps(HUB.status(), ensure_ascii=False))
        finally:
            ws.open = False
            if fwd in HUB.link.listeners:
                HUB.link.listeners.remove(fwd)


def main():
    global HUB
    ap = argparse.ArgumentParser(description="HEXA MATRIX hub for CardputerZero")
    ap.add_argument("--port", type=int, default=int(os.environ.get("HMATRIX_PORT", 8090)))
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--dev", default=None, help="USBシリアル (既定: 自動で探す)")
    ap.add_argument("--lib", default=os.environ.get("HMATRIX_LIB", DEF_LIB))
    a = ap.parse_args()
    H.load_fonts()
    HUB = Hub(Link(a.dev), a.lib)
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    srv.daemon_threads = True
    log(f"HEXA MATRIX hub {VERSION}  http://{local_ip()}:{a.port}/  library: {a.lib}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
