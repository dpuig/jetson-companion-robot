"""Smoke test: confirms Python runs on the Jetson and reports the platform."""
import platform
import sys


def main() -> None:
    print(f"python {sys.version.split()[0]} on {platform.machine()} ({platform.node()})")
    try:
        import torch  # optional: only present if JetPack PyTorch is installed

        print(f"torch {torch.__version__}, cuda available: {torch.cuda.is_available()}")
    except ImportError:
        print("torch not installed (optional)")


if __name__ == "__main__":
    main()
