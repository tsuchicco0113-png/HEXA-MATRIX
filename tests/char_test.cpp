#include <cstdio>
#include <cassert>
#include <cmath>
#include <cstdlib>
#include "../firmware/HexaMatrixFW/hxm_char.h"   // g++ -std=c++17 tests/char_test.cpp && ./a.out
static HxcWorld mk(uint32_t seed=7){ HxcSprite s; s.parse(HXC_BUILTIN,HXC_BUILTIN_H); HxcParams p; p.sleepAfter=60*4; HxcWorld w; w.init(s,p,seed); return w; }
static void run(HxcWorld& w,int n,int gx,int gy,uint8_t ev=0){ for(int i=0;i<n;i++){ HxcIn in; in.gx=gx; in.gy=gy; in.ev=(i==0?ev:0); w.step(in);} }
static void show(const HxcWorld& w,const char* t){ uint8_t f[32]; w.render(f); printf("-- %s (q=%d st=%d x=%d y=%d)\n",t,w.q,w.st,(int)(w.x>>8),(int)(w.y>>8));
  for(int y=0;y<16;y++){ for(int x=0;x<16;x++) putchar((f[y*2+(x>>3)]>>(7-(x&7)))&1?'#':'.'); putchar('\n'); } }
static int lit(const HxcWorld& w){ uint8_t f[32]; w.render(f); int n=0; for(int i=0;i<32;i++) n+=__builtin_popcount(f[i]); return n; }
int main(){
  HxcWorld w=mk();
  assert(w.eyeX[0]==3&&w.eyeY[0]==2&&w.eyeX[1]==10&&w.eyeY[1]==3); assert(w.legN==4);
  run(w,120,0,1000); assert(w.grounded && (w.y>>8)==6 && w.q==0); show(w,"吊るして静止");
  // 叩く → 跳んで、着地でつぶれる
  { HxcWorld a=w; HxcIn in; in.gy=1000; in.ev=HXC_TAP; a.step(in); int top=99; bool sawLand=false, sawAir=false;
    for(int i=0;i<120;i++){ HxcIn j; j.gy=1000; a.step(j); top=std::min(top,(int)(a.y>>8)); sawLand|=a.st==HXC_LAND; sawAir|=a.st==HXC_AIR; }
    printf("tap: top y=%d air=%d land=%d g=%d\n",top,sawAir,sawLand,a.grounded); fflush(stdout); assert(sawAir&&sawLand&&top<=3&&a.grounded); }
  // 少し傾いても滑らない / 大きく傾けると壁まで
  { HxcWorld a=w; int x0=a.x>>8; run(a,120,100,995); assert((a.x>>8)==x0); run(a,120,600,800); assert((a.x>>8)==16-14); printf("tilt ok x=%d\n",(int)(a.x>>8)); }
  // 左へ90°回す → 左の壁が床 (10x14)
  { HxcWorld a=w; run(a,150,-1000,0); assert(a.q==1 && a.grounded && (a.x>>8)==0 && a.bw()==10 && a.bh()==14); show(a,"左が下"); }
  // 逆さま → 天井が床
  { HxcWorld a=w; run(a,150,0,-1000); assert(a.q==2 && a.grounded && (a.y>>8)==0); show(a,"逆さま"); }
  // 右が下
  { HxcWorld a=w; run(a,150,1000,0); assert(a.q==3 && a.grounded && (a.x>>8)==6); show(a,"右が下"); }
  // 寝る → 動かすと起きる
  { HxcWorld a=w; a.pr.whim=0; run(a,60*5,0,1000); assert(a.st==HXC_SLEEP); show(a,"寝た"); HxcIn in; in.gx=400; in.gy=900; a.step(in); assert(a.st==HXC_WAKE||a.st==HXC_AIR); printf("wake st=%d\n",a.st); }
  // 振る → 目が回る
  { HxcWorld a=w; run(a,1,0,1000,HXC_SHAKE); assert(a.st==HXC_DIZZY); run(a,130,0,1000); assert(a.st!=HXC_DIZZY); }
  // 歩く (傾いて床を滑る間) は脚を交互に
  { HxcWorld a=w; a.x=0; a.pr.fric=8; bool walk=false; for(int i=0;i<40;i++){ HxcIn in; in.gx=500; in.gy=860; a.step(in); walk|=a.st==HXC_WALK; } assert(walk); }
  // 同じ入力なら同じ動き
  { HxcWorld a=mk(99), b=mk(99); srand(3); for(int i=0;i<5000;i++){ HxcIn in; in.gx=rand()%2001-1000; in.gy=rand()%2001-1000; in.ev=(rand()%300==0)?HXC_TAP:0; a.step(in); b.step(in); uint8_t fa[32],fb[32]; a.render(fa); b.render(fb); assert(!memcmp(fa,fb,32)); } puts("determinism ok"); }
  // 乱暴に揺らしても箱からはみ出さない・点の数は変わりすぎない
  { HxcWorld a=mk(5); srand(11); double ang=0; for(int i=0;i<20000;i++){ ang+= (rand()%200-100)/1000.0; HxcIn in; in.gx=(int)(1000*sin(ang))+rand()%600-300; in.gy=(int)(1000*cos(ang))+rand()%600-300; in.ev=(rand()%400==0)?HXC_TAP:(rand()%900==0)?HXC_SHAKE:0; a.step(in);
      int x=a.x>>8,y=a.y>>8; assert(x>=0&&y>=0&&x+a.bw()<=16&&y+a.bh()<=16); int n=lit(a); assert(n>=90&&n<=125); } puts("fuzz ok"); }
  // 重い設定でも、止まっている時に「着地」のまま固まらない
  { HxcWorld a=mk(); a.pr.grav=120; a.pr.bounce=0; a.pr.whim=0; int land=0; for(int i=0;i<300;i++){ HxcIn in; in.gy=1000; a.step(in); if(i>60) land+=a.st==HXC_LAND; } assert(land==0); puts("heavy ok"); }
  // .hxc: 書いて読むと同じ。壊れた物は読まない
  { HxcSprite s; s.parse(HXC_BUILTIN,HXC_BUILTIN_H); HxcParams p; p.grav=31; p.whim=7; p.sleepAfter=999; uint16_t t[16]={0}; t[3]=0x00F0;
    uint8_t b[HXC_FILE_SIZE]; hxcBake(b,s,p,t,"gomaebi"); HxcSprite s2; HxcParams p2; uint16_t t2[16]; char nm[17];
    assert(hxcParse(b,sizeof b,s2,p2,t2,nm)); assert(s2.w==14&&s2.h==10&&!memcmp(s2.rows,s.rows,sizeof s.rows)); assert(p2.grav==31&&p2.whim==7&&p2.sleepAfter==999&&p2.jump==p.jump);
    assert(t2[3]==0x00F0 && !strcmp(nm,"gomaebi"));
    b[0]='X'; assert(!hxcParse(b,sizeof b,s2,p2,t2,nm)); b[0]='H'; b[4]=0; assert(!hxcParse(b,sizeof b,s2,p2,t2,nm)); assert(!hxcParse(b,50,s2,p2,t2,nm)); puts("hxc ok"); }
  puts("char ok");
}
