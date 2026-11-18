// ============================================================
// 箱庭 (v0.11): キャラの絵・性格・地形を作って、ブラウザで動かしてみて、本体へ送る
//   エンジンは src/hako_engine.js (本体の hxm_char.h と同じ動き)
// ============================================================
(function(){
const HK_PARAMS=[   // キー, 名前, 最小, 最大, 刻み, 表示
  ["grav","重さ",5,150,1],
  ["bounce","跳ね返り",0,230,1],
  ["fric","止まりやすさ",2,160,1],
  ["stick","滑り出す傾き",0,600,10,v=>v+"mg"],
  ["jump","ジャンプ力",0,500,5],
  ["maxv","最高速度",40,255,5],
  ["whim","気まぐれ",0,255,5],
  ["sleepAfter","寝るまで",300,7200,60,v=>Math.round(v/60)+"秒"],
  ["slosh","回転の慣性",-100,100,5],
];
const HK_KEY="hexa-hako";
const hk={cells:new Uint8Array(256), ter:new Uint8Array(256), p:Object.assign({},HXC_DEFAULT), name:"hexa",
  mode:"c", ang:0, swing:false, phone:null, ev:0, w:new HxcWorld(), shown:false, raf:0, acc:0, last:0,
  trying:false, tryT:0, seed:1};

// ---- 絵 ⇔ セル
function builtinCells(){
  const c=new Uint8Array(256), ox=1, oy=3;
  HXC_BUILTIN_ROWS.forEach((r,y)=>{ for(let x=0;x<r.length;x++) if(r[x]==="#") c[(y+oy)*16+x+ox]=1; });
  return c;
}
function cellsToSprite(cells){
  let x0=16,y0=16,x1=-1,y1=-1;
  for(let y=0;y<16;y++) for(let x=0;x<16;x++) if(cells[y*16+x]){ x0=Math.min(x0,x); y0=Math.min(y0,y); x1=Math.max(x1,x); y1=Math.max(y1,y); }
  if(x1<0) return null;
  const rows=new Array(16).fill(0);
  for(let y=y0;y<=y1;y++) for(let x=x0;x<=x1;x++) if(cells[y*16+x]) rows[y-y0]|=(1<<(x-x0));
  return {w:x1-x0+1,h:y1-y0+1,rows:rows};
}
function spriteToCells(sp){
  const c=new Uint8Array(256), ox=Math.floor((16-sp.w)/2), oy=16-sp.h;
  for(let y=0;y<sp.h;y++) for(let x=0;x<sp.w;x++) if((sp.rows[y]>>x)&1) c[(y+oy)*16+x+ox]=1;
  return c;
}
const terRows=()=>{ const r=new Array(16).fill(0); for(let y=0;y<16;y++) for(let x=0;x<16;x++) if(hk.ter[y*16+x]) r[y]|=(1<<x); return r; };
function bytes(){ const sp=cellsToSprite(hk.cells); return sp?hxcBake(sp,hk.p,terRows(),hk.name):null; }

// ---- 保存 (ブラウザ)
function save(){ try{ localStorage.setItem(HK_KEY,JSON.stringify({c:Array.from(hk.cells),t:Array.from(hk.ter),p:hk.p,n:hk.name})); }catch(e){} }
function load(){
  try{ const j=JSON.parse(localStorage.getItem(HK_KEY)||"null"); if(!j) return false;
    if(j.c&&j.c.length===256) hk.cells=Uint8Array.from(j.c); if(j.t&&j.t.length===256) hk.ter=Uint8Array.from(j.t);
    hk.p=Object.assign({},HXC_DEFAULT,j.p||{}); hk.name=String(j.n||"hexa"); return true; }catch(e){ return false; }
}

// ---- 動かす
function resetSim(){
  const sp=cellsToSprite(hk.cells);
  hk.w=new HxcWorld();
  if(!sp){ return; }
  hk.w.init(sp,hk.p,hk.seed=(hk.seed*1103515245+12345)>>>0||1);
  hk.w.terrain=terRows(); hk.w.fit();   // 地形に埋まっていたら近くへ逃がす
}
function input(){
  if(hk.phone&&hk.phone.g) return {gx:hk.phone.g[0],gy:hk.phone.g[1],gz:hk.phone.g[2],wz:0};
  const sw=hk.swing?14*Math.sin(performance.now()/1000*2*Math.PI*1.2):0;
  const r=(hk.ang+sw)*Math.PI/180;
  return {gx:Math.round(-1000*Math.sin(r)),gy:Math.round(1000*Math.cos(r)),gz:0,wz:0};
}
function tick(t){
  if(!hk.shown) return;
  if(!hk.last) hk.last=t;
  hk.acc+=Math.min(200,t-hk.last); hk.last=t;
  while(hk.acc>=1000/60){
    hk.acc-=1000/60;
    if(hk.w.sp.w){ const i=input(); i.ev=hk.ev; hk.ev=0; if(hk.phone&&hk.phone.ev){ i.ev|=hk.phone.ev; hk.phone.ev=0; } hk.w.step(i); }
  }
  drawSim();
  hk.raf=requestAnimationFrame(tick);
}
function drawSim(){
  const cv=$("hkpv"), g=cv.getContext("2d"), S=cv.width;
  g.fillStyle="#06080b"; g.fillRect(0,0,S,S);
  const sw=hk.phone&&hk.phone.g?0:(hk.swing?14*Math.sin(performance.now()/1000*2*Math.PI*1.2):0);
  const a=hk.phone&&hk.phone.g?0:(hk.ang+sw)*Math.PI/180;
  g.save(); g.translate(S/2,S/2+10); g.rotate(-a);
  const D=290, R=26;
  if(hk.phone&&hk.phone.g){} else if(Math.abs(hk.ang)<30){ g.strokeStyle="#9aa0a6"; g.lineWidth=3; g.beginPath(); g.moveTo(0,-D/2-12); g.lineTo(0,-D/2-200); g.stroke(); }
  g.fillStyle="#1c1f24"; g.strokeStyle="#454b55"; g.lineWidth=3;
  g.beginPath(); if(g.roundRect) g.roundRect(-D/2,-D/2,D,D,R); else g.rect(-D/2,-D/2,D,D); g.fill(); g.stroke();
  g.fillStyle="#ffb02e"; g.fillRect(-16,-D/2-14,32,16); g.fillStyle="#06080b"; g.fillRect(-7,-D/2-9,14,7);   // 吊り穴の印
  const f=hk.w.sp.w?hk.w.render():new Uint8Array(32), p=(D-40)/16, x0=-D/2+20+p/2, y0=-D/2+20+p/2, slp=hk.w.sleeping&&hk.w.sleeping();
  for(let y=0;y<16;y++) for(let x=0;x<16;x++){
    const on=(f[y*2+(x>>3)]>>(7-(x&7)))&1;
    g.fillStyle=on?(slp?"#7c8199":"#eef2ff"):"#2a3038";
    g.beginPath(); g.arc(x0+x*p,y0+y*p,on?p*0.34:p*0.13,0,6.2832); g.fill();
  }
  g.restore();
  const qn=["下","左","上","右"][hk.w.q|0]||"-";
  $("hkInfo").textContent=hk.w.sp.w?("状態: "+HXC.ST_NAME[hk.w.st]+" ・ 床: 画面の"+qn+(hk.phone&&hk.phone.g?" ・ スマホの傾き":" ・ 傾き "+Math.round(((hk.ang%360)+540)%360-180)+"°")):"キャラを描いてください";
}

// ---- 絵を描く
function drawEd(){
  const cv=$("hkEd"), g=cv.getContext("2d"), S=cv.width, p=S/16;
  g.fillStyle="#000"; g.fillRect(0,0,S,S);
  const sp=cellsToSprite(hk.cells), info=new HxcWorld();
  let eyes=[], ox=0, oy=0;
  if(sp){ info.init(sp,hk.p,1); for(let i=0;i<2;i++) if(info.eyeX[i]>=0) eyes.push([info.eyeX[i],info.eyeY[i]]);
    // 絵の左上 (セル上)
    outer: for(let y=0;y<16;y++) for(let x=0;x<16;x++) if(hk.cells[y*16+x]){ oy=y; break outer; }
    ox=16; for(let y=0;y<16;y++) for(let x=0;x<16;x++) if(hk.cells[y*16+x]) ox=Math.min(ox,x);
  }
  for(let y=0;y<16;y++) for(let x=0;x<16;x++){
    const c=hk.cells[y*16+x], t=hk.ter[y*16+x], cx=(x+.5)*p, cy=(y+.5)*p;
    let col="#1b1f26", r=p*0.16;
    if(hk.mode==="c"){ if(c){ col="#ffffff"; r=p*0.38; } else if(t){ col="#3b4250"; r=p*0.3; } }
    else { if(t){ col="#2fd67b"; r=p*0.38; } else if(c){ col="#4a4f5a"; r=p*0.3; } }
    g.fillStyle=col; g.beginPath(); g.arc(cx,cy,r,0,6.2832); g.fill();
  }
  if(hk.mode==="c") for(const [ex,ey] of eyes){ g.strokeStyle="#ffb02e"; g.lineWidth=2; g.beginPath(); g.arc((ex+ox+.5)*p,(ey+oy+.5)*p,p*0.42,0,6.2832); g.stroke(); }
  $("hkFound").textContent=sp?("大きさ "+sp.w+"×"+sp.h+" ・ 目 "+eyes.length+" (オレンジの丸) ・ 脚 "+info.legN+(sp.w>14||sp.h>14?" ・ ※大きいので、あまり動けません":"")):"キャラがありません";
}
let paint=null;
function cellAt(e){ const cv=$("hkEd"), r=cv.getBoundingClientRect(); const x=Math.floor((e.clientX-r.left)/r.width*16), y=Math.floor((e.clientY-r.top)/r.height*16); return (x<0||y<0||x>15||y>15)?-1:y*16+x; }
function edDown(e){ const i=cellAt(e); if(i<0) return; const a=hk.mode==="c"?hk.cells:hk.ter; paint=a[i]?0:1; a[i]=paint; changed(); try{ e.target.setPointerCapture(e.pointerId); }catch(_){} }
function edMove(e){ if(paint===null) return; const i=cellAt(e); if(i<0) return; const a=hk.mode==="c"?hk.cells:hk.ter; if(a[i]!==paint){ a[i]=paint; changed(); } }
function edUp(){ paint=null; }

// ---- 性格
function buildParams(){
  const el=$("hkParams"); el.innerHTML="";
  for(const [k,label,mn,mx,stp,fmt] of HK_PARAMS){
    const row=document.createElement("div"); row.className="hkrow";
    const h=document.createElement("span"); h.className="h"; h.textContent=label;
    const r=document.createElement("input"); r.type="range"; r.min=mn; r.max=mx; r.step=stp; r.value=hk.p[k]; r.id="hkp_"+k;
    const v=document.createElement("span"); v.className="v"; v.textContent=fmt?fmt(hk.p[k]):hk.p[k];
    r.oninput=()=>{ hk.p[k]=+r.value; v.textContent=fmt?fmt(hk.p[k]):hk.p[k]; changed(true); };
    row.appendChild(h); row.appendChild(r); row.appendChild(v); el.appendChild(row);
  }
}

// ---- 変わった
let chT=0;
function changed(paramOnly){
  save(); drawEd();
  clearTimeout(chT); chT=setTimeout(()=>{ resetSim(); if(hk.trying) sendTry(true); },paramOnly?250:120);
}

// ---- 本体
const fwAt=v=>!!devFw && devFw.localeCompare(v,undefined,{numeric:true})>=0;
const fwOk=()=>fwAt("0.11.0");
// 試している間は、叩く・振る・なでる・つつく・寝かせる を本体にも送る (ファーム v0.11.1〜)
function devEv(bits){
  if(!hk.trying||!writer||!fwAt("0.11.1")) return;
  tx(packet(7,Array.from("hakoev="+bits,c=>c.charCodeAt(0))));
}
function devState(){
  const on=!!writer&&fwOk()&&!devBusy;
  $("hkTry").disabled=!on; $("hkSave").disabled=!on; $("hkStop").disabled=!(writer&&hk.trying);
}
async function sendTry(quiet){
  const b=bytes(); if(!b||!writer) return;
  if(typeof stopPlay==="function") stopPlay();
  try{ const j=await xferFile("@char",b); hk.trying=true; if(!quiet){ log("本体で箱庭を試しています: "+(j.char||hk.name)+" (止めるまで箱庭のまま)","ok"); status("本体で試しています","ok"); } }
  catch(e){ hk.trying=false; log("箱庭: "+e.message,"err"); status(e.message,"err"); }
  devState();
}
function stopTry(){
  if(hk.trying&&writer) tx(packet(HXF.PLAY,[0xFE]));
  hk.trying=false; devState();
}
async function saveDev(){
  const b=bytes(); if(!b) return;
  if(typeof stopPlay==="function") stopPlay();
  try{ const j=await xferFile("hako.hxc",b); log("本体に保存しました: 箱庭のキャラ「"+(j.char||hk.name)+"」 (USB を抜くと出てきます)","ok"); status("本体に保存しました","ok"); }
  catch(e){ log("箱庭: "+e.message,"err"); status(e.message,"err"); }
}

// ---- スマホの傾き
async function phoneOn(){
  if(hk.phone){ window.removeEventListener("devicemotion",hk.phone.fn); hk.phone=null; $("hkPhone").textContent="スマホの傾きで動かす"; $("hkPhoneSt").textContent=""; return; }
  const DM=window.DeviceMotionEvent;
  if(!DM){ $("hkPhoneSt").textContent="このブラウザは傾きセンサーが使えません"; return; }
  if(typeof DM.requestPermission==="function"){
    try{ if(await DM.requestPermission()!=="granted"){ $("hkPhoneSt").textContent="傾きセンサーの許可がありません"; return; } }
    catch(e){ $("hkPhoneSt").textContent="傾きセンサーを使えません: "+e.message; return; }
  }
  const ios=typeof DM.requestPermission==="function", s=ios?-1:1;   // iOS は向きが逆
  const ph={g:null,ev:0,last:null,cool:0,peaks:[],fn:null};
  ph.fn=e=>{
    const a=e.accelerationIncludingGravity; if(!a||a.x==null) return;
    const ax=a.x*s, ay=a.y*s, az=(a.z||0)*s;
    ph.g=[Math.round(-ax/9.81*1000),Math.round(ay/9.81*1000),Math.round(az/9.81*1000)];   // 画面の向き (y は下が +)
    const now=performance.now(), m=Math.hypot(ax,ay,az);
    if(ph.last){ const j=Math.hypot(ax-ph.last[0],ay-ph.last[1],az-ph.last[2]);
      if(m>19.6){ ph.peaks=ph.peaks.filter(t=>now-t<800); if(!ph.peaks.length||now-ph.peaks[ph.peaks.length-1]>120) ph.peaks.push(now); if(ph.peaks.length>=3){ ph.ev|=HXC.SHAKE; ph.peaks=[]; ph.cool=now+1500; } }
      else if(j>10.8&&now>ph.cool){ ph.ev|=HXC.TAP; ph.cool=now+400; } }
    ph.last=[ax,ay,az];
  };
  window.addEventListener("devicemotion",ph.fn); hk.phone=ph;
  $("hkPhone").textContent="スマホの傾きをやめる"; $("hkPhoneSt").textContent="スマホを CoreMatrix に見立てて傾けてください (縦向き固定がおすすめ)";
}

// ---- つなぐ
function wire(){
  $("hkEd").addEventListener("pointerdown",edDown); $("hkEd").addEventListener("pointermove",edMove);
  window.addEventListener("pointerup",edUp);
  const pv=$("hkpv"); let drag=null;
  pv.addEventListener("pointerdown",e=>{ drag=e.clientX; try{ pv.setPointerCapture(e.pointerId); }catch(_){} pv.style.cursor="grabbing"; });
  pv.addEventListener("pointermove",e=>{ if(drag===null) return; hk.ang-=(e.clientX-drag)*0.6; drag=e.clientX; });
  pv.addEventListener("pointerup",()=>{ drag=null; pv.style.cursor="grab"; });
  $("hkL90").onclick=()=>{ hk.ang+=90; }; $("hkR90").onclick=()=>{ hk.ang-=90; };
  $("hk180").onclick=()=>{ hk.ang+=180; }; $("hk0").onclick=()=>{ hk.ang=0; };
  $("hkSwing").onchange=e=>{ hk.swing=e.target.checked; };
  const ev=b=>{ hk.ev|=b; devEv(b); };
  $("hkTap").onclick=()=>ev(HXC.TAP); $("hkShake").onclick=()=>ev(HXC.SHAKE);
  $("hkPet").onclick=()=>ev(HXC.PET); $("hkPoke").onclick=()=>ev(HXC.POKE);
  $("hkSleep").onclick=()=>{ hk.w.still=0xFFFF; devEv(16); };
  $("hkPhone").onclick=phoneOn;
  $("hkModeC").onclick=()=>{ hk.mode="c"; $("hkModeC").classList.add("sel"); $("hkModeT").classList.remove("sel"); drawEd(); };
  $("hkModeT").onclick=()=>{ hk.mode="t"; $("hkModeT").classList.add("sel"); $("hkModeC").classList.remove("sel"); drawEd(); };
  $("hkBuiltin").onclick=()=>{ hk.cells=builtinCells(); changed(); };
  $("hkFromMark").onclick=()=>{ if(typeof grid==="undefined") return; hk.cells=Uint8Array.from(grid); changed(); status("「マークを作る」の絵を使いました","ok"); };
  $("hkFlip").onclick=()=>{ const a=hk.mode==="c"?hk.cells:hk.ter, b=new Uint8Array(256); for(let y=0;y<16;y++) for(let x=0;x<16;x++) b[y*16+x]=a[y*16+15-x]; if(hk.mode==="c") hk.cells=b; else hk.ter=b; changed(); };
  $("hkClear").onclick=()=>{ if(!confirm(hk.mode==="c"?"キャラの絵を消します。よろしいですか？":"地形を消します。よろしいですか？")) return; if(hk.mode==="c") hk.cells=new Uint8Array(256); else hk.ter=new Uint8Array(256); changed(); };
  $("hkDefault").onclick=()=>{ hk.p=Object.assign({},HXC_DEFAULT); buildParams(); changed(true); };
  $("hkName").value=hk.name; $("hkName").oninput=e=>{ hk.name=e.target.value.replace(/[^\x20-\x7e]/g,"").slice(0,16); save(); };
  $("hkExport").onclick=()=>{ const b=bytes(); if(!b){ status("キャラがありません","err"); return; } download((hk.name||"hako").replace(/[^A-Za-z0-9_-]+/g,"_")+".hxc",new Blob([b],{type:"application/octet-stream"})); status("書き出しました","ok"); };
  $("hkImport").onclick=()=>$("hkFile").click();
  $("hkFile").onchange=async e=>{
    const f=e.target.files[0]; e.target.value=""; if(!f) return;
    const j=hxcParse(new Uint8Array(await f.arrayBuffer()));
    if(!j){ status(".hxc の形が違います","err"); return; }
    hk.cells=spriteToCells(j.sp); hk.ter=new Uint8Array(256); j.terrain.forEach((r,y)=>{ for(let x=0;x<16;x++) if((r>>x)&1) hk.ter[y*16+x]=1; });
    hk.p=Object.assign({},HXC_DEFAULT,j.p); hk.name=j.name||hk.name; $("hkName").value=hk.name; buildParams(); changed(); status("読み込みました: "+(j.name||f.name),"ok");
  };
  $("hkTry").onclick=()=>sendTry(false); $("hkStop").onclick=stopTry; $("hkSave").onclick=saveDev;
  setInterval(()=>{ if(!writer) hk.trying=false; devState(); },500);
}

// 画面の切り替え (program.js の setView から)
window.hakoShow=function(on){
  if(on===hk.shown) return;
  hk.shown=on;
  if(on){ drawEd(); hk.last=0; hk.raf=requestAnimationFrame(tick); }
  else { cancelAnimationFrame(hk.raf); if(hk.trying) stopTry(); }
};

if(!load()) hk.cells=builtinCells();
buildParams(); wire(); resetSim(); drawEd(); drawSim();
})();
