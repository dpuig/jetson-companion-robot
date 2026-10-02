"""The brain: merges speech, text, files and the camera into one conversation with Qwen3-VL.

Inputs are queued and handled one at a time. Each user turn carries the newest camera frame,
so the model can answer "what am I holding?". Replies stream from llama-server and are
published sentence by sentence on /robot/say, so the voice starts before generation ends.

For the face: /robot/thinking is true while a turn is being processed, and the model opens each
reply with a mood tag ("[happy] ...") that is stripped from the text and published on /robot/emotion.
"""
import base64
import json
import queue
import re
import threading
import time

import rclpy
import requests
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool, String

from companion import files, topics

SYSTEM_PROMPT = """You are {name}, a friendly companion robot. You can see through a camera and \
hear through a microphone. Your replies are spoken aloud, so keep them short and conversational: \
one to three sentences, no lists, no markdown, no emoji. When an image is attached, it is what \
your camera sees right now; mention it only when it is relevant. If you are not sure what you \
see or heard, say so.

Begin every reply with exactly one mood tag that sets your facial expression, chosen from: \
{emotions}. The tag is not spoken. Example: [happy] Nice to see you again!"""

MOOD_TAG = re.compile(r"^\s*\[(\w+)\]\s*")
# Split after ., !, ? or newline once enough text has built up to be worth speaking.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


class Brain(Node):
    def __init__(self):
        super().__init__("brain")
        p = self.declare_parameters("", [
            ("llm_url", "http://127.0.0.1:8081/v1/chat/completions"),
            ("whisper_url", "http://127.0.0.1:8082/inference"),
            ("robot_name", "Kusi"),
            ("see_on_every_turn", True),
            ("frame_max_age_s", 3.0),
            ("history_turns", 8),
            ("max_tokens", 400),
            ("temperature", 0.7),
            ("file_max_chars", 12000),
        ])
        self.cfg = {x.name: x.value for x in p}

        self.frame: bytes | None = None
        self.frame_time = 0.0
        self.history: list[dict] = []   # text-only past turns; images are never kept
        self.pending: list[files.Extracted] = []   # files waiting for the next user turn
        self.inbox: queue.Queue = queue.Queue()

        self.say = self.create_publisher(String, topics.SAY, 10)
        self.reply = self.create_publisher(String, topics.REPLY, 10)
        self.thinking = self.create_publisher(Bool, topics.THINKING, 10)
        self.emotion = self.create_publisher(String, topics.EMOTION, 10)
        self.create_subscription(CompressedImage, topics.IMAGE, self.on_frame, 1)
        self.create_subscription(String, topics.SPEECH_TEXT, lambda m: self.inbox.put(("speech", m.data)), 10)
        self.create_subscription(String, topics.USER_TEXT, lambda m: self.inbox.put(("text", m.data)), 10)
        self.create_subscription(String, topics.USER_FILE, lambda m: self.inbox.put(("file", m.data)), 10)

        threading.Thread(target=self.worker, daemon=True).start()
        self.get_logger().info(f"ready; model at {self.cfg['llm_url']}")

    def on_frame(self, msg: CompressedImage):
        self.frame, self.frame_time = bytes(msg.data), time.monotonic()

    def worker(self):
        while rclpy.ok():
            source, data = self.inbox.get()
            self.thinking.publish(Bool(data=True))
            try:
                if source == "file":
                    self.handle_file(json.loads(data))
                elif data.strip():
                    self.turn(data.strip(), source)
            except Exception as e:  # keep the robot alive through a bad input
                self.get_logger().error(f"{source} input failed: {e}")
                self.set_emotion("confused")
                self.speak("Sorry, something went wrong on my side.", "error")
            finally:
                self.thinking.publish(Bool(data=False))

    def handle_file(self, req: dict):
        ex = files.extract(req["path"], self.cfg["file_max_chars"], self.cfg["whisper_url"])
        self.get_logger().info(f"file {ex.name}: {len(ex.text)} chars, image={bool(ex.image_b64)}")
        self.pending.append(ex)
        # With a prompt, answer now; without one, the file rides along with the next message.
        self.turn(req.get("prompt") or f"I just gave you the file {ex.name}. Briefly, what is it?", "file")

    def turn(self, text: str, source: str):
        self.publish_reply("user", text, source)
        parts: list[dict] = []
        notes: list[str] = []

        for ex in self.pending:
            if ex.image_b64:
                parts.append(image_part(ex.image_b64, ex.mime))
                notes.append(f"[attached image file: {ex.name}]")
            else:
                notes.append(f"[attached file: {ex.name}]\n{ex.text}")
        self.pending.clear()

        fresh = self.frame and time.monotonic() - self.frame_time < self.cfg["frame_max_age_s"]
        if self.cfg["see_on_every_turn"] and fresh:
            parts.append(image_part(base64.b64encode(self.frame).decode(), "image/jpeg"))
            notes.append("[camera: live view attached]")
        elif self.cfg["see_on_every_turn"]:
            notes.append("[camera: no image available right now]")

        prefix = "(spoken) " if source == "speech" else ""
        user_text = "\n\n".join(notes + [prefix + text])
        parts.append({"type": "text", "text": user_text})

        system = SYSTEM_PROMPT.format(name=self.cfg["robot_name"],
                                      emotions=", ".join(f"[{e}]" for e in topics.EMOTIONS))
        messages = [{"role": "system", "content": system}]
        messages += self.history + [{"role": "user", "content": parts}]

        raw, answer = self.stream(messages)
        # History keeps the text only: an old camera frame costs ~190 tokens and is stale anyway.
        # The assistant turn keeps its mood tag, which shows the model the format it should follow.
        self.history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": raw}]
        self.history = self.history[-2 * self.cfg["history_turns"]:]
        self.publish_reply("assistant", answer, source)

    def stream(self, messages: list[dict]) -> tuple[str, str]:
        """Streams a reply; returns (raw text with mood tag, spoken text without it)."""
        t0 = time.monotonic()
        body = {
            "messages": messages,
            "stream": True,
            "max_tokens": self.cfg["max_tokens"],
            "temperature": self.cfg["temperature"],
        }
        raw, buf, first = "", "", None
        tagged = False   # mood tag handled (found, or clearly absent)
        with requests.post(self.cfg["llm_url"], json=body, stream=True, timeout=(5, 120)) as r:
            r.raise_for_status()
            r.encoding = "utf-8"  # SSE has no charset header; requests would assume ISO-8859-1
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                delta = json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
                if not delta:  # the first chunk only carries the role; don't judge the tag on it
                    continue
                if first is None:
                    first = time.monotonic() - t0
                raw, buf = raw + delta, buf + delta
                if not tagged:
                    if (m := MOOD_TAG.match(buf)):
                        self.set_emotion(m.group(1))
                        buf, tagged = buf[m.end():], True
                    elif not buf.lstrip().startswith("[") or len(buf) > 24:
                        tagged = True   # no tag: speak it as-is
                    else:
                        continue        # still reading a possible tag
                *done, buf = SENTENCE_END.split(buf)
                for sentence in done:
                    self.speak(sentence, "llm")
        self.speak(buf, "llm")
        answer = MOOD_TAG.sub("", raw, count=1).strip()
        self.get_logger().info(
            f"reply in {time.monotonic() - t0:.1f}s (first token {first or 0:.1f}s): {raw!r}")
        return raw.strip(), answer

    def speak(self, sentence: str, _source: str):
        if sentence.strip():
            self.say.publish(String(data=sentence.strip()))

    def set_emotion(self, emotion: str):
        emotion = emotion.lower()
        self.emotion.publish(String(data=emotion if emotion in topics.EMOTIONS else "neutral"))

    def publish_reply(self, role: str, text: str, source: str):
        self.reply.publish(String(data=json.dumps({"role": role, "text": text, "source": source})))


def image_part(b64: str, mime: str) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def main():
    rclpy.init()
    try:
        rclpy.spin(Brain())
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.try_shutdown()
