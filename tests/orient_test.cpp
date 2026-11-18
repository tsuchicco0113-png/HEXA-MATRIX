#include <cstdio>
#include <cassert>
#include <cmath>
#include "../firmware/HexaMatrixFW/hxm_orient.h"   // g++ -std=c++17 tests/orient_test.cpp && ./a.out
// 実機の対応がどうであっても覚えれば当たるか: 本当の対応 = base + dir*90*r
static void trial(float base, float dir){
  HxmOrient o; o.clear();
  auto truth=[&](int r){ return hxm_wrap180(base+dir*90.f*r); };
  float d; assert(o.best(0,&d)==-1);
  o.learn(1, truth(1)+3);                       // 1つ覚えた (少しずれて)
  assert(o.best(truth(1),&d)==1);
  assert(o.best(truth(3),&d)==3);               // 逆さまは1つでも当たる
  bool ok90 = o.best(truth(2),&d)==2;           // 90° は回り方しだい
  assert(ok90 == (dir>0));
  o.learn(2, truth(2)-4);                       // 隣を覚えたら全部当たる
  for(int r=0;r<4;r++){ assert(o.best(truth(r)+20,&d)==r); assert(o.best(truth(r)-20,&d)==r); }
  o.learn(0, truth(2));                         // 言い直し: 2 の傾きで 0 と言った → 2 は忘れる
  assert(std::isnan(o.ang[2]) && o.best(truth(2),&d)==0);
}
int main(){
  for(float b=-170;b<=180;b+=37){ trial(b,1); trial(b,-1); }
  float a; assert(!hxm_tilt(0,0,1,&a)); assert(hxm_tilt(0,-1,0.1f,&a) && fabsf(a+90)<0.1f);
  HxmShake s; int hits=0; uint32_t t=1000;
  for(int i=0;i<3;i++){ hits+=s.feed(2.5f,t); t+=200; } assert(hits==1);
  hits=0; for(int i=0;i<3;i++){ hits+=s.feed(2.5f,t); t+=200; } assert(hits==0);          // 冷却中
  t+=2000; hits=0; for(int i=0;i<3;i++){ hits+=s.feed(2.5f,t); t+=500; } assert(hits==0); // 間が空きすぎ
  t+=2000; hits=0; for(int i=0;i<6;i++){ hits+=s.feed(1.0f,t); t+=100; } assert(hits==0); // 静か
  puts("orient ok");
}
