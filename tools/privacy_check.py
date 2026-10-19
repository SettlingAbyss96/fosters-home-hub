#!/usr/bin/env python3
"""Look for your house in your repo before you push it anywhere. Standard library only.

  python tools/privacy_check.py            this repo
  python tools/privacy_check.py PATH       another checkout

Reads the files git would commit (tracked plus untracked-but-not-ignored) and reports:
  problem   house.toml, about.local.md or parakeet-words.local.txt being committed at all; any value
            from your house.toml (your Wi-Fi's name, addresses, entity ids, the calendar address)
            turning up in a committed file; anything that looks like a token or a private key
  check     private network addresses, MAC addresses and email addresses: often fine (a comment
            about a router's usual address), sometimes yours
Exit status 1 when there's a problem. It can't know everything that's private to you, people's names
in about.md say, so it's a net, not a guarantee.
"""
import ipaddress
import pathlib
import re
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent)
NEVER = ("house.toml", "ha/context/about.local.md", "hub/parakeet-words.local.txt")
SKIP_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".bin", ".onnx", ".zip", ".gz")
# values in house.example.toml are examples, not anyone's house
EXAMPLE_FILE = ROOT / "house.example.toml"

TOKEN = re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"                          # a JWT, like a Home Assistant token
                   r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
                   r"|(?i:(?:api[_-]?key|secret|token|password|passwd)\s*[:=]\s*[\"'][^\"'\s$<{]{16,}[\"'])")
MAC = re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
SAFE_IPS = {"0.0.0.0", "127.0.0.1"}


def files():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        sys.exit(f"{ROOT} isn't a git checkout")
    return [l for l in out.stdout.splitlines() if l]


def strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)
    elif isinstance(obj, str):
        yield obj


def house_values():
    p = ROOT / "house.toml"
    if not p.is_file():
        return set()
    examples = set()
    if EXAMPLE_FILE.is_file():
        with open(EXAMPLE_FILE, "rb") as f:
            examples = set(strings(tomllib.load(f)))
    with open(p, "rb") as f:
        mine = set(strings(tomllib.load(f)))
    # short or generic values (a layer, a role, "Living Room") would match all over the repo
    common = {"ambient", "task", "accent", "sunrise", "bedside", "no_dim", "stand_in", "keep", "mushroom", "hey_jarvis"}
    return {v for v in mine - examples if len(v) >= 6 and v.lower() not in common}


def private_ip(text):
    for m in IPV4.finditer(text):
        try:
            ip = ipaddress.ip_address(m.group(0))
        except ValueError:
            continue
        if m.group(0) in SAFE_IPS or ip in ipaddress.ip_network("192.0.2.0/24"):
            continue
        if ip.is_private:
            yield m.group(0)


def main():
    problems, checks = [], []
    tracked = files()
    for name in NEVER:
        if name in tracked:
            problems.append(f"{name} would be committed: it's yours, git rm --cached it")
    mine = house_values()
    for rel in tracked:
        if rel.endswith(SKIP_SUFFIX) or rel in NEVER or rel == "house.example.toml":
            continue
        p = ROOT / rel
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for v in mine:
                if v in line:
                    problems.append(f"{rel}:{n}: has {v!r} from your house.toml")
            if TOKEN.search(line):
                problems.append(f"{rel}:{n}: looks like a token or a key")
            for ip in private_ip(line):
                checks.append(f"{rel}:{n}: a private address, {ip}")
            for mac in MAC.findall(line):
                checks.append(f"{rel}:{n}: a MAC address, {mac}")
            for mail in EMAIL.findall(line):
                if not mail.endswith(("users.noreply.github.com", ".local", ".service")) and "@ha-hub" not in mail:
                    checks.append(f"{rel}:{n}: an email address, {mail}")
    for line in problems:
        print("problem:", line)
    for line in checks:
        print("check:  ", line)
    print(f"{len(tracked)} files, {len(problems)} problems, {len(checks)} to check")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
