#!/usr/bin/env python3
"""
Standalone Neural Visualization Server for Fruitfly DOOM.
Raw socket HTTP + WebSocket - NO http.server, NO socketserver, NO asyncio.
Pure stdlib: socket, threading, select, json, base64, hashlib, struct.
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
import threading
import socket
import select
import base64
import hashlib
import struct
import re

# Configure logging FIRST
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout
)
log = logging.getLogger("neural-viz")

FRONTEND_DIR = Path(__file__).parent / "neural_viz_frontend"

# Global state
latest_state = {
    "timestamp": 0,
    "frame": 0,
    "rates": {},
    "features": {},
    "actions": [],
    "turn_delta": 0.0,
    "visual_dn": 0.0,
    "spikes": 0,
    "total_spikes": 0,
    "simulation_ms": 0.0,
    "kernel_ms": 0.0,
    "frame_luma_mean": 0.0,
    "frame_luma_std": 0.0,
}
state_lock = threading.Lock()
ws_clients = []
ws_lock = threading.Lock()
http_server_running = False
ws_server_running = False

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
HTTP_VERSION = "HTTP/1.1"

def update_state(data: dict):
    global latest_state
    with state_lock:
        latest_state = {**latest_state, **data, "timestamp": time.time()}


def get_state() -> dict:
    with state_lock:
        return dict(latest_state)


def broadcast_ws(message: str):
    dead = []
    data = message.encode('utf-8')
    with ws_lock:
        for ws in ws_clients:
            try:
                ws_send_frame(ws, data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in ws_clients:
                ws_clients.remove(ws)


# ===== WebSocket Frame Helpers =====
def ws_handshake(client_sock, request: bytes) -> bool:
    try:
        req_str = request.decode('utf-8', errors='ignore')
        lines = req_str.split('\r\n')
        key = None
        for line in lines:
            if line.lower().startswith('sec-websocket-key:'):
                key = line.split(':', 1)[1].strip()
                break
        if not key:
            return False

        accept_key = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()
        ).decode()

        response = (
            f"{HTTP_VERSION} 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key}\r\n"
            "\r\n"
        )
        client_sock.send(response.encode())
        return True
    except Exception as e:
        log.debug(f"WS handshake error: {e}")
        return False


def ws_recv_frame(sock) -> bytes | None:
    try:
        header = sock.recv(2)
        if not header or len(header) < 2:
            return None
        fin = header[0] & 0x80
        opcode = header[0] & 0x0F
        masked = header[1] & 0x80
        payload_len = header[1] & 0x7F

        if opcode == 0x8:  # Close
            return None

        if payload_len == 126:
            ext = sock.recv(2)
            if len(ext) < 2:
                return None
            payload_len = struct.unpack('>H', ext)[0]
        elif payload_len == 127:
            ext = sock.recv(8)
            if len(ext) < 8:
                return None
            payload_len = struct.unpack('>Q', ext)[0]

        mask = b''
        if masked:
            mask = sock.recv(4)
            if len(mask) < 4:
                return None

        payload = b''
        while len(payload) < payload_len:
            chunk = sock.recv(payload_len - len(payload))
            if not chunk:
                return None
            payload += chunk

        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

        return payload
    except Exception:
        return None


def ws_send_frame(sock, data: bytes, opcode: int = 0x1) -> bool:
    try:
        payload_len = len(data)
        header = bytearray()
        header.append(0x80 | opcode)
        if payload_len < 126:
            header.append(payload_len)
        elif payload_len < 65536:
            header.append(126)
            header.extend(struct.pack('>H', payload_len))
        else:
            header.append(127)
            header.extend(struct.pack('>Q', payload_len))
        sock.send(header + data)
        return True
    except Exception:
        return False


def ws_client_handler(client_sock, addr):
    client_id = str(uuid.uuid4())[:8]
    log.info(f"WS client connected: {client_id} from {addr}")

    try:
        initial = json.dumps({"type": "state", "data": get_state()})
        ws_send_frame(client_sock, initial.encode('utf-8'))

        while True:
            ready = select.select([client_sock], [], [], 1.0)
            if ready[0]:
                payload = ws_recv_frame(client_sock)
                if payload is None:
                    break
            else:
                ws_send_frame(client_sock, b'', opcode=0x9)  # Ping
    except Exception as e:
        log.debug(f"WS client error: {e}")
    finally:
        with ws_lock:
            if client_sock in ws_clients:
                ws_clients.remove(client_sock)
        try:
            client_sock.close()
        except Exception:
            pass
        log.info(f"WS client disconnected: {client_id}")


def ws_server_thread(host: str, port: int):
    global ws_server_running
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(5)
    server.settimeout(1.0)
    ws_server_running = True
    log.info(f"WebSocket server listening on ws://{host}:{port}")

    while ws_server_running:
        try:
            client_sock, addr = server.accept()
            client_sock.settimeout(5.0)
            request = client_sock.recv(4096)
            if ws_handshake(client_sock, request):
                with ws_lock:
                    ws_clients.append(client_sock)
                t = threading.Thread(target=ws_client_handler, args=(client_sock, addr), daemon=True)
                t.start()
            else:
                client_sock.close()
        except socket.timeout:
            continue
        except Exception as e:
            if ws_server_running:
                log.debug(f"WS server error: {e}")

    server.close()


# ===== Raw HTTP Helpers =====
def parse_request(data: bytes) -> dict | None:
    """Parse raw HTTP request. Returns dict with method, path, headers, body."""
    try:
        text = data.decode('utf-8', errors='ignore')
        # Split headers and body
        parts = text.split('\r\n\r\n', 1)
        header_part = parts[0]
        body = parts[1] if len(parts) > 1 else ''

        lines = header_part.split('\r\n')
        if not lines:
            return None

        # Parse request line
        request_line = lines[0].split(' ')
        if len(request_line) != 3:
            return None
        method, path, version = request_line

        # Parse headers
        headers = {}
        for line in lines[1:]:
            if ':' in line:
                k, v = line.split(':', 1)
                headers[k.strip().lower()] = v.strip()

        return {
            'method': method,
            'path': path,
            'version': version,
            'headers': headers,
            'body': body
        }
    except Exception:
        return None


def send_response(sock, status: int, headers: dict, body: bytes = b''):
    """Send HTTP response."""
    status_text = {200: "OK", 400: "Bad Request", 404: "Not Found", 500: "Internal Server Error"}.get(status, "OK")
    response = f"{HTTP_VERSION} {status} {status_text}\r\n"
    for k, v in headers.items():
        response += f"{k}: {v}\r\n"
    response += f"Content-Length: {len(body)}\r\n"
    response += "\r\n"
    sock.send(response.encode() + body)


def serve_file(sock, filename: str):
    filepath = FRONTEND_DIR / filename
    if not filepath.is_file() or ".." in filename:
        send_response(sock, 404, {"Content-Type": "text/plain"}, b"Not Found")
        return

    mime_type, _ = mimetypes.guess_type(str(filepath))
    if mime_type is None:
        mime_type = "application/octet-stream"

    with open(filepath, "rb") as f:
        content = f.read()

    send_response(sock, 200, {"Content-Type": mime_type, "Cache-Control": "no-cache"}, content)


def handle_http_request(client_sock, addr):
    """Handle a single HTTP request."""
    try:
        # Read request (with timeout)
        client_sock.settimeout(5.0)
        data = b''
        while True:
            chunk = client_sock.recv(4096)
            if not chunk:
                break
            data += chunk
            # Check if we have complete request (headers end with \r\n\r\n)
            if b'\r\n\r\n' in data:
                # Check Content-Length for body
                header_end = data.index(b'\r\n\r\n') + 4
                headers_text = data[:header_end].decode('utf-8', errors='ignore')
                content_length = 0
                for line in headers_text.split('\r\n'):
                    if line.lower().startswith('content-length:'):
                        content_length = int(line.split(':', 1)[1].strip())
                        break
                if len(data) >= header_end + content_length:
                    break

        if not data:
            return

        req = parse_request(data)
        if not req:
            send_response(client_sock, 400, {"Content-Type": "text/plain"}, b"Bad Request")
            return

        method = req['method']
        path = req['path']
        body = req['body']

        # Route
        if method == "GET":
            if path in ("/", "/viz", "/viz/"):
                serve_file(client_sock, "index.html")
            elif path.startswith("/viz/"):
                serve_file(client_sock, path[5:])
            elif path == "/api/state":
                send_response(client_sock, 200,
                    {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
                    json.dumps(get_state()).encode())
            else:
                send_response(client_sock, 404, {"Content-Type": "text/plain"}, b"Not Found")

        elif method == "POST" and path == "/api/neural":
            try:
                data = json.loads(body)
                update_state(data)
                broadcast_ws(json.dumps({"type": "update", "data": data}))
                send_response(client_sock, 200,
                    {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
                    json.dumps({"status": "ok", "connections": len(ws_clients)}).encode())
            except Exception as e:
                send_response(client_sock, 400,
                    {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
                    json.dumps({"status": "error", "message": str(e)}).encode())
        else:
            send_response(client_sock, 404, {"Content-Type": "text/plain"}, b"Not Found")

    except Exception as e:
        log.debug(f"HTTP request error: {e}")
    finally:
        try:
            client_sock.close()
        except Exception:
            pass


def http_server_thread(host: str, port: int):
    global http_server_running
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(50)
    server.settimeout(1.0)
    http_server_running = True
    log.info(f"HTTP server running on http://{host}:{port}")
    log.info(f"Dashboard: http://{host}:{port}/viz")

    while http_server_running:
        try:
            client_sock, addr = server.accept()
            # Handle each request in a thread (simple but works for low traffic)
            t = threading.Thread(target=handle_http_request, args=(client_sock, addr), daemon=True)
            t.start()
        except socket.timeout:
            continue
        except Exception as e:
            if http_server_running:
                log.debug(f"HTTP server error: {e}")

    server.close()


# ===== Main =====
def main():
    parser = argparse.ArgumentParser(description="Neural Visualization Server for Fruitfly DOOM (raw sockets, no http.server)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ws-port", type=int, default=8766, help="WebSocket port")
    args = parser.parse_args()

    if not FRONTEND_DIR.exists():
        log.error(f"Frontend directory not found: {FRONTEND_DIR}")
        sys.exit(1)

    # Start WebSocket server thread
    ws_thread = threading.Thread(target=ws_server_thread, args=(args.host, args.ws_port), daemon=True)
    ws_thread.start()

    # Run HTTP server in main thread
    try:
        http_server_thread(args.host, args.port)
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        global http_server_running, ws_server_running
        http_server_running = False
        ws_server_running = False


if __name__ == "__main__":
    main()