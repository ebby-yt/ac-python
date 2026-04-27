# Autostart Loop Guide

This guide runs `complete/complete_v4.py` in an endless loop that boots automatically with the Raspberry Pi and only stops when the device loses power.

## 1. Create A Loop Wrapper

Choose a path for the launcher, for example `/usr/local/bin/ac-wearable.sh`, then create it:

```bash
sudo tee /usr/local/bin/ac-wearable.sh > /dev/null <<'EOF'
#!/bin/bash
set -euo pipefail
cd /home/pi/ac-python
source /home/pi/.venvs/ac/bin/activate  # adjust if you use another env
while true; do
    python complete/complete_v4.py "$@"
    echo "complete_v4.py exited with $?; restarting in 5s" >&2
    sleep 5
done
EOF
sudo chmod +x /usr/local/bin/ac-wearable.sh
```

The loop restarts the wearable after crashes or manual exits, so the LEDs recover automatically.

## 2. Define The Service

Create `/etc/systemd/system/ac-wearable.service`:

```ini
[Unit]
Description=AC Wearable Loop
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ac-wearable.sh
Restart=always
RestartSec=2
StandardOutput=journal
StandardError=journal
User=pi
WorkingDirectory=/home/pi/ac-python

[Install]
WantedBy=multi-user.target
```

Adjust `User`, `WorkingDirectory`, virtualenv path, and optional CLI flags for your deployment. Add `--single-strip` to `ExecStart` only when debugging the legacy one-strip renderer.

## 3. Enable And Monitor

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ac-wearable.service
sudo systemctl status ac-wearable.service
journalctl -u ac-wearable.service -f
```

- `enable --now` starts the loop immediately and registers it for every boot.
- `journalctl -f` tails the logs, useful for verifying sensor status and fallback messages.

## 4. Shutdown Behavior

- To stop the LEDs temporarily without cutting power: `sudo systemctl stop ac-wearable.service`.
- On shutdown or power loss, the service halts automatically and resumes on the next boot.

## 5. Troubleshooting

### `ModuleNotFoundError: No module named 'smbus'`

Install the missing dependency and I2C tooling:

```bash
sudo apt update
sudo apt install -y python3-smbus i2c-tools
```

Enable I2C if it was not configured:

```bash
sudo raspi-config nonint do_i2c 0
sudo reboot
```

After reboot, rerun `complete/complete_v4.py`; the import should succeed because `python3-smbus` ships the required bindings.

### `ModuleNotFoundError: No module named 'numpy'`

Install the packaged dependency:

```bash
sudo apt update
sudo apt install -y python3-numpy
```

If the virtualenv lacks system packages, add it there too:

```bash
source /home/pi/.venvs/ac/bin/activate
pip install numpy
```

Sanity-check before relaunching the loop:

```bash
python - <<'PY'
import numpy
print("numpy", numpy.__version__)
PY
```

### `RuntimeError: ws2811_init failed with code -5 (mmap() failed)`

`rpi_ws281x` needs `/dev/mem` access. If systemd runs the wearable as a non-root user, the driver cannot map the hardware registers.

Option A, simplest: run the service as root.

```ini
[Service]
User=root
ExecStart=/home/raspberrypi/ac-python/.env/bin/python /home/raspberrypi/ac-python/complete/complete_v4.py
```

Reload systemd, then restart the service.

Option B, stay non-root: grant the interpreter the required capabilities.

```bash
sudo setcap 'cap_sys_rawio,cap_sys_admin+ep' /home/raspberrypi/ac-python/.env/bin/python
sudo usermod -a -G gpio,i2c raspberrypi
sudo systemctl restart ac-wearable.service
```

Pick one option; once `/dev/mem` is accessible, `strip.begin()` succeeds under systemd.
