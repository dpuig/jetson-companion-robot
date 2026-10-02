"""Starts the inference servers and every companion node.

    ros2 launch companion companion.launch.py                    # everything
    ros2 launch companion companion.launch.py servers:=false     # servers already running
    ros2 launch companion companion.launch.py camera:=false hearing:=false voice:=false
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

HOME = os.path.expanduser("~")
MODELS = os.path.join(HOME, "models")
OPT = os.path.join(HOME, "opt")


def evict_page_cache(roots, min_bytes=5 << 20):
    """Drop cached pages of large files under `roots` before the model loads (no root needed).

    On Jetson, CPU and GPU share RAM, and cudaMalloc (NvMap) only takes truly free pages; it does
    not reclaim page cache. Anything recently read stays cached (seen: 2.3 GB of cuDNN/TensorRT
    libraries, and the model files themselves), and loading then fails with "cudaMalloc failed:
    out of memory" while `free` still shows GBs "available". llama-server's `--load-mode dio`
    keeps the model from refilling the cache as it loads.
    """
    for root in roots:
        for dirpath, _dirs, names in os.walk(root):
            for name in names:
                path = os.path.join(dirpath, name)
                try:
                    if os.path.islink(path) or os.path.getsize(path) < min_bytes:
                        continue
                    fd = os.open(path, os.O_RDONLY)
                    os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
                    os.close(fd)
                except OSError:
                    pass


def generate_launch_description():
    share = get_package_share_directory("companion")
    evict_page_cache([MODELS, OPT, "/usr/lib/aarch64-linux-gnu", "/usr/local/cuda/lib64"])
    params = LaunchConfiguration("params")
    servers = IfCondition(LaunchConfiguration("servers"))

    llama = ExecuteProcess(
        name="llama_server",
        condition=servers,
        output="screen",
        cmd=[
            f"{OPT}/llama.cpp/build/bin/llama-server",
            "-m", f"{MODELS}/Qwen3VL-4B-Instruct-Q4_K_M.gguf",
            "--mmproj", f"{MODELS}/mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf",
            "-ngl", "99",             # all layers on the GPU
            "-c", "8192",             # context: 8K tokens of conversation + one image
            "-np", "1",               # one conversation at a time
            "-fa", "on",
            "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",  # halves KV-cache memory
            "--load-mode", "dio",     # direct I/O: weights skip the page cache (see evict_page_cache)
            "--host", "127.0.0.1", "--port", "8081",
        ],
    )
    whisper = ExecuteProcess(
        name="whisper_server",
        condition=servers,
        output="screen",
        cmd=[
            f"{OPT}/whisper.cpp/build/bin/whisper-server",
            "-m", f"{MODELS}/ggml-small-q5_1.bin",
            "--host", "127.0.0.1", "--port", "8082",
        ],
    )

    def node(name):
        return Node(
            package="companion",
            executable=name,
            name=name,
            parameters=[params],
            output="screen",
            condition=IfCondition(LaunchConfiguration(name)),
        )

    args = [
        DeclareLaunchArgument("params", default_value=os.path.join(share, "config", "companion.yaml")),
        DeclareLaunchArgument("servers", default_value="true"),
    ] + [
        DeclareLaunchArgument(n, default_value="true")
        for n in ("camera", "hearing", "brain", "voice", "gateway")
    ]
    nodes = [node(n) for n in ("camera", "hearing", "brain", "voice", "gateway")]
    return LaunchDescription(args + [llama, whisper] + nodes)
