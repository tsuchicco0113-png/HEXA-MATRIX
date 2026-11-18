"""箱庭のプレビュー GIF を作る (tools/hako_sim.cpp の出力から)。python3 tools/hako_gif.py sim.txt → hakoniwa_preview.gif"""
from PIL import Image, ImageDraw, ImageFont
import math, sys
import glob
_F=(glob.glob("/usr/share/fonts/**/NotoSansCJK-Regular.ttc",recursive=True)+glob.glob("/System/Library/Fonts/*Hiragino*")+glob.glob("C:/Windows/Fonts/meiryo.ttc")+[None])[0]
fnt=ImageFont.truetype(_F,22) if _F else ImageFont.load_default(); fs=ImageFont.truetype(_F,15) if _F else ImageFont.load_default()
ST=["待機","歩く","空中","着地","目が回る","寝る","起きた","うれしい"]
def draw(ang,st,lab,slp,bits):
    S=420; im=Image.new("RGB",(S,S),(14,14,16)); d=ImageDraw.Draw(im)
    dev=Image.new("RGBA",(400,400),(0,0,0,0)); dd=ImageDraw.Draw(dev)
    dd.rounded_rectangle((60,60,340,340),28,fill=(30,30,34),outline=(70,70,78),width=3)
    dd.rounded_rectangle((182,44,218,64),6,fill=(255,176,46))          # 吊り穴 (ストラップ) の印
    dd.rounded_rectangle((192,50,208,58),3,fill=(14,14,16))
    pitch=16.2; x0=200-7.5*pitch; y0=200-7.5*pitch
    on=(235,240,255) if not slp else (120,125,150)
    for y in range(16):
        for x in range(16):
            b=(bits[y*2+(x>>3)]>>(7-(x&7)))&1
            cx=x0+x*pitch; cy=y0+y*pitch; r=5.2 if b else 2.0
            dd.ellipse((cx-r,cy-r,cx+r,cy+r),fill=on if b else (52,58,66))
    # 画面は「吊るした時に正立」する向き。本体の傾き (反時計回り +) だけ回す
    dev=dev.rotate(ang,expand=False,resample=Image.BICUBIC)
    im.paste(dev,(10,30),dev)
    a=math.radians(ang)
    hx=210-140*math.sin(a); hy=230-140*math.cos(a)        # 吊り穴 (画面の上辺の真ん中)
    if abs(ang)<30: d.line((210,0,hx,hy),fill=(150,150,160),width=3)
    d.text((10,8),lab,font=fnt,fill=(255,176,46))
    d.text((10,392),"状態: "+ST[st],font=fs,fill=(200,200,210))
    return im
def parse(ln):
    ang,st,lab,slp,hexs=ln.rstrip("\n").split("|")
    return float(ang),int(st),lab,int(slp),bytes.fromhex(hexs)
if __name__=="__main__":
    src=sys.argv[1] if len(sys.argv)>1 else "sim.txt"
    fr=[draw(*parse(l)) for l in open(src)]
    fr[0].save("hakoniwa_preview.gif",save_all=True,append_images=fr[1:],duration=33,loop=0,optimize=True)
    lines=open(src).read().splitlines()
    want=[3.0,5.3,5.5,8.6,10.8,12.6,13.6,19.5,21.6,22.4]
    tiles=[draw(*parse(lines[int(s*30)])).resize((280,280)) for s in want]
    W=Image.new("RGB",(280*5,280*2))
    for k,t in enumerate(tiles): W.paste(t,((k%5)*280,(k//5)*280))
    W.save("preview_sheet.png")
