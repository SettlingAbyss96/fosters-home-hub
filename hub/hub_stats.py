#!/usr/bin/env python3
"""CPU, memory, temperatures and disk for the Hub's Debian host, as Home Assistant sensors over
MQTT, on the same "Hub 500" device as hub_screen.py.

Home Assistant's own System Monitor only sees inside its VM. On this box the interesting part is
everything around it: the VM, Ollama, the kiosk and the voice satellite all sharing 4 cores and
8 GB. So besides the totals it splits CPU and memory by part. Memory per part is PSS, which
splits shared pages between the processes using them, so Chromium's dozen processes don't count
the same libraries a dozen times.

Every INTERVAL seconds it publishes one JSON state, and each sensor picks its value out of it.
"""
import json
import os
import time
from pathlib import Path

import paho.mqtt.client as mqtt

ENV_FILE = "/etc/ha-hub/mqtt.env"
BASE = "ha-hub/stats"
AVAIL = f"{BASE}/availability"
# 30 s: every 15 s wrote 37,000 states a day between the sensors, for graphs that look the
# same at half that
INTERVAL = 30
DEVICE = {"identifiers": ["ha-hub"], "name": "Hub 500", "manufacturer": "Lenovo",
          "model": "ThinkSmart Hub 500"}
TICK = os.sysconf("SC_CLK_TCK")
NCPU = os.cpu_count() or 1

# part of the box -> what its processes look like (comm, or anywhere in the command line)
PARTS = {
    "vm": ("qemu-system",),
    "ollama": ("ollama",),
    "kiosk": ("chromium", "cage"),
    "voice": ("linux_voice_assistant", "pipewire", "wireplumber"),
}

SENSORS = {
    # key: (name, unit, device_class, icon)
    "cpu": ("CPU", "%", None, "mdi:cpu-64-bit"),
    "cpu_temp": ("CPU temperature", "°C", "temperature", None),
    "load": ("Load (1 min)", None, None, "mdi:gauge"),
    "mem_used_pct": ("Memory used", "%", None, "mdi:memory"),
    "mem_used": ("Memory used (GiB)", "GiB", "data_size", "mdi:memory"),
    "mem_free": ("Memory available", "GiB", "data_size", "mdi:memory"),
    "swap_used": ("Swap used", "GiB", "data_size", "mdi:swap-horizontal"),
    "disk_used_pct": ("Disk used", "%", None, "mdi:harddisk"),
    "nvme_temp": ("SSD temperature", "°C", "temperature", None),
    "cpu_vm": ("CPU, Home Assistant VM", "%", None, "mdi:home-assistant"),
    "cpu_ollama": ("CPU, Ollama", "%", None, "mdi:brain"),
    "cpu_kiosk": ("CPU, kiosk", "%", None, "mdi:monitor-dashboard"),
    "cpu_voice": ("CPU, voice", "%", None, "mdi:microphone"),
    "mem_vm": ("Memory, Home Assistant VM", "GiB", "data_size", "mdi:home-assistant"),
    "mem_ollama": ("Memory, Ollama", "GiB", "data_size", "mdi:brain"),
    "mem_kiosk": ("Memory, kiosk", "GiB", "data_size", "mdi:monitor-dashboard"),
    "mem_voice": ("Memory, voice", "GiB", "data_size", "mdi:microphone"),
}


def log(*a):
    print(*a, flush=True)


def read(path, default=""):
    try:
        return Path(path).read_text()
    except OSError:
        return default


def total_cpu_ticks():
    fields = read("/proc/stat").split("\n", 1)[0].split()[1:]
    nums = [int(x) for x in fields]
    idle = nums[3] + nums[4]  # idle + iowait
    return sum(nums), idle


def part_of(pid):
    comm = read(f"/proc/{pid}/comm").strip()
    cmd = read(f"/proc/{pid}/cmdline").replace("\0", " ")
    for part, needles in PARTS.items():
        if any(n in comm or n in cmd for n in needles):
            return part
    return None


def per_part():
    """CPU ticks used so far, per process as {pid: (part, ticks)}, and PSS in kB summed per part.
    Kept per process so one that starts or exits between samples doesn't skew its part."""
    ticks = {}
    pss = {p: 0 for p in PARTS}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        part = part_of(d.name)
        if not part:
            continue
        stat = read(d / "stat")
        if stat:
            # fields after the ")" so a process name with spaces can't shift them
            rest = stat.rsplit(")", 1)[-1].split()
            ticks[d.name] = (part, int(rest[11]) + int(rest[12]))  # utime + stime
        for line in read(d / "smaps_rollup").splitlines():
            if line.startswith("Pss:"):
                pss[part] += int(line.split()[1])
                break
    return ticks, pss


def meminfo():
    m = {}
    for line in read("/proc/meminfo").splitlines():
        k, v = line.split(":", 1)
        m[k] = int(v.split()[0])  # kB
    return m


def hwmon_temp(name, label=None):
    for h in Path("/sys/class/hwmon").iterdir():
        if read(h / "name").strip() != name:
            continue
        for t in sorted(h.glob("temp*_input")):
            lab = read(str(t).replace("_input", "_label")).strip()
            if label is None or lab == label:
                return round(int(read(t).strip()) / 1000, 1)
    return None


def gib(kb):
    return round(kb / 1048576, 2)


class Stats:
    def __init__(self):
        env = dict(l.split("=", 1) for l in Path(ENV_FILE).read_text().split() if "=" in l)
        self.mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ha-hub-stats")
        self.mq.username_pw_set(env["MQTT_USER"], env["MQTT_PASS"])
        self.mq.will_set(AVAIL, "offline", retain=True)
        self.mq.on_connect = self._on_connect
        self.mq.on_message = self._on_message
        self.mq.reconnect_delay_set(1, 30)
        self.mq.connect_async(env["MQTT_HOST"], int(env.get("MQTT_PORT", 1883)))

    def _discovery(self):
        for key, (name, unit, dclass, icon) in SENSORS.items():
            cfg = {"name": name, "unique_id": f"ha-hub_{key}", "state_topic": f"{BASE}/state",
                   "value_template": "{{ value_json.%s }}" % key, "state_class": "measurement",
                   "availability_topic": AVAIL, "device": DEVICE, "entity_category": "diagnostic"}
            if unit:
                cfg["unit_of_measurement"] = unit
            if dclass:
                cfg["device_class"] = dclass
            if icon:
                cfg["icon"] = icon
            self.mq.publish(f"homeassistant/sensor/ha-hub/{key}/config", json.dumps(cfg), retain=True)
        self.mq.publish(AVAIL, "online", retain=True)

    def _on_connect(self, client, userdata, flags, reason, props):
        log(f"MQTT connected ({reason})")
        client.subscribe("homeassistant/status")
        self._discovery()

    def _on_message(self, client, userdata, msg):
        if msg.payload == b"online":
            self._discovery()

    def run(self):
        self.mq.loop_start()
        prev_total, prev_idle = total_cpu_ticks()
        prev_parts, _ = per_part()
        while True:
            time.sleep(INTERVAL)
            total, idle = total_cpu_ticks()
            parts, pss = per_part()
            dt = max(1, total - prev_total)
            state = {"cpu": round(100 * (dt - (idle - prev_idle)) / dt, 1)}
            # per part: share of the whole box (all 4 cores = 100 %), same scale as "cpu"
            wall_ticks = INTERVAL * TICK * NCPU
            used = {p: 0 for p in PARTS}
            for pid, (part, t) in parts.items():
                # a process that's new since the last sample spent all its ticks in this window
                used[part] += max(0, t - prev_parts.get(pid, (part, 0))[1])
            for p in PARTS:
                state[f"cpu_{p}"] = round(100 * used[p] / wall_ticks, 1)
                state[f"mem_{p}"] = gib(pss[p])
            prev_total, prev_idle, prev_parts = total, idle, parts

            m = meminfo()
            mem_used = m["MemTotal"] - m["MemAvailable"]
            state.update({
                "mem_used_pct": round(100 * mem_used / m["MemTotal"], 1),
                "mem_used": gib(mem_used),
                "mem_free": gib(m["MemAvailable"]),
                "swap_used": gib(m["SwapTotal"] - m["SwapFree"]),
                "load": round(os.getloadavg()[0], 2),
                "cpu_temp": hwmon_temp("coretemp", "Package id 0"),
                "nvme_temp": hwmon_temp("nvme"),
            })
            st = os.statvfs("/")
            state["disk_used_pct"] = round(100 * (1 - st.f_bavail / st.f_blocks), 1)
            self.mq.publish(f"{BASE}/state", json.dumps(state), retain=True)


if __name__ == "__main__":
    Stats().run()
