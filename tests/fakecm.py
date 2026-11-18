"""模擬 CoreMatrix (pty)。ハブを実機なしで試す: python3 tests/fakecm.py & python3 cpz/hmatrixd.py --dev /tmp/fakecm
ファーム v0.4 の返事をまねる。/tmp/fakecm にリンクを作る
  --fw 0.9.5   返すファームの版 (0.9.5〜 は "win" も返す)   --win 16   "win" の値 (0 で返さない)
  --rtt 30     返事を 30ms 遅らせる (往復の待ちのまね。窓の効果を見る)
  --busy 1     最初の N 回の BEGIN に "busy" を返す         --key abc  Wi-Fi の合言葉 (AUTH 0x06)"""
import os, pty, tty, json, struct, zlib, time, sys, select, re, socket
TCP = int(sys.argv[sys.argv.index("--tcp") + 1]) if "--tcp" in sys.argv else 0   # Wi-Fi の代わり: --tcp 7800
if TCP:
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", TCP)); srv.listen(1)
    m = None; name = f"tcp 127.0.0.1:{TCP}"
else:
    m, s = pty.openpty()
    tty.setraw(m); tty.setraw(s)
    name = os.ttyname(s)
    if os.path.lexists("/tmp/fakecm"): os.remove("/tmp/fakecm")
    os.symlink(name, "/tmp/fakecm")
FILES = {}; cur = 0; paused = False; live = False; liveBri = 128; rot = 1; frames = 0
up = None
stats = {"frames": 0, "bright": [], "last": None}
def crc8(d):
    c = 0
    for b in d:
        c ^= b
        for _ in range(8): c = ((c << 1) ^ 7) & 255 if c & 128 else (c << 1) & 255
    return c
LOSE = int(sys.argv[sys.argv.index("--lose") + 1]) if "--lose" in sys.argv else 0   # 最初の N 回の BEGIN を黙って捨てる
DELAY = float(sys.argv[sys.argv.index("--delay") + 1]) / 1000 if "--delay" in sys.argv else 0   # 返事の遅れ (Wi-Fi のまね)
def arg(k, d): return sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
FW = arg("--fw", "0.9.6"); WIN = int(arg("--win", "16")); RTT = float(arg("--rtt", "0")) / 1000
BUSY = int(arg("--busy", "0")); KEY = arg("--key", ""); authed = not KEY
CFG = {"autorot": 0, "shake": 0, "psave": 1}; SSID2 = [""]; LEARN = [0]
Q = []; stats_q = {"max": 0, "data": 0}       # 遅らせて返す返事 (送る時刻, 中身)
def fwv(): return tuple(int(x) for x in FW.split("."))
def out(j):
    if DELAY: time.sleep(DELAY)
    b = (json.dumps(j) + "\n").encode()
    if RTT:
        Q.append((time.monotonic() + RTT, b)); stats_q["max"] = max(stats_q["max"], len(Q)); return
    try: os.write(m, b)
    except (OSError, TypeError): pass
def flushq():
    now = time.monotonic()
    while Q and Q[0][0] <= now:
        _, b = Q.pop(0)
        try: os.write(m, b)
        except (OSError, TypeError): pass
def status(): out(dict({"ok": True, "dev": "corematrix", "fw": FW, "bri": liveBri, "rot": rot, "frames": stats["frames"],
                   "store": "sd", "sd": "ok", "n": len(FILES), "cur": cur, "paused": paused, "live": live, "master": 4, "wifi": "ok" if TCP else "off", "ip": "", "name": "hexamatrix",
                   "net": {"begin": stats.get("begin", 0), "drop": stats.get("drop", 0)},
                   "auth": bool(KEY) and not authed, "maxq": stats_q["max"]}, **({"win": WIN} if WIN and fwv() >= (0, 9, 5) else {}),
                   **({"imu": "ok", "learn": LEARN[0], "cfg": dict(CFG), "batt": 3950, "lvl": 82, "chg": False,
                       "wnet": 1 if TCP else 0, "wsleep": 0, "ssid2": bool(SSID2[0])} if fwv() >= (0, 9, 6) else {})))
def names(): return sorted(FILES)
def lst(): out({"ok": True, "list": True, "store": "sd", "sd": "ok", "free": 1000000, "cur": cur, "paused": paused,
               "files": [{"n": n, "s": len(FILES[n])} for n in names()]})
def err(e): out({"ok": False, "err": e})
def handle(t, p):
    global cur, paused, live, liveBri, rot, up, authed, BUSY
    if TCP and not authed and t not in (3, 6):
        return err("auth")
    if t == 7 and fwv() >= (0, 9, 6):
        txt = p.decode()
        open("/tmp/fakecm.frames", "a").write(f"{time.monotonic():.3f} CONFIG {txt}\n")
        if txt.startswith(("ssid2=", "pass2=")):
            if TCP: return err("usb only")
            if txt.startswith("ssid2="): SSID2[0] = txt[6:]
            return status()
        for it in txt.split(";"):
            k, _, v = it.partition("=")
            if k in CFG: CFG[k] = 1 if v[:1] in "1ot" else 0
            elif k == "autorot": pass
            elif k == "rotreset": LEARN[0] = 0
            elif k == "rotlearn": LEARN[0] += 1
            else: return err("bad config")
            if k == "autorot" and CFG[k]: LEARN[0] = max(LEARN[0], 1)
        return status()
    if t == 6:
        if not KEY or p.decode() == KEY: authed = True; return out({"ok": True, "auth": True})
        err("auth"); raise ConnectionAbortedError
    if t == 1:
        stats["frames"] += 1; stats["last"] = p.hex(); live = True
        open("/tmp/fakecm.frames", "a").write(f"{time.monotonic():.3f} F {p.hex()}\n")
    elif t == 2:
        liveBri = p[0]; open("/tmp/fakecm.frames", "a").write(f"{time.monotonic():.3f} B {p[0]}\n")
    elif t == 3: status()
    elif t == 4: rot = p[0] & 3; status()
    elif t == 0x10:
        global LOSE
        stats["begin"] = stats.get("begin", 0) + 1
        if LOSE > 0: LOSE -= 1; return
        if BUSY > 0: BUSY -= 1; return err("busy")
        sz = struct.unpack_from("<I", p)[0]; n = p[4:].decode()
        if n.startswith("@"):
            up = {"name": n, "size": sz, "seq": 0, "data": bytearray(), "ram": True}; out({"ok": True, "ack": "begin"}); return
        if not re.fullmatch(r"[A-Za-z0-9_\-.]{1,40}", n): return err("bad name")
        up = {"name": n, "size": sz, "seq": 0, "data": bytearray()}; out({"ok": True, "ack": "begin"})
    elif t == 0x11:
        sq = struct.unpack_from("<H", p)[0]
        if not up: stats["drop"] = stats.get("drop", 0) + 1; return   # v0.9.1: 始まっていない受け取りの残りは黙って捨てる
        if sq != up["seq"]: up = None; return err("seq")
        up["data"] += p[2:]; up["seq"] = (sq + 1) & 0xFFFF; stats_q["data"] += 1; out({"ok": True, "ack": sq})
    elif t == 0x12:
        c = struct.unpack_from("<I", p)[0]
        if not up: return
        if len(up["data"]) != up["size"]: up = None; return err("size")
        if zlib.crc32(bytes(up["data"])) != c: up = None; return err("crc")
        if up.get("ram"):
            d = bytes(up["data"]); cnt = struct.unpack_from("<I", d, 4)[0] & 0x7FFFFFFF
            open("/tmp/fakecm.frames", "a").write(f"{time.monotonic():.3f} CLIP {up['name']} {cnt} {len(d)}\n")
            open("/tmp/fakecm_clip.hxm", "wb").write(d)
            out({"ok": True, "clip": cnt, "loop": up["name"] == "@live"}); up = None; return
        FILES[up["name"]] = bytes(up["data"]); open("/tmp/fakecm_" + up["name"], "wb").write(up["data"])
        idx = names().index(up["name"]); cur = idx; live = False; paused = False
        out({"ok": True, "saved": up["name"], "idx": idx}); up = None
    elif t == 0x13: lst()
    elif t == 0x14:
        n = p.decode()
        if n in FILES: del FILES[n]; lst()
        else: err("not found")
    elif t == 0x15:
        if p[0] == 0xFE: open("/tmp/fakecm.frames", "a").write(f"{time.monotonic():.3f} STOPCLIP\n")
        elif p[0] == 0xFF: paused = True
        else: paused = False; live = False; cur = p[0] % max(1, len(FILES))
        status()
    else: err("unknown type")
buf = bytearray()
print("fake at", name, flush=True)
open("/tmp/fakecm.frames", "w").close()
conn = None
while True:
    rl = ([srv] if TCP else []) + ([m] if m is not None else [])
    r, _, _ = select.select(rl, [], [], 0.002 if Q else 0.5)
    flushq()
    if not r: continue
    if TCP and srv in r:
        if conn: conn.close()
        conn, _ = srv.accept(); m = conn.fileno(); buf.clear(); authed = not KEY; Q.clear(); continue
    try: data = os.read(m, 4096)
    except OSError: data = b""
    if not data:
        if TCP: conn.close(); conn = None; m = None; continue
        continue
    buf += data
    while True:
        i = buf.find(b"\xA5\x5A")
        if i < 0: buf.clear(); break
        if i: del buf[:i]
        if len(buf) < 5: break
        t, n = buf[2], buf[3]
        if len(buf) < 5 + n: break
        body = bytes(buf[2:4 + n]); c = buf[4 + n]; del buf[:5 + n]
        if crc8(body) != c: err("crc"); continue
        try:
            handle(t, body[2:])
        except ConnectionAbortedError:             # 合言葉違い: 返事を送ってから切る
            time.sleep(RTT); flushq(); conn.close(); conn = None; m = None; buf.clear(); break
