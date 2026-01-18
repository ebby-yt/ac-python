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
WARNING_COLOR  = (255, 0, 0)

# MIN/MAX values initalization
TEMP_MIN = 0
TEMP_MAX = 40

SPO2_MIN = 90
SPO2_MAX = 100

RYTH_MIN = 50
RYTH_MAX = 110

# Targeted slices for the three planned metrics, aligned with their sensor thresholds.
# Index ranges are inclusive of start and exclusive of end so each strip owns a contiguous
# segment of the 256 LEDs.
STRIP_LAYOUT = (
    {
        'metric': 'heart_rate',
        'start_index': 0,
        'end_index': 85,
        'min_value': RYTH_MIN,
        'max_value': RYTH_MAX,
    },
    {
        'metric': 'spo2',
        'start_index': 85,
        'end_index': 170,
        'min_value': SPO2_MIN,
        'max_value': SPO2_MAX,
    },
    {
        'metric': 'temperature',
        'start_index': 170,
        'end_index': LED_COUNT,
        'min_value': TEMP_MIN,
        'max_value': TEMP_MAX,
    },
)

COLOR_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'color_config.json')
SAFE_DEFAULT_CONFIG = {
    'strip_order': ['heart_rate', 'spo2', 'temperature'],
    'base_colors': [(255, 0, 0), (0, 128, 255), (255, 140, 0)],
    'end_colors': [(255, 200, 200), (0, 255, 255), (255, 255, 0)],
}


def parse_args():
    parser = argparse.ArgumentParser(description='Drive multi-strip wearable gradients.')
    parser.add_argument(
        '--single-strip',
        action='store_true',
        help='Render the full LED array as a single gradient (legacy behavior).',
    )
    return parser.parse_args()


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


def _coerce_index(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _sanitize_slice_bounds(slice_candidate):
    start_index = _coerce_index(slice_candidate.get('start_index', 0), 0)
    end_index = _coerce_index(slice_candidate.get('end_index', LED_COUNT), LED_COUNT)
    start_index = max(0, min(LED_COUNT, start_index))
    end_index = max(start_index + 1, min(LED_COUNT, end_index))
    return start_index, end_index


def _sanitize_metric_range(slice_candidate, fallback_min=0, fallback_max=255):
    try:
        min_value = float(slice_candidate.get('min_value', fallback_min))
    except (TypeError, ValueError):
        min_value = float(fallback_min)
    try:
        max_value = float(slice_candidate.get('max_value', fallback_max))
    except (TypeError, ValueError):
        max_value = float(fallback_max)
    if min_value >= max_value:
        log_color_config_issue('Invalid metric range; reverting to defaults.')
        return float(fallback_min), float(fallback_max)
    return min_value, max_value


def _resolve_color_entry(entries, index, label):
    if not entries:
        log_color_config_issue(f"{label} missing entirely; defaulting to black.")
        return (0, 0, 0)
    if index >= len(entries):
        log_color_config_issue(f"{label}[{index}] missing; using last available entry.")
        return tuple(entries[-1])
    return tuple(entries[index])


def build_strip_metadata(color_config, layout=STRIP_LAYOUT):
    layout_lookup = {entry['metric']: entry for entry in layout}
    metadata = []
    fallback_slice = {'start_index': 0, 'end_index': LED_COUNT, 'min_value': 0, 'max_value': 255}
    for index, metric in enumerate(color_config['strip_order']):
        slice_candidate = layout_lookup.get(metric)
        if slice_candidate is None:
            log_color_config_issue(f"No strip layout defined for {metric}; defaulting to full strip.")
            slice_candidate = fallback_slice
        start_index, end_index = _sanitize_slice_bounds(slice_candidate)
        min_value, max_value = _sanitize_metric_range(slice_candidate, fallback_slice['min_value'], fallback_slice['max_value'])
        if start_index >= end_index:
            log_color_config_issue(f"Invalid slice for {metric}; forcing at least one LED.")
            end_index = min(LED_COUNT, start_index + 1)
        metadata.append({
            'metric': metric,
            'start_index': start_index,
            'end_index': end_index,
            'min_value': min_value,
            'max_value': max_value,
            'base_color': _resolve_color_entry(color_config['base_colors'], index, 'base_colors'),
            'end_color': _resolve_color_entry(color_config['end_colors'], index, 'end_colors'),
        })
    return metadata


def attach_metric_ratios(strip_metadata, normalized_values, validity_map=None):
    validity_map = validity_map or {}
    for entry in strip_metadata:
        metric_key = entry['metric']
        is_valid = bool(validity_map.get(metric_key, True))
        normalized_value = clamp_color_value(normalized_values.get(metric_key, 0)) if is_valid else 0
        ratio = normalized_value / 255.0 if normalized_value else 0.0
        entry['normalized_value'] = normalized_value
        entry['ratio'] = ratio
        entry['valid'] = is_valid
    return strip_metadata


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


def render_strip_segments(strip, metadata, wait_ms=0):
    warning_active = int(time.time() * 2) % 2 == 0
    for entry in metadata:
        start_index = entry['start_index']
        end_index = entry['end_index']
        segment_length = max(0, end_index - start_index)
        if segment_length <= 0:
            continue
        if not entry.get('valid', True):
            warning_color = WARNING_COLOR if warning_active else (0, 0, 0)
            gradient = [warning_color] * segment_length
        else:
            ratio = entry.get('ratio', 0)
            target_end_color = scale_color(entry['end_color'], ratio)
            gradient = build_gradient(entry['base_color'], target_end_color, segment_length)
        for offset, (red_channel, green_channel, blue_channel) in enumerate(gradient):
            strip.setPixelColor(start_index + offset, Color(red_channel, green_channel, blue_channel))
    strip.show()
    if wait_ms:
        time.sleep(wait_ms / 1000.0)


def render_single_strip(strip, metadata, cleaned_values):
    if not metadata:
        return
    primary_strip = metadata[0]
    base_start_color = primary_strip['base_color']
    base_end_color = primary_strip['end_color']
    max_clean_value = max(cleaned_values.values()) if cleaned_values else 0
    intensity_factor = max_clean_value / 255.0 if max_clean_value else 1.0
    start_color = scale_color(base_start_color, intensity_factor)
    end_color = scale_color(base_end_color, intensity_factor)
    betterColorWipe(strip, start_color, end_color)

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

if __name__ == '__main__':
    args = parse_args()
    # MAX30102 initialization
    m = max30102.MAX30102()
    # LED strip initialization
    strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
    # Intialize the library (must be called once before other functions).
    strip.begin()
    color_config = load_color_config()
    try:
        while True:
            raw_r, raw_g, raw_b = 0, 0, 0
            color_r, color_g, color_b = 0, 0, 0

            print("Reading temp")
            raw_b = read_temp()
            temp_valid = raw_b is not None
            if not temp_valid:
                raw_b = TEMP_MIN
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
            strip_metadata = build_strip_metadata(color_config)
            if not strip_metadata:
                log_color_config_issue('No strip metadata resolved; falling back to defaults.')
                strip_metadata = [{
                    'metric': 'fallback',
                    'start_index': 0,
                    'end_index': LED_COUNT,
                    'base_color': (255, 0, 0),
                    'end_color': (0, 0, 255),
                    'min_value': 0,
                    'max_value': 255,
                }]
            cleaned_metric_values = {
                'heart_rate': color_r,
                'spo2': color_g,
                'temperature': color_b,
                'fallback': max(color_r, color_g, color_b),
            }
            metric_validity = {
                'heart_rate': hr_valid,
                'spo2': spo2_valid,
                'temperature': temp_valid,
                'fallback': True,
            }
            strip_metadata = attach_metric_ratios(strip_metadata, cleaned_metric_values, metric_validity)
            if args.single_strip:
                render_single_strip(strip, strip_metadata, cleaned_metric_values)
            else:
                render_strip_segments(strip, strip_metadata)
            time.sleep(2)
    except KeyboardInterrupt:
        print("Loop interrupted; exiting.")
