# companion

The Jetson as the brain of a companion robot. Qwen3-VL-4B-Instruct (4-bit) is the model: it reads
text and camera images natively. Input arrives as video, speech, typed text and files. Output is
speech and text.

```
 USB webcam ─▶ camera ──/camera/image/compressed──┐
                                                  ▼
 mic ─▶ hearing ─(whisper-server)─/speech/text─▶ brain ─(llama-server: Qwen3-VL-4B)
                                                  │  ├─/robot/say───▶ voice (Piper) ─▶ speaker
 browser ─▶ gateway ──/user/text, /user/file────▶─┘  └─/robot/reply─▶ gateway ─▶ browser
                ◀────────────── /robot/speaking (mutes the mic while talking) ──── voice
```

| node | does | key params (`config/companion.yaml`) |
|---|---|---|
| `camera` | newest V4L2 frame → 512 px JPEG, 2 Hz. A video-file `source` loops for testing | `source`, `fps`, `width` |
| `hearing` | mic → webrtcvad → whisper-server → text. Muted while the robot speaks | `device`, `language`, `silence_ms` |
| `brain` | one conversation: queues inputs, attaches the live frame to each turn, streams the reply sentence by sentence | `robot_name`, `see_on_every_turn`, `history_turns` |
| `voice` | Piper TTS → speaker, in order. `save_dir` keeps WAVs when there's no speaker | `model`, `device`, `save_dir` |
| `gateway` | web UI at `http://dpuig-desktop.local:8080`: chat, file upload, camera preview. Serves the face at `/face` and owns `/robot/state` | `port`, `upload_dir` |

Topic names and message formats are in `companion/topics.py`. That's the contract to follow when
adding nodes such as motors, a face display or a wake word.

## Run

```sh
scripts/jetson.sh setup      # once, needs sudo: ROS 2, audio libs, pip, then builds + models
scripts/jetson.sh run bot    # sync → colcon build → launch servers + all nodes
```

Then open `http://dpuig-desktop.local:8080`. The launch file starts `llama-server` (port 8081) and
`whisper-server` (port 8082) as well. Loading the model takes about 10 s, and anything sent
before then gets an error reply.

To test without hardware:
```sh
ros2 launch companion companion.launch.py hearing:=false camera:=false   # text + files only
ros2 param set /camera source /path/to/clip.mp4                          # (or set it in the yaml)
ros2 topic pub --once /user/text std_msgs/String "{data: 'What do you see?'}"
ros2 topic echo /robot/reply
```

## Face

`web/face.html` is the robot's face: small white glyphs on a navy screen (flat, no glow), drawn
fullscreen on the robot's display by the kiosk (bare Xorg + `scripts/face-viewer.py`, WebKitGTK).

**How it's built:** every eye and mouth is a *glyph*, a short SVG path in `GLYPHS`. On load, each
glyph is resampled to 64 points (leftmost point first, clockwise), so any glyph can morph into any
other by moving the points. A blink is "morph to a line and back". Lip sync blends the expression's
mouth toward its `talk` glyph by the speech loudness. Line-like glyphs (`‿ > × ∩`) are paths that go
out and come back; they have no area, so only the stroke shows. (This morphing idea comes from
[Procedural-Expression-Library](https://github.com/ggldnl/Procedural-Expression-Library), which is
GPL-3.0. This is a separate implementation, and no code was copied.)

| emotion | eyes | mouth |
|---|---|---|
| neutral | pills | `‿` |
| happy | half-moons | `D` |
| excited | `>` `<` (bouncing) | `D` |
| curious | pill + short pill, head tilted | `o` |
| surprised | round dots | small `▲` |
| sad | pills, lower and closer | `∩` |
| confused | pill + short pill, tilted | wavy |
| love | hearts | `‿` |

| state | from | the face does |
|---|---|---|
| idle | (nothing happening) | blinks every 2–6 s, glances around, bobs gently |
| listening | `hearing`: speech detected | eyes grow 10%, gaze settles on you |
| thinking | `brain`: waiting on the model | glances up-right, flat mouth, `(•••)` bubble with bouncing dots |
| speaking | `voice`: audio playing | mouth opens toward the `talk` glyph with the speech envelope (`/robot/mouth`) |
| offline | gateway unreachable | sleeping `◡ ◡` eyes, slow breathing |

The emotion goes back to neutral 6 s after the robot falls idle.
**Adding an expression:** draw glyphs in `GLYPHS` if needed, add an entry to `EMOTIONS` in
`face.html`, and add the same name to `EMOTIONS` in `companion/topics.py` (the model is told the list).

**Design on the Mac, with no robot:** `python3 -m http.server -d ros2_ws/src/companion/web`, then
open `localhost:8000/face.html?demo`. Keys 1–8 switch emotions, `i l t s o` switch states, and
space fakes speech. Against the live robot, open `http://dpuig-desktop.local:8080/face`.

**On the Jetson's monitor, without ROS or sudo:** `scripts/jetson.sh face-demo` serves `web/` on
port 8000 and opens a fullscreen WebKit window (`scripts/face-viewer.py`, the same engine as the
kiosk) on the desktop session. It cycles every expression and state with labels and an fps counter.
`scripts/jetson.sh face-demo demo` gives keyboard control instead (use the Jetson's keyboard; Esc
closes it), and `scripts/jetson.sh face-demo stop` stops it. Measured: 62 fps at 1920×1080 with the
model *not* running.

## Robot mode (boot into the robot)

```sh
scripts/jetson.sh robot-mode          # sudo; then: ssh -t jetson sudo reboot
scripts/jetson.sh robot-mode --undo   # back to the Ubuntu desktop
```

This boots to `multi-user.target` with no GNOME. It starts the stack as the user service
`companion` and the face kiosk as `companion-face` (bare Xorg + the WebKit face viewer; cage/cog cannot drive the Jetson display) on the HDMI/DP display. The kiosk waits
until the gateway serves `/face`, so the screen is black while the model loads (~40 s).
`scripts/jetson.sh run bot` stops the `companion` service first, and the kiosk then shows the face from
your development run. `systemctl --user start companion` puts the service back (no sudo needed).
Logs: `journalctl --user -u companion -f`, `journalctl -u companion-face -f`.

## File inputs

| type | becomes |
|---|---|
| `.jpg .png .webp …` | an image in the next turn (next to the live frame) |
| `.pdf` | extracted text (pypdf), truncated to `file_max_chars` |
| `.wav` | a transcript via whisper-server (16 kHz WAV; other formats need `--convert` + ffmpeg) |
| anything else | read as text |

A file sent with text in the box is answered using that text as the prompt. Without text, the robot
says what the file is. The file's contents apply to one turn, and only the conversation text is kept
in history.

## Measured on this Jetson (Orin Nano 8GB, JetPack 6.2, 2026-09-30)

`python3 scripts/llm-smoke.py` with llama-server running (flags as in the launch file):

| turn | total | prompt processing | generation |
|---|---|---|---|
| 640×480 image + question (353 prompt tokens) | 5.0 s | 175 tok/s | 15.7 tok/s |
| text only | 2.4 s | 188 tok/s | 16.7 tok/s |

Memory: with the model loaded, the **system as a whole** used 5.8 GB, leaving 1.4 GB available with
the Ubuntu desktop running. whisper + Piper + the nodes need ~1 GB of that, which is too close to
the limit. **Run headless** (`sudo systemctl set-default multi-user.target`, which frees ~1.3 GB). Or
lower the context to `-c 4096` in the launch file, which saves 300 MB of KV cache.

**Jetson gotcha:** `cudaMalloc failed: out of memory` while `free` shows GBs available. CPU and GPU
share RAM, and the GPU allocator (NvMap) doesn't reclaim page cache. The launch file evicts the
model files from cache before starting the servers. If it still happens, run
`sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'` and relaunch.

### 2026-10-01: model, mood tags and speech (desktop session, no ROS)

- **Loading:** fails with `cudaMalloc ... out of memory` unless the page cache is evicted first.
  2.3 GB of cuDNN/TensorRT libraries were sitting in it. The launch file now does that and loads
  with `--load-mode dio`, which brought the model up in 46 s.
- **Mood tags:** `scripts/llm-emotion-test.py` gets 8/8 valid tags with the brain's real prompt
  (excited at good news, sad at a sick dog, confused at gibberish, love at affection), 1–2.3 s per reply.
- **Speech loop:** `scripts/speech-loop-test.py` has Piper speak and whisper transcribe. It got
  5/5 sentences right ("Kusi" → "QC", as expected for a made-up name). Piper: 0.5–0.8 s per sentence
  of ~3 s. **whisper on the CPU: ~14 s per sentence, unusable**, so whisper must use the GPU.
- **With GNOME + the face viewer + the model loaded, whisper can't start on the GPU.** Its own CUDA
  context doesn't fit, even with 700 MB free. **The full stack needs robot mode (no desktop).**

## Latency (what to expect)

From when you stop talking to when the robot starts speaking: end-of-speech detection (0.7 s) +
whisper (~0.5 s) + prompt with the camera frame (~1.5–2 s at 512 px) + first sentence (~0.5 s) +
Piper (~0.2 s) ≈ **3–4 s**. To go faster, lower `silence_ms`, set `see_on_every_turn: false`
(text-only turns start in well under a second), or use a smaller camera `width`.

## Hardware still needed

- **USB webcam.** One with a built-in mic covers `hearing` too.
- **Speaker:** a USB speaker or USB sound card. The dev kit's only audio output is HDMI.
- For a microphone that works across a room, a USB mic array (e.g. ReSpeaker) with echo cancellation.
