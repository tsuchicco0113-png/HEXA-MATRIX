// C++ 側: 入力ファイル (1行目 .hxc の16進、2行目 seed、以下 "gx gy gz wz ev") を流して、コマを16進で出す
//   g++ -std=c++17 tests/hako_parity.cpp -o /tmp/hp && node tests/hako_parity.js   (JS と比べる)
#include <cstdio>
#include <cstring>
#include <string>
#include <iostream>
#include "../firmware/HexaMatrixFW/hxm_char.h"
int main(int argc,char**argv){
  std::string hex; uint32_t seed; std::cin>>hex>>seed;
  uint8_t b[HXC_FILE_SIZE]; for(int i=0;i<HXC_FILE_SIZE;i++) b[i]=(uint8_t)std::stoi(hex.substr(i*2,2),nullptr,16);
  HxcSprite s; HxcParams p; uint16_t t[16]; char nm[17];
  if(!hxcParse(b,sizeof b,s,p,t,nm)){ puts("BAD"); return 1; }
  HxcWorld w; w.init(s,p,seed); memcpy(w.terrain,t,sizeof t); w.fit();
  int gx,gy,gz,wz,ev;
  while(std::cin>>gx>>gy>>gz>>wz>>ev){ HxcIn in; in.gx=gx; in.gy=gy; in.gz=gz; in.wz=wz; in.ev=ev; w.step(in); uint8_t f[32]; w.render(f);
    for(int i=0;i<32;i++) printf("%02x",f[i]); printf(" %d %d %d\n",(int)w.st,(int)w.q,(int)w.rng); }
}
