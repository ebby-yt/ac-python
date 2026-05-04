# Button V4

`complete/button_v4.py` is the Shelly BLU Button 1 version of `complete/complete_v4.py`.
It keeps the V4 multi-strip LED layout from `complete/color_config.json`, but it uses
Bluetooth button presses instead of MAX30102/temperature sensor readings to switch the
outfit between inactive and active gradients.

## What It Controls

By default, `button_v4.py` initializes the same three physical strips as `complete_v4.py`:

- `left_arm`: GPIO 18, channel 0, 24 LEDs
- `center_piece`: GPIO 13, channel 1, 54 LEDs
- `right_arm`: GPIO 21, channel 0, 24 LEDs

Each strip uses its `blocks` from `complete/color_config.json`. When the button state is
inactive, blocks use `inactive_gradient`. When the button state is active, blocks use
`active_gradient`.

At startup, `button_v4.py` builds a fixed per-LED two-state map from those blocks. In
normal multi-strip mode, each physical LED can only be rendered with its inactive color
or its active color from that map.

## Requirements

Install the normal project requirements first:

```bash
python -m pip install -r requirements.txt
```

The Bluetooth listener needs `bleak`, which is already listed in `requirements.txt`.
On Raspberry Pi OS, make sure Bluetooth is enabled and the script has permission to scan
BLE advertisements.

`rpi_ws281x` often needs elevated hardware access. If LED initialization fails with a
`/dev/mem` or `mmap()` error, run with `sudo` for testing or use the systemd/root setup in
`docs/autostart-loop.md`.

## Run

From the project root on the Raspberry Pi:

```bash
python complete/button_v4.py
```

Useful examples:

```bash
python complete/button_v4.py --button-address AA:BB:CC:DD:EE:FF
python complete/button_v4.py --button-name SBBT
python complete/button_v4.py --button-mode momentary --active-seconds 5
python complete/button_v4.py --scan-all-debug
```

For the legacy single-strip debug renderer:

```bash
python complete/button_v4.py --single-strip
```

## Button Behavior

The script listens for Shelly BLU Button 1 BTHome advertisements.

- Default mode is `toggle`: each recognized button event flips active on or off.
- By default, only a normal press changes the LEDs.
- `momentary` mode activates the gradient for `--active-seconds`; use toggle mode for the cleanest two-state behavior.
- Duplicate packets are filtered so one BLE advertisement burst should not flip the state repeatedly.

Double press, triple press, long press, and hold advertisements are ignored unless their CLI flags are enabled.

## CLI Options

- `--single-strip`: render one 256 LED strip on GPIO 18 for debugging.
- `--button-address`: only accept advertisements from this Bluetooth MAC/address.
- `--button-name`: accept devices whose advertised name starts with this prefix.
- `--button-mode`: choose `toggle` or `momentary`.
- `--active-seconds`: momentary active duration, default `5.0`.
- `--scan-debug`: print parsed button advertisements.
- `--scan-all-debug`: print nearby BLE advertisements, including non-button packets.
- `--include-multi-click-events`: also accept double, triple, and long press events.
- `--include-hold-events`: also accept hold events.
- `--event-debounce-seconds`: minimum gap between accepted events, default `1.0`.

## Configuration

Edit `complete/color_config.json` to change:

- physical strip pins, channels, LED counts, and block ranges under `led_strips`
- inactive colors under `inactive_gradient`
- active colors under `active_gradient`

Both gradients should contain eight RGB triplets. Each block uses its zero-based
`color_index` to select the matching color from the current gradient.

## Validation

Before deploying:

```bash
python -m json.tool complete/color_config.json
python -c "import ast,pathlib; ast.parse(pathlib.Path('complete/button_v4.py').read_text(encoding='utf-8'))"
```

If your machine can write to `__pycache__`, this is also useful:

```bash
python -m compileall complete/button_v4.py
```

## Troubleshooting

- `bleak is not installed`: install dependencies with `python -m pip install -r requirements.txt`.
- No button events: run with `--scan-all-debug` and press the Shelly button near the Pi.
- Too many devices trigger the state: add `--button-address AA:BB:CC:DD:EE:FF`.
- LEDs do not initialize: check `rpi_ws281x` permissions and GPIO/channel support.
- Colors look wrong: verify each block `color_index` is between `0` and `7`.
