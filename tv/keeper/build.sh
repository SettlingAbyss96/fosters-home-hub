#!/usr/bin/env bash
# Builds the keeper into build/keeper.apk, on the Hub (host/79-android.sh puts the tools there).
# tools/tv-keeper.sh runs it. No Gradle and no SDK: javac against the stand-ins in stubs/, R8's D8
# for the dex, aapt for the package, zipalign, and apksigner with the Hub's own key
set -euo pipefail
cd "$(dirname "$0")"
tools=/opt/ha-hub/android
framework=$(dpkg -L android-framework-res | grep -m1 'framework-res.apk$')
rm -rf build && mkdir -p build/stubs build/classes build/dex
javac --release 8 -nowarn -Xlint:-options -d build/stubs $(find stubs -name '*.java')
javac --release 8 -nowarn -Xlint:-options -cp build/stubs -d build/classes $(find src -name '*.java')
java -cp "$tools/r8.jar" com.android.tools.r8.D8 --release --min-api 23 --no-desugaring \
  --output build/dex $(find build/classes -name '*.class')
aapt package -f -M AndroidManifest.xml -I "$framework" -F build/unaligned.apk
(cd build/dex && aapt add ../unaligned.apk classes.dex >/dev/null)
zipalign -f -p 4 build/unaligned.apk build/aligned.apk
apksigner sign --ks "$tools/keeper.jks" --ks-pass "file:$tools/keystore-pass" --out build/keeper.apk build/aligned.apk
apksigner verify build/keeper.apk
echo "built keeper.apk, $(stat -c %s build/keeper.apk) bytes"
