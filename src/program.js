// ============================================================
// 番組 (シーンを並べて再生する)
// ============================================================
const PROG_KEY="hexa_matrix_program_v1";
const IN_OPTS=[["none","なし (すぐ)"],["slideL","← 流れて"],["slideR","→ 流れて"],["slideU","↑ 上へ"],["slideD","↓ 下へ"],
  ["wipe","ワイプ"],["type","1字ずつ"],["dissolve","粒で"],["drop","落ちて"],["fade","フェード"],["zoom","ズーム"]];
const SHOW_OPTS=[["static","止める (長い文はページ送り)"],["scrollL","← 横流し"],["scrollR","→ 横流し"],["scrollU","↑ 縦送り"],
  ["wave","波打ちながら横流し"],["bounce","往復"],["blink","点滅"],["invert","反転点滅"],["breathe","ゆっくり明暗"]];
const ANIM_OPTS=[["play","くりかえし"],["pingpong","行って戻る"]];
const KIND_NAME={text:"文字",mark:"マーク",anim:"コマアニメ"};
const optName=(list,v)=>{ const o=list.find(x=>x[0]===v); return o?o[1].replace(/ \(.*\)/,""):v; };
const HEART_ROWS=[0x0000,0x1E78,0x3FFC,0x7FFE,0x7FFE,0x7FFE,0x7FFE,0x3FFC,0x1FF8,0x0FF0,0x0FF0,0x07E0,0x03C0,0x0180,0x0000,0x0000];

let prog={name:"はじめての番組",scenes:[]}, sel=0, fontsOK=false;
// ヘッダー/フッター: 番組の頭と終わりに挟むシーン。every 周に1回だけ出す
const EVERY_OPTS=[[1,"毎回"],[2,"2周に1回"],[3,"3周に1回"],[5,"5周に1回"],[10,"10周に1回"]];
function defaultHF(which){
  return which==="H"
    ? {on:false,every:1,scene:{kind:"text",text:"HEXA STAGE",size:16,bold:false,in:"none",show:"scrollL",out:"none",speed:6,hold:2,loops:1,bri:10}}
    : {on:false,every:1,scene:{kind:"text",text:"ありがとう",size:16,bold:false,in:"none",show:"scrollL",out:"none",speed:6,hold:2,loops:1,bri:8}};
}
function okHF(x,which){
  const d=defaultHF(which);
  if(!x||!okScene(x.scene)) return d;
  return {on:!!x.on, every:EVERY_OPTS.some(o=>o[0]===x.every)?x.every:1, scene:x.scene};
}
/// sel は 0〜 の番号か、"H" (ヘッダー) / "F" (フッター)
function curSc(){ return sel==="H"?prog.header.scene : sel==="F"?prog.footer.scene : prog.scenes[sel]; }
function hfOf(sc){ return sc===prog.header.scene?"H" : sc===prog.footer.scene?"F" : null; }
const gcd=(a,b)=>b?gcd(b,a%b):a;
/// 1周ぶんの並び。ヘッダー/フッターの間隔がそろうまで周を重ねる (例: 2周に1回と3周に1回なら6周)
function programSequence(){
  const h=prog.header, f=prog.footer;
  let L=1;
  if(h.on) L=L*h.every/gcd(L,h.every);
  if(f.on) L=L*f.every/gcd(L,f.every);
  const out=[];
  for(let c=0;c<L;c++){
    if(h.on && c%h.every===0) out.push(h.scene);
    out.push(...prog.scenes);
    if(f.on && c%f.every===0) out.push(f.scene);
  }
  return {list:out, cycles:L};
}
function newScene(kind){
  const base={kind:kind,in:"none",show:"static",out:"none",speed:6,hold:2,loops:1,bri:8};
  if(kind==="text") return Object.assign(base,{text:"HEXA STAGE",size:16,bold:false,show:"scrollL"});
  if(kind==="mark") return Object.assign(base,{rows:toRows(grid),name:$("name").value.trim()||"いまのマーク",in:"zoom",show:"breathe",out:"dissolve"});
  return Object.assign(base,{frames:[toRows(grid)],fps:6,show:"play",hold:3});
}
function demoProgram(){
  return {name:"はじめての番組",scenes:[
    {kind:"text",text:"HEXA STAGE",size:16,bold:false,in:"none",show:"scrollL",out:"none",speed:6,hold:2,loops:1,bri:8},
    {kind:"mark",rows:HEART_ROWS,name:"heart",in:"zoom",show:"breathe",out:"dissolve",speed:6,hold:3,loops:1,bri:10},
    {kind:"text",text:"ようこそ\nHEXA",size:8,bold:false,in:"type",show:"static",out:"slideU",speed:6,hold:2,loops:1,bri:8},
    {kind:"text",text:"営業中",size:16,bold:false,in:"drop",show:"static",out:"fade",speed:6,hold:1.5,loops:1,bri:12}
  ]};
}
function okScene(s){ return s && (s.kind==="text"||s.kind==="mark"||s.kind==="anim"); }
function progLoad(){
  const s=store(); let p=null;
  if(s){ try{ p=JSON.parse(s.getItem(PROG_KEY)||"null"); }catch(e){} }
  prog = (p && Array.isArray(p.scenes) && p.scenes.filter(okScene).length) ? {name:p.name||"番組",scenes:p.scenes.filter(okScene),header:p.header,footer:p.footer} : demoProgram();
  prog.header=okHF(prog.header,"H"); prog.footer=okHF(prog.footer,"F");
}
let saveT=0;
function progSave(){ clearTimeout(saveT); saveT=setTimeout(()=>{ const s=store(); if(s) try{ s.setItem(PROG_KEY,JSON.stringify(prog)); }catch(e){} },300); }

// ---- 一覧 ----
function sceneSummary(sc){
  let what = sc.kind==="text" ? "「"+String(sc.text||"").replace(/\n/g," / ")+"」" : sc.kind==="mark" ? (sc.name||"マーク") : (sc.frames||[]).length+"コマ";
  const shows = sc.kind==="anim" ? ANIM_OPTS : SHOW_OPTS;
  const parts=[];
  if(!SCROLLS.includes(sc.show) && sc.in!=="none") parts.push(optName(IN_OPTS,sc.in));
  parts.push(optName(shows,sc.show));
  if(!SCROLLS.includes(sc.show) && sc.out!=="none") parts.push(optName(IN_OPTS,sc.out)+"消える");
  return {what:what, how:parts.join(" → ")};
}
function thumbFrame(sc){
  if(!fontsOK && sc.kind==="text") return new Uint8Array(NN);
  try{
    if(sc.kind==="mark") return fromRows(sc.rows||[]);
    if(sc.kind==="anim") return fromRows((sc.frames||[])[0]||[]);
    return pagesOf(textStrip(sc.text,sc.size===8?8:16,!!sc.bold))[0].b;
  }catch(e){ return new Uint8Array(NN); }
}
function hfRender(which){
  const hf=which==="H"?prog.header:prog.footer, el=$(which==="H"?"hfHead":"hfFoot"); el.innerHTML="";
  const r=document.createElement("div"); r.className="scene hf"+(sel===which?" sel":"")+(hf.on?"":" off");
  const sw=document.createElement("label"); sw.className="hfsw"; sw.title=(hf.on?"使わない":"使う");
  const cb=document.createElement("input"); cb.type="checkbox"; cb.checked=hf.on;
  cb.onclick=e=>e.stopPropagation();
  cb.onchange=()=>{ hf.on=cb.checked; changed(true); };
  sw.appendChild(cb); sw.onclick=e=>e.stopPropagation(); r.appendChild(sw);
  const cv=document.createElement("canvas"); cv.width=cv.height=48; drawLed(cv,thumbFrame(hf.scene)); r.appendChild(cv);
  const sm=sceneSummary(hf.scene), tx=document.createElement("div"); tx.className="stxt";
  const a=document.createElement("b"); a.textContent=(which==="H"?"ヘッダー":"フッター")+" "+KIND_NAME[hf.scene.kind]+" "+sm.what;
  const b=document.createElement("span"); b.textContent=hf.on?sm.how:"使わない";
  tx.appendChild(a); tx.appendChild(b); r.appendChild(tx);
  const ev=document.createElement("select"); ev.title="出す間隔"; ev.disabled=!hf.on;
  for(const [v,t] of EVERY_OPTS){ const o=document.createElement("option"); o.value=v; o.textContent=t; ev.appendChild(o); }
  ev.value=String(hf.every); ev.onclick=e=>e.stopPropagation();
  ev.onchange=()=>{ hf.every=+ev.value; changed(true); };
  r.appendChild(ev);
  r.onclick=()=>{ sel=which; sceneRender(); formFill(); previewSelected(); };
  el.appendChild(r);
}
function sceneRender(){
  hfRender("H"); hfRender("F");
  const seq=programSequence();
  $("cycleNote").textContent = seq.cycles>1 ? "ヘッダー/フッターの間隔に合わせて "+seq.cycles+"周 でひとまわりします" : "";
  const el=$("scenes"); el.innerHTML="";
  prog.scenes.forEach((sc,i)=>{
    const r=document.createElement("div"); r.className="scene"+(i===sel?" sel":"");
    const cv=document.createElement("canvas"); cv.width=cv.height=48; drawLed(cv,thumbFrame(sc)); r.appendChild(cv);
    const sm=sceneSummary(sc), tx=document.createElement("div"); tx.className="stxt";
    const a=document.createElement("b"); a.textContent=(i+1)+". "+KIND_NAME[sc.kind]+" "+sm.what;
    const b=document.createElement("span"); b.textContent=sm.how;
    tx.appendChild(a); tx.appendChild(b); r.appendChild(tx);
    const bs=document.createElement("div"); bs.className="sbtn";
    const mk=(t,title,fn,cls)=>{ const x=document.createElement("button"); x.textContent=t; x.title=title; if(cls) x.className=cls; x.onclick=e=>{ e.stopPropagation(); fn(); }; bs.appendChild(x); };
    mk("↑","上へ",()=>moveScene(i,-1)); mk("↓","下へ",()=>moveScene(i,1));
    mk("⧉","複製",()=>{ prog.scenes.splice(i+1,0,JSON.parse(JSON.stringify(sc))); sel=i+1; changed(true); });
    mk("✕","消す",()=>{ if(prog.scenes.length<=1){ status("最後の1つは消せません","err"); return; } prog.scenes.splice(i,1); if(typeof sel==="number") sel=Math.min(sel,prog.scenes.length-1); changed(true); },"warn");
    r.appendChild(bs);
    r.onclick=()=>{ sel=i; sceneRender(); formFill(); previewSelected(); };
    el.appendChild(r);
  });
  $("progName").value=prog.name;
}
function moveScene(i,d){
  const j=i+d; if(j<0||j>=prog.scenes.length) return;
  const t=prog.scenes[i]; prog.scenes[i]=prog.scenes[j]; prog.scenes[j]=t;
  if(sel===i) sel=j; else if(sel===j) sel=i;
  changed(true);
}
function addScene(kind){
  const at = sel==="H" ? 0 : sel==="F" ? prog.scenes.length : sel+1;
  prog.scenes.splice(at,0,newScene(kind)); sel=at; changed(true);
}
$("addText").onclick=()=>addScene("text");
$("addMark").onclick=()=>addScene("mark");
$("addAnim").onclick=()=>addScene("anim");

// ---- 設定フォーム ----
function fillSelect(el,list){ el.innerHTML=""; for(const [v,t] of list){ const o=document.createElement("option"); o.value=v; o.textContent=t; el.appendChild(o); } }
fillSelect($("fIn"),IN_OPTS); fillSelect($("fOut"),IN_OPTS);
function libOptions(){
  const el=$("fLib"); el.innerHTML="";
  const o0=document.createElement("option"); o0.value=""; o0.textContent=lib.length?"マーク置き場から選ぶ…":"(マーク置き場は空です)"; el.appendChild(o0);
  lib.forEach((it,i)=>{ const o=document.createElement("option"); o.value=i; o.textContent=it.name; el.appendChild(o); });
}
function formFill(){
  const sc=curSc(); if(!sc) return;
  $("fKind").textContent=(sel==="H"?"ヘッダー / ":sel==="F"?"フッター / ":"")+KIND_NAME[sc.kind];
  $("fKindSel").value=sc.kind;
  document.querySelectorAll("[data-k]").forEach(e=>{ e.style.display = e.dataset.k.split(" ").includes(sc.kind) ? "" : "none"; });
  fillSelect($("fShow"), sc.kind==="anim"?ANIM_OPTS:SHOW_OPTS);
  $("fShow").value=sc.show; $("fIn").value=sc.in; $("fOut").value=sc.out;
  if(sc.kind==="text"){ $("fText").value=sc.text||""; $("fSize").value=String(sc.size===8?8:16); $("fBold").checked=!!sc.bold; }
  if(sc.kind==="anim"){ $("fFps").value=sc.fps||6; animRender(); }
  if(sc.kind==="mark"){ const c=$("fMarkPv"); drawLed(c,fromRows(sc.rows||[])); $("fMarkName").textContent=sc.name||""; }
  libOptions();
  for(const k of ["speed","hold","loops","bri"]) $("f_"+k).value=sc[k];
  formLabels();
}
function formLabels(){
  const sc=curSc(); if(!sc) return;
  const scroll=SCROLLS.includes(sc.show);
  $("rowIn").classList.toggle("dimrow",scroll); $("rowOut").classList.toggle("dimrow",scroll);
  $("scrollNote").style.display=scroll?"":"none";
  $("rowLoops").style.display=(scroll||sc.show==="bounce")?"":"none";
  $("rowHold").style.display=(sc.show==="scrollL"||sc.show==="scrollR"||sc.show==="wave")?"none":"";
  $("v_speed").textContent=sc.speed; $("v_hold").textContent=(+sc.hold).toFixed(1)+"秒";
  $("v_loops").textContent=sc.loops+"回"; $("v_bri").textContent=sc.bri+"/16"; $("v_fps").textContent=(sc.fps||6)+"コマ/秒";
  $("fSizeNote").textContent = sc.kind==="text" ? (sc.size===8 ? "8ドット: 改行で2行まで。1行に全角2字・半角4字が入ります" : "16ドット: 全角1字・半角2字ずつ。改行は空白になります") : "";
}
function animRender(){
  const sc=curSc(), el=$("fFrames"); el.innerHTML="";
  (sc.frames||[]).forEach((rows,i)=>{
    const d=document.createElement("div"); d.className="fr";
    const cv=document.createElement("canvas"); cv.width=cv.height=40; drawLed(cv,fromRows(rows)); d.appendChild(cv);
    const x=document.createElement("button"); x.textContent="✕"; x.title=(i+1)+"コマめを消す";
    x.onclick=()=>{ if(sc.frames.length<=1){ status("コマは1つ以上必要です","err"); return; } sc.frames.splice(i,1); animRender(); changed(); };
    d.appendChild(x); el.appendChild(d);
  });
}
$("fKindSel").onchange=e=>{
  const sc=curSc(), k=e.target.value; if(!sc||sc.kind===k) return;
  const fresh=newScene(k);
  for(const key of Object.keys(sc)) delete sc[key];
  Object.assign(sc,fresh,{speed:fresh.speed,bri:fresh.bri});
  changed(true);
};
function upd(k,v){ const sc=curSc(); if(!sc) return; sc[k]=v; changed(); }
$("fText").oninput=e=>upd("text",e.target.value);
$("fSize").onchange=e=>upd("size",+e.target.value);
$("fBold").onchange=e=>upd("bold",e.target.checked);
$("fIn").onchange=e=>upd("in",e.target.value);
$("fShow").onchange=e=>upd("show",e.target.value);
$("fOut").onchange=e=>upd("out",e.target.value);
$("fFps").oninput=e=>upd("fps",+e.target.value);
for(const k of ["speed","hold","loops","bri"]) $("f_"+k).oninput=e=>upd(k,+e.target.value);
$("fLib").onchange=e=>{
  const it=lib[+e.target.value]; e.target.value=""; if(!it) return;
  const sc=curSc();
  if(sc.kind==="anim"){ sc.frames.push(it.rows.slice()); animRender(); }
  else{ sc.rows=it.rows.slice(); sc.name=it.name; }
  changed(); formFill();
};
$("fFromEd").onclick=()=>{
  const sc=curSc();
  if(sc.kind==="anim"){ sc.frames.push(toRows(grid)); animRender(); }
  else{ sc.rows=toRows(grid); sc.name=$("name").value.trim()||"いまのマーク"; }
  changed(); formFill();
};
function changed(listToo){
  progSave(); sceneRender(); if(!listToo) formLabels(); else formFill();
  clearTimeout(pvT2); pvT2=setTimeout(previewSelected,180);
}
let pvT2=0;
$("progName").oninput=e=>{ prog.name=e.target.value; progSave(); };

// ---- 再生 ----
const P={frames:[],i:0,timer:0,playing:false,next:0,lastB:null,lastBri:-1,total:0,mode:"scene"};
function drawBig(b,bri){
  const cv=$("ppv"), g=cv.getContext("2d"), s=cv.width/N;
  g.fillStyle="#000"; g.fillRect(0,0,cv.width,cv.height);
  const k=0.18+0.82*Math.min(1,(bri==null?255:bri)/255);
  for(let i=0;i<NN;i++){
    const on=b[i];
    g.fillStyle = on ? "rgba(255,255,255,"+k.toFixed(3)+")" : "#1b1f26";
    g.beginPath(); g.arc((i%N+.5)*s,(((i/N)|0)+.5)*s,s*.38,0,6.2832); g.fill();
  }
}
function toDevice(f){
  if(!writer || !$("pLive").checked || curView!=="prog") return;
  if(f.bri!==P.lastBri){ tx(packet(HXM.BRIGHT,[f.bri])); P.lastBri=f.bri; }
  if(!P.lastB || !sameF(P.lastB,f.b)){ queueFrame(f.b); P.lastB=f.b; }
}
function stopPlay(){
  clearTimeout(P.timer); P.playing=false; $("pPlay").textContent="▶ 再生";
  if(writer){ tx(packet(HXM.BRIGHT,[$("bri").value*16-1])); P.lastBri=-1; }
}
function startPlay(frames,mode){
  clearTimeout(P.timer);
  P.frames=frames; P.i=0; P.mode=mode; P.playing=true; P.lastB=null; P.lastBri=-1;
  P.total=frames.reduce((a,f)=>a+f.ms,0);
  $("pPlay").textContent="■ 止める";
  P.next=performance.now(); tick();
}
function tick(){
  if(!P.playing||!P.frames.length) return;
  if(P.i>=P.frames.length){
    if(!$("pLoop").checked){ stopPlay(); return; }
    P.i=0;
  }
  const f=P.frames[P.i++];
  drawBig(f.b,f.bri); toDevice(f);
  let t=0; for(let k=0;k<P.i-1;k++) t+=P.frames[k].ms;
  const w = hfOf(f.scene);
  const where = w==="H" ? "ヘッダー" : w==="F" ? "フッター" : "シーン"+(prog.scenes.indexOf(f.scene)+1)+"/"+prog.scenes.length;
  $("pInfo").textContent=(P.mode==="all"?"番組ぜんぶ":"このシーン")+" ・ "+where+" ・ "+(t/1000).toFixed(1)+" / "+(P.total/1000).toFixed(1)+"秒";
  P.next+=f.ms;
  const now=performance.now();
  if(P.next<now-500) P.next=now;                 // タブが裏に回って遅れたら追いつこうとしない
  P.timer=setTimeout(tick,Math.max(0,P.next-now));
}
function safeRender(list){
  try{ return renderProgram(list); }
  catch(e){ status("作れませんでした: "+e.message,"err"); return null; }
}
function previewSelected(){
  if(curView!=="prog") return;
  if(P.playing && P.mode==="all") return;        // 番組の通し再生中は邪魔しない
  const sc=curSc(); if(!sc) return;
  if(sc.kind==="text" && !fontsOK){ stopPlay(); drawBig(new Uint8Array(NN),255); return; }
  const f=safeRender([sc]); if(f&&f.length) startPlay(f,"scene");
}
$("pPlay").onclick=()=>{
  if(P.playing){ stopPlay(); return; }
  const mode=$("pMode").value;
  let list=mode==="all"?programSequence().list:[curSc()];
  if(!fontsOK) list=list.filter(s=>s.kind!=="text");
  if(!list.length){ status("文字のシーンは再生できません","err"); return; }
  const f=safeRender(list);
  if(f&&f.length) startPlay(f,mode==="all"?"all":"scene");
};
$("pMode").onchange=()=>{ if(P.playing){ stopPlay(); $("pPlay").click(); } };

// ---- 保存・書き出し ----
$("progExp").onclick=()=>{
  download((prog.name||"program").replace(/[\\/:*?"<>|]/g,"_")+".hxmprog.json",
    new Blob([JSON.stringify({format:"hexa-matrix-program",version:1,name:prog.name,scenes:prog.scenes,header:prog.header,footer:prog.footer},null,1)],{type:"application/json"}));
  status("番組を書き出しました","ok");
};
$("progImp").onclick=()=>$("progFile").click();
$("progFile").onchange=async e=>{
  const f=e.target.files[0]; e.target.value=""; if(!f) return;
  try{
    const j=JSON.parse(await f.text()); const sc=(j.scenes||[]).filter(okScene);
    if(!sc.length) throw new Error("シーンが見つかりません");
    if(!confirm("いまの番組を「"+(j.name||f.name)+"」("+sc.length+"シーン) に置きかえます。よろしいですか？")) return;
    stopPlay(); prog={name:j.name||"番組",scenes:sc,header:okHF(j.header,"H"),footer:okHF(j.footer,"F")}; sel=0; changed(true); status("読み込みました","ok");
  }catch(err){ status("読み込み失敗: "+err.message,"err"); }
};
$("progBin").onclick=()=>{
  const f=safeRender(programSequence().list); if(!f) return;
  const b=bakeBin(f);
  download((prog.name||"program").replace(/[\\/:*?"<>|]/g,"_")+".hxm",new Blob([b],{type:"application/octet-stream"}));
  status("コマ列を書き出しました ("+f.length+"コマ / "+(b.length/1024).toFixed(1)+"KB)","ok");
};
/// CardputerZero のライブラリに置く (CPZ が同じエンジンでコマ列を作る)
$("progCpz").onclick=async()=>{
  const name=(prog.name||"番組").trim();
  const body={name:name,program:{format:"hexa-matrix-program",version:1,name:prog.name,scenes:prog.scenes,header:prog.header,footer:prog.footer}};
  $("progCpz").disabled=true;
  try{
    const j=await (await fetch("/api/library",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})).json();
    if(!j.ok) throw new Error(j.err||"失敗しました");
    status("CPZに置きました: "+j.name+" ("+j.frames+"コマ / "+(j.size/1024).toFixed(1)+"KB)","ok");
    log("CPZのライブラリに置きました: "+j.name+(j.cycles>1?" ("+j.cycles+"周ぶん)":""),"ok");
  }catch(e){ status("CPZに置けません: "+e.message,"err"); }
  $("progCpz").disabled=false;
};
$("progNew").onclick=()=>{
  if(!confirm("番組を最初の見本に戻します。いまの番組は消えます。よろしいですか？")) return;
  stopPlay(); prog=demoProgram(); prog.header=defaultHF("H"); prog.footer=defaultHF("F"); sel=0; changed(true);
};

// ---- 画面切替 ----
let curView="mark";
function setView(v){
  curView=v;
  document.querySelectorAll(".vtabs button").forEach(b=>b.classList.toggle("sel",b.dataset.v===v));
  $("vMark").hidden = v!=="mark"; $("vProg").hidden = v!=="prog";
  document.querySelectorAll(".markOnly").forEach(e=>e.style.display = v==="mark"?"":"none");
  if(v==="prog"){ libOptions(); formFill(); previewSelected(); }
  else{ stopPlay(); if(writer) queueFrame(grid); }
  try{ history.replaceState(null,"","#"+v); }catch(e){}
}
document.querySelectorAll(".vtabs button").forEach(b=>b.onclick=()=>setView(b.dataset.v));

async function progInit(){
  progLoad(); sceneRender();
  if(typeof DecompressionStream==="undefined"){
    $("fontErr").style.display="block"; $("fontErr").textContent="このブラウザでは文字を作れません (Chrome 80 以降 / Safari 16.4 以降が必要です)。マークとコマアニメは使えます。";
  }else{
    try{ await loadFonts(); fontsOK=true; }
    catch(e){ $("fontErr").style.display="block"; $("fontErr").textContent="フォントを読めませんでした: "+e.message; }
  }
  sceneRender(); formFill();
  setView(location.hash==="#prog"?"prog":"mark");
  if(!fontsOK && curView==="prog") status("文字のシーンは再生できません","err");
}
