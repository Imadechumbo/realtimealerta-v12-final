import json
import os
import threading
from collections import defaultdict

STATE_PATH = os.environ.get("STABILITY_STATE_PATH", "/tmp/realtime_stability_state.json")
DEFAULT_ALPHA = float(os.environ.get("STABILITY_ALPHA", "0.28"))
DEFAULT_WINDOW = int(os.environ.get("STABILITY_WINDOW", "5"))
DEFAULT_MAX_DELTA = float(os.environ.get("STABILITY_MAX_DELTA", "12"))
TREND_THRESHOLD = float(os.environ.get("STABILITY_TREND_THRESHOLD", "1.5"))

LOCK = threading.Lock()
LAST_VALUES = {}
HISTORY = defaultdict(list)


def _load_state():
    global LAST_VALUES, HISTORY
    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        LAST_VALUES = {k: float(v) for k, v in (payload.get('last_values') or {}).items()}
        HISTORY = defaultdict(list, {
            k: [float(x) for x in (v or [])][-DEFAULT_WINDOW:]
            for k, v in (payload.get('history') or {}).items()
        })
    except Exception:
        LAST_VALUES = {}
        HISTORY = defaultdict(list)


def _save_state():
    try:
        with open(STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump({'last_values': LAST_VALUES, 'history': dict(HISTORY)}, f, ensure_ascii=False)
    except Exception:
        pass


def clamp_variation(key, new, max_delta=DEFAULT_MAX_DELTA):
    prev = LAST_VALUES.get(key)
    if prev is None:
        return float(new)
    delta = float(new) - float(prev)
    if abs(delta) > max_delta:
        return float(prev) + (max_delta if delta > 0 else -max_delta)
    return float(new)


def ema_smoothing(key, new, alpha=DEFAULT_ALPHA):
    prev = LAST_VALUES.get(key)
    if prev is None:
        LAST_VALUES[key] = float(new)
        return float(new)
    smoothed = (alpha * float(new)) + ((1 - alpha) * float(prev))
    LAST_VALUES[key] = smoothed
    return smoothed


def rolling_average(key, new, window=DEFAULT_WINDOW):
    arr = HISTORY[key]
    arr.append(float(new))
    if len(arr) > window:
        del arr[:-window]
    return sum(arr) / len(arr)


def calculate_trend(key, threshold=TREND_THRESHOLD):
    arr = HISTORY.get(key, [])
    if len(arr) < 2:
        return '→'
    delta = arr[-1] - arr[-2]
    if delta > threshold:
        return '↑'
    if delta < -threshold:
        return '↓'
    return '→'


def stabilize(key, raw_value, alpha=DEFAULT_ALPHA, window=DEFAULT_WINDOW, max_delta=DEFAULT_MAX_DELTA):
    with LOCK:
        value = clamp_variation(key, raw_value, max_delta=max_delta)
        value = ema_smoothing(key, value, alpha=alpha)
        value = rolling_average(key, value, window=window)
        trend = calculate_trend(key)
        _save_state()
        return int(round(value)), trend


_load_state()
