# Autostart Loop Guide

This guide walks through running `complete/complete_v2.py` in an endless loop that boots automatically with the Raspberry Pi and only stops when the device loses power.

## 1. Create a loop wrapper script
1. Choose a path for the launcher (e.g., `/usr/local/bin/ac-wearable.sh`).
2. Create the script with executable permissions:
   ```bash
   sudo tee /usr/local/bin/ac-wearable.sh > /dev/null <<'EOF'
   #!/bin/bash
   set -euo pipefail
   cd /home/pi/ac-python
   source /home/pi/.venvs/ac/bin/activate  # adjust if you use another env
   while true; do
       python complete/complete_v2.py "$@"
       echo "complete_v2.py exited with $?; restarting in 5s" >&2
       sleep 5
   done
   EOF
   sudo chmod +x /usr/local/bin/ac-wearable.sh
   ```
3. The loop restarts the script after crashes or manual exits, ensuring LEDs recover automatically.

## 2. Define a systemd service
1. Create `/etc/systemd/system/ac-wearable.service`:
   ```ini
   [Unit]
   Description=AC Wearable Loop
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=simple
   ExecStart=/usr/local/bin/ac-wearable.sh --single-strip
   Restart=always
   RestartSec=2
   StandardOutput=journal
   StandardError=journal
   User=pi
   WorkingDirectory=/home/pi/ac-python

   [Install]
   WantedBy=multi-user.target
   ```
2. Adjust `User`, `WorkingDirectory`, virtualenv, or CLI flags (`--single-strip`) for your deployment. The `Restart=always` directive keeps the service alive until the board loses power.

## 3. Enable and monitor the service
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ac-wearable.service
sudo systemctl status ac-wearable.service
journalctl -u ac-wearable.service -f
```

- `enable --now` starts the loop immediately and registers it for every boot.
- `journalctl -f` tails the logs, useful for verifying sensor status or watching the graceful-degradation warnings.

## 4. Shutdown behavior
- To stop the LEDs temporarily without cutting power: `sudo systemctl stop ac-wearable.service`.
- On shutdown or power loss the service halts automatically; it resumes on the next boot without manual intervention.

Following these steps gives you an auto-launched, self-restarting loop that matches the “run forever until power disappears” requirement.
