import ipaddress
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ejudgment.config import Settings
from tests.fixtures.legacy_fixture import LegacyFixture, build_legacy_fixture

_real_connect = socket.socket.connect


def _is_local(address: Any) -> bool:
    if not isinstance(address, tuple):  # unix sockets
        return True
    host = address[0]
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that tries to reach a non-loopback host (GhaLII, paid APIs, ...)."""

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if not _is_local(address):
            raise RuntimeError(f"Network access blocked in tests: {address!r}")
        return _real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture
def legacy_fixture(tmp_path: Path) -> LegacyFixture:
    return build_legacy_fixture(tmp_path)


@pytest.fixture
def settings() -> Iterator[Settings]:
    yield Settings(ingest_batch_size=17)  # odd size so batches straddle special rows
