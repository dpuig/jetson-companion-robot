"""Voice: speaks each sentence from /robot/say with Piper TTS, in order.

Publishes /robot/speaking while audio plays so hearing can mute the mic, and, just before each
sentence, its loudness envelope on /robot/mouth so the face can move its mouth in sync.
With no speaker attached, playback errors are logged and the node waits out the audio's duration
anyway, so the face still "talks". Set `save_dir` to keep each utterance as a WAV.
"""
import json
import os
import queue
import threading
import time
import wave

import numpy as np
import rclpy
import sounddevice as sd
from piper import PiperVoice
from rclpy.node import Node
from std_msgs.msg import Bool, String

from companion import topics


class Voice(Node):
    def __init__(self):
        super().__init__("voice")
        p = self.declare_parameters("", [
            ("model", "~/models/en_US-lessac-medium.onnx"),
            ("device", ""),
            ("save_dir", ""),
            ("enabled", True),
        ])
        self.cfg = {x.name: x.value for x in p}
        self.voice = PiperVoice.load(os.path.expanduser(self.cfg["model"]))
        self.rate = self.voice.config.sample_rate
        self.save_dir = os.path.expanduser(self.cfg["save_dir"]) if self.cfg["save_dir"] else ""
        if self.save_dir:
            os.makedirs(self.save_dir, exist_ok=True)
        self.lines: queue.Queue = queue.Queue()
        self.speaking = self.create_publisher(Bool, topics.SPEAKING, 10)
        self.mouth = self.create_publisher(String, topics.MOUTH, 10)
        self.create_subscription(String, topics.SAY, lambda m: self.lines.put(m.data), 10)
        threading.Thread(target=self.worker, daemon=True).start()
        self.get_logger().info(f"voice ready ({self.rate} Hz)")

    def synth(self, text: str) -> np.ndarray:
        # piper-tts >= 1.3 yields AudioChunks; older versions stream raw int16 bytes.
        if hasattr(self.voice, "synthesize_stream_raw"):
            raw = b"".join(self.voice.synthesize_stream_raw(text))
        else:
            raw = b"".join(c.audio_int16_bytes for c in self.voice.synthesize(text))
        return np.frombuffer(raw, dtype=np.int16)

    def worker(self):
        while rclpy.ok():
            text = self.lines.get()
            if not self.cfg["enabled"]:
                continue
            audio = self.synth(text)
            if self.save_dir:
                self.save(audio)
            self.speaking.publish(Bool(data=True))
            self.mouth.publish(String(data=json.dumps({"env": envelope(audio, self.rate), "dt": ENV_DT})))
            t0 = time.monotonic()
            try:
                sd.play(audio, self.rate, device=self.cfg["device"] or None, blocking=True)
            except Exception as e:
                self.get_logger().warn(f"no audio output ({e})", throttle_duration_sec=30)
                time.sleep(max(0.0, len(audio) / self.rate - (time.monotonic() - t0)))
            finally:
                if self.lines.empty():  # stay "speaking" between sentences of one reply
                    time.sleep(0.2)     # let the room echo die down before the mic reopens
                    self.speaking.publish(Bool(data=False))

    def save(self, audio: np.ndarray):
        path = os.path.join(self.save_dir, time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1000:03d}.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(audio.tobytes())


ENV_DT = 1 / 30  # mouth envelope resolution: one value per display-ish frame


def envelope(audio: np.ndarray, rate: int) -> list[float]:
    """Loudness per ENV_DT window, 0..1, for lip sync. Normalised to the sentence's own peak so
    quiet and loud voices both open the mouth fully; a square root makes small sounds visible."""
    win = max(1, int(rate * ENV_DT))
    n = len(audio) // win
    if n == 0:
        return []
    frames = audio[: n * win].astype(np.float32).reshape(n, win)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    rms /= max(float(rms.max()), 1.0)
    return [round(float(v), 2) for v in np.sqrt(rms)]


def main():
    rclpy.init()
    try:
        rclpy.spin(Voice())
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.try_shutdown()
