"""src/ から1枚の hexa-matrix-studio.html を組み立てる"""
import json, os
D = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(D, "src/studio.html"), encoding="utf-8").read()
s = s.replace("/*@@ENGINE@@*/", open(os.path.join(D, "src/engine.js"), encoding="utf-8").read())
s = s.replace("/*@@PROGRAM@@*/", open(os.path.join(D, "src/program.js"), encoding="utf-8").read())
s = s.replace("/*@@ANIM@@*/", open(os.path.join(D, "src/anim.js"), encoding="utf-8").read())
s = s.replace("/*@@DEVICE@@*/", open(os.path.join(D, "src/device.js"), encoding="utf-8").read())
fd = json.load(open(os.path.join(D, "src/fonts.json")))
s = s.replace("@@FONTDATA@@", json.dumps(fd, separators=(",", ":")))
assert "@@" not in s.replace("@@ENGINE@@", "").replace("@@PROGRAM@@", "").replace("@@DEVICE@@", "").replace("@@ANIM@@", ""), "置き換え漏れ"
open(os.path.join(D, "hexa-matrix-studio.html"), "w", encoding="utf-8").write(s)
print("hexa-matrix-studio.html", len(s.encode()) // 1024, "KB")
