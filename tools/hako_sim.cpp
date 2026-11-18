// 箱庭のプレビュー: g++ -std=c++17 tools/hako_sim.cpp -o /tmp/hako_sim && /tmp/hako_sim > /tmp/sim.txt && python3 tools/hako_gif.py /tmp/sim.txt
// 箱庭のシナリオを流して、コマごとに 加速度/状態/16x16 を出す
#include <cstdio>
#include <cmath>
#include <cstdlib>
#include "../firmware/HexaMatrixFW/hxm_char.h"
int main(){
  HxcSprite s; s.parse(HXC_BUILTIN,HXC_BUILTIN_H);
  HxcParams p; p.sleepAfter=60*3;
  HxcWorld w; w.init(s,p,12345);
  double ang=0;  // 本体の傾き (度)。0=吊るして正立
  srand(4);
  for(int t=0;t<60*24;t++){
    double sec=t/60.0; uint8_t ev=0; const char* lab="吊るしている";
    double gx,gy, shake=0, sw=0;
    if(sec<2.5){ ang=0; }
    else if(sec<5.0){ lab="ぶらぶら揺れる"; ang=14*sin((sec-2.5)*2*M_PI*1.3)*exp(-(sec-2.5)*0.5); }
    else if(sec<6.5){ lab="トンと叩く"; ang=0; if(t==(int)(5.2*60)) ev=HXC_TAP; if(t==(int)(5.9*60)) ev=HXC_TAP; }
    else if(sec<9.0){ lab="横に倒す"; double k=std::min(1.0,(sec-6.5)/0.7); ang=-90*k; }
    else if(sec<11.5){ lab="ひっくり返す"; double k=std::min(1.0,(sec-9.0)/0.8); ang=-90-90*k; }
    else if(sec<13.0){ lab="元に戻す"; double k=std::min(1.0,(sec-11.5)/0.8); ang=-180+180*k; }
    else if(sec<15.0){ lab="振る"; ang=0; if(sec<13.8){ shake=900; } if(t==(int)(13.5*60)) ev=HXC_SHAKE; }
    else if(sec<21.5){ lab=w.sleeping()?"(静かにしていると寝る)":"静かに吊るしておく"; ang=0; }
    else { lab="手に取る"; ang=(sec<22.0)?8*sin((sec-21.5)*20):0; }
    double r=ang*M_PI/180;
    gx= -1000*sin(r); gy=1000*cos(r);       // 本体を左へ回す(ang<0) と、画面では重力が左へ
    if(shake>0){ gx+=rand()%(int)(2*shake)-shake; gy+=rand()%(int)(2*shake)-shake; }
    HxcIn in; in.gx=(int16_t)gx; in.gy=(int16_t)gy; in.ev=ev; w.step(in);
    if(t%2==0){ uint8_t f[32]; w.render(f); printf("%.3f|%d|%s|%d|",ang,w.st,lab,w.sleeping());
      for(int i=0;i<32;i++) printf("%02x",f[i]); printf("\n"); }
  }
}
