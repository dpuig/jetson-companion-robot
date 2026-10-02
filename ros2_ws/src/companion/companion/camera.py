"""Camera: publishes a small JPEG of the newest frame a few times a second.

`source` is a V4L2 device (/dev/video0) or a video file, which loops, for testing without a camera.
A background thread keeps draining the device so the frame we publish is current, not buffered.
"""
import os
import threading

import cv2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

from companion import topics


class Camera(Node):
    def __init__(self):
        super().__init__("camera")
        p = self.declare_parameters("", [
            ("source", "/dev/video0"),
            ("fps", 2.0),
            ("width", 512),
            ("jpeg_quality", 80),
        ])
        self.cfg = {x.name: x.value for x in p}
        self.is_file = os.path.isfile(self.cfg["source"]) and not self.cfg["source"].startswith("/dev/")
        self.cap = self.open()
        self.latest = None
        self.lock = threading.Lock()
        self.pub = self.create_publisher(CompressedImage, topics.IMAGE, 1)
        if not self.is_file:
            threading.Thread(target=self.drain, daemon=True).start()
        self.create_timer(1.0 / self.cfg["fps"], self.tick)

    def open(self):
        src = self.cfg["source"]
        cap = cv2.VideoCapture(src) if self.is_file else cv2.VideoCapture(src, cv2.CAP_V4L2)
        if not cap.isOpened():
            self.get_logger().warn(f"cannot open {src}; will keep retrying")
        else:
            self.get_logger().info(f"streaming from {src}")
        return cap

    def drain(self):
        while rclpy.ok():
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.latest = frame
            else:  # unplugged or not there yet: back off and reopen
                self.cap.release()
                threading.Event().wait(2.0)
                self.cap = self.open()

    def tick(self):
        if self.is_file:
            ok, frame = self.cap.read()
            if not ok:  # loop the test video
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self.cap.read()
            if not ok:
                return
        else:
            with self.lock:
                frame, self.latest = self.latest, None
            if frame is None:
                return

        h, w = frame.shape[:2]
        if w > self.cfg["width"]:
            frame = cv2.resize(frame, (self.cfg["width"], int(h * self.cfg["width"] / w)),
                               interpolation=cv2.INTER_AREA)
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.cfg["jpeg_quality"]])
        if ok:
            msg = CompressedImage(format="jpeg", data=jpg.tobytes())
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = "camera"
            self.pub.publish(msg)


def main():
    rclpy.init()
    try:
        rclpy.spin(Camera())
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.try_shutdown()
