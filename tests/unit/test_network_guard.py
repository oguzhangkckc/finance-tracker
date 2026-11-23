import socket

import pytest


def test_real_network_is_blocked_in_tests() -> None:
    with pytest.raises(RuntimeError, match="ağ erişimi kapalı"):
        socket.create_connection(("example.com", 443), timeout=1)


def test_dns_lookup_is_blocked_in_tests() -> None:
    with pytest.raises(RuntimeError, match="ağ erişimi kapalı"):
        socket.getaddrinfo("example.com", 443)
