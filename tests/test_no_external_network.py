import http.client
import socket
import urllib.request

import httpx
import pytest


def test_external_connection_entrypoints_fail_fast() -> None:
    with pytest.raises(AssertionError, match="External network access"):
        socket.create_connection(("127.0.0.1", 1))

    with pytest.raises(AssertionError, match="External network access"):
        httpx.HTTPTransport()

    with pytest.raises(AssertionError, match="External network access"):
        httpx.AsyncHTTPTransport()

    with pytest.raises(AssertionError, match="External network access"):
        urllib.request.urlopen("http://127.0.0.1")


def test_socket_methods_are_guarded_without_connecting() -> None:
    connection = socket.socket()
    try:
        with pytest.raises(AssertionError, match="External network access"):
            connection.connect(("127.0.0.1", 1))
        with pytest.raises(AssertionError, match="External network access"):
            connection.connect_ex(("127.0.0.1", 1))
    finally:
        connection.close()


def test_socket_getaddrinfo_is_guarded_without_resolving() -> None:
    with pytest.raises(AssertionError, match="External network access"):
        socket.getaddrinfo("localhost", 1)


def test_socket_sendto_is_guarded_without_sending() -> None:
    connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(AssertionError, match="External network access"):
            connection.sendto(b"blocked", ("127.0.0.1", 9))
    finally:
        connection.close()


def test_socket_send_is_guarded_without_sending() -> None:
    connection = socket.socket()
    try:
        with pytest.raises(AssertionError, match="External network access"):
            connection.send(b"blocked")
    finally:
        connection.close()


def test_socket_sendall_is_guarded_without_sending() -> None:
    connection = socket.socket()
    try:
        with pytest.raises(AssertionError, match="External network access"):
            connection.sendall(b"blocked")
    finally:
        connection.close()


def test_http_client_connect_methods_are_guarded_without_connecting() -> None:
    http_connection = http.client.HTTPConnection("127.0.0.1", 1)
    try:
        with pytest.raises(AssertionError, match="External network access"):
            http_connection.connect()
    finally:
        http_connection.close()

    https_connection = http.client.HTTPSConnection("127.0.0.1", 1)
    try:
        with pytest.raises(AssertionError, match="External network access"):
            https_connection.connect()
    finally:
        https_connection.close()


def test_socketpair_internal_send_methods_remain_allowed() -> None:
    left, right = socket.socketpair()
    try:
        assert left.send(b"allowed") == len(b"allowed")
        assert right.recv(len(b"allowed")) == b"allowed"

        right.sendall(b"also allowed")
        assert left.recv(len(b"also allowed")) == b"also allowed"
    finally:
        left.close()
        right.close()
