"""Knowing when I've finished talking, for Linux Voice Assistant (host/patches/lva-endofturn.patch).

Home Assistant ends a turn after a fixed stretch of silence, which is too long after "turn off the
lamp" and too short when I stop to think of a name. This listens to the turn as it streams: Silero
VAD finds the pauses, and at a pause Smart Turn v3.2 (pipecat-ai/smart-turn, BSD 2-clause) hears
the last 8 s and says how sure it is that the sentence is finished. Sure enough for how long the
pause has lasted, and the satellite ends the turn itself. Not sure, and Home Assistant's own
silence timer (set to "relaxed", 1.25 s) still ends it.

The checks, how long the pause has gone on and how sure Smart Turn has to be, come from replaying
108 real turns (docs/voice.md): early and very sure, or later and a bit less sure. Every check goes
in the journal, so the numbers can be tuned on what actually happens:
  journalctl --user -u linux-voice-assistant | grep "end of turn"

Smart Turn runs on its own thread (about 0.1 s a check on one core) so the mic, and the wake word
with it, never wait for it. Anything wrong with the models and this switches itself off, and the
turn ends the way it always did.
"""
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np

_LOGGER = logging.getLogger(__name__)

RATE = 16000
VAD_CHUNK = 512                      # Silero wants 32 ms at 16 kHz
WINDOW = 8 * RATE                    # Smart Turn hears the last 8 s
SPEECH = 0.5                         # Silero's probability for "that's speech"
MIN_RUN = 4                          # 128 ms of speech in a row before it counts (coughs, clicks)
# (seconds of pause, how sure) pairs, in order. LVA_TURN_CHECKS="0.3:0.98,0.45:0.95,..." overrides
DEFAULT_CHECKS = ((0.3, 0.98), (0.45, 0.95), (0.6, 0.85), (0.9, 0.5))


def _checks():
    raw = os.environ.get("LVA_TURN_CHECKS", "")
    try:
        return tuple((float(a), float(b)) for a, b in (p.split(":") for p in raw.split(",") if p)) or DEFAULT_CHECKS
    except ValueError:
        return DEFAULT_CHECKS


def _session(ort, path):
    so = ort.SessionOptions()
    so.inter_op_num_threads = 1
    so.intra_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(path, sess_options=so, providers=["CPUExecutionProvider"])


def _mel_filters(n_mels=80, n_fft=400):
    """The Slaney mel filterbank Whisper's feature extractor uses (checked against it to 1e-7)."""
    def hz_to_mel(f):
        f = np.asarray(f, dtype=np.float64)
        return np.where(f >= 1000.0, 15.0 + np.log(np.maximum(f, 1e-10) / 1000.0) / (np.log(6.4) / 27.0), 3.0 * f / 200.0)

    def mel_to_hz(m):
        m = np.asarray(m, dtype=np.float64)
        return np.where(m >= 15.0, 1000.0 * np.exp((np.log(6.4) / 27.0) * (m - 15.0)), 200.0 * m / 3.0)

    fft_freqs = np.linspace(0, RATE / 2, n_fft // 2 + 1)
    pts = mel_to_hz(np.linspace(hz_to_mel(0.0), hz_to_mel(RATE / 2), n_mels + 2))
    ramps = pts[:, None] - fft_freqs[None, :]
    weights = np.maximum(0, np.minimum(-ramps[:-2] / np.diff(pts)[:-1, None], ramps[2:] / np.diff(pts)[1:, None]))
    return weights * (2.0 / (pts[2:n_mels + 2] - pts[:n_mels]))[:, None]


_FILTERS = _mel_filters()
_HANN = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(400) / 400)


def features(audio):
    """Whisper's log-mel of the last 8 s, padded with silence in front, the way Smart Turn trained."""
    a = np.asarray(audio, dtype=np.float32)
    a = a[-WINDOW:] if len(a) > WINDOW else np.pad(a, (WINDOW - len(a), 0))
    a = (a - a.mean()) / np.sqrt(a.var() + 1e-7)
    x = np.pad(a.astype(np.float64), (200, 200), mode="reflect")
    spec = np.abs(np.fft.rfft(np.lib.stride_tricks.sliding_window_view(x, 400)[::160] * _HANN, axis=-1)) ** 2
    log = np.log10(np.maximum(_FILTERS @ spec[:-1].T, 1e-10))
    return ((np.maximum(log, log.max() - 8.0) + 4.0) / 4.0).astype(np.float32)[None]


class EndOfTurn:
    """Feed it the turn's audio as it streams. It calls on_finished(p, pause) at most once a turn."""

    def __init__(self, model_dir, on_finished):
        import onnxruntime as ort

        self._vad = _session(ort, os.path.join(model_dir, "silero_vad.onnx"))
        self._turn = _session(ort, os.path.join(model_dir, "smart-turn-v3.2-cpu.onnx"))
        self._on_finished = on_finished
        self._checks = _checks()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="end-of-turn")
        self._lock = threading.RLock()
        self._turn_id = 0
        self.reset()

    def reset(self):
        with self._lock:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
            self._context = np.zeros((1, 64), dtype=np.float32)
            self._audio = np.zeros(0, dtype=np.float32)
            self._rest = np.zeros(0, dtype=np.float32)
            self._heard = False     # a real run of speech so far this turn
            self._run = 0           # speech chunks in a row
            self._pause = 0.0       # seconds since the last real run of speech
            self._next = 0          # which check is next in this pause
            self._pause_id = 0      # a check only counts for the pause it was asked in
            self._done = False
            self._turn_id += 1      # a check left over from the last turn never ends this one

    def _speech(self, chunk):
        x = np.concatenate((self._context, chunk.reshape(1, -1)), axis=1)
        out, self._state = self._vad.run(None, {"input": x, "state": self._state, "sr": np.array(RATE, dtype=np.int64)})
        self._context = x[:, -64:]
        return float(out[0][0]) > SPEECH

    def feed(self, pcm):
        """16-bit mono 16 kHz, any length."""
        if self._done:
            return
        a = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        with self._lock:
            self._audio = np.concatenate((self._audio, a))[-WINDOW:]
            buf = np.concatenate((self._rest, a))
            n = len(buf) // VAD_CHUNK * VAD_CHUNK
            self._rest = buf[n:]
            for i in range(0, n, VAD_CHUNK):
                if self._speech(buf[i:i + VAD_CHUNK]):
                    self._run += 1
                    if self._run >= MIN_RUN:
                        self._heard, self._pause, self._next = True, 0.0, 0
                        self._pause_id += 1
                    continue
                self._run = 0
                self._pause += VAD_CHUNK / RATE
                if self._heard and self._next < len(self._checks) and self._pause >= self._checks[self._next][0]:
                    after, sure = self._checks[self._next]
                    self._next += 1
                    self._pool.submit(self._ask, self._audio.copy(), after, sure, self._turn_id, self._pause_id)

    def _ask(self, audio, after, sure, turn_id, pause_id):
        try:
            p = float(self._turn.run(None, {"input_features": features(audio)})[0][0][0])
        except Exception:  # never take the satellite down over this
            _LOGGER.exception("end of turn: Smart Turn failed")
            return
        with self._lock:
            current = turn_id == self._turn_id and pause_id == self._pause_id and not self._done
            finished = current and p > sure
            if finished:
                self._done = True
        _LOGGER.info("end of turn: %.2f s pause, %.0f%% sure (needs %.0f%%)%s", after, p * 100, sure * 100,
                     ", ending the turn" if finished else ("" if current else ", too late, talking again"))
        if finished:
            self._on_finished(p, after)


def load(on_finished):
    """An EndOfTurn if LVA_END_OF_TURN points at the models and onnxruntime is there, otherwise None."""
    model_dir = os.environ.get("LVA_END_OF_TURN")
    if not model_dir:
        return None
    try:
        return EndOfTurn(model_dir, on_finished)
    except Exception:
        _LOGGER.exception("end of turn: off, couldn't load the models from %s", model_dir)
        return None
