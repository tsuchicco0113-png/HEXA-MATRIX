"""cpz/hxengine.py が STUDIO と同じコマ列を作るか確かめる (先に node tests/engine_cases.js)"""
import json,sys,base64,os
D=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,os.path.join(D,'..','cpz'))
import hxengine as H
H.load_fonts(os.path.join(D,'..','src','fonts.json'))
cs=json.load(open(os.path.join(D,'cases.json'))); bad=0; nf=0
for c in cs:
    f=H.render_scene(c['sc']); raw=[[x.ms,x.bri] for x in f]
    b=H.bake_bin(H.render_program([c['sc']]))
    nf+=len(f)
    if raw!=c['raw'] or base64.b64encode(b).decode()!=c['bin']:
        bad+=1
        if bad<4:
            print('NG',c['sc']['kind'],c['sc'].get('show'),c['sc'].get('in'),c['sc'].get('out'),len(raw),len(c['raw']))
            for i,(p,q) in enumerate(zip(raw,c['raw'])):
                if p!=q: print(' first diff',i,p,q); break
print('cases',len(cs),'frames',nf,'NG',bad)
sys.exit(1 if bad else 0)
