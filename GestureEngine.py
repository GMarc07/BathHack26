"""
gesture_engine.py
-----------------
Shared module for recording and matching custom hand gestures.

Gestures are stored as normalized landmark offsets relative to the wrist
(landmark 0), divided by the hand scale so they are distance-invariant.

Record flow (IPC via flag files):
  Config.py writes  → record_flag.json  {"name": "...", "action": "...", "key": "..."}
  skeletonTracking  → captures next frame, saves to gestures.json, deletes flag
  Config.py polls   → detects flag gone, refreshes gesture list
"""

import json
import math
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BASE       = Path(__file__).parent
GESTURES_FILE = _BASE / "gestures.json"
RECORD_FLAG   = _BASE / "record_flag.json"
RESULT_FLAG   = _BASE / "record_result.json"   # written by tracker on success/fail

# ---------------------------------------------------------------------------
# Supported actions
# ---------------------------------------------------------------------------
ACTIONS = [
    "next_slide",
    "prev_slide",
    "left_click",
    "right_click",
    "scroll_up",
    "scroll_down",
    "custom_key",
]

# ---------------------------------------------------------------------------
# Scale helper (matches skeletonTracking.getScale)
# ---------------------------------------------------------------------------
def _get_scale(hand) -> float:
    """Sum of 4 segment lengths: wrist→MCP1 → PIP1 → DIP1 → TIP1 (index chain)."""
    def dist(a, b):
        return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)
    return (
        dist(hand[0], hand[5])
        + dist(hand[5], hand[6])
        + dist(hand[6], hand[7])
        + dist(hand[7], hand[8])
    )

# ---------------------------------------------------------------------------
# Normalise landmarks → list of {dx, dy} relative to wrist, scaled
# ---------------------------------------------------------------------------
def normalise(hand) -> list[dict]:
    """
    Returns 21 entries (landmarks 0-20).
    Landmark 0 (wrist) is always {dx:0, dy:0}.
    All others are offset from wrist, divided by hand scale.
    """
    scale = _get_scale(hand)
    if scale == 0:
        scale = 1.0
    wrist = hand[0]
    return [
        {"dx": (lm.x - wrist.x) / scale,
         "dy": (lm.y - wrist.y) / scale}
        for lm in hand
    ]

# ---------------------------------------------------------------------------
# Gesture file I/O
# ---------------------------------------------------------------------------
def load_gestures() -> list[dict]:
    if GESTURES_FILE.exists():
        try:
            data = json.loads(GESTURES_FILE.read_text())
            return data.get("gestures", [])
        except Exception:
            pass
    return []


def save_gestures(gestures: list[dict]):
    GESTURES_FILE.write_text(json.dumps({"gestures": gestures}, indent=2))


def add_gesture(name: str, action: str, key: str, landmarks: list[dict],
                threshold: float = 0.20):
    gestures = load_gestures()
    # Replace if same name exists
    gestures = [g for g in gestures if g["name"] != name]
    gestures.append({
        "name":      name,
        "action":    action,
        "key":       key,          # used only for custom_key action
        "landmarks": landmarks,
        "threshold": threshold,
        "cooldown":  1.0,          # minimum seconds between triggers
    })
    save_gestures(gestures)


def delete_gesture(name: str):
    gestures = [g for g in load_gestures() if g["name"] != name]
    save_gestures(gestures)

# ---------------------------------------------------------------------------
# Record-flag helpers
# ---------------------------------------------------------------------------
def request_record(name: str, action: str, key: str = ""):
    """Config calls this to ask the tracker to capture the next frame."""
    RECORD_FLAG.write_text(json.dumps({"name": name, "action": action, "key": key}))
    # Clear any old result
    if RESULT_FLAG.exists():
        RESULT_FLAG.unlink()


def poll_record_request() -> dict | None:
    """Tracker calls this every frame. Returns the pending request dict or None."""
    if RECORD_FLAG.exists():
        try:
            return json.loads(RECORD_FLAG.read_text())
        except Exception:
            pass
    return None


def complete_record(req: dict, hand):
    """Tracker calls this when hand is visible and record flag is pending."""
    landmarks = normalise(hand)
    add_gesture(req["name"], req["action"], req.get("key", ""), landmarks)
    RECORD_FLAG.unlink(missing_ok=True)
    RESULT_FLAG.write_text(json.dumps({"status": "ok", "name": req["name"]}))


def fail_record(reason: str = "no hand"):
    RECORD_FLAG.unlink(missing_ok=True)
    RESULT_FLAG.write_text(json.dumps({"status": "fail", "reason": reason}))


def poll_result() -> dict | None:
    """Config polls this to know when recording finished."""
    if RESULT_FLAG.exists():
        try:
            return json.loads(RESULT_FLAG.read_text())
        except Exception:
            pass
    return None


def clear_result():
    RESULT_FLAG.unlink(missing_ok=True)

# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def _rms_error(live: list[dict], stored: list[dict]) -> float:
    """Root-mean-square error across all 21 normalised landmarks."""
    total = 0.0
    for l, s in zip(live, stored):
        total += (l["dx"] - s["dx"]) ** 2 + (l["dy"] - s["dy"]) ** 2
    return math.sqrt(total / len(live))


# Per-gesture last-trigger timestamps (name → float)
_last_triggered: dict[str, float] = {}


def check_gestures(hand) -> list[dict]:
    """
    Compare live hand against all stored gestures.
    Returns list of gestures that matched (usually 0 or 1).
    Respects per-gesture cooldown so actions don't fire continuously.
    """
    live = normalise(hand)
    now  = time.monotonic()
    matched = []

    for g in load_gestures():
        stored    = g["landmarks"]
        threshold = g.get("threshold", 0.20)
        cooldown  = g.get("cooldown",  1.0)
        name      = g["name"]

        err = _rms_error(live, stored)
        if err < threshold:
            last = _last_triggered.get(name, 0.0)
            if now - last >= cooldown:
                _last_triggered[name] = now
                matched.append(g)

    return matched