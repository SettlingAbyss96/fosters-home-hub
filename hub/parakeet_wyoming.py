#!/usr/bin/env python3
"""Parakeet speech-to-text as a Wyoming server, so Home Assistant can use it in place of Whisper.

Whisper small took 2.9 s after I stopped talking, every time, however short the question: it
always works on a 30-second window, padded with silence. NVIDIA's Parakeet TDT 0.6B v2 (the int8
export, through sherpa-onnx) takes about 0.37 s on the Hub's CPU for the same clips, and on my own
calibration recordings it got 11.2% of words wrong to Whisper's 12.8% (docs/voice.md has the whole
comparison). Two things make that work, and without them it was worse than Whisper:

  - the house's own words (Jarvis, Roborock, the printer's name, the people you talk about) get a
    boost while it decodes, the way Whisper had them in its prompt. The list is parakeet-words.txt,
    one word or phrase a line (host/76-parakeet.sh merges in parakeet-words.local.txt)
  - the level gets turned up first. The Hub's mics are quiet, my voice peaks around -42 dBFS from
    across the room, and Parakeet cares about that more than Whisper does. Peak at -6 dBFS

  --uri         where to listen (default tcp://0.0.0.0:10310; fenced to the VM by host/76-parakeet.sh)
  --model       the model folder (encoder, decoder, joiner, tokens.txt)
  --words       the house words file
  --boost       how hard to push those words (1.5; 2.5 already made it worse)
  --threads     CPU threads for decoding (2)
"""
import argparse
import asyncio
import logging
import re
import tempfile
from functools import partial
from pathlib import Path

import numpy as np
import sherpa_onnx
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import AsrModel, AsrProgram, Attribution, Describe, Info
from wyoming.server import AsyncEventHandler, AsyncServer

RATE = 16000
PEAK = 0.5  # -6 dBFS
_LOG = logging.getLogger("parakeet_wyoming")
ATTRIBUTION = Attribution(name="NVIDIA", url="https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2")


# The satellite sends a quarter second from before the wake word fired, so the first word isn't
# clipped (host/patches/lva-preroll.patch). Sometimes that brings the end of "Jarvis" along with it
WAKE_TAIL = re.compile(r"^\s*(?:hey[,.]?\s+)?(?:jarvis|jervis|arvis|vis)\b[\s,.!?]*", re.IGNORECASE)


def tidy(text):
    """Parakeet spells some things its own way ("T V" for TV), and the wake word's tail goes"""
    text = WAKE_TAIL.sub("", re.sub(r"\bT\.? ?V\b", "TV", text)).strip()
    return text[:1].upper() + text[1:]


class Listener:
    """One model, one decode at a time."""

    def __init__(self, model, words, boost, threads):
        m = Path(model)
        extra = {}
        if words and Path(words).is_file():
            # sherpa-onnx turns the words into the model's own word pieces with a sentencepiece-style
            # vocabulary. The model ships its pieces in id order, which is the merge order, so the
            # vocabulary is just those with descending scores
            vocab = Path(tempfile.mkdtemp(prefix="parakeet-")) / "bpe.vocab"
            with open(vocab, "w", encoding="utf-8") as out:
                for line in open(m / "tokens.txt", encoding="utf-8"):
                    parts = line.split()
                    if len(parts) == 2 and not parts[0].startswith("<"):
                        out.write(f"{parts[0]}\t-{parts[1]}\n")
            extra = dict(hotwords_file=str(words), hotwords_score=boost, bpe_vocab=str(vocab),
                         decoding_method="modified_beam_search", modeling_unit="bpe")
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            tokens=str(m / "tokens.txt"), encoder=str(m / "encoder.int8.onnx"), decoder=str(m / "decoder.int8.onnx"),
            joiner=str(m / "joiner.int8.onnx"), num_threads=threads, model_type="nemo_transducer", **extra)
        self.lock = asyncio.Lock()

    def _decode(self, pcm):
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        if audio.size < RATE // 10:
            return ""
        peak = float(np.abs(audio).max())
        if peak > 1e-4:
            audio = audio * (PEAK / peak)
        stream = self.recognizer.create_stream()
        stream.accept_waveform(RATE, audio)
        self.recognizer.decode_stream(stream)
        return tidy(stream.result.text)

    async def text(self, pcm):
        async with self.lock:
            return await asyncio.get_running_loop().run_in_executor(None, partial(self._decode, pcm))


INFO = Info(asr=[AsrProgram(
    name="parakeet", description="Parakeet TDT 0.6B v2 (local)", version="0.6b-v2", installed=True,
    attribution=ATTRIBUTION,
    models=[AsrModel(name="parakeet-tdt-0.6b-v2-int8", description="Parakeet TDT 0.6B v2, int8", version="2",
                     installed=True, attribution=ATTRIBUTION, languages=["en"])])])


class Handler(AsyncEventHandler):
    def __init__(self, listener, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.listener = listener
        self.convert = AudioChunkConverter(rate=RATE, width=2, channels=1)
        self.pcm = bytearray()

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            await self.write_event(INFO.event())
        elif Transcribe.is_type(event.type) or AudioStart.is_type(event.type):
            self.pcm = bytearray()
        elif AudioChunk.is_type(event.type):
            self.pcm += self.convert.convert(AudioChunk.from_event(event)).audio
        elif AudioStop.is_type(event.type):
            secs = len(self.pcm) / (2 * RATE)
            text = await self.listener.text(bytes(self.pcm))
            _LOG.info("%.1f s of speech: %r", secs, text)
            await self.write_event(Transcript(text=text).event())
            self.pcm = bytearray()
            return False
        return True


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default="tcp://0.0.0.0:10310")
    ap.add_argument("--model", default="/opt/ha-hub/parakeet/model")
    ap.add_argument("--words", default="/usr/local/lib/ha-hub/parakeet-words.txt")
    ap.add_argument("--boost", type=float, default=1.5)
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    listener = Listener(args.model, args.words, args.boost, args.threads)
    _LOG.info("listening on %s", args.uri)
    await AsyncServer.from_uri(args.uri).run(partial(Handler, listener))


if __name__ == "__main__":
    asyncio.run(main())
