#!/usr/bin/env python3
"""Smoke-test the running llama-server: one image+text turn and one text turn, with timings.

Runs ON the Jetson (stdlib only):  python3 scripts/llm-smoke.py [image.jpg]
Default image: the COCO "two cats on a couch" photo, downloaded once to ~/cats.jpg.
"""
import base64
import json
import os
import sys
import time
import urllib.request

URL = "http://127.0.0.1:8081/v1/chat/completions"
SYSTEM = ("You are Kusi, a friendly companion robot. Replies are spoken aloud: "
          "one to three short sentences, no markdown.")


def ask(content, label):
    body = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
            "max_tokens": 150, "temperature": 0.7}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=120))
    tm = r.get("timings", {})
    print(f"== {label}: {time.time() - t:.1f}s total | "
          f"prompt {tm.get('prompt_n')} tok @ {tm.get('prompt_per_second', 0):.0f} tok/s | "
          f"generated {tm.get('predicted_n')} tok @ {tm.get('predicted_per_second', 0):.1f} tok/s")
    print("  ", r["choices"][0]["message"]["content"].strip())


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/cats.jpg")
    if not os.path.exists(path):
        urllib.request.urlretrieve("http://images.cocodataset.org/val2017/000000039769.jpg", path)
    img = base64.b64encode(open(path, "rb").read()).decode()
    ask([{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + img}},
         {"type": "text", "text": "[camera: live view attached]\n\nWhat do you see right now?"}], "image + text")
    ask("Hi! What is your name, and what can you do?", "text only")


if __name__ == "__main__":
    main()
