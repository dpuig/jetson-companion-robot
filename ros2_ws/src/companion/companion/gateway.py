"""Gateway: the robot's web pages, and the bridge between them and ROS.

    /        chat page: text and file input, camera view, the running conversation
    /face    the robot's face, shown fullscreen on the robot's display (kiosk) or any browser

    POST /api/text   {"text": str}                     → /user/text
    POST /api/file   multipart file (+ form "prompt")  → saved to upload_dir → /user/file
    GET  /api/events server-sent events, JSON with a "type":
                       reply   {"role", "text", "source"}      from /robot/reply
                       state   {"state"}                       idle | listening | thinking | speaking
                       emotion {"emotion"}                     from /robot/emotion
                       mouth   {"env": [0..1], "dt"}           from /robot/mouth
    GET  /api/frame  newest camera JPEG

It also owns /robot/state: the one overall state, derived from the listening/thinking/speaking
signals (speaking wins, then thinking, then listening), so the face and any future consumer
(LEDs, head motors) agree on it.
"""
import asyncio
import json
import os
import re
import threading
import time

import rclpy
import uvicorn
from ament_index_python.packages import get_package_share_directory
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool, String

from companion import topics


class TextIn(BaseModel):
    text: str


class Gateway(Node):
    def __init__(self):
        super().__init__("gateway")
        p = self.declare_parameters("", [
            ("host", "0.0.0.0"),
            ("port", 8080),
            ("upload_dir", "~/companion/uploads"),
        ])
        self.cfg = {x.name: x.value for x in p}
        self.upload_dir = os.path.expanduser(self.cfg["upload_dir"])
        os.makedirs(self.upload_dir, exist_ok=True)
        self.frame: bytes | None = None
        self.browsers: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

        self.flags = {"listening": False, "thinking": False, "speaking": False}
        self.state = "idle"
        self.emotion = "neutral"

        self.text_pub = self.create_publisher(String, topics.USER_TEXT, 10)
        self.file_pub = self.create_publisher(String, topics.USER_FILE, 10)
        self.state_pub = self.create_publisher(String, topics.STATE, 10)
        self.create_subscription(String, topics.REPLY, lambda m: self.send("reply", json.loads(m.data)), 10)
        self.create_subscription(String, topics.MOUTH, lambda m: self.send("mouth", json.loads(m.data)), 10)
        self.create_subscription(String, topics.EMOTION, self.on_emotion, 10)
        self.create_subscription(CompressedImage, topics.IMAGE, lambda m: setattr(self, "frame", bytes(m.data)), 1)
        for flag, topic in (("listening", topics.LISTENING), ("thinking", topics.THINKING),
                            ("speaking", topics.SPEAKING)):
            self.create_subscription(Bool, topic, lambda m, f=flag: self.on_flag(f, m.data), 10)
        self.state_pub.publish(String(data=self.state))

    def on_flag(self, flag: str, value: bool):
        self.flags[flag] = value
        state = next((s for s in ("speaking", "thinking", "listening") if self.flags[s]), "idle")
        if state != self.state:
            self.state = state
            self.state_pub.publish(String(data=state))
            self.send("state", {"state": state})

    def on_emotion(self, msg: String):
        self.emotion = msg.data
        self.send("emotion", {"emotion": msg.data})

    def send(self, kind: str, payload: dict):  # ROS thread → every connected browser
        if self.loop:
            data = json.dumps({"type": kind, **payload})
            for q in list(self.browsers):
                self.loop.call_soon_threadsafe(q.put_nowait, data)

    def app(self) -> FastAPI:
        app = FastAPI()
        web = os.path.join(get_package_share_directory("companion"), "web")

        @app.on_event("startup")
        async def grab_loop():
            self.loop = asyncio.get_running_loop()

        @app.get("/")
        def chat_page():
            return FileResponse(os.path.join(web, "index.html"))

        @app.get("/face")
        def face_page():
            return FileResponse(os.path.join(web, "face.html"))

        @app.post("/api/text")
        def text(body: TextIn):
            self.text_pub.publish(String(data=body.text))
            return {"ok": True}

        @app.post("/api/file")
        async def upload(file: UploadFile = File(...), prompt: str = Form("")):
            safe = re.sub(r"[^\w.\-]", "_", os.path.basename(file.filename or "upload"))
            path = os.path.join(self.upload_dir, f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}")
            with open(path, "wb") as f:
                f.write(await file.read())
            self.file_pub.publish(String(data=json.dumps({"path": path, "prompt": prompt})))
            return {"ok": True, "path": path}

        @app.get("/api/frame")
        def frame():
            if not self.frame:
                return Response(status_code=204)
            return Response(self.frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

        @app.get("/api/events")
        async def events():
            q: asyncio.Queue = asyncio.Queue()
            # A page that (re)connects starts from the current face, not a blank one.
            q.put_nowait(json.dumps({"type": "state", "state": self.state}))
            q.put_nowait(json.dumps({"type": "emotion", "emotion": self.emotion}))
            self.browsers.add(q)

            async def gen():
                try:
                    while True:
                        try:
                            yield f"data: {await asyncio.wait_for(q.get(), 15)}\n\n"
                        except asyncio.TimeoutError:
                            yield ": keepalive\n\n"
                finally:
                    self.browsers.discard(q)

            return StreamingResponse(gen(), media_type="text/event-stream")

        return app


def main():
    rclpy.init()
    node = Gateway()
    threading.Thread(target=rclpy.spin, args=(node,), daemon=True).start()
    node.get_logger().info(f"web UI on http://{node.cfg['host']}:{node.cfg['port']} (face at /face)")
    try:
        uvicorn.run(node.app(), host=node.cfg["host"], port=node.cfg["port"], log_level="warning")
    finally:
        rclpy.try_shutdown()
