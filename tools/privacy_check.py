#!/usr/bin/env python3
"""Look for your house in this repo before any of it goes anywhere. Standard library only.

  privacy_check.py                 the files git would commit now (tracked plus untracked-but-not-ignored)
  privacy_check.py --staged        what's about to be committed (the pre-commit hook)
  privacy_check.py --message FILE  a commit message (the commit-msg hook)
  privacy_check.py --push          every commit about to be pushed, read from git's pre-push input
  privacy_check.py --history       every commit there is, for a look at what's already out
  privacy_check.py --install       put the three hooks in this clone (local, never committed)

What's yours comes from the house folder (tools/house.py), never from this repo, so the list of
things to stop on is never itself something to leak:
  - every value in house.toml longer than a few letters that isn't one of house.example.toml's:
    your Wi-Fi's name, your addresses, your entity ids, the calendar address
  - private-words.txt, one thing a line, matched without caring about case: people's names,
    the street, the building, where you work, a serial number. A line starting with ! is the
    opposite, a word that's fine in public even though it's in house.toml (a vacuum's brand, say)
  - house.toml and your other files themselves being committed at all
Then, whoever's house it is: anything shaped like a token or a private key, private network
addresses, MAC addresses and email addresses. In the hooks those stop the commit too, because a
real one in a public repo is never fine; the plain scan only lists them, since a README can
mention a router's usual address.

A commit is checked line by line as it was written, and a push commit by commit, message and
author included, because something added and taken out again two commits later is still in the
history for anyone to read. Exit status 1 when there's a problem. It's a net, not a guarantee: it
can't know a story about your week is private. Read your diff.
"""
import ipaddress
import pathlib
import re
import subprocess
import sys
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import house as housefile  # noqa: E402

ROOT = HERE.parent
SKIP_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".bin", ".onnx", ".zip", ".gz", ".apk", ".jks")
# short or generic values in a house.toml would match all over the repo
COMMON = {"ambient", "task", "accent", "sunrise", "bedside", "no_dim", "stand_in", "keep", "mushroom", "hey_jarvis",
          "bm_daniel", "en_GB", "Living Room", "Kitchen", "Bedroom", "Bathroom"}

TOKEN = re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"                          # a JWT, like a Home Assistant token
                   r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
                   r"|(?i:(?:api[_-]?key|secret|token|password|passwd)\s*[:=]\s*[\"'][^\"'\s$<{]{16,}[\"'])")
MAC = re.compile(r"\b[0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5}\b")
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
SAFE_MAIL = ("users.noreply.github.com", "example.com", "example.org", "example.net", ".local", ".service")
# a latitude and longitude written out, which is where someone lives or works
COORDS = re.compile(r"(?<![\d.])-?[1-8]?[1-9]\.\d{4,},\s*-?(?:1[0-7]\d|[1-9]\d?)\.\d{4,}(?![\d.])")


def git(*args, check=False):
    out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and out.returncode != 0:
        sys.exit(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout


def strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)
    elif isinstance(obj, str):
        yield obj


def yours():
    """(things to stop on, things that are fine, the files that are yours as repo paths). Read from
    the house folder. A clone whose git config names a house folder that isn't there stops here
    (tools/house.py says so), rather than checking against nothing"""
    home = housefile.home()
    stop, fine = set(), set()
    house = home / "house.toml"
    if house.is_file():
        examples = set()
        example = ROOT / "house.example.toml"
        if example.is_file():
            with open(example, "rb") as f:
                examples = set(strings(tomllib.load(f)))
        with open(house, "rb") as f:
            mine = set(strings(tomllib.load(f)))
        # entity ids are left to private-words.txt: once a house is on the standard names they're
        # this repo's own words (person.resident), and the ones that give a house away are its old ones
        stop |= {v for v in mine - examples - COMMON if len(v) >= 6 and not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", v)}
    words = housefile.file("private_words")
    if words.is_file():
        for line in words.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            (fine if line.startswith("!") else stop).add(line.lstrip("!").strip())
    stop = {s for s in stop if s.lower() not in {f.lower() for f in fine}}
    # a MAC address matches however it's written
    stop |= {re.sub(r"[:-]", "", s) for s in stop if MAC.fullmatch(s)}
    files = {"house.toml", "private-words.txt"} | {v for k, v in housefile.LOCAL.items() if k != "config"}
    return stop, files


class Report:
    def __init__(self):
        self.problems, self.checks = [], []
        self.stop, self.files = yours()
        self.low = [(s, s.lower()) for s in self.stop]

    def line(self, where, text, strict):
        low = text.lower()
        for s, sl in self.low:
            if sl in low:
                self.problems.append(f"{where}: has {s!r}, which is yours")
        if TOKEN.search(text):
            self.problems.append(f"{where}: looks like a token or a key")
        found = self.problems if strict else self.checks
        for m in IPV4.finditer(text):
            try:
                ip = ipaddress.ip_address(m.group(0))
            except ValueError:
                continue
            if ip.is_private and not (ip in ipaddress.ip_network("192.0.2.0/24") or ip in ipaddress.ip_network("0.0.0.0/8")
                                      or ip.is_loopback):
                found.append(f"{where}: a private address, {m.group(0)}")
        for mac in MAC.findall(text):
            found.append(f"{where}: a MAC address, {mac}")
        for mail in EMAIL.findall(text):
            if not mail.lower().endswith(SAFE_MAIL) and "@ha-hub" not in mail:
                found.append(f"{where}: an email address, {mail}")
        for c in COORDS.findall(text):
            found.append(f"{where}: a latitude and longitude, {c}")

    def path(self, where, rel):
        rel = rel.replace("\\", "/")
        if rel in self.files or rel.split("/")[-1] in ("house.toml", "private-words.txt"):
            self.problems.append(f"{where}: {rel} is yours and would be in the repo")
        self.line(where, rel, True)

    def diff(self, where, text):
        """A diff (git show / git diff -U0): the paths it touches and the lines it adds"""
        for l in text.splitlines():
            if l.startswith("+++ b/"):
                self.path(where, l[6:])
                current = l[6:]
            elif l.startswith("+") and not l.startswith("+++"):
                if not current.endswith(SKIP_SUFFIX):
                    self.line(f"{where} {current}", l[1:], True)
            elif l.startswith("diff --git"):
                current = l.split(" b/", 1)[-1]

    def done(self):
        for line in self.problems:
            print("problem:", line)
        for line in self.checks:
            print("check:  ", line)
        sys.stdout.flush()
        if self.problems:
            print("Nothing went anywhere. If one of those really is fine in public, private-words.txt in the house "
                  "folder takes a line starting with ! for it", file=sys.stderr)
        return 1 if self.problems else 0


def commit(r, sha):
    who = git("show", "-s", "--format=%an <%ae>%n%cn <%ce>", sha)
    r.line(f"{sha[:7]} author", who, True)
    r.line(f"{sha[:7]} message", git("show", "-s", "--format=%B", sha), True)
    r.diff(sha[:7], git("show", "--format=", "-U0", "--no-color", "--no-ext-diff", sha))


def main():
    args = sys.argv[1:]
    if "--install" in args:
        return install()
    r = Report()
    if "--staged" in args:
        r.diff("staged", git("diff", "--cached", "-U0", "--no-color", "--no-ext-diff", check=True))
    elif "--message" in args:
        p = pathlib.Path(args[args.index("--message") + 1])
        r.line("commit message", "\n".join(l for l in p.read_text(encoding="utf-8").splitlines() if not l.startswith("#")), True)
    elif "--push" in args:
        for line in sys.stdin.read().splitlines():
            parts = line.split()
            if len(parts) != 4 or set(parts[1]) == {"0"}:
                continue
            local, remote = parts[1], parts[3]
            span = [local, "--not", "--remotes"] if set(remote) == {"0"} else [f"{remote}..{local}"]
            for sha in git("rev-list", *span).split():
                commit(r, sha)
    elif "--history" in args:
        shas = git("rev-list", "--all").split()
        for sha in shas:
            commit(r, sha)
        print(f"{len(shas)} commits")
    else:
        tracked = [l for l in git("ls-files", "--cached", "--others", "--exclude-standard", check=True).splitlines() if l]
        for rel in tracked:
            r.path(rel, rel)
            p = ROOT / rel
            if rel.endswith(SKIP_SUFFIX) or not p.is_file() or p.stat().st_size > 2_000_000 or rel == "house.example.toml":
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                r.line(f"{rel}:{n}", line, False)
        print(f"{len(tracked)} files, {len(r.problems)} problems, {len(r.checks)} to check")
    return r.done()


HOOK = """#!/bin/sh
# tools/privacy_check.py (local, put here by privacy_check.py --install)
PY=$(command -v python || command -v python3)
[ -n "$PY" ] || { echo "privacy check: no python, so nothing gets past" >&2; exit 1; }
exec "$PY" "$(git rev-parse --show-toplevel)/tools/privacy_check.py" {args}
"""


def install():
    """Each hook goes in as the hook itself, unless something else already has that name (a style
    guard, say): then it goes in <hook>.d/ next to it, which a hook that runs its folder picks up"""
    hooks = pathlib.Path(git("rev-parse", "--git-path", "hooks", check=True).strip())
    hooks = hooks if hooks.is_absolute() else ROOT / hooks
    hooks.mkdir(parents=True, exist_ok=True)
    mark = "privacy_check.py --install"
    for name, args in (("pre-commit", "--staged"), ("commit-msg", '--message "$1"'), ("pre-push", "--push")):
        main_hook = hooks / name
        theirs = main_hook.exists() and mark not in main_hook.read_text(encoding="utf-8", errors="replace")
        path = hooks / f"{name}.d" / "privacy" if theirs else main_hook
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(HOOK.replace("{args}", args), encoding="utf-8", newline="\n")
        path.chmod(0o755)
        print(f"installed {name}" + (f" in {path.parent.name}/" if theirs else ""))
        if theirs and f"{name}.d" not in main_hook.read_text(encoding="utf-8", errors="replace"):
            print(f"  note: {main_hook} is someone else's and doesn't run {name}.d/, so this one won't run until it does")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
