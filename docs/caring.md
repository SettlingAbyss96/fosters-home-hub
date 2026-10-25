# Do you care?

*Level 3 to 4. The math behind what Jarvis decides is worth saying: surprise, attention, repetition,
the psychology of market news, and the model the digest uses to guess whether you'll care. The code
is `hub/hub_digest.py`, the knobs are in `hub/digest.toml` (from `hub/digest.example.toml`), and
what it does day to day is in [routines.md](routines.md#when-something-gets-said-again).*

## What a briefing is for

Take a Friday when the S&P 500 closes down half a percent and the 10-year Treasury yield rises 4
basis points. Neither is worth a word in the welcome home, because with the S&P's normal day around
0.7%, half a percent is about three quarters of one, and 4 basis points is under a normal day for
the 10-year. A 1.8% drop on a day when yields jump 12 basis points leads the whole thing, with the
reason. Same two series, same two numbers to look at, and the only difference is how far each one
moved against its own idea of normal.

The welcome home is about 25 seconds of speech, somewhere around 70 words, and everything in the
digest is competing for those words. That makes it a channel with a capacity, which is a very
controls-shaped problem. A sensor network that can't send every reading has to decide which readings
are worth the bandwidth, and the answer it usually lands on is the reading that tells the receiver
something it couldn't have predicted. This page is about what "worth the bandwidth" means, where the
math comes from, and what the digest actually computes.

The model makes a prediction every time it picks something, and every "more like that" or "less like
that" is a label, so after a couple of months there's enough to draw a calibration curve and see
whether the things it scores high are really the things you like. That's the measurement still
missing.

## Three ways to measure news

Picture what you believe about the S&P as a bell curve of where it'll close tomorrow. A normal day
nudges the curve a little. A crash shoves the whole thing sideways and widens it. Three fields give
three different numbers for that shove, and each one catches something the others miss.

Information theory measures how unlikely the event was. Shannon's self-information of an outcome
with probability $`p`$ is

```math
I(x) = -\log_2 p(x)
```

so a one-in-a-thousand day carries about 10 bits and a coin flip carries 1. It's clean, but it only
looks at the event, and a rare event you don't care about is still rare.

[Itti and
Baldi](https://proceedings.neurips.cc/paper_files/paper/2005/file/0172d289da48c48de8c5ebf3de9f7ee1-Paper.pdf)
measured surprise as how far the observation moves the observer's beliefs, the Kullback-Leibler
divergence from prior to posterior:

```math
S(D) = \mathrm{KL}\left(P(M \mid D)\ \|\ P(M)\right)
```

That's the most useful of the three here, because it's about the listener rather than the event. In
their experiments on people watching television and video games, 72% of gaze shifts went to places
more surprising than average, and 84% when every subject looked at the same spot. Attention follows
belief updates. For a belief that's a bell curve one normal day wide, a move of $`z`$ normal days
shifts it by a KL divergence of $`z^2/2`$ nats, so surprise grows with the square of the move
measured in its own normal days, and that's where the z-scores in the digest come from.

Decision theory measures what the news changes. Howard's value of information says a piece of news
is worth the improvement in the decision you'd make with it, and the [expected value of perfect
information](https://en.wikipedia.org/wiki/Expected_value_of_perfect_information) can never be
negative, because you can always ignore it. The flip side is what makes it useful here. News that
can't change anything you'd do is worth exactly zero to a decision maker, and that's the honest
argument for proximity, since a recall on your car or a change to a module your printer uses can
change what you do this week and a recall on someone else's car can't.

Economics measures the cost.
[Sims](https://collaborate.princeton.edu/en/publications/implications-of-rational-inattention/)
modelled attention as a channel with finite Shannon capacity, so a person who can only process so
many bits chooses which to process, and that's rational inattention. The welcome home is literally
that channel, about 70 words of it.

## How people actually react to it

Attention without relevance costs money. [Barber and
Odean](https://ideas.repec.org/a/oup/rfinst/v21y2008i2p785-818.html) found individual investors are
net buyers of whatever grabbed attention that day, through news, unusual volume or an extreme
one-day move, and the stocks they bought on those days tended to underperform the ones they sold.
That's the biggest risk in building anything like this. A system that only measures how loud
something is turns into a glitter machine, so loudness only ever gets to multiply relevance, never
replace it.

[Soroka, Fournier and
Nir](https://cris.huji.ac.il/en/publications/cross-national-evidence-of-a-negativity-bias-in-psychophysiologic/)
ran 1,156 people in 17 countries through real BBC stories with sensors on their fingers, and the bad
news showed up in the body, with negative stories raising skin conductance and heart rate
variability more than positive ones, although the spread between people was large and some countries
showed no significant effect. Prospect theory puts a number on the money version, a loss weighing
about 2.25 times a gain of the same size in [Tversky and Kahneman's 1992
fit](https://psych.fullerton.edu/mbirnbaum/psych466/articles/Tversky_Kahneman_JRU_92.pdf), and a
later meta-analysis puts the average nearer 1.96.

Markets agree for a less emotional reason. Engle and Ng's [news impact
curve](https://www.nber.org/papers/w3681.pdf) is asymmetric, a bad shock raises future volatility
more than a good one of the same size, which is why the digest weighs a fall in the S&P, the Nasdaq,
small caps and high yield at 1.25 times a rise in the example. It's 1.25 on purpose and not 2.25.
The tilt is there because a fall says more about what comes next, not to make a red day sound worse.

Investors checking their portfolios less when markets fall is what [Karlsson, Loewenstein and
Seppi](https://www.cmu.edu/tepper/faculty-and-research/assets/docs/ppaper-61264983153898-ostrich-effect-1.pdf)
called the ostrich effect, and Jason Zweig's summary of their Scandinavian data puts it at 50% to
80% less. A later study of active online investors found the opposite, a "meerkat effect", so it
isn't universal, but it's exactly the habit a briefing should work against.

Earnings announced on a Friday got a 15% weaker immediate response and a 70% stronger delayed one in
[DellaVigna and Pollet's](https://www.nber.org/papers/w11683) data, which they read as weekend
inattention delaying the reaction without removing it, though Michaely and coauthors argue fixed
effects make the Friday effect disappear. Either way it's why the morning briefing carries the
night, since things that land while you're not looking still matter when you are.

Tone isn't information.
[Tetlock](https://www.columbia.edu/~pt2238/papers/Tetlock_Media_Sentiment_JF.pdf) found that
pessimism in the Wall Street Journal's "Abreast of the Market" column predicted downward pressure on
prices followed by a reversion to fundamentals, so gloomy writing moves prices for a while and then
the facts win. The digest measures moves and lets the headlines explain them, and it never measures
the mood of the coverage.

[Bordalo, Gennaioli and
Shleifer](https://scholar.harvard.edu/sites/scholar.harvard.edu/files/shleifer/files/salience_theory_of_choice_under_risk_qje.pdf)
built salience theory on contrast and the Weber-Fechner law, so differences count relative to their
level and with diminishing sensitivity, the way a gap between 11 and 10 feels bigger than one
between 16 and 15. A 1% move means nothing on its own and everything once it's divided by what the
series usually does.

## Hearing it again

The question worth asking first is why the third time you hear something feels like nagging, when a
follow-up on something that got worse doesn't. Psychology has had the answer since 1966, when
Thompson and Spencer listed the properties of habituation: a repeated stimulus gets a weaker and
weaker response, the response comes back on its own if the stimulus stops for a while, and a strong
new stimulus brings it back straight away, which they called dishabituation. Their list has been
argued over and [refined since](https://pmc.ncbi.nlm.nih.gov/articles/PMC2754195/), but those three
hold up, and the digest copies them directly. Habituation to a shelf or a source is a sum over what
you've heard lately,

```math
H = \sum_{i} e^{-\Delta t_i / \tau}, \qquad \tau = 1.5\ \mathrm{days}
```

subtracted from the log-odds at 0.7 per unit. Two items from the same newsletter yesterday cost it
about half its odds today. Leave it alone and it recovers by itself, and anything severe or
surprising enough outweighs it, which is dishabituation.

Saying something again is a separate rule, and it comes from networked control. Send-on-delta
transmits a measurement only when it leaves a deadband around the last value sent, so every series
and story keeps what it was when you last heard it. A market series comes back when today's move, or
its drift since then, crosses the deadband in units of its own normal day. For drift the digest runs
a two-sided [CUSUM](https://en.wikipedia.org/wiki/CUSUM) on the standardised daily changes $`z_n`$,
Page's 1954 detector for a shift that no single sample shows:

```math
S^+_n = \max\left(0,\ S^+_{n-1} + z_n - k\right), \qquad S^-_n = \max\left(0,\ S^-_{n-1} - z_n - k\right)
```

with $`k = 0.5`$, which tunes it for a one normal-day shift, and a signal at $`h = 4`$. Day after
day at 0.8 of a normal day down never trips the daily deadband, and the CUSUM gets there in about
two weeks.

Stories spread in bursts, and the burst is the signal. Crane and Sornette modelled YouTube views on
about half a million videos as a Hawkes process, where each view raises the chance of the next,

```math
\lambda(t) = \mu + \sum_{t_i < t} \alpha\, e^{-\beta (t - t_i)}
```

and found the shape of the decay tells an outside shock from word of mouth, which [a later
simulation](https://arxiv.org/pdf/0907.3864) mostly confirmed. Shiller's narrative economics treats
economic stories the same way, as epidemics. The digest uses the crude version, a story told
yesterday comes back as a follow-up when at least two more sources pick it up, and a story nobody's
told you yet gets a social boost from every other source already carrying it. A fork comes back when
its stars have doubled and gained at least 150, two days on at the earliest, so a fork told at 500
stars comes back once it passes 1,000.

## The care model

From the controls side this is a state estimator feeding a selector, and the state is how much you'd
want to hear each thing. Recommendation systems already score articles this way, as the log-odds of
a click, and the digest borrows the shape and changes every input. For a candidate $`x`$:

```math
\eta(x) = \ln w_s + \mu_s + \mu_{sh} + b_p\,p(x) + b_s\,\sigma(x) + b_v\,v(x) - \ln 2\,\frac{a(x)}{t_{1/2}} - b_h\,H_s
```

Here $`w_s`$ is the weight the source has in `digest.toml`, the prior. $`\mu_s`$ and $`\mu_{sh}`$
are what the house has learned about the source and the shelf since. $`p(x)`$ is proximity from 0 to
1, how close it comes to your own things, which is a list of words with weights in `[mine.words]`
(your printer, your car, your devices) plus every module your `printer.cfg` uses in `[mine]
modules`, so a Kalico commit titled `quad_gantry_level: ...` counts as touching a Voron 2.4 and one
titled `lis2dw: ...` doesn't. There's a catch. Every post on r/VORONDesign says "Voron" and every
one on r/klippers says "Klipper", so proximity would fire on all of them and mean nothing, which is
Shannon again, since a word that's nearly certain to appear carries nearly no information. A word
now counts in proportion to how unusual it is for its source, $`w \cdot (1 - f)`$ with $`f`$ the
share of that source's items that mention it, once the source has at least four items to judge by.
On r/VORONDesign "Voron" is worth about nothing, and one Hackaday piece that mentions it gets the
full weight. $`\sigma(x)`$ is social velocity, the log of stars a day, Hacker News points and other
sources on the same story. $`v(x)`$ is severity, 1 for a safety recall and 0.5 for a security hole
or a breaking change. The age term halves the odds every half-life, and $`H_s`$ is habituation to
the source.

With $`b_p = 1.5`$, a story that touches your printer gets $`e^{1.5} \approx 4.5`$ times the odds of
an identical one that doesn't. In a test with two otherwise matched items it wins about 82% of the
time. Severity at $`b_v = 2`$ is $`e^2 \approx 7.4`$ times, social at $`b_s = 0.5`$ means a repo
gaining 50 stars a day is about 3.3 times, and those coefficients are guesses, which is the honest
state of it, set where they feel right and written down in `[care]` so they can be tested.

Within a shelf the digest picks with probability proportional to $`e^\eta`$, a softmax, so the top
item usually wins without always winning. Shelves are drawn the same way from their weights, the
learned shelf interest and habituation. A few things skip the line entirely. A new safety recall on
your car comes first and is said once. A market move past the deadband goes in ahead of the format's
items and leads from 2.5. A follow-up takes a slot of its own. Those are interrupts, the way an
alarm input overrides a filter.

It's simpler than hand-tuned shelf penalties, which is the nice surprise, since the habituation sum
does that job with one constant and a reason.

## Learning what you like

The interest terms $`\mu`$ are a Kalman filter, one per source and one per shelf. Your interest in
something is treated as a level that drifts slowly, and every "more like that" or "less like that"
is a noisy measurement of it:

```math
\mu_k = \mu_{k-1} + w, \quad w \sim \mathcal{N}(0, q\,\Delta t) \qquad\qquad y_k = \mu_k + v, \quad v \sim \mathcal{N}(0, r)
```

with $`y = +1`$ for liked and $`-1`$ for not. The update is the usual one, $`K = P/(P + r)`$, then
$`\mu \leftarrow \mu + K(y - \mu)`$ and $`P \leftarrow (1 - K)P`$, and between updates $`P`$ grows
by $`q`$ a day. Starting from $`P_0 = 0.15`$ with $`r = 1`$, the first like moves a source by 0.13,
about 14% more odds, and ten in a row take it to 0.6. With $`q = 0.01`$ a day its certainty fades as
well, because interests drift, so after a quiet month the next remark moves it at least as far as
the first one did.

The feedback is spoken. "More like that", "I liked that", "less like that" or "that was boring"
after a welcome or a morning briefing reaches the digest, which moves every source and shelf in that
kit. Each draw samples $`\tilde\mu \sim \mathcal{N}(\mu, P)`$ in place of using $`\mu`$ itself,
which is Thompson sampling. It keeps trying the things it's unsure about, so a source you went quiet
on still gets the odd chance to win you back. Yahoo's front page is where both ideas got tested at
scale. [Li, Chu, Langford and
Schapire](https://microsoft.com/en-us/research/wp-content/uploads/2016/02/p661.pdf) treated news
recommendation as a contextual bandit over 33 million events, and [Chapelle and
Li](https://papers.nips.cc/paper/2011/hash/e53a0a2978c28872a4505bdb51db06dc-Abstract.html) found
Thompson sampling highly competitive on the same kind of problem.

Feedback is the scarce part. At one remark a day it takes a couple of weeks for a habit to show, and
a remark after a kit with four items credits all four, so the noise term is set high on purpose.
Where it stops holding is the stuff you hear elsewhere. The digest has no way to know you already
read the OrcaSlicer release notes on your phone, so it'll happily tell you again.

## Across the shelves

The trouble with most news feeds is that they optimise for the click, and the click is mostly
recency and loudness, which is exactly the glitter Barber and Odean warned about. Each shelf here
gets the same score with different evidence behind it.

Markets get measured moves and nothing else. Eleven series in the example, from the S&P 500 to
Bitcoin, each against its own normal day, the downside tilt on the risk assets, the CUSUM for drift,
and the FT's and CNBC's headlines for the why. A quiet market stays quiet and a bad day leads, with
its reason. Howard says news is worth what it changes, and nothing changes more than your own
positions, so the tickers you hold make sense as series of their own, weighted above the indexes.

AI is the loudest shelf by a distance, so habituation does the most work there. Coverage velocity
across Simon Willison, Import AI, Interconnects and the forums decides what's big, and stars a day
decide which new repos are real.

3D printing is where proximity matters most. Kalico and Klipper commits that touch your printer's
modules are marked, OrcaSlicer and Bambu Studio releases come as "what changed since you last
heard", and a fork like the wave-overhang one gets a follow-up only once it has properly taken off.

The car has the sharpest rule. NHTSA's recall API takes a make, a model and a year, and the example
has a recalls source to fill in with yours. A new recall is said once, ahead of everything, and one
over a year and a half old is history. Electrek and InsideEVs fill the rest of the shelf, and your
car's name belongs in the proximity words.

The house is the one shelf with a perfect proximity score, because it's all yours. The overnight log
counts repeats, drops anything you've already dealt with, and last night's sleep is compared with
your month only past a deadband.

The open question is how fast interest really drifts. $`q = 0.01`$ a day is a guess, and the data to
check it is a few months of "more like that" away.
