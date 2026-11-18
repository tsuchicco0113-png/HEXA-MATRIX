#!/bin/bash
# HEXA MATRIX イベント用アクセスポイント (v0.9.6)
#   会場にルーターが無い時、CPZ を Wi-Fi のアクセスポイントにして CoreMatrix をつなぐ。
#   CoreMatrix 側は wifi.txt の ssid2= / pass2= (または CPZ アプリの「本体に教える」) にこの名前とパスワードを入れておく。
#   家の Wi-Fi が見つからないと、CoreMatrix は 15 秒で 2つ目 (ここ) へ切り替える。
#
#   usage: hexa-ap on | off | status      (install.sh が /usr/local/sbin/hexa-ap に置き、ハブから sudo -n で呼ぶ)
#   設定: /etc/hexa-matrix/ap.conf   AP_SSID= / AP_PASS= (8文字以上) / AP_IFACE= (省略で最初の Wi-Fi)
#   NetworkManager (nmcli) が必要。2.4GHz 固定 (ESP32 は 5GHz を使えない)、WPA2。CPZ の IP は 10.42.0.1
#   つないでいる間、CPZ 自身は家の Wi-Fi から外れる (Wi-Fi が1つなので)。off で家の Wi-Fi に戻る。
#   再起動すると自動では AP にならない (autoconnect no)。
set -u
CONF=/etc/hexa-matrix/ap.conf
AP_SSID=hexamatrix-ap; AP_PASS=""; AP_IFACE=""
[ -r "$CONF" ] && . "$CONF"
CON=hexa-ap

jstr() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
fail() { printf '{"ok":false,"err":"%s"}\n' "$(jstr "$1")"; exit 2; }
state() {
  local on=false ip=""
  if nmcli -t -f NAME con show --active 2>/dev/null | grep -qx "$CON"; then
    on=true
    ip=$(nmcli -g IP4.ADDRESS con show "$CON" 2>/dev/null | head -1 | cut -d/ -f1)
  fi
  printf '{"ok":true,"on":%s,"ssid":"%s","pass":"%s","ip":"%s","iface":"%s"}\n' \
    "$on" "$(jstr "$AP_SSID")" "$(jstr "$AP_PASS")" "$(jstr "${ip:-}")" "$(jstr "$AP_IFACE")"
}

command -v nmcli >/dev/null 2>&1 || fail "nmcli がありません (NetworkManager が必要です)"
[ -n "$AP_IFACE" ] || AP_IFACE=$(nmcli -t -f DEVICE,TYPE device 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}')
[ -n "$AP_IFACE" ] || fail "Wi-Fi の装置が見つかりません"

case "${1:-status}" in
  on)
    [ ${#AP_PASS} -ge 8 ] || fail "$CONF の AP_PASS を8文字以上にしてください"
    nmcli con delete "$CON" >/dev/null 2>&1 || true
    nmcli con add type wifi ifname "$AP_IFACE" con-name "$CON" autoconnect no ssid "$AP_SSID" \
      802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared \
      wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp \
      wifi-sec.psk "$AP_PASS" >/dev/null 2>&1 || fail "アクセスポイントを作れませんでした"
    nmcli con up "$CON" >/dev/null 2>&1 || fail "アクセスポイントを始められませんでした (この Wi-Fi は AP にできないかもしれません)"
    state ;;
  off)
    nmcli con down "$CON" >/dev/null 2>&1 || true
    nmcli device connect "$AP_IFACE" >/dev/null 2>&1 || true     # 家の Wi-Fi へ戻す (見つかれば)
    state ;;
  status)
    state ;;
  *)
    fail "usage: hexa-ap on|off|status" ;;
esac
