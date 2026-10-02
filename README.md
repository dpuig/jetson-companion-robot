# robotics

A companion robot whose brain is a Jetson Orin Nano. It sees through a camera, hears through a
microphone, takes typed text and files, thinks with **Qwen3-VL-4B**, speaks with Piper, and shows
its mood on an animated face on the HDMI screen. Everything is developed on the Mac and built and
run **natively on the Jetson**: no cross-compiling.

- **Using the robot:** this file.
- **How the robot works inside** (nodes, topics, face design, measurements):
  [`ros2_ws/src/companion/README.md`](ros2_ws/src/companion/README.md).

| path | what |
|---|---|
| `ros2_ws/src/companion/` | the robot: ROS 2 nodes, launch file, config, web UI and face |
| `scripts/jetson.sh` | the one command for everything on the Jetson (run it with no arguments for help) |
| `scripts/jetson-*.sh` | setup scripts that run on the Jetson (called by `jetson.sh`) |
| `scripts/*-test.py`, `llm-smoke.py` | checks for the model, mood tags and speech |
| `scripts/face-viewer.py` | fullscreen face window (the kiosk, and the desktop demo) |
| `python/`, `cpp/`, `ros2_ws/src/hello_ros/` | Python, CUDA and ROS 2 samples that prove the toolchain |
| `.jetson.env` | target host, remote dir, ROS distro, build parallelism |

Target: Orin Nano 8GB, JetPack 6.2 (L4T R36.4.7, Ubuntu 22.04, CUDA 12.6), SSH alias `jetson` →
`dpuig-desktop.local`. All commands below run **on the Mac, from this folder**.

---

## Quick start (new Jetson, or after reflashing)

Commands marked 🔑 ask for the Jetson's sudo password. Run those in Terminal.app or the VS Code
terminal, not through Claude Code's `!` prompt, which can't take passwords.

```sh
ssh-copy-id -i ~/.ssh/id_ed25519.pub jetson   # 🔑 once: passwordless SSH (alias is in ~/.ssh/config)
scripts/jetson.sh setup                       # 🔑 ROS 2, audio libs, pip, then builds + model downloads (~45 min)
scripts/jetson.sh build bot                   # compile the robot's ROS workspace
scripts/jetson.sh robot-mode                  # 🔑 boot straight into the robot (no desktop)
ssh -t jetson sudo reboot                     # 🔑
```

About a minute after boot (the model takes ~45 s to load) the face appears on the screen.
`scripts/jetson.sh doctor` shows what's installed if something seems missing.

## Using the robot

| to… | do |
|---|---|
| **talk to it by typing, send files** | open **http://dpuig-desktop.local:8080** (chat, 📎 for PDF/text/image/WAV, live camera view) |
| **see its face from the Mac** | http://dpuig-desktop.local:8080/face |
| **talk to it by voice** | plug in a USB mic and speaker (not connected yet; see the companion README's "Hardware still needed") |
| **change its name / personality / camera / language** | edit `ros2_ws/src/companion/config/companion.yaml`, then `scripts/jetson.sh run bot` |

The face reacts by itself. It **listens** (eyes widen) when you speak, shows a **(•••)** bubble while
thinking, moves its mouth while speaking, and shows the model's mood for each reply (happy, sad,
excited, curious, surprised, confused, love). Sleeping eyes `◡ ◡` mean the robot software isn't
running.

### Robot mode (how the Jetson boots)

With robot mode on, the Jetson has no desktop. At boot it starts two services:

| service | what | control (no sudo for `companion`) |
|---|---|---|
| `companion` | the ROS 2 stack: model, whisper, all nodes, web UI | `ssh jetson systemctl --user {status,restart,stop,start} companion` |
| `companion-face` | the kiosk: bare Xorg + the face viewer on the HDMI screen | `ssh -t jetson sudo systemctl restart companion-face` 🔑 |

```sh
scripts/jetson.sh robot-mode --undo && ssh -t jetson sudo reboot   # 🔑 back to the Ubuntu desktop
scripts/jetson.sh robot-mode        && ssh -t jetson sudo reboot   # 🔑 and back to robot mode
```

### Changing the code (everyday loop)

Edit on the Mac, then:

```sh
scripts/jetson.sh run bot      # sync → build → stop the boot service → launch in this terminal (Ctrl-C stops it)
```

The screen keeps showing the face, now driven by your terminal run, and its logs print right there.
When you're done, put the boot service back: `ssh jetson systemctl --user start companion`.

Just the face (`web/face.html`) needs no ROS at all. Iterate on it on the Mac with
`python3 -m http.server -d ros2_ws/src/companion/web 8000` → `localhost:8000/face.html?demo`
(keys 1–8 emotions, `i l t s o` states, space = talk).

### Checks

Run these on the Jetson (`scripts/jetson.sh shell`) while the stack is up:

```sh
python3 scripts/llm-smoke.py            # image + text turn, with speed figures
python3 scripts/llm-emotion-test.py     # 8 prompts; every reply must carry a valid [mood] tag
python3 scripts/speech-loop-test.py     # Piper speaks → whisper transcribes, 5 sentences
```

### Face demo on the desktop (robot mode off)

```sh
scripts/jetson.sh face-demo           # fullscreen showcase cycling every expression, with fps
scripts/jetson.sh face-demo demo      # keyboard control on the Jetson (Esc closes)
scripts/jetson.sh face-demo stop
```

## Troubleshooting

| symptom | cause → fix |
|---|---|
| **Black screen, blinking cursor** (robot mode) | The kiosk waits until the web UI is up, so the stack hasn't started. Usually the ROS workspace isn't built: `scripts/jetson.sh build bot`. Otherwise see the logs below |
| **Red "Found 0 GPUs… wlroots backend"** | An old `cage` kiosk. Re-run `scripts/jetson.sh robot-mode` 🔑 (it now uses bare Xorg; Jetson's display driver can't run Wayland compositors) |
| **Face shows sleeping eyes** | The web UI isn't reachable: `ssh jetson systemctl --user restart companion` |
| **`cudaMalloc failed: out of memory`** while `free` shows GBs available | The GPU can't use RAM that's holding cached files. The launch file evicts the cache and loads with `--load-mode dio`. If it still fails: `ssh -t jetson "sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'"` 🔑, then restart `companion` |
| **whisper won't start / everything OOMs with the desktop on** | The model + whisper + GNOME don't fit in 8 GB. Use robot mode |
| **`import cv2` fails: numpy.core.multiarray** | Something upgraded numpy to 2.x: `ssh jetson 'python3 -m pip install --user "numpy<2"'` |
| **Face demo on the desktop shows nothing** | GNOME blanked and locked the screen. Unlock it with the Jetson's keyboard |
| **`ssh jetson` can't connect** | Wi-Fi IP changed and mDNS is slow; retry, or find the IP with `arp -a \| grep 9c:c7:d3:89:cd:a7` |

**Logs.** The user journal isn't kept on this Jetson, so:

```sh
ssh jetson 'tail -50 $(ls -td ~/.ros/log/*/ | head -1)launch.log'   # which node started / died
ssh jetson 'ls -t ~/.ros/log/*.log | head'                       # per-node logs (brain replies, errors)
ssh jetson 'journalctl -u companion-face -n 30 --no-pager'       # kiosk
# A node that dies at startup prints its error only to the console. Run it by hand:
ssh jetson 'cd ~/dev/robotics && source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash &&
  ros2 run companion gateway --ros-args --params-file ros2_ws/install/companion/share/companion/config/companion.yaml'
```

---

## Development workflow (any code, not just the robot)

**1. Edit on the Mac, run on the Jetson** (source of truth stays on the Mac)

```sh
scripts/jetson.sh run py      # rsync → python3 on the Jetson
scripts/jetson.sh run cuda    # rsync → cmake build → run
scripts/jetson.sh run ros     # rsync → colcon build → ros2 run hello_ros talker
scripts/jetson.sh shell       # shell in ~/dev/robotics on the Jetson
```

In VS Code: **⌘⇧B** = build on the Jetson (compiler errors link to the local files). Use
*Run Task → jetson: run* to run it. To debug Python, pick **Jetson: debug Python (from Mac)**
in the Run panel: it syncs, starts debugpy on the Jetson, tunnels port 5678, and attaches.

`rsync --delete` mirrors the Mac onto `~/dev/robotics`, so **don't edit files on the Jetson
in this mode**, because the next sync overwrites them. Build outputs (`build/`, `ros2_ws/install/`)
are excluded and stay on the Jetson. Use `scripts/jetson.sh fetch <path>` to pull results back.

**2. Remote-SSH window** (needed for C++/CUDA debugging)

F1 → *Remote-SSH: Connect to Host* → `jetson` → open `~/dev/robotics`. The editor UI stays on
the Mac, while extensions, the terminal, gdb/cuda-gdb and IntelliSense run on the Jetson against
its real headers. The `Remote-SSH: …` launch configs debug the CUDA binary and the ROS node there.
Install the recommended extensions *in the remote* when prompted. When you're done, sync from the
Mac again (mode 1), or commit and push from the remote first so the Mac doesn't overwrite those edits.

### Adding code

- **Robot features:** a new ROS node in `ros2_ws/src/companion/companion/`, registered in `setup.py`
  and the launch file. Talk to the rest of the robot only through the topics in `companion/topics.py`.
- **C++/CUDA:** add `cpp/<name>/CMakeLists.txt` and `add_subdirectory(<name>)` in `cpp/CMakeLists.txt`.
- **Other ROS 2 packages:** `ros2 pkg create` inside `ros2_ws/src/`, then `scripts/jetson.sh build ros`.
- **Python:** the `py` target runs `python/hello_py/main.py`; edit `run_cmd` in `scripts/jetson.sh` to change it.

## Jetson notes

- **Memory:** the CPU and GPU share 8 GB. The robot needs ~6 GB with the desktop off. If a build
  gets killed (OOM), set `BUILD_JOBS=2` in `.jetson.env`.
- **Storage:** the system runs from a 128 GB microSD (~87 MB/s, so the model takes ~45 s to load).
  An M.2 2280 NVMe SSD (no heatsink) would cut that to a few seconds. It's optional.
- **Addressing:** the Wi-Fi IP changes, so the SSH alias uses mDNS (`dpuig-desktop.local`). A DHCP
  reservation for MAC `9c:c7:d3:89:cd:a7` on the router also works.
- **Performance:** power modes are 0 = 15 W, 1 = 25 W, **2 = MAXN_SUPER** (fastest), 3 = 7 W.
  `sudo nvpmodel -m 2 && sudo jetson_clocks` before benchmarking; `sudo nvpmodel -q` shows the current one.
