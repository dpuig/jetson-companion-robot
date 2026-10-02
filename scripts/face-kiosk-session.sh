#!/usr/bin/env bash
# The X client for the robot-mode kiosk: the face viewer with its own D-Bus session (WebKitGTK wants
# one; there is no desktop session). Started by xinit from companion-face.service:
#   xinit scripts/face-kiosk-session.sh [URL] -- /usr/bin/Xorg :0 vt1 ...
# It's a script because xinit splits its arguments on "--", which dbus-run-session also uses.
exec /usr/bin/dbus-run-session -- /usr/bin/python3 "$(dirname "$0")/face-viewer.py" "${1:-http://127.0.0.1:8080/face}"
