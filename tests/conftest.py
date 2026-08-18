"""全テストで外部接続を禁止する共通fixture。"""

from collections.abc import Iterator

import pytest

from tests.support.no_external_network import install_network_guards


@pytest.fixture(scope="session", autouse=True)
def _block_external_network() -> Iterator[None]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        install_network_guards(monkeypatch)
        yield
    finally:
        monkeypatch.undo()
