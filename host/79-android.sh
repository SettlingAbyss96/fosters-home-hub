#!/usr/bin/env bash
# What the Hub needs to build the TV's keeper app (tv/keeper), so nothing gets installed on the PC.
# Debian's own packages for the JDK, aapt, zipalign, apksigner and Android's framework resources,
# and Google's R8 (Apache 2.0, from Google's Maven repository) for its D8 dex compiler, which Debian
# doesn't package. Pinned by version and sha256 like everything else. No Android SDK, so no SDK
# licence to accept: the app compiles against a few stand-in classes in tv/keeper/stubs instead of
# android.jar.
# The signing key is made here the first time and stays on the Hub, in /opt/ha-hub/android, never
# in the repo. Keep it: an update signed with a different key won't install over the old app.
# From the PC: tools/push.sh host/79-android.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
dir=/opt/ha-hub/android
r8_ver=8.13.25
r8_sha=0d4f2f68c4fcbc9434eff122f41feb6fb1d98efd2faa530cec1abacab1cea03d

apt-get install -y -qq --no-install-recommends openjdk-21-jdk-headless aapt zipalign apksigner android-framework-res >/dev/null
install -d -o hub -g hub "$dir"
if ! { [ -f "$dir/r8.jar" ] && echo "$r8_sha  $dir/r8.jar" | sha256sum -c --quiet -; } >/dev/null 2>&1; then
  curl -fsSL -m 300 -o "$dir/r8.jar.tmp" "https://dl.google.com/android/maven2/com/android/tools/r8/$r8_ver/r8-$r8_ver.jar"
  echo "$r8_sha  $dir/r8.jar.tmp" | sha256sum -c --quiet - || { rm -f "$dir/r8.jar.tmp"; echo "R8 checksum mismatch"; exit 1; }
  mv "$dir/r8.jar.tmp" "$dir/r8.jar"
  chown hub:hub "$dir/r8.jar"
fi
if [ ! -f "$dir/keeper.jks" ]; then
  umask 077
  head -c 24 /dev/urandom | base64 | tr -d '/+=' >"$dir/keystore-pass"
  keytool -genkeypair -keystore "$dir/keeper.jks" -storepass:file "$dir/keystore-pass" -alias keeper \
    -keyalg RSA -keysize 3072 -validity 36500 -dname "CN=home-assistant-hub tv keeper" >/dev/null 2>&1
  chown hub:hub "$dir/keeper.jks" "$dir/keystore-pass"
fi
framework=$(dpkg -L android-framework-res | grep -m1 'framework-res.apk$')
echo "android build tools: R8 $r8_ver, framework resources at $framework"
