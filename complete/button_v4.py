import os
import glob
import time
import json
import asyncio
import threading
from rpi_ws281x import Adafruit_NeoPixel, Color
import argparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError

max30102 = None

try:
    from bleak import BleakScanner
except ImportError:
    BleakScanner = None

# KS0023 initalization
os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')
base_dir = '/sys/bus/w1/devices/'
device_folders = glob.glob(base_dir + '28*')
device_file = os.path.join(device_folders[0], 'w1_slave') if device_folders else None

# LED output initialization
LED_COUNT_W    = 8
LED_COUNT_H    = 32
LED_COUNT      = LED_COUNT_W * LED_COUNT_H
LED_PIN        = 18
LED_STRIP_PINS = (18, 13, 21)
LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA        = 10      # DMA channel to use for generating a signal (try 10)
LED_BRIGHTNESS = 30      # Set to 0 for darkest and 255 for brightest
LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL    = 0       # set to '1' for GPIOs 13, 19, 41, 45 or 53
LED_STRIP_CHANNELS = (0, 1, 0)
WARNING_COLOR  = (255, 0, 0)
SENSOR_READ_TIMEOUT = 5.0
_SENSOR_EXECUTOR = ThreadPoolExecutor(max_workers=1)
GRADIENT_COLOR_COUNT = 8
BLANK_ROWS = (10, 21)
SHELLY_BTHOME_SERVICE_UUID = '0000fcd2-0000-1000-8000-00805f9b34fb'
BUTTON_EVENT_NAMES = {
    0x01: 'press',
    0x02: 'double_press',
    0x03: 'triple_press',
    0x04: 'long_press',
    0x80: 'hold',
    0xFE: 'hold',
}
DEFAULT_BUTTON_EVENT_CODES = (0x01, 0x02, 0x03, 0x04)

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

DEFAULT_PHYSICAL_STRIPS = (
    {
        'name': 'left_arm',
        'pin': 18,
        'channel': 0,
        'count': 24,
        'blocks': (
            {'name': 'left_arm_single_8', 'start_index': 0, 'end_index': 1, 'color_index': 7},
            {'name': 'left_arm_single_6', 'start_index': 1, 'end_index': 2, 'color_index': 5},
            {'name': 'left_arm_single_4', 'start_index': 2, 'end_index': 3, 'color_index': 3},
            {'name': 'left_arm_gradient_2', 'start_index': 3, 'end_index': 6, 'color_index': 1},
            {'name': 'left_arm_gradient_3', 'start_index': 6, 'end_index': 9, 'color_index': 2},
            {'name': 'left_arm_gradient_4', 'start_index': 9, 'end_index': 12, 'color_index': 3},
            {'name': 'left_arm_gradient_5', 'start_index': 12, 'end_index': 14, 'color_index': 4},
            {'name': 'left_arm_gradient_6', 'start_index': 14, 'end_index': 16, 'color_index': 5},
            {'name': 'left_arm_gradient_7', 'start_index': 16, 'end_index': 18, 'color_index': 6},
            {'name': 'left_arm_final_8', 'start_index': 18, 'end_index': 24, 'color_index': 7},
        ),
    },
    {
        'name': 'center_piece',
        'pin': 13,
        'channel': 1,
        'count': 54,
        'blocks': (
            {'name': 'center_base_8', 'start_index': 0, 'end_index': 27, 'color_index': 7},
            {'name': 'center_gradient_down_5', 'start_index': 27, 'end_index': 30, 'color_index': 4},
            {'name': 'center_gradient_down_4', 'start_index': 30, 'end_index': 32, 'color_index': 3},
            {'name': 'center_gradient_down_3', 'start_index': 32, 'end_index': 34, 'color_index': 2},
            {'name': 'center_gradient_down_2', 'start_index': 34, 'end_index': 36, 'color_index': 1},
            {'name': 'center_middle_1', 'start_index': 36, 'end_index': 45, 'color_index': 0},
            {'name': 'center_gradient_up_2', 'start_index': 45, 'end_index': 48, 'color_index': 1},
            {'name': 'center_gradient_up_3', 'start_index': 48, 'end_index': 50, 'color_index': 2},
            {'name': 'center_gradient_up_4', 'start_index': 50, 'end_index': 52, 'color_index': 3},
            {'name': 'center_gradient_up_5', 'start_index': 52, 'end_index': 54, 'color_index': 4},
        ),
    },
    {
        'name': 'right_arm',
        'pin': 21,
        'channel': 0,
        'count': 24,
        'blocks': (
            {'name': 'right_arm_single_8', 'start_index': 0, 'end_index': 1, 'color_index': 7},
            {'name': 'right_arm_single_6', 'start_index': 1, 'end_index': 2, 'color_index': 5},
            {'name': 'right_arm_single_4', 'start_index': 2, 'end_index': 3, 'color_index': 3},
            {'name': 'right_arm_gradient_2', 'start_index': 3, 'end_index': 6, 'color_index': 1},
            {'name': 'right_arm_gradient_3', 'start_index': 6, 'end_index': 9, 'color_index': 2},
            {'name': 'right_arm_gradient_4', 'start_index': 9, 'end_index': 12, 'color_index': 3},
            {'name': 'right_arm_gradient_5', 'start_index': 12, 'end_index': 14, 'color_index': 4},
            {'name': 'right_arm_gradient_6', 'start_index': 14, 'end_index': 16, 'color_index': 5},
            {'name': 'right_arm_gradient_7', 'start_index': 16, 'end_index': 18, 'color_index': 6},
            {'name': 'right_arm_final_8', 'start_index': 18, 'end_index': 24, 'color_index': 7},
        ),
    },
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
    'active_gradient': [
        (52, 43, 34),
        (78, 42, 40),
        (79, 66, 42),
        (92, 94, 47),
        (150, 118, 63),
        (218, 143, 122),
        (233, 106, 44),
        (166, 56, 23)
    ],
    'led_strips': DEFAULT_PHYSICAL_STRIPS,
}


def parse_args():
    parser = argparse.ArgumentParser(description='Drive multi-strip wearable gradients from a Shelly BLU Button 1.')
    parser.add_argument(
        '--single-strip',
        action='store_true',
        help='Render the full LED array as a single gradient (legacy behavior).',
    )
    parser.add_argument(
        '--button-address',
        default='',
        help='Optional Shelly BLU Button 1 Bluetooth MAC/address filter.',
    )
    parser.add_argument(
        '--button-name',
        default='',
        help='Optional Bluetooth name prefix to accept when --button-address is not set.',
    )
    parser.add_argument(
        '--button-mode',
        choices=('toggle', 'momentary'),
        default='toggle',
        help='toggle changes state on each button press; momentary activates for --active-seconds.',
    )
    parser.add_argument(
        '--active-seconds',
        type=float,
        default=5.0,
        help='How long a button event stays active in momentary mode.',
    )
    parser.add_argument(
        '--scan-debug',
        action='store_true',
        help='Print parsed BTHome button advertisements while pairing/debugging.',
    )
    parser.add_argument(
        '--scan-all-debug',
        action='store_true',
        help='Print nearby BLE advertisements, even when they are not recognized as the button.',
    )
    parser.add_argument(
        '--include-hold-events',
        action='store_true',
        help='Also let hold advertisements toggle/activate the gradient.',
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
        'active_gradient': [tuple(color) for color in SAFE_DEFAULT_CONFIG['active_gradient']],
        'led_strips': [
            {
                'name': strip_config['name'],
                'pin': strip_config['pin'],
                'channel': strip_config['channel'],
                'count': strip_config['count'],
                'blocks': [dict(block) for block in strip_config['blocks']],
            }
            for strip_config in SAFE_DEFAULT_CONFIG['led_strips']
        ],
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
    active_gradient = _normalize_gradient_length(
        _parse_color_entries(
            payload.get('active_gradient'),
            defaults['active_gradient'],
            'active_gradient',
        ),
        'active_gradient',
    )
    led_strips = _parse_physical_strips(
        payload.get('led_strips'),
        defaults['led_strips'],
        inactive_gradient,
    )

    return {
        'strip_order': _parse_strip_order(payload.get('strip_order'), defaults['strip_order']),
        'base_colors': _parse_color_entries(payload.get('base_colors'), defaults['base_colors'], 'base_colors'),
        'end_colors': _parse_color_entries(payload.get('end_colors'), defaults['end_colors'], 'end_colors'),
        'led_strips': led_strips,
        'gradients': {
            'inactive': inactive_gradient,
            'active': active_gradient,
        },
    }


def _coerce_index(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_int(value, fallback, label):
    try:
        return int(value)
    except (TypeError, ValueError):
        log_color_config_issue(f"{label} invalid; using {fallback}.")
        return fallback


def _parse_color_index(value, palette_length, fallback, label):
    index = _coerce_int(value, fallback, label)
    if palette_length <= 0:
        return 0
    if index < 0 or index >= palette_length:
        log_color_config_issue(f"{label} outside palette; clamping to shared color range.")
        index = max(0, min(palette_length - 1, index))
    return index


def _sanitize_slice_bounds(slice_candidate):
    start_index = _coerce_index(slice_candidate.get('start_index', 0), 0)
    end_index = _coerce_index(slice_candidate.get('end_index', LED_COUNT), LED_COUNT)
    start_index = max(0, min(LED_COUNT - 1, start_index))
    end_index = max(start_index + 1, min(LED_COUNT, end_index))
    return start_index, end_index


def _sanitize_block_bounds(block_candidate, led_count):
    start_index = _coerce_index(block_candidate.get('start_index', 0), 0)
    end_index = _coerce_index(block_candidate.get('end_index', led_count), led_count)
    start_index = max(0, min(led_count - 1, start_index))
    end_index = max(start_index + 1, min(led_count, end_index))
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


def _parse_block_config(raw_block, fallback_block, led_count, palette_length, strip_label, block_index):
    if not isinstance(raw_block, dict):
        log_color_config_issue(f"{strip_label}.blocks[{block_index}] invalid; using default block.")
        raw_block = fallback_block
    start_index, end_index = _sanitize_block_bounds(raw_block, led_count)
    fallback_color_index = fallback_block.get('color_index', block_index % max(1, palette_length))
    color_index = _parse_color_index(
        raw_block.get('color_index', fallback_color_index),
        palette_length,
        fallback_color_index,
        f"{strip_label}.blocks[{block_index}].color_index",
    )
    name = raw_block.get('name', f"block_{block_index + 1}")
    if not isinstance(name, str) or not name:
        name = f"block_{block_index + 1}"
    return {
        'name': name,
        'start_index': start_index,
        'end_index': end_index,
        'color_index': color_index,
    }


def _parse_physical_strips(raw_strips, fallback_strips, shared_palette):
    if not isinstance(raw_strips, list) or not raw_strips:
        log_color_config_issue('led_strips missing or invalid; using defaults.')
        raw_strips = fallback_strips
    palette_length = len(shared_palette or [])
    resolved = []
    for strip_index, raw_strip in enumerate(raw_strips):
        fallback_strip = fallback_strips[min(strip_index, len(fallback_strips) - 1)]
        if not isinstance(raw_strip, dict):
            log_color_config_issue(f"led_strips[{strip_index}] invalid; using default strip.")
            raw_strip = fallback_strip
        label = f"led_strips[{strip_index}]"
        pin = _coerce_int(raw_strip.get('pin', fallback_strip['pin']), fallback_strip['pin'], f"{label}.pin")
        channel = _coerce_int(
            raw_strip.get('channel', fallback_strip.get('channel', LED_CHANNEL)),
            fallback_strip.get('channel', LED_CHANNEL),
            f"{label}.channel",
        )
        count = _coerce_int(raw_strip.get('count', fallback_strip['count']), fallback_strip['count'], f"{label}.count")
        if count <= 0:
            log_color_config_issue(f"{label}.count must be positive; using {fallback_strip['count']}.")
            count = fallback_strip['count']
        name = raw_strip.get('name', f"pin_{pin}")
        if not isinstance(name, str) or not name:
            name = f"pin_{pin}"
        raw_blocks = raw_strip.get('blocks', fallback_strip['blocks'])
        if not isinstance(raw_blocks, list) or not raw_blocks:
            log_color_config_issue(f"{label}.blocks missing or invalid; using default blocks.")
            raw_blocks = fallback_strip['blocks']
        fallback_blocks = list(fallback_strip['blocks'])
        blocks = []
        for block_index, raw_block in enumerate(raw_blocks):
            fallback_block = fallback_blocks[min(block_index, len(fallback_blocks) - 1)]
            blocks.append(_parse_block_config(raw_block, fallback_block, count, palette_length, label, block_index))
        resolved.append({
            'name': name,
            'pin': pin,
            'channel': channel,
            'count': count,
            'blocks': blocks,
        })
    return resolved


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


def build_physical_strip_metadata(color_config):
    physical_metadata = []
    for strip_config in color_config.get('led_strips', []):
        blocks = []
        for block in strip_config.get('blocks', []):
            block_metadata = dict(block)
            block_metadata.update({
                'pin': strip_config['pin'],
                'strip_name': strip_config['name'],
            })
            blocks.append(block_metadata)
        physical_metadata.append({
            'name': strip_config['name'],
            'pin': strip_config['pin'],
            'channel': strip_config['channel'],
            'count': strip_config['count'],
            'blocks': blocks,
        })
    return physical_metadata


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


def evaluate_global_activity(raw_metrics, layout=STRIP_LAYOUT):
    for entry in layout:
        metric = entry['metric']
        raw_value = raw_metrics.get(metric)
        if raw_value is None:
            continue
        min_value = float(entry.get('min_value', 0))
        max_value = float(entry.get('max_value', 0))
        threshold = min_value + (max_value - min_value) / 2.0
        try:
            if float(raw_value) >= threshold:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _clear_blank_rows(strip):
    for row in BLANK_ROWS:
        start = row * LED_COUNT_W
        end = min(start + LED_COUNT_W, strip.numPixels())
        for pixel_index in range(start, end):
            strip.setPixelColor(pixel_index, Color(0, 0, 0))

def render_strip_segments(strip, metadata, gradients, wait_ms=0):
    gradients = gradients or {}
    inactive_palette = gradients.get('inactive') or [(0, 0, 0)]
    active_palette = gradients.get('active') or inactive_palette
    for block_index, entry in enumerate(metadata):
        start_index = entry['start_index']
        end_index = entry['end_index']
        segment_length = max(0, end_index - start_index)
        if segment_length <= 0:
            continue
        if not entry.get('valid', True):
            print(f"[display] Block {block_index + 1} ({entry['metric']}) invalid; using inactive palette.")
            gradient = build_checkpoint_gradient(inactive_palette, segment_length, 0.2)
        else:
            ratio = entry.get('ratio', 0.0)
            palette = inactive_palette
            if entry.get('active'):
                palette = active_palette
            gradient = build_checkpoint_gradient(palette, segment_length, 0.2)
        for offset, (red_channel, green_channel, blue_channel) in enumerate(gradient):
            strip.setPixelColor(start_index + offset, Color(red_channel, green_channel, blue_channel))
    _clear_blank_rows(strip)
    strip.show()
    if wait_ms:
        time.sleep(wait_ms / 1000.0)


def render_physical_strip_blocks(strip_entries, gradients, active=False, wait_ms=0):
    gradients = gradients or {}
    inactive_palette = gradients.get('inactive') or [(0, 0, 0)]
    active_palette = gradients.get('active') or inactive_palette
    selected_palette = active_palette if active else inactive_palette
    for strip_entry in strip_entries:
        strip = strip_entry['strip']
        for pixel_index in range(strip.numPixels()):
            strip.setPixelColor(pixel_index, Color(0, 0, 0))
        for block_index, block in enumerate(strip_entry.get('blocks', [])):
            start_index = block['start_index']
            end_index = block['end_index']
            color_index = block.get('color_index', block_index % len(selected_palette))
            block_color = selected_palette[color_index]
            red_channel, green_channel, blue_channel = block_color
            for pixel_index in range(start_index, end_index):
                strip.setPixelColor(pixel_index, Color(red_channel, green_channel, blue_channel))
        _clear_blank_rows(strip)
        strip.show()
    if wait_ms:
        time.sleep(wait_ms / 1000.0)


def render_single_strip(strip, metadata, cleaned_values, gradients):
    gradients = gradients or {}
    inactive_palette = gradients.get('inactive') or [(0, 0, 0)]
    active_palette = gradients.get('active') or inactive_palette
    palette = inactive_palette
    intensity_factor = max((entry.get('ratio', 0.0) for entry in metadata), default=0.0)
    for entry in metadata:
        if entry.get('active'):
            palette = active_palette
            break
    gradient = build_checkpoint_gradient(palette, strip.numPixels(), intensity_factor)
    for index, (red_channel, green_channel, blue_channel) in enumerate(gradient):
        strip.setPixelColor(index, Color(red_channel, green_channel, blue_channel))
    strip.show()


def render_button_gradient(strip, gradients, active=False):
    gradients = gradients or {}
    inactive_palette = gradients.get('inactive') or [(0, 0, 0)]
    active_palette = gradients.get('active') or inactive_palette
    palette = active_palette if active else inactive_palette
    gradient = build_checkpoint_gradient(palette, strip.numPixels(), 1.0)
    for index, (red_channel, green_channel, blue_channel) in enumerate(gradient):
        strip.setPixelColor(index, Color(red_channel, green_channel, blue_channel))
    strip.show()


class ButtonGradientState:
    def __init__(self, mode='toggle', active_seconds=5.0):
        self.mode = mode
        self.active_seconds = max(0.1, float(active_seconds or 0.1))
        self._active = False
        self._active_until = 0.0
        self._last_packet_key = None
        self._last_event_at = 0.0
        self._lock = threading.Lock()
        self._event_received = threading.Event()

    def handle_event(self, event_code, packet_id=None):
        event_name = BUTTON_EVENT_NAMES.get(event_code, f'event_{event_code}')
        now = time.monotonic()
        packet_key = (packet_id, event_code)
        with self._lock:
            if packet_id is not None and packet_key == self._last_packet_key and now - self._last_event_at < 2.0:
                return None
            if packet_id is None and now - self._last_event_at < 0.7:
                return None
            self._last_packet_key = packet_key
            self._last_event_at = now
            if self.mode == 'momentary':
                self._active = True
                self._active_until = now + self.active_seconds
            else:
                self._active = not self._active
            self._event_received.set()
            return event_name, self._active

    def is_active(self):
        with self._lock:
            if self.mode == 'momentary' and self._active and time.monotonic() >= self._active_until:
                self._active = False
            return self._active

    def wait_for_event(self, timeout=0.5):
        event_received = self._event_received.wait(timeout)
        if event_received:
            self._event_received.clear()
        return event_received


def _device_matches(device, advertisement_data, event_code=None, button_address='', button_name=''):
    if button_address and device.address.lower() == button_address.lower():
        return True
    if event_code is not None and not button_name:
        return True
    names = [
        getattr(device, 'name', '') or '',
        getattr(advertisement_data, 'local_name', '') or '',
    ]
    return bool(button_name) and any(name.startswith(button_name) for name in names if name)


def _normalize_uuid(uuid):
    return str(uuid).lower()


def _iter_advertisement_payloads(advertisement_data, prefer_bthome=False):
    service_data = getattr(advertisement_data, 'service_data', {}) or {}
    for uuid, payload in service_data.items():
        normalized_uuid = _normalize_uuid(uuid)
        is_bthome = normalized_uuid in (SHELLY_BTHOME_SERVICE_UUID, 'fcd2', '0000fcd2')
        if prefer_bthome and not is_bthome:
            continue
        yield bytes(payload), normalized_uuid, is_bthome
    if prefer_bthome:
        return
    for company_id, payload in (getattr(advertisement_data, 'manufacturer_data', {}) or {}).items():
        yield bytes(payload), f'manufacturer:{company_id}', False


def _parse_shelly_button_event(advertisement_data):
    packet_id = None
    parsed_any_payload = False
    for prefer_bthome in (True, False):
        for payload, _source, _is_bthome in _iter_advertisement_payloads(advertisement_data, prefer_bthome):
            parsed_any_payload = True
            result, packet_id = _parse_bthome_payload(payload, packet_id)
            if result is not None:
                return result, packet_id
        if parsed_any_payload:
            break
    return None, packet_id


def _parse_bthome_payload(payload, packet_id=None):
    if not payload:
        return None, packet_id
    start_indexes = (1, 0)
    for start_index in start_indexes:
        if start_index >= len(payload):
            continue
        index = start_index
        while index < len(payload):
            object_id = payload[index]
            if object_id == 0x00 and index + 1 < len(payload):
                packet_id = payload[index + 1]
                index += 2
                continue
            if object_id == 0x3A and index + 1 < len(payload):
                event_code = payload[index + 1]
                if event_code in BUTTON_EVENT_NAMES:
                    return event_code, packet_id
                index += 2
                continue
            index += 1
    return None, packet_id


def _format_debug_advertisement(device, advertisement_data, event_code, packet_id):
    names = [
        getattr(device, 'name', '') or '',
        getattr(advertisement_data, 'local_name', '') or '',
    ]
    service_data = getattr(advertisement_data, 'service_data', {}) or {}
    manufacturer_data = getattr(advertisement_data, 'manufacturer_data', {}) or {}
    service_keys = list(service_data.keys())
    manufacturer_keys = list(manufacturer_data.keys())
    service_hex = {
        str(uuid): bytes(payload).hex()
        for uuid, payload in service_data.items()
    }
    manufacturer_hex = {
        str(company_id): bytes(payload).hex()
        for company_id, payload in manufacturer_data.items()
    }
    return (
        f"[button] adv address={device.address} "
        f"name={next((name for name in names if name), '<none>')} "
        f"rssi={getattr(advertisement_data, 'rssi', '<unknown>')} "
        f"services={service_keys} manufacturers={manufacturer_keys} "
        f"event={event_code} packet={packet_id} "
        f"service_data={service_hex} manufacturer_data={manufacturer_hex}"
    )


async def _scan_shelly_button(state, args, stop_event):
    if BleakScanner is None:
        print("[button] bleak is not installed; run `python -m pip install bleak`.")
        return

    def detection_callback(device, advertisement_data):
        if stop_event.is_set():
            return
        event_code, packet_id = _parse_shelly_button_event(advertisement_data)
        if args.scan_all_debug:
            print(_format_debug_advertisement(device, advertisement_data, event_code, packet_id))
        if not _device_matches(device, advertisement_data, event_code, args.button_address, args.button_name):
            return
        if args.scan_debug and event_code is not None:
            print(_format_debug_advertisement(device, advertisement_data, event_code, packet_id))
        if event_code is None:
            return
        accepted_events = set(DEFAULT_BUTTON_EVENT_CODES)
        if args.include_hold_events:
            accepted_events.update((0x80, 0xFE))
        if event_code not in accepted_events:
            return
        result = state.handle_event(event_code, packet_id)
        if result:
            event_name, active = result
            print(f"[button] {event_name}; gradient active={active}")

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    try:
        while not stop_event.is_set():
            await asyncio.sleep(0.2)
    finally:
        await scanner.stop()


def start_button_listener(state, args):
    stop_event = threading.Event()

    def runner():
        try:
            asyncio.run(_scan_shelly_button(state, args, stop_event))
        except Exception as error:
            print(f"[button] Listener stopped: {error}")

    thread = threading.Thread(target=runner, name='shelly-button-listener', daemon=True)
    thread.start()
    return stop_event, thread

def read_temp_raw():
    if device_file is None:
        return []
    f = open(device_file, 'r')
    lines = f.readlines()
    f.close()
    return lines

def read_temp():
    lines = read_temp_raw()
    if len(lines) < 2:
        return None
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
        if len(lines) < 2:
            return None
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
    if max30102 is None:
        print("[max30102] Sensor module is not loaded in button_v4.py.")
        return None
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


def initialize_led_strip(strip_config):
    strip = Adafruit_NeoPixel(
        strip_config['count'],
        strip_config['pin'],
        LED_FREQ_HZ,
        LED_DMA,
        LED_INVERT,
        LED_BRIGHTNESS,
        strip_config['channel'],
    )
    strip.begin()
    print(
        f"[led] Initialized {strip_config['name']} on GPIO {strip_config['pin']} "
        f"with {strip_config['count']} LEDs on channel {strip_config['channel']}."
    )
    return strip


def attach_strip_objects(physical_metadata):
    strip_entries = []
    for strip_config in physical_metadata:
        entry = dict(strip_config)
        entry['strip'] = initialize_led_strip(strip_config)
        strip_entries.append(entry)
    return strip_entries

if __name__ == '__main__':
    args = parse_args()
    color_config = load_color_config()
    gradients = color_config.get('gradients', {})
    physical_metadata = build_physical_strip_metadata(color_config)
    if args.single_strip:
        strip = initialize_led_strip({
            'name': 'single_strip',
            'pin': LED_PIN,
            'channel': LED_CHANNEL,
            'count': LED_COUNT,
        })
        strip_entries = []
    else:
        strip = None
        strip_entries = attach_strip_objects(physical_metadata)
    button_state = ButtonGradientState(args.button_mode, args.active_seconds)
    stop_button_listener, button_thread = start_button_listener(button_state, args)
    try:
        while True:
            if not button_state.wait_for_event():
                continue
            active = button_state.is_active()
            print(f"[display] Button gradient active={active}")
            if args.single_strip:
                render_button_gradient(strip, gradients, active)
            else:
                render_physical_strip_blocks(strip_entries, gradients, active)
    except KeyboardInterrupt:
        print("Loop interrupted; exiting.")
    finally:
        stop_button_listener.set()
        button_thread.join(timeout=1.0)
        shutdown_sensor_executor()
