"""Local wake signal for the durable inbox; SQLite remains the source of truth."""

import socket
from .store import ROOT


def signal():
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(b"wake", str(ROOT / "data" / "worker.sock"))
    except OSError:
        pass  # Offline worker will read the durable inbox at startup.
