<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/olig89/button-blueprinter/main/custom_components/button_blueprinter/brand/dark_logo.png">
    <img alt="Button Blueprinter" src="https://raw.githubusercontent.com/olig89/button-blueprinter/main/custom_components/button_blueprinter/brand/logo.png" height="72">
  </picture>
</p>

<p align="center">
  <a href="https://hacs.xyz/docs/faq/custom_repositories/"><img alt="HACS custom repository" src="https://img.shields.io/badge/HACS-custom-41BDF5"></a>
  <a href="https://github.com/olig89/button-blueprinter/releases"><img alt="Latest release" src="https://img.shields.io/github/v/release/olig89/button-blueprinter?color=2F6FDB"></a>
  <img alt="Home Assistant 2026.9 or later" src="https://img.shields.io/badge/Home%20Assistant-2026.9%2B-18BCF2">
  <a href="https://github.com/olig89/button-blueprinter/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/olig89/button-blueprinter/actions/workflows/tests.yml/badge.svg"></a>
</p>

A Home Assistant integration: every physical switch in your home, room by
room, drawn as it looks, and what each button does.

Status: **0.7.2**, in daily use on one home's KNX, Hue, IKEA, Nuimo and
Zigbee2MQTT switches. Built for that home first, so expect rough edges.

## What it does

- A sidebar page, **Button Blueprinter**, open to everyone in the household.
  Rooms come from Home Assistant's areas. Each switch is drawn from its model,
  with each button's label and icon.
- Tap a button on the picture to see what each gesture does (tap, double tap,
  hold, turn, swipe, …), change it, clear it, or test it.
- **Everyone** can set a button from a menu of safe actions: switch on or off,
  switch on at a brightness, switch off, a scene (optionally "again turns it
  off"), brighter, dimmer, a speaker command, run a script, send a robot
  vacuum to clean an area (vacuum, mop or both; a press while it is out
  cleaning sends it home).
- **Administrators** can also write actions by hand, add and change switches,
  mark a gesture as handled outside Home Assistant (a KNX-direct fallback, for
  example), set labels and icons, make an LED follow an entity, switch a
  switch between **On**, **Dry run** and **Off**, copy an old automation's
  buttons in, and export a switch as a plain automation.
- **Dry run**: presses are logged with what they would have done, and nothing
  runs. New switches start in a dry run, so they can sit next to an old
  automation and be compared.
- The **What happened** tab lists the latest presses and what each did.

## Switch models

One YAML file per model in `custom_components/button_blueprinter/models/`.
The page draws the switch from the shapes in the file, so a new model needs
no picture and no code, only a new file, unless it reaches Home Assistant in a
new way.

| Model | File | How presses arrive |
|---|---|---|
| Schneider Push Button Dynamic Labelling, 8 buttons (MTN6194) | `schneider_mtn619x.yaml` | KNX telegrams |
| Schneider D-Life Pushbuttons Pro T, 4 buttons (MTN6185) | `schneider_mtn6185.yaml` | KNX telegrams |
| Hue Dimmer switch | `hue_dimmer.yaml` | Hue event entities |
| Hue Tap dial switch | `hue_tap_dial.yaml` | Hue event entities |
| IKEA BILRESA scroll wheel | `ikea_bilresa_scroll_wheel.yaml` | `ikea_bilresa` integration's channel entities |
| IKEA BILRESA dual button | `ikea_bilresa_dual_button.yaml` | `ikea_bilresa` integration (v0.6.0+) |
| Senic Nuimo | `senic_nuimo.yaml` | `nuimo` integration's event entity |
| Aqara Cube T1 Pro | `aqara_cube_t1_pro.yaml` | Zigbee2MQTT's own messages (face up, rotate angle) |

The IKEA TRÅDFRI remote, shortcut button and STYRBAR are left out on purpose:
adding one later is the test that a new model needs only one file.

### Icon sets: switches that can only show certain icons

Some switches can't show just any icon. A model can name an **icon set**
(`icon_sets/*.yaml`), and its buttons then only offer icons from that set:

- **Schneider D-Life Dynamics display (MTN6194, 8 buttons)**: each button has a
  look for *status on* and one for *status off*, each one of Schneider's 54 icons
  and one of six colours (white, green, blue, red, orange, yellow), plus a name
  of up to 12 characters that it shows or not ("icon only", "icon and name",
  "nothing"). The page shows the look for the button's current status, which
  comes from its status object (the LED address). These are ETS settings: the
  plate has no bus object to change them, so the page shows and plans what ETS
  has downloaded.
- **Schneider D-Life Pro T push-button (MTN6185, 4 buttons)**: a printed insert
  per button, from Schneider's four insert sheets.

The real icon pictures are Schneider's and are not in this repository. Copy
them out of your own ETS project into Home Assistant, and the page uses them
instead of look-alikes:

    python tools/schneider_icons.py MyHouse.knxproj out
    # then copy out/schneider_dlife/ to <HA config>/button_blueprinter_icons/schneider_dlife/ and restart

**Asking for a new look.** Because these looks are changed in ETS (or by
printing a new insert), nobody can change them from the page directly. Anyone
in the household can *ask* for one: pick the icons, colours and name on a
button, press "Ask for this", and the request goes on the **Waiting for ETS**
tab with the exact ETS settings to change (plate address, Function number,
setting, now, change to). The page keeps drawing what the plate really shows,
with an orange mark on a button that has a request. A request is ticked off by
itself when a fresh read of ETS shows the plate matches; an administrator can
also press "It's done" (the only way for an insert). Anyone can withdraw a
request. What a button *does* is separate and changes straight away.

To fill the 8-button plates' looks from ETS (names, icons, colours, what they
show), run `tools/ets_looks.py` on a JSON export of your ETS project's
parameter values (its docstring has the format), and send the result with the
admin websocket command `button_blueprinter/apply_looks`.

### Writing a model

```yaml
id: my_remote            # must match the file name
name: My remote
maker: Someone
input: event_entity      # or knx, or zigbee2mqtt
picture: {width: 40, height: 90, radius: 6, colour: "#eee", ink: "#333"}
looks: [label, icon]
controls:                # rect (x y w h), circle (cx cy r) or ring (cx cy r inner)
  - {id: top, name: Top button, shape: rect, x: 4, y: 4, w: 32, h: 40,
     gestures: [press, double_press, long_press, long_press_repeat, long_press_release]}
entities:                # event_entity models: one slot per event entity
  - slot: button_1
    find: "_button_1$"   # pattern matched against the entity id
    events:              # the device's own event type -> what it means
      short_release: {control: top, raw: tap}          # a tap; may become a double tap
      long_press: {control: top, gesture: long_press}  # a gesture straight away
      rotate: {control: ring, turn: delta, divide: 10} # a turn; the sign is the direction
```

`raw: down` / `raw: up` are for a device that only says finger on, finger off:
Button Blueprinter times tap, double tap and hold itself. `steps: <attribute>`
on a gesture reads how far a dial turned.

`zigbee2mqtt` models have `actions:` instead of `entities:`, keyed by the
message's `action`; the rest of the message are its attributes. `pick: side`
with `controls: {1: face_1, ...}` chooses the control from a field (the cube's
face). `match: [CTP-R01]` lists the Zigbee2MQTT model ids the file is for, so
the page offers those devices first.

KNX models give each control a `knx` offset and say what each address means
(`tap: tap`, `hold: long_press`, `led: led`). A switch then stores the first
address of each kind (`6/0/40`, `6/1/40`, `6/2/40`); the rest follow on.

## Put back (opt-in, per switch)

For a play or task switch: "Put lights back after N minutes", for all its
buttons or only some. The first such press saves how the lights its menu
binding touches look (on/off, brightness, colour; a scene's lights). Each
press starts the clock again. When it runs out, each light goes back, unless
something else changed it in the meantime (the wall, an app, another button):
then it's left alone. Hand-written actions aren't tracked. The menu item "Put
things back now" (offered only on such a switch) does it at once; so does the
`button_blueprinter.put_back` action and the button on the page. The saved
looks survive a restart.

## How it listens

- **KNX**: the KNX integration's own `knx.telegram` trigger, attached in code,
  so no `knx: event:` setting is needed. Writes to a tap or hold address are
  presses; reads of an LED address are answered (when the switch is On).
- **Event entities**: a state change to a new time stamp is a new event. A
  state restored at start-up, or coming back from unavailable, is not a press.
- **Zigbee2MQTT**: the device's own topic, `zigbee2mqtt/<device name>`, where the
  name is Home Assistant's device name, which Zigbee2MQTT keeps equal to its
  friendly name; a rename there moves the subscription. A message with an
  `action` is an event. Needs the MQTT integration.

## Install

Copy `custom_components/button_blueprinter` into Home Assistant's
`custom_components` folder (or add this repository to HACS as a custom
repository), restart, then Settings → Devices & services → Add integration →
Button Blueprinter.

## Development

See `CLAUDE.md`.
