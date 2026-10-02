#!/usr/bin/env bash
# Develop on the Mac, build and run on the Jetson.
#
#   scripts/jetson.sh sync                  rsync the repo to the Jetson
#   scripts/jetson.sh build  <py|cuda|ros|bot>  sync, then build on the Jetson (bot = companion robot)
#   scripts/jetson.sh run    <py|cuda|ros|bot>  sync, build, run (Ctrl-C stops it remotely)
#   scripts/jetson.sh debug  py             run Python under debugpy, waiting on :5678
#   scripts/jetson.sh fetch  <remote-path>  copy a file/dir back from the Jetson
#   scripts/jetson.sh shell                 interactive shell in the remote repo
#   scripts/jetson.sh doctor                report the Jetson's toolchain
#   scripts/jetson.sh setup                 one-time install of ROS 2, colcon, debugpy (sudo)
#   scripts/jetson.sh ai-setup              build llama.cpp/whisper.cpp, fetch models (no sudo)
#   scripts/jetson.sh robot-mode [--undo]   boot into the robot: stack + face kiosk, no desktop (sudo)
#   scripts/jetson.sh face-demo [stop|URL-query]  face showcase fullscreen on the Jetson's monitor
#
# Settings come from .jetson.env (overridable by environment variables).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.jetson.env" ]] && source "$ROOT/.jetson.env"
: "${JETSON_HOST:=jetson}"
: "${JETSON_DIR:=dev/robotics}"   # relative to the remote $HOME
: "${ROS_DISTRO:=humble}"
: "${BUILD_JOBS:=}"               # empty = nproc on the Jetson

# Non-interactive SSH shells skip ~/.bashrc, so put CUDA on PATH explicitly.
REMOTE_ENV="export PATH=/usr/local/cuda/bin:\$HOME/.local/bin:\$PATH LD_LIBRARY_PATH=/usr/local/cuda/lib64:\${LD_LIBRARY_PATH:-}; \
JOBS=\${BUILD_JOBS:-\$(nproc)}; cd ~/$JETSON_DIR"

remote() {  # remote <cmd>: run in the synced repo; -t so Ctrl-C reaches the process
  ssh $([[ -t 0 ]] && echo -t) "$JETSON_HOST" "BUILD_JOBS='$BUILD_JOBS'; $REMOTE_ENV; $1"
}

sync() {
  ssh "$JETSON_HOST" "mkdir -p ~/$JETSON_DIR"
  rsync -az --delete \
    --exclude-from="$ROOT/.rsyncignore" \
    "$ROOT/" "$JETSON_HOST:$JETSON_DIR/"
}

ros_env='source /opt/ros/$ROS_DISTRO/setup.bash'

build_cmd() {
  case "$1" in
    py)   echo "python3 -m compileall -q python" ;;
    cuda) echo "cmake -S cpp -B build/cpp -DCMAKE_BUILD_TYPE=RelWithDebInfo \
                && cmake --build build/cpp -j\$JOBS" ;;
    ros)  echo "ROS_DISTRO=$ROS_DISTRO; $ros_env && cd ros2_ws \
                && colcon build --symlink-install --parallel-workers \$JOBS \
                   --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo \
                && (source install/setup.bash && env) > ../.vscode/ros.env" ;;  # for launch.json
    bot)  build_cmd ros ;;
    *)    echo "unknown target '$1' (expected py|cuda|ros|bot)" >&2; exit 2 ;;
  esac
}

run_cmd() {
  case "$1" in
    py)   echo "python3 python/hello_py/main.py" ;;
    cuda) echo "./build/cpp/hello_cuda/hello_cuda" ;;
    ros)  echo "ROS_DISTRO=$ROS_DISTRO; $ros_env && source ros2_ws/install/setup.bash \
                && ros2 run hello_ros talker" ;;
    bot)  echo "systemctl --user stop companion 2>/dev/null; \
                ROS_DISTRO=$ROS_DISTRO; $ros_env && source ros2_ws/install/setup.bash \
                && ros2 launch companion companion.launch.py" ;;
  esac
}

cmd="${1:-}"; shift || true
case "$cmd" in
  sync)  sync ;;
  build) sync; remote "$(build_cmd "$1")" ;;
  run)   sync; remote "( $(build_cmd "$1") ) && $(run_cmd "$1") ${*:2}" ;;
  debug)
    [[ "${1:-}" == py ]] || { echo "debug over SSH supports 'py'; for C++/CUDA use the Remote-SSH window" >&2; exit 2; }
    sync
    echo ">> waiting for debugger on $JETSON_HOST:5678 (forwarded to localhost:5678)"
    ssh -t -L 5678:localhost:5678 "$JETSON_HOST" \
      "$REMOTE_ENV; python3 -m debugpy --listen localhost:5678 --wait-for-client python/hello_py/main.py ${*:2}" ;;
  fetch) rsync -az "$JETSON_HOST:$JETSON_DIR/$1" "$ROOT/${2:-.}" ;;
  shell) ssh -t "$JETSON_HOST" "cd ~/$JETSON_DIR 2>/dev/null; exec bash -l" ;;
  setup) sync; ssh -t "$JETSON_HOST" "ROS_DISTRO=$ROS_DISTRO bash ~/$JETSON_DIR/scripts/jetson-setup.sh" ;;
  robot-mode) sync; ssh -t "$JETSON_HOST" "bash ~/$JETSON_DIR/scripts/jetson-robot-mode.sh ${1:-}" ;;
  face-demo)
    # Serves web/ on :8000 and opens a fullscreen WebKit window on the desktop session (DISPLAY=:0).
    # Default query cycles every expression; pass e.g. "demo" for keyboard control, or "stop".
    # "[f]ace": the pattern must not match this ssh shell's own command line
    ssh "$JETSON_HOST" "pkill -f '[f]ace-viewer.py'; pkill -f '[h]ttp.server 8000'" || true
    [[ "${1:-}" == stop ]] && exit 0
    sync
    ssh "$JETSON_HOST" "cd ~/$JETSON_DIR; \
      setsid nohup python3 -m http.server 8000 -d ros2_ws/src/companion/web >/tmp/face-http.log 2>&1 </dev/null & \
      sleep 1; DISPLAY=:0 XAUTHORITY=/run/user/\$(id -u)/gdm/Xauthority \
      DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/\$(id -u)/bus \
      setsid nohup python3 scripts/face-viewer.py 'http://127.0.0.1:8000/face.html?${1:-demo&cycle=3&fps}' \
      >/tmp/face-viewer.log 2>&1 </dev/null &"
    echo ">> face on the Jetson's monitor (Esc closes it). Also: http://dpuig-desktop.local:8000/face.html?demo"
    echo ">> stop: scripts/jetson.sh face-demo stop" ;;
  ai-setup) sync; ssh "$JETSON_HOST" "bash ~/$JETSON_DIR/scripts/jetson-ai-setup.sh" ;;
  doctor)
    ssh "$JETSON_HOST" "$REMOTE_ENV 2>/dev/null; set +e
      echo \"host:    \$(hostname)  \$(uname -m)\"
      echo \"l4t:     \$(head -1 /etc/nv_tegra_release 2>/dev/null)\"
      echo \"os:      \$(. /etc/os-release; echo \$PRETTY_NAME)\"
      echo \"cpu/mem: \$(nproc) cores, \$(free -h | awk '/Mem/{print \$2}') RAM, \$(free -h | awk '/Swap/{print \$2}') swap\"
      echo \"disk:    \$(df -h ~ | awk 'NR==2{print \$4\" free\"}')\"
      for t in nvcc cmake gcc python3 gdb cuda-gdb rsync colcon docker; do
        printf '%-8s %s\n' \"\$t:\" \"\$(command -v \$t || echo MISSING)\"; done
      python3 -c 'import debugpy' 2>/dev/null && echo 'debugpy: ok' || echo 'debugpy: MISSING'
      ls -d /opt/ros/*/ 2>/dev/null || echo 'ros:     MISSING'" ;;
  *) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
