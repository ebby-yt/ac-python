# Raspberry Pi Wearable Sensors and NeoPixels

This project drives a Raspberry Pi wearable that combines:

- MAX30102 heart-rate and SpO2 sensing
- 1-Wire temperature sensing
- NeoPixel/WS281x LED strips
- A configurable three-strip costume layout

The current production entry point is `complete/complete_v4.py`. Older `complete_v2.py` and `complete_v3.py` files are kept as references while the hardware layout evolves.

## Project Structure

```text
.
|-- complete/
|   |-- complete_v4.py        # Current multi-strip wearable script
|   |-- color_config.json     # LED palettes, pins, strip sizes, and blocks
|   |-- hrcalc.py             # Heart-rate/SpO2 calculation helpers
|   |-- max30102.py           # MAX30102 sensor driver
|   |-- complete_v2.py        # Older production reference
|   |-- complete_v3.py        # Older production reference
|   `-- cleanup.py
|-- docs/
|   |-- autostart-loop.md     # systemd boot-loop setup
|   `-- multi-strip-plan.md
|-- i2ctest/max30102/         # MAX30102 experiments and harnesses
|-- neopixels/                # NeoPixel test scripts
|-- temptest/                 # Temperature sensor test script
`-- requirements.txt
```

## First-Time Raspberry Pi Setup

Run these before launching `complete/complete_v4.py` on a fresh Pi. Adjust paths if your checkout or virtualenv lives somewhere else.

1. Install OS packages:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-dev python3-smbus i2c-tools python3-numpy
```

2. Enable the hardware interfaces:

```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_onewire 0
sudo reboot
```

3. Create and activate the Python environment:

```bash
cd /home/pi/ac-python
python3 -m venv .env --system-site-packages
source .env/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

`--system-site-packages` lets the virtualenv see Raspberry Pi OS packages such as `python3-smbus` and `python3-numpy`.

4. Install Python dependencies:

```bash
python -m pip install -r requirements.txt
```

5. Confirm the important imports and hardware-facing modules load:

```bash
python - <<'PY'
import numpy
import smbus
import rpi_ws281x
print("numpy", numpy.__version__)
print("smbus ok")
print("rpi_ws281x ok")
PY
```

6. Validate the wearable files:

```bash
python -m json.tool complete/color_config.json
python -c "import ast,pathlib; ast.parse(pathlib.Path('complete/complete_v4.py').read_text(encoding='utf-8'))"
```

7. Launch the wearable:

```bash
python complete/complete_v4.py
```

If LED initialization fails with a `/dev/mem` or `mmap()` error, run the script with `sudo` for a quick test, then use the systemd/root or capability setup in `docs/autostart-loop.md` for deployment.

## Current LED Model

`complete/complete_v4.py` reads `complete/color_config.json` and creates three physical LED outputs:

- `left_arm`: GPIO 18, channel 0, 24 LEDs
- `center_piece`: GPIO 13, channel 1, 54 LEDs
- `right_arm`: GPIO 21, channel 0, 24 LEDs

Each strip has a `blocks` list. A block defines a contiguous LED range and selects one of the eight palette colors:

```json
{ "name": "left_arm_single_8", "start_index": 0, "end_index": 1, "color_index": 7 }
```

Block ranges are zero-based and `end_index` is exclusive, so `0` to `1` covers one LED, and `3` to `6` covers three LEDs. `color_index` is also zero-based: user-facing color 1 is `0`, and color 8 is `7`.

## Active and Inactive States

The outfit has one global state:

- If any sensor value is at or above its threshold, all strips use `active_gradient`.
- If all sensor values are below threshold or unavailable, all strips use `inactive_gradient`.

Both palettes must contain eight RGB colors. Blocks keep the same `color_index` in either state, so a block with `color_index: 7` uses the eighth inactive color while inactive and the eighth active color while active.

The current thresholds are constants near the top of `complete/complete_v4.py`:

- Heart rate: `RYTH_MIN` to `RYTH_MAX`; active threshold is halfway through that range.
- SpO2: `SPO2_MIN` to `SPO2_MAX`; active threshold is halfway through that range.
- Temperature: `TEMP_MIN` to `TEMP_MAX`; active threshold is halfway through that range.

## Running the Wearable

From the project root on the Raspberry Pi:

```bash
python complete/complete_v4.py
```

For the legacy one-strip debug renderer:

```bash
python complete/complete_v4.py --single-strip
```

The normal V4 mode uses the `led_strips` entries in `complete/color_config.json`.

## Autostart

The recommended deployment is a small loop wrapper launched by `systemd`. See `docs/autostart-loop.md` for the full guide.

Typical service flow:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ac-wearable.service
sudo systemctl status ac-wearable.service
journalctl -u ac-wearable.service -f
```

`rpi_ws281x` usually needs elevated access to hardware registers. If the service fails with `ws2811_init failed with code -5 (mmap() failed)`, run the service as root or grant the Python interpreter the required capabilities as described in `docs/autostart-loop.md`.

## Hardware Notes

- Enable I2C and 1-Wire on the Raspberry Pi before running the wearable.
- The MAX30102 provides heart rate and SpO2 samples.
- The temperature sensor is read from `/sys/bus/w1/devices/28*/w1_slave`.
- NeoPixels are driven with `rpi_ws281x`, so hardware PWM pin/channel support matters.
- Keep LED power and ground wiring sized for the actual LED count and brightness.

## Validation

Before deploying changes:

```bash
python -m json.tool complete/color_config.json
python -m compileall complete/complete_v4.py
```

If `compileall` cannot write to `__pycache__` on your development machine, a syntax-only parse is still useful:

```bash
python -c "import ast,pathlib; ast.parse(pathlib.Path('complete/complete_v4.py').read_text(encoding='utf-8'))"
```

## Troubleshooting

- `ModuleNotFoundError: No module named 'smbus'`: install `python3-smbus` and enable I2C.
- `ModuleNotFoundError: No module named 'numpy'`: install `python3-numpy` or add `numpy` to the active virtualenv.
- `ws2811_init failed`: check root/capability access for `rpi_ws281x`.
- No temperature sensor found: verify 1-Wire is enabled and the probe appears under `/sys/bus/w1/devices/`.

## License

This project is for educational and prototyping purposes. See individual files for license details if present.
