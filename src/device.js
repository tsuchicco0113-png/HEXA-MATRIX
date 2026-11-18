// ============================================================
// 本体の番組 (SD / 本体フラッシュ)。ファームの hxm_xfer.h と対になる
// ============================================================
const HXF={BEGIN:0x10,DATA:0x11,END:0x12,LIST:0x13,DEL:0x14,PLAY:0x15};
const CRC_T=(()=>{ const t=new Uint32Array(256); for(let n=0;n<256;n++){ let c=n; for(let k=0;k<8;k++) c=(c&1)?(0xEDB88320^(c>>>1)):(c>>>1); t[n]=c>>>0; } return t; })();
function crc32(u8){ let c=0xFFFFFFFF; for(let i=0;i<u8.length;i++) c=CRC_T[(c^u8[i])&255]^(c>>>8); return (c^0xFFFFFFFF)>>>0; }
const u32le=v=>[v&255,(v>>>8)&255,(v>>>16)&255,(v>>>24)&255];
const ascii=s=>[...s].map(c=>c.charCodeAt(0));

let waiters=[], devBusy=false, devList=null, devFw="", devWin=0;
/// 返事を待たずに先へ送ってよい DATA の数。ファーム v0.9.5〜 は PING の "win" で教えてくれる。それより前は1つずつ
const xferWin=()=>Math.max(1,Math.min(16,devWin||1));
const fwOld=()=>!!devFw && devFw.localeCompare("0.3.0",undefined,{numeric:true})<0;
/// 本体の返事 (1行JSON) を待つ。ok:false が来たらその内容で失敗にする
function waitReply(pred,ms){
  return new Promise((res,rej)=>{
    const w={pred:pred,res:res,rej:rej};
    w.t=setTimeout(()=>{ waiters=waiters.filter(x=>x!==w); rej(new Error("本体から返事がありません")); },ms);
    waiters.push(w);
  });
}
function deliverReply(j){
  for(const w of waiters.slice()){
    if(j.ok===false){ clearTimeout(w.t); waiters=waiters.filter(x=>x!==w); w.rej(new Error(errText(j.err))); continue; }
    if(w.pred(j)){ clearTimeout(w.t); waiters=waiters.filter(x=>x!==w); w.res(j); }
  }
}
function errText(e){
  return ({"no storage":"保存先がありません","bad name":"ファイル名が使えません","no space":"空きが足りません",
    "seq":"順番が乱れました","too big":"大きさが合いません","crc":"中身が壊れました","size":"大きさが合いません",
    "open failed":"ファイルを作れません","write failed":"書き込めません","rename failed":"名前を付けられません",
    "not found":"見つかりません","upload timeout":"途中で止まりました",
    "busy":"本体が別の受け取りの最中です (CPZ から Wi-Fi で送っていませんか)。少し待ってもう一度",
    "auth":"本体の合言葉が必要です (Wi-Fi)","no memory":"本体のメモリが足りません","bad clip":"コマ列の形が違います",
    "unknown type":"本体のファームが古いです。v0.3.0 以上を書き込んでください"})[e]||e||"エラー";
}
/// 返事が送信より先に届いても取りこぼさないよう、待ちを先に登録してから送る
async function request(type,payload,pred,ms){
  const p=waitReply(pred,ms||3000);
  if(!await tx(packet(type,payload))) p.catch(()=>{});
  return p;
}

/// ファイル転送 (BEGIN / DATA / END)。名前が @live / @once なら本体はメモリに置いて流す (一時再生、v0.6〜)。
/// STUDIO の中の転送は1本の列に並べる (本体に保存とプレビューの転送が混ざらないように)
let xferChain=Promise.resolve();
function xferFile(name,data,onProgress){
  const run=async()=>{
    await request(HXF.BEGIN,u32le(data.length).concat(ascii(name)),j=>j.ack==="begin",4000);
    const CH=200, win=xferWin(), pend=[];
    // v0.9.5: 返事を待たずに win 個先まで送る (USB の往復の待ちで遅くならないように)。古いファームは win=1
    try{
      for(let seq=0,off=0;off<data.length;seq++,off+=CH){
        const chunk=[...data.subarray(off,off+CH)];
        const s=seq&0xFFFF;
        const p=request(HXF.DATA,[s&255,s>>8].concat(chunk),j=>j.ack===s,4000+win*500);
        p.catch(()=>{});                             // 待つ前に失敗しても「未処理」にしない (後で await する)
        pend.push(p);
        if(pend.length>=win) await pend.shift();
        if(onProgress) onProgress(Math.min(1,(off+CH)/data.length));
      }
      while(pend.length) await pend.shift();
    }finally{ pend.length=0; }
    return await request(HXF.END,u32le(crc32(data)),j=>j.saved!==undefined||typeof j.clip==="number",8000);
    // ↑ PING の返事の clip は true/false、END の返事はコマ数 (数) なので数だけ見る
  };
  const p=xferChain.then(run,run);
  xferChain=p.catch(()=>{});
  return p;
}
const clipOK=()=>!!devFw && devFw.localeCompare("0.6.0",undefined,{numeric:true})>=0;

function slug(s){ return String(s||"").normalize("NFKC").replace(/[^A-Za-z0-9_-]+/g,"_").replace(/^_+|_+$/g,"").slice(0,30); }
function suggestName(){
  const used=new Set((devList&&devList.files||[]).map(f=>f.n));
  const base=slug(prog.name)||"program";
  for(let i=1;i<100;i++){ const n=String(i).padStart(2,"0")+"_"+base+".hxm"; if(![...used].some(u=>u.slice(0,3)===n.slice(0,3))) return n; }
  return base+".hxm";
}
function devRender(){
  const el=$("devList"); el.innerHTML="";
  const on=!!writer;
  for(const id of ["devSave","devRefresh","devPause"]) $(id).disabled=!on||devBusy||fwOld();
  if(!on){ $("devStore").textContent="未接続"; return; }
  if(fwOld()){ $("devStore").textContent="本体のファームが v"+devFw+" です。v0.3.0 以上を書き込むと使えます"; $("devStore").style.color="var(--warn)"; return; }
  $("devStore").style.color="";
  if(!devList){ $("devStore").textContent="-"; return; }
  const st={sd:"microSD",flash:"本体メモリ (カードなし)",none:"保存先なし"}[devList.store]||devList.store;
  $("devStore").textContent=st+(devList.store!=="none"?" ・ 空き "+(devList.free>=1024?(devList.free/1024).toFixed(1)+"MB":devList.free+"KB"):"");
  if(devList.sd==="unreadable"){ $("devStore").textContent+=" ※ microSDが読めません。FAT32 でフォーマットし直してください"; $("devStore").style.color="var(--warn)"; }
  if(!devList.files.length){ const d=document.createElement("div"); d.className="empty"; d.textContent="まだ番組がありません。下の「本体に保存」で送ってください。"; el.appendChild(d); }
  devList.files.forEach((f,i)=>{
    const r=document.createElement("div"); r.className="dev"+(i===devList.cur?" sel":"");
    const t=document.createElement("span"); t.className="dn"; t.textContent=(i+1)+". "+f.n; r.appendChild(t);
    const z=document.createElement("span"); z.className="lbl"; z.textContent=(f.s/1024).toFixed(1)+"KB"; r.appendChild(z);
    const p=document.createElement("button"); p.textContent="▶"; p.title="本体でこの番組を流す"; p.disabled=devBusy;
    p.onclick=()=>devDo(async()=>{ stopPlay(); await request(HXF.PLAY,[i],j=>j.dev!==undefined); devList.cur=i; devRender(); });
    const x=document.createElement("button"); x.textContent="✕"; x.className="warn"; x.title="本体から消す"; x.disabled=devBusy;
    x.onclick=()=>{ if(!confirm("本体から「"+f.n+"」を消します。よろしいですか？")) return;
      devDo(async()=>{ const j=await request(HXF.DEL,ascii(f.n),j=>j.list); devList=j; devRender(); log("消しました: "+f.n,"ok"); }); };
    r.appendChild(p); r.appendChild(x); el.appendChild(r);
  });
}
async function devDo(fn){
  if(devBusy||!writer) return;
  devBusy=true; devRender();
  try{ await fn(); }catch(e){ log("本体: "+e.message,"err"); status(e.message,"err"); }
  devBusy=false; devRender();
}
async function devRefresh(){ if(fwOld()) return; await devDo(async()=>{ devList=await request(HXF.LIST,[],j=>j.list,4000); if(!$("devName").value) $("devName").value=suggestName(); }); }
$("devRefresh").onclick=devRefresh;
$("devPause").onclick=()=>devDo(async()=>{ stopPlay(); await request(HXF.PLAY,[0xFF],j=>j.dev!==undefined); log("本体の再生を止めました (本体のBで再開)","ok"); });
$("devSave").onclick=()=>devDo(async()=>{
  let name=$("devName").value.trim()||suggestName();
  name=slug(name.replace(/\.hxm$/i,""));
  name = name ? name+".hxm" : suggestName();       // 英数字が残らない名前 (日本語だけ等) は番号付きの名前にする
  $("devName").value=name;
  const f=renderProgram(programSequence().list), data=bakeBin(f,prog.loop===false);
  stopPlay();                                      // 送っている間は実機へのプレビューを止める
  await new Promise(r=>setTimeout(r,120));
  const bar=$("devBar"); bar.style.width="0%"; $("devProg").style.display="block";
  const t0=performance.now(), win=xferWin();
  const j=await xferFile(name,data,f=>{ bar.style.width=Math.round(f*100)+"%"; });
  log("本体に保存しました: "+j.saved+" ("+(data.length/1024).toFixed(1)+"KB / "+((performance.now()-t0)/1000).toFixed(1)+"秒 / 窓"+win+")","ok");
  status("本体に保存しました。本体だけで流れます","ok");
  devList=await request(HXF.LIST,[],j=>j.list,4000);
  $("devName").value=suggestName();
  setTimeout(()=>{ $("devProg").style.display="none"; },1500);
});
