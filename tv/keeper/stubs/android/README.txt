Stand-ins for the few Android framework classes the keeper uses, so it compiles without android.jar
(and so without the Android SDK and its licence). Only the shape matters: the signatures here match
Android's own exactly, javac checks the app against them, and on the TV the real classes run. None of
this goes into the app (build.sh dexes only src/). Adding a call to the app means adding its exact
signature here.
