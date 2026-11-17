#include <cstdio>
#include <cassert>
#include <string>
#include "../firmware/HexaMatrixFW/hxm_wifi.h"   // g++ -std=c++17 tests/wifi_txt_test.cpp && ./a.out
int main(){
  const char* t="\xEF\xBB\xBF# 家のWi-Fi\r\nssid = MyHome-5G \r\npass=p@ss=word 1\r\nname=Hexa_Matrix-1\r\n";
  HxmWifiCfg c; assert(hxm_wifi_parse(t,strlen(t),&c));
  printf("ssid[%s] pass[%s] name[%s] masked=%d\n",c.ssid,c.pass,c.name,c.passMasked);
  char out[512]; size_t m=hxm_wifi_mask(t,strlen(t),out,sizeof out); out[m]=0;
  printf("masked file:\n%s---\n",out);
  HxmWifiCfg d; hxm_wifi_parse(out,m,&d); printf("after: pass[%s] masked=%d\n",d.pass,d.passMasked);
  assert(hxm_wifi_mask(out,m,out+300,200)==0);
  const char* e="ssid=\n"; hxm_wifi_parse(e,strlen(e),&d); printf("empty ssid has=%d ssid[%s]\n",d.hasSsid,d.ssid);
  const char* nopw="ssid=open\n"; hxm_wifi_parse(nopw,strlen(nopw),&d); printf("open: hasPass=%d mask=%zu\n",d.hasPass,hxm_wifi_mask(nopw,strlen(nopw),out,512));
  const char* last="ssid=a\npass=xyz"; m=hxm_wifi_mask(last,strlen(last),out,512); out[m]=0; printf("no newline: [%s]\n",out);
}
