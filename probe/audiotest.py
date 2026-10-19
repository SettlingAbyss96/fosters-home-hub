#!/usr/bin/env python3
# Pure-stdlib audio helper for the Hub 500 tests.
#   audiotest.py gen OUT.wav            loopback test signal
#   audiotest.py beep OUT.wav N         N short beeps (cue for the person)
#   audiotest.py analyze IN.wav         per-window levels + L/R comparison
import array, math, random, sys, wave

RATE = 48000


def write(path, frames):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames.tobytes())


def gen(path):
    amp = int(32767 * 10 ** (-20 / 20))
    out = array.array("h")

    def silence(sec):
        out.extend([0] * int(RATE * sec) * 2)

    def noise(sec, left=True, right=True):
        for _ in range(int(RATE * sec)):
            v = int(random.uniform(-amp, amp))
            out.append(v if left else 0)
            out.append(v if right else 0)

    def tone(sec, hz=1000):
        for i in range(int(RATE * sec)):
            v = int(amp * math.sin(2 * math.pi * hz * i / RATE))
            out.extend((v, v))

    silence(2)      # 0-2    noise floor
    noise(4)        # 2-6    both speakers
    silence(1.5)    # 6-7.5
    tone(1)         # 7.5-8.5
    silence(1.5)    # 8.5-10
    noise(1.5, right=False)  # 10-11.5 left speaker only
    silence(0.5)
    noise(1.5, left=False)   # 12-13.5 right speaker only
    silence(1.5)
    write(path, out)


def beep(path, n):
    amp = int(32767 * 10 ** (-14 / 20))
    out = array.array("h")
    for _ in range(int(n)):
        for i in range(int(RATE * 0.15)):
            v = int(amp * math.sin(2 * math.pi * 880 * i / RATE))
            out.extend((v, v))
        out.extend([0] * int(RATE * 0.15) * 2)
    write(path, out)


def db(x):
    return 20 * math.log10(x / 32768) if x > 0 else -120.0


def analyze(path):
    with wave.open(path, "rb") as w:
        ch, rate, width = w.getnchannels(), w.getframerate(), w.getsampwidth()
        data = array.array("h", w.readframes(w.getnframes()))
    print(f"channels={ch} rate={rate} width={width} seconds={len(data) / ch / rate:.2f}")
    if ch != 2:
        return
    L, R = data[0::2], data[1::2]
    win = rate // 4
    print("  t(s)   L dBFS   R dBFS")
    for s in range(0, len(L) - win + 1, win):
        l = math.sqrt(sum(v * v for v in L[s:s + win]) / win)
        r = math.sqrt(sum(v * v for v in R[s:s + win]) / win)
        print(f"{s / rate:6.2f} {db(l):8.1f} {db(r):8.1f}")
    same = sum(1 for a, b in zip(L, R) if a == b)
    n = len(L)
    ml, mr = sum(L) / n, sum(R) / n
    cov = sum((a - ml) * (b - mr) for a, b in zip(L, R))
    vl = sum((a - ml) ** 2 for a in L)
    vr = sum((b - mr) ** 2 for b in R)
    corr = cov / math.sqrt(vl * vr) if vl and vr else float("nan")
    print(f"identical L/R samples: {100 * same / n:.1f}%   L/R correlation: {corr:.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "gen":
        gen(sys.argv[2])
    elif cmd == "beep":
        beep(sys.argv[2], sys.argv[3])
    elif cmd == "analyze":
        analyze(sys.argv[2])
