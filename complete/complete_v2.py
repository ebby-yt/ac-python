import os
import glob
import time
import json
import max30102
import hrcalc
from rpi_ws281x import Adafruit_NeoPixel, Color
import argparse
import smbus

# KS0023 initalization
os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')
base_dir = '/sys/bus/w1/devices/'
device_folder = glob.glob(base_dir + '28*')[0]
device_file = device_folder + '/w1_slave'

# LED output initialization
LED_COUNT      = 256
LED_COUNT_W    = 8
LED_COUNT_H    = 32
LED_PIN        = 18
LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA        = 10      # DMA channel to use for generating a signal (try 10)
LED_BRIGHTNESS = 65      # Set to 0 for darkest and 255 for brightest
LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL    = 0       # set to '1' for GPIOs 13, 19, 41, 45 or 53

# MIN/MAX values initalization
TEMP_MIN = 0
TEMP_MAX = 40

SPO2_MIN = 90
SPO2_MAX = 100

RYTH_MIN = 50
RYTH_MAX = 110

COLOR_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'color_config.json')
SAFE_DEFAULT_CONFIG = {
    'strip_order': ['heart_rate', 'spo2', 'temperature'],
    'base_colors': [(255, 0, 0), (0, 128, 255), (255, 140, 0)],
    'end_colors': [(255, 200, 200), (0, 255, 255), (255, 255, 0)],
}


def clamp_color_value(value):
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        numeric_value = 0
    return max(0, min(255, numeric_value))


def parse_color(data, fallback):
    if isinstance(data, (list, tuple)) and len(data) == 3:
        return tuple(clamp_color_value(component) for component in data)
    return fallback


def log_color_config_issue(message):
    print(f"[color-config] {message}")


def _load_default_payload(config_path):
    try:
        with open(config_path, 'r', encoding='utf-8') as config_file:
            payload = json.load(config_file)
            if isinstance(payload, dict):
                return payload
            log_color_config_issue('Malformed color_config.json payload; using safe defaults.')
    except (OSError, ValueError) as error:
        log_color_config_issue(f"Failed to read {config_path}: {error}. Using safe defaults.")
    return {
        'strip_order': list(SAFE_DEFAULT_CONFIG['strip_order']),
        'base_colors': [tuple(color) for color in SAFE_DEFAULT_CONFIG['base_colors']],
        'end_colors': [tuple(color) for color in SAFE_DEFAULT_CONFIG['end_colors']],
    }


def _parse_strip_order(raw_order, fallback):
    if isinstance(raw_order, list) and raw_order and all(isinstance(item, str) and item for item in raw_order):
        return raw_order
    log_color_config_issue('strip_order missing or invalid; using defaults.')
    return list(fallback)


def _parse_color_entries(raw_colors, fallback, label):
    expected_length = len(fallback)
    if not isinstance(raw_colors, list):
        log_color_config_issue(f"{label} missing or invalid; using defaults.")
        return [tuple(color) for color in fallback]
    resolved = []
    for index in range(expected_length):
        if index >= len(raw_colors):
            log_color_config_issue(f"{label}[{index}] missing; default {fallback[index]} applied.")
            resolved.append(tuple(fallback[index]))
            continue
        resolved.append(_parse_single_color(raw_colors[index], fallback[index], label, index))
    if len(raw_colors) > expected_length:
        log_color_config_issue(
            f"{label} contains {len(raw_colors) - expected_length} extra entries; ignoring extras."
        )
    return resolved


def _parse_single_color(candidate, fallback, label, index):
    if not isinstance(candidate, (list, tuple)) or len(candidate) != 3:
        log_color_config_issue(f"{label}[{index}] invalid; default {fallback} applied.")
        return tuple(fallback)
    return parse_color(candidate, fallback)


def load_color_config(config_path=COLOR_CONFIG_PATH):
    defaults = _load_default_payload(config_path)
    payload = defaults
    try:
        with open(config_path, 'r', encoding='utf-8') as config_file:
            maybe_payload = json.load(config_file)
            if isinstance(maybe_payload, dict):
                payload = maybe_payload
            else:
                log_color_config_issue('color_config.json is not a JSON object; reusing defaults from file.')
    except (OSError, ValueError) as error:
        log_color_config_issue(f"Failed to read {config_path}: {error}. Reusing defaults from file.")

    return {
        'strip_order': _parse_strip_order(payload.get('strip_order'), defaults['strip_order']),
        'base_colors': _parse_color_entries(payload.get('base_colors'), defaults['base_colors'], 'base_colors'),
        'end_colors': _parse_color_entries(payload.get('end_colors'), defaults['end_colors'], 'end_colors'),
    }


def build_gradient(start_color, end_color, steps):
    if steps <= 1:
        return [start_color]
    gradient = []
    for index in range(steps):
        ratio = index / (steps - 1)
        gradient.append(
            tuple(
                clamp_color_value(
                    round(start_color[channel] + (end_color[channel] - start_color[channel]) * ratio)
                )
                for channel in range(3)
            )
        )
    return gradient


def scale_color(color, factor):
    return tuple(clamp_color_value(channel * factor) for channel in color)

def read_temp_raw():
    f = open(device_file, 'r')
    lines = f.readlines()
    f.close()
    return lines

def read_temp():
    lines = read_temp_raw()
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos+2:]
        temp_c = float(temp_string) / 1000.0

        return temp_c

def colorWipe(strip, color, wait_ms=50):
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, color)
        strip.show()
        time.sleep(wait_ms/1000.0)


def colorWipe2(strip, color_r, color_g, color_b, color_w=1, wait_ms=50):
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, color_r, color_g, color_b, color_w*LED_BRIGHTNESS)
        strip.show()
        time.sleep(wait_ms/1000.0)


def fromColorAToColorB(strip, color_a, color_b, wait_ms=50):
    color = color_a
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, color)
        strip.show()
        time.sleep(wait_ms/1000.0)


def curtainFall(strip, color, max_brightness, wait_ms=50):
    for i in range(LED_COUNT_H):
        for j in range(LED_COUNT_W):
            strip.setColor(i*LED_COUNT_H + j, color)
        strip.show()
        time.sleep(wait_ms/1000.0)


def betterColorWipe(strip, start_color, end_color, wait_ms=50):
    gradient = build_gradient(start_color, end_color, strip.numPixels())
    for index, (red_channel, green_channel, blue_channel) in enumerate(gradient):
        strip.setPixelColor(index, Color(red_channel, green_channel, blue_channel))
        strip.show()
        time.sleep(wait_ms/1000.0)

def clean_data(raw_r, raw_g, raw_b, clean_r, clean_g, clean_b):
    if raw_r < RYTH_MIN :
        raw_r = RYTH_MIN
    elif raw_r > RYTH_MAX :
        raw_r = RYTH_MAX
    clean_r = int((raw_r - RYTH_MIN) * (255 / (RYTH_MAX - RYTH_MIN)))

    if raw_g != 0 :
        if raw_g < SPO2_MIN :
            raw_g = SPO2_MIN
        elif raw_g > SPO2_MAX :
            raw_g = SPO2_MAX
        clean_g = int((raw_g - SPO2_MIN) * (255 / (SPO2_MAX - SPO2_MIN)))

    if raw_b != 0 :
        if raw_b < TEMP_MIN :
            raw_b = TEMP_MIN
        elif raw_b > TEMP_MAX :
            raw_b = TEMP_MAX
        clean_b = int((raw_b - TEMP_MIN) * (255 / (TEMP_MAX - TEMP_MIN)))

    return clean_r, clean_g, clean_b

if __name__ == '__main__' :
    # MAX30102 initialization
    m = max30102.MAX30102()
    # LED strip initialization
    strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
    # Intialize the library (must be called once before other functions).
    strip.begin()
    raw_r, raw_g, raw_b = 0, 0, 0
    color_r, color_b, color_g = 0, 0, 0

    print("Reading temp")
    raw_b = read_temp()
    print("SPO2 and HR")
    print("Reading sequential data")

    # Read data from the sensor
    red, ir = m.read_sequential()

    # Calculate heart rate and SpO2
    print("Calculating HR & SPO2")
    hr, hr_valid, spo2, spo2_valid = hrcalc.calc_hr_and_spo2(ir, red)

    # Check if valid readings are obtained
    if hr_valid :
        raw_r = hr
    if spo2_valid :
        raw_g = spo2

    # Clean raw data
    print("Cleaning data")
    color_r, color_g, color_b = clean_data(raw_r, raw_g, raw_b, color_r, color_g, color_b)
    print((color_r, color_g, color_b))

    # Fill the strip with new colors
    print("Displaying")
    color_config = load_color_config()
    base_start_color = color_config['base_colors'][0]
    base_end_color = color_config['end_colors'][0]
    max_clean_value = max(color_r, color_g, color_b)
    intensity_factor = max_clean_value / 255.0 if max_clean_value else 1.0
    start_color = scale_color(base_start_color, intensity_factor)
    end_color = scale_color(base_end_color, intensity_factor)
    betterColorWipe(strip, start_color, end_color)
    time.sleep(1)
