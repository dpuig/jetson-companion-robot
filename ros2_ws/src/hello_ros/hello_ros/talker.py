"""Smoke test: publishes a counter on /chatter at 1 Hz."""
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class Talker(Node):
    def __init__(self) -> None:
        super().__init__("talker")
        self.pub = self.create_publisher(String, "chatter", 10)
        self.count = 0
        self.create_timer(1.0, self.tick)

    def tick(self) -> None:
        msg = String(data=f"hello from jetson #{self.count}")
        self.pub.publish(msg)
        self.get_logger().info(msg.data)
        self.count += 1


def main() -> None:
    rclpy.init()
    try:
        rclpy.spin(Talker())
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.try_shutdown()
