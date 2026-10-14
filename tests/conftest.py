import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


import socket

import pytest


@pytest.fixture(autouse=True)
def _no_real_network_in_unit_tests(monkeypatch):
    """Unit tests must never leave the machine (a live scan once made CI hang for 18 minutes)."""
    attempts: list[str] = []
    original = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in {"127.0.0.1", "::1", "localhost"} and not str(host).startswith("/"):
            attempts.append(str(address))
            raise OSError(f"network access blocked in unit tests: {address}")
        return original(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield
    assert not attempts, f"unit test tried to reach the network: {attempts}"
