#!/usr/bin/env python3
"""Talk to Home Assistant from the PC, REST and WebSocket, standard library only.

  ha.py get PATH                      REST GET, e.g. /api/config
  ha.py post PATH [JSON]              REST POST
  ha.py delete PATH                   REST DELETE
  ha.py ws JSON                       one WebSocket command, e.g. '{"type": "config_entries/get"}'
  ha.py sup METHOD ENDPOINT [JSON]    Supervisor API through the WebSocket, e.g. get /supervisor/info
  ha.py expose on|off ENTITY...       show or hide entities from the voice assistant, skipping any
                                      that don't exist (a house without that device)

The leading slash on PATH and ENDPOINT is optional. Leave it off in Git Bash, which rewrites
anything starting with / into a Windows path before Python ever sees it.
JSON arguments can also be @file.json. The token comes from $HA_TOKEN or ~/.config/ha-hub/token and
never gets printed. The address is home_assistant.url in house.toml (http://homeassistant.local,
port 80 on this install, without one), HA_URL overrides it, and HA_TIMEOUT (seconds, default 600)
covers slow things like app installs.
"""
import base64
import json
import os
import socket
import ssl
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

def _house_url():
    try:
        import tomllib
        with open(os.environ.get("HOUSE", Path(__file__).resolve().parent.parent / "house.toml"), "rb") as f:
            return tomllib.load(f).get("home_assistant", {}).get("url")
    except (OSError, ValueError, ImportError):
        return None


URL = (os.environ.get("HA_URL") or _house_url() or "http://homeassistant.local").rstrip("/")
TIMEOUT = float(os.environ.get("HA_TIMEOUT", "600"))


def token():
    t = os.environ.get("HA_TOKEN")
    if not t:
        t = (Path.home() / ".config" / "ha-hub" / "token").read_text().strip()
    return t


def arg_json(s):
    if s.startswith("@"):
        with open(s[1:], encoding="utf-8") as f:
            return json.load(f)
    return json.loads(s)


def slash(p):
    return "/" + p.lstrip("/")


def rest(method, path, body=None, strict=True):
    """strict=False hands back None on an HTTP error instead of stopping (tools/setup_ha.py)"""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(URL + path, data=data, method=method, headers={
        "Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if not strict:
            return None
        sys.exit(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode(errors="replace")


class WS:
    """Just enough RFC 6455 for Home Assistant: text frames, ping/pong, close."""

    def __init__(self):
        u = urllib.parse.urlparse(URL)
        port = u.port or (443 if u.scheme == "https" else 80)
        s = socket.create_connection((u.hostname, port), timeout=TIMEOUT)
        if u.scheme == "https":
            s = ssl.create_default_context().wrap_socket(s, server_hostname=u.hostname)
        self.s, self.buf, self.n = s, b"", 0
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET /api/websocket HTTP/1.1\r\nHost: {u.hostname}:{port}\r\n"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        while b"\r\n\r\n" not in self.buf:
            self._fill()
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n")[0].decode(errors="replace")
        if " 101 " not in status:
            sys.exit(f"websocket upgrade refused: {status}")
        self.recv()  # auth_required
        self.send({"type": "auth", "access_token": token()})
        msg = self.recv()
        if msg.get("type") != "auth_ok":
            sys.exit(f"websocket auth failed: {msg.get('message', msg.get('type'))}")

    def _fill(self):
        chunk = self.s.recv(65536)
        if not chunk:
            sys.exit("connection closed")
        self.buf += chunk

    def _read(self, n):
        while len(self.buf) < n:
            self._fill()
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self, op, payload):
        n = len(payload)
        if n < 126:
            head = struct.pack("!BB", 0x80 | op, 0x80 | n)
        elif n < 65536:
            head = struct.pack("!BBH", 0x80 | op, 0x80 | 126, n)
        else:
            head = struct.pack("!BBQ", 0x80 | op, 0x80 | 127, n)
        mask = os.urandom(4)
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, obj):
        self._frame(0x1, json.dumps(obj).encode())

    def recv(self):
        data = b""
        while True:
            b1, b2 = self._read(2)
            op, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            payload = self._read(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if op == 0x8:
                sys.exit("server closed the websocket")
            if op == 0x9:
                self._frame(0xA, payload)
                continue
            if op == 0xA:
                continue
            data += payload
            if b1 & 0x80:
                return json.loads(data)

    def call(self, cmd, strict=True):
        """strict=False hands back None on an error result instead of stopping"""
        self.n += 1
        self.send(dict(cmd, id=self.n))
        while True:
            msg = self.recv()
            if msg.get("id") == self.n and msg.get("type") == "result":
                if not msg.get("success"):
                    if not strict:
                        return None
                    sys.exit(f"error: {json.dumps(msg.get('error'))}")
                return msg.get("result")


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    cmd = argv[1]
    if cmd in ("get", "post", "delete"):
        body = arg_json(argv[3]) if len(argv) > 3 else ({} if cmd == "post" else None)
        out = rest(cmd.upper(), slash(argv[2]), body)
    elif cmd == "ws":
        out = WS().call(arg_json(argv[2]))
    elif cmd == "expose" and argv[2] in ("on", "off"):
        ws = WS()
        have = {s["entity_id"] for s in ws.call({"type": "get_states"})}
        ids = [e for e in argv[3:] if e in have]
        if ids:
            ws.call({"type": "homeassistant/expose_entity", "assistants": ["conversation"],
                     "entity_ids": ids, "should_expose": argv[2] == "on"})
        out = {"exposed" if argv[2] == "on" else "hidden": len(ids), "missing": len(argv) - 3 - len(ids)}
    elif cmd == "sup" and len(argv) > 3:
        # The Supervisor's own default timeout is 10 s, too short for an install. It refuses null.
        c = {"type": "supervisor/api", "method": argv[2].lower(), "endpoint": slash(argv[3]),
             "timeout": int(TIMEOUT)}
        if len(argv) > 4:
            c["data"] = arg_json(argv[4])
        out = WS().call(c)
    else:
        sys.exit(__doc__)
    print(out if isinstance(out, str) else json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv)
