#!/usr/bin/env bash
# Robot mode (runs ON the Jetson, needs sudo): boot straight into the companion, no desktop.
#
#   companion.service       (user unit)   the ROS 2 stack: ros2 launch companion companion.launch.py
#   companion-face.service  (system unit) kiosk: a bare Xorg (NVIDIA driver, no desktop, no window
#                                         manager) running scripts/face-viewer.py fullscreen on
#                                         http://localhost:8080/face, on tty1
#   (Not cage/cog: Wayland compositors need DRM/KMS, which Jetson's display driver doesn't expose.
#    cage fails with "Found 0 GPUs, cannot create backend". Xorg with the nvidia driver works.)
#   default target → multi-user (GNOME off: frees ~1.3-2.8 GB for the model)
#
# From the Mac:  scripts/jetson.sh robot-mode          enable
#                scripts/jetson.sh robot-mode --undo   back to the Ubuntu desktop
set -euo pipefail

USER_NAME="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
REPO="$USER_HOME/dev/robotics"
UNIT_DIR="$USER_HOME/.config/systemd/user"
as_user() { sudo -u "$USER_NAME" XDG_RUNTIME_DIR="/run/user/$(id -u "$USER_NAME")" "$@"; }

if [[ "${1:-}" == "--undo" ]]; then
  sudo systemctl disable --now companion-face.service || true
  as_user systemctl --user disable --now companion.service || true
  sudo systemctl set-default graphical.target
  echo ">> desktop restored; reboot to get GNOME back"
  exit 0
fi

echo ">> kiosk: bare Xorg needs xinit (normally present on JetPack)"
command -v xinit >/dev/null || sudo apt-get install -y xinit

echo ">> companion.service (user unit; control it without sudo: systemctl --user stop companion)"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/companion.service" <<EOF
[Unit]
Description=Companion robot: ROS 2 stack (brain, senses, voice, web gateway)
After=default.target

[Service]
WorkingDirectory=$REPO
Environment=PATH=/usr/local/cuda/bin:$USER_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=LD_LIBRARY_PATH=/usr/local/cuda/lib64
ExecStart=/bin/bash -c 'source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && exec ros2 launch companion companion.launch.py'
Restart=on-failure
RestartSec=5
# ros2 launch forwards SIGINT to every node; a plain SIGTERM can leave llama-server running.
KillSignal=SIGINT
TimeoutStopSec=20

[Install]
WantedBy=default.target
EOF
chown -R "$USER_NAME:" "$USER_HOME/.config/systemd"
sudo loginctl enable-linger "$USER_NAME"   # user units start at boot, without a login
as_user systemctl --user daemon-reload
as_user systemctl --user enable companion.service

echo ">> companion-face.service (kiosk on tty1)"
sudo tee /etc/systemd/system/companion-face.service >/dev/null <<EOF
[Unit]
Description=Companion robot face (bare Xorg + WebKit kiosk)
After=systemd-user-sessions.service plymouth-quit-wait.service
Conflicts=getty@tty1.service

[Service]
User=$USER_NAME
PAMName=login
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
StandardInput=tty-fail
UtmpIdentifier=tty1
UtmpMode=user
# The face page is served by the gateway node; wait for it rather than show a browser error page.
ExecStartPre=/bin/sh -c 'until curl -sf -o /dev/null http://127.0.0.1:8080/face; do sleep 1; done'
# -s 0 -dpms: never blank the screen. Xorg runs via Xorg.wrap (needs_root_rights=yes on JetPack).
ExecStart=/usr/bin/xinit $REPO/scripts/face-kiosk-session.sh http://127.0.0.1:8080/face -- /usr/bin/Xorg :0 vt1 -nolisten tcp -nocursor -s 0 -dpms
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable companion-face.service
pkill -f "[f]ace-kiosk-session" || true   # a hand-started test kiosk would hold the display
sudo systemctl restart companion-face.service

echo ">> boot to multi-user (no GNOME)"
sudo systemctl set-default multi-user.target

echo ">> done. Reboot to start in robot mode:  sudo reboot"
