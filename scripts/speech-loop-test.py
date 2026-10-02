#!/usr/bin/env python3
"""Speech round trip without a mic or speaker: Piper speaks a sentence, whisper-server transcribes it.

Runs ON the Jetson with whisper-server on :8082:  python3 scripts/speech-loop-test.py
Synthesis mirrors voice.py (Piper) and the request mirrors hearing.py (16 kHz mono WAV), so this
exercises the same code paths as the robot. Exits 1 if any transcript differs by more than 1 word.
"""
import io
import json
import os
import re
import sys
import time
import urllib.request
import wave

import numpy as np
from piper import PiperVoice

MODEL = os.path.expanduser("~/models/en_US-lessac-medium.onnx")
URL = "http://127.0.0.1:8082/inference"
SENTENCES = [
    "Hello, my name is Kusi, and I am your companion robot.",
    "That is amazing news, I am so happy for you!",
    "Would you like me to remind you to water the plants tomorrow?",
    "The camera shows two cats sleeping on a pink blanket.",
    "I did not catch that. Could you say it again?",
]


def synth(voice, text):  # same API handling as companion/voice.py
    if hasattr(voice, "synthesize_stream_raw"):
        raw = b"".join(voice.synthesize_stream_raw(text))
    else:
        raw = b"".join(c.audio_int16_bytes for c in voice.synthesize(text))
    return np.frombuffer(raw, dtype=np.int16)


def to_wav16k(audio, rate):  # same linear resample as companion/hearing.py
    n = round(len(audio) * 16000 / rate)
    pcm = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio.astype(np.float32)).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000), w.writeframes(pcm.tobytes())
    return buf.getvalue()


def transcribe(wav):
    boundary = "----companion"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"u.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + wav + (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson"
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\nen"
            f"\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.load(urllib.request.urlopen(req, timeout=60))["text"].strip()


def words(s):
    return re.findall(r"[a-z']+", s.lower())


def main():
    voice = PiperVoice.load(MODEL)
    rate = voice.config.sample_rate
    bad = 0
    for text in SENTENCES:
        t0 = time.time()
        audio = synth(voice, text)
        t1 = time.time()
        heard = transcribe(to_wav16k(audio, rate))
        t2 = time.time()
        a, b = words(text), words(heard)
        diff = sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))
        bad += diff > 1
        print(f"{'ok ' if diff <= 1 else 'BAD'} tts {t1 - t0:.2f}s for {len(audio) / rate:.1f}s audio | "
              f"stt {t2 - t1:.2f}s | {diff} word(s) off\n      said:  {text}\n      heard: {heard}")
    print(f"\n{len(SENTENCES) - bad}/{len(SENTENCES)} round trips matched")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
