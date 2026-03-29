#!/usr/bin/env python3
import argparse
import base64
import hashlib
import http.server
import socket
import subprocess
import threading
import time


HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>c4 ui stream</title>
  <style>
    html, body {
      margin: 0;
      background: #111;
      color: #eee;
      font-family: system-ui, sans-serif;
    }
    .wrap {
      display: grid;
      place-items: center;
      min-height: 100vh;
      gap: 12px;
      padding: 16px;
      box-sizing: border-box;
    }
    img {
      max-width: min(96vw, 1200px);
      max-height: 88vh;
      border-radius: 12px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.45);
      background: #000;
    }
    .meta {
      font-size: 14px;
      opacity: 0.8;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <img id="screen" alt="c4 ui stream" />
    <div class="meta" id="meta">connecting...</div>
  </div>
  <script>
    const img = document.getElementById("screen");
    const meta = document.getElementById("meta");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.hostname}:${location.port.replace("8765", "8766")}`);
    ws.onopen = () => { meta.textContent = "connected"; };
    ws.onclose = () => { meta.textContent = "disconnected"; };
    ws.onerror = () => { meta.textContent = "websocket error"; };
    ws.onmessage = (ev) => {
      img.src = `data:image/png;base64,${ev.data}`;
      meta.textContent = `updated ${new Date().toLocaleTimeString()}`;
    };
  </script>
</body>
</html>
"""


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class PageHandler(http.server.BaseHTTPRequestHandler):
  def do_GET(self):
    body = HTML.encode("utf-8")
    self.send_response(200)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def log_message(self, fmt, *args):
    return


class WebSocketBroadcaster:
  def __init__(self, host: str, port: int):
    self.host = host
    self.port = port
    self._clients: list[socket.socket] = []
    self._lock = threading.Lock()

  def start(self):
    thread = threading.Thread(target=self._serve, daemon=True)
    thread.start()

  def broadcast_text(self, payload: str):
    frame = self._encode_frame(payload.encode("utf-8"))
    dead = []
    with self._lock:
      for client in self._clients:
        try:
          client.sendall(frame)
        except OSError:
          dead.append(client)
      for client in dead:
        self._clients.remove(client)
        try:
          client.close()
        except OSError:
          pass

  def _serve(self):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((self.host, self.port))
    server.listen()
    print(f"[c4-ui-ws] websocket listening on ws://{self.host}:{self.port}", flush=True)
    while True:
      conn, _addr = server.accept()
      thread = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
      thread.start()

  def _handle_client(self, conn: socket.socket):
    try:
      request = conn.recv(4096).decode("utf-8", errors="ignore")
      key = None
      for line in request.split("\r\n"):
        if line.lower().startswith("sec-websocket-key:"):
          key = line.split(":", 1)[1].strip()
          break
      if not key:
        conn.close()
        return
      accept = base64.b64encode(hashlib.sha1((key + GUID).encode("utf-8")).digest()).decode("utf-8")
      response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
      )
      conn.sendall(response.encode("utf-8"))
      with self._lock:
        self._clients.append(conn)
      while True:
        data = conn.recv(1024)
        if not data:
          break
    except OSError:
      pass
    finally:
      with self._lock:
        if conn in self._clients:
          self._clients.remove(conn)
      try:
        conn.close()
      except OSError:
        pass

  def _encode_frame(self, payload: bytes) -> bytes:
    length = len(payload)
    if length < 126:
      header = bytes([0x81, length])
    elif length < 65536:
      header = bytes([0x81, 126]) + length.to_bytes(2, "big")
    else:
      header = bytes([0x81, 127]) + length.to_bytes(8, "big")
    return header + payload


def adb_screencap(serial: str | None) -> bytes:
  cmd = ["adb"]
  if serial:
    cmd += ["-s", serial]
  cmd += ["exec-out", "screencap", "-p"]
  return subprocess.check_output(cmd)


def ssh_screencap(target: str, port: int, remote_cmd: str) -> bytes:
  cmd = [
    "ssh",
    "-p",
    str(port),
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=5",
    target,
    remote_cmd,
  ]
  return subprocess.check_output(cmd)


def main():
  parser = argparse.ArgumentParser(description="Stream c4 UI to a browser over websockets")
  parser.add_argument("--host", default="0.0.0.0")
  parser.add_argument("--http-port", type=int, default=8765)
  parser.add_argument("--ws-port", type=int, default=8766)
  parser.add_argument("--fps", type=float, default=5.0)
  parser.add_argument("--serial", default=None, help="adb serial if multiple devices are connected")
  parser.add_argument("--ssh", default=None, help="ssh target like comma@192.168.63.208")
  parser.add_argument("--ssh-port", type=int, default=22)
  parser.add_argument("--ssh-cmd", default="screencap -p", help="remote screenshot command")
  args = parser.parse_args()

  ws = WebSocketBroadcaster(args.host, args.ws_port)
  ws.start()

  httpd = http.server.ThreadingHTTPServer((args.host, args.http_port), PageHandler)
  http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
  http_thread.start()
  print(f"[c4-ui-ws] page listening on http://{args.host}:{args.http_port}", flush=True)
  if args.ssh:
    print(f"[c4-ui-ws] capture mode: ssh {args.ssh}:{args.ssh_port} cmd={args.ssh_cmd!r}", flush=True)
  else:
    print(f"[c4-ui-ws] capture mode: adb serial={args.serial or 'default'}", flush=True)

  period = 1.0 / max(args.fps, 0.5)
  while True:
    started = time.monotonic()
    try:
      if args.ssh:
        frame = ssh_screencap(args.ssh, args.ssh_port, args.ssh_cmd)
      else:
        frame = adb_screencap(args.serial)
      ws.broadcast_text(base64.b64encode(frame).decode("ascii"))
    except subprocess.CalledProcessError as err:
      mode = "ssh" if args.ssh else "adb"
      print(f"[c4-ui-ws] {mode} screencap failed: {err}", flush=True)
    except FileNotFoundError:
      tool = "ssh" if args.ssh else "adb"
      print(f"[c4-ui-ws] {tool} not found in PATH", flush=True)
      break
    elapsed = time.monotonic() - started
    time.sleep(max(0.0, period - elapsed))


if __name__ == "__main__":
  main()
