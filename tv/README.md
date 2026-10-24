# The Fire TV

Everything here goes down the ADB connection Home Assistant already has to the TV (port 5555, from
`fire_tv.address` in `house.toml`), with `tools/tv.py`, so nothing new has to be allowed on the TV
after that first "Allow USB debugging?". All of it is optional, and the TV module works without it.

## The debloat

A Fire TV ships with Amazon's content recognition (it watches what's on screen, HDMI included), ad
and recommendation feeders, an advertising ID, telemetry uploads, tutorials and a row of preloaded
apps. [CleanYourTV](https://github.com/Gathin23/cleanyourtv) (MIT) keeps a list per TV model of what
can be switched off safely. `debloat.example.txt` is theirs for a Hisense Fire TV (AFTCIBFBD1, Fire
OS 8): copy it to `tv/debloat.txt` (yours, not committed), check their list for your model, and
keep anything you use. Packages are disabled for user 0, nothing is uninstalled, and the state from
before goes into `tv/before.txt` the first time, so a restore puts back exactly what was there.

```bash
python tools/tv.py check     # what's drifted (a Fire OS update brings packages back), exit 1 if any
python tools/tv.py apply     # the list again
python tools/tv.py restore   # back to before.txt
```

Fire OS keeps its own home screen whatever anyone does, so Amazon's own promotions on it stay. The
list's private DNS line (AdGuard's resolver) takes out the third-party ad in Home's banner, at the
price of AdGuard seeing every name the TV looks up. Leave the ambient pictures package on if you
use the house's "TV off", which is the TV's ambient mode.

## The keeper

The house's connection depends on ADB debugging staying on, and a Fire OS update or a reset can
switch it off, after which nothing over the network can switch it back: it takes the remote and the
Developer Options menu. `keeper/` is a 12.6 KB app with no screen and no network permission that
runs on the TV at boot and every 15 minutes, and puts back two settings if anything changed them:
`adb_enabled` to 1, and `adb_allowed_connection_time` to 0, so Home Assistant's approved key never
expires (Android forgets one after 7 days without a connection, which a week away with the TV
unplugged would hit). It only ever puts back what was already there.

It writes those with WRITE_SECURE_SETTINGS, which only ADB can grant. The Hub builds it
(`host/79-android.sh` for the tools: Debian's JDK and Android packages plus Google's R8, pinned),
from the source in `keeper/src` compiled against stand-ins for the dozen Android classes it touches,
so there's no Android SDK and no SDK licence. The signing key stays on the Hub.

```bash
tools/push.sh host/79-android.sh     # once
tools/tv-keeper.sh                   # build it on the Hub, the app lands in tv/keeper/build/
python tools/tv.py install-keeper    # onto the TV, permission granted, started once
```

Network debugging left on is the usual way a TV stays open to the network, which CleanYourTV's own
Remote Access add-on is there to warn about. Here it's on because the house runs on it, and a device
still can't connect without someone accepting its key on the TV screen. The keeper doesn't widen
that, it keeps it from being lost to an update. `tools/tv.py restore` takes it off again.
