"""Local live dashboard for the FlyScroll Freedoom adventure pilot."""
from __future__ import annotations
import base64, io, json, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from PIL import Image

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "dashboard"
STATE: dict[str, Any] = {"connected": False, "frame": 0, "timestamp": 0, "rates": {}, "features": {}, "actions": [], "stats": {}, "target": "Waiting for the fly...", "brain_connected": False, "spikes": 0, "total_spikes": 0, "neural_ms": 0.0, "kernel_ms": 0.0, "fps": 0.0, "screen": None, "reason": "Waiting for simulation telemetry"}
LOCK = threading.Lock()
FRAME_JPEG: bytes | None = None

def publish(frame, rates=None, features=None, actions=None, stats=None, target="exploring", brain_connected=False, spikes=0, total_spikes=0, neural_ms=0.0, kernel_ms=0.0, fps=0.0, decision=0, reward=0.0):
    global FRAME_JPEG
    if frame is not None:
        image = Image.fromarray(frame).convert("RGB")
        image.thumbnail((640, 480), Image.Resampling.BILINEAR)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=78)
        with LOCK: FRAME_JPEG = buffer.getvalue()
    payload = {"connected": True, "timestamp": time.time(), "frame": int(decision), "rates": rates or {}, "features": features or {}, "actions": actions or [], "stats": stats or {}, "target": str(target), "brain_connected": bool(brain_connected), "spikes": int(spikes), "total_spikes": int(total_spikes), "neural_ms": round(float(neural_ms), 3), "kernel_ms": round(float(kernel_ms), 3), "fps": round(float(fps), 2), "reward": round(float(reward), 3), "reason": "Live ViZDoom telemetry"}
    with LOCK: STATE.update(payload)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"): self._file("index.html", "text/html; charset=utf-8")
        elif self.path == "/app.js": self._file("app.js", "text/javascript; charset=utf-8")
        elif self.path == "/styles.css": self._file("styles.css", "text/css; charset=utf-8")
        elif self.path == "/api/state":
            with LOCK: body = json.dumps(STATE, separators=(",", ":")).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        elif self.path.startswith("/api/frame.jpg"):
            with LOCK: body = FRAME_JPEG
            if body is None: self.send_error(503, "No game frame published yet"); return
            self.send_response(200); self.send_header("Content-Type", "image/jpeg"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        else: self.send_error(404)
    def _file(self, name, content_type):
        path = WEB_ROOT / name
        if not path.is_file(): self.send_error(404, f"Missing dashboard asset: {name}"); return
        body = path.read_bytes()
        self.send_response(200); self.send_header("Content-Type", content_type); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *_args): pass

class FlyScrollDashboard:
    def __init__(self, host="127.0.0.1", port=8765, open_browser=True):
        self.server = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = f"http://{host}:{self.server.server_port}/"
        if open_browser: threading.Timer(0.8, lambda: webbrowser.open(self.url)).start()
        print(f"[dashboard] Live dashboard: {self.url}", flush=True)
    def close(self):
        self.server.shutdown(); self.server.server_close()
