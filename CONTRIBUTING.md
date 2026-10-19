# Contributing

Fixes, "this step didn't work on my Hub", and support for devices I don't have are all welcome.
Open an issue, or a pull request if you've got the fix.

## Keep your house out of it

Before anything else: nothing from your own house goes in a pull request. Your `house.toml`,
`about.local.md` and `parakeet-words.local.txt` are ignored by git for that reason, and so is
everything made from them. Run this before you push, and read your diff too:

```bash
python tools/privacy_check.py
```

## How the packages are written

- Standard names only ([docs/devices.md](docs/devices.md)). A package reads `vacuum.robot_vacuum`,
  never the name your vacuum came with. If a new device needs a new standard name, add it to the
  table there and to `[devices]` in `house.example.toml`
- Every light command goes through `script.light_set`, so the arbiter knows who asked
  ([docs/control.md](docs/control.md))
- Lights are found by label (layer and job), never listed by entity id
- Optional devices are allowed to be missing: guard any action on one, and let templates fall back
  instead of erroring
- Every action that talks to a device has `continue_on_error: true`, so one dead device doesn't stop
  a routine
- A new behaviour that runs by itself gets an `auto_` switch in `packages/controls.yaml` as its first
  condition

## How the docs are written

- Casual first person. Write like you're explaining it to a friend. Opinions are welcome, and so is
  "I'm not sure"
- Explain the why, not just the setting. If a number shows up, say where it comes from, and say
  whose box it was measured on
- Say when something is a guess, and link the paper when something is established
- No em dashes. Use commas, colons, parentheses or a new sentence
- Math in LaTeX: inline in `` $`...`$ ``, display in a ```` ```math ```` block. GitHub refuses
  `\operatorname`, so write `\mathrm{rank}` instead

## Before you push

```bash
python tools/check_docs.py
```

```bash
python tools/privacy_check.py
```

```bash
tools/test.sh
```

The first checks the docs render on GitHub (links, anchors, LaTeX, dashes), the second that nothing
of yours is in the commit, and the third runs the scenario tests on your Hub's test bench
([docs/testing.md](docs/testing.md)). A change to a package should come with a test that would have
failed without it.
