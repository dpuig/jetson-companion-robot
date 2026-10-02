#!/usr/bin/env python3
"""Checks that the model opens each reply with a valid [mood] tag, using brain.py's real system prompt.

Runs ON the Jetson with llama-server up (stdlib only):  python3 scripts/llm-emotion-test.py
Each prompt is a fresh conversation. Prints the tag, timing and reply; exits 1 if any tag is invalid.
"""
import ast
import json
import pathlib
import re
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "ros2_ws/src/companion/companion"
URL = "http://127.0.0.1:8081/v1/chat/completions"


def constant(path, name):
    """Read a module-level constant without importing the module (brain.py needs rclpy)."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == name:
            return ast.literal_eval(node.value)
    raise KeyError(name)


EMOTIONS = constant(PKG / "topics.py", "EMOTIONS")
SYSTEM = constant(PKG / "brain.py", "SYSTEM_PROMPT").format(
    name="Kusi", emotions=", ".join(f"[{e}]" for e in EMOTIONS))
TAG = re.compile(r"^\s*\[(\w+)\]\s*")

PROMPTS = [
    "Hi Kusi! How are you today?",
    "I just got the job I applied for!",
    "My dog has been sick all week and I'm worried.",
    "What do you think is inside a black hole?",
    "Guess what, I'm going to Machu Picchu tomorrow!",
    "Can you explain what a qubit is in one sentence?",
    "Blorp fizzle wonk?",
    "I love spending time with you, you're my favorite robot.",
]


def main():
    bad = 0
    for prompt in PROMPTS:
        body = {"messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": "[camera: no image available right now]\n\n" + prompt}],
                "max_tokens": 120, "temperature": 0.7}
        req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        t = time.time()
        reply = json.load(urllib.request.urlopen(req, timeout=120))["choices"][0]["message"]["content"]
        m = TAG.match(reply)
        tag = m.group(1).lower() if m else None
        ok = tag in EMOTIONS
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} [{tag}] {time.time() - t:4.1f}s  {prompt}\n      → {reply.strip()!r}")
    print(f"\n{len(PROMPTS) - bad}/{len(PROMPTS)} replies had a valid mood tag")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
