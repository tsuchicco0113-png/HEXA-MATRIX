// ============================================================
// 描画エンジン (DOMに触れない。CPZ側へ移すときはこの部分を写す)
//   シーン → コマ列 [{b:Uint8Array(256), ms, bri(0〜255)}]
// ============================================================
const FONT={};                                  // {16:{H,map}, 8:{H,map}}
function b64bytes(s){ const t=atob(s), o=new Uint8Array(t.length); for(let i=0;i<t.length;i++) o[i]=t.charCodeAt(i); return o; }
async function inflateRaw(u8){
  const st=new Blob([u8]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(st).arrayBuffer());
}
/// 形式は fonts/mkfont.py を参照 ('HXF1' / 高さ / 字数 / 差分varint / 幅 / ビットマップ)
function parseFont(raw){
  if(String.fromCharCode(raw[0],raw[1],raw[2],raw[3])!=="HXF1") throw new Error("フォントの形式が違います");
  const H=raw[4], n=(raw[5]|raw[6]<<8|raw[7]<<16|raw[8]<<24)>>>0;
  let p=9, c=0; const cps=new Uint32Array(n);
  for(let i=0;i<n;i++){ let d=0,s=0,b; do{ b=raw[p++]; d+=(b&127)*Math.pow(2,s); s+=7; }while(b&128); c+=d; cps[i]=c; }
  const ws=raw.subarray(p,p+n); p+=n;
  const map=new Map();
  for(let i=0;i<n;i++){
    const w=ws[i], nb=(w+7)>>3, rows=new Uint16Array(H);
    for(let y=0;y<H;y++){ let v=0; for(let k=0;k<nb;k++) v=(v<<8)|raw[p++]; rows[y]=(nb===1)?(v<<8):v; }
    map.set(cps[i],{w:w,rows:rows});
  }
  return {H:H,map:map};
}
async function loadFonts(){
  const j=JSON.parse(document.getElementById("fontdata").textContent);
  FONT[16]=parseFont(await inflateRaw(b64bytes(j.g16)));
  FONT[8]=parseFont(await inflateRaw(b64bytes(j.g8)));
}

const W=16, A=256;
const blankF=()=>new Uint8Array(A);
function glyph(f,ch){ return f.map.get(ch.codePointAt(0)) || f.map.get(0x3F) || null; }

/// 文字を横長の帯 {w,h:16,d,cuts} にする。cuts は字の切れ目 (ページ送りと1字ずつ表示に使う)
function textStrip(text,size,bold){
  const f=FONT[size];
  let lines=String(text==null?"":text).replace(/\r/g,"").split("\n");
  if(size===16) lines=[lines.join(" ")]; else lines=lines.slice(0,2);
  const bw=bold?1:0;
  const parts=lines.map(l=>{
    const gs=[...l].map(ch=>glyph(f,ch)).filter(Boolean);
    let w=0; const cuts=[0];
    for(const g of gs){ w+=g.w+bw; cuts.push(w); }
    return {gs:gs,w:w,cuts:cuts};
  });
  const sw=Math.max(0,...parts.map(p=>p.w));
  const st={w:sw,h:W,d:new Uint8Array(Math.max(1,sw)*W),cuts:[]};
  const y0s = size===16 ? [0] : (parts.length===1 ? [4] : [0,8]);
  parts.forEach((p,li)=>{
    let x=0;
    for(const g of p.gs){
      for(let y=0;y<f.H;y++){
        const r=g.rows[y], yy=y0s[li]+y; if(yy>=W) continue;
        for(let i=0;i<g.w;i++) if(r&(0x8000>>i)){ st.d[yy*sw+x+i]=1; if(bw) st.d[yy*sw+x+i+1]=1; }
      }
      x+=g.w+bw;
    }
  });
  const set=new Set(); parts.forEach(p=>p.cuts.forEach(c=>set.add(c))); set.add(sw);
  st.cuts=[...set].sort((a,b)=>a-b);
  return st;
}
function stripOfFrame(b){ return {w:W,h:W,d:Uint8Array.from(b),cuts:[0,W]}; }
/// 帯の a〜b 列を16×16の真ん中に置いたページ
function pageOf(st,a,b){
  const o=blankF(), w=b-a, off=Math.floor((W-w)/2);
  for(let y=0;y<W;y++) for(let x=0;x<w;x++) if(st.d[y*st.w+a+x]) o[y*W+off+x]=1;
  return {b:o, cuts:st.cuts.filter(c=>c>a&&c<=b).map(c=>c-a+off)};
}
/// 字の切れ目で16列以内に区切ってページにする
function pagesOf(st){
  if(st.w<=W) return [pageOf(st,0,st.w)];
  const pages=[]; let s=0;
  while(s<st.w){
    let e=s; for(const c of st.cuts) if(c>s && c-s<=W) e=c;
    if(e===s) e=Math.min(st.w,s+W);
    pages.push(pageOf(st,s,e)); s=e;
  }
  return pages;
}
function view(st,ox,oy,wave,t){                 // 帯を ox だけずらして16×16を切り出す
  const o=blankF();
  for(let x=0;x<W;x++){
    const sx=ox+x; if(sx<0||sx>=st.w) continue;
    const dy = wave ? Math.round(2.2*Math.sin(sx*0.42+t*0.35)) : 0;
    for(let y=0;y<W;y++){ const sy=y-dy-(oy||0); if(sy>=0&&sy<W&&st.d[sy*st.w+sx]) o[y*W+x]=1; }
  }
  return o;
}
function shiftF(b,dx,dy){
  const o=blankF();
  for(let y=0;y<W;y++) for(let x=0;x<W;x++){ const nx=x+dx, ny=y+dy; if(b[y*W+x]&&nx>=0&&nx<W&&ny>=0&&ny<W) o[ny*W+nx]=1; }
  return o;
}
function orF(a,b){ const o=new Uint8Array(A); for(let i=0;i<A;i++) o[i]=a[i]|b[i]; return o; }
function invF(b){ return b.map(v=>v?0:1); }
function sameF(a,b){ for(let i=0;i<A;i++) if(a[i]!==b[i]) return false; return true; }
function litBox(b){
  let x0=W,x1=-1; for(let i=0;i<A;i++) if(b[i]){ const x=i%W; if(x<x0)x0=x; if(x>x1)x1=x; }
  return x1<0?null:{x0:x0,x1:x1};
}
function rng(seed){ let s=seed>>>0||1; return ()=>{ s^=s<<13; s>>>=0; s^=s>>17; s^=s<<5; s>>>=0; return s/4294967296; }; }
function zoomF(b,k){                             // 中心から k 倍 (0〜1) に縮めた絵
  const o=blankF(); if(k<=0) return o;
  for(let y=0;y<W;y++) for(let x=0;x<W;x++){
    const sx=Math.floor((x-7.5)/k+7.5+1e-6), sy=Math.floor((y-7.5)/k+7.5+1e-6);
    if(sx>=0&&sx<W&&sy>=0&&sy<W&&b[sy*W+sx]) o[y*W+x]=1;
  }
  return o;
}

/// 1コマ1ステップの長さ。はやさ 1→160ms、10→約16ms
const stepMs=spd=>160*Math.pow(0.775,Math.max(1,Math.min(10,spd))-1);
const lvBri=lv=>Math.max(1,Math.min(16,lv|0))*16-1;

class Emitter{
  constructor(bri){ this.f=[]; this.bri=bri; this.cap=60000; }
  emit(b,ms,bri){
    const br=(bri==null)?this.bri:Math.max(0,Math.min(255,Math.round(bri)));
    const last=this.f[this.f.length-1];
    if(last && last.bri===br && sameF(last.b,b)){ last.ms+=ms; return; }   // 同じ絵は伸ばすだけ
    if(this.f.length>=this.cap) throw new Error("コマが多すぎます (はやさを上げるか文を短くしてください)");
    this.f.push({b:b,ms:ms,bri:br});
  }
}
const SCROLLS=["scrollL","scrollR","scrollU","wave"];

/// A→B の切り替え。入り方でも出方でも同じ式 (入り方は A=空、出方は B=空)
function transition(E,a,b,eff,ms,cutsB,cutsA,isOut){
  const T=W;
  switch(eff){
    case "slideL": for(let t=1;t<=T;t++) E.emit(orF(shiftF(a,-t,0),shiftF(b,T-t,0)),ms); break;
    case "slideR": for(let t=1;t<=T;t++) E.emit(orF(shiftF(a,t,0),shiftF(b,t-T,0)),ms); break;
    case "slideU": for(let t=1;t<=T;t++) E.emit(orF(shiftF(a,0,-t),shiftF(b,0,T-t)),ms); break;
    case "slideD": for(let t=1;t<=T;t++) E.emit(orF(shiftF(a,0,t),shiftF(b,0,t-T)),ms); break;
    case "wipe":
      for(let t=1;t<=T;t++){ const o=blankF(); for(let i=0;i<A;i++) o[i]=(i%W)<t?b[i]:a[i]; E.emit(o,ms); } break;
    case "dissolve":{
      const r=rng(1234), p=[...Array(A).keys()];
      for(let i=A-1;i>0;i--){ const j=Math.floor(r()*(i+1)); const t=p[i]; p[i]=p[j]; p[j]=t; }
      const o=Uint8Array.from(a);
      for(let s=0;s<16;s++){ for(let k=s*16;k<s*16+16;k++) o[p[k]]=b[p[k]]; E.emit(Uint8Array.from(o),ms); }
      break; }
    case "type":{
      const src=isOut?a:b, cuts=(isOut?cutsA:cutsB)||[];
      const cs=cuts.filter(c=>c>0); const box=litBox(src);
      if(cs.length<2){ return transition(E,a,b,"wipe",ms,cutsB,cutsA,isOut); }
      const seq=isOut?cs.slice(0,-1).reverse().concat([box?box.x0:0]):cs;
      for(const c of seq){ const o=blankF(); for(let i=0;i<A;i++) if((i%W)<c) o[i]=src[i]; E.emit(o,ms*3); }
      if(isOut) E.emit(blankF(),ms*3);
      break; }
    case "drop":{
      for(let t=1;t<=T+W;t++){
        const o=blankF();
        for(let x=0;x<W;x++){
          const p=Math.max(0,Math.min(T,t-x));
          const src=isOut?a:b, dy=isOut?p:p-T;
          for(let y=0;y<W;y++){ const sy=y-dy; if(sy>=0&&sy<W&&src[sy*W+x]) o[y*W+x]=1; }
        }
        E.emit(o,ms/2);
      }
      break; }
    case "fade":
      if(isOut) for(let k=15;k>=0;k--) E.emit(a,ms*1.5,E.bri*k/16);
      else for(let k=1;k<=16;k++) E.emit(b,ms*1.5,E.bri*k/16);
      break;
    case "zoom":
      for(let k=1;k<=8;k++) E.emit(isOut?zoomF(a,1-k/8):zoomF(b,k/8),ms*1.5);
      break;
    default: break;                                // "none" はすぐ切り替える
  }
  E.emit(b,1);
}

/// sc: {kind:"text"|"mark"|"anim", text,size,bold, rows, frames:[rows], fps,
///      in, show, out, speed(1〜10), hold(秒), loops, bri(1〜16)}
function renderScene(sc){
  const E=new Emitter(lvBri(sc.bri||8)), ms=stepMs(sc.speed||5), hold=Math.max(0.2,+sc.hold||2)*1000;
  const loops=Math.max(1,Math.min(20,sc.loops|0||1)), blank=blankF();
  if(sc.kind==="anim"){
    const fr=(sc.frames||[]).map(fromRows); if(!fr.length) return E.f;
    const fms=1000/Math.max(1,Math.min(30,sc.fps||8));
    const seq = sc.show==="pingpong" && fr.length>2 ? fr.concat(fr.slice(1,-1).reverse()) : fr;
    transition(E,blank,seq[0],sc.in,ms,null,null,false);
    let t=0, i=0, last=seq[0];
    do{ last=seq[i%seq.length]; E.emit(last,fms); t+=fms; i++; }while(t<hold || i%seq.length);
    transition(E,last,blank,sc.out,ms,null,null,true);
    return E.f;
  }
  let st;
  if(sc.kind==="mark") st=stripOfFrame(fromRows(sc.rows||[]));
  else st=textStrip(sc.text,sc.size===8?8:16,!!sc.bold);
  if(st.w===0) return E.f;
  const show=sc.show||"static";

  if(show==="scrollL"||show==="scrollR"||show==="wave"){
    let t=0;
    for(let l=0;l<loops;l++){
      if(show==="scrollR") for(let o=st.w;o>=-W;o--) E.emit(view(st,o,0),ms);
      else for(let o=-W;o<=st.w;o++) E.emit(view(st,o,0,show==="wave",t++),ms);
    }
    return E.f;
  }
  if(show==="bounce" && st.w>W){                 // 長い文は帯ごと端から端へ往復させる
    const v0=view(st,0,0), end=st.w-W;
    transition(E,blank,v0,sc.in,ms,null,null,false);
    for(let l=0;l<loops;l++){
      for(let o=0;o<=end;o++) E.emit(view(st,o,0),ms);
      E.emit(view(st,end,0),hold/2);
      for(let o=end;o>=0;o--) E.emit(view(st,o,0),ms);
      E.emit(v0,hold/2);
    }
    transition(E,v0,blank,sc.out,ms,null,null,true);
    return E.f;
  }
  const pages = sc.kind==="mark" ? [{b:fromRows(sc.rows||[]),cuts:null}] : pagesOf(st);
  if(show==="scrollU"){
    for(let l=0;l<loops;l++){
      let prev=blank;
      for(const p of pages){ transition(E,prev,p.b,"slideU",ms,null,null,false); E.emit(p.b,hold); prev=p.b; }
      transition(E,prev,blank,"slideU",ms,null,null,true);
    }
    return E.f;
  }
  // ここから下は「止めて見せる」系。入り方 → 見せ方 → 出方
  transition(E,blank,pages[0].b,sc.in,ms,pages[0].cuts,null,false);
  let cur=pages[0];
  pages.forEach((p,pi)=>{
    if(pi>0){
      const eff=(sc.in==="none"||sc.in==="fade"||sc.in==="zoom")?"slideL":sc.in;   // ページの間は流して見せる
      transition(E,cur.b,p.b,eff,ms,p.cuts,cur.cuts,false); cur=p;
    }
    const b=p.b;
    if(show==="blink"||show==="invert"){
      const per=Math.max(80,ms*6); let t=0, on=true;
      while(t<hold){ E.emit(on?b:(show==="blink"?blank:invF(b)),per); t+=per; on=!on; }
      E.emit(b,1);
    }else if(show==="breathe"){
      const n=Math.max(8,Math.round(hold/Math.max(30,ms*1.5)));
      for(let k=0;k<n;k++) E.emit(b,hold/n,E.bri*(0.12+0.88*(0.5+0.5*Math.cos(k/n*2*Math.PI*Math.max(1,Math.round(hold/2000))))));
      E.emit(b,1,E.bri);
    }else if(show==="bounce"){
      const bx=litBox(b);
      if(!bx) E.emit(b,hold);
      else{
        const lo=-bx.x0, hi=W-1-bx.x1;
        for(let l=0;l<loops;l++){
          for(let d=0;d>=lo;d--) E.emit(shiftF(b,d,0),ms*2);
          for(let d=lo;d<=hi;d++) E.emit(shiftF(b,d,0),ms*2);
          for(let d=hi;d>=0;d--) E.emit(shiftF(b,d,0),ms*2);
        }
        E.emit(b,hold/2);
      }
    }else{
      E.emit(b,hold);
    }
  });
  transition(E,cur.b,blank,sc.out,ms,null,cur.cuts,true);
  return E.f;
}
function renderProgram(scenes){
  let out=[];
  for(const sc of scenes){ const f=renderScene(sc); f.forEach(x=>x.scene=sc); out=out.concat(f); }
  for(const f of out) f.ms=Math.max(1,Math.round(f.ms));
  return out;
}
/// コマ列のバイナリ: 'HXM1' / u32 コマ数 / コマごとに u16 ms, u8 明るさ, 32バイト
function bakeBin(frames){
  const parts=[];
  for(const f of frames){ let ms=f.ms; while(ms>0){ const m=Math.min(65535,ms); parts.push([m,f.bri,f.b]); ms-=m; } }
  const o=new Uint8Array(8+parts.length*35), dv=new DataView(o.buffer);
  o.set([0x48,0x58,0x4D,0x31]); dv.setUint32(4,parts.length,true);
  parts.forEach((p,i)=>{ const q=8+i*35; dv.setUint16(q,p[0],true); o[q+2]=p[1]; o.set(toBytes(p[2]),q+3); });
  return o;
}
