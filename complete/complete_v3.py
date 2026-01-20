import os
import glob
import time
import json
import max30102
import hrcalc
from rpi_ws281x import Adafruit_NeoPixel, Color
import argparse
import smbus
from concurrent.futures import ThreadPoolExecutor, TimeoutError

# KS0023 initalization
os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')
base_dir = '/sys/bus/w1/devices/'
device_folder = glob.glob(base_dir + '28*')[0]
device_file = device_folder + '/w1_slave'

# LED output initialization
LED_COUNT_W    = 8
LED_COUNT_H    = 32
LED_COUNT      = LED_COUNT_W * LED_COUNT_H
LED_PIN        = 18
LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA        = 10      # DMA channel to use for generating a signal (try 10)
LED_BRIGHTNESS = 30      # Set to 0 for darkest and 255 for brightest
LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL    = 0       # set to '1' for GPIOs 13, 19, 41, 45 or 53
WARNING_COLOR  = (255, 0, 0)
SENSOR_READ_TIMEOUT = 5.0
_SENSOR_EXECUTOR = ThreadPoolExecutor(max_workers=1)
GRADIENT_COLOR_COUNT = 8
BLANK_ROWS = (10, 21)

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
BLANK_ROWS = (10, 21)

def _matrix_slice(line_start, line_count):
    start_index = max(0, line_start) * LED_COUNT_W
    end_index = min(LED_COUNT, start_index + max(1, line_count) * LED_COUNT_W)
    return start_index, end_index

HR_START, HR_END = _matrix_slice(0, 10)
SPO2_START, SPO2_END = _matrix_slice(11, 10)
TEMP_START, TEMP_END = _matrix_slice(22, 10)
STRIP_LAYOUT = (
    {'metric': 'heart_rate', 'start_index': HR_START, 'end_index': HR_END, 'min_value': RYTH_MIN, 'max_value': RYTH_MAX},
    {'metric': 'spo2', 'start_index': SPO2_START, 'end_index': SPO2_END, 'min_value': SPO2_MIN, 'max_value': SPO2_MAX},
    {'metric': 'temperature', 'start_index': TEMP_START, 'end_index': TEMP_END, 'min_value': TEMP_MIN, 'max_value': TEMP_MAX},
)

COLOR_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'color_config.json')
SAFE_DEFAULT_CONFIG = {
    'strip_order': ['heart_rate', 'spo2', 'temperature'],
    'base_colors': [(255, 0, 0), (0, 255, 0), (0, 0, 255)],
    'end_colors': [(255, 255, 255), (255, 255, 255), (255, 255, 255)],
    'inactive_gradient': [
        (52, 43, 34),
        (78, 42, 40),
        (79, 66, 42),
        (92, 94, 47),
        (150, 118, 63),
        (218, 143, 122),
        (233, 106, 44),
        (166, 56, 23)
    ],
    'active_gradients': {
        'heart_rate': [
            (52, 43, 34),
            (78, 42, 40),
            (79, 66, 42),
            (92, 94, 47),
            (113, 94, 96),
            (171, 81, 98),
            (169, 26, 60),
            (101, 34, 44)
        ],
        'spo2': [
            (0, 158, 153),
            (118, 193, 199),
            (156, 209, 192),
            (116, 185, 135),
            (69, 151, 101),
            (70, 107, 103),
            (92, 63, 95),
            (134, 42, 85)
        ],
        'temperature': [
            (0, 158, 153),
            (118, 193, 199),
            (232, 212, 204),
            (218, 143, 122),
            (233, 106, 44),
            (166, 56, 23),
            (169, 26, 60),
            (171, 81, 98)
        ],
    },
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
    base_defaults = {
        'strip_order': list(SAFE_DEFAULT_CONFIG['strip_order']),
        'base_colors': [tuple(color) for color in SAFE_DEFAULT_CONFIG['base_colors']],
        'end_colors': [tuple(color) for color in SAFE_DEFAULT_CONFIG['end_colors']],
        'inactive_gradient': [tuple(color) for color in SAFE_DEFAULT_CONFIG['inactive_gradient']],
        'active_gradients': {
            metric: [tuple(color) for color in gradients]
            for metric, gradients in SAFE_DEFAULT_CONFIG['active_gradients'].items()
        },
    }
    try:
        with open(config_path, 'r', encoding='utf-8') as config_file:
            payload = json.load(config_file)
            if isinstance(payload, dict):
                merged = dict(base_defaults)
                merged.update(payload)
                return merged
            log_color_config_issue('Malformed color_config.json payload; using safe defaults.')
    except (OSError, ValueError) as error:
        log_color_config_issue(f"Failed to read {config_path}: {error}. Using safe defaults.")
    return base_defaults


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

def _normalize_gradient_length(palette, label):
    palette = [tuple(parse_color(color, (0, 0, 0))) for color in (palette or [(0, 0, 0)])]
    if len(palette) > GRADIENT_COLOR_COUNT:
        log_color_config_issue(f"{label} contains extra entries; truncating to {GRADIENT_COLOR_COUNT}.")
        palette = palette[:GRADIENT_COLOR_COUNT]
    while len(palette) < GRADIENT_COLOR_COUNT:
        log_color_config_issue(f"{label} missing entries; repeating last color to reach {GRADIENT_COLOR_COUNT}.")
        palette.append(palette[-1])
    return palette

def _parse_metric_gradients(raw_dict, defaults, label):
    if not isinstance(raw_dict, dict):
        log_color_config_issue(f"{label} missing or invalid; using defaults.")
        raw_dict = {}
    resolved = {}
    for metric, default_palette in defaults.items():
        candidate = raw_dict.get(metric, default_palette)
        resolved[metric] = _normalize_gradient_length(
            _parse_color_entries(candidate, default_palette, f"{label}.{metric}"),
            f"{label}.{metric}",
        )
    for metric, candidate in raw_dict.items():
        if metric in resolved:
            continue
        resolved[metric] = _normalize_gradient_length(
            _parse_color_entries(candidate, candidate, f"{label}.{metric}"),
            f"{label}.{metric}",
        )
    return resolved


def load_color_config(config_path=COLOR_CONFIG_PATH):
    defaults = _load_default_payload(config_path)
    payload = defaults
    try:
        with open(config_path, 'r', encoding='utf-8') as config_file:
            maybe_payload = json.load(config_file)
            if isinstance(maybe_payload, dict):
                merged = dict(defaults)
                merged.update(maybe_payload)
                payload = merged
            else:
                log_color_config_issue('color_config.json is not a JSON object; reusing defaults from file.')
    except (OSError, ValueError) as error:
        log_color_config_issue(f"Failed to read {config_path}: {error}. Reusing defaults from file.")

    inactive_gradient = _normalize_gradient_length(
        _parse_color_entries(payload.get('inactive_gradient'), defaults['inactive_gradient'], 'inactive_gradient'),
        'inactive_gradient',
    )
    active_gradients = _parse_metric_gradients(
        payload.get('active_gradients'),
        defaults['active_gradients'],
        'active_gradients',
    )

    return {
        'strip_order': _parse_strip_order(payload.get('strip_order'), defaults['strip_order']),
        'base_colors': _parse_color_entries(payload.get('base_colors'), defaults['base_colors'], 'base_colors'),
        'end_colors': _parse_color_entries(payload.get('end_colors'), defaults['end_colors'], 'end_colors'),
        'gradients': {
            'inactive': inactive_gradient,
            'active': active_gradients,
        },
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
    factor = max(0.0, min(1.0, float(factor)))
    return tuple(clamp_color_value(round(channel * factor)) for channel in color)

def build_checkpoint_gradient(checkpoints, steps, intensity_ratio=1.0):
    steps = max(0, int(steps))
    if steps == 0:
        return []
    sanitized = [parse_color(color, (0, 0, 0)) for color in (checkpoints or [(0, 0, 0)])]
    intensity_ratio = max(0.0, min(1.0, float(intensity_ratio or 0.0)))
    if len(sanitized) == 1 or steps == 1:
        scaled = scale_color(sanitized[-1], intensity_ratio)
        return [scaled] * steps
    segments = len(sanitized) - 1
    gradient = []
    for index in range(steps):
        position = (index / (steps - 1)) * segments
        base_index = min(int(position), segments - 1)
        local_ratio = position - base_index
        start_color = sanitized[base_index]
        end_color = sanitized[base_index + 1]
        interpolated = tuple(
            clamp_color_value(
                round(start_color[channel] + (end_color[channel] - start_color[channel]) * local_ratio)
            )
            for channel in range(3)
        )
        gradient.append(scale_color(interpolated, intensity_ratio))
    return gradient

def evaluate_metric_activity(strip_metadata, raw_metrics):
    activity = {}
    for entry in strip_metadata:
        metric = entry['metric']
        raw_value = raw_metrics.get(metric)
        min_value = float(entry.get('min_value', 0))
        max_value = float(entry.get('max_value', 0))
        threshold = min_value + (max_value - min_value) / 2.0
        active = False
        if raw_value is not None:
            try:
                active = float(raw_value) >= threshold
            except (TypeError, ValueError):
                active = False
        activity[metric] = active
    return activity

def _clear_blank_rows(strip):
    for row in BLANK_ROWS:
        start = row * LED_COUNT_W
        end = min(start + LED_COUNT_W, strip.numPixels())
        for pixel_index in range(start, end):
            strip.setPixelColor(pixel_index, Color(0, 0, 0))

def render_strip_segments(strip, metadata, gradients, wait_ms=0):
    gradients = gradients or {}
    inactive_palette = gradients.get('inactive') or [(0, 0, 0)]
    active_palettes = gradients.get('active') or {}
    for block_index, entry in enumerate(metadata):
        start_index = entry['start_index']
        end_index = entry['end_index']
        segment_length = max(0, end_index - start_index)
        if segment_length <= 0:
            continue
        if not entry.get('valid', True):
            print(f"[display] Block {block_index + 1} ({entry['metric']}) invalid; using inactive palette.")
            gradient = build_checkpoint_gradient(inactive_palette, segment_length, 0.0)
        else:
            ratio = entry.get('ratio', 0.0)
            palette = inactive_palette
            if entry.get('active'):
                palette = active_palettes.get(entry['metric'], inactive_palette)
            gradient = build_checkpoint_gradient(palette, segment_length, ratio)
        for offset, (red_channel, green_channel, blue_channel) in enumerate(gradient):
            strip.setPixelColor(start_index + offset, Color(red_channel, green_channel, blue_channel))
    _clear_blank_rows(strip)
    strip.show()
    if wait_ms:
        time.sleep(wait_ms / 1000.0)


def render_single_strip(strip, metadata, cleaned_values, gradients):
    gradients = gradients or {}
    inactive_palette = gradients.get('inactive') or [(0, 0, 0)]
    active_palettes = gradients.get('active') or {}
    palette = inactive_palette
    intensity_factor = max((entry.get('ratio', 0.0) for entry in metadata), default=0.0)
    for entry in metadata:
        if entry.get('active'):
            palette = active_palettes.get(entry['metric'], inactive_palette)
            break
    gradient = build_checkpoint_gradient(palette, strip.numPixels(), intensity_factor)
    for index, (red_channel, green_channel, blue_channel) in enumerate(gradient):
        strip.setPixelColor(index, Color(red_channel, green_channel, blue_channel))
    strip.show()

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

def initialize_sensor(max_retries=3, retry_delay=0.5):
    for attempt in range(1, max_retries + 1):
        try:
            return max30102.MAX30102()
        except Exception as error:
            print(f"[max30102] Init failed (attempt {attempt}/{max_retries}): {error}")
            time.sleep(retry_delay)
    return None

def shutdown_sensor_executor():
    global _SENSOR_EXECUTOR
    if _SENSOR_EXECUTOR:
        _SENSOR_EXECUTOR.shutdown(wait=False)
        _SENSOR_EXECUTOR = None

def fetch_sequential_with_timeout(sensor, timeout=SENSOR_READ_TIMEOUT):
    if _SENSOR_EXECUTOR is None:
        return None, None
    future = _SENSOR_EXECUTOR.submit(sensor.read_sequential)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        future.cancel()
        print(f"[max30102] Sequential read timed out after {timeout}s.")
    except OSError as error:
        print(f"[max30102] Sequential read raised OSError: {error}")
    return None, None

def reset_sensor_fifo(sensor):
    reset_fn = getattr(sensor, 'reset_fifo', None)
    if callable(reset_fn):
        reset_fn()


def acquire_sensor_samples(sensor, retries=3, settle_delay=0.15):
    for attempt in range(1, retries + 1):
        reset_sensor_fifo(sensor)
        time.sleep(settle_delay)
        red, ir = fetch_sequential_with_timeout(sensor)
        if red and ir:
            return red, ir
        print(f"[max30102] Empty or timed-out sequential batch (attempt {attempt}/{retries}); retrying.")
        time.sleep(settle_delay)
    return None, None


def _is_zero_batch(red_samples, ir_samples):
    if not red_samples or not ir_samples:
        return False
    return all(sample == 0 for sample in red_samples) and all(sample == 0 for sample in ir_samples)

if __name__ == '__main__':
    args = parse_args()
    m = None
    # LED strip initialization
    strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
    # Intialize the library (must be called once before other functions).
    strip.begin()
    color_config = load_color_config()
    gradients = color_config.get('gradients', {})
    prev_hr_value = 0
    prev_spo2_value = 0
    prev_hr_valid = False
    prev_spo2_valid = False
    prev_alert_active = False
    try:
        while True:
            raw_r, raw_g, raw_b = 0, 0, 0
            color_r, color_g, color_b = 0, 0, 0
            m = initialize_sensor()
            if m is None:
                print("[max30102] Sensor unavailable; delaying next attempt.")
                time.sleep(2)
                continue

            print("Reading temp")
            temp_reading = read_temp()
            temp_valid = temp_reading is not None
            raw_b = temp_reading if temp_valid else TEMP_MIN
            print("SPO2 and HR")
            print("Reading sequential data")
            red, ir = acquire_sensor_samples(m)
            if red is None or ir is None:
                print("[max30102] Unable to fetch sequential data; retrying after full reinit.")
                time.sleep(2)
                continue

            if _is_zero_batch(red, ir):
                print("[max30102] Sequential batch was zeroed; reusing cached HR/SpO2.")
                if not (prev_hr_valid or prev_spo2_valid):
                    print("[max30102] No cached HR/SpO2 available; waiting for next cycle.")
                    time.sleep(2)
                    continue
                hr, hr_valid = prev_hr_value, prev_hr_valid
                spo2, spo2_valid = prev_spo2_value, prev_spo2_valid
            else:
                print("Calculating HR & SPO2")
                hr, hr_valid, spo2, spo2_valid = hrcalc.calc_hr_and_spo2(ir, red)
                if hr_valid:
                    prev_hr_value = hr
                    prev_hr_valid = True
                if spo2_valid:
                    prev_spo2_value = spo2
                    prev_spo2_valid = True

            if hr_valid:
                raw_r = hr
            if spo2_valid:
                raw_g = spo2
            raw_metric_values = {
                'heart_rate': hr if hr_valid else None,
                'spo2': spo2 if spo2_valid else None,
                'temperature': temp_reading if temp_valid else None,
            }
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
            activity_lookup = evaluate_metric_activity(strip_metadata, raw_metric_values)
            for entry in strip_metadata:
                entry['active'] = activity_lookup.get(entry['metric'], False)
            if args.single_strip:
                render_single_strip(strip, strip_metadata, cleaned_metric_values, gradients)
            else:
                render_strip_segments(strip, strip_metadata, gradients)
            m = None
            time.sleep(2)
    except KeyboardInterrupt:
        print("Loop interrupted; exiting.")
    finally:
        shutdown_sensor_executor()
