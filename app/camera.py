#!/usr/bin/env python3
"""Serve multiple V4L2 cameras as MJPEG streams on one web page.

Usage (LeKiwi defaults):
    python3 cam_stream.py
    python3 cam_stream.py --cams /dev/video0:front:180 /dev/video2:wrist:90
    python3 cam_stream.py --cams 0:cam0:0 2:cam1:0 --port 8080

Then open http://<robot-ip>:8080 in a browser.
"""

import json
import argparse
import html
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2

BOUNDARY = "frameboundary"

ROTATIONS = {
    0: None,
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


class CameraWorker(threading.Thread):
    """Grabs frames from one camera as fast as it can, keeping only the latest."""

    daemon = True

    def __init__(self, source, name, rotate, width, height, fps, quality):
        super().__init__(name=f"cam-{name}")
        self.source = source
        self.name = name
        self.rotate = ROTATIONS[rotate]
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = quality

        self._cond = threading.Condition()
        self._jpeg = None
        self._seq = 0
        self.capture_ns = 0
        self._stop = threading.Event()
        self.status = "starting"
        self.frames = 0

    def _open(self):
        src = int(self.source) if str(self.source).isdigit() else self.source
        cap = cv2.VideoCapture(src, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def run(self):
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
        cap = None
        while not self._stop.is_set():
            if cap is None:
                cap = self._open()
                if cap is None:
                    self.status = f"cannot open {self.source}"
                    self._stop.wait(2.0)
                    continue
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self.status = f"streaming {w}x{h}"
                print(f"[{self.name}] opened {self.source} at {w}x{h}", flush=True)

            ok, frame = cap.read()
            capture_ns = time.monotonic_ns()
            if not ok or frame is None:
                self.status = "read failed, reopening"
                cap.release()
                cap = None
                self._stop.wait(1.0)
                continue

            if self.rotate is not None:
                frame = cv2.rotate(frame, self.rotate)

            ok, buf = cv2.imencode(".jpg", frame, encode_params)
            if not ok:
                continue

            with self._cond:
                self._jpeg = buf.tobytes()
                self.capture_ns = capture_ns
                self._seq += 1
                self.frames += 1
                self._cond.notify_all()

        if cap is not None:
            cap.release()

    def wait_frame(self, last_seq, timeout=5.0):
        """Block until a frame newer than last_seq exists. Returns (jpeg, seq)."""
        with self._cond:
            if self._seq == last_seq:
                self._cond.wait(timeout)
            return self._jpeg, self._seq

    def stop(self):
        self._stop.set()


PAGE = """<!doctype html>
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; background: #111; color: #eee;
         font: 14px system-ui, -apple-system, sans-serif; }}
  header {{ padding: 10px 16px; border-bottom: 1px solid #333; }}
  h1 {{ font-size: 16px; margin: 0; font-weight: 600; }}
  .grid {{ display: flex; flex-wrap: wrap; gap: 12px; padding: 12px; }}
  figure {{ margin: 0; background: #000; border: 1px solid #333;
            border-radius: 8px; overflow: hidden; }}
  figcaption {{ padding: 6px 10px; background: #1b1b1b;
                border-top: 1px solid #333; }}
  img {{ display: block; max-width: 100%; height: auto; background: #000; }}
</style>
<header><h1>{title}</h1></header>
<div class="grid">
{cards}
</div>
"""

CARD = """  <figure>
    <img src="/stream?cam={idx}" alt="{name}" width="{w}">
    <figcaption>{name} &mdash; <code>{source}</code></figcaption>
  </figure>"""


def make_handler(cams, title, card_width):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # keep the console readable
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_page()
            elif parsed.path == "/stream":
                qs = parse_qs(parsed.query)
                try:
                    idx = int(qs.get("cam", ["-1"])[0])
                    cam = cams[idx]
                except (ValueError, IndexError):
                    self.send_error(404, "no such camera")
                    return
                self.send_stream(cam)
            elif parsed.path == "/snapshot":
                cam = cams[0]
                with cam._cond:
                    jpeg, seq, capture_ns = cam._jpeg, cam._seq, cam.capture_ns
                if jpeg is None or time.monotonic_ns() - capture_ns > 500_000_000:
                    self.send_error(503, "camera not ready")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Sequence", str(seq))
                self.send_header("X-Capture-Monotonic-Ns", str(capture_ns))
                self.end_headers()
                self.wfile.write(jpeg)
            elif parsed.path == "/api/cameras":
                body=json.dumps([{'role':c.name,'connected':c._jpeg is not None and time.monotonic_ns()-c.capture_ns<500_000_000} for c in cams]).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
            elif parsed.path == "/status":
                self.send_status()
            else:
                self.send_error(404)

        def send_page(self):
            cards = "\n".join(
                CARD.format(
                    idx=i,
                    name=html.escape(c.name),
                    source=html.escape(str(c.source)),
                    w=card_width,
                )
                for i, c in enumerate(cams)
            )
            body = PAGE.format(title=html.escape(title), cards=cards).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_status(self):
            lines = [f"{c.name}\t{c.source}\t{c.status}\tframes={c.frames}" for c in cams]
            body = ("\n".join(lines) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_stream(self, cam):
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header(
                "Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}"
            )
            self.end_headers()

            seq = 0
            try:
                while True:
                    jpeg, seq = cam.wait_frame(seq)
                    if jpeg is None:
                        continue
                    self.wfile.write(
                        f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                    )
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass  # viewer closed the tab

    return Handler


def parse_cam(spec, n):
    """`source[:name[:rotation]]` -> (source, name, rotation)"""
    parts = spec.rsplit(":", 2)
    source = parts[0]
    name = parts[1] if len(parts) > 1 and parts[1] else f"cam{n}"
    rot = int(parts[2]) if len(parts) > 2 and parts[2] else 0
    if rot not in ROTATIONS:
        raise argparse.ArgumentTypeError(f"rotation must be 0/90/180/270, got {rot}")
    return source, name, rot


def local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return ips


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--cams",
        nargs="+",
        default=["/dev/video0:front:180", "/dev/video2:wrist:90"],
        help="camera specs as source[:name[:rotation]] (default: LeKiwi front+wrist)",
    )
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--quality", type=int, default=80, help="JPEG quality 1-100")
    p.add_argument("--card-width", type=int, default=480, help="displayed width in px")
    p.add_argument("--title", default="LeKiwi cameras")
    args = p.parse_args()

    specs = [parse_cam(s, i) for i, s in enumerate(args.cams)]
    cams = [
        CameraWorker(src, name, rot, args.width, args.height, args.fps, args.quality)
        for src, name, rot in specs
    ]
    for c in cams:
        c.start()

    handler = make_handler(cams, args.title, args.card_width)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.daemon_threads = True

    print(f"Running on host: {socket.gethostname()}")
    print(f"Serving {len(cams)} camera(s) on port {args.port}:")
    for ip in local_ips():
        print(f"    http://{ip}:{args.port}")
    print("Ctrl-C to stop.", flush=True)

    # Give the workers a moment so the first status line is informative.
    time.sleep(1.5)
    for c in cams:
        print(f"    [{c.name}] {c.source}: {c.status}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        for c in cams:
            c.stop()
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
