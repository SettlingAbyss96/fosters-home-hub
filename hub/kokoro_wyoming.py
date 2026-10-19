#!/usr/bin/env python3
"""Kokoro text-to-speech as a Wyoming server, so Home Assistant can use it like Piper.

Kokoro (82M parameters, kokoro-onnx with the int8 model) sounds far more natural than Piper and
still runs on the Hub's CPU, at about twice real time. Nobody ships it for Home Assistant yet, so
this is the whole bridge: Home Assistant connects over Wyoming, asks what voices there are, and
sends text; this answers with 24 kHz 16-bit mono audio.

It speaks sentence by sentence. With streaming on (Home Assistant sends the reply as it's being
written), each sentence goes to Kokoro the moment it's complete and its audio goes straight back,
so the first words play while the rest are still being made. That hides most of the 2x.

  --uri         where to listen (default tcp://0.0.0.0:10210; fenced to the VM by host/74-kokoro.sh)
  --voice       default voice (bm_daniel)
  --speed       speaking rate (1.0)
"""
import argparse
import asyncio
import logging
import re
from functools import partial

import numpy as np
from kokoro_onnx import Kokoro
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Attribution, Describe, Info, TtsProgram, TtsVoice
from wyoming.server import AsyncEventHandler, AsyncServer
from wyoming.tts import Synthesize, SynthesizeChunk, SynthesizeStart, SynthesizeStop, SynthesizeStopped

RATE, WIDTH, CHANNELS, SAMPLES_PER_CHUNK = 24000, 2, 1, 2048
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
LANGS = {"a": ("en_US", "en-us"), "b": ("en_GB", "en-gb")}  # Kokoro voice prefix -> (Wyoming, espeak)
_LOG = logging.getLogger("kokoro_wyoming")


class Speaker:
    """One Kokoro model, one synthesis at a time (the CPU only has four threads anyway)."""

    def __init__(self, model, voices, default_voice, speed):
        self.kokoro = Kokoro(model, voices)
        self.default_voice = default_voice
        self.speed = speed
        self.lock = asyncio.Lock()
        self.voices = sorted(v for v in self.kokoro.get_voices() if v[:1] in LANGS)

    def info(self):
        voices = [TtsVoice(name=v, description=v, version="1.0", installed=True, languages=[LANGS[v[0]][0]],
                           attribution=Attribution(name="hexgrad", url="https://huggingface.co/hexgrad/Kokoro-82M"))
                  for v in self.voices]
        return Info(tts=[TtsProgram(name="kokoro", description="Kokoro 82M (local)", version="1.0", installed=True,
                                    attribution=Attribution(name="hexgrad", url="https://huggingface.co/hexgrad/Kokoro-82M"),
                                    voices=voices, supports_synthesize_streaming=True)])

    async def pcm(self, text, voice):
        voice = voice if voice in self.voices else self.default_voice
        lang = LANGS[voice[0]][1]
        async with self.lock:
            audio, _ = await asyncio.get_running_loop().run_in_executor(
                None, partial(self.kokoro.create, text, voice=voice, speed=self.speed, lang=lang))
        return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


class Handler(AsyncEventHandler):
    def __init__(self, speaker, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.speaker = speaker
        self.streaming = False
        self.voice = None
        self.buffer = ""
        self.started = False

    async def _say(self, text):
        text = text.strip()
        if not text:
            return
        # Nothing has played yet, so the wait is all down to this first piece: speak up to its first
        # comma on its own, and the rest of the sentence gets made while that plays. Only for a real
        # clause, four words or more, and never in a list ("Genius, billionaire, playboy,
        # philanthropist" came out in two halves with a gap in the middle)
        cut = text.find(", ", 15)
        if (not self.started and len(text) > 60 and cut != -1 and len(text) - cut > 25
                and len(text[:cut].split()) >= 4 and text.count(", ") < 3):
            await self._say(text[:cut + 1])
            text = text[cut + 2:]
        if not self.started:
            await self.write_event(AudioStart(rate=RATE, width=WIDTH, channels=CHANNELS).event())
            self.started = True
        pcm = await self.speaker.pcm(text, self.voice)
        step = SAMPLES_PER_CHUNK * WIDTH
        for i in range(0, len(pcm), step):
            await self.write_event(AudioChunk(rate=RATE, width=WIDTH, channels=CHANNELS, audio=pcm[i:i + step]).event())

    async def _finish(self):
        if not self.started:  # nothing said, but the client still expects a well-formed reply
            await self.write_event(AudioStart(rate=RATE, width=WIDTH, channels=CHANNELS).event())
        await self.write_event(AudioStop().event())
        self.started = False

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            await self.write_event(self.speaker.info().event())
        elif SynthesizeStart.is_type(event.type):
            start = SynthesizeStart.from_event(event)
            self.streaming, self.buffer = True, ""
            self.voice = start.voice.name if start.voice and start.voice.name else None
        elif SynthesizeChunk.is_type(event.type) and self.streaming:
            self.buffer += SynthesizeChunk.from_event(event).text
            *done, self.buffer = SENTENCE_END.split(self.buffer)
            for sentence in done:
                await self._say(sentence)
        elif SynthesizeStop.is_type(event.type) and self.streaming:
            await self._say(self.buffer)
            self.buffer, self.streaming = "", False
            await self._finish()
            await self.write_event(SynthesizeStopped().event())
        elif Synthesize.is_type(event.type) and not self.streaming:
            # The one-shot request. A streaming client sends one too, for old servers, which is
            # why it's ignored while a stream is open
            syn = Synthesize.from_event(event)
            self.voice = syn.voice.name if syn.voice and syn.voice.name else None
            for sentence in SENTENCE_END.split(syn.text):
                await self._say(sentence)
            await self._finish()
        return True


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default="tcp://0.0.0.0:10210")
    ap.add_argument("--model", default="/opt/ha-hub/kokoro/kokoro-v1.0.int8.onnx")
    ap.add_argument("--voices", default="/opt/ha-hub/kokoro/voices-v1.0.bin")
    ap.add_argument("--voice", default="bm_daniel")
    ap.add_argument("--speed", type=float, default=1.0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    speaker = Speaker(args.model, args.voices, args.voice, args.speed)
    await speaker.pcm("Ready.", args.voice)  # load and warm up before anyone's waiting on it
    _LOG.info("Kokoro ready on %s, %d voices, default %s", args.uri, len(speaker.voices), args.voice)
    await AsyncServer.from_uri(args.uri).run(partial(Handler, speaker))


if __name__ == "__main__":
    asyncio.run(main())
