"""外部OS socketとHTTP clientの接続経路をfail-fastに置き換える。"""

import socket
import threading
import urllib.request
from typing import Any, NoReturn
from weakref import WeakSet

import httpx
import pytest

_ORIGINAL_SOCKET_CONNECT = socket.socket.connect
_ORIGINAL_SOCKET_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_SOCKET_SEND = socket.socket.send
_ORIGINAL_SOCKET_SENDALL = socket.socket.sendall
_ORIGINAL_SOCKETPAIR = socket.socketpair
# 内部 socketpair の endpoint だけを識別し、通常の socket への送信は拒否する。
_INTERNAL_SOCKETPAIR_SOCKETS: WeakSet[socket.socket] = WeakSet()
_SOCKETPAIR_STATE = threading.local()


def _blocked_external_call(*args: Any, **kwargs: Any) -> NoReturn:
    del args, kwargs
    raise AssertionError("External network access is forbidden in Phase 0 tests")


def _guarded_socket_connect(connection: socket.socket, address: Any) -> None:
    if getattr(_SOCKETPAIR_STATE, "allow", False):
        _ORIGINAL_SOCKET_CONNECT(connection, address)
        return
    raise AssertionError("External network access is forbidden in Phase 0 tests")


def _guarded_socket_connect_ex(connection: socket.socket, address: Any) -> int:
    if getattr(_SOCKETPAIR_STATE, "allow", False):
        return _ORIGINAL_SOCKET_CONNECT_EX(connection, address)
    raise AssertionError("External network access is forbidden in Phase 0 tests")


def _guarded_socket_send(connection: socket.socket, data: Any, flags: int = 0) -> int:
    if getattr(_SOCKETPAIR_STATE, "allow", False) or connection in _INTERNAL_SOCKETPAIR_SOCKETS:
        return _ORIGINAL_SOCKET_SEND(connection, data, flags)
    raise AssertionError("External network access is forbidden in Phase 0 tests")


def _guarded_socket_sendall(connection: socket.socket, data: Any, flags: int = 0) -> None:
    if getattr(_SOCKETPAIR_STATE, "allow", False) or connection in _INTERNAL_SOCKETPAIR_SOCKETS:
        _ORIGINAL_SOCKET_SENDALL(connection, data, flags)
        return
    raise AssertionError("External network access is forbidden in Phase 0 tests")


def _guarded_socketpair(*args: Any, **kwargs: Any) -> tuple[socket.socket, socket.socket]:
    previous = getattr(_SOCKETPAIR_STATE, "allow", False)
    _SOCKETPAIR_STATE.allow = True
    try:
        pair = _ORIGINAL_SOCKETPAIR(*args, **kwargs)
        _INTERNAL_SOCKETPAIR_SOCKETS.update(pair)
        return pair
    finally:
        _SOCKETPAIR_STATE.allow = previous


def install_network_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    """pytest TestClientのASGI transportを残し、それ以外の接続を拒否する。"""

    monkeypatch.setattr(socket.socket, "connect", _guarded_socket_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_socket_connect_ex)
    monkeypatch.setattr(socket.socket, "send", _guarded_socket_send)
    monkeypatch.setattr(socket.socket, "sendall", _guarded_socket_sendall)
    monkeypatch.setattr(socket.socket, "sendto", _blocked_external_call)
    monkeypatch.setattr(socket, "socketpair", _guarded_socketpair)
    monkeypatch.setattr(socket, "create_connection", _blocked_external_call)
    monkeypatch.setattr(httpx, "HTTPTransport", _blocked_external_call)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", _blocked_external_call)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked_external_call)
