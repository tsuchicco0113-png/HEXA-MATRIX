// ============================================================
// 箱庭エンジン (JS 版)。firmware/HexaMatrixFW/hxm_char.h と同じ動きをする (同じ入力なら同じコマ)
//   ・C の整数の割り算 (0 に向かって切り捨て) は idiv()、uint8/uint16 のあふれは & で合わせる
//   ・変えたら tests/hako_parity.js で C++ と一致するか確かめる
// ============================================================
const HXC={TAP:1,SHAKE:2,PET:4,POKE:8,
  IDLE:0,WALK:1,AIR:2,LAND:3,DIZZY:4,SLEEP:5,WAKE:6,HAPPY:7,
  ST_NAME:["待機","歩く","空中","着地","目が回る","寝る","起きた","うれしい"]};
const HXC_DEFAULT={grav:26,maxv:170,bounce:80,fric:36,stick:140,jump:235,whim:120,sleepAfter:60*25,slosh:0};
const HXC_BUILTIN_ROWS=[
  "..##########..",
  ".############.",
  ".##.#########.",
  "##########.###",
  "##############",
  ".#############",
  ".############.",
  ".##.##..##.##.",
  ".##.##..##.##.",
  "..#.##..##.##."];
function idiv(a,b){ return Math.trunc(a/b); }
function hxcSpriteFromLines(lines){
  const rows=new Array(16).fill(0); let w=0; const h=Math.min(16,lines.length);
  for(let y=0;y<h;y++) for(let x=0;x<lines[y].length&&x<16;x++){ if(lines[y][x]==="#"||lines[y][x]==="1") rows[y]|=(1<<x); if(x+1>w) w=x+1; }
  return {w:w,h:h,rows:rows};
}
function hxcSprPx(s,x,y){ return x>=0&&y>=0&&x<s.w&&y<s.h&&((s.rows[y]>>x)&1)===1; }
function hxcSprSet(s,x,y,on){ if(x>=0&&y>=0&&x<16&&y<16){ if(on) s.rows[y]|=(1<<x); else s.rows[y]&=~(1<<x); s.rows[y]&=0xFFFF; } }
function hxcSprCopy(s){ return {w:s.w,h:s.h,rows:s.rows.slice()}; }

class HxcWorld{
  constructor(){ this.terrain=new Array(16).fill(0); this.sp={w:0,h:0,rows:new Array(16).fill(0)}; this.pr=Object.assign({},HXC_DEFAULT);
    this.x=0;this.y=0;this.vx=0;this.vy=0;this.q=0;this.qCand=0;this.qT=0;this.st=HXC.IDLE;this.stT=0;this.still=0;this.blinkT=0;this.whimT=0;
    this.lookX=0;this.lookY=0;this.face=1;this.walkPh=0;this.walkT=0;this.dizzyT=0;this.landT=0;this.wakeT=0;this.happyT=0;this.grounded=false;
    this.lgx=0;this.lgy=1000;this.lgz=0;this.lastWz=0;this.rng=1;this.ticks=0;this.eyeX=[-1,-1];this.eyeY=[-1,-1];this.legN=0;this.legX0=[0,0,0,0,0,0];this.legX1=[0,0,0,0,0,0];this.midRow=0; }
  init(s,p,seed){
    this.sp=hxcSprCopy(s); this.pr=Object.assign({},HXC_DEFAULT,p); this.rng=(seed>>>0)||1;
    this.analyze();
    this.q=this.qCand=0; this.qT=0;
    this.x=idiv((16-this.sp.w)<<8,2); this.y=(16-this.sp.h)<<8; this.vx=this.vy=0;
    this.st=HXC.IDLE; this.stT=this.still=0; this.blinkT=(120+this.rnd(180))&0xFFFF; this.whimT=(240+this.rnd(240))&0xFFFF;
    this.face=1; this.ticks=0;
  }
  analyze(){
    const sp=this.sp; let ne=0;
    this.eyeX=[-1,-1]; this.eyeY=[-1,-1];
    for(let yy=1;yy<sp.h-1&&ne<2;yy++)
      for(let xx=1;xx<sp.w-1&&ne<2;xx++)
        if(!hxcSprPx(sp,xx,yy)&&hxcSprPx(sp,xx-1,yy)&&hxcSprPx(sp,xx+1,yy)&&hxcSprPx(sp,xx,yy-1)&&hxcSprPx(sp,xx,yy+1)){
          if(yy<idiv(sp.h,2)+1){ this.eyeX[ne]=xx; this.eyeY[ne]=yy; ne++; }
        }
    this.legN=0; const last=sp.h-1;
    for(let xx=0;xx<sp.w&&this.legN<6;){
      if(hxcSprPx(sp,xx,last)){ const x0=xx; while(xx<sp.w&&hxcSprPx(sp,xx,last)) xx++; this.legX0[this.legN]=x0; this.legX1[this.legN]=xx-1; this.legN++; }
      else xx++;
    }
    let legTop=last;
    while(legTop>0&&sp.rows[legTop-1]===sp.rows[last]) legTop--;
    this.midRow=legTop>2?idiv(legTop,2):idiv(sp.h,2);
  }
  rnd(n){ let r=this.rng>>>0; r=(r^(r<<13))>>>0; r=(r^(r>>>17))>>>0; r=(r^(r<<5))>>>0; this.rng=r; return n?r%n:r; }
  bw(){ return (this.q&1)?this.sp.h:this.sp.w; }
  bh(){ return (this.q&1)?this.sp.w:this.sp.h; }
  static gdir(q){ return [q===1?-1:q===3?1:0, q===0?1:q===2?-1:0]; }
  static tdir(q){ return [q===0?1:q===2?-1:0, q===1?1:q===3?-1:0]; }
  solid(px,py,w,h){
    if(px<0||py<0||px+w>16||py+h>16) return true;
    const m=(((1<<w)-1)<<px)&0xFFFF;
    for(let yy=py;yy<py+h;yy++) if(this.terrain[yy]&m) return true;
    return false;
  }
  moveAxis(isX){
    const w=this.bw(), h=this.bh();
    let p=isX?this.x:this.y, v=isX?this.vx:this.vy;
    const np=p+v, from=p>>8, to=np>>8, step=to>from?1:-1;
    for(let c=from;c!==to;c+=step){
      const n=c+step;
      if(isX?this.solid(n,this.y>>8,w,h):this.solid(this.x>>8,n,w,h)){
        p=step>0?(c<<8)+255:(c<<8);
        const hit=v<0?-v:v;
        v=idiv(-(v*this.pr.bounce),256);
        if((v<0?-v:v)<24) v=0;
        if(isX){ this.x=p; this.vx=v; } else { this.y=p; this.vy=v; }
        return hit;
      }
    }
    p=np; if(p<0) p=0;
    if(isX) this.x=p; else this.y=p;
    return 0;
  }
  onFloor(){ const [dx,dy]=HxcWorld.gdir(this.q); return this.solid((this.x>>8)+dx,(this.y>>8)+dy,this.bw(),this.bh()); }
  setQ(nq){
    const cx=(this.x>>8)*2+this.bw(), cy=(this.y>>8)*2+this.bh();
    this.q=nq;
    let nx=idiv(cx-this.bw(),2), ny=idiv(cy-this.bh(),2);
    if(nx<0) nx=0; if(ny<0) ny=0;
    if(nx+this.bw()>16) nx=16-this.bw(); if(ny+this.bh()>16) ny=16-this.bh();
    for(let k=0;k<16&&this.solid(nx,ny,this.bw(),this.bh());k++){ const [dx,dy]=HxcWorld.gdir(this.q); nx-=dx; ny-=dy; }
    this.x=nx<<8; this.y=ny<<8; this.vx=this.vy=0;
  }
  enter(s){ if(this.st!==s){ this.st=s; this.stT=0; } }
  step(inp){
    const pr=this.pr, gx=inp.gx|0, gy=inp.gy|0, gz=inp.gz|0, wz=inp.wz|0, ev=inp.ev|0;
    this.ticks=(this.ticks+1)>>>0;
    const dmove=Math.abs(gx-this.lgx)+Math.abs(gy-this.lgy)+Math.abs(gz-this.lgz);
    this.lgx+=idiv(gx-this.lgx,8); this.lgy+=idiv(gy-this.lgy,8); this.lgz+=idiv(gz-this.lgz,8);
    const moving=dmove>90||ev!==0;
    if(moving) this.still=0; else if(this.still<0xFFFF) this.still++;
    const ax=gx, ay=gy, mag=Math.max(Math.abs(ax),Math.abs(ay));
    let want=this.q;
    if(mag>450){
      if(Math.abs(ay)*10>Math.abs(ax)*13) want=ay>0?0:2;
      else if(Math.abs(ax)*10>Math.abs(ay)*13) want=ax<0?1:3;
    }
    if(want!==this.q){ if(want===this.qCand){ this.qT=(this.qT+1)&0xFF; if(this.qT>=18){ this.setQ(want); this.qT=0; this.enter(HXC.AIR); } } else { this.qCand=want; this.qT=0; } }
    else this.qT=0;
    if(this.st===HXC.SLEEP){
      if(moving){ this.enter(HXC.WAKE); this.wakeT=30; this.kick(idiv(-pr.jump*2,3),0); }
      else { this.stT=(this.stT+1)&0xFFFF; this.animTick(); return; }
    }
    const [gdx,gdy]=HxcWorld.gdir(this.q), [tdx,tdy]=HxcWorld.tdir(this.q);
    this.grounded=this.onFloor();
    const vn0=this.vx*gdx+this.vy*gdy;              // 力を足す前の、床へ向かう速さ
    let ax8=idiv(ax*pr.grav,1000), ay8=idiv(ay*pr.grav,1000);
    if(pr.slosh){
      const dw=wz-this.lastWz, rx=(this.x>>8)+idiv(this.bw(),2)-8, ry=(this.y>>8)+idiv(this.bh(),2)-8;
      ax8+=idiv(pr.slosh*dw*ry,2048); ay8-=idiv(pr.slosh*dw*rx,2048);
    }
    this.lastWz=wz;
    const at=ax8*tdx+ay8*tdy, aTmg=ax*tdx+ay*tdy;
    if(this.grounded&&Math.abs(aTmg)<pr.stick){ ax8-=at*tdx; ay8-=at*tdy; }
    this.vx+=ax8; this.vy+=ay8;
    if(this.grounded){ const vt=this.vx*tdx+this.vy*tdy, dec=idiv(vt*pr.fric,256); this.vx-=dec*tdx; this.vy-=dec*tdy; }
    else { this.vx-=idiv(this.vx,128); this.vy-=idiv(this.vy,128); }
    this.vx=Math.max(-pr.maxv,Math.min(pr.maxv,this.vx)); this.vy=Math.max(-pr.maxv*2,Math.min(pr.maxv*2,this.vy));
    if(ev&HXC.SHAKE){ this.dizzyT=120; this.enter(HXC.DIZZY); }
    if((ev&(HXC.TAP|HXC.POKE))&&this.grounded) this.kick(-pr.jump,(this.rnd(3)|0)-1);
    if(ev&HXC.PET){ this.happyT=40; if(this.grounded) this.kick(idiv(-pr.jump,2),0); }
    if(this.grounded&&this.st!==HXC.DIZZY&&this.still>120&&pr.whim){
      if(this.whimT) this.whimT--;
      else {
        const r=this.rnd(256);
        if(r<idiv(pr.whim,2)){ const k=this.rnd(3), t=this.rnd(3); this.kick(idiv(-pr.jump*(2+k),5),t-1); }
        else { this.lookX=this.rnd(3)-1; this.lookY=this.rnd(3)-1; }
        this.whimT=(150+Math.floor(this.rnd(300)*(256-pr.whim)/128))&0xFFFF;
      }
    }
    const hitX=this.moveAxis(true), hitY=this.moveAxis(false);
    const hitN=gdx?hitX:hitY;
    this.grounded=this.onFloor();
    if(vn0>40&&this.grounded&&hitN>60) this.landT=hitN>160?10:6;   // 止まっているだけでは「着地」にしない
    const vt=this.vx*tdx+this.vy*tdy;
    if(Math.abs(vt)>20) this.face=vt>0?1:-1;
    if(this.dizzyT){ this.dizzyT--; this.enter(HXC.DIZZY); }
    else if(this.wakeT){ this.wakeT--; this.enter(HXC.WAKE); }
    else if(this.landT){ this.landT--; this.enter(HXC.LAND); }
    else if(!this.grounded) this.enter(HXC.AIR);
    else if(this.happyT){ this.happyT--; this.enter(HXC.HAPPY); }
    else if(Math.abs(vt)>18) this.enter(HXC.WALK);
    else if(this.still>pr.sleepAfter) this.enter(HXC.SLEEP);
    else this.enter(HXC.IDLE);
    this.stT=(this.stT+1)&0xFFFF;
    this.animTick();
  }
  kick(n,t){ const [gdx,gdy]=HxcWorld.gdir(this.q), [tdx,tdy]=HxcWorld.tdir(this.q); this.vx+=n*gdx+t*60*tdx; this.vy+=n*gdy+t*60*tdy; }
  animTick(){
    if(this.blinkT) this.blinkT--; else this.blinkT=(150+this.rnd(240))&0xFFFF;
    if(this.st===HXC.WALK){ this.walkT=(this.walkT+1)&0xFF; if(this.walkT>=7){ this.walkT=0; this.walkPh^=1; } }
    else this.walkPh=0;
    if(this.st!==HXC.IDLE&&this.st!==HXC.SLEEP){
      const [tdx,tdy]=HxcWorld.tdir(this.q), [gdx,gdy]=HxcWorld.gdir(this.q);
      const vt=this.vx*tdx+this.vy*tdy, vn=this.vx*gdx+this.vy*gdy;
      this.lookX=vt>30?1:vt< -30?-1:0; this.lookY=vn>40?1:vn< -40?-1:0;
    }
  }
  pose(){
    const sp=this.sp, o=hxcSprCopy(sp); let dh=0, sway=0, closed=false, ex=this.lookX, ey=this.lookY;
    switch(this.st){
      case HXC.LAND: dh=-1; break;
      case HXC.AIR: { const [gdx,gdy]=HxcWorld.gdir(this.q); const vn=this.vx*gdx+this.vy*gdy; dh=vn< -90?1:0; break; }
      case HXC.WAKE: dh=(idiv(this.stT,4)&1)?1:0; ey=-1; break;
      case HXC.SLEEP: closed=true; dh=(idiv(this.stT,50)&1)?-1:0; ex=ey=0; break;
      case HXC.DIZZY: ex=(idiv(this.ticks,5)%3)-1; ey=(idiv(this.ticks,7)%3)-1; sway=(idiv(this.ticks,6)&1)?1:-1; break;
      case HXC.HAPPY: closed=(idiv(this.stT,6)&1)===1; break;
    }
    if(this.st===HXC.IDLE&&this.blinkT<7) closed=true;
    for(let i=0;i<2;i++){ if(this.eyeX[i]<0) continue; hxcSprSet(o,this.eyeX[i],this.eyeY[i],true); }
    if(!closed) for(let i=0;i<2;i++){
      if(this.eyeX[i]<0) continue;
      let nx=this.eyeX[i]+ex*this.face, ny=this.eyeY[i]+ey;
      const ok=hxcSprPx(sp,nx-1,ny)&&hxcSprPx(sp,nx+1,ny)&&hxcSprPx(sp,nx,ny-1)&&hxcSprPx(sp,nx,ny+1)&&hxcSprPx(sp,nx,ny);
      if(!ok){ nx=this.eyeX[i]; ny=this.eyeY[i]; }
      hxcSprSet(o,nx,ny,false);
    }
    if(this.st===HXC.WALK) for(let k=0;k<this.legN;k++) if((k&1)===this.walkPh) for(let xx=this.legX0[k];xx<=this.legX1[k];xx++) hxcSprSet(o,xx,sp.h-1,false);
    if(dh){
      const t=o.rows.slice(); let j=0; o.rows=new Array(16).fill(0);
      for(let yy=0;yy<sp.h;yy++){
        if(dh<0&&yy===this.midRow) continue;
        if(j<16) o.rows[j++]=t[yy];
        if(dh>0&&yy===this.midRow&&j<16) o.rows[j++]=t[yy];
      }
      o.h=j;
    }
    return {o:o,dh:dh,sway:sway};
  }
  /// 16×16 のコマ (Uint8Array(32)、ファームと同じ並び)
  render(){
    const out=new Uint8Array(32);
    const dot=(px,py)=>{ if(px<0||py<0||px>15||py>15) return; out[py*2+(px>>3)]|=(0x80>>(px&7)); };
    for(let yy=0;yy<16;yy++) for(let xx=0;xx<16;xx++) if((this.terrain[yy]>>xx)&1) dot(xx,yy);
    const {o,dh,sway}=this.pose(); const bx=this.x>>8, by=this.y>>8, w=this.sp.w, h=this.sp.h; const [tdx,tdy]=HxcWorld.tdir(this.q);
    for(let v=0;v<o.h;v++) for(let u=0;u<o.w;u++){
      if(!hxcSprPx(o,u,v)) continue;
      const uu=this.face<0?w-1-u:u, vb=v-dh; let sx,sy;
      switch(this.q){ case 0: sx=uu; sy=vb; break; case 2: sx=w-1-uu; sy=h-1-vb; break; case 1: sx=h-1-vb; sy=uu; break; default: sx=vb; sy=w-1-uu; }
      dot(bx+sx+sway*tdx, by+sy+sway*tdy);
    }
    return out;
  }
  sleeping(){ return this.st===HXC.SLEEP; }
}

// ---- .hxc (101 バイト、hxm_char.h の hxcParse / hxcBake と同じ)
const HXC_FILE_SIZE=101;
function hxcBake(sp,p,terrain,name){
  const b=new Uint8Array(HXC_FILE_SIZE), w16=(o,v)=>{ b[o]=v&255; b[o+1]=(v>>8)&255; };
  b.set([72,88,67,49],0); b[4]=sp.w; b[5]=sp.h;
  for(let y=0;y<16;y++) w16(6+y*2,sp.rows[y]||0);
  const q=38; w16(q,p.grav); w16(q+2,p.maxv); b[q+4]=p.bounce&255; b[q+5]=p.fric&255; w16(q+6,p.stick); w16(q+8,p.jump); b[q+10]=p.whim&255; w16(q+11,p.sleepAfter); w16(q+13,p.slosh);
  for(let y=0;y<16;y++) w16(53+y*2,(terrain&&terrain[y])||0);
  const nm=String(name||"").replace(/[^\x20-\x7e]/g,"").slice(0,16);
  for(let i=0;i<nm.length;i++) b[85+i]=nm.charCodeAt(i);
  return b;
}
function hxcParse(b){
  if(!b||b.length<HXC_FILE_SIZE||b[0]!==72||b[1]!==88||b[2]!==67||b[3]!==49) return null;
  const w=b[4], h=b[5]; if(w<1||w>16||h<1||h>16) return null;
  const u16=o=>b[o]|(b[o+1]<<8), s16=o=>{ const v=u16(o); return v>=32768?v-65536:v; };
  const mask=(1<<w)-1, rows=[]; let dots=0;
  for(let y=0;y<16;y++){ const r=y<h?(u16(6+y*2)&mask):0; rows.push(r); for(let k=r;k;k&=k-1) dots++; }
  if(!dots) return null;
  const q=38, p={grav:s16(q),maxv:s16(q+2),bounce:b[q+4],fric:b[q+5],stick:s16(q+6),jump:s16(q+8),whim:b[q+10],sleepAfter:u16(q+11),slosh:s16(q+13)};
  p.grav=Math.max(1,Math.min(400,p.grav)); p.maxv=Math.max(16,Math.min(255,p.maxv)); p.jump=Math.max(0,Math.min(600,p.jump)); p.sleepAfter=Math.max(60,p.sleepAfter);
  const terrain=[]; for(let y=0;y<16;y++) terrain.push(u16(53+y*2));
  let name=""; for(let i=0;i<16;i++){ const c=b[85+i]; if(!c) break; if(c>=32&&c<127) name+=String.fromCharCode(c); }
  return {sp:{w:w,h:h,rows:rows},p:p,terrain:terrain,name:name};
}
if(typeof module!=="undefined") module.exports={HXC,HXC_DEFAULT,HXC_BUILTIN_ROWS,HxcWorld,hxcSpriteFromLines,hxcBake,hxcParse,HXC_FILE_SIZE};
