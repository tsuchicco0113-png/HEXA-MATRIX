// STUDIO (engine.js) で色々なシーンを描いて tests/cases.json に書く。続けて python3 tests/engine_parity.py
const fs=require('fs'), path=require('path'); const R_=p=>path.join(__dirname,'..',p);
global.document={getElementById:()=>({textContent:fs.readFileSync(R_('src/fonts.json'),'utf8')})};
const N=16,NN=256;
function fromRows(r){ const b=new Uint8Array(NN); for(let y=0;y<N;y++)for(let x=0;x<N;x++) if((r[y]|0)&(0x8000>>x)) b[y*N+x]=1; return b; }
function toBytes(b){ const o=new Uint8Array(32); for(let y=0;y<16;y++){ let w=0; for(let x=0;x<16;x++) if(b[y*16+x]) w|=0x8000>>x; o[y*2]=w>>8; o[y*2+1]=w&255;} return o; }
eval(fs.readFileSync(R_('src/engine.js'),'utf8')+';global.E={loadFonts,renderScene,renderProgram,bakeBin}');
(async()=>{
  await E.loadFonts();
  const HEART=[0x0000,0x1E78,0x3FFC,0x7FFE,0x7FFE,0x7FFE,0x7FFE,0x3FFC,0x1FF8,0x0FF0,0x0FF0,0x07E0,0x03C0,0x0180,0,0];
  const ins=["none","slideL","slideR","slideU","slideD","wipe","type","dissolve","drop","fade","zoom"];
  const shows=["static","scrollL","scrollR","scrollU","wave","bounce","blink","invert","breathe"];
  const texts=["営業中","A","ようこそ\nHEXA","HEXA STAGE ｺﾞﾏｴﾋﾞ","𠀋☃","", "ありがとうございました本日"];
  let s=7; const R=n=>{ s=(s*1103515245+12345)&0x7fffffff; return s%n; };
  const cases=[];
  for(const kind of ["text","mark"]) for(const show of shows) for(const i of ins) for(const o of [ins[R(ins.length)], i]){
    const sc={kind,show,in:i,out:o,speed:1+R(10),hold:[0.1,0.5,1,2,3.3,5][R(6)],loops:1+R(3),bri:1+R(16),
      text:texts[R(texts.length)],size:R(2)?16:8,bold:!!R(2),rows:HEART.map(v=>v>>R(3))};
    cases.push(sc);
  }
  for(const show of ["play","pingpong"]) for(const i of ins){ cases.push({kind:"anim",show,in:i,out:ins[R(ins.length)],fps:1+R(30),speed:1+R(10),hold:[0.3,1,2.5][R(3)],bri:1+R(16),frames:[HEART,HEART.map(v=>v>>1),HEART.map(v=>v<<1&0xffff)].slice(0,1+R(3))}); }
  cases.push({kind:"text",text:"x",speed:0,hold:"3",loops:"2",bri:0});
  const out=cases.map(sc=>{ const f=E.renderScene(sc); return {sc, raw:f.map(x=>[x.ms,x.bri]), bin:Buffer.from(E.bakeBin(E.renderProgram([sc]))).toString('base64')}; });
  fs.writeFileSync(path.join(__dirname,'cases.json'),JSON.stringify(out));
  console.log(out.length);
})();
