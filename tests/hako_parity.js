// JS 版の箱庭エンジン (src/hako_engine.js) が C++ (hxm_char.h) と同じコマを出すか、何通りかの入力で比べる
//   g++ -std=c++17 tests/hako_parity.cpp -o /tmp/hp && node tests/hako_parity.js
const {HxcWorld,hxcSpriteFromLines,hxcBake,hxcParse,HXC_DEFAULT,HXC_BUILTIN_ROWS}=require("../src/hako_engine.js");
const {execFileSync}=require("child_process");
const BIN=process.argv[2]||"/tmp/hp";
let seed=12345; const R=()=>{ seed=(seed*1103515245+12345)&0x7fffffff; return seed; };
function cases(){
  const small=hxcSpriteFromLines([".###.","#.#.#","#####",".#.#."]);
  const blob=hxcSpriteFromLines(["..##..",".####.","##.###","######","######","#.##.#"]);
  const ter=new Array(16).fill(0); ter[10]=0x0FF0; ter[5]=0x00F0; for(let y=0;y<16;y++) ter[y]|=(y>12?0x0003:0);
  return [
    {name:"組み込み", sp:hxcSpriteFromLines(HXC_BUILTIN_ROWS), p:{sleepAfter:900}, ter:new Array(16).fill(0)},
    {name:"小さい+地形", sp:small, p:{grav:40,bounce:150,whim:220,sleepAfter:200}, ter},
    {name:"6x6 すべり+慣性", sp:blob, p:{fric:8,stick:60,slosh:40,maxv:220,jump:300,sleepAfter:600}, ter:new Array(16).fill(0)},
    {name:"組み込み+床2行 (回すと地形にかかる)", sp:hxcSpriteFromLines(HXC_BUILTIN_ROWS), p:{sleepAfter:900}, ter:Array.from({length:16},(_,y)=>y>=14?0xFFFF:0)},
    {name:"重い・跳ねない", sp:hxcSpriteFromLines(HXC_BUILTIN_ROWS), p:{grav:120,bounce:0,whim:0,sleepAfter:90}, ter:new Array(16).fill(0)},
  ];
}
function inputs(n){
  // 0〜999: 揺らす (ときどき叩く・振る・なでる・つつく) / 1000〜2999: 静かに置く (寝る) / 3000: 動かす (起きる) …をくり返す
  const L=[]; let ang=0; const EV=[1,2,4,8];
  for(let i=0;i<n;i++){
    const ph=i%3200, quiet=ph>=1000&&ph<3000;
    if(!quiet) ang+=((R()%200)-100)/700; else ang*=0.98;
    let gx=Math.round(-1000*Math.sin(ang)), gy=Math.round(1000*Math.cos(ang)), gz=0, wz=0, ev=0;
    if(!quiet){ gx+=(R()>>4)%300-150; gy+=(R()>>4)%300-150; gz=(R()>>4)%400-200; wz=(R()>>4)%600-300; if(ph%170===37) ev=EV[(i/170|0)%4]; }
    L.push(`${gx} ${gy} ${gz} ${wz} ${ev}`);
  }
  return L;
}
let bad=0;
for(const c of cases()){
  const p=Object.assign({},HXC_DEFAULT,c.p), file=hxcBake(c.sp,p,c.ter,c.name), hex=Buffer.from(file).toString("hex");
  const sd=(R()>>>0)||1, ins=inputs(16000);
  const cpp=execFileSync(BIN,{input:hex+"\n"+sd+"\n"+ins.join("\n")+"\n",maxBuffer:1<<26}).toString().trim().split("\n");
  const pr=hxcParse(file), w=new HxcWorld(); w.init(pr.sp,pr.p,sd); w.terrain=pr.terrain.slice(); w.fit();
  let diff=-1;
  for(let i=0;i<ins.length;i++){
    const [gx,gy,gz,wz,ev]=ins[i].split(" ").map(Number); w.step({gx,gy,gz,wz,ev});
    const js=Buffer.from(w.render()).toString("hex")+" "+w.st+" "+w.q+" "+(w.rng|0);
    if(js!==cpp[i]){ diff=i; console.log("  JS ",js,"\n  C++",cpp[i]); break; }
  }
  const sts=new Set(cpp.map(l=>l.split(" ")[1]));
  console.log((diff<0?"一致":"ずれ "+diff+" 回目")+` : ${c.name} (${ins.length} step、通った状態 ${[...sts].sort().join(",")})`);
  if(diff>=0) bad++;
  if(sts.size<8){ console.log("  ※ 通っていない状態がある"); bad++; }
}
process.exit(bad?1:0);
