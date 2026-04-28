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
SHELLY_BTHOME_SERVICE_UUID = '0000fcd2-0000-1000-8000-00805f9b34fb'
BUTTON_EVENT_NAMES = {
    0x01: 'press',
    0x02: 'double_press',
    0x03: 'triple_press',
    0x04: 'long_press',
    0x80: 'hold',
    0xFE: 'hold',
}

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
    parser = argparse.ArgumentParser(description='Drive one-strip gradients from a Shelly BLU Button 1.')
    parser.add_argument(
        '--single-strip',
        action='store_true',
        help='Accepted for compatibility; complete_button always renders one physical strip.',
    )
    parser.add_argument(
        '--button-address',
        default='',
        help='Optional Shelly BLU Button 1 Bluetooth MAC/address filter.',
    )
    parser.add_argument(
        '--button-name',
        default='ShellyBLU',
        help='Bluetooth name prefix to accept when --button-address is not set.',
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
        '--active-palette',
        default='heart_rate',
        help='active_gradients key to use while active, e.g. heart_rate, spo2, or temperature.',
    )
    parser.add_argument(
        '--scan-debug',
        action='store_true',
        help='Print matching BLE advertisements while pairing/debugging.',
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
            gradient = build_checkpoint_gradient(inactive_palette, segment_length, 0.2)
        else:
            ratio = entry.get('ratio', 0.0)
            palette = inactive_palette
            if entry.get('active'):
                palette = active_palettes.get(entry['metric'], inactive_palette)
            gradient = build_checkpoint_gradient(palette, segment_length, 0.2)
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


def render_button_gradient(strip, gradients, active=False, active_palette_key='heart_rate'):
    gradients = gradients or {}
    inactive_palette = gradients.get('inactive') or [(0, 0, 0)]
    active_palettes = gradients.get('active') or {}
    palette = inactive_palette
    if active:
        palette = active_palettes.get(active_palette_key, inactive_palette)
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
            return event_name, self._active

    def is_active(self):
        with self._lock:
            if self.mode == 'momentary' and self._active and time.monotonic() >= self._active_until:
                self._active = False
            return self._active


def _device_matches(device, advertisement_data, button_address='', button_name='ShellyBLU'):
    if button_address and device.address.lower() == button_address.lower():
        return True
    names = [
        getattr(device, 'name', '') or '',
        getattr(advertisement_data, 'local_name', '') or '',
    ]
    return any(name.startswith(button_name) for name in names if name)


def _iter_advertisement_payloads(advertisement_data):
    for payload in getattr(advertisement_data, 'service_data', {}).values():
        yield bytes(payload)
    for payload in getattr(advertisement_data, 'manufacturer_data', {}).values():
        yield bytes(payload)


def _parse_shelly_button_event(advertisement_data):
    packet_id = None
    for payload in _iter_advertisement_payloads(advertisement_data):
        index = 0
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


async def _scan_shelly_button(state, args, stop_event):
    if BleakScanner is None:
        print("[button] bleak is not installed; run `python -m pip install bleak`.")
        return

    def detection_callback(device, advertisement_data):
        if stop_event.is_set():
            return
        if not _device_matches(device, advertisement_data, args.button_address, args.button_name):
            return
        event_code, packet_id = _parse_shelly_button_event(advertisement_data)
        if args.scan_debug:
            print(f"[button] Advertisement from {device.address}; event={event_code}; packet={packet_id}")
        if event_code is None:
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
        print("[max30102] Sensor module is not loaded in complete_button.py.")
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

if __name__ == '__main__':
    args = parse_args()
    strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
    strip.begin()
    color_config = load_color_config()
    gradients = color_config.get('gradients', {})
    button_state = ButtonGradientState(args.button_mode, args.active_seconds)
    stop_button_listener, button_thread = start_button_listener(button_state, args)
    last_active = None
    try:
        while True:
            active = button_state.is_active()
            if active != last_active:
                print(f"[display] Button gradient active={active}")
                last_active = active
            render_button_gradient(strip, gradients, active, args.active_palette)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Loop interrupted; exiting.")
    finally:
        stop_button_listener.set()
        shutdown_sensor_executor()
