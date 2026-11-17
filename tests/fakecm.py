"""模擬 CoreMatrix (pty)。ハブを実機なしで試す: python3 tests/fakecm.py & python3 cpz/hmatrixd.py --dev /tmp/fakecm
ファーム v0.4 の返事をまねる。/tmp/fakecm にリンクを作る"""
import os, pty, tty, json, struct, zlib, time, sys, select, re
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
def out(j): os.write(m, (json.dumps(j) + "\n").encode())
def status(): out({"ok": True, "dev": "corematrix", "fw": "0.4.0", "bri": liveBri, "rot": rot, "frames": stats["frames"],
                   "store": "sd", "sd": "ok", "n": len(FILES), "cur": cur, "paused": paused, "live": live, "master": 4})
def names(): return sorted(FILES)
def lst(): out({"ok": True, "list": True, "store": "sd", "sd": "ok", "free": 1000000, "cur": cur, "paused": paused,
               "files": [{"n": n, "s": len(FILES[n])} for n in names()]})
def err(e): out({"ok": False, "err": e})
def handle(t, p):
    global cur, paused, live, liveBri, rot, up
    if t == 1:
        stats["frames"] += 1; stats["last"] = p.hex(); live = True
        open("/tmp/fakecm.frames", "a").write(f"{time.monotonic():.3f} F {p.hex()}\n")
    elif t == 2:
        liveBri = p[0]; open("/tmp/fakecm.frames", "a").write(f"{time.monotonic():.3f} B {p[0]}\n")
    elif t == 3: status()
    elif t == 4: rot = p[0] & 3; status()
    elif t == 0x10:
        sz = struct.unpack_from("<I", p)[0]; n = p[4:].decode()
        if not re.fullmatch(r"[A-Za-z0-9_\-.]{1,40}", n): return err("bad name")
        up = {"name": n, "size": sz, "seq": 0, "data": bytearray()}; out({"ok": True, "ack": "begin"})
    elif t == 0x11:
        sq = struct.unpack_from("<H", p)[0]
        if not up: return err("not started")
        if sq != up["seq"]: up = None; return err("seq")
        up["data"] += p[2:]; up["seq"] = (sq + 1) & 0xFFFF; out({"ok": True, "ack": sq})
    elif t == 0x12:
        c = struct.unpack_from("<I", p)[0]
        if not up: return err("not started")
        if len(up["data"]) != up["size"]: up = None; return err("size")
        if zlib.crc32(bytes(up["data"])) != c: up = None; return err("crc")
        FILES[up["name"]] = bytes(up["data"]); open("/tmp/fakecm_" + up["name"], "wb").write(up["data"])
        idx = names().index(up["name"]); cur = idx; live = False; paused = False
        out({"ok": True, "saved": up["name"], "idx": idx}); up = None
    elif t == 0x13: lst()
    elif t == 0x14:
        n = p.decode()
        if n in FILES: del FILES[n]; lst()
        else: err("not found")
    elif t == 0x15:
        if p[0] == 0xFF: paused = True
        else: paused = False; live = False; cur = p[0] % max(1, len(FILES))
        status()
    else: err("unknown type")
buf = bytearray()
print("fake at", name, flush=True)
open("/tmp/fakecm.frames", "w").close()
while True:
    r, _, _ = select.select([m], [], [], 0.5)
    if not r: continue
    buf += os.read(m, 4096)
    while True:
        i = buf.find(b"\xA5\x5A")
        if i < 0: buf.clear(); break
        if i: del buf[:i]
        if len(buf) < 5: break
        t, n = buf[2], buf[3]
        if len(buf) < 5 + n: break
        body = bytes(buf[2:4 + n]); c = buf[4 + n]; del buf[:5 + n]
        if crc8(body) != c: err("crc"); continue
        handle(t, body[2:])
