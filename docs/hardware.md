# The Hub 500 under Linux

*Level 1 to 2. The box, measured: what's inside, what Linux makes of it, and the quirks.*

What this box actually is once Windows is gone, measured on my unit (model `10V50000US`, BIOS
`M23KT31A` from 2022-12-30) from a Debian 13.7 live session, kernel 6.12. Lenovo stopped
developing for the Hub 500 in October 2025, so nobody is coming to fix the firmware. Whatever it
does now, it does forever.

## What's inside

| | |
|---|---|
| **CPU** | Intel Core i5-7500T, 4 cores, 2.7 to 3.3 GHz, VT-x on |
| **RAM** | 2 × 4 GB DDR4-2400 SO-DIMM (Samsung `M471A5244CB0-CRC`), both slots full |
| **SSD** | Samsung PM961 128 GB NVMe (`MZVLW128HEGR`) |
| **Display** | 11.6" 1920 × 1080, Synaptics `SYNA7508` touch (`06CB:16EF`) on I2C |
| **Audio** | Lenovo "USB Audio" `17ef:a017`: stereo speakers, 2-mic array, LED ring |
| **HDMI in** | Lenovo UVC capture `17ef:7219`, with its own stereo audio input |
| **Network** | Intel I219-LM gigabit (`enp0s31f6`), Intel 8265 Wi-Fi and Bluetooth |
| **Firmware** | UEFI, Secure Boot on, no supervisor password on mine |

## Touch

The touch controller hangs off the chipset's LPSS I2C controller and binds to `i2c_hid_acpi`.
Debian's stock kernel handles it without any help. Home Assistant OS doesn't ship those drivers,
which is the main reason HAOS runs in a VM here instead of on the bare metal. Touch also works in
the BIOS setup screen, oddly enough.

## Audio

Everything audible lives on one USB device with two PCM devices:

| ALSA | What | Formats |
|---|---|---|
| `Audio,0` playback | Internal speakers | 48 kHz stereo, S16 or S24 |
| `Audio,0` capture | Internal mic array | 48 kHz stereo, S16 or S24 |
| `Audio,1` | Probably the 3.5 mm headset jack (its capture control has +30 dB of gain) | Same |
| `UAC,0` capture | HDMI input audio | 48 kHz stereo, S16 |

Other people have seen WirePlumber pick the HDMI capture card as the default mic and record silence.
On mine it picked the right one, but I'd still pin it by name rather than trust the default.

The speaker DSP ignores USB volume requests (per the community notes below), so volume is software
only. The LED ring is a HID interface on the same USB device and only does white, green and red.

## The mics

They're real, separate capsules. With broadband noise from the speakers the left/right
correlation is about 0.98, and 0.85 on speech, so it's not one signal copied twice.
Noise from the left speaker alone lands about 1.8 dB louder on the left mic, and the right speaker
about 1.4 dB louder on the right one.

There's no echo cancellation on the mic stream, either. White noise at -20 dBFS through the speakers
shows up at -44.5 dBFS on the mics, flat for the whole four seconds. An echo canceller would pull
that down as it adapts, and nothing moves. The mixer has an `Extension Unit` switch that looked
promising, but the device refuses to turn it on. My guess is the echo cancelling lived in the
Windows driver or the Teams stack, not in this DSP's USB interface. Not a disaster: PipeWire's
WebRTC echo canceller does it in software, about 47 dB of it, and since the speaker and the mics
share one USB clock there's no drift between them to fight.

And the mics are quiet. With nothing playing, the floor is about -70 dBFS (fan included, at idle).
Talking normally from 3 to 4 m, speech peaks at -50 to -55 dBFS in 0.25 s windows, so roughly
15 to 20 dB above the floor, with the `Mic` capture control already at its maximum (67/67, 0 dB).
After PipeWire's echo canceller and its gain, `hub_mic` has my voice around -42 dBFS over a floor
near -89, which the wake word and speech to text are happy with (Parakeet with a little help,
[voice.md](voice.md)).

![Dot plot in dBFS. Raw mics: room noise -70, me at 3 to 4 m -55 to -50, the Hub's own speaker -45.7. hub_mic: the speaker -93.3, room noise -89, me -42](figures/hardware-levels.svg)

*The same mics before and after the echo canceller.*

## Display, sensors, fan

The USB audio device's consumer-control HID ("Generic USB Audio Consumer Control") claims to be a
pointer, so any compositor draws a mouse cursor that touch never moves. A udev rule sets
`LIBINPUT_IGNORE_DEVICE` on it.


There's no `/sys/class/backlight`. The panel (AU Optronics, `DP-1`) takes DDC/CI on `/dev/i2c-5`
once `i2c-dev` is loaded, though the bus number isn't promised to stay put, so code looks it up.
Brightness is VCP `0x10`, 0 to 100, and it comes up at 100. Power is VCP `0xD6`: writing 4 puts it
in standby in about 0.13 s, writing 1 brings it back in about 0.6 s. ddcutil 2.2 prints "Both
--verify and --noverify specified" if you pass `--noverify`, then does it anyway.

There's no light sensor, so no phone-style auto brightness. What there is:

- The PIR is an IIO device called `prox`, sitting on a GigaDevice sensor hub (`28e9:028c`,
  which calls itself "USB Sensor BIOMETERIC", spelling and all). It reads a constant 0 until a
  sampling rate is written. On mine that write took 10.2 s, the first read 20.7 s, and every read
  after that about 0.1 s, returning a plain 0 or 1 for movement. The same hub has two more HID
  sensor collections (`HID-SENSOR-200001` and `HID-SENSOR-10000`) I haven't looked into
- The fan ramps up and down with load on its own, so the BIOS has it

## Sources

- [jethac/thinksmart-hub-hal](https://github.com/jethac/thinksmart-hub-hal): Debian 13 support
  library, and the best map of the weird parts (DDC/CI, the PIR, the DSP volume)
- [Radeon24/lnxlink-thinksmart-hub-500](https://github.com/Radeon24/lnxlink-thinksmart-hub-500):
  LED ring, brightness, volume and presence as Home Assistant entities over MQTT
- [Home Assistant community thread on the Hub 500](https://community.home-assistant.io/t/lenovo-thinksmart-hub-500/916239):
  the HAOS touch problem and the custom kernel workaround
- The raw numbers came from [`probe/hub500-probe.sh`](../probe/hub500-probe.sh) and
  [`probe/audiotest.py`](../probe/audiotest.py)
