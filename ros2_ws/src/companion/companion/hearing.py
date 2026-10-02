"""Hearing: microphone → voice-activity detection → whisper-server → /speech/text.

Audio is captured at 16 kHz mono (resampled from the device's native rate if it can't do 16 kHz). webrtcvad marks
30 ms frames as speech; an utterance ends after `silence_ms` of silence and is transcribed.
The mic is ignored while /robot/speaking is true, so the robot doesn't transcribe itself.
"""
import io
import queue
import threading
import wave

import numpy as np
import rclpy
import requests
import sounddevice as sd
import webrtcvad
from rclpy.node import Node
from std_msgs.msg import Bool, String

from companion import topics

RATE = 16000
FRAME_MS = 30
FRAME = RATE * FRAME_MS // 1000   # samples per VAD frame
# Whisper hallucinates these on noise or silence; drop them.
HALLUCINATIONS = {"", "you", "thank you.", "thanks for watching!", "[blank_audio]", "(silence)"}


class Hearing(Node):
    def __init__(self):
        super().__init__("hearing")
        p = self.declare_parameters("", [
            ("device", ""),
            ("whisper_url", "http://127.0.0.1:8082/inference"),
            ("language", "auto"),
            ("vad_aggressiveness", 2),
            ("silence_ms", 700),
            ("min_speech_ms", 300),
        ])
        self.cfg = {x.name: x.value for x in p}
        self.vad = webrtcvad.Vad(self.cfg["vad_aggressiveness"])
        self.muted = False
        self.pub = self.create_publisher(String, topics.SPEECH_TEXT, 10)
        self.listening = self.create_publisher(Bool, topics.LISTENING, 10)  # drives the face
        self.create_subscription(Bool, topics.SPEAKING, self.on_speaking, 10)
        self.frames: queue.Queue = queue.Queue(maxsize=200)
        threading.Thread(target=self.listen, daemon=True).start()

    def on_speaking(self, msg: Bool):
        self.muted = msg.data
        if msg.data:  # drop anything queued while we were about to talk
            with self.frames.mutex:
                self.frames.queue.clear()

    def listen(self):
        device = self.cfg["device"] or None
        try:
            native = int(sd.query_devices(device, "input")["default_samplerate"])
        except Exception as e:
            self.get_logger().error(f"no microphone ({e}); hearing disabled")
            return
        try:  # most USB mics (and PulseAudio/PipeWire) can capture at 16 kHz directly
            sd.check_input_settings(device=device, channels=1, samplerate=RATE, dtype="int16")
            native = RATE
        except Exception:
            pass
        self.get_logger().info(f"listening on {device or 'default'} at {native} Hz")

        pending = np.zeros(0, dtype=np.int16)

        def callback(indata, _frames, _time, status):
            nonlocal pending
            if status:
                self.get_logger().warn(str(status), throttle_duration_sec=5)
            if self.muted:
                return
            mono = indata[:, 0]
            if native != RATE:  # linear resample; plenty for speech recognition
                n_out = round(len(mono) * RATE / native)
                mono = np.interp(np.linspace(0, len(mono) - 1, n_out), np.arange(len(mono)),
                                 mono.astype(np.float32)).astype(np.int16)
            pending = np.concatenate([pending, mono])
            while len(pending) >= FRAME:
                try:
                    self.frames.put_nowait(pending[:FRAME].tobytes())
                except queue.Full:
                    pass
                pending = pending[FRAME:]

        with sd.InputStream(device=device, channels=1, samplerate=native, dtype="int16",
                            blocksize=native * FRAME_MS // 1000, callback=callback):
            self.segment()

    def segment(self):
        speech, silent, voiced = [], 0, 0
        max_silent = self.cfg["silence_ms"] // FRAME_MS
        min_voiced = self.cfg["min_speech_ms"] // FRAME_MS
        preroll: list[bytes] = []  # keep a little audio from before speech starts
        while rclpy.ok():
            frame = self.frames.get()
            is_speech = self.vad.is_speech(frame, RATE)
            if not speech:
                preroll = (preroll + [frame])[-10:]
                if is_speech:
                    speech, silent, voiced = list(preroll), 0, 1
                    self.listening.publish(Bool(data=True))
                continue
            speech.append(frame)
            voiced += is_speech
            silent = 0 if is_speech else silent + 1
            if silent >= max_silent:
                if voiced >= min_voiced:
                    threading.Thread(target=self.transcribe, args=(b"".join(speech),), daemon=True).start()
                speech = []
                self.listening.publish(Bool(data=False))

    def transcribe(self, pcm: bytes):
        wav = io.BytesIO()
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm)
        try:
            r = requests.post(self.cfg["whisper_url"], files={"file": ("u.wav", wav.getvalue())},
                              data={"response_format": "json", "language": self.cfg["language"]},
                              timeout=30)
            r.raise_for_status()
            text = r.json().get("text", "").strip()
        except Exception as e:
            self.get_logger().error(f"whisper failed: {e}")
            return
        if text.lower() in HALLUCINATIONS:
            return
        self.get_logger().info(f"heard: {text!r}")
        self.pub.publish(String(data=text))


def main():
    rclpy.init()
    try:
        rclpy.spin(Hearing())
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.try_shutdown()
