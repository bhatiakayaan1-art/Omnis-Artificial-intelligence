import socket


DEFAULT_PORT = 8000
PORT_ATTEMPTS = 20


def available_local_port(start=DEFAULT_PORT, attempts=PORT_ATTEMPTS, host="127.0.0.1"):
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            try:
                listener.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(
        f"No free local Omnis port is available between {start} and {start + attempts - 1}."
    )
