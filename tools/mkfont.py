"""BDF → HEXA MATRIX 用の小さなフォント表 (deflate-raw + base64)

形式 (すべてリトルエンディアン):
  'HXF1' / u8 高さ / u32 字数
  コードポイント: 差分を varint で字数ぶん
  幅: u8 を字数ぶん
  ビットマップ: 字ごとに 高さ×ceil(幅/8) バイト (行は上から、MSBが左)

使い方: python3 mkfont.py 出力.json
"""
import base64, json, sys, zlib

SHN = "/home/claude/fonts/shn/xfonts-shinonome-0.9.11/bdf/"
MSK = "/home/claude/fonts/misaki/"


def parse_bdf(path):
    """{ENCODING: (dwidth, rows[list of int, 各行を左詰め], bbx)} とフォント全体の (高さ, 下がり) を返す"""
    out, fb = {}, None
    with open(path, "rb") as f:
        lines = f.read().decode("latin-1").splitlines()
    i = 0
    cur = None
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("FONTBOUNDINGBOX"):
            _, w, h, x, y = ln.split()
            fb = (int(h), -int(y))
        elif ln.startswith("STARTCHAR"):
            cur = {}
        elif ln.startswith("ENCODING"):
            cur["enc"] = int(ln.split()[1])
        elif ln.startswith("DWIDTH"):
            cur["dw"] = int(ln.split()[1])
        elif ln.startswith("BBX"):
            cur["bbx"] = tuple(int(v) for v in ln.split()[1:5])
        elif ln.startswith("BITMAP"):
            w, h, _, _ = cur["bbx"]
            nb = (w + 7) // 8
            rows = []
            for k in range(h):
                v = int(lines[i + 1 + k].strip() or "0", 16)
                rows.append(v << (8 * (4 - nb)))     # 32bit の左詰めにそろえる
            cur["rows"] = rows
            i += h
        elif ln.startswith("ENDCHAR"):
            if cur.get("enc", -1) >= 0:
                out[cur["enc"]] = cur
            cur = None
        i += 1
    return out, fb


def place(g, H, D):
    """字をフォントの高さ H のセルに置き、(幅, [左詰め32bit行]) を返す"""
    w, h, xo, yo = g["bbx"]
    asc = H - D
    top = asc - (yo + h)
    cell = [0] * H
    for k, r in enumerate(g["rows"]):
        y = top + k
        if 0 <= y < H:
            cell[y] = (r >> max(0, xo)) & 0xFFFFFFFF
    return g["dw"], cell


def pack(glyphs, H):
    """glyphs: {cp: (w, rows32)}"""
    cps = sorted(glyphs)
    head = b"HXF1" + bytes([H]) + len(cps).to_bytes(4, "little")
    vd = bytearray()
    prev = 0
    for c in cps:
        d = c - prev
        prev = c
        while True:
            b = d & 0x7F
            d >>= 7
            vd.append(b | (0x80 if d else 0))
            if not d:
                break
    ws = bytes(glyphs[c][0] for c in cps)
    bm = bytearray()
    for c in cps:
        w, rows = glyphs[c]
        nb = (w + 7) // 8
        for r in rows:
            bm += (r >> (8 * (4 - nb)) & ((1 << (8 * nb)) - 1)).to_bytes(nb, "big")
    raw = head + bytes(vd) + ws + bytes(bm)
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    z = co.compress(raw) + co.flush()
    return raw, z


def shinonome16():
    g = {}
    k16, (H, D) = parse_bdf(SHN + "shnmk16.bdf")
    for enc, ch in k16.items():
        try:
            u = bytes([(enc >> 8) | 0x80, (enc & 0xFF) | 0x80]).decode("euc_jp")
        except UnicodeDecodeError:
            continue
        if len(u) == 1:
            g[ord(u)] = place(ch, H, D)
    a16, (Ha, Da) = parse_bdf(SHN + "shnm8x16a.bdf")
    for enc, ch in a16.items():
        if 0x20 <= enc <= 0x7E or 0xA0 <= enc <= 0xFF:
            g[enc] = place(ch, Ha, Da)
    r16, (Hr, Dr) = parse_bdf(SHN + "shnm8x16r.bdf")
    for enc, ch in r16.items():
        if 0xA1 <= enc <= 0xDF:                    # 半角カナ → U+FF61..U+FF9F
            g[0xFF61 + enc - 0xA1] = place(ch, Hr, Dr)
    return g, H


def misaki8():
    m, (H, D) = parse_bdf(MSK + "misaki_gothic.bdf")
    return {enc: place(ch, H, D) for enc, ch in m.items()}, H


if __name__ == "__main__":
    res = {}
    for name, (g, H) in {"g16": shinonome16(), "g8": misaki8()}.items():
        raw, z = pack(g, H)
        res[name] = base64.b64encode(z).decode()
        print(name, "字数", len(g), "高さ", H, "生", len(raw), "圧縮", len(z), "base64", len(res[name]), file=sys.stderr)
    json.dump(res, open(sys.argv[1], "w"))
