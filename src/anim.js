// ============================================================
// コマアニメ (マークを作る画面)
//   frames[] に16×16のコマを並べる。grid はいつも frames[cur] (いま描いているコマ)。
//   再生は大きいグリッドに表示し、「描いたらすぐ映す」がオンなら実機にも流す。
// ============================================================
const MAX_FRAMES=64;
const AN={playing:false, timer:0, i:0, next:0};

/// コマの帯 (サムネイル) を作り直す
function stripRender(){
  const el=$("fstrip"); el.innerHTML="";
  frames.forEach((f,k)=>{
    const d=document.createElement("div"); d.className="ft"+(k===cur?" sel":""); d.dataset.n=k;   // data-k は設定フォームの表示切替で使っているので別名
    const cv=document.createElement("canvas"); cv.width=cv.height=40; drawLed(cv,f); d.appendChild(cv);
    const n=document.createElement("span"); n.textContent=k+1; d.appendChild(n);
    d.title=(k+1)+"コマめ";
    d.onclick=()=>gotoFrame(k);
    el.appendChild(d);
  });
  const add=document.createElement("div"); add.className="ft add";
  const b=document.createElement("button"); b.textContent="＋"; b.title="白紙のコマを最後に足す";
  b.onclick=()=>{ if(frames.length>=MAX_FRAMES){ status("コマは"+MAX_FRAMES+"までです","err"); return; }
    animStop(true); frames.push(new Uint8Array(NN)); gotoFrame(frames.length-1); push(); };
  add.appendChild(b); el.appendChild(add);
  animInfo();
  // 今のコマが見える所まで帯だけを横に送る (scrollIntoView はページごと動くので使わない)
  const s=el.children[cur];
  if(s){ const l=s.offsetLeft-el.offsetLeft; if(l<el.scrollLeft||l+45>el.scrollLeft+el.clientWidth) el.scrollLeft=Math.max(0,l-el.clientWidth/2+20); }
}
/// 1コマぶんのサムネイルだけ描き直す (なぞっている間はこちらで軽く済ませる)
function stripThumb(k){
  const d=$("fstrip").children[k]; if(!d) return;
  const cv=d.querySelector("canvas"); if(cv) drawLed(cv,frames[k]);
}
function animInfo(){
  const fps=+$("aFps").value, n=frames.length;
  $("fInfo").textContent="コマ "+(cur+1)+" / "+n+(n>1?"":"  (コマを足すとアニメになります)");
  $("aDur").textContent = n>1 ? "ひとまわり "+(n/fps).toFixed(2)+"秒" : "";
  $("fDel").disabled = n<=1; $("fLeft").disabled = cur<=0; $("fRight").disabled = cur>=n-1;
  $("aPlay").disabled = n<=1;
}
function gotoFrame(k){
  if(k<0||k>=frames.length) return;
  animStop(true);
  frames[cur]=grid; cur=k; grid=frames[cur];
  render(); stripRender();
}
function insertFrame(b){
  if(frames.length>=MAX_FRAMES){ status("コマは"+MAX_FRAMES+"までです","err"); return; }
  animStop(true);
  frames[cur]=grid; frames.splice(cur+1,0,b); cur++; grid=frames[cur];
  render(); stripRender(); push();
}
$("fAdd").onclick=()=>insertFrame(new Uint8Array(NN));
$("fDup").onclick=()=>insertFrame(grid.slice());
$("fDel").onclick=()=>{
  if(frames.length<=1) return;
  animStop(true);
  frames.splice(cur,1); if(cur>=frames.length) cur=frames.length-1; grid=frames[cur];
  render(); stripRender(); push();
};
function moveFrame(d){
  const j=cur+d; if(j<0||j>=frames.length) return;
  animStop(true);
  frames[cur]=grid; const t=frames[cur]; frames[cur]=frames[j]; frames[j]=t; cur=j; grid=frames[cur];
  render(); stripRender(); push();
}
$("fLeft").onclick=()=>moveFrame(-1);
$("fRight").onclick=()=>moveFrame(1);
$("onion").onclick=e=>{ onionOn=!onionOn; e.target.classList.toggle("sel",onionOn); render(); };

// ---- 再生 ----
function showCells(b){
  for(let i=0;i<NN;i++){ cells[i].classList.toggle("on",!!b[i]); cells[i].classList.remove("onion"); }
  drawLed($("pv"),b);
}
function animStop(quiet){
  if(!AN.playing) return;
  AN.playing=false; clearTimeout(AN.timer);
  $("aPlay").textContent="▶ 再生"; gridEl.classList.remove("playing");
  document.querySelectorAll(".ft.play").forEach(x=>x.classList.remove("play"));
  if(!quiet) render();                     // 描いていたコマの表示に戻す
}
function animTick(){
  if(!AN.playing) return;
  const k=AN.i%frames.length, f=frames[k];
  showCells(f);
  document.querySelectorAll(".ft.play").forEach(x=>x.classList.remove("play"));
  const t=$("fstrip").children[k]; if(t) t.classList.add("play");
  if(curView==="mark" && $("live").checked) queueFrame(f);
  AN.i++;
  AN.next+=1000/(+$("aFps").value);
  const now=performance.now();
  if(AN.next<now-300) AN.next=now;
  AN.timer=setTimeout(animTick,Math.max(0,AN.next-now));
}
function animStart(){
  if(frames.length<2) return;
  frames[cur]=grid;
  AN.playing=true; AN.i=cur; AN.next=performance.now();
  $("aPlay").textContent="■ 止める"; gridEl.classList.add("playing");
  animTick();
}
$("aPlay").onclick=()=>{ AN.playing ? animStop() : animStart(); };
$("aFps").oninput=()=>{ $("aFpsV").textContent=$("aFps").value+"コマ/秒"; animInfo(); };
// 再生中にグリッドを押したら止めて、そのコマから描けるようにする
gridEl.addEventListener("pointerdown",()=>{ if(AN.playing) animStop(); },true);
// [ と ] でコマを移動
window.addEventListener("keydown",e=>{
  if(/INPUT|SELECT|TEXTAREA/.test(e.target.tagName) || curView!=="mark") return;
  if(e.key==="["){ e.preventDefault(); gotoFrame(cur-1); }
  else if(e.key==="]"){ e.preventDefault(); gotoFrame(cur+1); }
});

// ---- 番組に入れる ----
$("aToProg").onclick=()=>{
  frames[cur]=grid;
  const nm=$("name").value.trim();
  let sc;
  if(frames.length<2){
    sc=newScene("mark");
  }else{
    sc=newScene("anim");
    sc.frames=frames.map(toRows); sc.fps=+$("aFps").value;
    sc.hold=Math.max(0.5,Math.min(10,Math.round(frames.length/sc.fps*2)/2));   // 1まわり以上は見せる
    if(nm) sc.name=nm;
  }
  prog.scenes.push(sc); sel=prog.scenes.length-1; changed(true);
  status("番組の最後に入れました (シーン"+prog.scenes.length+" / "+(frames.length<2?"マーク":frames.length+"コマ")+")。「番組を作る」で動きを決められます","ok");
};

// ============================================================
// トゥイーン (自動中割り)
//   今のコマの絵を、はじめ→おわり の間で 位置・大きさ・点の残り を補間して並べる。
//   LEDは点くか消えるかだけなので、「点の残り」は 4×4 の網目 (Bayer) で間引いて表す。
// ============================================================
const TW_BAYER=[[0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]];
function twBounce(t){
  const n=7.5625, d=2.75;
  if(t<1/d) return n*t*t;
  if(t<2/d) return n*(t-=1.5/d)*t+0.75;
  if(t<2.5/d) return n*(t-=2.25/d)*t+0.9375;
  return n*(t-=2.625/d)*t+0.984375;
}
const TW_EASE={
  linear:t=>t,
  easeIn:t=>t*t*t,
  easeOut:t=>1-Math.pow(1-t,3),
  easeInOut:t=>t<0.5 ? 4*t*t*t : 1-Math.pow(-2*t+2,3)/2,
  bounce:twBounce
};
/// src を 大きさ s (中心基準) → (dx,dy) ずらし → 点の残り op で間引いた新しいコマ
function tweenFrame(src,dx,dy,s,op){
  const o=new Uint8Array(NN);
  if(s<=0.001 || op<=0) return o;
  for(let y=0;y<N;y++)for(let x=0;x<N;x++){
    const sx=Math.floor((x-dx-7.5)/s+7.5+1e-6), sy=Math.floor((y-dy-7.5)/s+7.5+1e-6);
    if(sx<0||sx>=N||sy<0||sy>=N||!src[sy*N+sx]) continue;
    if(op<1 && (TW_BAYER[y&3][x&3]+0.5)/16>=op) continue;
    o[y*N+x]=1;
  }
  return o;
}
/// 設定から n コマを作る (純粋な計算。テストしやすいよう DOM に触れない)
function tweenMake(src,p){
  const n=Math.max(2,Math.min(32,p.n|0)), ease=TW_EASE[p.ease]||TW_EASE.linear, out=[];
  for(let f=0;f<n;f++){
    // 片道は f/(n-1) でおわりに着く。往復は f/n にして、ループのつなぎ目で同じ絵が2回続かないようにする
    let t = p.pp ? f/n : f/(n-1);
    if(p.pp) t = t<=0.5 ? t*2 : (1-t)*2;
    const e=ease(t), L=(a,b)=>a+(b-a)*e;
    out.push(tweenFrame(src, Math.round(L(p.sx,p.ex)), Math.round(L(p.sy,p.ey)),
                        L(p.ss,p.es)/100, L(p.so,p.eo)/100));
  }
  return out;
}
const TW_PRESETS={
  sway:   {sx:0,  ex:0,  sy:0,   ey:-3, ss:100,es:100,so:100,eo:100,n:8, ease:"easeInOut",pp:true},
  inL:    {sx:-16,ex:0,  sy:0,   ey:0,  ss:100,es:100,so:100,eo:100,n:10,ease:"easeOut",  pp:false},
  outR:   {sx:0,  ex:16, sy:0,   ey:0,  ss:100,es:100,so:100,eo:100,n:10,ease:"easeIn",   pp:false},
  inT:    {sx:0,  ex:0,  sy:-16, ey:0,  ss:100,es:100,so:100,eo:100,n:12,ease:"bounce",   pp:false},
  pop:    {sx:0,  ex:0,  sy:6,   ey:0,  ss:100,es:100,so:0,  eo:100,n:6, ease:"easeOut",  pp:false},
  fadeIn: {sx:0,  ex:0,  sy:0,   ey:0,  ss:100,es:100,so:0,  eo:100,n:8, ease:"linear",   pp:false},
  fadeOut:{sx:0,  ex:0,  sy:0,   ey:0,  ss:100,es:100,so:100,eo:0,  n:8, ease:"linear",   pp:false},
  zoomIn: {sx:0,  ex:0,  sy:0,   ey:0,  ss:0,  es:100,so:100,eo:100,n:8, ease:"easeOut",  pp:false},
  beat:   {sx:0,  ex:0,  sy:0,   ey:0,  ss:100,es:125,so:100,eo:100,n:6, ease:"easeInOut",pp:true}
};
const TW_IDS={sx:"twSX",ex:"twEX",sy:"twSY",ey:"twEY",ss:"twSS",es:"twES",so:"twSO",eo:"twEO",n:"twN"};
$("twPreset").onchange=e=>{
  const p=TW_PRESETS[e.target.value]; if(!p) return;
  for(const k in TW_IDS) $(TW_IDS[k]).value=p[k];
  $("twEase").value=p.ease; $("twPP").checked=p.pp;
  status("ひな形を入れました。「コマを作る」で反映されます","ok");
};
function twParams(){
  const p={}, num=id=>{ const v=parseFloat($(id).value); return Number.isFinite(v)?v:0; };
  for(const k in TW_IDS) p[k]=num(TW_IDS[k]);
  p.sx=Math.max(-16,Math.min(16,p.sx)); p.ex=Math.max(-16,Math.min(16,p.ex));
  p.sy=Math.max(-16,Math.min(16,p.sy)); p.ey=Math.max(-16,Math.min(16,p.ey));
  p.ss=Math.max(0,Math.min(300,p.ss)); p.es=Math.max(0,Math.min(300,p.es));
  p.so=Math.max(0,Math.min(100,p.so)); p.eo=Math.max(0,Math.min(100,p.eo));
  p.ease=$("twEase").value; p.pp=$("twPP").checked;
  return p;
}
$("twGen").onclick=()=>{
  animStop(true);
  frames[cur]=grid;
  if(!grid.some(v=>v)){ status("今のコマが空です。絵を描くか呼び出してから作ってください","err"); return; }
  const p=twParams(), made=tweenMake(grid,p);
  const replace=$("twPlace").value==="replace";
  if(frames.length-(replace?1:0)+made.length>MAX_FRAMES){
    status("コマが"+MAX_FRAMES+"を超えます。コマ数を減らすか、いらないコマを消してください","err"); return;
  }
  if(replace){ frames.splice(cur,1,...made); }
  else{ frames.splice(cur+1,0,...made); cur++; }
  grid=frames[cur];
  render(); stripRender(); push();
  status(made.length+"コマ作りました"+(p.pp?" (往復)":"")+"。▶ 再生で確かめられます","ok");
};
