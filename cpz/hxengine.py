"""HEXA MATRIX 描画エンジン (src/engine.js の Python 版)

シーン(dict) → コマ列 [Frame(b=bytearray(256), ms, bri)] → .hxm
STUDIO と同じシーンから同じコマ列を作る (tests で全パターンをバイト一致で確認)。
標準ライブラリだけで動く。
"""
import base64, json, math, os, struct, zlib

W = 16
A = 256
M32 = 0xFFFFFFFF


# ------------------------------------------------------------------
# フォント ('HXF1'。tools/mkfont.py を参照)
# ------------------------------------------------------------------
class Font:
    def __init__(self, raw):
        if raw[:4] != b"HXF1":
            raise ValueError("フォントの形式が違います")
        self.H = raw[4]
        n = struct.unpack_from("<I", raw, 5)[0]
        p, c, cps = 9, 0, []
        for _ in range(n):
            d = s = 0
            while True:
                b = raw[p]; p += 1
                d += (b & 127) << s; s += 7
                if not b & 128:
                    break
            c += d
            cps.append(c)
        ws = raw[p:p + n]; p += n
        self.map = {}
        for i in range(n):
            w = ws[i]; nb = (w + 7) >> 3
            rows = []
            for _ in range(self.H):
                v = 0
                for _k in range(nb):
                    v = (v << 8) | raw[p]; p += 1
                rows.append((v << 8) if nb == 1 else v)
            self.map[cps[i]] = (w, rows)

    def glyph(self, ch):
        return self.map.get(ord(ch)) or self.map.get(0x3F)


FONT = {}


def load_fonts(path=None):
    """fonts.json ({"g16","g8"}: deflate-raw + base64) を読む"""
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        for cand in (os.path.join(here, "fonts.json"), os.path.join(here, "..", "src", "fonts.json")):
            if os.path.exists(cand):
                path = cand; break
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    for key, size in (("g16", 16), ("g8", 8)):
        FONT[size] = Font(zlib.decompress(base64.b64decode(j[key]), -15))
    return FONT


# ------------------------------------------------------------------
# 小道具
# ------------------------------------------------------------------
def js_round(x):
    """JS の Math.round (0.5 は + 側へ)"""
    return math.floor(x + 0.5)


def blank():
    return bytearray(A)


def from_rows(r):
    b = bytearray(A)
    r = list(r or [])
    for y in range(W):
        v = int(r[y]) if y < len(r) and r[y] is not None else 0
        v &= M32
        for x in range(W):
            if v & (0x8000 >> x):
                b[y * W + x] = 1
    return b


def to_rows(b):
    out = []
    for y in range(W):
        v = 0
        for x in range(W):
            if b[y * W + x]:
                v |= 0x8000 >> x
        out.append(v)
    return out


def to_bytes(b):
    """送信用の1コマ=32バイト (行順、各行は左8点→右8点、MSBが左)"""
    o = bytearray(32)
    for y, v in enumerate(to_rows(b)):
        o[y * 2] = v >> 8; o[y * 2 + 1] = v & 255
    return bytes(o)


def from_bytes(d):
    b = bytearray(A)
    for y in range(W):
        v = (d[y * 2] << 8) | d[y * 2 + 1]
        for x in range(W):
            if v & (0x8000 >> x):
                b[y * W + x] = 1
    return b


class Strip:
    __slots__ = ("w", "h", "d", "cuts")

    def __init__(self, w, d, cuts):
        self.w, self.h, self.d, self.cuts = w, W, d, cuts


def text_strip(text, size, bold):
    f = FONT[size]
    lines = ("" if text is None else str(text)).replace("\r", "").split("\n")
    lines = [" ".join(lines)] if size == 16 else lines[:2]
    bw = 1 if bold else 0
    parts = []
    for l in lines:
        gs = [g for g in (f.glyph(ch) for ch in l) if g]
        w = 0; cuts = [0]
        for g in gs:
            w += g[0] + bw; cuts.append(w)
        parts.append((gs, w, cuts))
    sw = max([0] + [p[1] for p in parts])
    d = bytearray(max(1, sw) * W)
    n = len(d)
    y0s = [0] if size == 16 else ([4] if len(parts) == 1 else [0, 8])
    for li, (gs, _w, _c) in enumerate(parts):
        x = 0
        for gw, rows in gs:
            for y in range(f.H):
                r = rows[y]; yy = y0s[li] + y
                if yy >= W:
                    continue
                for i in range(gw):
                    if r & (0x8000 >> i):
                        k = yy * sw + x + i
                        if k < n: d[k] = 1
                        if bw and k + 1 < n: d[k + 1] = 1
            x += gw + bw
    s = set([sw])
    for p in parts:
        s.update(p[2])
    return Strip(sw, d, sorted(s))


def strip_of_frame(b):
    return Strip(W, bytearray(b), [0, W])


def page_of(st, a, b):
    o = blank(); w = b - a; off = (W - w) // 2
    for y in range(W):
        for x in range(w):
            if st.d[y * st.w + a + x]:
                o[y * W + off + x] = 1
    return (o, [c - a + off for c in st.cuts if a < c <= b])


def pages_of(st):
    if st.w <= W:
        return [page_of(st, 0, st.w)]
    pages = []; s = 0
    while s < st.w:
        e = s
        for c in st.cuts:
            if c > s and c - s <= W:
                e = c
        if e == s:
            e = min(st.w, s + W)
        pages.append(page_of(st, s, e)); s = e
    return pages


def view(st, ox, oy=0, wave=False, t=0):
    o = blank()
    for x in range(W):
        sx = ox + x
        if sx < 0 or sx >= st.w:
            continue
        dy = js_round(2.2 * math.sin(sx * 0.42 + t * 0.35)) if wave else 0
        for y in range(W):
            sy = y - dy - (oy or 0)
            if 0 <= sy < W and st.d[sy * st.w + sx]:
                o[y * W + x] = 1
    return o


def shift_f(b, dx, dy):
    o = blank()
    for y in range(W):
        ny = y + dy
        if ny < 0 or ny >= W:
            continue
        for x in range(W):
            nx = x + dx
            if b[y * W + x] and 0 <= nx < W:
                o[ny * W + nx] = 1
    return o


def or_f(a, b):
    return bytearray(x | y for x, y in zip(a, b))


def inv_f(b):
    return bytearray(0 if v else 1 for v in b)


def lit_box(b):
    x0, x1 = W, -1
    for i in range(A):
        if b[i]:
            x = i % W
            if x < x0: x0 = x
            if x > x1: x1 = x
    return None if x1 < 0 else (x0, x1)


def rng(seed):
    st = [(seed & M32) or 1]

    def nxt():
        s = st[0]
        s = (s ^ (s << 13)) & M32
        si = s - (1 << 32) if s >= (1 << 31) else s      # JS の >> は符号付き
        s = (s ^ (si >> 17)) & M32
        s = (s ^ (s << 5)) & M32
        st[0] = s
        return s / 4294967296
    return nxt


def zoom_f(b, k):
    o = blank()
    if k <= 0:
        return o
    for y in range(W):
        sy = math.floor((y - 7.5) / k + 7.5 + 1e-6)
        for x in range(W):
            sx = math.floor((x - 7.5) / k + 7.5 + 1e-6)
            if 0 <= sx < W and 0 <= sy < W and b[sy * W + sx]:
                o[y * W + x] = 1
    return o


# JS (V8) の Math.pow と1桁ずれる所があるので、整数のはやさは JS の値を表にしておく
_STEP_JS = {1: 160.0, 2: 124.0, 3: 96.10000000000001, 4: 74.4775, 5: 57.720062500000004,
            6: 44.7330484375, 7: 34.668112539062506, 8: 26.86778721777344,
            9: 20.822535093774416, 10: 16.137464697675174}


def step_ms(spd):
    s = max(1, min(10, spd))
    if s == int(s):
        return _STEP_JS[int(s)]
    return 160 * math.pow(0.775, s - 1)


def lv_bri(lv):
    return max(1, min(16, int(lv))) * 16 - 1


class Frame:
    __slots__ = ("b", "ms", "bri")

    def __init__(self, b, ms, bri):
        self.b, self.ms, self.bri = b, ms, bri


class Emitter:
    def __init__(self, bri):
        self.f = []; self.bri = bri; self.cap = 60000

    def emit(self, b, ms, bri=None):
        br = self.bri if bri is None else max(0, min(255, js_round(bri)))
        if self.f:
            last = self.f[-1]
            if last.bri == br and last.b == b:
                last.ms += ms; return
        if len(self.f) >= self.cap:
            raise ValueError("コマが多すぎます (はやさを上げるか文を短くしてください)")
        self.f.append(Frame(bytearray(b), ms, br))


SCROLLS = ("scrollL", "scrollR", "scrollU", "wave")


def transition(E, a, b, eff, ms, cutsB, cutsA, is_out):
    T = W
    if eff == "slideL":
        for t in range(1, T + 1): E.emit(or_f(shift_f(a, -t, 0), shift_f(b, T - t, 0)), ms)
    elif eff == "slideR":
        for t in range(1, T + 1): E.emit(or_f(shift_f(a, t, 0), shift_f(b, t - T, 0)), ms)
    elif eff == "slideU":
        for t in range(1, T + 1): E.emit(or_f(shift_f(a, 0, -t), shift_f(b, 0, T - t)), ms)
    elif eff == "slideD":
        for t in range(1, T + 1): E.emit(or_f(shift_f(a, 0, t), shift_f(b, 0, t - T)), ms)
    elif eff == "wipe":
        for t in range(1, T + 1):
            E.emit(bytearray(b[i] if (i % W) < t else a[i] for i in range(A)), ms)
    elif eff == "dissolve":
        r = rng(1234); p = list(range(A))
        for i in range(A - 1, 0, -1):
            j = math.floor(r() * (i + 1)); p[i], p[j] = p[j], p[i]
        o = bytearray(a)
        for s in range(16):
            for k in range(s * 16, s * 16 + 16):
                o[p[k]] = b[p[k]]
            E.emit(bytearray(o), ms)
    elif eff == "type":
        src = a if is_out else b
        cuts = (cutsA if is_out else cutsB) or []
        cs = [c for c in cuts if c > 0]; box = lit_box(src)
        if len(cs) < 2:
            return transition(E, a, b, "wipe", ms, cutsB, cutsA, is_out)
        seq = (list(reversed(cs[:-1])) + [box[0] if box else 0]) if is_out else cs
        for c in seq:
            E.emit(bytearray(src[i] if (i % W) < c else 0 for i in range(A)), ms * 3)
        if is_out:
            E.emit(blank(), ms * 3)
    elif eff == "drop":
        src = a if is_out else b
        for t in range(1, T + W + 1):
            o = blank()
            for x in range(W):
                p = max(0, min(T, t - x))
                dy = p if is_out else p - T
                for y in range(W):
                    sy = y - dy
                    if 0 <= sy < W and src[sy * W + x]:
                        o[y * W + x] = 1
            E.emit(o, ms / 2)
    elif eff == "fade":
        if is_out:
            for k in range(15, -1, -1): E.emit(a, ms * 1.5, E.bri * k / 16)
        else:
            for k in range(1, 17): E.emit(b, ms * 1.5, E.bri * k / 16)
    elif eff == "zoom":
        for k in range(1, 9):
            E.emit(zoom_f(a, 1 - k / 8) if is_out else zoom_f(b, k / 8), ms * 1.5)
    E.emit(b, 1)


def _num(v, default):
    """JS の (v||default) に合わせる"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return v if v and not math.isnan(v) else default


def _int0(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def render_scene(sc):
    E = Emitter(lv_bri(_num(sc.get("bri"), 8)))
    ms = step_ms(_num(sc.get("speed"), 5))
    hold = max(0.2, _num(sc.get("hold"), 2)) * 1000
    loops = max(1, min(20, _int0(sc.get("loops")) or 1))
    bl = blank()
    sin, sout = sc.get("in"), sc.get("out")
    if sc.get("kind") == "anim":
        fr = [from_rows(r) for r in (sc.get("frames") or [])]
        if not fr:
            return E.f
        fms = 1000 / max(1, min(30, _num(sc.get("fps"), 8)))
        seq = fr + list(reversed(fr[1:-1])) if sc.get("show") == "pingpong" and len(fr) > 2 else fr
        transition(E, bl, seq[0], sin, ms, None, None, False)
        t = 0; i = 0
        while True:
            last = seq[i % len(seq)]; E.emit(last, fms); t += fms; i += 1
            if not (t < hold or i % len(seq)):
                break
        transition(E, last, bl, sout, ms, None, None, True)
        return E.f

    if sc.get("kind") == "mark":
        st = strip_of_frame(from_rows(sc.get("rows") or []))
    else:
        st = text_strip(sc.get("text"), 8 if sc.get("size") == 8 else 16, bool(sc.get("bold")))
    if st.w == 0:
        return E.f
    show = sc.get("show") or "static"

    if show in ("scrollL", "scrollR", "wave"):
        t = 0
        for _ in range(loops):
            if show == "scrollR":
                for o in range(st.w, -W - 1, -1): E.emit(view(st, o, 0), ms)
            else:
                for o in range(-W, st.w + 1):
                    E.emit(view(st, o, 0, show == "wave", t), ms); t += 1
        return E.f
    if show == "bounce" and st.w > W:
        v0 = view(st, 0, 0); end = st.w - W
        transition(E, bl, v0, sin, ms, None, None, False)
        for _ in range(loops):
            for o in range(0, end + 1): E.emit(view(st, o, 0), ms)
            E.emit(view(st, end, 0), hold / 2)
            for o in range(end, -1, -1): E.emit(view(st, o, 0), ms)
            E.emit(v0, hold / 2)
        transition(E, v0, bl, sout, ms, None, None, True)
        return E.f
    pages = [(from_rows(sc.get("rows") or []), None)] if sc.get("kind") == "mark" else pages_of(st)
    if show == "scrollU":
        for _ in range(loops):
            prev = bl
            for pb, _c in pages:
                transition(E, prev, pb, "slideU", ms, None, None, False); E.emit(pb, hold); prev = pb
            transition(E, prev, bl, "slideU", ms, None, None, True)
        return E.f
    transition(E, bl, pages[0][0], sin, ms, pages[0][1], None, False)
    cur = pages[0]
    for pi, p in enumerate(pages):
        if pi > 0:
            eff = "slideL" if sin in ("none", "fade", "zoom") else sin
            transition(E, cur[0], p[0], eff, ms, p[1], cur[1], False); cur = p
        b = p[0]
        if show in ("blink", "invert"):
            per = max(80, ms * 6); t = 0; on = True
            while t < hold:
                E.emit(b if on else (bl if show == "blink" else inv_f(b)), per); t += per; on = not on
            E.emit(b, 1)
        elif show == "breathe":
            n = max(8, js_round(hold / max(30, ms * 1.5)))
            cyc = max(1, js_round(hold / 2000))
            for k in range(n):
                E.emit(b, hold / n, E.bri * (0.12 + 0.88 * (0.5 + 0.5 * math.cos(k / n * 2 * math.pi * cyc))))
            E.emit(b, 1, E.bri)
        elif show == "bounce":
            bx = lit_box(b)
            if not bx:
                E.emit(b, hold)
            else:
                lo, hi = -bx[0], W - 1 - bx[1]
                for _ in range(loops):
                    for d in range(0, lo - 1, -1): E.emit(shift_f(b, d, 0), ms * 2)
                    for d in range(lo, hi + 1): E.emit(shift_f(b, d, 0), ms * 2)
                    for d in range(hi, -1, -1): E.emit(shift_f(b, d, 0), ms * 2)
                E.emit(b, hold / 2)
        else:
            E.emit(b, hold)
    transition(E, cur[0], bl, sout, ms, None, cur[1], True)
    return E.f


def render_program(scenes):
    out = []
    for sc in scenes:
        out.extend(render_scene(sc))
    for f in out:
        f.ms = max(1, js_round(f.ms))
    return out


# ------------------------------------------------------------------
# 番組 (ヘッダー/フッター込みの並び。src/program.js の programSequence と同じ)
# ------------------------------------------------------------------
def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def program_sequence(prog):
    scenes = list(prog.get("scenes") or [])
    hf = []
    for key in ("header", "footer"):
        x = prog.get(key) or {}
        if x.get("on") and x.get("scene"):
            hf.append((key, max(1, _int0(x.get("every")) or 1), x["scene"]))
    L = 1
    for _k, ev, _s in hf:
        L = L * ev // _gcd(L, ev)
    out = []
    for c in range(L):
        for k, ev, s in hf:
            if k == "header" and c % ev == 0: out.append(s)
        out.extend(scenes)
        for k, ev, s in hf:
            if k == "footer" and c % ev == 0: out.append(s)
    return out, L


# ------------------------------------------------------------------
# .hxm ('HXM1' / u32 コマ数 / コマごとに u16 ms, u8 明るさ, 32バイト)
# ------------------------------------------------------------------
def bake_bin(frames):
    parts = []
    for f in frames:
        ms = int(f.ms)
        while ms > 0:
            m = min(65535, ms); parts.append((m, f.bri, f.b)); ms -= m
    o = bytearray(b"HXM1" + struct.pack("<I", len(parts)))
    for m, bri, b in parts:
        o += struct.pack("<HB", m, bri) + to_bytes(b)
    return bytes(o)


def parse_hxm(data):
    """→ [(ms, bri, 32バイト)]"""
    if data[:4] != b"HXM1":
        raise ValueError("HXM1 ではありません")
    n = struct.unpack_from("<I", data, 4)[0]
    if 8 + n * 35 > len(data):
        raise ValueError("ファイルが途中で切れています")
    out = []
    for i in range(n):
        q = 8 + i * 35
        ms, bri = struct.unpack_from("<HB", data, q)
        out.append((ms, bri, bytes(data[q + 3:q + 35])))
    return out


def say_scene(text, show="scrollL", speed=6, bri=8, size=16, hold=2, loops=1, eff="none", bold=False):
    """本体アプリの「ことば」用の手早いシーン"""
    return {"kind": "text", "text": text, "size": size, "bold": bold, "show": show,
            "in": eff, "out": eff, "speed": speed, "hold": hold, "loops": loops, "bri": bri}


if __name__ == "__main__":
    import sys
    load_fonts()
    txt = sys.argv[1] if len(sys.argv) > 1 else "HEXA"
    fr = render_program([say_scene(txt, show="static")])
    b = fr[0].b
    print("\n".join("".join("#" if b[y * W + x] else "." for x in range(W)) for y in range(W)))
