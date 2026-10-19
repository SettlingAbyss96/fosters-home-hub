# Addresses on the home network

*Level 1. Which devices need a reserved address, and a way to lay the addresses out so a new device
never needs thinking about.*

What I don't like about how most home networks end up is that every address is whatever the router
felt like handing out that day, which is fine right up until something reaches a device by address
and the device moves. Home Assistant's Android TV integration only knows a TV by its IP, and has
no way to change it, so a TV that comes back from a power cut on a new address just sits there
retrying the old one. The fix for that one device is a reservation, and the fix for the next ten is
to decide once how the addresses are laid out.

## What has to be reserved

These are reached by address, so they need to stay put:

| Device | Why |
|---|---|
| The Hub | Home Assistant reaches Kokoro and Parakeet on it by address (`hub.address` in `house.toml`), because a name looked up over mDNS fails now and then, and every failure is a deaf or a mute assistant |
| The Home Assistant VM | the speech engines' fences let in its MAC, the phone's app and HASS.Agent are set up with its address, and `homeassistant.local` is only as good as mDNS |
| A Fire TV | the Android TV integration knows it only by address (`fire_tv.address`) |
| A Klipper printer | Moonraker is added by address (`klipper.moonraker`) |
| A Bambu printer | it's found by discovery, but a fixed address helps when discovery doesn't |

Everything else (Matter devices, the doorbell over HomeKit, phones, laptops, guests) finds itself or
gets found, and can have whatever the router gives it. Phones and laptops mostly use a private,
per-network MAC anyway, so a reservation for one only holds as long as the operating system keeps
that MAC for your network.

The bridge on the Hub (`host/20-bridge.sh`) is pinned to the Ethernet port's own MAC, which matters
here: without that, the bridge takes the lowest MAC among its ports, the VM's virtual NIC is lower,
and the Hub's address would change every time the VM started.

## A layout to borrow

One way to do it, a block of addresses per kind of device, so a glance at an address says what it
is and a new device takes the next free number in its block. In a /24 with the router at the
bottom, something like:

| Range | What goes there |
|---|---|
| `.1` | the router |
| `.2` to `.19` | network gear: access points, switches, mesh points |
| `.20` to `.29` | the server: the Hub, the Home Assistant VM, a backup target later |
| `.30` to `.49` | computers and the workshop: desktops, printers |
| `.50` to `.59` | TVs and media |
| `.60` to `.89` | lights, plugs and switches, if they need addresses at all |
| `.90` to `.99` | appliances, the doorbell, cameras |
| `.100` to `.199` | sensors and DIY: ESPHome boards, a second voice satellite |
| `.200` and up | everything that doesn't need a reservation |

Some routers insist that a reservation falls inside the DHCP pool, in which case the pool has to
start low and cover the blocks too. The router still won't hand a reserved address to anything
else, so the only cost is that an unreserved laptop might one day land in the middle of a block.
Annoying, not broken.

## Moving to it

Reservations only apply when a device next asks for a lease, so after setting them: reboot the Hub
(the VM comes back with it), restart the TV, and let the rest move on their own as their leases run
out. Then the Home Assistant side: put the new addresses in `house.toml` and run
`tools/ha-apps.sh`, which removes the TV's entry for its old address and adds it again at the new
one (the ADB key survives, so the TV doesn't ask to be allowed again). The speech engines are the
one thing it can't move: a Wyoming entry has no way to change its address, so if the Hub's address
changes, delete the kokoro and parakeet entries (Settings, Devices and services, Wyoming) first, and
the deploy adds them back at the new one.
