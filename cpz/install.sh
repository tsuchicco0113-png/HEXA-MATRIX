#!/bin/sh
# HEXA MATRIX installer for CardputerZero
# 使い方: cd ~/hexa-matrix && sh cpz/install.sh   (sudo は付けずに実行)
set -e
DIR=$(cd "$(dirname "$0")" && pwd)          # .../hexa-matrix/cpz
U=$(id -un)
if [ "$U" = "root" ]; then
  echo "sudo を付けずに実行してください (sh cpz/install.sh)"; exit 1
fi
APPL=/usr/share/APPLaunch
PORT=8090

echo "== packages"
sudo apt-get install -y python3-pil python3-numpy python3-qrcode libnss-mdns >/dev/null   # libnss-mdns: hexamatrix.local を引く

echo "== files"
chmod +x "$DIR/hmatrixd.py" "$DIR/hmatrix_app.py" "$DIR/hmatrix-app"
sudo ln -sf "$DIR/hmatrix-app" /usr/local/bin/hmatrix-app

echo "== permissions (USBシリアル / 画面 / キーボードを sudo なしで使う)"
NEED_REBOOT=0
for g in dialout video input; do
  if ! id -nG "$U" | tr ' ' '\n' | grep -qx "$g"; then
    sudo usermod -aG "$g" "$U"
    NEED_REBOOT=1
  fi
done

echo "== event access point (hexa-ap)"
# v0.9.6: イベント用に CPZ をアクセスポイントにする。ハブ (このユーザー) から sudo -n で呼べるように、
# root の持ち物として /usr/local/sbin に置く (ユーザーが書き換えられる場所のスクリプトを sudo 許可にしない)
sudo install -m 755 -o root -g root "$DIR/hexa-ap.sh" /usr/local/sbin/hexa-ap
sudo install -d -m 755 /etc/hexa-matrix
if ! sudo test -f /etc/hexa-matrix/ap.conf; then
  APP=$(tr -dc 'a-km-z2-9' </dev/urandom | head -c 10)
  printf 'AP_SSID=hexamatrix-ap\nAP_PASS=%s\nAP_IFACE=\n' "$APP" | sudo tee /etc/hexa-matrix/ap.conf >/dev/null
  sudo chmod 600 /etc/hexa-matrix/ap.conf
fi
echo "$U ALL=(root) NOPASSWD: /usr/local/sbin/hexa-ap" | sudo tee /etc/sudoers.d/hexa-matrix >/dev/null
sudo chmod 440 /etc/sudoers.d/hexa-matrix
sudo visudo -cf /etc/sudoers.d/hexa-matrix >/dev/null || { sudo rm -f /etc/sudoers.d/hexa-matrix; echo "sudoers の設定に失敗 (イベントAPは使えません)"; }
command -v nmcli >/dev/null 2>&1 || echo "※ nmcli (NetworkManager) が無いので、イベントAPは使えません"

echo "== service hexa-matrix (user: $U, port $PORT)"
sudo tee /etc/systemd/system/hexa-matrix.service >/dev/null <<UNIT
[Unit]
Description=HEXA MATRIX hub (CoreMatrix over USB + STUDIO server)
After=network-online.target
Wants=network-online.target

[Service]
User=$U
SupplementaryGroups=dialout input
Environment=HMATRIX_PORT=$PORT
ExecStart=/usr/bin/python3 $DIR/hmatrixd.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable hexa-matrix >/dev/null 2>&1
sudo systemctl restart hexa-matrix

if [ -d "$APPL/applications" ]; then
  echo "== launcher (APPLaunch)"
  REF="$APPL/share/images/camera1.png"
  [ -f "$REF" ] || REF=64
  python3 "$DIR/make_icon.py" /tmp/hexa-matrix.png "$REF"
  sudo install -m 644 /tmp/hexa-matrix.png "$APPL/share/images/hexa-matrix.png"
  sudo tee "$APPL/applications/hexa-matrix.desktop" >/dev/null <<DESK
[Desktop Entry]
Type=Application
Name=HEXA MATRIX
Comment=CoreMatrix controller
Exec=/usr/local/bin/hmatrix-app
Icon=share/images/hexa-matrix.png
Terminal=false
Categories=Utility;
StartupNotify=false
DESK
  NEED_REBOOT=1
fi

sleep 1.5
echo "== done"
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "STUDIO: http://${IP:-<CPZのIP>}:$PORT/   (スマホ/PCのブラウザで)"
systemctl is-active --quiet hexa-matrix && echo "hub: 動いています" || echo "hub: 止まっています → journalctl -u hexa-matrix -n 30"
if [ "$NEED_REBOOT" = 1 ]; then
  echo ""
  echo "*** ホーム画面へのアイコン追加と権限の反映のため、再起動してください: sudo reboot"
fi
