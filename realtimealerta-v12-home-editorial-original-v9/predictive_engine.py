import time

PRED_HISTORY = {}

def update_history(key, value):
    arr = PRED_HISTORY.setdefault(key, [])
    arr.append({
        "value": float(value),
        "ts": time.time()
    })
    if len(arr) > 10:
        arr.pop(0)
    return arr

def calculate_velocity(arr):
    if len(arr) < 2:
        return 0.0
    return float(arr[-1]["value"]) - float(arr[-2]["value"])

def predict_next(value, velocity):
    return float(value) + (float(velocity) * 1.5)

def classify_trend(velocity):
    if velocity > 2:
        return "ESCALANDO"
    if velocity < -2:
        return "REDUZINDO"
    return "ESTÁVEL"

def predictive_analysis(key, current_value):
    history = update_history(key, current_value)
    velocity = calculate_velocity(history)
    projection = max(0.0, min(100.0, predict_next(current_value, velocity)))
    return {
        "current": round(float(current_value), 1),
        "projected": round(projection, 1),
        "velocity": round(float(velocity), 2),
        "trend": classify_trend(velocity)
    }

def check_early_warning(pred):
    if not pred:
        return None
    if pred.get("projected", 0) >= 80 and pred.get("trend") == "ESCALANDO":
        return "⚠️ POSSÍVEL ESCALADA CRÍTICA NAS PRÓXIMAS HORAS"
    return None
