# Raspberry Pi Sensor & Neopixel Project

This project contains Python scripts and modules for working with various sensors (I2C, temperature, heart rate) and controlling NeoPixel LEDs on a Raspberry Pi. It is organized into several folders, each targeting a specific hardware component or functionality.

## Project Structure

```
.
├── i2c_scanner.py           # Scan for I2C devices on the bus
├── complete/                # Heart rate and sensor utilities (main scripts)
│   ├── complete.py
│   ├── complete_v2.py
│   ├── complete_bak.py
│   ├── complete_backup240109.py
│   ├── cleanup.py
│   ├── hrcalc.py
│   ├── max30102.py
│   └── __pycache__/
├── i2ctest/                 # Heart rate monitor (MAX30102) test suite
│   └── max30102/
│       ├── main.py
│       ├── heartrate_monitor.py
│       ├── hrcalc.py
│       ├── max30102.py
│       ├── test.py
│       ├── README.md
│       └── __pycache__/
├── neopixels/               # NeoPixel LED test scripts
│   ├── complexTest.py
│   └── test.py
├── temptest/                # Temperature sensor test script
│   └── tempRead.py
└── .env/                    # Python virtual environment and dependencies
```

## Features

- **I2C Device Scanning:**
  - `i2c_scanner.py` scans and lists all I2C devices connected to the Raspberry Pi.

- **Heart Rate Monitoring (MAX30102):**
  - Scripts in `i2ctest/max30102/` and `complete/` provide heart rate calculation and sensor interfacing using the MAX30102 sensor.
  - Includes utilities for heart rate calculation (`hrcalc.py`) and sensor management (`max30102.py`).

- **NeoPixel LED Control:**
  - Scripts in `neopixels/` demonstrate basic and advanced control of NeoPixel LED strips.

- **Temperature Sensing:**
  - `temptest/tempRead.py` reads temperature data from supported sensors.

- **Virtual Environment:**
  - The `.env/` folder contains a Python virtual environment with all required dependencies (Adafruit libraries, numpy, etc.).

## Setup

1. **Clone the repository** and navigate to the project directory.
2. **Activate the virtual environment:**
   - On Windows:
     ```powershell
     .env\bin\Activate.ps1
     ```
   - On Linux/macOS:
     ```bash
     python3 -m venv .env --copies
     source .env/bin/activate

     # Sanity check with :
     python -c "import sys; print(sys.executable)"

     # Reinstall dependencies
     python -m pip install --upgrade pip setuptools wheel
     python -m pip install -r requirements.txt
     ```
3. **Install dependencies** (if not already present):
   ```bash
   pip install -r requirements.txt
   ```
   *(A requirements.txt can be generated from the environment if needed.)*

## Usage

- **Scan I2C Devices:**
  ```bash
  python i2c_scanner.py
  ```
- **Run Heart Rate Monitor:**
  ```bash
  python i2ctest/max30102/main.py
  ```
- **Test NeoPixels:**
  ```bash
  python neopixels/test.py
  ```
- **Read Temperature:**
  ```bash
  python temptest/tempRead.py
  ```

## Dependencies

- Python 3.11+
- [Adafruit Blinka](https://github.com/adafruit/Adafruit_Blinka)
- [Adafruit CircuitPython MAX30102](https://github.com/adafruit/Adafruit_CircuitPython_MAX30102)
- [Adafruit CircuitPython NeoPixel](https://github.com/adafruit/Adafruit_CircuitPython_NeoPixel)
- [Adafruit CircuitPython DHT](https://github.com/adafruit/Adafruit_CircuitPython_DHT)
- numpy, gpiozero, and other common libraries

All dependencies are included in the `.env` virtual environment.

## Notes

- Ensure I2C and SPI interfaces are enabled on your Raspberry Pi (via `raspi-config`).
- Some scripts may require root privileges to access hardware interfaces.
- For more details on the heart rate monitor, see `i2ctest/max30102/README.md`.

## License

This project is for educational and prototyping purposes. See individual files for license details if present.
