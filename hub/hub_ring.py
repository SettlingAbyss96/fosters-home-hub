#!/usr/bin/env python3
"""The Hub's LED ring as Jarvis's status light, in place of the chimes.

Listens to the voice satellite's peripheral API (Linux Voice Assistant, ws://127.0.0.1:6055) and
sets the ring to match:

  off      waiting for the wake word, which is nearly all the time
  green    listening
  white    thinking, then talking
  red      muted, or a short flash when a request fails

The ring hangs off the USB audio device (17ef:a017) and has only white, green and red. Driving it
is the method from Radeon24/lnxlink-thinksmart-hub-500: one HID feature report to wake the LED
controller up, then a few vendor register writes over ep0 per change. Nothing is written to
flash and no USB interface gets detached, so the speakers and mics carry on regardless. Each
change takes about 7 ms. Runs as root for the raw USB access.
"""
import asyncio
import fcntl
import glob
import json
import os
import threading

import usb.core
import websockets

VID, PID = 0x17EF, 0xA017
LVA = os.environ.get("LVA_PERIPHERAL", "ws://127.0.0.1:6055")
# (usage fef7, state fef8, mode feee), as the lnxlink module found them
PRESETS = {"off": (0x4F, 0x00, 0x02), "red": (0x09, 0x00, 0x02),
           "green": (0x17, 0x01, 0x02), "white": (0x3D, 0x00, 0x02)}
EVENTS = {"wake_word_detected": "green", "listening": "green",
          "thinking": "white", "tts_speaking": "white",
          "idle": "off", "disconnected": "off"}


def log(*a):
    print(*a, flush=True)


class Ring:
    def __init__(self):
        self.lock = threading.Lock()
        self.dev = None
        self.color = None

    def _find(self):
        if self.dev is None:
            self.dev = usb.core.find(idVendor=VID, idProduct=PID)
            if self.dev is None:
                raise RuntimeError("17ef:a017 not found")
            self._prime()

    def _prime(self):
        """The controller ignores vendor writes until it has seen one HID feature report."""
        for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
            try:
                uevent = open(f"{node}/device/uevent").read().upper()
            except OSError:
                continue
            iface = os.path.basename(os.path.dirname(os.path.realpath(f"{node}/device")))
            if "17EF" in uevent and "A017" in uevent and iface.endswith(".5"):
                fd = os.open(f"/dev/{os.path.basename(node)}", os.O_RDWR)
                try:
                    report = bytearray(64)
                    report[0] = 2
                    fcntl.ioctl(fd, (3 << 30) | (64 << 16) | (ord("H") << 8) | 0x06, bytes(report))
                finally:
                    os.close(fd)
                return

    def _rd(self, reg):
        return self.dev.ctrl_transfer(0xC0, 0x25, 0, reg, 1, timeout=2000)[0]

    def _wr(self, reg, value):
        self.dev.ctrl_transfer(0x40, 0x24, 0, reg, bytes([value & 0xFF]), timeout=2000)

    def set(self, color):
        with self.lock:
            if color == self.color:
                return
            try:
                self._find()
                usage, state, mode = PRESETS[color]
                self._wr(0xFE96, self._rd(0xFE96) | 0x08)
                self._wr(0xFEF7, usage)
                self._wr(0xFEF8, state)
                self._wr(0xFEF9, 0x00)
                self._wr(0xFEFA, 0x00)
                self._wr(0xFEEE, mode)
                self._wr(0xFEEF, 0x80)
                for _ in range(200):
                    if self._rd(0xFEEF) & 0x40:
                        break
                self._wr(0xFE96, self._rd(0xFE96) & ~0x08)
                self.color = color
                log(f"ring {color}")
            except Exception as e:  # noqa: BLE001 - USB re-enumerates after a replug, find it again
                log(f"ring {color} failed: {e}")
                self.dev = None
                self.color = None


async def main():
    ring = Ring()
    ring.set("off")
    muted = False
    flash = None
    while True:
        try:
            async with websockets.connect(LVA, ping_interval=20) as ws:
                log(f"connected to {LVA}")
                async for raw in ws:
                    msg = json.loads(raw)
                    event, data = msg.get("event"), msg.get("data") or {}
                    if event == "snapshot":
                        muted = bool(data.get("muted"))
                        ring.set("red" if muted else "off")
                    elif event == "muted":
                        muted = bool(data.get("muted"))
                        ring.set("red" if muted else "off")
                    elif event == "pipeline_error":
                        ring.set("red")
                        if flash:
                            flash.cancel()
                        flash = asyncio.get_running_loop().call_later(
                            1.5, lambda: ring.set("red" if muted else "off"))
                    elif event in EVENTS:
                        if flash:
                            flash.cancel()
                            flash = None
                        # Muted is red, full stop. A follow-up window that gets skipped because
                        # of the mute still says "listening" first, and left the ring green
                        ring.set("red" if muted else EVENTS[event])
        except (OSError, websockets.WebSocketException) as e:
            ring.set("off")
            log(f"satellite not reachable ({e}), retrying")
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
