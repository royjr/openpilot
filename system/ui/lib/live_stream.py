import http.server
import os
import socketserver
import struct
import threading
import time


STREAM_ENABLED = os.getenv("UI_STREAM") == "1"
STREAM_HOST = os.getenv("UI_STREAM_HOST", "0.0.0.0")
STREAM_PORT = int(os.getenv("UI_STREAM_PORT", "8765"))
STREAM_FPS = float(os.getenv("UI_STREAM_FPS", "3.0"))
STREAM_SCALE = max(0.1, min(1.0, float(os.getenv("UI_STREAM_SCALE", "0.75"))))

HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>UI Stream</title>
  <style>
    html, body {
      margin: 0;
      background: #111;
      color: #eee;
      font-family: system-ui, sans-serif;
    }
    .wrap {
      min-height: 100vh;
      display: grid;
      place-items: center;
      gap: 12px;
      padding: 16px;
      box-sizing: border-box;
    }
    img {
      width: min(100vw, calc(100vh * 0.7));
      max-width: 100vw;
      max-height: 100vh;
      object-fit: contain;
      border-radius: 0;
      background: #000;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
      transform: scaleY(-1);
    }
  </style>
</head>
<body>
  <div class="wrap">
    <img id="screen" alt="ui stream" src="/frame.bmp">
    <div id="meta">waiting for frames...</div>
  </div>
  <script>
    const img = document.getElementById("screen");
    const meta = document.getElementById("meta");
    let inFlight = false;
    function loop() {
      if (inFlight) return;
      inFlight = true;
      const next = new Image();
      next.onload = () => {
        img.src = next.src;
        meta.textContent = "connected " + new Date().toLocaleTimeString();
        inFlight = false;
        setTimeout(loop, 1000 / 3);
      };
      next.onerror = () => {
        meta.textContent = "waiting for frames...";
        inFlight = false;
        setTimeout(loop, 1000);
      };
      next.src = "/frame.bmp?t=" + Date.now();
    }
    loop();
</script>
</body>
</html>
"""


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
  daemon_threads = True


class UILiveStream:
  def __init__(self, host: str = STREAM_HOST, port: int = STREAM_PORT):
    self.host = host
    self.port = port
    self._lock = threading.Lock()
    self._frame_bytes = b""
    self._started = False
    self._min_interval = 1.0 / max(STREAM_FPS, 0.25)
    self._last_update = 0.0

  def start(self):
    if self._started:
      return
    self._started = True
    server = self

    class Handler(http.server.BaseHTTPRequestHandler):
      def do_GET(self):
        if self.path.startswith("/frame.bmp"):
          with server._lock:
            data = server._frame_bytes
          if not data:
            self.send_response(503)
            self.end_headers()
            try:
              self.wfile.write(b"waiting for first frame")
            except (BrokenPipeError, ConnectionResetError):
              pass
            return
          self.send_response(200)
          self.send_header("Content-Type", "image/bmp")
          self.send_header("Content-Length", str(len(data)))
          self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
          self.end_headers()
          try:
            self.wfile.write(data)
          except (BrokenPipeError, ConnectionResetError):
            pass
          return

        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
          self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
          pass

      def log_message(self, fmt, *args):
        return

    httpd = _ThreadingHTTPServer((self.host, self.port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    print(f"[ui-stream] serving http://{self.host}:{self.port}", flush=True)

  def update_rgba(self, width: int, height: int, rgba_bytes: bytes):
    now = time.monotonic()
    if now - self._last_update < self._min_interval:
      return
    if STREAM_SCALE < 0.999:
      width, height, rgba_bytes = _downscale_rgba(width, height, rgba_bytes, STREAM_SCALE)
    bmp = _rgba_to_bmp(width, height, rgba_bytes)
    with self._lock:
      self._frame_bytes = bmp
    self._last_update = now


def _downscale_rgba(width: int, height: int, rgba_bytes: bytes, scale: float) -> tuple[int, int, bytes]:
  target_width = max(1, int(width * scale))
  target_height = max(1, int(height * scale))
  if target_width == width and target_height == height:
    return width, height, rgba_bytes

  scaled = bytearray(target_width * target_height * 4)
  for y in range(target_height):
    src_y = min(height - 1, int(y * height / target_height))
    for x in range(target_width):
      src_x = min(width - 1, int(x * width / target_width))
      src_i = (src_y * width + src_x) * 4
      dst_i = (y * target_width + x) * 4
      scaled[dst_i:dst_i + 4] = rgba_bytes[src_i:src_i + 4]
  return target_width, target_height, bytes(scaled)


def _rgba_to_bmp(width: int, height: int, rgba_bytes: bytes) -> bytes:
  row_stride = width * 3
  row_pad = (4 - (row_stride % 4)) % 4
  pixel_data = bytearray()

  for y in range(height):
    row_start = y * width * 4
    for x in range(width):
      i = row_start + x * 4
      r = rgba_bytes[i]
      g = rgba_bytes[i + 1]
      b = rgba_bytes[i + 2]
      pixel_data.extend((b, g, r))
    if row_pad:
      pixel_data.extend(b"\x00" * row_pad)

  file_size = 14 + 40 + len(pixel_data)
  bmp = bytearray()
  bmp.extend(b"BM")
  bmp.extend(struct.pack("<I", file_size))
  bmp.extend(struct.pack("<HH", 0, 0))
  bmp.extend(struct.pack("<I", 54))
  bmp.extend(struct.pack("<I", 40))
  bmp.extend(struct.pack("<i", width))
  bmp.extend(struct.pack("<i", -height))
  bmp.extend(struct.pack("<H", 1))
  bmp.extend(struct.pack("<H", 24))
  bmp.extend(struct.pack("<I", 0))
  bmp.extend(struct.pack("<I", len(pixel_data)))
  bmp.extend(struct.pack("<i", 2835))
  bmp.extend(struct.pack("<i", 2835))
  bmp.extend(struct.pack("<I", 0))
  bmp.extend(struct.pack("<I", 0))
  bmp.extend(pixel_data)
  return bytes(bmp)
