"""Production entry point: `python -m app.api.serve`.

Railway's private network is IPv6 while its health checks arrive over IPv4. uvicorn's
`--host ::` makes an IPv6-only socket (asyncio sets IPV6_V6ONLY), so we bind one
dual-stack socket ourselves and hand it to uvicorn.
"""

import os
import socket

import uvicorn


def dual_stack_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", port))
    sock.set_inheritable(True)
    return sock


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    config = uvicorn.Config(
        "app.api.main:app",
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=False,
    )
    uvicorn.Server(config).run(sockets=[dual_stack_socket(port)])


if __name__ == "__main__":
    main()
