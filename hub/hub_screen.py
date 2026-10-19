#!/usr/bin/env python3
"""Screen and presence for the ThinkSmart Hub 500, as Home Assistant entities over MQTT.

  Screen       light. On/off is DDC/CI power mode (VCP D6), brightness is VCP 10 (0 to 100)
  Brightness   number, the same VCP 10 without touching power. A light's turn_on always wakes
               it, so automations that dim the screen at night use this one
  Motion       binary_sensor from the PIR, held on for MOTION_HOLD s after the last detection
  Auto sleep   switch. Sleep after N minutes without motion or touch, wake on motion
  Sleep after  number, minutes

Touch always wakes a sleeping screen. While asleep the touchscreen is grabbed, so the tap that
wakes it doesn't also press whatever was under the finger.

This owns sleep and wake because it has to work with Home Assistant down. Brightness levels
(bright by day, dim at night) belong to Home Assistant automations.
"""
import fcntl
import json
import os
import re
import select
import signal
import struct
import subprocess
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

ENV_FILE = "/etc/ha-hub/mqtt.env"
STATE_FILE = Path("/var/lib/ha-hub/screen.json")
BASE = "ha-hub"
AVAIL = f"{BASE}/availability"
MOTION_HOLD = 30
DEVICE = {"identifiers": ["ha-hub"], "name": "Hub 500", "manufacturer": "Lenovo",
          "model": "ThinkSmart Hub 500"}
EVIOCGRAB = 0x40044590
PIR_USB = ("28e9", "028c")


def log(*a):
    print(*a, flush=True)


def run_abandonable(cmd, timeout):
    """Run cmd, give up after timeout without waiting on it. The PIR driver can leave a reader
    stuck in uninterruptible sleep, and waiting on one of those hangs the waiter too."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    deadline = time.monotonic() + timeout
    while p.poll() is None:
        if time.monotonic() > deadline:
            p.kill()
            return None, ""
        time.sleep(0.05)
    return p.returncode, p.stdout.read()


class Panel:
    """ddcutil takes 0.1 to 0.6 s a call, so one worker applies only the newest request."""

    def __init__(self):
        self.bus = self._find_bus()
        self.cv = threading.Condition()
        self.pending = {}
        rc, out = run_abandonable(["ddcutil", "--bus", self.bus, "getvcp", "10", "--terse"], 15)
        m = re.search(r"C (\d+) (\d+)", out or "")
        self.brightness = int(m.group(1)) if m else 100
        threading.Thread(target=self._worker, daemon=True).start()

    @staticmethod
    def _find_bus():
        rc, out = run_abandonable(["ddcutil", "detect", "--brief"], 60)
        m = re.search(r"/dev/i2c-(\d+)", out or "")
        if not m:
            raise SystemExit("no DDC/CI display found")
        return m.group(1)

    def set(self, **kw):
        with self.cv:
            self.pending.update(kw)
            self.cv.notify()

    def _worker(self):
        while True:
            with self.cv:
                while not self.pending:
                    self.cv.wait()
                job, self.pending = self.pending, {}
            # wake before brightness, brightness before sleep, so nothing flashes
            if job.get("power") is True:
                self._vcp("D6", 1)
            if "brightness" in job:
                self._vcp("10", job["brightness"])
            if job.get("power") is False:
                self._vcp("D6", 4)

    def _vcp(self, code, value):
        rc, _ = run_abandonable(["ddcutil", "--bus", self.bus, "setvcp", code,
                                 str(value)], 15)
        if rc != 0:
            log(f"ddcutil setvcp {code} {value} failed ({rc})")


class Pir(threading.Thread):
    def __init__(self, on_motion):
        super().__init__(daemon=True)
        self.on_motion = on_motion

    @staticmethod
    def _iio():
        for d in Path("/sys/bus/iio/devices").glob("iio:device*"):
            if (d / "name").read_text().strip() == "prox":
                return d
        return None

    @staticmethod
    def _usb_reset():
        for d in Path("/sys/bus/usb/devices").iterdir():
            try:
                ids = ((d / "idVendor").read_text().strip(), (d / "idProduct").read_text().strip())
            except OSError:
                continue
            if ids == PIR_USB:
                log("PIR stuck, resetting its USB device")
                (d / "authorized").write_text("0")
                time.sleep(1)
                (d / "authorized").write_text("1")
                time.sleep(5)
                return

    def run(self):
        while True:
            dev = self._iio()
            if dev is None:
                log("no PIR found, retrying in 30 s")
                time.sleep(30)
                continue
            # It reads a constant 0 until a sampling rate is written, and the write takes ~10 s
            rc, _ = run_abandonable(["sh", "-c", f"echo 10 > {dev}/in_proximity_sampling_frequency"], 40)
            if rc != 0:
                self._usb_reset()
                continue
            child = subprocess.Popen(
                ["sh", "-c", f"while :; do cat {dev}/in_proximity_raw; sleep 0.5; done"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            log(f"PIR reading {dev}")
            stuck = True
            while True:
                ready, _, _ = select.select([child.stdout], [], [], 60)  # first read takes ~21 s
                if not ready:
                    break
                line = child.stdout.readline()
                if not line:
                    stuck = False
                    break
                if line.strip() == "1":
                    self.on_motion()
            child.kill()
            if stuck:
                self._usb_reset()
            time.sleep(5)


class Touch(threading.Thread):
    def __init__(self, on_touch):
        super().__init__(daemon=True)
        self.on_touch = on_touch
        self.fd = None
        self.grabbed = False
        self.lock = threading.Lock()

    @staticmethod
    def _path():
        for block in Path("/proc/bus/input/devices").read_text().split("\n\n"):
            if 'Name="SYNA' in block:
                m = re.search(r"\b(event\d+)\b", block)
                if m:
                    return f"/dev/input/{m.group(1)}"
        return None

    def grab(self, on):
        with self.lock:
            if self.fd is None or self.grabbed == on:
                return
            try:
                fcntl.ioctl(self.fd, EVIOCGRAB, 1 if on else 0)
                self.grabbed = on
            except OSError as e:
                log(f"touch grab {on} failed: {e}")

    def run(self):
        while True:
            path = self._path()
            if not path:
                time.sleep(10)
                continue
            try:
                fd = os.open(path, os.O_RDONLY)
                with self.lock:
                    self.fd, self.grabbed = fd, False
                while os.read(fd, struct.calcsize("llHHi") * 64):
                    self.on_touch()
            except OSError as e:
                log(f"touch read failed: {e}")
            with self.lock:
                self.fd = None
            time.sleep(5)


class Hub:
    def __init__(self):
        env = dict(l.split("=", 1) for l in Path(ENV_FILE).read_text().split() if "=" in l)
        saved = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
        self.auto = saved.get("auto_sleep", True)
        self.sleep_after = saved.get("sleep_after", 5)
        self.panel = Panel()
        self.awake = True
        self.motion = False
        self.last_motion = 0.0
        self.last_activity = time.monotonic()
        self.last_touch = 0.0
        self.lock = threading.RLock()

        self.mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ha-hub-screen")
        self.mq.username_pw_set(env["MQTT_USER"], env["MQTT_PASS"])
        self.mq.will_set(AVAIL, "offline", retain=True)
        self.mq.on_connect = self._on_connect
        self.mq.on_message = self._on_message
        self.mq.reconnect_delay_set(1, 30)
        self.mq.connect_async(env["MQTT_HOST"], int(env.get("MQTT_PORT", 1883)))

        self.touch = Touch(self.touched)
        self.pir = Pir(self.moved)

    # --- MQTT ---
    def _discovery(self):
        common = {"availability_topic": AVAIL, "device": DEVICE}
        entities = {
            "light/screen": {"name": "Screen", "schema": "json", "brightness_scale": 100, "supported_color_modes": ["brightness"],
                             "command_topic": f"{BASE}/screen/set",
                             "state_topic": f"{BASE}/screen/state", "icon": "mdi:tablet"},
            "number/brightness": {"name": "Brightness", "min": 0, "max": 100, "step": 1,
                                  "mode": "slider", "unit_of_measurement": "%",
                                  "command_topic": f"{BASE}/brightness/set",
                                  "state_topic": f"{BASE}/brightness/state",
                                  "icon": "mdi:brightness-6"},
            "binary_sensor/motion": {"name": "Motion", "device_class": "motion",
                                     "state_topic": f"{BASE}/motion/state"},
            "switch/auto_sleep": {"name": "Auto sleep", "entity_category": "config",
                                  "command_topic": f"{BASE}/auto_sleep/set",
                                  "state_topic": f"{BASE}/auto_sleep/state", "icon": "mdi:sleep"},
            "number/sleep_after": {"name": "Sleep after", "entity_category": "config",
                                   "min": 1, "max": 120, "step": 1, "mode": "box",
                                   "unit_of_measurement": "min",
                                   "command_topic": f"{BASE}/sleep_after/set",
                                   "state_topic": f"{BASE}/sleep_after/state",
                                   "icon": "mdi:timer-outline"},
        }
        for key, cfg in entities.items():
            comp, obj = key.split("/")
            cfg.update(common, unique_id=f"ha-hub_{obj}")
            self.mq.publish(f"homeassistant/{comp}/ha-hub/{obj}/config", json.dumps(cfg), retain=True)

    def _publish_all(self):
        self.mq.publish(AVAIL, "online", retain=True)
        self._pub_screen()
        self.mq.publish(f"{BASE}/motion/state", "ON" if self.motion else "OFF", retain=True)
        self.mq.publish(f"{BASE}/auto_sleep/state", "ON" if self.auto else "OFF", retain=True)
        self.mq.publish(f"{BASE}/sleep_after/state", str(self.sleep_after), retain=True)

    def _pub_screen(self):
        self.mq.publish(f"{BASE}/screen/state", json.dumps(
            {"state": "ON" if self.awake else "OFF", "brightness": self.panel.brightness}), retain=True)
        self.mq.publish(f"{BASE}/brightness/state", str(self.panel.brightness), retain=True)

    def _on_connect(self, client, userdata, flags, reason, props):
        log(f"MQTT connected ({reason})")
        client.subscribe([(f"{BASE}/+/set", 0), ("homeassistant/status", 0)])
        self._discovery()
        self._publish_all()

    def _on_message(self, client, userdata, msg):
        try:
            self._handle(msg.topic, msg.payload.decode(errors="replace").strip())
        except (ValueError, TypeError) as e:
            log(f"bad message on {msg.topic}: {e}")

    def _handle(self, topic, payload):
        with self.lock:
            if topic == "homeassistant/status" and payload == "online":
                self._discovery()
                self._publish_all()
            elif topic == f"{BASE}/screen/set":
                cmd = json.loads(payload)
                if "brightness" in cmd:
                    self.panel.brightness = max(0, min(100, int(cmd["brightness"])))
                    self.panel.set(brightness=self.panel.brightness)
                if cmd.get("state") == "OFF":
                    self.sleep()
                elif cmd.get("state") == "ON":
                    self.last_activity = time.monotonic()
                    self.wake()
                self._pub_screen()
            elif topic == f"{BASE}/brightness/set":
                self.panel.brightness = max(0, min(100, int(float(payload))))
                self.panel.set(brightness=self.panel.brightness)
                self._pub_screen()
            elif topic == f"{BASE}/auto_sleep/set":
                self.auto = payload == "ON"
                self.last_activity = time.monotonic()
                self._save()
                self.mq.publish(f"{BASE}/auto_sleep/state", payload, retain=True)
            elif topic == f"{BASE}/sleep_after/set":
                self.sleep_after = max(1, min(120, int(float(payload))))
                self._save()
                self.mq.publish(f"{BASE}/sleep_after/state", str(self.sleep_after), retain=True)

    def _save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"auto_sleep": self.auto, "sleep_after": self.sleep_after}))

    # --- behavior ---
    def wake(self):
        with self.lock:
            if not self.awake:
                self.awake = True
                self.panel.set(power=True)
                self._pub_screen()

    def sleep(self):
        with self.lock:
            if self.awake:
                self.awake = False
                self.panel.set(power=False)
                self.touch.grab(True)
                self._pub_screen()

    def touched(self):
        with self.lock:
            now = time.monotonic()
            self.last_touch = self.last_activity = now
            self.wake()

    def moved(self):
        with self.lock:
            now = time.monotonic()
            self.last_motion = self.last_activity = now
            if not self.motion:
                self.motion = True
                self.mq.publish(f"{BASE}/motion/state", "ON", retain=True)
            if self.auto:
                self.wake()

    def tick(self):
        with self.lock:
            now = time.monotonic()
            if self.motion and now - self.last_motion > MOTION_HOLD:
                self.motion = False
                self.mq.publish(f"{BASE}/motion/state", "OFF", retain=True)
            if self.auto and self.awake and now - self.last_activity > self.sleep_after * 60:
                self.sleep()
            # let go of the touchscreen once the waking finger has lifted
            if self.awake and self.touch.grabbed and now - self.last_touch > 0.4:
                self.touch.grab(False)

    def run(self):
        self.panel.set(power=True)
        self.touch.start()
        self.pir.start()
        self.mq.loop_start()
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *a: stop.set())
        signal.signal(signal.SIGINT, lambda *a: stop.set())
        while not stop.wait(0.25):
            self.tick()
        # never leave the screen dark and the touchscreen grabbed on the way out
        self.touch.grab(False)
        run_abandonable(["ddcutil", "--bus", self.panel.bus, "setvcp", "D6", "1"], 15)
        try:
            self.mq.publish(AVAIL, "offline", retain=True).wait_for_publish(3)
        except (RuntimeError, ValueError):
            pass
        self.mq.loop_stop()


if __name__ == "__main__":
    Hub().run()
