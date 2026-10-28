"""Draw the figures in docs/ as plain SVG files.

Standard library only, so anyone can rerun it:

    python docs/figures/make_figures.py

The measured ones read data.json (what the voice benches and the turn replays printed, the
recordings themselves stay out of the repo). The rest are simulations that use the house's own
numbers: the asleep filter and the PID block with the settings in param() in
ha/config/custom_templates/control.jinja, worked the way the control core in
ha/config/custom_components/house_control does it (copied rather than imported, so this stays standard
library only), the sunrise with the curve in wake.yaml.
"""

import json
import math
import os
import random
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
# categorical slots, in order (checked for colour-blind separation on white), then ink and grid
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
VIOLET = "#4a3aa7"
RED = "#e34948"
GRAY = "#8a8984"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e7e6e2"

with open(os.path.join(HERE, "data.json"), encoding="utf-8") as f:
    DATA = json.load(f)


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt(v):
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:g}"


class Plot:
    """One chart on a white card: axes, lines, points, bands, labels."""

    def __init__(self, title, xlabel, ylabel, xlim, ylim, xlog=False, subtitle=None,
                 w=760, h=430, ml=78, mr=28, mt=62, mb=64, title_x=None):
        self.title, self.subtitle = title, subtitle
        self.title_x = ml if title_x is None else title_x
        self.xlabel, self.ylabel = xlabel, ylabel
        self.xlim, self.ylim, self.xlog = xlim, ylim, xlog
        self.w, self.h, self.ml, self.mr, self.mt, self.mb = w, h, ml, mr, mt, mb
        self.back, self.items, self.legend_items = [], [], []

    def _t(self, v, lim, log):
        if log:
            return (math.log10(v) - math.log10(lim[0])) / (math.log10(lim[1]) - math.log10(lim[0]))
        return (v - lim[0]) / (lim[1] - lim[0])

    def X(self, x):
        return self.ml + self._t(x, self.xlim, self.xlog) * (self.w - self.ml - self.mr)

    def Y(self, y):
        return self.h - self.mb - self._t(y, self.ylim, False) * (self.h - self.mt - self.mb)

    def axes(self, xticks, yticks, xlabels=None, ylabels=None):
        x0, x1, y0, y1 = self.ml, self.w - self.mr, self.mt, self.h - self.mb
        for i, t in enumerate(xticks):
            x = self.X(t)
            self.back.append(f'<line x1="{x:.1f}" y1="{y0}" x2="{x:.1f}" y2="{y1}" stroke="{GRID}"/>')
            lab = xlabels[i] if xlabels else fmt(t)
            self.back.append(f'<text x="{x:.1f}" y="{y1 + 20}" font-size="13" text-anchor="middle" fill="{INK2}">{esc(lab)}</text>')
        for i, t in enumerate(yticks):
            y = self.Y(t)
            self.back.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{GRID}"/>')
            lab = ylabels[i] if ylabels else fmt(t)
            self.back.append(f'<text x="{x0 - 8}" y="{y + 4:.1f}" font-size="13" text-anchor="end" fill="{INK2}">{esc(lab)}</text>')
        self.back.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{INK}" stroke-width="1"/>')
        self.back.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="{INK}" stroke-width="1"/>')

    def band_x(self, a, b, color, label=None, opacity=0.12, label_y=None):
        x0, x1 = self.X(a), self.X(b)
        self.back.append(f'<rect x="{x0:.1f}" y="{self.mt}" width="{x1 - x0:.1f}" height="{self.h - self.mt - self.mb}" fill="{color}" opacity="{opacity}"/>')
        if label:
            ly = self.Y(label_y) if label_y is not None else self.mt + 16
            self.back.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{ly:.1f}" font-size="12.5" text-anchor="middle" fill="{INK2}">{esc(label)}</text>')

    def band_y(self, a, b, color, label=None, opacity=0.12, label_x=None):
        y0, y1 = self.Y(b), self.Y(a)
        self.back.append(f'<rect x="{self.ml}" y="{y0:.1f}" width="{self.w - self.ml - self.mr}" height="{y1 - y0:.1f}" fill="{color}" opacity="{opacity}"/>')
        if label:
            lx = self.X(label_x) if label_x is not None else self.w - self.mr - 6
            anchor = "middle" if label_x is not None else "end"
            self.back.append(f'<text x="{lx:.1f}" y="{(y0 + y1) / 2 + 4:.1f}" font-size="12.5" text-anchor="{anchor}" fill="{INK2}">{esc(label)}</text>')

    def hline(self, y, color, label=None, dash="6 4", label_x=None, anchor="end"):
        yy = self.Y(y)
        self.items.append(f'<line x1="{self.ml}" y1="{yy:.1f}" x2="{self.w - self.mr}" y2="{yy:.1f}" stroke="{color}" stroke-width="1.5" stroke-dasharray="{dash}"/>')
        if label:
            lx = self.X(label_x) if label_x is not None else self.w - self.mr - 6
            self.items.append(f'<text x="{lx:.1f}" y="{yy - 6:.1f}" font-size="12.5" text-anchor="{anchor}" fill="{INK2}">{esc(label)}</text>')

    def vline(self, x, color, label=None, dash="4 4", label_y=None, anchor="start"):
        xx = self.X(x)
        self.items.append(f'<line x1="{xx:.1f}" y1="{self.mt}" x2="{xx:.1f}" y2="{self.h - self.mb}" stroke="{color}" stroke-width="1.4" stroke-dasharray="{dash}"/>')
        if label:
            ly = self.Y(label_y) if label_y is not None else self.mt + 16
            dx = 5 if anchor == "start" else -5
            self.items.append(f'<text x="{xx + dx:.1f}" y="{ly:.1f}" font-size="12.5" text-anchor="{anchor}" fill="{INK2}">{esc(label)}</text>')

    def line(self, pts, color, label=None, width=2, dash=None, step=False):
        pts = [(x, y) for x, y in pts if self.xlim[0] <= x <= self.xlim[1]]
        if step:
            stepped = []
            for i, (x, y) in enumerate(pts):
                if i:
                    stepped.append((x, pts[i - 1][1]))
                stepped.append((x, y))
            pts = stepped
        d = " ".join(f"{'M' if i == 0 else 'L'}{self.X(x):.1f},{self.Y(min(max(y, self.ylim[0]), self.ylim[1])):.1f}"
                     for i, (x, y) in enumerate(pts))
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"{da}/>')
        if label:
            self.legend_items.append((label, color, dash, "line"))

    def rect(self, x0, x1, y0, y1, color, opacity=1.0, rx=3):
        X0, X1 = sorted((self.X(x0), self.X(x1)))
        Y0, Y1 = sorted((self.Y(y0), self.Y(y1)))
        self.items.append(f'<rect x="{X0:.1f}" y="{Y0:.1f}" width="{X1 - X0:.1f}" height="{Y1 - Y0:.1f}" rx="{rx}" fill="{color}" fill-opacity="{opacity}" stroke="white" stroke-width="2"/>')

    def point(self, x, y, color, r=4.5, label=None):
        if not (self.xlim[0] <= x <= self.xlim[1]):
            return
        self.items.append(f'<circle cx="{self.X(x):.1f}" cy="{self.Y(y):.1f}" r="{r}" fill="{color}" stroke="white" stroke-width="1.5"/>')
        if label and not any(l == label for l, *_ in self.legend_items):
            self.legend_items.append((label, color, None, "dot"))

    def raw_point(self, px, py, color, r=4.0, opacity=0.85):
        self.items.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{r}" fill="{color}" fill-opacity="{opacity}" stroke="white" stroke-width="1"/>')

    def text(self, x, y, s, color=INK, size=12.5, anchor="start", dx=0, dy=0, weight="normal"):
        self.items.append(f'<text x="{self.X(x) + dx:.1f}" y="{self.Y(y) + dy:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{color}" font-weight="{weight}">{esc(s)}</text>')

    def legend(self, pos="tr", at=None):
        """pos is a corner (tl, tr, bl, br), or at=(x, y) puts its top-left corner there, in data units"""
        if not self.legend_items:
            return
        n = len(self.legend_items)
        bw = max(len(l) for l, *_ in self.legend_items) * 6.9 + 50
        bh = n * 20 + 12
        x = self.w - self.mr - bw - 10 if pos.endswith("r") else self.ml + 10
        y = self.mt + 10 if pos.startswith("t") else self.h - self.mb - bh - 10
        if at:
            x, y = self.X(at[0]), self.Y(at[1])
        self.items.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh}" rx="6" fill="white" fill-opacity="0.94" stroke="{GRID}"/>')
        for i, (lab, col, dash, kind) in enumerate(self.legend_items):
            yy = y + 18 + i * 20
            if kind == "dot":
                self.items.append(f'<circle cx="{x + 22:.1f}" cy="{yy - 4:.1f}" r="5" fill="{col}"/>')
            else:
                da = f' stroke-dasharray="{dash}"' if dash else ""
                self.items.append(f'<line x1="{x + 10:.1f}" y1="{yy - 4:.1f}" x2="{x + 34:.1f}" y2="{yy - 4:.1f}" stroke="{col}" stroke-width="3"{da}/>')
            self.items.append(f'<text x="{x + 42:.1f}" y="{yy:.1f}" font-size="12.5" fill="{INK}">{esc(lab)}</text>')

    def body(self):
        out = [f'<rect x="0.5" y="0.5" width="{self.w - 1}" height="{self.h - 1}" rx="10" fill="white" stroke="{GRID}"/>',
               f'<text x="{self.title_x}" y="28" font-size="16" font-weight="600" fill="{INK}">{esc(self.title)}</text>']
        if self.subtitle:
            out.append(f'<text x="{self.title_x}" y="47" font-size="12.5" fill="{INK2}">{esc(self.subtitle)}</text>')
        out += self.back + self.items
        cx = (self.ml + self.w - self.mr) / 2
        out.append(f'<text x="{cx:.1f}" y="{self.h - 16}" font-size="13.5" text-anchor="middle" fill="{INK}">{esc(self.xlabel)}</text>')
        cy = (self.mt + self.h - self.mb) / 2
        out.append(f'<text x="24" y="{cy:.1f}" font-size="13.5" text-anchor="middle" fill="{INK}" transform="rotate(-90 24 {cy:.1f})">{esc(self.ylabel)}</text>')
        return out

    def svg(self):
        head = f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" font-family="{FONT}">'
        return "\n".join([head] + self.body() + ["</svg>"]) + "\n"


def stack(*plots):
    """Several plots on top of each other in one file."""
    w = max(p.w for p in plots)
    h = sum(p.h for p in plots) + 10 * (len(plots) - 1)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="{FONT}">']
    y = 0
    for p in plots:
        out.append(f'<g transform="translate(0 {y})">')
        out += p.body()
        out.append("</g>")
        y += p.h + 10
    out.append("</svg>")
    return "\n".join(out) + "\n"


def save(name, svg):
    with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)
    print("wrote", name)


def linspace(a, b, n=300):
    return [a + (b - a) * i / (n - 1) for i in range(n)]


# ---------------------------------------------------------------------------------------------
# Voice (docs/voice.md)
# ---------------------------------------------------------------------------------------------

def voice_latency():
    stages = [("end_of_turn", "Knowing I'm done", BLUE), ("stt", "Speech to text", ORANGE),
              ("agent_first_word", "Agent's first word", AQUA), ("tts_first_audio", "Kokoro's first sound", VIOLET)]
    rows = [("before", "Before"), ("after", "Now")]
    p = Plot("Where the wait goes, after I stop talking", "Seconds after the last word", "",
             (0, 6.2), (0, 2), w=760, h=300, ml=110, mt=86, mb=58,
             subtitle="A short question that needs no web search. Typical values from the pipeline's own timings")
    p.axes([0, 1, 2, 3, 4, 5, 6], [])
    for i, (key, name) in enumerate(rows):
        yc = 1.5 - i
        x = 0.0
        for k, label, col in stages:
            v = DATA["pipeline"][key][k]
            p.rect(x, x + v, yc - 0.3, yc + 0.3, col, opacity=0.95)
            if v > 0.28:
                p.text(x + v / 2, yc - 0.3, f"{v:g}", color=INK2, size=11.5, anchor="middle", dy=15)
            x += v
        p.text(0, yc, name, color=INK, size=13, anchor="end", dx=-10, dy=4)
        p.text(x, yc, f"{x:.2f} s", color=INK, size=13, dx=8, dy=4, weight="600")
    for j, (k, label, col) in enumerate(stages):
        lx = 110 + j * 160
        p.items.append(f'<rect x="{lx}" y="60" width="12" height="12" rx="2" fill="{col}"/>')
        p.items.append(f'<text x="{lx + 18}" y="70" font-size="12.5" fill="{INK}">{esc(label)}</text>')
    save("voice-latency.svg", p.svg())


def voice_stt_flat():
    clips = DATA["clips"]
    p = Plot("Whisper's fixed cost", "Length of what I said (s)", "Seconds from end of speech to text",
             (0, 8), (0, 4), subtitle="The 48 calibration phrases. Whisper small in the VM against Parakeet on the Hub, with straight-line fits")
    p.axes([0, 2, 4, 6, 8], [0, 1, 2, 3, 4])
    for c in clips:
        p.point(c["secs"], c["whisper"], ORANGE, r=4, label="Whisper small (int8)")
    for c in clips:
        p.point(c["secs"], c["parakeet"], BLUE, r=4, label="Parakeet TDT 0.6B v2 (int8)")
    for key, col in (("whisper", ORANGE), ("parakeet", BLUE)):
        a, b = fit([c["secs"] for c in clips], [c[key] for c in clips])
        p.line([(0, a), (8, a + 8 * b)], col, None, width=1.4, dash="5 4")
        p.text(4.6, a + 4.6 * b, f"{a:.2f} s + {b:.3f} s per second of speech", color=INK2, anchor="start", dy=22)
    p.legend("tl")
    save("voice-stt-flat.svg", p.svg())


def fit(xs, ys):
    """Least squares y = a + b x"""
    mx, my = statistics.mean(xs), statistics.mean(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - b * mx, b


def voice_bakeoff():
    p = Plot("Seven models on my own voice", "Seconds from end of speech to text (log scale)", "Words wrong (%)",
             (0.08, 5), (0, 35), xlog=True, subtitle="48 calibration phrases, the wake word trimmed off the front, on the Hub's i5-7500T")
    p.axes([0.1, 0.2, 0.5, 1, 2, 5], [0, 5, 10, 15, 20, 25, 30, 35], ["0.1", "0.2", "0.5", "1", "2", "5"])
    nudge = {"Parakeet TDT 0.6B v2, level": (-9, 4), "Parakeet TDT 0.6B v2, as shipped": (-9, 4),
             "Parakeet TDT 0.6B v3, words + level": (9, 4), "Canary 180M Flash": (9, 4),
             "Nemotron Streaming 0.6B, level": (9, 4), "Nemotron 3.5 Streaming 0.6B": (9, -6), "Moonshine base": (9, 16),
             "Whisper small, vocabulary prompt": (-9, -10), "Parakeet TDT 0.6B v2, words + level": (9, 16)}
    for m in DATA["bakeoff"]:
        col = BLUE if m["kind"] == "chosen" else (ORANGE if m["kind"] == "baseline" else GRAY)
        p.point(m["latency"], m["wer"], col, r=6 if m["kind"] != "offline" and m["kind"] != "streaming" else 5)
        dx, dy = nudge.get(m["model"], (8, 4))
        p.text(m["latency"], m["wer"], m["model"], color=INK if col != GRAY else INK2, size=12, anchor="start" if dx > 0 else "end", dx=dx, dy=dy)
    save("voice-bakeoff.svg", p.svg())


def voice_boost():
    pts = [(0.0, next(m["wer"] for m in DATA["bakeoff"] if m["model"] == "Parakeet TDT 0.6B v2, level"))]
    pts += [(b["score"], b["wer"]) for b in DATA["boost"]]
    whisper = DATA["bakeoff"][0]["wer"]
    p = Plot("How hard to push the house words", "Hotword boost (added log-score per matched token)", "Words wrong (%)",
             (0, 3.2), (8, 20), subtitle="Parakeet TDT 0.6B v2 with the level normalised, 30 house words and phrases")
    p.axes([0, 0.5, 1, 1.5, 2, 2.5, 3], [8, 10, 12, 14, 16, 18, 20])
    p.hline(whisper, ORANGE, None)
    p.text(3.2, whisper, f"Whisper small, {whisper}%", color=INK2, anchor="end", dx=-6, dy=17)
    p.line(pts, BLUE, "Parakeet")
    where = {0.0: ("start", 8, -10), 2.5: ("end", -9, -5), 3.0: ("middle", 0, -10)}
    for x, y in pts:
        p.point(x, y, BLUE)
        anchor, dx, dy = where.get(x, ("middle", 0, 21))
        p.text(x, y, f"{y}, no boost" if x == 0 else f"{y}", color=INK2, anchor=anchor, dx=dx, dy=dy)
    p.text(1.5, 11.2, "1.5 runs", color=INK, anchor="middle", dy=37)
    save("voice-boost.svg", p.svg())


def _pauses():
    """Every pause in the saved turns: how long it lasted and whether I carried on after it."""
    out = []
    for t in DATA["turns"]:
        runs = t["runs"]
        for k, r in enumerate(runs):
            end = runs[k + 1][0] if k + 1 < len(runs) else t["secs"]
            out.append((end - r[1], k + 1 < len(runs)))
    return out


def voice_resume():
    pauses = _pauses()
    taus = [i / 100 for i in range(10, 101, 2)]
    pts = []
    for tau in taus:
        lasted = [more for length, more in pauses if length >= tau]
        if len(lasted) >= 8:
            pts.append((tau, sum(lasted) / len(lasted)))
    allowed = [(0.3, 0.02), (0.45, 0.05), (0.6, 0.15), (0.9, 0.5)]
    p = Plot("The longer the pause, the less likely I carry on", "Pause so far (s)", "Probability",
             (0.1, 1.0), (0, 0.75), subtitle="Every pause in the 69 saved turns with speech, from Silero's speech runs")
    p.axes([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    p.line(pts, BLUE, "I start talking again, given the pause got this long")
    p.line([(0.1, 0.02)] + allowed + [(1.0, 0.5)], ORANGE, "Doubt Smart Turn may have and still end the turn", dash="6 4", step=True)
    for x, y in allowed:
        p.point(x, y, ORANGE, r=4)
    p.legend("tr")
    save("voice-resume.svg", p.svg())


def voice_smartturn():
    asks = [(a["pause"], a["p"], a["more"]) for t in DATA["turns"] for a in t["asks"]]
    xs = [0.2, 0.3, 0.45, 0.6, 0.9]
    p = Plot("What Smart Turn said at each pause", "Pause so far (s)", "Smart Turn: probability I've finished",
             (0, 6), (0, 1.0), mt=92, h=470, mb=84, subtitle="Each dot is one check in the replay of 108 saved turns. Dashed: how sure the satellite needs it to be")
    p.axes([0.75 + i * 1.15 for i in range(5)], [0, 0.2, 0.4, 0.6, 0.8, 1.0], [f"{x:g}" for x in xs])
    rng = random.Random(7)
    need = {0.3: 0.98, 0.45: 0.95, 0.6: 0.85, 0.9: 0.5}
    for i, x in enumerate(xs):
        cx = 0.75 + i * 1.15
        for pause, prob, more in asks:
            if pause != x:
                continue
            off = -0.22 if more else 0.22
            px = p.X(cx + off + rng.uniform(-0.15, 0.15))
            p.raw_point(px, p.Y(prob), ORANGE if more else BLUE, r=3.4, opacity=0.8)
        if x in need:
            p.items.append(f'<line x1="{p.X(cx - 0.5):.1f}" y1="{p.Y(need[x]):.1f}" x2="{p.X(cx + 0.5):.1f}" y2="{p.Y(need[x]):.1f}" stroke="{INK}" stroke-width="1.6" stroke-dasharray="5 3"/>')
        need_text = f"needs {round(need[x] * 100)}%" if x in need else "doesn't ask"
        p.items.append(f'<text x="{p.X(cx):.1f}" y="{p.h - p.mb + 37}" font-size="12" text-anchor="middle" fill="{INK2}">{need_text}</text>')

    for j, (lab, col) in enumerate([("I carried on talking after this pause", ORANGE), ("I'd finished", BLUE)]):
        lx = p.ml + j * 290
        p.items.append(f'<circle cx="{lx + 6}" cy="68" r="5.5" fill="{col}"/>')
        p.items.append(f'<text x="{lx + 18}" y="72" font-size="12.5" fill="{INK}">{esc(lab)}</text>')
    save("voice-smartturn.svg", p.svg())


def policy_outcome(rule):
    """(turns ended early and right, median seconds saved on those, times it cut me off)"""
    saved, cut = [], 0
    for t in DATA["turns"]:
        if not t["runs"]:
            continue
        hit = next((a for a in t["asks"] if a["pause"] in rule and a["p"] > rule[a["pause"]]), None)
        if hit is None:
            continue
        if hit["more"]:
            cut += t["label"] == "cut"
        else:
            saved.append(t["secs"] - hit["t"])
    return len(saved), statistics.median(saved), cut


POLICIES = [
    ("Any pause from 0.2 s, over 80%", {0.2: .8, 0.3: .8, 0.45: .8, 0.6: .8}),
    ("From 0.45 s, over 80%", {0.45: .8, 0.6: .8}),
    ("From 0.6 s, over 80%", {0.6: .8}),
    ("0.3 / 0.45 / 0.6 s at 97 / 90 / 80%", {0.3: .97, 0.45: .9, 0.6: .8}),
    ("0.45 / 0.6 s at 95 / 85%", {0.45: .95, 0.6: .85}),
    ("Running: 0.3 / 0.45 / 0.6 / 0.9 s at 98 / 95 / 85 / 50%", {0.3: .98, 0.45: .95, 0.6: .85, 0.9: .5}),
]


def voice_policies():
    p = Plot("Faster against cutting me off", "Times it cut me off mid-thought (of 69 turns)", "Median seconds saved",
             (-0.5, 7), (0.4, 1.1), subtitle="Rules for when to end the turn, replayed on the same saved turns", ml=84)
    p.axes([0, 1, 2, 3, 4, 5, 6, 7], [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1])
    spots = {}
    for name, rule in POLICIES:
        n, med, cut = policy_outcome(rule)
        spots.setdefault((cut, round(med, 3)), []).append((name, n))
    for (cut, med), names in spots.items():
        running = any(nm.startswith("Running") for nm, _ in names)
        p.point(cut, med, BLUE if running else GRAY, r=6 if running else 5)
        right = cut < 4
        for k, (nm, n) in enumerate(names):
            p.text(cut, med, f"{nm} ({n} turns)", color=INK if running else INK2, size=12,
                   anchor="start" if right else "end", dx=10 if right else -10, dy=4 + 16 * k)
    save("voice-policies.svg", p.svg())


def voice_wake():
    nxt = sorted(DATA["wake"]["next"])
    p = Plot("The next word often starts before the wake word fires", "Next word's start, relative to the wake word firing (s)", "",
             (-0.45, 0.85), (0, 15), h=360, subtitle="Every \"Hey Jarvis\" in the 5-minute calibration recording, through the satellite's own detector")
    p.axes([-0.4, -0.2, 0, 0.2, 0.4, 0.6, 0.8], [])
    p.band_x(-0.45, 0, RED, "", opacity=0.08)
    p.band_x(-0.256, 0, BLUE, "", opacity=0.12)
    p.text(-0.128, 14, "kept by the pre-roll", color=INK2, anchor="middle")
    p.text(-0.353, 14, "still lost", color=INK2, anchor="middle")
    p.vline(-0.256, BLUE, "0.256 s pre-roll", label_y=12.4, anchor="end")
    counts = {}
    for v in nxt:
        b = round(v / 0.04) * 0.04
        counts[b] = counts.get(b, 0) + 1
        p.raw_point(p.X(b), p.Y(counts[b] - 0.5), BLUE if v >= -0.256 else RED, r=5.5, opacity=0.9)
    save("voice-wake.svg", p.svg())


# ---------------------------------------------------------------------------------------------
# Control (docs/control.md): the blocks and the estimators, with the house's own numbers
# ---------------------------------------------------------------------------------------------

def bayes_step(b, stay, enter, ratio):
    prior = b * stay + (1 - b) * enter
    num = prior * ratio
    den = num + (1 - prior)
    return min(max(num / den if den > 0 else prior, 0.0001), 0.9999)


def asleep_minute(prev, ctx):
    """One minute of the control core's asleep_next (asleep.py), with the context handed in."""
    h = ctx["hour"]
    base = 0.008 if (h >= 23 or h < 4) else (0.003 if h >= 21 else (0.003 if h < 7 else 0.0003))
    q = ctx["quiet"]
    m = ((3 if ctx.get("night") else 1) * (1 if ctx.get("lights") else 2) * (6 if q >= 45 else (3 if q >= 15 else 1))
         * (1.5 if ctx.get("charger") else 1) * (1.3 if ctx.get("focus") else 1) * (0.5 if ctx.get("tv") else 1)
         * (1.5 if ctx.get("door_shut") and (h >= 21 or h < 6) else 1))
    enter = 0 if ctx.get("typing") else min(base * m, 0.3)
    wake = 0.002 * (4 if 5 <= h < 11 else 1) * (5 if ctx.get("waking") else 1)
    ratio = 0.001 if ctx.get("typing") else (0.05 if ctx.get("active") else 1)
    return min(bayes_step(prev, 1 - wake, enter, ratio), 0.99)


def night_context(minute):
    """A night, minute by minute from 21:00: laptop, TV, goodnight at 23:20, a bathroom trip, the alarm."""
    hour = (21 + minute // 60) % 24
    clock = 21 * 60 + minute
    ctx = {"hour": hour}
    if minute < 75:                          # 21:00 to 22:15 at the laptop
        ctx.update(typing=True, lights=True, active=True)
    elif minute < 140:                       # 22:15 to 23:20 the TV, moving now and then
        ctx.update(tv=True, lights=True, active=(minute % 6 == 0))
    elif 310 <= minute < 314:                # 02:10 a trip to the bathroom
        ctx.update(night=True, charger=True, focus=True, door_shut=False, lights=True, active=True)
    elif minute >= 476:                      # 04:56 the sunrise starts, 05:26 up and about
        ctx.update(night=True, charger=minute < 506, lights=True, waking=True, active=minute >= 506 and minute % 2 == 0)
    else:                                    # goodnight at 23:20
        ctx.update(night=True, charger=True, focus=True, door_shut=True)
    return ctx, clock


def run_night(minutes=600):
    b, quiet, last, out = 0.05, 0, False, []
    for t in range(minutes):
        ctx, clock = night_context(t)
        quiet = 0 if ctx.get("active") or ctx.get("typing") else quiet + 1
        ctx["quiet"] = quiet
        b = asleep_minute(b, ctx)
        last = b >= 0.85 or (last and b > 0.35)
        out.append((clock, b, last, ctx))
    return out


def clock_ticks(start, end, step=60):
    ticks = list(range(start, end + 1, step))
    labels = [f"{(t // 60) % 24}:{t % 60:02d}" for t in ticks]
    return ticks, labels


def control_asleep_night():
    night = run_night()
    xs, xl = clock_ticks(21 * 60, 31 * 60)
    p = Plot("A night through the asleep filter", "Time", "Belief I'm asleep (%)", (21 * 60, 31 * 60), (0, 100),
             subtitle="Simulated with the filter's own numbers: laptop, TV, goodnight at 23:20, the bathroom at 2:10, the alarm at 5:25")
    p.axes(xs, [0, 20, 35, 50, 85, 100], xl)
    on_start = None
    for clock, b, asleep, _ in night + [(31 * 60, 0, False, None)]:
        if asleep and on_start is None:
            on_start = clock
        if not asleep and on_start is not None:
            p.band_x(on_start, clock, BLUE, None, opacity=0.10)
            on_start = None
    p.hline(85, INK2, "on at 85%", label_x=21 * 60 + 8, anchor="start")
    p.hline(35, INK2, "off at 35%", label_x=21 * 60 + 8, anchor="start")
    p.line([(c, b * 100) for c, b, _, _ in night], BLUE, None, width=2.2)
    for clock, label in [(23 * 60 + 20, "goodnight"), (26 * 60 + 10, "bathroom"), (29 * 60 + 26, "up")]:
        p.vline(clock, GRAY, label, label_y=92, anchor="start" if label == "up" else "end")
    p.text(24 * 60 + 45, 45, "shaded: asleep is on", color=INK2, anchor="middle")
    save("control-asleep-night.svg", p.svg())


def naive_bayes(ctx, quiet):
    """The old binary_sensor.probably_asleep: prior 0.33, nine observations, each counted every minute."""
    h = ctx["hour"]
    obs = [(True, 0.99, 0.6), (h >= 23 or h < 6, 0.85, 0.12), (bool(ctx.get("night")), 0.75, 0.05),
           (quiet >= 30, 0.95, 0.35), (quiet >= 30, 0.92, 0.25), (bool(ctx.get("charger")), 0.8, 0.3),
           (bool(ctx.get("focus")), 0.8, 0.35), (not ctx.get("typing"), 0.99, 0.55), (not ctx.get("tv"), 0.92, 0.5)]
    lo = math.log(0.33 / 0.67)
    for seen, pt, pf in obs:
        lo += math.log(pt / pf) if seen else math.log((1 - pt) / (1 - pf))
    return 1 / (1 + math.exp(-lo))


def control_naive_vs_filter():
    night = run_night(390)
    quiet, pts_n = 0, []
    for clock, b, _, ctx in night:
        quiet = 0 if ctx.get("active") or ctx.get("typing") else quiet + 1
        pts_n.append((clock, 100 * naive_bayes(ctx, quiet)))
    xs, xl = clock_ticks(21 * 60, 27 * 60 + 30, 60)
    p = Plot("The old sensor against the filter", "Time", "Probability I'm asleep (%)", (21 * 60, 27 * 60 + 30), (0, 100),
             subtitle="Same evening. The old naive Bayes sensor recounted every observation every minute, with no memory")
    p.axes(xs, [0, 20, 40, 60, 80, 90, 100], xl)
    p.hline(90, ORANGE, "old sensor's line, 90%", label_x=21 * 60 + 8, anchor="start", dash="2 3")
    p.line(pts_n, ORANGE, "Old: naive Bayes, prior 1/3", width=2.2)
    p.line([(c, b * 100) for c, b, _, _ in night], BLUE, "Now: the Bayes filter", width=2.2)
    p.vline(23 * 60 + 20, GRAY, "goodnight", label_y=50, anchor="end")
    p.vline(26 * 60 + 10, GRAY, "bathroom, 3 minutes", label_y=50)
    p.legend(at=(23 * 60 + 38, 42))
    save("control-naive-vs-filter.svg", p.svg())


def minutes_to_asleep(ctx, start=0.05, limit=600):
    b = start
    for t in range(limit):
        c = dict(ctx, quiet=t)
        b = asleep_minute(b, c)
        if b >= 0.85:
            return t + 1
    return None


def control_hazard():
    cases = [("2 PM, Day, lights on", {"hour": 14, "lights": True}),
             ("10 PM, lights on, TV on", {"hour": 22, "lights": True, "tv": True}),
             ("10 PM, lights off, phone charging", {"hour": 22, "charger": True}),
             ("11:30 PM, Night, TV on", {"hour": 23, "night": True, "tv": True, "lights": True}),
             ("11:30 PM, Night, lights off, charging, Focus", {"hour": 23, "night": True, "charger": True, "focus": True}),
             ("...and the bedroom door shut", {"hour": 23, "night": True, "charger": True, "focus": True, "door_shut": True})]
    p = Plot("Context sets how fast it decides I'm asleep", "Minutes of quiet until the filter says asleep (85%)", "",
             (0, 400), (0, len(cases)), ml=300, h=330, mt=66, title_x=24,
             subtitle="From 5%, nothing happening, the context held still. It changes the hazard, never the evidence")
    p.axes([0, 50, 100, 150, 200, 300, 400], [])
    for i, (name, ctx) in enumerate(cases):
        yc = len(cases) - i - 0.5
        m = minutes_to_asleep(ctx)
        p.text(0, yc, name, color=INK, size=12.5, anchor="end", dx=-10, dy=4)
        if m is None:
            p.text(0, yc, "not within 10 hours", color=INK2, size=12.5, dx=8, dy=4)
            continue
        p.rect(0, min(m, 400), yc - 0.3, yc + 0.3, BLUE, opacity=0.95)
        p.text(min(m, 400), yc, f"{m} min", color=INK, size=12.5, dx=6, dy=4)
    save("control-hazard.svg", p.svg())


def control_lowpass():
    tau = 60.0
    p = Plot("The low-pass block is exact for any step", "Seconds after a step from 0 to 100", "Output",
             (0, 300), (0, 100), subtitle="tau = 60 s. Even 6 s steps and uneven 3 to 40 s steps land on the same curve")
    p.axes([0, 60, 120, 180, 240, 300], [0, 20, 40, 63.2, 80, 100], None, ["0", "20", "40", "63.2", "80", "100"])
    p.line([(t, 100 * (1 - math.exp(-t / tau))) for t in linspace(0, 300)], GRAY, "1 - exp(-t / tau)", width=2.5)
    y, t = 0.0, 0.0
    for _ in range(50):
        t += 6
        y += (1 - math.exp(-6 / tau)) * (100 - y)
        p.point(t, y, BLUE, r=3.5, label="every 6 s")
    rng = random.Random(3)
    y, t = 0.0, 0.0
    while t < 290:
        dt = rng.uniform(3, 40)
        t += dt
        y += (1 - math.exp(-dt / tau)) * (100 - y)
        p.point(t, y, ORANGE, r=5, label="uneven, 3 to 40 s")
    p.vline(60, INK2, "one time constant", label_y=20)
    p.legend("br")
    save("control-lowpass.svg", p.svg())


def control_schmitt():
    rng = random.Random(11)
    xs, x = [], 0.2
    for t in range(240):
        target = 0.2 + 0.7 / (1 + math.exp(-(t - 80) / 12)) - 0.5 / (1 + math.exp(-(t - 180) / 10))
        x += 0.25 * (target - x) + rng.gauss(0, 0.05)
        xs.append((t, min(max(x, 0.01), 0.99)))
    one, hyst, flips1, flips2, s1, s2 = [], [], 0, 0, False, False
    for t, v in xs:
        n1 = v >= 0.6
        flips1 += n1 != s1
        s1 = n1
        n2 = True if v >= 0.85 else (False if v <= 0.35 else s2)
        flips2 += n2 != s2
        s2 = n2
        one.append((t, 1 if s1 else 0))
        hyst.append((t, 1 if s2 else 0))
    a = Plot("A threshold on a noisy belief", "Minutes", "Belief", (0, 240), (0, 1), h=300,
             subtitle="The same signal into one threshold at 60%, and into a Schmitt trigger at 85% on, 35% off")
    a.axes([0, 60, 120, 180, 240], [0, 0.35, 0.6, 0.85, 1])
    a.hline(0.85, INK2, "on at 85%", dash="5 3", label_x=3, anchor="start")
    a.hline(0.6, ORANGE, "single threshold, 60%", dash="2 3", label_x=3, anchor="start")
    a.hline(0.35, INK2, "off at 35%", dash="5 3", label_x=3, anchor="start")
    a.line(xs, GRAY, None, width=1.6)
    b = Plot("What comes out", "Minutes", "Output", (0, 240), (-0.25, 3.05), h=260, mt=50,
             subtitle=f"One threshold flipped {flips1} times. The Schmitt trigger flipped {flips2} times")
    b.axes([0, 60, 120, 180, 240], [0, 1, 1.8, 2.8], None, ["off", "on", "off", "on"])
    b.line([(t, v + 1.8) for t, v in one], ORANGE, None, step=True)
    b.line(hyst, BLUE, None, step=True)
    b.text(140, 2.15, "one threshold", color=INK, anchor="middle")
    b.text(150, 0.35, "Schmitt trigger", color=INK, anchor="middle")
    save("control-schmitt.svg", stack(a, b))


def pid_sim(setpoints, anti_windup=True, kp=2.0, ki=0.05, dt=10.0, tau=120.0, lo=0.0, hi=100.0):
    """test_blocks.py's loop: a first-order room with a 2-minute time constant, the PID block driving it."""
    y, i, trace = 20.0, 0.0, []
    for sp in setpoints:
        err = sp - y
        i_new = i + err * dt
        u_try = kp * err + ki * i_new
        pinned = (u_try > hi and err > 0) or (u_try < lo and err < 0)
        i = i if (pinned and anti_windup) else i_new
        u = min(max(kp * err + ki * i, lo), hi)
        y += (u - y) * (dt / tau)
        trace.append((y, u))
    return trace


def control_pid():
    sps = [150.0] * 60 + [50.0] * 150
    good = pid_sim(sps)
    bad = pid_sim(sps, anti_windup=False)
    tm = [(k + 1) * 10 / 60 for k in range(len(sps))]
    p = Plot("Anti-windup: asking for the impossible, then something reasonable", "Minutes", "Room (made-up units)",
             (0, 35), (0, 110), subtitle="Kp 2, Ki 0.05, output 0 to 100, a first-order room with tau = 120 s, 10 s steps (tests/test_blocks.py)")
    p.axes([0, 5, 10, 15, 20, 25, 30, 35], [0, 20, 40, 50, 60, 80, 100])
    p.line([(t, min(s, 110)) for t, s in zip(tm, sps)], INK2, "setpoint (150 is out of reach)", dash="6 4", step=True)
    p.line(list(zip(tm, [y for y, _ in bad])), ORANGE, "integral grows while the output is pinned")
    p.line(list(zip(tm, [y for y, _ in good])), BLUE, "conditional integration (blocks.py)")
    p.legend("br")
    save("control-pid.svg", p.svg())


def control_arbiter():
    p = Plot("An evening through the gate", "Time", "Lamp (%)",
             (16.5 * 60, 21 * 60), (0, 100), subtitle="Priority 2 is a hand at the switch, 3 a routine, 4 the clock's look. A hold blocks anything weaker until it expires")
    xs, xl = clock_ticks(17 * 60, 21 * 60)
    p.axes(xs, [0, 25, 50, 75, 100], xl)
    p.band_x(18 * 60 + 45, 20 * 60 + 18, ORANGE, "held: priority 2, by hand", opacity=0.12, label_y=45)
    level = [(16.5 * 60, 0), (17 * 60 + 2, 80), (18 * 60 + 45, 0), (20 * 60 + 18, 80), (21 * 60, 80)]
    p.line(level, BLUE, None, width=2.4, step=True)
    events = [(17 * 60 + 2, 80, "17:02 Evening picked: go"), (18 * 60 + 45, 0, "18:45 off at the switch: hold for 3 h"),
              (19 * 60 + 30, 0, "a clock look, priority 4: held"), (20 * 60 + 18, 80, "20:18 home again, override: go, hold released")]
    for x, y, lab in events:
        p.point(x, y, INK if "held" not in lab else RED, r=5)
    p.text(17 * 60 + 2, 80, events[0][2], dx=8, dy=-10)
    p.text(18 * 60 + 45, 0, events[1][2], anchor="end", dx=-8, dy=-10)
    p.text(19 * 60 + 30, 0, events[2][2], anchor="middle", dy=-14)
    p.text(20 * 60 + 18, 80, events[3][2], anchor="end", dx=-8, dy=-10)
    save("control-arbiter.svg", p.svg())


# ---------------------------------------------------------------------------------------------
# Routines, hardware, sensing
# ---------------------------------------------------------------------------------------------

def lightness(level):
    """CIE L*, with the bulb's light taken as proportional to its level (roughly true)."""
    y = level / 100
    return 116 * y ** (1 / 3) - 16 if y > 0.008856 else 903.3 * y


def routines_sunrise():
    n, floor = 31, 28
    sq = [(i - 30, floor + (100 - floor) * (i / (n - 1)) ** 2) for i in range(n)]
    lin = [(i - 30, floor + (100 - floor) * (i / (n - 1))) for i in range(n)]
    p = Plot("Why the sunrise is squared", "Minutes to the wake time", "Percent",
             (-30, 0), (0, 100), subtitle="Bedroom overhead from 28% (where the bulbs start to glow) to full, one step a minute")
    p.axes([-30, -25, -20, -15, -10, -5, 0], [0, 20, 40, 60, 80, 100])
    p.line(lin, GRAY, "level, straight line", dash="6 4")
    p.line(sq, BLUE, "level, squared (wake.yaml)", dash="6 4")
    p.line([(x, lightness(v)) for x, v in lin], GRAY, "how bright it looks, straight line")
    p.line([(x, lightness(v)) for x, v in sq], BLUE, "how bright it looks, squared")
    p.legend("br")
    save("routines-sunrise.svg", p.svg())


def hardware_levels():
    a = DATA["audio_dbfs"]
    rows = [("Raw mics: room noise, idle", a["noise_floor_raw"], None, GRAY),
            ("Raw mics: me talking at 3 to 4 m", a["speech_3_4m_raw"][0], a["speech_3_4m_raw"][1], BLUE),
            ("Raw mics: the Hub's own speaker", a["speaker_on_mics_raw"], None, ORANGE),
            ("hub_mic: the Hub's own speaker", a["speaker_after_aec"], None, ORANGE),
            ("hub_mic: room noise", a["noise_hub_mic"], None, GRAY),
            ("hub_mic: me talking", a["speech_hub_mic"], None, BLUE)]
    p = Plot("What the mics hear, before and after echo cancelling", "Level (dBFS)", "", (-100, -30), (0, len(rows)),
             ml=260, h=330, mt=66, title_x=24, subtitle="Raw mics with the hardware gain maxed. hub_mic is after PipeWire's WebRTC echo canceller and its gain")
    p.axes([-100, -90, -80, -70, -60, -50, -40, -30], [])
    for i, (name, lo, hi, col) in enumerate(rows):
        yc = len(rows) - i - 0.5
        p.text(-100, yc, name, color=INK, size=12.5, anchor="end", dx=-10, dy=4)
        if hi is not None:
            p.rect(lo, hi, yc - 0.12, yc + 0.12, col, opacity=0.9, rx=4)
            p.text(hi, yc, f"{lo} to {hi}", color=INK2, dx=8, dy=4)
        else:
            p.point(lo, yc, col, r=6)
            p.text(lo, yc, f"{lo}", color=INK2, dx=10, dy=4)
    p.items.append(f'<line x1="{p.ml}" y1="{p.Y(3):.1f}" x2="{p.w - p.mr}" y2="{p.Y(3):.1f}" stroke="{INK2}" stroke-width="1"/>')
    save("hardware-levels.svg", p.svg())


def sensing_latency():
    rows = [("iOS Shortcuts (Wi-Fi, charger, alarm)", 0.3, 1.5), ("A light switched at the wall (Matter)", 0.5, 1.5),
            ("Door sensors (Zigbee through the G410)", 0.3, 1.0), ("Hub motion (PIR)", 0.5, 1.5),
            ("Doorbell ring, motion, faces", 1, 3), ("Plugs: watts", 1, 5), ("TV over ADB", 5, 15),
            ("Laptop input (HASS.Agent)", 5, 15), ("Washer (LG ThinQ cloud)", 5, 60),
            ("Phone GPS (person.resident)", 60, 600), ("Phone app sensors (SSID, Focus)", 30, 1800),
            ("Oura ring", 3600, 6 * 3600)]
    p = Plot("How late each signal tells the house", "Delay (seconds, log scale)", "", (0.1, 30000), (0, len(rows)),
             xlog=True, ml=300, h=450, mt=66, title_x=24, subtitle="Rough ranges, from watching the logs")
    p.axes([0.1, 1, 10, 60, 600, 3600, 21600], [], ["0.1", "1", "10", "1 min", "10 min", "1 h", "6 h"])
    for i, (name, lo, hi) in enumerate(rows):
        yc = len(rows) - i - 0.5
        p.text(0.1, yc, name, color=INK, size=12.5, anchor="end", dx=-10, dy=4)
        p.rect(lo, hi, yc - 0.18, yc + 0.18, BLUE, opacity=0.9, rx=4)
    save("sensing-latency.svg", p.svg())


# ---------------------------------------------------------------------------------------------
# Lighting (docs/lighting.md): the light curve over a day, with the control core's numbers (curve.py)
# ---------------------------------------------------------------------------------------------

def sun_elevation(doy, hour, lat=45.0, lon=-15.0, utc_offset=0):
    """NOAA's low-precision solar position, degrees above the horizon. For a made-up place at 45 degrees
    north whose clock noon is an hour ahead of the sun's, like most of the world on summer time"""
    g = 2 * math.pi / 365 * (doy - 1 + (hour - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    ha = math.radians((hour * 60 + eqtime + 4 * lon - 60 * utc_offset) / 4 - 180)
    la = math.radians(lat)
    cz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return 90 - math.degrees(math.acos(max(-1, min(1, cz))))


def smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def light_curve(hour, cloud, bed=21 + 40 / 60, wake=5 + 25 / 60, hrs=3.0, doy=288):
    """curve.py's light_curve(), for a clock hour in mid-October"""
    elev = sun_elevation(doy, hour)
    clear = max(0.0, min(1.0, math.sin(math.radians(elev)) / math.sin(math.radians(35))))
    d = clear * (1 - 0.75 * cloud ** 3.4)
    w = 0.0 if wake <= hour < 12 else smoothstep((hrs + 1 - (bed - hour)) / 1)
    level = 80 - (80 - 50) * d
    level += (35 - level) * w
    k = 4000 - 1300 * smoothstep((hour - 13) / 2)
    k = max(k + (2700 - k) * w, 2700)
    return level, k, elev


def lighting_curve():
    hours = [6 + i / 12 for i in range(18 * 12 + 1)]
    xs = [6, 9, 12, 15, 18, 21, 24]
    xl = ["6 AM", "9", "Noon", "3 PM", "6", "9", "12"]
    sunset = next(h for h in hours if h > 12 and sun_elevation(288, h) < 0)
    a = Plot("The ambient layer over a workday", "", "Floor lamp (%)", (6, 24), (0, 100), h=300, mb=40,
             subtitle="Mid-October at 45 degrees north, bedtime 9:40 PM, wind-down from 6:40. Clear and overcast")
    a.axes(xs, [0, 35, 50, 80, 100], xl)
    a.band_x(18 + 40 / 60 - 1, 18 + 40 / 60, VIOLET, None, opacity=0.08)
    a.band_x(18 + 40 / 60, 24, VIOLET, None, opacity=0.16)
    a.line([(h, light_curve(h, 0.0)[0]) for h in hours], BLUE, "clear", width=2.4)
    a.line([(h, light_curve(h, 0.9)[0]) for h in hours], GRAY, "overcast", width=2.4, dash="6 4")
    a.vline(sunset, INK2, "sunset", label_y=92)
    a.text(21.3, 35, "wind-down: 35%", color=INK2, anchor="middle", dy=-8)
    a.text(13.5, 50, "full daylight: the windows do the work", color=INK2, anchor="middle", dy=20)
    a.legend(at=(6.4, 30))
    b = Plot("And its colour", "", "Colour temperature (K)", (6, 24), (2400, 4400), h=260, mt=50, mb=56)
    b.axes(xs, [2700, 3000, 3500, 4000], xl)
    b.band_x(18 + 40 / 60 - 1, 18 + 40 / 60, VIOLET, None, opacity=0.08)
    b.band_x(18 + 40 / 60, 24, VIOLET, None, opacity=0.16)
    b.line([(h, light_curve(h, 0.0)[1]) for h in hours], ORANGE, None, width=2.4)
    b.text(9.5, 4000, "4000 K for the morning", color=INK2, anchor="middle", dy=-10)
    b.text(16.3, 2700, "2700 K by 3", color=INK2, anchor="middle", dy=-10)
    b.text(21.3, 2700, "and no warmer", color=INK2, anchor="middle", dy=-10)
    save("lighting-curve.svg", stack(a, b))


if __name__ == "__main__":
    voice_latency()
    voice_stt_flat()
    voice_bakeoff()
    voice_boost()
    voice_resume()
    voice_smartturn()
    voice_policies()
    voice_wake()
    control_asleep_night()
    control_naive_vs_filter()
    control_hazard()
    control_lowpass()
    control_schmitt()
    control_pid()
    control_arbiter()
    routines_sunrise()
    hardware_levels()
    sensing_latency()
    lighting_curve()
