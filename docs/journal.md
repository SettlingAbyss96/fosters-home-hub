# How did it go?

*Level 2 to 3. Jarvis asking about the day once you're home: how the house works out where you were
from the phone, what kind of place it was, what's worth a question, and what happens to the answer.
The code is `hub/hub_journal.py`, the questions are in `hub/journal.example.toml` (copy it to
`hub/journal.toml` to make them yours), and the Home Assistant side is `packages/journal.yaml`.*

The idea is a small journal that mostly writes itself, one question at a time. Back from work,
Jarvis asks how work went. Back from a cafe you hadn't been to before, it asks what the place was
like, and after a restaurant, how the food was. Whatever you say goes in the journal with the date
and the place, the last few show on the Routines page, and "what's in my journal today" reads them
back. It's quiet most of the time on purpose. For someone who works on site, a normal fortnight is a
question most weekdays, nearly all of them about work, with the odd new restaurant or shop in
between.

## Where you stayed

A phone's GPS is good to about 5 m outdoors, and on the move the companion app reports a new
position every few minutes, so `person.resident` is good enough to find the stays in. iOS only
reports when the phone has moved a few hundred metres or crossed a zone, though, which means a stay
is often a single position and then nothing until the next place. The journal takes that position as
the start of a stay and works out the end from the next one. If the next position is $`d`$ metres
away, the phone left about as long before it as the drive took:

```math
t_{\mathrm{end}} = \max\left(t_{\mathrm{last}},\ t_{\mathrm{next}} - \frac{d}{v}\right), \qquad v = 10\ \mathrm{m/s}
```

Positions within 120 m of each other are one place, anything under 8 minutes is a stop and not a
stay, and anything within 350 m of home is home, because the GPS wanders around a building. A zone
in Home Assistant is a place of its own, and work is one: make a zone called Work (Settings, then
Areas, labels and zones) big enough for the whole site, since a campus or a big office can spread
over most of a kilometre and no single point on a map covers it. 600 m is a reasonable start for one
that size.

## What kind of place it was

The first thing to know about a stay is what kind of place it was, and the phone doesn't say.
Reverse geocoding gives an address, a ZIP code or a highway most of the time and an area of interest
now and then, a park or a market or a campus, but never "cafe". OpenStreetMap does, so once a month
the journal downloads every named cafe, restaurant, shop, gym, park, museum, petrol station, clinic
and the rest in a box around home. Around a city a 20 km box is somewhere over ten thousand places
and under a megabyte. The places that never get a question stay on the map too, so a stay at the
pharmacy isn't put down to the cafe next door.

Picking the place is a guess, so it's made as one. Every place within 110 m gets a likelihood from a
round Gaussian whose spread is the position's accuracy $`a`$ and the place's size $`s`$ together, 10
m for a shop's node and 35 m for the centre of a building:

```math
L_i = \frac{1}{2\pi\sigma_i^2}\exp\left(-\frac{d_i^2}{2\sigma_i^2}\right), \qquad \sigma_i^2 = a^2 + s_i^2
```

Somewhere that isn't on the map gets a share of its own, $`L_0 = 1/(\pi R^2)`$ with $`R = 110`$ m,
as if it could be anywhere in reach. The best place has to come out more likely than not, $`L_i /
\sum_j L_j \ge 0.5`$, or the stay goes down as its area of interest or as nowhere in particular. A
cafe 8 m from a good fix, with nothing else close, comes out above 0.9. A dozen shops within 60 m of
a fix that's 40 m off indoors leave none of them anywhere near a half, so that stay gets no name and
no question, and that's the right way for it to fail, since a wrong guess means asking about the
wrong shop, or a clinic. Naming a place like that by voice ("that's my gym") would be the next thing
to build, so it gets its questions after all.

## What gets asked

Asking about everything would go wrong fast. A question after every trip to the supermarket is the
house nagging, the same habituation problem the digest has
([caring.md](caring.md#hearing-it-again)), so what gets asked comes down to novelty. Work gets a
question once a day, however ordinary the day. Anywhere new that's a cafe, a restaurant, a bar, a
shop, a gym, a park or a museum gets one. Somewhere familiar only gets asked about again after its
kind's `again_days` in the questions file, 14 for a cafe or a restaurant, 30 for a shop, 7 for the
gym, and a film or a concert every time since every one is different. A supermarket gets asked about
the first time and never again. A doctor's, a pharmacy, a place of worship, a petrol station, a bank
and anywhere with no name on the map never get a question, and that last one is mostly other
people's houses.

Two places at most go in one question, work first, then anywhere new, then the longest stay, so it
comes out as "How was work? And {name}, how was the ambiance?". Once you've answered, the rest of
the trip is dropped, so last night's shop doesn't turn up tomorrow. The questions are templates,
never one of the last three used for that kind, and none of them says how long you were anywhere.

The asking happens after the welcome home, through `assist_satellite.ask_question`, which plays the
question and stops the pipeline at speech to text, so the answer goes into the journal and nowhere
near the cloud agent. A finished sentence ends the turn on this satellite ([voice.md](voice.md)) and
15 seconds is the most it listens for, while a journal answer is often two sentences, so it asks
"Anything else?" once or twice until you say no. "Not now" is an answer, silence is too, and either
way that trip doesn't come round again. Not with guests in, not at night and not with Jarvis muted.
"Note" and anything at all adds a line whenever, and "ask me about my day" asks now, even with
"Jarvis asks how it went" switched off.

Silence turned out to be the fiddly one. Home Assistant logs it as an error, and the house's error
alert would send "something broke" to the phone every evening nobody felt like talking, so the alert
lets that one go.

## What stays in the house

Asking how the cafe was means the house knowing you were at a cafe, which is exactly the kind of
thing worth keeping in. Positions never leave the house. The map comes down as a box around home, so
OpenStreetMap learns roughly which city you live in and nothing about where you've been, the place
matching runs on the Hub, and the questions are templates written there, so no model sees the place
names either. The answers are kept twice, in the Hub's SQLite and as a line in
`/config/journal/journal.md`, which goes with Home Assistant's backups.

It stops holding past the edge of the box. A trip out of town has no map, so the only names it gets
there are the phone's areas of interest, a park or a market, and a cafe in a town you're visiting
goes unasked. The box grows by itself to cover where the phone has been, up to 40 km, but a weekend
away is never going to be inside it.
